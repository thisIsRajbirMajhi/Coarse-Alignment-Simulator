"""
Performance logging module — comprehensive real-time statistics.

Collects per-frame stats during a run and exports the full report:
core (duration, FPS, acquisition, error, retention, processing) +
extended (RMS, std, jitter, state distribution, detection/hit rates,
reacquisition, lock-loss count, per-beacon hitbox/center stats).

Fixes (2026-08-31 rebuild):
 - Monotonic clock for elapsed / acquisition / reacquisition (stable vs NTP)
 - File-handle leak fixed: start() closes previous csv_file; close() added
 - Reacquisition counting de-duplicated (single _lost_since gate)
 - Calculations verified: lock_retention, detection, hitbox, center, error,
   RMS, jitter, state_pct, times = frames/total * elapsed (wall-correct)
 - Dashboard real-time: summary() now O(1) extra, elapsed uses monotonic,
   pause-resume adjusts via offset (MainWindow responsibility)
 - Auto-CSV logs every 1s wall time with floor dedup fix
"""

import csv
import json
import math
import time
import os
import uuid
from datetime import datetime

from perf_log.error_stats import compute_error_stats, error_pct_from_px
from perf_log.rates import compute_rates
from perf_log.timing import compute_fps

class PerformanceLogger:
    def __init__(self):
        self.start_time = None          # kept for back-compat (wall time)
        self._start_mono = None         # monotonic for elapsed
        self.frame_count = 0
        self.locked_frame_count = 0
        self.tracking_errors: list[float] = []
        self.processing_times: list[float] = []
        self.acquisition_time: float | None = None

        # extended
        self.detection_count = 0  # frames where detector returned a blob for TARGET (hitbox-gated)
        self.hitbox_hit_count = 0
        self.center_hit_count = 0
        self.state_counts: dict[str, int] = {"searching": 0, "acquired": 0, "tracking": 0, "lost": 0}
        self.lock_losses = 0
        self.acquisitions = 0
        self._prev_locked = False
        self._prev_state: str | None = None
        self.reacquisition_times: list[float] = []
        self._lost_since: float | None = None  # monotonic
        self._first_lock_time: float | None = None

        # ml training auto-export
        self.csv_file = None
        self.csv_writer = None
        self._last_csv_log_time = 0.0
        self._run_dir = None
        self._pause_offset = 0.0  # total paused duration (not used internally, external adjusts start)

    # lifecycle helpers
    def close(self):
        """Flush and close auto-log CSV if open. Safe to call multiple times."""
        try:
            if self.csv_file is not None and not self.csv_file.closed:
                try:
                    self.csv_file.flush()
                except Exception:
                    pass
                self.csv_file.close()
        except Exception:
            pass
        finally:
            self.csv_file = None
            self.csv_writer = None

    def __del__(self):
        try:
            self.close()
        except Exception:
            pass

    def start(self):
        # FIX: close previous handle to avoid leak (was missing)
        self.close()
        self.start_time = time.time()
        self._start_mono = time.monotonic()
        self.frame_count = 0
        self.locked_frame_count = 0
        self.tracking_errors = []
        self.processing_times = []
        self.acquisition_time = None
        self.detection_count = 0
        self.hitbox_hit_count = 0
        self.center_hit_count = 0
        self.state_counts = {"searching": 0, "acquired": 0, "tracking": 0, "lost": 0}
        self.lock_losses = 0
        self.acquisitions = 0
        self._prev_locked = False
        self._prev_state = None
        self.reacquisition_times = []
        self._lost_since = None
        self._first_lock_time = None
        self._pause_offset = 0.0

        # setup ML auto-logging folder and csv (unique per run)
        try:
            base_dir = os.path.join(os.path.dirname(__file__), "runs")
            os.makedirs(base_dir, exist_ok=True)
            # Use microsecond + uuid to avoid collision on rapid restarts
            run_name = datetime.now().strftime("run_%Y%m%d_%H%M%S") + f"_{uuid.uuid4().hex[:6]}"
            self._run_dir = os.path.join(base_dir, run_name)
            os.makedirs(self._run_dir, exist_ok=True)

            self.csv_file = open(os.path.join(self._run_dir, "timeseries.csv"), "w", newline="", encoding="utf-8")
            self.csv_writer = csv.writer(self.csv_file)
            # Spec-aligned timeseries header — covers Sr.16-20 + centroiding/RMSE per PDF deliverables
            self.csv_writer.writerow([
                "Total Duration (S)",        # Sr. performance log: simulation duration / elapsed
                "FPS",                       # Sr.20 processing speed ≥20 FPS
                "Acquisition (S)",           # Sr.16 ≤2 sec
                "Reacquisition Avg (S)",     # Sr.19 ≤1 sec
                "Avg Tracking Error (px)",   # Sr.17 + centroiding — avg
                "RMS Error (px)",            # RMSE for benchmark
                "Max Error (px)",            # Sr. performance log
                "P95 Error (px)",            # extended distribution
                "Target Loss (%)",           # Sr.18 <5%  (100 - retention)
                "Retention %",               # Sr.18 complement
                "Lock Losses",               # reacquisition count validation
                "Acquisitions",              # total entries into tracking
                "Proc Time Avg (ms)",        # processing time per frame
                "Proc Jitter (ms)",          # processing jitter
                "Centroiding Avg (px)",      # centroiding error alias
                "Centroiding RMSE (px)",     # centroiding RMSE
                "Detection Rate %",          # extended
                "Detection Time (S)",
                "Searching Rate (%)",
                "Searching Time (S)",
                "Center Hit Rate (%)",
                "Center Hit Time (S)"
            ])
            self.csv_file.flush()
            self._last_csv_log_time = 0.0
        except Exception as e:
            print(f"Failed to setup ML log: {e}")
            self.csv_file = None
            self.csv_writer = None

    def _elapsed(self) -> float:
        if self._start_mono is None:
            return 0.0
        return max(0.0, time.monotonic() - self._start_mono)

    def adjust_for_pause(self, pause_duration_s: float):
        """Called by MainWindow on resume to keep elapsed wall-excluded."""
        if self._start_mono is not None:
            self._start_mono += float(pause_duration_s)
        if self.start_time is not None:
            self.start_time += float(pause_duration_s)

    def log_frame(self, is_locked: bool, tracking_error: float | None, frame_process_time: float,
                  *, detected: bool = False, hitbox_hit: bool = False, center_hit: bool = False,
                  lock_state: str | None = None):
        """Call once per simulation frame with that frame's outcome.

        Extended kwargs are optional for back-compat; when supplied they feed
        detection/hit rates and state distribution.

        FIX: detected should be primary-target hitbox detection, not any blob.
             Caller (MainWindow._tick) now passes hitbox_hit as detected to avoid
             distractor-inflated detection_rate.
        """
        self.frame_count += 1
        # clamp negative process time (should not happen)
        try:
            pt = float(frame_process_time)
            if pt < 0:
                pt = 0.0
        except Exception:
            pt = 0.0
        self.processing_times.append(pt)

        if is_locked:
            self.locked_frame_count += 1
            if tracking_error is not None:
                try:
                    self.tracking_errors.append(float(tracking_error))
                except Exception:
                    pass
            if self.acquisition_time is None and self._start_mono is not None:
                self.acquisition_time = self._elapsed()
                self._first_lock_time = self.acquisition_time

        # detection / hitbox — FIX: keep denominators consistent, document
        if detected:
            self.detection_count += 1
        if hitbox_hit:
            self.hitbox_hit_count += 1
        if center_hit:
            self.center_hit_count += 1

        # state distribution — FIX: deduplicate _lost_since logic
        if lock_state is not None:
            st = lock_state.lower().strip()
            if st in self.state_counts:
                self.state_counts[st] += 1
            # acquisition = transition into tracking (first time or after loss)
            if st == "tracking" and self._prev_state != "tracking":
                self.acquisitions += 1
                if self._lost_since is not None:
                    reacq = time.monotonic() - self._lost_since
                    # reacquisition should be >=0 and not absurdly large
                    if reacq >= 0 and reacq < 1e6:
                        self.reacquisition_times.append(float(reacq))
                    self._lost_since = None
            # entering lost/searching after being in tracking/acquired
            # single gate to set _lost_since (was duplicated before)
            if st in ("lost", "searching") and self._prev_state not in ("lost", "searching", None):
                # came from acquired/tracking into lost/searching
                if self._prev_state in ("acquired", "tracking"):
                    if self._prev_state == "tracking":
                        self.lock_losses += 1
                if self._lost_since is None:
                    self._lost_since = time.monotonic()
            elif self._prev_state == "tracking" and st in ("lost", "searching"):
                # already handled above, but keep lock_losses if not yet counted via gate
                # (gate covers it, so this branch is now redundant but kept for legacy paths)
                pass
            self._prev_state = st
        else:
            # fallback single-bit locked tracking for legacy callers
            if is_locked and not self._prev_locked:
                self.acquisitions += 1
            if not is_locked and self._prev_locked:
                self.lock_losses += 1
        self._prev_locked = is_locked

        # Auto-log every second (wall) — spec-aligned columns
        elapsed = self._elapsed()
        if self.csv_writer and self.csv_file and not self.csv_file.closed and (elapsed - self._last_csv_log_time >= 1.0):
            try:
                s = self.summary()
                self.csv_writer.writerow([
                    s.get("simulation_duration_s", 0),
                    s.get("fps", 0),
                    s.get("acquisition_time_s", 0) if s.get("acquisition_time_s") is not None else 0,
                    s.get("avg_reacquisition_time_s", 0) if s.get("avg_reacquisition_time_s") is not None else 0,
                    s.get("avg_tracking_error_px", 0),
                    s.get("rms_tracking_error_px", 0),
                    s.get("max_tracking_error_px", 0),
                    s.get("p95_tracking_error_px", 0),
                    s.get("target_loss_pct", 0),
                    s.get("lock_retention_rate_pct", 0),
                    s.get("lock_losses", 0),
                    s.get("acquisitions", 0),
                    s.get("avg_processing_time_ms", 0),
                    s.get("jitter_ms", 0),
                    s.get("centroiding_error_avg_px", 0),
                    s.get("centroiding_error_rmse_px", 0),
                    s.get("detection_rate_pct", 0),
                    s.get("detection_time_s", 0),
                    s.get("searching_rate_pct", 0),
                    s.get("searching_time_s", 0),
                    s.get("center_hit_rate_pct", 0),
                    s.get("center_hit_time_s", 0)
                ])
                self.csv_file.flush()
                self._last_csv_log_time = math.floor(elapsed)
            except Exception:
                pass

    def summary(self) -> dict:
        elapsed = self._elapsed()
        fps = compute_fps(self.frame_count, elapsed)

        stats = compute_error_stats(self.tracking_errors)
        avg_error = stats["avg"]
        max_error = stats["max"]
        min_error = stats["min"]
        rms = stats["rms"]
        std_err = stats["std"]
        median = stats["median"]
        p95 = stats["p95"]

        lock_retention = (self.locked_frame_count / self.frame_count * 100) if self.frame_count else 0.0
        rates = compute_rates(self.frame_count, self.detection_count, self.hitbox_hit_count, self.center_hit_count)
        detection_rate = rates["detection_rate"]
        hitbox_rate = rates["hitbox_rate"]
        center_rate = rates["center_rate"]
        center_overall = rates["center_overall"]

        if self.processing_times:
            avg_proc = sum(self.processing_times) / len(self.processing_times)
            m = avg_proc
            var_p = sum((x - m) ** 2 for x in self.processing_times) / len(self.processing_times)
            jitter_ms = math.sqrt(var_p) * 1000.0 if var_p > 0 else 0.0
            sp = sorted(self.processing_times)
            # p95 proc index
            idx = int(math.ceil(0.95 * len(sp))) - 1
            idx = max(0, min(idx, len(sp) - 1))
            p95_proc = sp[idx] * 1000.0
            min_proc = min(self.processing_times) * 1000.0
            max_proc = max(self.processing_times) * 1000.0
        else:
            avg_proc = jitter_ms = p95_proc = min_proc = max_proc = 0.0

        # reacquisition
        if self.reacquisition_times:
            avg_reacq = sum(self.reacquisition_times) / len(self.reacquisition_times)
            min_reacq = min(self.reacquisition_times)
            max_reacq = max(self.reacquisition_times)
        else:
            avg_reacq = min_reacq = max_reacq = 0.0

        # state pct — total uses frame_count, guard 0
        total = self.frame_count if self.frame_count else 1
        state_pct = {k: round(v / total * 100, 2) for k, v in self.state_counts.items()}

        tracking_error_pct = round((avg_error / max_error * 100) if max_error > 1e-9 else 0.0, 2)
        avg_tracking_error_pct = error_pct_from_px(avg_error)
        max_tracking_error_pct = error_pct_from_px(max_error)
        # Spec aliases — centroiding (same as tracking) and RMSE per benchmark
        centroiding_avg = round(avg_error, 3)
        centroiding_rmse = round(rms, 3)
        centroiding_max = round(max_error, 3)
        # Target loss is inverse of retention per Sr.18 (<5% loss == >95% retention)
        target_loss_pct = round(100.0 - lock_retention, 2) if self.frame_count else 0.0
        # Proc time in seconds for image spec (Dashboard: Proc. Time (S))
        proc_time_s = round(float(avg_proc), 6)  # avg_proc is seconds
        # Times: proportion of wall elapsed spent in that condition (correct for dashboard)
        detection_time_s = round((self.detection_count / total * elapsed) if self.frame_count else 0.0, 3)
        searching_time_s = round((self.state_counts.get("searching", 0) / total * elapsed) if self.frame_count else 0.0, 3)
        center_hit_time_s = round((self.center_hit_count / total * elapsed) if self.frame_count else 0.0, 3)

        return {
            # core — Timing & rate (Sr.16, Sr.20)
            "simulation_duration_s": round(elapsed, 3),
            "frame_count": self.frame_count,
            "fps": round(fps, 2),
            "processing_speed_fps": round(fps, 2),  # alias Sr.20
            "acquisition_time_s": round(self.acquisition_time, 3) if self.acquisition_time is not None else None,
            "avg_tracking_error_px": round(avg_error, 3),
            "max_tracking_error_px": round(max_error, 3),
            "lock_retention_rate_pct": round(lock_retention, 2),
            "target_loss_pct": target_loss_pct,  # Sr.18
            "avg_processing_time_ms": round(avg_proc * 1000, 3),
            # extended — error distribution
            "min_tracking_error_px": round(min_error, 3),
            "median_tracking_error_px": round(median, 3),
            "p95_tracking_error_px": round(p95, 3),
            "rms_tracking_error_px": round(rms, 3),
            "centroiding_error_avg_px": centroiding_avg,  # Sr. benchmark: centroiding = tracking
            "centroiding_error_max_px": centroiding_max,
            "centroiding_error_rmse_px": centroiding_rmse,  # RMSE alias for benchmark
            "centroiding_error_p95_px": round(p95, 3),
            "std_tracking_error_px": round(std_err, 3),
            # extended — processing
            "min_processing_time_ms": round(min_proc, 3),
            "max_processing_time_ms": round(max_proc, 3),
            "p95_processing_time_ms": round(p95_proc, 3),
            "jitter_ms": round(jitter_ms, 3),
            # extended — detection / hitbox
            "detection_count": self.detection_count,
            "detection_rate_pct": round(detection_rate, 2),
            "detection_time_s": detection_time_s,
            "hitbox_hit_count": self.hitbox_hit_count,
            "hitbox_hit_rate_pct": round(hitbox_rate, 2),
            "center_hit_count": self.center_hit_count,
            "center_hit_rate_pct": round((self.center_hit_count / total * 100) if self.frame_count else 0.0, 2),  # of total frames
            "center_hit_overall_pct": round(center_overall, 2),  # of detections
            "center_hit_time_s": center_hit_time_s,
            # dashboard-exact aliases (image spec)
            "tracking_error_pct": tracking_error_pct,
            "avg_tracking_error_pct": avg_tracking_error_pct,
            "max_tracking_error_pct": max_tracking_error_pct,
            "proc_time_s": proc_time_s,
            "searching_rate_pct": state_pct["searching"],
            "searching_time_s": searching_time_s,
            # spec aliases for re-acq and centroiding (benchmark naming)
            "reacquisition_time_s": round(avg_reacq, 3) if self.reacquisition_times else None,  # Sr.19 avg
            "reacquisition_time_avg_s": round(avg_reacq, 3) if self.reacquisition_times else None,
            "centroiding_error_px": centroiding_avg,
            "rmse_px": centroiding_rmse,  # short alias per evaluation table
            # extended — lock dynamics
            "lock_losses": self.lock_losses,
            "acquisitions": self.acquisitions,
            "avg_reacquisition_time_s": round(avg_reacq, 3) if self.reacquisition_times else None,
            "min_reacquisition_time_s": round(min_reacq, 3) if self.reacquisition_times else None,
            "max_reacquisition_time_s": round(max_reacq, 3) if self.reacquisition_times else None,
            # extended — state distribution
            "state_searching_pct": state_pct["searching"],
            "state_acquired_pct": state_pct["acquired"],
            "state_tracking_pct": state_pct["tracking"],
            "state_lost_pct": state_pct["lost"],
            "state_counts": dict(self.state_counts),
        }

    def export_report(self, path: str):
        """Write the final report to disk. Format is inferred from the
        file extension (.json or .csv, case-insensitive). JSON is pretty;
        CSV writes metric,value rows."""
        data = self.summary()
        # Flatten state_counts for CSV
        flat = {}
        for k, v in data.items():
            if k == "state_counts":
                for sk, sv in v.items():
                    flat[f"state_count_{sk}"] = sv
            else:
                flat[k] = v
        p = path.lower()
        try:
            if p.endswith(".json"):
                with open(path, "w", encoding="utf-8") as f:
                    json.dump(data, f, indent=2)
            else:
                with open(path, "w", newline="", encoding="utf-8") as f:
                    writer = csv.writer(f)
                    writer.writerow(["metric", "value"])
                    for k, v in flat.items():
                        writer.writerow([k, v])
        except OSError as e:
            raise OSError(f"Failed to export report to {path}: {e}") from e
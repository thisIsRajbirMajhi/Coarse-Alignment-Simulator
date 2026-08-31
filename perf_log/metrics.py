"""
Performance logging module — comprehensive real-time statistics.

Collects per-frame stats during a run and exports the full report:
core (duration, FPS, acquisition, error, retention, processing) +
extended (RMS, std, jitter, state distribution, detection/hit rates,
reacquisition, lock-loss count, per-beacon hitbox/center stats).
"""

import csv
import json
import math
import time
import os
from datetime import datetime


class PerformanceLogger:
    def __init__(self):
        self.start_time = None
        self.frame_count = 0
        self.locked_frame_count = 0
        self.tracking_errors: list[float] = []
        self.processing_times: list[float] = []
        self.acquisition_time: float | None = None

        # extended
        self.detection_count = 0  # frames where detector returned a blob for target
        self.hitbox_hit_count = 0
        self.center_hit_count = 0
        self.state_counts: dict[str, int] = {"searching": 0, "acquired": 0, "tracking": 0, "lost": 0}
        self.lock_losses = 0
        self.acquisitions = 0
        self._prev_locked = False
        self._prev_state: str | None = None
        self.reacquisition_times: list[float] = []
        self._lost_since: float | None = None
        # for jitter / p95
        self._first_lock_time: float | None = None
        
        # ml training auto-export
        self.csv_file = None
        self.csv_writer = None
        self._last_csv_log_time = 0.0
        self._run_dir = None

    def start(self):
        self.start_time = time.time()
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

        # setup ML auto-logging folder and csv
        try:
            base_dir = os.path.join(os.path.dirname(__file__), "runs")
            os.makedirs(base_dir, exist_ok=True)
            run_name = datetime.now().strftime("run_%Y%m%d_%H%M%S")
            self._run_dir = os.path.join(base_dir, run_name)
            os.makedirs(self._run_dir, exist_ok=True)
            
            self.csv_file = open(os.path.join(self._run_dir, "timeseries.csv"), "w", newline="")
            self.csv_writer = csv.writer(self.csv_file)
            # Write header
            self.csv_writer.writerow([
                "Total Duration (S)",
                "Acquisition (S)",
                "Proc Time (ms)",
                "Average Tracking Error",
                "Max Error",
                "Error %",
                "Retention %",
                "Detection Rate %",
                "Detection Time",
                "Searching Rate (%)",
                "Searching Time",
                "Center Hit Rate",
                "Center Hit Time"
            ])
            self._last_csv_log_time = 0.0
        except Exception as e:
            print(f"Failed to setup ML log: {e}")
            self.csv_file = None
            self.csv_writer = None

    def log_frame(self, is_locked: bool, tracking_error: float | None, frame_process_time: float,
                  *, detected: bool = False, hitbox_hit: bool = False, center_hit: bool = False,
                  lock_state: str | None = None):
        """Call once per simulation frame with that frame's outcome.

        Extended kwargs are optional for back-compat; when supplied they feed
        detection/hit rates and state distribution.
        """
        self.frame_count += 1
        self.processing_times.append(frame_process_time)

        if is_locked:
            self.locked_frame_count += 1
            if tracking_error is not None:
                self.tracking_errors.append(tracking_error)
            if self.acquisition_time is None and self.start_time is not None:
                self.acquisition_time = time.time() - self.start_time
                self._first_lock_time = self.acquisition_time

        # detection / hitbox
        if detected:
            self.detection_count += 1
        if hitbox_hit:
            self.hitbox_hit_count += 1
        if center_hit:
            self.center_hit_count += 1

        # state distribution
        if lock_state is not None:
            st = lock_state.lower()
            if st in self.state_counts:
                self.state_counts[st] += 1
            # lock loss / acquisition counting
            # acquisition = transition into tracking
            if st == "tracking" and self._prev_state != "tracking":
                self.acquisitions += 1
                if self._lost_since is not None:
                    # reacquisition time = now - time when we entered LOST
                    reacq = time.time() - self._lost_since
                    self.reacquisition_times.append(reacq)
                    self._lost_since = None
            if self._prev_state == "tracking" and st in ("lost", "searching"):
                self.lock_losses += 1
                if self._lost_since is None:
                    self._lost_since = time.time()
            if st in ("lost", "searching") and self._prev_state not in ("lost", "searching", None):
                if self._lost_since is None:
                    self._lost_since = time.time()
            self._prev_state = st
        else:
            # fallback single-bit locked tracking for legacy callers
            # treat is_locked as tracking vs not
            if is_locked and not self._prev_locked:
                self.acquisitions += 1
            if not is_locked and self._prev_locked:
                self.lock_losses += 1
        self._prev_locked = is_locked

        # Auto-log every second
        elapsed = (time.time() - self.start_time) if self.start_time else 0.0
        if self.csv_writer and self.csv_file and (elapsed - self._last_csv_log_time >= 1.0):
            # Calculate summary at this exact point to grab the requested metrics
            s = self.summary()
            
            # Write row mapped exactly to user requested ML features
            self.csv_writer.writerow([
                s.get("simulation_duration_s", 0),
                s.get("acquisition_time_s", 0) if s.get("acquisition_time_s") is not None else 0,
                s.get("avg_processing_time_ms", 0),
                s.get("avg_tracking_error_px", 0),
                s.get("max_tracking_error_px", 0),
                s.get("tracking_error_pct", 0),
                s.get("lock_retention_rate_pct", 0),
                s.get("detection_rate_pct", 0),
                s.get("detection_time_s", 0),
                s.get("searching_rate_pct", 0),
                s.get("searching_time_s", 0),
                s.get("center_hit_rate_pct", 0),
                s.get("center_hit_time_s", 0)
            ])
            self.csv_file.flush()
            self._last_csv_log_time = math.floor(elapsed)

    def summary(self) -> dict:
        elapsed = (time.time() - self.start_time) if self.start_time else 0.0
        fps = self.frame_count / elapsed if elapsed > 0 else 0.0
        # error stats
        n_err = len(self.tracking_errors)
        if n_err:
            avg_error = sum(self.tracking_errors) / n_err
            max_error = max(self.tracking_errors)
            min_error = min(self.tracking_errors)
            # rms
            rms = math.sqrt(sum(x*x for x in self.tracking_errors) / n_err)
            # std
            mean = avg_error
            var = sum((x - mean) ** 2 for x in self.tracking_errors) / n_err
            std_err = math.sqrt(var)
            # median and p95
            sorted_err = sorted(self.tracking_errors)
            median = sorted_err[n_err // 2]
            p95_idx = int(math.ceil(0.95 * n_err)) - 1
            p95 = sorted_err[max(0, min(p95_idx, n_err - 1))]
        else:
            avg_error = max_error = min_error = rms = std_err = median = p95 = 0.0

        lock_retention = (self.locked_frame_count / self.frame_count * 100) if self.frame_count else 0.0
        detection_rate = (self.detection_count / self.frame_count * 100) if self.frame_count else 0.0
        hitbox_rate = (self.hitbox_hit_count / self.detection_count * 100) if self.detection_count else 0.0
        center_rate = (self.center_hit_count / self.hitbox_hit_count * 100) if self.hitbox_hit_count else 0.0
        center_overall = (self.center_hit_count / self.detection_count * 100) if self.detection_count else 0.0

        if self.processing_times:
            avg_proc = sum(self.processing_times) / len(self.processing_times)
            # jitter = std of processing_time
            m = avg_proc
            var_p = sum((x - m) ** 2 for x in self.processing_times) / len(self.processing_times)
            jitter_ms = math.sqrt(var_p) * 1000.0
            # p95 proc
            sp = sorted(self.processing_times)
            p95_proc = sp[int(math.ceil(0.95 * len(sp))) - 1] * 1000.0
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

        # state pct
        total = self.frame_count if self.frame_count else 1
        state_pct = {k: round(v / total * 100, 2) for k, v in self.state_counts.items()}
        # ── dashboard-exact derived metrics ──
        # Tracking error (%) — avg as % of max (how much headroom remains); 0 if no max
        tracking_error_pct = round((avg_error / max_error * 100) if max_error > 0 else 0.0, 2)
        # Detection/Search/Center times — total time in that state = exact frames * duration
        detection_time_s = round((self.detection_count / total * elapsed) if self.frame_count else 0.0, 3)
        searching_time_s = round((self.state_counts.get("searching", 0) / total * elapsed) if self.frame_count else 0.0, 3)
        center_hit_time_s = round((self.center_hit_count / total * elapsed) if self.frame_count else 0.0, 3)
        # keep also fps-based alternative for reference (not shown in dashboard)
        return {
            # core — Timing & rate
            "simulation_duration_s": round(elapsed, 3),
            "frame_count": self.frame_count,
            "fps": round(fps, 2),
            "acquisition_time_s": round(self.acquisition_time, 3) if self.acquisition_time is not None else None,
            "avg_tracking_error_px": round(avg_error, 3),
            "max_tracking_error_px": round(max_error, 3),
            "lock_retention_rate_pct": round(lock_retention, 2),
            "avg_processing_time_ms": round(avg_proc * 1000, 3),
            # extended — error distribution
            "min_tracking_error_px": round(min_error, 3),
            "median_tracking_error_px": round(median, 3),
            "p95_tracking_error_px": round(p95, 3),
            "rms_tracking_error_px": round(rms, 3),
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
            # dashboard-exact aliases
            "tracking_error_pct": tracking_error_pct,
            "searching_rate_pct": state_pct["searching"],
            "searching_time_s": searching_time_s,
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
                with open(path, "w") as f:
                    json.dump(data, f, indent=2)
            else:
                with open(path, "w", newline="") as f:
                    writer = csv.writer(f)
                    writer.writerow(["metric", "value"])
                    for k, v in flat.items():
                        writer.writerow([k, v])
        except OSError as e:
            raise OSError(f"Failed to export report to {path}: {e}") from e

"""
Performance logging module — comprehensive real-time statistics and timeseries logging.

Collects per-frame stats during a simulation run and exports:
1) Frame-by-frame timeseries CSV per simulation directly in the 'log' folder
2) Complete metrics and statistics summary JSON per simulation
3) Export reports on demand (JSON / CSV)

All logs are stored directly in <project_root>/log/ without subfolder creation.
Optimized: dt-accumulated times, incremental stats, cached aggregates, EWMA FPS, config snapshot.
"""

import csv
import json
import math
import time
import os
import uuid
import atexit
import threading
import logging
from datetime import datetime

from perf_log.error_stats import compute_error_stats, error_pct_from_px
from perf_log.rates import compute_rates
from perf_log.timing import compute_fps

# Default log directory at project root: <project_root>/log, override via FSOC_LOG_DIR env
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOG_DIR = os.environ.get("FSOC_LOG_DIR", os.path.join(PROJECT_ROOT, "log"))
__version__ = "2.0"

logger = logging.getLogger("perf_log")
if not logger.handlers:
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("[%(levelname)s] perf_log: %(message)s"))
    logger.addHandler(handler)
    logger.setLevel(logging.WARNING)


class PerformanceLogger:
    """Collects frame-by-frame performance data and persists timeseries and summary logs."""

    def __init__(self, log_dir: str | None = None, auto_log: bool = True):
        self.log_dir = log_dir or LOG_DIR
        self.auto_log = auto_log

        self.start_time = None          # wall time (back-compat)
        self._start_mono = None         # monotonic for elapsed calculations
        self.frame_count = 0
        self.locked_frame_count = 0
        self.tracking_errors: list[float] = []
        self.processing_times: list[float] = []
        self.acquisition_time: float | None = None

        # extended stats
        self.detection_count = 0        # frames where detector found primary target
        self.hitbox_hit_count = 0
        self.center_hit_count = 0
        self.state_counts: dict[str, int] = {"searching": 0, "acquired": 0, "tracking": 0, "lost": 0}
        self.state_time_s: dict[str, float] = {"searching": 0.0, "acquired": 0.0, "tracking": 0.0, "lost": 0.0}
        self.lock_losses = 0
        self.acquisitions = 0
        self._prev_locked = False
        self._prev_state: str | None = None
        self.reacquisition_times: list[float] = []
        self._lost_since: float | None = None
        self._first_lock_time: float | None = None

        # incremental aggregates (avoid O(n log n) per frame)
        self._sum_err = 0.0
        self._sum_sq_err = 0.0
        self._min_err = float("inf")
        self._max_err = float("-inf")
        self._sum_proc = 0.0
        self._sum_sq_proc = 0.0
        self._min_proc = float("inf")
        self._max_proc = float("-inf")
        self._cached_stats: dict | None = None
        self._cached_stats_n: int = -1
        self._cached_p95_err: float = 0.0
        self._cached_p95_proc: float = 0.0

        # FPS EWMA (smooth display, raw fps still logged)
        self._fps_ewma: float | None = None
        self._last_frame_mono: float | None = None

        # config snapshot (set at start)
        self.config_snapshot: dict | None = None
        self.schema_version = __version__

        # File logging handles & paths
        self.csv_file = None
        self.csv_writer = None
        self.timeseries_path: str | None = None
        self.summary_path: str | None = None
        self._flush_counter = 0
        self._lock = threading.Lock()

        # atexit ensures flush on crash/close
        try:
            atexit.register(self.close)
        except Exception:
            pass

    def close(self):
        """Flush and close timeseries CSV, and auto-export final summary if data was logged."""
        with self._lock:
            # 1. Flush & close timeseries CSV
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

            # 2. Auto-save final simulation summary metrics if frames were recorded
            if self.auto_log and self.frame_count > 0 and self.summary_path:
                try:
                    os.makedirs(os.path.dirname(self.summary_path), exist_ok=True)
                    summary_data = self.summary()
                    with open(self.summary_path, "w", encoding="utf-8") as f:
                        json.dump(summary_data, f, indent=2)
                    # prune old logs (keep 20 latest)
                    try:
                        self._prune_old_logs(keep=20)
                    except Exception:
                        pass
                except Exception as e:
                    logger.warning(f"Failed to auto-save simulation summary: {e}")

    def _prune_old_logs(self, keep: int = 20):
        try:
            if not os.path.isdir(self.log_dir):
                return
            # only prune our own logs, never arbitrary user files; also ensure inside LOG_DIR
            allowed_prefixes = ("simulation_timeseries_", "simulation_summary_", "test_timeseries_", "test_summary_")
            abs_log = os.path.abspath(self.log_dir)
            candidates = []
            for f in os.listdir(self.log_dir):
                fp = os.path.join(self.log_dir, f)
                if not os.path.isfile(fp):
                    continue
                if not (f.startswith(allowed_prefixes) and (f.endswith(".csv") or f.endswith(".json"))):
                    continue
                # abspath check to prevent traversal
                if not os.path.abspath(fp).startswith(abs_log):
                    continue
                candidates.append(fp)
            if len(candidates) <= keep * 2:  # *2 for csv+json pairs
                return
            candidates.sort(key=lambda p: os.path.getmtime(p))
            to_remove = candidates[: len(candidates) - keep * 2]
            for p in to_remove:
                try:
                    os.remove(p)
                except Exception:
                    pass
        except Exception:
            pass

    def __del__(self):
        try:
            self.close()
        except Exception:
            pass

    def start(self, prefix: str = "simulation", config: dict | None = None):
        """Initialize state for a new simulation run and setup flat timeseries logging in log/."""
        # Close any existing handles / export summary for previous run
        self.close()

        self.start_time = time.time()
        self._start_mono = time.monotonic()
        self._last_frame_mono = self._start_mono
        self.frame_count = 0
        self.locked_frame_count = 0
        self.tracking_errors = []
        self.processing_times = []
        self.acquisition_time = None
        self.detection_count = 0
        self.hitbox_hit_count = 0
        self.center_hit_count = 0
        self.state_counts = {"searching": 0, "acquired": 0, "tracking": 0, "lost": 0}
        self.state_time_s = {"searching": 0.0, "acquired": 0.0, "tracking": 0.0, "lost": 0.0}
        self.lock_losses = 0
        self.acquisitions = 0
        self._prev_locked = False
        self._prev_state = None
        self.reacquisition_times = []
        self._lost_since = None
        self._first_lock_time = None
        self._flush_counter = 0
        self._sum_err = 0.0
        self._sum_sq_err = 0.0
        self._min_err = float("inf")
        self._max_err = float("-inf")
        self._sum_proc = 0.0
        self._sum_sq_proc = 0.0
        self._min_proc = float("inf")
        self._max_proc = float("-inf")
        self._cached_stats = None
        self._cached_stats_n = -1
        self._fps_ewma = None
        self.config_snapshot = dict(config) if isinstance(config, dict) else None

        if not self.auto_log:
            self.timeseries_path = None
            self.summary_path = None
            return

        # Setup logging directly inside the log folder (without creating subfolders)
        try:
            os.makedirs(self.log_dir, exist_ok=True)
            # sanitize prefix to prevent path traversal (C3)
            safe_prefix = "".join(c if c.isalnum() or c in ("_", "-") else "_" for c in str(prefix))[:32] or "simulation"
            # Timestamp with short unique ID to avoid collision on fast restarts
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S") + f"_{uuid.uuid4().hex[:4]}"
            timeseries_filename = f"{safe_prefix}_timeseries_{timestamp}.csv"
            summary_filename = f"{safe_prefix}_summary_{timestamp}.json"

            self.timeseries_path = os.path.join(self.log_dir, timeseries_filename)
            self.summary_path = os.path.join(self.log_dir, summary_filename)

            self.csv_file = open(self.timeseries_path, "w", newline="", encoding="utf-8", buffering=8192)
            self.csv_writer = csv.writer(self.csv_file)

            # Timeseries CSV header: per-frame instantaneous status + running statistics
            self.csv_writer.writerow([
                "Time (S)",
                "Frame",
                "Lock State",
                "Is Locked",
                "Instant Error (px)",
                "Frame Proc Time (ms)",
                "Detected",
                "Hitbox Hit",
                "Center Hit",
                "FPS",
                "FPS_EWMA",
                "Acquisition (S)",
                "Reacquisition Avg (S)",
                "Avg Tracking Error (px)",
                "RMS Error (px)",
                "Max Error (px)",
                "P95 Error (px)",
                "Std Error (px)",
                "Target Loss (%)",
                "Lock Retention (%)",
                "Lock Losses",
                "Acquisitions",
                "Proc Time Avg (ms)",
                "Proc Jitter (ms)",
                "Centroiding Avg (px)",
                "Centroiding RMSE (px)",
                "Detection Rate (%)",
                "Detection Time (S)",
                "Searching Rate (%)",
                "Searching Time (S)",
                "Center Hit Rate (%)",
                "Center Hit Time (S)"
            ])
            self.csv_file.flush()
        except Exception as e:
            logger.warning(f"Failed to setup simulation timeseries log: {e}")
            self.csv_file = None
            self.csv_writer = None

    def _elapsed(self) -> float:
        if self._start_mono is None:
            return 0.0
        return max(0.0, time.monotonic() - self._start_mono)

    def adjust_for_pause(self, pause_duration_s: float):
        """Called on resume to exclude paused wall-time from elapsed metrics."""
        if self._start_mono is not None:
            self._start_mono += float(pause_duration_s)
        if self.start_time is not None:
            self.start_time += float(pause_duration_s)
        if self._last_frame_mono is not None:
            self._last_frame_mono += float(pause_duration_s)

    def set_config_snapshot(self, config: dict):
        """Attach config snapshot for reproducibility (call before start or after)."""
        try:
            self.config_snapshot = dict(config)
        except Exception:
            self.config_snapshot = None

    def log_frame(self, is_locked: bool, tracking_error: float | None, frame_process_time: float,
                  *, detected: bool = False, hitbox_hit: bool = False, center_hit: bool = False,
                  lock_state: str | None = None, dt: float | None = None):
        """Record frame metrics and write timeseries row. dt (s) improves time accounting."""
        with self._lock:
            self.frame_count += 1
            now_mono = time.monotonic()
            # dt for state_time: use provided dt or delta from last frame
            if dt is None:
                if self._last_frame_mono is not None:
                    dt = max(0.0, now_mono - self._last_frame_mono)
                else:
                    dt = 0.033
            else:
                try:
                    dt = max(0.0, float(dt))
                except Exception:
                    dt = 0.033
            self._last_frame_mono = now_mono

            # FPS EWMA (alpha 0.1)
            instant_fps = (1.0 / dt) if dt > 1e-9 else 0.0
            if self._fps_ewma is None:
                self._fps_ewma = instant_fps
            else:
                self._fps_ewma = 0.9 * self._fps_ewma + 0.1 * instant_fps

            try:
                pt = float(frame_process_time)
                if pt < 0:
                    pt = 0.0
            except Exception:
                pt = 0.0
            self.processing_times.append(pt)
            # incremental proc stats with sliding window 5000
            self._sum_proc += pt
            self._sum_sq_proc += pt * pt
            if pt < self._min_proc:
                self._min_proc = pt
            if pt > self._max_proc:
                self._max_proc = pt
            if len(self.processing_times) > 5000:
                old = self.processing_times.pop(0)
                self._sum_proc -= old
                self._sum_sq_proc -= old * old
                if old == self._min_proc or old == self._max_proc:
                    # recompute min/max from window (rare)
                    try:
                        self._min_proc = min(self.processing_times) if self.processing_times else float("inf")
                        self._max_proc = max(self.processing_times) if self.processing_times else float("-inf")
                    except Exception:
                        pass

            # Tracking error & lock counting (sliding window 5000)
            err_val = None
            if is_locked:
                self.locked_frame_count += 1
                if tracking_error is not None:
                    try:
                        err_val = float(tracking_error)
                        self.tracking_errors.append(err_val)
                        self._sum_err += err_val
                        self._sum_sq_err += err_val * err_val
                        if err_val < self._min_err:
                            self._min_err = err_val
                        if err_val > self._max_err:
                            self._max_err = err_val
                        if len(self.tracking_errors) > 5000:
                            old_e = self.tracking_errors.pop(0)
                            self._sum_err -= old_e
                            self._sum_sq_err -= old_e * old_e
                            if old_e == self._min_err or old_e == self._max_err:
                                try:
                                    self._min_err = min(self.tracking_errors) if self.tracking_errors else float("inf")
                                    self._max_err = max(self.tracking_errors) if self.tracking_errors else float("-inf")
                                except Exception:
                                    pass
                    except Exception:
                        pass
                if self.acquisition_time is None and self._start_mono is not None:
                    self.acquisition_time = self._elapsed()
                    self._first_lock_time = self.acquisition_time

            # Detection & hitbox hits
            if detected:
                self.detection_count += 1
            if hitbox_hit:
                self.hitbox_hit_count += 1
            if center_hit:
                self.center_hit_count += 1

            # State transition tracking
            st_name = "searching"
            if lock_state is not None:
                st = lock_state.lower().strip()
                st_name = st
                if st in self.state_counts:
                    self.state_counts[st] += 1
                    self.state_time_s[st] += dt
                if st == "tracking" and self._prev_state != "tracking":
                    self.acquisitions += 1
                    if self._lost_since is not None:
                        reacq = now_mono - self._lost_since
                        if 0 <= reacq < 1e6:
                            self.reacquisition_times.append(float(reacq))
                        self._lost_since = None
                if st in ("lost", "searching") and self._prev_state not in ("lost", "searching", None):
                    if self._prev_state == "tracking":
                        self.lock_losses += 1
                    if self._lost_since is None:
                        self._lost_since = now_mono
                self._prev_state = st
            else:
                st_name = "tracking" if is_locked else "searching"
                # fallback state counts
                if st_name in self.state_counts:
                    self.state_counts[st_name] += 1
                    self.state_time_s[st_name] += dt
                if is_locked and not self._prev_locked:
                    self.acquisitions += 1
                if not is_locked and self._prev_locked:
                    self.lock_losses += 1
            self._prev_locked = is_locked

            # Write timeseries row (use cached summary to avoid double O(n) )
            if self.csv_writer and self.csv_file and not self.csv_file.closed:
                try:
                    elapsed = self._elapsed()
                    s = self._cached_summary()  # cheap cached
                    self.csv_writer.writerow([
                        round(elapsed, 3),
                        self.frame_count,
                        st_name,
                        1 if is_locked else 0,
                        round(err_val, 3) if err_val is not None else "",
                        round(pt * 1000.0, 3),
                        1 if detected else 0,
                        1 if hitbox_hit else 0,
                        1 if center_hit else 0,
                        s.get("fps", 0),
                        round(self._fps_ewma or 0, 2),
                        s.get("acquisition_time_s") if s.get("acquisition_time_s") is not None else "",
                        s.get("avg_reacquisition_time_s") if s.get("avg_reacquisition_time_s") is not None else "",
                        s.get("avg_tracking_error_px", 0),
                        s.get("rms_tracking_error_px", 0),
                        s.get("max_tracking_error_px", 0),
                        s.get("p95_tracking_error_px", 0),
                        s.get("std_tracking_error_px", 0),
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
                    # Flush periodically (every 30 frames ~1s @30Hz) to balance performance & durability
                    self._flush_counter += 1
                    if self._flush_counter % 30 == 0:
                        self.csv_file.flush()
                except Exception as e:
                    logger.debug(f"log_frame write failed: {e}")

    def _cached_summary(self) -> dict:
        """Return cached summary if n unchanged since last compute, else recompute lightweight."""
        n = self.frame_count
        if self._cached_stats is not None and self._cached_stats_n == n and self._cached_stats.get("_n_err") == len(self.tracking_errors):
            return self._cached_stats
        s = self.summary(use_cache=False)
        # store cache marker
        s["_n_err"] = len(self.tracking_errors)
        self._cached_stats = s
        self._cached_stats_n = n
        return s

    def summary(self, use_cache: bool = False) -> dict:
        """Compute all real-time and aggregate metrics and statistics."""
        if use_cache and self._cached_stats is not None and self._cached_stats_n == self.frame_count:
            return dict(self._cached_stats)
        elapsed = self._elapsed()
        fps = compute_fps(self.frame_count, elapsed)
        fps_ewma = round(self._fps_ewma or fps, 2)

        # Error stats: use incremental for avg/rms/std/min/max, compute p95/median via sampling every 10 frames or when n<1000
        n_err = len(self.tracking_errors)
        if n_err:
            avg_error = self._sum_err / n_err if n_err else 0.0
            rms = math.sqrt(self._sum_sq_err / n_err) if n_err else 0.0
            min_error = self._min_err if self._min_err != float("inf") else 0.0
            max_error = self._max_err if self._max_err != float("-inf") else 0.0
            var = (self._sum_sq_err / n_err - avg_error * avg_error) if n_err else 0.0
            std_err = math.sqrt(max(0.0, var))
            # p95/median via partial sort, throttled: recompute only every 30 frames or if n small
            if n_err < 500 or self.frame_count % 30 == 0 or self._cached_stats is None:
                s_sorted = sorted(self.tracking_errors)
                median = s_sorted[n_err // 2] if n_err % 2 == 1 else (s_sorted[n_err // 2 - 1] + s_sorted[n_err // 2]) / 2.0
                p95_idx = int(math.ceil(0.95 * n_err)) - 1
                p95_idx = max(0, min(p95_idx, n_err - 1))
                p95 = s_sorted[p95_idx]
                self._cached_p95_err = p95
            else:
                # use cached p95
                p95 = self._cached_p95_err
                s_sorted = None
                # quick median approx from avg if not recomputed
                median = avg_error
        else:
            avg_error = max_error = min_error = rms = std_err = median = p95 = 0.0

        lock_retention = (self.locked_frame_count / self.frame_count * 100) if self.frame_count else 0.0
        rates = compute_rates(self.frame_count, self.detection_count, self.hitbox_hit_count, self.center_hit_count)
        detection_rate = rates["detection_rate"]
        hitbox_rate = rates["hitbox_rate"]
        center_rate = rates["center_rate"]
        center_overall = rates["center_overall"]

        if self.processing_times:
            avg_proc = self._sum_proc / len(self.processing_times)
            var_p = (self._sum_sq_proc / len(self.processing_times) - avg_proc * avg_proc) if len(self.processing_times) else 0.0
            jitter_ms = math.sqrt(max(0.0, var_p)) * 1000.0
            # p95 proc throttled
            if len(self.processing_times) < 500 or self.frame_count % 30 == 0:
                sp = sorted(self.processing_times)
                idx = int(math.ceil(0.95 * len(sp))) - 1
                idx = max(0, min(idx, len(sp) - 1))
                p95_proc = sp[idx] * 1000.0
                self._cached_p95_proc = p95_proc
            else:
                p95_proc = self._cached_p95_proc
            min_proc = self._min_proc * 1000.0 if self._min_proc != float("inf") else 0.0
            max_proc = self._max_proc * 1000.0 if self._max_proc != float("-inf") else 0.0
        else:
            avg_proc = jitter_ms = p95_proc = min_proc = max_proc = 0.0

        if self.reacquisition_times:
            avg_reacq = sum(self.reacquisition_times) / len(self.reacquisition_times)
            min_reacq = min(self.reacquisition_times)
            max_reacq = max(self.reacquisition_times)
        else:
            avg_reacq = min_reacq = max_reacq = 0.0

        total = self.frame_count if self.frame_count else 1
        state_pct = {k: round(v / total * 100, 2) for k, v in self.state_counts.items()}

        tracking_error_pct = round((avg_error / max_error * 100) if max_error > 1e-9 else 0.0, 2)
        avg_tracking_error_pct = error_pct_from_px(avg_error)
        max_tracking_error_pct = error_pct_from_px(max_error)

        centroiding_avg = round(avg_error, 3)
        centroiding_rmse = round(rms, 3)
        centroiding_max = round(max_error, 3)
        target_loss_pct = round(100.0 - lock_retention, 2) if self.frame_count else 0.0
        proc_time_s = round(float(avg_proc), 6)

        # dt-accumulated times (accurate) fall back to count-proportional if dt not tracked (back-compat)
        detection_time_s = round(self.state_time_s.get("tracking", 0) if self.state_time_s.get("tracking") else (self.detection_count / total * elapsed) if self.frame_count else 0.0, 3)
        # more precise: detection_time is time where detected==True, but we approximate via state_time if available else proportional
        searching_time_s = round(self.state_time_s.get("searching", 0) if self.state_time_s.get("searching") else (self.state_counts.get("searching", 0) / total * elapsed) if self.frame_count else 0.0, 3)
        acquired_time_s = round(self.state_time_s.get("acquired", 0), 3)
        tracking_time_s = round(self.state_time_s.get("tracking", 0), 3)
        lost_time_s = round(self.state_time_s.get("lost", 0), 3)
        center_hit_time_s = round((self.center_hit_count / total * elapsed) if self.frame_count else 0.0, 3)

        return {
            "schema_version": self.schema_version,
            "created_at": datetime.now().isoformat(),
            "config_snapshot": self.config_snapshot,
            # Timing & rate (Sr.16, Sr.20)
            "simulation_duration_s": round(elapsed, 3),
            "frame_count": self.frame_count,
            "fps": round(fps, 2),
            "fps_ewma": fps_ewma,
            "processing_speed_fps": round(fps, 2),
            "acquisition_time_s": round(self.acquisition_time, 3) if self.acquisition_time is not None else None,
            "avg_tracking_error_px": round(avg_error, 3),
            "max_tracking_error_px": round(max_error, 3),
            "lock_retention_rate_pct": round(lock_retention, 2),
            "target_loss_pct": target_loss_pct,
            "avg_processing_time_ms": round(avg_proc * 1000, 3),

            # Error distribution
            "min_tracking_error_px": round(min_error, 3),
            "median_tracking_error_px": round(median, 3),
            "p95_tracking_error_px": round(p95, 3),
            "rms_tracking_error_px": round(rms, 3),
            "centroiding_error_avg_px": centroiding_avg,
            "centroiding_error_max_px": centroiding_max,
            "centroiding_error_rmse_px": centroiding_rmse,
            "centroiding_error_p95_px": round(p95, 3),
            "std_tracking_error_px": round(std_err, 3),

            # Processing timing & jitter
            "min_processing_time_ms": round(min_proc, 3),
            "max_processing_time_ms": round(max_proc, 3),
            "p95_processing_time_ms": round(p95_proc, 3),
            "jitter_ms": round(jitter_ms, 3),

            # Detection & hitbox rates
            "detection_count": self.detection_count,
            "detection_rate_pct": round(detection_rate, 2),
            "detection_time_s": detection_time_s,
            "hitbox_hit_count": self.hitbox_hit_count,
            "hitbox_hit_rate_pct": round(hitbox_rate, 2),
            "center_hit_count": self.center_hit_count,
            "center_hit_rate_pct": round((self.center_hit_count / total * 100) if self.frame_count else 0.0, 2),
            "center_hit_overall_pct": round(center_overall, 2),
            "center_hit_time_s": center_hit_time_s,

            # Dashboard aliases
            "tracking_error_pct": tracking_error_pct,
            "avg_tracking_error_pct": avg_tracking_error_pct,
            "max_tracking_error_pct": max_tracking_error_pct,
            "proc_time_s": proc_time_s,
            "searching_rate_pct": state_pct["searching"],
            "searching_time_s": searching_time_s,
            "reacquisition_time_s": round(avg_reacq, 3) if self.reacquisition_times else None,
            "reacquisition_time_avg_s": round(avg_reacq, 3) if self.reacquisition_times else None,
            "centroiding_error_px": centroiding_avg,
            "rmse_px": centroiding_rmse,

            # Lock dynamics & reacquisition
            "lock_losses": self.lock_losses,
            "acquisitions": self.acquisitions,
            "avg_reacquisition_time_s": round(avg_reacq, 3) if self.reacquisition_times else None,
            "min_reacquisition_time_s": round(min_reacq, 3) if self.reacquisition_times else None,
            "max_reacquisition_time_s": round(max_reacq, 3) if self.reacquisition_times else None,

            # State distribution & durations
            "state_searching_pct": state_pct["searching"],
            "state_acquired_pct": state_pct["acquired"],
            "state_tracking_pct": state_pct["tracking"],
            "state_lost_pct": state_pct["lost"],
            "state_searching_time_s": searching_time_s,
            "state_acquired_time_s": acquired_time_s,
            "state_tracking_time_s": tracking_time_s,
            "state_lost_time_s": lost_time_s,
            "state_counts": dict(self.state_counts),
            "state_time_s": dict(self.state_time_s),
        }

    def export_report(self, path: str):
        """Export current performance summary report to disk (JSON or CSV)."""
        data = self.summary()
        p = path.lower()
        try:
            os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
            if p.endswith(".json"):
                with open(path, "w", encoding="utf-8") as f:
                    json.dump(data, f, indent=2)
            else:
                flat = {}
                for k, v in data.items():
                    if k == "state_counts":
                        for sk, sv in v.items():
                            flat[f"state_count_{sk}"] = sv
                    elif k == "state_time_s":
                        for sk, sv in v.items():
                            flat[f"state_time_{sk}"] = sv
                    elif k == "config_snapshot" and isinstance(v, dict):
                        for ck, cv in v.items():
                            flat[f"config_{ck}"] = cv
                    else:
                        flat[k] = v
                with open(path, "w", newline="", encoding="utf-8") as f:
                    writer = csv.writer(f)
                    writer.writerow(["metric", "value"])
                    for k, v in flat.items():
                        writer.writerow([k, v])
        except OSError as e:
            raise OSError(f"Failed to export report to {path}: {e}") from e

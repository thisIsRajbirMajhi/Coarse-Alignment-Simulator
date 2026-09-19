# local_terminal/metrics.py - Live tracking-performance accumulator (Qt-free).
#
# Feeds the Live Dashboard (Metrics.png / Metrics1.png). Consumes only the
# LocalTerminal telemetry dict + dt, so it works identically for the GUI
# session, headless runs, and unit tests. No Qt, no sim imports.
from __future__ import annotations

import math
from typing import Any


def _num(value: Any, default: float = 0.0) -> float:
    try:
        out = float(value)
    except Exception:
        return float(default)
    if out != out or out in (float("inf"), float("-inf")):
        return float(default)
    return out


class TrackingMetrics:
    """Accumulates the 13 dashboard metrics from per-frame telemetry.

    Metrics (Metrics.png):
      acquisition_time_s .... search-episode start -> first ACQUIRED/TRACKING
      reacquisition_time_s .. last REACQUIRING episode duration (live while active)
      searching_time_s ...... cumulative time with acquisition_state == SEARCHING
      retention_rate_pct .... held/(held+unheld)*100 since first acquisition,
                              held = ACQUIRED/TRACKING/DEGRADED time
      detection_rate_pct .... frames with >=1 candidate / total frames * 100
      center_hit_rate_pct ... centered frames / TRACKING frames * 100
                              (centered = tracking error <= 5 px)
      target_loss_rate ...... target losses per minute of run time
      avg_track_err_px ...... mean tracking-error magnitude (px, TRACKING frames)
      reacquisition_count ... entries into REACQUIRING
      target_loss_count ..... entries into LOST
      target_switch_count ... active-observation changes (id A -> id B)
      rms_px ................ RMS tracking error (px, TRACKING frames)
    """

    CENTER_TOL_PX = 5.0

    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        self.total_frames = 0
        self.total_time_s = 0.0
        self.frames_with_candidate = 0
        self.searching_time_s = 0.0
        # acquisition timing
        self._search_episode_start: float | None = None
        self.acquisition_time_s: float | None = None
        self._ever_acquired = False
        # retention accounting (starts at first acquisition)
        self._held_time_s = 0.0
        self._unheld_time_s = 0.0
        # reacquisition episodes
        self._reacq_start: float | None = None
        self._reacq_live_s = 0.0
        self.reacquisition_time_s: float | None = None
        self.reacquisition_count = 0
        # losses / switches
        self.target_loss_count = 0
        self.target_switch_count = 0
        self._last_active_id: str | None = None
        self._had_active = False
        # error statistics (TRACKING frames only)
        self._track_frames = 0
        self._centered_frames = 0
        self._err_sum = 0.0
        self._err_sumsq = 0.0
        # previous discrete states for edge detection
        self._prev_acq: str | None = None
        self._prev_trk: str | None = None

    def update(self, dt: float, lt_telemetry: dict | None,
               pixel_scale_mrad: float = 0.109083) -> None:
        """Fold one frame of LocalTerminal.get_telemetry() output."""
        dt = _num(dt, 0.033)
        if not math.isfinite(dt) or dt <= 0:
            dt = 0.033
        dt = max(1e-4, min(dt, 0.5))
        self.total_frames += 1
        self.total_time_s += dt
        now = self.total_time_s
        if not isinstance(lt_telemetry, dict):
            return

        state = lt_telemetry.get("state") or {}
        acq = str(state.get("acquisition_state") or "")
        trk = str(state.get("tracking_state") or "")
        autonomy = lt_telemetry.get("autonomy") or {}
        active_id = autonomy.get("active_target_id")
        try:
            n_cands = int(autonomy.get("candidate_count", 0))
        except Exception:
            n_cands = 0

        if n_cands > 0:
            self.frames_with_candidate += 1
        if acq == "SEARCHING":
            self.searching_time_s += dt
            if self._prev_acq != "SEARCHING":
                self._search_episode_start = now
        if acq in ("ACQUIRED",) or trk in ("TRACKING", "DEGRADED", "REACQUIRING"):
            if not self._ever_acquired and self._search_episode_start is not None:
                self.acquisition_time_s = max(0.0, now - self._search_episode_start)
            self._ever_acquired = True

        if self._ever_acquired:
            if trk in ("TRACKING", "DEGRADED") or acq == "ACQUIRED":
                self._held_time_s += dt
            elif trk in ("REACQUIRING", "LOST"):
                self._unheld_time_s += dt

        # reacquisition episodes: edge into REACQUIRING / out of it
        if trk == "REACQUIRING" and self._prev_trk != "REACQUIRING":
            self._reacq_start = now
            self.reacquisition_count += 1
        if trk == "REACQUIRING":
            self._reacq_live_s = max(0.0, now - (self._reacq_start or now))
            self.reacquisition_time_s = self._reacq_live_s
        elif self._prev_trk == "REACQUIRING" and self._reacq_start is not None:
            self.reacquisition_time_s = max(0.0, now - self._reacq_start)
            self._reacq_start = None
            self._reacq_live_s = 0.0

        if trk == "LOST" and self._prev_trk != "LOST":
            self.target_loss_count += 1

        if isinstance(active_id, str) and active_id:
            if self._had_active and self._last_active_id not in (None, "") \
                    and active_id != self._last_active_id:
                self.target_switch_count += 1
            self._last_active_id = active_id
            self._had_active = True
        # NOTE: a None active id (coast/loss) intentionally does NOT clear
        # _last_active_id, so relocking a different observation afterwards
        # still counts as a target switch.

        # error statistics on TRACKING frames with a usable error vector
        if trk == "TRACKING":
            err = self._extract_error_px(lt_telemetry)
            if err is not None:
                self._track_frames += 1
                self._err_sum += err
                self._err_sumsq += err * err
                if err <= self.CENTER_TOL_PX:
                    self._centered_frames += 1

        self._prev_acq = acq
        self._prev_trk = trk

    @staticmethod
    def _extract_error_px(lt_telemetry: dict) -> float | None:
        try:
            tracking = lt_telemetry.get("tracking") or {}
            err = tracking.get("error_px")
            if err is not None and len(err) == 2:  # noqa: PLR2004
                ex, ey = _num(err[0]), _num(err[1])
                return math.hypot(ex, ey)
        except Exception:
            pass
        return None

    # -- derived readouts ------------------------------------------------
    @property
    def detection_rate_pct(self) -> float | None:
        if self.total_frames <= 0:
            return None
        return 100.0 * self.frames_with_candidate / self.total_frames

    @property
    def center_hit_rate_pct(self) -> float | None:
        if self._track_frames <= 0:
            return None
        return 100.0 * self._centered_frames / self._track_frames

    @property
    def retention_rate_pct(self) -> float | None:
        total = self._held_time_s + self._unheld_time_s
        if not self._ever_acquired or total <= 1e-9:
            return None
        return 100.0 * self._held_time_s / total

    @property
    def target_loss_rate_per_min(self) -> float:
        mins = self.total_time_s / 60.0
        if mins <= 1e-9:
            return 0.0
        return self.target_loss_count / mins

    @property
    def avg_track_err_px(self) -> float | None:
        if self._track_frames <= 0:
            return None
        return self._err_sum / self._track_frames

    @property
    def rms_px(self) -> float | None:
        if self._track_frames <= 0:
            return None
        return math.sqrt(self._err_sumsq / self._track_frames)

    def snapshot(self, pixel_scale_mrad: float = 0.109083) -> dict[str, Any]:
        """Display-ready values (None = no data yet)."""
        avg_px = self.avg_track_err_px
        rms = self.rms_px
        scale = _num(pixel_scale_mrad, 0.109083)
        return {
            "acquisition_time_s": self.acquisition_time_s,
            "reacquisition_time_s": self.reacquisition_time_s,
            "searching_time_s": self.searching_time_s,
            "retention_rate_pct": self.retention_rate_pct,
            "detection_rate_pct": self.detection_rate_pct,
            "center_hit_rate_pct": self.center_hit_rate_pct,
            "target_loss_rate_per_min": self.target_loss_rate_per_min,
            "avg_track_err_px": avg_px,
            "avg_track_err_mrad": (avg_px * scale) if avg_px is not None else None,
            "reacquisition_count": int(self.reacquisition_count),
            "target_loss_count": int(self.target_loss_count),
            "target_switch_count": int(self.target_switch_count),
            "rms_px": rms,
            "rms_mrad": (rms * scale) if rms is not None else None,
        }

# gui/presentation/simulation_presenter.py - Snapshot+metrics -> DashboardState.
# Single source of truth: MetricsLogger.summary + controller timing.
from __future__ import annotations

import logging
from collections import deque

log = logging.getLogger(__name__)

from gui.presentation.view_state import DashboardState


class SimulationPresenter:
    """Builds DashboardState from session/controller outputs. No Qt."""

    def __init__(self):
        self._err_window: deque[float] = deque(maxlen=200)
        self._acquisitions = 0
        self._lock_losses = 0
        self._prev_lock = "searching"

    def reset(self) -> None:
        self._err_window.clear()
        self._acquisitions = 0
        self._lock_losses = 0
        self._prev_lock = "searching"

    def update(self, snapshot, session, controller) -> DashboardState:
        lock = getattr(snapshot, "lock_state", "searching") if snapshot is not None else "searching"
        err = getattr(snapshot, "tracking_error_px", None) if snapshot is not None else None
        if err is not None:
            try:
                self._err_window.append(float(err))
            except Exception:
                pass
        if lock != self._prev_lock:
            if lock == "tracking" and self._prev_lock != "tracking":
                self._acquisitions += 1
            if self._prev_lock == "tracking" and lock != "tracking":
                self._lock_losses += 1
        self._prev_lock = lock

        scale = float(getattr(snapshot, "pixel_scale_mrad", 0.035) or 0.035) if snapshot else 0.035
        msum = None
        try:
            logger = getattr(session, "metrics_logger", None)
            recs = list(getattr(logger, "records", [])) if logger is not None else []
            if logger is not None and recs:
                try:
                    hb = int(getattr(session.target, "hitbox_radius", 14))
                except Exception:
                    hb = 14
                try:
                    cr = int(getattr(session.target, "center_radius", 2))
                except Exception:
                    cr = 2
                try:
                    msum = logger.summary(hitbox_radius=hb, center_radius=cr)
                except TypeError:
                    msum = logger.summary()
        except Exception as e:
            log.debug("metrics summary failed: %s", e)

        if msum:
            acq = msum.get("acquisition_time_s")
            reacq = msum.get("avg_reacquisition_time_s")
            search_t = msum.get("searching_time_s")
            retention = msum.get("lock_retention_pct")
            detection = msum.get("detection_rate_pct")
            center = msum.get("center_hit_rate_pct")
            loss = msum.get("target_loss_pct")
            reacq_count = int(msum.get("reacquisition_count", msum.get("reacq_events", 0)) or 0)
            loss_count = int(msum.get("loss_events", self._lock_losses) or self._lock_losses)
            switches = int(msum.get("id_switches", 0) or 0)
        else:
            acq = reacq = search_t = retention = detection = center = loss = None
            reacq_count = 0
            loss_count = int(self._lock_losses)
            switches = int(getattr(snapshot, "id_switches", 0) or 0) if snapshot else 0

        if self._err_window:
            import math
            arr = list(self._err_window)
            avg = sum(arr) / len(arr)
            rms = math.sqrt(sum(x * x for x in arr) / len(arr))
        else:
            avg = rms = None

        # Lifecycle-aware status: STOPPED/PAUSED override pipeline lock state.
        try:
            from gui.application.state import LifecycleState
            lc = getattr(controller, "lifecycle", None)
            if lc == LifecycleState.STOPPED:
                status = "STOPPED"
            elif lc == LifecycleState.PAUSED:
                status = "PAUSED"
            elif snapshot is None:
                status = "STOPPED"
            else:
                status = str(lock).upper()
        except Exception:
            status = str(lock).upper() if snapshot else "STOPPED"

        return DashboardState(
            jitter_ms=controller.jitter_ms if controller else None,
            acquisition_time_s=acq, reacquisition_time_s=reacq, searching_time_s=search_t,
            retention_rate_pct=float(retention) if retention is not None else None,
            detection_rate_pct=float(detection) if detection is not None else None,
            center_hit_rate_pct=float(center) if center is not None else None,
            target_loss_rate_pct=float(loss) if loss is not None else None,
            avg_track_err_px=avg, avg_track_err_mrad=(avg * scale) if avg is not None else None,
            reacquisition_count=reacq_count, target_loss_count=loss_count, target_switch_count=switches,
            rms_px=rms, rms_mrad=(rms * scale) if rms is not None else None,
            status=status,
            duration_s=float(controller.duration_s) if controller else 0.0,
            fps=float(controller.fps) if controller else 0.0,
        )

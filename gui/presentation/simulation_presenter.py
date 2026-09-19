# gui/presentation/simulation_presenter.py - Snapshot+metrics -> DashboardState.
from __future__ import annotations

import logging

log = logging.getLogger(__name__)

from gui.presentation.view_state import DashboardState


class SimulationPresenter:
    """Builds DashboardState from session/controller telemetry. No Qt."""

    def __init__(self):
        self._err_window: list[float] = []
        from local_terminal.telemetry.metrics import TrackingMetrics
        self.metrics = TrackingMetrics()

    def reset(self) -> None:
        self._err_window.clear()
        try:
            self.metrics.reset()
        except Exception:
            pass

    def update(self, snapshot, session, controller) -> DashboardState:
        # Lifecycle status
        try:
            from gui.application.state import LifecycleState
            lc = getattr(controller, "lifecycle", None)
            if lc == LifecycleState.STOPPED:
                status = "STOPPED"
            elif lc == LifecycleState.PAUSED:
                status = "PAUSED"
            elif lc == LifecycleState.ERROR:
                status = "ERROR"
            elif snapshot is None:
                status = "STOPPED"
            else:
                status = "RUNNING"
        except Exception:
            status = "STOPPED" if snapshot is None else "RUNNING"

        pan = float(getattr(snapshot, "pan", 0.0) if snapshot else 0.0)
        tilt = float(getattr(snapshot, "tilt", 0.0) if snapshot else 0.0)
        fov_sz = getattr(snapshot, "fov_size", (640, 480)) if snapshot else (640, 480)
        world_sz = getattr(snapshot, "world_size", (2000, 2000)) if snapshot else (2000, 2000)

        # Disturbance telemetry
        turb = 0
        vib = 0
        cam_mot = 0
        noise = 0
        preset = "Clear"
        prof = "Linear"
        spd = 0.0
        if session is not None and hasattr(session, "disturbance_config"):
            dc = session.disturbance_config
            turb = int(getattr(dc, "turbulence", 0))
            vib = int(getattr(dc, "vibration", 0))
            cam_mot = int(getattr(dc, "camera_motion", 0))
            noise = int(getattr(dc, "noise", 0))
            preset = str(getattr(dc, "atmospheric_preset", "Clear"))
            prof = str(getattr(dc, "platform_profile", "Linear"))
            spd = float(getattr(dc, "platform_speed", 0.0))

        # Tracking-performance metrics from the Local Terminal pipeline.
        # Snapshot carries the get_telemetry() dict; accumulator is
        # episode-persistent and resets via presenter.reset().
        try:
            lt_tele = getattr(snapshot, "local_terminal", None) if snapshot else None
            dt = float(getattr(snapshot, "dt", 1 / 30)) if snapshot else 1 / 30
            scale = float(getattr(snapshot, "pixel_scale_mrad", 0.109083)) if snapshot else 0.109083
            if snapshot is not None:
                self.metrics.update(dt, lt_tele if isinstance(lt_tele, dict) else None, scale)
            snap_metrics = self.metrics.snapshot(scale)
        except Exception:
            snap_metrics = {}

        return DashboardState(
            status=status,
            duration_s=float(controller.duration_s) if controller else 0.0,
            fps=float(controller.fps) if controller else 0.0,
            jitter_ms=controller.jitter_ms if controller else None,
            pan=pan,
            tilt=tilt,
            fov_w=int(fov_sz[0]),
            fov_h=int(fov_sz[1]),
            world_w=int(world_sz[0]),
            world_h=int(world_sz[1]),
            turbulence=turb,
            vibration=vib,
            camera_motion=cam_mot,
            noise=noise,
            atmospheric_preset=preset,
            platform_profile=prof,
            platform_speed=spd,
            acquisition_time_s=snap_metrics.get("acquisition_time_s"),
            reacquisition_time_s=snap_metrics.get("reacquisition_time_s"),
            searching_time_s=snap_metrics.get("searching_time_s"),
            retention_rate_pct=snap_metrics.get("retention_rate_pct"),
            detection_rate_pct=snap_metrics.get("detection_rate_pct"),
            center_hit_rate_pct=snap_metrics.get("center_hit_rate_pct"),
            target_loss_rate_pct=snap_metrics.get("target_loss_rate_per_min"),
            avg_track_err_px=snap_metrics.get("avg_track_err_px"),
            avg_track_err_mrad=snap_metrics.get("avg_track_err_mrad"),
            reacquisition_count=int(snap_metrics.get("reacquisition_count", 0)),
            target_loss_count=int(snap_metrics.get("target_loss_count", 0)),
            target_switch_count=int(snap_metrics.get("target_switch_count", 0)),
            rms_px=snap_metrics.get("rms_px"),
            rms_mrad=snap_metrics.get("rms_mrad"),
        )

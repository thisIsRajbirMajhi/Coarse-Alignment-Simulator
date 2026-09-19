# gui/presentation/simulation_presenter.py - Snapshot+metrics -> DashboardState.
from __future__ import annotations

import logging

log = logging.getLogger(__name__)

from gui.presentation.view_state import DashboardState


class SimulationPresenter:
    """Builds DashboardState from session/controller telemetry. No Qt."""

    def __init__(self):
        pass

    def reset(self) -> None:
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

        if status == "RUNNING":
            dur = float(controller.duration_s) if controller else 0.0
            snap_metrics = {
                "searching_time_s": dur,
                "detection_rate_pct": 0.0,
                "reacquisition_count": 0,
                "target_loss_count": 0,
                "target_switch_count": 0,
            }
        else:
            snap_metrics = {}

        # Diagnostics strip fields (best-effort; stay "—" when unknown).
        source_id, target_id, link_state, beacon_state = "—", "—", "—", "—"
        frame_id = 0
        try:
            if snapshot is not None:
                frame_id = int(getattr(snapshot, "frame_id", 0) or 0)
            terms = getattr(snapshot, "terminals", None) if snapshot else None
            if isinstance(terms, dict):
                link_state = str(terms.get("best_link", "—"))
                try:
                    emitting = int(terms.get("emitting_count", 0) or 0)
                    beacon_state = "EMITTING" if emitting > 0 else "—"
                except (TypeError, ValueError):
                    pass
                try:
                    term_list = terms.get("terminals", []) or []
                    if term_list and isinstance(term_list[0], dict):
                        target_id = str(term_list[0].get("id", "—"))
                except (TypeError, ValueError, AttributeError, IndexError):
                    pass
        except Exception:
            pass


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
            source_id=source_id,
            target_id=target_id,
            link_state=link_state,
            beacon_state=beacon_state,
            frame_id=frame_id,
        )

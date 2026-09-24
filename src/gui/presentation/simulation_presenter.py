# gui/presentation/simulation_presenter.py - Snapshot+metrics -> DashboardState.
from __future__ import annotations

import logging

log = logging.getLogger(__name__)

from src.gui.presentation.view_state import DashboardState, TerminalLiveState


def _terminal_state(t: dict) -> TerminalLiveState:
    """Best-effort conversion of one manager telemetry dict (never raises)."""
    try:
        pos = t.get("position_m") or (None, None)
        vel = t.get("velocity_mps") or (None, None)
        nav = t.get("beacon_navigation") or {}
        return TerminalLiveState(
            terminal_id=str(t.get("id")) if t.get("id") is not None else None,
            power_on=bool(t["power_on"]) if "power_on" in t else None,
            beacon_on=bool(t["beacon_on"]) if "beacon_on" in t else None,
            op_state=str(t.get("operational_state")) if t.get("operational_state") else None,
            power_w=float(t["optical_power_w"]) if t.get("optical_power_w") is not None else None,
            wavelength_nm=float(t["wavelength_nm"]) if t.get("wavelength_nm") is not None else None,
            pos_x_m=float(pos[0]) if pos[0] is not None else None,
            pos_y_m=float(pos[1]) if pos[1] is not None else None,
            vel_x_mps=float(vel[0]) if vel[0] is not None else None,
            vel_y_mps=float(vel[1]) if vel[1] is not None else None,
            los_deg=float(t["los_angle_deg"]) if t.get("los_angle_deg") is not None else None,
            beam_deg=float(t["beam_angle_deg"]) if t.get("beam_angle_deg") is not None else None,
            pointing_err_deg=float(t["pointing_error_deg"]) if t.get("pointing_error_deg") is not None else None,
            range_m=float(t["range_m"]) if t.get("range_m") is not None else None,
            beam_diameter_m=float(t["beam_diameter_m"]) if t.get("beam_diameter_m") is not None else None,
            emitting=bool(t["emitting"]) if "emitting" in t else None,
            beacon_seq=int(t["beacon_sequence"]) if t.get("beacon_sequence") is not None else None,
            nav_timestamp_ms=int(nav["timestamp_ms"]) if nav.get("timestamp_ms") is not None else None,
        )
    except (AttributeError, TypeError, ValueError, IndexError, KeyError):
        return TerminalLiveState()


class SimulationPresenter:
    """Builds DashboardState from session/controller telemetry. No Qt."""

    def __init__(self):
        self._total_track_frames = 0
        self._center_hit_frames = 0

    def reset(self) -> None:
        self._total_track_frames = 0
        self._center_hit_frames = 0

    def update(self, snapshot, session, controller) -> DashboardState:
        # Lifecycle status
        try:
            from src.gui.application.state import LifecycleState
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

        # Plan Stage 1: real image-tracker state replaces placeholder zeros.
        tt = dict(getattr(snapshot, "tracker_telemetry", None) or {})

        if status == "RUNNING":
            dur = float(controller.duration_s) if controller else 0.0
            search_t = float(tt.get("total_searching_time_s", dur))
            acq_t = tt.get("acquisition_time_s")
            reacq_t = tt.get("reacquisition_time_s")
            snap_metrics = {
                "searching_time_s": search_t,
                "acquisition_time_s": float(acq_t) if acq_t is not None else None,
                "reacquisition_time_s": float(reacq_t) if reacq_t is not None else None,
                "detection_rate_pct": float(tt.get("detection_rate_pct", 0.0)),
                "reacquisition_count": int(tt.get("reacquisition_count", 0)),
                "target_loss_count": int(tt.get("target_loss_count", 0)),
                "target_switch_count": 0,
            }
            # Tracking error and stability metrics
            losses = int(tt.get("target_loss_count", 0))
            locked = bool(tt.get("locked", False))
            pid_tel = getattr(snapshot, "pid_telemetry", None)
            err_px_val = None
            if pid_tel and isinstance(pid_tel, dict) and pid_tel.get("active"):
                err_px = float(pid_tel.get("error_pan_px", 0.0))
                err_py = float(pid_tel.get("error_tilt_px", 0.0))
                err_px_val = (err_px ** 2 + err_py ** 2) ** 0.5
                snap_metrics["avg_track_err_px"] = err_px_val
                snap_metrics["rms_px"] = err_px_val
                # Convert to mrad: (4° / 640px) * (pi / 180) * 1000 mrad/rad = ~0.109 mrad/px
                err_mrad = err_px_val * (4.0 / 640.0) * (3.14159265 / 180.0) * 1000.0
                snap_metrics["avg_track_err_mrad"] = err_mrad
                snap_metrics["rms_mrad"] = err_mrad

            # Center hit rate and retention rate
            if locked and err_px_val is not None:
                self._total_track_frames = getattr(self, "_total_track_frames", 0) + 1
                if err_px_val <= 10.0:
                    self._center_hit_frames = getattr(self, "_center_hit_frames", 0) + 1
                snap_metrics["center_hit_rate_pct"] = round(
                    100.0 * self._center_hit_frames / max(1, self._total_track_frames), 1
                )
                snap_metrics["retention_rate_pct"] = max(
                    0.0, min(100.0, round(100.0 * (1.0 - losses / max(1.0, self._total_track_frames / 30.0)), 1))
                )
            elif getattr(self, "_total_track_frames", 0) > 0:
                snap_metrics["center_hit_rate_pct"] = round(
                    100.0 * self._center_hit_frames / max(1, self._total_track_frames), 1
                )
                snap_metrics["retention_rate_pct"] = max(
                    0.0, min(100.0, round(100.0 * (1.0 - losses / max(1.0, self._total_track_frames / 30.0)), 1))
                )

            # Average loss rate per minute
            if dur > 0.5:
                snap_metrics["target_loss_rate_per_min"] = round(losses / (dur / 60.0), 2)
        else:
            snap_metrics = {}

        # Diagnostics strip fields (best-effort; stay "—" when unknown).
        source_id, target_id, link_state, beacon_state = "—", "—", "—", "—"
        frame_id = 0
        terminal_count = 0
        emitting_count = 0
        sim_time_s = 0.0
        live_terminal: TerminalLiveState | None = None
        terminal_rows: tuple = ()
        try:
            if snapshot is not None:
                frame_id = int(getattr(snapshot, "frame_id", 0) or 0)
            terms = getattr(snapshot, "terminals", None) if snapshot else None
            if isinstance(terms, dict):
                term_list = terms.get("terminals", []) or []
                terminal_count = int(terms.get("terminal_count", len(term_list)) or 0)
                try:
                    sim_time_s = float(terms.get("simulation_time_s", 0.0) or 0.0)
                except (TypeError, ValueError):
                    sim_time_s = 0.0
                rows = [_terminal_state(t) for t in term_list if isinstance(t, dict)]
                terminal_rows = tuple(rows)
                emitting = [t for t in term_list
                            if isinstance(t, dict) and t.get("emitting")]
                emitting_count = len(emitting)
                if emitting:
                    beacon_state = "EMITTING"
                    target_id = str(emitting[0].get("id", "—"))
                    live_terminal = _terminal_state(emitting[0])
                    states = {str(t.get("operational_state", "")) for t in emitting}
                    if "linked" in states:
                        link_state = "LINKED"
                    elif "beaconing" in states:
                        link_state = "BEACONING"
                    else:
                        link_state = "EMITTING"
                elif term_list and isinstance(term_list[0], dict):
                    target_id = str(term_list[0].get("id", "—"))
                    live_terminal = _terminal_state(term_list[0])
                    link_state = str(term_list[0].get("operational_state", "—")).upper()
        except (AttributeError, TypeError, ValueError):
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
            acquisition_time_s=snap_metrics.get("acquisition_time_s", tt.get("acquisition_time_s")),
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
            terminal_count=terminal_count,
            emitting_count=emitting_count,
            sim_time_s=sim_time_s,
            live_terminal=live_terminal,
            terminals=terminal_rows,
        )

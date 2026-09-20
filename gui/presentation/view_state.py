# gui/presentation/view_state.py - Presentation models (Qt-free).
from __future__ import annotations

from dataclasses import dataclass


def fmt_time_s(v: float | None) -> str:
    return "—" if v is None else f"{v:.1f} Sec"


def fmt_ms(v: float | None) -> str:
    return "—" if v is None else f"{v:.0f} Ms"


def fmt_pct(v: float | None) -> str:
    return "—" if v is None else f"{v:.0f} %"


def fmt_px(v: float | None) -> str:
    return "—" if v is None else f"{v:.1f} px"


def fmt_dim(w: int | None, h: int | None) -> str:
    if w is None or h is None:
        return "—"
    return f"{w} × {h}"


def fmt_px_mrad(px: float | None, mrad: float | None) -> str:
    if px is None or mrad is None:
        return "—"
    return f"{px:.0f} PX | {mrad:.2f} MRAD"


def fmt_per_min(v: float | None) -> str:
    return "—" if v is None else f"{v:.2f} /min"


def fmt_count(v: int | None) -> str:
    return "—" if v is None else str(int(v))


def fmt_xy(x: float | None, y: float | None, unit: str, decimals: int = 1) -> str:
    if x is None or y is None:
        return "—"
    return f"({x:.{decimals}f}, {y:.{decimals}f}) {unit}"


def fmt_deg(v: float | None) -> str:
    return "—" if v is None else f"{v:.1f}°"


def fmt_range_m(v: float | None) -> str:
    if v is None:
        return "—"
    if abs(v) >= 1000.0:
        return f"{v / 1000.0:.2f} km"
    return f"{v:.1f} m"


def fmt_on_off(v: bool | None) -> str:
    if v is None:
        return "—"
    return "ON" if v else "OFF"


_OP_STATE_SHORT = {
    "beaconing": "BEACON",
    "linked": "LINKED",
    "standby": "STANDBY",
    "off": "OFF",
    "fault": "FAULT",
}


def short_op_state(v: str | None) -> str:
    """Compact operational-state display for tables ("BEACONING" -> "BEACON")."""
    if v is None:
        return "—"
    return _OP_STATE_SHORT.get(str(v).lower(), str(v).upper())


@dataclass
class TerminalLiveState:
    """One terminal's live snapshot for the dashboard (all fields optional).

    ``None`` renders as "—". Lists in DashboardState are plain dicts so the
    presentation layer stays Qt-free and trivially testable.
    """

    terminal_id: str | None = None
    power_on: bool | None = None
    beacon_on: bool | None = None
    op_state: str | None = None
    power_w: float | None = None
    wavelength_nm: float | None = None
    pos_x_m: float | None = None
    pos_y_m: float | None = None
    vel_x_mps: float | None = None
    vel_y_mps: float | None = None
    los_deg: float | None = None
    beam_deg: float | None = None
    pointing_err_deg: float | None = None
    range_m: float | None = None
    beam_diameter_m: float | None = None
    emitting: bool | None = None
    beacon_seq: int | None = None
    nav_timestamp_ms: int | None = None


@dataclass
class DashboardState:
    # Simulator runtime & performance
    status: str = "STOPPED"
    duration_s: float = 0.0
    fps: float = 0.0
    jitter_ms: float | None = None

    # Camera telemetry
    pan: float = 0.0
    tilt: float = 0.0
    fov_w: int = 640
    fov_h: int = 480
    world_w: int = 2000
    world_h: int = 2000

    # Disturbance status
    turbulence: int = 0
    vibration: int = 0
    camera_motion: int = 0
    noise: int = 0
    atmospheric_preset: str = "Clear"
    platform_profile: str = "Linear"
    platform_speed: float = 0.0

    # Legacy fields (kept None for compatibility)
    acquisition_time_s: float | None = None
    reacquisition_time_s: float | None = None
    searching_time_s: float | None = None
    retention_rate_pct: float | None = None
    detection_rate_pct: float | None = None
    center_hit_rate_pct: float | None = None
    target_loss_rate_pct: float | None = None
    avg_track_err_px: float | None = None
    avg_track_err_mrad: float | None = None
    reacquisition_count: int = 0
    target_loss_count: int = 0
    target_switch_count: int = 0
    rms_px: float | None = None
    rms_mrad: float | None = None

    # Diagnostics strip (Design.md §29.6) — best-effort link telemetry.
    source_id: str = "—"
    target_id: str = "—"
    link_state: str = "—"
    beacon_state: str = "—"
    frame_id: int = 0

    # Remote-terminal live sections (dashboard LIVE STATE / TERMINALS / COMM STATUS).
    terminal_count: int = 0
    emitting_count: int = 0
    sim_time_s: float = 0.0
    live_terminal: TerminalLiveState | None = None
    terminals: tuple = ()

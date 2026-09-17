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

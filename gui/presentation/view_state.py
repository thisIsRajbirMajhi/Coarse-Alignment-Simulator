# gui/presentation/view_state.py - Presentation models (Qt-free).
from __future__ import annotations

from dataclasses import dataclass


def fmt_time_s(v: float | None) -> str:
    return "—" if v is None else f"{v:.1f} Sec"


def fmt_ms(v: float | None) -> str:
    return "—" if v is None else f"{v:.0f} Ms"


def fmt_pct(v: float | None) -> str:
    return "—" if v is None else f"{v:.0f} %"


def fmt_px_mrad(px: float | None, mrad: float | None) -> str:
    if px is None or mrad is None:
        return "—"
    return f"{px:.0f} PX | {mrad:.2f} MRAD"


@dataclass
class DashboardState:
    jitter_ms: float | None = None
    acquisition_time_s: float | None = None
    reacquisition_time_s: float | None = None  # avg
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
    status: str = "STOPPED"
    duration_s: float = 0.0
    fps: float = 0.0

# common/colors.py - Single source for lock-state colors — hex and BGR — eliminates 4+ duplicates

from __future__ import annotations

LOCK_STATUS_COLORS_HEX: dict[str, str] = {
    "searching": "#64748b",
    "acquired": "#06b6d4",
    "tracking": "#22c55e",
    "locked": "#22c55e",  # alias for tracking
    "lost": "#ef4444",
    "detecting": "#3b82f6",
}

# BGR for OpenCV (B,G,R) — canonical = overlay.constants.LOCK_COLOR_DEFAULTS
# Defined here as single source; overlay/constants.py now re-exports from here for consistency
LOCK_STATUS_COLORS_BGR: dict[str, tuple[int, int, int]] = {
    "searching": (170, 170, 170),  # gray
    "acquired": (90, 220, 220),    # cyan
    "tracking": (90, 220, 90),     # green
    "locked": (90, 220, 90),       # alias
    "lost": (255, 80, 80),         # red (BGR order as stored)
    "detecting": (255, 130, 130),  # blue-ish
}

def lock_color_hex(status: str, default: str = "#64748b") -> str:
    """Return hex color for status (case-insensitive), e.g., 'tracking' → '#22c55e'."""
    return LOCK_STATUS_COLORS_HEX.get(status.lower(), default)

def lock_color_bgr(status: str, default: tuple[int, int, int] = (170, 170, 170)) -> tuple[int, int, int]:
    """Return BGR tuple for status (for cv2), e.g., 'tracking' → (90,220,90)."""
    return LOCK_STATUS_COLORS_BGR.get(status.lower(), default)  # type: ignore

# Re-export for convenience
__all__ = ["LOCK_STATUS_COLORS_HEX", "LOCK_STATUS_COLORS_BGR", "lock_color_hex", "lock_color_bgr"]
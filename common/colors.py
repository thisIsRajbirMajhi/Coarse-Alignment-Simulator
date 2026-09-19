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

def _hex_to_bgr(hex_color: str) -> tuple[int, int, int]:
    """Convert '#RRGGBB' to OpenCV (B, G, R)."""
    h = hex_color.lstrip("#")
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return (b, g, r)


# BGR for OpenCV (B,G,R) — derived from HEX above so both stay in sync
LOCK_STATUS_COLORS_BGR: dict[str, tuple[int, int, int]] = {
    key: _hex_to_bgr(value) for key, value in LOCK_STATUS_COLORS_HEX.items()
}

def lock_color_hex(status: str | None, default: str = "#64748b") -> str:
    """Return hex color for status (case-insensitive), e.g., 'tracking' → '#22c55e'."""
    if not isinstance(status, str) or not status:
        return default
    return LOCK_STATUS_COLORS_HEX.get(status.lower(), default)


def lock_color_bgr(status: str | None, default: tuple[int, int, int] = (170, 170, 170)) -> tuple[int, int, int]:
    """Return BGR tuple for status (for cv2), e.g., 'tracking' → (90,220,90)."""
    if not isinstance(status, str) or not status:
        return default
    return LOCK_STATUS_COLORS_BGR.get(status.lower(), default)  # type: ignore

# Re-export for convenience
__all__ = ["LOCK_STATUS_COLORS_HEX", "LOCK_STATUS_COLORS_BGR", "lock_color_hex", "lock_color_bgr"]
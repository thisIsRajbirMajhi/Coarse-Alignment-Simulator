# gui/theme.py - Design tokens + application stylesheet (Plans/Design.md §1).
from __future__ import annotations

# --- Design tokens (single source) -------------------------------------------
BG_APP = "#0B0F14"
BG_SURFACE = "#111720"
BG_ELEVATED = "#151C26"
BORDER = "#283341"
TEXT_PRIMARY = "#E8EDF3"
TEXT_SECONDARY = "#8F9CAB"
TEXT_MUTED = "#647182"
ACCENT = "#61D6FF"
ACCENT_STRONG = "#2BB9EA"
SUCCESS = "#57D38C"
WARNING = "#F2B84B"
DANGER = "#F06D7A"
DISABLED = "#3B4653"

APP_STYLE_FALLBACK: str = ""


def apply_theme(widget) -> str:
    """Apply the application stylesheet to a top-level widget.

    Single fixed theme (no light/dark toggle). Returns "default".
    """
    try:
        from gui.styles import APP_STYLE
    except Exception:
        APP_STYLE = APP_STYLE_FALLBACK
    try:
        widget.setStyleSheet(APP_STYLE)
    except Exception:
        pass
    return "default"


__all__ = [
    "BG_APP", "BG_SURFACE", "BG_ELEVATED", "BORDER", "TEXT_PRIMARY",
    "TEXT_SECONDARY", "TEXT_MUTED", "ACCENT", "ACCENT_STRONG", "SUCCESS",
    "WARNING", "DANGER", "DISABLED", "apply_theme",
]

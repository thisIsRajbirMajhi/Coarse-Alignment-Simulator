# gui/theme.py - Design tokens + dark console theme (Plans/Design.md §1).
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

THEME_LIGHT = "light"
THEME_DARK = "dark"
_SETTINGS_KEY = "ui/theme"

DARK_STYLE: str = f"""
/* ---------- Global ---------- */
* {{
    font-family: 'Segoe UI', Inter, Roboto, 'Helvetica Neue', Arial, sans-serif;
}}
QMainWindow, QDialog {{
    background: {BG_APP};
}}
QWidget {{
    color: {TEXT_PRIMARY};
    selection-background-color: #1E3A4C;
    selection-color: {TEXT_PRIMARY};
}}
QToolTip {{
    background: {BG_ELEVATED};
    color: {TEXT_PRIMARY};
    border: 1px solid {BORDER};
    border-radius: 4px;
    padding: 5px 7px;
    font-size: 11px;
}}

/* ---------- Header / nav ---------- */
QWidget#headerBar {{
    background: {BG_SURFACE};
    border: 1px solid {BORDER};
    border-radius: 8px;
}}
QLabel#appTitle {{
    color: {TEXT_PRIMARY};
    font-size: 20px;
    font-weight: 700;
}}
QLabel#liveDot {{
    font-size: 12px;
    font-weight: 700;
}}

/* ---------- Cards / GroupBox ---------- */
QGroupBox {{
    background: {BG_SURFACE};
    border: 1px solid {BORDER};
    border-radius: 8px;
    margin-top: 14px;
    padding-top: 14px;
    color: {TEXT_PRIMARY};
    font-weight: 650;
    font-size: 14px;
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    subcontrol-position: top left;
    left: 12px;
    top: 0px;
    padding: 2px 10px;
    color: {TEXT_SECONDARY};
    font-size: 11px;
    font-weight: 650;
    background: {BG_ELEVATED};
    border: 1px solid {BORDER};
    border-radius: 4px;
}}
QGroupBox:disabled {{
    color: {TEXT_MUTED};
    border-color: {DISABLED};
}}
QFrame[card="true"] {{
    background: {BG_SURFACE};
    border: 1px solid {BORDER};
    border-radius: 8px;
}}
QFrame#dashboardCard {{
    background: {BG_SURFACE};
    border: 1px solid {BORDER};
    border-radius: 8px;
}}
QLabel {{
    color: {TEXT_SECONDARY};
    font-size: 12px;
    background: transparent;
}}
QLabel#metricLabel {{
    color: {TEXT_MUTED};
    font-size: 11px;
}}

/* ---------- Buttons ---------- */
QPushButton {{
    background: {BG_ELEVATED};
    border: 1px solid {BORDER};
    border-radius: 6px;
    padding: 6px 14px;
    color: {TEXT_PRIMARY};
    font-size: 12px;
    min-height: 22px;
}}
QPushButton:hover {{
    border-color: {ACCENT};
}}
QPushButton:pressed {{
    background: #0E141B;
}}
QPushButton:disabled {{
    color: {TEXT_MUTED};
    background: {BG_SURFACE};
    border-color: {DISABLED};
}}
QPushButton#startButton {{
    background: #0F2E1F;
    border: 1px solid {SUCCESS};
    color: {SUCCESS};
    font-weight: 700;
}}
QPushButton#stopButton {{
    background: #331418;
    border: 1px solid {DANGER};
    color: {DANGER};
    font-weight: 700;
}}
QPushButton#resetButton {{
    border: 1px solid {DANGER};
    color: {DANGER};
}}
QPushButton#randomizeAllButton {{
    background: #0E2A3A;
    border: 1px solid {ACCENT_STRONG};
    color: {ACCENT};
    font-weight: 700;
}}
QPushButton[chip="true"] {{
    border-radius: 10px;
    padding: 4px 12px;
    font-weight: 600;
}}
QPushButton[chip="true"][active="true"] {{
    background: #0E2A3A;
    border: 1px solid {ACCENT};
    color: {ACCENT};
}}

/* ---------- Sliders (4px track, 14px thumb) ---------- */
QSlider::groove:horizontal {{
    height: 4px;
    background: {DISABLED};
    border-radius: 2px;
}}
QSlider::sub-page:horizontal {{
    height: 4px;
    background: {ACCENT_STRONG};
    border-radius: 2px;
}}
QSlider::handle:horizontal {{
    width: 14px;
    height: 14px;
    margin: -5px 0;
    border-radius: 7px;
    background: {ACCENT};
    border: 1px solid #0B0F14;
}}
QSlider::handle:horizontal:hover {{
    background: #8FE3FF;
}}
QSlider::handle:horizontal:disabled {{
    background: {DISABLED};
}}
QSlider:focus {{
    border: none;
}}

/* ---------- Checkboxes / toggles ---------- */
QCheckBox {{
    color: {TEXT_SECONDARY};
    font-size: 12px;
    spacing: 8px;
}}
QCheckBox::indicator {{
    width: 15px;
    height: 15px;
    border-radius: 3px;
    border: 1px solid {BORDER};
    background: {BG_ELEVATED};
}}
QCheckBox::indicator:checked {{
    background: {ACCENT_STRONG};
    border: 1px solid {ACCENT};
}}
QCheckBox[toggle="true"]::indicator {{
    width: 34px;
    height: 18px;
    border-radius: 9px;
    border: 1px solid {BORDER};
    background: {DISABLED};
}}
QCheckBox[toggle="true"]::indicator:checked {{
    background: #0E2A3A;
    border: 1px solid {ACCENT};
}}
QCheckBox:disabled {{
    color: {TEXT_MUTED};
}}

/* ---------- Combos / edits / spins ---------- */
QComboBox {{
    background: {BG_ELEVATED};
    border: 1px solid {BORDER};
    border-radius: 6px;
    padding: 4px 8px;
    color: {TEXT_PRIMARY};
    min-height: 22px;
}}
QComboBox:hover {{
    border-color: {ACCENT};
}}
QComboBox QAbstractItemView {{
    background: {BG_ELEVATED};
    color: {TEXT_PRIMARY};
    selection-background-color: #1E3A4C;
    border: 1px solid {BORDER};
}}
QLineEdit, QSpinBox, QDoubleSpinBox {{
    background: #0B0F14;
    border: 1px solid {BORDER};
    border-radius: 6px;
    padding: 4px 8px;
    color: {TEXT_PRIMARY};
    selection-background-color: #1E3A4C;
    font-family: 'JetBrains Mono', 'SFMono-Regular', Consolas, monospace;
}}
QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus {{
    border: 1px solid {ACCENT};
}}
QLineEdit:disabled, QSpinBox:disabled, QDoubleSpinBox:disabled {{
    color: {TEXT_MUTED};
    background: {BG_SURFACE};
}}

/* ---------- Tabs (segmented nav) ---------- */
QTabWidget::pane {{
    border: 1px solid {BORDER};
    border-radius: 8px;
    background: {BG_APP};
    top: -1px;
}}
QTabBar::tab {{
    background: {BG_SURFACE};
    color: {TEXT_SECONDARY};
    border: 1px solid {BORDER};
    border-bottom: none;
    border-top-left-radius: 6px;
    border-top-right-radius: 6px;
    padding: 8px 18px;
    margin-right: 4px;
    font-size: 12px;
    min-height: 44px;
}}
QTabBar::tab:selected {{
    background: {BG_ELEVATED};
    color: {ACCENT};
    border-bottom: 2px solid {ACCENT};
}}
QTabBar::tab:!selected {{
    margin-top: 4px;
}}

/* ---------- Scroll / splitter / status ---------- */
QScrollArea {{
    border: none;
    background: transparent;
}}
QScrollBar:vertical {{
    background: transparent;
    width: 10px;
}}
QScrollBar::handle:vertical {{
    background: {DISABLED};
    border-radius: 5px;
    min-height: 30px;
}}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
    height: 0px;
}}
QScrollBar:horizontal {{
    background: transparent;
    height: 10px;
}}
QScrollBar::handle:horizontal {{
    background: {DISABLED};
    border-radius: 5px;
    min-width: 30px;
}}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
    width: 0px;
}}
QSplitter::handle {{
    background: {BORDER};
}}
QStatusBar {{
    background: {BG_SURFACE};
    color: {TEXT_SECONDARY};
    border-top: 1px solid {BORDER};
    font-size: 11px;
}}
QStatusBar::item {{
    border: none;
}}
QMenu {{
    background: {BG_ELEVATED};
    color: {TEXT_PRIMARY};
    border: 1px solid {BORDER};
}}
QMenu::item:selected {{
    background: #1E3A4C;
}}
QLabel#footerHint {{
    color: {TEXT_MUTED};
    font-size: 10px;
    font-style: italic;
}}
"""


def current_theme() -> str:
    """Persisted theme name (light default until dark acceptance)."""
    try:
        from PyQt5.QtCore import QSettings
        return str(QSettings("CoarseAlignmentSim", "ControlDeck").value(_SETTINGS_KEY, THEME_LIGHT))
    except Exception:
        return THEME_LIGHT


def set_theme(name: str) -> None:
    try:
        from PyQt5.QtCore import QSettings
        QSettings("CoarseAlignmentSim", "ControlDeck").setValue(_SETTINGS_KEY, name)
    except Exception:
        pass


def stylesheet_for(name: str) -> str:
    if name == THEME_DARK:
        return DARK_STYLE
    from gui.styles import APP_STYLE
    return APP_STYLE


def apply_theme(widget) -> str:
    """Apply the persisted theme stylesheet to a top-level widget.

    Returns the theme name applied (Design.md side-by-side: light default
    until dark acceptance; toggle persists via QSettings).
    """
    name = current_theme()
    try:
        widget.setStyleSheet(stylesheet_for(name))
    except Exception:
        pass
    return name


def toggle_theme() -> str:
    """Flip light<->dark, persist, return the new theme name."""
    name = THEME_DARK if current_theme() != THEME_DARK else THEME_LIGHT
    set_theme(name)
    return name


__all__ = [
    "BG_APP", "BG_SURFACE", "BG_ELEVATED", "BORDER", "TEXT_PRIMARY",
    "TEXT_SECONDARY", "TEXT_MUTED", "ACCENT", "ACCENT_STRONG", "SUCCESS",
    "WARNING", "DANGER", "DISABLED", "THEME_LIGHT", "THEME_DARK",
    "DARK_STYLE", "current_theme", "set_theme", "stylesheet_for", "apply_theme",
    "toggle_theme",
]

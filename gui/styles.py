"""
Module: gui.styles
Purpose: Centralized styling and layout constants for the FSOC Simulator GUI.
Public API: APP_STYLE, SCENE_SIZE, FOV_SIZE, TICK_MS
Notes: Extracted from gui.app monolith for modularity — single source for theme.
"""

# ============================================================
# SECTION: Layout Constants
# ============================================================

# Default world / camera geometry (px) — overridden by Environment/Camera panels at runtime.
SCENE_SIZE: tuple[int, int] = (1000, 1000)
FOV_SIZE: tuple[int, int] = (250, 250)

# Tick interval (ms) — QTimer driving simulation loop (~30 FPS).
TICK_MS: int = 33

# ============================================================
# SECTION: Application Stylesheet
# ============================================================

# Premium light theme — shared by MainWindow and ControlDashboardWindow.
# Sleek and intuitive aesthetic.
APP_STYLE: str = """
* {
    font-family: 'Segoe UI', Inter, Roboto, sans-serif;
}
QMainWindow { background: #f8fafc; }
QWidget { color: #0f172a; }
QGroupBox { 
    background: #ffffff; 
    border: 1px solid #e2e8f0; 
    border-radius: 8px; 
    margin-top: 18px; 
    padding-top: 16px;
    color: #0f172a;
    font-weight: 600;
}
QGroupBox::title { 
    subcontrol-origin: margin; 
    subcontrol-position: top left;
    left: 12px; 
    top: 0px;
    padding: 2px 8px; 
    color: #2563eb;
    font-size: 12px;
    font-weight: 700;
    background: #ffffff;
    border-radius: 4px;
    border: 1px solid #e2e8f0;
}
QLabel { color: #475569; font-size: 12px; background: transparent; }
QPushButton { 
    background: #ffffff; 
    border: 1px solid #cbd5e1; 
    border-radius: 6px; 
    padding: 8px 16px; 
    color: #0f172a; 
    font-weight: 600;
}
QPushButton:hover { background: #f1f5f9; border-color: #94a3b8; }
QPushButton:pressed { background: #e2e8f0; }
QComboBox, QSpinBox, QDoubleSpinBox {
    background: #ffffff;
    border: 1px solid #cbd5e1;
    border-radius: 6px;
    padding: 6px 10px;
    color: #0f172a;
    min-height: 22px;
}
QComboBox:hover, QSpinBox:hover, QDoubleSpinBox:hover {
    border: 1px solid #94a3b8;
}
QComboBox::drop-down, QSpinBox::up-button, QSpinBox::down-button, QDoubleSpinBox::up-button, QDoubleSpinBox::down-button {
    width: 20px; border: none; background: transparent;
}
QComboBox QAbstractItemView {
    background: #ffffff;
    border: 1px solid #cbd5e1;
    selection-background-color: #3b82f6;
    color: #0f172a;
    border-radius: 6px;
    outline: none;
}
QSlider::groove:horizontal { background: #e2e8f0; height: 6px; border-radius: 3px; }
QSlider::handle:horizontal { background: #3b82f6; width: 16px; height: 16px; margin: -5px 0; border-radius: 8px; border: 2px solid #ffffff; }
QSlider::handle:horizontal:hover { background: #2563eb; }
QSlider::sub-page:horizontal { background: #60a5fa; border-radius: 3px; }
QScrollArea { border: none; background: transparent; }
QScrollArea > QWidget > QWidget { background: transparent; }
QSplitter::handle { background: #e2e8f0; }
QSplitter::handle:horizontal { width: 4px; }
QSplitter::handle:vertical { height: 4px; }
QStatusBar { background: #ffffff; color: #64748b; border-top: 1px solid #e2e8f0; font-size: 11px; }
QCheckBox { color: #475569; spacing: 8px; font-size: 12px; background: transparent; }
QCheckBox::indicator { width: 16px; height: 16px; border: 1px solid #cbd5e1; border-radius: 4px; background: #ffffff; }
QCheckBox::indicator:hover { border-color: #94a3b8; }
QCheckBox::indicator:checked { background: #3b82f6; border-color: #3b82f6; }
QTabWidget::pane { border: 1px solid #e2e8f0; border-radius: 8px; background: #ffffff; top: -1px; }
QTabBar::tab { background: #f8fafc; border: 1px solid #e2e8f0; padding: 8px 16px; margin-right: 2px; border-top-left-radius: 6px; border-top-right-radius: 6px; color: #64748b; font-weight: 600; }
QTabBar::tab:hover { background: #f1f5f9; color: #0f172a; }
QTabBar::tab:selected { background: #ffffff; border-bottom: 1px solid #ffffff; color: #2563eb; }
QDockWidget {
    color: #0f172a;
    font-weight: 700;
}
QDockWidget::title {
    background: #ffffff;
    border-bottom: 1px solid #e2e8f0;
    text-align: left;
    padding: 8px 12px;
}
"""

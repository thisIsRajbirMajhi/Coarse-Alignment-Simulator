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

# Dark-light modern theme — shared by MainWindow and ControlDashboardWindow.
# Keeps visual consistency when panels are reparented to separate window.
APP_STYLE: str = """
QMainWindow { background: #f8fafc; }
QGroupBox { 
    background: #ffffff; 
    border: 1px solid #e2e8f0; 
    border-radius: 10px; 
    margin-top: 14px; 
    padding-top: 16px;
    color: #0f172a;
    font-weight: 600;
}
QGroupBox::title { 
    subcontrol-origin: margin; 
    left: 12px; 
    padding: 0 8px; 
    color: #2563eb;
    font-size: 11px;
    font-weight: 700;
    background: #ffffff;
}
QLabel { color: #334155; font-size: 11px; }
QPushButton { 
    background: #ffffff; 
    border: 1px solid #cbd5e1; 
    border-radius: 8px; 
    padding: 8px 14px; 
    color: #0f172a; 
}
QPushButton:hover { background: #f1f5f9; border-color: #94a3b8; }
QPushButton:pressed { background: #e2e8f0; }
QComboBox, QSpinBox, QDoubleSpinBox {
    background: #ffffff;
    border: 1px solid #cbd5e1;
    border-radius: 6px;
    padding: 4px 8px;
    color: #0f172a;
    min-height: 22px;
}
QComboBox::drop-down, QSpinBox::up-button, QSpinBox::down-button, QDoubleSpinBox::up-button, QDoubleSpinBox::down-button {
    width: 18px; border: none;
}
QSlider::groove:horizontal { background: #e2e8f0; height: 6px; border-radius: 3px; }
QSlider::handle:horizontal { background: #2563eb; width: 14px; height: 14px; margin: -4px 0; border-radius: 7px; border: 2px solid white; }
QSlider::sub-page:horizontal { background: #3b82f6; border-radius: 3px; }
QScrollArea { border: none; background: transparent; }
QSplitter::handle { background: #e2e8f0; }
QSplitter::handle:horizontal { width: 6px; }
QSplitter::handle:vertical { height: 6px; }
QStatusBar { background: #ffffff; color: #64748b; border-top: 1px solid #e2e8f0; }
QCheckBox { color: #334155; spacing: 6px; }
QCheckBox::indicator { width: 14px; height: 14px; border: 1px solid #cbd5e1; border-radius: 3px; background: white; }
QCheckBox::indicator:checked { background: #2563eb; border-color: #2563eb; }
QTabWidget::pane { border: 1px solid #e2e8f0; border-radius: 8px; background: white; }
QTabBar::tab { background: #f1f5f9; border: 1px solid #e2e8f0; padding: 6px 12px; margin-right: 2px; border-top-left-radius: 6px; border-top-right-radius: 6px; }
QTabBar::tab:selected { background: white; border-bottom: 1px solid white; color: #2563eb; font-weight: 700; }
"""

# gui/styles.py - Centralized styling and layout constants for the FSOC Simulator GUI

# Default world / camera geometry (px) — overridden by Environment/Camera panels at runtime.
SCENE_SIZE: tuple[int, int] = (1000, 1000)
FOV_SIZE: tuple[int, int] = (250, 250)

# Tick interval (ms) — QTimer driving simulation loop (~30 FPS).
TICK_MS: int = 33

# Design tokens:
#   App bg #f1f5f9  |  Card #ffffff  |  Dark stage #0f172a / #020617
#   Accent #2563eb  |  Cyan #06b6d4  |  Emerald #10b981 | Slate #64748b
#   Border #e2e8f0  |  Border-dark #1e293b  |  Radius 12px cards, 8px controls
#
# Philosophy:
#   - Video stage: deep navy/black, telemetry headers, pill badges, subtle inner glow
#   - Control deck: elevated white cards, soft shadow simulated via border, 8-12px radius
#   - Tabs: pill-segmented (selected = blue solid), hover = slate tint
#   - Sliders/Spins: chunky handles, blue fill, crisp focus
#   - Scrollbars: slim, rounded, dark track on video, light on deck

APP_STYLE: str = """
/* ---------- Global ---------- */
* {
    font-family: 'Segoe UI', Inter, Roboto, 'Helvetica Neue', Arial, sans-serif;
}
QMainWindow {
    background: #f1f5f9;
}
QWidget {
    color: #0f172a;
    selection-background-color: #2563eb;
    selection-color: #ffffff;
}
QToolTip {
    background: #0f172a;
    color: #f1f5f9;
    border: 1px solid #334155;
    border-radius: 6px;
    padding: 6px 8px;
    font-size: 11px;
}

/* ---------- Cards / GroupBox ---------- */
QGroupBox {
    background: #ffffff;
    border: 1px solid #e2e8f0;
    border-radius: 12px;
    margin-top: 18px;
    padding-top: 18px;
    color: #0f172a;
    font-weight: 600;
}
QGroupBox::title {
    subcontrol-origin: margin;
    subcontrol-position: top left;
    left: 14px;
    top: 0px;
    padding: 3px 10px;
    color: #1e40af;
    font-size: 11px;
    font-weight: 800;
    letter-spacing: 0.4px;
    background: #eff6ff;
    border: 1px solid #dbeafe;
    border-radius: 6px;
}
QGroupBox:disabled {
    background: #f8fafc;
    border-color: #e2e8f0;
}
QLabel {
    color: #475569;
    font-size: 12px;
    background: transparent;
}
QLabel[hint="true"] {
    color: #64748b;
    font-size: 10px;
    font-style: italic;
}

/* ---------- Buttons ---------- */
QPushButton {
    background: #ffffff;
    border: 1px solid #cbd5e1;
    border-radius: 8px;
    padding: 7px 14px;
    color: #0f172a;
    font-weight: 600;
    font-size: 11px;
}
QPushButton:hover {
    background: #f8fafc;
    border-color: #94a3b8;
}
QPushButton:pressed {
    background: #e2e8f0;
}
QPushButton:disabled {
    background: #f1f5f9;
    color: #94a3b8;
    border-color: #e2e8f0;
}
QPushButton[primary="true"] {
    background: qlineargradient(x1:0,y1:0,x2:1,y2:0, stop:0 #2563eb, stop:1 #1d4ed8);
    color: #ffffff;
    border: none;
    font-weight: 700;
}
QPushButton[primary="true"]:hover {
    background: qlineargradient(x1:0,y1:0,x2:1,y2:0, stop:0 #1d4ed8, stop:1 #1e40af);
}
QPushButton[accent="cyan"] {
    background: #06b6d4;
    color: #ffffff;
    border: none;
    font-weight: 700;
}
QPushButton[accent="emerald"] {
    background: #10b981;
    color: #ffffff;
    border: none;
    font-weight: 700;
}
QPushButton[accent="amber"] {
    background: #f59e0b;
    color: #ffffff;
    border: none;
    font-weight: 700;
}

/* ---------- Inputs ---------- */
QComboBox, QSpinBox, QDoubleSpinBox {
    background: #ffffff;
    border: 1px solid #cbd5e1;
    border-radius: 8px;
    padding: 5px 10px;
    color: #0f172a;
    min-height: 22px;
    font-size: 11px;
    selection-background-color: #2563eb;
}
QComboBox:hover, QSpinBox:hover, QDoubleSpinBox:hover {
    border: 1px solid #94a3b8;
    background: #f8fafc;
}
QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus {
    border: 1px solid #2563eb;
    background: #ffffff;
}
QComboBox:disabled, QSpinBox:disabled, QDoubleSpinBox:disabled {
    background: #f1f5f9;
    color: #94a3b8;
    border-color: #e2e8f0;
}
QComboBox::drop-down, QSpinBox::up-button, QSpinBox::down-button, QDoubleSpinBox::up-button, QDoubleSpinBox::down-button {
    width: 22px;
    border: none;
    background: transparent;
    subcontrol-origin: padding;
}
QComboBox::down-arrow {
    image: none;
    border-left: 4px solid transparent;
    border-right: 4px solid transparent;
    border-top: 5px solid #64748b;
    width: 0px; height: 0px;
    margin-right: 6px;
}
QSpinBox::up-arrow, QDoubleSpinBox::up-arrow {
    border-left: 4px solid transparent;
    border-right: 4px solid transparent;
    border-bottom: 5px solid #64748b;
    width: 0px; height: 0px;
}
QSpinBox::down-arrow, QDoubleSpinBox::down-arrow {
    border-left: 4px solid transparent;
    border-right: 4px solid transparent;
    border-top: 5px solid #64748b;
    width: 0px; height: 0px;
}
QComboBox QAbstractItemView {
    background: #ffffff;
    border: 1px solid #cbd5e1;
    selection-background-color: #2563eb;
    color: #0f172a;
    border-radius: 8px;
    outline: none;
    padding: 4px;
}
QComboBox QAbstractItemView::item {
    padding: 6px 10px;
    border-radius: 4px;
}
QComboBox QAbstractItemView::item:selected {
    background: #eff6ff;
    color: #1e40af;
}

/* ---------- Sliders ---------- */
QSlider::groove:horizontal {
    background: #e2e8f0;
    height: 6px;
    border-radius: 3px;
}
QSlider::sub-page:horizontal {
    background: qlineargradient(x1:0,y1:0,x2:1,y2:0, stop:0 #3b82f6, stop:1 #06b6d4);
    border-radius: 3px;
}
QSlider::handle:horizontal {
    background: #ffffff;
    width: 18px;
    height: 18px;
    margin: -6px 0;
    border-radius: 9px;
    border: 2px solid #2563eb;
}
QSlider::handle:horizontal:hover {
    background: #eff6ff;
    border: 2px solid #1d4ed8;
}
QSlider::handle:horizontal:pressed {
    background: #2563eb;
    border-color: #ffffff;
}
QSlider::groove:vertical {
    background: #e2e8f0;
    width: 6px;
    border-radius: 3px;
}
QSlider::add-page:vertical { background: #e2e8f0; border-radius: 3px; }
QSlider::sub-page:vertical { background: #3b82f6; border-radius: 3px; }

/* ---------- CheckBox ---------- */
QCheckBox {
    color: #334155;
    spacing: 8px;
    font-size: 11px;
    font-weight: 500;
    background: transparent;
}
QCheckBox::indicator {
    width: 18px;
    height: 18px;
    border: 1.5px solid #cbd5e1;
    border-radius: 5px;
    background: #ffffff;
}
QCheckBox::indicator:hover {
    border-color: #94a3b8;
    background: #f8fafc;
}
QCheckBox::indicator:checked {
    background: qlineargradient(x1:0,y1:0,x2:1,y2:1, stop:0 #2563eb, stop:1 #06b6d4);
    border-color: #2563eb;
    image: none;
}
QCheckBox:disabled {
    color: #94a3b8;
}

/* ---------- Tab Widget — Pill Segmented ---------- */
QTabWidget::pane {
    border: 1px solid #e2e8f0;
    border-radius: 12px;
    background: #ffffff;
    top: -1px;
}
QTabBar::tab {
    background: #f1f5f9;
    border: 1px solid #e2e8f0;
    padding: 8px 14px;
    margin-right: 4px;
    border-top-left-radius: 8px;
    border-top-right-radius: 8px;
    border-bottom: 1px solid #e2e8f0;
    color: #64748b;
    font-weight: 700;
    font-size: 11px;
    letter-spacing: 0.2px;
}
QTabBar::tab:hover:!selected {
    background: #e2e8f0;
    color: #334155;
    border-color: #cbd5e1;
}
QTabBar::tab:selected {
    background: #ffffff;
    color: #2563eb;
    border: 1px solid #e2e8f0;
    border-bottom: 1px solid #ffffff;
    margin-bottom: -1px;
}
QTabBar::tab:disabled {
    color: #94a3b8;
    background: #f8fafc;
}

/* ---------- Scroll Areas & Splitters ---------- */
QScrollArea {
    border: none;
    background: transparent;
}
QScrollArea > QWidget > QWidget {
    background: transparent;
}
QSplitter::handle {
    background: #e2e8f0;
    border-radius: 2px;
}
QSplitter::handle:horizontal {
    width: 6px;
    margin: 0 2px;
}
QSplitter::handle:vertical {
    height: 6px;
    margin: 2px 0;
}
QSplitter::handle:hover {
    background: #cbd5e1;
}
QScrollBar:vertical {
    background: #f1f5f9;
    width: 8px;
    border-radius: 4px;
    margin: 2px;
}
QScrollBar::handle:vertical {
    background: #cbd5e1;
    border-radius: 4px;
    min-height: 24px;
}
QScrollBar::handle:vertical:hover {
    background: #94a3b8;
}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical,
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {
    height: 0px;
    background: transparent;
}
QScrollBar:horizontal {
    background: #f1f5f9;
    height: 8px;
    border-radius: 4px;
    margin: 2px;
}
QScrollBar::handle:horizontal {
    background: #cbd5e1;
    border-radius: 4px;
    min-width: 24px;
}
QScrollBar::handle:horizontal:hover {
    background: #94a3b8;
}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal,
QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {
    width: 0px;
    background: transparent;
}

/* ---------- Status Bar ---------- */
QStatusBar {
    background: #ffffff;
    color: #64748b;
    border-top: 1px solid #e2e8f0;
    font-size: 11px;
    padding: 2px 8px;
}
QStatusBar::item { border: none; }

/* ---------- ToolBar ---------- */
QToolBar {
    background: #ffffff;
    border-bottom: 1px solid #e2e8f0;
    spacing: 6px;
    padding: 4px 8px;
}
QToolBar QToolButton {
    background: #f8fafc;
    border: 1px solid #e2e8f0;
    border-radius: 6px;
    padding: 5px 10px;
    color: #334155;
    font-weight: 600;
    font-size: 11px;
}
QToolBar QToolButton:hover {
    background: #eff6ff;
    border-color: #93c5fd;
    color: #1e40af;
}
QToolBar QToolButton:pressed {
    background: #dbeafe;
}

/* ============================================================
   CAMERA STAGE — Dark mission-control video cards
   ============================================================ */
QFrame#cameraCard {
    background: #0f172a;
    border: 1px solid #1e293b;
    border-radius: 14px;
}
QFrame#cameraCardHeader {
    background: qlineargradient(x1:0,y1:0,x2:1,y2:0, stop:0 #0f172a, stop:1 #1e293b);
    border: none;
    border-top-left-radius: 14px;
    border-top-right-radius: 14px;
    border-bottom: 1px solid #1e293b;
}
QFrame#cameraCardHeader QLabel {
    color: #e2e8f0;
}
QLabel#cameraTitle {
    color: #f8fafc;
    font-weight: 800;
    font-size: 11px;
    letter-spacing: 0.8px;
}
QLabel#cameraIcon {
    color: #38bdf8;
    font-size: 13px;
    background: #1e293b;
    border: 1px solid #334155;
    border-radius: 6px;
    padding: 3px 6px;
}
QLabel#liveBadge {
    background: #dc2626;
    color: #ffffff;
    font-weight: 800;
    font-size: 9px;
    letter-spacing: 0.6px;
    border-radius: 4px;
    padding: 3px 7px;
}
QLabel#liveBadge[active="false"] {
    background: #334155;
    color: #94a3b8;
}
QLabel#resBadge {
    background: #1e293b;
    color: #38bdf8;
    font-weight: 700;
    font-size: 10px;
    border: 1px solid #334155;
    border-radius: 6px;
    padding: 3px 8px;
    font-family: 'Consolas', 'Courier New', monospace;
}
QLabel#videoFeed {
    background: #020617;
    border: 1px solid #1e293b;
    border-radius: 10px;
}
QFrame#cameraCardFooter {
    background: #0f172a;
    border: none;
    border-top: 1px solid #1e293b;
    border-bottom-left-radius: 14px;
    border-bottom-right-radius: 14px;
}
QFrame#cameraCardFooter QLabel {
    color: #94a3b8;
    font-size: 10px;
    font-family: 'Consolas', 'Courier New', monospace;
}
QFrame#telemetryStrip {
    background: #ffffff;
    border: 1px solid #e2e8f0;
    border-radius: 10px;
}
QFrame#telemetryStrip QLabel {
    color: #475569;
    font-size: 11px;
}
QLabel#telemetryValue {
    background: #f8fafc;
    border: 1px solid #e2e8f0;
    border-radius: 6px;
    padding: 3px 8px;
    font-weight: 700;
    color: #0f172a;
    font-family: 'Consolas', 'Courier New', monospace;
    font-size: 11px;
}
QLabel#telemetryLabel {
    color: #64748b;
    font-size: 10px;
    font-weight: 600;
    letter-spacing: 0.3px;
}
QFrame#appHeader {
    background: qlineargradient(x1:0,y1:0,x2:1,y2:0, stop:0 #0f172a, stop:1 #1e3a8a);
    border: 1px solid #1e293b;
    border-radius: 12px;
}
QFrame#appHeader QLabel {
    color: #e2e8f0;
}
QLabel#appTitle {
    color: #f8fafc;
    font-weight: 900;
    font-size: 13px;
    letter-spacing: 1px;
}
QLabel#appSubtitle {
    color: #93c5fd;
    font-size: 10px;
    font-weight: 600;
    letter-spacing: 0.5px;
}
QLabel#headerBadge {
    background: rgba(255,255,255,0.12);
    color: #e0f2fe;
    border: 1px solid rgba(255,255,255,0.16);
    border-radius: 6px;
    padding: 4px 8px;
    font-weight: 700;
    font-size: 10px;
    font-family: 'Consolas', 'Courier New', monospace;
}
QFrame#controlHeader {
    background: qlineargradient(x1:0,y1:0,x2:1,y2:0, stop:0 #ffffff, stop:1 #f8fafc);
    border: 1px solid #e2e8f0;
    border-radius: 12px;
}
QLabel#controlTitle {
    color: #0f172a;
    font-weight: 900;
    font-size: 13px;
    letter-spacing: 0.6px;
}
QLabel#controlSubtitle {
    color: #64748b;
    font-size: 10px;
    font-weight: 500;
}
QLabel#hotBadge {
    background: #eff6ff;
    color: #2563eb;
    border: 1px solid #dbeafe;
    border-radius: 6px;
    padding: 3px 8px;
    font-weight: 800;
    font-size: 9px;
    letter-spacing: 0.5px;
}
QFrame#controlHeader QPushButton {
    background: #0f172a;
    color: #ffffff;
    border: none;
    border-radius: 6px;
    padding: 5px 10px;
    font-weight: 700;
    font-size: 10px;
}

/* ---------- Dashboard specifics ---------- */
QFrame#dashboardCard {
    background: #ffffff;
    border: 1px solid #e2e8f0;
    border-radius: 12px;
}

/* ---------- Beacon panel polish handled via dynamic stylesheet in code ---------- */
"""
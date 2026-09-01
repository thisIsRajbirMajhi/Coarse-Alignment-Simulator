# gui/styles.py - Centralized styling — simple light theme, no gradients, no vibe colors
# Video feeds are pitch black; everything else is light/neutral.

SCENE_SIZE: tuple[int, int] = (5000, 5000)
FOV_SIZE: tuple[int, int] = (640, 640)
TICK_MS: int = 33

APP_STYLE: str = """
/* ---------- Global ---------- */
* {
    font-family: 'Segoe UI', Inter, Roboto, 'Helvetica Neue', Arial, sans-serif;
}
QMainWindow {
    background: #f9fafb;
}
QWidget {
    color: #111827;
    selection-background-color: #e5e7eb;
    selection-color: #111827;
}
QToolTip {
    background: #ffffff;
    color: #111827;
    border: 1px solid #d1d5db;
    border-radius: 4px;
    padding: 5px 7px;
    font-size: 11px;
}

/* ---------- Cards / GroupBox ---------- */
QGroupBox {
    background: #ffffff;
    border: 1px solid #e5e7eb;
    border-radius: 6px;
    margin-top: 14px;
    padding-top: 14px;
    color: #111827;
    font-weight: 600;
    font-size: 11px;
}
QGroupBox::title {
    subcontrol-origin: margin;
    subcontrol-position: top left;
    left: 10px;
    top: 0px;
    padding: 2px 8px;
    color: #374151;
    font-size: 10px;
    font-weight: 600;
    background: #ffffff;
    border: 1px solid #e5e7eb;
    border-radius: 4px;
}
QGroupBox:disabled {
    background: #f9fafb;
    border-color: #e5e7eb;
}
QLabel {
    color: #374151;
    font-size: 11px;
    background: transparent;
}
QLabel[hint="true"] {
    color: #6b7280;
    font-size: 10px;
    font-style: italic;
}

/* ---------- Buttons ---------- */
QPushButton {
    background: #ffffff;
    border: 1px solid #d1d5db;
    border-radius: 6px;
    padding: 6px 12px;
    color: #111827;
    font-weight: 500;
    font-size: 11px;
}
QPushButton:hover {
    background: #f3f4f6;
    border-color: #9ca3af;
}
QPushButton:pressed {
    background: #e5e7eb;
}
QPushButton:disabled {
    background: #f9fafb;
    color: #9ca3af;
    border-color: #e5e7eb;
}
QPushButton[primary="true"] {
    background: #111827;
    color: #ffffff;
    border: 1px solid #111827;
    font-weight: 600;
}
QPushButton[primary="true"]:hover {
    background: #1f2937;
    border-color: #1f2937;
}
QPushButton[primary="true"]:pressed {
    background: #000000;
}

/* ---------- Inputs ---------- */
QComboBox, QSpinBox, QDoubleSpinBox {
    background: #ffffff;
    border: 1px solid #d1d5db;
    border-radius: 6px;
    padding: 4px 8px;
    color: #111827;
    min-height: 22px;
    font-size: 11px;
    selection-background-color: #e5e7eb;
}
QComboBox:hover, QSpinBox:hover, QDoubleSpinBox:hover {
    border-color: #9ca3af;
    background: #ffffff;
}
QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus {
    border: 1px solid #6b7280;
    background: #ffffff;
}
QComboBox:disabled, QSpinBox:disabled, QDoubleSpinBox:disabled {
    background: #f9fafb;
    color: #9ca3af;
    border-color: #e5e7eb;
}
QComboBox::drop-down, QSpinBox::up-button, QSpinBox::down-button, QDoubleSpinBox::up-button, QDoubleSpinBox::down-button {
    width: 20px;
    border: none;
    background: transparent;
    subcontrol-origin: padding;
}
QComboBox::down-arrow {
    image: none;
    border-left: 4px solid transparent;
    border-right: 4px solid transparent;
    border-top: 5px solid #6b7280;
    width: 0px; height: 0px;
    margin-right: 6px;
}
QSpinBox::up-arrow, QDoubleSpinBox::up-arrow {
    border-left: 4px solid transparent;
    border-right: 4px solid transparent;
    border-bottom: 5px solid #6b7280;
    width: 0px; height: 0px;
}
QSpinBox::down-arrow, QDoubleSpinBox::down-arrow {
    border-left: 4px solid transparent;
    border-right: 4px solid transparent;
    border-top: 5px solid #6b7280;
    width: 0px; height: 0px;
}
QComboBox QAbstractItemView {
    background: #ffffff;
    border: 1px solid #d1d5db;
    selection-background-color: #f3f4f6;
    selection-color: #111827;
    color: #111827;
    border-radius: 6px;
    outline: none;
    padding: 4px;
}
QComboBox QAbstractItemView::item {
    padding: 6px 10px;
    border-radius: 4px;
}
QComboBox QAbstractItemView::item:selected {
    background: #f3f4f6;
    color: #111827;
}

/* ---------- Sliders ---------- */
QSlider::groove:horizontal {
    background: #e5e7eb;
    height: 5px;
    border-radius: 2px;
}
QSlider::sub-page:horizontal {
    background: #111827;
    border-radius: 2px;
}
QSlider::handle:horizontal {
    background: #ffffff;
    width: 16px;
    height: 16px;
    margin: -6px 0;
    border-radius: 8px;
    border: 1px solid #9ca3af;
}
QSlider::handle:horizontal:hover {
    background: #f9fafb;
    border: 1px solid #6b7280;
}
QSlider::handle:horizontal:pressed {
    background: #111827;
    border-color: #111827;
}
QSlider::groove:vertical {
    background: #e5e7eb;
    width: 5px;
    border-radius: 2px;
}
QSlider::add-page:vertical { background: #e5e7eb; border-radius: 2px; }
QSlider::sub-page:vertical { background: #111827; border-radius: 2px; }

/* ---------- CheckBox ---------- */
QCheckBox {
    color: #374151;
    spacing: 7px;
    font-size: 11px;
    font-weight: 500;
    background: transparent;
}
QCheckBox::indicator {
    width: 16px;
    height: 16px;
    border: 1px solid #d1d5db;
    border-radius: 3px;
    background: #ffffff;
}
QCheckBox::indicator:hover {
    border-color: #9ca3af;
    background: #f9fafb;
}
QCheckBox::indicator:checked {
    background: #111827;
    border-color: #111827;
    image: none;
}
QCheckBox:disabled {
    color: #9ca3af;
}

/* ---------- Tab Widget ---------- */
QTabWidget::pane {
    border: 1px solid #e5e7eb;
    border-radius: 6px;
    background: #ffffff;
    top: -1px;
}
QTabBar::tab {
    background: #f9fafb;
    border: 1px solid #e5e7eb;
    padding: 7px 12px;
    margin-right: 3px;
    border-top-left-radius: 6px;
    border-top-right-radius: 6px;
    border-bottom: 1px solid #e5e7eb;
    color: #6b7280;
    font-weight: 600;
    font-size: 11px;
}
QTabBar::tab:hover:!selected {
    background: #f3f4f6;
    color: #374151;
    border-color: #d1d5db;
}
QTabBar::tab:selected {
    background: #ffffff;
    color: #111827;
    border: 1px solid #e5e7eb;
    border-bottom: 1px solid #ffffff;
    margin-bottom: -1px;
}
QTabBar::tab:disabled {
    color: #9ca3af;
    background: #f9fafb;
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
    background: #e5e7eb;
    border-radius: 2px;
}
QSplitter::handle:horizontal {
    width: 5px;
    margin: 0 2px;
}
QSplitter::handle:vertical {
    height: 5px;
    margin: 2px 0;
}
QSplitter::handle:hover {
    background: #d1d5db;
}
QScrollBar:vertical {
    background: #f9fafb;
    width: 8px;
    border-radius: 4px;
    margin: 2px;
}
QScrollBar::handle:vertical {
    background: #d1d5db;
    border-radius: 4px;
    min-height: 24px;
}
QScrollBar::handle:vertical:hover {
    background: #9ca3af;
}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical,
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {
    height: 0px;
    background: transparent;
}
QScrollBar:horizontal {
    background: #f9fafb;
    height: 8px;
    border-radius: 4px;
    margin: 2px;
}
QScrollBar::handle:horizontal {
    background: #d1d5db;
    border-radius: 4px;
    min-width: 24px;
}
QScrollBar::handle:horizontal:hover {
    background: #9ca3af;
}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal,
QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {
    width: 0px;
    background: transparent;
}

/* ---------- Status Bar ---------- */
QStatusBar {
    background: #ffffff;
    color: #6b7280;
    border-top: 1px solid #e5e7eb;
    font-size: 11px;
    padding: 2px 8px;
}
QStatusBar::item { border: none; }

/* ---------- ToolBar ---------- */
QToolBar {
    background: #ffffff;
    border-bottom: 1px solid #e5e7eb;
    spacing: 6px;
    padding: 4px 8px;
}
QToolBar QToolButton {
    background: #ffffff;
    border: 1px solid #e5e7eb;
    border-radius: 6px;
    padding: 5px 10px;
    color: #374151;
    font-weight: 500;
    font-size: 11px;
}
QToolBar QToolButton:hover {
    background: #f9fafb;
    border-color: #d1d5db;
    color: #111827;
}
QToolBar QToolButton:pressed {
    background: #f3f4f6;
}

/* ============================================================
   CAMERA STAGE — light cards, pitch black video
   ============================================================ */
QFrame#cameraCard {
    background: #ffffff;
    border: 1px solid #e5e7eb;
    border-radius: 8px;
}
QFrame#cameraCardHeader {
    background: #ffffff;
    border: none;
    border-top-left-radius: 8px;
    border-top-right-radius: 8px;
    border-bottom: 1px solid #e5e7eb;
}
QFrame#cameraCardHeader QLabel {
    color: #374151;
}
QLabel#cameraTitle {
    color: #111827;
    font-weight: 600;
    font-size: 11px;
    letter-spacing: 0.3px;
}
QLabel#cameraIcon {
    color: #6b7280;
    font-size: 11px;
    background: #f9fafb;
    border: 1px solid #e5e7eb;
    border-radius: 4px;
    padding: 3px 6px;
}
QLabel#liveBadge {
    background: #f3f4f6;
    color: #6b7280;
    font-weight: 600;
    font-size: 9px;
    letter-spacing: 0.4px;
    border-radius: 4px;
    border: 1px solid #e5e7eb;
    padding: 3px 7px;
}
QLabel#liveBadge[active="true"] {
    background: #111827;
    color: #ffffff;
    border-color: #111827;
}
QLabel#resBadge {
    background: #f9fafb;
    color: #374151;
    font-weight: 500;
    font-size: 10px;
    border: 1px solid #e5e7eb;
    border-radius: 4px;
    padding: 3px 8px;
    font-family: 'Consolas', 'Courier New', monospace;
}
QLabel#videoFeed {
    background: #000000;
    border: 1px solid #000000;
    border-radius: 4px;
}
QFrame#cameraCardFooter {
    background: #ffffff;
    border: none;
    border-top: 1px solid #e5e7eb;
    border-bottom-left-radius: 8px;
    border-bottom-right-radius: 8px;
}
QFrame#cameraCardFooter QLabel {
    color: #6b7280;
    font-size: 10px;
    font-family: 'Consolas', 'Courier New', monospace;
}
QFrame#telemetryStrip {
    background: #ffffff;
    border: 1px solid #e5e7eb;
    border-radius: 6px;
}
QFrame#telemetryStrip QLabel {
    color: #374151;
    font-size: 11px;
}
QLabel#telemetryValue {
    background: #f9fafb;
    border: 1px solid #e5e7eb;
    border-radius: 4px;
    padding: 3px 8px;
    font-weight: 600;
    color: #111827;
    font-family: 'Consolas', 'Courier New', monospace;
    font-size: 11px;
}
QLabel#telemetryLabel {
    color: #6b7280;
    font-size: 10px;
    font-weight: 500;
}
QFrame#appHeader {
    background: #ffffff;
    border: 1px solid #e5e7eb;
    border-radius: 6px;
}
QFrame#appHeader QLabel {
    color: #374151;
}
QLabel#appTitle {
    color: #111827;
    font-weight: 700;
    font-size: 12px;
    letter-spacing: 0.4px;
}
QLabel#appSubtitle {
    color: #6b7280;
    font-size: 10px;
    font-weight: 500;
}
QLabel#headerBadge {
    background: #f9fafb;
    color: #374151;
    border: 1px solid #e5e7eb;
    border-radius: 4px;
    padding: 4px 8px;
    font-weight: 500;
    font-size: 10px;
    font-family: 'Consolas', 'Courier New', monospace;
}
QFrame#controlHeader {
    background: #ffffff;
    border: 1px solid #e5e7eb;
    border-radius: 6px;
}
QLabel#controlTitle {
    color: #111827;
    font-weight: 700;
    font-size: 12px;
    letter-spacing: 0.3px;
}
QLabel#controlSubtitle {
    color: #6b7280;
    font-size: 10px;
    font-weight: 400;
}
QLabel#Badge {
    background: #f9fafb;
    color: #374151;
    border: 1px solid #e5e7eb;
    border-radius: 4px;
    padding: 3px 8px;
    font-weight: 600;
    font-size: 9px;
    letter-spacing: 0.3px;
}
QFrame#controlHeader QPushButton {
    background: #111827;
    color: #ffffff;
    border: 1px solid #111827;
    border-radius: 4px;
    padding: 5px 10px;
    font-weight: 600;
    font-size: 10px;
}

/* ---------- Dashboard specifics ---------- */
QFrame#dashboardCard {
    background: #ffffff;
    border: 1px solid #e5e7eb;
    border-radius: 6px;
}
"""

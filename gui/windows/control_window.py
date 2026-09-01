# gui/windows/control_window.py - Separate Control Dashboard window hosting live dashboard + all controls

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QMainWindow, QScrollArea, QStatusBar, QWidget

from gui.styles import APP_STYLE

class ControlDashboardWindow(QMainWindow):
    """
    Separate window that hosts the entire control panel + live dashboard.

    - All control widgets remain owned by MainWindow (signal wiring stays there)
      but are visually reparented here for the "separate window" requirement.
    - Clearly distinguished sections via tabs (Dashboard | Global | Beacons | Camera | Environment | Disturbances).
    - Hides on close instead of destroying — MainWindow keeps reference.
    """

    def __init__(self, main_window, control_widget: QWidget):
        super().__init__(main_window)
        self.main_window = main_window
        self.setWindowTitle("FSOC — Control Deck (Live)")
        self.setMinimumSize(460, 780)
        self.resize(520, 960)
        self.setStyleSheet(APP_STYLE)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("QScrollArea { border: none; background: #f9fafb; } QScrollBar:vertical { background:#e5e7eb; width:8px; }")
        scroll.setWidget(control_widget)
        self.setCentralWidget(scroll)
        sb = QStatusBar()
        sb.setStyleSheet("QStatusBar { background:#ffffff; border-top:1px solid #e5e7eb; } QStatusBar QLabel { color:#6b7280; }")
        sb.showMessage("Control Deck — all parameters live, no restart required")
        self.setStatusBar(sb)

        # Keep as normal top-level window (not modal)
        self.setWindowFlags(self.windowFlags() | Qt.Window)

    # Hidden instead of destroyed — preserves wiring

    def closeEvent(self, event):
        event.ignore()
        self.hide()
        if hasattr(self.main_window, "statusBar"):
            self.main_window.statusBar().showMessage("Control Panel hidden — click Show Controls to show", 3000)
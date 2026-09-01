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
        self.setWindowTitle("⬢ FSOC — Command Deck  •  Live Controls (HOT)")
        self.setMinimumSize(460, 780)
        self.resize(520, 960)
        self.setStyleSheet(APP_STYLE)

        # Central scroll — makes long tab content responsive with subtle outer bg
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("QScrollArea { border: none; background: #f1f5f9; } QScrollBar:vertical { background:#e2e8f0; width:8px; }")
        scroll.setWidget(control_widget)
        self.setCentralWidget(scroll)

        # Status bar — hints that controls are HOT with pill badge feel
        sb = QStatusBar()
        sb.setStyleSheet("QStatusBar { background:#ffffff; border-top:1px solid #e2e8f0; } QStatusBar QLabel { color:#475569; }")
        sb.showMessage("⬢ COMMAND DECK  •  all parameters live (HOT)  •  no restart required  •  drag to resize, tabs = mission presets")
        self.setStatusBar(sb)

        # Keep as normal top-level window (not modal)
        self.setWindowFlags(self.windowFlags() | Qt.Window)

    # Hidden instead of destroyed — preserves HOT wiring

    def closeEvent(self, event):
        event.ignore()
        self.hide()
        if hasattr(self.main_window, "statusBar"):
            self.main_window.statusBar().showMessage("Control Panel hidden — click 'Open Controls' to show", 3000)
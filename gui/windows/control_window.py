"""
Module: gui.windows.control_window
Purpose: Separate Control Dashboard window hosting live dashboard + all controls.
Public API: ControlDashboardWindow
Notes: Extracted from gui.app — reparented control_widget keeps logic in MainWindow.
"""

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QMainWindow, QScrollArea, QStatusBar, QWidget

from gui.styles import APP_STYLE

# ============================================================
# SECTION: ControlDashboardWindow — Separate live control panel
# ============================================================

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
        self.setWindowTitle("FSOC Control Panel — Live Dashboard & All Controls (Separate Window)")
        self.setMinimumSize(440, 760)
        self.resize(480, 920)
        self.setStyleSheet(APP_STYLE)

        # Central scroll — makes long tab content responsive
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("QScrollArea { border: none; background: #f8fafc; }")
        scroll.setWidget(control_widget)
        self.setCentralWidget(scroll)

        # Status bar — hints that controls are HOT
        sb = QStatusBar()
        sb.showMessage("Control Panel — all parameters live, no restart required")
        self.setStatusBar(sb)

        # Keep as normal top-level window (not modal)
        self.setWindowFlags(self.windowFlags() | Qt.Window)

    # --------------------------------------------------------
    # Hidden instead of destroyed — preserves HOT wiring
    # --------------------------------------------------------

    def closeEvent(self, event):
        event.ignore()
        self.hide()
        if hasattr(self.main_window, "statusBar"):
            self.main_window.statusBar().showMessage("Control Panel hidden — click 'Open Controls' to show", 3000)

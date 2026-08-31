"""
Module: gui.windows.dashboard_window
Purpose: Separate window hosting live dashboard and graph.
"""

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QMainWindow, QScrollArea, QWidget

from gui.styles import APP_STYLE

class DashboardWindow(QMainWindow):
    """
    Separate window for the DashboardPanel.
    """
    def __init__(self, main_window, dashboard_panel: QWidget):
        super().__init__(main_window)
        self.main_window = main_window
        self.setWindowTitle("FSOC Simulator — Dashboard & Metrics")
        self.setMinimumSize(800, 600)
        self.resize(1000, 800)
        self.setStyleSheet(APP_STYLE)

        self.setCentralWidget(dashboard_panel)

        self.setWindowFlags(self.windowFlags() | Qt.Window)

    def closeEvent(self, event):
        event.ignore()
        self.hide()

# gui/windows/dashboard_window.py - Live Dashboard in its OWN separate window.
# Reference PDF 2: dark header + white metric card. Fullscreen-capable, independent
# of the simulator window. Hosts DashboardView (pure renderer of DashboardState).
from __future__ import annotations

import logging

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QHBoxLayout, QLabel, QMainWindow, QPushButton, QScrollArea, QVBoxLayout, QWidget,
)

from gui.styles import APP_STYLE
from gui.views.dashboard_view import DashboardView

log = logging.getLogger(__name__)


class DashboardWindow(QMainWindow):
    """Separate top-level window for the Live Dashboard. No sim access."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Live Dashboard")
        self.setMinimumSize(700, 600)
        self.resize(900, 800)
        self.setStyleSheet(APP_STYLE)
        self._fullscreen = False

        central = QWidget(self)
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(10)

        header = QWidget(self)
        header.setObjectName("headerBar")
        hbox = QHBoxLayout(header)
        title = QLabel("Live Dashboard", header)
        title.setObjectName("appTitle")
        hbox.addWidget(title)
        hbox.addStretch(1)
        self.btn_fullscreen = QPushButton("Full Screen", header)
        self.btn_fullscreen.setObjectName("settingsButton")
        self.btn_fullscreen.clicked.connect(self.toggle_fullscreen)
        self.btn_close = QPushButton("Close", header)
        self.btn_close.setObjectName("resetButton")
        self.btn_close.clicked.connect(self.hide)
        hbox.addWidget(self.btn_fullscreen)
        hbox.addWidget(self.btn_close)
        root.addWidget(header)

        self.view = DashboardView(self)
        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setWidget(self.view)
        root.addWidget(scroll, 1)

    def toggle_fullscreen(self) -> None:
        try:
            if self._fullscreen or self.isFullScreen():
                self._fullscreen = False
                self.showMaximized()
                self.btn_fullscreen.setText("Full Screen")
            else:
                self._fullscreen = True
                self.showFullScreen()
                self.btn_fullscreen.setText("Exit Full Screen")
        except Exception as e:
            log.debug("dashboard fullscreen toggle failed: %s", e)

    def closeEvent(self, event) -> None:  # noqa: N802
        # Hide instead of destroying so live state is preserved.
        try:
            event.ignore()
            self.hide()
        except Exception:
            super().closeEvent(event)

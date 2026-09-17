# gui/views/settings_dialog.py - Fullscreen-capable Control Deck hosting Remote Terminal and system configs.
from __future__ import annotations

import logging

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from gui.styles import APP_STYLE

log = logging.getLogger(__name__)


class SettingsDialog(QDialog):
    """
    Control Deck window/dialog - fullscreen capable.
    Hosts:
      - Remote Terminal Control Deck (6-card architecture)
      - Camera Panel
      - Control Panel (PID)
      - Environment Panel
      - Disturbances Panel
    Emits validated Config objects upward. Never touches simulation directly.
    """

    cameraChanged = pyqtSignal(object)
    controlChanged = pyqtSignal(object)
    environmentChanged = pyqtSignal(object)
    disturbancesChanged = pyqtSignal(object)
    terminalChanged = pyqtSignal(object)

    def __init__(self, session, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Settings")
        self.setMinimumSize(950, 700)
        self.resize(1400, 920)
        self.setStyleSheet(APP_STYLE)
        self.setWindowFlags(self.windowFlags() | Qt.Window)
        self._fullscreen = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        # Header Bar
        header = QWidget(self)
        header.setObjectName("headerBar")
        hbox = QHBoxLayout(header)
        hbox.setContentsMargins(12, 8, 12, 8)
        title = QLabel("Control Deck", header)
        title.setObjectName("appTitle")
        title.setStyleSheet("font-size:16px; font-weight:700; color:#ffffff;")
        hbox.addWidget(title)

        sub = QLabel("Configuration & Remote Terminal System", header)
        sub.setStyleSheet("font-size:11px; color:#e2e8f0; margin-left:8px;")
        hbox.addWidget(sub)
        hbox.addStretch(1)

        self.btn_fullscreen = QPushButton("Full Screen", header)
        self.btn_fullscreen.setObjectName("settingsButton")
        self.btn_fullscreen.clicked.connect(self.toggle_fullscreen)
        hbox.addWidget(self.btn_fullscreen)

        self.btn_close = QPushButton("Close", header)
        self.btn_close.setObjectName("resetButton")
        self.btn_close.clicked.connect(self.close)
        hbox.addWidget(self.btn_close)
        layout.addWidget(header)

        # Tab Widget
        self.tabs = QTabWidget(self)
        self.tabs.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        layout.addWidget(self.tabs, 1)

        from gui.panels.camera_panel import CameraPanel
        from gui.panels.control_panel import ControlPanel
        from gui.panels.disturbances_panel import DisturbancesPanel
        from gui.panels.environment_panel import EnvironmentPanel
        from gui.panels.remote_terminal_panel import RemoteTerminalPanel

        # 1. Remote Terminal Panel
        scen_cfg = getattr(session, "scenario_config", None)
        self.terminal_panel = RemoteTerminalPanel(initial=scen_cfg)

        # 2. Camera Panel
        scene_bounds = (int(session.env_config.world_width), int(session.env_config.world_height))
        self.camera_panel = CameraPanel(initial=session.camera_config, scene_bounds=scene_bounds)

        # 3. Control Panel
        self.control_panel = ControlPanel(initial=session.controller_config)

        # 4. Environment Panel
        self.env_panel = EnvironmentPanel(initial=session.env_config)

        # 5. Disturbances Panel
        self.dist_panel = DisturbancesPanel(initial=session.disturbance_config)

        # Wrap each panel in a scroll area with custom clean background
        self._add_scrolled_tab(self.terminal_panel, "Remote Terminal")
        self._add_scrolled_tab(self.camera_panel, "Camera")
        self._add_scrolled_tab(self.control_panel, "Control (PID)")
        self._add_scrolled_tab(self.env_panel, "Environment")
        self._add_scrolled_tab(self.dist_panel, "Disturbances")

        # Connect signals
        self.terminal_panel.configChanged.connect(self.terminalChanged.emit)
        self.camera_panel.configChanged.connect(lambda: self.cameraChanged.emit(self.camera_panel.collect_config()))
        self.control_panel.configChanged.connect(self.controlChanged.emit)
        self.env_panel.configChanged.connect(self.environmentChanged.emit)
        self.dist_panel.configChanged.connect(self.disturbancesChanged.emit)

    def _add_scrolled_tab(self, widget: QWidget, title: str) -> None:
        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet(
            "QScrollArea { border:none; background:#f9fafb; } "
            "QScrollBar:vertical { background:#e5e7eb; width:8px; border-radius:4px; } "
            "QScrollBar::handle:vertical { background:#9ca3af; border-radius:4px; min-height:20px; } "
            "QScrollBar::handle:vertical:hover { background:#4b4d4f; }"
        )
        scroll.setWidget(widget)
        self.tabs.addTab(scroll, title)

    def toggle_fullscreen(self) -> None:
        try:
            if self._fullscreen or self.isFullScreen():
                self._fullscreen = False
                self.showNormal()
                self.btn_fullscreen.setText("Full Screen")
            else:
                self._fullscreen = True
                self.showFullScreen()
                self.btn_fullscreen.setText("Exit Full Screen")
        except Exception as e:
            log.debug("control deck fullscreen toggle failed: %s", e)

    def update_telemetry(self, telemetry: dict) -> None:
        try:
            self.terminal_panel.update_telemetry(telemetry)
        except Exception as e:
            log.debug("terminal telemetry update skipped: %s", e)

    def sync_world_bounds(self, session) -> None:
        """Push current world size into panels (call after world resize)."""
        try:
            bounds = (int(session.env_config.world_width), int(session.env_config.world_height))
        except Exception as e:
            log.debug("world bounds sync skipped: %s", e)
            return
        for panel, method in ((self.camera_panel, "set_scene_bounds"),):
            try:
                getattr(panel, method)(bounds)
            except Exception as e:
                log.debug("%s sync skipped: %s", method, e)

    def sync_from_session(self, session) -> None:
        """Pull clamped session values back into widgets (no emit, no loops)."""
        self.sync_world_bounds(session)
        try:
            if hasattr(session, "scenario_config"):
                self.terminal_panel.set_config(session.scenario_config, emit=False)
        except Exception as e:
            log.debug("terminal sync skipped: %s", e)
        try:
            self.camera_panel.set_config(session.camera_config, emit=False)
        except Exception as e:
            log.debug("camera sync skipped: %s", e)
        try:
            self.control_panel.set_config(session.controller_config, emit=False)
        except Exception as e:
            log.debug("control sync skipped: %s", e)
        try:
            self.env_panel.set_config(session.env_config, emit=False)
        except Exception as e:
            log.debug("env sync skipped: %s", e)
        try:
            self.dist_panel.set_config(session.disturbance_config, emit=False)
        except Exception as e:
            log.debug("disturbances sync skipped: %s", e)


ControlDeckDialog = SettingsDialog

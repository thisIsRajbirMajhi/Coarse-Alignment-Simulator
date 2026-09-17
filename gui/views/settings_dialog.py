# gui/views/settings_dialog.py - Secondary config: pure input components.
# Hosts existing panels; emits validated Config objects upward. Never touches sim.
from __future__ import annotations

import logging

from PyQt5.QtCore import pyqtSignal
from PyQt5.QtWidgets import QDialog, QHBoxLayout, QLabel, QPushButton, QTabWidget, QVBoxLayout, QWidget

from gui.styles import APP_STYLE

log = logging.getLogger(__name__)


class SettingsDialog(QDialog):
    cameraChanged = pyqtSignal(object)
    controlChanged = pyqtSignal(object)
    environmentChanged = pyqtSignal(object)
    disturbancesChanged = pyqtSignal(object)

    def __init__(self, session, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Settings")
        self.setMinimumSize(560, 640)
        self.setStyleSheet(APP_STYLE)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(10)
        header = QWidget(self)
        header.setObjectName("headerBar")
        hbox = QHBoxLayout(header)
        title = QLabel("Settings", header)
        title.setObjectName("appTitle")
        hbox.addWidget(title)
        hbox.addStretch(1)
        self.btn_close = QPushButton("Close", header)
        self.btn_close.setObjectName("resetButton")
        self.btn_close.clicked.connect(self.close)
        hbox.addWidget(self.btn_close)
        layout.addWidget(header)
        tabs = QTabWidget(self)
        layout.addWidget(tabs, 1)

        from gui.panels.camera_panel import CameraPanel
        from gui.panels.control_panel import ControlPanel
        from gui.panels.disturbances_panel import DisturbancesPanel
        from gui.panels.environment_panel import EnvironmentPanel

        self.camera_panel = CameraPanel(
            initial=session.camera_config,
            scene_bounds=(int(session.env_config.world_width), int(session.env_config.world_height)),
        )
        self.control_panel = ControlPanel(initial=session.controller_config)
        self.env_panel = EnvironmentPanel(initial=session.env_config)
        self.dist_panel = DisturbancesPanel(initial=session.disturbance_config)

        tabs.addTab(self.camera_panel, "Camera")
        tabs.addTab(self.control_panel, "Control")
        tabs.addTab(self.env_panel, "Environment")
        tabs.addTab(self.dist_panel, "Disturbances")

        self.camera_panel.configChanged.connect(
            lambda: self.cameraChanged.emit(self.camera_panel.collect_config()))
        self.control_panel.configChanged.connect(self.controlChanged.emit)
        self.env_panel.configChanged.connect(self.environmentChanged.emit)
        self.dist_panel.configChanged.connect(self.disturbancesChanged.emit)

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

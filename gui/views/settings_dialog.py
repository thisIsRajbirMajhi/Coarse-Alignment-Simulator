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
    beaconsChanged = pyqtSignal(object)
    targetChanged = pyqtSignal(int)
    thresholdChanged = pyqtSignal(int)

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
        from gui.panels.multi_beacon_panel import MultiBeaconPanel

        self.camera_panel = CameraPanel(initial=session.camera_config)
        self.control_panel = ControlPanel(initial=session.controller_config)
        self.env_panel = EnvironmentPanel(initial=session.env_config)
        self.dist_panel = DisturbancesPanel(initial=session.disturbance_config)
        self.beacon_panel = MultiBeaconPanel(
            initial=session.beacon_config,
            world_bounds=(int(session.env_config.world_width), int(session.env_config.world_height)),
        )
        tabs.addTab(self.camera_panel, "Camera")
        tabs.addTab(self.control_panel, "Control")
        tabs.addTab(self.env_panel, "Environment")
        tabs.addTab(self.dist_panel, "Disturbances")
        tabs.addTab(self.beacon_panel, "Beacons")

        self.camera_panel.configChanged.connect(
            lambda: self.cameraChanged.emit(self.camera_panel.collect_config()))
        self.control_panel.configChanged.connect(self.controlChanged.emit)
        self.env_panel.configChanged.connect(self.environmentChanged.emit)
        self.dist_panel.configChanged.connect(self.disturbancesChanged.emit)
        self.beacon_panel.multiConfigChanged.connect(self.beaconsChanged.emit)
        try:
            self.beacon_panel.targetChanged.connect(self.targetChanged.emit)
        except Exception as e:
            log.debug("beacon target wiring skipped: %s", e)
        # Detector bright threshold is not part of MultiBeaconConfig — wire it
        # directly so the slider actually drives the pipeline.
        try:
            self.beacon_panel.slider_thresh.setValue(int(session.detector_threshold))
            self.beacon_panel.threshChanged.connect(self.thresholdChanged.emit)
        except Exception as e:
            log.debug("threshold wiring skipped: %s", e)

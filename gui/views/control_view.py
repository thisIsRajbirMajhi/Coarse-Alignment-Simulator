# gui/views/control_view.py - Start/Stop/Pause/Reset primary controls.
from __future__ import annotations

import logging

from PyQt5.QtWidgets import QComboBox, QHBoxLayout, QPushButton, QWidget

log = logging.getLogger(__name__)


class ControlView(QWidget):
    """Emits intent signals only. Button enablement driven by lifecycle."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("controlView")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.btn_start = QPushButton("Start")
        self.btn_start.setObjectName("startButton")
        self.btn_stop = QPushButton("Stop")
        self.btn_stop.setObjectName("stopButton")
        self.btn_pause = QPushButton("Pause")
        self.btn_pause.setObjectName("pauseButton")
        self.btn_reset = QPushButton("Reset")
        self.btn_reset.setObjectName("resetButton")
        self.btn_settings = QPushButton("Control Deck")
        self.btn_settings.setObjectName("settingsButton")
        self.btn_control_deck = self.btn_settings
        self.btn_dashboard = QPushButton("Live Dashboard")
        self.btn_dashboard.setObjectName("settingsButton")
        self.btn_fullscreen = QPushButton("Full Screen")
        self.btn_fullscreen.setObjectName("settingsButton")
        # Testing presets: auto-configure all modules + auto-start.
        self.preset_combo = QComboBox(self)
        self.preset_combo.setObjectName("presetCombo")
        self.btn_preset = QPushButton("Load & Start")
        self.btn_preset.setObjectName("presetButton")
        self.btn_preset.setToolTip("Apply the selected testing preset to all modules and start the simulation")
        for b in (self.btn_start, self.btn_stop, self.btn_pause, self.btn_reset, self.btn_dashboard, self.btn_fullscreen, self.btn_settings):
            layout.addWidget(b)
        layout.addWidget(self.preset_combo)
        layout.addWidget(self.btn_preset)

    def apply_button_states(self, states: dict) -> None:
        self.btn_start.setEnabled(bool(states.get("start", False)))
        self.btn_stop.setEnabled(bool(states.get("stop", False)))
        self.btn_pause.setEnabled(bool(states.get("pause", False)))
        self.btn_reset.setEnabled(bool(states.get("reset", True)))
        try:
            self.btn_pause.setText(str(states.get("pause_text", "Pause")))
        except Exception as e:
            log.debug("pause label update skipped: %s", e)

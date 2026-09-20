# gui/views/control_view.py - Start/Stop/Pause/Reset primary controls.
from __future__ import annotations

import logging

from PyQt5.QtWidgets import QHBoxLayout, QLabel, QPushButton, QWidget

log = logging.getLogger(__name__)


class ControlView(QWidget):
    """Emits intent signals only. Button enablement driven by lifecycle."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("controlView")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.live_dot = QLabel("● LIVE")
        self.live_dot.setObjectName("liveDot")
        self.live_dot.setToolTip("Live preview — control changes apply to the simulation")
        layout.addWidget(self.live_dot)
        self.btn_start = QPushButton("Start")
        self.btn_start.setObjectName("startButton")
        self.btn_start.setToolTip("Start the simulation (rebuilds first if needed)")
        self.btn_stop = QPushButton("Stop")
        self.btn_stop.setObjectName("stopButton")
        self.btn_stop.setToolTip("Stop the simulation and clear runtime stats")
        self.btn_pause = QPushButton("Pause")
        self.btn_pause.setObjectName("pauseButton")
        self.btn_pause.setToolTip("Pause / resume the simulation")
        self.btn_reset = QPushButton("Reset")
        self.btn_reset.setObjectName("resetButton")
        self.btn_reset.setToolTip("Reset to a fresh simulation with default configuration")
        self.btn_settings = QPushButton("Control Deck")
        self.btn_settings.setObjectName("settingsButton")
        self.btn_control_deck = self.btn_settings
        self.btn_dashboard = QPushButton("Live Dashboard")
        self.btn_dashboard.setObjectName("settingsButton")
        self.btn_fullscreen = QPushButton("Full Screen")
        self.btn_fullscreen.setObjectName("settingsButton")
        self.btn_theme = QPushButton("◐ Dark")
        self.btn_theme.setObjectName("settingsButton")
        self.btn_theme.setToolTip("Toggle dark console theme (persists)")
        for b in (self.btn_start, self.btn_stop, self.btn_pause, self.btn_reset, self.btn_dashboard, self.btn_fullscreen, self.btn_theme, self.btn_settings):
            layout.addWidget(b)

    def apply_button_states(self, states: dict) -> None:
        self.btn_start.setEnabled(bool(states.get("start", False)))
        self.btn_stop.setEnabled(bool(states.get("stop", False)))
        self.btn_pause.setEnabled(bool(states.get("pause", False)))
        self.btn_reset.setEnabled(bool(states.get("reset", True)))
        try:
            self.btn_pause.setText(str(states.get("pause_text", "Pause")))
        except Exception as e:
            log.debug("pause label update skipped: %s", e)

    def set_live(self, pending: bool = False, running: bool = False) -> None:
        """LIVE badge (Design.md §15/§17): ● LIVE normally, ◌ APPLYING… while
        a debounced config apply is queued, ○ IDLE when stopped."""
        try:
            if pending:
                self.live_dot.setText("◌ APPLYING…")
                self.live_dot.setStyleSheet("color:#F2B84B; font-weight:700;")
            elif running:
                self.live_dot.setText("● LIVE")
                self.live_dot.setStyleSheet("color:#57D38C; font-weight:700;")
            else:
                self.live_dot.setText("○ IDLE")
                self.live_dot.setStyleSheet("color:#8F9CAB; font-weight:700;")
        except Exception as e:
            log.debug("live badge update skipped: %s", e)

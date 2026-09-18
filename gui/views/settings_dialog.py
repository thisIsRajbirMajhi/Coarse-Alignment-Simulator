# gui/views/settings_dialog.py - Fullscreen-capable Control Deck hosting Local Terminal, Remote Terminal, and system configs.
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
      - Local Terminal Control Deck (Configuration A–E & Operations F–I)
      - Remote Terminal Control Deck (6-card multi-terminal architecture)
      - Control Panel (PID)
      - Environment Panel
      - Disturbances Panel
    Emits validated Config objects upward. Never touches simulation directly.
    """

    localTerminalChanged = pyqtSignal(object)
    cameraChanged = pyqtSignal(object)  # Compatibility alias
    controlChanged = pyqtSignal(object)
    environmentChanged = pyqtSignal(object)
    disturbancesChanged = pyqtSignal(object)
    terminalChanged = pyqtSignal(object)

    def __init__(self, session, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Settings")
        self.setMinimumSize(1000, 720)
        self.resize(1440, 920)
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

        sub = QLabel("Local Optical Terminal • Remote Terminal • Environment • Disturbances", header)
        sub.setStyleSheet("font-size:11px; color:#e2e8f0; margin-left:8px;")
        hbox.addWidget(sub)
        hbox.addStretch(1)

        self.btn_randomize = QPushButton("🎲 Randomize All", header)
        self.btn_randomize.setObjectName("randomizeAllButton")
        self.btn_randomize.setToolTip("Randomize all remote and local terminal parameters and synchronize optical pairing on the go")
        self.btn_randomize.setStyleSheet(
            "QPushButton { background:#4f46e5; color:#ffffff; font-weight:700; font-size:12px; "
            "border:1px solid #4338ca; border-radius:6px; padding:6px 14px; margin-right:4px; } "
            "QPushButton:hover { background:#4338ca; border-color:#3730a3; } "
            "QPushButton:pressed { background:#3730a3; }"
        )
        self.btn_randomize.clicked.connect(self.randomize_all)
        hbox.addWidget(self.btn_randomize)

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

        from gui.panels.disturbances_panel import DisturbancesPanel
        from gui.panels.environment_panel import EnvironmentPanel
        from gui.panels.local_terminal_panel import LocalTerminalPanel
        from gui.panels.remote_terminal_panel import RemoteTerminalPanel

        scene_bounds = (int(session.env_config.world_width), int(session.env_config.world_height))

        # 1. Local Terminal Panel (replaces standalone camera deck)
        lt_cfg = getattr(session, "local_terminal_config", None) or getattr(session, "camera_config", None)
        self.local_terminal_panel = LocalTerminalPanel(initial=lt_cfg, scene_bounds=scene_bounds)
        # Compatibility alias
        self.camera_panel = self.local_terminal_panel

        # 2. Remote Terminal Panel
        scen_cfg = getattr(session, "scenario_config", None)
        self.terminal_panel = RemoteTerminalPanel(initial=scen_cfg)
        self.remote_terminal_panel = self.terminal_panel

        # 3. Environment Panel
        self.env_panel = EnvironmentPanel(initial=session.env_config)

        # 4. Disturbances Panel
        self.dist_panel = DisturbancesPanel(initial=session.disturbance_config)

        # Wrap each panel in a scroll area with custom clean background
        self._add_scrolled_tab(self.terminal_panel, "Remote Terminal")
        self._add_scrolled_tab(self.local_terminal_panel, "Local Terminal")
        self._add_scrolled_tab(self.env_panel, "Environment")
        self._add_scrolled_tab(self.dist_panel, "Disturbances")

        # Connect signals
        def _on_local_terminal_changed(cfg):
            self.localTerminalChanged.emit(cfg)
            self.cameraChanged.emit(cfg)

        self.local_terminal_panel.configChanged.connect(_on_local_terminal_changed)
        self.terminal_panel.configChanged.connect(self.terminalChanged.emit)
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

    def randomize_all(self) -> None:
        """Randomize remote and local terminal configurations in sync on the go."""
        import random

        laser_lines = [850.0, 980.0, 1064.0, 1310.0, 1550.0]
        tokens = ["ALPHA-7", "BRAVO-2", "ECHO-9", "SIERRA-4", "OMEGA-1", "KILO-6"]
        mod_types = ["AM", "OOK", "PM"]

        chosen_wl = random.choice(laser_lines)
        chosen_token = random.choice(tokens)
        chosen_mod = random.choice(mod_types)
        chosen_freq = round(random.uniform(8.0, 20.0), 1)

        # 1. Randomize Remote Terminal (emits exactly 1 terminalChanged signal via connect)
        self.terminal_panel.randomize(
            token=chosen_token,
            wavelength=chosen_wl,
            mod_type=chosen_mod,
            mod_freq=chosen_freq,
            emit=True,
        )

        # 2. Randomize Local Terminal (emits exactly 1 localTerminalChanged signal via connect)
        self.local_terminal_panel.randomize(
            wavelength=chosen_wl,
            mod_type=chosen_mod,
            mod_freq=chosen_freq,
            emit=True,
        )

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
        if not isinstance(telemetry, dict):
            return
        # Local Terminal telemetry
        try:
            lt_data = telemetry.get("local_terminal") or telemetry
            self.local_terminal_panel.update_telemetry(lt_data)
        except Exception as e:
            log.debug("local terminal telemetry update skipped: %s", e)

        # Remote Terminal telemetry
        try:
            rt_data = telemetry.get("terminals") or telemetry
            self.terminal_panel.update_telemetry(rt_data)
        except Exception as e:
            log.debug("remote terminal telemetry update skipped: %s", e)

    def sync_world_bounds(self, session) -> None:
        """Push current world size into panels (call after world resize)."""
        try:
            bounds = (int(session.env_config.world_width), int(session.env_config.world_height))
        except Exception as e:
            log.debug("world bounds sync skipped: %s", e)
            return
        for panel, method in ((self.local_terminal_panel, "set_scene_bounds"),):
            try:
                getattr(panel, method)(bounds)
            except Exception as e:
                log.debug("%s sync skipped: %s", method, e)

    def sync_from_session(self, session) -> None:
        """Pull clamped session values back into widgets (no emit, no loops)."""
        self.sync_world_bounds(session)
        try:
            if hasattr(session, "local_terminal_config"):
                self.local_terminal_panel.set_config(session.local_terminal_config, emit=False)
            elif hasattr(session, "camera_config"):
                self.local_terminal_panel.set_config(session.camera_config, emit=False)
        except Exception as e:
            log.debug("local terminal sync skipped: %s", e)
        try:
            if hasattr(session, "scenario_config"):
                self.terminal_panel.set_config(session.scenario_config, emit=False)
        except Exception as e:
            log.debug("remote terminal sync skipped: %s", e)
        try:
            self.env_panel.set_config(session.env_config, emit=False)
        except Exception as e:
            log.debug("env sync skipped: %s", e)
        try:
            self.dist_panel.set_config(session.disturbance_config, emit=False)
        except Exception as e:
            log.debug("disturbances sync skipped: %s", e)


ControlDeckDialog = SettingsDialog

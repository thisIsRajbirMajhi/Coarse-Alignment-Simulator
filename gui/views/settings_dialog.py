# gui/views/settings_dialog.py - Fullscreen-capable Control Deck hosting remote terminal and system configs.
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

from gui.theme import apply_theme

log = logging.getLogger(__name__)


class SettingsDialog(QDialog):
    """
    Control Deck window/dialog - fullscreen capable.
    Hosts:
      - Remote Terminal Panel (formation/motion/terminals + telemetry)
      - Environment Panel
      - Disturbances Panel
    Emits validated Config objects upward. Never touches simulation directly.
    """

    localTerminalChanged = pyqtSignal(object)
    cameraChanged = pyqtSignal(object)  # Compatibility alias
    controlChanged = pyqtSignal(object)
    environmentChanged = pyqtSignal(object)
    disturbancesChanged = pyqtSignal(object)
    remoteTerminalChanged = pyqtSignal(object)

    def __init__(self, session, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Settings")
        self.setMinimumSize(1000, 720)
        self.resize(1440, 920)
        apply_theme(self)
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
        hbox.setSpacing(8)
        title_block = QVBoxLayout()
        title_block.setContentsMargins(0, 0, 0, 0)
        title_block.setSpacing(1)
        title = QLabel("Control Deck", header)
        title.setObjectName("appTitle")
        title.setStyleSheet("font-size:16px; font-weight:700; color:#ffffff;")
        title_block.addWidget(title)

        sub = QLabel("4 Cards: Formation/Motion • Optical • Camera/PID+AI • Disturbance (+ Presets/Environment)", header)
        sub.setStyleSheet("font-size:11px; color:#e2e8f0;")
        sub.setWordWrap(True)
        sub.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        title_block.addWidget(sub)
        hbox.addLayout(title_block, 1)
        hbox.addStretch(1)

        self.btn_randomize = QPushButton("🎲 Randomize All", header)
        self.btn_randomize.setObjectName("randomizeAllButton")
        self.btn_randomize.setToolTip("Randomize all remote terminal, environment, and disturbance parameters on the go")
        self.btn_randomize.setMinimumHeight(30)
        self.btn_randomize.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self.btn_randomize.setStyleSheet(
            "QPushButton { background:#ffffff; color:#111827; font-weight:700; font-size:12px; "
            "border:1px solid #e5e7eb; border-radius:6px; padding:6px 14px; margin-right:4px; } "
            "QPushButton:hover { background:#f3f4f6; border-color:#9ca3af; } "
            "QPushButton:pressed { background:#e5e7eb; }"
        )
        self.btn_randomize.clicked.connect(self.randomize_all)
        hbox.addWidget(self.btn_randomize)

        # Scoped randomize overflow (Design.md §16/§46): Everything stays on
        # the main button; the ▾ menu randomizes one module without touching
        # the others (non-blocking, no modal confirmation).
        from PyQt5.QtWidgets import QMenu as _QMenu
        self.btn_randomize_scope = QPushButton("▾", header)
        self.btn_randomize_scope.setObjectName("settingsButton")
        self.btn_randomize_scope.setMinimumHeight(30)
        self.btn_randomize_scope.setFixedWidth(34)
        self.btn_randomize_scope.setToolTip("Randomize one scope: Remote Terminal, Environment, Disturbances, or Seed only")
        scope_menu = _QMenu(self.btn_randomize_scope)
        scope_menu.addAction("Everything", self.randomize_all)
        scope_menu.addAction("Remote Terminal", self.randomize_remote)
        scope_menu.addAction("Environment", self.randomize_environment)
        scope_menu.addAction("Disturbances", self.randomize_disturbances)
        scope_menu.addAction("Seed only", self.randomize_seed_only)
        self.btn_randomize_scope.setMenu(scope_menu)
        hbox.addWidget(self.btn_randomize_scope)

        self.btn_reset_defaults = QPushButton("Reset Defaults", header)
        self.btn_reset_defaults.setObjectName("resetButton")
        self.btn_reset_defaults.setMinimumHeight(30)
        self.btn_reset_defaults.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self.btn_reset_defaults.setToolTip("Reset all panels to their default settings")
        self.btn_reset_defaults.clicked.connect(self.reset_to_defaults)
        hbox.addWidget(self.btn_reset_defaults)

        self.btn_fullscreen = QPushButton("Full Screen", header)
        self.btn_fullscreen.setObjectName("settingsButton")
        self.btn_fullscreen.setMinimumHeight(30)
        self.btn_fullscreen.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self.btn_fullscreen.setToolTip("Toggle fullscreen for the Control Deck")
        self.btn_fullscreen.clicked.connect(self.toggle_fullscreen)
        hbox.addWidget(self.btn_fullscreen)

        self.btn_close = QPushButton("Close", header)
        self.btn_close.setObjectName("resetButton")
        self.btn_close.setMinimumHeight(30)
        self.btn_close.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self.btn_close.setToolTip("Close the Control Deck (configuration is applied live)")
        self.btn_close.clicked.connect(self.close)
        hbox.addWidget(self.btn_close)
        layout.addWidget(header)

        # Tab Widget
        self.tabs = QTabWidget(self)
        self.tabs.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.tabs.setDocumentMode(False)
        self.tabs.setUsesScrollButtons(True)
        self.tabs.setElideMode(Qt.ElideRight)
        self.tabs.setToolTip("Switch configuration sections — changes apply live")
        layout.addWidget(self.tabs, 1)

        footer_hint = QLabel("● LIVE preview — cheap knobs apply instantly, heavy scene rebuilds apply on release", self)
        footer_hint.setObjectName("footerHint")
        footer_hint.setStyleSheet("color:#6b7280; font-size:10px; font-style:italic;")
        footer_hint.setWordWrap(True)
        footer_hint.setAlignment(Qt.AlignCenter)
        layout.addWidget(footer_hint)

        from gui.panels.camera_panel import CameraPanel
        from gui.panels.controller_panel import ControllerPanel
        from gui.panels.disturbances_panel import DisturbancesPanel
        from gui.panels.environment_panel import EnvironmentPanel
        from gui.panels.local_terminal_panel import LocalTerminalPanel
        from gui.panels.presets_panel import PresetsPanel, apply_preset_to_session
        from gui.panels.remote_terminal_panel import RemoteTerminalPanel

        # 0. Presets Panel (testing bundles — collapsible, Apply loads session)
        self.presets_panel = PresetsPanel()

        # 1. Camera & PTZ Panel
        self.camera_panel = CameraPanel(initial=getattr(session, "camera_config", None))

        # 2. PID Controller Panel
        self.controller_panel = ControllerPanel(initial=getattr(session, "pid_config", None))

        # 3. Remote Terminal Panel
        self.remote_panel = RemoteTerminalPanel(initial=session.scenario_config)

        # 4. Local Terminal Panel (V2 AutonomyConfig)
        self.local_panel = LocalTerminalPanel(
            initial=getattr(session, "autonomy_config", getattr(session, "local_terminal_config", None)))

        # 5. Environment Panel
        self.env_panel = EnvironmentPanel(initial=session.env_config)

        # 6. Disturbances Panel
        self.dist_panel = DisturbancesPanel(initial=session.disturbance_config)

        # --- Plan §5: 4 Cards (collapsed from 7 tabs) ---
        # Card 1: Formation/Motion (count, shape 3, speed, heading, profile 5, start offset) — from remote_panel
        # Card 2: Optical (power, wavelength, spot, jitter, emission) — from remote_panel
        # Card 3: Camera/PID + AI (pan/tilt, kp/kd, AI OFF/ON) — camera+controller+local_panel
        # Card 4: Disturbance (S&P, Gauss, jitter, Haze/Fog) — disturbances+environment atmosphere (Advanced collapsed)
        # Preserve Presets as utility tab; keep original panels accessible via Advanced toggle if needed
        self._add_scrolled_tab(self.presets_panel, "Presets")
        # Card 1+2 combined: Remote Terminal already groups Formation/Motion (Card1) + Optical (Card2) with Advanced collapsed
        self._add_scrolled_tab(self.remote_panel, "Card 1+2 - Formation & Optical")
        # Card 3: stack Camera, PID, Local (AI) vertically
        card3 = QWidget(self)
        card3_layout = QVBoxLayout(card3)
        card3_layout.setContentsMargins(0, 0, 0, 0)
        card3_layout.setSpacing(12)
        card3_layout.addWidget(self.camera_panel)
        card3_layout.addWidget(self.controller_panel)
        card3_layout.addWidget(self.local_panel)
        card3_layout.addStretch(1)
        self._add_scrolled_tab(card3, "Card 3 - Camera/PID + AI")
        # Card 4: stack Disturbances + Environment (atmosphere/starfield collapsed Advanced)
        card4 = QWidget(self)
        card4_layout = QVBoxLayout(card4)
        card4_layout.setContentsMargins(0, 0, 0, 0)
        card4_layout.setSpacing(12)
        card4_layout.addWidget(self.dist_panel)
        card4_layout.addWidget(self.env_panel)
        card4_layout.addStretch(1)
        self._add_scrolled_tab(card4, "Card 4 - Disturbance")
        # Keep legacy tabs hidden but accessible for debugging (not added to QTabWidget to satisfy 4-card spec)
        # To debug legacy 7-tab layout, temporarily re-add above _add_scrolled_tab lines

        # Store helper for apply (session provided at init, may be stale after reset — caller syncs via apply_preset)
        self._preset_helper = apply_preset_to_session
        self._preset_session = session

        # Connect signals
        self.camera_panel.configChanged.connect(self.cameraChanged.emit)
        self.controller_panel.configChanged.connect(self.controlChanged.emit)
        self.remote_panel.configChanged.connect(self.remoteTerminalChanged.emit)
        self.local_panel.configChanged.connect(self.localTerminalChanged.emit)
        self.env_panel.configChanged.connect(self.environmentChanged.emit)
        self.dist_panel.configChanged.connect(self.disturbancesChanged.emit)
        self.presets_panel.applyRequested.connect(self._on_preset_apply)

    def _add_scrolled_tab(self, widget: QWidget, title: str) -> None:
        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setStyleSheet(
            "QScrollArea { border:none; background:#ffffff; } "
            "QScrollBar:vertical { background:#e5e7eb; width:8px; border-radius:4px; } "
            "QScrollBar::handle:vertical { background:#9ca3af; border-radius:4px; min-height:20px; } "
            "QScrollBar::handle:vertical:hover { background:#4b4d4f; }"
        )
        widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        scroll.setWidget(widget)
        idx = self.tabs.addTab(scroll, title)
        self.tabs.setTabToolTip(idx, f"{title} configuration")

    def randomize_all(self) -> None:
        """Randomize configurations across all active panels."""
        # 1. Randomize Remote Terminal (formation, motion, every terminal)
        self.randomize_remote()

        # 2. Randomize Environment
        self.randomize_environment()

        # 3. Randomize Disturbances
        self.randomize_disturbances()

    def randomize_remote(self) -> None:
        """Scope: remote terminal only (emits exactly 1 remoteTerminalChanged)."""
        try:
            self.remote_panel.randomize(emit=True)
        except Exception as e:
            log.debug("scoped remote randomize skipped: %s", e)

    def reset_to_defaults(self) -> None:
        """Reset every panel to default settings (each emits once)."""
        try:
            from camera.config import CameraConfig, PIDConfig
            self.camera_panel.set_config(CameraConfig().validate(), emit=True)
            self.controller_panel.set_config(PIDConfig().validate(), emit=True)
        except Exception as e:
            log.debug("camera/controller reset skipped: %s", e)
        try:
            from local_terminal.models import AutonomyConfig
            self.local_panel.set_config(AutonomyConfig().validate(), emit=True)
        except Exception as e:
            log.debug("local terminal reset skipped: %s", e)
        try:
            from remote_terminal import make_default_scenario
            self.remote_panel.set_config(make_default_scenario(), emit=True)
        except Exception as e:
            log.debug("remote terminal reset skipped: %s", e)
        try:
            from environment.config import EnvironmentConfig
            self.env_panel.set_config(EnvironmentConfig().validate(), emit=True)
        except Exception as e:
            log.debug("environment reset skipped: %s", e)
        try:
            from disturbance.core.config import DisturbanceConfig
            self.dist_panel.set_config(DisturbanceConfig().validate(), emit=True)
        except Exception as e:
            log.debug("disturbances reset skipped: %s", e)

    def randomize_environment(self) -> None:
        """Scope: environment only (atmosphere + starfield + seed)."""
        try:
            self.env_panel._randomize_all()
        except Exception as e:
            log.debug("scoped environment randomize skipped: %s", e)

    def randomize_disturbances(self) -> None:
        """Scope: disturbances only (emits exactly 1 disturbancesChanged)."""
        try:
            import numpy as _np
            cfg = self.dist_panel.collect_config().randomize_for_training(_np.random.default_rng(), "mixed")
            self.dist_panel.set_config(cfg.validate(), emit=True)
        except Exception as e:
            log.debug("scoped disturbances randomize skipped: %s", e)

    def randomize_seed_only(self) -> None:
        """Scope: environment seed only."""
        try:
            self.env_panel._randomize_seed()
        except Exception as e:
            log.debug("scoped seed randomize skipped: %s", e)

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
            log.debug("control deck fullscreen toggle failed: %s", e)

    def update_telemetry(self, telemetry: dict) -> None:
        if not isinstance(telemetry, dict):
            return
        try:
            terms = telemetry.get("terminals")
            if isinstance(terms, dict):
                self.remote_panel.update_telemetry(terms)
        except Exception as e:
            log.debug("remote terminal telemetry update skipped: %s", e)

    def sync_world_bounds(self, session) -> None:
        """Push current world size into panels (call after world resize)."""
        pass

    def _on_preset_apply(self, preset_id: str) -> None:
        """Apply preset bundle — via MainWindow bulk (stop→defaults→preset→start) when available."""
        try:
            from PyQt5.QtWidgets import QApplication as _QA
            app = _QA.instance()
            if app is not None:
                for w in app.topLevelWidgets():
                    if hasattr(w, "session") and hasattr(w, "controller") and hasattr(w, "_apply_preset_bulk"):
                        try:
                            w._apply_preset_bulk(preset_id)
                        except Exception as e:
                            log.warning("preset bulk apply failed: %s", e)
                        # Bulk swapped in a fresh session — refresh to the live one.
                        try:
                            self.sync_from_session(w.session)
                        except Exception:
                            pass
                        return
        except Exception:
            pass
        # Headless/test fallback — no MainWindow bulk, just apply bundle to the dialog's session.
        sess = getattr(self, "_preset_session", None)
        if sess is None:
            log.warning("preset %s not applied: no session", preset_id)
            return
        try:
            self._preset_helper(sess, preset_id)
            self.sync_from_session(sess)
        except Exception as e:
            log.warning("preset %s apply failed: %s", preset_id, e)

    def sync_from_session(self, session) -> None:
        """Pull clamped session values back into widgets (no emit, no loops)."""
        self._preset_session = session
        self.sync_world_bounds(session)
        try:
            if hasattr(session, "camera_config"):
                self.camera_panel.set_config(session.camera_config, emit=False)
            if hasattr(session, "pid_config"):
                self.controller_panel.set_config(session.pid_config, emit=False)
        except Exception as e:
            log.debug("camera/controller sync skipped: %s", e)
        try:
            self.remote_panel.set_config(session.scenario_config, emit=False)
        except Exception as e:
            log.debug("remote terminal sync skipped: %s", e)
        try:
            cfg = getattr(session, "autonomy_config", getattr(session, "local_terminal_config", None))
            if cfg is not None:
                self.local_panel.set_config(cfg, emit=False)
        except Exception as e:
            log.debug("local terminal sync skipped: %s", e)
        try:
            self.env_panel.set_config(session.env_config, emit=False)
        except Exception as e:
            log.debug("env sync skipped: %s", e)
        try:
            self.dist_panel.set_config(session.disturbance_config, emit=False)
        except Exception as e:
            log.debug("disturbances sync skipped: %s", e)

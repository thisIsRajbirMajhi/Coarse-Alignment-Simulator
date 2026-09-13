# gui/core/window_manager.py - Owns secondary windows (creation/reuse/geometry).
# Simulator window (MainWindow) and Live Dashboard window are fully separate
# top-level windows; this manager creates/reuses them without mixing content.
from __future__ import annotations

import logging

log = logging.getLogger(__name__)


class WindowManager:
    def __init__(self, parent):
        self._parent = parent
        self._settings = None
        self._dashboard_window = None

    # -- Live Dashboard (own separate window) --------------------------
    def ensure_dashboard(self) -> object:
        """Create the dashboard window on demand WITHOUT showing it."""
        from gui.windows.dashboard_window import DashboardWindow
        if self._dashboard_window is None:
            self._dashboard_window = DashboardWindow(None)  # top-level, not child
        return self._dashboard_window

    def show_dashboard(self, maximized: bool = True) -> object:
        w = self.ensure_dashboard()
        try:
            if maximized and not w.isFullScreen():
                w.showMaximized()
            else:
                w.show()
            w.raise_()
            w.activateWindow()
        except Exception as e:
            log.debug("show dashboard failed: %s", e)
        return w

    @property
    def dashboard_window(self):
        return self._dashboard_window

    # -- Settings (own dialog) ------------------------------------------
    def show_settings(self, session):
        from gui.views.settings_dialog import SettingsDialog
        if self._settings is None:
            self._settings = SettingsDialog(session, self._parent)
            # Wire intents -> parent controller hooks
            self._settings.cameraChanged.connect(self._parent._on_camera_config)
            self._settings.controlChanged.connect(self._parent._on_control_config)
            self._settings.environmentChanged.connect(self._parent._on_environment_config)
            self._settings.disturbancesChanged.connect(self._parent._on_disturbances_config)
            self._settings.beaconsChanged.connect(self._parent._on_beacons_config)
            try:
                self._settings.targetChanged.connect(self._parent._on_target_selected)
            except Exception as e:
                log.debug("settings target wiring skipped: %s", e)
            try:
                self._settings.thresholdChanged.connect(self._parent._on_threshold)
            except Exception as e:
                log.debug("settings threshold wiring skipped: %s", e)
        self._settings.show()
        self._settings.raise_()
        self._settings.activateWindow()

    def drop_settings(self) -> None:
        """Close and discard the settings dialog so stale panel values vanish."""
        try:
            if self._settings is not None:
                self._settings.close()
        except Exception as e:
            log.debug("drop settings skipped: %s", e)
        self._settings = None

    def close_all(self) -> None:
        for attr in ("_settings", "_dashboard_window"):
            try:
                w = getattr(self, attr, None)
                if w is not None:
                    w.close()
            except Exception as e:
                log.debug("close window skipped: %s", e)

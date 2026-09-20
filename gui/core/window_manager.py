# gui/core/window_manager.py - Owns secondary windows (creation/reuse/geometry).
# Simulator window (MainWindow) and Live Dashboard window are fully separate
# top-level windows; this manager creates/reuses them without mixing content.
from __future__ import annotations

import logging

from PyQt5.QtCore import Qt

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
            try:
                self._dashboard_window.setAttribute(Qt.WA_DeleteOnClose)
                self._dashboard_window.destroyed.connect(self._on_dashboard_destroyed)
            except Exception as e:
                log.debug("dashboard delete-on-close skipped: %s", e)
        return self._dashboard_window

    def _on_dashboard_destroyed(self) -> None:
        self._dashboard_window = None

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

    # -- Settings / Control Deck (own dialog) ---------------------------
    def show_settings(self, session, fullscreen: bool = True):
        from gui.views.settings_dialog import SettingsDialog
        if self._settings is None:
            self._settings = SettingsDialog(session, self._parent)
            self._settings.environmentChanged.connect(self._parent._on_environment_config)
            self._settings.disturbancesChanged.connect(self._parent._on_disturbances_config)
        try:
            if fullscreen and not self._settings.isFullScreen():
                self._settings.showFullScreen()
                self._settings._fullscreen = True
                self._settings.btn_fullscreen.setText("Exit Full Screen")
            else:
                self._settings.show()
            self._settings.raise_()
            self._settings.activateWindow()
        except Exception as e:
            log.debug("show settings failed: %s", e)

    def drop_settings(self) -> None:
        """Close and discard the settings dialog so stale panel values vanish."""
        try:
            if self._settings is not None:
                self._settings.close()
                self._settings.deleteLater()
        except Exception as e:
            log.debug("drop settings skipped: %s", e)
        self._settings = None

    def sync_dialog(self, session) -> None:
        """Pull session truth back into open panel widgets (clamped values)."""
        if self._settings is None:
            return
        try:
            self._settings.sync_from_session(session)
        except Exception as e:
            log.debug("dialog sync skipped: %s", e)

    def close_all(self) -> None:
        for attr in ("_settings", "_dashboard_window"):
            try:
                w = getattr(self, attr, None)
                if w is not None:
                    w.close()
                    w.deleteLater()
            except Exception as e:
                log.debug("close window skipped: %s", e)
        self._settings = None
        self._dashboard_window = None

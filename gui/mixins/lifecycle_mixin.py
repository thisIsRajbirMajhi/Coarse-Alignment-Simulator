# gui/mixins/lifecycle_mixin.py - Start/Pause/Reset/Export/close
# Extracted from gui/main_window.py lifecycle (200 lines).

import time
from PyQt5.QtWidgets import QMessageBox
from disturbance import disturbances as dist
from gui.styles import TICK_MS


class LifecycleMixin:
    """Mixin: Simulation lifecycle (start/pause/reset/export/close)."""

    def _start(self):
        if not self._running:
            self._last_tick_time = time.time()
            if getattr(self, "_pause_time", None) is not None:
                self._pause_time = None
            self.timer.start(TICK_MS); self._running = True
            try: self._update_live_indicators()
            except Exception: pass
            self.statusBar().showMessage("Running", 2000)

    def _pause(self):
        if self._running:
            self.timer.stop(); self._running = False; self._pause_time = time.time()
            try: self._update_live_indicators()
            except Exception: pass
            self.statusBar().showMessage("Paused", 2000)
        else: self._pause_time = None

    def _reset(self):
        self.timer.stop(); self._running=False; self._pause_time=None
        try: self._update_live_indicators()
        except Exception: pass
        # Reset all panels to defaults
        try:
            from environment.config import EnvironmentConfig as _EC
            from camera.config import CameraConfig as _CC
            from target.config import MultiBeaconConfig as _MBC
            from control.config import ControllerConfig as _CtrlC
            # Environment to defaults (world 2000 per PDF min, configurable 2000..5000)
            if hasattr(self, "env_panel"):
                self.env_panel.set_config(_EC().validate(), emit=False)
                self.env_config = _EC().validate()
                self._scene_size = (int(self.env_config.world_width), int(self.env_config.world_height))
            # Camera to defaults (640x640, 4x3 deg, viewport 2000, god = world size, centre locked, 30Hz)
            if hasattr(self, "camera_panel"):
                self.camera_panel.set_config(_CC().validate(self._scene_size), emit=False)
                self.camera_config = _CC().validate(self._scene_size)
            # Beacons to defaults per PDF Sr11 Random location default (10x10 square, Circular, 60) within world
            if hasattr(self, "beacon_manager"):
                import random as _rnd
                try:
                    _ws, _hs = self._scene_size
                except Exception:
                    _ws, _hs = (2000, 2000)
                rx = _rnd.randint(200, max(201, _ws - 200))
                ry = _rnd.randint(200, max(201, _hs - 200))
                self.beacon_manager.set_config(_MBC(beacon_count=1, target_index=0, shape="square", size_w=10, size_h=10, x=rx, y=ry, profile="curved", speed=60, blinking=False, speed_random=False).validate(), emit=False)
                self.beacon_config = _MBC(beacon_count=1, target_index=0, shape="square", size_w=10, size_h=10, x=rx, y=ry, profile="curved", speed=60, blinking=False, speed_random=False).validate()
                self._beacon_count = 1; self._target_beacon_id = 0
                try:
                    self.beacon_manager.spin_thresh.setValue(200)
                except Exception: pass
            # Disturbances to 0 — full spec reset (all new modules to Clear/Off)
            try:
                from disturbance.config import DisturbanceConfig as _DCReset
                _dc_default = _DCReset().validate()
                self.disturbance_config = _dc_default
                if hasattr(self, "disturbances_panel") and hasattr(self.disturbances_panel, "set_config"):
                    self.disturbances_panel.set_config(_dc_default, emit=False)
                    # keep legacy alias in sync
                    try:
                        self.sliders = self.disturbances_panel.sliders
                    except Exception: pass
            except Exception:
                if hasattr(self, "sliders"):
                    for s in self.sliders.values():
                        try:
                            s.blockSignals(True); s.setValue(0); s.blockSignals(False)
                        except Exception: pass
                if hasattr(self, "disturbances_panel"):
                    for s in self.disturbances_panel.sliders.values():
                        try:
                            s.blockSignals(True); s.setValue(0); s.blockSignals(False)
                        except Exception: pass
            # Clear per-instance platform/jitter states
            try:
                if hasattr(self, "_platform_motion_state"): self._platform_motion_state.clear()
                if hasattr(self, "_jitter_state"): self._jitter_state.clear()
            except Exception: pass
            # Control to defaults (P, kp 0.15, 30Hz fixed)
            if hasattr(self, "control_panel"):
                self.control_panel.set_config(_CtrlC().validate(), emit=False)
                self.controller_config = _CtrlC().validate()
            # Global hidden tuning to defaults (motion curved, speed 60, thresh 200)
            if hasattr(self, "motion_combo"):
                self.motion_combo.blockSignals(True); self.motion_combo.setCurrentText("curved"); self.motion_combo.blockSignals(False)
            if hasattr(self, "speed_slider"):
                self.speed_slider.blockSignals(True); self.speed_slider.setValue(60); self.speed_slider.blockSignals(False)
                try: self.speed_slider._value_label.setText("60")
                except Exception: pass
            if hasattr(self, "thresh_slider"):
                self.thresh_slider.blockSignals(True); self.thresh_slider.setValue(200); self.thresh_slider.blockSignals(False)
                try: self.thresh_slider._value_label.setText("200")
                except Exception: pass
            self._target_speed = 60; self._det_thresh = 200; self._ctrl_gain = 0.15
            self._detector_min_area = 2; self._sim_speed = 1.0; self._global_brightness = 255; self._global_radius = 5
            self._last_detection = None; self._last_estimate = None; self._last_lock_state = "searching"
            self._hitbox_radius = 14; self._center_radius = 2
            # Clear dirty
            try:
                self._dirty_tabs.clear(); self._applied_snapshot.clear()
            except Exception: pass
        except Exception as e:
            print(f"Reset defaults error: {e}")
        self._build_simulation()
        try:
            self._invalidate_minimap_cache()
        except Exception: pass
        try:
            self._rebuild_per_beacon_panels()
            self._sync_per_beacon_xy_ranges()
        except Exception: pass
        self._camera_drift_state={}; self._platform_motion_state={}; self._jitter_state={}; self._last_tick_time=None; self._last_detection=None; self._last_estimate=None; self._last_lock_state="searching"
        try:
            if hasattr(self, "_reset_stats"):
                self._reset_stats()
        except Exception: pass
        # Reset disturbance global state
        try:
            dist.reset_disturbance_state()
            self._camera_drift_state.clear()
            if hasattr(self, "_platform_motion_state"): self._platform_motion_state.clear()
            if hasattr(self, "_jitter_state"): self._jitter_state.clear()
        except Exception:
            pass
        self.footer_lock.setText("SEARCHING"); self.lock_dot.setStyleSheet("color:#64748b; font-size:14px;")
        self.viewport_label.clear(); self.minimap_label.clear()
        # Force repaint for immediate visibility
        try:
            if hasattr(self, "dashboard_panel"):
                self.dashboard_panel.repaint()
                if hasattr(self.dashboard_panel, "graph"):
                    self.dashboard_panel.graph.plot.repaint()
            if hasattr(self, "dashboard_window"):
                self.dashboard_window.repaint()
        except Exception:
            pass
        self.statusBar().showMessage("Reset — ready", 2000)

    def _export_log(self):
        QMessageBox.information(self, "Export", "Logging has been removed — no data to export.")

    def closeEvent(self, event):
        try:
            if hasattr(self, "timer"):
                self.timer.stop()
        except Exception:
            pass
        try:
            for t in getattr(self, "_auto_timers", {}).values():
                try:
                    t.stop()
                except Exception:
                    pass
        except Exception:
            pass
        super().closeEvent(event)

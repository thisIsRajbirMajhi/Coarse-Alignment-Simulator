# gui/mixins/lifecycle_mixin.py - Start/Pause/Reset/Export/close
# Extracted from gui/main_window.py lifecycle (200 lines).

import os
import random
import time
from datetime import datetime  # noqa
import numpy as np  # noqa
from PyQt5.QtWidgets import QFileDialog, QMessageBox  # noqa
from disturbance import disturbances as dist  # noqa
from environment.config import EnvironmentConfig  # noqa
from camera.config import CameraConfig  # noqa
from target.config import MultiBeaconConfig  # noqa
from control.config import ControllerConfig  # noqa
from perf_log.metrics import PerformanceLogger  # noqa
from gui.styles import TICK_MS  # noqa


class LifecycleMixin:
    """Mixin: Simulation lifecycle (start/pause/reset/export/close)."""

    def _start(self):
        if not self._running:
            # FIX: use monotonic pause offset via logger.adjust_for_pause; start fresh if never started
            if self.perf.start_time is None and getattr(self.perf, "_start_mono", None) is None:
                # capture config snapshot for reproducibility
                try:
                    cfg_snap = {}
                    if hasattr(self, "env_config"):
                        cfg_snap.update({f"env_{k}": v for k, v in self.env_config.to_dict().items()})
                    if hasattr(self, "camera_config"):
                        cfg_snap.update({f"cam_{k}": v for k, v in self.camera_config.to_dict().items()})
                    if hasattr(self, "controller_config"):
                        cfg_snap.update({f"ctrl_{k}": v for k, v in self.controller_config.to_dict().items()})
                    if hasattr(self, "disturbance_config"):
                        try:
                            cfg_snap.update({f"dist_{k}": v for k, v in self.disturbance_config.to_dict().items()})
                        except: pass
                    cfg_snap["world_size"] = getattr(self, "_scene_size", None)
                    cfg_snap["fov_size"] = getattr(self, "_fov_size", None)
                    self.perf.start(prefix="simulation", config=cfg_snap)
                except Exception:
                    self.perf.start()
            self._last_tick_time = time.time()
            if getattr(self, "_pause_time", None) is not None:
                # adjust logger elapsed to exclude paused wall time (monotonic)
                try:
                    pause_dur = time.time() - self._pause_time
                    if hasattr(self.perf, "adjust_for_pause"):
                        self.perf.adjust_for_pause(pause_dur)
                    else:
                        # fallback wall adjustment
                        self.perf.start_time += pause_dur
                        if hasattr(self.perf, "_start_mono") and self.perf._start_mono is not None:
                            self.perf._start_mono += pause_dur
                except Exception:
                    pass
                self._pause_time = None
            self.timer.start(TICK_MS); self._running = True
            try: self._update_live_indicators()
            except: pass
            self.statusBar().showMessage("Running — tracking…", 2000)

    def _pause(self):
        if self._running:
            self.timer.stop(); self._running = False; self._pause_time = time.time()
            try: self._update_live_indicators()
            except: pass
            self.statusBar().showMessage("Paused", 2000)
        else: self._pause_time = None

    def _reset(self):
        self.timer.stop(); self._running=False; self._pause_time=None
        try: self._update_live_indicators()
        except: pass
        try:
            if hasattr(self, "perf") and hasattr(self.perf, "close"):
                self.perf.close()
        except: pass
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
            # Beacons to defaults (1, square 10x10, Circular, 60, threshold 200, no blink, no random, centre 2500)
            if hasattr(self, "beacon_manager"):
                self.beacon_manager.set_config(_MBC(beacon_count=1, target_index=0, shape="square", size_w=10, size_h=10, x=2500, y=2500, profile="curved", speed=60, blinking=False, speed_random=False).validate(), emit=False)
                self.beacon_config = _MBC(beacon_count=1, target_index=0, shape="square", size_w=10, size_h=10, x=2500, y=2500, profile="curved", speed=60, blinking=False, speed_random=False).validate()
                self._beacon_count = 1; self._target_beacon_id = 0
                try:
                    self.beacon_manager.spin_thresh.setValue(200)
                except: pass
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
                    except: pass
            except:
                if hasattr(self, "sliders"):
                    for s in self.sliders.values():
                        try:
                            s.blockSignals(True); s.setValue(0); s.blockSignals(False)
                        except: pass
                if hasattr(self, "disturbances_panel"):
                    for s in self.disturbances_panel.sliders.values():
                        try:
                            s.blockSignals(True); s.setValue(0); s.blockSignals(False)
                        except: pass
            # Clear per-instance platform/jitter states
            try:
                if hasattr(self, "_platform_motion_state"): self._platform_motion_state.clear()
                if hasattr(self, "_jitter_state"): self._jitter_state.clear()
            except: pass
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
                except: pass
            if hasattr(self, "thresh_slider"):
                self.thresh_slider.blockSignals(True); self.thresh_slider.setValue(200); self.thresh_slider.blockSignals(False)
                try: self.thresh_slider._value_label.setText("200")
                except: pass
            self._target_speed = 60; self._det_thresh = 200; self._ctrl_gain = 0.15
            self._tracker_smoothing = 0.25; self._tracker_miss_limit = 5; self._detector_min_area = 2; self._sim_speed = 1.0; self._global_brightness = 255; self._global_radius = 5
            self._hitbox_radius = 14; self._center_radius = 2
            # Clear dirty
            try:
                self._dirty_tabs.clear(); self._applied_snapshot.clear()
            except: pass
        except Exception as e:
            print(f"Reset defaults error: {e}")
        self._build_simulation()
        try:
            self._invalidate_minimap_cache()
        except: pass
        try:
            self._rebuild_per_beacon_panels()
            self._sync_per_beacon_xy_ranges()
        except: pass
        self.perf=PerformanceLogger(); self._camera_drift_state={}; self._platform_motion_state={}; self._jitter_state={}; self._last_tick_time=None
        # FIX: reset dashboard history immediately so graph clears on reset (not lazy on next tick)
        try:
            if hasattr(self, "dashboard_panel") and hasattr(self.dashboard_panel, "reset_history"):
                self.dashboard_panel.reset_history()
        except Exception:
            pass
        # Reset disturbance global state — fixes stale phase/velocity on fresh run (reproducibility)
        try:
            dist.reset_disturbance_state()
            # Also clear per-instance drift / platform / jitter dicts (already {}) and any module globals
            self._camera_drift_state.clear()
            if hasattr(self, "_platform_motion_state"): self._platform_motion_state.clear()
            if hasattr(self, "_jitter_state"): self._jitter_state.clear()
        except Exception:
            pass
        # Proper reset: show initial 0 values with correct units (not "-") so no field appears empty
        try:
            if hasattr(self, "dashboard_panel") and hasattr(self.dashboard_panel, "update_from_summary"):
                # tracker is newly created via _build_simulation, use its status
                init_status = getattr(getattr(self, "tracker", None), "status", None)
                init_status = init_status.value if hasattr(init_status, "value") else "searching"
                cam_scale = 0.035
                try:
                    if hasattr(self, "camera") and hasattr(self.camera, "config") and getattr(self.camera.config, "pixel_scale_mrad", None) is not None:
                        cam_scale = float(self.camera.config.pixel_scale_mrad)
                except Exception:
                    pass
                self.dashboard_panel.update_from_summary(self.perf.summary(), init_status, None, camera_scale_mrad=cam_scale)
        except Exception:
            # Fallback: set labels to 0 with units
            for lbl in self.stat_labels.values():
                try:
                    lbl.setText("0.0")
                except: pass
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
        log_dir = getattr(self.perf, "log_dir", "log")
        default_name = os.path.join(log_dir, f"simulation_export_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv")
        path, _ = QFileDialog.getSaveFileName(self, "Export performance log", default_name, "CSV (*.csv);;JSON (*.json)")
        if path:
            try:
                self.perf.export_report(path)
                QMessageBox.information(self, "Export", f"Saved to:\n{path}")
            except Exception as e:
                QMessageBox.critical(self, "Export failed", str(e))

    def closeEvent(self, event):
        # FIX: ensure logger file closed on app exit (prevents leak / data loss)
        try:
            if hasattr(self, "perf") and hasattr(self.perf, "close"):
                self.perf.close()
        except Exception:
            pass
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

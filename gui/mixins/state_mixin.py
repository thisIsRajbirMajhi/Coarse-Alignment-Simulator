"""
Module: gui.mixins.state_mixin
Purpose: Dirty-tracking, HOT apply/discard, snapshots, debounced auto-apply.
Public API: StateMixin
Notes: Extracted from MainWindow monolith — modular, well-commented.
       MainWindow inherits this mixin to keep sectioned state logic separate.
"""

from PyQt5.QtCore import QTimer
from PyQt5.QtWidgets import QMessageBox

# ============================================================
# SECTION: StateMixin — HOT dirty + snapshot management
# ============================================================

class StateMixin:
    """
    Mixin for per-section dirty tracking.

    Sections: global | beacons | camera | environment | disturbances
    - mark_dirty(section) highlights apply button
    - schedule_auto() debounces HOT reloads
    - snapshot / discard handles typed config dicts (environment/beacons)
    """

    # --------------------------------------------------------
    # Dirty marking
    # --------------------------------------------------------

    def _mark_dirty(self, section: str):
        self._dirty_tabs.add(section)
        btn_map = {
            "global": getattr(self, "global_apply_btn", None),
            "beacons": getattr(self, "beacons_apply_btn2", None),
            "camera": getattr(self, "camera_apply_btn", None),
            "environment": getattr(self, "env_apply_btn", None),
            "disturbances": getattr(self, "disturbances_apply_btn", None),
        }
        btn = btn_map.get(section)
        if btn is not None:
            btn.setStyleSheet("background:#f59e0b; color:white; font-weight:700; border:none; border-radius:6px;")
            btn.setText(f"Apply {section.title()} — HOT ●")

    def _clear_dirty(self, section: str):
        self._dirty_tabs.discard(section)
        btn_map = {
            "global": getattr(self, "global_apply_btn", None),
            "beacons": getattr(self, "beacons_apply_btn2", None),
            "camera": getattr(self, "camera_apply_btn", None),
            "environment": getattr(self, "env_apply_btn", None),
            "disturbances": getattr(self, "disturbances_apply_btn", None),
        }
        btn = btn_map.get(section)
        if btn is not None:
            defaults = {
                "global": ("Apply Global — HOT", "#2563eb"),
                "beacons": ("Apply Beacons Section — HOT", "#2563eb"),
                "camera": ("Apply Camera — HOT", "#2563eb"),
                "environment": ("Apply Environment", "#2563eb"),
                "disturbances": ("Apply Disturbances — HOT", "#2563eb"),
            }
            txt, col = defaults.get(section, ("Apply", "#2563eb"))
            btn.setStyleSheet(f"background:{col}; color:white; font-weight:600; border:none; border-radius:6px;")
            btn.setText(txt)

    # --------------------------------------------------------
    # Apply / Discard per section (HOT)
    # --------------------------------------------------------

    def _apply_section(self, section: str, hot: bool = True):
        try:
            if section == "global":
                self._apply_global_tuning()
            elif section == "beacons":
                self._on_target_beacon_change(int(self.target_beacon_spin.value()))
            elif section == "camera":
                self._apply_camera_hot()
            elif section == "overlay":
                self._apply_overlay_hot()
            elif section == "environment":
                self._apply_scene_settings_hot()
            elif section == "disturbances":
                pass
            self._clear_dirty(section)
            self.statusBar().showMessage(f"{section.title()} applied — HOT, next tick", 3000)
        except Exception as e:
            QMessageBox.warning(self, f"Apply {section}", f"Failed: {e}")

    def _discard_section(self, section: str):
        try:
            snap = self._applied_snapshot.get(section)
            if snap is None:
                self.statusBar().showMessage(f"{section.title()} — nothing to discard", 2000)
                return
            if section == "environment" and snap and "world_width" in snap:
                try:
                    from environment.config import EnvironmentConfig
                    cfg = EnvironmentConfig.from_dict(snap).validate()
                    self.env_config = cfg
                    if hasattr(self, "env_panel"):
                        self.env_panel.set_config(cfg, emit=False)
                    self._scene_size = (int(cfg.world_width), int(cfg.world_height))
                except Exception:
                    for key, val in snap.items():
                        w = getattr(self, key, None)
                        if w is None: continue
                        try:
                            w.blockSignals(True)
                            if hasattr(w, "setValue"): w.setValue(val)
                            elif hasattr(w, "setCurrentText"): w.setCurrentText(val)
                            elif hasattr(w, "setChecked"): w.setChecked(bool(val))
                        finally:
                            w.blockSignals(False)
            elif section == "beacons" and snap and "beacon_count" in snap:
                try:
                    from target.config import MultiBeaconConfig
                    multi = MultiBeaconConfig.from_dict(snap).validate()
                    self.beacon_config = multi
                    self._beacon_count = int(multi.beacon_count)
                    self._target_beacon_id = int(multi.target_index)
                    if hasattr(self, "beacon_manager"):
                        self.beacon_manager.set_config(multi, emit=False)
                        self.per_beacon_panels = self.beacon_manager.get_per_beacon_panels()  # type: ignore
                    try:
                        self.beacon_count_spin.blockSignals(True); self.beacon_count_spin.setValue(int(multi.beacon_count)); self.beacon_count_spin.blockSignals(False)
                        self.target_beacon_spin.blockSignals(True); self.target_beacon_spin.setValue(int(multi.target_index)); self.target_beacon_spin.blockSignals(False)
                    except: pass
                except Exception:
                    for key, val in snap.items():
                        if key == "beacons": continue
                        w = getattr(self, key, None)
                        if w is None: continue
                        try:
                            w.blockSignals(True)
                            if hasattr(w, "setValue"): w.setValue(val)
                            elif hasattr(w, "setCurrentText"): w.setCurrentText(val)
                            elif hasattr(w, "setChecked"): w.setChecked(bool(val))
                        finally:
                            w.blockSignals(False)
            elif section == "camera" and snap and "fov_width" in snap:
                try:
                    from camera.config import CameraConfig
                    cam_cfg = CameraConfig.from_dict(snap).validate(self._scene_size if hasattr(self, "_scene_size") else None)
                    self.camera_config = cam_cfg
                    self._fov_size = (int(cam_cfg.fov_width), int(cam_cfg.fov_height))
                    self._viewport_display_size = (int(cam_cfg.viewport_width), int(cam_cfg.viewport_height))
                    self._god_display_size = (int(cam_cfg.god_width), int(cam_cfg.god_height))
                    if hasattr(self, "camera_panel"):
                        self.camera_panel.set_config(cam_cfg, emit=False)
                        # Sync aliases
                        for attr in ["fov_w_spin","fov_h_spin","viewport_w_spin","viewport_h_spin","god_w_spin","god_h_spin","gain_spin"]:
                            try:
                                w = getattr(self, attr, None)
                                if w is not None:
                                    w.blockSignals(True)
                                    # value already set via panel, but keep alias in sync
                                    w.blockSignals(False)
                            except: pass
                    # Apply to live camera
                    try:
                        self.camera.apply_config(cam_cfg, scene_bounds=self._scene_size)
                    except: pass
                    # Update display sizes
                    try:
                        self.fov_res_lbl.setText(f"{int(cam_cfg.fov_width)}x{int(cam_cfg.fov_height)}")
                        from gui.core.renderer import Renderer, ScreenSpec
                        spec = ScreenSpec(viewport_w=int(cam_cfg.viewport_width), viewport_h=int(cam_cfg.viewport_height), god_w=int(cam_cfg.god_width), god_h=int(cam_cfg.god_height))
                        Renderer.apply_screen_sizes(self.viewport_label, self.minimap_label, spec)
                    except: pass
                except Exception:
                    for key, val in snap.items():
                        w = getattr(self, key, None)
                        if w is None: continue
                        try:
                            w.blockSignals(True)
                            if hasattr(w, "setValue"): w.setValue(val)
                            elif hasattr(w, "setCurrentText"): w.setCurrentText(val)
                            elif hasattr(w, "setChecked"): w.setChecked(bool(val))
                        finally:
                            w.blockSignals(False)
            elif section == "overlay" and snap and "crosshair_style" in snap:
                try:
                    from overlay.config import OverlayConfig
                    cfg = OverlayConfig.from_dict(snap).validate()
                    self.overlay_config = cfg
                    if hasattr(self, "overlay_panel"):
                        self.overlay_panel.set_config(cfg, emit=False)
                except Exception:
                    for key, val in snap.items():
                        w = getattr(self, key, None)
                        if w is None: continue
                        try:
                            w.blockSignals(True)
                            if hasattr(w, "setValue"): w.setValue(val)
                            elif hasattr(w, "setCurrentText"): w.setCurrentText(val)
                            elif hasattr(w, "setChecked"): w.setChecked(bool(val))
                        finally:
                            w.blockSignals(False)
            else:
                for key, val in snap.items():
                    w = getattr(self, key, None)
                    if w is None: continue
                    try:
                        w.blockSignals(True)
                        if hasattr(w, "setValue"): w.setValue(val)
                        elif hasattr(w, "setCurrentText"): w.setCurrentText(val)
                        elif hasattr(w, "setChecked"): w.setChecked(bool(val))
                    finally:
                        w.blockSignals(False)
            self._clear_dirty(section)
            self.statusBar().showMessage(f"{section.title()} discarded — reverted", 2500)
        except Exception as e:
            QMessageBox.warning(self, f"Discard {section}", f"Failed: {e}")

    def _master_apply_all(self):
        if self._dirty_tabs:
            ret = QMessageBox.question(self, "Apply All Sections",
                f"Apply all dirty sections? ({', '.join(sorted(self._dirty_tabs))}) — HOT (next tick).",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes)
            if ret != QMessageBox.Yes:
                return
        for sec in ["global", "beacons", "camera", "overlay", "environment", "disturbances"]:
            self._apply_section(sec, hot=True)
        self._dirty_tabs.clear()
        self.statusBar().showMessage("All sections applied — HOT", 3000)

    def _master_discard_all(self):
        if not self._dirty_tabs:
            self.statusBar().showMessage("Nothing dirty to discard", 2000)
            return
        ret = QMessageBox.question(self, "Discard All",
            f"Discard changes in: {', '.join(sorted(self._dirty_tabs))}?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if ret != QMessageBox.Yes:
            return
        for sec in list(self._dirty_tabs):
            self._discard_section(sec)
        self._dirty_tabs.clear()

    # --------------------------------------------------------
    # Snapshots — for discard
    # --------------------------------------------------------

    def _snapshot_section(self, section: str):
        try:
            if section == "global":
                self._applied_snapshot[section] = {
                    "motion_combo": self.motion_combo.currentText(),
                }
                # Optional tuning spins may not exist (removed per request)
                for attr in ["tracker_smoothing_spin", "tracker_miss_spin", "detector_min_area_spin", "sim_speed_spin", "global_brightness_spin", "global_radius_spin"]:
                    w = getattr(self, attr, None)
                    if w is not None:
                        try: self._applied_snapshot[section][attr] = w.value()
                        except: pass
            elif section == "camera":
                # Snapshot via CameraPanel (full 11 params) if available
                try:
                    if hasattr(self, "camera_panel") and self.camera_panel is not None:
                        self._applied_snapshot[section] = self.camera_panel.collect_config().to_dict()
                        # Include gain separately (stored in panel)
                        self._applied_snapshot[section]["gain_spin"] = self.camera_panel.gain_spin.value()
                    else:
                        self._applied_snapshot[section] = {
                            "fov_w_spin": self.fov_w_spin.value(),
                            "fov_h_spin": self.fov_h_spin.value(),
                            "viewport_w_spin": self.viewport_w_spin.value(),
                            "viewport_h_spin": self.viewport_h_spin.value(),
                            "god_w_spin": self.god_w_spin.value(),
                            "god_h_spin": self.god_h_spin.value(),
                            "gain_spin": self.gain_spin.value(),
                        }
                except Exception:
                    self._applied_snapshot[section] = {
                        "fov_w_spin": self.fov_w_spin.value(),
                        "fov_h_spin": self.fov_h_spin.value(),
                        "viewport_w_spin": self.viewport_w_spin.value(),
                        "viewport_h_spin": self.viewport_h_spin.value(),
                        "god_w_spin": self.god_w_spin.value(),
                        "god_h_spin": self.god_h_spin.value(),
                        "gain_spin": self.gain_spin.value(),
                    }
            elif section == "environment":
                try:
                    cfg_dict = self.env_panel.collect_config().to_dict() if hasattr(self, "env_panel") else self.env_config.to_dict()
                    self._applied_snapshot[section] = cfg_dict
                except Exception:
                    self._applied_snapshot[section] = {
                        "scene_w_spin": self.scene_w_spin.value(),
                        "scene_h_spin": self.scene_h_spin.value(),
                        "seed_spin": self.seed_spin.value(),
                        "haze_spin": self.haze_spin.value(),
                        "env_star_count_spin": self.env_star_count_spin.value(),
                        "env_star_brightness_spin": self.env_star_brightness_spin.value(),
                        "env_bg_top_spin": self.env_bg_top_spin.value(),
                        "env_bg_bottom_spin": self.env_bg_bottom_spin.value(),
                        "env_vignetting_spin": self.env_vignetting_spin.value(),
                        "env_dynamic_speed_spin": self.env_dynamic_speed_spin.value(),
                    }
            elif section == "disturbances":
                self._applied_snapshot[section] = {k: s.value() for k, s in self.sliders.items()}
            elif section == "beacons":
                try:
                    if hasattr(self, "beacon_manager"):
                        self._applied_snapshot[section] = self.beacon_manager.collect_multi_config().to_dict()
                    else:
                        self._applied_snapshot[section] = {
                            "beacon_count_spin": self.beacon_count_spin.value(),
                            "hitbox_spin": self.hitbox_spin.value(),
                            "center_spin": self.center_spin.value(),
                            "target_beacon_spin": self.target_beacon_spin.value(),
                        }
                except Exception:
                    self._applied_snapshot[section] = {
                        "beacon_count_spin": self.beacon_count_spin.value(),
                        "hitbox_spin": self.hitbox_spin.value(),
                        "center_spin": self.center_spin.value(),
                        "target_beacon_spin": self.target_beacon_spin.value(),
                    }
            elif section == "overlay":
                try:
                    if hasattr(self, "overlay_panel"):
                        self._applied_snapshot[section] = self.overlay_panel.collect_config().to_dict()
                    else:
                        self._applied_snapshot[section] = self.overlay_config.to_dict()
                except Exception:
                    try:
                        self._applied_snapshot[section] = self.overlay_config.to_dict()
                    except: pass
        except: pass

    # --------------------------------------------------------
    # Debounced HOT — every slider change auto-applies
    # --------------------------------------------------------

    def _schedule_auto(self, section: str, func, delay: int = 360):
        if section in ("global_controls",):
            func()
            return
        old = self._auto_timers.get(section)
        if old is not None:
            try: old.stop()
            except: pass
        t = QTimer(self)
        t.setSingleShot(True)
        t.timeout.connect(lambda: func())
        self._auto_timers[section] = t
        t.start(delay)

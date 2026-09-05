# gui/mixins/scene_mixin.py - Environment & Camera scene application (HOT)
# Extracted from gui/main_window.py::_apply_scene_settings_hot/_apply_camera_hot/_apply_scene_settings etc.

import numpy as np
import random
from PyQt5.QtWidgets import QMessageBox  # noqa
from environment.constants import MAX_RES, MIN_RES  # noqa
from gui.core.renderer import Renderer, ScreenSpec  # noqa


class SceneMixin:
    """Mixin: Environment & Camera hot-apply without pause, plus disturbance/env handlers."""

    def _randomize_seed(self): self.seed_spin.setValue(random.randint(0, 999999))

    def _on_env_config_changed(self, cfg):
        """Immediate handler — panel emitted a validated EnvironmentConfig."""
        try:
            cfg = cfg.validate()
            self.env_config = cfg
            self._scene_size = (int(cfg.world_width), int(cfg.world_height))
        except Exception:
            pass
        self._mark_dirty("environment")
        # Debounced apply (520ms) — every single spin is without spamming
        self._schedule_auto("environment", self._apply_scene_settings_hot, 520)

    def _on_disturbance_config_changed(self, cfg):
        """Immediate handler — DisturbancesPanel emitted validated DisturbanceConfig (full spec)."""
        try:
            cfg = cfg.validate() if hasattr(cfg, "validate") else cfg
            self.disturbance_config = cfg
        except Exception:
            pass
        self._mark_dirty("disturbances")
        self._schedule_auto("disturbances", self._apply_disturbances_hot, 120)

    def _apply_disturbances_hot(self):
        """Apply disturbances — , validates, snapss, no rebuild needed."""
        try:
            if hasattr(self, "disturbances_panel"):
                cfg = self.disturbances_panel.collect_config().validate()
                self.disturbance_config = cfg
            else:
                cfg = self.disturbance_config.validate()
            self._clear_dirty("disturbances")
            self._snapshot_section("disturbances")
            # Summary for status bar
            parts = []
            if cfg.turbulence or cfg.vibration or cfg.camera_motion or cfg.noise:
                parts.append(f"Legacy T{cfg.turbulence} V{cfg.vibration} C{cfg.camera_motion} N{cfg.noise}")
            if cfg.image_noise_enabled():
                en = []
                if cfg.enable_salt_pepper: en.append(f"S&P{cfg.salt_pepper_density*100:.0f}%")
                if cfg.enable_gaussian: en.append(f"Gaussσ{cfg.gaussian_sigma:.0f}")
                if cfg.enable_poisson: en.append("Poisson")
                parts.append("Img: " + "+".join(en) + f" maxσ{cfg.gaussian_sigma_max:.0f}")
            if cfg.camera_jitter > 0:
                parts.append(f"Jitter±{cfg.camera_jitter:.1f}px")
            if str(cfg.atmospheric_preset) != "Clear":
                parts.append(f"Atmo {cfg.atmospheric_preset} C{cfg.atmospheric_contrast:.0f}% B{cfg.atmospheric_brightness:.0f}%")
            if cfg.platform_speed > 0:
                parts.append(f"Plat {cfg.platform_profile} {cfg.platform_speed:.1f}px/f")
            msg = "Disturbances — " + " • ".join(parts) if parts else "Disturbances — pristine (Clear)"
            self.statusBar().showMessage(msg, 2500)
        except Exception as e:
            QMessageBox.warning(self, "Disturbances", f"Failed: {e}")

    def _apply_scene_settings_hot(self):
        """ — applies Environment from EnvironmentPanel + EnvironmentConfig (modular, no pause)."""
        # Collect validated EnvironmentConfig (single source of truth)
        try:
            cfg = self.env_panel.collect_config().validate() if hasattr(self, "env_panel") else self.env_config.validate()
            self.env_config = cfg
        except Exception:
            cfg = self.env_config.validate()
        sw, sh = int(cfg.world_width), int(cfg.world_height)
        # Camera / display sizes still live in Camera tab spins (not env) — read directly
        fw = int(np.clip(self.fov_w_spin.value(), 20, MAX_RES))
        fh = int(np.clip(self.fov_h_spin.value(), 20, MAX_RES))
        vw = int(np.clip(self.viewport_w_spin.value(), 50, MAX_RES))
        vh = int(np.clip(self.viewport_h_spin.value(), 50, MAX_RES))
        gw = int(np.clip(self.god_w_spin.value(), 50, MAX_RES))
        gh = int(np.clip(self.god_h_spin.value(), 50, MAX_RES))
        fw = min(fw, sw-10); fh = min(fh, sh-10)
        if fw<20: fw=20
        if fh<20: fh=20
        if sw*sh > 16_000_000:
            self.statusBar().showMessage(f"Large world {sw}×{sh} = {sw*sh/1e6:.1f} MP — cached thumb active", 3000)
        self._scene_size = (sw, sh); self._fov_size = (fw, fh)
        self._viewport_display_size = (vw, vh); self._god_display_size = (gw, gh)
        self.fov_res_lbl.setText(f"{fw}×{fh}"); self.god_res_lbl.setText(f"{sw}×{sh}")
        self.viewport_label.setMinimumSize(max(200, min(vw, 900)), max(140, min(vh, 700)))
        self.minimap_label.setMinimumSize(max(200, min(gw, 900)), max(140, min(gh, 700)))
        self.fov_w_spin.blockSignals(True); self.fov_w_spin.setValue(fw); self.fov_w_spin.blockSignals(False)
        self.fov_h_spin.blockSignals(True); self.fov_h_spin.setValue(fh); self.fov_h_spin.blockSignals(False)
        # Apply scene via typed config — delegates to scene.regenerate_from_config (modular builders)
        try:
            self.scene.regenerate_from_config(cfg)
        except Exception:
            # Fallback: legacy regenerate with explicit fields
            try:
                self.scene.regenerate(
                    width=sw, height=sh, seed=int(cfg.seed), dynamic=bool(cfg.dynamic),
                    haze_strength=float(cfg.haze_pct)/100.0,
                    bg_top=int(cfg.bg_top), bg_bottom=int(cfg.bg_bottom),
                    vignetting=float(cfg.vignetting_pct)/100.0,
                    star_count=int(cfg.star_count),
                    star_brightness_scale=float(cfg.star_brightness),
                    dynamic_speed=float(cfg.dynamic_speed),
                )
            except Exception:
                self._build_simulation()
                self.scene.regenerate_from_config(cfg)
        try:
            self._invalidate_minimap_cache()
        except Exception: pass
        # Camera — update scene bounds and re-validate ranges/home against new world (modular)
        # Sync vignetting (camera image-space) from env config to camera
        try:
            vig = float(cfg.vignetting_pct) / 100.0 if 'cfg' in locals() else float(getattr(self.env_config, 'vignetting_pct', 0)) / 100.0
            self.camera.set_vignetting(vig)
        except Exception:
            pass
        try:
            if hasattr(self, "camera_panel"):
                self.camera_panel.set_scene_bounds((sw, sh))
                cam_cfg2 = self.camera_panel.collect_config().validate((sw, sh))
                self.camera_config = cam_cfg2
            else:
                cam_cfg2 = self.camera_config.validate((sw, sh))
            self.camera.apply_config(cam_cfg2, scene_bounds=(sw, sh))
            self._fov_size = (int(cam_cfg2.fov_width), int(cam_cfg2.fov_height))
            self._viewport_display_size = (int(cam_cfg2.viewport_width), int(cam_cfg2.viewport_height))
            self._god_display_size = (int(cam_cfg2.god_width), int(cam_cfg2.god_height))
            from gui.core.renderer import Renderer as _R3, ScreenSpec as _S3
            try:
                spec = _S3(viewport_w=int(cam_cfg2.viewport_width), viewport_h=int(cam_cfg2.viewport_height), god_w=int(cam_cfg2.god_width), god_h=int(cam_cfg2.god_height))
                _R3.apply_screen_sizes(self.viewport_label, self.minimap_label, spec)
                self.fov_res_lbl.setText(f"{int(cam_cfg2.fov_width)}x{int(cam_cfg2.fov_height)}")
                self.god_res_lbl.setText(f"{sw}x{sh}")
            except Exception: pass
        except Exception:
            self.camera.scene_bounds = (sw, sh)
            self.camera.fov_width = fw; self.camera.fov_height = fh
            try:
                self.camera.go_home()
            except Exception:
                self.camera.set_position(sw/2, sh/2)
        for b in getattr(self, "beacons", [self.target]):
            try:
                if hasattr(b, "set_bounds"):
                    b.set_bounds((sw, sh))
                else:
                    b.bounds = (sw, sh)
                    b.x = float(np.clip(b.x, 0, sw)); b.y = float(np.clip(b.y, 0, sh))
            except Exception:
                b.bounds = (sw, sh)
                b.x = float(np.clip(b.x, 0, sw)); b.y = float(np.clip(b.y, 0, sh))
        self._camera_drift_state = {}
        try:
            self._sync_per_beacon_xy_ranges()
            for idx, b in enumerate(getattr(self, "beacons", [])):
                panel = self.per_beacon_panels[idx] if idx < len(getattr(self, "per_beacon_panels", [])) else None
                if not panel:
                    continue
                if isinstance(panel, dict):
                    panel["x"].blockSignals(True); panel["x"].setValue(int(b.x)); panel["x"].blockSignals(False)
                    panel["y"].blockSignals(True); panel["y"].setValue(int(b.y)); panel["y"].blockSignals(False)
                else:
                    panel.spin_x.blockSignals(True); panel.spin_x.setValue(int(b.x)); panel.spin_x.blockSignals(False)
                    panel.spin_y.blockSignals(True); panel.spin_y.setValue(int(b.y)); panel.spin_y.blockSignals(False)
        except Exception: pass
        self._snapshot_section("environment"); self._snapshot_section("camera")
        try:
            cam_scale = float(self.camera_config.pixel_scale_mrad)
            self.statusBar().showMessage(f"Environment/Camera — world {sw}x{sh} FOV {self.camera_config.fov_width}x{self.camera_config.fov_height} pan {self.camera_config.pan_min}:{self.camera_config.pan_max} scale {cam_scale:.3f}mrad/px", 3000)
        except Exception:
            self.statusBar().showMessage(f"Environment/Camera applied — world {sw}x{sh} FOV {fw}x{fh}", 3000)

    def _apply_camera_hot(self):
        """ — apply full CameraConfig (11 params: FOV, mechanics, display, units + gain)."""
        try:
            # Collect validated camera config (all 11 params) against current scene
            sw, sh = self._scene_size
            try:
                cam_cfg = self.camera_panel.collect_config().validate((sw, sh))
                self.camera_config = cam_cfg
            except Exception:
                cam_cfg = self.camera_config.validate((sw, sh))
            # Clamp FOV to scene (handles FOV > scene case)
            fw, fh = int(cam_cfg.fov_width), int(cam_cfg.fov_height)
            fw_raw, fh_raw = fw, fh
            fw = min(fw, sw-10); fh = min(fh, sh-10)
            if fw<20: fw=20
            if fh<20: fh=20
            if fw != fw_raw or fh != fh_raw:
                self.statusBar().showMessage(f"FOV {fw_raw}x{fh_raw} clipped to {fw}x{fh} to fit world {sw}x{sh}", 3000)
            cam_cfg.fov_width = int(fw); cam_cfg.fov_height = int(fh)
            self.camera_config = cam_cfg
            # Legacy mirrors for renderer
            self._fov_size = (fw, fh)
            self._viewport_display_size = (int(cam_cfg.viewport_width), int(cam_cfg.viewport_height))
            self._god_display_size = (int(cam_cfg.god_width), int(cam_cfg.god_height))
            vw, vh = self._viewport_display_size; gw, gh = self._god_display_size
            # Update display labels
            self.fov_res_lbl.setText(f"{fw}x{fh}")
            # Screens — on-screen sizes independent of FOV resolution
            from gui.core.renderer import ScreenSpec
            spec = ScreenSpec(viewport_w=vw, viewport_h=vh, god_w=gw, god_h=gh)
            from gui.core.renderer import Renderer as _R
            try:
                _R.apply_screen_sizes(self.viewport_label, self.minimap_label, spec)
            except Exception:
                self.viewport_label.setMinimumSize(max(200, min(vw, 900)), max(140, min(vh, 700)))
                self.minimap_label.setMinimumSize(max(200, min(gw, 900)), max(140, min(gh, 700)))
            # Reflect clamped FOV back to panel without re-triggering
            self.camera_panel.fov_w_spin.blockSignals(True); self.camera_panel.fov_w_spin.setValue(int(fw)); self.camera_panel.fov_w_spin.blockSignals(False)
            self.camera_panel.fov_h_spin.blockSignals(True); self.camera_panel.fov_h_spin.setValue(int(fh)); self.camera_panel.fov_h_spin.blockSignals(False)
            # Apply to PTZCamera — handles pan/tilt ranges, home, slew, resolution, latency, pixel scale
            try:
                self.camera.apply_config(cam_cfg, scene_bounds=(sw, sh))
                # Sync panel scene bounds for range validation
                self.camera_panel.set_scene_bounds((sw, sh))
            except Exception:
                # Fallback legacy direct assignment
                self.camera.fov_width = int(fw); self.camera.fov_height = int(fh)
                self.camera.scene_bounds = (sw, sh)
            # Gain — controller
            try: self.controller.gain = float(self.camera_panel.gain_spin.value())
            except Exception: pass
            self._snapshot_section("camera")
            # Report includes angular scale for units verification
            scale = float(cam_cfg.pixel_scale_mrad)
            self.statusBar().showMessage(f"Camera — FOV {fw}x{fh} pan [{int(cam_cfg.pan_min or 0)}:{int(cam_cfg.pan_max or sw)}] slew {cam_cfg.max_slew_rate:.0f}px/s lat {cam_cfg.latency_ms}ms scale {scale:.3f}mrad/px gain {self.controller.gain:.2f}", 3000)
        except Exception as e:
            QMessageBox.warning(self, "Camera Apply", f"Failed: {e}")

    def _apply_scene_settings(self):
        sw = int(np.clip(self.scene_w_spin.value(), MIN_RES, MAX_RES))
        sh = int(np.clip(self.scene_h_spin.value(), MIN_RES, MAX_RES))
        fw = int(np.clip(self.fov_w_spin.value(), 20, MAX_RES))
        fh = int(np.clip(self.fov_h_spin.value(), 20, MAX_RES))
        vw = int(np.clip(self.viewport_w_spin.value(), 50, MAX_RES))
        vh = int(np.clip(self.viewport_h_spin.value(), 50, MAX_RES))
        gw = int(np.clip(self.god_w_spin.value(), 50, MAX_RES))
        gh = int(np.clip(self.god_h_spin.value(), 50, MAX_RES))
        fw = min(fw, sw-10); fh = min(fh, sh-10)
        if fw<20: fw=20
        if fh<20: fh=20
        total_px = sw*sh
        if total_px > 16_000_000:
            self.statusBar().showMessage(f"Large world {sw}×{sh} = {total_px/1e6:.1f} MP — cached thumb active", 3000)
        self._scene_size = (sw, sh)
        self._fov_size = (fw, fh)
        self._viewport_display_size = (vw, vh)
        self._god_display_size = (gw, gh)
        # Update labels and minimums (responsive — minimum grows, but window remains resizable)
        self.fov_res_lbl.setText(f"{fw}×{fh}")
        self.god_res_lbl.setText(f"{sw}×{sh}")
        self.viewport_label.setMinimumSize(max(200, min(vw, 900)), max(140, min(vh, 700)))
        self.minimap_label.setMinimumSize(max(200, min(gw, 900)), max(140, min(gh, 700)))
        # reflect clamped FOV
        self.fov_w_spin.blockSignals(True); self.fov_w_spin.setValue(fw); self.fov_w_spin.blockSignals(False)
        self.fov_h_spin.blockSignals(True); self.fov_h_spin.setValue(fh); self.fov_h_spin.blockSignals(False)
        was_running = self._running
        if was_running: self._pause()
        # Use validated EnvironmentConfig for full fidelity (10 params, not just 3)
        try:
            cfg = self.env_panel.collect_config().validate() if hasattr(self, "env_panel") else self.env_config.validate()
            self.env_config = cfg
            # Overwrite cfg world size with the clamped sw/sh already computed above
            cfg.world_width = sw; cfg.world_height = sh
            self.scene.regenerate_from_config(cfg)
        except Exception:
            seed = int(self.seed_spin.value()); dynamic = bool(self.dynamic_check.isChecked()); haze = float(self.haze_spin.value())/100.0
            try:
                self.scene.regenerate(width=sw, height=sh, seed=seed, dynamic=dynamic, haze_strength=haze)
            except Exception:
                self._build_simulation()
                self.scene.regenerate(width=sw, height=sh, seed=seed, dynamic=dynamic, haze_strength=haze)
        try:
            self._invalidate_minimap_cache()
        except Exception: pass
        # Camera — apply full config (FOV, mechanics, display, units) with new scene bounds
        try:
            if hasattr(self, "camera_panel"):
                self.camera_panel.set_scene_bounds((sw, sh))
                cam_cfg2 = self.camera_panel.collect_config().validate((sw, sh))
                self.camera_config = cam_cfg2
            else:
                cam_cfg2 = self.camera_config.validate((sw, sh))
            self.camera.apply_config(cam_cfg2, scene_bounds=(sw, sh))
            self._fov_size = (int(cam_cfg2.fov_width), int(cam_cfg2.fov_height))
            self._viewport_display_size = (int(cam_cfg2.viewport_width), int(cam_cfg2.viewport_height))
            self._god_display_size = (int(cam_cfg2.god_width), int(cam_cfg2.god_height))
            from gui.core.renderer import Renderer as _R4, ScreenSpec as _S4
            try:
                spec = _S4(viewport_w=int(cam_cfg2.viewport_width), viewport_h=int(cam_cfg2.viewport_height), god_w=int(cam_cfg2.god_width), god_h=int(cam_cfg2.god_height))
                _R4.apply_screen_sizes(self.viewport_label, self.minimap_label, spec)
                self.fov_res_lbl.setText(f"{int(cam_cfg2.fov_width)}x{int(cam_cfg2.fov_height)}")
                self.god_res_lbl.setText(f"{sw}x{sh}")
            except Exception: pass
        except Exception:
            self.camera.scene_bounds = (sw, sh)
            self.camera.fov_width = fw; self.camera.fov_height = fh
            try:
                self.camera.go_home()
            except Exception:
                self.camera.set_position(sw/2, sh/2)
        for b in getattr(self, "beacons", [self.target]):
            try:
                if hasattr(b, "set_bounds"):
                    b.set_bounds((sw, sh))
                else:
                    b.bounds = (sw, sh)
                    b.x = float(np.clip(b.x, 0, sw)); b.y = float(np.clip(b.y, 0, sh))
            except Exception:
                b.bounds = (sw, sh)
                b.x = float(np.clip(b.x, 0, sw)); b.y = float(np.clip(b.y, 0, sh))
        self._camera_drift_state = {}
        try:
            self._sync_per_beacon_xy_ranges()
            for idx, b in enumerate(getattr(self, "beacons", [])):
                panel = self.per_beacon_panels[idx] if idx < len(getattr(self, "per_beacon_panels", [])) else None
                if not panel:
                    continue
                if isinstance(panel, dict):
                    panel["x"].blockSignals(True); panel["x"].setValue(int(b.x)); panel["x"].blockSignals(False)
                    panel["y"].blockSignals(True); panel["y"].setValue(int(b.y)); panel["y"].blockSignals(False)
                else:
                    panel.spin_x.blockSignals(True); panel.spin_x.setValue(int(b.x)); panel.spin_x.blockSignals(False)
                    panel.spin_y.blockSignals(True); panel.spin_y.setValue(int(b.y)); panel.spin_y.blockSignals(False)
        except Exception: pass
        try:
            scale = float(self.camera_config.pixel_scale_mrad)
            self.statusBar().showMessage(f"Applied world {sw}x{sh} FOV {self.camera_config.fov_width}x{self.camera_config.fov_height} scale {scale:.3f}mrad/px seed {seed} dynamic={dynamic}", 4000)
        except Exception:
            self.statusBar().showMessage(f"Applied world {sw}x{sh} FOV {fw}x{fh} seed {seed} dynamic={dynamic}", 4000)
        if was_running: self._start()

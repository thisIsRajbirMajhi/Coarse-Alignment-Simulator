# gui/mixins/tick_mixin.py - Main simulation tick (disturbances → render, no beacon_tracker)

import time
import numpy as np
import cv2  # noqa
from PyQt5.QtCore import Qt  # noqa
from disturbance import disturbances as dist  # noqa
from gui.core.renderer import Renderer, ScreenSpec  # noqa
from gui.styles import TICK_MS  # noqa


class TickMixin:
    """Mixin: Tick pipeline (beacon_tracker removed — open-loop)."""

    def _tick(self):
        frame_start=time.time()
        dt = TICK_MS/1000.0 if self._last_tick_time is None else float(np.clip(frame_start-self._last_tick_time,0.005,0.1))
        self._last_tick_time=frame_start
        sim_speed = 1.0
        self._sim_speed = float(sim_speed)
        dt_eff = float(np.clip(dt * sim_speed, 1e-4, 0.1))
        for b in getattr(self, "beacons", [self.target]):
            if getattr(b, "enabled", True):
                b.update(dt_eff)
        if hasattr(self, "beacons") and self.beacons:
            try:
                tid = int(self.target_beacon_spin.value()) if hasattr(self, "target_beacon_spin") else int(getattr(self, "_target_beacon_id", 0))
            except Exception:
                tid = int(getattr(self, "_target_beacon_id", 0))
            tid = int(np.clip(tid, 0, len(self.beacons)-1))
            self._target_beacon_id = tid
            self.target = self.beacons[tid]
        try:
            for idx, b in enumerate(getattr(self, "beacons", [])):
                panel = self.per_beacon_panels[idx] if idx < len(getattr(self, "per_beacon_panels", [])) else None
                if not panel:
                    continue
                if isinstance(panel, dict):
                    if not panel["x"].hasFocus() and not panel["y"].hasFocus():
                        panel["x"].blockSignals(True); panel["x"].setValue(int(b.x)); panel["x"].blockSignals(False)
                        panel["y"].blockSignals(True); panel["y"].setValue(int(b.y)); panel["y"].blockSignals(False)
                else:
                    if not panel.spin_x.hasFocus() and not panel.spin_y.hasFocus():
                        panel.spin_x.blockSignals(True); panel.spin_x.setValue(int(b.x)); panel.spin_x.blockSignals(False)
                        panel.spin_y.blockSignals(True); panel.spin_y.setValue(int(b.y)); panel.spin_y.blockSignals(False)
        except Exception: pass
        try: self.scene.update(dt_eff)
        except Exception: pass
        try:
            self.camera.update(dt)
        except Exception: pass
        try:
            dc = getattr(self, "disturbance_config", None)
            if dc is not None:
                dc = dc.validate() if hasattr(dc, "validate") else dc
        except Exception:
            dc = None
        if dc is None and hasattr(self, "sliders") and self.sliders:
            try:
                from disturbance.config import DisturbanceConfig as _FallbackDC
                dc = _FallbackDC(
                    turbulence=int(self.sliders["Turbulence"].value()) if "Turbulence" in self.sliders else 0,
                    vibration=int(self.sliders["Vibration"].value()) if "Vibration" in self.sliders else 0,
                    camera_motion=int(self.sliders["Camera Motion"].value()) if "Camera Motion" in self.sliders else 0,
                    noise=int(self.sliders["Noise"].value()) if "Noise" in self.sliders else 0,
                ).validate()
            except Exception:
                dc = None

        try:
            vig_strength = float(getattr(self.scene, 'vignetting', 0.0) or 0.0)
            if hasattr(self, 'env_config') and hasattr(self.env_config, 'vignetting_pct'):
                vig_strength = float(self.env_config.vignetting_pct) / 100.0
        except Exception:
            vig_strength = 0.0
        try:
            self.camera.set_vignetting(vig_strength)
        except Exception:
            pass
        use_optimized = hasattr(self.scene, 'get_region')
        fov_capture_x0 = None
        fov_capture_y0 = None

        def _get_fov_base(disturbed_pan, disturbed_tilt):
            if use_optimized:
                rp2, rt2 = self.camera.pan, self.camera.tilt
                self.camera.pan, self.camera.tilt = float(disturbed_pan), float(disturbed_tilt)
                try:
                    x0, y0, x1, y1 = self.camera.get_fov_rect()
                    base = self.scene.get_region(int(x0), int(y0), int(x1), int(y1))
                finally:
                    self.camera.pan, self.camera.tilt = rp2, rt2
                return base, (x0, y0)
            else:
                full = self.scene.get_frame()
                return full, None

        scene_frame = None

        _rng = getattr(self, "rng", None)
        if dc is not None:
            if not hasattr(self, "_platform_motion_state") or self._platform_motion_state is None:
                self._platform_motion_state = {}
            if not hasattr(self, "_camera_drift_state") or self._camera_drift_state is None:
                self._camera_drift_state = {}
            pan_a, tilt_a = dist.apply_platform_vibration(self.camera.pan, self.camera.tilt, int(getattr(dc, "vibration", 0)), dt=dt_eff, rng=_rng)
            if float(getattr(dc, "platform_speed", 0.0)) > 1e-9:
                pan_b, tilt_b = dist.apply_platform_motion(
                    pan_a, tilt_a,
                    profile=str(getattr(dc, "platform_profile", "Linear")),
                    speed_px_per_frame=float(getattr(dc, "platform_speed", 0.0)),
                    dt=dt_eff,
                    state=self._platform_motion_state,
                    bounds=self._scene_size,
                    rng=_rng,
                )
            else:
                pan_b, tilt_b = pan_a, tilt_a
            if float(getattr(dc, "camera_jitter", 0.0)) > 1e-9:
                pan_c, tilt_c = dist.apply_camera_jitter(pan_b, tilt_b, jitter_px=float(getattr(dc, "camera_jitter")), rng=_rng)
            else:
                pan_c, tilt_c = pan_b, tilt_b
            pan_dist, tilt_dist = dist.apply_camera_motion_with_state(
                pan_c, tilt_c, int(getattr(dc, "camera_motion", 0)), self._camera_drift_state, dt=dt_eff, rng=_rng
            )
            # Apply disturbed pan/tilt to camera — respects all camera params and scene bounds
            try:
                self.camera.set_position(float(pan_dist), float(tilt_dist))
            except Exception:
                self.camera.pan, self.camera.tilt = float(pan_dist), float(tilt_dist)
                try: self.camera._clamp_to_range()
                except Exception: pass
            if use_optimized:
                fov_x0, fov_y0, _, _ = self.camera.get_fov_rect()
                fov_capture_x0, fov_capture_y0 = fov_x0, fov_y0
                try:
                    x0, y0, x1, y1 = self.camera.get_fov_rect()
                    fov_frame = self.scene.get_region(int(x0), int(y0), int(x1), int(y1))
                except Exception:
                    fov_frame, fov_origin = _get_fov_base(pan_dist, tilt_dist)
                    fov_x0, fov_y0 = int(fov_origin[0]), int(fov_origin[1])
                self._draw_targets_fov(fov_frame, fov_x0, fov_y0)
                if vig_strength > 1e-3:
                    from environment.vignetting import apply_vignetting
                    fov_frame = apply_vignetting(fov_frame, vig_strength)
            else:
                fov_frame = self.camera.capture(scene_frame)
                fov_capture_x0, fov_capture_y0 = None, None
            fov_frame = dist.apply_turbulence(fov_frame, int(getattr(dc, "turbulence", 0)), dt=dt_eff, rng=_rng)
            preset = str(getattr(dc, "atmospheric_preset", "Clear"))
            contrast = float(getattr(dc, "atmospheric_contrast", 0.0))
            brightness = float(getattr(dc, "atmospheric_brightness", 0.0))
            if preset != "Clear" or contrast > 1e-9 or brightness > 1e-9:
                fov_frame = dist.apply_atmospheric_disturbance(
                    fov_frame, preset=preset, contrast_reduction=contrast, brightness_reduction=brightness, rng=_rng
                )
            if int(getattr(dc, "noise", 0)) > 0:
                fov_frame = dist.apply_sensor_noise(fov_frame, int(getattr(dc, "noise")), rng=_rng)
            if bool(getattr(dc, "enable_salt_pepper", False) or getattr(dc, "enable_gaussian", False) or getattr(dc, "enable_poisson", False)):
                fov_frame = dist.apply_image_noise(
                    fov_frame,
                    enable_salt_pepper=bool(getattr(dc, "enable_salt_pepper", False)),
                    enable_gaussian=bool(getattr(dc, "enable_gaussian", False)),
                    enable_poisson=bool(getattr(dc, "enable_poisson", False)),
                    salt_pepper_density=float(getattr(dc, "salt_pepper_density", 0.10)),
                    salt_pepper_ratio=float(getattr(dc, "salt_pepper_ratio", 0.50)),
                    gaussian_sigma=float(getattr(dc, "gaussian_sigma", 8.0)),
                    gaussian_sigma_max=float(getattr(dc, "gaussian_sigma_max", 20.0)),
                    poisson_scale=float(getattr(dc, "poisson_scale", 1.0)),
                    poisson_peak=float(getattr(dc, "poisson_peak", 100.0)),
                    rng=_rng,
                )
        else:
            pan_vib, tilt_vib = dist.apply_platform_vibration(self.camera.pan, self.camera.tilt, self.sliders["Vibration"].value(), dt=dt_eff, rng=_rng)
            pan_dist, tilt_dist = dist.apply_camera_motion_with_state(pan_vib, tilt_vib, self.sliders["Camera Motion"].value(), self._camera_drift_state, dt=dt_eff, rng=_rng)
            try:
                self.camera.set_position(float(pan_dist), float(tilt_dist))
            except Exception:
                self.camera.pan, self.camera.tilt = float(pan_dist), float(tilt_dist)
                try: self.camera._clamp_to_range()
                except Exception: pass
            if use_optimized:
                fov_x0, fov_y0, _, _ = self.camera.get_fov_rect()
                fov_capture_x0, fov_capture_y0 = fov_x0, fov_y0
                try:
                    x0, y0, x1, y1 = self.camera.get_fov_rect()
                    fov_frame = self.scene.get_region(int(x0), int(y0), int(x1), int(y1))
                except Exception:
                    fov_frame, fov_origin = _get_fov_base(pan_dist, tilt_dist)
                    fov_x0, fov_y0 = int(fov_origin[0]), int(fov_origin[1])
                self._draw_targets_fov(fov_frame, fov_x0, fov_y0)
                if vig_strength > 1e-3:
                    from environment.vignetting import apply_vignetting
                    fov_frame = apply_vignetting(fov_frame, vig_strength)
            else:
                fov_frame = self.camera.capture(scene_frame)
                fov_capture_x0, fov_capture_y0 = None, None
            fov_frame = dist.apply_turbulence(fov_frame, self.sliders["Turbulence"].value(), dt=dt_eff, rng=_rng)
            fov_frame = dist.apply_sensor_noise(fov_frame, self.sliders["Noise"].value(), rng=_rng)
        # No beacon_tracker — no detection
        all_dets: list[dict] = []
        self._last_all_detections = all_dets
        self._last_estimate = None
        self._last_lock_state = "searching"
        tracking_error_px = None
        try:
            self._render_viewport(fov_frame, None, all_dets)
        except Exception:
            pass
        try:
            self._render_minimap(scene_frame)
        except Exception:
            pass
        try:
            if hasattr(self, "dashboard_panel"):
                self.dashboard_panel.repaint()
                if hasattr(self.dashboard_panel, "graph"):
                    self.dashboard_panel.graph.plot.repaint()
        except Exception:
            pass

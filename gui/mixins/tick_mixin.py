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
        # Record every simulation frame; dashboard rendering is intentionally throttled.
        try:
            self._ensure_stats()
            if getattr(self, "_stats_last_tick", None) is not None:
                self._stats_proc.append((frame_start - self._stats_last_tick) * 1000.0)
            self._stats_last_tick = frame_start
            self._stats_frames += 1
        except Exception:
            pass
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
        # Closed-loop tracking (Phase 7) + Benchmark-2 video mode + metrics log.
        # GT is used ONLY for logger scoring, never for control.
        all_dets: list[dict] = []
        estimate = None
        tracking_error_px = None
        try:
            src = str(getattr(self, "_source", "live"))
            if src == "video" and getattr(self, "_video_cap", None) is not None:
                # --- Video-file mode: bypass PTZ, score file frames ---
                import cv2 as _cv2

                ok, vframe = self._video_cap.read()
                if not ok:
                    try:
                        self._video_cap.set(_cv2.CAP_PROP_POS_FRAMES, 0)
                        ok, vframe = self._video_cap.read()
                    except Exception:
                        pass
                if ok and vframe is not None:
                    try:
                        fw, fh = int(self._fov_size[0]), int(self._fov_size[1])
                        if (vframe.shape[1], vframe.shape[0]) != (fw, fh):
                            vframe = _cv2.resize(vframe, (fw, fh), interpolation=_cv2.INTER_AREA)
                    except Exception:
                        pass
                    fov_frame = vframe
                # Run pipeline without moving camera (PTZ bypassed)
                pipe = getattr(self, "_pipeline", None)
                if pipe is not None and fov_frame is not None:
                    try:
                        res = pipe.update(fov_frame, dt_eff)
                        all_dets = [d.to_dict() for d in res.all_detections]
                        estimate = res.estimate
                        tracking_error_px = res.error_px
                        self._last_lock_state = str(res.state)
                    except Exception:
                        pass
                self._last_all_detections = all_dets
                self._last_estimate = estimate
            else:
                # --- Live mode: frame -> pipeline -> PID -> camera.move (next frame) ---
                pipe = getattr(self, "_pipeline", None)
                enabled = bool(getattr(self, "_tracking_enabled", True))
                if pipe is not None and enabled and fov_frame is not None:
                    try:
                        # Keep pipeline FOV + controller in sync with panels
                        try:
                            pipe.fov_w, pipe.fov_h = int(self._fov_size[0]), int(self._fov_size[1])
                        except Exception:
                            pass
                        try:
                            thresh = None
                            if hasattr(self, "beacon_manager") and hasattr(self.beacon_manager, "spin_thresh"):
                                thresh = int(self.beacon_manager.spin_thresh.value())
                            elif hasattr(self, "thresh_slider"):
                                thresh = int(self.thresh_slider.value())
                            if thresh is not None:
                                pipe.detector_config.threshold = int(thresh)
                                try:
                                    pipe.detector.config.threshold = int(thresh)
                                except Exception:
                                    pass
                        except Exception:
                            pass
                        try:
                            if hasattr(self, "controller_config"):
                                pipe.controller_config = self.controller_config.validate()
                                pipe.controller_config.use_privileged_velocity = False
                                pipe.controller.apply_config(pipe.controller_config)
                        except Exception:
                            pass
                        res = pipe.update(fov_frame, dt_eff)
                        all_dets = [d.to_dict() for d in res.all_detections]
                        estimate = res.estimate
                        tracking_error_px = res.error_px
                        self._last_lock_state = str(res.state)
                        self._last_all_detections = all_dets
                        self._last_estimate = estimate
                        # Search scans the valid camera range until acquisition;
                        # PID motion remains state-gated inside the pipeline.
                        move_pan = float(res.d_pan)
                        move_tilt = float(res.d_tilt)
                        if res.state in ("searching", "lost"):
                            search = getattr(self, "_search_pattern", None)
                            if search is not None:
                                target_pan, target_tilt = search.step(
                                    self.camera.pan,
                                    self.camera.tilt,
                                    self.camera.get_pan_range(),
                                    self.camera.get_tilt_range(),
                                    dt_eff,
                                )
                                move_pan = target_pan - float(self.camera.pan)
                                move_tilt = target_tilt - float(self.camera.tilt)
                        # Apply motion for the next frame.
                        if abs(move_pan) > 1e-9 or abs(move_tilt) > 1e-9:
                            try:
                                self.camera.move(move_pan, move_tilt, dt_eff)
                            except Exception:
                                try:
                                    self.camera.move(move_pan, move_tilt)
                                except Exception:
                                    pass
                    except Exception:
                        self._last_all_detections = []
                else:
                    self._last_all_detections = []
                    self._last_estimate = None
                    if not hasattr(self, "_last_lock_state") or self._last_lock_state not in ("searching", "tracking", "lost", "detected", "reacquiring"):
                        self._last_lock_state = "searching"
            # --- Metrics log (GT only here) ---
            try:
                logger = getattr(self, "_metrics_logger", None)
                if logger is not None and fov_frame is not None:
                    tid = int(getattr(self, "_target_beacon_id", 0))
                    beacons = getattr(self, "beacons", [])
                    if beacons:
                        tid = int(np.clip(tid, 0, len(beacons) - 1))
                        b = beacons[tid]
                        try:
                            x0, y0, _, _ = self.camera.get_fov_rect()
                        except Exception:
                            x0, y0 = 0, 0
                        gx, gy = float(b.x) - float(x0), float(b.y) - float(y0)
                        fw, fh = int(self._fov_size[0]), int(self._fov_size[1])
                        vis = (0 <= gx < fw) and (0 <= gy < fh)
                        # Selected approximated as closest det to estimate
                        det_c = None
                        det_conf = None
                        try:
                            if all_dets and estimate is not None:
                                import math as _m

                                best = min(all_dets, key=lambda d: _m.dist(tuple(d.get("center", (0, 0))), tuple(estimate)))
                                det_c = tuple(best.get("center", (0, 0)))
                                det_conf = float(best.get("confidence", 0.0))
                            elif all_dets:
                                det_c = tuple(all_dets[0].get("center", (0, 0)))
                                det_conf = float(all_dets[0].get("confidence", 0.0))
                        except Exception:
                            pass
                        try:
                            vel = tuple(getattr(getattr(self, "_pipeline", None), "tracker", None).velocity) if getattr(getattr(self, "_pipeline", None), "tracker", None) is not None and getattr(getattr(self, "_pipeline", None).tracker, "initialized", False) else (0.0, 0.0)
                        except Exception:
                            vel = (0.0, 0.0)
                        try:
                            lat = float(getattr(getattr(self, "_pipeline", None).detector, "last_latency_ms", 0.0))
                        except Exception:
                            lat = 0.0
                        self._frame_id = int(getattr(self, "_frame_id", 0)) + 1
                        logger.log(
                            self._frame_id, (gx, gy), vis, det_c, det_conf,
                            estimate, vel, str(getattr(self, "_last_lock_state", "searching")),
                            lat,
                        )
            except Exception:
                pass
        except Exception:
            pass
        if not hasattr(self, "_last_all_detections"):
            self._last_all_detections = all_dets
        if not hasattr(self, "_last_estimate"):
            self._last_estimate = estimate
        try:
            self._render_viewport(fov_frame, self._last_estimate, self._last_all_detections)
        except Exception:
            pass
        # Throttle heavy UI (minimap + stats + dashboard) to every 3rd tick (~10Hz).
        # Viewport stays every tick (user watches FOV); control stays every tick (30Hz loop).
        try:
            self._tick_count = int(getattr(self, "_tick_count", 0)) + 1
        except Exception:
            self._tick_count = 1
        do_slow_ui = (int(getattr(self, "_tick_count", 1)) % 3 == 0)
        try:
            if do_slow_ui:
                self._render_minimap(scene_frame)
        except Exception:
            pass
        try:
            if do_slow_ui and hasattr(self, "_update_stats"):
                self._update_stats(tracking_error_px)
        except Exception:
            pass
        try:
            if do_slow_ui and hasattr(self, "dashboard_panel"):
                self.dashboard_panel.repaint()
                if hasattr(self.dashboard_panel, "graph"):
                    self.dashboard_panel.graph.plot.repaint()
        except Exception:
            pass

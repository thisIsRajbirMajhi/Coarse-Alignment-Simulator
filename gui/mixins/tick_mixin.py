# gui/mixins/tick_mixin.py - Main simulation tick (disturbances → detection → tracking → control → render)
# Extracted from gui/main_window.py::_tick (326 lines).
# Single Responsibility: Advance dt, apply disturbances, detect, gate, track, control, perf log.

import math
import time
import numpy as np
import cv2  # noqa
from PyQt5.QtCore import Qt  # noqa
from disturbance import disturbances as dist  # noqa
from tracking.tracker import LockStatus  # noqa
from gui.core.renderer import Renderer, ScreenSpec  # noqa
from gui.styles import TICK_MS  # noqa


class TickMixin:
    """Mixin: Tick pipeline."""

    def _tick(self):
        frame_start=time.time()
        dt = TICK_MS/1000.0 if self._last_tick_time is None else float(np.clip(frame_start-self._last_tick_time,0.005,0.1))
        self._last_tick_time=frame_start
        # Global sim speed scales physics dt (realtime configurable 0.2–3.0x)
        try:
            sim_speed = float(self.sim_speed_spin.value()) if hasattr(self, "sim_speed_spin") else float(getattr(self, "_sim_speed", 1.0))
        except Exception:
            sim_speed = float(getattr(self, "_sim_speed", 1.0))
        self._sim_speed = float(sim_speed)
        dt_eff = float(np.clip(dt * sim_speed, 1e-4, 0.1))
        # Update all enabled beacons (single update, dt_eff scaled by sim_speed)
        for b in getattr(self, "beacons", [self.target]):
            if getattr(b, "enabled", True):
                b.update(dt_eff)
        # Keep target alias exactly as user-selected (realtime, not auto-switching to distractor)
        if hasattr(self, "beacons") and self.beacons:
            try:
                tid = int(self.target_beacon_spin.value()) if hasattr(self, "target_beacon_spin") else int(getattr(self, "_target_beacon_id", 0))
            except Exception:
                tid = int(getattr(self, "_target_beacon_id", 0))
            tid = int(np.clip(tid, 0, len(self.beacons)-1))
            self._target_beacon_id = tid
            self.target = self.beacons[tid]
        # keep per-beacon X/Y spins in sync if beacons moved (optional live readout) — modular
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
                    # BeaconPanel object
                    if not panel.spin_x.hasFocus() and not panel.spin_y.hasFocus():
                        panel.spin_x.blockSignals(True); panel.spin_x.setValue(int(b.x)); panel.spin_x.blockSignals(False)
                        panel.spin_y.blockSignals(True); panel.spin_y.setValue(int(b.y)); panel.spin_y.blockSignals(False)
        except Exception: pass
        try: self.scene.update(dt_eff)
        except Exception: pass
        # Camera latency queue — advance time and execute due moves
        try:
            self.camera.update(dt)
        except Exception: pass
        # ── PERFORMANCE FIX: Optimized FOV rendering — crop first (640×640 ≈1.2M px)
        #   instead of rebuilding full 5000×5000 (75M px, 300 MB float32) every 33 ms.
        #   Scene.get_region(x0,y0,x1,y1) applies haze shimmer + twinkle only to
        #   visible FOV stars. Vignetting is now camera image-space (follows FOV),
        #   applied AFTER beacon photometry at capture stage.
        #   God-view (minimap) uses a lightweight static-background path.
        # ── Disturbances (full spec) — dt_eff ensures sim-speed lockstep ──
        # Order positional: Vibration → Platform Motion → Jitter → Drift (OU)
        # Order image: Vignetting (camera) → Turbulence → Atmospheric → Sensor/Image Noise
        # Try to use DisturbanceConfig as single source; fallback to legacy sliders
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

        # Determine vignetting strength for camera image-space (follows FOV)
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
        # Decide path: optimized if Scene has get_region
        use_optimized = hasattr(self.scene, 'get_region')
        # For detection, remember disturbed FOV origin (camera-stage vignetting follows disturbed pose)
        fov_capture_x0 = None
        fov_capture_y0 = None

        # Helper to get base FOV (gradient+haze+stars, no beacons, no vignetting)
        def _get_fov_base(disturbed_pan, disturbed_tilt):
            if use_optimized:
                # Temporarily set camera to disturbed pose to get correct FOV rect,
                # then fetch cropped region (only 640×640 work)
                rp2, rt2 = self.camera.pan, self.camera.tilt
                self.camera.pan, self.camera.tilt = float(disturbed_pan), float(disturbed_tilt)
                try:
                    x0, y0, x1, y1 = self.camera.get_fov_rect()
                    base = self.scene.get_region(int(x0), int(y0), int(x1), int(y1))
                finally:
                    self.camera.pan, self.camera.tilt = rp2, rt2
                return base, (x0, y0)
            else:
                # Fallback heavy path: full frame then crop (for compat without get_region)
                full = self.scene.get_frame()
                return full, None

        # For god-view minimap — use cached low-res thumb (no 5000×5000 copy).
        # Legacy full-copy path kept as fallback but not used in optimized render.
        scene_frame = None  # No longer needed; _render_minimap() uses cached thumb internally.
        # _draw_targets on full world skipped — minimap draws hitboxes via renderer on thumb.

        # Now handle disturbances + FOV capture — deterministic via self.rng (seeded from env_config.seed)
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
            # Optimized FOV base fetch
            if use_optimized:
                fov_frame, fov_origin = _get_fov_base(pan_dist, tilt_dist)
                fov_x0, fov_y0 = int(fov_origin[0]), int(fov_origin[1])
                fov_capture_x0, fov_capture_y0 = fov_x0, fov_y0
                # Draw beacons in FOV coords (projected)
                self._draw_targets_fov(fov_frame, fov_x0, fov_y0)
                # Vignetting camera-stage (image-space, follows FOV)
                if vig_strength > 1e-3:
                    from environment.vignetting import apply_vignetting
                    fov_frame = apply_vignetting(fov_frame, vig_strength)
            else:
                # Heavy fallback
                rp, rt = self.camera.pan, self.camera.tilt
                self.camera.pan, self.camera.tilt = pan_dist, tilt_dist
                fov_frame = self.camera.capture(scene_frame)
                self.camera.pan, self.camera.tilt = rp, rt
                # vignetting already applied via camera.capture if set
                fov_capture_x0, fov_capture_y0 = None, None
            # Image disturbances after vignetting — deterministic via _rng
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
            # Legacy fallback (no config) — still deterministic via _rng
            pan_vib, tilt_vib = dist.apply_platform_vibration(self.camera.pan, self.camera.tilt, self.sliders["Vibration"].value(), dt=dt_eff, rng=_rng)
            pan_dist, tilt_dist = dist.apply_camera_motion_with_state(pan_vib, tilt_vib, self.sliders["Camera Motion"].value(), self._camera_drift_state, dt=dt_eff, rng=_rng)
            if use_optimized:
                fov_frame, fov_origin = _get_fov_base(pan_dist, tilt_dist)
                fov_x0, fov_y0 = int(fov_origin[0]), int(fov_origin[1])
                fov_capture_x0, fov_capture_y0 = fov_x0, fov_y0
                self._draw_targets_fov(fov_frame, fov_x0, fov_y0)
                if vig_strength > 1e-3:
                    from environment.vignetting import apply_vignetting
                    fov_frame = apply_vignetting(fov_frame, vig_strength)
            else:
                rp, rt = self.camera.pan, self.camera.tilt
                self.camera.pan, self.camera.tilt = pan_dist, tilt_dist
                fov_frame = self.camera.capture(scene_frame)
                self.camera.pan, self.camera.tilt = rp, rt
                fov_capture_x0, fov_capture_y0 = None, None
            fov_frame = dist.apply_turbulence(fov_frame, self.sliders["Turbulence"].value(), dt=dt_eff, rng=_rng)
            fov_frame = dist.apply_sensor_noise(fov_frame, self.sliders["Noise"].value(), rng=_rng)
        # ── Target-only realtime check (not hardcoded, hitbox-gated) ──
        all_dets = self.detector.detect_all(fov_frame)
        self._last_all_detections = all_dets
        # Use disturbed FOV origin for detection when optimized path was used (camera moved)
        if fov_capture_x0 is not None and fov_capture_y0 is not None:
            fov_x0, fov_y0 = int(fov_capture_x0), int(fov_capture_y0)
        else:
            fov_x0, fov_y0, _, _ = self.camera.get_fov_rect()
        primary = self.target
        # If target beacon itself is disabled, treat as not in viewport — ignore distractors
        hitbox_hit = False
        center_hit = False
        if not getattr(primary, "enabled", True):
            detection = None
            proj_x = proj_y = float("nan")
            target_in_fov = False
        else:
            proj_x = primary.x - fov_x0
            proj_y = primary.y - fov_y0
            # Realtime hitbox-aware FOV test (large hitbox, not single pixel; dynamic per beacon)
            target_in_fov = (
                -primary.hitbox_radius <= proj_x <= self.camera.fov_width + primary.hitbox_radius and
                -primary.hitbox_radius <= proj_y <= self.camera.fov_height + primary.hitbox_radius
            )
            if not target_in_fov:
                # Target leaves viewport — do NOT bother with distractors, report miss
                detection = None
            else:
                # Multi-beacon robust gating: nearest-neighbor against last known target position
                # rather than blind brightest. Prevents latching onto brighter non-target distractor.
                # Gate center prefers tracker estimate (Kalman-predicted last position) over ground-truth
                # cheat, fallback to ground truth when no estimate (SEARCHING).
                gate_x, gate_y = proj_x, proj_y
                gate_radius = primary.hitbox_radius
                if self.tracker.estimated_position is not None and self.tracker.status != LockStatus.SEARCHING:
                    try:
                        # Use last filtered/Kalman estimate as gate (continuity)
                        gate_x, gate_y = float(self.tracker.estimated_position[0]), float(self.tracker.estimated_position[1])
                    except Exception:
                        gate_x, gate_y = proj_x, proj_y
                detection = None
                min_dist = float("inf")
                # First try gate around last estimate (or ground truth if no estimate)
                for d in all_dets:
                    dist_c = math.hypot(d["x"] - gate_x, d["y"] - gate_y)
                    if dist_c <= gate_radius and dist_c < min_dist:
                        min_dist = dist_c
                        detection = (d["x"], d["y"])
                # Fallback: if gate missed (e.g., fast maneuver) try ground-truth projection
                if detection is None and (gate_x != proj_x or gate_y != proj_y):
                    min_dist = float("inf")
                    for d in all_dets:
                        dist_c = math.hypot(d["x"] - proj_x, d["y"] - proj_y)
                        if dist_c <= primary.hitbox_radius and dist_c < min_dist:
                            min_dist = dist_c
                            detection = (d["x"], d["y"])
                if detection is not None:
                    hitbox_hit = True
                    center_hit = min_dist <= primary.center_radius
        # Kalman-aware update: pass dt_eff so filter can coast through dropout/occlusion
        try:
            estimate = self.tracker.update(detection, dt=float(dt_eff))
        except TypeError:
            estimate = self.tracker.update(detection)
        tracking_error_px=None
        # Error to perfect center (not hitbox edge) for precision metrics
        if estimate is not None:
            cx, cy = self.camera.fov_width/2, self.camera.fov_height/2
            err_x, err_y = estimate[0]-cx, estimate[1]-cy
            tracking_error_px=float(np.hypot(err_x, err_y))
            # Control — PID+FF with dead zone, adaptive, Smith, clamp respecting camera slew
            # Feedforward uses target velocity (ground truth for now; later tracker velocity for non-cheating)
            try:
                cam_slew = float(self.camera_config.max_slew_rate) if hasattr(self, "camera_config") else None
            except Exception: cam_slew = None
            # Target velocity for feedforward/Smith (px/s)
            # AI-ready: default uses tracker-estimated velocity (non-cheating); set use_privileged_velocity=True to use GT (legacy cheat)
            use_priv = bool(getattr(getattr(self, "controller_config", None), "use_privileged_velocity", False))
            vel = None
            if not use_priv:
                # Try tracker first (non-privileged)
                try:
                    if hasattr(self.tracker, "get_velocity"):
                        vel = self.tracker.get_velocity()
                    # Fallback to Kalman state if get_velocity returns None/zero
                    if vel is None:
                        if hasattr(self.tracker, "kalman") and hasattr(self.tracker.kalman, "state"):
                            st = getattr(self.tracker.kalman, "state", None)
                            if st is not None and len(st) >= 4:
                                vel = (float(st[2]), float(st[3]))
                except Exception: vel = None
                # If tracker has no velocity (e.g., SEARCHING), keep None (no feedforward) — do not fall back to GT
            else:
                try:
                    if hasattr(self, "target") and hasattr(self.target, "get_velocity"):
                        vel = self.target.get_velocity()
                    elif hasattr(self.tracker, "kalman") and hasattr(self.tracker.kalman, "state"):
                        st = getattr(self.tracker.kalman, "state", None)
                        if st is not None and len(st) >= 4:
                            vel = (float(st[2]), float(st[3]))
                except Exception: vel = None
            try:
                d_pan,d_tilt=self.controller.compute_correction(err_x, err_y, dt=dt_eff, camera_max_slew=cam_slew, target_velocity=vel)
            except TypeError:
                try:
                    d_pan,d_tilt=self.controller.compute_correction(err_x, err_y, dt=dt_eff, camera_max_slew=cam_slew)
                except TypeError:
                    d_pan,d_tilt=self.controller.compute_correction(err_x, err_y)
            try:
                self.camera.move(d_pan, d_tilt, dt_eff)
            except TypeError:
                # Back-compat fallback (PTZCamera without dt)
                self.camera.move(d_pan, d_tilt)
            # Reset search step when tracking (have estimate)
            try:
                self._search_step = 0
            except Exception:
                pass
        else:
            # No estimate — active search when SEARCHING (wires scanner.py spiral into tick)
            try:
                if self.tracker.status == LockStatus.SEARCHING:
                    if not hasattr(self, "_search_step"):
                        self._search_step = 0
                    self._search_step += 1
                    try:
                        from beacon_tracker.search.scanner import SearchingStrategy
                    except Exception:
                        SearchingStrategy = None
                    if SearchingStrategy is not None:
                        # Incremental spiral delta for smooth expanding coverage (k=6.0)
                        cur_dx, cur_dy = SearchingStrategy.spiral_offset(self._search_step, k=6.0)
                        prev_dx, prev_dy = SearchingStrategy.spiral_offset(self._search_step - 1, k=6.0) if self._search_step > 1 else (0.0, 0.0)
                        d_pan = float(np.clip((cur_dx - prev_dx) * 0.7, -14, 14))
                        d_tilt = float(np.clip((cur_dy - prev_dy) * 0.7, -14, 14))
                        try:
                            self.camera.move(d_pan, d_tilt, dt_eff)
                        except TypeError:
                            self.camera.move(d_pan, d_tilt)
                else:
                    # LOST etc without estimate — reset search
                    self._search_step = 0
            except Exception:
                pass
        is_locked=self.tracker.status==LockStatus.TRACKING
        # Real-time accurate: detected = primary hitbox hit (not any distractor) + dt for time accounting
        self.perf.log_frame(is_locked, tracking_error_px, time.time()-frame_start,
                            detected=hitbox_hit, hitbox_hit=hitbox_hit, center_hit=center_hit,
                            lock_state=self.tracker.status.value, dt=dt)
        # Rendering must not block dashboard — ensure _update_stats always runs
        try:
            self._render_viewport(fov_frame, estimate, all_dets)
        except Exception:
            pass
        try:
            self._render_minimap(scene_frame)
        except Exception:
            pass
        try:
            self._update_stats(tracking_error_px)
        except Exception:
            pass
        # Force dashboard repaint for real-time visibility
        try:
            if hasattr(self, "dashboard_panel"):
                self.dashboard_panel.repaint()
                if hasattr(self.dashboard_panel, "graph"):
                    self.dashboard_panel.graph.plot.repaint()
        except Exception:
            pass

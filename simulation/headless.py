# simulation/headless.py - Headless FSOC simulation for AI training (no Qt, deterministic, gym-compatible)
# Extracted from gui/mixins/simulation_mixin.py + tick_mixin.py + rendering_mixin.py
# Single responsibility: run closed-loop tracking without GUI, with seeded RNG thread-through.
# Fixes:
#   1) Headless API — step/reset/observe, no QApplication/QTimer/QLabel
#   2) Global RNG nondeterminism — all disturbances/camera use self.rng (common.rng.get_rng)
#   3) Privileged velocity — default tracker velocity (non-cheating), flag to enable GT

from __future__ import annotations

import math
import time
from dataclasses import dataclass
from typing import Any

import cv2
import numpy as np

from camera.config import CameraConfig
from camera.ptz_camera import PTZCamera
from common.rng import get_rng, seed_global
from control.config import ControllerConfig
from control.controller import PIDController
from beacon_tracker.detection.config import DetectorConfig
from beacon_tracker.detection.detector import BeaconDetector
from disturbance import disturbances as dist
from disturbance.config import DisturbanceConfig
from environment.config import EnvironmentConfig
from environment.scene import Scene
from gui.core.renderer import Renderer  # stateless, no Qt needed for array renders (set_pixmap is Qt, but render_viewport is pure)
from perf_log.metrics import PerformanceLogger
from target.config import MultiBeaconConfig
from target.motion import MotionProfile, create_beacons
from tracking.tracker import LockStatus, Tracker


@dataclass
class HeadlessConfig:
    """Aggregated config for HeadlessSimulation — all validated, single source."""
    seed: int = 42
    env: EnvironmentConfig | None = None
    camera: CameraConfig | None = None
    controller: ControllerConfig | None = None
    disturbance: DisturbanceConfig | None = None
    beacon: MultiBeaconConfig | None = None
    detector: DetectorConfig | None = None
    # detector is via BeaconDetector, tracker via TrackerConfig if needed
    max_steps: int = 2000
    dt: float = 1/30  # 33ms base
    sim_speed: float = 1.0
    # Privileged velocity flag is on controller_config (use_privileged_velocity), but also headless override
    use_privileged_velocity: bool | None = None  # None = respect controller_config, else override


class HeadlessSimulation:
    """
    Headless FSOC simulator — gym-like, deterministic, no Qt.

    Mirrors MainWindow tick pipeline but without GUI:
      beacons.update(dt_eff) → scene.update → camera.update → disturbances → capture → detect → gate → tracker → controller → camera.move → perf.log

    Usage:
        sim = HeadlessSimulation(seed=42)
        obs = sim.reset(seed=42)
        obs, reward, terminated, truncated, info = sim.step(action=None)  # action None => PID, else np.array([d_pan,d_tilt])
        obs, reward, ... = sim.step(np.array([2.0, -1.0]))  # direct action
    Determinism: all disturbance/camera RNG via self.rng (seeded); beacons/scene seeded via EnvironmentConfig.seed + self.rng.
    No global np.random leakage after seed_global.
    """

    def __init__(
        self,
        seed: int = 42,
        env_config: EnvironmentConfig | None = None,
        camera_config: CameraConfig | None = None,
        controller_config: ControllerConfig | None = None,
        disturbance_config: DisturbanceConfig | None = None,
        beacon_config: MultiBeaconConfig | None = None,
        detector_config: DetectorConfig | None = None,
        rng: np.random.Generator | None = None,
        max_steps: int = 2000,
        dt: float = 1/30,
        sim_speed: float = 1.0,
        use_privileged_velocity: bool | None = None,
    ):
        self.seed = int(seed)
        self.rng: np.random.Generator = get_rng(rng, self.seed)
        # Seed global for any legacy np.random fallbacks
        seed_global(self.seed)

        # Store dt and sim_speed
        self.dt = float(dt)
        self.sim_speed = float(sim_speed)
        self.max_steps = int(max_steps)
        self.step_count = 0
        self._use_priv_override = use_privileged_velocity

        # Configs — validated, with scene bounds handling
        self.env_config = (env_config or EnvironmentConfig()).validate()
        # Override seed from headless seed if not explicitly set
        if env_config is None:
            self.env_config.seed = self.seed
            self.env_config.validate()
        self._scene_size = (int(self.env_config.world_width), int(self.env_config.world_height))

        # Camera config 11 params
        if camera_config is None:
            # Default viewport/god from _scene_size etc. (single source: DISPLAY_DEFAULTS 2000)
            from gui.styles import FOV_SIZE  # noqa, for default FOV
            fov = FOV_SIZE
            self.camera_config = CameraConfig(
                fov_width=fov[0], fov_height=fov[1],
                viewport_width=2000, viewport_height=2000,
                god_width=2000, god_height=2000,
            ).validate(self._scene_size)
        else:
            self.camera_config = camera_config.validate(self._scene_size)

        self.controller_config = (controller_config or ControllerConfig()).validate()
        # Override privileged flag if headless param given
        if use_privileged_velocity is not None:
            self.controller_config.use_privileged_velocity = bool(use_privileged_velocity)
            self.controller_config.validate()

        self.disturbance_config = (disturbance_config or DisturbanceConfig()).validate()
        self.beacon_config = (beacon_config or MultiBeaconConfig(beacon_count=1, target_index=0)).validate()
        self.detector_config = (detector_config or DetectorConfig()).validate()

        # State dicts for disturbances (isolated per-sim)
        self._camera_drift_state: dict = {}
        self._platform_motion_state: dict = {}
        self._jitter_state: dict = {}
        self._search_step: int = 0

        # Build simulation objects
        self._build_simulation()

        # Perf logger (no auto_log file + no Qt)
        self.perf = PerformanceLogger(auto_log=False)
        self._start_time = None
        self._last_tick_time: float | None = None

        # For templated RNG per step, we keep self.rng advancing deterministically
        # No additional per-step seeding needed; just use self.rng for disturbances

    def _build_simulation(self):
        # Scene
        cfg = self.env_config.validate()
        self._scene_size = (int(cfg.world_width), int(cfg.world_height))
        self.scene = Scene(config=cfg)

        # Camera bounds sync
        sw, sh = self._scene_size
        cam_cfg = self.camera_config.validate((sw, sh))
        # Clamp FOV to scene
        fov_w = min(int(cam_cfg.fov_width), sw - 10)
        fov_h = min(int(cam_cfg.fov_height), sh - 10)
        cam_cfg.fov_width = max(20, fov_w)
        cam_cfg.fov_height = max(20, fov_h)
        self.camera_config = cam_cfg
        self._fov_size = (int(cam_cfg.fov_width), int(cam_cfg.fov_height))
        # Camera with rng for encoder/jitter determinism
        self.camera = PTZCamera(config=cam_cfg, scene_bounds=(sw, sh), rng=self.rng)
        # Vignetting follows env
        try:
            vig = float(cfg.vignetting_pct) / 100.0
            self.camera.set_vignetting(vig)
        except Exception: pass

        # Beacons
        bc = self.beacon_config.validate()
        beacon_count = int(bc.beacon_count)
        tgt_id = int(bc.target_index)
        shape = str(getattr(bc, "shape", "square"))
        size_w = int(getattr(bc, "size_w", 10))
        size_h = int(getattr(bc, "size_h", 10))
        blinking = bool(getattr(bc, "blinking", False))
        speed_random = bool(getattr(bc, "speed_random", False))
        tgt_x = float(getattr(bc, "x", sw/2))
        tgt_y = float(getattr(bc, "y", sh/2))
        try:
            profile = bc.profile  # may be MotionProfile or str
        except Exception:
            profile = MotionProfile.CURVED
        speed = float(getattr(bc, "speed", 60))
        # Deterministic base seed from headless seed + step_count for variety but reproducible
        base_seed = int(self.env_config.seed if self.env_config.seed is not None else self.seed) + int(self.step_count) % 997
        self.beacons = create_beacons(
            beacon_count, (sw, sh), profile, speed,
            seed=base_seed, hitbox_radius=14, center_radius=2,
            brightness=255, radius=5,
            shape=shape, size_w=size_w, size_h=size_h, blinking=blinking,
            x=tgt_x if beacon_count == 1 else None, y=tgt_y if beacon_count == 1 else None,
            speed_random=speed_random
        )
        tgt_id = int(np.clip(tgt_id, 0, max(0, len(self.beacons)-1)))
        self._target_beacon_id = tgt_id
        self.target = self.beacons[tgt_id] if self.beacons else self.beacons[0]

        # Detector / Tracker / Controller
        det_cfg = self.detector_config.validate()
        self.detector = BeaconDetector(brightness_threshold=int(det_cfg.brightness_threshold), min_area=int(det_cfg.min_area))
        # Also store max_beacons if present
        try:
            self.detector.max_beacons = int(det_cfg.max_beacons)
        except Exception: pass
        # Tracker from env? Use defaults 0.25/5 if not specified
        self.tracker = Tracker(smoothing=0.25, miss_limit=5)
        # If we had TrackerConfig, honor it
        try:
            from tracking.config import TrackerConfig
            # Try to get from controller? Not, use defaults
            pass
        except Exception: pass

        ctrl_cfg = self.controller_config.validate()
        self.controller = PIDController(config=ctrl_cfg)

        # Reset disturbance states
        self._camera_drift_state.clear()
        self._platform_motion_state.clear()
        self._jitter_state.clear()
        # Minimap thumb not needed headless, but keep for compat
        self._minimap_thumb = None

    # API

    def reset(self, seed: int | None = None) -> dict:
        """Reset simulation to initial state. If seed given, reseed deterministically."""
        if seed is not None:
            self.seed = int(seed)
            self.rng = get_rng(None, self.seed)
            seed_global(self.seed)
            # Update env seed for new beacons/scene
            self.env_config.seed = self.seed
            self.env_config.validate()
        self.step_count = 0
        self._camera_drift_state.clear()
        self._platform_motion_state.clear()
        self._jitter_state.clear()
        try:
            from disturbance.state import reset_disturbance_state
            reset_disturbance_state()
        except Exception: pass
        self._build_simulation()
        self.perf = PerformanceLogger(auto_log=False)
        self.perf.start()
        self._last_tick_time = None
        return self.get_observation()

    def get_observation(self) -> dict:
        """Return current observation dict without stepping."""
        # Build obs via current state (no new frame)
        # For headless we return last computed obs if available, else synthesize
        # Synthesize minimal obs: estimate, error, pan/tilt, fov
        try:
            est = self.tracker.estimated_position
        except Exception:
            est = None
        err = None
        if est is not None:
            cx, cy = self.camera.fov_width/2, self.camera.fov_height/2
            err = float(np.hypot(est[0]-cx, est[1]-cy))
        return {
            "estimate": est,
            "tracking_error_px": err,
            "lock_status": self.tracker.status.value if hasattr(self.tracker, "status") else "searching",
            "pan": float(self.camera.pan),
            "tilt": float(self.camera.tilt),
            "fov_rect": self.camera.get_fov_rect(),
            "world_size": self._scene_size,
            "fov_size": self._fov_size,
            "beacon_count": len(getattr(self, "beacons", [])),
            "target_id": getattr(self, "_target_beacon_id", 0),
            "step_count": self.step_count,
        }

    def step(self, action: np.ndarray | tuple | None = None, dt: float | None = None) -> tuple[dict, float, bool, bool, dict]:
        """
        Advance one tick.
        Args:
            action: None => use internal PID; else np.array([d_pan,d_tilt]) direct camera delta (headless control)
            dt: override dt for this step, else self.dt
        Returns:
            obs, reward, terminated, truncated, info
        """
        step_start = time.time()
        dt = float(dt if dt is not None else self.dt)
        # Apply sim_speed scaling
        dt_eff = float(np.clip(dt * self.sim_speed, 1e-4, 0.1))
        dt_wall = float(np.clip(dt, 0.005, 0.1))

        # Update beacons and scene
        for b in getattr(self, "beacons", [self.target]):
            if getattr(b, "enabled", True):
                b.update(dt_eff)
        # Keep target alias correct
        if hasattr(self, "beacons") and self.beacons:
            tid = int(np.clip(int(getattr(self, "_target_beacon_id", 0)), 0, len(self.beacons)-1))
            self.target = self.beacons[tid]

        try: self.scene.update(dt_eff)
        except Exception: pass
        try: self.camera.update(dt_wall)
        except Exception: pass

        # Disturbances with seeded rng
        dc = self.disturbance_config.validate() if hasattr(self.disturbance_config, "validate") else self.disturbance_config
        # Vignetting
        try:
            vig = float(getattr(self.env_config, "vignetting_pct", 0)) / 100.0
            self.camera.set_vignetting(vig)
        except Exception: vig = 0.0

        use_optimized = hasattr(self.scene, "get_region")
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
        # Positional disturbances
        pan_a, tilt_a = dist.apply_platform_vibration(self.camera.pan, self.camera.tilt, int(getattr(dc, "vibration", 0)), dt=dt_eff, rng=self.rng)
        if float(getattr(dc, "platform_speed", 0.0)) > 1e-9:
            pan_b, tilt_b = dist.apply_platform_motion(
                pan_a, tilt_a,
                profile=str(getattr(dc, "platform_profile", "Linear")),
                speed_px_per_frame=float(getattr(dc, "platform_speed", 0.0)),
                dt=dt_eff,
                state=self._platform_motion_state,
                bounds=self._scene_size,
                rng=self.rng,
            )
        else:
            pan_b, tilt_b = pan_a, tilt_a
        if float(getattr(dc, "camera_jitter", 0.0)) > 1e-9:
            pan_c, tilt_c = dist.apply_camera_jitter(pan_b, tilt_b, jitter_px=float(getattr(dc, "camera_jitter")), rng=self.rng)
        else:
            pan_c, tilt_c = pan_b, tilt_b
        pan_dist, tilt_dist = dist.apply_camera_motion_with_state(pan_c, tilt_c, int(getattr(dc, "camera_motion", 0)), self._camera_drift_state, dt=dt_eff, rng=self.rng)

        if use_optimized:
            fov_frame, fov_origin = _get_fov_base(pan_dist, tilt_dist)
            fov_x0, fov_y0 = int(fov_origin[0]), int(fov_origin[1])
            fov_capture_x0, fov_capture_y0 = fov_x0, fov_y0
            self._draw_targets_fov(fov_frame, fov_x0, fov_y0)
            if vig > 1e-3:
                from environment.vignetting import apply_vignetting
                fov_frame = apply_vignetting(fov_frame, vig)
        else:
            rp, rt = self.camera.pan, self.camera.tilt
            self.camera.pan, self.camera.tilt = pan_dist, tilt_dist
            fov_frame = self.camera.capture(scene_frame)
            self.camera.pan, self.camera.tilt = rp, rt
            fov_capture_x0, fov_capture_y0 = None, None

        fov_frame = dist.apply_turbulence(fov_frame, int(getattr(dc, "turbulence", 0)), dt=dt_eff, rng=self.rng)
        preset = str(getattr(dc, "atmospheric_preset", "Clear"))
        contrast = float(getattr(dc, "atmospheric_contrast", 0.0))
        brightness = float(getattr(dc, "atmospheric_brightness", 0.0))
        if preset != "Clear" or contrast > 1e-9 or brightness > 1e-9:
            fov_frame = dist.apply_atmospheric_disturbance(fov_frame, preset=preset, contrast_reduction=contrast, brightness_reduction=brightness, rng=self.rng)
        if int(getattr(dc, "noise", 0)) > 0:
            fov_frame = dist.apply_sensor_noise(fov_frame, int(getattr(dc, "noise")), rng=self.rng)
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
                rng=self.rng,
            )

        # Detection gating
        all_dets = self.detector.detect_all(fov_frame)
        self._last_all_detections = all_dets
        if fov_capture_x0 is not None and fov_capture_y0 is not None:
            fov_x0, fov_y0 = int(fov_capture_x0), int(fov_capture_y0)
        else:
            fov_x0, fov_y0, _, _ = self.camera.get_fov_rect()
        primary = self.target
        hitbox_hit = False
        center_hit = False
        if not getattr(primary, "enabled", True):
            detection = None
            target_in_fov = False
        else:
            proj_x = primary.x - fov_x0
            proj_y = primary.y - fov_y0
            target_in_fov = (-primary.hitbox_radius <= proj_x <= self.camera.fov_width + primary.hitbox_radius and
                             -primary.hitbox_radius <= proj_y <= self.camera.fov_height + primary.hitbox_radius)
            if not target_in_fov:
                detection = None
            else:
                gate_x, gate_y = proj_x, proj_y
                gate_radius = primary.hitbox_radius
                if self.tracker.estimated_position is not None and self.tracker.status != LockStatus.SEARCHING:
                    try:
                        gate_x, gate_y = float(self.tracker.estimated_position[0]), float(self.tracker.estimated_position[1])
                    except Exception:
                        gate_x, gate_y = proj_x, proj_y
                detection = None
                min_dist = float("inf")
                for d in all_dets:
                    dist_c = math.hypot(d["x"] - gate_x, d["y"] - gate_y)
                    if dist_c <= gate_radius and dist_c < min_dist:
                        min_dist = dist_c
                        detection = (d["x"], d["y"])
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

        try:
            estimate = self.tracker.update(detection, dt=float(dt_eff))
        except TypeError:
            estimate = self.tracker.update(detection)

        tracking_error_px = None
        if estimate is not None:
            cx, cy = self.camera.fov_width/2, self.camera.fov_height/2
            err_x, err_y = estimate[0]-cx, estimate[1]-cy
            tracking_error_px = float(np.hypot(err_x, err_y))
            # Control or direct action
            if action is not None:
                # Direct action: interpret as (d_pan, d_tilt) in px
                try:
                    arr = np.asarray(action, dtype=float).reshape(-1)
                    d_pan = float(arr[0]) if len(arr) > 0 else 0.0
                    d_tilt = float(arr[1]) if len(arr) > 1 else 0.0
                except Exception:
                    d_pan, d_tilt = 0.0, 0.0
                try:
                    self.camera.move(d_pan, d_tilt, dt_eff)
                except TypeError:
                    self.camera.move(d_pan, d_tilt)
            else:
                # PID with AI-ready velocity (tracker vs GT)
                try:
                    cam_slew = float(self.camera_config.max_slew_rate) if hasattr(self, "camera_config") else None
                except Exception: cam_slew = None
                # Velocity selection
                use_priv = bool(getattr(self.controller_config, "use_privileged_velocity", False))
                vel = None
                if not use_priv:
                    try:
                        if hasattr(self.tracker, "get_velocity"):
                            vel = self.tracker.get_velocity()
                        if vel is None and hasattr(self.tracker, "kalman") and hasattr(self.tracker.kalman, "state"):
                            st = getattr(self.tracker.kalman, "state", None)
                            if st is not None and len(st) >= 4:
                                vel = (float(st[2]), float(st[3]))
                    except Exception: vel = None
                else:
                    try:
                        if hasattr(self.target, "get_velocity"):
                            vel = self.target.get_velocity()
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
                    self.camera.move(d_pan, d_tilt)
            # Reset search when tracking
            try:
                if hasattr(self, "_search_step"):
                    self._search_step = 0
            except Exception:
                pass
        else:
            # No estimate: if action provided, still allow direct move (e.g., searching)
            if action is not None:
                try:
                    arr = np.asarray(action, dtype=float).reshape(-1)
                    d_pan = float(arr[0]) if len(arr) > 0 else 0.0
                    d_tilt = float(arr[1]) if len(arr) > 1 else 0.0
                    try: self.camera.move(d_pan, d_tilt, dt_eff)
                    except Exception: self.camera.move(d_pan, d_tilt)
                except Exception: pass
            else:
                # Active spiral search when SEARCHING and no external action
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
                            cur_dx, cur_dy = SearchingStrategy.spiral_offset(self._search_step, k=6.0)
                            prev_dx, prev_dy = SearchingStrategy.spiral_offset(self._search_step - 1, k=6.0) if self._search_step > 1 else (0.0, 0.0)
                            d_pan = float(np.clip((cur_dx - prev_dx) * 0.7, -14, 14))
                            d_tilt = float(np.clip((cur_dy - prev_dy) * 0.7, -14, 14))
                            try:
                                self.camera.move(d_pan, d_tilt, dt_eff)
                            except TypeError:
                                self.camera.move(d_pan, d_tilt)
                    else:
                        if hasattr(self, "_search_step"):
                            self._search_step = 0
                except Exception:
                    pass

        is_locked = self.tracker.status == LockStatus.TRACKING
        self.perf.log_frame(is_locked, tracking_error_px, time.time()-step_start,
                            detected=hitbox_hit, hitbox_hit=hitbox_hit, center_hit=center_hit,
                            lock_state=self.tracker.status.value, dt=dt_wall)

        self.step_count += 1
        # Reward: negative tracking error plus lock bonus, as example
        if tracking_error_px is not None:
            reward = -float(tracking_error_px) / 15.0  # 15px = 100% -> -1
            if is_locked:
                reward += 0.5
            # Center hit bonus
            if center_hit:
                reward += 0.3
        else:
            reward = -1.0 if not is_locked else -0.5

        terminated = False
        truncated = self.step_count >= self.max_steps
        # Optional termination on long lost: if lost > 5 seconds
        # Not enforced by default

        obs = self.get_observation()
        # Enrich obs with frame and detections for AI that wants image
        obs["frame"] = fov_frame  # uint8 HxWx3
        obs["all_detections"] = all_dets
        obs["tracking_error_px"] = tracking_error_px
        obs["hitbox_hit"] = hitbox_hit
        obs["center_hit"] = center_hit
        obs["is_locked"] = is_locked

        # Render viewport for debugging (optional, not Qt)
        try:
            obs["viewport"] = Renderer.render_viewport(fov_frame, self.camera, self.beacons, self.target, self.tracker, all_dets)
        except Exception:
            obs["viewport"] = fov_frame

        info = {
            "perf_summary": self.perf.summary(),
            "detection": detection,
            "estimate": estimate,
            "all_detections": all_dets,
            "fov_origin": (fov_x0, fov_y0),
        }
        return obs, float(reward), bool(terminated), bool(truncated), info

    def _draw_targets_fov(self, fov_frame: np.ndarray, fov_x0: int, fov_y0: int):
        """Draw beacons onto FOV frame — same as MainWindow._draw_targets_fov but headless."""
        beacons = getattr(self, "beacons", [self.target]) if hasattr(self, "beacons") else [self.target]
        h, w = fov_frame.shape[:2]
        fog_factor = 0.0
        bloom_base = 0.0
        try:
            fog_factor = float(getattr(self.env_config, "haze_pct", 0)) / 100.0 * 0.55
            preset = str(getattr(self.disturbance_config, "atmospheric_preset", "Clear")).lower()
            if preset == "fog":
                fog_factor = max(fog_factor, 0.45 + float(getattr(self.disturbance_config, "atmospheric_contrast", 0)) / 220.0)
                bloom_base = 0.10
            elif preset == "haze":
                fog_factor = max(fog_factor, 0.18)
            elif "low light" in preset:
                bloom_base = 0.12
            elif preset == "rain":
                fog_factor = max(fog_factor, 0.12)
        except Exception: pass
        fog_factor = float(np.clip(fog_factor, 0.0, 0.85))
        for beacon in beacons:
            if not getattr(beacon, "enabled", True):
                continue
            if getattr(beacon, "blinking", False) and not getattr(beacon, "_blink_visible", True):
                continue
            try:
                px = float(beacon.x) - float(fov_x0)
                py = float(beacon.y) - float(fov_y0)
            except Exception: continue
            if px < -40 or px > w + 40 or py < -40 or py > h + 40:
                continue
            try:
                brightness, radius = beacon.get_photometry()
            except Exception:
                brightness, radius = float(getattr(beacon, "brightness", 200)), float(getattr(beacon, "radius", 5))
            if brightness < 8:
                continue
            shape = str(getattr(beacon, "shape", "square"))
            size_w = int(getattr(beacon, "size_w", 10))
            size_h = int(getattr(beacon, "size_h", 10))
            motion_vector = (0.0, 0.0)
            bloom_strength = float(bloom_base)
            jitter_px = 0.0
            color_bgr = None
            try:
                if hasattr(beacon, "get_optics_params"):
                    opt = beacon.get_optics_params()
                    motion_vector = tuple(opt.get("motion_vector", (0.0, 0.0)))
                    bloom_strength = max(bloom_strength, float(opt.get("bloom_strength", 0.0)))
                    jitter_px = float(opt.get("aoa_jitter", 0.0)) * 0.25
                    bid = int(opt.get("beacon_id", 0))
                    try:
                        from target.optics import get_beacon_color_bgr
                        color_bgr = get_beacon_color_bgr(bid, float(brightness))
                    except Exception: color_bgr = None
                if float(brightness) > 210 and fog_factor > 0.2:
                    bloom_strength += 0.06
            except Exception: pass
            rendered = False
            try:
                from target.optics import render_beacon_patch
                patch = render_beacon_patch(
                    size_w=size_w, size_h=size_h, brightness=float(brightness),
                    shape=shape, motion_vector=motion_vector,
                    fog_factor=fog_factor, jitter_px=jitter_px,
                    bloom_strength=float(np.clip(bloom_strength, 0, 0.28)),
                    color_bgr=color_bgr,
                )
                ph, pw = patch.shape[:2]
                x0 = int(round(px - pw // 2))
                y0 = int(round(py - ph // 2))
                x1 = x0 + pw
                y1 = y0 + ph
                sx0 = max(0, x0); sy0 = max(0, y0)
                sx1 = min(w, x1); sy1 = min(h, y1)
                if sx1 > sx0 and sy1 > sy0:
                    px0 = sx0 - x0; py0 = sy0 - y0
                    px1 = px0 + (sx1 - sx0); py1 = py0 + (sy1 - sy0)
                    patch_crop = patch[py0:py1, px0:px1]
                    roi = fov_frame[sy0:sy1, sx0:sx1]
                    alpha = (patch_crop.astype(np.float32) / 255.0 * 0.88 + 0.12)
                    alpha = np.clip(alpha, 0, 1)
                    blended = roi.astype(np.float32) * (1 - alpha * 0.72) + patch_crop.astype(np.float32) * alpha
                    bright_mask = patch_crop.max(axis=2) > 165 if patch_crop.ndim == 3 else patch_crop > 165
                    if np.any(bright_mask):
                        if roi.ndim == 3:
                            blended[bright_mask] = np.maximum(blended[bright_mask], patch_crop[bright_mask].astype(np.float32) * 0.95)
                        else:
                            blended[bright_mask] = np.maximum(blended[bright_mask], patch_crop[bright_mask].astype(np.float32))
                    fov_frame[sy0:sy1, sx0:sx1] = np.clip(blended, 0, 255).astype(np.uint8)
                    rendered = True
            except Exception: rendered = False
            if not rendered:
                ix, iy = int(round(px)), int(round(py))
                try:
                    vib = Renderer.beacon_vibrant_color(int(getattr(beacon, "beacon_id", 0)), float(brightness))
                except Exception:
                    vib = (0, 255, 255)
                if shape == "square":
                    hw, hh = size_w // 2, size_h // 2
                    if max(size_w, size_h) > 6:
                        glow = tuple(int(c * 0.55) for c in vib)
                        cv2.rectangle(fov_frame, (ix - hw - 1, iy - hh - 1), (ix + hw + 1, iy + hh + 1), glow, -1, cv2.LINE_AA)
                    cv2.rectangle(fov_frame, (ix - hw, iy - hh), (ix + hw, iy + hh), vib, -1, cv2.LINE_AA)
                    cv2.rectangle(fov_frame, (ix - hw, iy - hh), (ix + hw, iy + hh), (255, 255, 255), 1, cv2.LINE_AA)
                else:
                    r = max(1, int(round(max(size_w, size_h) / 2)) if size_w and size_h else int(round(radius)))
                    if r > 3:
                        glow = tuple(int(c * 0.55) for c in vib)
                        cv2.circle(fov_frame, (ix, iy), r+1, glow, -1, cv2.LINE_AA)
                    cv2.circle(fov_frame, (ix, iy), max(1, r), vib, -1, cv2.LINE_AA)
                    cv2.circle(fov_frame, (ix, iy), 1, (255, 255, 255), -1, cv2.LINE_AA)

    def close(self):
        try:
            if hasattr(self, "perf") and hasattr(self.perf, "close"):
                self.perf.close()
        except Exception: pass

    # Gym-like helpers
    @property
    def observation_space(self):
        """Return dict describing observation shapes (for documentation, not gymnasium)."""
        # Image: FOV size from camera_config
        try:
            h, w = int(self.camera_config.fov_height), int(self.camera_config.fov_width)
        except Exception:
            h, w = 480, 640
        return {
            "frame": (h, w, 3),
            "estimate": (2,),
            "tracking_error_px": (1,),
            "lock_status": ["searching","acquired","tracking","lost"],
            "pan_tilt": (2,),
            "all_detections": "list[dict]",
        }

    @property
    def action_space(self):
        """Direct pan/tilt delta in px, clipped to [-output_clamp, output_clamp]."""
        try:
            clamp = float(self.controller_config.output_clamp)
        except Exception:
            clamp = 120.0
        return {"d_pan": (-clamp, clamp), "d_tilt": (-clamp, clamp), "shape": (2,)}


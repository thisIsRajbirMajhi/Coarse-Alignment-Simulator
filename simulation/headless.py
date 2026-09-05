# simulation/headless.py - Headless FSOC simulation (no Qt, deterministic, gym-compatible)
# beacon_tracker removed: no detection — image is produced but not analyzed. Control is open-loop (direct action only).

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
from disturbance import disturbances as dist
from disturbance.config import DisturbanceConfig
from environment.config import EnvironmentConfig
from environment.scene import Scene
from gui.core.renderer import Renderer
from target.config import MultiBeaconConfig
from target.motion import MotionProfile, create_beacons


@dataclass
class HeadlessConfig:
    """Aggregated config for HeadlessSimulation — all validated, single source."""
    seed: int = 42
    env: EnvironmentConfig | None = None
    camera: CameraConfig | None = None
    controller: ControllerConfig | None = None
    disturbance: DisturbanceConfig | None = None
    beacon: MultiBeaconConfig | None = None
    max_steps: int = 2000
    dt: float = 1/30  # 33ms base
    sim_speed: float = 1.0
    use_privileged_velocity: bool | None = None  # None = respect controller_config, else override


class HeadlessSimulation:
    """
    Headless FSOC simulator — gym-like, deterministic, no Qt.

     Pipeline (beacon_tracker removed):
      beacons.update(dt_eff) → scene.update → camera.update → disturbances → capture → (no detection) → controller idle → camera.move (direct action only)

    Usage:
        sim = HeadlessSimulation(seed=42)
        obs = sim.reset(seed=42)
        obs, reward, terminated, truncated, info = sim.step(action=None)  # action None => hold, else np.array([d_pan,d_tilt])
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
        rng: np.random.Generator | None = None,
        max_steps: int = 2000,
        dt: float = 1/30,
        sim_speed: float = 1.0,
        use_privileged_velocity: bool | None = None,
    ):
        self.seed = int(seed)
        self.rng: np.random.Generator = get_rng(rng, self.seed)
        seed_global(self.seed)

        self.dt = float(dt)
        self.sim_speed = float(sim_speed)
        self.max_steps = int(max_steps)
        self.step_count = 0
        self._use_priv_override = use_privileged_velocity

        self.env_config = (env_config or EnvironmentConfig()).validate()
        if env_config is None:
            self.env_config.seed = self.seed
            self.env_config.validate()
        self._scene_size = (int(self.env_config.world_width), int(self.env_config.world_height))

        if camera_config is None:
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
        if use_privileged_velocity is not None:
            self.controller_config.use_privileged_velocity = bool(use_privileged_velocity)
            self.controller_config.validate()

        self.disturbance_config = (disturbance_config or DisturbanceConfig()).validate()
        self.beacon_config = (beacon_config or MultiBeaconConfig(beacon_count=1, target_index=0)).validate()

        self._camera_drift_state: dict = {}
        self._platform_motion_state: dict = {}
        self._jitter_state: dict = {}

        # No detection state (beacon_tracker removed)
        self._last_estimate: tuple[float, float] | None = None
        self._last_all_detections: list[dict] = []
        self._last_lock_state: str = "searching"

        self._build_simulation()

        self._start_time = None
        self._last_tick_time: float | None = None

    def _build_simulation(self):
        cfg = self.env_config.validate()
        self._scene_size = (int(cfg.world_width), int(cfg.world_height))
        self.scene = Scene(config=cfg)

        sw, sh = self._scene_size
        cam_cfg = self.camera_config.validate((sw, sh))
        fov_w = min(int(cam_cfg.fov_width), sw - 10)
        fov_h = min(int(cam_cfg.fov_height), sh - 10)
        cam_cfg.fov_width = max(20, fov_w)
        cam_cfg.fov_height = max(20, fov_h)
        self.camera_config = cam_cfg
        self._fov_size = (int(cam_cfg.fov_width), int(cam_cfg.fov_height))
        self.camera = PTZCamera(config=cam_cfg, scene_bounds=(sw, sh), rng=self.rng)
        try:
            vig = float(cfg.vignetting_pct) / 100.0
            self.camera.set_vignetting(vig)
        except Exception: pass

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
            profile = bc.profile
        except Exception:
            profile = MotionProfile.CURVED
        speed = float(getattr(bc, "speed", 60))
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

        ctrl_cfg = self.controller_config.validate()
        self.controller = PIDController(config=ctrl_cfg)

        self._camera_drift_state.clear()
        self._platform_motion_state.clear()
        self._jitter_state.clear()
        self._minimap_thumb = None
        self._last_estimate = None
        self._last_all_detections = []
        self._last_lock_state = "searching"

    def reset(self, seed: int | None = None) -> dict:
        if seed is not None:
            self.seed = int(seed)
            self.rng = get_rng(None, self.seed)
            seed_global(self.seed)
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
        self._last_tick_time = None
        return self.get_observation()

    def get_observation(self) -> dict:
        est = self._last_estimate
        err = None
        if est is not None:
            cx, cy = self.camera.fov_width/2, self.camera.fov_height/2
            err = float(np.hypot(est[0]-cx, est[1]-cy))
        return {
            "estimate": est,
            "tracking_error_px": err,
            "lock_status": self._last_lock_state,
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
        step_start = time.time()
        dt = float(dt if dt is not None else self.dt)
        dt_eff = float(np.clip(dt * self.sim_speed, 1e-4, 0.1))
        dt_wall = float(np.clip(dt, 0.005, 0.1))

        for b in getattr(self, "beacons", [self.target]):
            if getattr(b, "enabled", True):
                b.update(dt_eff)
        if hasattr(self, "beacons") and self.beacons:
            tid = int(np.clip(int(getattr(self, "_target_beacon_id", 0)), 0, len(self.beacons)-1))
            self.target = self.beacons[tid]

        try: self.scene.update(dt_eff)
        except Exception: pass
        try: self.camera.update(dt_wall)
        except Exception: pass

        dc = self.disturbance_config.validate() if hasattr(self.disturbance_config, "validate") else self.disturbance_config
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

        # Apply disturbed position to camera — respects all camera params and scene bounds
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
            if vig > 1e-3:
                from environment.vignetting import apply_vignetting
                fov_frame = apply_vignetting(fov_frame, vig)
        else:
            fov_frame = self.camera.capture(scene_frame)
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

        # No detection (beacon_tracker removed) — all detections empty
        all_dets: list[dict] = []
        self._last_all_detections = all_dets
        if fov_capture_x0 is not None and fov_capture_y0 is not None:
            fov_x0, fov_y0 = int(fov_capture_x0), int(fov_capture_y0)
        else:
            fov_x0, fov_y0, _, _ = self.camera.get_fov_rect()
        # No autonomous detection; estimate stays None
        estimate = None
        self._last_estimate = estimate
        tracking_error_px = None
        hitbox_hit = False
        center_hit = False
        detection = None

        # No PID from detection — only direct action moves camera
        if action is not None:
            try:
                arr = np.asarray(action, dtype=float).reshape(-1)
                d_pan = float(arr[0]) if len(arr) > 0 else 0.0
                d_tilt = float(arr[1]) if len(arr) > 1 else 0.0
                try: self.camera.move(d_pan, d_tilt, dt_eff)
                except Exception: self.camera.move(d_pan, d_tilt)
            except Exception: pass

        is_locked = False
        lock_state = "searching"
        self._last_lock_state = lock_state

        self.step_count += 1
        reward = -1.0

        terminated = False
        truncated = self.step_count >= self.max_steps

        obs = self.get_observation()
        obs["frame"] = fov_frame
        obs["all_detections"] = all_dets
        obs["tracking_error_px"] = tracking_error_px
        obs["hitbox_hit"] = hitbox_hit
        obs["center_hit"] = center_hit
        obs["is_locked"] = is_locked

        try:
            obs["viewport"] = Renderer.render_viewport(fov_frame, self.camera, self.beacons, self.target, None, all_dets, estimate=estimate)
        except Exception:
            obs["viewport"] = fov_frame

        info = {
            "detection": detection,
            "estimate": estimate,
            "all_detections": all_dets,
            "fov_origin": (fov_x0, fov_y0),
        }
        return obs, float(reward), bool(terminated), bool(truncated), info

    def _draw_targets_fov(self, fov_frame: np.ndarray, fov_x0: int, fov_y0: int):
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
        pass

    @property
    def observation_space(self):
        try:
            h, w = int(self.camera_config.fov_height), int(self.camera_config.fov_width)
        except Exception:
            h, w = 480, 640
        return {
            "frame": (h, w, 3),
            "estimate": (2,),
            "tracking_error_px": (1,),
            "lock_status": ["searching", "tracking"],
            "pan_tilt": (2,),
            "all_detections": "list[dict]",
        }

    @property
    def action_space(self):
        try:
            clamp = float(self.controller_config.output_clamp)
        except Exception:
            clamp = 120.0
        return {"d_pan": (-clamp, clamp), "d_tilt": (-clamp, clamp), "shape": (2,)}

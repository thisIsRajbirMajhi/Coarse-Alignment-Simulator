# gui/application/session.py - SimulationSession: Qt-free owner of simulation.
# Single place where target/camera/disturbance/tracking/PID advance.
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any

import numpy as np

log = logging.getLogger(__name__)


@dataclass
class FrameSnapshot:
    """Immutable per-step output for presenters/views."""
    frame_id: int
    fov_frame: Any  # np.ndarray BGR, raw disturbed (no overlay)
    world_frame: Any | None  # full scene background (may be None; view caches)
    fov_origin: tuple[int, int]  # (x0, y0) scene coords of FOV
    pan: float
    tilt: float
    fov_size: tuple[int, int]
    world_size: tuple[int, int]
    estimate: tuple[float, float] | None
    all_detections: list = field(default_factory=list)
    lock_state: str = "searching"
    lock_quality: float = 0.0
    tracking_error_px: float | None = None
    locked_track_id: Any = None
    id_switches: int = 0
    n_tracks: int = 0
    designated_target_id: int = 0
    pixel_scale_mrad: float = 0.035
    dt: float = 1 / 30


class SimulationSession:
    """Owns Scene/Beacons/Camera/Controller/Pipeline/Disturbance/Metrics.

    GUI talks to this; widgets never touch sim objects directly.
    """

    def __init__(self, env_config=None, camera_config=None, controller_config=None,
                 disturbance_config=None, beacon_config=None, seed: int = 42):
        from camera.config import CameraConfig
        from control.config import ControllerConfig
        from disturbance.core.config import DisturbanceConfig
        from environment.config import EnvironmentConfig
        from target.config import MultiBeaconConfig

        self.seed = int(seed)
        self.env_config = (env_config or EnvironmentConfig()).validate()
        # camera validate needs scene bounds
        scene_bounds = (int(self.env_config.world_width), int(self.env_config.world_height))
        self.camera_config = (camera_config or CameraConfig()).validate(scene_bounds)
        self.controller_config = (controller_config or ControllerConfig()).validate()
        self.disturbance_config = (disturbance_config or DisturbanceConfig()).validate()
        self.beacon_config = (beacon_config or MultiBeaconConfig()).validate()
        self.detector_threshold: int = 80  # classical bright threshold (DetectorConfig 50..255)
        self._built = False
        self._frame_id = 0
        self._last_dt = 1 / 30

    # -- construction -------------------------------------------------
    def build(self) -> None:
        from camera.ptz_camera import PTZCamera
        from common.rng import get_rng, seed_global
        from control.controller import PIDController
        from environment.scene import Scene
        from target.motion import MotionProfile, create_beacons

        cfg = self.env_config.validate()
        seed_global(int(cfg.seed) if cfg.seed is not None else self.seed)
        self.rng = get_rng(None, int(cfg.seed) if cfg.seed is not None else self.seed)
        try:
            from disturbance.core.state import reset_disturbance_state
            reset_disturbance_state()
            from disturbance.sensor.image_noise import clear_hot_pixel_cache
            clear_hot_pixel_cache()
        except Exception as e:
            log.debug("disturbance reset skipped: %s", e)

        scene_w, scene_h = int(cfg.world_width), int(cfg.world_height)
        cam_cfg = self.camera_config.validate((scene_w, scene_h))
        # clamp FOV inside world
        cam_cfg.fov_width = min(int(cam_cfg.fov_width), scene_w - 10)
        cam_cfg.fov_height = min(int(cam_cfg.fov_height), scene_h - 10)
        self.camera_config = cam_cfg

        self.scene = Scene(config=cfg)
        bcfg = self.beacon_config.validate()
        try:
            profile = bcfg.profile if hasattr(bcfg.profile, "value") is False else bcfg.profile
            if isinstance(profile, str):
                profile = MotionProfile(profile)
        except Exception:
            profile = MotionProfile.CURVED
        base_seed = int(cfg.seed) % 997 if cfg.seed is not None else self.seed
        # Single-beacon requested position: honour it ONLY if inside the world.
        # Out-of-bounds requests (e.g. stale 2500 defaults on a 2000 world) would
        # corrupt orbit anchors into wall-pinned orbits, so fall back to the
        # factory's stratified in-world placement instead.
        req_x = req_y = None
        if int(bcfg.beacon_count) == 1:
            try:
                qx, qy = float(getattr(bcfg, "x", 2500)), float(getattr(bcfg, "y", 2500))
            except Exception:
                qx = qy = None
            if qx is not None and 0 <= qx <= scene_w and 0 <= qy <= scene_h:
                req_x, req_y = qx, qy
            else:
                log.info("beacon request (%.0f,%.0f) outside %dx%d world — stratified placement",
                         qx if qx is not None else -1, qy if qy is not None else -1, scene_w, scene_h)
        self.beacons = create_beacons(
            int(bcfg.beacon_count), (scene_w, scene_h), profile, float(getattr(bcfg, "speed", 100)),
            seed=base_seed, hitbox_radius=14, center_radius=2,
            brightness=255, radius=5,
            shape=str(getattr(bcfg, "shape", "square")),
            size_w=int(getattr(bcfg, "size_w", 10)), size_h=int(getattr(bcfg, "size_h", 10)),
            blinking=bool(getattr(bcfg, "blinking", False)),
            x=req_x, y=req_y,
            speed_random=bool(getattr(bcfg, "speed_random", False)),
        )
        tid = int(np.clip(int(bcfg.target_index), 0, max(0, len(self.beacons) - 1)))
        self.designated_target_id = tid
        self.target = self.beacons[tid]
        # Guard parametric orbits (CURVED): an orbit radius larger than the
        # inscribed world pins the beacon at walls/corners. Cap it so the
        # ellipse fits inside the world; in-stratified spawns are untouched.
        try:
            m = 16.0
            for b in self.beacons:
                rx = float(getattr(b, "_orbit_radius", 0) or 0)
                if rx <= 0:
                    continue
                max_rx = min(scene_w, scene_h) / 2.0 - m
                if rx > max_rx > 0:
                    s = max_rx / rx
                    b._orbit_radius = max_rx
                    b._orbit_radius_y = float(getattr(b, "_orbit_radius_y", rx)) * s
                    b._orbit_omega0 = float(b.speed) / max(max_rx, 1.0)
                    log.info("capped orbit radius %.0f->%.0f to fit %dx%d world", rx, max_rx, scene_w, scene_h)
        except Exception as e:
            log.debug("orbit cap skipped: %s", e)
        self.camera = PTZCamera(config=cam_cfg, scene_bounds=(scene_w, scene_h), rng=getattr(self, "rng", None))
        try:
            self.camera.set_vignetting(float(getattr(cfg, "vignetting_pct", 0)) / 100.0)
        except Exception as e:
            log.debug("vignetting skipped: %s", e)
        ctrl_cfg = self.controller_config.validate()
        from control.controller import PIDController as _PID
        self.controller = _PID(config=ctrl_cfg)
        # Tracking pipeline (classical-only, real-time)
        try:
            from tracking.detector import DetectorConfig as _DC
            from tracking.metrics import MetricsLogger as _ML
            from tracking.pipeline import TrackingPipeline as _TP
            self.pipeline = _TP(
                detector_config=_DC(threshold=int(self.detector_threshold)),
                controller_config=ctrl_cfg, fov_size=(int(cam_cfg.fov_width), int(cam_cfg.fov_height)),
                use_yolo=False, designated_target_id=tid,
            )
            self.metrics_logger = _ML(fov_size=(int(cam_cfg.fov_width), int(cam_cfg.fov_height)))
        except Exception as e:
            log.warning("tracking pipeline unavailable: %s", e)
            self.pipeline = None
            self.metrics_logger = None
        self._disturbance_pipeline = None
        self._built = True
        self._frame_id = 0
        self._last_estimate = None
        self._last_all_detections: list = []
        self._last_lock_state = "searching"
        self._last_lock_quality = 0.0
        self._last_error_px = None

    def ensure_built(self) -> None:
        if not self._built:
            self.build()

    # -- lifecycle ----------------------------------------------------
    def reset(self, seed: int | None = None) -> None:
        if seed is not None:
            self.seed = int(seed)
            try:
                self.env_config.seed = int(seed)
            except Exception as e:
                log.debug("seed apply skipped: %s", e)
        self.build()
        if self.metrics_logger is not None:
            self.metrics_logger.reset()

    # -- config application (validated, explicit) ----------------------
    def apply_camera_config(self, config) -> None:
        self.ensure_built()
        scene_bounds = (int(self.env_config.world_width), int(self.env_config.world_height))
        self.camera_config = config.validate(scene_bounds)
        self.camera.apply_config(self.camera_config)

    def apply_controller_config(self, config) -> None:
        self.ensure_built()
        self.controller_config = config.validate()
        self.controller.apply_config(self.controller_config)
        if self.pipeline is not None:
            self.pipeline.controller_config = self.controller_config.validate()
            self.pipeline.controller.apply_config(self.pipeline.controller_config)

    def apply_environment_config(self, config) -> None:
        # World-size change requires rebuild (scene + camera bounds + beacons).
        self.env_config = config.validate()
        self.build()

    def apply_disturbance_config(self, config) -> None:
        self.ensure_built()
        self.disturbance_config = config.validate()

    def set_detector_threshold(self, value: int) -> None:
        """Validated classical-detector bright threshold (50..255). Hot-applied."""
        from tracking.detector import DetectorConfig as _DC
        v = _DC(threshold=int(value)).validate().threshold
        self.detector_threshold = int(v)
        if getattr(self, "pipeline", None) is not None:
            try:
                self.pipeline.detector_config.threshold = int(v)
                self.pipeline.detector.config.threshold = int(v)
            except Exception as e:
                log.debug("detector threshold hot-apply skipped: %s", e)

    def apply_beacon_config(self, config) -> None:
        # Beacon-count/shape change requires rebuild.
        self.beacon_config = config.validate()
        self.build()
        if self.pipeline is not None:
            try:
                self.pipeline.set_designated_target(int(self.beacon_config.target_index))
            except Exception as e:
                log.debug("set_designated_target failed: %s", e)

    def select_target(self, index: int) -> None:
        self.ensure_built()
        idx = int(np.clip(int(index), 0, len(self.beacons) - 1))
        self.designated_target_id = idx
        self.target = self.beacons[idx]
        try:
            self.beacon_config.target_index = idx
        except Exception:
            pass
        if self.pipeline is not None:
            try:
                self.pipeline.set_designated_target(idx)
            except Exception as e:
                log.debug("select_target pipeline sync failed: %s", e)

    # -- stepping ------------------------------------------------------
    def _disturbance_pipeline_for(self, dt: float):
        from disturbance.core import DisturbanceContext, DisturbancePipeline
        if self._disturbance_pipeline is None:
            self._disturbance_pipeline = DisturbancePipeline(
                DisturbanceContext(self.disturbance_config, rng=self.rng, dt=dt),
                bounds=(int(self.env_config.world_width), int(self.env_config.world_height)),
            )
        self._disturbance_pipeline.context.config = self.disturbance_config
        self._disturbance_pipeline.context.rng = self.rng
        self._disturbance_pipeline.context.dt = dt
        return self._disturbance_pipeline

    def step(self, dt: float) -> FrameSnapshot:
        self.ensure_built()
        dt_eff = float(np.clip(dt, 1e-4, 0.1))
        self._last_dt = dt_eff
        for b in self.beacons:
            if getattr(b, "enabled", True):
                b.update(dt_eff)
        self.target = self.beacons[int(np.clip(self.designated_target_id, 0, len(self.beacons) - 1))]
        self.scene.update(dt_eff)
        self.camera.update(dt)

        dc = self.disturbance_config.validate()
        pipe = self._disturbance_pipeline_for(dt_eff)
        pan_dist, tilt_dist = pipe.disturb_camera_pose(self.camera.pan, self.camera.tilt, dt_eff)
        try:
            self.camera.apply_disturbance(float(pan_dist), float(tilt_dist))
        except AttributeError:
            self.camera.set_position(float(pan_dist), float(tilt_dist), clear_queue=False)
        x0, y0, x1, y1 = self.camera.get_fov_rect()
        fov_frame = self.scene.get_region(int(x0), int(y0), int(x1), int(y1))
        # draw beacons (photon-level, sim-owned; see gui/core/photon_renderer.py)
        from gui.core.photon_renderer import draw_beacon_patches
        draw_beacon_patches(fov_frame, self.beacons, self.env_config, self.disturbance_config, int(x0), int(y0))
        try:
            vig = float(getattr(self.env_config, "vignetting_pct", 0)) / 100.0
            if vig > 1e-3:
                from environment.vignetting import apply_vignetting
                fov_frame = apply_vignetting(fov_frame, vig)
        except Exception as e:
            log.debug("vignetting skipped: %s", e)
        fov_frame = pipe.apply_frame(fov_frame)

        # Tracking closed loop
        all_dets: list = []
        estimate = None
        err = None
        lock = "searching"
        quality = 0.0
        if self.pipeline is not None:
            self.pipeline.fov_w, self.pipeline.fov_h = int(self.camera_config.fov_width), int(self.camera_config.fov_height)
            try:
                pan_rng = self.camera.get_pan_range()
                tilt_rng = self.camera.get_tilt_range()
            except Exception:
                pan_rng, tilt_rng = None, None
            res = self.pipeline.update(
                fov_frame, dt_eff,
                current_pan_tilt=(float(self.camera.pan), float(self.camera.tilt)),
                pan_range=pan_rng, tilt_range=tilt_rng,
            )
            all_dets = [d.to_dict() for d in res.all_detections]
            estimate = res.estimate
            err = res.error_px
            lock = str(res.state)
            quality = float(getattr(res, "lock_quality", 0.0) or 0.0)
            try:
                self._last_locked_track_id = getattr(res, "locked_track_id", None)
                self._last_id_switches = int(getattr(res, "id_switches", 0) or 0)
                self._last_n_tracks = int(getattr(res, "n_tracks", 0) or 0)
            except Exception:
                pass
            if abs(float(res.d_pan)) > 1e-9 or abs(float(res.d_tilt)) > 1e-9:
                try:
                    self.camera.move(float(res.d_pan), float(res.d_tilt), dt_eff)
                except TypeError:
                    self.camera.move(float(res.d_pan), float(res.d_tilt))
        self._last_all_detections = all_dets
        self._last_estimate = estimate
        self._last_lock_state = lock
        self._last_lock_quality = quality
        self._last_error_px = err
        self._frame_id += 1
        # Metrics log (GT isolated here — never fed back to control)
        try:
            if self.metrics_logger is not None:
                tid = int(np.clip(self.designated_target_id, 0, len(self.beacons) - 1))
                b = self.beacons[tid]
                gx, gy = float(b.x) - float(x0), float(b.y) - float(y0)
                fw, fh = int(self.camera_config.fov_width), int(self.camera_config.fov_height)
                vis = (0 <= gx < fw) and (0 <= gy < fh)
                det_c = det_conf = None
                if all_dets and estimate is not None:
                    import math as _m
                    best = min(all_dets, key=lambda d: _m.dist(tuple(d.get("center", (0, 0))), tuple(estimate)))
                    det_c = tuple(best.get("center", (0, 0)))
                    det_conf = float(best.get("confidence", 0.0))
                elif all_dets:
                    det_c = tuple(all_dets[0].get("center", (0, 0)))
                    det_conf = float(all_dets[0].get("confidence", 0.0))
                try:
                    tr = getattr(getattr(self.pipeline, "tracker", None), "velocity", (0.0, 0.0))
                    vel = tuple(tr) if tr is not None else (0.0, 0.0)
                except Exception:
                    vel = (0.0, 0.0)
                try:
                    lat = float(getattr(self.pipeline.detector, "last_latency_ms", 0.0))
                except Exception:
                    lat = 0.0
                det_pos_var = None
                if all_dets and det_c is not None:
                    for _dd in all_dets:
                        if tuple(_dd.get("center", (0, 0))) == tuple(det_c):
                            det_pos_var = float(_dd.get("pos_var", 9.0))
                            break
                self.metrics_logger.log(
                    self._frame_id, (gx, gy), vis, det_c, det_conf, estimate, vel, lock, lat,
                    lock_quality=quality, detection_pos_var=det_pos_var, all_detections=all_dets,
                    track_id=getattr(self, "_last_locked_track_id", None),
                    designated_target_id=int(self.designated_target_id),
                )
        except Exception as e:
            log.debug("metrics log skipped: %s", e)
        try:
            scale = float(getattr(self.camera.config, "pixel_scale_mrad", 0.035))
        except Exception:
            scale = 0.035
        return FrameSnapshot(
            frame_id=self._frame_id, fov_frame=fov_frame, world_frame=None,
            fov_origin=(int(x0), int(y0)), pan=float(self.camera.pan), tilt=float(self.camera.tilt),
            fov_size=(int(self.camera_config.fov_width), int(self.camera_config.fov_height)),
            world_size=(int(self.env_config.world_width), int(self.env_config.world_height)),
            estimate=estimate, all_detections=all_dets, lock_state=lock, lock_quality=quality,
            tracking_error_px=err, locked_track_id=getattr(self, "_last_locked_track_id", None),
            id_switches=int(getattr(self, "_last_id_switches", 0) or 0),
            n_tracks=int(getattr(self, "_last_n_tracks", 0) or 0),
            designated_target_id=int(self.designated_target_id),
            pixel_scale_mrad=scale, dt=dt_eff,
        )

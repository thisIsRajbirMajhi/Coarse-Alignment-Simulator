# gui/mixins/simulation_mixin.py - Simulation construction for MainWindow
#
# Extracted from gui/main_window.py::_build_simulation (184 lines).
# Single Responsibility: Build/reset simulation objects (Scene, Beacons, Camera, Detector, Tracker, Controller)
# from typed configs (EnvironmentConfig, CameraConfig, ControllerConfig, DisturbanceConfig, MultiBeaconConfig).

from __future__ import annotations

import time
import numpy as np
from PyQt5.QtCore import QTimer  # noqa: F401 (used by MainWindow, keep import for compat)

from common.rng import get_rng, seed_global


class SimulationMixin:
    """Mixin: simulation factory. Expects host to have config attrs and panel refs."""

    def _build_simulation(self):  # type: ignore
        speed = getattr(self, "_target_speed", 100)
        # Prefer Tuning panel threshold if available (single source)
        try:
            if hasattr(self, "tuning_panel") and hasattr(self.tuning_panel, "thresh_spin"):
                thresh = int(self.tuning_panel.thresh_spin.value())
            else:
                thresh = getattr(self, "_det_thresh", 200)
        except:
            thresh = getattr(self, "_det_thresh", 200)
        gain = getattr(self, "_ctrl_gain", 0.15)
        # Global tuning — use live widget values if available, else stored defaults
        try:
            smoothing = float(self.tracker_smoothing_spin.value()) if hasattr(self, "tracker_smoothing_spin") else float(getattr(self, "_tracker_smoothing", 0.25))  # type: ignore
        except:
            smoothing = float(getattr(self, "_tracker_smoothing", 0.25))
        try:
            miss_limit = int(self.tracker_miss_spin.value()) if hasattr(self, "tracker_miss_spin") else int(getattr(self, "_tracker_miss_limit", 5))  # type: ignore
        except:
            miss_limit = int(getattr(self, "_tracker_miss_limit", 5))
        try:
            min_area = int(self.detector_min_area_spin.value()) if hasattr(self, "detector_min_area_spin") else int(getattr(self, "_detector_min_area", 2))  # type: ignore
        except:
            min_area = int(getattr(self, "_detector_min_area", 2))
        try:
            sim_speed = float(self.sim_speed_spin.value()) if hasattr(self, "sim_speed_spin") else float(getattr(self, "_sim_speed", 1.0))  # type: ignore
        except:
            sim_speed = float(getattr(self, "_sim_speed", 1.0))
        try:
            g_bright = int(self.global_brightness_spin.value()) if hasattr(self, "global_brightness_spin") else int(getattr(self, "_global_brightness", 255))  # type: ignore
        except:
            g_bright = int(getattr(self, "_global_brightness", 255))
        try:
            g_radius = int(self.global_radius_spin.value()) if hasattr(self, "global_radius_spin") else int(getattr(self, "_global_radius", 5))  # type: ignore
        except:
            g_radius = int(getattr(self, "_global_radius", 5))
        try:
            from target.motion import MotionProfile
            profile = MotionProfile(self.motion_combo.currentText())  # type: ignore
        except Exception:
            from target.motion import MotionProfile  # noqa
            profile = MotionProfile.CURVED
        # Disturbances — collect validated DisturbanceConfig if panel available (single source)
        try:
            if hasattr(self, "disturbances_panel") and self.disturbances_panel is not None:
                dcfg = self.disturbances_panel.collect_config().validate()
                self.disturbance_config = dcfg
        except Exception:
            pass
        # Environment — collect validated config (panel if available, else env_config)
        try:
            if hasattr(self, "env_panel") and self.env_panel is not None:
                cfg = self.env_panel.collect_config().validate()
                self.env_config = cfg
            else:
                cfg = self.env_config.validate()
        except Exception:
            cfg = self.env_config.validate()
        # Seed global RNG for deterministic disturbances (AI-ready) — GUI now deterministic per seed
        try:
            seed_global(int(cfg.seed) if cfg.seed is not None else None)
            self.rng = get_rng(None, int(cfg.seed) if cfg.seed is not None else None)
            # Reset global disturbance state for determinism (turbulence _turb_state etc)
            try:
                from disturbance.state import reset_disturbance_state
                reset_disturbance_state()
                from disturbance.image_noise import clear_hot_pixel_cache
                clear_hot_pixel_cache()
            except Exception:
                pass
        except Exception:
            self.rng = get_rng(None)
        # Sync scene size from config (single source)
        scene_w, scene_h = int(cfg.world_width), int(cfg.world_height)
        self._scene_size = (scene_w, scene_h)

        # Camera — collect validated CameraConfig (11 params: FOV, mechanics, display, units)
        try:
            if hasattr(self, "camera_panel") and self.camera_panel is not None:
                cam_cfg = self.camera_panel.collect_config().validate((scene_w, scene_h))
                self.camera_config = cam_cfg
            else:
                cam_cfg = self.camera_config.validate((scene_w, scene_h))
        except Exception:
            cam_cfg = self.camera_config.validate((scene_w, scene_h))
        fov_w, fov_h = int(cam_cfg.fov_width), int(cam_cfg.fov_height)
        fov_w = min(fov_w, scene_w - 10)
        fov_h = min(fov_h, scene_h - 10)
        # Keep legacy _fov_size and display sizes in sync for renderer
        self._fov_size = (fov_w, fov_h)
        self._viewport_display_size = (int(cam_cfg.viewport_width), int(cam_cfg.viewport_height))
        self._god_display_size = (int(cam_cfg.god_width), int(cam_cfg.god_height))
        # Clamp FOV to scene and update config (handles FOV > scene case)
        cam_cfg.fov_width = int(fov_w); cam_cfg.fov_height = int(fov_h)
        self.camera_config = cam_cfg

        # Build scene via typed config
        from environment.scene import Scene  # local import to avoid cycles
        self.scene = Scene(config=cfg)
        # Beacons — single panel, all beacons share same rules
        beacon_count = int(getattr(self, "_beacon_count", 1))
        hb = int(np.clip(14, 3, 80))
        cr = int(np.clip(2, 1, hb))
        tgt_id = int(getattr(self, "_target_beacon_id", 0))
        shape = "square"
        size_w = 10
        size_h = 10
        blinking = False
        speed_random = False
        tgt_x = None
        tgt_y = None
        try:
            if hasattr(self, "beacon_manager") and self.beacon_manager is not None:
                multi_cfg = self.beacon_manager.collect_multi_config().validate()
                self.beacon_config = multi_cfg
                beacon_count = int(multi_cfg.beacon_count)
                tgt_id = int(multi_cfg.target_index)
                shape = str(getattr(multi_cfg, "shape", "square"))
                size_w = int(getattr(multi_cfg, "size_w", 10))
                size_h = int(getattr(multi_cfg, "size_h", 10))
                blinking = bool(getattr(multi_cfg, "blinking", False))
                speed_random = bool(getattr(multi_cfg, "speed_random", False))
                tgt_x = float(getattr(multi_cfg, "x", 2500))
                tgt_y = float(getattr(multi_cfg, "y", 2500))
                try:
                    profile = multi_cfg.profile
                except: pass
                speed = float(getattr(multi_cfg, "speed", speed))
            elif hasattr(self, "beacon_config"):
                multi_cfg = self.beacon_config.validate()
                beacon_count = int(multi_cfg.beacon_count)
                tgt_id = int(multi_cfg.target_index)
                shape = str(getattr(multi_cfg, "shape", shape))
                size_w = int(getattr(multi_cfg, "size_w", size_w))
                size_h = int(getattr(multi_cfg, "size_h", size_h))
                blinking = bool(getattr(multi_cfg, "blinking", blinking))
                speed_random = bool(getattr(multi_cfg, "speed_random", speed_random))
                tgt_x = float(getattr(multi_cfg, "x", 2500)) if beacon_count == 1 else None
                tgt_y = float(getattr(multi_cfg, "y", 2500)) if beacon_count == 1 else None
        except Exception:
            pass
        base_seed = int(cfg.seed) + int(self.perf.frame_count if hasattr(self, "perf") else 0) % 997 if 'cfg' in locals() else 42
        from target.motion import create_beacons  # local
        self.beacons: list = create_beacons(beacon_count, (scene_w, scene_h), profile, speed,
                                                     seed=base_seed, hitbox_radius=hb, center_radius=cr,
                                                     brightness=g_bright, radius=g_radius,
                                                     shape=shape, size_w=size_w, size_h=size_h, blinking=blinking,
                                                     x=tgt_x if beacon_count == 1 else None, y=tgt_y if beacon_count == 1 else None,
                                                     speed_random=speed_random)
        tgt_id = int(np.clip(int(tgt_id), 0, max(0, len(self.beacons)-1)))
        self._target_beacon_id = int(tgt_id)
        self._beacon_count = int(beacon_count)
        self._hitbox_radius = int(hb); self._center_radius = int(cr)
        from target.config import MultiBeaconConfig
        self.beacon_config = MultiBeaconConfig(beacon_count=len(self.beacons), target_index=int(tgt_id), shape=shape, size_w=size_w, size_h=size_h, x=float(tgt_x) if tgt_x is not None else 2500, y=float(tgt_y) if tgt_y is not None else 2500, profile=str(profile) if isinstance(profile, str) else profile.value if hasattr(profile, 'value') else "curved", speed=float(speed), blinking=bool(blinking), speed_random=bool(speed_random)).validate()
        self.target = self.beacons[tgt_id] if self.beacons else self.beacons[0]
        # Camera — full mechanics (slew, resolution, latency, ranges, home, optics) — deterministic via rng
        from camera.ptz_camera import PTZCamera
        self.camera = PTZCamera(config=cam_cfg, scene_bounds=(scene_w, scene_h), rng=getattr(self, "rng", None))
        # Sync vignetting (camera image-space, follows FOV — not world)
        try:
            vig = float(getattr(cfg, 'vignetting_pct', 0) if 'cfg' in locals() else getattr(self.env_config, 'vignetting_pct', 0)) / 100.0
            self.camera.set_vignetting(vig)
        except:
            pass
        from detection.detector import BeaconDetector
        self.detector = BeaconDetector(brightness_threshold=thresh, min_area=min_area)
        from tracking.tracker import Tracker
        self.tracker = Tracker(smoothing=smoothing, miss_limit=miss_limit)
        # Controller — P/PI/PID with dead zone, clamp, update rate (robust, modular)
        try:
            if hasattr(self, "control_panel") and self.control_panel is not None:
                ctrl_cfg = self.control_panel.collect_config().validate()
                self.controller_config = ctrl_cfg
            else:
                ctrl_cfg = self.controller_config.validate()
                try:
                    if 'gain' in locals():
                        ctrl_cfg.kp = float(gain)
                        ctrl_cfg.validate()
                        self.controller_config = ctrl_cfg
                except: pass
        except Exception:
            ctrl_cfg = self.controller_config.validate()
        # Sync camera panel gain alias for backward compat (if exists)
        try:
            if hasattr(self, "camera_panel") and hasattr(self.camera_panel, "gain_spin"):
                self.camera_panel.gain_spin.blockSignals(True)
                self.camera_panel.gain_spin.setValue(float(np.clip(ctrl_cfg.kp, 0.02, 0.50)))
                self.camera_panel.gain_slider.blockSignals(True)
                self.camera_panel.gain_slider.setValue(int(round(float(ctrl_cfg.kp)*100)))
                self.camera_panel.gain_spin.blockSignals(False)
                self.camera_panel.gain_slider.blockSignals(False)
        except: pass
        from control.controller import PIDController
        self.controller = PIDController(config=ctrl_cfg)
        # store sim speed for tick
        self._sim_speed = float(sim_speed)
        if not hasattr(self, "perf"):
            from perf_log.metrics import PerformanceLogger
            self.perf = PerformanceLogger()
        self._camera_drift_state = {}
        # Minimap cache — pre-resized thumb of static background (avoids 5000×5000 copy+resize each tick)
        self._minimap_thumb = None  # type: ignore
        self._minimap_thumb_size = None  # type: ignore
        self._minimap_scene_id = None  # type: ignore

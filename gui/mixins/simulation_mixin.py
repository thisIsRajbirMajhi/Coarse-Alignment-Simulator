# gui/mixins/simulation_mixin.py - Simulation construction for MainWindow
# beacon_tracker removed: builds Scene, Beacons, Camera, Controller only.

from __future__ import annotations

import time
import numpy as np
from PyQt5.QtCore import QTimer  # noqa: F401 (used by MainWindow, keep import for compat)

from common.rng import get_rng, seed_global


class SimulationMixin:
    """Mixin: simulation factory. Expects host to have config attrs and panel refs."""

    def _build_simulation(self):  # type: ignore
        speed = getattr(self, "_target_speed", 100)
        gain = getattr(self, "_ctrl_gain", 0.15)
        # Global tuning removed — use defaults
        sim_speed = 1.0
        g_bright = 255
        g_radius = 5
        try:
            from target.motion import MotionProfile
            profile = MotionProfile(self.motion_combo.currentText())  # type: ignore
        except Exception:
            from target.motion import MotionProfile  # noqa
            profile = MotionProfile.CURVED
        try:
            if hasattr(self, "disturbances_panel") and self.disturbances_panel is not None:
                dcfg = self.disturbances_panel.collect_config().validate()
                self.disturbance_config = dcfg
        except Exception:
            pass
        try:
            if hasattr(self, "env_panel") and self.env_panel is not None:
                cfg = self.env_panel.collect_config().validate()
                self.env_config = cfg
            else:
                cfg = self.env_config.validate()
        except Exception:
            cfg = self.env_config.validate()
        try:
            seed_global(int(cfg.seed) if cfg.seed is not None else None)
            self.rng = get_rng(None, int(cfg.seed) if cfg.seed is not None else None)
            try:
                from disturbance.state import reset_disturbance_state
                reset_disturbance_state()
                from disturbance.image_noise import clear_hot_pixel_cache
                clear_hot_pixel_cache()
            except Exception:
                pass
        except Exception:
            self.rng = get_rng(None)
        scene_w, scene_h = int(cfg.world_width), int(cfg.world_height)
        self._scene_size = (scene_w, scene_h)

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
        self._fov_size = (fov_w, fov_h)
        self._viewport_display_size = (int(cam_cfg.viewport_width), int(cam_cfg.viewport_height))
        self._god_display_size = (int(cam_cfg.god_width), int(cam_cfg.god_height))
        cam_cfg.fov_width = int(fov_w); cam_cfg.fov_height = int(fov_h)
        self.camera_config = cam_cfg

        from environment.scene import Scene  # local import to avoid cycles
        self.scene = Scene(config=cfg)
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
                except Exception: pass
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
        base_seed = int(cfg.seed) % 997 if 'cfg' in locals() else 42
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
        from camera.ptz_camera import PTZCamera
        self.camera = PTZCamera(config=cam_cfg, scene_bounds=(scene_w, scene_h), rng=getattr(self, "rng", None))
        try:
            vig = float(getattr(cfg, 'vignetting_pct', 0) if 'cfg' in locals() else getattr(self.env_config, 'vignetting_pct', 0)) / 100.0
            self.camera.set_vignetting(vig)
        except Exception:
            pass
        # No detector (beacon_tracker removed)
        self._last_estimate = None
        self._last_all_detections = []
        self._last_lock_state = "searching"
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
                except Exception: pass
        except Exception:
            ctrl_cfg = self.controller_config.validate()
        try:
            if hasattr(self, "camera_panel") and hasattr(self.camera_panel, "gain_spin"):
                self.camera_panel.gain_spin.blockSignals(True)
                self.camera_panel.gain_spin.setValue(float(np.clip(ctrl_cfg.kp, 0.02, 0.50)))
                self.camera_panel.gain_slider.blockSignals(True)
                self.camera_panel.gain_slider.setValue(int(round(float(ctrl_cfg.kp)*100)))
                self.camera_panel.gain_spin.blockSignals(False)
                self.camera_panel.gain_slider.blockSignals(False)
        except Exception: pass
        from control.controller import PIDController
        self.controller = PIDController(config=ctrl_cfg)
        self._sim_speed = float(sim_speed)
        self._camera_drift_state = {}
        self._minimap_thumb = None  # type: ignore
        self._minimap_thumb_size = None  # type: ignore
        self._minimap_scene_id = None  # type: ignore

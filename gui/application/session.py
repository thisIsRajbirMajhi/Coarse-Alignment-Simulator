# gui/application/session.py - V2 SimulationSession (Plan V2)
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import numpy as np

log = logging.getLogger(__name__)


@dataclass
class FrameSnapshot:
    frame_id: int
    world_frame: Any
    world_size: tuple[int, int]
    fov_frame: Any = None
    camera_telemetry: dict | None = None
    pid_telemetry: dict | None = None
    dt: float = 1 / 30
    terminals: dict | None = None
    pan: float = 0.0
    tilt: float = 0.0
    fov_size: tuple[int, int] = (640, 480)
    tracker_telemetry: dict | None = None
    # Disturbed (actual) FOV geometry — where the sensor really looked after jitter/platform.
    # God screen must use these, not the true gimbal center, to align FOV box with FOV content.
    fov_center_disturbed: tuple[float, float] | None = None
    fov_rect_disturbed: tuple[float, float, float, float] | None = None


class SimulationSession:
    """V2 session — Scene/Disturbance/Remote/Camera/PID/V2 FSM."""

    def __init__(self, env_config=None, disturbance_config=None, scenario_config=None,
                 camera_config=None, pid_config=None, seed: int = 42, **kwargs):
        from camera.config import CameraConfig, PIDConfig
        from disturbance.core.config import DisturbanceConfig
        from environment.config import EnvironmentConfig
        from remote_terminal import make_default_scenario

        self.seed = int(seed)
        self.env_config = (env_config or EnvironmentConfig()).validate()
        self.disturbance_config = (disturbance_config or DisturbanceConfig()).validate()
        scenario_config = scenario_config or kwargs.get("remote_config")
        self.scenario_config = (scenario_config or make_default_scenario()).validate()
        self.camera_config = (camera_config or CameraConfig()).validate()
        self.pid_config = (pid_config or PIDConfig()).validate()
        # V2 single source: AutonomyConfig (§19.2)
        autonomy_cfg = kwargs.get("autonomy_config") or kwargs.get("local_terminal_config") or kwargs.get("local_config")
        if autonomy_cfg is None:
            from local_terminal.models import AutonomyConfig
            autonomy_cfg = AutonomyConfig()
        try:
            autonomy_cfg = autonomy_cfg.validate()
        except AttributeError:
            from local_terminal.models import AutonomyConfig
            autonomy_cfg = AutonomyConfig().validate()
        self.autonomy_config = autonomy_cfg
        self._built = False
        self._frame_id = 0
        self._last_dt = 1 / 30

    def build(self) -> None:
        from camera.pid_controller import PIDController
        from camera.ptz import PTZCamera
        from common.rng import get_rng, seed_global
        from environment.scene import Scene
        from remote_terminal import RemoteTerminalManager

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

        self.scene = Scene(config=cfg)
        scene_seed = int(cfg.seed) if cfg.seed is not None else self.seed
        self.remote = RemoteTerminalManager(
            self.scenario_config,
            bounds=(int(cfg.world_width), int(cfg.world_height)),
            seed=scene_seed,
        )
        self.camera = PTZCamera(
            config=self.camera_config,
            world_size=(int(cfg.world_width), int(cfg.world_height)),
            rng=self.rng,
        )
        self.controller = PIDController(config=self.pid_config)
        from local_terminal import SignatureRegistry
        from local_terminal.supervisor import SupervisorV2
        self.supervisor = SupervisorV2(
            registry=SignatureRegistry.from_scenario(self.scenario_config),
            autonomy=self.autonomy_config,
        )
        self._apply_scan_start_index()
        self.tracker = self.supervisor.tracker
        self.comm_rx = self.supervisor.comm
        self.validator = self.supervisor.identity
        self._pending_track_error: tuple[float, float] | None = None
        self._pending_pid_active: bool = False
        self._pending_target_angles: tuple[float, float] | None = None
        self._pending_target_vel: tuple[float, float] | None = None
        self._last_disturbed_center: tuple[float, float] | None = None
        self._sim_time_s = 0.0
        self._disturbance_pipeline = None
        self._cached_world_frame = None
        self._built = True
        self._frame_id = 0

    def ensure_built(self) -> None:
        if not self._built:
            self.build()

    def reset(self, seed: int | None = None) -> None:
        if seed is not None:
            self.seed = int(seed)
            try:
                self.env_config.seed = int(seed)
            except Exception as e:
                log.debug("seed apply skipped: %s", e)
        self.build()
        if hasattr(self, "camera") and self.camera is not None:
            self.camera.reset()
        if hasattr(self, "controller") and self.controller is not None:
            self.controller.reset()

    def _apply_scan_start_index(self) -> None:
        try:
            scan = getattr(self.supervisor, "scan_ctrl", None)
            if scan is None:
                return
            # Prefer AutonomyConfig (new), fallback to CameraConfig (legacy)
            idx = int(getattr(self.autonomy_config, "search_start_index", 0) or 0)
            if not idx:
                idx = int(getattr(self.camera_config, "scan_start_index", 0) or 0)
            sched = list(getattr(scan, "_schedule", []) or [])
            if not sched:
                return
            idx = max(0, min(idx, len(sched) - 1))
            try:
                ptr = sched.index(idx)
            except ValueError:
                ptr = 0
            scan._schedule_ptr = int(ptr)
            scan._dwell_count = 0
            try:
                scan._required_dwell = int(scan.config.default_dwell_frames)
            except (AttributeError, TypeError, ValueError):
                pass
        except Exception as e:
            log.debug("scan start index apply skipped: %s", e)

    def apply_camera_config(self, config=None) -> None:
        if config is not None:
            old = self.camera_config
            old_idx = int(getattr(old, "scan_start_index", 0) or 0)
            old_use = bool(getattr(old, "use_custom_start", False))
            old_sp = float(getattr(old, "start_pan_deg", 0.0))
            old_st = float(getattr(old, "start_tilt_deg", 0.0))
            self.camera_config = config.validate()
            if hasattr(self, "camera") and self.camera is not None:
                self.camera.apply_config(self.camera_config)
                # If start pose changed (preset far start), jump camera to new start.
                if (bool(self.camera_config.use_custom_start) != old_use or
                    abs(float(self.camera_config.start_pan_deg) - old_sp) > 1e-6 or
                    abs(float(self.camera_config.start_tilt_deg) - old_st) > 1e-6):
                    try:
                        self.camera.reset()
                    except Exception as e:
                        log.debug("camera reset to start pose skipped: %s", e)
            new_idx = int(getattr(self.camera_config, "scan_start_index", 0) or 0)
            if new_idx != old_idx or not getattr(self, "_built", False):
                self._apply_scan_start_index()

    def apply_controller_config(self, config=None) -> None:
        if config is not None:
            self.pid_config = config.validate()
            if hasattr(self, "controller") and self.controller is not None:
                self.controller.apply_config(self.pid_config)

    def apply_environment_config(self, config) -> None:
        new_cfg = config.validate()
        old = self.env_config
        old_w = int(getattr(old, "world_width", 0) or 0)
        old_h = int(getattr(old, "world_height", 0) or 0)
        new_w, new_h = int(new_cfg.world_width), int(new_cfg.world_height)
        self.env_config = new_cfg
        if self._built and new_w == old_w and new_h == old_h:
            try:
                self.scene.regenerate_from_config(new_cfg)
            except Exception:
                self.build()
            return
        self.build()

    def apply_disturbance_config(self, config) -> None:
        self.ensure_built()
        self.disturbance_config = config.validate()

    def apply_remote_config(self, config) -> None:
        self.ensure_built()
        self.scenario_config = config.validate()
        self.remote.apply_config(self.scenario_config)
        from local_terminal import SignatureRegistry
        try:
            self.supervisor.set_registry(SignatureRegistry.from_scenario(self.scenario_config))
        except (AttributeError, TypeError):
            pass
        self.validator = getattr(self.supervisor, "validator", getattr(self.supervisor, "identity", None))

    def apply_local_terminal_config(self, config) -> None:
        self.ensure_built()
        # Accept AutonomyConfig (V2) or legacy LocalTerminalConfig shim
        try:
            cfg = config.validate()
        except AttributeError:
            from local_terminal.models import AutonomyConfig
            cfg = AutonomyConfig().validate()
        # If legacy LocalTerminalConfig, ignore old fields and use AutonomyConfig
        if hasattr(cfg, "detector"):
            from local_terminal.models import AutonomyConfig
            cfg = AutonomyConfig().validate()
        self.autonomy_config = cfg
        try:
            self.supervisor.apply_local_config(cfg)
        except (AttributeError, TypeError):
            try:
                self.supervisor.cfg = cfg
                self.supervisor.cfg.validate()
            except (AttributeError, TypeError):
                pass
        # Sync scan start index if changed
        try:
            self._apply_scan_start_index()
        except Exception:
            pass
        # Sync mission priority list to supervisor
        try:
            prio = list(getattr(cfg, "mission_priority", []) or [])
            if prio:
                self.supervisor.mission_priority = list(prio)
        except (AttributeError, TypeError):
            pass
        self.tracker = self.supervisor.tracker
        self.comm_rx = getattr(self.supervisor, "comm_rx", getattr(self.supervisor, "comm", None))
        self.validator = getattr(self.supervisor, "validator", getattr(self.supervisor, "identity", None))

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
        self._sim_time_s += dt_eff
        self.scene.update(dt_eff)
        try:
            self.remote.update(dt_eff)
        except Exception as e:
            log.debug("remote terminal update skipped: %s", e)
        pipe = self._disturbance_pipeline_for(dt_eff)
        terms = self._safe_remote_telemetry()
        cmd_pan, cmd_tilt = 0.0, 0.0
        if self.controller.config.mode == "AUTO" and self._pending_pid_active and self._pending_track_error is not None:
            ex, ey = self._pending_track_error
            tvx, tvy = self._pending_target_vel or (0.0, 0.0)
            cmd_pan, cmd_tilt = self.controller.compute_from_pixels(
                error_x_px=ex, error_y_px=ey,
                deg_per_px_h=self.camera.config.deg_per_px_h,
                deg_per_px_v=self.camera.config.deg_per_px_v,
                dt=dt_eff, target_vel_x_px_s=float(tvx), target_vel_y_px_s=float(tvy),
            )
            self.camera.update(dt_eff, cmd_pan_vel=cmd_pan, cmd_tilt_vel=cmd_tilt)
        elif self.controller.config.mode == "AUTO" and self._pending_target_angles is not None:
            self.camera.set_target_angles(self._pending_target_angles[0], self._pending_target_angles[1])
            self.camera.update(dt_eff)
        else:
            self.camera.update(dt_eff, cmd_pan_vel=0.0, cmd_tilt_vel=0.0)
        from simulation.fov_pipeline import apply_jitter as _apply_pose
        from simulation.fov_pipeline import apply_post_noise as _apply_post
        fb = bool(getattr(self.camera_config, "use_measured_feedback", False))
        cx, cy = self.camera.get_fov_center_world(use_measured=fb)
        try:
            dcx, dcy = _apply_pose(cx, cy, self.disturbance_config, dt_eff, self.rng, pipeline=pipe)
        except Exception as e:
            log.debug("camera pose disturbance skipped: %s", e)
            dcx, dcy = cx, cy
            try:
                pipe.context.advance(dt_eff)
            except Exception:
                pass
        # 60 FPS path: FOV-only rendering (0.3M) instead of world copy (4M).
        # Extract FOV directly from scene via get_region (memcpy 0.3M, not 4M) then
        # render spots on FOV only. World frame for God view is throttled to 15 FPS
        # (every 4th frame) to avoid 12MB copy per 16ms tick.
        fov_w, fov_h = int(self.camera.fov_width), int(self.camera.fov_height)
        x0 = int(round(dcx - fov_w / 2.0))
        y0 = int(round(dcy - fov_h / 2.0))
        x1 = x0 + fov_w
        y1 = y0 + fov_h
        try:
            fov_frame = self.scene.get_region(x0, y0, x1, y1)
        except Exception as e:
            log.debug("FOV get_region failed, fallback to extract: %s", e)
            # Fallback to old path
            world_tmp = self.scene.get_frame()
            fov_frame = self.camera.extract_fov_at(world_tmp, dcx, dcy)
            # Render spots on fallback path
            try:
                fov_frame = self.remote.render_spots_on_fov(fov_frame, (x0, y0, x1, y1))
            except Exception:
                pass
        else:
            # Render spots directly on FOV (FOV-local coordinates)
            try:
                fov_frame = self.remote.render_spots_on_fov(fov_frame, (x0, y0, x1, y1))
            except Exception as e:
                log.debug("FOV spot render skipped: %s", e)
        # Vignetting on FOV (0.3M) not world (4M)
        try:
            vig = float(getattr(self.env_config, "vignetting_pct", 0)) / 100.0
            if vig > 1e-3:
                from environment.vignetting import apply_vignetting
                fov_frame = apply_vignetting(fov_frame, vig)
        except Exception as e:
            log.debug("vignetting skipped: %s", e)
        try:
            fov_frame = _apply_post(fov_frame, self.disturbance_config, dt_eff, self.rng, pipe, advance=False)
        except Exception as e:
            log.debug("fov post noise skipped: %s", e)
        # Throttled world frame for God view (15 FPS is enough, saves 1.7ms per tick)
        world_frame = getattr(self, "_cached_world_frame", None)
        if world_frame is None or (self._frame_id % 4 == 0):
            try:
                wf = self.scene.get_frame()
                wf = self.remote.render_spots(wf)
                self._cached_world_frame = wf
                world_frame = wf
            except Exception as e:
                log.debug("throttled world render skipped: %s", e)
                world_frame = getattr(self, "_cached_world_frame", fov_frame)
                if world_frame is None:
                    world_frame = fov_frame
        else:
            world_frame = self._cached_world_frame
        if self._last_disturbed_center is None:
            shift = (0.0, 0.0)
        else:
            shift = (dcx - self._last_disturbed_center[0], dcy - self._last_disturbed_center[1])
        self._last_disturbed_center = (dcx, dcy)
        from local_terminal import CommSource
        sources = []
        for term in getattr(self.remote, "terminals", []):
            try:
                rt = term.runtime
                sources.append(CommSource(
                    position=(float(term.position_m.x), float(term.position_m.y)),
                    emitting=bool(rt.effective_emission_enabled),
                    power_w=float(term.config.optical_power_w),
                    chip_at=term.generator.chip_at,
                    pointing_error_deg=float(rt.pointing_error_deg),
                    wavelength_nm=float(term.config.wavelength_nm),
                    beam_diameter_m=float(rt.beam_diameter_m),
                    range_m=float(rt.range_m),
                ))
            except (AttributeError, TypeError, ValueError):
                continue
        sup_out = self.supervisor.step(
            fov_frame=fov_frame, dt=dt_eff, sim_time_s=self._sim_time_s,
            comm_sources=sources, boresight_world=(float(dcx), float(dcy)),
            cam_home=self.camera.get_home(),
            px_per_deg=(self.camera.config.px_per_deg_h, self.camera.config.px_per_deg_v),
            origin_shift=shift, fov_size=(int(self.camera.fov_width), int(self.camera.fov_height)),
        )
        self._pending_pid_active = sup_out.pid_active
        self._pending_track_error = sup_out.track_error_px
        self._pending_target_angles = sup_out.camera_target_angles
        self._pending_target_vel = getattr(sup_out, "target_vel_px_s", None)
        if bool(getattr(sup_out, "camera_reset_requested", False)):
            try:
                self.camera.reset()
            except (AttributeError, TypeError, ValueError) as e:
                log.debug("full-reset camera homing skipped: %s", e)
            self._pending_track_error = None
            self._pending_pid_active = False
            self._pending_target_angles = None
            self._pending_target_vel = None
        # Disturbed FOV rect for God screen overlay — must match extract_fov_at center.
        try:
            hw, hh = float(self.camera.fov_width) / 2.0, float(self.camera.fov_height) / 2.0
            fov_rect_disturbed = (float(dcx - hw), float(dcy - hh), float(dcx + hw), float(dcy + hh))
        except Exception:
            fov_rect_disturbed = None
        self._frame_id += 1
        cam_st = self.camera.get_state()
        return FrameSnapshot(
            frame_id=self._frame_id, world_frame=world_frame,
            world_size=(int(self.env_config.world_width), int(self.env_config.world_height)),
            fov_frame=fov_frame, camera_telemetry=self.camera.get_telemetry(),
            pid_telemetry=self.controller.get_telemetry(), dt=dt_eff,
            terminals=terms, pan=cam_st.pan_deg, tilt=cam_st.tilt_deg,
            fov_size=(self.camera.fov_width, self.camera.fov_height),
            tracker_telemetry=sup_out.telemetry,
            fov_center_disturbed=(float(dcx), float(dcy)),
            fov_rect_disturbed=fov_rect_disturbed,
        )

    def _safe_remote_telemetry(self) -> dict | None:
        try:
            return self.remote.get_telemetry()
        except Exception as e:
            log.debug("remote telemetry skipped: %s", e)
            return None

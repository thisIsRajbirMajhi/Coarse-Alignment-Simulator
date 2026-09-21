# simulation/headless.py - Headless V2 FSOC simulation (deterministic, V2 FSM only)
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np

from camera.config import CameraConfig, PIDConfig
from camera.pid_controller import PIDController
from camera.ptz import PTZCamera
from common.rng import get_rng, seed_global
from disturbance import disturbances as dist
from disturbance.core.config import DisturbanceConfig
from disturbance.core import DisturbanceContext, DisturbancePipeline
from environment.config import EnvironmentConfig
from environment.scene import Scene
from remote_terminal import RemoteTerminalManager, RemoteScenarioConfig, make_default_scenario


@dataclass
class HeadlessConfig:
    seed: int = 42
    env: EnvironmentConfig | None = None
    disturbance: DisturbanceConfig | None = None
    scenario: RemoteScenarioConfig | None = None
    camera: CameraConfig | None = None
    pid: PIDConfig | None = None
    max_steps: int = 2000
    dt: float = 1 / 30
    sim_speed: float = 1.0


class HeadlessSimulation:
    """Headless V2 simulator — scene → terminals → disturbances → camera → V2 FSM → PID."""

    def __init__(
        self,
        seed: int = 42,
        env_config: EnvironmentConfig | None = None,
        disturbance_config: DisturbanceConfig | None = None,
        scenario_config: RemoteScenarioConfig | None = None,
        camera_config: CameraConfig | None = None,
        pid_config: PIDConfig | None = None,
        rng: np.random.Generator | None = None,
        max_steps: int = 2000,
        dt: float = 1 / 30,
        sim_speed: float = 1.0,
        **kwargs,
    ):
        self.seed = int(seed)
        self.rng: np.random.Generator = get_rng(rng, self.seed)
        seed_global(self.seed)

        self.dt = float(dt)
        self.sim_speed = float(sim_speed)
        self.max_steps = int(max_steps)
        self.step_count = 0

        self.env_config = (env_config or EnvironmentConfig()).validate()
        if env_config is None:
            self.env_config.seed = self.seed
            self.env_config.validate()
        self._scene_size = (int(self.env_config.world_width), int(self.env_config.world_height))

        self.disturbance_config = (disturbance_config or DisturbanceConfig()).validate()
        scenario_config = scenario_config or kwargs.get("remote_config")
        self.scenario_config = (scenario_config or make_default_scenario()).validate()
        self.camera_config = (camera_config or CameraConfig()).validate()
        self.pid_config = (pid_config or PIDConfig()).validate()
        autonomy_cfg = kwargs.get("autonomy_config", None)
        from local_terminal.models import AutonomyConfig as _AC
        if autonomy_cfg is None:
            autonomy_cfg = _AC()
        else:
            try:
                autonomy_cfg = autonomy_cfg.validate()
            except AttributeError:
                pass
        self.autonomy_config = autonomy_cfg

        self._last_frame: np.ndarray | None = None
        self._last_fov: np.ndarray | None = None
        self._sim_time_s = 0.0
        self._pending_track_error: tuple[float, float] | None = None
        self._pending_target_vel: tuple[float, float] | None = None
        self._last_disturbed_center: tuple[float, float] | None = None

        self._build_simulation()
        self._disturbance_pipeline = DisturbancePipeline(
            DisturbanceContext(self.disturbance_config, rng=self.rng, dt=self.dt),
            bounds=self._scene_size,
        )
        from local_terminal import SignatureRegistry
        from local_terminal.supervisor import SupervisorV2
        self.supervisor = SupervisorV2(
            registry=SignatureRegistry.from_scenario(self.scenario_config),
            autonomy=self.autonomy_config,
        )
        try:
            self.supervisor.mission_priority = [
                str(getattr(t, "terminal_id", "")) for t in
                getattr(self.scenario_config, "terminals", [])]
        except (AttributeError, TypeError, ValueError):
            pass
        self.tracker = self.supervisor.tracker
        self.comm_rx = self.supervisor.comm
        self.validator = self.supervisor.identity
        self._pending_pid_active = False
        self._pending_target_angles = None

    def _build_simulation(self):
        cfg = self.env_config.validate()
        self._scene_size = (int(cfg.world_width), int(cfg.world_height))
        self.scene = Scene(config=cfg)
        scene_seed = int(cfg.seed) if cfg.seed is not None else self.seed
        self.remote = RemoteTerminalManager(
            self.scenario_config, bounds=self._scene_size, seed=scene_seed,
        )
        self.camera = PTZCamera(
            config=self.camera_config,
            world_size=self._scene_size,
            rng=self.rng,
        )
        self.controller = PIDController(config=self.pid_config)
        self._last_frame = None
        self._last_fov = None

    def _capture_frame(self, dt_eff: float = 1 / 30, advance: bool = True) -> np.ndarray:
        dc = self.disturbance_config
        self._disturbance_pipeline.context.config = dc
        self._disturbance_pipeline.context.rng = self.rng
        self._disturbance_pipeline.context.dt = dt_eff
        frame = self.scene.get_frame()
        try:
            frame = self.remote.render_spots(frame)
        except (AttributeError, TypeError, ValueError, RuntimeError):
            pass
        vig = float(getattr(self.env_config, "vignetting_pct", 0)) / 100.0
        if vig > 1e-3:
            try:
                from environment.vignetting import apply_vignetting
                frame = apply_vignetting(frame, vig)
            except (AttributeError, TypeError, ValueError):
                pass
        try:
            from simulation.fov_pipeline import apply_post_noise as _post
            frame = _post(frame, dc, dt_eff, self.rng, self._disturbance_pipeline, advance=advance)
        except (AttributeError, TypeError, ValueError, RuntimeError):
            frame = dist.apply_turbulence(frame, int(getattr(dc, "turbulence", 0)), dt=dt_eff, rng=self.rng)
        return frame

    _capture_fov_frame = _capture_frame

    def reset(self, seed: int | None = None) -> dict:
        if seed is not None:
            self.seed = int(seed)
            self.rng = get_rng(None, self.seed)
            seed_global(self.seed)
            self.env_config.seed = self.seed
            self.env_config.validate()
        self.step_count = 0
        self._sim_time_s = 0.0
        self._pending_track_error = None
        self._pending_pid_active = False
        self._pending_target_angles = None
        self._pending_target_vel = None
        self._last_disturbed_center = None
        _prev_priority = list(getattr(getattr(self, "supervisor", None), "mission_priority", []) or [])
        from local_terminal import SignatureRegistry
        from local_terminal.supervisor import SupervisorV2
        self.supervisor = SupervisorV2(
            registry=SignatureRegistry.from_scenario(self.scenario_config),
            autonomy=getattr(self, "autonomy_config", None),
        )
        if _prev_priority:
            self.supervisor.mission_priority = list(_prev_priority)
        else:
            try:
                self.supervisor.mission_priority = [
                    str(getattr(t, "terminal_id", "")) for t in
                    getattr(self.scenario_config, "terminals", [])]
            except (AttributeError, TypeError, ValueError):
                pass
        self.tracker = self.supervisor.tracker
        self.comm_rx = self.supervisor.comm
        self.validator = self.supervisor.identity
        try:
            from disturbance.core.state import reset_disturbance_state
            reset_disturbance_state()
        except Exception:
            pass
        self._build_simulation()
        self._disturbance_pipeline.reset()
        self._disturbance_pipeline.context.config = self.disturbance_config
        self._disturbance_pipeline.context.rng = self.rng
        self._last_frame = self._capture_frame(self.dt)
        obs = self.get_observation()
        obs["frame"] = self._last_frame
        return obs

    def get_observation(self) -> dict:
        obs = {
            "world_size": self._scene_size,
            "step_count": self.step_count,
        }
        try:
            obs["terminals"] = self.remote.get_telemetry()
        except (AttributeError, TypeError, ValueError, RuntimeError):
            pass
        try:
            obs["tracker"] = self.tracker.autonomy_telemetry()
        except (AttributeError, TypeError, ValueError, RuntimeError):
            pass
        if self._last_frame is not None:
            obs["frame"] = self._last_frame
        if self._last_fov is not None:
            obs["fov_frame"] = self._last_fov
        if hasattr(self, "camera"):
            obs["camera"] = self.camera.get_telemetry()
        if hasattr(self, "controller"):
            obs["pid"] = self.controller.get_telemetry()
        return obs

    def step(self, action: np.ndarray | tuple | None = None, dt: float | None = None) -> tuple[dict, float, bool, bool, dict]:
        dt = float(dt if dt is not None else self.dt)
        dt_eff = float(np.clip(dt * self.sim_speed, 1e-4, 0.1))
        self._sim_time_s += dt_eff
        try:
            self.scene.update(dt_eff)
        except Exception:
            pass
        try:
            self.remote.update(dt_eff)
        except Exception:
            pass
        cmd_pan, cmd_tilt = 0.0, 0.0
        if action is not None and len(action) >= 2:
            cmd_pan, cmd_tilt = float(action[0]), float(action[1])
            self.camera.update(dt_eff, cmd_pan_vel=cmd_pan, cmd_tilt_vel=cmd_tilt)
        elif self.controller.config.mode == "AUTO" and self._pending_pid_active and self._pending_track_error is not None:
            ex, ey = self._pending_track_error
            tvx, tvy = self._pending_target_vel or (0.0, 0.0)
            cmd_pan, cmd_tilt = self.controller.compute_from_pixels(
                error_x_px=ex, error_y_px=ey,
                deg_per_px_h=self.camera.config.deg_per_px_h,
                deg_per_px_v=self.camera.config.deg_per_px_v,
                dt=dt_eff, target_vel_x_px_s=float(tvx), target_vel_y_px_s=float(tvy),
            )
            self.camera.update(dt_eff, cmd_pan_vel=cmd_pan, cmd_tilt_vel=cmd_tilt)
        elif self._pending_target_angles is not None:
            self.camera.set_target_angles(self._pending_target_angles[0], self._pending_target_angles[1])
            self.camera.update(dt_eff)
        else:
            self.camera.update(dt_eff, cmd_pan_vel=0.0, cmd_tilt_vel=0.0)
        from simulation.fov_pipeline import apply_jitter as _apply_pose
        from simulation.fov_pipeline import apply_post_noise as _apply_post
        pipe = self._disturbance_pipeline
        pipe.context.config = self.disturbance_config
        pipe.context.rng = self.rng
        fb = bool(getattr(self.camera_config, "use_measured_feedback", False))
        cx, cy = self.camera.get_fov_center_world(use_measured=fb)
        dcx, dcy = _apply_pose(cx, cy, self.disturbance_config, dt_eff, self.rng, pipeline=pipe)
        # Capture clean world (no post) — heavy post runs on 640×480 FOV only for real-time.
        frame_clean = self.scene.get_frame()
        try:
            frame_clean = self.remote.render_spots(frame_clean)
        except Exception:
            pass
        try:
            vig = float(getattr(self.env_config, "vignetting_pct", 0)) / 100.0
            if vig > 1e-3:
                from environment.vignetting import apply_vignetting
                frame_clean = apply_vignetting(frame_clean, vig)
        except Exception:
            pass
        frame = frame_clean
        self._last_frame = frame
        fov_frame = self.camera.extract_fov_at(frame, dcx, dcy)
        try:
            fov_frame = _apply_post(fov_frame, self.disturbance_config, dt_eff, self.rng, pipe, advance=False)
        except Exception:
            pass
        self._last_fov = fov_frame
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
            except (AttributeError, TypeError, ValueError):
                pass
            self._pending_track_error = None
            self._pending_pid_active = False
            self._pending_target_angles = None
            self._pending_target_vel = None
        self.step_count += 1
        reward = 0.0
        terminated = False
        truncated = self.step_count >= self.max_steps
        obs = self.get_observation()
        obs["frame"] = frame
        obs["fov_frame"] = fov_frame
        obs["tracker"] = sup_out.telemetry
        info = {
            "step_count": self.step_count,
            "camera": self.camera.get_telemetry(),
            "pid": self.controller.get_telemetry(),
        }
        return obs, float(reward), bool(terminated), bool(truncated), info

    def close(self):
        pass

    @property
    def observation_space(self):
        w, h = self._scene_size
        return {"frame": (h, w, 3)}

    @property
    def action_space(self):
        return {"shape": (0,)}

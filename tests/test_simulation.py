# tests/test_simulation.py - Headless simulation and FSOCEnv test suite
from __future__ import annotations

import numpy as np
import pytest

from camera.config import CameraConfig
from control.config import ControllerConfig
from disturbance.core.config import DisturbanceConfig
from environment.config import EnvironmentConfig
from simulation.env import FSOCEnv
from simulation.headless import HeadlessConfig, HeadlessSimulation


def test_headless_simulation_initialization_defaults():
    sim = HeadlessSimulation(seed=42)
    assert sim.seed == 42
    assert sim.step_count == 0
    obs = sim.get_observation()
    assert "pan" in obs
    assert "tilt" in obs
    assert "fov_rect" in obs
    assert "world_size" in obs
    assert "fov_size" in obs


def test_headless_simulation_determinism():
    sim1 = HeadlessSimulation(seed=123)
    sim2 = HeadlessSimulation(seed=123)

    obs1 = sim1.reset(seed=123)
    obs2 = sim2.reset(seed=123)

    assert obs1["pan"] == obs2["pan"]
    assert obs1["tilt"] == obs2["tilt"]

    step1, _, _, _, _ = sim1.step(action=np.array([2.0, -1.0]))
    step2, _, _, _, _ = sim2.step(action=np.array([2.0, -1.0]))

    assert np.array_equal(step1["frame"], step2["frame"])
    assert step1["pan"] == step2["pan"]
    assert step1["tilt"] == step2["tilt"]


def test_headless_simulation_custom_configs():
    env_cfg = EnvironmentConfig(world_width=3000, world_height=2500, star_count=50)
    cam_cfg = CameraConfig(fov_width=800, fov_height=600)
    ctrl_cfg = ControllerConfig(kp=0.5, output_clamp=50.0)
    dist_cfg = DisturbanceConfig(turbulence=3)

    sim = HeadlessSimulation(
        seed=99,
        env_config=env_cfg,
        camera_config=cam_cfg,
        controller_config=ctrl_cfg,
        disturbance_config=dist_cfg,
    )
    obs = sim.reset(seed=99)
    assert obs["world_size"] == (3000, 2500)
    assert obs["fov_size"] == (800, 600)


def test_headless_simulation_step_with_action():
    sim = HeadlessSimulation(seed=42)
    sim.reset(seed=42)
    init_pan, init_tilt = sim.camera.pan, sim.camera.tilt

    # Move camera
    obs, reward, term, trunc, info = sim.step(action=np.array([10.0, -5.0]))
    assert isinstance(obs, dict)
    assert "frame" in obs
    assert obs["frame"].shape == (480, 640, 3)
    assert reward == 0.0
    assert not term
    assert not trunc
    assert info["step_count"] == 1


def test_headless_simulation_truncation():
    sim = HeadlessSimulation(seed=42, max_steps=5)
    sim.reset(seed=42)
    for i in range(5):
        _, _, _, trunc, _ = sim.step()
        if i < 4:
            assert not trunc
        else:
            assert trunc


def test_fsoc_env_lifecycle():
    env = FSOCEnv(seed=42)
    obs, info = env.reset(seed=42)
    assert "image" in obs
    assert "vector" in obs
    assert obs["image"].shape == (480, 640, 3)
    assert obs["vector"].shape == (4,)
    assert info["step_count"] == 0

    action = np.array([5.0, -3.0], dtype=np.float32)
    obs, reward, term, trunc, info = env.step(action)
    assert obs["image"].shape == (480, 640, 3)
    assert reward == 0.0
    assert not term
    assert not trunc
    assert info["step_count"] == 1


def test_fsoc_env_render():
    env = FSOCEnv(seed=42, render_mode="rgb_array")
    env.reset(seed=42)
    frame = env.render()
    assert frame is not None
    assert frame.shape == (480, 640, 3)
    env.close()


def test_headless_simulation_remote_terminals():
    from remote_terminal.config import RemoteTerminalScenarioConfig
    scen_cfg = RemoteTerminalScenarioConfig(terminal_count=2)
    scen_cfg.motion.start_x = 1000.0
    scen_cfg.motion.start_y = 1000.0
    sim = HeadlessSimulation(seed=42, scenario_config=scen_cfg)
    obs = sim.reset(seed=42)
    assert "terminals" in obs
    assert obs["terminals"]["terminal_count"] == 2
    step_obs, _, _, _, _ = sim.step()
    assert "terminals" in step_obs
    assert step_obs["terminals"]["terminal_count"] == 2

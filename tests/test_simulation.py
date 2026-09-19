# tests/test_simulation.py - Headless simulation and FSOCEnv test suite
from __future__ import annotations

import numpy as np
import pytest

from disturbance.core.config import DisturbanceConfig
from environment.config import EnvironmentConfig
from simulation.env import FSOCEnv
from simulation.headless import HeadlessConfig, HeadlessSimulation


def test_headless_simulation_initialization_defaults():
    sim = HeadlessSimulation(seed=42)
    assert sim.seed == 42
    assert sim.step_count == 0
    obs = sim.get_observation()
    assert "world_size" in obs
    assert "step_count" in obs


def test_headless_simulation_determinism():
    sim1 = HeadlessSimulation(seed=123)
    sim2 = HeadlessSimulation(seed=123)

    obs1 = sim1.reset(seed=123)
    obs2 = sim2.reset(seed=123)

    assert np.array_equal(obs1["frame"], obs2["frame"])

    step1, _, _, _, _ = sim1.step()
    step2, _, _, _, _ = sim2.step()

    assert np.array_equal(step1["frame"], step2["frame"])


def test_headless_simulation_custom_configs():
    env_cfg = EnvironmentConfig(world_width=3000, world_height=2500, star_count=50)
    dist_cfg = DisturbanceConfig(turbulence=3)

    sim = HeadlessSimulation(
        seed=99,
        env_config=env_cfg,
        disturbance_config=dist_cfg,
    )
    obs = sim.reset(seed=99)
    assert obs["world_size"] == (3000, 2500)


def test_headless_simulation_step_with_action():
    sim = HeadlessSimulation(seed=42)
    sim.reset(seed=42)

    obs, reward, term, trunc, info = sim.step()
    assert isinstance(obs, dict)
    assert "frame" in obs
    assert obs["frame"].shape == (2000, 2000, 3)
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


def test_fsOC_env_lifecycle():
    env = FSOCEnv(seed=42)
    obs, info = env.reset(seed=42)
    assert "image" in obs
    assert "vector" in obs
    assert obs["image"].shape == (2000, 2000, 3)
    assert obs["vector"].shape == (2,)
    assert info["step_count"] == 0

    obs, reward, term, trunc, info = env.step()
    assert obs["image"].shape == (2000, 2000, 3)
    assert reward == 0.0
    assert not term
    assert not trunc
    assert info["step_count"] == 1


def test_fsOC_env_render():
    env = FSOCEnv(seed=42, render_mode="rgb_array")
    env.reset(seed=42)
    frame = env.render()
    assert frame is not None
    assert frame.shape == (2000, 2000, 3)
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

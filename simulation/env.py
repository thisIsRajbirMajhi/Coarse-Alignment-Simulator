# simulation/env.py - Gymnasium wrapper for HeadlessSimulation (optional, no hard dep)
from __future__ import annotations

import numpy as np

from common.rng import seed_global
from simulation.headless import HeadlessConfig, HeadlessSimulation

try:
    import gymnasium as gym
    from gymnasium import spaces
    _HAS_GYM = True
except ImportError:
    try:
        import gym
        from gym import spaces
        _HAS_GYM = True
    except ImportError:
        _HAS_GYM = False
        gym = None
        spaces = None


def _make_sim_from_config(headless_config: HeadlessConfig, seed: int) -> HeadlessSimulation:
    return HeadlessSimulation(
        seed=seed,
        env_config=headless_config.env,
        disturbance_config=headless_config.disturbance,
        max_steps=headless_config.max_steps,
        dt=headless_config.dt,
        sim_speed=headless_config.sim_speed,
    )


if _HAS_GYM:
    class FSOCEnv(gym.Env):  # type: ignore
        """
        Gymnasium Env for FSOC — headless, deterministic.
        Observation: Dict { "image": Box(0,255,(H,W,3),uint8), "vector": Box(-inf,inf,(2,),float32) }
        """
        metadata = {"render_modes": ["rgb_array", "human"], "render_fps": 30}

        def __init__(self, seed: int = 42, headless_config: HeadlessConfig | None = None, render_mode: str | None = None, **kwargs):
            super().__init__()
            cfg_kwargs = {}
            for k, v in kwargs.items():
                if k in HeadlessConfig.__dataclass_fields__:
                    cfg_kwargs[k] = v
                elif k == "env_config":
                    cfg_kwargs["env"] = v
                elif k == "disturbance_config":
                    cfg_kwargs["disturbance"] = v
            self.headless_config = headless_config or HeadlessConfig(seed=seed, **cfg_kwargs)
            self.headless_config.seed = int(seed)
            self.sim = _make_sim_from_config(self.headless_config, int(seed))
            self.render_mode = render_mode
            w, h = self.sim._scene_size
            self.observation_space = spaces.Dict({
                "image": spaces.Box(low=0, high=255, shape=(h, w, 3), dtype=np.uint8),
                "vector": spaces.Box(low=-5000, high=5000, shape=(2,), dtype=np.float32),
            })
            self.action_space = spaces.Box(low=-1.0, high=1.0, shape=(0,), dtype=np.float32)
            self._step_count = 0

        def reset(self, seed: int | None = None, options: dict | None = None):
            if seed is not None:
                self.headless_config.seed = int(seed)
                seed_global(seed)
            obs_dict = self.sim.reset(seed=seed)
            self._step_count = 0
            obs = self._to_gym_obs(obs_dict)
            info = {"step_count": 0}
            return obs, info

        def step(self, action=None):
            obs_dict, reward, terminated, truncated, info = self.sim.step(action=action)
            self._step_count += 1
            gym_obs = self._to_gym_obs(obs_dict)
            return gym_obs, float(reward), bool(terminated), bool(truncated), info

        def _to_gym_obs(self, obs_dict: dict):
            img = obs_dict.get("frame")
            if img is None:
                w, h = self.sim._scene_size
                img = np.zeros((h, w, 3), dtype=np.uint8)
            w, h = self.sim._scene_size
            vec = np.array([float(w), float(h)], dtype=np.float32)
            return {"image": img, "vector": vec}

        def render(self):
            if self.render_mode == "rgb_array":
                obs = self.sim.get_observation()
                vp = obs.get("frame")
                if vp is None:
                    w, h = self.sim._scene_size
                    return np.zeros((h, w, 3), dtype=np.uint8)
                return vp
            return None

        def close(self):
            try:
                self.sim.close()
            except Exception:
                pass

else:
    class FSOCEnv:  # type: ignore
        metadata = {"render_modes": ["rgb_array", "human"], "render_fps": 30}

        def __init__(self, seed: int = 42, headless_config: HeadlessConfig | None = None, render_mode: str | None = None, **kwargs):
            cfg_kwargs = {}
            for k, v in kwargs.items():
                if k in HeadlessConfig.__dataclass_fields__:
                    cfg_kwargs[k] = v
                elif k == "env_config":
                    cfg_kwargs["env"] = v
                elif k == "disturbance_config":
                    cfg_kwargs["disturbance"] = v
            self.headless_config = headless_config or HeadlessConfig(seed=seed, **cfg_kwargs)
            self.headless_config.seed = int(seed)
            self.sim = _make_sim_from_config(self.headless_config, int(seed))
            self.render_mode = render_mode
            self._step_count = 0

        def _to_gym_obs(self, obs_dict: dict):
            img = obs_dict.get("frame")
            if img is None:
                w, h = self.sim._scene_size
                img = np.zeros((h, w, 3), dtype=np.uint8)
            w, h = self.sim._scene_size
            vec = np.array([float(w), float(h)], dtype=np.float32)
            return {"image": img, "vector": vec}

        def reset(self, seed: int | None = None, options: dict | None = None):
            if seed is not None:
                seed_global(seed)
            obs_dict = self.sim.reset(seed=seed)
            self._step_count = 0
            obs = self._to_gym_obs(obs_dict)
            return obs, {"step_count": 0}

        def step(self, action=None):
            obs_dict, reward, terminated, truncated, info = self.sim.step(action=action)
            self._step_count += 1
            return self._to_gym_obs(obs_dict), reward, terminated, truncated, info

        def render(self):
            if self.render_mode == "rgb_array":
                obs = self.sim.get_observation()
                vp = obs.get("frame")
                if vp is None:
                    w, h = self.sim._scene_size
                    return np.zeros((h, w, 3), dtype=np.uint8)
                return vp
            return None

        def close(self):
            try:
                self.sim.close()
            except Exception:
                pass

        @property
        def observation_space(self):
            w, h = self.sim._scene_size
            return {"image": (h, w, 3), "vector": (2,)}

        @property
        def action_space(self):
            return {"shape": (0,)}

# simulation/env.py - Gymnasium wrapper for HeadlessSimulation (optional, no hard dep)
# beacon_tracker removed: no detector config.

from __future__ import annotations

import numpy as np

from simulation.headless import HeadlessSimulation, HeadlessConfig
from common.rng import seed_global

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
        camera_config=headless_config.camera,
        controller_config=headless_config.controller,
        disturbance_config=headless_config.disturbance,
        beacon_config=headless_config.beacon,
        max_steps=headless_config.max_steps,
        dt=headless_config.dt,
        sim_speed=headless_config.sim_speed,
        use_privileged_velocity=headless_config.use_privileged_velocity,
    )


if _HAS_GYM:
    class FSOCEnv(gym.Env):  # type: ignore
        """
        Gymnasium Env for FSOC — headless, deterministic.
        Observation: Dict { "image": Box(0,255,(H,W,3),uint8), "vector": Box(-inf,inf,(6,),float32), "lock": Discrete(2) }
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
                elif k == "camera_config":
                    cfg_kwargs["camera"] = v
                elif k == "controller_config":
                    cfg_kwargs["controller"] = v
                elif k == "disturbance_config":
                    cfg_kwargs["disturbance"] = v
                elif k == "beacon_config":
                    cfg_kwargs["beacon"] = v
            self.headless_config = headless_config or HeadlessConfig(seed=seed, **cfg_kwargs)
            self.headless_config.seed = int(seed)
            self.sim = _make_sim_from_config(self.headless_config, int(seed))
            self.render_mode = render_mode
            h, w = int(self.sim.camera_config.fov_height), int(self.sim.camera_config.fov_width)
            clamp = float(self.sim.controller_config.output_clamp)
            self.observation_space = spaces.Dict({
                "image": spaces.Box(low=0, high=255, shape=(h, w, 3), dtype=np.uint8),
                "vector": spaces.Box(low=-5000, high=5000, shape=(6,), dtype=np.float32),
                "lock": spaces.Discrete(2),
            })
            self.action_space = spaces.Box(low=-clamp, high=clamp, shape=(2,), dtype=np.float32)
            self._step_count = 0

        def reset(self, seed: int | None = None, options: dict | None = None):
            if seed is not None:
                self.headless_config.seed = int(seed)
                seed_global(seed)
            obs_dict = self.sim.reset(seed=seed)
            self._step_count = 0
            obs = self._to_gym_obs(obs_dict)
            info = {"lock_status": obs_dict.get("lock_status"), "step_count": 0}
            return obs, info

        def step(self, action):
            if action is not None:
                action = np.asarray(action, dtype=np.float32).reshape(-1)
                if action.shape[0] == 1:
                    action = np.array([float(action[0]), 0.0], dtype=np.float32)
                elif action.shape[0] > 2:
                    action = action[:2]
            obs_dict, reward, terminated, truncated, info = self.sim.step(action=action)
            self._step_count += 1
            gym_obs = self._to_gym_obs(obs_dict)
            return gym_obs, float(reward), bool(terminated), bool(truncated), info

        def _to_gym_obs(self, obs_dict: dict):
            img = obs_dict.get("frame", obs_dict.get("viewport"))
            if img is None:
                h, w = int(self.sim.camera_config.fov_height), int(self.sim.camera_config.fov_width)
                img = np.zeros((h, w, 3), dtype=np.uint8)
            est = obs_dict.get("estimate")
            if est is not None:
                cx, cy = self.sim.camera.fov_width/2, self.sim.camera.fov_height/2
                err_x = float(est[0] - cx)
                err_y = float(est[1] - cy)
            else:
                err_x, err_y = 0.0, 0.0
            pan = float(obs_dict.get("pan", self.sim.camera.pan))
            tilt = float(obs_dict.get("tilt", self.sim.camera.tilt))
            vx, vy = 0.0, 0.0
            try:
                if bool(getattr(self.sim.controller_config, "use_privileged_velocity", False)):
                    if hasattr(self.sim.target, "get_velocity"):
                        v = self.sim.target.get_velocity()
                        if v is not None:
                            vx, vy = float(v[0]), float(v[1])
            except Exception:
                vx, vy = 0.0, 0.0
            vec = np.array([err_x, err_y, pan, tilt, float(vx), float(vy)], dtype=np.float32)
            lock_map = {"searching":0, "tracking":1, "locked":1, "acquired":1, "lost":0}
            lock = lock_map.get(str(obs_dict.get("lock_status","searching")).lower(), 0)
            return {"image": img, "vector": vec, "lock": lock}

        def render(self):
            if self.render_mode == "rgb_array":
                obs = self.sim.get_observation()
                vp = obs.get("viewport") if "viewport" in obs else obs.get("frame")
                if vp is None:
                    h, w = int(self.sim.camera_config.fov_height), int(self.sim.camera_config.fov_width)
                    return np.zeros((h,w,3), dtype=np.uint8)
                return vp
            return None

        def close(self):
            try: self.sim.close()
            except Exception: pass

else:
    class FSOCEnv:  # type: ignore
        def __init__(self, seed: int = 42, headless_config: HeadlessConfig | None = None, **kwargs):
            cfg_kwargs = {}
            for k, v in kwargs.items():
                if k in HeadlessConfig.__dataclass_fields__:
                    cfg_kwargs[k] = v
                elif k == "env_config":
                    cfg_kwargs["env"] = v
                elif k == "camera_config":
                    cfg_kwargs["camera"] = v
                elif k == "controller_config":
                    cfg_kwargs["controller"] = v
                elif k == "disturbance_config":
                    cfg_kwargs["disturbance"] = v
                elif k == "beacon_config":
                    cfg_kwargs["beacon"] = v
            self.headless_config = headless_config or HeadlessConfig(seed=seed, **cfg_kwargs)
            self.headless_config.seed = int(seed)
            self.sim = _make_sim_from_config(self.headless_config, int(seed))
            self._step_count = 0

        def _to_gym_obs(self, obs_dict: dict):
            img = obs_dict.get("frame", obs_dict.get("viewport"))
            if img is None:
                h, w = int(self.sim.camera_config.fov_height), int(self.sim.camera_config.fov_width)
                img = np.zeros((h, w, 3), dtype=np.uint8)
            est = obs_dict.get("estimate")
            if est is not None:
                cx, cy = self.sim.camera.fov_width/2, self.sim.camera.fov_height/2
                err_x = float(est[0] - cx)
                err_y = float(est[1] - cy)
            else:
                err_x, err_y = 0.0, 0.0
            pan = float(obs_dict.get("pan", self.sim.camera.pan))
            tilt = float(obs_dict.get("tilt", self.sim.camera.tilt))
            vx, vy = 0.0, 0.0
            try:
                if bool(getattr(self.sim.controller_config, "use_privileged_velocity", False)):
                    if hasattr(self.sim.target, "get_velocity"):
                        v = self.sim.target.get_velocity()
                        if v is not None:
                            vx, vy = float(v[0]), float(v[1])
            except Exception:
                vx, vy = 0.0, 0.0
            vec = np.array([err_x, err_y, pan, tilt, float(vx), float(vy)], dtype=np.float32)
            lock_map = {"searching":0, "tracking":1, "locked":1, "acquired":1, "lost":0}
            lock = lock_map.get(str(obs_dict.get("lock_status","searching")).lower(), 0)
            return {"image": img, "vector": vec, "lock": lock}

        def reset(self, seed: int | None = None, options: dict | None = None):
            if seed is not None:
                seed_global(seed)
            obs_dict = self.sim.reset(seed=seed)
            self._step_count = 0
            obs = self._to_gym_obs(obs_dict)
            return obs, {"lock_status": obs_dict.get("lock_status"), "step_count": 0}

        def step(self, action):
            obs_dict, reward, terminated, truncated, info = self.sim.step(action=action)
            self._step_count += 1
            return self._to_gym_obs(obs_dict), reward, terminated, truncated, info

        def close(self):
            try: self.sim.close()
            except Exception: pass

        @property
        def observation_space(self):
            h, w = int(self.sim.camera_config.fov_height), int(self.sim.camera_config.fov_width)
            return {"image": (h,w,3), "vector": (6,), "lock": 2}

        @property
        def action_space(self):
            try:
                clamp = float(self.sim.controller_config.output_clamp)
            except Exception:
                clamp = 120.0
            return {"d_pan": (-clamp, clamp), "d_tilt": (-clamp, clamp), "shape": (2,)}

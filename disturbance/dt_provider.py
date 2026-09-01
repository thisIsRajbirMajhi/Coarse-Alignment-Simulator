# disturbance/dt_provider.py - Single source for dt resolution — eliminates 3× duplication in turbulence/vibrat

from __future__ import annotations

import time

class DtProvider:
    """
    Resolves dt for disturbance physics — either explicit dt or wall-clock delta.

    Usage:
      dt = DtProvider.resolve(state_dict, dt, key="last_wall")
      # state_dict[key] is updated to time.time() when dt is None
      # returned dt is clipped to [0.005, 0.08] for stability
    """

    @staticmethod
    def resolve(state: dict, dt: float | None, key: str = "last_wall", wall_fn=time.time, clip: tuple[float, float] = (0.005, 0.08)) -> float:
        if dt is not None:
            try:
                # Explicit dt — update last_wall for next wall fallback
                state[key] = wall_fn()
            except Exception:
                pass
            try:
                return float(max(clip[0], min(float(dt), clip[1])))
            except Exception:
                return float(clip[0])
        # Wall-clock fallback
        try:
            now = wall_fn()
            last = state.get(key, None)
            if last is None:
                state[key] = now
                return float(clip[0])
            delta = float(now - float(last))
            state[key] = now
            return float(max(clip[0], min(delta, clip[1])))
        except Exception:
            return float(clip[0])

    @staticmethod
    def update_wall(state: dict, key: str = "last_wall", wall_fn=time.time) -> None:
        try:
            state[key] = wall_fn()
        except Exception:
            pass
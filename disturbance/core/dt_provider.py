# disturbance/dt_provider.py - Single source for dt resolution — eliminates 3× duplication in turbulence/vibrat

from __future__ import annotations

import time

class DtProvider:
    """
    Resolves dt for disturbance physics — either explicit dt or wall-clock delta.

    Usage:
      dt = DtProvider.resolve(state_dict, dt, key="last_wall")
      # state_dict[key] is updated to time.time() when dt is None
      # returned dt is clipped to [1e-4, 0.1] for stability (single clip
      # everywhere; sim tick always passes explicit dt so the wall fallback
      # never runs on the hot path).

    Wall-clock fallback is kept for GUI/offline direct calls only.
    """

    @staticmethod
    def resolve(state: dict, dt: float | None, key: str = "last_wall", wall_fn=time.time, clip: tuple[float, float] = (1e-4, 0.1)) -> float:
        if dt is not None:
            # Explicit dt — do NOT touch the wall clock (avoids wall-leak
            # and keeps sim-time deterministic). Just clip for stability.
            try:
                return float(max(clip[0], min(float(dt), clip[1])))
            except (TypeError, ValueError):
                return float(clip[0])
        # Wall-clock fallback (offline/GUI direct calls only — never tick path)
        try:
            now = wall_fn()
            last = state.get(key, None)
            if last is None:
                state[key] = now
                return float(clip[0])
            delta = float(now - float(last))
            state[key] = now
            return float(max(clip[0], min(delta, clip[1])))
        except (TypeError, ValueError, AttributeError):
            return float(clip[0])

    @staticmethod
    def update_wall(state: dict, key: str = "last_wall", wall_fn=time.time) -> None:
        try:
            state[key] = wall_fn()
        except (TypeError, ValueError, AttributeError):
            pass
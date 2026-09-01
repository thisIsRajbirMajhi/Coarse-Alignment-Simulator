# tracking/filter.py - Exponential smoothing filter — first-order IIR low-pass (well-commented physics)

import numpy as np

class ExponentialFilter:
    """
    First-order IIR exponential smoother.

    - alpha=0.5 → y = 0.5·y_prev + 0.5·x (current default)
    - Handles None initial state: first detection seeds estimate directly.
    """

    def __init__(self, smoothing: float = 0.5):
        lo, hi = (0.0, 0.95)
        self.alpha = float(np.clip(float(smoothing), lo, hi))
        self.estimate: tuple[float, float] | None = None

    def update(self, detection: tuple[float, float] | None) -> tuple[float, float] | None:
        """
        Feed detection (or None if missed) — returns current estimate.

        - If detection is not None and estimate is None: seed directly (no smoothing)
        - If detection not None: y = α·y_prev + (1-α)·x
        - If detection is None: hold (no update, caller handles miss counters)
        """
        if detection is None:
            return self.estimate
        if self.estimate is None:
            self.estimate = detection
            return self.estimate
        ex, ey = self.estimate
        dx, dy = detection
        a = float(self.alpha)
        self.estimate = (a * ex + (1 - a) * dx, a * ey + (1 - a) * dy)
        return self.estimate

    def reset(self) -> None:
        self.estimate = None

    def set_smoothing(self, alpha: float) -> None:
        self.alpha = float(np.clip(float(alpha), 0.0, 0.95))
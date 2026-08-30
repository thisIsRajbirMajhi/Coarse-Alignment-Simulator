"""
Module: tracking.filter
Purpose: Exponential smoothing filter — first-order IIR low-pass (well-commented physics).
Public API: ExponentialFilter
Notes: Used by Tracker to smooth noisy detections into stable estimate.

Maths:
  y[n] = α·y[n-1] + (1-α)·x[n]   where
    y = estimated_position, x = detection, α = smoothing (0..1)
    α=0 → y=x (snap, no memory, responsive but noisy)
    α→1 → y≈y_prev (heavy smoothing, stable but lags)
  Equivalent to RC low-pass with time constant τ = -1/ln(α) frames.
  For α=0.5, τ≈1.44 frames — halves noise variance at cost of 1-frame lag.

Physics: Beacon scintillation and detector centroid jitter are high-frequency;
         exponential filter rejects them while preserving low-frequency target motion.
         Not a Kalman predictor — no velocity model, so it lags during fast maneuvers
         (future upgrade: Kalman would predict through occlusion).
"""

import numpy as np

# ============================================================
# SECTION: ExponentialFilter — IIR low-pass
# ============================================================

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

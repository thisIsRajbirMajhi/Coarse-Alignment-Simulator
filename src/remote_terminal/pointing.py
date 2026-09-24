# remote_terminal/pointing.py - PointingModel: beam direction only (§47).
#
# beam_angle = los_angle + pointing_error, with a small internal bias and
# jitter. Both are INTERNAL constants, never GUI parameters.
from __future__ import annotations

from typing import Any

from src.remote_terminal.geometry import normalize_angle_deg

# Internal pointing-error constants (degrees).
POINTING_BIAS_DEG: float = 0.005
POINTING_JITTER_SIGMA_DEG: float = 0.002


def _draw_gaussian(rng: Any, sigma: float) -> float:
    if hasattr(rng, "gauss"):  # stdlib random.Random
        return rng.gauss(0.0, sigma)
    if hasattr(rng, "normal"):  # numpy Generator
        return float(rng.normal(0.0, sigma))
    raise TypeError(f"RNG must provide gauss() or normal(), got {type(rng).__name__}.")


class PointingModel:
    """Nominal LOS + small bias/jitter (§47)."""

    def __init__(
        self,
        bias_deg: float = POINTING_BIAS_DEG,
        jitter_sigma_deg: float = POINTING_JITTER_SIGMA_DEG,
    ):
        self.bias_deg = float(bias_deg)
        self.jitter_sigma_deg = max(0.0, float(jitter_sigma_deg))

    def compute(self, los_angle_deg: float, rng: Any) -> tuple[float, float]:
        """Returns (beam_angle_deg, pointing_error_deg)."""
        error = self.bias_deg + _draw_gaussian(rng, self.jitter_sigma_deg)
        beam = normalize_angle_deg(float(los_angle_deg) + error)
        return beam, float(error)


__all__ = ["PointingModel", "POINTING_BIAS_DEG", "POINTING_JITTER_SIGMA_DEG"]

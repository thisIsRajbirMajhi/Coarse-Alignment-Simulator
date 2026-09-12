import numpy as np


def apply_photometric_fluctuation(value, intensity: float = 0.0, rng=None):
    if float(intensity) <= 0:
        return value
    generator = rng or np.random.default_rng()
    scale = max(0.0, float(intensity)) * 0.01
    return value * float(1.0 + generator.normal(0.0, scale))


__all__ = ["apply_photometric_fluctuation"]
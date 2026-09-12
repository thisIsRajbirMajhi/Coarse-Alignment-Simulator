"""Target motion perturbation hook."""


def perturb_motion(dx: float, dy: float, intensity: float = 0.0, rng=None):
    del intensity, rng
    return dx, dy


__all__ = ["perturb_motion"]
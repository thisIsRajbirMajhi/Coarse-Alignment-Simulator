"""Environmental clutter hook."""


def apply_clutter(frame, intensity: float = 0.0, rng=None):
    del intensity, rng
    return frame


__all__ = ["apply_clutter"]
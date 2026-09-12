"""Cloud evolution hook; cloud state belongs to the environment domain."""


def apply_clouds(frame, intensity: float = 0.0, rng=None):
    del intensity, rng
    return frame


__all__ = ["apply_clouds"]
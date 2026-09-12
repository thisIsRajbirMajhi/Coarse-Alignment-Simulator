import numpy as np


def should_dropout(probability: float = 0.0, rng=None) -> bool:
    if float(probability) <= 0:
        return False
    generator = rng or np.random.default_rng()
    return bool(generator.random() < min(1.0, float(probability)))


__all__ = ["should_dropout"]
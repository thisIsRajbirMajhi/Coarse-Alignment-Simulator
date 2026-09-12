from disturbance.environment.atmospheric import apply_atmospheric_disturbance


def apply_atmospheric_propagation(frame, **kwargs):
    return apply_atmospheric_disturbance(frame, **kwargs)


__all__ = ["apply_atmospheric_propagation"]
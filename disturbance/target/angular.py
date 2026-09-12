from disturbance.camera.jitter import apply_camera_jitter


def apply_angular_jitter(pan, tilt, jitter_px=0.0, rng=None):
    return apply_camera_jitter(pan, tilt, jitter_px=jitter_px, rng=rng)


__all__ = ["apply_angular_jitter"]
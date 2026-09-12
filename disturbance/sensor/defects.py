from disturbance.sensor.image_noise import clear_hot_pixel_cache


def reset_defects() -> None:
    clear_hot_pixel_cache()


__all__ = ["reset_defects"]
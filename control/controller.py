"""
Control module.

Converts a tracking error (how far the target is from FOV center) into
a pan/tilt correction command for the camera. Deliberately tiny and
swappable - start with a proportional controller, upgrade later
without touching anything else.
"""


class ProportionalController:
    def __init__(self, gain: float = 0.1):
        self.gain = gain

    def compute_correction(self, error_x: float, error_y: float) -> tuple[float, float]:
        """error_x/y = target offset from FOV center, in frame pixels."""
        return (self.gain * error_x, self.gain * error_y)

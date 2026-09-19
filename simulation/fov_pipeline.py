# simulation/fov_pipeline — shared post-capture image chain (single source).
#
# Extracted from duplicated logic in simulation/headless.py and
# gui/mixins/tick_mixin.py. Both callers must use these helpers so noise
# ordering / double-count fixes apply everywhere.
from __future__ import annotations
import numpy as np
from disturbance.core.config import DisturbanceConfig
from disturbance.core import DisturbanceContext, DisturbancePipeline


def apply_jitter(pan: float, tilt: float, dc, dt_eff: float, rng, jitter_state: dict | None = None,
                  pipeline: DisturbancePipeline | None = None):
    # Reuse the caller's pipeline so temporal state (OU phases) is preserved.
    # Creating a fresh pipeline per call would reset jitter/drift each frame.
    if pipeline is not None:
        pipeline.context.config = dc
        return pipeline.disturb_camera_pose(pan, tilt, dt_eff)
    import warnings
    warnings.warn("fov_pipeline.apply_jitter without pipeline: fresh OU state per frame (flicker); pass pipeline",
                  UserWarning, stacklevel=2)
    context = DisturbanceContext(dc, rng=rng, dt=dt_eff)
    return DisturbancePipeline(context).disturb_camera_pose(pan, tilt, dt_eff)


def apply_post_noise(frame: np.ndarray, dc, dt_eff: float, rng, pipeline: DisturbancePipeline | None = None,
                     advance: bool = True) -> np.ndarray:
    """Apply the optical stage followed by the sensor stage.

    Args:
        advance: when False, do not advance context time (caller already
            advanced via disturb_camera_pose this frame — avoids 2x ageing).
    """
    if pipeline is None:
        import warnings
        warnings.warn("fov_pipeline.apply_post_noise without pipeline: fresh pipeline per frame (OU reset); pass pipeline",
                      UserWarning, stacklevel=2)
        pipeline = DisturbancePipeline(DisturbanceContext(dc, rng=rng, dt=dt_eff))
        return pipeline.apply_frame(frame, advance=advance)
    pipeline.context.config = dc
    pipeline.context.dt = dt_eff
    if advance:
        return pipeline.apply_frame(frame)
    pipeline._sync_config()
    return pipeline.sensor.apply(pipeline.optical.apply(frame, pipeline.context), pipeline.context)

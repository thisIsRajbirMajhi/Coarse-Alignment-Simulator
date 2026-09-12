# simulation/fov_pipeline — shared post-capture image chain (single source).
#
# Extracted from duplicated logic in simulation/headless.py and
# gui/mixins/tick_mixin.py. Both callers must use these helpers so noise
# ordering / double-count fixes apply everywhere.
from __future__ import annotations
import numpy as np
from disturbance.core.config import DisturbanceConfig
from disturbance.core import DisturbanceContext, DisturbancePipeline


def apply_jitter(pan: float, tilt: float, dc, dt_eff: float, rng, jitter_state: dict | None):
    context = DisturbanceContext(dc, rng=rng, dt=dt_eff)
    return DisturbancePipeline(context).disturb_camera_pose(pan, tilt, dt_eff)


def apply_post_noise(frame: np.ndarray, dc, dt_eff: float, rng, pipeline: DisturbancePipeline | None = None) -> np.ndarray:
    """Apply the optical stage followed by the sensor stage."""
    if pipeline is None:
        pipeline = DisturbancePipeline(DisturbanceContext(dc, rng=rng, dt=dt_eff))
    else:
        pipeline.context.config = dc
        pipeline.context.rng = rng
        pipeline.context.dt = dt_eff
    return pipeline.apply_frame(frame)

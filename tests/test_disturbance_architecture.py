import numpy as np

from disturbance.config import DisturbanceConfig
from disturbance.core import DisturbanceContext, DisturbancePipeline, DisturbanceScenarioGenerator


def test_pipeline_state_isolated_between_instances():
    config = DisturbanceConfig(camera_jitter=8, vibration=4, turbulence=3).validate()
    first = DisturbancePipeline(DisturbanceContext(config, rng=np.random.default_rng(1)))
    second = DisturbancePipeline(DisturbanceContext(config, rng=np.random.default_rng(2)))

    first.disturb_camera_pose(100.0, 100.0, 0.033)
    assert first.camera.jitter_state is not second.camera.jitter_state
    assert first.optical.turbulence_state is not second.optical.turbulence_state


def test_pipeline_is_deterministic_for_same_seed_and_inputs():
    config = DisturbanceConfig(camera_jitter=4, turbulence=2, noise=2).validate()
    left = DisturbancePipeline(DisturbanceContext(config, rng=np.random.default_rng(7)))
    right = DisturbancePipeline(DisturbanceContext(config, rng=np.random.default_rng(7)))
    frame = np.full((24, 24, 3), 120, dtype=np.uint8)

    left_pose = left.disturb_camera_pose(100.0, 200.0, 0.033)
    right_pose = right.disturb_camera_pose(100.0, 200.0, 0.033)
    assert left_pose == right_pose
    assert np.array_equal(left.apply_frame(frame), right.apply_frame(frame))


def test_pipeline_reset_returns_temporal_state_to_initial_behavior():
    config = DisturbanceConfig(camera_jitter=5, vibration=2).validate()
    pipeline = DisturbancePipeline(DisturbanceContext(config, rng=np.random.default_rng(12)))
    initial = pipeline.disturb_camera_pose(50.0, 60.0, 0.033)
    pipeline.reset()
    pipeline.context.rng = np.random.default_rng(12)
    assert pipeline.disturb_camera_pose(50.0, 60.0, 0.033) == initial


def test_scenario_generator_is_seed_deterministic():
    generator = DisturbanceScenarioGenerator()
    assert generator.generate(42, "hard").to_dict() == generator.generate(42, "hard").to_dict()


def test_legacy_entry_point_still_works():
    from disturbance import disturbances

    frame = np.zeros((8, 8, 3), dtype=np.uint8)
    assert np.array_equal(disturbances.apply_turbulence(frame, 0), frame)
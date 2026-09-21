# tests/test_reacquisition_coords.py - Unit tests verifying coordinate handling across re-acquisition ladder.
import math
import pytest

from common.coordinates import (
    FovPoint,
    WorldPoint,
    PtzAngles,
    angles_to_world_center,
    fov_to_angles,
    fov_to_world,
    world_to_fov,
)
from local_terminal.detector import Detection
from local_terminal.motion import AlphaBetaFilter2D
from local_terminal.reacquisition import (
    EscalationStage,
    ReacquisitionConfig,
    ReacquisitionManager,
)
from local_terminal.scan import ScanController
from local_terminal.selector import StandbyCandidate, StandbyPool
from local_terminal.validator import ValidationSnapshot


def test_reacquisition_stage1_fov_to_angles():
    reacq = ReacquisitionManager()
    model = AlphaBetaFilter2D()
    # Initialize filter at center of FOV with vx=100 px/s
    model.initialise(310.0, 240.0, 320.0, 240.0, 0.1)

    reacq.start("RT-001", last_known_pos=(1000.0, 1000.0), model=model, now_s=0.0)
    assert reacq.stage == EscalationStage.LOCAL_SEARCH

    # Step at dt=0.1s: pred_x should be 320 + 10 = 330, pred_y = 240
    # Camera currently at (0°, 0°)
    res = reacq.update(
        detections=[],
        decode_result=None,
        now_s=0.1,
        dt=0.1,
        standby_pool=StandbyPool(),
        scan_ctrl=ScanController(),
        cam_home=(1000.0, 1000.0),
        px_per_deg=(160.0, 160.0),
        current_cam_angles=(0.0, 0.0),
    )
    assert res.target_angles is not None
    # 330 px is 10 px right of center 320. At 160 px/deg, pan should be +10/160 = +0.0625 deg
    expected_pan = (330.0 - 320.0) / 160.0
    assert math.isclose(res.target_angles[0], expected_pan, abs_tol=1e-3)
    assert math.isclose(res.target_angles[1], 0.0, abs_tol=1e-3)


def test_reacquisition_stage3_returns_fov_coords():
    reacq = ReacquisitionManager()
    reacq.start("RT-001", last_known_pos=(1000.0, 1000.0), model=AlphaBetaFilter2D(), now_s=0.0)
    reacq.stage = EscalationStage.PRIORITY_3X3

    # Create mock decode result matching RT-001
    class MockPayload:
        tid = "RT-001"
    class MockDecode:
        valid_crc = True
        payload = MockPayload()

    # Suppose a detection is at (310.0, 235.0) in FOV
    dets = [
        Detection(
            fov_x=310.0,
            fov_y=235.0,
            peak=200.0,
            sigma_px=4.0,
            snr_db=25.0,
            compactness_r2=0.9,
            pixel_count=20,
        )
    ]

    res = reacq.update(
        detections=dets,
        decode_result=MockDecode(),
        now_s=1.0,
        dt=0.033,
        standby_pool=StandbyPool(),
        scan_ctrl=ScanController(),
        cam_home=(1000.0, 1000.0),
        px_per_deg=(160.0, 160.0),
        current_cam_angles=(0.0, 0.0),
    )
    assert res.reacquired is True
    assert res.target_id == "RT-001"
    # Must be in FOV coordinates (0..640, 0..480), NOT world coordinates (~1000, 1000)
    assert res.target_pos is not None
    assert math.isclose(res.target_pos[0], 310.0, abs_tol=1e-2)
    assert math.isclose(res.target_pos[1], 235.0, abs_tol=1e-2)

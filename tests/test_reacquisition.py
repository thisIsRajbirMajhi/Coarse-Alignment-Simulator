# tests/test_reacquisition.py - Plan Phase 5: Re-acquisition Manager tests.
import pytest
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


def _mock_decode(tid="RT-001", valid=True):
    class MockPayload:
        def __init__(self, tid):
            self.tid = tid

    class MockResult:
        def __init__(self, tid, valid):
            self.valid_crc = valid
            self.payload = MockPayload(tid)

    return MockResult(tid, valid)


def test_reacquisition_provisional_and_confirm():
    """Plan.md §8.2: provisional resume gate on detection -> confirmed on CRC pass."""
    mgr = ReacquisitionManager(ReacquisitionConfig(initial_radius_px=50.0, radius_step_px=20.0))
    model = AlphaBetaFilter2D()
    model.update(1000.0, 1000.0, 1 / 30)

    mgr.start("RT-001", (1000.0, 1000.0), model, now_s=0.0)
    assert mgr.active
    assert mgr.stage == EscalationStage.LOCAL_SEARCH

    # Step 1: Candidate detected within 50 px -> provisional gate passed
    det = Detection(fov_x=320.0, fov_y=240.0, peak=150.0, sigma_px=3.5, snr_db=15.0, compactness_r2=0.9, pixel_count=20)
    pool = StandbyPool()
    scan = ScanController()

    res = mgr.update([det], None, now_s=0.033, dt=1 / 30, standby_pool=pool, scan_ctrl=scan)
    assert res.provisional is True
    assert res.reacquired is False
    assert mgr.provisional_active is True

    # Step 2: Full frame CRC passes with matching TID -> CONFIRMED!
    res = mgr.update([det], _mock_decode("RT-001", True), now_s=0.066, dt=1 / 30, standby_pool=pool, scan_ctrl=scan)
    assert res.reacquired is True
    assert res.target_id == "RT-001"
    assert not mgr.active


def test_reacquisition_escalation_to_standby_and_3x3():
    """Plan.md §8.3: expanding window breaches max_radius -> standby pool -> 3×3."""
    mgr = ReacquisitionManager(ReacquisitionConfig(initial_radius_px=50.0, radius_step_px=500.0, max_radius_px=600.0))
    model = AlphaBetaFilter2D()
    mgr.start("RT-001", (1000.0, 1000.0), model, now_s=0.0)

    pool = StandbyPool()
    snap = ValidationSnapshot(terminal_id="RT-002", score=0.85, state="SCORED")
    pool.update([StandbyCandidate(snapshot=snap, fov_x=500.0, fov_y=500.0, timestamp_s=0.0, score=0.85)], now_s=0.0)
    scan = ScanController()

    # Frame 1: radius 50 -> 550
    mgr.update([], None, now_s=0.033, dt=1 / 30, standby_pool=pool, scan_ctrl=scan)
    # Frame 2: radius 550 -> 1050 > max_radius (600) -> escalates to STANDBY_POOL
    res = mgr.update([], None, now_s=0.066, dt=1 / 30, standby_pool=pool, scan_ctrl=scan)
    assert mgr.stage == EscalationStage.STANDBY_POOL

    # Frame 3: Standby candidate tried
    res = mgr.update([], None, now_s=0.099, dt=1 / 30, standby_pool=pool, scan_ctrl=scan)
    # Standby pool tried -> escalates to PRIORITY_3X3
    res = mgr.update([], None, now_s=0.132, dt=1 / 30, standby_pool=pool, scan_ctrl=scan)
    assert mgr.stage == EscalationStage.PRIORITY_3X3

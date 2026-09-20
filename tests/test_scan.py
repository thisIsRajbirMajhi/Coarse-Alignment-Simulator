# tests/test_scan.py - Plan Phase 1: Search & Scan Controller tests.
import pytest
from local_terminal.scan import (
    GRID_COLS,
    GRID_ROWS,
    TOTAL_POSITIONS,
    X_STARTS,
    Y_STARTS,
    ScanConfig,
    ScanController,
    ScanPosition,
    build_grid,
)


def test_scan_grid_geometry():
    """Plan.md §4.1: 4 columns × 5 rows = 20 positions, 10% overlap, edge-anchored."""
    assert GRID_COLS == 4
    assert GRID_ROWS == 5
    assert TOTAL_POSITIONS == 20
    assert X_STARTS == (0, 576, 1152, 1360)
    assert Y_STARTS == (0, 432, 864, 1296, 1520)

    grid = build_grid(640, 480)
    assert len(grid) == 20
    assert grid[0].x_start == 0 and grid[0].y_start == 0
    assert grid[0].center_x == 320.0 and grid[0].center_y == 240.0

    # Last position: col 3, row 4
    last = grid[19]
    assert last.col == 3 and last.row == 4
    assert last.x_start == 1360 and last.y_start == 1520
    assert last.center_x == 1360 + 320.0 and last.center_y == 1520 + 240.0
    # Must fit completely within 2000×2000
    assert last.x_start + 640 == 2000
    assert last.y_start + 480 == 2000


def test_visited_registry_and_dwell():
    """Plan.md §4.1 & §4.3: position marked visited only after dwell completes."""
    ctrl = ScanController(ScanConfig(default_dwell_frames=1, decoding_dwell_frames=10))
    assert ctrl.visited_mask == 0
    assert ctrl.visited_count == 0

    # Frame 1: at position 0, default dwell = 1 frame -> marked visited
    pos0 = ctrl.step(has_decoding_candidate=False)
    assert (ctrl.visited_mask & 1) == 1
    assert ctrl.visited_count == 1

    # Position 1: candidate detected, extends dwell to 10 frames
    for i in range(9):
        ctrl.step(has_decoding_candidate=True)
        # Not yet visited during dwell
        assert (ctrl.visited_mask & (1 << 1)) == 0

    # 10th frame completes dwell
    ctrl.step(has_decoding_candidate=False)
    assert (ctrl.visited_mask & (1 << 1)) != 0
    assert ctrl.visited_count == 2


def test_priority_scheduling_last_known():
    """Plan.md §4.2: Last-known region schedules 3×3 patch first."""
    ctrl = ScanController()
    # Terminal at (300, 300) -> top-left region
    sched = ctrl.plan_schedule(priority_mode="LAST_KNOWN", last_known=(300.0, 300.0))
    assert len(sched) == 20
    # Position 0 (center at 320, 240) must be first
    assert sched[0] == 0


def test_priority_scheduling_predicted():
    """Plan.md §4.2: Predicted region sorts by velocity alignment."""
    ctrl = ScanController()
    # Moving right: vx = 50, vy = 0 from center (1000, 1000)
    sched = ctrl.plan_schedule(priority_mode="PREDICTED", last_known=(1000.0, 1000.0), velocity=(50.0, 0.0))
    assert len(sched) == 20
    # First item should have center_x > 1000
    p_first = ctrl.grid[sched[0]]
    assert p_first.center_x >= 1000.0


def test_timing_budget():
    """Plan.md §4.4: 20 positions × 1 frame = 20 frames per clean cycle."""
    ctrl = ScanController(ScanConfig(default_dwell_frames=1))
    for i in range(19):
        ctrl.step(has_decoding_candidate=False)
        assert not ctrl.cycle_completed

    # 20th frame completes cycle
    ctrl.step(has_decoding_candidate=False)
    assert ctrl.cycle_completed
    assert ctrl.cycle_count == 1

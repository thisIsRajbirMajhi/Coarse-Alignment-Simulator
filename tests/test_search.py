# tests/test_search.py - Multi-method smart search: grid, auto-switch, no-repeat.
import pytest


def _step_many(search, n, ranges=((0.0, 400.0), (0.0, 400.0)), dt=0.1, start=(50.0, 50.0)):
    from tracking.search import SearchPattern  # noqa
    p = start
    out = []
    for _ in range(n):
        p = search.step(p[0], p[1], ranges[0], ranges[1], dt)
        out.append(p)
    return out


def test_grid_covers_new_cells_without_repeats():
    from tracking.search import SearchPattern
    g = SearchPattern(pan_speed=200.0, row_step=40.0, mode="grid")
    seen = set()
    p = (0.0, 0.0)
    for _ in range(36):
        p = g.step(p[0], p[1], (0.0, 200.0), (0.0, 200.0), 0.1)
        seen.add((int(p[0] // 40), int(p[1] // 40)))
    # 36-cell sweep region: grid must keep finding fresh ground.
    assert len(seen) >= 20
    assert g.coverage > 0


def test_auto_switches_methods_on_interval():
    from tracking.search import SearchPattern
    a = SearchPattern(pan_speed=100.0, row_step=40.0, mode="auto", switch_interval_s=2.0)
    modes = set()
    p = (50.0, 50.0)
    for _ in range(200):
        p = a.step(p[0], p[1], (0.0, 400.0), (0.0, 400.0), 0.1)
        modes.add(a.active_mode)
    assert modes == {"raster", "grid", "spiral"}
    assert a.switches >= 5


def test_auto_keeps_coverage_across_switch():
    from tracking.search import SearchPattern
    a = SearchPattern(pan_speed=100.0, row_step=40.0, mode="auto", switch_interval_s=1.0)
    p = (50.0, 50.0)
    for _ in range(10):
        p = a.step(p[0], p[1], (0.0, 400.0), (0.0, 400.0), 0.1)
    covered_before = a.coverage
    assert covered_before > 0
    # Force a switch; visited map must survive (no re-search of swept ground).
    a._mode_time = 999.0
    p = a.step(p[0], p[1], (0.0, 400.0), (0.0, 400.0), 0.1)
    assert a.coverage >= covered_before


def test_raster_skips_fully_searched_rows():
    from tracking.search import SearchPattern
    s = SearchPattern(pan_speed=400.0, row_step=40.0, mode="raster")
    for ci in range(-2, 14):
        for cj in (1, 2, 3):
            s.visited_cells.add((ci, cj))
    p = (0.0, 0.0)
    tilts = set()
    for _ in range(200):
        p = s.step(p[0], p[1], (0.0, 400.0), (0.0, 400.0), 0.1)
        tilts.add(round(p[1]))
    # Rows at tilt 80/120 fully pre-searched: must jump over them.
    assert 80 not in tilts and 120 not in tilts
    assert 160 in tilts  # ...and continue into fresh ground


def test_mark_found_restarts_episode():
    from tracking.search import SearchPattern
    a = SearchPattern(pan_speed=100.0, row_step=40.0, mode="auto", switch_interval_s=1.0)
    p = _step_many(a, 30)[-1]
    assert a.coverage > 0
    a.mark_found()
    assert a.active_mode == "raster"
    assert a.coverage == 0
    assert a.switches == 0


def test_pipeline_defaults_to_auto_search():
    from tracking.pipeline import TrackingPipeline
    pipe = TrackingPipeline(fov_size=(640, 480))
    assert pipe.search.mode == "auto"
    assert pipe.search.active_mode == "raster"

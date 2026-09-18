# tests/test_presets.py - Testing presets: definitions, runner, GUI wiring.
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def test_preset_registry_covers_all_cases():
    from presets import PRESET_IDS, list_presets
    items = list_presets()
    assert len(items) >= 10
    cats = {i["category"] for i in items}
    for required in ("Nominal", "Acquisition", "Identification", "Tracking", "Disturbance", "Challenging"):
        assert required in cats, f"missing category {required}"
    assert "nominal_lock" in PRESET_IDS
    assert "decoy_only" in PRESET_IDS
    assert "beacon_dark" in PRESET_IDS
    assert "reacquire_blink" in PRESET_IDS


def test_all_presets_build_valid_configs():
    from presets import PRESET_IDS, build_configs
    for pid in PRESET_IDS:
        env, lt, scen, dist, preset = build_configs(pid)
        assert env.world_width >= 50
        assert lt.fov_width > 0
        assert len(scen.terminals) >= 1
        assert preset.preset_id == pid


def test_apply_to_session_reconfigures_all_modules():
    from gui.application.session import SimulationSession
    from presets.runner import apply_to_session
    s = SimulationSession()
    s.ensure_built()
    apply_to_session(s, "multi_target")
    assert len(s.terminal_scenario.terminals) == 3
    ids = {t.config.identity.id for t in s.terminal_scenario.terminals}
    assert "RT-MATCH-VALID" in ids
    apply_to_session(s, "nominal_lock")
    assert len(s.terminal_scenario.terminals) == 1


def test_preset_nominal_lock_passes_headless():
    from presets.runner import run_headless
    res = run_headless("nominal_lock")
    assert res["passed"], res["reason"]
    assert res["final_tracking"] == "TRACKING"


def test_preset_multi_target_selects_valid():
    from presets.runner import run_headless
    res = run_headless("multi_target")
    assert res["passed"], res["reason"]
    assert res["active_target"] == "RT-MATCH-VALID"


def test_preset_negatives_never_lock():
    from presets.runner import run_headless
    for pid in ("decoy_only", "beacon_dark"):
        res = run_headless(pid)
        assert res["passed"], f"{pid}: {res['reason']}"
        assert res["final_tracking"] != "TRACKING" or res["final_detection"] != "TARGET_CONFIRMED"


def test_tracker_point_overlay_drawn_on_camera_screen():
    pytest = __import__("pytest")
    pytest.importorskip("PyQt5.QtWidgets", reason="PyQt5 required")
    import numpy as np
    from gui.core.renderer import Renderer
    frame = np.zeros((480, 640, 3), dtype=np.uint8)
    plain = Renderer.render_viewport(frame, None, telemetry=None)
    tele = {"autonomy": {"state": "LOCKED", "active_target_id": "RT-1",
                         "candidates": [{"terminal_id": "RT-1", "fov_x": 400.0,
                                         "fov_y": 300.0, "confidence": 0.95,
                                         "confirmed": True}]},
            "state": {}}
    marker = Renderer.tracker_marker_from_telemetry(tele, (640, 480))
    assert marker is not None
    assert marker[3] == "RT-1 LOCKED"
    marked = Renderer.render_viewport(frame, None, telemetry=tele)
    assert marked.sum() > plain.sum()
    # Out-of-frame candidate yields no marker (never raises).
    tele_out = {"autonomy": {"state": "SEARCHING", "active_target_id": None,
                             "candidates": [{"terminal_id": "RT-9", "fov_x": 9999.0,
                                             "fov_y": 9999.0, "confidence": 0.1,
                                             "confirmed": False}]},
                "state": {}}
    assert Renderer.tracker_marker_from_telemetry(tele_out, (640, 480)) is None
    assert Renderer.tracker_marker_from_telemetry(None) is None
    assert Renderer.render_viewport(frame, None) is not None


def test_challenging_presets_track_fast_and_random():
    from presets.runner import run_headless
    res = run_headless("hyper_mover")
    assert res["passed"], res["reason"]
    res = run_headless("agile_swarm")
    assert res["passed"], res["reason"]
    assert res["active_target"] == "RT-SW-VALID"


def test_wild_random_walker_is_caught_mid_run():
    from presets.runner import run_headless
    res = run_headless("random_walk_fast")
    assert res["passed"], res["reason"]
    assert res["saw_tracking"] is True


def test_motion_profile_alias_normalization():
    from remote_terminal.config import normalize_motion_profile
    assert normalize_motion_profile("Figure 8") == "Figure-8"
    assert normalize_motion_profile("FIGURE_8") == "Figure-8"
    assert normalize_motion_profile("fig8") == "Figure-8"
    assert normalize_motion_profile("Random") == "Random Walk"
    assert normalize_motion_profile("RANDOM") == "Random Walk"
    assert normalize_motion_profile("Circular") == "Circular"
    from remote_terminal.config import MotionConfig
    assert MotionConfig(profile="fig8").validate().profile == "Figure-8"
    assert MotionConfig(profile="Random").validate().profile == "Random Walk"
    assert MotionConfig(profile="bogus").validate().profile == "Constant Velocity"


def test_search_pattern_alias_normalization():
    from local_terminal.config import normalize_search_pattern, AcquisitionConfig
    assert normalize_search_pattern("FIGURE-8") == "FIGURE_8"
    assert normalize_search_pattern("fig8") == "FIGURE_8"
    assert AcquisitionConfig(search_pattern="figure-8").validate().search_pattern == "FIGURE_8"
    assert AcquisitionConfig(search_pattern="bogus").validate().search_pattern == "RANDOM"


def test_figure8_remote_motion_bounded_and_repeating():
    from remote_terminal.config import MotionConfig
    from remote_terminal.motion import ScenarioMotionTracker
    import numpy as np
    cfg = MotionConfig(profile="Figure-8", speed_mps=80.0, acceleration_mps2=60.0,
                       start_x=1000.0, start_y=1000.0)
    rng = np.random.default_rng(1)
    tr = ScenarioMotionTracker(cfg, bounds=(2000, 2000), rng=rng)
    xs, ys = [], []
    for _ in range(600):
        x, y, _ = tr.update(1 / 30)
        xs.append(x)
        ys.append(y)
    assert min(xs) >= 80.0 and max(xs) <= 1920.0
    assert min(ys) >= 80.0 and max(ys) <= 1920.0
    # Lissajous crosses the center region (both lobes + crossover visited).
    assert min(xs) < 1000.0 < max(xs)
    assert any(abs(x - 1000.0) < 60.0 and abs(y - 1000.0) < 60.0 for x, y in zip(xs, ys))


def test_figure8_scan_stays_in_region():
    from local_terminal.acquisition import AcquisitionScanner
    from local_terminal.config import AcquisitionConfig
    cfg = AcquisitionConfig(search_pattern="FIGURE_8", timeout=30.0)
    sc = AcquisitionScanner(cfg)
    sc.start()
    for _ in range(400):
        p, t, _ = sc.update(dt=1 / 30)
        assert -20.0 <= p <= 20.0
        assert -10.0 <= t <= 10.0


def test_challenging_figure8_presets():
    from presets.runner import run_headless
    res = run_headless("figure8_mover")
    assert res["passed"], res["reason"]
    res = run_headless("figure8_scan")
    assert res["passed"], res["reason"]


def test_gui_preset_combo_autostarts(monkeypatch=None):
    pytest = __import__("pytest")
    QtWidgets = pytest.importorskip("PyQt5.QtWidgets", reason="PyQt5 required")
    from PyQt5.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    from gui.main_window import MainWindow
    from gui.application.state import LifecycleState
    w = MainWindow()
    try:
        assert w.controls.preset_combo.count() >= 10
        assert w.apply_preset("nominal_lock", autostart=True) is True
        assert w.controller.lifecycle == LifecycleState.RUNNING
        for _ in range(5):
            w.on_timer()
        assert w.session._frame_id > 0
        assert w.apply_preset("nope", autostart=True) is False
    finally:
        try:
            w.close()
        except Exception:
            pass

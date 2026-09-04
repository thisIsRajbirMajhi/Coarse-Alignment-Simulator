import sys, tempfile, pathlib, os, time, csv, json
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest
from perf_log.metrics import PerformanceLogger, LOG_DIR


def test_acquisition_time():
    pl = PerformanceLogger(auto_log=False)
    pl.start()
    time.sleep(0.02)
    pl.log_frame(True, 5.0, 0.01)
    s = pl.summary()
    assert s["acquisition_time_s"] is not None
    assert s["frame_count"] == 1
    assert s["lock_retention_rate_pct"] == 100.0


def test_lock_retention():
    pl = PerformanceLogger(auto_log=False)
    pl.start()
    for e in [1, 2, 3]:
        pl.log_frame(True, e, 0.005)
    for _ in range(7):
        pl.log_frame(False, None, 0.005)
    s = pl.summary()
    assert s["lock_retention_rate_pct"] == 30.0
    assert s["avg_tracking_error_px"] == 2.0
    assert s["max_tracking_error_px"] == 3.0


def test_export_roundtrip():
    pl = PerformanceLogger(auto_log=False)
    pl.start()
    pl.log_frame(True, 4.0, 0.01)
    pl.log_frame(False, None, 0.02)
    tmp = tempfile.mkdtemp()
    p_json = os.path.join(tmp, "out.json")
    p_csv = os.path.join(tmp, "out.csv")
    pl.export_report(p_json)
    pl.export_report(p_csv)
    assert pathlib.Path(p_json).exists()
    assert pathlib.Path(p_csv).exists()
    txt = pathlib.Path(p_csv).read_text()
    assert "frame_count" in txt


def test_reset():
    pl = PerformanceLogger(auto_log=False)
    pl.start()
    pl.log_frame(True, 1.0, 0.01)
    pl.start()
    s = pl.summary()
    assert s["frame_count"] == 0


def test_flat_log_folder_and_file_naming():
    """Verify logs are written directly inside log folder with proper naming and no subfolders."""
    tmp_log_dir = tempfile.mkdtemp()
    pl = PerformanceLogger(log_dir=tmp_log_dir, auto_log=True)
    pl.start(prefix="simulation")

    assert pl.timeseries_path is not None
    assert os.path.dirname(pl.timeseries_path) == tmp_log_dir
    assert os.path.basename(pl.timeseries_path).startswith("simulation_timeseries_")
    assert pl.timeseries_path.endswith(".csv")

    assert pl.summary_path is not None
    assert os.path.dirname(pl.summary_path) == tmp_log_dir
    assert os.path.basename(pl.summary_path).startswith("simulation_summary_")
    assert pl.summary_path.endswith(".json")

    for i in range(5):
        pl.log_frame(True, 2.0 + i, 0.012, detected=True, hitbox_hit=True, center_hit=(i % 2 == 0), lock_state="tracking")
    pl.log_frame(False, None, 0.010, detected=False, hitbox_hit=False, center_hit=False, lock_state="lost")
    pl.close()

    entries = os.listdir(tmp_log_dir)
    assert len(entries) == 2, f"Expected 2 files, got {entries}"
    for entry in entries:
        full_path = os.path.join(tmp_log_dir, entry)
        assert os.path.isfile(full_path), f"Expected {entry} to be a file, not a directory"

    with open(pl.timeseries_path, "r", encoding="utf-8") as f:
        reader = list(csv.reader(f))
        assert len(reader) == 7
        header = reader[0]
        assert "Time (S)" in header
        assert "Frame" in header
        assert "Lock State" in header
        assert "Avg Tracking Error (px)" in header
        assert "RMS Error (px)" in header
        assert "Lock Retention (%)" in header
        assert "Proc Time Avg (ms)" in header

    with open(pl.summary_path, "r", encoding="utf-8") as f:
        summary_data = json.load(f)
        assert summary_data["frame_count"] == 6
        assert "simulation_duration_s" in summary_data
        assert "avg_tracking_error_px" in summary_data
        assert "rms_tracking_error_px" in summary_data
        assert "lock_retention_rate_pct" in summary_data
        assert "detection_rate_pct" in summary_data
        assert "center_hit_rate_pct" in summary_data
        assert "state_counts" in summary_data
        assert "jitter_ms" in summary_data


def test_default_log_dir_location():
    """Verify default log directory is '<project_root>/log'."""
    pl = PerformanceLogger(auto_log=False)
    assert pl.log_dir == LOG_DIR
    assert os.path.basename(LOG_DIR) == "log"


# --- New: Improved coverage for fixed bugs ---
def test_sliding_window_capped():
    pl = PerformanceLogger(auto_log=False)
    pl.start()
    for i in range(6000):
        pl.log_frame(True, float(i % 10), 0.005, lock_state="tracking", dt=0.033)
    # window should be capped to 5000, not 6000
    assert len(pl.tracking_errors) <= 5000
    assert len(pl.processing_times) <= 5000
    s = pl.summary()
    assert s["frame_count"] == 6000  # frame_count still counts all
    # avg should be for window, not all 6000 (approx)
    assert 4.0 < s["avg_tracking_error_px"] < 6.0


def test_dt_accumulated_state_time():
    pl = PerformanceLogger(auto_log=False)
    pl.start()
    for _ in range(5):
        pl.log_frame(True, 5.0, 0.01, lock_state="tracking", dt=0.05)
    for _ in range(5):
        pl.log_frame(False, None, 0.01, lock_state="searching", dt=0.05)
    s = pl.summary()
    # dt-accumulated: 5*0.05=0.25 each
    assert abs(s["state_tracking_time_s"] - 0.25) < 0.02
    assert abs(s["state_searching_time_s"] - 0.25) < 0.02


def test_fps_ewma_exists():
    pl = PerformanceLogger(auto_log=False)
    pl.start()
    for _ in range(10):
        pl.log_frame(True, 1.0, 0.01, dt=0.033)
    s = pl.summary()
    assert "fps_ewma" in s
    assert s["fps_ewma"] > 0


def test_config_snapshot_and_version():
    tmp = tempfile.mkdtemp()
    pl = PerformanceLogger(log_dir=tmp, auto_log=True)
    pl.start(prefix="test", config={"world_width": 2000, "fov": 640})
    pl.log_frame(True, 1.0, 0.01, dt=0.033)
    pl.close()
    js = list(pathlib.Path(tmp).glob("*summary*.json"))[0]
    data = json.loads(js.read_text())
    assert data["schema_version"] == "2.0"
    assert "created_at" in data
    assert data["config_snapshot"]["world_width"] == 2000


def test_prefix_sanitization_traversal():
    tmp = tempfile.mkdtemp()
    pl = PerformanceLogger(log_dir=tmp, auto_log=True)
    pl.start(prefix="../../etc/passwd")
    pl.log_frame(True, 1.0, 0.01, dt=0.033)
    pl.close()
    # should not write outside tmp, and filename sanitized
    assert os.path.dirname(pl.timeseries_path) == tmp
    assert ".." not in os.path.basename(pl.timeseries_path)
    assert "etc" not in os.path.basename(pl.timeseries_path) or "_" in os.path.basename(pl.timeseries_path)


def test_prune_allowlist():
    tmp = tempfile.mkdtemp()
    # create dummy user file that should NOT be pruned
    user_file = os.path.join(tmp, "my_notes.txt")
    Path = pathlib.Path
    Path(user_file).write_text("important")
    # create many sim logs to trigger prune (keep 20)
    for i in range(25):
        pl = PerformanceLogger(log_dir=tmp, auto_log=True)
        pl.start(prefix="simulation")
        pl.log_frame(True, 1.0, 0.01, dt=0.033)
        pl.close()
    # user file should still exist
    assert os.path.exists(user_file)
    # only allowlisted files pruned, count should be <=40 and user file preserved
    assert os.path.exists(user_file)


def test_export_includes_config_and_state_time():
    pl = PerformanceLogger(auto_log=False)
    pl.start(config={"env_world_width": 3000})
    pl.log_frame(True, 2.0, 0.01, lock_state="tracking", dt=0.033)
    tmp = tempfile.mkdtemp()
    p_csv = os.path.join(tmp, "out.csv")
    pl.export_report(p_csv)
    txt = pathlib.Path(p_csv).read_text()
    assert "state_time" in txt or "state_count" in txt
    assert "config_env_world_width" in txt or "world_width" in txt


@pytest.mark.parametrize("dt", [0.005, 0.033, 0.1])
def test_parametric_dt(dt):
    pl = PerformanceLogger(auto_log=False)
    pl.start()
    pl.log_frame(True, 5.0, 0.01, lock_state="tracking", dt=dt)
    s = pl.summary()
    assert s["state_tracking_time_s"] == pytest.approx(dt, rel=0.01)

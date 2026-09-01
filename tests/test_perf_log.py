import sys, tempfile, pathlib, os, time, csv, json
sys.path.insert(0, r"C:\Users\mrajb\OneDrive\Desktop\FSOC Simulator")

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

    # Log several frames
    for i in range(5):
        pl.log_frame(True, 2.0 + i, 0.012, detected=True, hitbox_hit=True, center_hit=(i % 2 == 0), lock_state="tracking")
    pl.log_frame(False, None, 0.010, detected=False, hitbox_hit=False, center_hit=False, lock_state="lost")

    # Close the logger
    pl.close()

    # Check directory contents — ensure ONLY flat files exist, NO subdirectories
    entries = os.listdir(tmp_log_dir)
    assert len(entries) == 2, f"Expected 2 files, got {entries}"
    for entry in entries:
        full_path = os.path.join(tmp_log_dir, entry)
        assert os.path.isfile(full_path), f"Expected {entry} to be a file, not a directory"

    # Verify timeseries CSV contents
    with open(pl.timeseries_path, "r", encoding="utf-8") as f:
        reader = list(csv.reader(f))
        assert len(reader) == 7  # 1 header + 6 data rows
        header = reader[0]
        assert "Time (S)" in header
        assert "Frame" in header
        assert "Lock State" in header
        assert "Avg Tracking Error (px)" in header
        assert "RMS Error (px)" in header
        assert "Lock Retention (%)" in header
        assert "Proc Time Avg (ms)" in header

    # Verify summary JSON contents
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


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print(f"pass {name}")
    print("all perf_log tests passed")
import sys, tempfile, pathlib, os, time
sys.path.insert(0, r"C:\Users\mrajb\OneDrive\Desktop\FSOC Simulator")

from perf_log.metrics import PerformanceLogger

def test_acquisition_time():
    pl = PerformanceLogger()
    pl.start()
    time.sleep(0.02)
    pl.log_frame(True, 5.0, 0.01)
    s = pl.summary()
    assert s["acquisition_time_s"] is not None
    assert s["frame_count"] == 1
    assert s["lock_retention_rate_pct"] == 100.0

def test_lock_retention():
    pl = PerformanceLogger()
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
    pl = PerformanceLogger()
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
    pl = PerformanceLogger()
    pl.start()
    pl.log_frame(True, 1.0, 0.01)
    pl.start()
    s = pl.summary()
    assert s["frame_count"] == 0

if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print(f"pass {name}")
    print("all perf_log tests passed")
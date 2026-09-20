# tests/test_local_terminal.py - Plan Stage 1: detector + image tracker + closed loop.
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
import pytest

from local_terminal import (
    AlphaBetaFilter2D,
    Detection,
    DetectorConfig,
    ImageTracker,
    TrackerConfig,
    detect_candidates,
)


@pytest.fixture(scope="module")
def qapp():
    pytest.importorskip("PyQt5.QtWidgets", reason="PyQt5 required")
    from PyQt5.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def _spot_frame(cx=100.0, cy=200.0, peak=150.0, sigma=3.5, size=(480, 640), bg=8.0, seed=0):
    rng = np.random.default_rng(seed)
    h, w = size
    ys, xs = np.mgrid[0:h, 0:w].astype(np.float64)
    frame = bg + rng.normal(0, 1.5, (h, w))
    frame += peak * np.exp(-((xs - cx) ** 2 + (ys - cy) ** 2) / (2 * sigma * sigma))
    return np.clip(frame, 0, 255).astype(np.uint8)


def test_detector_finds_synthetic_gaussian():
    frame = _spot_frame()
    dets = detect_candidates(frame)
    assert len(dets) == 1
    d = dets[0]
    assert abs(d.fov_x - 100.0) < 1.0
    assert abs(d.fov_y - 200.0) < 1.0
    assert abs(d.sigma_px - 3.5) < 0.75
    assert d.compactness_r2 >= 0.75
    assert d.snr_db >= 6.0


def test_detector_rejects_dim_spot():
    assert detect_candidates(_spot_frame(peak=20.0)) == []


def test_detector_rejects_streak():
    frame = np.full((480, 640), 8.0)
    frame[200, 50:200] = 150.0  # bright horizontal streak, not a spot
    assert detect_candidates(frame.astype(np.uint8)) == []


def test_detector_empty_frame_silent():
    assert detect_candidates(np.zeros((480, 640, 3), dtype=np.uint8)) == []


def test_tracker_lock_and_loss_counting():
    tr = ImageTracker(TrackerConfig(associate_gate_px=60.0, loss_after_misses=3))
    det = Detection(fov_x=320.0, fov_y=240.0, peak=120.0, sigma_px=3.2,
                    snr_db=20.0, compactness_r2=0.95, pixel_count=100)
    snap = tr.update([det], 1 / 30, 0.033)
    assert snap.locked and snap.first_lock_time_s == pytest.approx(0.033)
    assert tr.error_px() == pytest.approx((0.0, 0.0))
    for i in range(3):
        tr.update([], 1 / 30, 0.033 * (i + 2))
    assert tr.snapshot().locked  # coasts through ≤3 misses
    assert tr.error_px() is not None  # coasting steers to prediction (§7.1)
    tr.update([], 1 / 30, 0.2)
    snap = tr.snapshot()
    assert not snap.locked and snap.loss_count == 1
    assert tr.error_px() is None  # lost: no error
    tr.update([det], 1 / 30, 0.233)
    assert tr.snapshot().locked
    assert tr.snapshot().first_lock_time_s == pytest.approx(0.033)  # first lock kept


def test_tracker_default_bridges_ook_blink():
    """Default loss horizon must span dark OOK runs (header zero-runs hide
    the spot for several consecutive camera frames on real beacon frames)."""
    tr = ImageTracker()  # defaults
    det = Detection(fov_x=320.0, fov_y=240.0, peak=120.0, sigma_px=3.2,
                    snr_db=20.0, compactness_r2=0.95, pixel_count=100)
    tr.update([det], 1 / 30, 0.033)
    for i in range(8):  # 8-frame dark run: still coasting, no loss
        snap = tr.update([], 1 / 30, 0.033 * (i + 2))
    assert snap.locked and snap.loss_count == 0


def test_tracker_autonomy_schema():
    tr = ImageTracker()
    det = Detection(fov_x=400.0, fov_y=300.0, peak=120.0, sigma_px=3.2,
                    snr_db=20.0, compactness_r2=0.95, pixel_count=100)
    tr.update([det], 1 / 30, 0.033)
    tel = tr.autonomy_telemetry()
    assert tel["autonomy"]["state"] == "LOCKED"
    assert tel["autonomy"]["active_target_id"] == "TRACK"
    cand = tel["autonomy"]["candidates"][0]
    assert 0 <= cand["fov_x"] < 640 and 0 <= cand["fov_y"] < 480
    assert tel["locked"] and tel["detection_rate_pct"] == 100.0


def test_headless_image_loop_acquires_and_tracks():
    from disturbance.core.config import DisturbanceConfig
    from simulation.headless import HeadlessSimulation

    sim = HeadlessSimulation(seed=1, disturbance_config=DisturbanceConfig().validate())
    sim.reset(seed=1)
    last = None
    for _ in range(30):
        obs, _, _, _, _ = sim.step()
        last = obs["tracker"]
    assert last["locked"]
    assert last["acquisition_time_s"] is not None and last["acquisition_time_s"] <= 1.0


def test_headless_image_loop_deterministic():
    from disturbance.core.config import DisturbanceConfig
    from simulation.headless import HeadlessSimulation

    def run():
        sim = HeadlessSimulation(seed=3, disturbance_config=DisturbanceConfig().validate())
        sim.reset(seed=3)
        frames, tracks = [], []
        for _ in range(10):
            obs, _, _, _, _ = sim.step()
            frames.append(obs["fov_frame"])
            tracks.append(obs["tracker"])
        return frames, tracks

    f1, t1 = run()
    f2, t2 = run()
    assert all(np.array_equal(a, b) for a, b in zip(f1, f2))
    assert t1 == t2


def test_beacon_off_never_locks():
    from disturbance.core.config import DisturbanceConfig
    from remote_terminal import make_default_scenario
    from simulation.headless import HeadlessSimulation

    scen = make_default_scenario(1)
    scen.terminals[0].power_enabled = False
    scen.validate()
    sim = HeadlessSimulation(seed=1, scenario_config=scen,
                             disturbance_config=DisturbanceConfig().validate())
    sim.reset(seed=1)
    last = None
    for _ in range(10):
        obs, _, _, _, _ = sim.step()
        last = obs["tracker"]
    assert not last["locked"]
    assert last["acquisition_time_s"] is None


def test_gui_session_reports_tracker_telemetry():
    from disturbance.core.config import DisturbanceConfig
    from gui.application.session import SimulationSession

    sess = SimulationSession(disturbance_config=DisturbanceConfig().validate(), seed=7)
    sess.build()
    snap = None
    for _ in range(30):
        snap = sess.step(1 / 30)
    assert snap.tracker_telemetry is not None
    assert snap.tracker_telemetry["locked"]


# ---------------- Stage 2: motion model ----------------

def test_alpha_beta_tracks_constant_velocity():
    f = AlphaBetaFilter2D()
    dt = 1 / 30
    # True motion: x = 100 + 60*t (60 px/s).
    for i in range(30):
        f.update(100.0 + 60.0 * i * dt, 200.0, dt)
    vx, _ = f.velocity
    assert vx == pytest.approx(60.0, rel=0.1)
    px, _ = f.predict(dt)
    assert px == pytest.approx(100.0 + 60.0 * 30 * dt, abs=2.0)


def test_alpha_beta_coast_grows_uncertainty_to_cap():
    f = AlphaBetaFilter2D()
    dt = 1 / 30
    f.update(320.0, 240.0, dt)
    f.update(322.0, 240.0, dt)
    for _ in range(100):
        f.coast(dt)
    assert f.uncertainty_px == pytest.approx(30.0)  # capped at search cap
    px, _ = f.predict(dt)
    assert px > 322.0  # coasts along estimated velocity


def test_tracker_prediction_gates_moving_target():
    tr = ImageTracker()
    dt = 1 / 30
    # Target drifts +5 px/frame in x.
    for i in range(6):
        d = Detection(fov_x=300.0 + 5 * i, fov_y=240.0, peak=120.0,
                      sigma_px=3.2, snr_db=20.0, compactness_r2=0.95, pixel_count=100)
        snap = tr.update([d], dt, 0.033 * (i + 1))
    assert snap.locked
    vx, _ = tr.model.velocity
    assert vx == pytest.approx(150.0, rel=0.2)  # 5 px / 33 ms
    # Next detection near prediction associates even past the base gate.
    pred = tr.predicted_fov
    d = Detection(fov_x=pred[0] + 40.0, fov_y=240.0, peak=120.0,
                  sigma_px=3.2, snr_db=20.0, compactness_r2=0.95, pixel_count=100)
    snap = tr.update([d], dt, 0.033 * 7)
    assert snap.locked and snap.misses == 0


def test_tracker_origin_shift_compensates_camera_motion():
    tr = ImageTracker()
    dt = 1 / 30
    d = Detection(fov_x=320.0, fov_y=240.0, peak=120.0,
                  sigma_px=3.2, snr_db=20.0, compactness_r2=0.95, pixel_count=100)
    tr.update([d], dt, 0.033)
    tr.update([d], dt, 0.066)
    # Camera slews 50 px right: spot appears 50 px left in the new frame.
    d2 = Detection(fov_x=270.0, fov_y=240.0, peak=120.0,
                   sigma_px=3.2, snr_db=20.0, compactness_r2=0.95, pixel_count=100)
    snap = tr.update([d2], dt, 0.1, origin_shift=(50.0, 0.0))
    assert snap.locked and snap.misses == 0
    vx, _ = tr.model.velocity
    assert abs(vx) < 30.0  # shift absorbed, not mistaken for target motion


def test_measured_feedback_center_differs_by_quantization():
    from camera.config import CameraConfig
    from camera.ptz import PTZCamera

    cam = PTZCamera(config=CameraConfig(encoder_noise_deg=0.01).validate())
    cam.update(1 / 30, cmd_pan_vel=2.0, cmd_tilt_vel=-1.0)
    true_c = cam.get_fov_center_world()
    meas_c = cam.get_fov_center_world(use_measured=True)
    # 16-bit encoder step ≈ 0.0055° ≈ 0.9 px; noise 0.01° ≈ 1.6 px.
    assert abs(meas_c[0] - true_c[0]) < 8.0
    assert abs(meas_c[1] - true_c[1]) < 8.0


def test_camera_panel_measured_feedback_round_trip(qapp):
    from gui.panels.camera_panel import CameraPanel

    panel = CameraPanel()
    assert panel.collect_config().use_measured_feedback is False
    panel.chk_measured_feedback.setChecked(True)
    assert panel.collect_config().use_measured_feedback is True


def test_moving_target_tracking_error_bounded():
    """Constant-velocity terminal: image loop keeps centroid near boresight."""
    from disturbance.core.config import DisturbanceConfig
    from remote_terminal import make_default_scenario
    from remote_terminal.config import MotionProfile
    from simulation.headless import HeadlessSimulation

    scen = make_default_scenario(1)
    scen.formation.motion_profile = MotionProfile.CONSTANT_VELOCITY
    scen.formation.speed_mps = 10.0
    scen.validate()
    sim = HeadlessSimulation(seed=11, scenario_config=scen,
                             disturbance_config=DisturbanceConfig().validate())
    sim.reset(seed=11)
    errs = []
    last = None
    for _ in range(60):
        obs, _, _, _, _ = sim.step()
        last = obs["tracker"]
        if last["locked"] and last["misses"] == 0:
            cx = last["autonomy"]["candidates"][0]["fov_x"]
            cy = last["autonomy"]["candidates"][0]["fov_y"]
            errs.append(abs(cx - 320.0) + abs(cy - 240.0))
    assert last["locked"]  # blink-bridged: no loss declared all run
    assert last["target_loss_count"] == 0
    assert len(errs) > 10  # fresh detections throughout despite OOK blink
    assert float(np.mean(errs)) < 15.0  # loop holds centroid near boresight

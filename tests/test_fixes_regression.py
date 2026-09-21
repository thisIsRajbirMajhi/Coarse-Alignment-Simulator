# tests/test_fixes_regression.py - Regression tests for Fixes.md re-check items.
#
# Covers: C-04 (full-reset PTZ homing), C-11/8.1 (CommSource link metadata),
# 5.1 (re-acquisition gate around prediction), 7.2 (require_nav enforcement),
# 5.5 (PID feed-forward velocity plumbing).
from __future__ import annotations

import numpy as np


def _spot_image(cx: float = 320.0, cy: float = 240.0, peak: float = 200.0,
                sigma: float = 4.0, w: int = 640, h: int = 480):
    img = np.zeros((h, w, 3), dtype=np.uint8)
    yy, xx = np.mgrid[0:h, 0:w]
    spot = (peak * np.exp(-((xx - cx) ** 2 + (yy - cy) ** 2) / (2 * sigma ** 2))).astype(np.uint8)
    img[:, :, 0] = img[:, :, 1] = img[:, :, 2] = spot
    return img


def test_full_reset_homes_camera_in_session():
    """Fixes.md C-04/8.4: full_reset() → next integrated step homes the PTZ."""
    from gui.application.session import SimulationSession

    sess = SimulationSession()
    sess.build()
    # Drive the gimbal away from home.
    sess.camera.set_target_angles(4.0, 2.0)
    for _ in range(30):
        sess.camera.update(1 / 30)
    assert abs(sess.camera.pan_deg) > 0.5 or abs(sess.camera.tilt_deg) > 0.5

    assert sess.supervisor.full_reset() is True
    sess.step(1 / 30)

    st = sess.camera.get_state()
    home_pan, home_tilt = sess.camera_config.get_initial_pose()
    assert st.pan_deg == home_pan
    assert st.tilt_deg == home_tilt
    assert st.pan_vel_deg_s == 0.0
    assert st.tilt_vel_deg_s == 0.0
    assert st.pan_accel_deg_s2 == 0.0
    assert st.tilt_accel_deg_s2 == 0.0


def test_full_reset_emits_camera_reset_event_once():
    """The reset event fires exactly once per full_reset (no repeat homing)."""
    from local_terminal import AutonomySupervisor, SignatureRegistry
    from remote_terminal import make_default_scenario

    sup = AutonomySupervisor(registry=SignatureRegistry.from_scenario(make_default_scenario()))
    assert sup.full_reset() is True
    img = np.zeros((480, 640, 3), dtype=np.uint8)
    out1 = sup.step(img, 1 / 30, 0.033)
    assert out1.camera_reset_requested is True
    out2 = sup.step(img, 1 / 30, 0.066)
    assert out2.camera_reset_requested is False


def test_commsource_carries_link_metadata():
    """Fixes.md C-11: CommSource carries TX power + link metadata end-to-end."""
    from gui.application.session import SimulationSession

    sess = SimulationSession()
    sess.build()
    captured: dict = {}
    orig_step = sess.supervisor.step

    def _spy(**kwargs):
        captured["sources"] = kwargs.get("comm_sources", [])
        return orig_step(**kwargs)

    sess.supervisor.step = _spy  # type: ignore[method-assign]
    try:
        sess.step(1 / 30)
    finally:
        sess.supervisor.step = orig_step  # type: ignore[method-assign]

    sources = captured.get("sources", [])
    assert len(sources) >= 1
    src = sources[0]
    # TX high-chip source power (Fixes.md 3.5), not coupled instantaneous power.
    assert float(src.power_w) == float(sess.scenario_config.terminals[0].optical_power_w)
    assert float(src.wavelength_nm) == float(sess.scenario_config.terminals[0].wavelength_nm)
    assert float(src.range_m) > 0.0
    assert float(src.beam_diameter_m) > 0.0


def test_reacquisition_gates_around_prediction():
    """Fixes.md 5.1: Stage-1 gate measures from predicted pos, not FOV center."""
    from local_terminal.detector import Detection
    from local_terminal.motion import AlphaBetaFilter2D
    from local_terminal.reacquisition import ReacquisitionConfig, ReacquisitionManager
    from local_terminal.scan import ScanController
    from local_terminal.selector import StandbyPool

    model = AlphaBetaFilter2D()
    model.update(500.0, 400.0, 1 / 30)
    mgr = ReacquisitionManager(ReacquisitionConfig(initial_radius_px=50.0, radius_step_px=5.0))
    mgr.start("RT-001", (1000.0, 1000.0), model, 0.0)

    def _det(x, y):
        return Detection(fov_x=x, fov_y=y, peak=200.0, sigma_px=4.0,
                         snr_db=20.0, compactness_r2=0.95, pixel_count=40)

    scan = ScanController()
    # Boresight-near distractor far from prediction must NOT match.
    res = mgr.update([_det(320.0, 240.0)], None, 0.033, 1 / 30,
                     StandbyPool(), scan)
    assert res.provisional is False
    # Detection at the predicted location must match.
    res = mgr.update([_det(502.0, 401.0)], None, 0.066, 1 / 30,
                     StandbyPool(), scan)
    assert res.provisional is True


def test_validator_rejects_missing_nav_when_required():
    """Fixes.md 7.2: require_nav entries reject payloads without nav extension."""
    from common.protocol.beacon.frame import BeaconDecodeResult
    from common.protocol.beacon.navigation import NavigationState2D, encode_navigation_state
    from common.protocol.beacon.payload import BeaconPayload
    from local_terminal import SignatureRegistry
    from local_terminal.validator import TrackValidator
    from remote_terminal import make_default_scenario

    reg = SignatureRegistry.from_scenario(make_default_scenario(), require_nav=True)
    val = TrackValidator(reg)

    bare = BeaconDecodeResult(valid_crc=True, reason="OK",
                              payload=BeaconPayload(tid="RT-001", token="RT-001",
                                                    wl=1550, seq=5))
    snap = val.ingest(bare, {"snr_db": 20.0, "peak": 200.0, "centroid": (320.0, 240.0)},
                      False, 0.033)
    assert snap.state == "REJECTED"
    assert snap.reject_reason == "missing_nav"

    from common.protocol.beacon.navigation import CAP_NAVIGATION_STATE
    nav = encode_navigation_state(NavigationState2D(timestamp_ms=33,
                                                    position_x_m=0.0, position_y_m=0.0))
    with_nav = BeaconDecodeResult(
        valid_crc=True, reason="OK",
        payload=BeaconPayload(tid="RT-001", token="RT-001", wl=1550, seq=6,
                              capabilities=CAP_NAVIGATION_STATE, nav=nav))
    val2 = TrackValidator(reg)
    snap2 = val2.ingest(with_nav, {"snr_db": 20.0, "peak": 200.0, "centroid": (320.0, 240.0)},
                        False, 0.033)
    assert snap2.reject_reason != "missing_nav"


def test_pid_feedforward_velocity_flows():
    """Fixes.md 5.5: tracker α-β velocity reaches the supervisor output."""
    from local_terminal import AutonomySupervisor, SignatureRegistry
    from local_terminal.supervisor import AutonomyState
    from remote_terminal import make_default_scenario

    sup = AutonomySupervisor(registry=SignatureRegistry.from_scenario(make_default_scenario()))
    sup.state = AutonomyState.TRACK
    sup.tracker.lock_target("RT-001", 320.0, 240.0, 0.0)
    out = sup.step(_spot_image(322.0, 241.0), 1 / 30, 0.033, comm_sources=[])
    assert out.pid_active is True
    assert out.track_error_px is not None
    assert out.target_vel_px_s is not None
    vx, vy = out.target_vel_px_s
    assert np.isfinite(vx) and np.isfinite(vy)

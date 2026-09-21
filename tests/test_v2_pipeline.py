# tests/test_v2_pipeline.py - V2 contracts + module boundaries (Plan V2 §22).
import numpy as np

from local_terminal.association import associate_acquisition, associate_tracking
from local_terminal.detector import TemporalConfirmer, detect_spots
from local_terminal.identity import IdentityValidator
from local_terminal.models import (
    AutonomyConfig,
    BeaconObservation,
    SpotCandidate,
    TargetObservation,
    TargetTrack,
)
from local_terminal.reacquisition import V2Reacquisition
from local_terminal.registry import SignatureRegistry
from local_terminal.selector import select_active_v2
from local_terminal.supervisor import SupervisorV2, V2State
from local_terminal.tracker import KalmanFilter2D, KalmanTracker, r_for_snr


def _registry():
    reg = SignatureRegistry()
    from local_terminal.registry import ExpectedSignature
    reg.entries["RT-002"] = ExpectedSignature("RT-002", 1550.0)
    return reg


def test_models_roundtrip():
    for cls, kw in [
        (SpotCandidate, {"x": 1.5, "y": 2.5, "peak": 100.0, "snr_db": 12.0, "area_px": 20}),
        (BeaconObservation, {"terminal_id": "RT-002", "valid_crc": True, "sequence": 5,
                             "wavelength_nm": 1550.0, "p_rx_w": 1e-3, "snr_db": 15.0}),
        (TargetObservation, {"terminal_id": "RT-002", "fov_x": 320.0, "fov_y": 240.0}),
        (TargetTrack, {"terminal_id": "RT-002", "x": 1.0, "status": "TRACKING"}),
        (AutonomyConfig, {}),
    ]:
        obj = cls(**kw).validate()
        assert cls.from_dict(obj.to_dict()).validate() is not None
    bad = AutonomyConfig(search_pattern="bogus",
                         reacq_radii_px=[],
                         active_target_policy="bogus").validate()
    assert bad.search_pattern == "systematic"
    assert bad.active_target_policy == "priority"


def test_detect_spots_clean_and_empty():
    frame = np.zeros((480, 640, 3), dtype=np.uint8)
    yy, xx = np.mgrid[0:480, 0:640]
    blob = np.exp(-((xx - 320.0) ** 2 + (yy - 240.0) ** 2) / (2 * 3.0 ** 2)) * 200
    frame = np.clip(blob, 0, 255).astype(np.uint8)
    frame = np.stack([frame] * 3, axis=-1)
    spots = detect_spots(frame)
    assert len(spots) >= 1
    assert abs(spots[0].x - 320) < 3 and abs(spots[0].y - 240) < 3
    assert detect_spots(np.zeros((480, 640, 3), dtype=np.uint8)) == []
    # Temporal confirm rejects single-frame hot pixel
    conf = TemporalConfirmer(confirm_frames=2, gate_px=12.0)
    hot = [SpotCandidate(x=10.0, y=10.0, peak=255.0, snr_db=30.0, area_px=4)]
    assert conf.update(hot) == []
    assert len(conf.update(hot)) == 1


def test_identity_gates():
    reg = _registry()
    ident = IdentityValidator(reg)
    ok = BeaconObservation("RT-002", True, 7, 1550.0, None, 1e-3, 15.0, 1.0).validate()
    assert ident.check(ok, 1.0).accepted
    assert not ident.check(BeaconObservation("RT-999", True, 1, 1550.0, None, 1e-3, 9.0, 1.0).validate(), 1.0).accepted
    assert not ident.check(BeaconObservation("RT-002", False, 8, 1550.0, None, 1e-3, 9.0, 1.0).validate(), 1.0).accepted
    bad_wl = BeaconObservation("RT-002", True, 9, 1200.0, None, 1e-3, 9.0, 2.0).validate()
    assert ident.check(bad_wl, 2.0).reason == "wavelength_out_of_spec"
    stale = BeaconObservation("RT-002", True, 7, 1550.0, None, 1e-3, 9.0, 3.0).validate()
    assert ident.check(stale, 3.0).reason == "stale_sequence"


def test_association_acquire_and_track():
    spots = [SpotCandidate(x=311.0, y=236.0, peak=200.0, snr_db=18.0, area_px=30),
             SpotCandidate(x=455.0, y=241.0, peak=250.0, snr_db=20.0, area_px=30)]
    beacon = BeaconObservation("RT-002", True, 3, 1550.0, None, 1e-3, 18.0, 1.0).validate()
    res = associate_acquisition(spots, beacon)
    assert res.observation is not None and abs(res.observation.fov_x - 311.0) < 1e-6
    # Tracking: brighter spot outside gate must not steal
    far = [SpotCandidate(x=500.0, y=400.0, peak=255.0, snr_db=25.0, area_px=30)]
    near = [SpotCandidate(x=322.0, y=241.0, peak=100.0, snr_db=12.0, area_px=25)]
    r = associate_tracking(near + far, 320.0, 240.0, "RT-002", None,
                           pred_var=4.0, r_base=4.0, mahal_threshold=9.21)
    assert r.observation is not None and r.observation.fov_x < 400
    assert associate_tracking([], 320.0, 240.0, "RT-002").observation is None


def test_kalman_stationary_velocity_and_coast_growth():
    kf = KalmanFilter2D()
    kf.initialise(320.0, 240.0)
    for _ in range(30):
        kf.predict(1.0 / 30.0)
        kf.update(320.0, 240.0, 4.0)
    assert abs(kf.velocity[0]) < 5.0 and abs(kf.velocity[1]) < 5.0
    assert r_for_snr(25.0, kf.config) < r_for_snr(6.0, kf.config)
    tr = KalmanTracker()
    tr.lock("RT-002", 320.0, 240.0, 0.0)
    u0 = tr.effective_uncertainty_px()
    uncs = []
    for i in range(10):
        track = tr.step(None, 1.0 / 30.0, 0.033 * (i + 1))
        uncs.append(track.uncertainty_px)
    assert uncs[-1] > u0
    # Spec §12.4 growth: 10 misses ≈ 21 px (2 px/frame margin + covariance).
    assert 15.0 < uncs[-1] < 30.0
    assert tr.status == "COASTING"


def test_reacq_ladder_and_wrong_tid():
    rq = V2Reacquisition([50.0, 100.0])
    rq.start("RT-002")
    pred = (320.0, 240.0)
    far_spot = [SpotCandidate(x=500.0, y=400.0, peak=200.0, snr_db=15.0, area_px=20)]
    good_beacon = BeaconObservation("RT-002", True, 4, 1550.0, None, 1e-3, 15.0, 1.0).validate()
    wrong_beacon = BeaconObservation("RT-003", True, 4, 1550.0, None, 1e-3, 15.0, 1.0).validate()
    r1 = rq.update(far_spot, wrong_beacon, *pred)
    assert not r1.reacquired  # wrong TID never confirms
    near = [SpotCandidate(x=322.0, y=241.0, peak=200.0, snr_db=15.0, area_px=20)]
    r2 = rq.update(near, good_beacon, *pred)
    assert r2.reacquired and r2.target_id == "RT-002"


def test_selector_policies():
    cands = [
        TargetObservation("RT-001", 0, 0, 1e-4, 10.0, 0.0).validate(),
        TargetObservation("RT-002", 0, 0, 2e-3, 8.0, 0.0).validate(),
    ]
    assert select_active_v2(cands, "priority", ["RT-001", "RT-002"]) == "RT-001"
    assert select_active_v2(cands, "strongest_prx") == "RT-002"
    assert select_active_v2([], "priority") is None


def test_supervisor_v2_smoke_search_runs():
    sup = SupervisorV2(_registry(), AutonomyConfig())
    frame = np.zeros((480, 640, 3), dtype=np.uint8)
    out = sup.step(frame, 1.0 / 30.0, 0.033, [], (1000.0, 1000.0))
    assert out.state == V2State.SEARCH
    assert out.camera_target_angles is not None  # scan drives gimbal
    assert "active_target_id" in out.telemetry


def test_supervisor_v2_full_loss_cycle():
    """TRACK → COAST → REACQUIRE → TRACK with TID confirm (§5, §15.4)."""
    from local_terminal.supervisor import V2State as _S
    reg = _registry()
    sup = SupervisorV2(reg, AutonomyConfig())
    sup.tracker.lock("RT-002", 320.0, 240.0, 0.0, 1e-3)
    sup.state = _S.TRACK
    blank = np.zeros((480, 640, 3), dtype=np.uint8)
    t = 0.0
    for _ in range(30):
        t += 1.0 / 30.0
        sup.step(blank, 1.0 / 30.0, t, [], (1000.0, 1000.0))
    assert sup.state == _S.REACQUIRE
    assert sup.loss_count == 1
    yy, xx = np.mgrid[0:480, 0:640]
    for i in range(60):
        t += 1.0 / 30.0
        px, py = sup.tracker.kf.position
        blob = np.exp(-((xx - px) ** 2 + (yy - py) ** 2) / (2 * 3.0 ** 2)) * 200
        fr = np.stack([np.clip(blob, 0, 255).astype(np.uint8)] * 3, -1)
        sup._pending_beacon = BeaconObservation(
            "RT-002", True, 100 + i, 1550.0, None, 1e-3, 15.0, t).validate()
        sup.step(fr, 1.0 / 30.0, t, [], (1000.0, 1000.0))
        if sup.state == _S.TRACK:
            break
    assert sup.state == _S.TRACK
    assert sup.reacq_count == 1
    assert sup.reacq_time_s is not None and sup.reacq_time_s <= 1.0


def test_v2_multi_target_no_steal():
    """Scenario B: 3 terminals, priority lock holds, no brightness steal (§16)."""
    import copy
    from remote_terminal import make_default_scenario
    from remote_terminal.config import FormationShape
    from simulation.headless import HeadlessSimulation

    sc = make_default_scenario()
    t2 = copy.deepcopy(sc.terminals[0])
    t2.terminal_id = "RT-002"
    t2.wavelength_nm = 1310.0
    t2.optical_power_w = 0.8  # stronger than RT-001: must NOT steal
    t3 = copy.deepcopy(sc.terminals[0])
    t3.terminal_id = "RT-003"
    t3.optical_power_w = 0.2
    # Place RT-001 at formation centre so it dominates boresight (LINE offsets [-spacing,0,+spacing]).
    # Otherwise dominant/nearest-to-boresight (§8.4) would lock RT-002 at centre despite priority.
    sc.terminals = [t2, sc.terminals[0], t3]
    sc.formation.terminal_count = 3
    sc.formation.formation_shape = FormationShape.LINE
    sc.validate()
    sim = HeadlessSimulation(seed=42, scenario_config=sc)
    sim.reset(seed=42)
    sim.supervisor.mission_priority = ["RT-001", "RT-002", "RT-003"]
    seen = set()
    for _ in range(400):
        sim.step()
        tid = sim.supervisor.tracker.active_tid
        if tid:
            seen.add(tid)
    assert seen == {"RT-001"}, f"lock stolen or unsettled: {seen}"

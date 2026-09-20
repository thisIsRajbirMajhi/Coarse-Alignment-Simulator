# tests/test_remote_terminal.py - Remote Terminal subsystem (RemoteTerminal.md §§71, 74-76).
import math
import random as py_random

import pytest

from remote_terminal import (
    BeamModel,
    FormationManager,
    FormationShape,
    GeometryEngine,
    ModulationType,
    MotionModel,
    MotionProfile,
    OperationalState,
    PointingModel,
    RemoteFormationConfig,
    RemoteScenarioConfig,
    RemoteTerminal,
    RemoteTerminalConfig,
    RemoteTerminalManager,
    Vector2,
    beam_diameter_m,
    beam_width_rad,
    coerce_enum,
    is_emitting,
    make_default_scenario,
)


# -- configuration (§13) ----------------------------------------------

def test_valid_configuration():
    cfg = make_default_scenario(3)
    assert cfg.formation.terminal_count == 3
    assert len(cfg.terminals) == 3


def test_invalid_terminal_count():
    with pytest.raises(ValueError):
        RemoteScenarioConfig(
            formation=RemoteFormationConfig(terminal_count=0),
            terminals=[],
        ).validate()
    with pytest.raises(ValueError):
        make_default_scenario(9)


def test_count_mismatch():
    with pytest.raises(ValueError, match="Terminal count is 5 but 4"):
        RemoteScenarioConfig(
            formation=RemoteFormationConfig(terminal_count=5,
                                            formation_shape=FormationShape.LINE),
            terminals=[RemoteTerminalConfig(terminal_id=f"RT-{i:03d}") for i in range(4)],
        ).validate()


def test_duplicate_ids():
    with pytest.raises(ValueError, match="duplicated"):
        RemoteScenarioConfig(
            formation=RemoteFormationConfig(terminal_count=2,
                                            formation_shape=FormationShape.LINE),
            terminals=[RemoteTerminalConfig(terminal_id="RT-001"),
                       RemoteTerminalConfig(terminal_id="RT-001")],
        ).validate()


def test_invalid_speed_spacing_power_spot():
    with pytest.raises(ValueError, match="Speed cannot be negative"):
        RemoteFormationConfig(speed_mps=-1.0).validate()
    with pytest.raises(ValueError, match="spacing cannot be negative"):
        RemoteFormationConfig(terminal_spacing_m=-5.0).validate()
    with pytest.raises(ValueError, match="Optical power cannot be negative"):
        RemoteTerminalConfig(optical_power_w=-0.1).validate()
    with pytest.raises(ValueError, match="greater than zero"):
        RemoteTerminalConfig(spot_size_mrad=0.0).validate()


def test_invalid_wavelength_heading_single():
    with pytest.raises(ValueError, match="supported range"):
        RemoteTerminalConfig(wavelength_nm=700.0).validate()
    with pytest.raises(ValueError, match="outside"):
        RemoteFormationConfig(heading_deg=200.0).validate()
    with pytest.raises(ValueError, match="SINGLE formation requires exactly one"):
        RemoteScenarioConfig(
            formation=RemoteFormationConfig(terminal_count=2,
                                            formation_shape=FormationShape.SINGLE),
            terminals=[RemoteTerminalConfig(terminal_id="RT-001"),
                       RemoteTerminalConfig(terminal_id="RT-002")],
        ).validate()


def test_coerce_accepts_display_labels():
    assert coerce_enum(MotionProfile, "Sinusoidal", "motion") == MotionProfile.SINUSOIDAL
    assert coerce_enum(FormationShape, "V Formation", "shape") == FormationShape.V_FORMATION
    assert coerce_enum(OperationalState, "BEACONING", "state") == OperationalState.BEACONING
    with pytest.raises(ValueError, match="Allowed"):
        coerce_enum(MotionProfile, "Warp", "motion")
    with pytest.raises(ValueError):
        RemoteScenarioConfig.from_dict({"formation": {"motion_profile": "Warp"},
                                        "terminals": []})


def test_validation_does_not_silently_correct():
    form = RemoteFormationConfig(speed_mps=-3.0)
    with pytest.raises(ValueError):
        form.validate()
    assert form.speed_mps == -3.0  # unchanged: caller must fix input


# -- formation (§§35-44) ------------------------------------------------

def _centroid(pts):
    return (sum(p.x for p in pts) / len(pts), sum(p.y for p in pts) / len(pts))


@pytest.mark.parametrize("shape", list(FormationShape))
def test_formation_count_centering(shape):
    fm = FormationManager()
    count = 1 if shape == FormationShape.SINGLE else 5
    pts = fm.compute_offsets(count, shape, 100.0)
    assert len(pts) == count
    if shape == FormationShape.ARC:
        # An arc is symmetric about the formation origin (§39), not
        # centroid-centered: y values mirror about the x-axis.
        ys = sorted(p.y for p in pts)
        assert ys == pytest.approx([-y for y in reversed(ys)], abs=1e-9)
        return
    cx, cy = _centroid(pts)
    assert cx == pytest.approx(0.0, abs=1e-6)
    assert cy == pytest.approx(0.0, abs=1e-6)


def test_line_spacing_and_circle_radius():
    fm = FormationManager()
    line = fm.compute_offsets(5, FormationShape.LINE, 100.0)
    xs = sorted(p.x for p in line)
    assert xs == pytest.approx([-200.0, -100.0, 0.0, 100.0, 200.0])
    assert all(p.y == pytest.approx(0.0) for p in line)
    circle = fm.compute_offsets(8, FormationShape.CIRCLE, 100.0)
    expected_r = 8 * 100.0 / (2.0 * math.pi)
    for p in circle:
        assert math.hypot(p.x, p.y) == pytest.approx(expected_r, rel=1e-9)


def test_formation_heading_rotation():
    fm = FormationManager()
    base = fm.oriented_offsets(3, FormationShape.LINE, 100.0, 0.0)
    rot = fm.oriented_offsets(3, FormationShape.LINE, 100.0, 90.0)
    assert sorted(round(p.x) for p in base) == [-100, 0, 100]
    assert sorted(round(p.y) for p in rot) == [-100, 0, 100]
    assert all(abs(p.x) < 1e-6 for p in rot)


def test_v_formation_leader_front():
    fm = FormationManager()
    pts = fm.compute_offsets(5, FormationShape.V_FORMATION, 100.0)
    leader = max(pts, key=lambda p: p.x)
    assert all(q.x <= leader.x + 1e-9 for q in pts)


def test_rectangle_perimeter_count():
    fm = FormationManager()
    pts = fm.compute_offsets(7, FormationShape.RECTANGLE, 100.0)
    assert len(pts) == 7


# -- motion (§§28-34) ----------------------------------------------------

def test_rest_profile_fixed():
    m = MotionModel(50.0, 30.0, MotionProfile.REST, start=Vector2(100.0, 200.0))
    for _ in range(5):
        pos, vel = m.step(1.0)
    assert (pos.x, pos.y) == (100.0, 200.0)
    assert (vel.x, vel.y) == (0.0, 0.0)


def test_constant_velocity_derived():
    m = MotionModel(50.0, 30.0, MotionProfile.CONSTANT_VELOCITY, start=Vector2(0.0, 0.0))
    pos, vel = m.step(10.0)
    assert vel.x == pytest.approx(50.0 * math.cos(math.radians(30.0)))
    assert vel.y == pytest.approx(50.0 * math.sin(math.radians(30.0)))
    assert pos.x == pytest.approx(vel.x * 10.0)
    assert pos.y == pytest.approx(vel.y * 10.0)


def test_linear_ramps_to_speed():
    m = MotionModel(10.0, 0.0, MotionProfile.LINEAR, start=Vector2(0.0, 0.0))
    _, early_vel = m.step(0.5)
    assert early_vel.length() < 10.0
    for _ in range(60):
        pos, vel = m.step(0.5)
    assert vel.length() == pytest.approx(10.0)
    assert pos.y == pytest.approx(0.0)


def test_circular_speed_and_closure():
    from remote_terminal.motion import CIRCULAR_RADIUS_M
    m = MotionModel(50.0, 0.0, MotionProfile.CIRCULAR, start=Vector2(0.0, 0.0))
    _, vel = m.step(0.1)
    assert vel.length() == pytest.approx(50.0, rel=1e-6)  # tangential speed
    # Land exactly on one full period: analytic in t, so closure is exact.
    m.reset()
    period = 2.0 * math.pi * CIRCULAR_RADIUS_M / 50.0
    n = 200
    for _ in range(n):
        pos, _ = m.step(period / n)
    assert math.hypot(pos.x, pos.y) == pytest.approx(0.0, abs=1e-6)


def test_sinusoidal_drift_plus_oscillation():
    m = MotionModel(10.0, 0.0, MotionProfile.SINUSOIDAL, start=Vector2(0.0, 0.0))
    positions = [m.step(0.1)[0] for _ in range(200)]
    assert positions[-1].x == pytest.approx(10.0 * 20.0, rel=1e-6)  # forward drift
    ys = [p.y for p in positions]
    assert max(ys) > 1.0 and min(ys) < -1.0  # cross-track oscillation


def test_figure8_bounded_and_repeating():
    from remote_terminal.motion import FIGURE8_AMPLITUDE_X_M, FIGURE8_OMEGA_RAD_S
    m = MotionModel(10.0, 0.0, MotionProfile.FIGURE_8, start=Vector2(0.0, 0.0))
    period = 2.0 * math.pi / FIGURE8_OMEGA_RAD_S
    pos, _ = m.step(period / 4.0)
    assert abs(pos.x) == pytest.approx(FIGURE8_AMPLITUDE_X_M, rel=1e-6)
    # Full periods from t=0 close exactly (trajectory is analytic in t).
    m.reset()
    n = 200
    for _ in range(n):
        pos, _ = m.step(period / n)
    assert math.hypot(pos.x, pos.y) == pytest.approx(0.0, abs=1e-6)
    assert abs(pos.x) <= FIGURE8_AMPLITUDE_X_M + 1e-6


def test_random_reproducible_bounded_continuous():
    def run():
        m = MotionModel(10.0, 0.0, MotionProfile.RANDOM, start=Vector2(0.0, 0.0),
                        rng=py_random.Random(7))
        return [m.step(0.1) for _ in range(100)]
    traj_a, traj_b = run(), run()
    for (pa, va), (pb, vb) in zip(traj_a, traj_b):
        assert (pa.x, pa.y) == (pb.x, pb.y)  # same seed → same trajectory
    for i, (pos, vel) in enumerate(traj_a):
        assert vel.length() == pytest.approx(10.0)  # bounded velocity
        if i:
            prev = traj_a[i - 1][0]
            assert math.hypot(pos.x - prev.x, pos.y - prev.y) < 2.0  # continuous


# -- emission (§74) / optics (§75) ----------------------------------------

@pytest.mark.parametrize("state", list(OperationalState))
def test_emission_state_matrix(state):
    cfg = RemoteTerminalConfig(operational_state=state)
    assert is_emitting(cfg) == (state in (OperationalState.BEACONING, OperationalState.LINKED))


def test_emission_switches():
    assert is_emitting(RemoteTerminalConfig(power_enabled=False)) is False
    assert is_emitting(RemoteTerminalConfig(beacon_enabled=False)) is False
    assert is_emitting(RemoteTerminalConfig()) is True


def test_optics_math_and_preservation():
    assert beam_width_rad(1.0) == pytest.approx(1e-3)
    assert beam_diameter_m(10000.0, 1e-3) == pytest.approx(10.0)  # spec §6 example
    beam = BeamModel()
    cfg = RemoteTerminalConfig(optical_power_w=0.5, wavelength_nm=1064.0,
                               modulation=ModulationType.PPM)
    em = beam.emission(config=cfg, beam_angle_deg=12.0, range_m=500.0, chip_level=1)
    assert em.active is True
    assert em.instantaneous_power_w == pytest.approx(0.5)
    assert em.wavelength_nm == pytest.approx(1064.0)
    assert em.modulation == ModulationType.PPM
    assert em.beam_center_angle_deg == pytest.approx(12.0)
    assert em.beam_width_rad == pytest.approx(1e-3)
    dark = beam.emission(config=cfg, beam_angle_deg=0.0, range_m=1.0, chip_level=0)
    assert dark.instantaneous_power_w == pytest.approx(0.0)


def test_geometry_and_pointing():
    src, ref = Vector2(0.0, 0.0), Vector2(300.0, 400.0)
    assert GeometryEngine.range_m(src, ref) == pytest.approx(5.0 * 100.0)
    assert GeometryEngine.los_angle_deg(src, ref) == pytest.approx(math.degrees(math.atan2(400.0, 300.0)))
    beam, err = PointingModel().compute(45.0, py_random.Random(3))
    assert abs(err) < 1.0  # small internal bias + jitter
    assert beam == pytest.approx(45.0 + err)


# -- integration (§76) -----------------------------------------------------

def test_end_to_end_consistency():
    from common.protocol.beacon import (
        BeaconFrameParser, PayloadDecoder, frame_to_chips,
    )
    cfg = make_default_scenario(2)
    cfg.formation.formation_shape = FormationShape.LINE
    cfg.formation.terminal_spacing_m = 100.0
    cfg.formation.speed_mps = 10.0
    cfg.validate()
    mgr = RemoteTerminalManager(cfg, bounds=(2000, 2000), seed=11)
    runtime = mgr.update(0.5)
    assert len(runtime.terminals) == 2
    t0 = mgr.terminals[0]
    # runtime state → beacon payload → decoded payload stay consistent
    frame = t0.generator.current.frame
    parsed = BeaconFrameParser().parse(frame_to_chips(frame))
    assert parsed.valid_crc
    decoded = PayloadDecoder.decode(parsed.payload.serialize())
    assert decoded.terminal_id == t0.config.terminal_id
    assert decoded.navigation_state is not None
    assert decoded.navigation_state.position_x_m == pytest.approx(t0.position_m.x, abs=0.5)
    assert decoded.navigation_state.position_y_m == pytest.approx(t0.position_m.y, abs=0.5)
    # optical emission consistent with config
    assert t0.emission.wavelength_nm == pytest.approx(t0.config.wavelength_nm)
    assert t0.emission.modulation == t0.config.modulation


def test_manager_determinism_telemetry_render():
    import numpy as np
    cfg = make_default_scenario(4)
    cfg.formation.formation_shape = FormationShape.CIRCLE
    # CW emits constant power (OOK blinks with the chip clock, so it is not
    # a deterministic render target); one CW terminal guarantees a marker.
    cfg.terminals[0].modulation = ModulationType.CW
    cfg.validate()
    a = RemoteTerminalManager(cfg, bounds=(2000, 2000), seed=5)
    b = RemoteTerminalManager(cfg, bounds=(2000, 2000), seed=5)
    for _ in range(20):
        ra, rb = a.update(1 / 30), b.update(1 / 30)
    for ta, tb in zip(ra.terminals, rb.terminals):
        assert (ta.position_m.x, ta.position_m.y) == (tb.position_m.x, tb.position_m.y)
    tele = a.get_telemetry()
    assert tele["terminal_count"] == 4
    assert tele["emitting_count"] >= 1
    assert len(tele["terminals"]) == 4
    frame = np.zeros((2000, 2000, 3), dtype=np.uint8)
    out = a.render_spots(frame)
    assert out.shape == frame.shape and out.max() > 0


def test_manager_apply_config():
    mgr = RemoteTerminalManager(make_default_scenario(1), bounds=(2000, 2000), seed=5)
    mgr.update(0.1)
    new_cfg = make_default_scenario(2)
    mgr.apply_config(new_cfg)
    assert len(mgr.terminals) == 2
    with pytest.raises(ValueError):
        mgr.apply_config(RemoteScenarioConfig(
            formation=RemoteFormationConfig(terminal_count=2),
            terminals=[RemoteTerminalConfig(terminal_id="RT-001")],
        ))


def test_sequence_increments_with_wrap():
    from common.protocol.beacon.navigation import NavigationState2D as Nav
    term = RemoteTerminal(RemoteTerminalConfig())
    assert term.generator.sequence == 0
    term.generator.sequence = 255
    beacon = term.generator.new_frame(Nav(0, 0.0, 0.0), 0.0)
    assert beacon.sequence == 255
    assert term.generator.sequence == 0  # wrapped


def test_telemetry_carries_switch_and_config_power():
    mgr = RemoteTerminalManager(make_default_scenario(1), bounds=(2000, 2000), seed=5)
    mgr.update(0.1)
    t = mgr.get_telemetry()["terminals"][0]
    assert t["power_on"] is True and t["beacon_on"] is True
    assert t["optical_power_w"] == 0.5
    assert t["wavelength_nm"] == 1550.0


def test_controller_remote_apply_path():
    from gui.application.commands import ApplyConfigCommand
    from gui.application.controller import ApplicationController
    from gui.application.session import SimulationSession
    from gui.application.state import LifecycleState

    session = SimulationSession(seed=21)
    session.ensure_built()
    controller = ApplicationController(session)
    cfg = make_default_scenario(3)
    cfg.formation.formation_shape = FormationShape.GRID
    cfg.validate()
    controller.apply_config(ApplyConfigCommand(section="remote_terminal", config=cfg))
    assert controller.lifecycle == LifecycleState.STOPPED  # unchanged, no error
    assert controller.last_error is None
    assert controller.session.scenario_config.formation.terminal_count == 3
    assert len(controller.session.remote.terminals) == 3
    controller.start()
    snap = controller.step()
    assert snap.terminals["terminal_count"] == 3


def test_first_frames_staggered_deterministically():
    from remote_terminal.beacon_encoder import CHIP_DURATION_S, FIRST_FRAME_STAGGER_CHIPS
    stagger = FIRST_FRAME_STAGGER_CHIPS * CHIP_DURATION_S  # 0.016 s per index
    mgr = RemoteTerminalManager(make_default_scenario(3), bounds=(2000, 2000), seed=8)
    mgr.update(0.01)
    # Terminal 0 frames immediately; terminals 1-2 wait out their delays.
    assert mgr.terminals[0].generator.current is not None
    assert mgr.terminals[1].generator.current is None
    assert mgr.terminals[2].generator.current is None
    for _ in range(20):
        mgr.update(0.005)
    starts = [t.generator.current.start_time_s for t in mgr.terminals]
    assert starts[0] < starts[1] < starts[2]  # strictly staggered
    for i, s in enumerate(starts):
        assert s >= i * stagger  # never before its delay
    assert starts[1] - starts[0] == pytest.approx(stagger, abs=0.006)
    assert starts[2] - starts[1] == pytest.approx(stagger, abs=0.006)
    # Same seed replays the identical stagger (deterministic, not wall-clock).
    mgr2 = RemoteTerminalManager(make_default_scenario(3), bounds=(2000, 2000), seed=8)
    mgr2.update(0.01)
    for _ in range(20):
        mgr2.update(0.005)
    assert [t.generator.current.start_time_s for t in mgr2.terminals] == starts

# tests/test_remote_terminal.py - Unit tests for Remote Terminal subsystem
import math
import numpy as np
import pytest

from remote_terminal.config import (
    BeaconConfig,
    FormationConfig,
    IdentityConfig,
    MotionConfig,
    PositionConfig,
    RemoteTerminalConfig,
    RemoteTerminalScenarioConfig,
    StateConfig,
    TargetSignatureConfig,
)
from remote_terminal.motion import ScenarioMotionTracker, compute_formation_offsets
from remote_terminal.optics import compute_temporal_factor, render_terminal_beacon_patch
from remote_terminal.scenario import RemoteTerminalScenario
from remote_terminal.terminal import RemoteTerminal


def test_config_defaults_and_roundtrip():
    cfg = RemoteTerminalScenarioConfig(terminal_count=3).validate()
    assert len(cfg.terminals) == 3
    assert cfg.terminals[0].identity.id == "RT-001"
    assert cfg.terminals[1].identity.id == "RT-002"
    assert cfg.terminals[2].identity.id == "RT-003"

    d = cfg.to_dict()
    reloaded = RemoteTerminalScenarioConfig.from_dict(d)
    assert reloaded.terminal_count == 3
    assert reloaded.terminals[0].beacon.wavelength_nm == 1550.0


def test_formation_offsets():
    # Circle with 4 terminals
    form = FormationConfig(shape="Circle", radius_m=100.0)
    offsets = compute_formation_offsets(4, form)
    assert len(offsets) == 4
    # All should be at radius 100
    for ox, oy, oz in offsets:
        r = math.hypot(ox, oy)
        assert pytest.approx(r, abs=1e-2) == 100.0

    # Line formation
    form_line = FormationConfig(shape="Line", spacing_m=50.0)
    line_offsets = compute_formation_offsets(3, form_line)
    assert len(line_offsets) == 3
    assert pytest.approx(line_offsets[0][0], abs=1e-2) == -50.0
    assert pytest.approx(line_offsets[1][0], abs=1e-2) == 0.0
    assert pytest.approx(line_offsets[2][0], abs=1e-2) == 50.0


def test_motion_tracker():
    mot = MotionConfig(profile="Constant Velocity", speed_mps=20.0, direction_deg=0.0, acceleration_mps2=10.0, start_x=500.0, start_y=500.0)
    tracker = ScenarioMotionTracker(mot, bounds=(2000, 2000))
    # Step 0.5s -> speed ramps from 0 to 5 m/s, avg 2.5 m/s
    tracker.update(0.5)
    assert tracker.current_speed > 0.0
    assert tracker.x > 500.0


def test_optics_patch_and_modulation():
    patch = render_terminal_beacon_patch(
        power_w=1.0,
        wavelength_nm=1550.0,
        div_h_mrad=1.0,
        div_v_mrad=1.0,
        profile_type="GAUSSIAN",
    )
    assert patch.ndim == 3
    assert patch.shape[2] == 3
    assert patch.max() > 150  # bright beacon center

    # Temporal AM modulation
    f1 = compute_temporal_factor(sim_time=0.0, mod_type="AM", mod_depth=1.0)
    assert f1 > 0.0

    # Pulse modulation
    f_pulse = compute_temporal_factor(sim_time=0.01, pulse_enabled=True, duty_cycle=0.5)
    assert f_pulse in (1.0, 0.05)


def test_terminal_state_transitions():
    term = RemoteTerminal()
    assert term.is_emitting is True

    term.set_power(False)
    assert term.is_emitting is False
    assert term.config.state.power_state == "OFF"

    term.set_power(True)
    assert term.is_emitting is True

    term.set_operational_mode("STANDBY")
    assert term.config.state.beacon_state == "READY"
    assert term.is_emitting is False  # In STANDBY, beacon is READY, not emitting

    term.set_beacon_enabled(False)
    assert term.is_emitting is False


class MockCamera:
    def __init__(self, x0=800, y0=800, x1=1200, y1=1200):
        self._rect = (x0, y0, x1, y1)
        self.pan = (x0 + x1) / 2
        self.tilt = (y0 + y1) / 2

    def get_fov_rect(self):
        return self._rect


def test_scenario_link_progression():
    cfg = RemoteTerminalScenarioConfig(terminal_count=1)
    cfg.motion.start_x = 1000.0
    cfg.motion.start_y = 1000.0
    cfg.motion.profile = "Stationary"
    scen = RemoteTerminalScenario(cfg, bounds=(2000, 2000))

    cam = MockCamera(x0=800, y0=800, x1=1200, y1=1200)

    # Initial state
    assert scen.terminals[0].config.state.communication_state == "NO_LINK"

    # Step when camera is centered on terminal
    scen.update(0.1, camera=cam)
    assert scen.terminals[0].config.state.communication_state in ("DETECTING", "OPTICAL_LOCK")

    # Step for > 1.5 seconds to achieve lock, handshake, connected
    for _ in range(25):
        scen.update(0.1, camera=cam)

    assert scen.terminals[0].config.state.communication_state == "CONNECTED"

    # Move camera far away
    far_cam = MockCamera(x0=100, y0=100, x1=300, y1=300)
    for _ in range(20):
        scen.update(0.1, camera=far_cam)

    assert scen.terminals[0].config.state.communication_state == "NO_LINK"


def test_sinusoidal_and_circular_kinematics():
    # Sinusoidal motion test
    sin_cfg = MotionConfig(
        profile="Sinusoidal",
        speed_mps=15.0,
        direction_deg=0.0,  # forward in +x direction
        acceleration_mps2=0.0,
        start_x=500.0,
        start_y=500.0,
    )
    tracker = ScenarioMotionTracker(sin_cfg, bounds=(2000, 2000))
    # Step forward in time
    y_values = []
    for _ in range(30):
        tracker.update(0.1)
        y_values.append(tracker.y)

    # Must weave laterally (std deviation of y must be non-zero)
    assert max(y_values) != min(y_values)
    assert np.std(y_values) > 1.0

    # Circular motion test
    circ_cfg = MotionConfig(
        profile="Circular",
        speed_mps=10.0,
        direction_deg=0.0,
        acceleration_mps2=0.0,
        start_x=800.0,
        start_y=600.0,
    )
    circ_tracker = ScenarioMotionTracker(circ_cfg, bounds=(2000, 2000))
    # At t=0, starts exactly at start_x, start_y
    assert pytest.approx(circ_tracker.x, abs=1e-3) == 800.0
    assert pytest.approx(circ_tracker.y, abs=1e-3) == 600.0

    # Steps in circle without unbounded phase
    for _ in range(50):
        circ_tracker.update(0.1)
    assert 0.0 <= circ_tracker._circle_phase <= 2.0 * math.pi


def test_optics_extinguished_beacon():
    # 0 power returns all zero patch
    patch_zero_pwr = render_terminal_beacon_patch(power_w=0.0, wavelength_nm=1550.0)
    assert np.count_nonzero(patch_zero_pwr) == 0

    # 0 temporal factor (e.g. pulse low phase) returns all zero patch
    patch_zero_temp = render_terminal_beacon_patch(power_w=1.0, temporal_factor=0.0)
    assert np.count_nonzero(patch_zero_temp) == 0


def test_resilient_from_dict_and_camel_case():
    raw = {
        "identity": {
            "id": "RT-099",
            "terminalType": "OPTICAL_TERMINAL",
            "platformId": "PLATFORM-99",
            "unknownExtraField": "should_be_ignored",
        },
        "state": {
            "operationalState": "STANDBY",
            "powerState": "ON",
        },
        "beacon": {
            "wavelengthNm": 1064.0,
            "modType": "OOK",
            "modFreqKhz": 25.0,
        },
    }
    cfg = RemoteTerminalConfig.from_dict(raw)
    assert cfg.identity.id == "RT-099"
    assert cfg.identity.terminal_type == "OPTICAL_TERMINAL"
    assert cfg.identity.platform_id == "PLATFORM-99"
    assert cfg.state.operational_state == "STANDBY"
    assert cfg.beacon.wavelength_nm == 1064.0
    assert cfg.beacon.mod_type == "OOK"
    assert cfg.beacon.mod_freq_khz == 25.0


def test_scenario_apply_config_preserves_terminals():
    cfg1 = RemoteTerminalScenarioConfig(terminal_count=2).validate()
    scen = RemoteTerminalScenario(cfg1, bounds=(2000, 2000))
    t0_id = id(scen.terminals[0])
    scen.terminals[0].sim_time = 12.34

    # Apply modified config with same terminal count
    cfg2 = RemoteTerminalScenarioConfig(terminal_count=2).validate()
    cfg2.terminals[0].beacon.power_w = 4.5
    scen.apply_config(cfg2)

    # Object identity & runtime state preserved
    assert id(scen.terminals[0]) == t0_id
    assert scen.terminals[0].sim_time == 12.34
    assert scen.terminals[0].config.beacon.power_w == 4.5

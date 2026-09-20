# tests/test_autonomy.py - Autonomy Supervisor unit tests (Plan.md §9).
import numpy as np
import pytest

from common.protocol.beacon.navigation import NavigationState2D
from local_terminal import (
    AutonomyState,
    AutonomySupervisor,
    CommSource,
    SignatureRegistry,
    SupervisorConfig,
)
from remote_terminal.beacon_encoder import BeaconGenerator


def _make_synth_frame(spot_x=320, spot_y=240, peak=200):
    """Create a 640×480 monochrome image with a Gaussian spot."""
    img = np.zeros((480, 640, 3), dtype=np.uint8)
    yy, xx = np.mgrid[0:480, 0:640]
    r2 = (xx - spot_x) ** 2 + (yy - spot_y) ** 2
    spot = np.clip(peak * np.exp(-r2 / (2 * 4.0 ** 2)), 0, 255).astype(np.uint8)
    img[:, :, 0] = spot
    img[:, :, 1] = spot
    img[:, :, 2] = spot
    return img


def test_supervisor_initial_state_and_search():
    sup = AutonomySupervisor()
    assert sup.state == AutonomyState.SEARCH
    # Empty frame -> stays in SEARCH, advances scan
    out = sup.step(np.zeros((480, 640, 3), dtype=np.uint8), 1 / 30, 0.0)
    assert out.state == AutonomyState.SEARCH
    assert out.camera_target_angles is not None
    assert not out.pid_active


def test_supervisor_detection_and_validation_flow():
    from remote_terminal import make_default_scenario
    reg = SignatureRegistry.from_scenario(make_default_scenario(1))
    sup = AutonomySupervisor(registry=reg)

    g = BeaconGenerator("RT-001", 1550.0)
    src = CommSource(position=(1000.0, 1000.0), emitting=True, power_w=0.5, chip_at=g.chip_at)

    frame = _make_synth_frame(320, 240, 220)
    t = 0.0

    # Step 1: Detect spot -> transitions to DETECT
    out = sup.step(frame, 1 / 30, t, comm_sources=[src])
    assert sup.state in (AutonomyState.DETECT, AutonomyState.VALIDATE)

    # Feed frames until full beacon frame received and target locked
    for i in range(40):
        t += 1 / 30
        if g.needs_new_frame(t, True):
            nav = NavigationState2D(timestamp_ms=int(t * 1000), position_x_m=0.0, position_y_m=0.0)
            g.new_frame(nav, t)
        out = sup.step(frame, 1 / 30, t, comm_sources=[src])
        if sup.state == AutonomyState.TRACK:
            break

    assert sup.state == AutonomyState.TRACK
    assert out.pid_active
    assert out.active_target_id == "RT-001"
    assert sup.acquisition_time_s is not None


def test_supervisor_reset_policy_rate_limiting():
    """Plan.md §9.3: Rate-limited to 3 per 5 min -> beyond that, hold wide-scan and FAULT."""
    sup = AutonomySupervisor(config=SupervisorConfig(max_resets_per_window=3, reset_window_s=300.0))

    # Reset 1 @ t=0s
    sup.sim_time_s = 0.0
    assert sup.full_reset() is True
    assert sup.full_reset_count == 1

    # Reset 2 @ t=10s
    sup.sim_time_s = 10.0
    assert sup.full_reset() is True
    assert sup.full_reset_count == 2

    # Reset 3 @ t=20s
    sup.sim_time_s = 20.0
    assert sup.full_reset() is True
    assert sup.full_reset_count == 3

    # Reset 4 @ t=30s -> RATE LIMIT EXCEEDED -> FAULT!
    sup.sim_time_s = 30.0
    assert sup.full_reset() is False
    assert sup.state == AutonomyState.FAULT
    assert sup.fault_active is True

    # At t=305s, the first reset has aged out (window=300s) -> allowed again
    sup.sim_time_s = 305.0
    assert sup.full_reset() is True
    assert sup.state == AutonomyState.SEARCH
    assert sup.fault_active is False

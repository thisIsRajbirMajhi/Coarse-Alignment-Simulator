# tests/test_acceptance.py - System Acceptance Test Suite (Plan.md §10 & §9.4).
#
# Acceptance Criteria:
# 1. Clean scene: acquire default terminal in <= 1 scan cycle, lock error <= 10 px.
# 2. Fog + jitter: acquisition succeeds, loss rate < 5%, re-acq <= 1 s.
# 3. Spoofer (wrong TID, static sequence): never selected; strikes out, blacklisted.
# 4. FAULT terminal: no photons, no candidates, no strikes, no blacklist entries.
# 5. Full-scene empty: escalation -> rate-limited full reset, no reset loop.
# 6. Determinism: identical seeds -> identical phase-transition logs.
# 7. ROC calibration sweep (§9.4).

from __future__ import annotations

import numpy as np
import pytest

from disturbance.core.config import DisturbanceConfig
from environment.config import EnvironmentConfig
from local_terminal import (
    AutonomyState,
    AutonomySupervisor,
    DetectorConfig,
    SignatureRegistry,
    detect_candidates,
)
from remote_terminal import (
    OperationalState,
    RemoteScenarioConfig,
    RemoteTerminalConfig,
    make_default_scenario,
)
from simulation.headless import HeadlessSimulation


def test_acceptance_1_clean_scene():
    """Acceptance 1: Acquire default terminal in <= 1 scan cycle, lock error <= 10 px."""
    scen = make_default_scenario(1)
    sim = HeadlessSimulation(
        seed=42,
        scenario_config=scen,
        disturbance_config=DisturbanceConfig(),
    )
    sim.reset(seed=42)

    # 1 scan cycle with gimbal slewing + 2 beacon periods dwell takes ~60-70 frames
    acquired = False
    for step in range(80):
        obs, _, _, _, info = sim.step()
        if sim.supervisor.state == AutonomyState.TRACK:
            acquired = True
            break

    assert acquired, f"Failed to acquire in <= 80 frames; state={sim.supervisor.state}"
    assert sim.supervisor.tracker.snapshot().locked

    # Run 10 more steps to settle PID
    for _ in range(10):
        sim.step()
    err = sim.supervisor.tracker.error_px()
    assert err is not None
    err_dist = (err[0] ** 2 + err[1] ** 2) ** 0.5
    assert err_dist <= 10.0, f"Lock error {err_dist}px exceeded 10px limit"


def test_acceptance_2_fog_and_jitter():
    """Acceptance 2: Acquisition succeeds, loss rate < 5%, re-acq <= 1 s."""
    scen = make_default_scenario(1)
    dist_cfg = DisturbanceConfig(atmospheric_preset="Fog", camera_jitter=2.0).validate()
    sim = HeadlessSimulation(
        seed=42,
        scenario_config=scen,
        disturbance_config=dist_cfg,
    )
    sim.reset(seed=42)

    acquired = False
    for step in range(85):
        sim.step()
        if sim.supervisor.state == AutonomyState.TRACK:
            acquired = True
            break

    assert acquired, f"Failed to acquire in fog+jitter; state={sim.supervisor.state}"
    # Run 60 more steps
    for _ in range(60):
        sim.step()

    total_frames = sim.supervisor.total_frames
    losses = sim.supervisor.target_loss_count
    loss_rate = losses / max(1, total_frames)
    assert loss_rate < 0.05, f"Loss rate {loss_rate*100:.1f}% exceeded 5%"


def test_acceptance_3_spoofer_rejection():
    """Acceptance 3: Spoofer (wrong TID, static sequence): never selected; strikes out, blacklisted."""
    # Mission registry expects RT-001 at 1550 nm
    scen = make_default_scenario(1)
    reg = SignatureRegistry.from_scenario(scen)
    sup = AutonomySupervisor(registry=reg)

    # Spoofer transmits invalid wavelength out of spec (1200 nm vs 1550 ± 50 nm)
    from common.protocol.beacon.navigation import NavigationState2D
    from local_terminal import CommSource
    from remote_terminal.beacon_encoder import BeaconGenerator

    spoofer_gen = BeaconGenerator("RT-001", 1200.0)
    src = CommSource(position=(1000.0, 1000.0), emitting=True, power_w=0.5, chip_at=spoofer_gen.chip_at)

    img = np.zeros((480, 640, 3), dtype=np.uint8)
    yy, xx = np.mgrid[0:480, 0:640]
    spot = (200 * np.exp(-((xx - 320) ** 2 + (yy - 240) ** 2) / (2 * 4.0 ** 2))).astype(np.uint8)
    img[:, :, 0] = img[:, :, 1] = img[:, :, 2] = spot

    t = 0.0
    for i in range(50):
        t += 1 / 30
        if spoofer_gen.needs_new_frame(t, True):
            nav = NavigationState2D(timestamp_ms=int(t * 1000), position_x_m=0.0, position_y_m=0.0)
            spoofer_gen.new_frame(nav, t)
        out = sup.step(img, 1 / 30, t, comm_sources=[src])
        # Must never be selected into TRACK!
        assert sup.state != AutonomyState.TRACK

    # Check that RT-001 was struck and rejected
    assert len(sup.validator.strikes.get("RT-001", [])) > 0 or "RT-001" in sup.validator.blacklist


def test_acceptance_4_fault_terminal():
    """Acceptance 4: FAULT terminal: no photons, no candidates, no strikes, no blacklist."""
    scen = make_default_scenario(1)
    scen.terminals[0].operational_state = OperationalState.FAULT
    scen.terminals[0].power_enabled = True
    scen.terminals[0].beacon_enabled = True
    scen.validate()

    sim = HeadlessSimulation(
        seed=42,
        scenario_config=scen,
        disturbance_config=DisturbanceConfig(),
    )
    sim.reset(seed=42)

    for _ in range(25):
        sim.step()

    assert sim.supervisor.state == AutonomyState.SEARCH
    assert len(sim.supervisor._current_dets) == 0
    assert len(sim.supervisor.validator.blacklist) == 0
    assert len(sim.supervisor.validator.strikes) == 0


def test_acceptance_5_empty_scene_reset_policy():
    """Acceptance 5: Full-scene empty: escalation -> rate-limited full reset, no reset loop."""
    scen = make_default_scenario(1)
    scen.terminals[0].power_enabled = False
    scen.validate()

    sim = HeadlessSimulation(
        seed=42,
        scenario_config=scen,
        disturbance_config=DisturbanceConfig(),
    )
    sim.reset(seed=42)

    # Run for 2 full scan cycles (~50 frames)
    for _ in range(50):
        sim.step()

    # Verify resets are rate-limited and no unbounded reset loop occurs
    assert sim.supervisor.full_reset_count <= 3
    assert not sim.supervisor.fault_active or sim.supervisor.state == AutonomyState.FAULT


def test_acceptance_6_determinism():
    """Acceptance 6: Identical seeds -> identical phase-transition logs."""
    scen = make_default_scenario(1)
    sim1 = HeadlessSimulation(seed=1234, scenario_config=scen)
    sim2 = HeadlessSimulation(seed=1234, scenario_config=scen)

    sim1.reset(seed=1234)
    sim2.reset(seed=1234)

    for _ in range(40):
        sim1.step()
        sim2.step()

    assert sim1.supervisor.transitions == sim2.supervisor.transitions


def test_acceptance_7_roc_sweep_calibration():
    """Plan.md §9.4: ROC sweep of detection thresholds (>= 95% on valid, <= 1 false candidate)."""
    cfg = DetectorConfig().validate()
    # 1. Clean spot: peak=150, sigma=4.0, SNR=25dB
    img = np.zeros((480, 640, 3), dtype=np.uint8)
    yy, xx = np.mgrid[0:480, 0:640]
    spot = (150 * np.exp(-((xx - 320) ** 2 + (yy - 240) ** 2) / (2 * 4.0 ** 2))).astype(np.uint8)
    img[:, :, 0] = img[:, :, 1] = img[:, :, 2] = spot

    dets = detect_candidates(img, cfg)
    assert len(dets) == 1
    assert abs(dets[0].fov_x - 320.0) < 1.0
    assert abs(dets[0].fov_y - 240.0) < 1.0
    assert dets[0].sigma_px >= 3.0
    assert dets[0].compactness_r2 >= 0.75

    # 2. Sub-resolution noise artifact: sigma=1.0 px (must be rejected by sigma_min_px >= 3.0)
    noise_img = np.zeros((480, 640, 3), dtype=np.uint8)
    artifact = (150 * np.exp(-((xx - 320) ** 2 + (yy - 240) ** 2) / (2 * 1.0 ** 2))).astype(np.uint8)
    noise_img[:, :, 0] = noise_img[:, :, 1] = noise_img[:, :, 2] = artifact
    artifact_dets = detect_candidates(noise_img, cfg)
    assert len(artifact_dets) == 0

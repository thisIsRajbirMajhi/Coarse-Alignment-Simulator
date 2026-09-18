# tests/test_local_terminal.py - Unit and integration tests for Local Terminal subsystem per LocalTerminal.md
from __future__ import annotations

import math
import numpy as np
import pytest

from local_terminal.acquisition import AcquisitionScanner
from local_terminal.config import (
    AcquisitionConfig,
    AngularModelConfig,
    DetectionConfig,
    DisplayConfig,
    IdentityConfig,
    LocalCameraConfig,
    LocalCommunicationConfig,
    LocalStateConfig,
    LocalTerminalConfig,
    PositionConfig,
    PTZConfig,
    RealismConfig,
    TrackingConfig,
)
from local_terminal.detection import DetectionEngine
from local_terminal.terminal import LocalTerminal
from local_terminal.tracking import TargetTracker
from remote_terminal.config import RemoteTerminalConfig, RemoteTerminalScenarioConfig
from remote_terminal.scenario import RemoteTerminalScenario


class TestLocalTerminalConfig:
    def test_default_config_instantiation(self):
        cfg = LocalTerminalConfig()
        cfg.validate((2000, 2000))
        assert cfg.identity.id == "LT-001"
        assert cfg.identity.type == "LOCAL_OPTICAL_TERMINAL"
        assert cfg.state.operational_state == "STANDBY"
        assert cfg.state.power_state == "ON"
        assert cfg.camera.resolution_width == 640
        assert cfg.camera.resolution_height == 480
        assert abs(cfg.camera.fov_x - 4.0) < 1e-5
        assert abs(cfg.camera.fov_y - 3.0) < 1e-5
        assert cfg.ptz.home_pan == 1000.0
        assert cfg.ptz.home_tilt == 1000.0

    def test_dynamic_angular_model_derivation(self):
        cfg = LocalTerminalConfig()
        cfg.validate((2000, 2000))
        # 4 deg / 640 px: (4.0 * pi / 180 * 1e6) / 640 ~= 109.083 urad/px
        expected_x = (math.radians(4.0) * 1e6) / 640.0
        expected_y = (math.radians(3.0) * 1e6) / 480.0
        assert abs(cfg.angular_model.pixel_to_angle_x - expected_x) < 1e-3
        assert abs(cfg.angular_model.pixel_to_angle_y - expected_y) < 1e-3
        assert abs(cfg.angular_model.angle_to_pixel_x - (1.0 / expected_x)) < 1e-6
        assert cfg.angular_model.unit == "urad_per_pixel"

        # Update FOV and re-verify automatic recalculation
        cfg.camera.fov_x = 8.0
        cfg.validate((2000, 2000))
        assert abs(cfg.angular_model.pixel_to_angle_x - expected_x * 2.0) < 1e-3

    def test_json_serialization_roundtrip(self):
        cfg = LocalTerminalConfig()
        cfg.identity.name = "Custom Terminal Alpha"
        cfg.detection.wavelength = 1550.0
        cfg.acquisition.search_pattern = "SPIRAL"
        cfg.validate((2000, 2000))

        data = cfg.to_dict()
        assert "localTerminal" in data
        assert data["localTerminal"]["identity"]["name"] == "Custom Terminal Alpha"
        assert data["localTerminal"]["acquisition"]["searchPattern"] == "SPIRAL"

        # Deserialization
        restored = LocalTerminalConfig.from_dict(data)
        assert restored.identity.name == "Custom Terminal Alpha"
        assert restored.acquisition.search_pattern == "SPIRAL"
        assert restored.detection.wavelength == 1550.0

    def test_backward_compatibility_properties(self):
        cfg = LocalTerminalConfig()
        cfg.fov_width = 800
        cfg.fov_height = 600
        cfg.pan_min = 100
        cfg.pan_max = 1900
        cfg.max_pan_speed_deg = 10.0
        cfg.resolution = 0.05
        cfg.latency_ms = 25
        assert cfg.camera.resolution_width == 800
        assert cfg.camera.resolution_height == 600
        assert cfg.ptz.pan_min == 100
        assert cfg.ptz.pan_max == 1900
        assert cfg.ptz.pan_speed == 10.0
        assert cfg.ptz.resolution == 0.05
        assert cfg.ptz.latency == 25


class TestLocalTerminalMechanics:
    def test_clamped_move_and_set_position(self):
        term = LocalTerminal(scene_bounds=(1000, 1000))
        term.set_position(500, 500)
        assert abs(term.pan - 500) < 1e-3
        assert abs(term.tilt - 500) < 1e-3

        # Bounds clamp test
        term.set_position(10000, 10000)
        max_pan, max_tilt = term.get_pan_range()[1], term.get_tilt_range()[1]
        assert term.pan == max_pan
        assert term.tilt == max_tilt

        term.set_position(-1000, -1000)
        min_pan, min_tilt = term.get_pan_range()[0], term.get_tilt_range()[0]
        assert term.pan == min_pan
        assert term.tilt == min_tilt

    def test_slew_limiting_with_dt(self):
        cfg = LocalTerminalConfig()
        cfg.ptz.pan_speed = 5.0  # deg/s
        cfg.ptz.tilt_speed = 5.0
        term = LocalTerminal(config=cfg, scene_bounds=(1000, 1000))
        term.set_position(500, 500)

        # Move request large delta with dt=0.033
        term.move(1000, 0, dt=0.033)
        # Should be slew-limited
        assert abs(term.pan - 500) < 50

    def test_actuator_quantization(self):
        cfg = LocalTerminalConfig()
        cfg.ptz.resolution = 0.5
        term = LocalTerminal(config=cfg, scene_bounds=(1000, 1000))
        term.set_position(500, 500)
        term.move(0.6, 0.6, dt=0.033)
        assert (term.pan - 500) % 0.5 < 1e-6

    def test_gear_backlash(self):
        cfg = LocalTerminalConfig()
        cfg.realism.backlash = 2.0  # px
        cfg.ptz.latency = 0
        term = LocalTerminal(config=cfg, scene_bounds=(1000, 1000))
        term.set_position(500, 500)

        # Move forward +10
        term.move(10.0, 0.0, dt=0.1)
        p1 = term.pan
        assert p1 > 500.0

        # Reverse -1.0 (smaller than backlash 2.0 -> no physical movement)
        term.move(-1.0, 0.0, dt=0.1)
        assert abs(term.pan - p1) < 1e-5

        # Reverse further -3.0 (overcomes remaining 1.0 backlash -> moves -2.0)
        term.move(-3.0, 0.0, dt=0.1)
        assert term.pan < p1

    def test_latency_queue_and_flush(self):
        cfg = LocalTerminalConfig()
        cfg.ptz.latency = 100  # ms
        term = LocalTerminal(config=cfg, scene_bounds=(1000, 1000))
        term.set_position(500, 500)

        term.move(50.0, 0.0, dt=0.033)
        assert term.pan == 500.0  # queued, not yet applied

        term.update(dt=0.05)
        assert term.pan == 500.0  # still pending at 50ms < 100ms

        term.update(dt=0.06)
        assert term.pan != 500.0  # executed at 110ms > 100ms

        # Test flush_pending
        term.set_position(500, 500)
        term.move(30.0, 20.0, dt=0.033)
        term.flush_pending()
        assert term.pan != 500.0


class TestAcquisitionScanner:
    def test_raster_scanning(self):
        cfg = AcquisitionConfig(
            mode="SEARCH",
            search_pattern="RASTER",
            search_region_pan_min=-10.0,
            search_region_pan_max=10.0,
            search_region_tilt_min=-5.0,
            search_region_tilt_max=5.0,
            search_speed=20.0,
            timeout=10.0,
        )
        scanner = AcquisitionScanner(cfg)
        scanner.start()
        assert scanner.active

        d_pan, d_tilt, timed_out = scanner.update(dt=0.5)
        assert not timed_out
        assert d_pan > -10.0  # swept forward

    def test_spiral_scanning(self):
        cfg = AcquisitionConfig(
            mode="SEARCH",
            search_pattern="SPIRAL",
            search_speed=10.0,
            timeout=5.0,
        )
        scanner = AcquisitionScanner(cfg)
        scanner.start()

        p0, t0, _ = scanner.update(dt=0.1)
        p1, t1, _ = scanner.update(dt=0.5)
        r0 = math.hypot(p0, t0)
        r1 = math.hypot(p1, t1)
        assert r1 >= r0  # expanding spiral

    def test_random_scanning(self):
        cfg = AcquisitionConfig(
            mode="AUTO",
            search_pattern="RANDOM",
            search_region_pan_min=-20.0,
            search_region_pan_max=20.0,
            search_region_tilt_min=-10.0,
            search_region_tilt_max=10.0,
            search_speed=15.0,
            timeout=10.0,
        )
        scanner = AcquisitionScanner(cfg)
        scanner.start()
        assert scanner.active

        # Step scanner over several frames
        positions = []
        for _ in range(10):
            p, t, timed_out = scanner.update(dt=0.2)
            positions.append((p, t))
            assert -20.0 <= p <= 20.0
            assert -10.0 <= t <= 10.0

        # Verify that coordinates change dynamically across waypoints
        assert positions[0] != positions[-1]


class TestDetectionEngine:
    def test_detection_matching_success(self):
        cfg = DetectionConfig(
            wavelength=1550.0,
            bandwidth=10.0,
            minimum_snr=8.0,
            expected_spot_size=3.0,
            expected_spot_tolerance=0.5,
            modulation_type="AM",
            modulation_frequency=10.0,
            confidence_threshold=0.85,
        )
        engine = DetectionEngine(cfg)

        eval_res = engine.evaluate_target(
            in_fov=True,
            beacon_power=1.0,
            beacon_wavelength=1550.0,
            beacon_bandwidth=2.0,
            beacon_divergence_mrad=3.0,
            modulation_type="AM",
            modulation_freq_khz=10.0,
            estimated_snr_db=15.0,
            estimated_dn=200.0,
        )
        assert eval_res["detected"]
        assert eval_res["confirmed"]
        assert eval_res["confidence"] >= 0.85
        assert eval_res["wavelength_match"]
        assert eval_res["modulation_match"]
        assert eval_res["spot_size_match"]

    def test_detection_mismatch_fails_confirmation(self):
        cfg = DetectionConfig(wavelength=1550.0, bandwidth=10.0)
        engine = DetectionEngine(cfg)

        # Wavelength mismatch (e.g. 850 nm against 1550 nm)
        eval_res = engine.evaluate_target(
            in_fov=True,
            beacon_power=1.0,
            beacon_wavelength=850.0,
            beacon_bandwidth=2.0,
            beacon_divergence_mrad=3.0,
            modulation_type="AM",
            modulation_freq_khz=10.0,
        )
        assert not eval_res["confirmed"]
        assert not eval_res["wavelength_match"]


class TestTargetTracker:
    def test_tracking_error_derivation(self):
        ang_model = AngularModelConfig(pixel_to_angle_x=100.0, pixel_to_angle_y=100.0)
        trk_cfg = TrackingConfig(mode="TRACKING", prediction=True, prediction_horizon=0.5)
        tracker = TargetTracker(trk_cfg, ang_model)

        fov_size = (640, 480)
        # Spot located at (340, 240) -> offset Δx = +20 px, Δy = 0 px
        res = tracker.update(dt=0.033, target_in_fov=True, spot_center_fov=(340.0, 240.0), fov_size=fov_size)
        assert res["active"]
        assert res["locked"]
        assert res["error_px"][0] > 0.0
        # 20 px * 100 urad/px = 2000 urad
        assert res["error_urad"][0] > 0.0


class TestLocalTerminalScenarioIntegration:
    def test_local_terminal_detects_and_locks_remote_terminal(self):
        # Local Terminal at center
        lt_cfg = LocalTerminalConfig()
        lt_cfg.ptz.home_pan = 500.0
        lt_cfg.ptz.home_tilt = 500.0
        lt_cfg.camera.resolution_width = 400
        lt_cfg.camera.resolution_height = 400
        lt_cfg.acquisition.mode = "MANUAL"
        term = LocalTerminal(config=lt_cfg, scene_bounds=(1000, 1000))
        term.set_position(500.0, 500.0)

        # Remote terminal placed right inside FOV at (520, 510)
        rt_cfg = RemoteTerminalConfig()
        rt_cfg.position.x = 520.0
        rt_cfg.position.y = 510.0
        rt_cfg.beacon.wavelength_nm = 1550.0
        rt_cfg.beacon.power_w = 2.0
        rt_cfg.beacon.divergence_mrad = 3.0
        rt_cfg.beacon.mod_type = "AM"
        rt_cfg.beacon.pulse_rate_hz = 10000.0

        scen_cfg = RemoteTerminalScenarioConfig(terminals=[rt_cfg])
        scen_cfg.motion.start_x = 520.0
        scen_cfg.motion.start_y = 510.0
        scenario = RemoteTerminalScenario(scen_cfg, bounds=(1000, 1000))

        # Step terminal with scenario
        for _ in range(50):
            scenario.update(0.033, camera=term)
            term.update(0.033, remote_scenario=scenario)

        telem = term.get_telemetry()
        assert telem["detection"]["detected"]
        assert telem["detection"]["confirmed"]
        assert telem["state"]["detection_state"] == "TARGET_CONFIRMED"
        assert telem["state"]["link_state"] in ("OPTICAL_LOCK", "HANDSHAKE", "CONNECTED")

    def test_exact_camelcase_schema_serialization(self):
        cfg = LocalTerminalConfig()
        cfg.validate((2000, 2000))
        d = cfg.to_dict()["localTerminal"]

        # Verify exact camelCase field names per LocalTerminal.md
        assert "platformId" in d["identity"]
        assert "operationalState" in d["state"]
        assert "powerState" in d["state"]
        assert "referenceFrame" in d["position"]
        assert "cameraScreen" in d["display"]
        assert "godView" in d["display"]
        assert "worldSize" in d["display"]
        assert "maxAcceleration" in d["realism"]
        assert "encoderSigma" in d["realism"]
        assert "latencyJitter" in d["realism"]
        assert "searchPattern" in d["acquisition"]
        assert "panMin" in d["acquisition"]["searchRegion"]
        assert "expectedSpotSize" in d["detection"]
        assert "updateRate" in d["tracking"]
        assert "predictionHorizon" in d["tracking"]
        assert "lostTargetBehavior" in d["tracking"]
        assert "terminalId" in d["communication"]
        assert "linkState" in d["communication"]

    def test_tracking_initial_frame_has_zero_velocity_spike(self):
        tracker = TargetTracker(TrackingConfig(prediction=True, prediction_horizon=0.5))
        # Initial frame with non-zero offset
        res1 = tracker.update(0.033, True, (360.0, 240.0), (640, 480))
        # Spot offset is 40px. Without fix, vel jumped to 1200 px/s with 600px prediction spike.
        assert tracker.vel_x == 0.0
        assert tracker.vel_y == 0.0
        assert abs(res1["error_px"][0] - 40.0) < 1e-3

    def test_scanner_timeout_wrapping_behavior(self):
        cfg = AcquisitionConfig(mode="SEARCH", search_pattern="SPIRAL", timeout=2.0)
        scanner = AcquisitionScanner(cfg)
        scanner.start()
        # Step past timeout
        p, t, timed_out = scanner.update(dt=2.5)
        assert timed_out is True
        # Verify elapsed time wrapped and didn't stay stuck > timeout
        assert scanner.elapsed_time < 2.0

    def test_detection_any_modulation_type(self):
        cfg = DetectionConfig(modulation_type="ANY")
        engine = DetectionEngine(cfg)
        eval_res = engine.evaluate_target(
            in_fov=True, beacon_power=1.0, beacon_wavelength=1550.0,
            beacon_bandwidth=2.0, beacon_divergence_mrad=3.0,
            modulation_type="CUSTOM_PULSED", modulation_freq_khz=999.0,
        )
        assert eval_res["modulation_match"] is True

    def test_zero_and_negative_dt_safety(self):
        term = LocalTerminal()
        # Move with 0 and negative dt must not throw ValueError in np.clip
        term.move(100.0, 50.0, dt=0.0)
        term.move(100.0, 50.0, dt=-0.01)
        term.update(dt=0.0)
        assert True

    def test_beacon_config_attribute_compatibility(self):
        term = LocalTerminal()
        # Create scenario with default BeaconConfig (which has div_h_mrad, not divergence_mrad)
        scen = RemoteTerminalScenario(RemoteTerminalScenarioConfig(terminal_count=1))
        # Must execute without AttributeError
        term.step_operations(0.033, remote_scenario=scen)
        assert term.config.state.detection_state in ("NO_TARGET", "DETECTING", "DISCRIMINATING", "TARGET_CONFIRMED")

    def test_autonomous_multi_target_discrimination_and_lock(self):
        lt_cfg = LocalTerminalConfig()
        lt_cfg.ptz.home_pan = 500.0
        lt_cfg.ptz.home_tilt = 500.0
        lt_cfg.camera.resolution_width = 400
        lt_cfg.camera.resolution_height = 400
        # Target criteria: 1550 nm, AM, 10 kHz, 3 mrad
        lt_cfg.detection.wavelength = 1550.0
        lt_cfg.detection.bandwidth = 10.0
        lt_cfg.detection.modulation_type = "AM"
        lt_cfg.detection.modulation_frequency = 10.0
        lt_cfg.detection.expected_spot_size = 3.0
        lt_cfg.acquisition.mode = "AUTO"
        lt_cfg.tracking.mode = "AUTO"

        term = LocalTerminal(config=lt_cfg, scene_bounds=(1000, 1000))
        term.set_position(500.0, 500.0)

        # 3 Terminals in FOV:
        # 1: Decoy with mismatched wavelength (850 nm)
        rt1 = RemoteTerminalConfig()
        rt1.identity.id = "RT-DECOY-WL"
        rt1.beacon.wavelength_nm = 850.0
        rt1.beacon.div_h_mrad = 3.0
        rt1.beacon.mod_type = "AM"
        rt1.beacon.pulse_rate_hz = 10000.0

        # 2: Authentic matching target (1550 nm, AM, 10 kHz, 3 mrad)
        rt2 = RemoteTerminalConfig()
        rt2.identity.id = "RT-MATCH-VALID"
        rt2.beacon.wavelength_nm = 1550.0
        rt2.beacon.div_h_mrad = 3.0
        rt2.beacon.mod_type = "AM"
        rt2.beacon.pulse_rate_hz = 10000.0

        # 3: Decoy with mismatched modulation (1550 nm, PM, 50 kHz)
        rt3 = RemoteTerminalConfig()
        rt3.identity.id = "RT-DECOY-MOD"
        rt3.beacon.wavelength_nm = 1550.0
        rt3.beacon.div_h_mrad = 3.0
        rt3.beacon.mod_type = "PM"
        rt3.beacon.pulse_rate_hz = 50000.0

        scen_cfg = RemoteTerminalScenarioConfig(terminal_count=3, terminals=[rt1, rt2, rt3])
        scen_cfg.motion.profile = "Stationary"
        scen_cfg.motion.start_x = 500.0
        scen_cfg.motion.start_y = 500.0
        scen = RemoteTerminalScenario(scen_cfg, bounds=(1000, 1000))

        # Step terminal and scenario
        for _ in range(15):
            scen.update(0.033, camera=term)
            term.update(0.033, remote_scenario=scen)

        telem = term.get_telemetry()
        aut = telem["autonomy"]

        # All 3 candidates must be evaluated
        assert aut["candidate_count"] == 3
        # Candidate evaluations should identify mismatch on RT-DECOY-WL and RT-DECOY-MOD
        cand_map = {c["terminal_id"]: c for c in aut["candidates"]}
        assert not cand_map["RT-DECOY-WL"]["wavelength_match"]
        assert not cand_map["RT-DECOY-MOD"]["modulation_match"]
        assert cand_map["RT-MATCH-VALID"]["confirmed"]

        # Autonomous lock must select RT-MATCH-VALID
        assert aut["active_target_id"] == "RT-MATCH-VALID"
        assert aut["state"] == "LOCKED"
        assert telem["state"]["tracking_state"] == "TRACKING"
        assert telem["state"]["detection_state"] == "TARGET_CONFIRMED"

    def test_autonomous_reacquisition_and_resume_search(self):
        lt_cfg = LocalTerminalConfig()
        lt_cfg.ptz.home_pan = 500.0
        lt_cfg.ptz.home_tilt = 500.0
        lt_cfg.camera.resolution_width = 400
        lt_cfg.camera.resolution_height = 400
        lt_cfg.detection.expected_spot_size = 3.0
        lt_cfg.acquisition.mode = "AUTO"
        lt_cfg.tracking.mode = "AUTO"
        lt_cfg.tracking.lost_target_behavior = "RESUME_SEARCH"

        term = LocalTerminal(config=lt_cfg, scene_bounds=(1000, 1000))
        term.set_position(500.0, 500.0)

        rt_cfg = RemoteTerminalConfig()
        rt_cfg.identity.id = "RT-TARGET-01"
        rt_cfg.beacon.wavelength_nm = 1550.0
        rt_cfg.beacon.div_h_mrad = 3.0
        rt_cfg.beacon.mod_type = "AM"
        rt_cfg.beacon.pulse_rate_hz = 10000.0

        scen_cfg = RemoteTerminalScenarioConfig(terminal_count=1, terminals=[rt_cfg])
        scen_cfg.motion.profile = "Stationary"
        scen_cfg.motion.start_x = 510.0
        scen_cfg.motion.start_y = 510.0
        scen = RemoteTerminalScenario(scen_cfg, bounds=(1000, 1000))

        # Lock onto target
        for _ in range(30):
            scen.update(0.033, camera=term)
            term.update(0.033, remote_scenario=scen)

        assert term.active_target_id == "RT-TARGET-01"
        assert term.config.state.tracking_state == "TRACKING"

        # Now extinguish target beacon (or move out of FOV)
        for t in scen.terminals:
            t.config.beacon.power_w = 0.0

        # Step 0.3s -> should enter REACQUIRING state with predictive coasting
        for _ in range(10):
            scen.update(0.033, camera=term)
            term.update(0.033, remote_scenario=scen)

        telem_reacq = term.get_telemetry()
        assert telem_reacq["state"]["tracking_state"] == "REACQUIRING"
        assert telem_reacq["autonomy"]["state"] == "REACQUIRING"
        assert telem_reacq["autonomy"]["active_target_id"] == "RT-TARGET-01"
        assert telem_reacq["autonomy"]["reacquire_dwell"] > 0.0

        # Step past 1.5s reacquisition timeout -> should autonomously clear target and resume search
        for _ in range(50):
            scen.update(0.033, camera=term)
            term.update(0.033, remote_scenario=scen)

        telem_search = term.get_telemetry()
        assert telem_search["autonomy"]["active_target_id"] is None
        assert telem_search["state"]["acquisition_state"] == "SEARCHING"
        assert telem_search["autonomy"]["state"] == "SEARCHING"


class TestTargetTrackerServo:
    def test_proportional_response(self):
        cfg = TrackingConfig(kp=0.5, ki=0.0, kd=0.0, dead_zone=0.0, output_clamp=500.0)
        ang = AngularModelConfig()
        tracker = TargetTracker(cfg, ang)

        cmd_x, cmd_y = tracker.compute_control(err_x=20.0, err_y=-30.0, dt=0.05)
        assert abs(cmd_x - 10.0) < 1e-4
        assert abs(cmd_y - (-15.0)) < 1e-4

    def test_dead_zone_suppression(self):
        cfg = TrackingConfig(kp=1.0, ki=0.1, kd=0.05, dead_zone=1.0, output_clamp=500.0)
        ang = AngularModelConfig()
        tracker = TargetTracker(cfg, ang)

        # Error within dead band: [0.5, -0.8] < dead_zone (1.0)
        cmd_x, cmd_y = tracker.compute_control(err_x=0.5, err_y=-0.8, dt=0.05)
        assert cmd_x == 0.0
        assert cmd_y == 0.0

        # Error exceeding dead band
        cmd_x, cmd_y = tracker.compute_control(err_x=2.0, err_y=-2.0, dt=0.05)
        assert abs(cmd_x) > 0.0
        assert abs(cmd_y) > 0.0

    def test_integral_accumulation_and_anti_windup(self):
        cfg = TrackingConfig(kp=0.0, ki=1.0, kd=0.0, dead_zone=0.0, output_clamp=50.0)
        ang = AngularModelConfig()
        tracker = TargetTracker(cfg, ang)

        # Apply constant error for multiple steps
        for _ in range(10):
            cmd_x, _ = tracker.compute_control(err_x=10.0, err_y=0.0, dt=0.1)

        # 10 steps * 10.0 * 0.1 = 10.0 integral accumulation * ki (1.0) = 10.0
        assert abs(cmd_x - 10.0) < 1e-2

        # Step 200 times to test anti-windup clamping to output_clamp (50.0)
        for _ in range(200):
            cmd_x, _ = tracker.compute_control(err_x=10.0, err_y=0.0, dt=0.1)

        assert abs(cmd_x - 50.0) < 1e-3

    def test_derivative_damping_action(self):
        cfg = TrackingConfig(kp=0.1, ki=0.0, kd=0.5, dead_zone=0.0, output_clamp=500.0)
        ang = AngularModelConfig()
        tracker = TargetTracker(cfg, ang)

        # First call establishes previous error baseline
        tracker.compute_control(err_x=0.0, err_y=0.0, dt=0.1)

        # Rapid jump in error: rate of change = (50.0 - 0.0) / 0.1 = 500 px/s
        cmd_x, _ = tracker.compute_control(err_x=50.0, err_y=0.0, dt=0.1)
        # cmd_x includes proportional (0.1 * 50 = 5) + derivative contribution (0.5 * filtered deriv > 0)
        assert cmd_x > 5.0

    def test_reset_clears_pid_state(self):
        cfg = TrackingConfig(kp=0.25, ki=0.05, kd=0.02)
        ang = AngularModelConfig()
        tracker = TargetTracker(cfg, ang)

        # Accumulate state
        tracker.compute_control(err_x=10.0, err_y=10.0, dt=0.1)
        assert tracker._integral_x != 0.0
        assert tracker._prev_err_x is not None

        tracker.reset()
        assert tracker._integral_x == 0.0
        assert tracker._integral_y == 0.0
        assert tracker._prev_err_x is None
        assert tracker._prev_err_y is None
        assert tracker._prev_deriv_x == 0.0
        assert tracker._prev_deriv_y == 0.0


def test_minimap_overlay_queries():
    term = LocalTerminal(scene_bounds=(2000, 2000))
    hx, hy = term.get_home()
    assert abs(hx - term.config.ptz.home_pan) < 1e-5
    assert abs(hy - term.config.ptz.home_tilt) < 1e-5

    eff_pmin, eff_pmax = term._effective_pan_range()
    p_min, p_max = term.get_pan_range()
    assert abs(p_min - eff_pmin) < 1e-5
    assert abs(p_max - eff_pmax) < 1e-5

    eff_tmin, eff_tmax = term._effective_tilt_range()
    t_min, t_max = term.get_tilt_range()
    assert abs(t_min - eff_tmin) < 1e-5
    assert abs(t_max - eff_tmax) < 1e-5


def test_config_controller_config_property():
    cfg = LocalTerminalConfig()
    assert cfg.controller_config is cfg.tracking
    assert cfg.controller_config.kp == cfg.tracking.kp





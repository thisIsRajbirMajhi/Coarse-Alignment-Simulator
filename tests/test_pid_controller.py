# tests/test_pid_controller.py - Comprehensive unit tests for Dual-Axis PID Controller.
import math
import numpy as np
import pytest

from camera.config import PIDConfig
from camera.constants import PID_LIMITS
from camera.pid_controller import PIDController


def test_pid_config_validation():
    """Test PIDConfig defaults, limits, and mode validation."""
    cfg = PIDConfig().validate()
    assert cfg.kp_pan == 1.5
    assert cfg.ki_pan == 0.1
    assert cfg.kd_pan == 0.25
    assert cfg.tau == 0.02
    assert cfg.deadband_px == 1.0
    assert cfg.mode == "AUTO"

    # Out of limits clamping
    bad = PIDConfig(kp_pan=50.0, tau=1.0, mode="INVALID").validate()
    assert bad.kp_pan == PID_LIMITS["kp_pan"][1]
    assert bad.tau == PID_LIMITS["tau"][1]
    assert bad.mode == "AUTO"


def test_pid_proportional_response():
    """Test proportional term generates command proportional to angular error."""
    cfg = PIDConfig(kp_pan=2.0, ki_pan=0.0, kd_pan=0.0, deadband_px=0.0, max_output_deg_s=20.0)
    ctrl = PIDController(config=cfg)

    # 10 pixels error, with 0.01 deg/px scale -> 0.1 deg error
    # cmd should be kp * error = 2.0 * 0.1 = 0.2 deg/s
    cmd_pan, cmd_tilt = ctrl.compute_from_pixels(
        error_x_px=10.0,
        error_y_px=0.0,
        deg_per_px_h=0.01,
        deg_per_px_v=0.01,
        dt=0.033,
    )
    assert abs(cmd_pan - 0.2) < 1e-4
    assert abs(cmd_tilt - 0.0) < 1e-4


def test_pid_deadband():
    """Test that errors within deadband do not trigger actuator movement."""
    cfg = PIDConfig(kp_pan=2.0, deadband_px=2.0)
    ctrl = PIDController(config=cfg)

    # 1.5 pixels error is inside 2.0 pixel deadband
    cmd_pan, cmd_tilt = ctrl.compute_from_pixels(
        error_x_px=1.0,
        error_y_px=1.0,  # hypot = 1.414 < 2.0
        deg_per_px_h=0.01,
        deg_per_px_v=0.01,
        dt=0.033,
    )
    assert cmd_pan == 0.0
    assert cmd_tilt == 0.0


def test_pid_integral_and_anti_windup():
    """Test integral accumulation over time and anti-windup clamping."""
    cfg = PIDConfig(
        kp_pan=0.0,
        ki_pan=1.0,
        kd_pan=0.0,
        deadband_px=0.0,
        max_integral_deg=5.0,
        max_output_deg_s=10.0,
    )
    ctrl = PIDController(config=cfg)

    # Sustained error of 1.0 deg (100 px * 0.01 deg/px)
    # Integral should accumulate by ki * error * dt = 1.0 * 1.0 * 0.1 = 0.1 deg per step
    for _ in range(10):
        ctrl.compute_from_pixels(100.0, 0.0, 0.01, 0.01, dt=0.1)

    st = ctrl.get_state()
    assert abs(st.i_pan - 1.0) < 1e-3

    # Run for 100 more seconds to test anti-windup clamping at 5.0 deg
    for _ in range(100):
        ctrl.compute_from_pixels(100.0, 0.0, 0.01, 0.01, dt=0.1)

    st = ctrl.get_state()
    assert abs(st.i_pan - 5.0) < 1e-3


def test_pid_filtered_derivative():
    """Test low-pass filtered derivative term."""
    # First test: no derivative kick on step 0
    cfg = PIDConfig(kp_pan=0.0, ki_pan=0.0, kd_pan=1.0, tau=0.02, deadband_px=0.0)
    ctrl = PIDController(config=cfg)

    cmd_pan, _ = ctrl.compute_from_pixels(100.0, 0.0, 0.01, 0.01, dt=0.02)
    # First step should have 0 derivative
    assert cmd_pan == 0.0

    # Second step with sudden change in error
    cmd_pan2, _ = ctrl.compute_from_pixels(200.0, 0.0, 0.01, 0.01, dt=0.02)
    # Error delta = 1.0 deg. dt = 0.02, tau = 0.02.
    # d_term = (tau / (tau + dt)) * prev_d + (kd / (tau + dt)) * delta_e
    # = (0.02 / 0.04) * 0 + (1.0 / 0.04) * 1.0 = 25.0 deg/s (clamped by max_output_deg_s)
    st = ctrl.get_state()
    assert st.d_pan > 0.0


def test_pid_mode_off():
    """Test that OFF mode zeros all commands and clears state."""
    cfg = PIDConfig(kp_pan=2.0, mode="OFF")
    ctrl = PIDController(config=cfg)

    cmd_pan, cmd_tilt = ctrl.compute_from_pixels(50.0, 50.0, 0.01, 0.01, dt=0.033)
    assert cmd_pan == 0.0
    assert cmd_tilt == 0.0


def test_pid_closed_loop_tracking():
    """Simulate a closed-loop tracking scenario where PID drives error to near-zero."""
    from camera.ptz import PTZCamera

    cam = PTZCamera(world_size=(2000, 2000))
    ctrl = PIDController(PIDConfig(kp_pan=2.0, ki_pan=0.1, kd_pan=0.2, deadband_px=0.5))

    # Target is located at world coordinates (1100, 1050)
    target_x = 1100.0
    target_y = 1050.0

    dt = 0.033
    for _ in range(150):  # 5 seconds of tracking
        cx, cy = cam.get_fov_center_world()
        err_x = target_x - cx
        err_y = target_y - cy

        cmd_pan, cmd_tilt = ctrl.compute_from_pixels(
            error_x_px=err_x,
            error_y_px=err_y,
            deg_per_px_h=cam.config.deg_per_px_h,
            deg_per_px_v=cam.config.deg_per_px_v,
            dt=dt,
        )
        cam.update(dt, cmd_pan_vel=cmd_pan, cmd_tilt_vel=cmd_tilt)

    # Final error should be within PDF specification (<= 10 pixels)
    cx_final, cy_final = cam.get_fov_center_world()
    final_err_px = math.hypot(target_x - cx_final, target_y - cy_final)
    assert final_err_px <= 10.0  # Specification: Tracking Error <= 10 pixels per PDF
    assert final_err_px < 5.0


def test_pid_derivative_kick_protection():
    """Test that extreme discontinuous error jumps are slew-limited."""
    cfg = PIDConfig(kp_pan=0.0, ki_pan=0.0, kd_pan=2.0, tau=0.02, deadband_px=0.0, max_output_deg_s=30.0)
    ctrl = PIDController(config=cfg)

    # First step: init at 0
    ctrl.compute_from_pixels(0.0, 0.0, 0.01, 0.01, dt=0.02)

    # Sudden huge jump: 1000 pixels (10 deg error jump)
    # Without slew limit of 3.0 deg, d_term would be (2.0 / 0.04) * 10 = 500 deg/s
    # With slew limit of 3.0 deg, d_term is (2.0 / 0.04) * 3.0 = 150 deg/s (clamped to max_output 30.0)
    cmd_pan, _ = ctrl.compute_from_pixels(1000.0, 0.0, 0.01, 0.01, dt=0.02)
    st = ctrl.get_state()
    # D-term should be based on slew-limited delta (<= 3.0 deg)
    # (2.0 / (0.02 + 0.02)) * 3.0 = 150.0
    assert abs(st.d_pan - 150.0) < 1e-3


def test_pid_nan_inf_protection():
    """Test that NaN and Inf inputs do not crash or corrupt the controller."""
    ctrl = PIDController()
    cmd_pan, cmd_tilt = ctrl.compute_from_pixels(float("nan"), 10.0, 0.01, 0.01, dt=0.033)
    assert cmd_pan == 0.0
    assert cmd_tilt == 0.0

    cmd_pan, cmd_tilt = ctrl.compute_from_pixels(10.0, float("inf"), 0.01, 0.01, dt=0.033)
    assert cmd_pan == 0.0
    assert cmd_tilt == 0.0


def test_pid_mode_transitions():
    """Test that switching modes cleanly resets integrators and derivative filters."""
    cfg = PIDConfig(kp_pan=1.0, ki_pan=1.0)
    ctrl = PIDController(config=cfg)

    # Accumulate integral
    for _ in range(5):
        ctrl.compute_from_pixels(100.0, 0.0, 0.01, 0.01, dt=0.1)

    assert ctrl.integral_pan > 0.0

    # Switch to MANUAL -> should reset
    ctrl.set_mode("MANUAL")
    assert ctrl.integral_pan == 0.0
    assert ctrl.prev_error_pan == 0.0

    # Switch back to AUTO -> starts fresh
    ctrl.set_mode("AUTO")
    assert ctrl.integral_pan == 0.0
    assert ctrl._first_step_pan is True


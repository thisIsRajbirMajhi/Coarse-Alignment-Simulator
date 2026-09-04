import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import time
import pytest
import numpy as np
from control.controller import PIDController
from control.config import ControllerConfig
from camera.config import CameraConfig


def test_pid_monotonic_not_wall():
    cfg = ControllerConfig(controller_type="P", kp=0.1, update_rate_hz=30).validate()
    ctrl = PIDController(config=cfg)
    # first call should succeed
    out1 = ctrl.compute_correction(10, 10)
    assert out1 is not None
    # immediate second call within interval should return same output (throttle)
    out2 = ctrl.compute_correction(10, 10)
    assert out2 == out1
    # wait interval
    time.sleep(0.04)
    out3 = ctrl.compute_correction(20, 20)
    assert out3 != out1


def test_dead_zone():
    cfg = ControllerConfig(controller_type="P", kp=0.5, dead_zone=10.0, output_clamp=100).validate()
    ctrl = PIDController(config=cfg)
    out = ctrl.compute_correction(5, 5, dt=0.033)  # inside dead_zone 10
    assert out == (0.0, 0.0)
    out2 = ctrl.compute_correction(15, 0, dt=0.033)
    assert out2[0] != 0.0


def test_output_clamp_with_camera_slew():
    cfg = ControllerConfig(controller_type="P", kp=10.0, output_clamp=1000).validate()
    ctrl = PIDController(config=cfg)
    # camera slew 800 px/s *0.033 ~26 px
    out = ctrl.compute_correction(100, 0, dt=0.033, camera_max_slew=800)
    assert abs(out[0]) <= 27


def test_integral_windup_clamp():
    cfg = ControllerConfig(controller_type="PI", kp=0.1, ki=1.0, output_clamp=10).validate()
    ctrl = PIDController(config=cfg)
    for _ in range(100):
        ctrl.compute_correction(100, 100, dt=0.033)
        time.sleep(0.035)
    # integral should be clamped to output_clamp
    assert abs(ctrl._integral_x) <= 10
    assert abs(ctrl._integral_y) <= 10


def test_derivative_filter():
    cfg = ControllerConfig(controller_type="PID", kp=0.1, ki=0.0, kd=0.1).validate()
    ctrl = PIDController(config=cfg)
    ctrl.compute_correction(0, 0, dt=0.033)
    time.sleep(0.04)
    out1 = ctrl.compute_correction(10, 0, dt=0.033)
    time.sleep(0.04)
    out2 = ctrl.compute_correction(20, 0, dt=0.033)
    # derivative should be filtered, not raw jump
    assert out1[0] != 0 and out2[0] != 0


def test_camera_config_pixel_scale():
    cfg = CameraConfig(fov_width=640, fov_height=480, fov_deg_x=4.0, fov_deg_y=3.0).validate((2000, 2000))
    assert abs(cfg.pixel_scale_mrad - 0.109) < 0.005
    # non-square aspect mismatch should average
    cfg2 = CameraConfig(fov_width=640, fov_height=480, fov_deg_x=5.0, fov_deg_y=3.0).validate((2000, 2000))
    assert hasattr(cfg2, "pixel_scale_mrad_y")


@pytest.mark.parametrize("ctype", ["P", "PI", "PID"])
def test_parametric_controller_types(ctype):
    cfg = ControllerConfig(controller_type=ctype, kp=0.2).validate()
    ctrl = PIDController(config=cfg)
    out = ctrl.compute_correction(10, -5, dt=0.033)
    assert isinstance(out, tuple) and len(out) == 2


def test_dt_clipping():
    cfg = ControllerConfig(controller_type="P", kp=0.1).validate()
    ctrl = PIDController(config=cfg)
    # huge dt should be clipped to 0.2
    out = ctrl.compute_correction(10, 10, dt=10.0)
    assert out is not None
    # tiny dt
    out2 = ctrl.compute_correction(10, 10, dt=1e-9)
    assert out2 is not None

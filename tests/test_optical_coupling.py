# tests/test_optical_coupling.py - Tests for optical pointing coupling and physical beam model.
import math
import pytest

from remote_terminal.config import RemoteTerminalConfig, ModulationType
from remote_terminal.optics import BeamModel, beam_width_rad, beam_diameter_m


def test_beam_model_zero_pointing_error():
    cfg = RemoteTerminalConfig(optical_power_w=1.0, spot_size_mrad=1.0, modulation=ModulationType.CW)
    beam = BeamModel()
    emission = beam.emission(
        config=cfg,
        beam_angle_deg=0.0,
        range_m=1000.0,
        chip_level=1,
        pointing_error_deg=0.0,
    )
    assert emission.active
    assert math.isclose(emission.instantaneous_power_w, 1.0, rel_tol=1e-5)
    assert math.isclose(emission.pointing_coupling, 1.0, rel_tol=1e-5)


def test_beam_model_pointing_attenuation():
    cfg = RemoteTerminalConfig(optical_power_w=1.0, spot_size_mrad=2.0, modulation=ModulationType.CW)
    beam = BeamModel()
    
    # 2 mrad beam width at 1000 m -> beam diameter = 2 m -> waist w = 1.0 m
    # With 0.0573 deg pointing error (1 mrad) -> delta_r = 1000 * tan(1 mrad) ≈ 1.0 m
    # delta_r / w ≈ 1.0 -> coupling = exp(-2 * 1^2) = exp(-2) ≈ 0.1353
    deg_err = math.degrees(0.001)
    emission = beam.emission(
        config=cfg,
        beam_angle_deg=0.0,
        range_m=1000.0,
        chip_level=1,
        pointing_error_deg=deg_err,
    )
    expected_coupling = math.exp(-2.0 * (1000.0 * math.tan(math.radians(deg_err)) / 1.0) ** 2)
    assert math.isclose(emission.pointing_coupling, expected_coupling, rel_tol=1e-4)
    assert math.isclose(emission.instantaneous_power_w, expected_coupling, rel_tol=1e-4)


def test_beam_model_finite_extinction():
    cfg = RemoteTerminalConfig(optical_power_w=2.0, spot_size_mrad=1.0, modulation=ModulationType.OOK)
    beam = BeamModel()
    high_em = beam.emission(
        config=cfg,
        beam_angle_deg=0.0,
        range_m=500.0,
        chip_level=1,
        pointing_error_deg=0.0,
    )
    low_em = beam.emission(
        config=cfg,
        beam_angle_deg=0.0,
        range_m=500.0,
        chip_level=0,
        pointing_error_deg=0.0,
    )
    assert math.isclose(high_em.instantaneous_power_w, 2.0, rel_tol=1e-5)
    assert math.isclose(low_em.instantaneous_power_w, 2.0 * 0.45, rel_tol=1e-5)

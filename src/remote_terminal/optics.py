# remote_terminal/optics.py - BeamModel: beam/optical emission only (Plan Hybrid-AI §1).
# Locked to OOK only — CW/PPM deleted. Emission gated by single emission_enabled.

from __future__ import annotations

from src.remote_terminal.config import OperationalState, RemoteTerminalConfig
from src.remote_terminal.models import OpticalEmission

MILLIRAD_TO_RAD: float = 1e-3


def is_emitting(config: RemoteTerminalConfig) -> bool:
    """Whether the terminal may emit (Plan Hybrid-AI: single master switch)."""
    if not bool(getattr(config, "emission_enabled", True)):
        return False
    # Backward compat: check legacy flags if emission_enabled not set
    if not bool(getattr(config, "power_enabled", True)):
        return False
    if not bool(getattr(config, "beacon_enabled", True)):
        return False
    if config.operational_state == OperationalState.FAULT:
        return False
    return True


def beam_width_rad(spot_size_mrad: float) -> float:
    return float(spot_size_mrad) * MILLIRAD_TO_RAD


def beam_diameter_m(range_m: float, width_rad: float) -> float:
    return max(0.0, float(range_m)) * max(0.0, float(width_rad))


class BeamModel:
    """Optical power/wavelength/spot/angle/range → emission (OOK only)."""

    def emission(
        self,
        *,
        config: RemoteTerminalConfig,
        beam_angle_deg: float,
        range_m: float,
        chip_level: int = 1,
        pointing_error_deg: float = 0.0,
    ) -> OpticalEmission:
        import math

        active = is_emitting(config)
        width = beam_width_rad(config.spot_size_mrad)
        power = 0.0
        coupling = 1.0

        if active:
            # OOK only: high chip = full power, low chip = 0.45 extinction
            extinction = 1.0 if int(chip_level) == 1 else 0.45
            base_power = max(0.0, float(config.optical_power_w)) * extinction

            r_m = max(0.0, float(range_m))
            diam_m = beam_diameter_m(r_m, width)
            w_radius = diam_m / 2.0
            if w_radius > 1e-6 and abs(pointing_error_deg) > 1e-6:
                delta_r = r_m * math.tan(abs(pointing_error_deg) * math.pi / 180.0)
                coupling = float(math.exp(-2.0 * ((delta_r / w_radius) ** 2)))
            else:
                coupling = 1.0
            power = base_power * coupling

        return OpticalEmission(
            active=active,
            wavelength_nm=float(config.wavelength_nm),
            instantaneous_power_w=power,
            pointing_coupling=coupling,
            modulation=config.modulation,
            beam_center_angle_deg=float(beam_angle_deg),
            beam_width_rad=width,
        )


__all__ = ["BeamModel", "is_emitting", "beam_width_rad", "beam_diameter_m", "MILLIRAD_TO_RAD"]

# remote_terminal/optics.py - BeamModel: beam/optical emission only (§§48-50).
#
# Approximate angular-Gaussian beam treatment: no detailed EM simulation.
# Emission gating follows RemoteTerminal.md §50 exactly.
from __future__ import annotations

from remote_terminal.config import ModulationType, OperationalState, RemoteTerminalConfig
from remote_terminal.models import OpticalEmission

MILLIRAD_TO_RAD: float = 1e-3


def is_emitting(config: RemoteTerminalConfig) -> bool:
    """Whether the terminal may emit (RemoteTerminal.md §50)."""
    if not config.power_enabled:
        return False
    if not config.beacon_enabled:
        return False
    if config.operational_state in {
        OperationalState.OFF,
        OperationalState.STANDBY,
        OperationalState.FAULT,
    }:
        return False
    return True


def beam_width_rad(spot_size_mrad: float) -> float:
    """Full angular beam width in radians (never FWHM/radius/half-angle)."""
    return float(spot_size_mrad) * MILLIRAD_TO_RAD


def beam_diameter_m(range_m: float, width_rad: float) -> float:
    """Approximate beam footprint at range: ``R * beam_width_rad`` (§6)."""
    return max(0.0, float(range_m)) * max(0.0, float(width_rad))


class BeamModel:
    """Optical power/wavelength/modulation/spot/angle/range → emission (§48)."""

    def emission(
        self,
        *,
        config: RemoteTerminalConfig,
        beam_angle_deg: float,
        range_m: float,
        chip_level: int = 1,
        pointing_error_deg: float = 0.0,
    ) -> OpticalEmission:
        """Build the OpticalEmission consumed by the environment layer (§49).

        ``chip_level`` is the current OOK chip (1/0). CW ignores it; OOK/PPM
        emit full power on a high chip and nothing on a low chip. The
        configured modulation label is always preserved on the emission.
        Pointing error attenuates optical power along the receiver LOS.
        """
        import math

        active = is_emitting(config)
        width = beam_width_rad(config.spot_size_mrad)
        power = 0.0
        coupling = 1.0

        if active:
            if config.modulation == ModulationType.CW:
                base_power = max(0.0, float(config.optical_power_w))
            else:
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


__all__ = [
    "BeamModel",
    "is_emitting",
    "beam_width_rad",
    "beam_diameter_m",
    "MILLIRAD_TO_RAD",
]

# remote_terminal/terminal.py - RemoteTerminal: orchestration only (§§68-70).
#
# Per-terminal update: motion state (from the formation center) → position →
# geometry → pointing → beacon → optical emission. Sub-steps delegate to the
# single-responsibility subsystems; this class only orchestrates.
from __future__ import annotations

from typing import Any

from common.protocol.beacon.navigation import NavigationState2D
from remote_terminal.beacon_encoder import CHIP_DURATION_S, FIRST_FRAME_STAGGER_CHIPS, BeaconGenerator
from remote_terminal.config import RemoteTerminalConfig
from remote_terminal.geometry import GeometryEngine
from remote_terminal.models import OpticalEmission, RemoteTerminalRuntime, Vector2
from remote_terminal.optics import BeamModel, beam_diameter_m, is_emitting
from remote_terminal.pointing import PointingModel


class RemoteTerminal:
    """One remote terminal: config → state → geometry → emission (§69)."""

    def __init__(
        self,
        config: RemoteTerminalConfig | None = None,
        terminal_index: int = 0,
    ):
        self.config = (config or RemoteTerminalConfig()).validate()
        self.generator = BeaconGenerator(
            terminal_id=self.config.terminal_id,
            wavelength_nm=self.config.wavelength_nm,
            initial_delay_s=max(0, int(terminal_index))
            * FIRST_FRAME_STAGGER_CHIPS
            * CHIP_DURATION_S,
        )
        self._geometry = GeometryEngine()
        self._pointing = PointingModel()
        self._beam = BeamModel()
        self.position_m = Vector2(0.0, 0.0)
        self.velocity_mps = Vector2(0.0, 0.0)
        self.runtime = RemoteTerminalRuntime(
            terminal_id=self.config.terminal_id,
            operational_state=self.config.operational_state,
        )
        self.emission = OpticalEmission(
            active=False,
            wavelength_nm=self.config.wavelength_nm,
            modulation=self.config.modulation,
        )
        self._last_sequence = 0
        self._has_frame = False

    # -- update ------------------------------------------------------
    def step(
        self,
        *,
        dt: float,  # noqa: ARG002 - kept for the §69 update() signature symmetry
        sim_time_s: float,
        position_m: Vector2,
        velocity_mps: Vector2,
        reference_m: Vector2,
        rng: Any,
    ) -> RemoteTerminalRuntime:
        """Execute update_motion/geometry/pointing/beacon/emission (§69).

        ``position_m``/``velocity_mps`` come from the formation center plus
        the terminal's rotated formation offset (manager-owned motion).
        ``reference_m`` is the intended receiver point for LOS geometry.
        """
        self.position_m = position_m
        self.velocity_mps = velocity_mps
        self.update_geometry(reference_m)
        self.update_pointing(rng)
        self.update_beacon(sim_time_s)
        self.update_optical_emission(sim_time_s)
        return self.runtime

    def update_geometry(self, reference_m: Vector2) -> None:
        self.runtime.range_m = self._geometry.range_m(self.position_m, reference_m)
        self.runtime.los_angle_deg = self._geometry.los_angle_deg(
            self.position_m, reference_m
        )

    def update_pointing(self, rng: Any) -> None:
        beam, error = self._pointing.compute(self.runtime.los_angle_deg, rng)
        self.runtime.beam_angle_deg = beam
        self.runtime.pointing_error_deg = error

    def update_beacon(self, sim_time_s: float) -> None:
        emitting = is_emitting(self.config)
        if self.generator.needs_new_frame(sim_time_s, emitting):
            # Sample ONCE per frame: timestamp + X/Y frozen into the payload.
            # The live terminal may move afterwards; the frame must not change.
            nav = NavigationState2D(
                timestamp_ms=int(round(float(sim_time_s) * 1000.0)),
                position_x_m=float(self.position_m.x),
                position_y_m=float(self.position_m.y),
            )
            beacon = self.generator.new_frame(nav, sim_time_s)
            self._last_sequence = beacon.sequence
            self._has_frame = True
        self.runtime.beacon_sequence = self._last_sequence

    def update_optical_emission(self, sim_time_s: float) -> None:
        chip = self.generator.chip_at(sim_time_s)
        self.emission = self._beam.emission(
            config=self.config,
            beam_angle_deg=self.runtime.beam_angle_deg,
            range_m=self.runtime.range_m,
            chip_level=chip,
        )
        self.runtime.position_m = Vector2(self.position_m.x, self.position_m.y)
        self.runtime.velocity_mps = Vector2(self.velocity_mps.x, self.velocity_mps.y)
        self.runtime.beam_width_rad = self.emission.beam_width_rad
        self.runtime.beam_diameter_m = beam_diameter_m(
            self.runtime.range_m, self.emission.beam_width_rad
        )
        self.runtime.effective_emission_enabled = self.emission.active
        self.runtime.instantaneous_power_w = self.emission.instantaneous_power_w
        self.runtime.operational_state = self.config.operational_state

    # -- telemetry ---------------------------------------------------
    def get_telemetry(self) -> dict[str, Any]:
        r = self.runtime
        nav = None
        if self.generator.current is not None:
            n = self.generator.current.navigation
            nav = {
                "timestamp_ms": n.timestamp_ms,
                "position_x_m": n.position_x_m,
                "position_y_m": n.position_y_m,
            }
        return {
            "id": r.terminal_id,
            "operational_state": r.operational_state.value,
            "emitting": bool(r.effective_emission_enabled),
            "position_m": r.position_m.as_tuple(),
            "velocity_mps": r.velocity_mps.as_tuple(),
            "range_m": r.range_m,
            "los_angle_deg": r.los_angle_deg,
            "beam_angle_deg": r.beam_angle_deg,
            "pointing_error_deg": r.pointing_error_deg,
            "beam_width_rad": r.beam_width_rad,
            "beam_diameter_m": r.beam_diameter_m,
            "instantaneous_power_w": r.instantaneous_power_w,
            "wavelength_nm": self.config.wavelength_nm,
            "modulation": self.config.modulation.value,
            "beacon_sequence": r.beacon_sequence,
            "has_beacon_frame": self._has_frame,
            "beacon_navigation": nav,
        }


__all__ = ["RemoteTerminal"]

# remote_terminal/terminal.py - Individual Remote Terminal model per RemoteTerminal.md
from __future__ import annotations

import math
from typing import Any

import numpy as np

from remote_terminal.config import RemoteTerminalConfig
from remote_terminal.optics import compute_temporal_factor, render_terminal_beacon_patch
from remote_terminal.beacon_encoder import BeaconEncoder, BeaconEncoderConfig


class RemoteTerminal:
    """
    Simulated Remote Optical Terminal.

    Encapsulates:
      - Stable identity & platform reference
      - Operational / Power / Beacon / Communication state machines
      - Kinematic position & attitude
      - Optical beacon physics & emission
      - Target signature declaration
    """

    def __init__(self, config: RemoteTerminalConfig | None = None):
        self.config = (config or RemoteTerminalConfig()).validate()
        self.x = float(self.config.position.x)
        self.y = float(self.config.position.y)
        self.z = float(self.config.position.z)
        self.roll = float(self.config.position.roll)
        self.pitch = float(self.config.position.pitch)
        self.yaw = float(self.config.position.yaw)
        self.sim_time = 0.0
        # Phase-2: beacon encoder for structured identity frames
        bc = self.config.beacon
        self._encoder = BeaconEncoder(BeaconEncoderConfig(
            terminal_id=str(self.config.identity.id),
            token=str(getattr(bc, "token", "ALPHA-7")),
            wavelength_nm=int(getattr(bc, "wavelength_nm", 1550)),
            chip_rate_hz=float(getattr(bc, "identification_chip_rate_hz", 8.0)),
        ))
        self._sync_states()

    def _sync_states(self) -> None:
        """Derive active states from configuration and operational causes."""
        st = self.config.state
        bc = self.config.beacon
        if st.power_state == "OFF":
            st.beacon_state = "OFF"
            if st.operational_state not in ("OFF", "MAINTENANCE"):
                st.operational_state = "OFF"
        elif st.operational_state == "STANDBY":
            st.beacon_state = "READY"
        elif st.operational_state == "ACTIVE":
            if bc.enabled:
                st.beacon_state = "EMITTING"
            else:
                st.beacon_state = "READY"
        elif st.operational_state in ("FAULT", "MAINTENANCE"):
            st.beacon_state = "FAULT"

    def set_power(self, on: bool) -> None:
        self.config.state.power_state = "ON" if on else "OFF"
        if not on:
            self.config.state.operational_state = "OFF"
        elif self.config.state.operational_state == "OFF":
            self.config.state.operational_state = "ACTIVE"
        self._sync_states()

    def set_operational_mode(self, mode: str) -> None:
        self.config.state.operational_state = str(mode)
        self._sync_states()

    def set_beacon_enabled(self, enabled: bool) -> None:
        self.config.beacon.enabled = bool(enabled)
        self._sync_states()

    def set_position(self, x: float, y: float, z: float = 0.0) -> None:
        self.x = float(x)
        self.y = float(y)
        self.z = float(z)
        self.config.position.x = self.x
        self.config.position.y = self.y
        self.config.position.z = self.z

    def point_at(self, target_x: float, target_y: float) -> None:
        """Compute and set azimuth & elevation pointing towards target."""
        dx = float(target_x) - self.x
        dy = float(target_y) - self.y
        az = math.degrees(math.atan2(dy, dx))
        self.config.beacon.azimuth_deg = az
        self.config.beacon.elevation_deg = 0.0

    def point_boresight(self) -> None:
        """Reset beam pointing to boresight (0, 0)."""
        self.config.beacon.azimuth_deg = 0.0
        self.config.beacon.elevation_deg = 0.0

    @property
    def is_emitting(self) -> bool:
        return (
            self.config.state.power_state == "ON"
            and self.config.state.operational_state in ("ACTIVE", "STANDBY")
            and self.config.beacon.enabled
            and self.config.state.beacon_state == "EMITTING"
        )

    def update(self, dt: float) -> None:
        self.sim_time += dt
        bc = self.config.beacon
        target_id = str(self.config.identity.id)
        chip_rate = float(getattr(bc, "identification_chip_rate_hz", 8.0))
        token = str(getattr(bc, "token", "ALPHA-7"))
        wl = int(getattr(bc, "wavelength_nm", 1550))
        if (self._encoder.config.terminal_id != target_id
            or self._encoder.config.chip_rate_hz != chip_rate
            or self._encoder.config.token != token
            or self._encoder.config.wavelength_nm != wl):
            self._encoder.config.terminal_id = target_id
            self._encoder.config.chip_rate_hz = chip_rate
            self._encoder.config.token = token
            self._encoder.config.wavelength_nm = wl
            self._encoder._rebuild()
        self._encoder.update(self.sim_time)
        self._sync_states()

    def emit_ideal_beam(self, pixel_scale_mrad: float = 0.035):
        """Ideal optical beam state before the Propagation Channel (§2/§17).

        Returns OpticalBeamState with emitted intensity (temporal modulation
        included), geometric position, beam direction and spot characteristics.
        The Propagation Channel transforms this into the received state.
        """
        from disturbance.optical.channel import OpticalBeamState

        bc = self.config.beacon
        temp_fac = compute_temporal_factor(
            sim_time=self.sim_time,
            mod_type=bc.mod_type,
            mod_freq_khz=bc.mod_freq_khz,
            mod_depth=bc.mod_depth,
            mod_phase_deg=bc.mod_phase_deg,
            pulse_enabled=bc.pulse_enabled,
            pulse_rate_khz=bc.pulse_rate_khz,
            duty_cycle=bc.duty_cycle,
        )
        if getattr(bc, "identification_code_enabled", True) and bc.mod_type != "NONE":
            temp_fac *= self._encoder.get_intensity_factor(self.sim_time)
        scale = max(1e-4, float(pixel_scale_mrad))
        spot = float((float(bc.div_h_mrad) / scale * 0.25 + float(bc.div_v_mrad) / scale * 0.25) / 2.0)
        emitted = float(max(0.0, float(bc.power_w) / 1.5) ** 0.5 * max(0.0, float(temp_fac)))
        if not self.is_emitting:
            emitted = 0.0
        return OpticalBeamState(
            emittedIntensity=float(emitted),
            position=(float(self.x), float(self.y)),
            direction=(float(bc.azimuth_deg), float(bc.elevation_deg)),
            spotSize=float(max(3.0, min(45.0, spot))),
            wavelength_nm=float(bc.wavelength_nm),
            power_w=float(bc.power_w),
        )

    def render_to_fov(
        self,
        fov_rect: tuple[int, int, int, int],
        pixel_scale_mrad: float = 0.035,
    ) -> tuple[np.ndarray | None, int, int]:
        """
        If emitting and within/near FOV, renders the optical spot.
        Returns: (patch_bgr, top_left_x, top_left_y) in FOV pixel coords.
        """
        if not self.is_emitting:
            return None, 0, 0

        x0, y0, x1, y1 = fov_rect
        # Terminal pos in FOV pixel coordinates
        px = self.x - x0
        py = self.y - y0

        # Margin check: spot can bleed into FOV edges
        margin = 35.0
        fov_w = x1 - x0
        fov_h = y1 - y0
        if px < -margin or px > fov_w + margin or py < -margin or py > fov_h + margin:
            return None, 0, 0

        bc = self.config.beacon
        temp_fac = compute_temporal_factor(
            sim_time=self.sim_time,
            mod_type=bc.mod_type,
            mod_freq_khz=bc.mod_freq_khz,
            mod_depth=bc.mod_depth,
            mod_phase_deg=bc.mod_phase_deg,
            pulse_enabled=bc.pulse_enabled,
            pulse_rate_khz=bc.pulse_rate_khz,
            duty_cycle=bc.duty_cycle,
        )
        if getattr(bc, "identification_code_enabled", True) and bc.mod_type != "NONE":
            temp_fac *= self._encoder.get_intensity_factor(self.sim_time)

        patch = render_terminal_beacon_patch(
            power_w=bc.power_w,
            wavelength_nm=bc.wavelength_nm,
            div_h_mrad=bc.div_h_mrad,
            div_v_mrad=bc.div_v_mrad,
            profile_type=bc.profile_type,
            temporal_factor=temp_fac,
            pixel_scale_mrad=pixel_scale_mrad,
        )

        ph, pw = patch.shape[:2]
        tl_x = int(round(px - pw / 2.0))
        tl_y = int(round(py - ph / 2.0))
        return patch, tl_x, tl_y

    def get_telemetry(self) -> dict[str, Any]:
        return {
            "id": self.config.identity.id,
            "name": self.config.identity.name,
            "operational_state": self.config.state.operational_state,
            "power_state": self.config.state.power_state,
            "beacon_state": self.config.state.beacon_state,
            "communication_state": self.config.state.communication_state,
            "position": (self.x, self.y, self.z),
            "is_emitting": self.is_emitting,
            "power_w": self.config.beacon.power_w,
            "wavelength_nm": self.config.beacon.wavelength_nm,
            "azimuth_deg": self.config.beacon.azimuth_deg,
            "elevation_deg": self.config.beacon.elevation_deg,
        }

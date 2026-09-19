# remote_terminal/terminal.py - 2D remote beacon (x, y + OOK identity).
from __future__ import annotations

import math
from typing import Any

import numpy as np

from remote_terminal.config import RemoteTerminalConfig
from remote_terminal.optics import compute_temporal_factor, render_terminal_beacon_patch
from remote_terminal.beacon_encoder import BeaconEncoder, BeaconEncoderConfig


class RemoteTerminal:
    """2D remote beacon: identity + on/off + OOK intensity + x/y spot.

    Full ``RemoteTerminalConfig`` accepted; physics reads the 2D subset
    (id/token/wl/power/enabled/chip_rate/net + x/y).
    """

    def __init__(self, config: RemoteTerminalConfig | None = None):
        self.config = (config or RemoteTerminalConfig()).validate()
        self.x = float(self.config.position.x)
        self.y = float(self.config.position.y)
        self.sim_time = 0.0
        # Beacon encoder for structured identity frames
        bc = self.config.beacon
        self._encoder = BeaconEncoder(BeaconEncoderConfig(
            terminal_id=str(self.config.identity.id),
            token=str(getattr(bc, "token", "ALPHA-7")),
            wavelength_nm=int(getattr(bc, "wavelength_nm", 1550)),
            protocol_version=int(getattr(bc, "protocol_version", 1)),
            message_type=int(getattr(bc, "message_type", 1)),
            payload_codec=str(getattr(bc, "payload_codec", "COMPACT")),
            chip_rate_hz=float(getattr(bc, "chip_rate_hz", 12.0)),
            network_id=int(getattr(bc, "network_id", 0) or 0),
            capabilities=int(getattr(bc, "capabilities", 0) or 0),
        ))
        self._sync_states()

    def _sync_states(self) -> None:
        """Derive active states from configuration and operational causes."""
        st = self.config.state
        bc = self.config.beacon
        if st.power_state == "OFF":
            st.beacon_state = "OFF"
            if st.operational_state not in ("OFF",):
                st.operational_state = "OFF"
        elif st.operational_state == "STANDBY":
            st.beacon_state = "READY"
        elif st.operational_state == "ACTIVE":
            if bc.enabled:
                st.beacon_state = "EMITTING"
            else:
                st.beacon_state = "READY"

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

    def set_position(self, x: float, y: float) -> None:
        """Set 2D position."""
        self.x = float(x)
        self.y = float(y)
        self.config.position.x = self.x
        self.config.position.y = self.y

    @property
    def is_emitting(self) -> bool:
        return (
            self.config.state.power_state == "ON"
            and self.config.state.operational_state in ("ACTIVE", "STANDBY")
            and self.config.beacon.enabled
            and self.config.state.beacon_state == "EMITTING"
        )

    def _combined_temporal_factor(self) -> float:
        """Single truth for intensity: framed OOK owns square-wave types.

        ``compute_temporal_factor`` is a visual alias for the kHz carrier.
        Square-wave mod types (OOK/PM/PPM) use the encoder only;
        AM keeps its envelope × encoder; NONE uses encoder.
        """
        bc = self.config.beacon
        id_on = bool(getattr(bc, "identification_code_enabled", True))
        mod = str(getattr(bc, "mod_type", "AM") or "AM").upper()
        ook = float(self._encoder.get_intensity_factor(self.sim_time)) if id_on else 1.0
        if id_on and mod in ("OOK", "PM", "PPM"):
            return float(ook)
        visual = compute_temporal_factor(
            sim_time=self.sim_time,
            mod_type=bc.mod_type,
            mod_freq_khz=bc.mod_freq_khz,
            mod_depth=bc.mod_depth,
            mod_phase_deg=bc.mod_phase_deg,
        )
        if id_on and mod != "NONE":
            return float(visual) * float(ook)
        return float(visual)

    def update(self, dt: float) -> None:
        self.sim_time += dt
        bc = self.config.beacon
        target_id = str(self.config.identity.id)
        chip_rate = float(getattr(bc, "chip_rate_hz", 12.0))
        token = str(getattr(bc, "token", "ALPHA-7"))
        wl = int(getattr(bc, "wavelength_nm", 1550))
        net = int(getattr(bc, "network_id", 0) or 0)
        caps = int(getattr(bc, "capabilities", 0) or 0)
        if (self._encoder.config.terminal_id != target_id
            or self._encoder.config.chip_rate_hz != chip_rate
            or self._encoder.config.token != token
            or self._encoder.config.wavelength_nm != wl
            or int(getattr(self._encoder.config, "network_id", 0) or 0) != net
            or int(getattr(self._encoder.config, "capabilities", 0) or 0) != caps):
            self._encoder.config.terminal_id = target_id
            self._encoder.config.chip_rate_hz = chip_rate
            self._encoder.config.token = token
            self._encoder.config.wavelength_nm = wl
            self._encoder.config.network_id = net
            self._encoder.config.capabilities = caps
            self._encoder._rebuild()
        self._encoder.update(self.sim_time)
        self._sync_states()

    def emit_ideal_beam(self, pixel_scale_mrad: float = 0.035):
        """Ideal optical beam state before the Propagation Channel.

        Returns OpticalBeamState with emitted intensity (temporal modulation
        included), geometric position, and spot characteristics.
        """
        from disturbance.optical.channel import OpticalBeamState

        bc = self.config.beacon
        temp_fac = self._combined_temporal_factor()
        scale = max(1e-4, float(pixel_scale_mrad))
        spot = float((float(bc.div_h_mrad) / scale * 0.25 + float(bc.div_v_mrad) / scale * 0.25) / 2.0)
        emitted = float(max(0.0, float(bc.power_w) / 1.5) ** 0.5 * max(0.0, float(temp_fac)))
        if not self.is_emitting:
            emitted = 0.0
        return OpticalBeamState(
            emittedIntensity=float(emitted),
            position=(float(self.x), float(self.y)),
            direction=(0.0, 0.0),
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
        temp_fac = self._combined_temporal_factor()

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
            "position": (self.x, self.y),
            "is_emitting": self.is_emitting,
            "power_w": self.config.beacon.power_w,
            "wavelength_nm": self.config.beacon.wavelength_nm,
        }

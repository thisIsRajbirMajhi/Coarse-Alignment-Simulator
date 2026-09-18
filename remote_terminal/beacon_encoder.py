"""Remote-side framing and OOK modulation; no receiver state is involved.
Per Plans/Upgrade.md §§3-6.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from common.protocol.beacon import (
    CHIP_HIGH,
    CHIP_LOW,
    MESSAGE_TYPE_BEACON,
    PROTOCOL_VERSION,
    BeaconFrame,
    BeaconPayload,
    OOKEncoder,
    frame_to_chips,
)


@dataclass
class BeaconEncoderConfig:
    terminal_id: str = "RT-001"
    token: str = "ALPHA-7"
    wavelength_nm: int = 1550
    protocol_version: int = PROTOCOL_VERSION
    message_type: int = MESSAGE_TYPE_BEACON
    payload_codec: str = "COMPACT"
    chip_rate_hz: float = 12.0
    frame_period_s: float = -1.0
    network_id: int = 0

    def __init__(
        self,
        terminal_id: str = "RT-001",
        token: str = "ALPHA-7",
        wavelength_nm: int = 1550,
        protocol_version: int = PROTOCOL_VERSION,
        message_type: int = MESSAGE_TYPE_BEACON,
        payload_codec: str = "COMPACT",
        chip_rate_hz: float = 12.0,
        frame_period_s: float = -1.0,
        network_id: int = 0,
        **kwargs: Any,
    ):
        self.terminal_id = str(terminal_id)
        self.token = str(token)
        self.wavelength_nm = int(wavelength_nm)
        self.protocol_version = int(protocol_version)
        self.message_type = int(message_type)
        self.payload_codec = str(payload_codec)
        self.chip_rate_hz = float(chip_rate_hz)
        self.frame_period_s = float(frame_period_s)
        self.network_id = int(network_id)


class BeaconFrameEncoder:
    """Builds the deterministic logical frame from the remote configuration (§5)."""

    def __init__(self, config: BeaconEncoderConfig):
        self.config = config

    def encode(self, sequence_number: int) -> BeaconFrame:
        return BeaconFrame(
            payload=BeaconPayload(
                tid=str(self.config.terminal_id),
                token=str(self.config.token),
                wl=int(self.config.wavelength_nm),
                seq=int(sequence_number),
            ),
            protocol_version=int(self.config.protocol_version),
            message_type=int(self.config.message_type),
            payload_codec=str(getattr(self.config, "payload_codec", "COMPACT")),
        )


class OOKEncoder:
    """Explicit frame -> bits -> OOK intensity abstraction (§5, §6)."""

    def chips(self, frame: BeaconFrame) -> list[int]:
        return frame_to_chips(frame)

    def intensity(self, chip: int) -> float:
        return CHIP_HIGH if chip else CHIP_LOW


class BeaconEncoder:
    """Continuously repeats a framed OOK transmission and advances ``seq`` per frame (§5, §6)."""

    def __init__(self, config: BeaconEncoderConfig | None = None):
        self.config = config or BeaconEncoderConfig()
        self._frame_encoder = BeaconFrameEncoder(self.config)
        self._ook = OOKEncoder()
        self._seq = 0
        self._last_frame_time = 0.0
        self._chips: list[int] = []
        self._period_s = 1.0
        self._rebuild()

    def _rebuild(self) -> None:
        self._frame_encoder.config = self.config
        self._chips = self._ook.chips(self.current_frame())
        rate = max(0.5, float(self.config.chip_rate_hz))
        requested = float(self.config.frame_period_s)
        self._period_s = requested if requested > 0 else len(self._chips) / rate

    def current_frame(self) -> BeaconFrame:
        return self._frame_encoder.encode(self._seq)

    def update(self, sim_time: float) -> None:
        if sim_time < self._last_frame_time:
            self._last_frame_time = sim_time
        while sim_time - self._last_frame_time >= self._period_s:
            self._seq += 1
            self._last_frame_time += self._period_s
            self._rebuild()

    def get_intensity_factor(self, sim_time: float) -> float:
        self.update(sim_time)
        index = int(
            math.floor(
                max(0.0, sim_time - self._last_frame_time)
                * max(0.5, self.config.chip_rate_hz)
            )
        )
        return (
            self._ook.intensity(self._chips[index % len(self._chips)])
            if self._chips
            else CHIP_LOW
        )

    def reconfigure(self, config: BeaconEncoderConfig) -> None:
        self.config = config
        self._frame_encoder = BeaconFrameEncoder(config)
        self._rebuild()

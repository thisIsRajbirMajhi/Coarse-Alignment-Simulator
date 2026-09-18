"""Remote-side framing and OOK modulation; no receiver state is involved."""
from __future__ import annotations

import math
from dataclasses import dataclass

from local_terminal.beacon_frame import (
    BeaconFrame, BeaconPayload, CHIP_HIGH, CHIP_LOW, MESSAGE_TYPE_BEACON,
    PROTOCOL_VERSION, frame_to_chips,
)


@dataclass
class BeaconEncoderConfig:
    terminal_id: str = "RT-001"
    token: str = "ALPHA-7"
    wavelength_nm: int = 1550
    protocol_version: int = PROTOCOL_VERSION
    message_type: int = MESSAGE_TYPE_BEACON
    chip_rate_hz: float = 8.0
    frame_period_s: float = -1.0


class BeaconFrameEncoder:
    """Builds the deterministic logical frame from the remote configuration."""
    def __init__(self, config: BeaconEncoderConfig): self.config = config

    def encode(self, sequence_number: int) -> BeaconFrame:
        return BeaconFrame(
            payload=BeaconPayload(self.config.terminal_id, self.config.token, int(self.config.wavelength_nm), int(sequence_number)),
            protocol_version=int(self.config.protocol_version), message_type=int(self.config.message_type),
        )


class OOKEncoder:
    """Explicit frame -> bits -> OOK intensity abstraction."""
    def chips(self, frame: BeaconFrame) -> list[int]: return frame_to_chips(frame)
    def intensity(self, chip: int) -> float: return CHIP_HIGH if chip else CHIP_LOW


class BeaconEncoder:
    """Continuously repeats a framed OOK transmission and advances ``seq`` per frame."""
    def __init__(self, config: BeaconEncoderConfig | None = None):
        self.config = config or BeaconEncoderConfig()
        self._frame_encoder, self._ook = BeaconFrameEncoder(self.config), OOKEncoder()
        self._seq, self._last_frame_time, self._chips, self._period_s = 0, 0.0, [], 1.0
        self._rebuild()

    def _rebuild(self) -> None:
        self._frame_encoder.config = self.config
        self._chips = self._ook.chips(self.current_frame())
        rate = max(0.5, float(self.config.chip_rate_hz))
        requested = float(self.config.frame_period_s)
        self._period_s = requested if requested > 0 else len(self._chips) / rate

    def current_frame(self) -> BeaconFrame: return self._frame_encoder.encode(self._seq)

    def update(self, sim_time: float) -> None:
        if sim_time < self._last_frame_time: self._last_frame_time = sim_time
        while sim_time - self._last_frame_time >= self._period_s:
            self._seq += 1
            self._last_frame_time += self._period_s
            self._rebuild()

    def get_intensity_factor(self, sim_time: float) -> float:
        self.update(sim_time)
        index = int(math.floor(max(0.0, sim_time - self._last_frame_time) * max(0.5, self.config.chip_rate_hz)))
        return self._ook.intensity(self._chips[index % len(self._chips)]) if self._chips else CHIP_LOW

    def reconfigure(self, config: BeaconEncoderConfig) -> None:
        self.config = config
        self._frame_encoder = BeaconFrameEncoder(config)
        self._rebuild()

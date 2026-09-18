"""Frame Decoder: Converts SignalMeasurement (chip samples) into decoded frames per Upgrade.md §§11, 12."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from local_terminal.beacon_frame import (
    BeaconDecodeResult,
    BeaconFrame,
    BeaconFrameParser,
    byte_to_terminal_id,
    decode_chips,
    terminal_id_to_byte,
)
from local_terminal.signal_analyzer import SignalMeasurement


@dataclass
class DecodedFrame:
    """Result of one decode attempt for a candidate track."""

    valid: bool = False  # CRC passed + sync found
    terminal_id: str = ""
    terminal_id_byte: int = 0
    token: str = ""
    wavelength_nm: float = 1550.0
    network_id: int = 0
    sequence_number: int = -1
    capabilities: int = 0
    crc_ok: bool = False
    reason: str = "NO_DATA"
    # Running statistics
    attempt_count: int = 0
    success_count: int = 0
    last_seq_seen: int = -1
    consecutive_valid: int = 0
    confidence: float = 0.0
    frame: BeaconFrame | None = None
    decode_result: BeaconDecodeResult | None = None

    @property
    def terminal_id_str(self) -> str:
        if self.terminal_id:
            return self.terminal_id
        return byte_to_terminal_id(self.terminal_id_byte)


class TrackDecodeState:
    """Per-track sliding bit buffer for frame synchronisation (§10, §12)."""

    WINDOW = 1600  # hold sufficient chips

    def __init__(self) -> None:
        self._bit_buf: list[int] = []
        self._attempt_count = 0
        self._success_count = 0
        self._last_seq = -1
        self._consec_valid = 0
        self._consec_invalid = 0
        self._sliding_window: list[float] = []
        self._WINDOW_N = 10
        self._parser = BeaconFrameParser()

    def reset(self) -> None:
        self._bit_buf.clear()
        self._last_seq = -1
        self._consec_valid = 0
        self._consec_invalid = 0

    def push_chips(self, chip_samples: list[float]) -> None:
        """Append new hard-decided chip samples to sliding buffer."""
        for s in chip_samples:
            self._bit_buf.append(1 if float(s) >= 0.5 else 0)
        if len(self._bit_buf) > self.WINDOW:
            self._bit_buf = self._bit_buf[-self.WINDOW :]

    def try_decode(self) -> DecodedFrame | None:
        """Attempt to find and decode a frame in the current buffer."""
        if len(self._bit_buf) < 48:
            return None

        self._attempt_count += 1
        result = self._parser.parse(self._bit_buf)

        if result.valid_crc and result.frame is not None:
            self._success_count += 1
            self._consec_valid += 1
            self._consec_invalid = 0
            self._sliding_window.append(1.0)
            self._last_seq = result.sequence_number

            confidence = self._sliding_confidence()
            df = DecodedFrame(
                valid=True,
                terminal_id=result.terminal_id,
                terminal_id_byte=result.terminal_id_byte,
                token=result.token,
                wavelength_nm=result.wavelength_nm,
                network_id=result.network_id,
                sequence_number=result.sequence_number,
                capabilities=result.capabilities,
                crc_ok=True,
                reason=result.reason,
                attempt_count=self._attempt_count,
                success_count=self._success_count,
                last_seq_seen=result.sequence_number,
                consecutive_valid=self._consec_valid,
                confidence=confidence,
                frame=result.frame,
                decode_result=result,
            )
            return df
        else:
            self._consec_valid = 0
            self._consec_invalid += 1
            self._sliding_window.append(0.0)

        del self._sliding_window[:-self._WINDOW_N]
        return None

    def _sliding_confidence(self) -> float:
        if not self._sliding_window:
            return 0.0
        w = self._sliding_window[-self._WINDOW_N :]
        return float(sum(w) / len(w))

    def statistics(self) -> dict[str, Any]:
        return {
            "attempt_count": self._attempt_count,
            "success_count": self._success_count,
            "consecutive_valid": self._consec_valid,
            "consecutive_invalid": self._consec_invalid,
            "confidence": self._sliding_confidence(),
            "last_seq": self._last_seq,
            "buf_chips": len(self._bit_buf),
        }


class FrameDecoder:
    """Stateful per-track frame decoder."""

    def __init__(self) -> None:
        self._states: dict[str, TrackDecodeState] = {}

    def reset_track(self, observation_id: str) -> None:
        self._states.pop(observation_id, None)

    def update(
        self,
        observation_id: str,
        signal: SignalMeasurement,
        last_frame: DecodedFrame | None,
    ) -> DecodedFrame:
        if observation_id not in self._states:
            self._states[observation_id] = TrackDecodeState()
        state = self._states[observation_id]

        if not signal.sufficient_data or not signal.chip_samples:
            if last_frame is not None:
                return last_frame
            return DecodedFrame(
                attempt_count=state._attempt_count,
                success_count=state._success_count,
            )

        state.push_chips(signal.chip_samples)
        result = state.try_decode()

        if result is not None:
            return result

        stats = state.statistics()
        prev = last_frame if last_frame is not None else DecodedFrame()
        prev.attempt_count = stats["attempt_count"]
        prev.success_count = stats["success_count"]
        prev.consecutive_valid = stats["consecutive_valid"]
        prev.confidence = stats["confidence"]
        return prev

    def get_statistics(self, observation_id: str) -> dict[str, Any]:
        state = self._states.get(observation_id)
        if state is None:
            return {}
        return state.statistics()

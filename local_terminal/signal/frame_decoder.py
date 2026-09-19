"""Frame Decoder: Converts SignalMeasurement (chip samples) into decoded frames.
Per Plans/New Upgrades.md §§5, 13, 16, 18.

Implements real streaming decoding, sample index tracking, and canonical sequence semantics.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from common.protocol.beacon import (
    BeaconDecodeResult,
    BeaconFrame,
    BeaconFrameParser,
    byte_to_terminal_id,
    decode_chips,
    terminal_id_to_byte,
)
from local_terminal.signal.signal_analyzer import SignalMeasurement


@dataclass
class DecodedFrame:
    """Result of one decode attempt for a candidate track (§13, §16)."""

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
    is_new_frame: bool = False  # Mandatory per §16
    # Running statistics
    attempt_count: int = 0
    success_count: int = 0
    last_seq_seen: int = -1
    consecutive_valid: int = 0
    confidence: float = 0.0
    frame: BeaconFrame | None = None
    decode_result: BeaconDecodeResult | None = None
    last_processed_sample_index: int = 0

    @property
    def terminal_id_str(self) -> str:
        if self.terminal_id:
            return self.terminal_id
        return byte_to_terminal_id(self.terminal_id_byte)


class TrackDecodeState:
    """Per-track streaming state machine for frame synchronisation (§13, §18)."""

    WINDOW = 1600  # hold sufficient chips for multiple frames
    # Max chips appended per update: bounds reset floods; steady flow is ~1.
    MAX_APPEND = 64

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
        self.last_processed_sample_index = 0
        self.last_valid_frame: BeaconFrame | None = None
        self.last_is_new_frame = False

    def reset(self) -> None:
        self._bit_buf.clear()
        self._last_seq = -1
        self._consec_valid = 0
        self._consec_invalid = 0
        self.last_processed_sample_index = 0
        self.last_valid_frame = None
        self.last_is_new_frame = False

    def push_chips(self, chip_samples: list[float], sample_index: int | None = None) -> None:
        """Append new hard-decided chip samples to sliding buffer without duplicating old samples (§13)."""
        if sample_index is not None:
            # Incremental append based on sample_index
            if sample_index < self.last_processed_sample_index:
                # History buffer was cleared/reset; restart from 0
                self.last_processed_sample_index = 0
            new_samples = chip_samples[self.last_processed_sample_index : sample_index]
            if len(new_samples) > self.MAX_APPEND:
                # Reset flood guard: a rebuilt window is not all-new data.
                new_samples = new_samples[-self.MAX_APPEND :]
            if not new_samples and chip_samples:
                # Window slid without index advance (capped history): keep the
                # stream flowing with the newest chip instead of stalling.
                new_samples = chip_samples[-1:]
            self.last_processed_sample_index = sample_index
        else:
            # Direct/standalone push (e.g. unit tests)
            new_samples = chip_samples
            self.last_processed_sample_index += len(chip_samples)

        for s in new_samples:
            self._bit_buf.append(1 if float(s) >= 0.5 else 0)

        if len(self._bit_buf) > self.WINDOW:
            self._bit_buf = self._bit_buf[-self.WINDOW :]

    def try_decode(self) -> DecodedFrame | None:
        """Attempt to find and decode a frame in the streaming bit buffer (§13, §16, §18)."""
        if len(self._bit_buf) < 48:
            return None

        self._attempt_count += 1
        result = self._parser.parse(self._bit_buf, last_seq=self._last_seq)

        if result.valid_crc and result.frame is not None:
            if getattr(result, "consumed_bits", 0) > 0:
                self._bit_buf = self._bit_buf[result.consumed_bits :]
            seq = result.sequence_number
            if self._last_seq < 0:
                is_new = True
                self._last_seq = seq
                self._consec_valid = 1
                self._success_count += 1
                self.last_valid_frame = result.frame
            elif seq == self._last_seq:
                # Duplicate sequence: valid decode but does NOT increment valid persistence (§18)
                is_new = False
            elif 1 <= (int(seq) - int(self._last_seq)) % 256 <= 127:
                # Advancing (modular: tolerates 255→0 wrap / reboot)
                is_new = True
                self._last_seq = seq
                self._consec_valid += 1
                self._success_count += 1
                self.last_valid_frame = result.frame
            else:
                # Older sequence: invalid sequence
                is_new = False

            self.last_is_new_frame = is_new
            result.is_new_frame = is_new
            self._consec_invalid = 0
            self._sliding_window.append(1.0)

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
                is_new_frame=is_new,
                attempt_count=self._attempt_count,
                success_count=self._success_count,
                last_seq_seen=result.sequence_number,
                consecutive_valid=self._consec_valid,
                confidence=confidence,
                frame=result.frame,
                decode_result=result,
                last_processed_sample_index=self.last_processed_sample_index,
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
            "last_processed_sample_index": self.last_processed_sample_index,
            "is_new_frame": self.last_is_new_frame,
        }


class FrameDecoder:
    """Stateful per-track streaming frame decoder (§13)."""

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

        # Pass total chip count to only append new chips (§13)
        state.push_chips(signal.chip_samples, sample_index=len(signal.chip_samples))
        result = state.try_decode()

        if result is not None:
            return result

        stats = state.statistics()
        prev = last_frame if last_frame is not None else DecodedFrame()
        prev.attempt_count = stats["attempt_count"]
        prev.success_count = stats["success_count"]
        prev.consecutive_valid = stats["consecutive_valid"]
        prev.confidence = stats["confidence"]
        prev.is_new_frame = False
        prev.last_processed_sample_index = stats["last_processed_sample_index"]
        return prev

    def get_statistics(self, observation_id: str) -> dict[str, Any]:
        state = self._states.get(observation_id)
        if state is None:
            return {}
        return state.statistics()

# local_terminal/frame_decoder.py - Module: Frame Decoder
#
# Converts a SignalMeasurement (chip samples) into a decoded BeaconFrame.
# Maintains per-track decode state (bit buffer, sync state, last good frame).
#
# Decode pipeline per track:
#   chip_samples (float [0,1])
#     → hard decision (threshold 0.5)
#     → sliding window preamble+sync search
#     → field extraction (56 chips = 7 bytes)
#     → CRC-8 validation
#     → DecodedFrame
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

from local_terminal.beacon_frame import (
    BeaconFrame,
    FRAME_BITS,
    PREAMBLE,
    SYNC_WORD,
    bytes_to_chips,
    chips_to_bytes,
    crc8,
    decode_chips,
)
from local_terminal.signal_analyzer import SignalMeasurement


@dataclass
class DecodedFrame:
    """Result of one decode attempt for a candidate track."""
    valid:              bool  = False   # CRC passed + sync found
    terminal_id_byte:   int   = 0
    network_id:         int   = 0
    sequence_number:    int   = -1
    capabilities:       int   = 0
    crc_ok:             bool  = False
    # Running statistics
    attempt_count:      int   = 0      # total decode attempts so far
    success_count:      int   = 0      # successful CRC-passing decodes
    last_seq_seen:      int   = -1     # most recent accepted sequence number
    consecutive_valid:  int   = 0      # streak of consecutive valid decodes
    confidence:         float = 0.0    # success_count / attempt_count (sliding)
    # Convenience: the full BeaconFrame when valid
    frame:              BeaconFrame | None = None

    @property
    def terminal_id_str(self) -> str:
        from local_terminal.beacon_frame import byte_to_terminal_id
        return byte_to_terminal_id(self.terminal_id_byte)


class TrackDecodeState:
    """Per-track sliding bit buffer for frame synchronisation."""

    WINDOW = FRAME_BITS * 3   # hold 3 frame-lengths of chips in the buffer

    def __init__(self) -> None:
        self._bit_buf: list[int] = []
        self._attempt_count = 0
        self._success_count = 0
        self._last_seq = -1
        self._consec_valid = 0
        self._consec_invalid = 0
        self._sliding_window: list[float] = []  # confidence over last N attempts
        self._WINDOW_N = 10

    def reset(self) -> None:
        self._bit_buf.clear()
        self._last_seq = -1
        self._consec_valid = 0
        self._consec_invalid = 0

    def push_chips(self, chip_samples: list[float]) -> None:
        """Append new chip samples (hard-decided) to the sliding buffer."""
        for s in chip_samples:
            self._bit_buf.append(1 if float(s) >= 0.5 else 0)
        # Keep buffer bounded
        if len(self._bit_buf) > self.WINDOW:
            self._bit_buf = self._bit_buf[-self.WINDOW:]

    def try_decode(self) -> DecodedFrame | None:
        """Attempt to find and decode a complete frame in the current buffer.

        Returns a DecodedFrame on CRC success, None otherwise.
        Advances internal statistics regardless.
        """
        if len(self._bit_buf) < FRAME_BITS:
            return None

        self._attempt_count += 1
        result = decode_chips(self._bit_buf)

        if result is not None and result.crc_ok:
            self._success_count += 1
            self._consec_valid += 1
            self._consec_invalid = 0
            self._sliding_window.append(1.0)
            seq_ok = (result.sequence_number != self._last_seq)
            self._last_seq = result.sequence_number

            confidence = self._sliding_confidence()
            df = DecodedFrame(
                valid=True,
                terminal_id_byte=result.terminal_id_byte,
                network_id=result.network_id,
                sequence_number=result.sequence_number,
                capabilities=result.capabilities,
                crc_ok=True,
                attempt_count=self._attempt_count,
                success_count=self._success_count,
                last_seq_seen=result.sequence_number,
                consecutive_valid=self._consec_valid,
                confidence=confidence,
                frame=result,
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
        w = self._sliding_window[-self._WINDOW_N:]
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
    """Stateful per-track frame decoder.

    Maintains a dict of TrackDecodeState keyed by observation_id.
    Called from system.update() after SignalAnalyzer.
    """

    def __init__(self) -> None:
        self._states: dict[str, TrackDecodeState] = {}

    def reset_track(self, observation_id: str) -> None:
        """Clear decode state for a track (call on LOST/REJECTED)."""
        self._states.pop(observation_id, None)

    def update(
        self,
        observation_id: str,
        signal: SignalMeasurement,
        last_frame: DecodedFrame | None,
    ) -> DecodedFrame:
        """Process new signal samples for a track; return latest DecodedFrame.

        If insufficient data or no sync found, returns the *previous* decoded
        frame (with valid=False if never decoded) so downstream always gets a
        stable object.
        """
        if observation_id not in self._states:
            self._states[observation_id] = TrackDecodeState()
        state = self._states[observation_id]

        if not signal.sufficient_data or not signal.chip_samples:
            # Return last known result unchanged
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

        # Decode failed this cycle; return last valid frame with updated stats
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

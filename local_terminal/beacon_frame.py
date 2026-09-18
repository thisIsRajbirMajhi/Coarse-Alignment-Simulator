"""The receiver-visible framed beacon protocol per Plans/Upgrade.md §§3-6, 12, 13.

Frames are:
  PREAMBLE (0xAA) | SYNC (0xD5) | PROTOCOL_VERSION (1) | MESSAGE_TYPE (1) | PAYLOAD_LENGTH (2B) | JSON PAYLOAD | CRC-8 (1B)

Only the resulting OOK bits traverse the optical simulation.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

PREAMBLE = 0xAA
SYNC_WORD = 0xD5
PROTOCOL_VERSION = 1
MESSAGE_TYPE_BEACON = 1
PREAMBLE_BYTES = bytes((PREAMBLE,))
SYNC_BYTES = bytes((SYNC_WORD,))
MAX_PAYLOAD_BYTES = 256

# OOK intensity levels
CHIP_HIGH = 1.0
CHIP_LOW = 0.45

# Compatibility constants
FRAME_BYTES = 0
PAYLOAD_BYTES = 0
FRAME_BITS = 0


class CRC8:
    """CRC-8/ATM (polynomial 0x07) over header plus payload."""

    @staticmethod
    def compute(data: bytes | list[int]) -> int:
        crc = 0
        for value in data:
            crc ^= int(value) & 0xFF
            for _ in range(8):
                if crc & 0x80:
                    crc = ((crc << 1) ^ 0x07) & 0xFF
                else:
                    crc = (crc << 1) & 0xFF
        return crc


def crc8(data: bytes | list[int]) -> int:
    return CRC8.compute(data)


class CRCValidator:
    """Validates CRC-8 over header + payload (§7, §12)."""

    @staticmethod
    def validate(data: bytes | list[int], expected_crc: int) -> bool:
        return CRC8.compute(data) == (int(expected_crc) & 0xFF)


@dataclass(frozen=True)
class BeaconPayload:
    """Framed beacon payload format (§4): tid, token, wl, seq."""

    tid: str = "RT-001"
    token: str = "ALPHA-7"
    wl: int = 1550
    seq: int = 0

    def serialize(self) -> bytes:
        value = {
            "seq": int(self.seq),
            "tid": str(self.tid),
            "token": str(self.token),
            "wl": int(self.wl),
        }
        return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("ascii")

    @classmethod
    def deserialize(cls, raw: bytes) -> BeaconPayload:
        value = json.loads(raw.decode("ascii"))
        required = {"tid", "token", "wl", "seq"}
        if not isinstance(value, dict) or required - set(value):
            raise ValueError("payload must include tid, token, wl and seq")
        return cls(str(value["tid"]), str(value["token"]), int(value["wl"]), int(value["seq"]))


@dataclass
class DecodedPayload:
    """Standard decoded beacon payload per Upgrade.md §13."""

    terminal_id: str = "RT-001"
    token: str = "ALPHA-7"
    wavelength_nm: float = 1550.0
    sequence_number: int = 0


class PayloadDecoder:
    """Converts binary payload into DecodedPayload (§13)."""

    @staticmethod
    def decode(raw_payload: bytes) -> DecodedPayload:
        payload = BeaconPayload.deserialize(raw_payload)
        return DecodedPayload(
            terminal_id=str(payload.tid),
            token=str(payload.token),
            wavelength_nm=float(payload.wl),
            sequence_number=int(payload.seq),
        )


class BeaconFrame:
    """Framed digital beacon message per Upgrade.md §§3-5."""

    def __init__(
        self,
        payload: BeaconPayload | None = None,
        protocol_version: int = PROTOCOL_VERSION,
        message_type: int = MESSAGE_TYPE_BEACON,
        raw_bytes: bytes = b"",
        crc_ok: bool = True,
        **kwargs: Any,
    ):
        if payload is not None:
            self.payload = payload
        else:
            # Flexible construction from keywords for backward compatibility
            tid = kwargs.get("terminal_id", "")
            if not tid and "terminal_id_byte" in kwargs:
                tid = byte_to_terminal_id(int(kwargs["terminal_id_byte"]))
            if not tid:
                tid = "RT-001"
            token = str(kwargs.get("token", "ALPHA-7"))
            wl = int(kwargs.get("wavelength_nm", kwargs.get("wl", 1550)))
            seq = int(kwargs.get("sequence_number", kwargs.get("seq", 0)))
            self.payload = BeaconPayload(tid=str(tid), token=token, wl=wl, seq=seq)

        self.protocol_version = int(protocol_version)
        self.message_type = int(message_type)
        self.raw_bytes = raw_bytes
        self.crc_ok = bool(crc_ok)
        self._network_id = int(kwargs.get("network_id", 0))
        self._capabilities = int(kwargs.get("capabilities", 0))

    @property
    def terminal_id(self) -> str:
        return self.payload.tid

    @property
    def terminal_id_str(self) -> str:
        return self.payload.tid

    @property
    def token(self) -> str:
        return self.payload.token

    @property
    def wavelength_nm(self) -> float:
        return float(self.payload.wl)

    @property
    def sequence_number(self) -> int:
        return self.payload.seq

    @property
    def terminal_id_byte(self) -> int:
        return terminal_id_to_byte(self.payload.tid)

    @property
    def network_id(self) -> int:
        return self._network_id

    @property
    def capabilities(self) -> int:
        return self._capabilities

    def to_bytes(self) -> bytes:
        body = self.payload.serialize()
        if len(body) > MAX_PAYLOAD_BYTES:
            raise ValueError(f"beacon payload exceeds {MAX_PAYLOAD_BYTES} bytes")
        header = (
            bytes((self.protocol_version & 0xFF, self.message_type & 0xFF))
            + len(body).to_bytes(2, "big")
        )
        data = header + body
        crc_val = CRC8.compute(data)
        return PREAMBLE_BYTES + SYNC_BYTES + data + bytes((crc_val,))

    def __repr__(self) -> str:
        return (
            f"BeaconFrame(tid='{self.terminal_id}', seq={self.sequence_number}, "
            f"token='{self.token}', wl={self.wavelength_nm}, v={self.protocol_version}, "
            f"crc_ok={self.crc_ok})"
        )


@dataclass
class BeaconDecodeResult:
    """Structured result of frame decoding (§12)."""

    frame_detected: bool = False
    synchronized: bool = False
    valid_crc: bool = False
    protocol_version: int | None = None
    message_type: int | None = None
    payload_length: int = 0
    payload: BeaconPayload | None = None
    decode_confidence: float = 0.0
    reason: str = "NO_FRAME"
    frame: BeaconFrame | None = None

    @property
    def terminal_id(self) -> str:
        return self.payload.tid if self.payload else ""

    @property
    def terminal_id_str(self) -> str:
        return self.payload.tid if self.payload else ""

    @property
    def token(self) -> str:
        return self.payload.token if self.payload else ""

    @property
    def wavelength_nm(self) -> float:
        return float(self.payload.wl) if self.payload else 0.0

    @property
    def sequence_number(self) -> int:
        return self.payload.seq if self.payload else -1

    @property
    def terminal_id_byte(self) -> int:
        return terminal_id_to_byte(self.terminal_id) if self.terminal_id else 0

    @property
    def network_id(self) -> int:
        return self.frame.network_id if self.frame else 0

    @property
    def capabilities(self) -> int:
        return self.frame.capabilities if self.frame else 0

    @property
    def crc_ok(self) -> bool:
        return self.valid_crc


class BeaconFrameParser:
    """Parses recovered chips/bytes and preserves structured failure reasons (§12)."""

    # 16-bit sync pattern: PREAMBLE (0xAA) then SYNC (0xD5)
    # Binary: 10101010 11010101
    MARKER_BITS = [1, 0, 1, 0, 1, 0, 1, 0, 1, 1, 0, 1, 0, 1, 0, 1]

    def parse(self, chips_or_bytes: list[int] | bytes, confidence: float = 0.0) -> BeaconDecodeResult:
        if isinstance(chips_or_bytes, bytes):
            chips = bytes_to_chips(chips_or_bytes)
        else:
            chips = [1 if c else 0 for c in chips_or_bytes]

        if len(chips) < len(self.MARKER_BITS) + 40:  # Need marker + header (4B = 32b) + CRC (8b)
            return BeaconDecodeResult(decode_confidence=confidence, reason="INSUFFICIENT_DATA")

        # Find marker bits in chips stream (sliding bit search)
        m_len = len(self.MARKER_BITS)
        start_idx = -1
        for i in range(len(chips) - m_len - 39):
            if chips[i : i + m_len] == self.MARKER_BITS:
                start_idx = i
                break

        if start_idx < 0:
            return BeaconDecodeResult(decode_confidence=confidence, reason="INVALID_PREAMBLE_OR_SYNC")

        # Extract bits following marker
        rest_chips = chips[start_idx + m_len :]
        # Check if we have at least 4 bytes for header (v, type, len_hi, len_lo) + 1 byte CRC = 40 bits
        if len(rest_chips) < 40:
            return BeaconDecodeResult(
                frame_detected=True,
                synchronized=True,
                decode_confidence=confidence,
                reason="TRUNCATED_FRAME",
            )

        data = chips_to_bytes(rest_chips)
        if len(data) < 5:
            return BeaconDecodeResult(
                frame_detected=True,
                synchronized=True,
                decode_confidence=confidence,
                reason="TRUNCATED_FRAME",
            )

        version = data[0]
        message_type = data[1]
        length = int.from_bytes(data[2:4], "big")

        common = dict(
            frame_detected=True,
            synchronized=True,
            protocol_version=version,
            message_type=message_type,
            payload_length=length,
            decode_confidence=confidence,
        )

        if version != PROTOCOL_VERSION:
            return BeaconDecodeResult(**common, reason="UNSUPPORTED_PROTOCOL_VERSION")
        if message_type != MESSAGE_TYPE_BEACON:
            return BeaconDecodeResult(**common, reason="UNSUPPORTED_MESSAGE_TYPE")
        if length > MAX_PAYLOAD_BYTES or length < 2:
            return BeaconDecodeResult(**common, reason="INVALID_LENGTH")

        end = 4 + length
        if len(data) < end + 1:
            return BeaconDecodeResult(**common, reason="TRUNCATED_FRAME")

        header_and_payload = data[:end]
        raw_payload = data[4:end]
        received_crc = data[end]

        if not CRCValidator.validate(header_and_payload, received_crc):
            return BeaconDecodeResult(**common, reason="CRC_MISMATCH")

        try:
            payload = BeaconPayload.deserialize(raw_payload)
        except (UnicodeDecodeError, ValueError, TypeError, json.JSONDecodeError):
            return BeaconDecodeResult(**common, valid_crc=True, reason="INVALID_PAYLOAD")

        frame_bytes = bytes((PREAMBLE, SYNC_WORD)) + data[: end + 1]
        frame = BeaconFrame(
            payload=payload,
            protocol_version=version,
            message_type=message_type,
            raw_bytes=frame_bytes,
            crc_ok=True,
        )
        return BeaconDecodeResult(
            **common,
            valid_crc=True,
            payload=payload,
            frame=frame,
            reason="OK",
        )


def bytes_to_chips(data: bytes) -> list[int]:
    return [(byte >> bit) & 1 for byte in data for bit in range(7, -1, -1)]


def chips_to_bytes(chips: list[int]) -> bytes:
    return bytes(
        sum((int(chips[i + bit]) & 1) << (7 - bit) for bit in range(8))
        for i in range(0, len(chips) - 7, 8)
    )


def frame_to_bytes(frame: BeaconFrame) -> bytes:
    return frame.to_bytes()


def frame_to_chips(frame: BeaconFrame) -> list[int]:
    return bytes_to_chips(frame.to_bytes())


def chips_to_intensity(chip: int) -> float:
    return CHIP_HIGH if chip else CHIP_LOW


def decode_chips(chips: list[int]) -> BeaconFrame | None:
    result = BeaconFrameParser().parse(chips)
    return result.frame if result.valid_crc else None


def terminal_id_to_byte(tid: str) -> int:
    suffix = ""
    for char in reversed(str(tid)):
        if char.isdigit():
            suffix = char + suffix
        elif suffix:
            break
    return int(suffix) & 0xFF if suffix else sum(map(ord, str(tid))) & 0xFF


def byte_to_terminal_id(value: int, prefix: str = "RT") -> str:
    return f"{prefix}-{int(value) & 0xFF:03d}"

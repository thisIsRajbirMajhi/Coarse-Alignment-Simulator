"""The receiver-visible framed beacon protocol.

Frames are ``PREAMBLE | SYNC | VERSION | TYPE | LENGTH | JSON PAYLOAD | CRC``.
Only the resulting OOK bits traverse the optical simulation.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field

PREAMBLE, SYNC_WORD = 0xAA, 0xD5
PROTOCOL_VERSION, MESSAGE_TYPE_BEACON = 1, 1
PREAMBLE_BYTES, SYNC_BYTES = bytes((PREAMBLE,)), bytes((SYNC_WORD,))
MAX_PAYLOAD_BYTES = 192
# Compatibility constants; a framed message is deliberately variable-length.
FRAME_BYTES = PAYLOAD_BYTES = FRAME_BITS = 0
CHIP_HIGH, CHIP_LOW = 1.0, 0.55


class CRC8:
    """CRC-8/ATM over header plus payload."""
    @staticmethod
    def compute(data: bytes | list[int]) -> int:
        crc = 0
        for value in data:
            crc ^= int(value) & 0xFF
            for _ in range(8):
                crc = ((crc << 1) ^ 0x07) & 0xFF if crc & 0x80 else (crc << 1) & 0xFF
        return crc


def crc8(data: bytes | list[int]) -> int: return CRC8.compute(data)


@dataclass(frozen=True)
class BeaconPayload:
    tid: str = "RT-001"
    token: str = "ALPHA-7"
    wl: int = 1550
    seq: int = 0

    def serialize(self) -> bytes:
        value = {"seq": int(self.seq), "tid": str(self.tid), "token": str(self.token), "wl": int(self.wl)}
        return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("ascii")

    @classmethod
    def deserialize(cls, raw: bytes) -> "BeaconPayload":
        value = json.loads(raw.decode("ascii"))
        required = {"tid", "token", "wl", "seq"}
        if not isinstance(value, dict) or required - set(value):
            raise ValueError("payload must include tid, token, wl and seq")
        return cls(str(value["tid"]), str(value["token"]), int(value["wl"]), int(value["seq"]))


@dataclass
class BeaconFrame:
    payload: BeaconPayload = field(default_factory=BeaconPayload)
    protocol_version: int = PROTOCOL_VERSION
    message_type: int = MESSAGE_TYPE_BEACON
    raw_bytes: bytes = b""
    crc_ok: bool = True

    @property
    def terminal_id_str(self) -> str: return self.payload.tid
    @property
    def sequence_number(self) -> int: return self.payload.seq
    @property
    def terminal_id_byte(self) -> int: return terminal_id_to_byte(self.payload.tid)
    @property
    def network_id(self) -> int: return 0
    @property
    def capabilities(self) -> int: return 0

    def to_bytes(self) -> bytes:
        body = self.payload.serialize()
        if len(body) > MAX_PAYLOAD_BYTES:
            raise ValueError(f"beacon payload exceeds {MAX_PAYLOAD_BYTES} bytes")
        header = bytes((self.protocol_version & 0xFF, self.message_type & 0xFF)) + len(body).to_bytes(2, "big")
        return PREAMBLE_BYTES + SYNC_BYTES + header + body + bytes((CRC8.compute(header + body),))


@dataclass
class BeaconDecodeResult:
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
    def terminal_id(self) -> str: return self.payload.tid if self.payload else ""
    @property
    def sequence_number(self) -> int: return self.payload.seq if self.payload else -1


class BeaconFrameParser:
    """Parses recovered chips and preserves structured failure reasons."""
    def parse(self, chips: list[int], confidence: float = 0.0) -> BeaconDecodeResult:
        data, marker = chips_to_bytes(chips), PREAMBLE_BYTES + SYNC_BYTES
        start = data.find(marker)
        if start < 0:
            return BeaconDecodeResult(decode_confidence=confidence, reason="INVALID_PREAMBLE_OR_SYNC")
        rest = data[start + len(marker):]
        if len(rest) < 5:
            return BeaconDecodeResult(frame_detected=True, synchronized=True, decode_confidence=confidence, reason="TRUNCATED_FRAME")
        version, message_type, length = rest[0], rest[1], int.from_bytes(rest[2:4], "big")
        common = dict(frame_detected=True, synchronized=True, protocol_version=version, message_type=message_type,
                      payload_length=length, decode_confidence=confidence)
        if length > MAX_PAYLOAD_BYTES:
            return BeaconDecodeResult(**common, reason="INVALID_LENGTH")
        end = 4 + length
        if len(rest) < end + 1:
            return BeaconDecodeResult(**common, reason="TRUNCATED_FRAME")
        raw_payload, received_crc = rest[4:end], rest[end]
        if CRC8.compute(rest[:end]) != received_crc:
            return BeaconDecodeResult(**common, reason="CRC_MISMATCH")
        try:
            payload = BeaconPayload.deserialize(raw_payload)
        except (UnicodeDecodeError, ValueError, TypeError, json.JSONDecodeError):
            return BeaconDecodeResult(**common, valid_crc=True, reason="INVALID_PAYLOAD")
        frame = BeaconFrame(payload, version, message_type, data[start:start + len(marker) + end + 1], True)
        return BeaconDecodeResult(**common, valid_crc=True, payload=payload, frame=frame, reason="OK")


def bytes_to_chips(data: bytes) -> list[int]:
    return [(byte >> bit) & 1 for byte in data for bit in range(7, -1, -1)]


def chips_to_bytes(chips: list[int]) -> bytes:
    return bytes(sum((int(chips[i + bit]) & 1) << (7 - bit) for bit in range(8)) for i in range(0, len(chips) - 7, 8))


def frame_to_bytes(frame: BeaconFrame) -> bytes: return frame.to_bytes()
def frame_to_chips(frame: BeaconFrame) -> list[int]: return bytes_to_chips(frame.to_bytes())
def chips_to_intensity(chip: int) -> float: return CHIP_HIGH if chip else CHIP_LOW
def decode_chips(chips: list[int]) -> BeaconFrame | None:
    result = BeaconFrameParser().parse(chips)
    return result.frame if result.valid_crc else None


def terminal_id_to_byte(tid: str) -> int:
    suffix = ""
    for char in reversed(str(tid)):
        if char.isdigit(): suffix = char + suffix
        elif suffix: break
    return int(suffix) & 0xFF if suffix else sum(map(ord, str(tid))) & 0xFF


def byte_to_terminal_id(value: int, prefix: str = "RT") -> str:
    return f"{prefix}-{int(value) & 0xFF:03d}"

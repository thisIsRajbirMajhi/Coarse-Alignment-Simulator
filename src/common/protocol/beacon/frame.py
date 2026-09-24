"""Beacon Frame structure, serialization, and parsing per Plans/New Upgrades.md §§5, 6, 16.

Frames are:
  PREAMBLE (0xAA) | SYNC (0xD5) | PROTOCOL_VERSION (1) | MESSAGE_TYPE (1) | PAYLOAD_LENGTH (2B) | PAYLOAD | CRC-8 (1B)
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from src.common.protocol.beacon.crc import CRC8, CRCValidator
from src.common.protocol.beacon.navigation import SEQUENCE_MODULUS, sequence_is_newer
from src.common.protocol.beacon.ook import (
    bytes_to_chips,
    chips_to_bytes,
    terminal_id_to_byte,
)
from src.common.protocol.beacon.payload import (
    BeaconPayload,
    DecodedPayload,
    PayloadDecoder,
)

PREAMBLE: int = 0xAA
SYNC_WORD: int = 0xD5
PROTOCOL_VERSION: int = 1
MESSAGE_TYPE_BEACON: int = 1
PREAMBLE_BYTES: bytes = bytes((PREAMBLE,))
SYNC_BYTES: bytes = bytes((SYNC_WORD,))
MAX_PAYLOAD_BYTES: int = 256


class BeaconFrame:
    """Framed digital beacon message per New Upgrades.md §§6, 7."""

    def __init__(
        self,
        payload: BeaconPayload | None = None,
        protocol_version: int = PROTOCOL_VERSION,
        message_type: int = MESSAGE_TYPE_BEACON,
        payload_codec: str = "COMPACT",
        raw_bytes: bytes = b"",
        crc_ok: bool = True,
        **kwargs: Any,
    ):
        if payload is not None:
            # Fill payload-level net/caps from kwargs when payload lacks them.
            try:
                _pn = int(getattr(payload, "network_id", 0) or 0)
                _pc = int(getattr(payload, "capabilities", 0) or 0)
            except Exception:
                _pn, _pc = 0, 0
            _kn = int(kwargs.get("network_id", 0) or 0)
            _kc = int(kwargs.get("capabilities", 0) or 0)
            if (not _pn and _kn) or (not _pc and _kc):
                try:
                    import dataclasses as _dc
                    payload = _dc.replace(payload,
                                          network_id=_pn or _kn,
                                          capabilities=_pc or _kc)
                except Exception:
                    pass
            self.payload = payload
        else:
            tid = kwargs.get("terminal_id", "")
            if not tid and "terminal_id_byte" in kwargs:
                from src.common.protocol.beacon.ook import byte_to_terminal_id
                tid = byte_to_terminal_id(int(kwargs["terminal_id_byte"]))
            if not tid:
                tid = "RT-001"
            token = str(kwargs.get("token", "ALPHA-7"))
            wl = int(kwargs.get("wavelength_nm", kwargs.get("wl", 1550)))
            seq = int(kwargs.get("sequence_number", kwargs.get("seq", 0)))
            self.payload = BeaconPayload(tid=str(tid), token=token, wl=wl, seq=seq,
                                         network_id=int(kwargs.get("network_id", 0) or 0),
                                         capabilities=int(kwargs.get("capabilities", 0) or 0))

        self.protocol_version = int(protocol_version)
        self.message_type = int(message_type)
        self.payload_codec = str(payload_codec)
        self.raw_bytes = raw_bytes
        self.crc_ok = bool(crc_ok)
        # Prefer explicit kwargs, else payload-level values (now serialized).
        try:
            _pl_n = int(getattr(self.payload, "network_id", 0) or 0)
            _pl_c = int(getattr(self.payload, "capabilities", 0) or 0)
        except Exception:
            _pl_n, _pl_c = 0, 0
        self._network_id = int(kwargs.get("network_id", _pl_n) or 0)
        self._capabilities = int(kwargs.get("capabilities", _pl_c) or 0)

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
        """Serialize frame to binary wire bytes."""
        body = self.payload.serialize(codec=self.payload_codec)
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
            f"codec='{self.payload_codec}', crc_ok={self.crc_ok})"
        )


@dataclass
class BeaconDecodeResult:
    """Structured result of frame decoding per New Upgrades.md §§6, 16."""

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
    is_new_frame: bool = False  # Mandatory per §16
    consumed_bits: int = 0

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
    """Parses recovered chips/bytes and preserves structured failure reasons (§6, §16)."""

    # 16-bit sync pattern: PREAMBLE (0xAA) then SYNC (0xD5)
    # Binary: 10101010 11010101
    MARKER_BITS = [1, 0, 1, 0, 1, 0, 1, 0, 1, 1, 0, 1, 0, 1, 0, 1]

    def parse(
        self,
        chips_or_bytes: list[int] | bytes,
        confidence: float = 0.0,
        last_seq: int = -1,
    ) -> BeaconDecodeResult:
        if isinstance(chips_or_bytes, bytes):
            chips = bytes_to_chips(chips_or_bytes)
        else:
            chips = [1 if c else 0 for c in chips_or_bytes]

        m_len = len(self.MARKER_BITS)
        if len(chips) < m_len + 40:  # Need marker + header (4B = 32b) + CRC (8b)
            return BeaconDecodeResult(decode_confidence=confidence, reason="INSUFFICIENT_DATA")

        best_fail: BeaconDecodeResult | None = None

        # Search for markers in chip stream
        for i in range(len(chips) - m_len - 39):
            if chips[i : i + m_len] == self.MARKER_BITS:
                start_idx = i
                rest_chips = chips[start_idx + m_len :]
                if len(rest_chips) < 40:
                    if best_fail is None:
                        best_fail = BeaconDecodeResult(
                            frame_detected=True,
                            synchronized=True,
                            decode_confidence=confidence,
                            reason="TRUNCATED_FRAME",
                        )
                    continue

                data = chips_to_bytes(rest_chips)
                if len(data) < 5:
                    if best_fail is None:
                        best_fail = BeaconDecodeResult(
                            frame_detected=True,
                            synchronized=True,
                            decode_confidence=confidence,
                            reason="TRUNCATED_FRAME",
                        )
                    continue

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
                    best_fail = BeaconDecodeResult(**common, reason="UNSUPPORTED_PROTOCOL_VERSION")
                    continue
                if message_type != MESSAGE_TYPE_BEACON:
                    best_fail = BeaconDecodeResult(**common, reason="UNSUPPORTED_MESSAGE_TYPE")
                    continue
                if length > MAX_PAYLOAD_BYTES or length < 2:
                    best_fail = BeaconDecodeResult(**common, reason="INVALID_LENGTH")
                    continue

                end = 4 + length
                if len(data) < end + 1:
                    best_fail = BeaconDecodeResult(**common, reason="TRUNCATED_FRAME")
                    continue

                header_and_payload = data[:end]
                raw_payload = data[4:end]
                received_crc = data[end]

                if not CRCValidator.validate(header_and_payload, received_crc):
                    best_fail = BeaconDecodeResult(**common, reason="CRC_MISMATCH")
                    continue

                try:
                    payload = BeaconPayload.deserialize(raw_payload, codec="AUTO")
                except Exception:
                    best_fail = BeaconDecodeResult(**common, valid_crc=True, reason="INVALID_PAYLOAD")
                    continue

                frame_bytes = bytes((PREAMBLE, SYNC_WORD)) + data[: end + 1]
                frame = BeaconFrame(
                    payload=payload,
                    protocol_version=version,
                    message_type=message_type,
                    raw_bytes=frame_bytes,
                    crc_ok=True,
                )

                is_new = bool(
                    last_seq < 0
                    or sequence_is_newer(
                        int(payload.seq) % SEQUENCE_MODULUS,
                        int(last_seq) % SEQUENCE_MODULUS,
                    )
                )
                consumed_bits = start_idx + m_len + (end + 1) * 8
                return BeaconDecodeResult(
                    **common,
                    valid_crc=True,
                    payload=payload,
                    frame=frame,
                    reason="OK",
                    is_new_frame=is_new,
                    consumed_bits=consumed_bits,
                )

        if best_fail is not None:
            return best_fail
        return BeaconDecodeResult(decode_confidence=confidence, reason="INVALID_PREAMBLE_OR_SYNC")


class BeaconFrameEncoder:
    """Builds the deterministic logical frame from configuration (§5, §6)."""

    def __init__(self, config: Any):
        self.config = config

    def encode(self, sequence_number: int) -> BeaconFrame:
        return BeaconFrame(
            payload=BeaconPayload(
                tid=str(getattr(self.config, "terminal_id", "RT-001")),
                token=str(getattr(self.config, "token", "ALPHA-7")),
                wl=int(getattr(self.config, "wavelength_nm", 1550)),
                seq=int(sequence_number),
                network_id=int(getattr(self.config, "network_id", 0) or 0),
                capabilities=int(getattr(self.config, "capabilities", 0) or 0),
                nav=bytes(getattr(self.config, "nav_bytes", b"") or b""),
            ),
            protocol_version=int(getattr(self.config, "protocol_version", PROTOCOL_VERSION)),
            message_type=int(getattr(self.config, "message_type", MESSAGE_TYPE_BEACON)),
            payload_codec=str(getattr(self.config, "payload_codec", "COMPACT")),
        )


def frame_to_bytes(frame: BeaconFrame) -> bytes:
    return frame.to_bytes()


def frame_to_chips(frame: BeaconFrame) -> list[int]:
    return bytes_to_chips(frame.to_bytes())


def decode_chips(chips: list[int]) -> BeaconFrame | None:
    result = BeaconFrameParser().parse(chips)
    return result.frame if result.valid_crc else None

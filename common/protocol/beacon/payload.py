"""Beacon Payload definitions and codecs per Plans/New Upgrades.md §§5, 7, 17.

Provides:
  - BeaconPayload: core dataclass holding logical payload fields
  - DecodedPayload: standardized output of payload decoding
  - PayloadCodec: supports compact binary encoding (default) and JSON (debug/reference)
  - PayloadDecoder: centralized payload parser
"""
from __future__ import annotations

import json
import struct
from dataclasses import dataclass
from typing import Any

from common.protocol.beacon.navigation import (
    CAP_NAVIGATION_STATE,
    NAV_EXTENSION_BYTES,
    NavigationState2D,
    decode_navigation_state,
)


@dataclass(frozen=True)
class BeaconPayload:
    """Framed beacon logical payload format (§7): tid, token, wl, seq.

    ``network_id`` (u8) and ``capabilities`` (u16BE) are optional trailing
    fields: omitted on the wire when both are 0 so default frames stay
    21 bytes (backward compatible). Present when either is non-zero.

    ``nav`` carries the 12-byte navigation extension (timestamp_ms uint32BE +
    x/y float32BE) and is emitted on the wire only when the
    ``CAP_NAVIGATION_STATE`` capability bit is set. Decoders must tolerate
    its absence (legacy payloads) and malformed truncations (contained as
    absent rather than raising).
    """

    tid: str = "RT-001"
    token: str = "ALPHA-7"
    wl: int = 1550
    seq: int = 0
    network_id: int = 0
    capabilities: int = 0
    nav: bytes = b""

    def serialize(self, codec: str = "COMPACT") -> bytes:
        """Serialize payload using specified codec ('COMPACT' or 'JSON')."""
        if str(codec).upper() == "JSON":
            return PayloadCodec.serialize_json(self)
        return PayloadCodec.serialize_compact(self)

    @classmethod
    def deserialize(cls, raw: bytes, codec: str = "AUTO") -> BeaconPayload:
        """Deserialize raw bytes to BeaconPayload, auto-detecting format if requested."""
        return PayloadCodec.deserialize(raw, codec=codec)


@dataclass
class DecodedPayload:
    """Standard decoded beacon payload per New Upgrades.md §17."""

    terminal_id: str = "RT-001"
    token: str = "ALPHA-7"
    wavelength_nm: float = 1550.0
    sequence_number: int = 0
    network_id: int = 0
    capabilities: int = 0
    navigation_state: NavigationState2D | None = None


class PayloadCodec:
    """Encodes and decodes BeaconPayload to/from raw wire bytes (§7)."""

    @staticmethod
    def serialize_compact(payload: BeaconPayload) -> bytes:
        """Compact deterministic binary wire format:
        tid_len   : uint8
        tid       : UTF-8 bytes
        token_len : uint8
        token     : UTF-8 bytes
        wavelength: uint16 (big-endian)
        sequence  : uint32 (big-endian)
        [network_id: uint8 + capabilities: uint16BE] — only when non-zero
        [navigation extension: 12B] — only when CAP_NAVIGATION_STATE is set
        """
        tid_b = str(payload.tid).encode("utf-8")
        token_b = str(payload.token).encode("utf-8")
        if len(tid_b) > 255 or len(token_b) > 255:
            raise ValueError("tid and token must each be <= 255 bytes")
        header = bytes([len(tid_b)]) + tid_b + bytes([len(token_b)]) + token_b
        tail = struct.pack(">HI", int(payload.wl) & 0xFFFF, int(payload.seq) & 0xFFFFFFFF)
        net = int(getattr(payload, "network_id", 0) or 0) & 0xFF
        caps = int(getattr(payload, "capabilities", 0) or 0) & 0xFFFF
        nav = bytes(getattr(payload, "nav", b"") or b"")
        nav_gated = bool(caps & CAP_NAVIGATION_STATE)
        if nav and not nav_gated:
            raise ValueError("navigation bytes present without CAP_NAVIGATION_STATE")
        if nav_gated and len(nav) != NAV_EXTENSION_BYTES:
            raise ValueError(
                f"CAP_NAVIGATION_STATE set but nav is {len(nav)} bytes "
                f"(expected {NAV_EXTENSION_BYTES})"
            )
        if net or caps:
            tail += struct.pack(">BH", net, caps)
        if nav_gated:
            tail += nav
        return header + tail

    @staticmethod
    def deserialize_compact(raw: bytes) -> BeaconPayload:
        """Unpack compact binary payload format (tolerates trailing net/caps/nav).

        Missing or truncated navigation extensions are contained as absent
        (``nav=b""``) so malformed frames never crash the caller.
        """
        if len(raw) < 8:  # Min: 1B len + 0B + 1B len + 0B + 2B wl + 4B seq = 8 bytes
            raise ValueError(f"compact payload too short: {len(raw)} bytes")
        offset = 0
        tid_len = raw[offset]
        offset += 1
        if len(raw) < offset + tid_len + 1:
            raise ValueError("malformed compact payload: truncated tid")
        tid = raw[offset : offset + tid_len].decode("utf-8", errors="replace")
        offset += tid_len

        token_len = raw[offset]
        offset += 1
        if len(raw) < offset + token_len + 6:
            raise ValueError("malformed compact payload: truncated token or footer")
        token = raw[offset : offset + token_len].decode("utf-8", errors="replace")
        offset += token_len

        wl, seq = struct.unpack(">HI", raw[offset : offset + 6])
        offset += 6
        net, caps = 0, 0
        if len(raw) >= offset + 3:
            try:
                net, caps = struct.unpack(">BH", raw[offset : offset + 3])
            except Exception:
                net, caps = 0, 0
            else:
                offset += 3
        nav = b""
        if caps & CAP_NAVIGATION_STATE and len(raw) >= offset + NAV_EXTENSION_BYTES:
            nav = bytes(raw[offset : offset + NAV_EXTENSION_BYTES])
        return BeaconPayload(tid=tid, token=token, wl=int(wl), seq=int(seq),
                             network_id=int(net), capabilities=int(caps), nav=nav)

    @staticmethod
    def serialize_json(payload: BeaconPayload) -> bytes:
        """JSON serialization for debug/reference (§7)."""
        value = {
            "seq": int(payload.seq),
            "tid": str(payload.tid),
            "token": str(payload.token),
            "wl": int(payload.wl),
        }
        if int(getattr(payload, "network_id", 0) or 0):
            value["net"] = int(payload.network_id)
        if int(getattr(payload, "capabilities", 0) or 0):
            value["caps"] = int(payload.capabilities)
        nav = bytes(getattr(payload, "nav", b"") or b"")
        if nav:
            if not (int(getattr(payload, "capabilities", 0) or 0) & CAP_NAVIGATION_STATE):
                raise ValueError("navigation bytes present without CAP_NAVIGATION_STATE")
            if len(nav) != NAV_EXTENSION_BYTES:
                raise ValueError(f"nav must be {NAV_EXTENSION_BYTES} bytes, got {len(nav)}")
            value["nav"] = nav.hex()
        return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("ascii")

    @staticmethod
    def deserialize_json(raw: bytes) -> BeaconPayload:
        """JSON deserialization for debug/reference (§7)."""
        value = json.loads(raw.decode("ascii"))
        required = {"tid", "token", "wl", "seq"}
        if not isinstance(value, dict) or required - set(value):
            raise ValueError("payload must include tid, token, wl and seq")
        nav_hex = value.get("nav", value.get("navigation", ""))
        nav = b""
        if nav_hex:
            try:
                nav = bytes.fromhex(str(nav_hex))
            except ValueError as e:
                raise ValueError(f"invalid nav hex: {e}") from e
            if len(nav) != NAV_EXTENSION_BYTES:
                raise ValueError(f"nav must be {NAV_EXTENSION_BYTES} bytes, got {len(nav)}")
        return BeaconPayload(str(value["tid"]), str(value["token"]), int(value["wl"]), int(value["seq"]),
                             network_id=int(value.get("net", value.get("network_id", 0)) or 0),
                             capabilities=int(value.get("caps", value.get("capabilities", 0)) or 0),
                             nav=nav)

    @classmethod
    def deserialize(cls, raw: bytes, codec: str = "AUTO") -> BeaconPayload:
        codec_upper = str(codec).upper()
        if codec_upper == "JSON":
            return cls.deserialize_json(raw)
        if codec_upper == "COMPACT":
            return cls.deserialize_compact(raw)
        # AUTO detection: JSON starts with b"{"
        if raw.startswith(b"{"):
            try:
                return cls.deserialize_json(raw)
            except Exception:
                pass
        return cls.deserialize_compact(raw)


class PayloadDecoder:
    """Converts binary payload bytes into DecodedPayload (§17)."""

    @staticmethod
    def decode(raw_payload: bytes, codec: str = "AUTO") -> DecodedPayload:
        payload = BeaconPayload.deserialize(raw_payload, codec=codec)
        nav_state: NavigationState2D | None = None
        nav = bytes(getattr(payload, "nav", b"") or b"")
        if nav:
            # Contained: a corrupt extension yields absent state, never a crash.
            try:
                nav_state = decode_navigation_state(nav)
            except (TypeError, ValueError):
                nav_state = None
        return DecodedPayload(
            terminal_id=str(payload.tid),
            token=str(payload.token),
            wavelength_nm=float(payload.wl),
            sequence_number=int(payload.seq),
            network_id=int(getattr(payload, "network_id", 0) or 0),
            capabilities=int(getattr(payload, "capabilities", 0) or 0),
            navigation_state=nav_state,
        )

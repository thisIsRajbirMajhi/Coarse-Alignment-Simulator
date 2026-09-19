"""The receiver-visible framed beacon protocol per Plans/New Upgrades.md §§5, 6, 7.

Re-exports shared definitions from common.protocol.beacon for backward compatibility.
"""
from __future__ import annotations

from common.protocol.beacon import (
    CHIP_HIGH,
    CHIP_LOW,
    MAX_PAYLOAD_BYTES,
    MESSAGE_TYPE_BEACON,
    PREAMBLE,
    PREAMBLE_BYTES,
    PROTOCOL_VERSION,
    SYNC_BYTES,
    SYNC_WORD,
    BeaconDecodeResult,
    BeaconFrame,
    BeaconFrameEncoder,
    BeaconFrameParser,
    BeaconPayload,
    CRC8,
    CRCValidator,
    DecodedPayload,
    OOKEncoder,
    PayloadCodec,
    PayloadDecoder,
    byte_to_terminal_id,
    bytes_to_chips,
    chips_to_bytes,
    chips_to_intensity,
    crc8,
    decode_chips,
    frame_to_bytes,
    frame_to_chips,
    terminal_id_to_byte,
)

# Compatibility constants
FRAME_BYTES: int = 0
PAYLOAD_BYTES: int = 0
FRAME_BITS: int = 0

__all__ = [
    "BeaconPayload",
    "DecodedPayload",
    "PayloadCodec",
    "PayloadDecoder",
    "BeaconFrame",
    "BeaconFrameEncoder",
    "BeaconDecodeResult",
    "BeaconFrameParser",
    "frame_to_bytes",
    "frame_to_chips",
    "decode_chips",
    "CRC8",
    "CRCValidator",
    "crc8",
    "OOKEncoder",
    "CHIP_HIGH",
    "CHIP_LOW",
    "bytes_to_chips",
    "chips_to_bytes",
    "chips_to_intensity",
    "terminal_id_to_byte",
    "byte_to_terminal_id",
    "PREAMBLE",
    "SYNC_WORD",
    "PROTOCOL_VERSION",
    "MESSAGE_TYPE_BEACON",
    "PREAMBLE_BYTES",
    "SYNC_BYTES",
    "MAX_PAYLOAD_BYTES",
    "FRAME_BYTES",
    "PAYLOAD_BYTES",
    "FRAME_BITS",
]

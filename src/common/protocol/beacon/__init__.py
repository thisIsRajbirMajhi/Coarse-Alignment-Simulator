"""Neutral shared beacon protocol package per Plans/New Upgrades.md §5."""
from __future__ import annotations

from src.common.protocol.beacon.crc import CRC8, CRCValidator, crc8
from src.common.protocol.beacon.frame import (
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
    decode_chips,
    frame_to_bytes,
    frame_to_chips,
)
from src.common.protocol.beacon.ook import (
    CHIP_HIGH,
    CHIP_LOW,
    OOKEncoder,
    byte_to_terminal_id,
    bytes_to_chips,
    chips_to_bytes,
    chips_to_intensity,
    terminal_id_to_byte,
)
from src.common.protocol.beacon.navigation import (
    CAP_NAVIGATION_STATE,
    NAV_EXTENSION_BYTES,
    NAV_EXTENSION_FORMAT,
    SEQUENCE_MODULUS,
    NavigationState2D,
    decode_navigation_state,
    encode_navigation_state,
    sequence_is_newer,
)
from src.common.protocol.beacon.payload import (
    BeaconPayload,
    DecodedPayload,
    PayloadCodec,
    PayloadDecoder,
)

__all__ = [
    # Payload
    "BeaconPayload",
    "DecodedPayload",
    "PayloadCodec",
    "PayloadDecoder",
    # Navigation extension (RemoteTerminal.md §§17-23)
    "CAP_NAVIGATION_STATE",
    "NAV_EXTENSION_BYTES",
    "NAV_EXTENSION_FORMAT",
    "SEQUENCE_MODULUS",
    "NavigationState2D",
    "encode_navigation_state",
    "decode_navigation_state",
    "sequence_is_newer",
    # Frame
    "BeaconFrame",
    "BeaconFrameEncoder",
    "BeaconDecodeResult",
    "BeaconFrameParser",
    "frame_to_bytes",
    "frame_to_chips",
    "decode_chips",
    # CRC
    "CRC8",
    "CRCValidator",
    "crc8",
    # OOK
    "OOKEncoder",
    "CHIP_HIGH",
    "CHIP_LOW",
    "bytes_to_chips",
    "chips_to_bytes",
    "chips_to_intensity",
    "terminal_id_to_byte",
    "byte_to_terminal_id",
    # Constants
    "PREAMBLE",
    "SYNC_WORD",
    "PROTOCOL_VERSION",
    "MESSAGE_TYPE_BEACON",
    "PREAMBLE_BYTES",
    "SYNC_BYTES",
    "MAX_PAYLOAD_BYTES",
]

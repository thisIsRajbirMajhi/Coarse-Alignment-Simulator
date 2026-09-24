"""OOK chip modulation, bit conversion, and intensity encoding per Plans/New Upgrades.md §§5, 9.
"""
from __future__ import annotations

from typing import Any

# Normalized optical intensity levels for OOK chips
CHIP_HIGH: float = 1.0
CHIP_LOW: float = 0.45


def bytes_to_chips(data: bytes) -> list[int]:
    """Convert bytes to a list of binary chips (MSB first)."""
    return [(byte >> bit) & 1 for byte in data for bit in range(7, -1, -1)]


def chips_to_bytes(chips: list[int]) -> bytes:
    """Convert a list of binary chips back into bytes."""
    return bytes(
        sum((int(chips[i + bit]) & 1) << (7 - bit) for bit in range(8))
        for i in range(0, len(chips) - 7, 8)
    )


def chips_to_intensity(chip: int) -> float:
    """Map binary chip {0, 1} to optical intensity level."""
    return CHIP_HIGH if chip else CHIP_LOW


class OOKEncoder:
    """Explicit frame -> bits -> OOK intensity abstraction (§9)."""

    def chips(self, frame_or_bytes: Any) -> list[int]:
        if hasattr(frame_or_bytes, "to_bytes"):
            raw = frame_or_bytes.to_bytes()
        elif isinstance(frame_or_bytes, bytes):
            raw = frame_or_bytes
        elif isinstance(frame_or_bytes, (list, tuple)):
            return [1 if c else 0 for c in frame_or_bytes]
        else:
            raise TypeError(f"cannot extract chips from {type(frame_or_bytes)}")
        return bytes_to_chips(raw)

    def intensity(self, chip: int) -> float:
        return chips_to_intensity(chip)


def terminal_id_to_byte(tid: str) -> int:
    """Extract or hash terminal ID into a single byte for legacy/compact identifiers."""
    suffix = ""
    for char in reversed(str(tid)):
        if char.isdigit():
            suffix = char + suffix
        elif suffix:
            break
    return int(suffix) & 0xFF if suffix else sum(map(ord, str(tid))) & 0xFF


def byte_to_terminal_id(value: int, prefix: str = "RT") -> str:
    """Convert single byte into canonical terminal ID string e.g. RT-001."""
    return f"{prefix}-{int(value) & 0xFF:03d}"

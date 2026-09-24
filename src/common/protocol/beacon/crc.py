"""CRC-8 calculation and validation for beacon frames per Plans/New Upgrades.md §§5, 6.

Uses CRC-8/ATM (polynomial 0x07) over header plus payload.
"""
from __future__ import annotations


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
    """Convenience function returning CRC-8 of input data."""
    return CRC8.compute(data)


class CRCValidator:
    """Validates CRC-8 over header + payload (§6)."""

    @staticmethod
    def validate(data: bytes | list[int], expected_crc: int) -> bool:
        return CRC8.compute(data) == (int(expected_crc) & 0xFF)

"""Navigation-state extension for the shared beacon protocol (RemoteTerminal.md §§17-23).

Wire format (big-endian, IEEE-754, 12 bytes total)::

    timestamp_ms : uint32
    position_x_m : float32
    position_y_m : float32

The extension rides inside ``BeaconPayload`` as trailing bytes, gated by the
``CAP_NAVIGATION_STATE`` capability bit. Payloads without the bit (including
all legacy payloads) decode with ``navigation_state = None``.

Sequence numbers wrap modulo 256 (see ``sequence_is_newer``); naive
``new > old`` ordering must NOT be used for freshness checks.
"""
from __future__ import annotations

import struct
from dataclasses import dataclass

# First (lowest) capability bit — no named capability bits existed before,
# so bit 0 is the first currently-unused one (RemoteTerminal.md §19).
CAP_NAVIGATION_STATE: int = 0x0001

# Sequence numbers live in 0..255 and wrap (RemoteTerminal.md §26).
SEQUENCE_MODULUS: int = 256

NAV_EXTENSION_FORMAT: str = ">Iff"
NAV_EXTENSION_BYTES: int = struct.calcsize(NAV_EXTENSION_FORMAT)  # 12

_UINT32_MAX: int = 0xFFFFFFFF


@dataclass(frozen=True)
class NavigationState2D:
    """Sampled last-known 2D location carried by the optical beacon.

    A *sampled report*, not live truth: encode once per beacon frame from the
    terminal's position at frame start; never mutate an encoded frame.
    Units: timestamp_ms (int ms), positions in metres.
    """

    timestamp_ms: int
    position_x_m: float
    position_y_m: float


def encode_navigation_state(state: NavigationState2D) -> bytes:
    """Deterministic 12-byte binary encoding (big-endian, IEEE-754).

    Raises:
        TypeError: if ``state`` is not a NavigationState2D.
        ValueError: if the timestamp is not a non-negative uint32 or a
            position is not finite.
    """
    if not isinstance(state, NavigationState2D):
        raise TypeError(f"expected NavigationState2D, got {type(state).__name__}")
    ts = int(state.timestamp_ms)
    if ts < 0 or ts > _UINT32_MAX:
        raise ValueError(f"timestamp_ms out of uint32 range: {state.timestamp_ms!r}")
    try:
        x = float(state.position_x_m)
        y = float(state.position_y_m)
    except (TypeError, ValueError) as e:
        raise ValueError(f"non-numeric navigation position: {e}") from e
    import math
    if not (math.isfinite(x) and math.isfinite(y)):
        raise ValueError(f"navigation position must be finite: ({x!r}, {y!r})")
    return struct.pack(NAV_EXTENSION_FORMAT, ts, x, y)


def decode_navigation_state(data: bytes) -> NavigationState2D:
    """Decode 12 extension bytes back into a NavigationState2D.

    Raises:
        TypeError: if ``data`` is not bytes-like.
        ValueError: if the length is not exactly 12 bytes or the payload
            is structurally invalid. Callers that must not fail (e.g. the
            payload decoder) should catch ValueError and treat the
            navigation state as absent.
    """
    if not isinstance(data, (bytes, bytearray, memoryview)):
        raise TypeError(f"expected bytes, got {type(data).__name__}")
    if len(data) != NAV_EXTENSION_BYTES:
        raise ValueError(
            f"navigation extension must be {NAV_EXTENSION_BYTES} bytes, got {len(data)}"
        )
    try:
        ts, x, y = struct.unpack(NAV_EXTENSION_FORMAT, bytes(data))
    except struct.error as e:
        raise ValueError(f"malformed navigation extension: {e}") from e
    return NavigationState2D(timestamp_ms=int(ts), position_x_m=float(x), position_y_m=float(y))


def sequence_is_newer(new_seq: int, old_seq: int, bits: int = 8) -> bool:
    """Modulo-``bits`` freshness check (RemoteTerminal.md §26).

    True when ``new_seq`` is strictly ahead of ``old_seq`` on the wrapping
    ring, i.e. ``0 < (new - old) mod 2**bits < 2**(bits-1)``. Equal values
    are never "newer"; values exactly half a ring apart are treated as stale
    (ambiguous) rather than newer.
    """
    if bits < 2:
        raise ValueError(f"bits must be >= 2, got {bits!r}")
    mod = 1 << int(bits)
    delta = (int(new_seq) - int(old_seq)) % mod
    return 0 < delta < (mod // 2)


__all__ = [
    "CAP_NAVIGATION_STATE",
    "SEQUENCE_MODULUS",
    "NAV_EXTENSION_BYTES",
    "NAV_EXTENSION_FORMAT",
    "NavigationState2D",
    "encode_navigation_state",
    "decode_navigation_state",
    "sequence_is_newer",
]

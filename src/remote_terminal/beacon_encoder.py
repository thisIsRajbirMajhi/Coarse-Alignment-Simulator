# remote_terminal/beacon_encoder.py - BeaconGenerator: protocol/modulation only.
#
# Owns the per-terminal beacon frame lifecycle (RemoteTerminal.md §§24-26,
# §§51-52): sample navigation ONCE per frame, encode payload, frame it, CRC
# it, modulate to OOK chips, then transmit that FIXED frame until completion.
# Never reads live position mid-frame; never computes formation/trajectory/
# range/footprint (those belong elsewhere).
from __future__ import annotations

from dataclasses import dataclass

# Recent-frame history for time-truthful chip sampling (chip_at). A receiver
# sampling a past interval after the manager already advanced would otherwise
# read the NEW frame's clamped chip-0 for the OLD frame's tail chips and
# corrupt every CRC. Four frames (~1.3 s) cover any sampling lag.
FRAME_HISTORY_LEN: int = 4

from src.common.protocol.beacon.frame import BeaconFrame
from src.common.protocol.beacon.navigation import (
    CAP_NAVIGATION_STATE,
    SEQUENCE_MODULUS,
    NavigationState2D,
    encode_navigation_state,
)
from src.common.protocol.beacon.ook import OOKEncoder
from src.common.protocol.beacon.payload import BeaconPayload

# Internal chip timing: one OOK chip per millisecond. The frame period is
# derived (chips × duration), so a frame always completes before the next
# one is generated (§52). NOT a GUI parameter.
CHIP_DURATION_S: float = 1e-3

# Stagger between terminal first-frames, in chips. Co-located terminals share
# the frame clock, so without a deterministic index-based stagger every
# beacon would blink in lockstep. NOT a GUI parameter.
FIRST_FRAME_STAGGER_CHIPS: int = 16


@dataclass
class GeneratedBeacon:
    """One immutable encoded beacon frame (never modified after creation)."""

    terminal_id: str
    sequence: int
    navigation: NavigationState2D
    payload: BeaconPayload
    frame: BeaconFrame
    chips: list[int]
    frame_bytes: bytes
    start_time_s: float

    @property
    def frame_period_s(self) -> float:
        return len(self.chips) * CHIP_DURATION_S

    def is_complete(self, sim_time_s: float) -> bool:
        return float(sim_time_s) - self.start_time_s >= self.frame_period_s

    def chip_at(self, sim_time_s: float) -> int:
        """Current OOK chip (1/0); clamped to the frame bounds."""
        if not self.chips:
            return 1
        idx = int((float(sim_time_s) - self.start_time_s) / CHIP_DURATION_S)
        idx = min(max(idx, 0), len(self.chips) - 1)
        return 1 if self.chips[idx] else 0


class BeaconGenerator:
    """Sample → encode → frame → modulate (§51)."""

    def __init__(
        self,
        terminal_id: str,
        wavelength_nm: float,
        initial_delay_s: float = 0.0,
        token: str = "",
        network_id: int = 0,
        enable_nav: bool = True,
    ):
        self.terminal_id = str(terminal_id)
        self.wavelength_nm = float(wavelength_nm)
        # First-frame delay staggers co-clocked terminals (see above).
        self.initial_delay_s = max(0.0, float(initial_delay_s))
        self.token = str(token or "").strip()
        try:
            net = int(network_id)
        except (TypeError, ValueError):
            net = 0
        self.network_id = max(0, min(255, net))
        self.enable_nav = bool(enable_nav)
        self.sequence = 0
        self.current: GeneratedBeacon | None = None
        self._ook = OOKEncoder()
        from collections import deque as _deque
        self.history: _deque = _deque(maxlen=FRAME_HISTORY_LEN)

    def new_frame(self, navigation: NavigationState2D, sim_time_s: float) -> GeneratedBeacon:
        """Encode a new frame from a pre-sampled navigation snapshot.

        Uses the current sequence number, then increments with modulo-256
        wrap (§26). The ``navigation`` snapshot is encoded as-is: pass the
        frame-start sample, never live state.
        """
        if not isinstance(navigation, NavigationState2D):
            raise TypeError(
                f"navigation must be NavigationState2D, got {type(navigation).__name__}."
            )
        seq = int(self.sequence) % SEQUENCE_MODULUS
        nav = encode_navigation_state(navigation) if self.enable_nav else b""
        payload = BeaconPayload(
            tid=self.terminal_id,
            token=(self.token or self.terminal_id),
            wl=int(round(self.wavelength_nm)),
            seq=seq,
            network_id=int(self.network_id),
            capabilities=(CAP_NAVIGATION_STATE if self.enable_nav else 0),
            nav=nav,
        )
        frame = BeaconFrame(payload=payload)
        wire = frame.to_bytes()  # CRC covers the extended frame (§83)
        chips = self._ook.chips(wire)
        beacon = GeneratedBeacon(
            terminal_id=self.terminal_id,
            sequence=seq,
            navigation=navigation,
            payload=payload,
            frame=frame,
            chips=chips,
            frame_bytes=wire,
            start_time_s=float(sim_time_s),
        )
        self.current = beacon
        self.history.append(beacon)
        self.sequence = (seq + 1) % SEQUENCE_MODULUS
        return beacon

    def needs_new_frame(self, sim_time_s: float, emitting: bool) -> bool:
        """True when emitting and no frame exists or the current one completed."""
        if not emitting:
            return False
        if self.current is None:
            return float(sim_time_s) >= self.initial_delay_s
        return self.current.is_complete(float(sim_time_s))

    def chip_at(self, sim_time_s: float) -> int:
        """Current OOK chip level; 1 when no frame exists yet.

        Time-truthful: the frame covering ``sim_time_s`` answers (newest
        first), so post-update sampling of a past interval reads the frame
        that actually owned those milliseconds — not the current frame's
        clamped edge. Outside all known frames the legacy clamps apply
        (pre-emission idle-high, post-end last chip), matching BeamModel.
        """
        t = float(sim_time_s)
        for beacon in reversed(self.history):
            start = float(beacon.start_time_s)
            if start <= t < start + beacon.frame_period_s and beacon.chips:
                idx = int((t - start) / CHIP_DURATION_S)
                idx = min(max(idx, 0), len(beacon.chips) - 1)
                return 1 if beacon.chips[idx] else 0
        if self.current is None:
            return 1
        return self.current.chip_at(t)


__all__ = [
    "BeaconGenerator",
    "GeneratedBeacon",
    "CHIP_DURATION_S",
    "FIRST_FRAME_STAGGER_CHIPS",
    "FRAME_HISTORY_LEN",
]

# local_terminal/comm_receiver.py - Fast-photodiode comm receiver (Plan.md Stage 3).
#
# Physical basis: the tracking camera (30 Hz) cannot resolve 1 kHz OOK chips,
# so decoding runs on a separate co-boresighted photodiode model. It observes
# the *received waveform* — the same sensor-privilege level as the camera
# image. Ground-truth isolation holds: positions/states are used only as
# sensor-FOV physics (which emitter's light reaches the diode), the same
# privilege render_spots already exercises. Decoded content (TID, seq,
# wavelength, CRC) is the only thing that crosses into validation.
#
# Clock recovery (real): the receiver clock is NOT synchronized to the
# transmitter — float truncation alone corrupts int()-indexed sampling, and
# any fixed phase assumption breaks. The receiver therefore oversamples at
# 4× (0.25 ms), acquires chip phase by correlating the known 16-bit
# preamble/sync marker across the four sub-phases (exactly what the marker
# is for), then slices chips on the recovered grid. Mid-grid quantization is
# ≤1/8 chip, immune to float error. Loss of parses triggers re-acquisition.
#
# Simplification (documented): capture effect — the nearest-to-boresight
# emitter dominates. Multi-emitter chip superposition is Stage-4 work.

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field

from common.protocol.beacon.frame import BeaconDecodeResult, BeaconFrameParser


CHIP_DT_S: float = 1e-3
# 8× oversampling: each chip's majority vote absorbs up to 3 boundary-flipped
# subs, so float-exact chip-edge sampling cannot corrupt CRCs. (4× proved
# insufficient: a systematic single-sub edge hit survived windowed means.)
SUBS_PER_CHIP: int = 8
SUB_DT_S: float = CHIP_DT_S / SUBS_PER_CHIP
# Sub-clock offset (fraction of one sub-sample): keeps samples safely inside
# chips instead of exactly on chip boundaries, where float truncation in
# int()-indexed chip lookup flips edge samples randomly and corrupts CRCs.
SUB_GRID_EPSILON: float = 0.37
BUFFER_CHIPS: int = 2048
SUB_BUFFER_MAX: int = SUBS_PER_CHIP * 600
MARKER_BITS: tuple[int, ...] = (1, 0, 1, 0, 1, 0, 1, 0, 1, 1, 0, 1, 0, 1, 0, 1)
REALIGN_AFTER_UPDATES_WITHOUT_PARSE: int = 100


def ber_from_snr_db(snr_db: float) -> float:
    """OOK bit-error rate from photometric SNR (hard-decision proxy).

    BER = ½·erfc(√(SNR_lin/2)). Clean-sky SNR (~30 dB) → ~0; detection
    floor (6 dB) → ~2%. Faded/dim candidates therefore fail CRC and strike
    out instead of validating — physical, not a tuning artefact.
    """
    import math

    try:
        snr_lin = 10.0 ** (float(snr_db) / 10.0)
    except (TypeError, ValueError):
        return 0.5
    if snr_lin <= 0.0:
        return 0.5
    return float(0.5 * math.erfc(math.sqrt(snr_lin / 2.0)))


@dataclass
class CommSource:
    """One emitter as seen by the diode (sensor-model view, built by glue)."""

    position: tuple[float, float] = (0.0, 0.0)
    emitting: bool = False
    power_w: float = 0.0
    chip_at: object = None  # callable(sim_time_s) -> 0/1


@dataclass
class CommReceiver:
    """Oversampling photodiode + clock recovery + frame synchroniser."""

    buffer: deque = field(default_factory=lambda: deque(maxlen=BUFFER_CHIPS))
    parsed_frames: int = 0
    crc_failures: int = 0

    def __post_init__(self) -> None:
        self._sub: deque = deque(maxlen=SUB_BUFFER_MAX)
        self._phase: int | None = None
        self._updates_since_ok = 0
        self._next_t: float | None = None

    def reset(self) -> None:
        self.buffer.clear()
        self.parsed_frames = 0
        self.crc_failures = 0
        self._sub.clear()
        self._phase = None
        self._updates_since_ok = 0
        self._next_t = None

    @property
    def aligned(self) -> bool:
        return self._phase is not None

    def update(self, sources: list[CommSource], boresight: tuple[float, float],
               sim_time_s: float, dt: float, ber: float = 0.0, rng=None) -> None:
        """Sample one camera-frame worth of waveform at 4× oversampling,
        recover chip phase, and slice newly completed chips into the buffer.

        Sampling runs on a free-running uniform sub-clock (not round(dt)
        samples per step) so the grid never drifts against transmitter time.
        """
        now = float(sim_time_s)
        if self._next_t is None:
            self._next_t = now - max(float(dt), 1e-6) + SUB_DT_S * SUB_GRID_EPSILON
        guard = 0
        while self._next_t <= now + 1e-9 and guard < 4096:
            self._sub.append(self._dominant_chip(sources, boresight, self._next_t))
            self._next_t += SUB_DT_S
            guard += 1
        if self._phase is None:
            self._acquire_phase()
        if self._phase is not None:
            self._slice_chips(float(ber), rng)
            self._updates_since_ok += 1
            if self._updates_since_ok > REALIGN_AFTER_UPDATES_WITHOUT_PARSE:
                # Parses stopped arriving (phase slip / source change): re-acquire.
                self._phase = None
                self._sub.clear()
                self.buffer.clear()
                self._updates_since_ok = 0

    def _dominant_chip(self, sources: list[CommSource], boresight: tuple[float, float],
                       t: float) -> int:
        best = None
        best_d2 = None
        for src in sources:
            # Gate on link activity only: a low OOK chip (power 0 *now*) is a
            # valid chip-0 observation, not absence of signal. Snapshotting
            # instantaneous power at step end and gating on it would discard
            # whole steps ending on a low chip.
            if not src.emitting:
                continue
            dx = float(src.position[0]) - float(boresight[0])
            dy = float(src.position[1]) - float(boresight[1])
            d2 = dx * dx + dy * dy
            if best is None or d2 < best_d2:
                best, best_d2 = src, d2
        if best is None:
            return 0
        try:
            return 1 if int(best.chip_at(float(t))) else 0
        except Exception:
            return 0

    def _slice_phase(self, sub: list[int], phase: int) -> list[int]:
        """Majority-vote chips for one candidate phase.

        Acquisition and slicing MUST share this exact rule: correlating on
        single subs while slicing windowed means can disagree by one chip at
        straddled boundaries and shift the whole stream.
        """
        chips = []
        k = 0
        while phase + SUBS_PER_CHIP * k + SUBS_PER_CHIP <= len(sub):
            window = sub[phase + SUBS_PER_CHIP * k:phase + SUBS_PER_CHIP * (k + 1)]
            chips.append(1 if sum(window) * 2 >= len(window) else 0)
            k += 1
        return chips

    def _acquire_phase(self) -> None:
        """Correlate the sync marker on each sub-phase's sliced stream; lock
        the phase with the most marker matches (nearest mid-chip)."""
        sub = list(self._sub)
        m = len(MARKER_BITS)
        best: tuple[int, int, int] | None = None  # (matches, phase, first_index)
        for phase in range(SUBS_PER_CHIP):
            chips = self._slice_phase(sub, phase)
            if len(chips) < m + 8:
                continue
            hits = [j for j in range(len(chips) - m + 1)
                    if all(chips[j + k] == MARKER_BITS[k] for k in range(m))]
            if hits and (best is None or len(hits) > best[0]):
                best = (len(hits), phase, hits[0])
        if best is None:
            return
        _, phase, j = best
        self._phase = phase
        # Drop waveform before the marker; slicing reproduces identical chips
        # by construction, so the buffer starts exactly on the marker.
        drop = phase + SUBS_PER_CHIP * j
        for _ in range(min(drop, len(self._sub))):
            self._sub.popleft()

    def _slice_chips(self, ber: float, rng) -> None:
        """Slice newly completed chips on the locked grid (same majority-vote
        rule as acquisition, so framing cannot shift between the two)."""
        assert self._phase is not None
        sub = list(self._sub)
        chips = self._slice_phase(sub, self._phase)
        for chip in chips:
            if ber > 0.0 and rng is not None:
                try:
                    if float(rng.random()) < float(ber):
                        chip ^= 1
                except Exception:
                    pass
            self.buffer.append(chip)
        drop = self._phase + SUBS_PER_CHIP * len(chips)
        for _ in range(min(drop, len(self._sub))):
            self._sub.popleft()

    def try_parse(self) -> BeaconDecodeResult | None:
        """Attempt frame sync on the sliced chip buffer; consume on CRC-OK."""
        if len(self.buffer) < 64:
            return None
        result = BeaconFrameParser().parse(list(self.buffer))
        if result.valid_crc:
            self.parsed_frames += 1
            self._updates_since_ok = 0
            drop = max(int(getattr(result, "consumed_bits", 0)), 0)
            for _ in range(min(drop, len(self.buffer))):
                self.buffer.popleft()
            return result
        if result.reason == "CRC_MISMATCH":
            self.crc_failures += 1
        return None


__all__ = [
    "CommReceiver",
    "CommSource",
    "CHIP_DT_S",
    "SUBS_PER_CHIP",
    "SUB_DT_S",
    "BUFFER_CHIPS",
    "ber_from_snr_db",
]

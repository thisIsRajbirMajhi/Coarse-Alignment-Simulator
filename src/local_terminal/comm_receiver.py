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
# 8× (0.125 ms), acquires chip phase by correlating the known 16-bit
# preamble/sync marker across the eight sub-phases (exactly what the marker
# is for), then slices chips on the recovered grid. Mid-grid quantization is
# ≤1/16 chip, immune to float error. Loss of parses triggers re-acquisition.
#
# Simplification (documented): capture effect — the nearest-to-boresight
# emitter dominates. Multi-emitter chip superposition is Stage-4 work.

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field

from src.common.protocol.beacon.frame import BeaconDecodeResult, BeaconFrameParser


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


# Physical photodiode receiver constants (P1/P0 requirements)
Q_ELECTRON: float = 1.602176634e-19
K_BOLTZMANN: float = 1.380649e-23
T_KELVIN: float = 300.0
LOAD_RESISTANCE_OHM: float = 10000.0   # 10 kOhm TIA gain
RX_BANDWIDTH_HZ: float = 10000.0       # 10 kHz bandwidth (1 kHz chip rate)
I_DARK_A: float = 1.0e-9               # 1 nA dark current
RESPONSIVITY_A_W: float = 0.95         # InGaAs PIN responsivity at 1550 nm
FILTER_TRANSMISSION: float = 0.85      # Optical bandpass filter throughput
RX_APERTURE_DIAMETER_M: float = 0.05   # 50 mm collection aperture
RX_APERTURE_AREA_M2: float = 3.141592653589793 * (0.05 / 2.0) ** 2


def ber_from_snr_db(snr_db: float) -> float:
    """OOK bit-error rate from SNR.

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
    pointing_error_deg: float = 0.0
    wavelength_nm: float = 1550.0
    beam_diameter_m: float = 0.0
    range_m: float = 0.0
    atm_transmission: float = 1.0


def compute_photodiode_snr(
    sources: list[CommSource],
    boresight: tuple[float, float],
    rx_fov_radius_px: float = 320.0,
) -> tuple[float, float, float]:
    """Compute electrical SNR (dB), BER, and received optical power (W) on the photodiode.

    Returns:
        (snr_pd_db, ber, p_rx_high_w)
    """
    import math

    # Find dominant emitting source near boresight
    best_src = None
    best_d2 = None
    for src in sources:
        if not src.emitting:
            continue
        dx = float(src.position[0]) - float(boresight[0])
        dy = float(src.position[1]) - float(boresight[1])
        d2 = dx * dx + dy * dy
        if best_src is None or d2 < best_d2:
            best_src = src
            best_d2 = d2

    if best_src is None or best_src.power_w <= 0.0:
        return (-30.0, 0.5, 0.0)

    # 1. Geometric collection & optical channel
    p_tx = float(best_src.power_w)
    r_m = float(best_src.range_m)
    beam_d_m = float(best_src.beam_diameter_m)

    # Aperture collection efficiency
    if r_m > 0.0 and beam_d_m > 0.0:
        beam_area = 3.141592653589793 * (beam_d_m / 2.0) ** 2
        eta_aperture = min(1.0, RX_APERTURE_AREA_M2 / max(beam_area, 1e-9))
    else:
        eta_aperture = 1.0

    # Pointing coupling
    if abs(best_src.pointing_error_deg) > 1e-6 and r_m > 0.0 and beam_d_m > 0.0:
        w = beam_d_m / 2.0
        delta_r = r_m * math.tan(abs(best_src.pointing_error_deg) * math.pi / 180.0)
        eta_pointing = float(math.exp(-2.0 * (delta_r / max(w, 1e-6)) ** 2))
    else:
        eta_pointing = 1.0

    # Diode FOV acceptance (Gaussian roll-off away from boresight)
    dist = math.sqrt(best_d2)
    eta_fov = float(math.exp(-2.0 * (dist / max(rx_fov_radius_px, 1.0)) ** 2))

    # Atmospheric transmission
    eta_atm = float(max(1e-4, min(1.0, getattr(best_src, "atm_transmission", 1.0))))

    # Wavelength responsivity factor
    wl = float(getattr(best_src, "wavelength_nm", 1550.0))
    # Gaussian filter centered at 1550 nm with 50 nm FWHM
    filter_resp = math.exp(-4.0 * math.log(2.0) * ((wl - 1550.0) / 50.0) ** 2) if wl > 0 else 1.0

    # Received optical power for high and low chips (OOK with finite extinction ratio)
    p_rx_high = p_tx * eta_pointing * eta_aperture * eta_atm * FILTER_TRANSMISSION * filter_resp * eta_fov
    p_rx_low = 0.45 * p_rx_high  # Finite extinction ratio ~3.5 dB

    # 2. Photocurrent conversion
    i_high = RESPONSIVITY_A_W * p_rx_high
    i_low = RESPONSIVITY_A_W * p_rx_low
    delta_i = i_high - i_low

    # 3. Noise model: Shot noise + Thermal noise
    sigma_shot_sq = 2.0 * Q_ELECTRON * (i_high + I_DARK_A) * RX_BANDWIDTH_HZ
    sigma_th_sq = (4.0 * K_BOLTZMANN * T_KELVIN * RX_BANDWIDTH_HZ) / LOAD_RESISTANCE_OHM
    sigma_total = math.sqrt(sigma_shot_sq + sigma_th_sq)

    # 4. Electrical SNR and BER
    snr_pd_lin = (delta_i / max(sigma_total, 1e-18)) ** 2
    snr_pd_db = 10.0 * math.log10(max(snr_pd_lin, 1e-6))

    # Optimal slicing threshold BER: 0.5 * erfc( delta_i / (2 * sqrt(2) * sigma) )
    snr_arg = delta_i / (2.0 * math.sqrt(2.0) * max(sigma_total, 1e-18))
    ber = float(0.5 * math.erfc(snr_arg))
    ber = float(max(0.0, min(0.5, ber)))

    return (snr_pd_db, ber, p_rx_high)


@dataclass
class CommReceiver:
    """Oversampling photodiode + clock recovery + frame synchroniser."""

    buffer: deque = field(default_factory=lambda: deque(maxlen=BUFFER_CHIPS))
    parsed_frames: int = 0
    crc_failures: int = 0
    last_snr_pd_db: float = 0.0
    last_ber: float = 0.0
    last_p_rx_w: float = 0.0

    def __post_init__(self) -> None:
        self._sub: deque = deque(maxlen=SUB_BUFFER_MAX)
        self._phase: int | None = None
        self._updates_since_ok = 0
        self._next_t: float | None = None
        self.latest = None
        self._last_t: float = 0.0
        self._last_crc_failed: bool = False

    def reset(self) -> None:
        self.buffer.clear()
        self.parsed_frames = 0
        self.crc_failures = 0
        self.last_snr_pd_db = 0.0
        self.last_ber = 0.0
        self.last_p_rx_w = 0.0
        self._sub.clear()
        self._phase = None
        self._updates_since_ok = 0
        self._next_t = None
        self.latest = None
        self._last_crc_failed = False

    @property
    def aligned(self) -> bool:
        return self._phase is not None

    def update(self, sources: list[CommSource], boresight: tuple[float, float],
               sim_time_s: float, dt: float, ber: float | None = None, rng=None) -> None:
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

        # Derive physical BER if not explicitly provided
        if ber is not None:
            effective_ber = float(ber)
            self.last_ber = effective_ber
        else:
            snr_db, calc_ber, p_rx = compute_photodiode_snr(sources, boresight)
            self.last_snr_pd_db = snr_db
            self.last_ber = calc_ber
            self.last_p_rx_w = p_rx
            effective_ber = calc_ber

        if self._phase is None:
            self._acquire_phase()
        if self._phase is not None:
            self._slice_chips(float(effective_ber), rng)
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
            try:
                self.latest = decode_to_observation(
                    result, self.last_p_rx_w, self.last_snr_pd_db,
                    getattr(self, "_last_t", 0.0),
                )
            except Exception:
                pass
            return result
        if result.reason == "CRC_MISMATCH":
            self.crc_failures += 1
        return None

    # -- V2 slot-model API (Implementation_plan_V2.md §2.2, §8.3) ---------
    # Single-threaded: decoder runs each tick but the camera fast path only
    # reads the latest completed BeaconObservation slot — never blocks on
    # the ~336 ms beacon frame. No threads; deterministic.
    def poll_observation(self, sources: list[CommSource], boresight: tuple[float, float],
                         sim_time_s: float, dt: float, ber: float | None = None,
                         rng=None) -> "BeaconObservation | None":
        """Run one decoder tick and return the latest completed observation.

        Returns the newest valid-CRC BeaconObservation if a frame completed
        this tick, else the previously latched slot (may be None). Always
        advances the `latest` slot attribute for the fast path to read.
        """
        self._last_t = float(sim_time_s)
        crc_before = self.crc_failures
        self.update(sources, boresight, sim_time_s, dt, ber=ber, rng=rng)
        result = self.try_parse()
        crc_failed = self.crc_failures > crc_before
        if result is not None and bool(getattr(result, "valid_crc", False)):
            obs = decode_to_observation(result, self.last_p_rx_w, self.last_snr_pd_db, float(sim_time_s))
            self.latest = obs
            return obs
        # No new frame: expose latched slot + crc flag for identity gating.
        self._last_crc_failed = bool(crc_failed)
        return getattr(self, "latest", None)

    def read_slot(self) -> "BeaconObservation | None":
        """Non-blocking read of the latest completed beacon slot."""
        return getattr(self, "latest", None)


def decode_to_observation(result, p_rx_w: float = 0.0, snr_db: float = 0.0,
                          timestamp_s: float = 0.0) -> "BeaconObservation":
    """Convert a BeaconDecodeResult + photodiode stats into a V2 BeaconObservation."""
    from src.local_terminal.models import BeaconObservation as _BO

    payload = getattr(result, "payload", None)
    tid = str(getattr(payload, "tid", "") or "") if payload is not None else ""
    try:
        seq = int(getattr(payload, "seq", -1)) if payload is not None else None
    except (TypeError, ValueError):
        seq = None
    try:
        wl = float(getattr(payload, "wl", 0.0)) if payload is not None else None
    except (TypeError, ValueError):
        wl = None
    return _BO(
        terminal_id=tid,
        valid_crc=bool(getattr(result, "valid_crc", False)),
        sequence=seq,
        wavelength_nm=wl,
        modulation=None,
        p_rx_w=float(p_rx_w or 0.0),
        snr_db=float(snr_db or 0.0),
        timestamp_s=float(timestamp_s),
    ).validate()


__all__ = [
    "CommReceiver",
    "CommSource",
    "CHIP_DT_S",
    "SUBS_PER_CHIP",
    "SUB_DT_S",
    "BUFFER_CHIPS",
    "ber_from_snr_db",
    "decode_to_observation",
    "compute_photodiode_snr",
]

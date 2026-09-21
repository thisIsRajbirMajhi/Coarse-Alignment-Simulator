# local_terminal/validator.py - Beacon validation lifecycle (Plan.md §5.3-5.5).
#
# Single active-track validator (multi-candidate pools arrive with the Stage 4
# selection manager). Lifecycle: DETECTED→DECODING→SIGNATURE_CHECK→SCORED→
# SELECTED/REJECTED, strike-based blacklist, §5.4 composite score.
#
# Ground-truth isolation: inputs are decoded payloads (TID/seq/wavelength/CRC
# from the comm receiver), photometry (SNR/peak/centroid from the detector),
# and the mission-file registry. Enforcement (dropping invalid tracks,
# blacklist consulted pre-decode) wires up in Stage 4; here the validator
# reports, and only an undecodable-track drop is acted on immediately.

from __future__ import annotations

import math
from dataclasses import dataclass, field

from common.protocol.beacon.navigation import SEQUENCE_MODULUS, sequence_is_newer
from local_terminal.registry import SignatureRegistry


SCORE_MIN: float = 0.60
W_WAVELENGTH: float = 0.30
W_SNR: float = 0.25
W_SEQUENCE: float = 0.20
W_STABILITY: float = 0.15
W_POWER: float = 0.10
STRIKES_TO_BLACKLIST: int = 3
STRIKE_WINDOW_S: float = 30.0
DECODE_TIMEOUT_S: float = 0.672  # 2 beacon periods (§9.2 watchdog)
HISTORY_N: int = 10
UNDECODED_DROPS_TO_ABANDON: int = 3


@dataclass
class ValidationConfig:
    score_min: float = SCORE_MIN
    strikes_to_blacklist: int = STRIKES_TO_BLACKLIST
    strike_window_s: float = STRIKE_WINDOW_S
    decode_timeout_s: float = DECODE_TIMEOUT_S
    history_n: int = HISTORY_N

    def validate(self) -> "ValidationConfig":
        self.score_min = float(min(max(self.score_min, 0.0), 1.0))
        self.strikes_to_blacklist = int(max(1, self.strikes_to_blacklist))
        self.strike_window_s = float(max(1.0, self.strike_window_s))
        self.decode_timeout_s = float(max(0.05, self.decode_timeout_s))
        self.history_n = int(max(2, self.history_n))
        return self


@dataclass
class ValidationSnapshot:
    state: str = "IDLE"  # IDLE|DECODING|SIGNATURE_CHECK|SCORED|SELECTED|REJECTED
    terminal_id: str | None = None
    score: float = 0.0
    validated: bool = False
    strikes: int = 0
    blacklisted: bool = False
    drop_track: bool = False
    reject_reason: str | None = None
    clean_runs: int = 0

    def to_dict(self) -> dict:
        return {
            "state": self.state,
            "terminal_id": self.terminal_id,
            "score": round(float(self.score), 3),
            "validated": bool(self.validated),
            "strikes": int(self.strikes),
            "blacklisted": bool(self.blacklisted),
            "drop_track": bool(self.drop_track),
            "reject_reason": self.reject_reason,
            "clean_runs": int(self.clean_runs),
        }


class TrackValidator:
    """Lifecycle + strikes + scoring for the active photometric track."""

    def __init__(self, registry: SignatureRegistry | None = None,
                 config: ValidationConfig | None = None):
        self.registry = registry or SignatureRegistry()
        self.config = (config or ValidationConfig()).validate()
        self.strikes: dict[str, list[float]] = {}
        self.blacklist: set[str] = set()
        self.last_seq: dict[str, int] = {}
        self.clean_runs: dict[str, int] = {}
        self.reset_track()

    def reset_track(self) -> None:
        """Drop active-track progress (keeps strikes/blacklist/sequence memory)."""
        self.state = "IDLE"
        self.current_tid: str | None = None
        self.score = 0.0
        self.validated = False
        self.drop_track = False
        self.reject_reason: str | None = None
        self.peaks: list[float] = []
        self.centroids: list[tuple[float, float]] = []
        self.decode_deadline: float | None = None
        self.undecoded_windows = 0
        self._now = 0.0

    def set_registry(self, registry: SignatureRegistry) -> None:
        self.registry = registry

    # -- strikes ------------------------------------------------------
    def _prune(self, tid: str, now: float) -> list[float]:
        keep = [t for t in self.strikes.get(tid, []) if now - t <= self.config.strike_window_s]
        self.strikes[tid] = keep
        return keep

    def _strike(self, tid: str, now: float) -> int:
        keep = self._prune(tid, now) + [float(now)]
        self.strikes[tid] = keep
        if len(keep) >= self.config.strikes_to_blacklist:
            self.blacklist.add(tid)
        return len(keep)

    # -- ingest -------------------------------------------------------
    def ingest(self, decode_result, photometry: dict | None, crc_failed: bool,
               sim_time_s: float) -> ValidationSnapshot:
        """Advance the lifecycle one step.

        Args:
            decode_result: BeaconDecodeResult with valid_crc, or None.
            photometry: {snr_db, peak, centroid} from the current detection,
                or None on dark frames.
            crc_failed: a CRC-mismatched frame was observed this step.
            sim_time_s: mission clock for windows/timeouts.
        """
        now = float(sim_time_s)
        self._now = now
        if photometry is not None:
            try:
                self.peaks.append(float(photometry.get("peak", 0.0)))
                c = photometry.get("centroid", (0.0, 0.0))
                self.centroids.append((float(c[0]), float(c[1])))
            except (TypeError, ValueError):
                pass
            del self.peaks[:-self.config.history_n]
            del self.centroids[:-self.config.history_n]

        if self.state == "IDLE":
            self.state = "DECODING"
            self.decode_deadline = now + self.config.decode_timeout_s

        if crc_failed:
            self.undecoded_windows += 1
            if self.undecoded_windows >= UNDECODED_DROPS_TO_ABANDON:
                self.drop_track = True
                self.state = "REJECTED"
                self.reject_reason = "undecodable"
                self.undecoded_windows = 0
                return self.snapshot()
        if decode_result is not None and bool(getattr(decode_result, "valid_crc", False)):
            self.undecoded_windows = 0
            return self._on_decoded(decode_result, photometry, now)
        if self.decode_deadline is not None and now > self.decode_deadline:
            # Watchdog: no decodable frame in time — treat like a CRC failure.
            self.decode_deadline = now + self.config.decode_timeout_s
            self.undecoded_windows += 1
            if self.undecoded_windows >= UNDECODED_DROPS_TO_ABANDON:
                self.drop_track = True
                self.state = "REJECTED"
                self.reject_reason = "decode_timeout"
                self.undecoded_windows = 0
        return self.snapshot()

    def _on_decoded(self, result, photometry: dict | None, now: float) -> ValidationSnapshot:
        payload = getattr(result, "payload", None)
        tid = str(getattr(payload, "tid", "") or "")
        self.current_tid = tid or None
        if not tid:
            return self.snapshot()
        if self.registry.is_self(tid):
            self.state = "REJECTED"
            self.reject_reason = "loopback_self_id"
            self.drop_track = True
            return self.snapshot()
        if tid in self.blacklist:
            self.state = "REJECTED"
            self.reject_reason = "blacklisted"
            self.drop_track = True
            return self.snapshot()
        if not self.registry.is_known(tid):
            # Non-cooperative traffic: ignored, never struck (§3.1).
            self.state = "REJECTED"
            self.reject_reason = "unknown_id"
            self.drop_track = True
            return self.snapshot()
        # Mission-defined signature enforcement (Fixes.md 7.2): required
        # navigation extension must be present when the registry demands it.
        try:
            _entry = self.registry.entries.get(tid)
            _need_nav = bool(getattr(_entry, "require_nav", False))
        except AttributeError:
            _need_nav = False
        if _need_nav and not bytes(getattr(payload, "nav", b"") or b""):
            self._strike(tid, now)
            self._reject(tid, "missing_nav")
            return self.snapshot()
        try:
            seq = int(getattr(payload, "seq", -1)) % SEQUENCE_MODULUS
        except (TypeError, ValueError):
            seq = -1
        wl = float(getattr(payload, "wl", 0.0) or 0.0)
        wl_score = self.registry.wavelength_match_score(tid, wl)
        if wl_score < 0.0:
            n = self._strike(tid, now)
            self._reject(tid, "wavelength_out_of_spec")
            return self.snapshot()
        if seq < 0:
            n = self._strike(tid, now)
            self._reject(tid, "missing_sequence")
            return self.snapshot()
        if tid in self.last_seq and not sequence_is_newer(seq, self.last_seq[tid]):
            self.clean_runs[tid] = 0
            n = self._strike(tid, now)
            self._reject(tid, "stale_sequence")
            return self.snapshot()
        if tid not in self.last_seq:
            # First decoded frame: record, await continuity (§5.3 — sequence
            # must advance across ≥2 frames before SIGNATURE_CHECK passes).
            self.last_seq[tid] = seq
            self.state = "DECODING"
            return self.snapshot()
        self.last_seq[tid] = seq
        self.clean_runs[tid] = min(int(self.clean_runs.get(tid, 0)) + 1, 5)
        self.state = "SIGNATURE_CHECK"
        if photometry is None:
            return self.snapshot()  # decoded on a dark camera frame; await photometry
        self.state = "SCORED"
        self.score = self._score(tid, wl_score, photometry)
        if self.score >= self.config.score_min:
            self.state = "SELECTED"
            self.validated = True
        else:
            n = self._strike(tid, now)
            self._reject(tid, "score_below_minimum")
        return self.snapshot()

    def _reject(self, tid: str, reason: str) -> None:
        self.state = "REJECTED"
        self.reject_reason = reason
        self.validated = False
        if tid in self.blacklist:
            self.drop_track = True

    def _score(self, tid: str, wl_score: float, photometry: dict) -> float:
        try:
            snr = float(photometry.get("snr_db", 0.0))
        except (TypeError, ValueError):
            snr = 0.0
        snr_term = max(0.0, min(1.0, (snr - 6.0) / 12.0))
        seq_term = min(int(self.clean_runs.get(tid, 0)), 5) / 5.0
        if len(self.centroids) >= 2:
            xs = [c[0] for c in self.centroids]
            ys = [c[1] for c in self.centroids]
            var = (sum((v - sum(xs) / len(xs)) ** 2 for v in xs) / len(xs)
                   + sum((v - sum(ys) / len(ys)) ** 2 for v in ys) / len(ys))
            stab_term = 1.0 - min(1.0, var / 25.0)
        else:
            stab_term = 0.5
        exp_peak = photometry.get("expected_peak")
        if exp_peak is not None:
            try:
                curr_peak = float(photometry.get("peak", 0.0))
                power_term = max(0.0, min(1.0, 1.0 - abs(curr_peak - float(exp_peak)) / max(float(exp_peak), 1.0)))
            except (TypeError, ValueError):
                power_term = 0.5
        elif len(self.peaks) >= 2:
            mean = sum(self.peaks) / len(self.peaks)
            std = math.sqrt(sum((p - mean) ** 2 for p in self.peaks) / len(self.peaks))
            power_term = 1.0 - min(1.0, std / max(mean, 1e-6))
        else:
            power_term = 0.5
        return (W_WAVELENGTH * max(0.0, wl_score) + W_SNR * snr_term
                + W_SEQUENCE * seq_term + W_STABILITY * stab_term + W_POWER * power_term)

    def snapshot(self) -> ValidationSnapshot:
        tid = self.current_tid
        strikes = len(self._prune(tid, self._now)) if tid else 0
        return ValidationSnapshot(
            state=self.state,
            terminal_id=tid,
            score=self.score,
            validated=self.validated,
            strikes=strikes,
            blacklisted=bool(tid and tid in self.blacklist),
            drop_track=self.drop_track,
            reject_reason=self.reject_reason,
            clean_runs=int(self.clean_runs.get(tid or "", 0)),
        )


__all__ = [
    "TrackValidator",
    "ValidationConfig",
    "ValidationSnapshot",
    "SCORE_MIN",
]

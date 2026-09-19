# local_terminal/acquisition_mgr.py - Module 7: Acquisition Manager (§§17-18).
#
# Phase-2 upgrade: dual lock required for acquisition.
#   IDENTITY LOCK  — identity_matched == True (decoded ID confirms target)
#   SPATIAL LOCK   — centroid stable, SNR adequate, score above threshold
#
# A track with matching identity but no spatial lock → DECODING / IDENTITY_UNKNOWN
# A track with spatial lock but wrong identity → REJECTED (impostor)
# Acquisition = IDENTITY LOCK + SPATIAL LOCK + persistence confirmation
from __future__ import annotations

from dataclasses import dataclass

from local_terminal.core.models import AcquisitionResult, CandidateTrack
from local_terminal.core.states import CandidateState


@dataclass
class AcquisitionConfig2:
    minimum_signature_score: float = 0.85
    minimum_confirmation_count: int = 3
    confirmation_window: float = 2.0
    maximum_centroid_jump_px: float = 40.0
    minimum_snr_db: float = 8.0
    acquisition_timeout: float = 30.0
    # Phase-2: identity gate
    require_identity_lock: bool = True   # if True, identity gate is active
    require_identity_match: bool = True  # if True, identity_matched must be True to acquire
    expected_terminal_id: str = "RT-001"
    legacy_optical_mode: bool = False

    @classmethod
    def from_detection(cls, det_cfg: object, timeout: float = 30.0) -> AcquisitionConfig2:
        try:
            return cls(minimum_signature_score=float(getattr(det_cfg, "confidence_threshold", 0.85)),
                       minimum_confirmation_count=int(getattr(det_cfg, "code_persistence", 2) or 2),
                       minimum_snr_db=float(getattr(det_cfg, "minimum_snr", 8.0)),
                       acquisition_timeout=float(timeout))
        except Exception:
            return cls()


class AcquisitionManager:
    """Dual-lock confirmation stage between identification and tracking.

    Identity lock:   decoded frame matches TargetProfile  (Phase-2)
    Spatial lock:    centroid stable + SNR + score >= threshold

    Both locks must be active for acquired=True.
    Falls back to optical-only when require_identity_lock=False or
    when no identification_code is configured (wildcard profile).
    """

    def __init__(self, config: AcquisitionConfig2 | None = None):
        self.config = config or AcquisitionConfig2()
        self._confirm_windows: dict[str, list[float]] = {}
        self._prev_centroid: dict[str, tuple[float, float]] = {}

    def select(self, tracks: list[CandidateTrack]) -> CandidateTrack | None:
        """Pick the best candidate from the active track pool.

        Phase-2 priority order:
          1. identity_matched + IDENTIFIED/ACQUIRED/TRACKING (identity-confirmed)
          2. IDENTIFIED/VALIDATING without identity data (optical path)
          3. DECODING / IDENTITY_UNKNOWN (still accumulating)
          4. Others

        Tracks with is_impostor=True are always excluded.
        """
        if not tracks:
            return None

        # Hard-exclude impostors
        eligible = [t for t in tracks if not t.is_impostor
                    and t.lifecycle_state not in (CandidateState.REJECTED, CandidateState.EXPIRED,
                                                   CandidateState.LOST)]
        if not eligible:
            return None

        # Tier 1: identity-confirmed tracks
        id_confirmed = [t for t in eligible
                        if t.identity_matched
                        and t.lifecycle_state in (
                            CandidateState.IDENTIFIED, CandidateState.SELECTED,
                            CandidateState.ACQUIRED, CandidateState.TRACKING,
                            CandidateState.DEGRADED, CandidateState.REACQUIRING)]
        # Tier 2: optical-only identified (no identity data / wildcard)
        opt_identified = [t for t in eligible
                          if not t.identity_matched
                          and t.lifecycle_state in (
                              CandidateState.IDENTIFIED, CandidateState.SELECTED,
                              CandidateState.ACQUIRED, CandidateState.TRACKING,
                              CandidateState.DEGRADED, CandidateState.REACQUIRING)]
        # Tier 3: still decoding
        decoding = [t for t in eligible
                    if t.lifecycle_state in (
                        CandidateState.DECODING, CandidateState.IDENTITY_UNKNOWN,
                        CandidateState.SIGNAL_DETECTED)]

        pool = id_confirmed or opt_identified or decoding
        if not pool:
            # Fall back to any alive candidate
            pool = [t for t in eligible if t.lifecycle_state in (
                CandidateState.VALIDATING, CandidateState.TENTATIVE)]
        if not pool:
            return None

        def key(t: CandidateTrack) -> tuple:
            persist = min(1.0, t.hit_count / 10.0)
            uncert = 1.0 / (1.0 + max(0.0, t.uncertainty))
            id_bonus = 0.30 if t.identity_matched else 0.0
            return (t.signature.overall_score * 0.55 + persist * 0.15
                    + min(1.0, t.meas_snr / 20.0) * 0.05 + uncert * 0.10
                    + id_bonus + t.signal_state.decode_confidence * 0.15,
                    t.hit_count, -t.miss_count)

        pool.sort(key=key, reverse=True)
        return pool[0]

    def confirm(self, track: CandidateTrack | None, timestamp: float) -> AcquisitionResult:
        """Evaluate dual lock and update confirmation window.

        Returns acquired=True only when IDENTITY LOCK + SPATIAL LOCK are both active
        and the sliding confirmation window exceeds the threshold.
        """
        if track is None:
            return AcquisitionResult(acquired=False, timestamp=float(timestamp))

        # ── Spatial lock gates ────────────────────────────────────────────
        ok_score = track.signature.overall_score >= self.config.minimum_signature_score
        ok_snr   = track.meas_snr >= self.config.minimum_snr_db

        # Centroid jump gate (was previously config-only, now enforced)
        prev = self._prev_centroid.get(track.observation_id)
        centroid_ok = True
        if prev is not None:
            jump = ((track.meas_x - prev[0]) ** 2 + (track.meas_y - prev[1]) ** 2) ** 0.5
            if jump > self.config.maximum_centroid_jump_px:
                centroid_ok = False
        self._prev_centroid[track.observation_id] = (track.meas_x, track.meas_y)

        spatial_lock = ok_score and ok_snr and centroid_ok

        # ── Identity lock gate (§24, §25) ─────────────────────────────────
        if track.is_impostor:
            window = self._confirm_windows.setdefault(track.observation_id, [])
            window.append(-2.0)
            del window[:-32]
            return AcquisitionResult(acquired=False, observation_id=track.observation_id,
                                     confidence=float(track.signature.overall_score),
                                     timestamp=float(timestamp))

        if getattr(self.config, "legacy_optical_mode", False) or not self.config.require_identity_lock:
            id_locked = True
        else:
            id_locked = bool(track.signal_state.identity_matched)

        # ── Confirmation window ───────────────────────────────────────────
        window = self._confirm_windows.setdefault(track.observation_id, [])
        window.append(float(timestamp) if (spatial_lock and id_locked) else -1.0)
        del window[:-32]

        positives = sum(1 for v in window[-int(self.config.minimum_confirmation_count * 5):] if v >= 0)
        acquired = bool(
            positives >= self.config.minimum_confirmation_count
            and track.lifecycle_state in (
                CandidateState.IDENTIFIED, CandidateState.SELECTED,
                CandidateState.ACQUIRED, CandidateState.TRACKING,
                CandidateState.DEGRADED, CandidateState.REACQUIRING)
        )

        if acquired and track.lifecycle_state == CandidateState.IDENTIFIED:
            track.lifecycle_state = CandidateState.SELECTED
        if acquired:
            track.lifecycle_state = CandidateState.ACQUIRED

        return AcquisitionResult(acquired=acquired, observation_id=track.observation_id,
                                 confidence=float(track.signature.overall_score),
                                 timestamp=float(timestamp))

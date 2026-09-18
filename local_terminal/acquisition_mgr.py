# local_terminal/acquisition_mgr.py - Module 7: Acquisition Manager (§§17-18).
from __future__ import annotations

from dataclasses import dataclass

from local_terminal.models import AcquisitionResult, CandidateTrack
from local_terminal.states import CandidateState


@dataclass
class AcquisitionConfig2:
    minimum_signature_score: float = 0.85
    minimum_confirmation_count: int = 3
    confirmation_window: float = 2.0
    maximum_centroid_jump_px: float = 40.0
    minimum_snr_db: float = 8.0
    acquisition_timeout: float = 30.0

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
    """Confirmation stage between identification and tracking.

    Considers overall score, persistence, temporal/spatial consistency,
    SNR, uncertainty — never brightest-only (§17).
    """

    def __init__(self, config: AcquisitionConfig2 | None = None):
        self.config = config or AcquisitionConfig2()
        self._confirm_windows: dict[str, list[float]] = {}

    def select(self, tracks: list[CandidateTrack]) -> CandidateTrack | None:
        if not tracks:
            return None
        # Prefer identified tracks over unidentified ones: a bright
        # unconfirmed decoy must never preempt an identified target (§17).
        identified = [t for t in tracks if t.lifecycle_state in (
            CandidateState.IDENTIFIED, CandidateState.SELECTED, CandidateState.ACQUIRED,
            CandidateState.TRACKING, CandidateState.DEGRADED, CandidateState.REACQUIRING)]
        pool = identified if identified else [t for t in tracks if t.lifecycle_state in (
            CandidateState.VALIDATING, CandidateState.TENTATIVE)]
        if not pool:
            return None
        def key(t: CandidateTrack):
            persist = min(1.0, t.hit_count / 10.0)
            uncert = 1.0 / (1.0 + max(0.0, t.uncertainty))
            # Signature dominates; SNR is a small tiebreak, never primary.
            return (t.signature.overall_score * 0.7 + persist * 0.15
                    + min(1.0, t.meas_snr / 20.0) * 0.05 + uncert * 0.10,
                    t.hit_count, -t.miss_count)
        pool.sort(key=key, reverse=True)
        return pool[0]

    def confirm(self, track: CandidateTrack | None, timestamp: float) -> AcquisitionResult:
        if track is None:
            return AcquisitionResult(acquired=False, timestamp=float(timestamp))
        ok_score = track.signature.overall_score >= self.config.minimum_signature_score
        ok_snr = track.meas_snr >= self.config.minimum_snr_db
        window = self._confirm_windows.setdefault(track.observation_id, [])
        window.append(float(timestamp) if (ok_score and ok_snr) else -1.0)
        del window[:-32]
        # Wide slice (~10 frames at min_count=2) bridges one full AM visual
        # period so envelope minima cannot break an established lock.
        positives = sum(1 for v in window[-int(self.config.minimum_confirmation_count * 5):] if v >= 0)
        # Window-latched: a single below-threshold frame (AM envelope
        # minimum) appends -1 but does not veto while the window still
        # holds enough confirmations. This is the §16 persistence rule:
        # minScore + minConfirmations over multiple observations.
        acquired = bool(positives >= self.config.minimum_confirmation_count
                        and track.lifecycle_state in (CandidateState.IDENTIFIED, CandidateState.SELECTED,
                                                      CandidateState.ACQUIRED, CandidateState.TRACKING,
                                                      CandidateState.DEGRADED, CandidateState.REACQUIRING))
        # First-time promotion: IDENTIFIED + persistence -> SELECTED/ACQUIRED
        if acquired and track.lifecycle_state == CandidateState.IDENTIFIED:
            track.lifecycle_state = CandidateState.SELECTED
        if acquired:
            track.lifecycle_state = CandidateState.ACQUIRED
        return AcquisitionResult(acquired=acquired, observation_id=track.observation_id,
                                 confidence=float(track.signature.overall_score),
                                 timestamp=float(timestamp))

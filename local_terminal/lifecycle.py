# local_terminal/lifecycle.py - Module 6: Candidate Lifecycle Manager (§12).
from __future__ import annotations

from local_terminal.models import CandidateTrack
from local_terminal.states import CandidateState


class CandidateLifecycleManager:
    """Implements SEEN->TENTATIVE->VALIDATING->IDENTIFIED->SELECTED->
    ACQUIRED->TRACKING->DEGRADED->REACQUIRING->TRACKING with exits
    TENTATIVE/VALIDATING->REJECTED, REACQUIRING->LOST, LOST->EXPIRED.
    """

    def __init__(self, tentative_hits: int = 2, expire_misses: int = 45,
                 degrade_below: float = 0.70):
        self.tentative_hits = int(tentative_hits)
        self.expire_misses = int(expire_misses)
        self.degrade_below = float(degrade_below)

    def update_on_hit(self, track: CandidateTrack, signature_ok: bool,
                      score_ok: bool) -> CandidateState:
        st = track.lifecycle_state
        if st == CandidateState.SEEN:
            track.lifecycle_state = (CandidateState.TENTATIVE if track.hit_count >= self.tentative_hits
                                     else CandidateState.SEEN)
        elif st == CandidateState.TENTATIVE:
            track.lifecycle_state = CandidateState.VALIDATING if track.hit_count >= self.tentative_hits else st
        elif st == CandidateState.VALIDATING:
            if signature_ok and score_ok:
                track.confirm_count += 1
                from local_terminal.models import TargetIdentificationSignature  # noqa
                if track.confirm_count >= 1:
                    track.lifecycle_state = CandidateState.IDENTIFIED
            else:
                track.confirm_count = 0
        elif st == CandidateState.IDENTIFIED:
            if signature_ok and score_ok:
                track.confirm_count += 1
            else:
                track.confirm_count = max(0, track.confirm_count - 1)
                if track.confidence < self.degrade_below:
                    track.lifecycle_state = CandidateState.DEGRADED
        elif st in (CandidateState.SELECTED, CandidateState.ACQUIRED, CandidateState.TRACKING):
            if not signature_ok and track.confidence < self.degrade_below:
                track.lifecycle_state = CandidateState.DEGRADED
        elif st == CandidateState.DEGRADED:
            if signature_ok and score_ok:
                track.lifecycle_state = CandidateState.TRACKING
            elif track.miss_count > 5:
                track.lifecycle_state = CandidateState.REACQUIRING
        elif st == CandidateState.REACQUIRING:
            if signature_ok and score_ok:
                track.lifecycle_state = CandidateState.TRACKING
        elif st == CandidateState.LOST:
            # Safety: dead tracks should not absorb hits (association
            # excludes them), but a validated re-observation re-enters
            # recovery rather than lingering dead.
            if signature_ok and score_ok:
                track.miss_count = 0
                track.lifecycle_state = CandidateState.REACQUIRING
        elif st in (CandidateState.REJECTED, CandidateState.EXPIRED):
            pass
        return track.lifecycle_state

    def update_on_miss(self, track: CandidateTrack) -> CandidateState:
        track.miss_count += 1
        if track.lifecycle_state in (CandidateState.SEEN, CandidateState.TENTATIVE, CandidateState.VALIDATING):
            if track.miss_count > 10:
                track.lifecycle_state = CandidateState.REJECTED
        elif track.lifecycle_state in (CandidateState.IDENTIFIED, CandidateState.SELECTED,
                                       CandidateState.ACQUIRED, CandidateState.TRACKING,
                                       CandidateState.DEGRADED):
            # Tolerate brief dropouts (AM minima, single-frame threshold
            # flicker): DEGRADED first, REACQUIRING only after 3 misses.
            if track.miss_count > 3:
                track.lifecycle_state = CandidateState.REACQUIRING
            elif track.lifecycle_state in (CandidateState.TRACKING, CandidateState.ACQUIRED):
                track.lifecycle_state = CandidateState.DEGRADED
        elif track.lifecycle_state == CandidateState.REACQUIRING:
            # The ReacquisitionManager owns the 1.5 s timeout; the lifecycle
            # is a backstop only (longer) so the two do not race.
            if track.miss_count > 60:
                track.lifecycle_state = CandidateState.LOST
        elif track.lifecycle_state == CandidateState.LOST:
            if track.miss_count > 90:
                track.lifecycle_state = CandidateState.EXPIRED
        return track.lifecycle_state

    def reject(self, track: CandidateTrack) -> None:
        track.lifecycle_state = CandidateState.REJECTED

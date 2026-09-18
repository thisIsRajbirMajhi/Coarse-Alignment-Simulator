# local_terminal/lifecycle.py - Module 6: Candidate Lifecycle Manager (§12).
#
# Phase-2 upgrade: identity-aware state transitions.
# New state path:
#   SEEN → TENTATIVE → SIGNAL_DETECTED → DECODING → IDENTITY_UNKNOWN
#                                                     ↓  (identity matched)
#                                                 IDENTIFIED → SELECTED → ACQUIRED → TRACKING
#                                                     ↓  (impostor)
#                                                 REJECTED  (hard, permanent)
#
# The optical-only path (no identification_code / wildcard profile) still
# works: tracks advance through the legacy VALIDATING → IDENTIFIED path.
from __future__ import annotations

from local_terminal.models import CandidateTrack
from local_terminal.states import CandidateState


class CandidateLifecycleManager:
    """Identity-aware lifecycle: SEEN → … → IDENTIFIED → ACQUIRED → TRACKING."""

    def __init__(self, tentative_hits: int = 2, expire_misses: int = 45,
                 degrade_below: float = 0.70):
        self.tentative_hits = int(tentative_hits)
        self.expire_misses = int(expire_misses)
        self.degrade_below = float(degrade_below)

    # -- Phase-2 fast-path: identity-driven transitions -------------------

    def apply_identity_result(self, track: CandidateTrack) -> CandidateState:
        """Called immediately after IdentityMatcher runs on a track.

        Decision rules:
        - is_impostor (ID_MISMATCH / NET_MISMATCH) → REJECTED immediately
        - identity_matched → fast-track to IDENTIFIED (skip VALIDATING)
        - decode in progress → advance through SIGNAL_DETECTED → DECODING
        - no data yet or wildcard profile → leave state to optical path
        """
        ss = track.signal_state
        st = track.lifecycle_state

        # Impostors are immediately and permanently rejected
        if track.is_impostor:
            track.lifecycle_state = CandidateState.REJECTED
            return CandidateState.REJECTED

        # Track already in a post-identification state — do not regress
        if st in (CandidateState.IDENTIFIED, CandidateState.SELECTED,
                  CandidateState.ACQUIRED, CandidateState.TRACKING,
                  CandidateState.DEGRADED, CandidateState.REACQUIRING):
            return st

        reason = ss.identity_reason
        # Wildcard profile (byte=0) or NO_DATA → optical path owns lifecycle
        if reason == "NO_DATA":
            return st

        # A decode was attempted — advance through comm-path states
        if st in (CandidateState.SEEN, CandidateState.TENTATIVE, CandidateState.VALIDATING):
            if ss.num_chip_samples >= 20:
                track.lifecycle_state = CandidateState.SIGNAL_DETECTED
                st = CandidateState.SIGNAL_DETECTED

        if st == CandidateState.SIGNAL_DETECTED and ss.total_attempts > 0:
            track.lifecycle_state = CandidateState.DECODING
            st = CandidateState.DECODING

        if st == CandidateState.DECODING:
            if ss.frame_valid:
                track.lifecycle_state = CandidateState.IDENTITY_UNKNOWN
                st = CandidateState.IDENTITY_UNKNOWN

        if st == CandidateState.IDENTITY_UNKNOWN:
            if ss.identity_matched:
                track.confirm_count += 1
                track.lifecycle_state = CandidateState.IDENTIFIED
                return CandidateState.IDENTIFIED
            # Specific failure reasons that are non-fatal (may resolve next frame)
            if reason in ("LOW_CONF", "BUILDING", "REPLAY"):
                pass  # stay IDENTITY_UNKNOWN until match or timeout

        return track.lifecycle_state

    # -- Optical path (unchanged from Phase-1) ----------------------------

    def update_on_hit(self, track: CandidateTrack, signature_ok: bool,
                      score_ok: bool) -> CandidateState:
        """Advance track state on a hit frame.

        Identity match (if available from a non-wildcard profile) takes priority
        over optical scoring.  Falls back to the legacy optical path when the
        profile is a wildcard (expected_terminal_id_byte=0) or no identity data
        has been decoded yet (NO_DATA).
        """
        st = track.lifecycle_state

        # Impostors must never be promoted by optical scoring
        if track.is_impostor or st == CandidateState.REJECTED:
            track.lifecycle_state = CandidateState.REJECTED
            return CandidateState.REJECTED

        # Apply identity result first ONLY when identity data is active
        # (non-NO_DATA reason). Wildcard profile → reason stays NO_DATA → optical path.
        reason = track.signal_state.identity_reason
        has_identity_data = reason != "NO_DATA"
        if has_identity_data:
            new_st = self.apply_identity_result(track)
            if new_st in (CandidateState.REJECTED, CandidateState.IDENTIFIED):
                return new_st
            # If we are still in a comm-path state, optical scoring is
            # supporting evidence only — do not regress the state.
            if new_st in (CandidateState.SIGNAL_DETECTED, CandidateState.DECODING,
                          CandidateState.IDENTITY_UNKNOWN):
                return new_st

        # Legacy optical path (used when identification_code is empty / wildcard
        # or while identity data is still accumulating as NO_DATA)
        if st == CandidateState.SEEN:
            track.lifecycle_state = (CandidateState.TENTATIVE if track.hit_count >= self.tentative_hits
                                     else CandidateState.SEEN)
        elif st == CandidateState.TENTATIVE:
            track.lifecycle_state = CandidateState.VALIDATING if track.hit_count >= self.tentative_hits else st
        elif st == CandidateState.VALIDATING:
            if signature_ok and score_ok:
                track.confirm_count += 1
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
            if signature_ok and score_ok:
                track.miss_count = 0
                track.lifecycle_state = CandidateState.REACQUIRING
        elif st in (CandidateState.REJECTED, CandidateState.EXPIRED):
            pass
        return track.lifecycle_state

    def update_on_miss(self, track: CandidateTrack) -> CandidateState:
        track.miss_count += 1
        early = (CandidateState.SEEN, CandidateState.TENTATIVE, CandidateState.VALIDATING,
                 CandidateState.SIGNAL_DETECTED, CandidateState.DECODING, CandidateState.IDENTITY_UNKNOWN)
        if track.lifecycle_state in early:
            if track.miss_count > 10:
                track.lifecycle_state = CandidateState.REJECTED
        elif track.lifecycle_state in (CandidateState.IDENTIFIED, CandidateState.SELECTED,
                                       CandidateState.ACQUIRED, CandidateState.TRACKING,
                                       CandidateState.DEGRADED):
            if track.miss_count > 3:
                track.lifecycle_state = CandidateState.REACQUIRING
            elif track.lifecycle_state in (CandidateState.TRACKING, CandidateState.ACQUIRED):
                track.lifecycle_state = CandidateState.DEGRADED
        elif track.lifecycle_state == CandidateState.REACQUIRING:
            if track.miss_count > 60:
                track.lifecycle_state = CandidateState.LOST
        elif track.lifecycle_state == CandidateState.LOST:
            if track.miss_count > 90:
                track.lifecycle_state = CandidateState.EXPIRED
        return track.lifecycle_state

    def reject(self, track: CandidateTrack) -> None:
        track.lifecycle_state = CandidateState.REJECTED

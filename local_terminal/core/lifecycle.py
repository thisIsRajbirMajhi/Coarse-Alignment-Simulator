# local_terminal/lifecycle.py - Module 6: Candidate Lifecycle Manager (§12).
#
# Phase-2 upgrade: identity-aware state transitions.
# New state path:
#   SEEN → TENTATIVE → SIGNAL_DETECTED → DECODING → IDENTITY_UNKNOWN
#                                                     ↓  (identity matched)
#                                                 IDENTIFIED → SELECTED → ACQUIRING → ACQUIRED → TRACKING
#                                                     ↓  (impostor)
#                                                 REJECTED  (hard, permanent)
#
# Optical-only path (wildcard profile / legacy optical mode): tracks advance
# TENTATIVE → IDENTIFIED directly on signature/score confirmation.
from __future__ import annotations

import logging
from collections import deque

from local_terminal.core.models import CandidateTrack
from local_terminal.core.states import CandidateState

log = logging.getLogger(__name__)

# Bounded audit trail of recent lifecycle transitions (diagnostics, X3).
_TRANSITION_HISTORY: deque[tuple[str, str, str, str]] = deque(maxlen=256)


def recent_transitions(n: int = 20) -> list[tuple[str, str, str, str]]:
    """Last n (observation_id, old, new, reason) transitions."""
    return list(_TRANSITION_HISTORY)[-max(1, int(n)):]

# Central transition table: every legal lifecycle edge. transition_track()
# warns (and allows) anything outside it so illegal races surface in logs
# instead of silently corrupting state.
_VALID_TRANSITIONS: dict[CandidateState, frozenset[CandidateState]] = {
    CandidateState.SEEN: frozenset({
        CandidateState.TENTATIVE, CandidateState.SIGNAL_DETECTED,
        CandidateState.REJECTED, CandidateState.EXPIRED}),
    CandidateState.TENTATIVE: frozenset({
        CandidateState.VALIDATING, CandidateState.SIGNAL_DETECTED,
        CandidateState.IDENTIFIED, CandidateState.REJECTED, CandidateState.EXPIRED}),
    CandidateState.VALIDATING: frozenset({
        CandidateState.SIGNAL_DETECTED, CandidateState.IDENTIFIED,
        CandidateState.REJECTED, CandidateState.EXPIRED}),
    CandidateState.SIGNAL_DETECTED: frozenset({
        CandidateState.DECODING, CandidateState.IDENTIFIED,
        CandidateState.REJECTED, CandidateState.EXPIRED}),
    CandidateState.DECODING: frozenset({
        CandidateState.IDENTITY_UNKNOWN, CandidateState.IDENTIFIED,
        CandidateState.REJECTED, CandidateState.EXPIRED}),
    CandidateState.IDENTITY_UNKNOWN: frozenset({
        CandidateState.IDENTIFIED, CandidateState.REJECTED, CandidateState.EXPIRED}),
    CandidateState.IDENTIFIED: frozenset({
        CandidateState.SELECTED, CandidateState.ACQUIRING, CandidateState.ACQUIRED,
        CandidateState.DEGRADED, CandidateState.REJECTED, CandidateState.EXPIRED}),
    CandidateState.SELECTED: frozenset({
        CandidateState.ACQUIRING, CandidateState.ACQUIRED,
        CandidateState.DEGRADED, CandidateState.REJECTED, CandidateState.EXPIRED}),
    CandidateState.ACQUIRING: frozenset({
        CandidateState.ACQUIRED, CandidateState.TRACKING,
        CandidateState.DEGRADED, CandidateState.REJECTED, CandidateState.EXPIRED}),
    CandidateState.ACQUIRED: frozenset({
        CandidateState.TRACKING, CandidateState.DEGRADED, CandidateState.REACQUIRING,
        CandidateState.LOST, CandidateState.REJECTED, CandidateState.EXPIRED}),
    CandidateState.TRACKING: frozenset({
        CandidateState.DEGRADED, CandidateState.REACQUIRING,
        CandidateState.LOST, CandidateState.REJECTED, CandidateState.EXPIRED}),
    CandidateState.DEGRADED: frozenset({
        CandidateState.TRACKING, CandidateState.ACQUIRED, CandidateState.REACQUIRING,
        CandidateState.LOST, CandidateState.REJECTED, CandidateState.EXPIRED}),
    CandidateState.REACQUIRING: frozenset({
        CandidateState.TRACKING, CandidateState.ACQUIRED, CandidateState.LOST,
        CandidateState.REJECTED, CandidateState.EXPIRED}),
    CandidateState.LOST: frozenset({
        CandidateState.REACQUIRING,
        CandidateState.REJECTED, CandidateState.EXPIRED}),
    CandidateState.REJECTED: frozenset(),
    CandidateState.EXPIRED: frozenset(),
}


def transition_track(track: CandidateTrack, new_state: CandidateState,
                     reason: str = "") -> CandidateState:
    """Validated lifecycle transition with audit logging.

    Warns on illegal edges (fail-open: still applies so the pipeline cannot
    strand a track). Terminal states REJECTED/EXPIRED never leave.
    """
    try:
        old = track.lifecycle_state
    except AttributeError:
        return new_state
    if old == new_state:
        return old
    if old in (CandidateState.REJECTED, CandidateState.EXPIRED):
        log.warning("LT lifecycle blocked %s -> %s (%s) for %s",
                    old, new_state, reason,
                    getattr(track, "observation_id", "?"))
        return old
    allowed = _VALID_TRANSITIONS.get(old, frozenset())
    if new_state not in allowed:
        log.warning("LT lifecycle illegal %s -> %s (%s) for %s",
                    old, new_state, reason,
                    getattr(track, "observation_id", "?"))
    else:
        log.debug("LT lifecycle %s -> %s (%s) for %s",
                  old, new_state, reason,
                  getattr(track, "observation_id", "?"))
    try:
        _TRANSITION_HISTORY.append(
            (str(getattr(track, "observation_id", "?")), str(old), str(new_state), str(reason)))
    except Exception:
        pass
    track.lifecycle_state = new_state
    return new_state


class CandidateLifecycleManager:
    """Identity-aware lifecycle: SEEN → … → IDENTIFIED → ACQUIRED → TRACKING per Plans/New Upgrades.md §4, §22, §23."""

    def __init__(
        self,
        tentative_hits: int = 2,
        expire_misses: int = 45,
        degrade_below: float = 0.70,
        legacy_optical_identification_enabled: bool = False,
    ):
        self.tentative_hits = int(tentative_hits)
        self.expire_misses = int(expire_misses)
        self.degrade_below = float(degrade_below)
        self.legacy_optical_identification_enabled = bool(legacy_optical_identification_enabled)

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
            return transition_track(track, CandidateState.REJECTED, "impostor")

        # Track already in a post-identification state — do not regress
        if st in (CandidateState.IDENTIFIED, CandidateState.SELECTED,
                  CandidateState.ACQUIRING, CandidateState.ACQUIRED,
                  CandidateState.TRACKING,
                  CandidateState.DEGRADED, CandidateState.REACQUIRING):
            return st

        reason = ss.identity_reason
        # Wildcard profile (byte=0) or NO_DATA → optical path owns lifecycle
        if reason == "NO_DATA":
            return st

        # A decode was attempted — advance through comm-path states
        if st in (CandidateState.SEEN, CandidateState.TENTATIVE, CandidateState.VALIDATING):
            if ss.num_chip_samples >= 20:
                transition_track(track, CandidateState.SIGNAL_DETECTED, "samples")
                st = CandidateState.SIGNAL_DETECTED

        if st == CandidateState.SIGNAL_DETECTED and ss.total_attempts > 0:
            transition_track(track, CandidateState.DECODING, "attempt")
            st = CandidateState.DECODING

        if st == CandidateState.DECODING:
            if ss.frame_valid:
                transition_track(track, CandidateState.IDENTITY_UNKNOWN, "frame")
                st = CandidateState.IDENTITY_UNKNOWN

        if st == CandidateState.IDENTITY_UNKNOWN:
            if ss.identity_matched:
                track.confirm_count += 1
                return transition_track(track, CandidateState.IDENTIFIED, "identity-match")
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
            return transition_track(track, CandidateState.REJECTED, "impostor-hit")

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

        # Legacy optical path (used ONLY when legacy_optical_identification_enabled is explicitly True per §4, §23)
        if st == CandidateState.SEEN:
            transition_track(track, (CandidateState.TENTATIVE if track.hit_count >= self.tentative_hits
                                     else CandidateState.SEEN), "hits")
        elif st == CandidateState.TENTATIVE:
            if track.hit_count >= self.tentative_hits:
                if self.legacy_optical_identification_enabled and signature_ok and score_ok:
                    track.confirm_count += 1
                    transition_track(track, CandidateState.IDENTIFIED, "optical-confirm")
                elif not self.legacy_optical_identification_enabled:
                    transition_track(track, CandidateState.VALIDATING, "validating-optical")
                else:
                    track.confirm_count = 0
                # else: hold TENTATIVE until scores confirm or misses reject
        elif st == CandidateState.VALIDATING:
            if self.legacy_optical_identification_enabled and signature_ok and score_ok:
                track.confirm_count += 1
                if track.confirm_count >= 1:
                    transition_track(track, CandidateState.IDENTIFIED, "optical-confirm")
            else:
                track.confirm_count = 0
        elif st == CandidateState.IDENTIFIED:
            if signature_ok and score_ok:
                track.confirm_count += 1
            else:
                track.confirm_count = max(0, track.confirm_count - 1)
                if track.confidence < self.degrade_below:
                    transition_track(track, CandidateState.DEGRADED, "low-confidence")
        elif st in (CandidateState.SELECTED, CandidateState.ACQUIRING,
                    CandidateState.ACQUIRED, CandidateState.TRACKING):
            if not signature_ok and track.confidence < self.degrade_below:
                transition_track(track, CandidateState.DEGRADED, "low-confidence")
        elif st == CandidateState.DEGRADED:
            if signature_ok and score_ok:
                transition_track(track, CandidateState.TRACKING, "recovered")
            elif track.miss_count > 5:
                transition_track(track, CandidateState.REACQUIRING, "misses")
        elif st == CandidateState.REACQUIRING:
            if signature_ok and score_ok:
                transition_track(track, CandidateState.TRACKING, "recovered")
        elif st == CandidateState.LOST:
            if signature_ok and score_ok:
                track.miss_count = 0
                transition_track(track, CandidateState.REACQUIRING, "re-hit")
        elif st in (CandidateState.REJECTED, CandidateState.EXPIRED):
            pass
        return track.lifecycle_state

    def update_on_miss(self, track: CandidateTrack) -> CandidateState:
        track.miss_count += 1
        early = (CandidateState.SEEN, CandidateState.TENTATIVE, CandidateState.VALIDATING,
                 CandidateState.SIGNAL_DETECTED, CandidateState.DECODING, CandidateState.IDENTITY_UNKNOWN)
        if track.lifecycle_state in early:
            if track.miss_count > 10:
                transition_track(track, CandidateState.REJECTED, "early-misses")
        elif track.lifecycle_state in (CandidateState.IDENTIFIED, CandidateState.SELECTED,
                                       CandidateState.ACQUIRING,
                                       CandidateState.ACQUIRED, CandidateState.TRACKING,
                                       CandidateState.DEGRADED):
            if track.miss_count > 3:
                transition_track(track, CandidateState.REACQUIRING, "misses")
            elif track.lifecycle_state in (CandidateState.TRACKING, CandidateState.ACQUIRED):
                transition_track(track, CandidateState.DEGRADED, "miss")
        elif track.lifecycle_state == CandidateState.REACQUIRING:
            if track.miss_count > 60:
                transition_track(track, CandidateState.LOST, "reacq-misses")
        elif track.lifecycle_state == CandidateState.LOST:
            if track.miss_count > 90:
                transition_track(track, CandidateState.EXPIRED, "lost-misses")
        return track.lifecycle_state

    def reject(self, track: CandidateTrack) -> None:
        transition_track(track, CandidateState.REJECTED, "manual")

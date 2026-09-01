# tracking/state.py - Lock status state machine — orchestrator that delegates to isolated

from __future__ import annotations

from dataclasses import dataclass

from tracking.types import LockStatus  # single source — also re-exported for backward compat

@dataclass
class StateTransition:
    """Record of a state change — for logging/debugging."""
    from_status: LockStatus
    to_status: LockStatus
    reason: str

class LockStateMachine:
    """
    Lock state machine — owns status + hit/miss counters + estimate lifetime.

    Transitions are deterministic given detection presence and counters.
    Separate from smoothing (filter) — state only tracks confidence, not position.
    """

    def __init__(self, miss_limit: int = 5, acquire_hits: int = 3, lost_grace_mult: float = 2.0):
        self.status: LockStatus = LockStatus.SEARCHING
        self.miss_limit: int = int(miss_limit)
        self.acquire_hits: int = int(acquire_hits)
        self.lost_grace_mult: float = float(lost_grace_mult)
        self._consecutive_hits: int = 0
        self._consecutive_misses: int = 0
        # For external estimate management: when to clear estimate
        self.should_clear_estimate: bool = False
        self.last_transition: StateTransition | None = None

    def reset(self) -> None:
        self.status = LockStatus.SEARCHING
        self._consecutive_hits = 0
        self._consecutive_misses = 0
        self.should_clear_estimate = False
        self.last_transition = None

    def update(self, has_detection: bool) -> LockStatus:
        """
        Feed whether this frame had a detection (True) or not (False).

        Delegates to isolated phase handlers:
          - SEARCHING → searching.handler.SearchingHandler
          - ACQUIRED  → acquired.handler.AcquiredHandler
          - TRACKING  → locked.handler.LockedHandler (TRACKING == LOCKED)
          - LOST      → lost.handler.LostHandler
        Fallback inline logic preserved if isolated modules unavailable.

        Returns new status. Side effects: updates hit/miss counters via handlers,
        sets should_clear_estimate when transitioning LOST→SEARCHING.

        Transition table (has_detection):
          SEARCHING + hit → ACQUIRED (hits=1, misses=0)
          SEARCHING + miss → stay SEARCHING
          ACQUIRED + hit → if hits≥acquire_hits → TRACKING else stay ACQUIRED
          ACQUIRED + miss → if misses≥miss_limit → LOST
          TRACKING + hit → stay TRACKING
          TRACKING + miss → if misses≥miss_limit → LOST
          LOST + hit → ACQUIRED (reacquisition)
          LOST + miss → if misses≥miss_limit*grace_mult → SEARCHING (clear)
        """
        prev = self.status
        should_clear = False
        new_status = prev

        # Try delegated isolated handlers (lazy imports avoid circular)
        try:
            if self.status == LockStatus.SEARCHING:
                from searching.handler import SearchingHandler

                new_status, should_clear = SearchingHandler.update(self, bool(has_detection))
            elif self.status == LockStatus.ACQUIRED:
                from acquired.handler import AcquiredHandler

                new_status, should_clear = AcquiredHandler.update(self, bool(has_detection))
            elif self.status == LockStatus.TRACKING:
                from locked.handler import LockedHandler

                new_status, should_clear = LockedHandler.update(self, bool(has_detection))
            elif self.status == LockStatus.LOST:
                from lost.handler import LostHandler

                new_status, should_clear = LostHandler.update(self, bool(has_detection))
            else:
                raise ImportError("unknown status")
        except Exception:
            # Fallback — inline original logic (robust if isolated dirs not yet on path)
            if has_detection:
                self._consecutive_hits += 1
                self._consecutive_misses = 0
                if self.status == LockStatus.SEARCHING:
                    new_status = LockStatus.ACQUIRED
                elif self.status == LockStatus.ACQUIRED:
                    if self._consecutive_hits >= int(self.acquire_hits):
                        new_status = LockStatus.TRACKING
                    else:
                        new_status = LockStatus.ACQUIRED
                elif self.status == LockStatus.LOST:
                    new_status = LockStatus.ACQUIRED
                elif self.status == LockStatus.TRACKING:
                    new_status = LockStatus.TRACKING
            else:
                self._consecutive_hits = 0
                self._consecutive_misses += 1
                if self.status in (LockStatus.ACQUIRED, LockStatus.TRACKING):
                    if self._consecutive_misses >= int(self.miss_limit):
                        new_status = LockStatus.LOST
                elif self.status == LockStatus.LOST:
                    if self._consecutive_misses >= int(self.miss_limit * float(self.lost_grace_mult)):
                        new_status = LockStatus.SEARCHING
                        should_clear = True
                elif self.status == LockStatus.SEARCHING:
                    new_status = LockStatus.SEARCHING

        self.should_clear_estimate = bool(should_clear)
        if new_status != prev:
            self.last_transition = StateTransition(prev, new_status, "hit" if has_detection else "miss")
            self.status = new_status
        return self.status

    @property
    def hits(self) -> int:
        return int(self._consecutive_hits)

    @property
    def misses(self) -> int:
        return int(self._consecutive_misses)

    def set_thresholds(self, miss_limit: int | None = None, acquire_hits: int | None = None, grace_mult: float | None = None) -> None:
        if miss_limit is not None:
            self.miss_limit = int(miss_limit)
        if acquire_hits is not None:
            self.acquire_hits = int(acquire_hits)
        if grace_mult is not None:
            self.lost_grace_mult = float(grace_mult)
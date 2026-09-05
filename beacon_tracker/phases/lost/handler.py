# beacon_tracker/phases/lost/handler.py
# Isolated LOST algorithm — retain estimate, await reacquisition or timeout
# Moved from lost/handler.py; imports updated to beacon_tracker paths

from __future__ import annotations

from common.colors import lock_color_hex
from tracking.types import LockStatus  # tracking/types.py is the canonical single source


class LostHandler:
    """
    LOST-phase handler — loss-of-lock hold.

    - Retains last estimate (Tracker holds it, state machine signals should_clear only after grace).
    - Hit promotes to ACQUIRED (reacquisition probation), not directly LOCKED.
    - Miss increments; after grace → SEARCHING with should_clear=True to discard stale estimate.
    """

    @staticmethod
    def update(machine, has_detection: bool) -> tuple["LockStatus", bool]:
        """
        Handle one frame in LOST.

        Args:
            machine: LockStateMachine
            has_detection: bool

        Returns:
            (new_status, should_clear_estimate)
            - should_clear is True only when LOST→SEARCHING after grace
        """
        should_clear = False
        miss_limit = int(getattr(machine, "miss_limit", 5))
        grace_mult = float(getattr(machine, "lost_grace_mult", 2.0))
        grace_threshold = int(miss_limit * float(grace_mult))

        if has_detection:
            machine._consecutive_hits += 1  # type: ignore[attr-defined]
            machine._consecutive_misses = 0  # type: ignore[attr-defined]
            new_status = LockStatus.ACQUIRED
        else:
            machine._consecutive_hits = 0  # type: ignore[attr-defined]
            machine._consecutive_misses += 1  # type: ignore[attr-defined]
            if int(machine._consecutive_misses) >= grace_threshold:  # type: ignore[attr-defined]
                new_status = LockStatus.SEARCHING
                should_clear = True  # discard stale estimate
            else:
                new_status = LockStatus.LOST

        return new_status, bool(should_clear)

    @staticmethod
    def should_report_estimate() -> bool:
        """LOST still reports last estimate (held) for reacquisition cue."""
        return True

    @staticmethod
    def color() -> str:
        return lock_color_hex("lost")

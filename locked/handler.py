# locked/handler.py - Isolated LOCKED (=TRACKING) algorithm — stable lock, retention

from __future__ import annotations

from common.colors import lock_color_hex
from tracking.types import LockStatus

class LockedHandler:
    """
    LOCKED-phase handler — stable tracking.

    - Reports estimate (filtered) every frame.
    - Counts toward lock retention (perf_log).
    - Misses increment; only after miss_limit → LOST (not immediate).
    - Never clears estimate directly; LOST handles retention then possible clear.
    """

    @staticmethod
    def update(machine, has_detection: bool) -> tuple["LockStatus", bool]:
        """
        Handle one frame in LOCKED (=TRACKING).

        Args:
            machine: LockStateMachine
            has_detection: bool

        Returns:
            (new_status, should_clear) — should_clear always False for LOCKED
        """
        should_clear = False
        miss_limit = int(getattr(machine, "miss_limit", 5))

        if has_detection:
            machine._consecutive_hits += 1  # type: ignore[attr-defined]
            machine._consecutive_misses = 0  # type: ignore[attr-defined]
            new_status = LockStatus.TRACKING
        else:
            machine._consecutive_hits = 0  # type: ignore[attr-defined]
            machine._consecutive_misses += 1  # type: ignore[attr-defined]
            if int(machine._consecutive_misses) >= miss_limit:  # type: ignore[attr-defined]
                new_status = LockStatus.LOST
            else:
                new_status = LockStatus.TRACKING

        return new_status, bool(should_clear)

    @staticmethod
    def should_report_estimate() -> bool:
        return True

    @staticmethod
    def color() -> str:
        return lock_color_hex("tracking")

    @staticmethod
    def is_locked() -> bool:
        """Helper for perf_log — LOCKED counts as locked."""
        return True
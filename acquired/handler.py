# acquired/handler.py - Isolated ACQUIRED algorithm — probation before lock

from __future__ import annotations

from common.colors import lock_color_hex
from tracking.types import LockStatus

class AcquiredHandler:
    """
    ACQUIRED-phase handler — probation before committing to LOCKED/TRACKING.

    Invariant: never clears estimate (should_clear always False) — LOST still
    retains last estimate for reacquisition; only LOST→SEARCHING clears.
    """

    @staticmethod
    def update(machine, has_detection: bool) -> tuple["LockStatus", bool]:
        """
        Handle one frame in ACQUIRED.

        Args:
            machine: LockStateMachine (owns counters, thresholds)
            has_detection: bool

        Returns:
            (new_status, should_clear) — should_clear is always False for ACQUIRED
        """
        should_clear = False
        # Thresholds from machine — single source (TrackerConfig)
        acquire_hits = int(getattr(machine, "acquire_hits", 3))
        miss_limit = int(getattr(machine, "miss_limit", 5))

        if has_detection:
            machine._consecutive_hits += 1  # type: ignore[attr-defined]
            machine._consecutive_misses = 0  # type: ignore[attr-defined]
            if int(machine._consecutive_hits) >= acquire_hits:  # type: ignore[attr-defined]
                new_status = LockStatus.TRACKING
            else:
                new_status = LockStatus.ACQUIRED
        else:
            machine._consecutive_hits = 0  # type: ignore[attr-defined]
            machine._consecutive_misses += 1  # type: ignore[attr-defined]
            if int(machine._consecutive_misses) >= miss_limit:  # type: ignore[attr-defined]
                new_status = LockStatus.LOST
            else:
                new_status = LockStatus.ACQUIRED

        return new_status, bool(should_clear)

    @staticmethod
    def should_report_estimate() -> bool:
        """ACQUIRED does report a provisional estimate (filtered)."""
        return True

    @staticmethod
    def color() -> str:
        return lock_color_hex("acquired")
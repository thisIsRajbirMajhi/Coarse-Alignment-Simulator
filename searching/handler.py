"""
Module: searching.handler
Purpose: Isolated SEARCHING algorithm — no estimate, wait for first hit.
Public API: SearchingHandler
Notes: Stateless per-frame logic. Owns the SEARCHING → ACQUIRED transition
       and the SEARCHING → SEARCHING dwell. No filtering, no memory beyond counters.

Maths:
  SEARCHING + hit  → ACQUIRED (hits=1, misses=0)
  SEARCHING + miss → SEARCHING (hits=0, misses+=1, estimate stays None)
       Miss counter increments for diagnostics but does not trigger LOST
       (LOST requires prior lock). Colours: #64748b (gray).

Transition table (isolated):
  Input: has_detection: bool, counters: _consecutive_hits/_consecutive_misses,
         thresholds: none needed for SEARCHING (first hit suffices).
  Output: (new_status: LockStatus, should_clear: bool)
"""

from __future__ import annotations

from common.colors import lock_color_hex
from tracking.types import LockStatus  # single source, no fallback duplication

# ============================================================
# SECTION: SearchingHandler — SEARCHING algorithm
# ============================================================

class SearchingHandler:
    """
    SEARCHING-phase handler — isolated algorithm for idle scan.

    - No estimate is reported (None) — GUI shows SEARCHING badge.
    - First detection is sufficient to promote to ACQUIRED (probation).
    - Misses keep SEARCHING indefinitely (until hit); should_clear is always False
      because there is no estimate to discard in SEARCHING.

    Invariant: should_clear = False always (SEARCHING has no estimate).
    """

    @staticmethod
    def update(machine, has_detection: bool) -> tuple["LockStatus", bool]:
        """
        Handle one frame in SEARCHING.

        Args:
            machine: LockStateMachine (owns counters & status)
            has_detection: bool — whether detector returned a blob this frame

        Returns:
            (new_status, should_clear_estimate)
            - new_status is either SEARCHING or ACQUIRED
            - should_clear is always False for SEARCHING
        """
        should_clear = False
        if has_detection:
            # First hit — seed probation
            machine._consecutive_hits += 1  # type: ignore[attr-defined]
            machine._consecutive_misses = 0  # type: ignore[attr-defined]
            new_status = LockStatus.ACQUIRED
        else:
            # Remain in SEARCHING — increment miss for diagnostics, zero hits
            machine._consecutive_hits = 0  # type: ignore[attr-defined]
            machine._consecutive_misses += 1  # type: ignore[attr-defined]
            new_status = LockStatus.SEARCHING

        return new_status, bool(should_clear)

    @staticmethod
    def should_report_estimate() -> bool:
        """SEARCHING never reports an estimate (stateless)."""
        return False

    @staticmethod
    def color() -> str:
        return lock_color_hex("searching")

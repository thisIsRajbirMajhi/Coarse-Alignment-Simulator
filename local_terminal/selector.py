# local_terminal/selector.py - Target Selection & Standby Pool (Plan.md §6).
#
# Phase 3 Target Selection:
# - selected = argmax(score) over SCORED candidates (score >= 0.60).
# - Tie within 0.05 -> higher sequence-continuity wins.
# - Non-selected SCORED candidates enter the standby pool as re-acquisition alternates.
# - Empty pool after a full cycle -> autonomy supervisor decides (§8.3).

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Sequence

from local_terminal.validator import SCORE_MIN, ValidationSnapshot


@dataclass
class StandbyCandidate:
    """A scored alternate target maintained in the standby pool."""

    snapshot: ValidationSnapshot
    fov_x: float
    fov_y: float
    timestamp_s: float
    score: float = 0.0
    world_x: float = 0.0
    world_y: float = 0.0

    def to_dict(self) -> dict:
        return {
            "terminal_id": self.snapshot.terminal_id,
            "score": round(float(self.score), 3),
            "fov_x": round(float(self.fov_x), 1),
            "fov_y": round(float(self.fov_y), 1),
            "world_x": round(float(self.world_x), 1),
            "world_y": round(float(self.world_y), 1),
            "timestamp_s": round(float(self.timestamp_s), 3),
        }


class StandbyPool:
    """Maintains scored alternate candidates for fast re-acquisition (Plan.md §6, §8.2)."""

    def __init__(self, max_age_s: float = 10.0, max_size: int = 8):
        self.max_age_s = float(max_age_s)
        self.max_size = int(max_size)
        self._pool: dict[str, StandbyCandidate] = {}

    def clear(self) -> None:
        self._pool.clear()

    def update(self, alternates: Sequence[StandbyCandidate], now_s: float, blacklist: set[str] | None = None) -> None:
        """Add or update alternates, pruning expired or blacklisted entries."""
        bl = blacklist or set()
        for cand in alternates:
            tid = cand.snapshot.terminal_id
            if tid and tid not in bl and cand.score >= SCORE_MIN:
                self._pool[tid] = cand

        # Prune expired and blacklisted
        self.prune(now_s, bl)

    def prune(self, now_s: float, blacklist: set[str] | None = None) -> None:
        bl = blacklist or set()
        expired = [
            tid
            for tid, c in self._pool.items()
            if (now_s - c.timestamp_s > self.max_age_s) or (tid in bl)
        ]
        for tid in expired:
            del self._pool[tid]

        # Keep top max_size by score
        if len(self._pool) > self.max_size:
            sorted_items = sorted(self._pool.items(), key=lambda item: item[1].score, reverse=True)
            self._pool = dict(sorted_items[: self.max_size])

    def get_best(self) -> StandbyCandidate | None:
        """Return highest-scoring available candidate."""
        if not self._pool:
            return None
        return max(self._pool.values(), key=lambda c: (c.score, c.snapshot.clean_runs))

    def pop_best(self) -> StandbyCandidate | None:
        best = self.get_best()
        if best and best.snapshot.terminal_id:
            del self._pool[best.snapshot.terminal_id]
        return best

    def all_candidates(self) -> list[StandbyCandidate]:
        return sorted(self._pool.values(), key=lambda c: c.score, reverse=True)

    def __len__(self) -> int:
        return len(self._pool)


class TargetSelector:
    """Phase 3 Target Selection per Plan.md §6."""

    def __init__(self, score_min: float = SCORE_MIN):
        self.score_min = float(score_min)
        self.standby_pool = StandbyPool()

    def select(
        self,
        candidates: Sequence[tuple[ValidationSnapshot, tuple[float, float]] | tuple[ValidationSnapshot, tuple[float, float], tuple[float, float]]],
        now_s: float,
        blacklist: set[str] | None = None,
    ) -> tuple[ValidationSnapshot | None, tuple[float, float] | None]:
        """Select best candidate from scored list.

        Args:
            candidates: list of (ValidationSnapshot, (fov_x, fov_y)) or
                        (ValidationSnapshot, (fov_x, fov_y), (world_x, world_y)).
            now_s: current sim time.
            blacklist: current session blacklist.

        Returns:
            (selected_snapshot, (fov_x, fov_y)) or (None, None) if empty pool.
        """
        bl = blacklist or set()
        valid: list[tuple[ValidationSnapshot, tuple[float, float], tuple[float, float]]] = []

        for item in candidates:
            snap = item[0]
            pos = item[1]
            w_pos = item[2] if len(item) > 2 else (0.0, 0.0)
            tid = snap.terminal_id
            if (
                snap.score >= self.score_min
                and snap.state in ("SCORED", "SELECTED")
                and tid
                and tid not in bl
            ):
                valid.append((snap, pos, w_pos))

        if not valid:
            return None, None

        # Sort descending by score
        valid.sort(key=lambda item: item[0].score, reverse=True)
        top_score = valid[0][0].score

        # Tie-break within 0.05: higher sequence-continuity (clean_runs) wins (§6)
        contenders = [item for item in valid if item[0].score >= top_score - 0.05]
        selected = max(contenders, key=lambda item: (item[0].clean_runs, item[0].score))

        # Non-selected enter standby pool (§6)
        alternates = [
            StandbyCandidate(
                snapshot=snap,
                fov_x=pos[0],
                fov_y=pos[1],
                timestamp_s=now_s,
                score=snap.score,
                world_x=w_pos[0],
                world_y=w_pos[1],
            )
            for snap, pos, w_pos in valid
            if snap.terminal_id != selected[0].terminal_id
        ]
        self.standby_pool.update(alternates, now_s, bl)

        return selected[0], selected[1]


__all__ = [
    "StandbyCandidate",
    "StandbyPool",
    "TargetSelector",
]

# local_terminal/scan.py - Search & Scan Controller (Plan.md §4).
#
# Owns: camera pose schedule, visited registry.
# Must never touch: pixel data, validation state (§1.2).
#
# Grid geometry: 2000×2000 scene, 640×480 FOV, 10% overlap, edge-anchored.
# 4 columns × 5 rows = 20 positions.
# Visited registry: 20-bit mask, marked only after dwell completes.

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Sequence


GRID_COLS: int = 4
GRID_ROWS: int = 5
TOTAL_POSITIONS: int = GRID_COLS * GRID_ROWS  # 20
X_STARTS: tuple[int, ...] = (0, 576, 1152, 1360)
Y_STARTS: tuple[int, ...] = (0, 432, 864, 1296, 1520)


@dataclass(frozen=True)
class ScanPosition:
    """One fixed FOV position on the 20-cell scan grid."""

    index: int
    col: int
    row: int
    x_start: int
    y_start: int
    fov_w: int = 640
    fov_h: int = 480

    @property
    def center_x(self) -> float:
        return float(self.x_start + self.fov_w / 2.0)

    @property
    def center_y(self) -> float:
        return float(self.y_start + self.fov_h / 2.0)

    def target_angles(
        self,
        home: tuple[float, float] = (1000.0, 1000.0),
        px_per_deg_h: float = 160.0,
        px_per_deg_v: float = 160.0,
    ) -> tuple[float, float]:
        """Convert FOV center in world px to gimbal (pan_deg, tilt_deg)."""
        pan = (self.center_x - home[0]) / max(px_per_deg_h, 1e-6)
        tilt = (home[1] - self.center_y) / max(px_per_deg_v, 1e-6)
        return float(pan), float(tilt)


def build_grid(fov_w: int = 640, fov_h: int = 480) -> list[ScanPosition]:
    """Build the fixed 20-position grid per Plan.md §4.1."""
    positions: list[ScanPosition] = []
    idx = 0
    for r, y0 in enumerate(Y_STARTS):
        for c, x0 in enumerate(X_STARTS):
            positions.append(
                ScanPosition(
                    index=idx,
                    col=c,
                    row=r,
                    x_start=x0,
                    y_start=y0,
                    fov_w=fov_w,
                    fov_h=fov_h,
                )
            )
            idx += 1
    return positions


@dataclass
class ScanConfig:
    """Search and scan configuration (Plan.md §4)."""

    default_dwell_frames: int = 1       # 1 frame for photometry (§4.3)
    decoding_dwell_frames: int = 10     # extends to >=10 on DECODING (§4.3)
    pattern: str = "RASTER"             # RASTER, SPIRAL, SECTOR (§4.2)
    world_w: int = 2000
    world_h: int = 2000
    fov_w: int = 640
    fov_h: int = 480

    def validate(self) -> "ScanConfig":
        self.default_dwell_frames = int(max(1, self.default_dwell_frames))
        self.decoding_dwell_frames = int(max(self.default_dwell_frames, self.decoding_dwell_frames))
        self.pattern = str(self.pattern).upper()
        if self.pattern not in {"RASTER", "SPIRAL", "SECTOR"}:
            self.pattern = "RASTER"
        return self


class ScanController:
    """Scan grid scheduler and visited registry manager (Plan.md §4)."""

    def __init__(self, config: ScanConfig | None = None):
        self.config = (config or ScanConfig()).validate()
        self.grid: list[ScanPosition] = build_grid(self.config.fov_w, self.config.fov_h)
        self.visited_mask: int = 0  # 20-bit mask
        self._schedule: list[int] = list(range(TOTAL_POSITIONS))
        self._schedule_ptr: int = 0
        self._dwell_count: int = 0
        self._required_dwell: int = self.config.default_dwell_frames
        self.cycle_count: int = 0
        self.cycle_completed: bool = False

    def reset(self, clear_visited: bool = True) -> None:
        """Reset scan progress."""
        if clear_visited:
            self.visited_mask = 0
        self._schedule_ptr = 0
        self._dwell_count = 0
        self._required_dwell = self.config.default_dwell_frames
        self.cycle_completed = False

    @property
    def current_position(self) -> ScanPosition:
        """Current target scan position."""
        if not self._schedule:
            return self.grid[0]
        pos_idx = self._schedule[min(self._schedule_ptr, len(self._schedule) - 1)]
        return self.grid[pos_idx]

    @property
    def is_visited(self) -> bool:
        """Whether current position is marked visited."""
        pos = self.current_position
        return bool((self.visited_mask >> pos.index) & 1)

    @property
    def all_visited(self) -> bool:
        return self.visited_mask == (1 << TOTAL_POSITIONS) - 1

    @property
    def visited_count(self) -> int:
        return bin(self.visited_mask).count("1")

    # -- Priority Scheduling (§4.2) -----------------------------------
    def plan_schedule(
        self,
        priority_mode: str = "SYSTEMATIC",
        last_known: tuple[float, float] | None = None,
        velocity: tuple[float, float] | None = None,
    ) -> list[int]:
        """Compute execution order for the 20 positions.

        Priority modes (§4.2):
        1. 'LAST_KNOWN': 3×3 FOV patch around last_known, then remaining.
        2. 'PREDICTED': sector along predicted velocity, then remaining.
        3. 'SYSTEMATIC': raster / spiral / sector sweep.
        """
        all_indices = list(range(TOTAL_POSITIONS))

        if priority_mode == "LAST_KNOWN" and last_known is not None:
            lx, ly = float(last_known[0]), float(last_known[1])
            # 3×3 FOV patch centered on last position
            patch_half_w = 1.5 * self.config.fov_w
            patch_half_h = 1.5 * self.config.fov_h
            in_patch = []
            outside = []
            for p in self.grid:
                if (abs(p.center_x - lx) <= patch_half_w and
                        abs(p.center_y - ly) <= patch_half_h):
                    in_patch.append(p.index)
                else:
                    outside.append(p.index)
            # Sort in-patch by distance to last_known
            in_patch.sort(key=lambda i: (self.grid[i].center_x - lx) ** 2 + (self.grid[i].center_y - ly) ** 2)
            self._schedule = in_patch + outside

        elif priority_mode == "PREDICTED" and last_known is not None and velocity is not None:
            lx, ly = float(last_known[0]), float(last_known[1])
            vx, vy = float(velocity[0]), float(velocity[1])
            v_norm = math.hypot(vx, vy)
            if v_norm > 1e-3:
                # Sort positions by alignment with velocity vector from last_known
                def _score(i: int) -> float:
                    dx = self.grid[i].center_x - lx
                    dy = self.grid[i].center_y - ly
                    d = math.hypot(dx, dy)
                    if d < 1e-3:
                        return 10.0  # at current location
                    dot = (dx * vx + dy * vy) / (d * v_norm)
                    return dot - d / 2000.0  # reward forward sector, penalize distance
                all_indices.sort(key=_score, reverse=True)
                self._schedule = all_indices
            else:
                self._schedule = self._systematic_schedule()
        else:
            self._schedule = self._systematic_schedule()

        self._schedule_ptr = 0
        self._dwell_count = 0
        self._required_dwell = self.config.default_dwell_frames
        return list(self._schedule)

    def _systematic_schedule(self) -> list[int]:
        if self.config.pattern == "SPIRAL":
            # Center-out spiral order over 4 cols × 5 rows (center around col 1.5, row 2)
            indices = list(range(TOTAL_POSITIONS))
            cx, cy = 1.5, 2.0
            indices.sort(key=lambda i: (self.grid[i].col - cx) ** 2 + (self.grid[i].row - cy) ** 2)
            return indices
        # Default RASTER: row-major 0..19
        return list(range(TOTAL_POSITIONS))

    # -- Step & Dwell (§4.3) -------------------------------------------
    def step(self, has_decoding_candidate: bool = False) -> ScanPosition:
        """Advance scan state by one camera frame.

        Args:
            has_decoding_candidate: if True, extends dwell to >= 10 frames
                to allow observing a full 336 ms beacon frame (§4.3).

        Returns:
            The active ScanPosition for this frame.
        """
        self.cycle_completed = False

        if has_decoding_candidate:
            self._required_dwell = max(self._required_dwell, self.config.decoding_dwell_frames)

        self._dwell_count += 1

        if self._dwell_count >= self._required_dwell:
            # Dwell completed: mark visited (§4.1)
            pos = self.current_position
            self.visited_mask |= (1 << pos.index)

            # Check if all positions visited
            if self.all_visited or self._schedule_ptr >= len(self._schedule) - 1:
                self.cycle_completed = True
                self.cycle_count += 1
                # Cycle resets schedule pointer and visited mask for continuous scan
                self._schedule_ptr = 0
                self.visited_mask = 0
            else:
                self._schedule_ptr += 1

            self._dwell_count = 0
            self._required_dwell = self.config.default_dwell_frames

        return self.current_position

    def telemetry(self) -> dict:
        pos = self.current_position
        return {
            "current_index": pos.index,
            "col": pos.col,
            "row": pos.row,
            "center_x": pos.center_x,
            "center_y": pos.center_y,
            "visited_count": self.visited_count,
            "total_positions": TOTAL_POSITIONS,
            "visited_mask": self.visited_mask,
            "dwell_count": self._dwell_count,
            "required_dwell": self._required_dwell,
            "cycle_count": self.cycle_count,
            "cycle_completed": self.cycle_completed,
        }


__all__ = [
    "ScanConfig",
    "ScanPosition",
    "ScanController",
    "build_grid",
    "GRID_COLS",
    "GRID_ROWS",
    "TOTAL_POSITIONS",
    "X_STARTS",
    "Y_STARTS",
]

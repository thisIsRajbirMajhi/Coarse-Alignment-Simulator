# evaluation/ground_truth.py - Keep ground truth isolated from control path.
# No GT is fed to tracker/detector; this module is for post-hoc scoring only.
# Error formula per spec: error_t = hypot(est_x - gt_x, est_y - gt_y) in pixels (FOV frame).
from __future__ import annotations

import math
from dataclasses import dataclass, asdict
from typing import Any


def compute_error_px(est_x: float | None, est_y: float | None,
                     gt_x: float | None, gt_y: float | None) -> float | None:
    """Spec error: error_t = hypot(est - gt) in pixel space. Returns None if any input is None/NaN."""
    if est_x is None or est_y is None or gt_x is None or gt_y is None:
        return None
    try:
        ex, ey, gx, gy = float(est_x), float(est_y), float(gt_x), float(gt_y)
        if any(math.isnan(v) for v in (ex, ey, gx, gy)) or any(math.isinf(v) for v in (ex, ey, gx, gy)):
            return None
        return float(math.hypot(ex - gx, ey - gy))
    except (TypeError, ValueError):
        return None


@dataclass
class GroundTruthFrame:
    """GT for a single frame — kept separate from any control input."""
    frame_index: int
    timestamp_s: float
    x: float
    y: float
    # Optional: world coords if needed, but FOV px is primary scoring space
    world_x: float | None = None
    world_y: float | None = None
    visible: bool = True  # whether beacon in FOV / emitting

    def to_dict(self) -> dict:
        return asdict(self)


class GroundTruthLog:
    """Thin append-only store for GT frames; never passed to autonomy.

    Usage:
        gt = GroundTruthLog()
        gt.add(frame_index=0, timestamp_s=0.0, x=320, y=240)
        err = gt.error_for(est_x=325, est_y=242, frame_index=0)
    """
    def __init__(self) -> None:
        self._frames: dict[int, GroundTruthFrame] = {}
        self._ordered: list[GroundTruthFrame] = []

    def add(self, frame_index: int, timestamp_s: float, x: float, y: float,
            world_x: float | None = None, world_y: float | None = None,
            visible: bool = True) -> None:
        f = GroundTruthFrame(int(frame_index), float(timestamp_s), float(x), float(y),
                             world_x=None if world_x is None else float(world_x),
                             world_y=None if world_y is None else float(world_y),
                             visible=bool(visible))
        self._frames[int(frame_index)] = f
        self._ordered.append(f)

    def get(self, frame_index: int) -> GroundTruthFrame | None:
        return self._frames.get(int(frame_index))

    def error_for(self, est_x: float | None, est_y: float | None,
                  frame_index: int) -> float | None:
        gt = self.get(frame_index)
        if gt is None or gt.visible is False:
            return None
        return compute_error_px(est_x, est_y, gt.x, gt.y)

    def all_frames(self) -> list[GroundTruthFrame]:
        return list(self._ordered)

    def to_list(self) -> list[dict]:
        return [f.to_dict() for f in self._ordered]

    # Helper to extract GT from src.simulation truth without leaking into control path.
    @staticmethod
    def extract_from_simulation(sim: Any, fov_center: tuple[float, float] | None = None,
                                fov_size: tuple[int, int] = (640, 480)) -> tuple[float | None, float | None, bool]:
        """Best-effort GT extraction for scoring.

        Tries in order:
          1) packet ground_truth if benchmark video (sim._video_source packet GT mapped to FOV centre proxy)
          2) remote terminals telemetry world pos -> FOV px via boresight (disturbed center)
        Returns (gt_x, gt_y, visible). gt_x/y are FOV pixel coords or None if not determinable.
        Never call this to feed tracker — scoring only.
        """
        # 1) try benchmark packet GT proxy already in FOV px (if sim exposes)
        # Caller should provide GT directly when available; this is a fallback.
        try:
            # Try to get first emitting terminal world pos
            terms = getattr(sim, "remote", None)
            if terms is not None and hasattr(terms, "terminals"):
                for term in getattr(terms, "terminals", []):
                    try:
                        rt = term.runtime
                        if not bool(getattr(rt, "effective_emission_enabled", True)):
                            continue
                        wx = float(getattr(term.position_m, "x", 0.0))
                        wy = float(getattr(term.position_m, "y", 0.0))
                        if fov_center is not None:
                            cx, cy = float(fov_center[0]), float(fov_center[1])
                            fw, fh = float(fov_size[0]), float(fov_size[1])
                            # Map world -> FOV pixel (FOV origin = cx - fw/2, cy - fh/2)
                            gx = (wx - (cx - fw / 2.0))
                            gy = (wy - (cy - fh / 2.0))
                            # Visible if inside FOV rect
                            vis = 0 <= gx < fw and 0 <= gy < fh
                            return float(gx), float(gy), bool(vis)
                        else:
                            return float(wx), float(wy), True
                    except Exception:
                        continue
            # Fallback: telemetry dict
            tel = None
            try:
                tel = sim.get_observation() if hasattr(sim, "get_observation") else None
            except Exception:
                tel = None
            if tel and "terminals" in tel:
                # terminals telemetry is dict-ish; take first terminal with position
                t = tel["terminals"]
                if isinstance(t, dict):
                    for v in t.values():
                        if isinstance(v, dict) and "x" in v and "y" in v:
                            return float(v["x"]), float(v["y"]), True
                elif isinstance(t, list) and t:
                    v = t[0]
                    if isinstance(v, dict) and "x" in v:
                        return float(v["x"]), float(v["y"]), True
        except Exception:
            pass
        return None, None, False

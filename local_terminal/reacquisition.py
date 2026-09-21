# local_terminal/reacquisition.py - V2 target-specific reacquisition (Plan V2 §15).
#
# Escalation ladder centred on Kalman predicted position:
#   50 → 100 → 200 → 400 → 800 px → full coarse scan
# No standby-pool stage (§25 excluded).
# Confirmation contract (§15.4):
#   P_rx > thr AND valid CRC AND TID == lost AND spot in expected region.

from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass
class V2ReacqResult:
    reacquired: bool = False
    target_id: str | None = None
    target_pos: tuple[float, float] | None = None
    radius_px: float = 50.0
    full_scan: bool = False
    exhausted: bool = False
    target_angles: tuple[float, float] | None = None


class V2Reacquisition:
    """Minimal V2 recovery search for the lost active target only."""

    def __init__(self, radii=None, full_scan_enabled: bool = True,
                 frames_per_level: int = 10):
        self.radii = [float(r) for r in (radii or [50.0, 100.0, 200.0, 400.0, 800.0])]
        self.full_scan_enabled = bool(full_scan_enabled)
        self.frames_per_level = int(max(1, frames_per_level))
        self.active = False
        self.target_id: str | None = None
        self._level = 0
        self._dwell = 0

    def start(self, target_id: str) -> None:
        self.active = True
        self.target_id = str(target_id)
        self._level = 0
        self._dwell = 0

    def reset(self) -> None:
        self.active = False
        self.target_id = None
        self._level = 0
        self._dwell = 0

    @property
    def radius_px(self) -> float:
        if self._level < len(self.radii):
            return self.radii[self._level]
        return self.radii[-1]

    def update(self, spots, beacon, pred_x: float, pred_y: float,
               p_rx_threshold_w: float = 0.0, scan_ctrl=None,
               cam_home=(1000.0, 1000.0), px_per_deg=(160.0, 160.0)) -> V2ReacqResult:
        """One-frame V2 reacquire step. spots: SpotCandidate[], beacon: BeaconObservation|None."""
        if not self.active or self.target_id is None:
            return V2ReacqResult()
        tid_ok = (beacon is not None and bool(getattr(beacon, "valid_crc", False))
                  and str(getattr(beacon, "terminal_id", "")) == str(self.target_id)
                  and float(getattr(beacon, "p_rx_w", 0.0)) > float(p_rx_threshold_w))
        in_local = self._level < len(self.radii)
        if tid_ok and spots:
            radius = self.radius_px if in_local else 1e9
            for s in spots:
                if math.hypot(float(s.x) - float(pred_x), float(s.y) - float(pred_y)) <= radius:
                    res = V2ReacqResult(True, self.target_id, (float(s.x), float(s.y)),
                                        radius, not in_local, False, None)
                    self.reset()
                    return res
        if in_local:
            radius = self.radius_px
            self._dwell += 1
            if self._dwell >= self.frames_per_level:
                self._dwell = 0
                self._level += 1
            return V2ReacqResult(False, self.target_id, None, radius, False, False, None)
        scan_radius = self.radius_px
        if self.full_scan_enabled and scan_ctrl is not None:
            pos = scan_ctrl.step(has_decoding_candidate=bool(spots))
            angles = pos.target_angles(cam_home, px_per_deg[0], px_per_deg[1])
            if tid_ok and spots:
                best = min(spots, key=lambda s: (s.x - 320.0) ** 2 + (s.y - 240.0) ** 2)
                res = V2ReacqResult(True, self.target_id, (float(best.x), float(best.y)),
                                    scan_radius, True, False, angles)
                self.reset()
                return res
            if getattr(scan_ctrl, "cycle_completed", False):
                return V2ReacqResult(False, self.target_id, None, scan_radius, True, True, angles)
            return V2ReacqResult(False, self.target_id, None, scan_radius, True, False, angles)
        return V2ReacqResult(False, self.target_id, None, self.radius_px, True, True, None)


__all__ = ["V2ReacqResult", "V2Reacquisition"]

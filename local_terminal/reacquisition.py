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
    """Hardened V2 recovery: velocity-aware start radius + 2-frame confirm to kill single-frame S&P/star."""

    def __init__(self, radii=None, full_scan_enabled: bool = True,
                 frames_per_level: int = 10):
        self.radii = [float(r) for r in (radii or [50.0, 100.0, 200.0, 400.0, 800.0])]
        self.full_scan_enabled = bool(full_scan_enabled)
        self.frames_per_level = int(max(1, frames_per_level))
        self.active = False
        self.target_id: str | None = None
        self._level = 0
        self._dwell = 0
        self._confirm_pos: tuple[float,float] | None = None
        self._confirm_tid: str | None = None

    def start(self, target_id: str, velocity_hint: tuple[float,float] | None = None, uncertainty_px: float | None = None) -> None:
        self.active = True
        self.target_id = str(target_id)
        self._level = 0
        self._dwell = 0
        self._confirm_pos = None
        self._confirm_tid = None
        # Velocity-aware jump: fast target after 0.5s needs larger initial radius
        if velocity_hint is not None and uncertainty_px is not None:
            try:
                v = math.hypot(float(velocity_hint[0]), float(velocity_hint[1]))
                unc = float(uncertainty_px)
                # Predicted drift during loss: v * 0.5s + unc; pick first radius covering it
                need = v * 0.5 + unc + 20.0
                for i, r in enumerate(self.radii):
                    if r >= need:
                        self._level = max(0, i)
                        break
                else:
                    self._level = len(self.radii) - 1
            except Exception:
                pass

    def reset(self) -> None:
        self.active = False
        self.target_id = None
        self._level = 0
        self._dwell = 0
        self._confirm_pos = None
        self._confirm_tid = None

    @property
    def radius_px(self) -> float:
        if self._level < len(self.radii):
            return self.radii[self._level]
        return self.radii[-1]

    def update(self, spots, beacon, pred_x: float, pred_y: float,
                p_rx_threshold_w: float = 0.0, scan_ctrl=None,
                cam_home=(1000.0, 1000.0), px_per_deg=(160.0, 160.0)) -> V2ReacqResult:
        """One-frame V2 reacquire step with 2-frame confirmation to eliminate single-frame false (hot pixel/star)."""
        if not self.active or self.target_id is None:
            return V2ReacqResult()
        tid_ok = (beacon is not None and bool(getattr(beacon, "valid_crc", False))
                   and str(getattr(beacon, "terminal_id", "")) == str(self.target_id)
                   and float(getattr(beacon, "p_rx_w", 0.0)) > float(p_rx_threshold_w))
        in_local = self._level < len(self.radii)
        # Helper to test candidate within radius
        def _candidate_in_radius():
            if not (tid_ok and spots):
                return None
            radius = self.radius_px if in_local else 1e9
            best = None
            best_d = 1e9
            for s in spots:
                d = math.hypot(float(s.x) - float(pred_x), float(s.y) - float(pred_y))
                if d <= radius and float(s.snr_db) >= 6.0 and d < best_d:
                    best_d = d
                    best = s
            return best
        cand = _candidate_in_radius()
        # 2-frame confirmation: single S&P / star coincidence will not survive second frame
        if cand is not None:
            pos = (float(cand.x), float(cand.y))
            if self._confirm_pos is not None and self._confirm_tid == str(self.target_id):
                if math.hypot(pos[0]-self._confirm_pos[0], pos[1]-self._confirm_pos[1]) <= 14.0:
                    # Confirmed across 2 frames -> reacquire
                    radius = self.radius_px if in_local else 1e9
                    res = V2ReacqResult(True, self.target_id, pos, radius, not in_local, False, None)
                    self.reset()
                    return res
                else:
                    self._confirm_pos = pos
                    self._confirm_tid = str(self.target_id)
                    # stay one more frame, don't advance level yet
                    return V2ReacqResult(False, self.target_id, None, self.radius_px if in_local else 1e9, False, False, None)
            else:
                self._confirm_pos = pos
                self._confirm_tid = str(self.target_id)
                # High-SNR beacons (>14dB) confirm immediately to keep reacq <=1s (spec)
                if float(cand.snr_db) >= 14.0:
                    radius = self.radius_px if in_local else 1e9
                    res = V2ReacqResult(True, self.target_id, pos, radius, not in_local, False, None)
                    self.reset()
                    return res
                return V2ReacqResult(False, self.target_id, None, self.radius_px if in_local else 1e9, False, False, None)
        else:
            # No candidate this frame: clear pending but keep level dwell
            pass
        if in_local:
            radius = self.radius_px
            self._dwell += 1
            if self._dwell >= self.frames_per_level:
                self._dwell = 0
                self._level += 1
                self._confirm_pos = None  # reset confirm across level
            return V2ReacqResult(False, self.target_id, None, radius, False, False, None)
        scan_radius = self.radius_px
        if self.full_scan_enabled and scan_ctrl is not None:
            pos = scan_ctrl.step(has_decoding_candidate=bool(spots))
            angles = pos.target_angles(cam_home, px_per_deg[0], px_per_deg[1])
            # In full scan, also require 2-frame confirm, but allow boresight-nearest
            if cand is not None:
                # reuse confirm logic: already handled above for local; for full scan, need boresight proximity
                best = min(spots, key=lambda s: (s.x - 320.0) ** 2 + (s.y - 240.0) ** 2)
                # treat as cand
                pos2 = (float(best.x), float(best.y))
                if self._confirm_pos is not None and math.hypot(pos2[0]-self._confirm_pos[0], pos2[1]-self._confirm_pos[1]) <= 14.0:
                    res = V2ReacqResult(True, self.target_id, pos2, scan_radius, True, False, angles)
                    self.reset()
                    return res
                self._confirm_pos = pos2
                return V2ReacqResult(False, self.target_id, None, scan_radius, True, False, angles)
            if getattr(scan_ctrl, "cycle_completed", False):
                return V2ReacqResult(False, self.target_id, None, scan_radius, True, True, angles)
            return V2ReacqResult(False, self.target_id, None, scan_radius, True, False, angles)
        return V2ReacqResult(False, self.target_id, None, self.radius_px, True, True, None)


__all__ = ["V2ReacqResult", "V2Reacquisition"]

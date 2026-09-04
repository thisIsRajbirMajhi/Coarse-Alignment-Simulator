# tracking/signature.py - Beacon photometric signature for ID confirmation
# Learns area/peak after ACQUIRED, then scores detections in TRACKING to reject distractors

from __future__ import annotations

import numpy as np


class BeaconSignature:
    """
    Simple signature: learns avg area and peak from first 3 hits (ACQUIRED),
    then scores detections in TRACKING. Distractors with very different
    photometry (e.g., larger area or dimmer peak due to haze) get penalized.

    Also handles blinking: if peak is 0 (blink off), signature ignores that frame.
    """

    def __init__(self, window: int = 5):
        self.window = int(window)
        self._areas: list[float] = []
        self._peaks: list[float] = []
        self._locked: bool = False
        self._avg_area: float | None = None
        self._avg_peak: float | None = None

    def reset(self) -> None:
        self._areas.clear()
        self._peaks.clear()
        self._locked = False
        self._avg_area = None
        self._avg_peak = None

    def update(self, area: float | None, peak: float | None, is_hit: bool) -> None:
        """
        Call each frame with detection area/peak if has_det else None.
        After window hits, lock signature (avg).
        """
        if not is_hit or area is None or peak is None:
            # don't push misses, but keep locked signature
            return
        # ignore blink-off (peak 0) and tiny noise (<5 area)
        if peak < 10 or area < 3:
            return
        self._areas.append(float(area))
        self._peaks.append(float(peak))
        # keep window
        if len(self._areas) > self.window:
            self._areas.pop(0)
            self._peaks.pop(0)
        if len(self._areas) >= 3 and not self._locked:
            self._locked = True
            self._avg_area = float(np.mean(self._areas))
            self._avg_peak = float(np.mean(self._peaks))
        elif self._locked:
            # slowly adapt (EWMA 0.2) to handle scintillation drift
            try:
                self._avg_area = float(0.8 * self._avg_area + 0.2 * float(area))  # type: ignore
                self._avg_peak = float(0.8 * self._avg_peak + 0.2 * float(peak))  # type: ignore
            except Exception:
                pass

    def score(self, area: float, peak: float) -> float:
        """
        Return 0..1 score (1 = perfect match). If not locked, returns 1 (no penalty).
        Penalizes large deviation from learned avg.
        """
        if not self._locked or self._avg_area is None or self._avg_peak is None:
            return 1.0
        try:
            # area deviation (allow 40% tolerance)
            da = abs(float(area) - float(self._avg_area)) / max(float(self._avg_area), 1.0)
            pa = abs(float(peak) - float(self._avg_peak)) / max(float(self._avg_peak), 1.0)
            # score decays with deviation
            s_area = float(np.exp(- (da / 0.45) ** 2))
            s_peak = float(np.exp(- (pa / 0.35) ** 2))
            return float(0.6 * s_area + 0.4 * s_peak)
        except Exception:
            return 1.0

    def is_locked(self) -> bool:
        return bool(self._locked)

    def get_avg(self) -> tuple[float, float] | None:
        if self._avg_area is None or self._avg_peak is None:
            return None
        return (float(self._avg_area), float(self._avg_peak))

# overlay/renderer.py - Robust crosshair / tracking overlay drawing (modular, intuitive)

import math
import time

import cv2
import numpy as np

from overlay.config import OverlayConfig

class PulseState:
    """
    Tracks lock status transitions and computes pulse progress 0..1.

    When status changes and pulse_enabled, pulse progresses over pulse_duration_ms
    with ease-out. Renderer draws expanding/fading circle or flash.
    """

    def __init__(self):
        self.last_status: str | None = None
        self.pulse_start: float | None = None
        self.pulse_status: str | None = None

    def update(self, current_status: str, pulse_enabled: bool, duration_ms: int) -> float:
        """
        Call each tick with current tracker status.

        Returns pulse progress 0..1 (0 = no pulse, 1 = just triggered, decays to 0).
        Side effect: records transition time if status changed.
        """
        if current_status != self.last_status:
            # Transition — trigger pulse if enabled and not first frame
            if self.last_status is not None and pulse_enabled:
                self.pulse_start = time.time()
                self.pulse_status = current_status
            self.last_status = current_status
        if not pulse_enabled or self.pulse_start is None:
            return 0.0
        elapsed = (time.time() - self.pulse_start) * 1000.0
        dur = max(1, int(duration_ms))
        if elapsed >= dur:
            self.pulse_start = None
            return 0.0
        # Ease-out: 1 -> 0 over duration
        progress = 1.0 - (elapsed / dur)
        # Smoothstep
        progress = progress * progress * (3 - 2 * progress)
        return float(np.clip(progress, 0.0, 1.0))

class OverlayRenderer:
    """
    Stateless overlay drawing — crosshair, lock, error.

    All methods take OverlayConfig and camera pixel_scale for angular units.
    Pulse is driven by PulseState passed in.
    """

    # Crosshair — style/size/gap/thickness/dot

    @staticmethod
    def draw_crosshair(img: np.ndarray, overlay: OverlayConfig, center: tuple[int,int] | None = None) -> None:
        h, w = img.shape[:2]
        cx, cy = center if center is not None else (w//2, h//2)
        cx, cy = int(cx), int(cy)
        size = int(overlay.crosshair_size)
        gap = int(overlay.crosshair_gap)
        thick = int(overlay.crosshair_thickness)
        color = tuple(int(c) for c in overlay.crosshair_color)
        has_cross = overlay.has_cross()
        has_bracket = overlay.has_bracket()
        has_circle = overlay.has_circle()

        # Cross (+) — 4 arms
        if has_cross:
            cv2.line(img, (cx - gap - size, cy), (cx - gap, cy), color, thick, cv2.LINE_AA)
            cv2.line(img, (cx + gap, cy), (cx + gap + size, cy), color, thick, cv2.LINE_AA)
            cv2.line(img, (cx, cy - gap - size), (cx, cy - gap), color, thick, cv2.LINE_AA)
            cv2.line(img, (cx, cy + gap), (cx, cy + gap + size), color, thick, cv2.LINE_AA)

        # Bracket corners — 4 corners, each 2 lines
        if has_bracket:
            margin = 4
            length = max(8, min(w, h)//20)
            # Use crosshair size to scale bracket length slightly
            length = int(length * (0.7 + 0.3 * size/16))
            corners = [
                ((margin, margin), (margin+length, margin), (margin, margin+length)),
                ((w-margin, margin), (w-margin-length, margin), (w-margin, margin+length)),
                ((margin, h-margin), (margin+length, h-margin), (margin, h-margin-length)),
                ((w-margin, h-margin), (w-margin-length, h-margin), (w-margin, h-margin-length)),
            ]
            for (cx0, cy0), (hx, hy), (vx, vy) in corners:
                cv2.line(img, (cx0, cy0), (hx, hy), color, thick, cv2.LINE_AA)
                cv2.line(img, (cx0, cy0), (vx, vy), color, thick, cv2.LINE_AA)

        # Circle — centered ring
        if has_circle:
            radius = gap + size // 2 + 4
            cv2.circle(img, (cx, cy), int(radius), color, thick, cv2.LINE_AA)

        # Centre dot — optional, radius configurable
        if overlay.centre_dot and int(overlay.centre_dot_radius) > 0:
            r = int(overlay.centre_dot_radius)
            cv2.circle(img, (cx, cy), int(r), color, -1, cv2.LINE_AA)
        elif overlay.centre_dot:
            cv2.circle(img, (cx, cy), 1, color, -1, cv2.LINE_AA)

    # Lock circle — around detected beacon, pulse on change

    @staticmethod
    def draw_lock_circle(img: np.ndarray, center: tuple[int,int], overlay: OverlayConfig, status: str, hitbox_radius: int | None = None, pulse_progress: float = 0.0) -> None:
        cx, cy = int(center[0]), int(center[1])
        # Radius: fixed if >0 else hitbox radius
        if int(overlay.lock_circle_radius) > 0:
            radius = int(overlay.lock_circle_radius)
        else:
            # Scale with hitbox if available, else default 14
            radius = int(hitbox_radius) if hitbox_radius is not None else 14
        color = overlay.lock_color(status)
        thick = int(overlay.lock_circle_thickness)
        cv2.circle(img, (cx, cy), int(radius), color, thick, cv2.LINE_AA)
        # Pulse — expanding, fading
        if pulse_progress > 0.0:
            # Expand radius by 6 * progress, fade alpha via thickness/color
            pulse_r = int(radius + 6 * pulse_progress)
            pulse_color = tuple(int(c * (0.5 + 0.5 * pulse_progress)) for c in color)
            pulse_thick = max(1, int(thick + 1 * pulse_progress))
            cv2.circle(img, (cx, cy), int(pulse_r), pulse_color, pulse_thick, cv2.LINE_AA)
            # Also center flash
            flash_r = int(2 + 3 * pulse_progress)
            cv2.circle(img, (cx, cy), int(flash_r), color, -1, cv2.LINE_AA)

    # Error visualization — line + text with units
    @staticmethod
    def draw_error(img: np.ndarray, fov_center: tuple[int,int], estimate: tuple[int,int], overlay: OverlayConfig, status: str, pixel_scale_mrad: float = 0.035) -> None:
        cx, cy = int(fov_center[0]), int(fov_center[1])
        ex, ey = int(estimate[0]), int(estimate[1])
        color = overlay.lock_color(status)
        thick = int(overlay.crosshair_thickness)

        # Error vector line — FOV centre → estimate
        if overlay.show_error_line:
            cv2.line(img, (cx, cy), (ex, ey), color, thick, cv2.LINE_AA)
            # Small arrow head at estimate
            angle = math.atan2(ey - cy, ex - cx)
            arr_len = 6
            for sign in (-1, 1):
                ax = int(ex - arr_len * math.cos(angle + sign * 0.4))
                ay = int(ey - arr_len * math.sin(angle + sign * 0.4))
                cv2.line(img, (ex, ey), (ax, ay), color, thick, cv2.LINE_AA)

        # Error text — near midpoint
        if overlay.show_error_text:
            err_px = math.hypot(ex - cx, ey - cy)
            # Units handling
            units = overlay.error_units.lower()
            if units == "px":
                label = f"{err_px:.1f}px"
            elif units == "mrad":
                mrad = err_px * float(pixel_scale_mrad)
                label = f"{mrad:.3f}mrad"
            elif units == "urad":
                urad = err_px * float(pixel_scale_mrad) * 1000.0
                label = f"{urad:.0f}µrad"
            elif units == "px+mrad":
                mrad = err_px * float(pixel_scale_mrad)
                label = f"{err_px:.0f}px {mrad:.2f}mrad"
            else:
                label = f"{err_px:.1f}px"
            mx, my = (cx + ex)//2 + 3, (cy + ey)//2 - 3
            # Ensure inside image
            h, w = img.shape[:2]
            mx = int(np.clip(mx, 4, w-60))
            my = int(np.clip(my, 12, h-4))
            cv2.putText(img, label, (mx, my), cv2.FONT_HERSHEY_SIMPLEX, overlay.error_text_scale, color, 1, cv2.LINE_AA)
            # Also show status and FOV size
            cv2.putText(img, status.upper(), (6, 12), cv2.FONT_HERSHEY_SIMPLEX, 0.32, color, 1, cv2.LINE_AA)
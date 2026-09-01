"""
Module: gui.core.renderer
Purpose: Viewport, crosshair, and screen rendering for camera FOV + God-view.
Public API: Renderer, CrosshairStyle, ScreenSpec
Notes: Modular, well-commented, stateless. Crosshair and screens are now
       configurable via OverlayConfig (crosshair style/size/gap/thickness/dot,
       lock colors/circle/pulse, error line/text/units) and respect CameraConfig
       pixel→angle. Delegates overlay drawing to overlay.renderer.OverlayRenderer.
"""

import math

import cv2
import numpy as np
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QImage, QPixmap

from tracking.types import LockStatus

from common.colors import LOCK_STATUS_COLORS_BGR, lock_color_bgr

# Optional overlay integration — fallback to legacy if not available
try:
    from overlay.config import OverlayConfig
    from overlay.renderer import OverlayRenderer
except Exception:
    OverlayConfig = None  # type: ignore
    OverlayRenderer = None  # type: ignore

# ============================================================
# SECTION: Crosshair & Screen specs (configurable, legacy)
# ============================================================

class CrosshairStyle:
    """Legacy crosshair spec — kept for backward compat; new code uses OverlayConfig."""
    def __init__(self, gap: int = 10, arm: int = 16, color=(230, 230, 230), thickness: int = 1, show_center_dot: bool = True, show_coords: bool = False):
        self.gap = int(gap); self.arm = int(arm); self.color = color; self.thickness = int(thickness)
        self.show_center_dot = bool(show_center_dot); self.show_coords = bool(show_coords)

class ScreenSpec:
    """On-screen display sizes — independent of FOV sensor resolution."""
    def __init__(self, viewport_w: int = 400, viewport_h: int = 300, god_w: int = 400, god_h: int = 300, keep_aspect: bool = True):
        self.viewport_w = int(viewport_w); self.viewport_h = int(viewport_h)
        self.god_w = int(god_w); self.god_h = int(god_h); self.keep_aspect = bool(keep_aspect)

# ============================================================
# SECTION: Renderer — stateless helpers (now overlay-aware)
# ============================================================

class Renderer:
    """
    Stateless renderer — delegates overlay to OverlayRenderer when OverlayConfig supplied.

    Backward compat: render_viewport(fov_frame, camera, beacons, target, tracker, all_dets)
    still works (uses default crosshair). New: render_viewport(..., overlay, pulse_progress, pixel_scale)
    enables full configurability.
    """

    @staticmethod
    def beacon_vibrant_color(beacon_id: int, brightness: float) -> tuple[int, int, int]:
        b_vals = [0, 30, 60, 90, 120, 150, 180, 210, 15, 45, 105, 135]
        b_base = b_vals[int(beacon_id) % len(b_vals)]
        scale = float(np.clip(brightness / 255.0, 0.7, 1.0))
        b_col = int(b_base * scale); g_col = int(255 * scale); r_col = int(255 * scale)
        g_col = max(g_col, 200); r_col = max(r_col, 200)
        return (int(b_col), int(g_col), int(r_col))

    @staticmethod
    def draw_targets(scene_frame: np.ndarray, beacons, target=None) -> None:
        for beacon in beacons:
            if not getattr(beacon, "enabled", True):
                continue
            x, y = beacon.get_position()
            try: brightness, radius = beacon.get_photometry()
            except: brightness, radius = float(beacon.brightness), float(beacon.radius)
            ix, iy = int(round(x)), int(round(y)); r = int(round(radius))
            vib = Renderer.beacon_vibrant_color(beacon.beacon_id, brightness)
            if r > 3:
                glow = tuple(int(c * 0.55) for c in vib)
                cv2.circle(scene_frame, (ix, iy), r+1, glow, -1, cv2.LINE_AA)
            cv2.circle(scene_frame, (ix, iy), max(1, r), vib, -1, cv2.LINE_AA)
            cv2.circle(scene_frame, (ix, iy), 1, (255, 255, 255), -1, cv2.LINE_AA)

    @staticmethod
    def draw_reticle(img, center, gap=10, arm=16, color=(230, 230, 230), thickness=1, show_dot: bool = True) -> None:
        cx, cy = int(center[0]), int(center[1])
        cv2.line(img, (cx - gap - arm, cy), (cx - gap, cy), color, thickness, cv2.LINE_AA)
        cv2.line(img, (cx + gap, cy), (cx + gap + arm, cy), color, thickness, cv2.LINE_AA)
        cv2.line(img, (cx, cy - gap - arm), (cx, cy - gap), color, thickness, cv2.LINE_AA)
        cv2.line(img, (cx, cy + gap), (cx, cy + gap + arm), color, thickness, cv2.LINE_AA)
        if show_dot:
            cv2.circle(img, (cx, cy), 1, color, -1, cv2.LINE_AA)

    @staticmethod
    def draw_corner_brackets(img, margin=6, length=10, color=(180, 180, 180), thickness=1) -> None:
        h, w = img.shape[:2]
        corners = [
            ((margin, margin), (margin+length, margin), (margin, margin+length)),
            ((w-margin, margin), (w-margin-length, margin), (w-margin, margin+length)),
            ((margin, h-margin), (margin+length, h-margin), (margin, h-margin-length)),
            ((w-margin, h-margin), (w-margin-length, h-margin), (w-margin, h-margin-length)),
        ]
        for (cx, cy), (hx, hy), (vx, vy) in corners:
            cv2.line(img, (cx, cy), (hx, hy), color, thickness, cv2.LINE_AA)
            cv2.line(img, (cx, cy), (vx, vy), color, thickness, cv2.LINE_AA)

    @staticmethod
    def draw_crosshair(img, style: CrosshairStyle | None = None, pan_tilt: tuple[float,float] | None = None) -> None:
        if style is None:
            style = CrosshairStyle()
        h, w = img.shape[:2]; cx, cy = w//2, h//2
        gap = style.gap if style.gap != 10 or w < 200 else max(8, min(w, h)//16)
        arm = style.arm if style.arm != 16 or w < 200 else max(12, min(w, h)//12)
        Renderer.draw_reticle(img, (cx, cy), gap=gap, arm=arm, color=style.color, thickness=style.thickness, show_dot=style.show_center_dot)
        Renderer.draw_corner_brackets(img, margin=4, length=max(8, min(w,h)//20), color=(180, 180, 180), thickness=1)

    # --------------------------------------------------------
    # Viewport — FOV with overlay (crosshair/lock/error) + pulse
    # --------------------------------------------------------

    @staticmethod
    def render_viewport(fov_frame: np.ndarray, camera, beacons, target, tracker, all_dets: list[dict] | None, overlay=None, pulse_progress: float = 0.0, pixel_scale_mrad: float | None = None) -> np.ndarray:
        """
        Render FOV viewport.

        If overlay (OverlayConfig) supplied, uses OverlayRenderer for:
          - Crosshair style/size/gap/thickness/dot
          - Lock circle + pulse
          - Error line/text with units (px/mrad/urad auto)
        Else falls back to legacy rendering (backward compat).
        """
        display = fov_frame.copy()
        h, w = display.shape[:2]
        cx, cy = w // 2, h // 2

        # Resolve overlay and pixel scale
        use_overlay = overlay is not None and OverlayRenderer is not None and OverlayConfig is not None
        if pixel_scale_mrad is None:
            try:
                pixel_scale_mrad = float(getattr(getattr(camera, "config", None), "pixel_scale_mrad", 0.035))
            except:
                pixel_scale_mrad = 0.035

        # Crosshair — overlay-aware
        if use_overlay:
            OverlayRenderer.draw_crosshair(display, overlay, center=(cx, cy))
        else:
            gap = max(8, min(w, h)//16); arm = max(12, min(w, h)//12)
            Renderer.draw_reticle(display, (cx, cy), gap=gap, arm=arm, color=(230, 230, 230), thickness=1)
            Renderer.draw_corner_brackets(display, margin=4, length=max(8, min(w,h)//20), color=(180, 180, 180), thickness=1)

        status = tracker.status
        # Lock colors — single source via common.colors, overlay if present
        if use_overlay:
            base_color = overlay.lock_color(status.value)  # type: ignore
        else:
            # Single source fallback — common BGR map (replaces inline color_map duplication)
            base_color = lock_color_bgr(status.value, default=(170, 170, 170))

        # Beacons — hitbox/center + lock circle with pulse
        fov_x0, fov_y0, _, _ = camera.get_fov_rect()
        for beacon in beacons:
            if not getattr(beacon, "enabled", True):
                continue
            px = beacon.x - fov_x0; py = beacon.y - fov_y0
            if -beacon.hitbox_radius <= px <= w + beacon.hitbox_radius and -beacon.hitbox_radius <= py <= h + beacon.hitbox_radius:
                is_primary = (beacon is target)
                # Lock circle — overlay or legacy
                if use_overlay:
                    # Only for primary or if showing all
                    if is_primary:
                        OverlayRenderer.draw_lock_circle(display, (int(px), int(py)), overlay, status.value, hitbox_radius=int(beacon.hitbox_radius), pulse_progress=float(pulse_progress) if is_primary else 0.0)
                    # Still draw subtle hitbox for distractors
                    col_hit = base_color if is_primary else (160, 180, 120)
                    if not is_primary or int(overlay.lock_circle_radius) != 0:
                        cv2.circle(display, (int(px), int(py)), int(beacon.hitbox_radius), col_hit, 1, cv2.LINE_AA)
                    col_center = (255, 255, 255) if is_primary else (200, 200, 170)
                    cv2.circle(display, (int(px), int(py)), int(beacon.center_radius), col_center, -1, cv2.LINE_AA)
                else:
                    col_hit = (0, 220, 255) if is_primary else (160, 180, 120)
                    cv2.circle(display, (int(px), int(py)), int(beacon.hitbox_radius), col_hit, 1, cv2.LINE_AA)
                    col_center = (255, 255, 255) if is_primary else (200, 200, 170)
                    cv2.circle(display, (int(px), int(py)), int(beacon.center_radius), col_center, -1, cv2.LINE_AA)
                if len(beacons) > 1:
                    cv2.putText(display, f"#{beacon.beacon_id}", (int(px)+beacon.hitbox_radius+2, int(py)-2),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.28, base_color if is_primary else (160,180,120), 1, cv2.LINE_AA)

        # Detections — diamonds
        if all_dets:
            for d in all_dets:
                x, y = int(d["x"]), int(d["y"])
                pts = np.array([[x, y-3],[x+3, y],[x, y+3],[x-3, y]], np.int32)
                cv2.polylines(display, [pts], True, (130, 130, 255), 1, cv2.LINE_AA)

        # Tracker estimate — error line/text + status, via overlay or legacy
        estimate = tracker.estimated_position
        if estimate is not None:
            ex, ey = int(estimate[0]), int(estimate[1])
            if use_overlay:
                OverlayRenderer.draw_error(display, (cx, cy), (ex, ey), overlay, status.value, pixel_scale_mrad=float(pixel_scale_mrad))
                # Also draw estimate box/marker with lock color
                cv2.rectangle(display, (ex-6, ey-6), (ex+6, ey+6), base_color, 1, cv2.LINE_AA)
                cv2.drawMarker(display, (ex, ey), base_color, cv2.MARKER_CROSS, 10, 1, cv2.LINE_AA)
                cv2.putText(display, f"{w}x{h}", (w-44, 12), cv2.FONT_HERSHEY_SIMPLEX, 0.28, (180, 180, 180), 1, cv2.LINE_AA)
            else:
                cv2.rectangle(display, (ex-6, ey-6), (ex+6, ey+6), base_color, 1, cv2.LINE_AA)
                cv2.drawMarker(display, (ex, ey), base_color, cv2.MARKER_CROSS, 10, 1, cv2.LINE_AA)
                cv2.putText(display, status.value.upper(), (6, 12), cv2.FONT_HERSHEY_SIMPLEX, 0.32, base_color, 1, cv2.LINE_AA)
                cv2.putText(display, f"{w}x{h}", (w-44, 12), cv2.FONT_HERSHEY_SIMPLEX, 0.28, (180, 180, 180), 1, cv2.LINE_AA)
                cv2.line(display, (cx, cy), (ex, ey), base_color, 1, cv2.LINE_AA)
                err = math.hypot(ex - cx, ey - cy)
                try:
                    scale = float(pixel_scale_mrad)
                    label = f"{err:.0f}px {err*scale:.2f}mrad"
                except:
                    label = f"{err:.0f}px"
                cv2.putText(display, label, ((cx+ex)//2+3, (cy+ey)//2-3), cv2.FONT_HERSHEY_SIMPLEX, 0.28, base_color, 1, cv2.LINE_AA)
            # Pan/tilt + slew queue
            try:
                pan, tilt = float(camera.pan), float(camera.tilt)
                qlen = int(camera.pending_queue_len()) if hasattr(camera, "pending_queue_len") else 0
                pan_txt = f"pan {pan:.0f} tilt {tilt:.0f}" + (f" q{qlen}" if qlen else "")
                cv2.putText(display, pan_txt, (6, h-8), cv2.FONT_HERSHEY_SIMPLEX, 0.28, (160, 160, 160), 1, cv2.LINE_AA)
            except: pass
        else:
            cv2.putText(display, f"{w}x{h}", (w-44, 12), cv2.FONT_HERSHEY_SIMPLEX, 0.28, (180, 180, 180), 1, cv2.LINE_AA)
            try:
                pan, tilt = float(camera.pan), float(camera.tilt)
                cv2.putText(display, f"pan {pan:.0f} tilt {tilt:.0f}", (6, h-8), cv2.FONT_HERSHEY_SIMPLEX, 0.28, (160, 160, 160), 1, cv2.LINE_AA)
            except: pass
        return display

    @staticmethod
    def render_minimap(scene_frame: np.ndarray, camera, beacons, target, tracker, label_size: tuple[int, int], scene_size: tuple[int,int]) -> np.ndarray:
        lw, lh = label_size; sw, sh = scene_size
        display = cv2.resize(scene_frame, (max(50, lw), max(50, lh)), interpolation=cv2.INTER_LINEAR)
        scale_x, scale_y = display.shape[1] / sw, display.shape[0] / sh
        x0, y0, x1, y1 = camera.get_fov_rect()
        x0s, y0s, x1s, y1s = int(x0*scale_x), int(y0*scale_y), int(x1*scale_x), int(y1*scale_y)
        cv2.rectangle(display, (x0s, y0s), (x1s, y1s), (70, 170, 255), 1, cv2.LINE_AA)
        fcx, fcy = (x0s+x1s)//2, (y0s+y1s)//2
        cv2.line(display, (fcx-5, fcy), (fcx+5, fcy), (70, 170, 255), 1, cv2.LINE_AA)
        cv2.line(display, (fcx, fcy-5), (fcx, fcy+5), (70, 170, 255), 1, cv2.LINE_AA)
        cv2.circle(display, (fcx, fcy), 1, (70, 170, 255), -1, cv2.LINE_AA)
        try:
            hx, hy = camera.get_home()
            hxs, hys = int(hx*scale_x), int(hy*scale_y)
            pts = np.array([[hxs, hys-4],[hxs+4, hys],[hxs, hys+4],[hxs-4, hys]], np.int32)
            cv2.polylines(display, [pts], True, (255, 200, 50), 1, cv2.LINE_AA)
            cv2.putText(display, "H", (hxs+5, hys+2), cv2.FONT_HERSHEY_SIMPLEX, 0.28, (255, 200, 50), 1, cv2.LINE_AA)
        except: pass
        try:
            pan_lo, pan_hi = camera.get_pan_range()
            tilt_lo, tilt_hi = camera.get_tilt_range()
            rx0 = int((pan_lo - camera.fov_width/2)*scale_x); ry0 = int((tilt_lo - camera.fov_height/2)*scale_y)
            rx1 = int((pan_hi + camera.fov_width/2)*scale_x); ry1 = int((tilt_hi + camera.fov_height/2)*scale_y)
            rx0 = max(0, min(rx0, display.shape[1]-1)); rx1 = max(0, min(rx1, display.shape[1]-1))
            ry0 = max(0, min(ry0, display.shape[0]-1)); ry1 = max(0, min(ry1, display.shape[0]-1))
            cv2.rectangle(display, (rx0, ry0), (rx1, ry1), (90, 90, 90), 1, cv2.LINE_AA)
        except: pass
        cv2.putText(display, f"{sw}x{sh}", (4, 10), cv2.FONT_HERSHEY_SIMPLEX, 0.28, (180, 180, 180), 1, cv2.LINE_AA)
        for beacon in beacons:
            if not getattr(beacon, "enabled", True):
                continue
            bx, by = beacon.x, beacon.y
            mx, my = int(bx * scale_x), int(by * scale_y)
            hr_s = max(2, int(beacon.hitbox_radius * min(scale_x, scale_y)))
            cr_s = max(1, int(beacon.center_radius * min(scale_x, scale_y)))
            if hr_s < 3: hr_s = 3
            is_primary = (beacon is target)
            col_hit = (0, 220, 255) if is_primary else (165, 175, 120)
            col_center = (255, 255, 255) if is_primary else (200, 200, 170)
            cv2.circle(display, (mx, my), hr_s, col_hit, 1, cv2.LINE_AA)
            cv2.circle(display, (mx, my), cr_s, col_center, -1, cv2.LINE_AA)
            if len(beacons) > 1:
                cv2.putText(display, f"#{beacon.beacon_id}", (mx+hr_s+2, my-2),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.28, col_hit, 1, cv2.LINE_AA)
        if tracker.estimated_position is not None:
            ex, ey = tracker.estimated_position
            fx0, fy0, _, _ = camera.get_fov_rect()
            mx, my = int((fx0+ex)*scale_x), int((fy0+ey)*scale_y)
            cv2.drawMarker(display, (mx, my), (0, 255, 255), cv2.MARKER_CROSS, 7, 1, cv2.LINE_AA)
            cv2.circle(display, (mx, my), 1, (0, 255, 255), -1, cv2.LINE_AA)
        return display

    @staticmethod
    def set_pixmap(label, bgr_frame: np.ndarray, spec=None) -> np.ndarray:
        rgb = cv2.cvtColor(bgr_frame, cv2.COLOR_BGR2RGB)
        h, w, ch = rgb.shape
        qimg = QImage(rgb.data, w, h, ch*w, QImage.Format_RGB888)
        qimg = qimg.copy()
        pixmap = QPixmap.fromImage(qimg).scaled(label.width(), label.height(), Qt.KeepAspectRatio, Qt.SmoothTransformation)
        label.setPixmap(pixmap)
        return rgb

    @staticmethod
    def apply_screen_sizes(viewport_label, minimap_label, spec) -> None:
        viewport_label.setMinimumSize(max(200, min(spec.viewport_w, 900)), max(140, min(spec.viewport_h, 700)))
        minimap_label.setMinimumSize(max(200, min(spec.god_w, 900)), max(140, min(spec.god_h, 700)))

# gui/core/renderer.py - Viewport and God-view rendering with standard crosshair only

import math

import cv2
import numpy as np
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QImage, QPixmap

from common.colors import lock_color_bgr


class CrosshairStyle:
    """Standard crosshair — fixed style, no configuration."""
    def __init__(self, gap: int = 10, arm: int = 16, color=(230, 230, 230), thickness: int = 1, show_center_dot: bool = True):
        self.gap = int(gap)
        self.arm = int(arm)
        self.color = color
        self.thickness = int(thickness)
        self.show_center_dot = bool(show_center_dot)


class ScreenSpec:
    """On-screen display sizes — independent of FOV sensor resolution."""
    def __init__(self, viewport_w: int = 400, viewport_h: int = 300, god_w: int = 400, god_h: int = 300, keep_aspect: bool = True):
        self.viewport_w = int(viewport_w)
        self.viewport_h = int(viewport_h)
        self.god_w = int(god_w)
        self.god_h = int(god_h)
        self.keep_aspect = bool(keep_aspect)


class Renderer:
    """Stateless renderer — standard crosshair only."""

    @staticmethod
    def beacon_vibrant_color(beacon_id: int, brightness: float) -> tuple[int, int, int]:
        b_vals = [0, 30, 60, 90, 120, 150, 180, 210, 15, 45, 105, 135]
        b_base = b_vals[int(beacon_id) % len(b_vals)]
        scale = float(np.clip(brightness / 255.0, 0.7, 1.0))
        b_col = int(b_base * scale)
        g_col = int(255 * scale)
        r_col = int(255 * scale)
        g_col = max(g_col, 200)
        r_col = max(r_col, 200)
        return (int(b_col), int(g_col), int(r_col))

    @staticmethod
    def draw_targets(scene_frame: np.ndarray, beacons, target=None) -> None:
        for beacon in beacons:
            if not getattr(beacon, "enabled", True):
                continue
            if getattr(beacon, "blinking", False) and not getattr(beacon, "_blink_visible", True):
                continue
            x, y = beacon.get_position()
            try:
                brightness, radius = beacon.get_photometry()
            except Exception:
                brightness, radius = float(beacon.brightness), float(beacon.radius)
            ix, iy = int(round(x)), int(round(y))
            vib = Renderer.beacon_vibrant_color(beacon.beacon_id, brightness)
            shape = getattr(beacon, "shape", "square")
            size_w = int(getattr(beacon, "size_w", 10))
            size_h = int(getattr(beacon, "size_h", 10))
            # For square: use size_w/h as side lengths; for circle: use radius
            if shape == "square":
                hw, hh = size_w // 2, size_h // 2
                # Glow
                if max(size_w, size_h) > 6:
                    glow = tuple(int(c * 0.55) for c in vib)
                    cv2.rectangle(scene_frame, (ix - hw - 1, iy - hh - 1), (ix + hw + 1, iy + hh + 1), glow, -1, cv2.LINE_AA)
                cv2.rectangle(scene_frame, (ix - hw, iy - hh), (ix + hw, iy + hh), vib, -1, cv2.LINE_AA)
                cv2.rectangle(scene_frame, (ix - hw, iy - hh), (ix + hw, iy + hh), (255, 255, 255), 1, cv2.LINE_AA)
            else:
                r = max(1, int(round(max(size_w, size_h) / 2)) if size_w and size_h else int(round(radius)))
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
        # Square box + thin circle + plus half-cutting square
        h, w = img.shape[:2]
        cx, cy = w//2, h//2
        # Square size ~30% of min dimension, at least 80px for visibility
        S = int(min(w, h) * 0.32)
        S = max(80, min(S, min(w, h) - 20))
        half = S // 2
        # Square box thin (1px) light gray
        x0, y0 = cx - half, cy - half
        x1, y1 = cx + half, cy + half
        cv2.rectangle(img, (x0, y0), (x1, y1), (220, 220, 220), 1, cv2.LINE_AA)
        # Thin circle inside square — radius 0.38*S
        r = int(S * 0.38)
        cv2.circle(img, (cx, cy), r, (200, 200, 200), 1, cv2.LINE_AA)
        # Plus crosshair half cutting square — arms from centre to square edge
        # Horizontal
        cv2.line(img, (x0, cy), (x1, cy), (230, 230, 230), 1, cv2.LINE_AA)
        # Vertical
        cv2.line(img, (cx, y0), (cx, y1), (230, 230, 230), 1, cv2.LINE_AA)
        # Small centre dot
        cv2.circle(img, (cx, cy), 1, (255, 255, 255), -1, cv2.LINE_AA)
        # Corner brackets for FOV border refinement
        Renderer.draw_corner_brackets(img, margin=4, length=max(8, min(w,h)//20), color=(180, 180, 180), thickness=1)

    @staticmethod
    def render_viewport(fov_frame: np.ndarray, camera, beacons, target, tracker, all_dets: list[dict] | None, overlay=None, pulse_progress: float = 0.0, pixel_scale_mrad: float | None = None) -> np.ndarray:
        """Render FOV viewport with standard crosshair only."""
        display = fov_frame.copy()
        h, w = display.shape[:2]
        cx, cy = w // 2, h // 2

        if pixel_scale_mrad is None:
            try:
                pixel_scale_mrad = float(getattr(getattr(camera, "config", None), "pixel_scale_mrad", 0.035))
            except Exception:
                pixel_scale_mrad = 0.035

        # Standard crosshair
        gap = max(8, min(w, h)//16)
        arm = max(12, min(w, h)//12)
        Renderer.draw_reticle(display, (cx, cy), gap=gap, arm=arm, color=(230, 230, 230), thickness=1)
        Renderer.draw_corner_brackets(display, margin=4, length=max(8, min(w,h)//20), color=(180, 180, 180), thickness=1)

        status = tracker.status
        base_color = lock_color_bgr(status.value, default=(170, 170, 170))

        fov_x0, fov_y0, _, _ = camera.get_fov_rect()
        for beacon in beacons:
            if not getattr(beacon, "enabled", True):
                continue
            if getattr(beacon, "blinking", False) and not getattr(beacon, "_blink_visible", True):
                # Skip drawing when blinking off, but keep hitbox for detection? Skip visual only
                pass
            else:
                px = beacon.x - fov_x0
                py = beacon.y - fov_y0
                if -beacon.hitbox_radius <= px <= w + beacon.hitbox_radius and -beacon.hitbox_radius <= py <= h + beacon.hitbox_radius:
                    is_primary = (beacon is target)
                    # Visual shape
                    shape = getattr(beacon, "shape", "square")
                    size_w = int(getattr(beacon, "size_w", 10))
                    size_h = int(getattr(beacon, "size_h", 10))
                    if shape == "square":
                        hw, hh = size_w // 2, size_h // 2
                        col = (0, 220, 255) if is_primary else (200, 200, 200)
                        cv2.rectangle(display, (int(px)-hw, int(py)-hh), (int(px)+hw, int(py)+hh), col, 1, cv2.LINE_AA)
                        cv2.rectangle(display, (int(px)-1, int(py)-1), (int(px)+1, int(py)+1), (255,255,255), -1, cv2.LINE_AA)
                    else:
                        r = max(2, max(size_w, size_h)//2)
                        col = (0, 220, 255) if is_primary else (200, 200, 200)
                        cv2.circle(display, (int(px), int(py)), r, col, 1, cv2.LINE_AA)
                        cv2.circle(display, (int(px), int(py)), 1, (255,255,255), -1, cv2.LINE_AA)
                    # Hitbox
                    col_hit = (0, 220, 255) if is_primary else (160, 180, 120)
                    cv2.circle(display, (int(px), int(py)), int(beacon.hitbox_radius), col_hit, 1, cv2.LINE_AA)
                    col_center = (255, 255, 255) if is_primary else (200, 200, 170)
                    cv2.circle(display, (int(px), int(py)), int(beacon.center_radius), col_center, -1, cv2.LINE_AA)
                    if len(beacons) > 1:
                        cv2.putText(display, f"#{beacon.beacon_id}", (int(px)+beacon.hitbox_radius+2, int(py)-2),
                                    cv2.FONT_HERSHEY_SIMPLEX, 0.28, base_color if is_primary else (160,180,120), 1, cv2.LINE_AA)

        if all_dets:
            for d in all_dets:
                x, y = int(d["x"]), int(d["y"])
                pts = np.array([[x, y-3],[x+3, y],[x, y+3],[x-3, y]], np.int32)
                cv2.polylines(display, [pts], True, (130, 130, 255), 1, cv2.LINE_AA)

        estimate = tracker.estimated_position
        if estimate is not None:
            ex, ey = int(estimate[0]), int(estimate[1])
            cv2.rectangle(display, (ex-6, ey-6), (ex+6, ey+6), base_color, 1, cv2.LINE_AA)
            cv2.drawMarker(display, (ex, ey), base_color, cv2.MARKER_CROSS, 10, 1, cv2.LINE_AA)
            # No in-screen text overlays — resolution/pan-tilt hidden per spec
        # No resolution or pan-tilt text inside screen
        return display

    @staticmethod
    def render_minimap_cached(minimap_thumb: np.ndarray, camera, beacons, target, tracker, label_size: tuple[int, int], scene_size: tuple[int,int]) -> np.ndarray:
        """Fast path — minimap_thumb already resized to label_size (cached, ~0.16M px).
        No 5000×5000 resize or copy. Just overlay FOV/beacons."""
        lw, lh = label_size; sw, sh = scene_size
        display = minimap_thumb.copy()
        # Ensure size matches label (thumb may be slightly off due to aspect)
        th, tw = display.shape[:2]
        if tw != max(50, lw) or th != max(50, lh):
            display = cv2.resize(display, (max(50, lw), max(50, lh)), interpolation=cv2.INTER_LINEAR)
        # scale computed from display->world
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
        except Exception: pass
        try:
            pan_lo, pan_hi = camera.get_pan_range()
            tilt_lo, tilt_hi = camera.get_tilt_range()
            rx0 = int((pan_lo - camera.fov_width/2)*scale_x); ry0 = int((tilt_lo - camera.fov_height/2)*scale_y)
            rx1 = int((pan_hi + camera.fov_width/2)*scale_x); ry1 = int((tilt_hi + camera.fov_height/2)*scale_y)
            rx0 = max(0, min(rx0, display.shape[1]-1)); rx1 = max(0, min(rx1, display.shape[1]-1))
            ry0 = max(0, min(ry0, display.shape[0]-1)); ry1 = max(0, min(ry1, display.shape[0]-1))
            cv2.rectangle(display, (rx0, ry0), (rx1, ry1), (90, 90, 90), 1, cv2.LINE_AA)
        except Exception: pass
        cv2.putText(display, f"{sw}x{sh}", (4, 10), cv2.FONT_HERSHEY_SIMPLEX, 0.28, (180, 180, 180), 1, cv2.LINE_AA)
        for beacon in beacons:
            if not getattr(beacon, "enabled", True):
                continue
            if getattr(beacon, "blinking", False) and not getattr(beacon, "_blink_visible", True):
                continue
            bx, by = beacon.x, beacon.y
            mx, my = int(bx * scale_x), int(by * scale_y)
            hr_s = max(2, int(beacon.hitbox_radius * min(scale_x, scale_y)))
            cr_s = max(1, int(beacon.center_radius * min(scale_x, scale_y)))
            if hr_s < 3: hr_s = 3
            is_primary = (beacon is target)
            col_hit = (0, 220, 255) if is_primary else (165, 175, 120)
            col_center = (255, 255, 255) if is_primary else (200, 200, 170)
            shape = getattr(beacon, "shape", "square")
            size_w = int(getattr(beacon, "size_w", 10))
            size_h = int(getattr(beacon, "size_h", 10))
            if shape == "square":
                hw = max(1, int(size_w * scale_x / 2))
                hh = max(1, int(size_h * scale_y / 2))
                col = (0, 220, 255) if is_primary else (200, 200, 200)
                cv2.rectangle(display, (mx - hw, my - hh), (mx + hw, my + hh), col, 1, cv2.LINE_AA)
            else:
                r = max(1, int(max(size_w, size_h) * min(scale_x, scale_y) / 2))
                col = (0, 220, 255) if is_primary else (200, 200, 200)
                cv2.circle(display, (mx, my), r, col, 1, cv2.LINE_AA)
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
        except Exception: pass
        try:
            pan_lo, pan_hi = camera.get_pan_range()
            tilt_lo, tilt_hi = camera.get_tilt_range()
            rx0 = int((pan_lo - camera.fov_width/2)*scale_x); ry0 = int((tilt_lo - camera.fov_height/2)*scale_y)
            rx1 = int((pan_hi + camera.fov_width/2)*scale_x); ry1 = int((tilt_hi + camera.fov_height/2)*scale_y)
            rx0 = max(0, min(rx0, display.shape[1]-1)); rx1 = max(0, min(rx1, display.shape[1]-1))
            ry0 = max(0, min(ry0, display.shape[0]-1)); ry1 = max(0, min(ry1, display.shape[0]-1))
            cv2.rectangle(display, (rx0, ry0), (rx1, ry1), (90, 90, 90), 1, cv2.LINE_AA)
        except Exception: pass
        cv2.putText(display, f"{sw}x{sh}", (4, 10), cv2.FONT_HERSHEY_SIMPLEX, 0.28, (180, 180, 180), 1, cv2.LINE_AA)
        for beacon in beacons:
            if not getattr(beacon, "enabled", True):
                continue
            if getattr(beacon, "blinking", False) and not getattr(beacon, "_blink_visible", True):
                continue
            bx, by = beacon.x, beacon.y
            mx, my = int(bx * scale_x), int(by * scale_y)
            hr_s = max(2, int(beacon.hitbox_radius * min(scale_x, scale_y)))
            cr_s = max(1, int(beacon.center_radius * min(scale_x, scale_y)))
            if hr_s < 3: hr_s = 3
            is_primary = (beacon is target)
            col_hit = (0, 220, 255) if is_primary else (165, 175, 120)
            col_center = (255, 255, 255) if is_primary else (200, 200, 170)
            # Shape visual
            shape = getattr(beacon, "shape", "square")
            size_w = int(getattr(beacon, "size_w", 10))
            size_h = int(getattr(beacon, "size_h", 10))
            if shape == "square":
                hw = max(1, int(size_w * scale_x / 2))
                hh = max(1, int(size_h * scale_y / 2))
                col = (0, 220, 255) if is_primary else (200, 200, 200)
                cv2.rectangle(display, (mx - hw, my - hh), (mx + hw, my + hh), col, 1, cv2.LINE_AA)
            else:
                r = max(1, int(max(size_w, size_h) * min(scale_x, scale_y) / 2))
                col = (0, 220, 255) if is_primary else (200, 200, 200)
                cv2.circle(display, (mx, my), r, col, 1, cv2.LINE_AA)
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

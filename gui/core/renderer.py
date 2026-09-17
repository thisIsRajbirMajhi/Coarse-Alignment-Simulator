# gui/core/renderer.py - Viewport and God-view rendering with standard crosshair
from __future__ import annotations

import cv2
import numpy as np
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QImage, QPixmap


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
    """Stateless renderer — standard crosshair and camera viewport overlays."""

    @staticmethod
    def draw_reticle(img: np.ndarray, center: tuple[int, int], gap: int = 10, arm: int = 16,
                     color: tuple[int, int, int] = (230, 230, 230), thickness: int = 1,
                     show_dot: bool = True) -> None:
        cx, cy = int(center[0]), int(center[1])
        cv2.line(img, (cx - gap - arm, cy), (cx - gap, cy), color, thickness, cv2.LINE_AA)
        cv2.line(img, (cx + gap, cy), (cx + gap + arm, cy), color, thickness, cv2.LINE_AA)
        cv2.line(img, (cx, cy - gap - arm), (cx, cy - gap), color, thickness, cv2.LINE_AA)
        cv2.line(img, (cx, cy + gap), (cx, cy + gap + arm), color, thickness, cv2.LINE_AA)
        if show_dot:
            cv2.circle(img, (cx, cy), 1, color, -1, cv2.LINE_AA)

    @staticmethod
    def draw_corner_brackets(img: np.ndarray, margin: int = 6, length: int = 10,
                             color: tuple[int, int, int] = (180, 180, 180), thickness: int = 1) -> None:
        h, w = img.shape[:2]
        corners = [
            ((margin, margin), (margin + length, margin), (margin, margin + length)),
            ((w - margin, margin), (w - margin - length, margin), (w - margin, margin + length)),
            ((margin, h - margin), (margin + length, h - margin), (margin, h - margin - length)),
            ((w - margin, h - margin), (w - margin - length, h - margin), (w - margin, h - margin - length)),
        ]
        for (cx, cy), (hx, hy), (vx, vy) in corners:
            cv2.line(img, (cx, cy), (hx, hy), color, thickness, cv2.LINE_AA)
            cv2.line(img, (cx, cy), (vx, vy), color, thickness, cv2.LINE_AA)

    @staticmethod
    def draw_crosshair(img: np.ndarray, style: CrosshairStyle | None = None,
                       pan_tilt: tuple[float, float] | None = None) -> None:
        h, w = img.shape[:2]
        cx, cy = w // 2, h // 2
        S = int(min(w, h) * 0.32)
        S = max(80, min(S, min(w, h) - 20))
        half = S // 2
        x0, y0 = cx - half, cy - half
        x1, y1 = cx + half, cy + half
        cv2.rectangle(img, (x0, y0), (x1, y1), (220, 220, 220), 1, cv2.LINE_AA)
        r = int(S * 0.38)
        cv2.circle(img, (cx, cy), r, (200, 200, 200), 1, cv2.LINE_AA)
        cv2.line(img, (x0, cy), (x1, cy), (230, 230, 230), 1, cv2.LINE_AA)
        cv2.line(img, (cx, y0), (cx, y1), (230, 230, 230), 1, cv2.LINE_AA)
        cv2.circle(img, (cx, cy), 1, (255, 255, 255), -1, cv2.LINE_AA)
        Renderer.draw_corner_brackets(img, margin=4, length=max(8, min(w, h) // 20), color=(180, 180, 180), thickness=1)

    @staticmethod
    def render_viewport(fov_frame: np.ndarray, camera=None, *args, **kwargs) -> np.ndarray:
        """Render FOV viewport with standard crosshair and framing reticle."""
        display = fov_frame.copy()
        h, w = display.shape[:2]
        cx, cy = w // 2, h // 2

        gap = max(8, min(w, h) // 16)
        arm = max(12, min(w, h) // 12)
        Renderer.draw_reticle(display, (cx, cy), gap=gap, arm=arm, color=(230, 230, 230), thickness=1)
        Renderer.draw_corner_brackets(display, margin=4, length=max(8, min(w, h) // 20), color=(180, 180, 180), thickness=1)
        return display

    @staticmethod
    def render_minimap_cached(minimap_thumb: np.ndarray, camera, *args,
                              label_size: tuple[int, int] = (400, 300),
                              scene_size: tuple[int, int] = (2000, 2000), **kwargs) -> np.ndarray:
        """Fast path: minimap_thumb already resized. Overlays FOV bounds and home indicator."""
        lw, lh = label_size
        sw, sh = scene_size
        display = minimap_thumb.copy()
        th, tw = display.shape[:2]
        if tw != max(50, lw) or th != max(50, lh):
            display = cv2.resize(display, (max(50, lw), max(50, lh)), interpolation=cv2.INTER_LINEAR)
        scale_x, scale_y = display.shape[1] / sw, display.shape[0] / sh

        x0, y0, x1, y1 = camera.get_fov_rect()
        x0s, y0s, x1s, y1s = int(x0 * scale_x), int(y0 * scale_y), int(x1 * scale_x), int(y1 * scale_y)
        cv2.rectangle(display, (x0s, y0s), (x1s, y1s), (70, 170, 255), 1, cv2.LINE_AA)
        fcx, fcy = (x0s + x1s) // 2, (y0s + y1s) // 2
        cv2.line(display, (fcx - 5, fcy), (fcx + 5, fcy), (70, 170, 255), 1, cv2.LINE_AA)
        cv2.line(display, (fcx, fcy - 5), (fcx, fcy + 5), (70, 170, 255), 1, cv2.LINE_AA)
        cv2.circle(display, (fcx, fcy), 1, (70, 170, 255), -1, cv2.LINE_AA)

        try:
            hx, hy = camera.get_home()
            hxs, hys = int(hx * scale_x), int(hy * scale_y)
            pts = np.array([[hxs, hys - 4], [hxs + 4, hys], [hxs, hys + 4], [hxs - 4, hys]], np.int32)
            cv2.polylines(display, [pts], True, (255, 200, 50), 1, cv2.LINE_AA)
            cv2.putText(display, "H", (hxs + 5, hys + 2), cv2.FONT_HERSHEY_SIMPLEX, 0.28, (255, 200, 50), 1, cv2.LINE_AA)
        except Exception:
            pass

        try:
            pan_lo, pan_hi = camera.get_pan_range()
            tilt_lo, tilt_hi = camera.get_tilt_range()
            rx0 = int((pan_lo - camera.fov_width / 2) * scale_x)
            ry0 = int((tilt_lo - camera.fov_height / 2) * scale_y)
            rx1 = int((pan_hi + camera.fov_width / 2) * scale_x)
            ry1 = int((tilt_hi + camera.fov_height / 2) * scale_y)
            rx0 = max(0, min(rx0, display.shape[1] - 1))
            rx1 = max(0, min(rx1, display.shape[1] - 1))
            ry0 = max(0, min(ry0, display.shape[0] - 1))
            ry1 = max(0, min(ry1, display.shape[0] - 1))
            cv2.rectangle(display, (rx0, ry0), (rx1, ry1), (90, 90, 90), 1, cv2.LINE_AA)
        except Exception:
            pass

        # Draw remote terminals on minimap
        terminals_data = kwargs.get("terminals")
        if terminals_data and isinstance(terminals_data, dict):
            term_list = terminals_data.get("terminals", [])
            for t in term_list:
                pos = t.get("position", (0, 0, 0))
                txs = int(pos[0] * scale_x)
                tys = int(pos[1] * scale_y)
                is_em = t.get("is_emitting", False)
                tid = str(t.get("id", "RT"))
                color = (50, 220, 120) if is_em else (140, 140, 140)
                cv2.circle(display, (txs, tys), 3, color, -1, cv2.LINE_AA)
                if is_em:
                    cv2.circle(display, (txs, tys), 6, color, 1, cv2.LINE_AA)
                cv2.putText(display, tid, (txs + 5, tys + 3), cv2.FONT_HERSHEY_SIMPLEX, 0.28, color, 1, cv2.LINE_AA)

        cv2.putText(display, f"{sw}x{sh}", (4, 10), cv2.FONT_HERSHEY_SIMPLEX, 0.28, (180, 180, 180), 1, cv2.LINE_AA)
        return display

    @staticmethod
    def render_minimap(scene_frame: np.ndarray, camera, *args,
                       label_size: tuple[int, int] = (400, 300),
                       scene_size: tuple[int, int] = (2000, 2000), **kwargs) -> np.ndarray:
        lw, lh = label_size
        sw, sh = scene_size
        display = cv2.resize(scene_frame, (max(50, lw), max(50, lh)), interpolation=cv2.INTER_LINEAR)
        return Renderer.render_minimap_cached(display, camera, label_size=label_size, scene_size=scene_size, **kwargs)

    @staticmethod
    def set_pixmap(label, bgr_frame: np.ndarray, spec=None) -> np.ndarray:
        rgb = cv2.cvtColor(bgr_frame, cv2.COLOR_BGR2RGB)
        h, w, ch = rgb.shape
        qimg = QImage(rgb.data, w, h, ch * w, QImage.Format_RGB888)
        qimg = qimg.copy()
        lw, lh = int(label.width()), int(label.height())
        if lw < 10 or lh < 10:
            lw, lh = w, h
        pixmap = QPixmap.fromImage(qimg).scaled(lw, lh, Qt.KeepAspectRatio, Qt.FastTransformation)
        label.setPixmap(pixmap)
        return rgb

    @staticmethod
    def apply_screen_sizes(viewport_label, minimap_label, spec) -> None:
        viewport_label.setMinimumSize(max(200, min(spec.viewport_w, 900)), max(140, min(spec.viewport_h, 700)))
        minimap_label.setMinimumSize(max(200, min(spec.god_w, 900)), max(140, min(spec.god_h, 700)))

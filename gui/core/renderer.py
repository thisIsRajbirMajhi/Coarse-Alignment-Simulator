# gui/core/renderer.py - Viewport and God-view rendering with standard crosshair
from __future__ import annotations

import math

import cv2
import numpy as np


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

    # Tracker-point colors (BGR): lock-state aware.
    TRACKER_COLORS: dict[str, tuple[int, int, int]] = {
        "LOCKED": (80, 210, 90),
        "TRACKING": (80, 210, 90),
        "REACQUIRING": (60, 190, 255),
        "DISCRIMINATING": (220, 190, 80),
        "DETECTING": (220, 190, 80),
        "SEARCHING": (150, 150, 150),
        "IDLE": (150, 150, 150),
    }

    @staticmethod
    def tracker_point_color(autonomy_state: str) -> tuple[int, int, int]:
        """BGR color for the tracker marker from autonomy state (LOCKED green ...)."""
        try:
            return Renderer.TRACKER_COLORS.get(str(autonomy_state).upper(), (150, 150, 150))
        except Exception:
            return (150, 150, 150)

    @staticmethod
    def tracker_marker_from_telemetry(telemetry, fov_size: tuple[int, int] | None = None):
        """Extract (x, y, color, label) tracker point from local-terminal telemetry.

        Prefers the active target, else the best confirmed candidate, else the
        first visible candidate (dim). Returns None when nothing trackable.
        Pure helper — never raises, safe with None/partial telemetry.
        """
        try:
            if not isinstance(telemetry, dict):
                return None
            autonomy = telemetry.get("autonomy") or {}
            candidates = autonomy.get("candidates") or []
            if not candidates:
                return None
            active_id = autonomy.get("active_target_id")
            state = str(autonomy.get("state") or "IDLE")
            pick = None
            if active_id is not None:
                for c in candidates:
                    if c.get("terminal_id") == active_id:
                        pick = c
                        break
            if pick is None:
                confirmed = [c for c in candidates if c.get("confirmed")]
                if confirmed:
                    confirmed.sort(key=lambda c: float(c.get("confidence", 0.0)), reverse=True)
                    pick = confirmed[0]
            if pick is None:
                pick = candidates[0]
            x = float(pick.get("fov_x", 0.0))
            y = float(pick.get("fov_y", 0.0))
            if fov_size is not None:
                fw, fh = int(fov_size[0]), int(fov_size[1])
                if not (0 <= x < fw and 0 <= y < fh):
                    return None
            color = Renderer.tracker_point_color(state)
            label = f"{pick.get('terminal_id', 'RT')} {state}"
            return (x, y, color, label)
        except Exception:
            return None

    @staticmethod
    def draw_tracker_point(img: np.ndarray, spot: tuple[float, float],
                           color: tuple[int, int, int] = (80, 210, 90),
                           label: str | None = None) -> None:
        """Draw the tracker point as a hollow circle so the object stays visible inside.

        Ring outline only (nothing painted over the target) + error line from
        FOV center stopping at the ring rim + label.
        """
        h, w = img.shape[:2]
        sx, sy = int(round(float(spot[0]))), int(round(float(spot[1])))
        sx = max(0, min(w - 1, sx))
        sy = max(0, min(h - 1, sy))
        cx, cy = w // 2, h // 2
        r = max(10, min(w, h) // 32)
        # Error vector from FOV center, stopping at the ring rim so it never
        # crosses the object.
        try:
            dx, dy = float(sx - cx), float(sy - cy)
            dist = math.hypot(dx, dy)
            dim = tuple(max(0, min(255, int(c * 0.55))) for c in color)
            if dist > r + 2:
                ex = int(round(sx - dx / dist * r))
                ey = int(round(sy - dy / dist * r))
                cv2.line(img, (cx, cy), (ex, ey), dim, 1, cv2.LINE_AA)
        except Exception:
            pass
        # Hollow ring — object visible inside.
        cv2.circle(img, (sx, sy), r, color, 2, cv2.LINE_AA)
        if label:
            try:
                (tw, th), _ = cv2.getTextSize(str(label), cv2.FONT_HERSHEY_SIMPLEX, 0.4, 1)
                tx = max(2, min(w - tw - 4, sx + r + 4))
                ty = max(th + 4, sy - r - 4)
                cv2.rectangle(img, (tx - 2, ty - th - 3), (tx + tw + 2, ty + 2), (10, 10, 10), -1)
                cv2.putText(img, str(label), (tx, ty - 1), cv2.FONT_HERSHEY_SIMPLEX, 0.4, color, 1, cv2.LINE_AA)
            except Exception:
                pass

    @staticmethod
    def render_viewport(fov_frame: np.ndarray, camera=None, *args, **kwargs) -> np.ndarray:
        """Render FOV viewport: crosshair + framing reticle + tracker point.

        Tracker telemetry may be passed as ``telemetry=`` kwarg (local-terminal
        telemetry dict) or derived from ``camera`` when it carries one. Extra
        positional/keyword args are ignored for backward compatibility.
        """
        display = fov_frame.copy()
        h, w = display.shape[:2]
        cx, cy = w // 2, h // 2

        gap = max(8, min(w, h) // 16)
        arm = max(12, min(w, h) // 12)
        Renderer.draw_reticle(display, (cx, cy), gap=gap, arm=arm, color=(230, 230, 230), thickness=1)
        Renderer.draw_corner_brackets(display, margin=4, length=max(8, min(w, h) // 20), color=(180, 180, 180), thickness=1)

        telemetry = kwargs.get("telemetry", None)
        if telemetry is None and len(args) >= 1 and isinstance(args[0], dict):
            telemetry = args[0]
        marker = Renderer.tracker_marker_from_telemetry(telemetry, (w, h))
        if marker is not None:
            x, y, color, label = marker
            Renderer.draw_tracker_point(display, (x, y), color=color, label=label)
        return display

    @staticmethod
    def render_minimap_cached(minimap_thumb: np.ndarray, camera=None, *args,
                              label_size: tuple[int, int] = (400, 300),
                              scene_size: tuple[int, int] = (2000, 2000), **kwargs) -> np.ndarray:
        """Fast path: minimap_thumb already resized. Overlays home indicator and terminals."""
        lw, lh = label_size
        sw, sh = scene_size
        display = minimap_thumb.copy()
        th, tw = display.shape[:2]
        if tw != max(50, lw) or th != max(50, lh):
            display = cv2.resize(display, (max(50, lw), max(50, lh)), interpolation=cv2.INTER_LINEAR)
        scale_x, scale_y = display.shape[1] / sw, display.shape[0] / sh

        if camera is not None:
            try:
                x0, y0, x1, y1 = camera.get_fov_rect()
                x0s, y0s, x1s, y1s = int(x0 * scale_x), int(y0 * scale_y), int(x1 * scale_x), int(y1 * scale_y)
                cv2.rectangle(display, (x0s, y0s), (x1s, y1s), (70, 170, 255), 1, cv2.LINE_AA)
                fcx, fcy = (x0s + x1s) // 2, (y0s + y1s) // 2
                cv2.line(display, (fcx - 5, fcy), (fcx + 5, fcy), (70, 170, 255), 1, cv2.LINE_AA)
                cv2.line(display, (fcx, fcy - 5), (fcx, fcy + 5), (70, 170, 255), 1, cv2.LINE_AA)
                cv2.circle(display, (fcx, fcy), 1, (70, 170, 255), -1, cv2.LINE_AA)
            except Exception:
                pass

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

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
    """Stateless renderer — standard crosshair, tactical reticle, and camera viewport overlays."""

    @staticmethod
    def draw_hud_badge(
        img: np.ndarray,
        text: str,
        pos: tuple[int, int],
        bg_color: tuple[int, int, int] = (15, 23, 42),
        text_color: tuple[int, int, int] = (226, 232, 240),
        font_scale: float = 0.42,
        thickness: int = 1,
        padding: int = 4,
        border_color: tuple[int, int, int] | None = (51, 65, 85),
        font_face: int = cv2.FONT_HERSHEY_DUPLEX,
    ) -> tuple[int, int, int, int]:
        """Draw text with a high-contrast background pill for crisp readability over any video background."""
        x, y = int(pos[0]), int(pos[1])
        (tw, th), baseline = cv2.getTextSize(text, font_face, font_scale, thickness)
        bx0 = max(0, x - padding)
        by0 = max(0, y - th - padding)
        bx1 = min(img.shape[1] - 1, x + tw + padding)
        by1 = min(img.shape[0] - 1, y + baseline + padding)
        cv2.rectangle(img, (bx0, by0), (bx1, by1), bg_color, -1)
        if border_color is not None:
            border_thick = max(1, int(round(thickness / 2.0)))
            cv2.rectangle(img, (bx0, by0), (bx1, by1), border_color, border_thick, cv2.LINE_AA)
        cv2.putText(img, text, (x, y), font_face, font_scale, text_color, thickness, cv2.LINE_AA)
        return (bx0, by0, bx1, by1)

    @staticmethod
    def draw_reticle(img: np.ndarray, center: tuple[int, int], gap: int = 10, arm: int = 18,
                     color: tuple[int, int, int] = (220, 225, 230), thickness: int = 1,
                     show_dot: bool = True) -> None:
        """Simple, clean boresight reticle with 10px coarse alignment boundary circle."""
        cx, cy = int(center[0]), int(center[1])
        # Crosshair arms
        cv2.line(img, (cx - gap - arm, cy), (cx - gap, cy), color, thickness, cv2.LINE_AA)
        cv2.line(img, (cx + gap, cy), (cx + gap + arm, cy), color, thickness, cv2.LINE_AA)
        cv2.line(img, (cx, cy - gap - arm), (cx, cy - gap), color, thickness, cv2.LINE_AA)
        cv2.line(img, (cx, cy + gap), (cx, cy + gap + arm), color, thickness, cv2.LINE_AA)

        # 10px coarse alignment threshold circle (PDF specification limit)
        cv2.circle(img, (cx, cy), 10, (74, 222, 128), 1, cv2.LINE_AA)

        if show_dot:
            cv2.circle(img, (cx, cy), 1, (255, 255, 255), -1, cv2.LINE_AA)

    @staticmethod
    def draw_corner_brackets(img: np.ndarray, margin: int = 6, length: int = 12,
                             color: tuple[int, int, int] = (140, 150, 165), thickness: int = 1) -> None:
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
        "LOCKED": (74, 222, 128),
        "TRACKING": (74, 222, 128),
        "REACQUIRING": (56, 189, 248),
        "DISCRIMINATING": (250, 204, 21),
        "DETECTING": (250, 204, 21),
        "SEARCHING": (148, 163, 184),
        "IDLE": (148, 163, 184),
    }

    @staticmethod
    def tracker_point_color(autonomy_state: str) -> tuple[int, int, int]:
        """BGR color for the tracker marker from autonomy state (LOCKED green ...)."""
        try:
            return Renderer.TRACKER_COLORS.get(str(autonomy_state).upper(), (148, 163, 184))
        except Exception:
            return (148, 163, 184)

    @staticmethod
    def tracker_marker_from_telemetry(telemetry, fov_size: tuple[int, int] | None = None, camera=None):
        """Extract (x, y, color, label, heading_rad, speed) tracker point from telemetry.

        Supports:
        1. Local-terminal autonomy telemetry (candidates, active_target_id)
        2. Remote terminal list with camera world_to_fov coordinate mapping.
        Prefers the active emitting target, else first confirmed/visible candidate.
        Returns None when nothing trackable.
        Pure helper — never raises, safe with None/partial telemetry.
        """
        try:
            if not isinstance(telemetry, dict):
                return None

            # 1. Autonomy candidate pipeline
            autonomy = telemetry.get("autonomy") or {}
            candidates = autonomy.get("candidates") or []
            if candidates:
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
                return (x, y, color, label, None, None)

            # 2. Direct remote terminals pipeline with camera FOV projection
            # GROUND-TRUTH fallback (Fixes.md 3.8): never label as an
            # autonomy estimate — explicit TRUTH prefix.
            if camera is not None and "terminals" in telemetry:
                term_list = telemetry.get("terminals", [])
                if isinstance(term_list, list) and term_list:
                    active_t = next((t for t in term_list if t.get("emitting")), term_list[0] if term_list else None)
                    if active_t is not None:
                        pos = active_t.get("position_m", (0.0, 0.0))
                        tx, ty = float(pos[0]), float(pos[1])
                        fx, fy = camera.world_to_fov(tx, ty)
                        if fov_size is not None:
                            fw, fh = int(fov_size[0]), int(fov_size[1])
                            if not (0 <= fx < fw and 0 <= fy < fh):
                                return None
                        is_em = bool(active_t.get("emitting", False))
                        color = (74, 222, 128) if is_em else (148, 163, 184)
                        tid = str(active_t.get("id", "RT"))
                        label = f"TRUTH {tid} (ACTIVE)" if is_em else f"TRUTH {tid}"
                        # velocity_mps is (vx, vy) tuple in telemetry; derive heading/speed
                        vel = active_t.get("velocity_mps")
                        if isinstance(vel, (list, tuple)) and len(vel) == 2:
                            try:
                                vx, vy = float(vel[0]), float(vel[1])
                                speed = math.hypot(vx, vy)
                                heading_rad = math.atan2(vy, vx) if speed > 1e-6 else None
                            except Exception:
                                heading_rad, speed = None, None
                        else:
                            heading_rad = float(active_t.get("heading_rad", 0.0)) if "heading_rad" in active_t else None
                            speed = float(active_t.get("velocity_m_s", 0.0)) if "velocity_m_s" in active_t else None
                        return (fx, fy, color, label, heading_rad, speed)

            return None
        except Exception:
            return None

    @staticmethod
    def draw_tracker_point(img: np.ndarray, spot: tuple[float, float],
                           color: tuple[int, int, int] = (74, 222, 128),
                           label: str | None = None,
                           heading_rad: float | None = None,
                           speed: float | None = None) -> None:
        """Draw clean target lock ring, error line, and clear status label."""
        h, w = img.shape[:2]
        sx, sy = int(round(float(spot[0]))), int(round(float(spot[1])))
        sx = max(0, min(w - 1, sx))
        sy = max(0, min(h - 1, sy))
        cx, cy = w // 2, h // 2
        r = 14

        # 1. Error line from boresight to target rim
        try:
            dx, dy = float(sx - cx), float(sy - cy)
            dist = math.hypot(dx, dy)
            dim = tuple(max(0, min(255, int(c * 0.6))) for c in color)
            if dist > r + 2:
                ex = int(round(sx - dx / dist * r))
                ey = int(round(sy - dy / dist * r))
                cv2.line(img, (cx, cy), (ex, ey), dim, 1, cv2.LINE_AA)
                mx, my = (cx + ex) // 2, (cy + ey) // 2
                Renderer.draw_hud_badge(
                    img,
                    f"{dist:.1f}px",
                    (mx + 4, my - 2),
                    bg_color=(10, 15, 25),
                    text_color=(56, 189, 248),
                    font_scale=0.38,
                    padding=3,
                    border_color=(3, 105, 161),
                )
        except Exception:
            pass

        # 2. Hollow ring around target
        cv2.circle(img, (sx, sy), r, color, 2, cv2.LINE_AA)

        # 3. Heading arrow (if moving)
        if heading_rad is not None and speed is not None and speed > 0.5:
            v_len = 24.0
            vx = int(round(sx + v_len * math.cos(heading_rad)))
            vy = int(round(sy - v_len * math.sin(heading_rad)))
            cv2.arrowedLine(img, (sx, sy), (vx, vy), (250, 204, 21), 2, cv2.LINE_AA, tipLength=0.3)

        # 4. Target label badge
        if label:
            Renderer.draw_hud_badge(
                img,
                str(label),
                (sx + r + 8, sy + 5),
                bg_color=(10, 15, 25),
                text_color=color,
                font_scale=0.44,
                thickness=1,
                padding=4,
                border_color=(30, 41, 59),
            )

    @staticmethod
    def render_viewport(fov_frame: np.ndarray, camera=None, *args, **kwargs) -> np.ndarray:
        """Render FOV viewport: clean boresight reticle + target tracking + simple telemetry."""
        display = fov_frame.copy()
        h, w = display.shape[:2]
        cx, cy = w // 2, h // 2

        # 1. Boresight reticle & corner brackets
        Renderer.draw_reticle(display, (cx, cy), gap=10, arm=18, color=(220, 225, 230), thickness=1)
        Renderer.draw_corner_brackets(display, margin=6, length=12, color=(140, 150, 165), thickness=1)

        # 2. Target marker
        telemetry = kwargs.get("telemetry", None)
        if telemetry is None and len(args) >= 1 and isinstance(args[0], dict):
            telemetry = args[0]
        marker = Renderer.tracker_marker_from_telemetry(telemetry, (w, h), camera=camera)
        if marker is not None:
            if len(marker) >= 6:
                x, y, color, label, h_rad, spd = marker[:6]
                Renderer.draw_tracker_point(display, (x, y), color=color, label=label, heading_rad=h_rad, speed=spd)
            else:
                x, y, color, label = marker[:4]
                Renderer.draw_tracker_point(display, (x, y), color=color, label=label)

        # 2b. Candidate markers - limited to top 3, de-duplicated to avoid overlap (fixes image 1 clutter)
        if telemetry and isinstance(telemetry, dict):
            autonomy = telemetry.get("autonomy") or {}
            cands = autonomy.get("candidates") or []
            # Filter to non-active candidates, sort by confidence, limit to 3, dedup overlapping <24px
            filtered = []
            for c in cands:
                # Skip the active track candidate (already drawn as main marker)
                if c.get("confirmed") and c.get("terminal_id") != "CANDIDATE":
                    continue
                cx_c = float(c.get("fov_x", 0.0))
                cy_c = float(c.get("fov_y", 0.0))
                if marker is not None and math.hypot(cx_c - marker[0], cy_c - marker[1]) < 12.0:
                    continue
                # Deduplicate overlapping candidates
                overlap = False
                for fc in filtered:
                    if math.hypot(cx_c - fc["x"], cy_c - fc["y"]) < 24.0:
                        overlap = True
                        break
                if overlap:
                    continue
                filtered.append({"x": cx_c, "y": cy_c, "c": c})
                if len(filtered) >= 3:
                    break
            for fc in filtered:
                c = fc["c"]
                icx, icy = int(round(fc["x"])), int(round(fc["y"]))
                if 0 <= icx < w and 0 <= icy < h:
                    cv2.rectangle(display, (icx - 7, icy - 7), (icx + 7, icy + 7), (100, 160, 200), 1, cv2.LINE_AA)
                    conf = float(c.get("confidence", 0.0))
                    # Show SNR instead of always 1.00 for better diagnostics
                    snr = float(c.get("snr_db", 0.0)) if "snr_db" in c else conf * 12 + 6
                    Renderer.draw_hud_badge(
                        display,
                        f"CAND {conf:.2f} {snr:.0f}dB",
                        (icx + 9, icy + 4),
                        bg_color=(10, 15, 25),
                        text_color=(100, 160, 200),
                        font_scale=0.32,
                        padding=2,
                        border_color=(30, 41, 59),
                    )

        # 3. Simple, Clean Telemetry Badges
        cam_tel = kwargs.get("camera_telemetry")
        pid_tel = kwargs.get("pid_telemetry")

        # Top-Left: Pan / Tilt
        pan_txt, tilt_txt = "+0.00°", "+0.00°"
        if cam_tel and isinstance(cam_tel, dict):
            ptz = cam_tel.get("ptz", {})
            pan_txt = f"{float(ptz.get('pan_deg', 0.0)):+.2f}°"
            tilt_txt = f"{float(ptz.get('tilt_deg', 0.0)):+.2f}°"
        elif camera is not None:
            pan_txt = f"{camera.pan_deg:+.2f}°"
            tilt_txt = f"{camera.tilt_deg:+.2f}°"

        Renderer.draw_hud_badge(
            display,
            f"Pan: {pan_txt}  Tilt: {tilt_txt}",
            (12, 24),
            bg_color=(10, 15, 25),
            text_color=(226, 232, 240),
            font_scale=0.44,
            thickness=1,
            padding=5,
            border_color=(30, 41, 59),
        )

        # Top-Right: Mode & Tracking Error
        mode_str = "AUTO"
        err_px_val = 0.0
        if pid_tel and isinstance(pid_tel, dict):
            epx = float(pid_tel.get("error_pan_px", 0.0))
            epy = float(pid_tel.get("error_tilt_px", 0.0))
            err_px_val = math.hypot(epx, epy)
            mode_str = str(pid_tel.get("mode", "AUTO"))

        # Real autonomy state from telemetry - error-aware (fixes LOCKED with 180px)
        aut_state = None
        if telemetry and isinstance(telemetry, dict):
            aut = telemetry.get("autonomy")
            if isinstance(aut, dict):
                aut_state = aut.get("state")
        # Error takes precedence: even if FSM says LOCKED but error >50, show COAST/SEARCH
        if err_px_val > 50.0:
            status_txt = "SEARCHING" if err_px_val > 100 else "COAST"
        elif err_px_val > 10.0:
            # Large error but within 50px - show TRACKING/COAST, not LOCKED
            if aut_state and str(aut_state).upper() in ("COAST", "LOST", "REACQUIRE"):
                status_txt = str(aut_state).upper()
            else:
                status_txt = "TRACKING"
        else:
            if aut_state:
                # Only show LOCKED if error is actually <10
                st = str(aut_state).upper()
                if st == "LOCKED" and err_px_val > 10.0:
                    status_txt = "TRACKING"
                else:
                    status_txt = st
            else:
                status_txt = "LOCKED" if err_px_val <= 10.0 and err_px_val > 0.0 else ("TRACKING" if err_px_val <= 50.0 and err_px_val > 0.0 else "SEARCHING")

        status_col = Renderer.tracker_point_color(status_txt)

        status_badge_text = f"[{mode_str}] {status_txt}  Err: {err_px_val:.1f}px"
        (stw, _), _ = cv2.getTextSize(status_badge_text, cv2.FONT_HERSHEY_DUPLEX, 0.44, 1)
        right_x = max(12, w - stw - 18)

        Renderer.draw_hud_badge(
            display,
            status_badge_text,
            (right_x, 24),
            bg_color=(10, 15, 25),
            text_color=status_col,
            font_scale=0.44,
            thickness=1,
            padding=5,
            border_color=(30, 41, 59),
        )

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
            p_min, p_max, t_min, t_max = camera.get_effective_angular_limits()
            hx, hy = camera.get_home()
            x_min = hx + p_min * camera.config.px_per_deg_h - camera.fov_width / 2.0
            x_max = hx + p_max * camera.config.px_per_deg_h + camera.fov_width / 2.0
            y_min = hy - t_max * camera.config.px_per_deg_v - camera.fov_height / 2.0
            y_max = hy - t_min * camera.config.px_per_deg_v + camera.fov_height / 2.0
            rx0 = int(x_min * scale_x)
            ry0 = int(y_min * scale_y)
            rx1 = int(x_max * scale_x)
            ry1 = int(y_max * scale_y)
            rx0 = max(0, min(rx0, display.shape[1] - 1))
            rx1 = max(0, min(rx1, display.shape[1] - 1))
            ry0 = max(0, min(ry0, display.shape[0] - 1))
            ry1 = max(0, min(ry1, display.shape[0] - 1))
            cv2.rectangle(display, (rx0, ry0), (rx1, ry1), (90, 90, 90), 1, cv2.LINE_AA)
        except Exception:
            pass

        # Draw remote terminals on minimap (1 m = 1 px scene mapping).
        terminals_data = kwargs.get("terminals")
        if terminals_data and isinstance(terminals_data, dict):
            term_list = terminals_data.get("terminals", [])
            for t in term_list:
                try:
                    if not isinstance(t, dict):
                        continue
                    pos = t.get("position_m", (0, 0))
                    txs = int(float(pos[0]) * scale_x)
                    tys = int(float(pos[1]) * scale_y)
                    is_em = bool(t.get("emitting", False))
                    tid = str(t.get("id", "RT"))
                    color = (50, 220, 120) if is_em else (140, 140, 140)
                    cv2.circle(display, (txs, tys), 3, color, -1, cv2.LINE_AA)
                    if is_em:
                        cv2.circle(display, (txs, tys), 6, color, 1, cv2.LINE_AA)
                    cv2.putText(display, tid, (txs + 5, tys + 3), cv2.FONT_HERSHEY_SIMPLEX, 0.28, color, 1, cv2.LINE_AA)
                except (TypeError, ValueError, IndexError):
                    continue

        cv2.putText(display, f"{sw}x{sh}", (4, 10), cv2.FONT_HERSHEY_SIMPLEX, 0.28, (180, 180, 180), 1, cv2.LINE_AA)
        return display

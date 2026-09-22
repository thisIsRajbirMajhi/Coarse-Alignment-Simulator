# gui/views/simulation_view.py - Side-by-side Camera FOV viewport and God screen.
from __future__ import annotations

import logging
import math
from typing import Any

import cv2
import numpy as np
from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from gui.core.frame_presenter import frame_to_pixmap
from gui.core.renderer import Renderer

log = logging.getLogger(__name__)


class SimulationView(QWidget):
    """
    Unified dual-viewport showing Camera FOV screen side-by-side with God Screen.
    
    Left: Camera FOV Screen (640x480 native monochrome viewport with reticle & tracker).
    Right: God Screen (full world scene with camera FOV footprint overlay & terminal spots).
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        splitter = QSplitter(Qt.Horizontal, self)
        splitter.setHandleWidth(4)
        splitter.setStyleSheet(
            "QSplitter::handle { background:#1e293b; border-radius:2px; } "
            "QSplitter::handle:hover { background:#38bdf8; }"
        )

        # --- LEFT PANEL: Camera FOV Screen ---
        self.fov_label = QLabel("Camera FOV ", splitter)
        self.fov_label.setObjectName("simFovView")
        self.fov_label.setAlignment(Qt.AlignCenter)
        self.fov_label.setMinimumSize(320, 240)
        self.fov_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.fov_label.setStyleSheet("background:#000000; color:#64748b; border:1px solid #1e293b; border-radius:6px;")

        # --- RIGHT PANEL: God Screen (World Scene) ---
        self.world_label = QLabel("World Screen", splitter)
        self.world_label.setObjectName("simWorldView")
        self.world_label.setAlignment(Qt.AlignCenter)
        self.world_label.setMinimumSize(320, 240)
        self.world_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.world_label.setStyleSheet("background:#000000; color:#64748b; border:1px solid #1e293b; border-radius:6px;")

        # Add both to splitter with equal initial distribution
        splitter.addWidget(self.fov_label)
        splitter.addWidget(self.world_label)
        splitter.setSizes([640, 640])
        layout.addWidget(splitter, 1)

        # Backward compatibility aliases
        self.view_label = self.world_label
        self.lbl_cam_telemetry = None
        self.lbl_cam_err = None
        self.lbl_world_sub = None

        self._fov_pixmap_size = None
        self._world_pixmap_size = None
        self._trajectory_history: dict[str, list[tuple[float, float]]] = {}

    @staticmethod
    def _scale_for_label(pm, label, last_size):
        """Fit pixmap into label preserving aspect ratio with smooth anti-aliased scaling."""
        size = label.size()
        key = (size.width(), size.height())
        return pm.scaled(size, Qt.KeepAspectRatio, Qt.SmoothTransformation), key

    def render_snapshot(self, snapshot: Any, session: Any) -> None:
        if snapshot is None:
            return

        world_frame = getattr(snapshot, "world_frame", None)
        fov_frame = getattr(snapshot, "fov_frame", None)

        # Fallback if fov_frame is not yet extracted
        if fov_frame is None and session is not None and hasattr(session, "camera") and world_frame is not None:
            fov_frame = session.camera.extract_fov(world_frame)

        # 1. Render Left Panel (Camera FOV Viewport with Reticle & Tracking)
        if fov_frame is not None:
            try:
                overlayed_fov = Renderer.render_viewport(
                    fov_frame,
                    camera=getattr(session, "camera", None),
                    telemetry=getattr(snapshot, "tracker_telemetry", None) or getattr(snapshot, "terminals", None),
                    camera_telemetry=getattr(snapshot, "camera_telemetry", None),
                    pid_telemetry=getattr(snapshot, "pid_telemetry", None),
                )
                pm_fov = frame_to_pixmap(overlayed_fov)
                if pm_fov is not None:
                    pm_fov, self._fov_pixmap_size = self._scale_for_label(pm_fov, self.fov_label, self._fov_pixmap_size)
                    self.fov_label.setPixmap(pm_fov)
            except Exception as e:
                log.warning("FOV view render failed: %s", e)

        # 2. Render Right Panel (God View) - throttled to 15 FPS for 60 FPS FOV
        # God view is 2000x2000 (4M) with heavy overlays; throttling + downsampling to 800x600 saves ~10ms.
        frame_id = int(getattr(snapshot, "frame_id", 0) or 0)
        if world_frame is not None:
            if frame_id % 4 != 0 and hasattr(self, "_cached_god_pixmap") and self._cached_god_pixmap is not None:
                try:
                    self.world_label.setPixmap(self._cached_god_pixmap)
                except Exception:
                    pass
            else:
                try:
                    display_world = world_frame.copy()
                    wh, ww = display_world.shape[:2]
                    frame_id = int(getattr(snapshot, "frame_id", 0))

                    # Reset history on session restart
                    if frame_id <= 1:
                        self._trajectory_history.clear()

                    # Dynamic scale factor S to normalize drawing size to widget dimensions
                    lbl_w = max(200, self.world_label.width())
                    lbl_h = max(200, self.world_label.height())
                    S = max(1.0, max(ww / float(lbl_w), wh / float(lbl_h)))

                    camera = getattr(session, "camera", None)

                    # (a) Gimbal Home Base (subtle, fine diamond)
                    if camera is not None:
                        hx, hy = camera.get_home()
                        ihx, ihy = int(round(hx)), int(round(hy))
                        d = int(round(8 * S))
                        pts = np.array([[ihx, ihy - d], [ihx + d, ihy], [ihx, ihy + d], [ihx - d, ihy]], np.int32)
                        cv2.polylines(display_world, [pts], True, (100, 140, 180), max(1, int(round(1.2 * S))), cv2.LINE_AA)
                        cv2.putText(
                            display_world,
                            "BASE",
                            (ihx + int(round(10 * S)), ihy + int(round(4 * S))),
                            cv2.FONT_HERSHEY_DUPLEX,
                            0.34 * S,
                            (100, 140, 180),
                            max(1, int(round(1.0 * S))),
                            cv2.LINE_AA,
                        )

                        # (b) Camera FOV Bounding Box (sleek cyan frame + center cross)
                        # Use disturbed (actual) FOV geometry so God box aligns with FOV content under jitter/platform.
                        if getattr(snapshot, "fov_rect_disturbed", None) is not None:
                            x0, y0, x1, y1 = snapshot.fov_rect_disturbed
                        elif getattr(snapshot, "fov_center_disturbed", None) is not None:
                            dcx, dcy = snapshot.fov_center_disturbed
                            hw, hh = camera.fov_width / 2.0, camera.fov_height / 2.0
                            x0, y0, x1, y1 = dcx - hw, dcy - hh, dcx + hw, dcy + hh
                        else:
                            x0, y0, x1, y1 = camera.get_fov_rect()
                        ix0, iy0 = int(round(x0)), int(round(y0))
                        ix1, iy1 = int(round(x1)), int(round(y1))
                        cv2.rectangle(display_world, (ix0, iy0), (ix1, iy1), (56, 189, 248), max(1, int(round(1.5 * S))), cv2.LINE_AA)

                        if getattr(snapshot, "fov_center_disturbed", None) is not None:
                            cx, cy = snapshot.fov_center_disturbed
                        else:
                            cx, cy = camera.get_fov_center_world()
                        icx, icy = int(round(cx)), int(round(cy))
                        arm = int(round(12 * S))
                        thk = max(1, int(round(1.2 * S)))
                        cv2.line(display_world, (icx - arm, icy), (icx + arm, icy), (56, 189, 248), thk, cv2.LINE_AA)
                        cv2.line(display_world, (icx, icy - arm), (icx, icy + arm), (56, 189, 248), thk, cv2.LINE_AA)

                        # Subtle text inside top-left corner
                        cv2.putText(
                            display_world,
                            "CAM FOV",
                            (ix0 + int(round(8 * S)), iy0 + int(round(18 * S))),
                            cv2.FONT_HERSHEY_DUPLEX,
                            0.36 * S,
                            (56, 189, 248),
                            max(1, int(round(1.0 * S))),
                            cv2.LINE_AA,
                        )

                    # (c) Remote Terminals: Breadcrumb Trails, Predictive Lead Vectors, & Markers
                    terms = getattr(snapshot, "terminals", None)
                    # Prefer tracked target for link line — not just first emitting.
                    active_tid = None
                    try:
                        tt = getattr(snapshot, "tracker_telemetry", None) or {}
                        active_tid = (tt.get("autonomy") or {}).get("active_target_id")
                    except Exception:
                        pass
                    active_target_pos = None
                    if terms and isinstance(terms, dict):
                        for t in terms.get("terminals", []):
                            pos = t.get("position_m")
                            if not pos:
                                continue
                            tx, ty = int(round(pos[0])), int(round(pos[1]))
                            is_em = bool(t.get("emitting", False))
                            tid = str(t.get("id", "RT"))
                            # velocity_mps is (vx, vy) tuple — derive speed/heading (old keys velocity_m_s/heading_rad never emitted)
                            vel = t.get("velocity_mps") or (0.0, 0.0)
                            try:
                                vx, vy = float(vel[0]), float(vel[1])
                                spd = math.hypot(vx, vy)
                                heading = math.atan2(vy, vx) if spd > 1e-6 else 0.0
                            except Exception:
                                spd = float(t.get("velocity_m_s", 0.0))
                                heading = float(t.get("heading_rad", 0.0))

                            # Feature 1: Trajectory Breadcrumb Trail (Motion History)
                            hist = self._trajectory_history.setdefault(tid, [])
                            if not hist or math.hypot(tx - hist[-1][0], ty - hist[-1][1]) >= 2.0:
                                hist.append((float(tx), float(ty)))
                                if len(hist) > 35:
                                    hist.pop(0)

                            if len(hist) >= 2 and spd > 0.3:
                                n_pts = len(hist)
                                for idx in range(1, n_pts):
                                    p0 = (int(round(hist[idx - 1][0])), int(round(hist[idx - 1][1])))
                                    p1 = (int(round(hist[idx][0])), int(round(hist[idx][1])))
                                    frac = idx / float(n_pts)
                                    if is_em:
                                        seg_col = (int(74 * frac * 0.7), int(222 * frac * 0.7), int(128 * frac * 0.7))
                                    else:
                                        seg_col = (int(148 * frac * 0.4), int(163 * frac * 0.4), int(184 * frac * 0.4))
                                    cv2.line(display_world, p0, p1, seg_col, max(1, int(round(1.0 * S))), cv2.LINE_AA)

                            # Feature 2: Predictive Lead Vector (+1.0s Lookahead Indicator)
                            if spd > 0.5:
                                t_look = 1.0
                                lx = tx + spd * math.cos(heading) * t_look
                                ly = ty - spd * math.sin(heading) * t_look
                                ilx, ily = int(round(lx)), int(round(ly))
                                # 4 fine projection dots along path
                                for step in range(1, 5):
                                    st = step / 4.0
                                    dx = int(round(tx + (lx - tx) * st))
                                    dy = int(round(ty + (ly - ty) * st))
                                    cv2.circle(display_world, (dx, dy), max(1, int(round(1.0 * S))), (250, 204, 21), -1, cv2.LINE_AA)
                                # Projected arrival reticle
                                cv2.circle(display_world, (ilx, ily), max(2, int(round(2.5 * S))), (250, 204, 21), max(1, int(round(1.0 * S))), cv2.LINE_AA)

                            # Terminal Markers — track active_target_id for link line.
                            if is_em:
                                if active_tid is None or str(t.get("id")) == str(active_tid):
                                    active_target_pos = (tx, ty)
                                elif active_target_pos is None:
                                    active_target_pos = (tx, ty)

                                # Dynamic radiating beacon pulse
                                pulse_phase = (frame_id % 30) / 30.0
                                pulse_r = int(round((6.0 + 12.0 * pulse_phase) * S))
                                pulse_alpha = 1.0 - pulse_phase
                                pulse_col = (int(74 * pulse_alpha), int(222 * pulse_alpha), int(128 * pulse_alpha))
                                cv2.circle(display_world, (tx, ty), pulse_r, pulse_col, max(1, int(round(1.0 * S))), cv2.LINE_AA)

                                # Sleek target marker: fine ring + center dot
                                cv2.circle(display_world, (tx, ty), int(round(6 * S)), (74, 222, 128), max(1, int(round(1.5 * S))), cv2.LINE_AA)
                                cv2.circle(display_world, (tx, ty), max(2, int(round(2 * S))), (255, 255, 255), -1, cv2.LINE_AA)

                                # Compact, high-contrast label with subtle shadow
                                cv2.putText(
                                    display_world,
                                    tid,
                                    (tx + int(round(9 * S)) + 1, ty + int(round(4 * S)) + 1),
                                    cv2.FONT_HERSHEY_DUPLEX,
                                    0.35 * S,
                                    (0, 0, 0),
                                    max(1, int(round(1.5 * S))),
                                    cv2.LINE_AA,
                                )
                                cv2.putText(
                                    display_world,
                                    tid,
                                    (tx + int(round(9 * S)), ty + int(round(4 * S))),
                                    cv2.FONT_HERSHEY_DUPLEX,
                                    0.35 * S,
                                    (74, 222, 128),
                                    max(1, int(round(1.0 * S))),
                                    cv2.LINE_AA,
                                )
                            else:
                                # Standby terminal: sleek muted slate ring + center dot
                                cv2.circle(display_world, (tx, ty), int(round(5 * S)), (148, 163, 184), max(1, int(round(1.2 * S))), cv2.LINE_AA)
                                cv2.circle(display_world, (tx, ty), max(1, int(round(1.5 * S))), (148, 163, 184), -1, cv2.LINE_AA)

                                cv2.putText(
                                    display_world,
                                    tid,
                                    (tx + int(round(8 * S)) + 1, ty + int(round(4 * S)) + 1),
                                    cv2.FONT_HERSHEY_DUPLEX,
                                    0.32 * S,
                                    (0, 0, 0),
                                    max(1, int(round(1.5 * S))),
                                    cv2.LINE_AA,
                                )
                                cv2.putText(
                                    display_world,
                                    tid,
                                    (tx + int(round(8 * S)), ty + int(round(4 * S))),
                                    cv2.FONT_HERSHEY_DUPLEX,
                                    0.32 * S,
                                    (148, 163, 184),
                                    max(1, int(round(1.0 * S))),
                                    cv2.LINE_AA,
                                )

                            # Sleek dynamic velocity vector arrow
                            if spd > 0.3:
                                arrow_len = max(16.0 * S, spd * 1.8 * S)
                                vx = int(round(tx + arrow_len * math.cos(heading)))
                                vy = int(round(ty - arrow_len * math.sin(heading)))
                                cv2.arrowedLine(
                                    display_world,
                                    (tx, ty),
                                    (vx, vy),
                                    (250, 204, 21),
                                    max(1, int(round(1.2 * S))),
                                    cv2.LINE_AA,
                                    tipLength=0.25,
                                )

                    # Feature 3: Dynamic Optical Link State & Photon Stream
                    if camera is not None and active_target_pos is not None:
                        if getattr(snapshot, "fov_center_disturbed", None) is not None:
                            cx, cy = snapshot.fov_center_disturbed
                        else:
                            cx, cy = camera.get_fov_center_world()
                        icx, icy = int(round(cx)), int(round(cy))
                        atx, aty = active_target_pos

                        if getattr(snapshot, "fov_rect_disturbed", None) is not None:
                            x0, y0, x1, y1 = snapshot.fov_rect_disturbed
                        else:
                            x0, y0, x1, y1 = camera.get_fov_rect()
                        in_fov = (x0 <= atx <= x1) and (y0 <= aty <= y1)

                        # Extract tracking error from PID telemetry
                        pid_tel = getattr(snapshot, "pid_telemetry", None)
                        err_px_val = 999.0
                        if pid_tel and isinstance(pid_tel, dict):
                            epx = float(pid_tel.get("error_pan_px", 0.0))
                            epy = float(pid_tel.get("error_tilt_px", 0.0))
                            err_px_val = math.hypot(epx, epy)

                        is_locked = in_fov and (err_px_val <= 10.0)

                        if is_locked:
                            # Coarse Alignment Locked (PAT Spec <= 10px): Solid emerald link with dynamic photon flow
                            cv2.line(display_world, (icx, icy), (atx, aty), (74, 222, 128), max(1, int(round(1.5 * S))), cv2.LINE_AA)

                            # Dynamic streaming photon packets
                            for j in range(3):
                                t_pkt = ((frame_id * 0.04 + j / 3.0) % 1.0)
                                px = int(round(icx + t_pkt * (atx - icx)))
                                py = int(round(icy + t_pkt * (aty - icy)))
                                cv2.circle(display_world, (px, py), max(1, int(round(1.8 * S))), (255, 255, 255), -1, cv2.LINE_AA)

                            # Sleek corner lock brackets around target
                            bl = int(round(4 * S))
                            tr = int(round(8 * S))
                            cv2.line(display_world, (atx - tr, aty - tr), (atx - tr + bl, aty - tr), (74, 222, 128), max(1, int(round(1.0 * S))), cv2.LINE_AA)
                            cv2.line(display_world, (atx - tr, aty - tr), (atx - tr, aty - tr + bl), (74, 222, 128), max(1, int(round(1.0 * S))), cv2.LINE_AA)
                            cv2.line(display_world, (atx + tr, aty - tr), (atx + tr - bl, aty - tr), (74, 222, 128), max(1, int(round(1.0 * S))), cv2.LINE_AA)
                            cv2.line(display_world, (atx + tr, aty - tr), (atx + tr, aty - tr + bl), (74, 222, 128), max(1, int(round(1.0 * S))), cv2.LINE_AA)
                            cv2.line(display_world, (atx - tr, aty + tr), (atx - tr + bl, aty + tr), (74, 222, 128), max(1, int(round(1.0 * S))), cv2.LINE_AA)
                            cv2.line(display_world, (atx - tr, aty + tr), (atx - tr, aty + tr - bl), (74, 222, 128), max(1, int(round(1.0 * S))), cv2.LINE_AA)
                            cv2.line(display_world, (atx + tr, aty + tr), (atx + tr - bl, aty + tr), (74, 222, 128), max(1, int(round(1.0 * S))), cv2.LINE_AA)
                            cv2.line(display_world, (atx + tr, aty + tr), (atx + tr, aty + tr - bl), (74, 222, 128), max(1, int(round(1.0 * S))), cv2.LINE_AA)

                        elif in_fov:
                            # Acquired inside FOV: Solid cyan link with cyan photon packet
                            cv2.line(display_world, (icx, icy), (atx, aty), (56, 189, 248), max(1, int(round(1.2 * S))), cv2.LINE_AA)
                            t_pkt = ((frame_id * 0.03) % 1.0)
                            px = int(round(icx + t_pkt * (atx - icx)))
                            py = int(round(icy + t_pkt * (aty - icy)))
                            cv2.circle(display_world, (px, py), max(1, int(round(1.5 * S))), (56, 189, 248), -1, cv2.LINE_AA)

                        else:
                            # Searching (Out of FOV): Faint dotted line
                            link_dist = math.hypot(atx - icx, aty - icy)
                            if link_dist > 1.0:
                                dot_step = max(14, int(round(14 * S)))
                                num_dots = int(link_dist / dot_step)
                                for d_idx in range(1, num_dots):
                                    t_d = d_idx / float(num_dots)
                                    dx = int(round(icx + t_d * (atx - icx)))
                                    dy = int(round(icy + t_d * (aty - icy)))
                                    cv2.circle(display_world, (dx, dy), max(1, int(round(1.0 * S))), (100, 130, 160), -1, cv2.LINE_AA)

                    # Downsample 2000x2000 -> 800x600 for display (6x smaller, 5ms saved)
                    try:
                        display_small = cv2.resize(display_world, (800, 600), interpolation=cv2.INTER_AREA)
                    except Exception:
                        display_small = display_world
                    pm_world = frame_to_pixmap(display_small)
                    if pm_world is not None:
                        pm_world, self._world_pixmap_size = self._scale_for_label(pm_world, self.world_label, self._world_pixmap_size)
                        self.world_label.setPixmap(pm_world)
                        try:
                            self._cached_god_pixmap = pm_world
                        except Exception:
                            pass
                except Exception as e:
                    log.warning("God screen render failed: %s", e)

        # 3. Update telemetry badges on header if present
        # 3. Update telemetry badges on header if present
        try:
            cam_tel = getattr(snapshot, "camera_telemetry", None)
            pid_tel = getattr(snapshot, "pid_telemetry", None)
            if cam_tel and isinstance(cam_tel, dict) and self.lbl_cam_telemetry is not None:
                ptz = cam_tel.get("ptz", {})
                pan = float(ptz.get("pan_deg", 0.0))
                tilt = float(ptz.get("tilt_deg", 0.0))
                self.lbl_cam_telemetry.setText(f"Pan: {pan:+.2f}° | Tilt: {tilt:+.2f}°")

            if pid_tel and isinstance(pid_tel, dict) and self.lbl_cam_err is not None:
                err_px = float(pid_tel.get("error_pan_px", 0.0))
                err_py = float(pid_tel.get("error_tilt_px", 0.0))
                dist_px = (err_px ** 2 + err_py ** 2) ** 0.5
                self.lbl_cam_err.setText(f"Err: {dist_px:.1f} px")

            wsz = getattr(snapshot, "world_size", None)
            if wsz is not None and self.lbl_world_sub is not None:
                self.lbl_world_sub.setText(f"{int(wsz[0])}×{int(wsz[1])} World Scene")
        except Exception as e:
            log.debug("SimulationView telemetry update skipped: %s", e)

    def invalidate_world_cache(self) -> None:
        self._fov_pixmap_size = None
        self._world_pixmap_size = None
        self._trajectory_history.clear()

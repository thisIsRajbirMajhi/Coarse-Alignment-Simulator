# gui/windows/fov_window.py - Dedicated Camera FOV Viewport Window.
from __future__ import annotations

import logging
from typing import Any

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from gui.core.frame_presenter import frame_to_pixmap
from gui.core.renderer import Renderer
from gui.theme import apply_theme

log = logging.getLogger(__name__)


class FOVWindow(QMainWindow):
    """
    Dedicated window for the virtual PTZ Camera FOV viewport.
    
    Features:
    - Fixed 640 x 480 native resolution viewport per requirements
    - Monochrome camera feed with boresight crosshairs and tracker overlay
    - Real-time telemetry status strip (Pan/Tilt angles, rates, tracking error, PID mode)
    - Fullscreen toggle and safe hide-on-close
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Camera FOV Viewport — 640×480 Monochrome")
        self.setMinimumSize(660, 560)
        self.resize(680, 580)
        apply_theme(self)
        self._fullscreen = False

        central = QWidget(self)
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(8)

        # Header Bar
        header = QWidget(self)
        header.setObjectName("headerBar")
        hbox = QHBoxLayout(header)
        hbox.setContentsMargins(10, 6, 10, 6)
        hbox.setSpacing(10)

        title_col = QVBoxLayout()
        title_col.setSpacing(1)
        title = QLabel("CAMERA FOV VIEWPORT", header)
        title.setObjectName("appTitle")
        title.setStyleSheet("font-size:14px; font-weight:700; color:#38bdf8; font-family:'Segoe UI',system-ui,sans-serif;")
        title_col.addWidget(title)

        subtitle = QLabel("640×480 Native • Monochrome FPA", header)
        subtitle.setStyleSheet("font-size:11px; color:#94a3b8; font-family:'Segoe UI',system-ui,sans-serif;")
        title_col.addWidget(subtitle)
        hbox.addLayout(title_col)

        hbox.addStretch(1)

        # Live telemetry pills
        self.lbl_pan_tilt = QLabel("Pan: 0.0° | Tilt: 0.0°", header)
        self.lbl_pan_tilt.setStyleSheet(
            "color:#e2e8f0; font-family:'Consolas','Fira Code','Courier New',monospace; font-size:11px; font-weight:600; "
            "background:#1e293b; border:1px solid #334155; border-radius:4px; padding:3px 8px;"
        )
        hbox.addWidget(self.lbl_pan_tilt)

        self.lbl_err = QLabel("Err: 0.0 px", header)
        self.lbl_err.setStyleSheet(
            "color:#38bdf8; font-family:'Consolas','Fira Code','Courier New',monospace; font-size:11px; font-weight:700; "
            "background:#1e293b; border:1px solid #334155; border-radius:4px; padding:3px 8px;"
        )
        hbox.addWidget(self.lbl_err)

        self.lbl_mode = QLabel("AUTO", header)
        self.lbl_mode.setStyleSheet(
            "color:#4ade80; font-weight:700; font-size:11px; "
            "background:#14532d; border:1px solid #16a34a; border-radius:4px; padding:3px 8px;"
        )
        hbox.addWidget(self.lbl_mode)

        self.btn_fullscreen = QPushButton("Full Screen", header)
        self.btn_fullscreen.setObjectName("settingsButton")
        self.btn_fullscreen.setMinimumHeight(28)
        self.btn_fullscreen.clicked.connect(self.toggle_fullscreen)
        hbox.addWidget(self.btn_fullscreen)

        self.btn_close = QPushButton("Close", header)
        self.btn_close.setObjectName("resetButton")
        self.btn_close.setMinimumHeight(28)
        self.btn_close.clicked.connect(self.hide)
        hbox.addWidget(self.btn_close)

        root.addWidget(header)

        # Viewport Container (centers the fixed 640x480 display)
        viewport_container = QWidget(self)
        viewport_layout = QHBoxLayout(viewport_container)
        viewport_layout.setContentsMargins(0, 0, 0, 0)
        viewport_layout.setAlignment(Qt.AlignCenter)

        self.fov_label = QLabel("Waiting for camera feed...", viewport_container)
        self.fov_label.setObjectName("fovView")
        self.fov_label.setFixedSize(640, 480)
        self.fov_label.setAlignment(Qt.AlignCenter)
        self.fov_label.setStyleSheet("background:#000000; color:#64748b; border:2px solid #334155; border-radius:4px;")
        viewport_layout.addWidget(self.fov_label)

        root.addWidget(viewport_container, 1)

    def toggle_fullscreen(self) -> None:
        try:
            if self._fullscreen or self.isFullScreen():
                self._fullscreen = False
                self.showNormal()
                self.btn_fullscreen.setText("Full Screen")
            else:
                self._fullscreen = True
                self.showFullScreen()
                self.btn_fullscreen.setText("Exit Full Screen")
        except Exception as e:
            log.debug("fov window fullscreen toggle failed: %s", e)

    def render_snapshot(self, snapshot: Any, session: Any = None) -> None:
        """Render the camera FOV frame and update telemetry badges."""
        if snapshot is None:
            return

        # Retrieve or extract FOV frame
        fov_frame = getattr(snapshot, "fov_frame", None)
        if fov_frame is None and session is not None and hasattr(session, "camera"):
            world_frame = getattr(snapshot, "world_frame", None)
            if world_frame is not None:
                fov_frame = session.camera.extract_fov(world_frame)

        if fov_frame is not None:
            try:
                # Render reticle, tactical target markers, and HUD overlays
                overlayed = Renderer.render_viewport(
                    fov_frame,
                    camera=getattr(session, "camera", None),
                    telemetry=getattr(snapshot, "terminals", None),
                    camera_telemetry=getattr(snapshot, "camera_telemetry", None),
                    pid_telemetry=getattr(snapshot, "pid_telemetry", None),
                )
                pm = frame_to_pixmap(overlayed)
                if pm is not None:
                    self.fov_label.setPixmap(pm)
            except Exception as e:
                log.warning("FOV window render failed: %s", e)

        # Update telemetry badges
        try:
            cam_tel = getattr(snapshot, "camera_telemetry", None)
            pid_tel = getattr(snapshot, "pid_telemetry", None)

            if cam_tel and isinstance(cam_tel, dict):
                ptz = cam_tel.get("ptz", {})
                pan = float(ptz.get("pan_deg", 0.0))
                tilt = float(ptz.get("tilt_deg", 0.0))
                self.lbl_pan_tilt.setText(f"Pan: {pan:+.2f}° | Tilt: {tilt:+.2f}°")

            if pid_tel and isinstance(pid_tel, dict):
                err_px = float(pid_tel.get("error_pan_px", 0.0))
                err_py = float(pid_tel.get("error_tilt_px", 0.0))
                dist_px = (err_px ** 2 + err_py ** 2) ** 0.5
                self.lbl_err.setText(f"Err: {dist_px:.1f} px")

                mode = str(pid_tel.get("mode", "AUTO")).upper()
                self.lbl_mode.setText(mode)
                if mode == "AUTO":
                    self.lbl_mode.setStyleSheet(
                        "color:#4ade80; font-weight:700; font-size:10px; "
                        "background:#14532d; border:1px solid #16a34a; border-radius:4px; padding:3px 8px;"
                    )
                elif mode == "MANUAL":
                    self.lbl_mode.setStyleSheet(
                        "color:#facc15; font-weight:700; font-size:10px; "
                        "background:#713f12; border:1px solid #ca8a04; border-radius:4px; padding:3px 8px;"
                    )
                else:
                    self.lbl_mode.setStyleSheet(
                        "color:#94a3b8; font-weight:700; font-size:10px; "
                        "background:#1e293b; border:1px solid #475569; border-radius:4px; padding:3px 8px;"
                    )
        except Exception as e:
            log.debug("FOV telemetry update skipped: %s", e)

    def closeEvent(self, event) -> None:  # noqa: N802
        try:
            event.ignore()
            self.hide()
        except Exception:
            super().closeEvent(event)

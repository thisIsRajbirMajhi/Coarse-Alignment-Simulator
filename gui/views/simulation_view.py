# gui/views/simulation_view.py - Pure views: FOV + world panels. No sim access.
from __future__ import annotations

import logging

import cv2
from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QLabel, QSizePolicy, QSplitter, QVBoxLayout, QWidget

from gui.core.frame_presenter import frame_to_pixmap
from gui.core.renderer import Renderer

log = logging.getLogger(__name__)


class SimulationView(QWidget):
    """Two video surfaces. Receives snapshots/overlays from MainWindow."""

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        splitter = QSplitter(Qt.Horizontal, self)
        splitter.setObjectName("simSplitter")
        self.fov_label = QLabel("FOV — press Start")
        self.fov_label.setObjectName("fovView")
        self.fov_label.setAlignment(Qt.AlignCenter)
        self.fov_label.setMinimumSize(320, 240)
        self.fov_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.fov_label.setStyleSheet("background:black; color:#888; border-radius:12px;")
        self.world_label = QLabel("World")
        self.world_label.setObjectName("worldView")
        self.world_label.setAlignment(Qt.AlignCenter)
        self.world_label.setMinimumSize(320, 240)
        self.world_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.world_label.setStyleSheet("background:black; color:#888; border-radius:12px;")
        splitter.addWidget(self.fov_label)
        splitter.addWidget(self.world_label)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 1)
        layout.addWidget(splitter)
        self._world_thumb = None
        self._world_thumb_key = None

    def render_snapshot(self, snapshot, session) -> None:
        if snapshot is None or session is None:
            return
        # FOV overlay via stateless Renderer (view support, not sim).
        try:
            fov = snapshot.fov_frame.copy() if snapshot.fov_frame is not None else None
            if fov is not None:
                overlay = Renderer.render_viewport(
                    fov, session.camera, session.beacons, session.target,
                    tracker=None, all_dets=snapshot.all_detections,
                    estimate=snapshot.estimate, lock_status=snapshot.lock_state,
                )
                pm = frame_to_pixmap(overlay)
                if pm is not None:
                    self.fov_label.setPixmap(pm.scaled(
                        self.fov_label.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation))
        except Exception as e:
            log.warning("FOV render failed: %s", e)
        # World/minimap: cached raw thumb + overlays.
        try:
            try:
                bg = session.scene._static_background
            except Exception:
                bg = None
            if bg is None:
                try:
                    bg = session.scene.get_frame()
                except Exception as e:
                    log.debug("world background unavailable: %s", e)
                    bg = None
            if bg is not None:
                lw = self.world_label.width() if self.world_label.width() > 10 else 400
                lh = self.world_label.height() if self.world_label.height() > 10 else 300
                world_size = (int(session.env_config.world_width), int(session.env_config.world_height))
                key = (lw, lh, id(bg))
                if self._world_thumb is None or self._world_thumb_key != key:
                    self._world_thumb = cv2.resize(bg, (max(50, lw), max(50, lh)), interpolation=cv2.INTER_AREA)
                    self._world_thumb_key = key
                mini = Renderer.render_minimap_cached(
                    self._world_thumb, session.camera, session.beacons, session.target,
                    tracker=None, label_size=(max(50, lw), max(50, lh)),
                    scene_size=world_size, estimate=snapshot.estimate,
                    lock_status=snapshot.lock_state,
                )
                pm2 = frame_to_pixmap(mini)
                if pm2 is not None:
                    self.world_label.setPixmap(pm2.scaled(
                        self.world_label.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation))
        except Exception as e:
            log.warning("world render failed: %s", e)

    def invalidate_world_cache(self) -> None:
        self._world_thumb = None
        self._world_thumb_key = None

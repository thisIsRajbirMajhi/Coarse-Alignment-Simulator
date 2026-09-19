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
    """Two video surfaces: FOV and Minimap. Receives snapshots/overlays from MainWindow."""

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
        self._world_pixmap = None
        self._world_pixmap_key = None
        self._fov_size = None
        self._world_size = None

    @staticmethod
    def _scale_for_label(pm, label, last_size):
        """Fit pixmap into label: Smooth only on resize, Fast every tick.

        SmoothTransformation each tick is a full-frame resample; live video is
        visually identical with FastTransformation once the size is stable.
        Returns (pixmap, size).
        """
        size = label.size()
        key = (size.width(), size.height())
        if key != last_size:
            return pm.scaled(size, Qt.KeepAspectRatio, Qt.SmoothTransformation), key
        return pm.scaled(size, Qt.KeepAspectRatio, Qt.FastTransformation), key

    @staticmethod
    def _minimap_key(camera, label_size, terminals) -> tuple:
        """Cheap cache key for minimap overlays (pose + size + beacon spots)."""
        try:
            rect = tuple(int(v) for v in camera.get_fov_rect())
        except Exception:
            rect = (0, 0, 0, 0)
        spots: list[tuple] = []
        try:
            term_list = (terminals or {}).get("terminals", []) if isinstance(terminals, dict) else []
            for t in term_list:
                pos = t.get("position", (0, 0, 0))
                spots.append((str(t.get("id", "RT")), int(pos[0]), int(pos[1]), bool(t.get("is_emitting", False))))
        except Exception:
            pass
        return (rect, tuple(label_size), tuple(spots))

    def render_snapshot(self, snapshot, session) -> None:
        if snapshot is None or session is None:
            return
        # FOV overlay via stateless Renderer. No outer .copy() — the renderer
        # copies internally (headless shares that path and needs it).
        try:
            fov = snapshot.fov_frame
            if fov is not None:
                overlay = Renderer.render_viewport(
                    fov, session.camera,
                    telemetry=getattr(snapshot, "local_terminal", None))
                pm = frame_to_pixmap(overlay)
                if pm is not None:
                    pm, self._fov_size = self._scale_for_label(pm, self.fov_label, self._fov_size)
                    self.fov_label.setPixmap(pm)
        except Exception as e:
            log.warning("FOV render failed: %s", e)

        # World/minimap: cached raw thumb + overlays.
        try:
            try:
                bg = session.scene._static_background
            except Exception:
                bg = None
            if bg is None:
                # Never build a full scene in the hot loop — reuse last thumb.
                if self._world_thumb is None:
                    log.debug("world background unavailable, no cached thumb")
                bg = None
            if bg is not None:
                lw = self.world_label.width() if self.world_label.width() > 10 else 400
                lh = self.world_label.height() if self.world_label.height() > 10 else 300
                world_size = (int(session.env_config.world_width), int(session.env_config.world_height))
                key = (lw, lh, id(bg))
                if self._world_thumb is None or self._world_thumb_key != key:
                    self._world_thumb = cv2.resize(bg, (max(50, lw), max(50, lh)), interpolation=cv2.INTER_AREA)
                    self._world_thumb_key = key
                    self._world_pixmap_key = None  # thumb changed → overlays stale
            if self._world_thumb is not None:
                lw = self.world_label.width() if self.world_label.width() > 10 else 400
                lh = self.world_label.height() if self.world_label.height() > 10 else 300
                world_size = (int(session.env_config.world_width), int(session.env_config.world_height))
                terminals = getattr(snapshot, "terminals", None)
                mkey = self._minimap_key(session.camera, (max(50, lw), max(50, lh)), terminals)
                if self._world_pixmap is None or self._world_pixmap_key != mkey:
                    mini = Renderer.render_minimap_cached(
                        self._world_thumb, session.camera,
                        label_size=(max(50, lw), max(50, lh)),
                        scene_size=world_size,
                        terminals=terminals,
                    )
                    pm2 = frame_to_pixmap(mini)
                    if pm2 is not None:
                        pm2, self._world_size = self._scale_for_label(pm2, self.world_label, self._world_size)
                        self._world_pixmap = pm2
                        self._world_pixmap_key = mkey
                if self._world_pixmap is not None:
                    self.world_label.setPixmap(self._world_pixmap)
        except Exception as e:
            log.warning("world render failed: %s", e)

    def invalidate_world_cache(self) -> None:
        self._world_thumb = None
        self._world_thumb_key = None
        self._world_pixmap = None
        self._world_pixmap_key = None

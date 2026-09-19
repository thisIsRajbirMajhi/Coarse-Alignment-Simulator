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
    """Single unified simulation viewport showing the world scene with remote optical beacons."""

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.view_label = QLabel("Simulation View — press Start")
        self.view_label.setObjectName("simView")
        self.view_label.setAlignment(Qt.AlignCenter)
        self.view_label.setMinimumSize(480, 360)
        self.view_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.view_label.setStyleSheet("background:black; color:#888; border-radius:12px;")
        layout.addWidget(self.view_label)

        # Backward compatibility aliases for existing tests and references
        self.fov_label = self.view_label
        self.world_label = self.view_label

        self._pixmap = None
        self._pixmap_size = None

    @staticmethod
    def _scale_for_label(pm, label, last_size):
        """Fit pixmap into label: Smooth only on resize, Fast every tick.

        Returns (pixmap, size).
        """
        size = label.size()
        key = (size.width(), size.height())
        if key != last_size:
            return pm.scaled(size, Qt.KeepAspectRatio, Qt.SmoothTransformation), key
        return pm.scaled(size, Qt.KeepAspectRatio, Qt.FastTransformation), key

    def render_snapshot(self, snapshot, session) -> None:
        if snapshot is None:
            return
        frame = getattr(snapshot, "world_frame", None)
        if frame is None:
            frame = getattr(snapshot, "fov_frame", None)
        if frame is None:
            return
        try:
            pm = frame_to_pixmap(frame)
            if pm is not None:
                pm, self._pixmap_size = self._scale_for_label(pm, self.view_label, self._pixmap_size)
                self.view_label.setPixmap(pm)
        except Exception as e:
            log.warning("Simulation view render failed: %s", e)

    def invalidate_world_cache(self) -> None:
        self._pixmap = None
        self._pixmap_size = None


# gui/core/frame_presenter.py - NumPy/OpenCV -> QPixmap (view support, no sim logic).
from __future__ import annotations

import numpy as np
from PyQt5.QtGui import QImage, QPixmap


def frame_to_pixmap(frame: np.ndarray | None) -> QPixmap | None:
    """Zero-extra-copy NumPy BGR -> QPixmap.

    The QImage borrows the numpy buffer without copying; QPixmap.fromImage()
    copies synchronously while the array is still alive, so no .copy() is
    needed (was 1 full-frame memcpy per view per tick).
    """
    if frame is None:
        return None
    try:
        arr = np.ascontiguousarray(frame)
        if arr.dtype != np.uint8:
            arr = np.clip(arr, 0, 255).astype(np.uint8)
        h, w = arr.shape[:2]
        if arr.ndim == 2:
            qimg = QImage(arr.data, w, h, w, QImage.Format_Grayscale8)
        else:
            import cv2
            rgb = cv2.cvtColor(arr, cv2.COLOR_BGR2RGB)
            rgb = np.ascontiguousarray(rgb)
            qimg = QImage(rgb.data, w, h, 3 * w, QImage.Format_RGB888)
        return QPixmap.fromImage(qimg)
    except Exception:
        return None

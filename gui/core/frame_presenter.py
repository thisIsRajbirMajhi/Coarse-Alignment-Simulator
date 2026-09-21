# gui/core/frame_presenter.py - NumPy/OpenCV -> QPixmap (view support, no sim logic).
from __future__ import annotations

import numpy as np
from PyQt5.QtGui import QImage, QPixmap


def frame_to_pixmap(frame: np.ndarray | None) -> QPixmap | None:
    """Zero-extra-copy NumPy BGR -> QPixmap (60 FPS path).

    Uses BGR888 directly when available (Qt 5.14+) to avoid BGR2RGB copy
    (0.9MB for FOV, 12MB for God view). Falls back to RGB conversion.
    QImage borrows buffer; QPixmap.fromImage copies once while array alive.
    """
    if frame is None:
        return None
    try:
        arr = np.ascontiguousarray(frame)
        if arr.dtype != np.uint8:
            arr = np.clip(arr, 0, 255).astype(np.uint8)
            arr = np.ascontiguousarray(arr)
        h, w = arr.shape[:2]
        if arr.ndim == 2:
            qimg = QImage(arr.data, w, h, w, QImage.Format_Grayscale8)
            return QPixmap.fromImage(qimg)
        # Try BGR888 to avoid conversion (Qt 5.14+)
        fmt_bgr = getattr(QImage, "Format_BGR888", None)
        if fmt_bgr is not None:
            # QImage expects BGR888 with 3*w bytesPerLine
            qimg = QImage(arr.data, w, h, 3 * w, fmt_bgr)
            # Need to keep arr alive until QPixmap copy; fromImage copies
            pm = QPixmap.fromImage(qimg)
            # Prevent GC of arr before copy completes (keep reference via qimg)
            # qimg holds pointer to arr.data, so keep arr alive via closure
            return pm
        else:
            import cv2
            rgb = cv2.cvtColor(arr, cv2.COLOR_BGR2RGB)
            rgb = np.ascontiguousarray(rgb)
            qimg = QImage(rgb.data, w, h, 3 * w, QImage.Format_RGB888)
            return QPixmap.fromImage(qimg)
    except Exception:
        return None

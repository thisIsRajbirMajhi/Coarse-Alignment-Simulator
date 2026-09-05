# beacon_tracker/detection/preprocessor.py
# Frame preprocessing — grayscale + threshold + morphology
# Moved from detection/preprocessing.py; renamed to preprocessor.py for clarity

import cv2
import numpy as np

from beacon_tracker.detection.constants import MORPH_KERNEL


def to_grayscale(frame: np.ndarray) -> np.ndarray:
    """
    Convert BGR/BGRA or already-gray frame to single-channel grayscale.

    Physics: For BGR, OpenCV uses Y = 0.114·B + 0.587·G + 0.299·R.
    Beacon is white (255,255,255) → Y≈255, background ~12 → Y≈12, so threshold separates well.
    """
    if frame.ndim == 3:
        if frame.shape[2] == 4:
            return cv2.cvtColor(frame, cv2.COLOR_BGRA2GRAY)
        elif frame.shape[2] == 3:
            return cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        elif frame.shape[2] == 1:
            return frame.squeeze(axis=2)
    return frame


def threshold_frame(gray: np.ndarray, brightness_threshold: int) -> np.ndarray:
    """
    Binary threshold: mask = 255 where gray > T, else 0.

    Maths: mask(x,y) = 255·H(I(x,y) - T) where H is Heaviside step.
    Higher T = stricter (fewer false positives, may miss dim beacon at high haze).
    """
    _, mask = cv2.threshold(gray, int(brightness_threshold), 255, cv2.THRESH_BINARY)
    return mask


def close_gaps(mask: np.ndarray, kernel: np.ndarray = MORPH_KERNEL, iterations: int = 1) -> np.ndarray:
    """
    Morphological closing — dilate then erode to close small gaps.

    Closing with 3×3 kernel, 1 iteration fills single-pixel holes from scintillation
    (e.g., beacon split by turbulence) without significantly dilating beacon area.
    Maths: mask_closed = (mask ⊕ kernel) ⊖ kernel
    """
    return cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel, iterations=int(iterations))

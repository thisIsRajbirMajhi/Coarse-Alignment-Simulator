"""
Module: detection.preprocessing
Purpose: Frame preprocessing — grayscale + threshold + morphology (well-commented physics).
Public API: to_grayscale, threshold_frame, close_gaps
Notes: Stateless helpers used by BeaconDetector. Each step documented with maths.

Maths:
  Grayscale: Y = 0.299·R + 0.587·G + 0.114·B (OpenCV BGR→GRAY)
  Threshold: mask(x,y) = 255 if I(x,y) > T else 0  (binary segmentation)
  Closing:   mask_closed = dilate(erode(mask)) with 3×3 kernel — fills 1-px holes
             from scintillation without merging separate beacons.
"""

import cv2
import numpy as np

from detection.constants import MORPH_KERNEL

# ============================================================
# SECTION: Preprocessing — grayscale + threshold + morphology
# ============================================================

def to_grayscale(frame: np.ndarray) -> np.ndarray:
    """
    Convert BGR or already-gray frame to single-channel grayscale.

    Physics: For BGR, OpenCV uses Y = 0.114·B + 0.587·G + 0.299·R.
    Beacon is white (255,255,255) → Y≈255, background ~12 → Y≈12, so threshold separates well.
    """
    if frame.ndim == 3:
        return cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
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

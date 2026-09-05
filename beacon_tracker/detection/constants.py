# beacon_tracker/detection/constants.py
# Single source for detector limits & defaults — moved from detection/constants.py

import numpy as np

DETECTOR_LIMITS: dict[str, tuple[int, int]] = {
    # Brightness threshold — binary segmentation T in I(x,y) > T
    # Higher T = stricter (fewer false positives, may miss dim beacon)
    "brightness_threshold": (0, 255),
    # Minimum contour area — rejects single-pixel noise (px²)
    "min_area": (1, 50),
    # Max beacons reported per frame
    "max_beacons": (1, 20),
}

DETECTOR_DEFAULTS: dict = {
    "brightness_threshold": 200,  # 200/255 ≈ 78% brightness — bright beacon on dim background
    "min_area": 2,                # 2 px² — rejects isolated pixels
    "max_beacons": 12,
}

# Morphology kernel for closing small gaps from scintillation
# 3×3 ones, MORPH_CLOSE, 1 iteration — fills 1-px holes without dilating beacon
MORPH_KERNEL = np.ones((3, 3), np.uint8)

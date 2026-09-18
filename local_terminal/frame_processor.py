# local_terminal/frame_processor.py - Module 2: Frame Processor (§6).
from __future__ import annotations

import numpy as np

from local_terminal.models import CameraFrame, ProcessedFrame


class FrameProcessor:
    """CameraFrame -> ProcessedFrame. Never destroys the raw frame.

    Performs optional denoise (3x3 median approx via box blur residual),
    background estimation (median), subtraction, normalization.
    Bounded per-frame work only (§34).
    """

    def __init__(self, denoise: bool = True):
        self.denoise = bool(denoise)

    def process(self, frame: CameraFrame | None) -> ProcessedFrame | None:
        if frame is None or not frame.valid():
            return None
        try:
            arr = np.asarray(frame.image)
            if arr.size == 0:
                return None
            if arr.ndim == 3:
                gray = arr[..., :3].astype(np.float32).mean(axis=2)
            elif arr.ndim == 2:
                gray = arr.astype(np.float32)
            else:
                return None
            bg = float(np.median(gray))
            noise = float(np.median(np.abs(gray - bg)) * 1.4826)
            noise = max(1.0, noise)
            proc = gray - bg
            if self.denoise:
                # Cheap 3x3 box smoothing to suppress single-pixel spikes,
                # then keep max(original, smoothed) residual detail.
                try:
                    import cv2
                    smooth = cv2.blur(proc, (3, 3))
                    proc = np.maximum(proc, smooth)
                except Exception:
                    pass
            proc = np.clip(proc, 0, 255).astype(np.float32)
            return ProcessedFrame(timestamp=float(frame.timestamp), raw_image=arr,
                                  background_estimate=bg, processed_image=proc,
                                  noise_estimate=noise)
        except Exception:
            return None

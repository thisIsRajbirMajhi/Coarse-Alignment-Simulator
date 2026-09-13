# gui/core/photon_renderer.py - Qt-free beacon photon rendering onto FOV frames.
# Extracted from legacy RenderingMixin._draw_targets_fov; sim-owned (photon-level),
# NOT widget logic. Session calls this; views never do.
from __future__ import annotations

import logging

import cv2
import numpy as np

from gui.core.renderer import Renderer

log = logging.getLogger(__name__)


def draw_beacon_patches(fov_frame: np.ndarray, beacons, env_config=None,
                        disturbance_config=None, fov_x0: int = 0, fov_y0: int = 0) -> None:
    """Alpha-blend realistic beacon patches onto fov_frame in place."""
    h, w = fov_frame.shape[:2]
    fog_factor = 0.0
    bloom_base = 0.0
    try:
        if env_config is not None:
            fog_factor = float(getattr(env_config, "haze_pct", 0)) / 100.0 * 0.55
        if disturbance_config is not None:
            preset = str(getattr(disturbance_config, "atmospheric_preset", "Clear")).lower()
            if preset == "fog":
                fog_factor = max(fog_factor, 0.45 + float(getattr(disturbance_config, "atmospheric_contrast", 0)) / 220.0)
                bloom_base = 0.10
            elif preset == "haze":
                fog_factor = max(fog_factor, 0.18)
    except Exception as e:
        log.debug("fog factor fallback: %s", e)
    fog_factor = float(np.clip(fog_factor, 0.0, 0.85))

    for beacon in beacons or []:
        if not getattr(beacon, "enabled", True):
            continue
        if getattr(beacon, "blinking", False) and not getattr(beacon, "_blink_visible", True):
            continue
        try:
            px = float(beacon.x) - float(fov_x0)
            py = float(beacon.y) - float(fov_y0)
        except Exception as e:
            log.debug("beacon position unreadable, skipping: %s", e)
            continue
        if px < -40 or px > w + 40 or py < -40 or py > h + 40:
            continue
        try:
            brightness, radius = beacon.get_photometry()
        except Exception:
            brightness, radius = float(getattr(beacon, "brightness", 200)), float(getattr(beacon, "radius", 5))
        if brightness < 8:
            continue
        shape = str(getattr(beacon, "shape", "square"))
        size_w = int(getattr(beacon, "size_w", 10))
        size_h = int(getattr(beacon, "size_h", 10))
        motion_vector = (0.0, 0.0)
        bloom_strength = float(bloom_base)
        jitter_px = 0.0
        color_bgr = None
        try:
            if hasattr(beacon, "get_optics_params"):
                opt = beacon.get_optics_params()
                motion_vector = tuple(opt.get("motion_vector", (0.0, 0.0)))
                bloom_strength = max(bloom_strength, float(opt.get("bloom_strength", 0.0)))
                jitter_px = float(opt.get("aoa_jitter", 0.0)) * 0.25
                bid = int(opt.get("beacon_id", 0))
                try:
                    from target.optics import get_beacon_color_bgr
                    color_bgr = get_beacon_color_bgr(bid, float(brightness))
                except Exception as e:
                    log.debug("beacon color fallback: %s", e)
            if float(brightness) > 210 and fog_factor > 0.2:
                bloom_strength += 0.06
        except Exception as e:
            log.debug("optics params fallback: %s", e)

        rendered = False
        try:
            from target.optics import render_beacon_patch
            patch = render_beacon_patch(
                size_w=size_w, size_h=size_h, brightness=float(brightness),
                shape=shape, motion_vector=motion_vector,
                fog_factor=fog_factor, jitter_px=jitter_px,
                bloom_strength=float(np.clip(bloom_strength, 0, 0.28)),
                color_bgr=color_bgr,
            )
            ph, pw = patch.shape[:2]
            x0 = int(round(px - pw // 2))
            y0 = int(round(py - ph // 2))
            x1, y1 = x0 + pw, y0 + ph
            sx0, sy0 = max(0, x0), max(0, y0)
            sx1, sy1 = min(w, x1), min(h, y1)
            if sx1 > sx0 and sy1 > sy0:
                px0, py0 = sx0 - x0, sy0 - y0
                px1, py1 = px0 + (sx1 - sx0), py0 + (sy1 - sy0)
                patch_crop = patch[py0:py1, px0:px1]
                roi = fov_frame[sy0:sy1, sx0:sx1]
                alpha = np.clip(patch_crop.astype(np.float32) / 255.0 * 0.88 + 0.12, 0, 1)
                blended = roi.astype(np.float32) * (1 - alpha * 0.72) + patch_crop.astype(np.float32) * alpha
                bright_mask = patch_crop.max(axis=2) > 165 if patch_crop.ndim == 3 else patch_crop > 165
                if np.any(bright_mask):
                    if roi.ndim == 3:
                        blended[bright_mask] = np.maximum(blended[bright_mask], patch_crop[bright_mask].astype(np.float32) * 0.95)
                    else:
                        blended[bright_mask] = np.maximum(blended[bright_mask], patch_crop[bright_mask].astype(np.float32))
                fov_frame[sy0:sy1, sx0:sx1] = np.clip(blended, 0, 255).astype(np.uint8)
                rendered = True
        except Exception as e:
            log.debug("patch render failed, using fallback rect: %s", e)
            rendered = False

        if not rendered:
            ix, iy = int(round(px)), int(round(py))
            try:
                vib = Renderer.beacon_vibrant_color(int(getattr(beacon, "beacon_id", 0)), float(brightness))
            except Exception as e:
                log.debug("vibrant color fallback: %s", e)
                vib = (0, 255, 255)
            if shape == "square":
                hw, hh = size_w // 2, size_h // 2
                if max(size_w, size_h) > 6:
                    glow = tuple(int(c * 0.55) for c in vib)
                    cv2.rectangle(fov_frame, (ix - hw - 1, iy - hh - 1), (ix + hw + 1, iy + hh + 1), glow, -1, cv2.LINE_AA)
                cv2.rectangle(fov_frame, (ix - hw, iy - hh), (ix + hw, iy + hh), vib, -1, cv2.LINE_AA)
                cv2.rectangle(fov_frame, (ix - hw, iy - hh), (ix + hw, iy + hh), (255, 255, 255), 1, cv2.LINE_AA)
            else:
                r = max(1, int(round(max(size_w, size_h) / 2)) if size_w and size_h else int(round(radius)))
                if r > 3:
                    glow = tuple(int(c * 0.55) for c in vib)
                    cv2.circle(fov_frame, (ix, iy), r + 1, glow, -1, cv2.LINE_AA)
                cv2.circle(fov_frame, (ix, iy), max(1, r), vib, -1, cv2.LINE_AA)
                cv2.circle(fov_frame, (ix, iy), 1, (255, 255, 255), -1, cv2.LINE_AA)

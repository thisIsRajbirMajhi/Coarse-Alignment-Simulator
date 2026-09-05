# gui/mixins/rendering_mixin.py - Viewport/minimap rendering helpers
# Extracted from gui/main_window.py rendering section (300 lines).

import numpy as np
import cv2
from PyQt5.QtCore import Qt  # noqa
from PyQt5.QtGui import QImage, QPixmap  # noqa
from gui.core.renderer import Renderer, ScreenSpec  # noqa


class RenderingMixin:
    """Mixin: Delegates drawing to Renderer, manages minimap thumb cache."""

    def _beacon_vibrant_color(self, beacon_id: int, brightness: float) -> tuple[int,int,int]:
        return Renderer.beacon_vibrant_color(beacon_id, brightness)

    def _draw_targets(self, scene_frame: np.ndarray):
        Renderer.draw_targets(scene_frame, getattr(self, "beacons", [self.target]), self.target)

    def _draw_targets_fov(self, fov_frame: np.ndarray, fov_x0: int, fov_y0: int):
        """Draw beacon photometry onto a 640×640 FOV frame — realistic optics (Airy/Gaussian + streak + bloom)."""
        beacons = getattr(self, "beacons", [self.target]) if hasattr(self, "beacons") else [self.target]
        h, w = fov_frame.shape[:2]
        # Fog factor for optics: combine environment haze and atmospheric preset for size/bloom
        fog_factor = 0.0
        bloom_base = 0.0
        try:
            fog_factor = float(getattr(self.env_config, "haze_pct", 0)) / 100.0 * 0.55
            preset = str(getattr(self.disturbance_config, "atmospheric_preset", "Clear")).lower()
            if preset == "fog":
                fog_factor = max(fog_factor, 0.45 + float(getattr(self.disturbance_config, "atmospheric_contrast", 0)) / 220.0)
                bloom_base = 0.10
            elif preset == "haze":
                fog_factor = max(fog_factor, 0.18)
            elif "low light" in preset:
                bloom_base = 0.12
            elif preset == "rain":
                fog_factor = max(fog_factor, 0.12)
        except Exception:
            pass
        fog_factor = float(np.clip(fog_factor, 0.0, 0.85))

        for beacon in beacons:
            if not getattr(beacon, "enabled", True):
                continue
            if getattr(beacon, "blinking", False) and not getattr(beacon, "_blink_visible", True):
                continue
            try:
                px = float(beacon.x) - float(fov_x0)
                py = float(beacon.y) - float(fov_y0)
            except Exception:
                continue
            if px < -40 or px > w + 40 or py < -40 or py > h + 40:
                continue
            try:
                brightness, radius = beacon.get_photometry()
            except Exception:
                brightness, radius = float(getattr(beacon, "brightness", 200)), float(getattr(beacon, "radius", 5))
            if brightness < 8:
                continue  # eclipsed / deeply faded — invisible
            shape = str(getattr(beacon, "shape", "square"))
            size_w = int(getattr(beacon, "size_w", 10))
            size_h = int(getattr(beacon, "size_h", 10))
            # Optics params: motion streak, per-beacon bloom, AoA jitter
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
                    except Exception:
                        color_bgr = None
                # Scintillation-driven bloom: deeply scintillated bright beacons bloom more
                if float(brightness) > 210 and fog_factor > 0.2:
                    bloom_strength += 0.06
            except Exception:
                pass

            # Try realistic optics rendering — fallback to simple rectangle on failure
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
                # Center patch at (px, py) — handle clipping at FOV edges (partial visibility)
                x0 = int(round(px - pw // 2))
                y0 = int(round(py - ph // 2))
                x1 = x0 + pw
                y1 = y0 + ph
                # Intersection with FOV
                sx0 = max(0, x0); sy0 = max(0, y0)
                sx1 = min(w, x1); sy1 = min(h, y1)
                if sx1 > sx0 and sy1 > sy0:
                    # Source region in patch
                    px0 = sx0 - x0; py0 = sy0 - y0
                    px1 = px0 + (sx1 - sx0); py1 = py0 + (sy1 - sy0)
                    patch_crop = patch[py0:py1, px0:px1]
                    roi = fov_frame[sy0:sy1, sx0:sx1]
                    # Blend: max (additive light) — beacon is emissive
                    # Use lighten: result = max(roi, patch) with slight screen blend for halo
                    # For realistic optics, patch already includes background level (0..255), so
                    # we use alpha blend where patch brightens
                    alpha = (patch_crop.astype(np.float32) / 255.0 * 0.88 + 0.12)
                    alpha = np.clip(alpha, 0, 1)
                    # Emissive additive
                    blended = roi.astype(np.float32) * (1 - alpha * 0.72) + patch_crop.astype(np.float32) * alpha
                    # Keep at least patch where patch is very bright
                    bright_mask = patch_crop.max(axis=2) > 165 if patch_crop.ndim == 3 else patch_crop > 165
                    if np.any(bright_mask):
                        if roi.ndim == 3:
                            blended[bright_mask] = np.maximum(blended[bright_mask], patch_crop[bright_mask].astype(np.float32) * 0.95)
                        else:
                            blended[bright_mask] = np.maximum(blended[bright_mask], patch_crop[bright_mask].astype(np.float32))
                    fov_frame[sy0:sy1, sx0:sx1] = np.clip(blended, 0, 255).astype(np.uint8)
                    rendered = True
            except Exception:
                rendered = False

            if not rendered:
                # Fallback — prior simple rectangle/circle
                ix, iy = int(round(px)), int(round(py))
                try:
                    vib = Renderer.beacon_vibrant_color(int(getattr(beacon, "beacon_id", 0)), float(brightness))
                except Exception:
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
                        cv2.circle(fov_frame, (ix, iy), r+1, glow, -1, cv2.LINE_AA)
                    cv2.circle(fov_frame, (ix, iy), max(1, r), vib, -1, cv2.LINE_AA)
                    cv2.circle(fov_frame, (ix, iy), 1, (255, 255, 255), -1, cv2.LINE_AA)

    def _draw_target(self, scene_frame: np.ndarray):
        return self._draw_targets(scene_frame)

    def _draw_reticle(self, img, center, gap=10, arm=16, color=(255, 255, 255), thickness=1):
        return Renderer.draw_reticle(img, center, gap, arm, color, thickness)

    def _draw_corner_brackets(self, img, margin=6, length=10, color=(200, 200, 200), thickness=1):
        return Renderer.draw_corner_brackets(img, margin, length, color, thickness)

    def _render_viewport(self, fov_frame: np.ndarray, estimate, all_dets: list[dict] | None = None):
        # Standard crosshair only — no overlay configuration
        pixel_scale = 0.035
        try:
            pixel_scale = float(getattr(getattr(self, "camera", None).config, "pixel_scale_mrad", 0.035))
        except Exception: pass
        try:
            display = Renderer.render_viewport(fov_frame, self.camera, getattr(self, "beacons", [self.target]), self.target, self.tracker, all_dets, pixel_scale_mrad=pixel_scale)
        except Exception:
            display = Renderer.render_viewport(fov_frame, self.camera, getattr(self, "beacons", [self.target]), self.target, self.tracker, all_dets)
        self._last_viewport_frame = display
        self._set_pixmap(self.viewport_label, display)

    def _get_minimap_thumb(self, lw: int, lh: int) -> np.ndarray:
        """Return cached low-res thumb of static background (rebuild only on size/scene change).
        Saves 11 ms copy + 3 ms resize of 5000×5000 each tick → 0.2 ms copy of 0.16 MP thumb."""
        lw = max(50, int(lw)); lh = max(50, int(lh))
        scene_id = id(getattr(self.scene, '_static_background', None))
        if (self._minimap_thumb is not None and self._minimap_thumb_size == (lw, lh)
                and self._minimap_scene_id == scene_id):
            return self._minimap_thumb
        try:
            base = getattr(self.scene, '_static_background', None)
            if base is None:
                base = self.scene.get_frame()
            # For 5000×5000 → 400×300, INTER_AREA is sharper and faster than LINEAR for downscale
            self._minimap_thumb = cv2.resize(base, (lw, lh), interpolation=cv2.INTER_AREA)
        except Exception:
            self._minimap_thumb = np.zeros((lh, lw, 3), dtype=np.uint8)
        self._minimap_thumb_size = (lw, lh)
        self._minimap_scene_id = scene_id
        return self._minimap_thumb

    def _invalidate_minimap_cache(self):
        self._minimap_thumb = None
        self._minimap_thumb_size = None
        self._minimap_scene_id = None

    def _render_minimap(self, scene_frame: np.ndarray | None = None):
        lw = self.minimap_label.width() if self.minimap_label.width()>10 else self._god_display_size[0]
        lh = self.minimap_label.height() if self.minimap_label.height()>10 else self._god_display_size[1]
        # Optimized path: use cached thumb (no 5000×5000 copy/resize). Fallback to legacy if needed.
        if hasattr(self, '_get_minimap_thumb'):
            try:
                thumb = self._get_minimap_thumb(lw, lh)
                display = Renderer.render_minimap_cached(thumb, self.camera, getattr(self, "beacons", [self.target]), self.target, self.tracker, (lw, lh), self._scene_size)
                self._last_god_frame = display
                self._set_pixmap(self.minimap_label, display)
                return
            except Exception:
                pass
        # Legacy fallback (heavy)
        if scene_frame is None:
            try:
                scene_frame = self.scene._static_background.copy() if hasattr(self.scene, '_static_background') and self.scene._static_background is not None else self.scene.get_frame()
            except Exception:
                scene_frame = self.scene.get_frame()
        display = Renderer.render_minimap(scene_frame, self.camera, getattr(self, "beacons", [self.target]), self.target, self.tracker, (lw, lh), self._scene_size)
        self._last_god_frame = display
        self._set_pixmap(self.minimap_label, display)

    def _set_pixmap(self, label, bgr_frame: np.ndarray):
        # Delegate to Renderer (handles QImage copy + scaling)
        rgb = Renderer.set_pixmap(label, bgr_frame)
        self._last_rgb = rgb
        return rgb

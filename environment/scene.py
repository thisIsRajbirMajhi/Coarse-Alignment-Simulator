# environment/scene.py - Realistic 2D sky/background — thin orchestrator delegating to modular sub-builders
#
# World-size policy: Per PDF Sr.1 — Screen Size (min.) 2000×2000, Optional User-defined up to 5000.
#   - environment.constants.LIMITS["world_width/height"] = (2000,5000) per spec (min 2000).
#   - DEFAULTS = 2000×2000 for best FPS (4 MP vs 25 MP at 5000, ~6× cheaper).
#   - Scene(...) as generic engine still supports 50..5000 for headless tests (MIN_RES..MAX_RES).
#
# Vignetting policy: REAL lens vignetting is sensor/image-space (centered on camera FOV),
#   NOT world-space (centered on world 2500,2500). Previous Scene._build_background baked
#   vignetting into the 5000×5000 world buffer (dark corners at world centre). Now vignetting
#   is NOT applied in Scene; it is applied at camera-capture stage (PTZCamera.capture or
#   MainWindow post-capture) so it follows the camera FOV.

import numpy as np

# Re-export limits for back-compat (gui/app.py imports these)
from environment.constants import MAX_RES, MIN_RES, DEFAULTS
from environment.gradient import build_gradient
from environment.haze import build_haze_field, get_haze_advect_offset, haze_modulation
from environment.stars import draw_static_stars, draw_twinkling_stars, generate_starfield

# Optional typed config (avoid hard import cycle at runtime)
try:
    from environment.config import EnvironmentConfig  # noqa: F401
except Exception:
    EnvironmentConfig = None  # type: ignore

class Scene:
    """
    2D scene composer — owns world size, RNG, and layered background.

    Per PDF Sr.1 — world configurable 2000..5000 (min 2000, default 2000 for FPS).
    Generic engine supports 50..5000 for tests.

    10 configurable parameters (grouped per EnvironmentPanel):
      1) World Width/Height (px)     — configurable 2000..5000 in production (default 2000);
                                       generic engine 50..5000 for tests
      2) Seed (reproducible RNG)    — 0..999999
      3) Randomize button            — rerolls seed (GUI)
      4) BG Top/Bottom colors        — 0..60 / 0..80
      5) Vignetting (%)              — 0..92  (STORED here for config round-trip,
                                      but APPLIED at camera image stage, not world)
      6) Haze (%)                    — 0..100 (static field + scalar shimmer; see haze.py)
      7) Star/clutter count          — 0..4000
      8) Star brightness scale       — 0.5..1.8
      9) Dynamic toggle              — bool
      10) Dynamic speed               — 0.1..5.0 x

    Lifecycle:
      Scene(...) -> _build_background() -> get_frame() [static copy or dynamic twinkle]
                                            update(dt) advances _time
                                            regenerate() / regenerate_from_config() rebuilds
      Optimized path: get_region(x0,y0,x1,y1) returns 640×640 FOV crop without
      rebuilding full 5000×5000 float32 buffer each tick (60× cheaper).
    """

    # Constructor — supports legacy kwargs and new config object

    def __init__(
        self,
        width: int = 2000,
        height: int = 2000,
        seed: int | None = 42,
        num_clutter_points: int = 60,
        clutter_brightness_range: tuple[int, int] = (35, 85),  # legacy, kept for API compat
        background_color: int = 12,  # legacy fallback for bg_top/bottom
        haze_strength: float = 0.35,
        star_count: int | None = None,
        dynamic: bool = False,
        dynamic_speed: float = 1.0,
        bg_top: int | None = None,
        bg_bottom: int | None = None,
        vignetting: float = 0.0,
        star_brightness_scale: float = 1.0,
        config=None,  # EnvironmentConfig optional (immediate migration path)
    ):
        # If a validated config is supplied, it takes precedence (single source).
        if config is not None:
            self._apply_config(config, rebuild=False)
        else:
            # Legacy path — clamp via constants (mirrors old np.clip behaviour)
            self.width = int(np.clip(int(width), MIN_RES, MAX_RES))
            self.height = int(np.clip(int(height), MIN_RES, MAX_RES))
            self.seed = seed
            self.num_clutter_points = int(num_clutter_points)
            self.clutter_brightness_range = clutter_brightness_range
            self.background_color = int(np.clip(background_color, 0, 255))
            # Gradient colors derive from background_color if not explicitly set
            self.bg_top = int(np.clip(int(bg_top) if bg_top is not None else background_color, 0, 60))
            self.bg_bottom = int(np.clip(int(bg_bottom) if bg_bottom is not None else int(background_color + 10), 0, 80))
            self.haze_strength = float(np.clip(haze_strength, 0.0, 1.0))
            self.dynamic = bool(dynamic)
            self.dynamic_speed = float(np.clip(dynamic_speed, 0.1, 5.0))
            self.vignetting = float(np.clip(vignetting, 0.0, 0.92))
            self.star_brightness_scale = float(np.clip(star_brightness_scale, 0.5, 1.8))
            # Star count: explicit star_count wins, else num_clutter_points
            sc = star_count if star_count is not None else num_clutter_points
            self._star_count = int(np.clip(int(sc), 0, 4000))

        # Internal state - background animation removed (always static)
        self._time: float = 0.0
        self._rng = np.random.default_rng(self.seed)
        # Buffers populated by _build_background()
        self._base_no_stars: np.ndarray | None = None  # (H,W,3) uint8 without stars
        self._haze_base: np.ndarray | None = None      # (H,W) float32 for dynamic
        self._static_background: np.ndarray | None = None
        self._stars_xy: np.ndarray = np.zeros((0, 2), dtype=int)
        self._star_base_brightness: np.ndarray = np.array([], dtype=np.float32)
        self._star_sizes: np.ndarray = np.array([], dtype=np.int32)
        self._star_phases: np.ndarray = np.array([], dtype=np.float32)
        self._star_freqs: np.ndarray = np.array([], dtype=np.float32)
        self._star_colors: np.ndarray = np.zeros((0, 3), dtype=np.float32)
        self._star_is_hard_negative: np.ndarray = np.array([], dtype=bool)

        self._build_background()

    def _apply_config(self, config, rebuild: bool = True) -> None:
        """Apply a validated EnvironmentConfig to this Scene's fields."""
        # Use to_scene_kwargs for consistent unit conversion
        try:
            kwargs = config.to_scene_kwargs() if hasattr(config, "to_scene_kwargs") else dict(config)
        except Exception:
            kwargs = dict(config) if isinstance(config, dict) else {}
        # Map canonical keys to Scene fields
        if "width" in kwargs:
            self.width = int(np.clip(int(kwargs["width"]), MIN_RES, MAX_RES))
        if "height" in kwargs:
            self.height = int(np.clip(int(kwargs["height"]), MIN_RES, MAX_RES))
        if "world_width" in kwargs:
            self.width = int(np.clip(int(kwargs["world_width"]), MIN_RES, MAX_RES))
        if "world_height" in kwargs:
            self.height = int(np.clip(int(kwargs["world_height"]), MIN_RES, MAX_RES))
        if "seed" in kwargs:
            self.seed = kwargs["seed"]
        if "haze_strength" in kwargs:
            self.haze_strength = float(np.clip(float(kwargs["haze_strength"]), 0.0, 1.0))
        if "haze_pct" in kwargs:
            self.haze_strength = float(np.clip(int(kwargs["haze_pct"]) / 100.0, 0.0, 1.0))
        if "star_count" in kwargs:
            self._star_count = int(np.clip(int(kwargs["star_count"]), 0, 4000))
            self.num_clutter_points = self._star_count
        if "bg_top" in kwargs:
            self.bg_top = int(np.clip(int(kwargs["bg_top"]), 0, 60))
        if "bg_bottom" in kwargs:
            self.bg_bottom = int(np.clip(int(kwargs["bg_bottom"]), 0, 80))
        if "background_color" in kwargs and "bg_top" not in kwargs:
            self.background_color = int(np.clip(int(kwargs["background_color"]), 0, 255))
        if "vignetting" in kwargs:
            self.vignetting = float(np.clip(float(kwargs["vignetting"]), 0.0, 0.92))
        if "vignetting_pct" in kwargs:
            self.vignetting = float(np.clip(int(kwargs["vignetting_pct"]) / 100.0, 0.0, 0.92))
        if "star_brightness_scale" in kwargs:
            self.star_brightness_scale = float(np.clip(float(kwargs["star_brightness_scale"]), 0.5, 1.8))
        if "star_brightness" in kwargs:
            self.star_brightness_scale = float(np.clip(float(kwargs["star_brightness"]), 0.5, 1.8))
        # Legacy clutter compat
        if "num_clutter_points" in kwargs and "star_count" not in kwargs:
            self._star_count = int(np.clip(int(kwargs["num_clutter_points"]), 0, 4000))
            self.num_clutter_points = self._star_count
        if not hasattr(self, "num_clutter_points"):
            self.num_clutter_points = int(self._star_count)
        if not hasattr(self, "background_color"):
            self.background_color = int(self.bg_top)
        if rebuild:
            self._rng = np.random.default_rng(self.seed)
            self._build_background()

    def _build_background(self) -> None:
        """
        Compose the full background in layered order:
          1) Gradient (zenith→horizon)  [gradient.py]
          2) Haze field                  [haze.py]
          3) Starfield metadata + static composite [stars.py]
        NOTE: Vignetting is NOT applied here — it is a camera/image-space effect
        (radial falloff centered on FOV, not world). Applied at capture stage via
        environment.vignetting.apply_vignetting on the 640×640 FOV frame.
        Caches _base_no_stars (without stars) and _static_background (with stars).
        """
        rng = self._rng
        w, h = self.width, self.height

        # 1) Sky gradient
        base = build_gradient(w, h, self.bg_top, self.bg_bottom)

        # 2) Haze — low-frequency filtered noise (adds ±8 DN, static field)
        self._haze_base = build_haze_field(w, h, rng, self.haze_strength)
        if self.haze_strength > 1e-6 and self._haze_base is not None:
            base += self._haze_base[:, :, None]
            base = np.clip(base, 0, 255)

        # Save base without stars for dynamic twinkle path — crystal sharp
        self._base_no_stars = base.astype(np.uint8)

        # 3) Starfield — magnitude-tiered + spectral colors + hard negatives
        star_data = generate_starfield(w, h, rng, self._star_count, self.star_brightness_scale)
        self._stars_xy = star_data["xy"]
        self._star_base_brightness = star_data["brightness"]
        self._star_sizes = star_data["sizes"]
        self._star_phases = star_data["phases"]
        self._star_freqs = star_data["freqs"]
        self._star_colors = star_data.get("colors", np.zeros((len(self._stars_xy), 3), dtype=np.float32))
        self._star_is_hard_negative = star_data.get("is_hard_negative", np.zeros(len(self._stars_xy), dtype=bool))
        self._star_count = int(self._stars_xy.shape[0])
        self.num_clutter_points = self._star_count

        # Precompute static background (with stars at mean brightness) for fast path
        static = self._base_no_stars.copy()
        if self._star_colors is not None and len(self._star_colors) == len(self._stars_xy) and len(self._stars_xy) > 0:
            draw_static_stars(static, self._stars_xy, self._star_base_brightness, self._star_sizes, self._star_colors)
        else:
            draw_static_stars(static, self._stars_xy, self._star_base_brightness, self._star_sizes)
        self._static_background = static
        self._static_with_stars = static  # alias for clarity
        self._time = 0.0

    def update(self, dt: float) -> None:
        """Advance internal time — background animation removed (always static)."""
        pass

    def get_frame(self) -> np.ndarray:
        """
        Return current full-scene image as uint8 (H, W, 3) — always static (background animation removed).
        Returns a copy so callers can safely draw beacons without mutating cache.
        """
        return self._static_background.copy()

    def get_region(self, x0: int, y0: int, x1: int, y1: int) -> np.ndarray:
        """
        Optimized cropped rendering — returns (y1-y0, x1-x0, 3) uint8 region.

        This is the PERFORMANCE FIX for dynamic 5000×5000 rendering: instead of
        rebuilding a full 5000×5000 RGB buffer every tick and then cropping to
        640×640, we crop first (640×640 ≈ 1.2M pixels vs 75M) and apply haze
        shimmer + twinkle only to the visible FOV stars. ~60× fewer pixels,
        no 300 MB float32 temp.

        Handles out-of-bounds FOV (clamped pan at edges) by zero-padding.
        Vignetting is NOT applied here — caller applies vignetting at camera
        image stage (image-space).

        Args:
          x0,y0,x1,y1 : world coords (from PTZCamera.get_fov_rect())
        Returns:
          uint8 (h,w,3) crop.
        """
        w = int(x1 - x0)
        h = int(y1 - y0)
        if w <= 0 or h <= 0:
            # return requested size (at least 1) to avoid 1x1 leak that breaks renderer scale
            return np.zeros((max(1, h if h>0 else 1), max(1, w if w>0 else 1), 3), dtype=np.uint8)
        out = np.zeros((h, w, 3), dtype=np.uint8)
        # Intersection with world bounds
        sx0 = int(max(0, x0)); sy0 = int(max(0, y0))
        sx1 = int(min(self.width, x1)); sy1 = int(min(self.height, y1))
        if sx1 <= sx0 or sy1 <= sy0:
            return out
        dx0 = int(sx0 - x0); dy0 = int(sy0 - y0)
        dh = int(sy1 - sy0); dw = int(sx1 - sx0)
        # clamp destination to out bounds (prevent OOB when x0 negative beyond -w)
        dx0 = int(np.clip(dx0, 0, w - dw))
        dy0 = int(np.clip(dy0, 0, h - dh))

        # Always static — background animation removed
        crop = self._static_background[sy0:sy1, sx0:sx1]
        out[dy0:dy0+dh, dx0:dx0+dw] = crop
        return out

    def get_cropped_frame(self, x0: int, y0: int, x1: int, y1: int) -> np.ndarray:
        """Alias for get_region for backward compat."""
        return self.get_region(x0, y0, x1, y1)

    def regenerate(
        self,
        seed: int | None = None,
        width: int | None = None,
        height: int | None = None,
        haze_strength: float | None = None,
        bg_top: int | None = None,
        bg_bottom: int | None = None,
        vignetting: float | None = None,
        star_count: int | None = None,
        star_brightness_scale: float | None = None,
        config=None,  # EnvironmentConfig support for immediate migration
    ) -> None:
        """
        Regenerate background with new parameters (all optional, back-compat).

        Preferred new call: scene.regenerate_from_config(env_config)
        Legacy call: scene.regenerate(width=..., seed=..., ...)
        """
        # Config path takes precedence if supplied
        if config is not None:
            self._apply_config(config, rebuild=False)
            self._rng = np.random.default_rng(self.seed)
            self._build_background()
            return

        if seed is not None:
            self.seed = int(seed)
        if width is not None:
            self.width = int(np.clip(int(width), MIN_RES, MAX_RES))
        if height is not None:
            self.height = int(np.clip(int(height), MIN_RES, MAX_RES))
        if haze_strength is not None:
            self.haze_strength = float(np.clip(haze_strength, 0.0, 1.0))
        if bg_top is not None:
            self.bg_top = int(np.clip(int(bg_top), 0, 60))
        if bg_bottom is not None:
            self.bg_bottom = int(np.clip(int(bg_bottom), 0, 80))
        if vignetting is not None:
            self.vignetting = float(np.clip(vignetting, 0.0, 0.92))
        if star_count is not None:
            self._star_count = int(np.clip(int(star_count), 0, 4000))
            self.num_clutter_points = self._star_count
        if star_brightness_scale is not None:
            self.star_brightness_scale = float(np.clip(star_brightness_scale, 0.5, 1.8))
        self._rng = np.random.default_rng(self.seed)
        self._build_background()

    def regenerate_from_config(self, config) -> None:
        """
        Regenerate from a validated EnvironmentConfig (preferred API).

        Example:
            cfg = EnvironmentConfig(world_width=1200, haze_pct=50, ...).validate()
            scene.regenerate_from_config(cfg)
        """
        self._apply_config(config, rebuild=False)
        self._rng = np.random.default_rng(self.seed)
        self._build_background()

    def resize(self, width: int, height: int) -> None:
        """Change resolution and regenerate (back-compat helper)."""
        self.regenerate(width=width, height=height)

    def set_dynamic(self, enabled: bool, speed: float = 1.0) -> None:
        """No-op — background animation removed (always static)."""
        pass

    def get_star_count(self) -> int:
        return int(self._star_count)

    def get_resolution(self) -> tuple[int, int]:
        return (self.width, self.height)
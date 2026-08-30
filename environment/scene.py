"""
Module: environment.scene
Purpose: Realistic 2D sky/background — thin orchestrator delegating to modular sub-builders.
Public API: Scene, MAX_RES, MIN_RES
Architecture:
  - constants.py : limits & defaults (single source)
  - config.py    : EnvironmentConfig dataclass (10 params, typed)
  - gradient.py  : sky gradient (zenith → horizon)
  - vignetting.py: radial edge darkening
  - haze.py      : low-frequency fog texture + dynamic drift
  - stars.py     : starfield / clutter generation & drawing
  - scene.py     : orchestration, caching, dynamic time, public API
Notes:
  - Backwards compatible: old Scene(width, height, seed, ...) still works.
  - New path: Scene(config=EnvironmentConfig(...)) or regenerate_from_config().
  - Crystal sharp: no Gaussian blur on final composite.
"""

# ============================================================
# SECTION: Imports
# ============================================================

import numpy as np

# Re-export limits for back-compat (gui/app.py imports these)
from environment.constants import MAX_RES, MIN_RES, DEFAULTS
from environment.gradient import build_gradient
from environment.haze import build_haze_field, haze_modulation
from environment.stars import draw_static_stars, draw_twinkling_stars, generate_starfield
from environment.vignetting import apply_vignetting

# Optional typed config (avoid hard import cycle at runtime)
try:
    from environment.config import EnvironmentConfig  # noqa: F401
except Exception:
    EnvironmentConfig = None  # type: ignore

# ============================================================
# SECTION: Scene — Orchestrator
# ============================================================

class Scene:
    """
    2D scene composer — owns world size, RNG, and layered background.

    10 configurable parameters (grouped per EnvironmentPanel):
      1) World Width/Height (px)     — 50..5000
      2) Seed (reproducible RNG)    — 0..999999
      3) Randomize button            — rerolls seed (GUI)
      4) BG Top/Bottom colors        — 0..60 / 0..80
      5) Vignetting (%)              — 0..92
      6) Haze (%)                    — 0..100
      7) Star/clutter count          — 0..4000
      8) Star brightness scale       — 0.5..1.8
      9) Dynamic toggle              — bool
     10) Dynamic speed               — 0.1..5.0 x

    Lifecycle:
      Scene(...) -> _build_background() -> get_frame() [static copy or dynamic twinkle]
                                            update(dt) advances _time
                                            regenerate() / regenerate_from_config() rebuilds
    """

    # --------------------------------------------------------
    # Constructor — supports legacy kwargs and new config object
    # --------------------------------------------------------

    def __init__(
        self,
        width: int = 1000,
        height: int = 1000,
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

        # Internal state
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
        self._star_subpix: np.ndarray = np.zeros((0, 2))

        self._build_background()

    # ========================================================
    # SECTION: Private — Config Apply Helper
    # ========================================================

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
        if "dynamic" in kwargs:
            self.dynamic = bool(kwargs["dynamic"])
        if "dynamic_speed" in kwargs:
            self.dynamic_speed = float(np.clip(float(kwargs["dynamic_speed"]), 0.1, 5.0))
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

    # ========================================================
    # SECTION: Private — Background Build (delegates to submodules)
    # ========================================================

    def _build_background(self) -> None:
        """
        Compose the full background in layered order:
          1) Gradient (zenith→horizon)  [gradient.py]
          2) Vignetting (radial)         [vignetting.py]
          3) Haze field                  [haze.py]
          4) Starfield metadata + static composite [stars.py]
        Caches _base_no_stars (without stars) and _static_background (with stars).
        """
        rng = self._rng
        w, h = self.width, self.height

        # ----------------------------------------------------
        # 1) Sky gradient
        # ----------------------------------------------------
        base = build_gradient(w, h, self.bg_top, self.bg_bottom)

        # ----------------------------------------------------
        # 2) Vignetting — edge darkening
        # ----------------------------------------------------
        base = apply_vignetting(base, self.vignetting)

        # ----------------------------------------------------
        # 3) Haze — low-frequency filtered noise
        # ----------------------------------------------------
        self._haze_base = build_haze_field(w, h, rng, self.haze_strength)
        if self.haze_strength > 1e-6:
            base += self._haze_base[:, :, None]
            base = np.clip(base, 0, 255)

        # Save base without stars for dynamic twinkle path — crystal sharp
        self._base_no_stars = base.astype(np.uint8)

        # ----------------------------------------------------
        # 4) Starfield — magnitude-tiered generation
        # ----------------------------------------------------
        star_data = generate_starfield(w, h, rng, self._star_count, self.star_brightness_scale)
        self._stars_xy = star_data["xy"]
        self._star_base_brightness = star_data["brightness"]
        self._star_sizes = star_data["sizes"]
        self._star_phases = star_data["phases"]
        self._star_freqs = star_data["freqs"]
        self._star_subpix = star_data["subpix"]
        self._star_count = int(self._stars_xy.shape[0])
        self.num_clutter_points = self._star_count

        # Precompute static background (with stars at mean brightness) for fast path
        static = self._base_no_stars.copy()
        draw_static_stars(static, self._stars_xy, self._star_base_brightness, self._star_sizes)
        self._static_background = static
        self._static_with_stars = static  # alias for clarity
        self._time = 0.0

    # ========================================================
    # SECTION: Public — Dynamic Update
    # ========================================================

    def update(self, dt: float) -> None:
        """Advance internal time for dynamic effects. Call once per tick."""
        if self.dynamic:
            self._time += dt * self.dynamic_speed

    # ========================================================
    # SECTION: Public — Frame Retrieval
    # ========================================================

    def get_frame(self) -> np.ndarray:
        """
        Return current full-scene image as uint8 (H, W, 3).

        - Static (dynamic=False): returns fast copy of precomputed background.
        - Dynamic (dynamic=True): recomposes base + haze modulation + twinkling stars.
        Returns a copy so callers can safely draw beacons without mutating cache.
        """
        if not self.dynamic:
            return self._static_background.copy()

        # Dynamic path — start from base without stars
        base = self._base_no_stars.astype(np.float32)

        # Haze wind shimmer — small sinusoidal modulation (cheap, plausible)
        if self.haze_strength > 1e-6 and self._haze_base is not None:
            base += haze_modulation(self._time)
            base = np.clip(base, 0, 255)

        frame = base.astype(np.uint8).copy()

        # Twinkling stars — ±18% variation per star
        draw_twinkling_stars(
            frame,
            self._stars_xy,
            self._star_base_brightness,
            self._star_sizes,
            self._star_phases,
            self._star_freqs,
            self._time,
        )
        return frame

    # ========================================================
    # SECTION: Public — Regeneration
    # ========================================================

    def regenerate(
        self,
        seed: int | None = None,
        width: int | None = None,
        height: int | None = None,
        dynamic: bool | None = None,
        haze_strength: float | None = None,
        bg_top: int | None = None,
        bg_bottom: int | None = None,
        vignetting: float | None = None,
        star_count: int | None = None,
        star_brightness_scale: float | None = None,
        dynamic_speed: float | None = None,
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
        if dynamic is not None:
            self.dynamic = bool(dynamic)
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
        if dynamic_speed is not None:
            self.dynamic_speed = float(np.clip(dynamic_speed, 0.1, 5.0))
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

    # ========================================================
    # SECTION: Convenience Helpers
    # ========================================================

    def resize(self, width: int, height: int) -> None:
        """Change resolution and regenerate (back-compat helper)."""
        self.regenerate(width=width, height=height)

    def set_dynamic(self, enabled: bool, speed: float = 1.0) -> None:
        """Toggle dynamics without full rebuild."""
        self.dynamic = bool(enabled)
        self.dynamic_speed = float(np.clip(speed, 0.1, 5.0))

    def get_star_count(self) -> int:
        return int(self._star_count)

    def get_resolution(self) -> tuple[int, int]:
        return (self.width, self.height)

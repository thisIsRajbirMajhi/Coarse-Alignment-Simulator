# target/motion.py - Beacon/Target dynamics — per-beacon motion, pometry, and hit geometry

from __future__ import annotations

import math
from enum import Enum

import numpy as np

# Lightweight imports — avoid hard cycle at import time
try:
    from target.config import BeaconConfig
except Exception:
    BeaconConfig = None  # type: ignore

try:
    from target.constants import BEACON_DEFAULTS, BEACON_LIMITS
except Exception:
    BEACON_LIMITS = {}
    BEACON_DEFAULTS = {}

from target.strategy import LinearStrategy, MotionContext, StationaryStrategy

class MotionProfile(Enum):
    """
    Enumeration of supported motion profiles.

    Basics: STATIONARY, LINEAR, SINUSOIDAL, ZIGZAG
    Advanced: CURVED, FIGURE_EIGHT, SPIRAL, ACCELERATING, WAYPOINT, RANDOM_WALK
    """

    # Basics
    STATIONARY = "stationary"
    LINEAR = "linear"
    SINUSOIDAL = "sinusoidal"
    ZIGZAG = "zigzag"
    # Advanced
    CURVED = "curved"
    FIGURE_EIGHT = "figure_eight"
    SPIRAL = "spiral"
    ACCELERATING = "accelerating"
    WAYPOINT = "waypoint"
    RANDOM_WALK = "random_walk"

    # Back-compat aliases — allow "elliptical"/"circular"/"orbit" strings
    @classmethod
    def _missing_(cls, value):
        if isinstance(value, str) and value.lower() in ("elliptical", "circular", "orbit"):
            return cls.CURVED
        return None

    @classmethod
    def from_string(cls, value: str | "MotionProfile") -> "MotionProfile":
        """Resolve string or enum to MotionProfile, case-insensitive."""
        if isinstance(value, cls):
            return value
        try:
            return cls(str(value).lower())
        except Exception:
            return cls.CURVED

class Target:
    """
    Beacon/Target instance — owns per-beacon state (8 params + dynamics).

    8 Per-Beacon Parameters (BeaconConfig fields):
      1) enabled           — Toggle beacon on/off (bool)
      2) profile           — Motion profile (MotionProfile)
      3) position_seed     — Random seed for starting position (int, also stored as _seed)
      4) speed             — Motion speed px/s (5..300)
      5) brightness        — Beacon intensity 0..255 (scintillation 180..255)
      6) radius            — Visual size px 1..15
      7) hitbox_radius     — Valid hit radius px 3..80 (≥ radius)
      8) center_radius     — Precise center radius px 1..10 (≤ hitbox)

    Additional computed state:
      x,y, vx,vy, heading, bounds, t, RNG, photometry, orbit params, etc.

    Hot-apply: use apply_config(BeaconConfig) for live GUI updates (no rebuild).
    """

    # Constructor — supports legacy args and BeaconConfig

    def __init__(
        self,
        x: float = 400.0,
        y: float = 300.0,
        profile: MotionProfile | str = "curved",
        speed: float = 60.0,
        bounds: tuple[int, int] = (800, 600),
        seed: int | None = None,
        brightness: int = 255,
        radius: int = 5,
        heading: float | None = None,
        hitbox_radius: int = 14,
        center_radius: int = 2,
        beacon_id: int = 0,
        config: "BeaconConfig | None" = None,
        enabled: bool = True,
        shape: str = "square",
        size_w: int = 10,
        size_h: int = 10,
        blinking: bool = False,
    ):
        # If BeaconConfig supplied, it drives construction (validated)
        if config is not None and BeaconConfig is not None:
            try:
                cfg = config.validate()
                x = float(cfg.x)
                y = float(cfg.y)
                profile = cfg.profile
                speed = float(cfg.speed)
                seed = int(cfg.position_seed)
                brightness = int(cfg.brightness)
                radius = int(cfg.radius)
                hitbox_radius = int(cfg.hitbox_radius)
                center_radius = int(cfg.center_radius)
                heading = None if cfg.heading is None else float(cfg.heading) * math.pi / 180.0
                beacon_id = int(cfg.beacon_id)
                enabled = bool(cfg.enabled)
                shape = str(getattr(cfg, "shape", shape))
                size_w = int(getattr(cfg, "size_w", size_w))
                size_h = int(getattr(cfg, "size_h", size_h))
                blinking = bool(getattr(cfg, "blinking", blinking))
            except Exception as e:
                import logging
                logging.getLogger("target").warning(f"BeaconConfig validate failed: {e}, using raw values with later clamping")

        # Core identity — clamped via constants
        self.x = float(x); self.y = float(y)
        # Normalize profile string → enum
        try:
            self.profile = profile if isinstance(profile, MotionProfile) else MotionProfile(str(profile).lower())
        except Exception:
            self.profile = MotionProfile.CURVED
        # Clamp via constants (fallback to manual if constants missing)
        try:
            lo, hi = BEACON_LIMITS.get("speed", (5, 300))
            self.speed = float(np.clip(float(speed), lo, hi))
        except Exception:
            self.speed = float(speed)
        try:
            lo, hi = BEACON_LIMITS.get("brightness", (0, 255))
            self.brightness = int(np.clip(int(brightness), lo, hi))
        except Exception:
            self.brightness = int(np.clip(int(brightness), 0, 255))
        try:
            lo, hi = BEACON_LIMITS.get("radius", (1, 15))
            self.radius = int(np.clip(int(radius), lo, hi))
            if self.radius < 1: self.radius = 1
        except Exception:
            self.radius = int(max(1, int(radius)))

        self.bounds = bounds
        self._t = 0.0
        self._rng = np.random.default_rng(seed)
        self._seed = seed
        # Hitbox geometry — ensure center ≤ hitbox
        try:
            lo, hi = BEACON_LIMITS.get("hitbox_radius", (3, 80))
            self.hitbox_radius = int(np.clip(int(hitbox_radius), lo, hi))
            lo, hi = BEACON_LIMITS.get("center_radius", (1, 10))
            self.center_radius = int(np.clip(int(center_radius), lo, hi))
            if self.center_radius > self.hitbox_radius:
                self.center_radius = int(self.hitbox_radius)
        except Exception:
            self.hitbox_radius = int(np.clip(int(hitbox_radius), 3, 80))
            self.center_radius = int(np.clip(int(center_radius), 1, 10))
        self.beacon_id = int(beacon_id)
        self.enabled = bool(enabled)
        self.shape = str(shape).lower() if shape in ("square", "circle") else "square"
        self.size_w = int(np.clip(int(size_w), 5, 20))
        self.size_h = int(np.clip(int(size_h), 2, 20))
        self.blinking = bool(blinking)
        self._blink_visible = True
        self._blink_timer = 0.0

        # Heading & velocity — seeded RNG for reproducibility
        if heading is not None:
            self._heading = float(heading)
        else:
            self._heading = float(self._rng.uniform(0, 2*math.pi))
        self.vx = self.speed * math.cos(self._heading)
        self.vy = self.speed * math.sin(self._heading)
        self.ax = 0.0; self.ay = 0.0

        # Pometric scintillation state
        self._scint_phase = float(self._rng.uniform(0, 2*math.pi))
        self._scint_freq = float(self._rng.uniform(8.0, 14.0))
        self.current_brightness = float(self.brightness)
        self.current_radius = float(self.radius)

        # Profile-specific initializations (orbit, random walk, etc.)
        self._init_orbit_params()
        self._init_random_walk_params()
        self._init_sinusoidal_params()
        self._init_zigzag_params()
        self._init_figure_eight_params()
        self._init_spiral_params()
        self._init_accelerating_params()
        self._init_waypoint_params()

        # Realistic beacon extensions — robust-simple, additive
        self._init_realistic_photometry()
        self._init_aoa_jitter()
        self._init_wind_gust()
        self._init_gimbal_lag()
        self._init_beacon_coding()
        self._init_eclipse()

    # Private — profile initializers (grouped for clarity)

    def _init_orbit_params(self) -> None:
        """Curved/orbit parameters — center-relative radius & phase."""
        cx, cy = self.bounds[0]/2, self.bounds[1]/2
        dx0, dy0 = self.x - cx, self.y - cy
        self._orbit_radius = max(math.hypot(dx0, dy0), 60.0)
        self._orbit_radius_y = self._orbit_radius * float(self._rng.uniform(0.60, 0.85))
        self._orbit_phase = math.atan2(dy0, dx0) if (dx0 or dy0) else 0.0
        self._orbit_ecc_phase = float(self._rng.uniform(0, math.pi))
        self._orbit_omega0 = self.speed / max(self._orbit_radius, 1.0)

    def _init_random_walk_params(self) -> None:
        """Langevin random-walk state."""
        self._rw_vx = float(self._rng.normal(0, self.speed*0.4))
        self._rw_vy = float(self._rng.normal(0, self.speed*0.4))
        self._rw_damping = 1.8
        self._rw_noise = self.speed * 1.6

    def _init_sinusoidal_params(self) -> None:
        """Sinusoidal horizontal scan with vertical drift."""
        w, h = self.bounds
        cy = h/2
        self._sin_amp = float(min(w, h) * 0.32)  # covers ~64% world
        self._sin_omega = self.speed / max(self._sin_amp, 1.0) * 0.9
        self._sin_phase = float(self._rng.uniform(0, 2*math.pi))
        self._sin_cy = float(cy)

    def _init_zigzag_params(self) -> None:
        self._zz_next_turn = float(self._rng.uniform(1.0, 2.2))
        self._zz_interval = 1.6

    def _init_figure_eight_params(self) -> None:
        self._fe_A = self._orbit_radius
        self._fe_B = self._orbit_radius * 0.55
        self._fe_omega = self.speed / max(self._fe_A, 1.0)

    def _init_spiral_params(self) -> None:
        w, h = self.bounds
        self._sp_r0 = max(30.0, self._orbit_radius * 0.45)
        self._sp_max_r = min(w, h) * 0.42
        self._sp_omega = self.speed / max(self._sp_r0, 1.0) * 0.85
        self._sp_expand_rate = 0.55  # rad/s for pulsation

    def _init_accelerating_params(self) -> None:
        self._acc = float(self.speed * 0.18)  # px/s^2
        self._cur_speed = float(max(8.0, self.speed * 0.45))

    def _init_waypoint_params(self) -> None:
        w, h = self.bounds
        self._wp = np.array([float(self._rng.uniform(80, w-80)),
                             float(self._rng.uniform(80, h-80))])
        self._wp_speed = float(self.speed)
        self._wp_turn_rate = 3.2  # 1/s lerp toward target heading

    # ----- Realistic beacon extensions -----
    def _init_realistic_photometry(self) -> None:
        # Gamma-Gamma parameters: alpha~4.2 beta~2.8 for moderate turbulence, will vary per beacon
        self._gg_alpha = float(self._rng.uniform(3.2, 5.8))
        self._gg_beta = float(self._rng.uniform(2.2, 3.6))
        self._scint_state = 0.0  # OU state for correlated flicker
        self._aoa_phase = float(self._rng.uniform(0, 2 * math.pi))

    def _init_aoa_jitter(self) -> None:
        # Angle-of-arrival: 1.2-2.8 px high-frequency dance, OU tau 45ms
        self._aoa_amp = float(self._rng.uniform(1.2, 2.8))
        self._aoa_tau = 0.045
        self._aoa_x = 0.0
        self._aoa_y = 0.0
        # Gimbal lag position
        self._gimbal_x = float(self.x)
        self._gimbal_y = float(self.y)
        self._gimbal_tau = float(self._rng.uniform(0.022, 0.042))  # 22-42ms lag

    def _init_wind_gust(self) -> None:
        # Dryden-like wind gust state
        self._wind_vx = 0.0
        self._wind_vy = 0.0
        self._wind_tau = float(self._rng.uniform(0.18, 0.35))
        self._wind_sigma = float(self._rng.uniform(4.0, 9.0))
        self._wind_next_gust = float(self._rng.uniform(2.0, 6.0))

    def _init_gimbal_lag(self) -> None:
        # Already done in _init_aoa_jitter — keep alias
        pass

    def _init_beacon_coding(self) -> None:
        # PRN-like ID code: 10-bit LSFR per beacon_id, varies blink pattern subtly
        # For multi-beacon challenge: IDs beacon 0..4 have different code phases
        self._code_len = 20
        self._code = np.array([int(b) for b in format((self.beacon_id * 73 + 0x2A) & 0x3FF, '010b')], dtype=int)
        # Repeat to 20
        self._code = np.tile(self._code, 2)[:20]
        self._code_phase = float(self._rng.uniform(0, self._code_len))
        self._code_rate = float(self._rng.uniform(8.0, 14.0))  # Hz

    def _init_eclipse(self) -> None:
        # Eclipse / dropout: 1-2% chance of 0.4-0.9 sec full dropout
        self._eclipse_timer = 0.0
        self._eclipse_time_left = 0.0
        self._eclipse_interval = float(self._rng.uniform(18.0, 45.0))

    def to_config(self) -> "BeaconConfig":
        """Export this Target's 8 params + state as a BeaconConfig."""
        if BeaconConfig is None:
            raise RuntimeError("BeaconConfig not available")
        return BeaconConfig.from_target(self)

    def apply_config(self, cfg: "BeaconConfig") -> None:
        """Hot-apply a BeaconConfig onto this live Target (no rebuild)."""
        if BeaconConfig is None:
            return
        cfg.validate().apply_to_target(self)

    def randomize_position(self, seed: int | None = None) -> None:
        """
        Reroll starting position via seed (for 'Random Seed' per-beacon action).

        Uses a fresh RNG seeded from seed (or random) to place within 60..W-60
        and re-initializes heading/orbit to match new location.
        """
        import random as _rnd
        if seed is None:
            seed = int(_rnd.randint(0, 999999))
        self._seed = int(seed)
        # Use deterministic placement via new RNG
        rng = np.random.default_rng(int(seed) + int(self.beacon_id) * 997)
        w, h = self.bounds
        self.x = float(rng.uniform(60, max(61, w-60)))
        self.y = float(rng.uniform(60, max(61, h-60)))
        # Re-seed heading and re-init orbit params for consistency
        self._rng = np.random.default_rng(int(seed) + 7919)
        self._heading = float(self._rng.uniform(0, 2*math.pi))
        self.vx = self.speed * math.cos(self._heading)
        self.vy = self.speed * math.sin(self._heading)
        self._t = 0.0
        # Re-init profile-specific anchors that depend on x,y
        self._init_orbit_params()
        self._init_sinusoidal_params()
        self._init_figure_eight_params()
        self._init_spiral_params()
        self._init_waypoint_params()
        # Realistic extensions
        try:
            self._init_realistic_photometry()
            self._init_aoa_jitter()
            self._init_wind_gust()
            self._init_beacon_coding()
            self._init_eclipse()
            self._gimbal_x, self._gimbal_y = float(self.x), float(self.y)
        except Exception:
            pass
        # Clamp
        self.x = float(np.clip(self.x, 0, w)); self.y = float(np.clip(self.y, 0, h))

    def randomize_all(self, seed: int | None = None) -> None:
        """
        Reroll every per-beacon parameter at once (for 'Randomize All').

        Randomizes profile, speed, brightness, radius, hitbox/center, heading,
        and position — seeded for reproducibility if seed given.
        """
        import random as _rnd
        rng = np.random.default_rng(int(seed) if seed is not None else int(_rnd.randint(0, 999999)))
        # Profile random among all
        try:
            self.profile = rng.choice(list(MotionProfile))
        except Exception:
            pass
        # Scalar randomization within limits
        lo, hi = BEACON_LIMITS.get("speed", (5, 300))
        self.speed = float(rng.uniform(lo, hi))
        lo, hi = BEACON_LIMITS.get("brightness", (0, 255))
        self.brightness = int(rng.integers(int(lo), int(hi)+1))
        self.current_brightness = float(self.brightness)
        lo, hi = BEACON_LIMITS.get("radius", (1, 15))
        self.radius = int(rng.integers(int(lo), int(hi)+1))
        self.current_radius = float(self.radius)
        lo, hi = BEACON_LIMITS.get("hitbox_radius", (3, 80))
        self.hitbox_radius = int(rng.integers(int(lo), int(hi)+1))
        lo, hi = BEACON_LIMITS.get("center_radius", (1, 10))
        # Center must be ≤ hitbox
        max_center = min(int(hi), int(self.hitbox_radius))
        self.center_radius = int(rng.integers(int(lo), max(int(lo), max_center)+1))
        # Position via seed (reinitializes 5 anchors: orbit, sinusoidal, figure_eight, spiral, waypoint)
        self.randomize_position(seed=int(rng.integers(0, 999999)))
        # Complete reinit — randomize_position misses zigzag timers, accelerating state, and random_walk velocities.
        # Call all 8 _init_*_params to make randomize_all truly complete for the new profile.
        try:
            self._init_orbit_params()
        except:
            pass
        try:
            self._init_random_walk_params()
        except:
            pass
        try:
            self._init_sinusoidal_params()
        except:
            pass
        try:
            self._init_zigzag_params()
        except:
            pass
        try:
            self._init_figure_eight_params()
        except:
            pass
        try:
            self._init_spiral_params()
        except:
            pass
        try:
            self._init_accelerating_params()
        except:
            pass
        try:
            self._init_waypoint_params()
        except:
            pass
        try:
            self._init_realistic_photometry()
            self._init_aoa_jitter()
            self._init_wind_gust()
            self._init_beacon_coding()
            self._init_eclipse()
            self._gimbal_x, self._gimbal_y = float(self.x), float(self.y)
        except:
            pass

    def update(self, dt: float):
        """
        Advance beacon by dt seconds — dispatches to profile-specific handler.

        Branches: STATIONARY, LINEAR, SINUSOIDAL, ZIGZAG, CURVED,
                  FIGURE_EIGHT, SPIRAL, ACCELERATING, WAYPOINT, RANDOM_WALK.
        Always applies photometric scintillation at end.
        """
        dt = float(np.clip(dt, 1e-4, 0.1))
        self._t += dt
        w, h = self.bounds

        # Isolated strategies for stationary/linear
        if self.profile == MotionProfile.STATIONARY:
            StationaryStrategy().step(self, MotionContext(dt, self.bounds, self._t, self._rng))
        elif self.profile == MotionProfile.LINEAR:
            # Delegated to strategy (single source, no double-step)
            LinearStrategy().step(self, MotionContext(dt, self.bounds, self._t, self._rng))
            # strategy already handles position, velocity and bounce with 0.88 coeff and clips

        # SINUSOIDAL — horizontal sinusoid + slow vertical drift
        elif self.profile == MotionProfile.SINUSOIDAL:
            cx, cy = w/2, h/2
            drift_vy = 18.0 * math.sin(self._t*0.25 + self._sin_phase*0.5)
            self._sin_cy = float(np.clip(cy + drift_vy*2.0, h*0.2, h*0.8))
            self.x = cx + self._sin_amp * math.sin(self._sin_omega*self._t + self._sin_phase)
            self.y = self._sin_cy + (self._sin_amp*0.28) * math.cos(self._sin_omega*self._t*0.6 + self._sin_phase)
            self.vx = self._sin_amp * self._sin_omega * math.cos(self._sin_omega*self._t + self._sin_phase)
            self.vy = -(self._sin_amp*0.28) * (self._sin_omega*0.6) * math.sin(self._sin_omega*self._t*0.6 + self._sin_phase)
            self._heading = math.atan2(self.vy, self.vx) if (self.vx or self.vy) else self._heading
            self.x = float(np.clip(self.x, 0, w)); self.y = float(np.clip(self.y, 0, h))

        # ZIGZAG — straight segments with periodic heading flips
        elif self.profile == MotionProfile.ZIGZAG:
            self._zz_next_turn -= dt
            if self._zz_next_turn <= 0:
                turn = float(self._rng.uniform(60, 120)) * math.pi/180.0
                if self._rng.random() < 0.5: turn = -turn
                self._heading += turn
                self._zz_next_turn = float(self._rng.uniform(1.0, 2.0))
            self.vx = self.speed * math.cos(self._heading)
            self.vy = self.speed * math.sin(self._heading)
            self.x += self.vx*dt; self.y += self.vy*dt
            bounced=False
            if self.x <= 0: self.x=0.5; self.vx=abs(self.vx)*0.88; bounced=True
            elif self.x >= w: self.x=w-0.5; self.vx=-abs(self.vx)*0.88; bounced=True
            if self.y <= 0: self.y=0.5; self.vy=abs(self.vy)*0.88; bounced=True
            elif self.y >= h: self.y=h-0.5; self.vy=-abs(self.vy)*0.88; bounced=True
            if bounced: self._heading = math.atan2(self.vy, self.vx); self._zz_next_turn = float(self._rng.uniform(0.8, 1.6))
            self.x=float(np.clip(self.x,0,w)); self.y=float(np.clip(self.y,0,h))

        # CURVED — elliptical orbit with perturbation & breathing
        elif self.profile == MotionProfile.CURVED:
            cx, cy = w/2, h/2
            perturb = 1.0 + 0.08*math.sin(self._t*0.9 + self._orbit_ecc_phase)
            ang_speed = self._orbit_omega0 * perturb
            self._orbit_phase += ang_speed*dt + float(self._rng.normal(0, 0.02*math.sqrt(dt)))
            breath = 1.0 + 0.04*math.sin(self._t*1.3)
            rx = self._orbit_radius*breath; ry = self._orbit_radius_y*breath
            self.x = cx + rx*math.cos(self._orbit_phase)
            self.y = cy + ry*math.sin(self._orbit_phase)
            self.vx = -rx*ang_speed*math.sin(self._orbit_phase)
            self.vy = ry*ang_speed*math.cos(self._orbit_phase)
            self._heading = math.atan2(self.vy, self.vx)
            self.x=float(np.clip(self.x,0,w)); self.y=float(np.clip(self.y,0,h))

        # FIGURE_EIGHT — Lissajous with frequency wobble
        elif self.profile == MotionProfile.FIGURE_EIGHT:
            cx, cy = w/2, h/2
            omega = self._fe_omega
            omega_eff = omega * (1.0 + 0.06*math.sin(self._t*0.7))
            t = self._t
            self.x = cx + self._fe_A * math.sin(omega_eff*t)
            self.y = cy + self._fe_B * math.sin(2*omega_eff*t)
            self.vx = self._fe_A * omega_eff * math.cos(omega_eff*t)
            self.vy = self._fe_B * 2*omega_eff * math.cos(2*omega_eff*t)
            self._fe_A = float(np.clip(self._fe_A + self._rng.normal(0, 0.08), 30, min(w,h)*0.45))
            self._heading = math.atan2(self.vy, self.vx)
            self.x=float(np.clip(self.x,0,w)); self.y=float(np.clip(self.y,0,h))

        # SPIRAL — pulsating radius + tangential + radial velocity
        elif self.profile == MotionProfile.SPIRAL:
            cx, cy = w/2, h/2
            r_range = (self._sp_max_r - self._sp_r0)
            puls = 0.5 + 0.5*math.sin(self._sp_expand_rate*self._t)
            r = self._sp_r0 + r_range * puls
            r += float(self._rng.normal(0, 1.2))
            angle = self._sp_omega*self._t
            self.x = cx + r*math.cos(angle)
            self.y = cy + r*math.sin(angle)
            drdt = r_range*0.5*self._sp_expand_rate*math.cos(self._sp_expand_rate*self._t)
            self.vx = drdt*math.cos(angle) - r*self._sp_omega*math.sin(angle)
            self.vy = drdt*math.sin(angle) + r*self._sp_omega*math.cos(angle)
            self._heading = math.atan2(self.vy, self.vx)
            self.x=float(np.clip(self.x,0,w)); self.y=float(np.clip(self.y,0,h))

        # ACCELERATING — 1-D along heading, bounce resets speed
        elif self.profile == MotionProfile.ACCELERATING:
            self._cur_speed += self._acc*dt
            self.x += self._cur_speed * math.cos(self._heading)*dt
            self.y += self._cur_speed * math.sin(self._heading)*dt
            hit=False
            if self.x <= 0: self.x=0.5; self._heading = math.pi - self._heading; hit=True
            elif self.x >= w: self.x=w-0.5; self._heading = math.pi - self._heading; hit=True
            if self.y <= 0: self.y=0.5; self._heading = -self._heading; hit=True
            elif self.y >= h: self.y=h-0.5; self._heading = -self._heading; hit=True
            if hit:
                self._cur_speed = float(max(8.0, self.speed*0.45))
            self._cur_speed = float(np.clip(self._cur_speed, 6.0, self.speed*2.2))
            self.vx = self._cur_speed*math.cos(self._heading)
            self.vy = self._cur_speed*math.sin(self._heading)
            self.x=float(np.clip(self.x,0,w)); self.y=float(np.clip(self.y,0,h))

        # WAYPOINT — steer toward waypoint with limited turn rate
        elif self.profile == MotionProfile.WAYPOINT:
            tx, ty = self._wp
            dx, dy = tx - self.x, ty - self.y
            dist_wp = math.hypot(dx, dy)
            if dist_wp < 18.0:
                for _ in range(8):
                    nx = float(self._rng.uniform(60, w-60))
                    ny = float(self._rng.uniform(60, h-60))
                    if math.hypot(nx - self.x, ny - self.y) > 120: break
                self._wp = np.array([nx, ny])
                tx, ty = self._wp; dx, dy = tx - self.x, ty - self.y; dist_wp = math.hypot(dx, dy)
            target_heading = math.atan2(dy, dx)
            diff = (target_heading - self._heading + math.pi) % (2*math.pi) - math.pi
            max_turn = self._wp_turn_rate*dt
            diff = float(np.clip(diff, -max_turn, max_turn))
            self._heading += diff
            desired_speed = float(np.clip(self.speed, 12, 180))
            self._wp_speed += float(np.clip(desired_speed - self._wp_speed, -40*dt, 40*dt))
            self.vx = self._wp_speed*math.cos(self._heading)
            self.vy = self._wp_speed*math.sin(self._heading)
            self.x += self.vx*dt; self.y += self.vy*dt
            self.x=float(np.clip(self.x,0,w)); self.y=float(np.clip(self.y,0,h))

        # RANDOM_WALK — Langevin / OU process with damping
        elif self.profile == MotionProfile.RANDOM_WALK:
            damping=self._rw_damping; scale=self._rw_noise
            noise_x=float(self._rng.normal(0,1)); noise_y=float(self._rng.normal(0,1))
            self._rw_vx += (-damping*self._rw_vx*dt + noise_x*scale*math.sqrt(dt))
            self._rw_vy += (-damping*self._rw_vy*dt + noise_y*scale*math.sqrt(dt))
            vmax=self.speed*1.8; vmag=math.hypot(self._rw_vx,self._rw_vy)
            if vmag>vmax:
                self._rw_vx*=vmax/vmag; self._rw_vy*=vmax/vmag
            self.vx,self.vy=self._rw_vx,self._rw_vy
            self.x+=self.vx*dt; self.y+=self.vy*dt
            if self.x<=0: self.x=0.5; self._rw_vx=abs(self._rw_vx)*0.65; self.vx=self._rw_vx
            elif self.x>=w: self.x=w-0.5; self._rw_vx=-abs(self._rw_vx)*0.65; self.vx=self._rw_vx
            if self.y<=0: self.y=0.5; self._rw_vy=abs(self._rw_vy)*0.65; self.vy=self._rw_vy
            elif self.y>=h: self.y=h-0.5; self._rw_vy=-abs(self._rw_vy)*0.65; self.vy=self._rw_vy
            self._heading=math.atan2(self.vy,self.vx) if (self.vx or self.vy) else self._heading
            self.x=float(np.clip(self.x,0,w)); self.y=float(np.clip(self.y,0,h))

        # Universal wall rebound for ALL profiles (ensures target never sticks at edge)
        # Parametric profiles (SINUSOIDAL, CURVED, FIGURE_EIGHT, SPIRAL) previously only clipped,
        # now reflect velocity/phase so they bounce. Handles world shrink/expand as well.
        try:
            bounced = False
            if self.x <= 0.6:
                self.x = 0.5
                if self.vx < -1e-9:
                    self.vx = abs(self.vx) * 0.88
                    if hasattr(self, "_vx"):
                        self._vx = abs(float(getattr(self, "_vx", self.vx))) * 0.88
                    if hasattr(self, "_rw_vx"):
                        self._rw_vx = abs(float(self._rw_vx)) * 0.65
                        self.vx = self._rw_vx
                    bounced = True
                    if self.profile == MotionProfile.SINUSOIDAL:
                        self._sin_phase = math.pi - self._sin_phase
                    elif self.profile in (MotionProfile.CURVED, MotionProfile.SPIRAL):
                        self._orbit_phase = math.pi - self._orbit_phase
                    elif self.profile == MotionProfile.FIGURE_EIGHT:
                        self._fe_omega = -float(getattr(self, "_fe_omega", 1.0))
            elif self.x >= w - 0.6:
                self.x = w - 0.5
                if self.vx > 1e-9:
                    self.vx = -abs(self.vx) * 0.88
                    if hasattr(self, "_vx"):
                        self._vx = -abs(float(getattr(self, "_vx", self.vx))) * 0.88
                    if hasattr(self, "_rw_vx"):
                        self._rw_vx = -abs(float(self._rw_vx)) * 0.65
                        self.vx = self._rw_vx
                    bounced = True
                    if self.profile == MotionProfile.SINUSOIDAL:
                        self._sin_phase = math.pi - self._sin_phase
                    elif self.profile in (MotionProfile.CURVED, MotionProfile.SPIRAL):
                        self._orbit_phase = math.pi - self._orbit_phase
                    elif self.profile == MotionProfile.FIGURE_EIGHT:
                        self._fe_omega = -float(getattr(self, "_fe_omega", 1.0))
            if self.y <= 0.6:
                self.y = 0.5
                if self.vy < -1e-9:
                    self.vy = abs(self.vy) * 0.88
                    if hasattr(self, "_vy"):
                        self._vy = abs(float(getattr(self, "_vy", self.vy))) * 0.88
                    if hasattr(self, "_rw_vy"):
                        self._rw_vy = abs(float(getattr(self, "_rw_vy")) ) * 0.65
                        self.vy = self._rw_vy
                    bounced = True
                    if self.profile == MotionProfile.SINUSOIDAL:
                        # y uses cos, reflect via phase shift
                        self._sin_phase = -self._sin_phase
                    elif self.profile in (MotionProfile.CURVED, MotionProfile.SPIRAL):
                        self._orbit_phase = -self._orbit_phase
            elif self.y >= h - 0.6:
                self.y = h - 0.5
                if self.vy > 1e-9:
                    self.vy = -abs(self.vy) * 0.88
                    if hasattr(self, "_vy"):
                        self._vy = -abs(float(getattr(self, "_vy", self.vy))) * 0.88
                    if hasattr(self, "_rw_vy"):
                        self._rw_vy = -abs(float(getattr(self, "_rw_vy"))) * 0.65
                        self.vy = self._rw_vy
                    bounced = True
                    if self.profile == MotionProfile.SINUSOIDAL:
                        self._sin_phase = -self._sin_phase
                    elif self.profile in (MotionProfile.CURVED, MotionProfile.SPIRAL):
                        self._orbit_phase = -self._orbit_phase
            if bounced:
                self._heading = math.atan2(self.vy, self.vx) if (self.vx or self.vy) else self._heading
                self.x = float(np.clip(self.x, 0, w)); self.y = float(np.clip(self.y, 0, h))
        except Exception:
            pass

        # --- Realistic beacon contributions (additive, bounded) ---
        # 1) Wind gust — Dryden-like OU gust added to x/y before photometry (affects apparent position)
        try:
            self._wind_next_gust -= dt
            if self._wind_next_gust <= 0:
                # New gust impulse
                gust_amp = float(self._rng.uniform(-self._wind_sigma, self._wind_sigma))
                self._wind_vx += gust_amp * 0.7
                self._wind_vy += float(self._rng.uniform(-self._wind_sigma * 0.6, self._wind_sigma * 0.6)) * 0.6
                self._wind_next_gust = float(self._rng.uniform(2.0, 6.0))
            # OU decay
            alpha_w = math.exp(-dt / max(self._wind_tau, 0.05))
            self._wind_vx = self._wind_vx * alpha_w + float(self._rng.normal(0, 1.2)) * math.sqrt(max(0, 1 - alpha_w*alpha_w))
            self._wind_vy = self._wind_vy * alpha_w + float(self._rng.normal(0, 1.0)) * math.sqrt(max(0, 1 - alpha_w*alpha_w))
            self._wind_vx = float(np.clip(self._wind_vx, -18, 18))
            self._wind_vy = float(np.clip(self._wind_vy, -12, 12))
            self.x += self._wind_vx * dt * 0.18
            self.y += self._wind_vy * dt * 0.18
            self.x = float(np.clip(self.x, 0, w)); self.y = float(np.clip(self.y, 0, h))
        except Exception:
            pass

        # 2) Gimbal lag — realistic pointing mechanics (exponential lag)
        try:
            tau_g = float(getattr(self, "_gimbal_tau", 0.032))
            alpha_g = math.exp(-dt / max(tau_g, 0.008))
            # Lagged position follows true position
            self._gimbal_x = alpha_g * self._gimbal_x + (1 - alpha_g) * self.x
            self._gimbal_y = alpha_g * self._gimbal_y + (1 - alpha_g) * self.y
            # Use lagged position as effective reported position for rendering? Keep true x,y for physics
            # but store lag delta for optics streak length (velocity already captures)
        except Exception:
            pass

        # 3) Angle-of-Arrival jitter — high frequency 1.2-2.8 px dance
        try:
            alpha_aoa = math.exp(-dt / float(getattr(self, "_aoa_tau", 0.045)))
            scale_aoa = float(getattr(self, "_aoa_amp", 1.8)) * math.sqrt(max(0, 1 - alpha_aoa*alpha_aoa))
            self._aoa_x = self._aoa_x * alpha_aoa + float(self._rng.normal(0, 1)) * scale_aoa
            self._aoa_y = self._aoa_y * alpha_aoa + float(self._rng.normal(0, 1)) * scale_aoa * 0.72
            # Add to apparent position; also small 30Hz harmonic
            aoa_harm = 0.55 * math.sin(self._t * 32 + self._aoa_phase)
            self.x += self._aoa_x * 0.22 + aoa_harm * 0.12
            self.y += self._aoa_y * 0.22 + aoa_harm * 0.08
            self.x = float(np.clip(self.x, 0, w)); self.y = float(np.clip(self.y, 0, h))
        except Exception:
            pass

        # 4) Photometric scintillation — Gamma-Gamma + harmonic + OU
        try:
            # Gamma-Gamma deep fade: sample occasionally (every ~80ms)
            gg_factor = 1.0
            if int(self._t * 60) % 5 == 0:  # ~12 Hz sampling
                # Sample X~Gamma(alpha,1), Y~Gamma(beta,1) => I = X*Y/(alpha*beta)
                try:
                    # Use numpy gamma (fast) — keep mean ~1.0
                    gx = float(self._rng.gamma(float(getattr(self, "_gg_alpha", 4.2)), 1.0))
                    gy = float(self._rng.gamma(float(getattr(self, "_gg_beta", 2.8)), 1.0))
                    gg_factor = (gx * gy) / (float(getattr(self, "_gg_alpha", 4.2)) * float(getattr(self, "_gg_beta", 2.8)))
                    gg_factor = float(np.clip(gg_factor, 0.32, 1.85))
                    # Smooth with OU so not too spiky
                    alpha_sc = math.exp(-dt / 0.11)
                    self._scint_state = alpha_sc * self._scint_state + (1 - alpha_sc) * (gg_factor - 1.0)
                except Exception:
                    gg_factor = 1.0
            fast = 0.06 * math.sin(self._t * self._scint_freq + self._scint_phase)
            slow = 0.04 * math.sin(self._t * 0.7 + self._aoa_phase * 0.3)
            noise = float(self._rng.normal(0, 0.015))
            ou_flicker = float(getattr(self, "_scint_state", 0.0)) * 0.45
            scint = float(np.clip(1.0 + fast + slow + noise + ou_flicker, 0.32, 1.85))
            # For very low gg_factor, allow deeper dim but not below 0.32
            if gg_factor < 0.5:
                scint = float(np.clip(scint * (0.72 + 0.28 * gg_factor / 0.5), 0.32, 1.85))
        except Exception:
            fast = 0.06 * math.sin(self._t * self._scint_freq + self._scint_phase)
            slow = 0.04 * math.sin(self._t * 0.7)
            noise = float(self._rng.normal(0, 0.015))
            scint = float(np.clip(1.0 + fast + slow + noise, 0.78, 1.22))

        # Beacon ID code — subtle amplitude modulation per ID (0.88-1.0) to aid ID learning
        code_mod = 1.0
        try:
            self._code_phase = (self._code_phase + dt * float(getattr(self, "_code_rate", 10.0))) % float(getattr(self, "_code_len", 20))
            idx = int(self._code_phase) % len(self._code)
            code_bit = int(self._code[idx])
            # Bright when bit=1 (1.0), slightly dim when 0 (0.88) — not full blink, just coding
            code_mod = 0.88 + 0.12 * code_bit
            # For blinking mode, code is overridden by full blink toggle below
            if not getattr(self, "blinking", False):
                scint = scint * (0.96 + 0.04 * code_mod)
        except Exception:
            pass

        self.current_brightness = float(np.clip(self.brightness * scint, 45, 255))
        # Radius breathes with scintillation and with fog scattering (softer when dim)
        rad_factor = 0.92 + 0.18 * scint
        # If deeply faded, beacon appears slightly larger due to scattering (harder for centroid)
        if scint < 0.55:
            rad_factor += (0.55 - scint) * 0.22
        self.current_radius = float(np.clip(self.radius * rad_factor, 1.0, self.radius * 1.6))

        # 5) Eclipse / dropout — 1-2% long dropout tests re-acquisition
        try:
            self._eclipse_timer += dt
            if self._eclipse_time_left > 0:
                self._eclipse_time_left -= dt
                self.current_brightness = 0.0
                self.current_radius = 0.0
                if self._eclipse_time_left <= 0:
                    self._eclipse_timer = 0.0
                    self._eclipse_interval = float(self._rng.uniform(18.0, 45.0))
            elif self._eclipse_timer >= float(getattr(self, "_eclipse_interval", 30.0)):
                if float(self._rng.random()) < 0.018:  # 1.8% trigger
                    self._eclipse_time_left = float(self._rng.uniform(0.35, 0.85))
                    self.current_brightness = 0.0
                else:
                    self._eclipse_timer = 0.0
                    self._eclipse_interval = float(self._rng.uniform(18.0, 45.0))
        except Exception:
            pass

        # 6) Blinking (user-enabled) — overrides everything when off
        if self.blinking:
            self._blink_timer += dt
            if self._blink_timer >= 0.4:
                self._blink_timer = 0.0
                self._blink_visible = not self._blink_visible
            if not self._blink_visible:
                self.current_brightness = 0.0
        else:
            # Keep _blink_visible True for renderer when not blinking
            self._blink_visible = True

    def get_position(self) -> tuple[float,float]:
        return (float(self.x), float(self.y))
    def get_velocity(self) -> tuple[float,float]:
        return (float(self.vx), float(self.vy))
    def get_photometry(self) -> tuple[float,float]:
        return (float(self.current_brightness), float(self.current_radius))

    def get_optics_params(self) -> dict:
        """Return optics rendering hints for renderer (motion vector, fog, bloom)."""
        try:
            mv = (float(self.vx * 0.033), float(self.vy * 0.033))
        except Exception:
            mv = (0.0, 0.0)
        bloom = 0.0
        try:
            # Bloom stronger when deeply scintillated or in fog-like low brightness
            if float(self.current_brightness) > 200:
                bloom = 0.08 + 0.04 * (float(self.current_brightness) - 200) / 55
            if float(self._scint_state) < -0.3:
                bloom += 0.06
        except Exception:
            pass
        return {
            "motion_vector": mv,
            "bloom_strength": float(np.clip(bloom, 0, 0.22)),
            "aoa_jitter": float(getattr(self, "_aoa_amp", 1.5)),
            "beacon_id": int(getattr(self, "beacon_id", 0)),
            "fog_factor": 0.0,  # caller fills from haze/atmospheric
        }

    def get_state_vector(self) -> np.ndarray:
        return np.array([self.x,self.y,self.vx,self.vy], dtype=np.float64)

    def get_hitbox(self) -> tuple[float,float,int]:
        """Return (x,y, hitbox_radius) — large box for coarse lock."""
        return (float(self.x), float(self.y), int(self.hitbox_radius))
    def get_center(self) -> tuple[float,float,int]:
        """Return (x,y, center_radius) — perfect center for precision error."""
        return (float(self.x), float(self.y), int(self.center_radius))
    def distance_to_center(self, px: float, py: float) -> float:
        return float(math.hypot(px - self.x, py - self.y))
    def is_inside_hitbox(self, px: float, py: float) -> bool:
        return self.distance_to_center(px, py) <= self.hitbox_radius
    def is_on_center(self, px: float, py: float, tol: float | None = None) -> bool:
        r = tol if tol is not None else self.center_radius
        return self.distance_to_center(px, py) <= r
    def set_hitbox(self, hitbox_radius: int, center_radius: int | None = None):
        """Update hitbox/center radii — clamped, center ≤ hitbox enforced."""
        try:
            lo, hi = BEACON_LIMITS.get("hitbox_radius", (3, 80))
            self.hitbox_radius = int(np.clip(int(hitbox_radius), lo, hi))
            if center_radius is not None:
                lo, hi = BEACON_LIMITS.get("center_radius", (1, 10))
                self.center_radius = int(np.clip(int(center_radius), lo, hi))
                if self.center_radius > self.hitbox_radius:
                    self.center_radius = int(self.hitbox_radius)
        except Exception:
            self.hitbox_radius = int(np.clip(int(hitbox_radius), 3, 80))
            if center_radius is not None:
                self.center_radius = int(np.clip(int(center_radius), 1, 10))

    def set_bounds(self, bounds: tuple[int, int]):
        """Update world bounds after Environment resize — rescales orbit/amplitude to keep inside."""
        old_w, old_h = self.bounds
        new_w, new_h = int(bounds[0]), int(bounds[1])
        self.bounds = (new_w, new_h)
        # clamp position immediately
        self.x = float(np.clip(self.x, 0, new_w))
        self.y = float(np.clip(self.y, 0, new_h))
        # rescale amplitudes that depend on world size
        try:
            scale = min(new_w / max(1, old_w), new_h / max(1, old_h))
            # sinusoidal
            if hasattr(self, "_sin_amp"):
                self._sin_amp = float(np.clip(self._sin_amp * scale, 20, min(new_w, new_h) * 0.32))
            # orbit
            if hasattr(self, "_orbit_radius"):
                self._orbit_radius = float(np.clip(self._orbit_radius * scale, 60, min(new_w, new_h) * 0.42))
                self._orbit_radius_y = float(np.clip(self._orbit_radius_y * scale, 30, min(new_w, new_h) * 0.35))
            # figure eight
            if hasattr(self, "_fe_A"):
                self._fe_A = float(np.clip(self._fe_A * scale, 30, min(new_w, new_h) * 0.45))
                self._fe_B = float(np.clip(self._fe_B * scale, 20, min(new_w, new_h) * 0.30))
            # spiral
            if hasattr(self, "_sp_r0"):
                self._sp_r0 = float(np.clip(self._sp_r0 * scale, 30, min(new_w, new_h) * 0.35))
                self._sp_max_r = float(min(new_w, new_h) * 0.42)
            # waypoint
            if hasattr(self, "_wp"):
                self._wp[0] = float(np.clip(self._wp[0], 60, new_w - 60))
                self._wp[1] = float(np.clip(self._wp[1], 60, new_h - 60))
        except Exception:
            pass

def create_beacons(count: int, bounds: tuple[int,int], profile: MotionProfile,
                   speed: float, seed: int | None = 42,
                   hitbox_radius: int = 14, center_radius: int = 2,
                   brightness: int = 255, radius: int = 5,
                   shape: str = "square", size_w: int = 10, size_h: int = 10,
                   blinking: bool = False, x: float | None = None, y: float | None = None,
                   speed_random: bool = False) -> list[Target]:
    """
    Factory to create one or more beacons.
    Supports shape, size, blinking, initial location and speed_random.
    """
    try:
        from target.factory import create_beacons as _factory_create
        return _factory_create(count, bounds, profile, speed, seed, hitbox_radius, center_radius, brightness, radius,
                               shape, size_w, size_h, blinking, x, y, speed_random)
    except Exception as e:
        # Fallback if factory fails
        pass
    # Fallback inline (original logic)
    rng = np.random.default_rng(seed)
    beacons: list[Target] = []
    w, h = bounds
    for i in range(int(np.clip(count, 1, 16))):
        x = float(rng.uniform(w*0.18, w*0.82))
        y = float(rng.uniform(h*0.18, h*0.82))
        for _ in range(6):
            too_close = any(math.hypot(x - b.x, y - b.y) < hitbox_radius*2.2 for b in beacons)
            if not too_close: break
            x = float(rng.uniform(w*0.15, w*0.85))
            y = float(rng.uniform(h*0.15, h*0.85))
        sp = float(np.clip(rng.normal(speed, speed*0.12), speed*0.55, speed*1.45)) if count > 1 else speed
        prof = profile if i == 0 else rng.choice(list(MotionProfile))
        beacons.append(Target(x, y, prof, sp, bounds, seed=int(rng.integers(0, 999999)),
                              brightness=brightness, radius=radius,
                              hitbox_radius=hitbox_radius, center_radius=center_radius,
                              beacon_id=i))
    return beacons
# disturbance/constants.py - Physical constants and slider mappings for FSOC impairments

# FSOC wavelength — 1550 nm (eye-safe, low atmospheric absorption)
WAVELENGTH: float = 1.55e-6  # m

# Pixel angular scale — 35 µrad per px (FSOC camera, ≈ 7 arcsec)
# Used to map tilt variance from rad to pixels.
PIXEL_SCALE_RAD: float = 35e-6  # rad/px

# Fried r0 mapping: r0(I) = r0_0 * (1 + β·I)^-0.6
# At 1550 nm: weak (I=0) r0≈0.18 m, strong (I=10) r0≈0.021 m
R0_0: float = 0.18      # m
R0_BETA: float = 1.1
R0_MIN: float = 0.015
R0_MAX: float = 0.5

# Outer / inner scales for von Kármán PSD
OUTER_SCALE: float = 12.0   # m
INNER_SCALE: float = 0.008  # m

# Tilt decorrelation time — frozen-flow wind 8 m/s → τ≈80 ms
TILT_TAU: float = 0.11  # s

# Scintillation — Rytov variance cap
RYTOV_CAP: float = 1.2

# Harmonic tones — typical UAV/sat reaction wheels + structure
VIBRATION_FREQS = (7.0, 18.0, 35.0, 72.0, 150.0)  # Hz
# Base amplitudes at I=5 → RMS≈0.9 px, at I=10 → 3.2 px
VIBRATION_BASE_AMPS = (0.42, 0.31, 0.22, 0.14, 0.07)  # px
VIBRATION_OU_TAU: float = 0.022  # s — coloured noise

CAMERA_TAU: float = 6.0   # s — long correlation (thermal/mount)
CAMERA_VMAX_SLOPE: float = 2.2
CAMERA_VMAX_OFFSET: float = 1.5

ELECTRONS_PER_DN: float = 8.0
READ_SIGMA_BASE: float = 1.2  # DN
T_EXP: float = 0.033  # s — 30 FPS

# Slider limits
SLIDER_MIN: int = 0
SLIDER_MAX: int = 10

# ── Image Noise — Salt & Pepper / Gaussian / Poisson ─────────────────────
# Salt & Pepper density default 10% (≈ 0.10), user 0-20%
SALT_PEPPER_DEFAULT_DENSITY: float = 0.10
SALT_PEPPER_LIMITS: tuple[float, float] = (0.0, 0.20)
SALT_PEPPER_RATIO_DEFAULT: float = 0.50
SALT_PEPPER_RATIO_LIMITS: tuple[float, float] = (0.0, 1.0)
# Gaussian noise — Max StdDev 20px per spec Sr21.2, user-defined up to 20
GAUSSIAN_SIGMA_DEFAULT: float = 8.0
GAUSSIAN_SIGMA_LIMITS: tuple[float, float] = (0.0, 20.0)
GAUSSIAN_SIGMA_MAX_USER: float = 20.0  # per spec max 20
GAUSSIAN_SIGMA_USER_LIMITS: tuple[float, float] = (0.0, 20.0)
# Poisson scale (lambda multiplier) 0..10 controls shot strength
POISSON_LIMITS: tuple[float, float] = (0.0, 10.0)
POISSON_DEFAULT: float = 0.0
POISSON_SCALE_LIMITS: tuple[float, float] = (0.5, 5.0)
POISSON_SCALE_DEFAULT: float = 1.0
POISSON_PEAK_LIMITS: tuple[float, float] = (30.0, 255.0)
POISSON_PEAK_DEFAULT: float = 100.0

# Legacy sensor noise std alias for GUI
MAX_NOISE_STD: float = 20.0  # px/DN per spec Sr21.2
MAX_NOISE_STD_USER_LIMITS: tuple[float, float] = (0.0, 20.0)

# ── Camera Jitter — per-frame uniform ±20 px ────────────────────────────
CAMERA_JITTER_LIMITS: tuple[float, float] = (0.0, 20.0)
CAMERA_JITTER_DEFAULT: float = 0.0
CAMERA_JITTER_MAX: float = 20.0

# ── Atmospheric Disturbance — Clear/Haze/Fog + User ───────
ATMOSPHERIC_PRESETS: tuple[str, ...] = ("Clear", "Haze", "Fog", "User Defined")
ATMOSPHERIC_DEFAULT_PRESET: str = "Clear"
# Contrast/brightness reduction 0..100 % (maps to 0..1 fraction)
ATMOSPHERIC_CONTRAST_LIMITS: tuple[float, float] = (0.0, 100.0)
ATMOSPHERIC_BRIGHTNESS_LIMITS: tuple[float, float] = (0.0, 100.0)
# Preset → (contrast %, brightness %, blur sigma, extra flag)
ATMOSPHERIC_PRESET_MAP: dict[str, dict] = {
    "Clear":      {"contrast": 0,  "brightness": 0,  "blur": 0.0, "haze": 0.0},
    "Haze":       {"contrast": 15, "brightness": 10, "blur": 0.6, "haze": 0.18},
    "Fog":        {"contrast": 38, "brightness": 22, "blur": 1.4, "haze": 0.42},
    "User Defined": {"contrast": 0, "brightness": 0, "blur": 0.0, "haze": 0.0},
}

# ── Platform Motion — px/frame MAX 20, default Linear ────────────────────
PLATFORM_SPEED_LIMITS: tuple[float, float] = (0.0, 20.0)  # px / frame
PLATFORM_SPEED_DEFAULT: float = 5.0
PLATFORM_MAX_PX_PER_FRAME: float = 20.0
PLATFORM_PROFILES: tuple[str, ...] = ("Linear", "Circular", "Random", "Spiral", "Figure 8", "Sin", "Zig-Zag")
PLATFORM_DEFAULT_PROFILE: str = "Linear"
# Mapping display name → internal key
PLATFORM_PROFILE_MAP: dict[str, str] = {
    "Linear": "linear",
    "Circular": "circular",
    "Random": "random",
    "Spiral": "spiral",
    "Figure 8": "figure_8",
    "Sin": "sin",
    "Zig-Zag": "zigzag",
    # aliases
    "figure_8": "figure_8",
    "figure8": "figure_8",
    "zigzag": "zigzag",
    "zig_zag": "zigzag",
}
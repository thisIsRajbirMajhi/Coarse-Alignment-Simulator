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
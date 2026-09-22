# gui/panels/presets_panel.py - Testing Presets Panel (collapsible per-preset cards).
# All presets are MAX-STRESS: stars 1500x1.5, BG top 30/bottom 40, vignetting 60%, haze 60%,
# random seeds per preset, atmospheric User Defined 50/30 + full camera disturbances
# (6px jitter, 3 vib/3 drift, channel 0.85 wander/spread, sensor capped for 60 FPS).
# Each preset targets one autonomy phase: SEARCH / DETECTION / IDENTIFICATION /
# ACQUISITION / RE-ACQUISITION / TRACKING / MIXED.
from __future__ import annotations

import logging
import random
from dataclasses import dataclass, field

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtWidgets import (
    QCheckBox,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from gui.panels.base import BaseConfigPanel

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data contract — kept compatible with existing callers
# ---------------------------------------------------------------------------
@dataclass
class PresetDefinition:
    id: str
    name: str
    category: str  # SEARCH / DETECTION / …
    difficulty: str  # Easy / Medium / Hard
    description: str  # short 1-line summary (kept for compat)
    goal: str  # short goal line (kept for compat)
    # Longer rich explanations (new) — rendered in dedicated sections.
    about: str = ""
    end_goal: str = ""
    # Human-readable config summary (shown in card) — compat with old UI.
    configs: list[tuple[str, str]] = field(default_factory=list)
    # Expected results (shown in card)
    expected: list[tuple[str, str]] = field(default_factory=list)
    # Builder that returns validated config bundle for session apply
    # bundle keys: scenario, camera, pid, autonomy, disturbance, env (any may be None)
    bundle_builder: object = None  # callable -> dict


# ---------------------------------------------------------------------------
# Helpers to build bundles — camera far, formation far, max env/disturb
# ---------------------------------------------------------------------------

def _far_camera(fov_h: float = 4.0, fov_v: float | None = None, **kw):
    """Helper: camera parked far from scene centre (top-left) so SEARCH is required."""
    from camera.config import CameraConfig
    if fov_v is None:
        fov_v = fov_h * 0.75
    base = dict(fov_deg_h=float(fov_h), fov_deg_v=float(fov_v),
                use_custom_start=True, start_pan_deg=-90.0, start_tilt_deg=90.0,
                scan_start_index=0, **kw)
    return CameraConfig(**base).validate()


def _far_formation(**kw):
    """Helper: formation offset far from camera (bottom-right) to force raster search."""
    from remote_terminal.config import RemoteFormationConfig
    base = dict(start_offset_x_m=600.0, start_offset_y_m=600.0)
    base.update(kw)
    return RemoteFormationConfig(**base)


# ---------------------------------------------------------------------------
# MAX-STRESS shared helpers — every preset shares these
# ---------------------------------------------------------------------------

def _max_env(seed: int) -> object:
    """High-stress sky: 1500 stars x1.5, BG 30/40, vignette 60, haze 60, random seed."""
    from environment.config import EnvironmentConfig
    return EnvironmentConfig(
        world_width=2000,
        world_height=2000,
        seed=int(seed),
        bg_top=30,
        bg_bottom=40,
        vignetting_pct=60,
        haze_pct=60,
        star_count=1500,
        star_brightness=1.5,
    ).validate()


def _max_disturbance() -> object:
    """60 FPS MAX: capped sensor/turbulence to keep step <16 ms while staying visually max."""
    from disturbance.core.config import DisturbanceConfig
    return DisturbanceConfig(
        global_enabled=True,
        channel_enabled=True,
        channel_severity=0.85,
        channel_beam_wander=0.8,
        channel_beam_spread=0.8,
        channel_intensity_fluctuation=0.8,
        channel_attenuation_enabled=True,
        channel_attenuation_strength=0.85,
        channel_attenuation_model="Atmospheric",
        turbulence=2,
        vibration=3.0,
        camera_motion=3.0,
        noise=0,
        enable_gaussian=False,
        gaussian_sigma=0.0,
        gaussian_sigma_max=20.0,
        enable_salt_pepper=False,
        salt_pepper_density=0.0,
        salt_pepper_ratio=0.50,
        enable_poisson=False,
        poisson_scale=0.0,
        poisson_peak=100.0,
        max_noise_std=20.0,
        camera_jitter=6.0,
        camera_jitter_enabled=True,
        camera_jitter_max_x=6.0,
        camera_jitter_max_y=6.0,
        camera_jitter_profile="Gaussian",
        camera_jitter_frequency=12.0,
        atmospheric_preset="User Defined",
        atmospheric_contrast=50.0,
        atmospheric_brightness=30.0,
        platform_enabled=True,
        platform_profile="Random",
        platform_speed=6.0,
        platform_amplitude_x=120.0,
        platform_amplitude_y=120.0,
        platform_direction=0.0,
        platform_frequency=1.8,
        platform_phase=0.0,
    ).validate()


# ---------------------------------------------------------------------------
# Parameter descriptions — used to render Value + Description columns
# ---------------------------------------------------------------------------

# Group help subtitles
_GROUP_HELP: dict[str, str] = {
    "Remote Scenario — Formation": "Where the beacons start, how they are shaped and how they move. All presets offset the formation far (600,600) so the camera must SEARCH.",
    "Remote Terminals — Emitters": "Per-beacon optical emission (power, wavelength, spot size). Similar powers make identification harder; dim powers make detection harder.",
    "Camera / Gimbal": "PTZ optics and gimbal kinematics. Narrow FOV = harder raster hunt; wide Agile = faster acquisition but more sky to gate.",
    "PID Controller": "Dual-axis pan/tilt tracker. Aggressive Kp tracks fast targets but risks windup under jitter; conservative damps jitter.",
    "Autonomy — Search / Detection / Association / Tracking": "All V2 autonomy gates and filters: SNR gate, confirm frames, association gate, Kalman Q, coast/lost, REACQ ladder.",
    "Disturbance — Propagation Channel": "Beam-state medium before the camera (haze→wander/spread/scintillation). User Defined 50/30 drives blur + depth haze.",
    "Disturbance — Platform / Jitter / Sensor": "Geometry shake (platform), per-frame camera jitter, and sensor noise layers. Capped for 60 FPS yet visually max-stress.",
    "Environment — Sky / Stars / Atmosphere": "Full-scene sky truth: starfield clutter, gradient background, vignetting and haze. 1500 stars at 1.5× mimics dense clutter.",
}

# Per-parameter one-line meaning
_PARAM_HELP: dict[str, str] = {
    # formation
    "terminal_count": "Number of beacons in the scene (1–8). More = harder association.",
    "formation_shape": "Geometric layout — SINGLE, LINE, GRID, etc. Sets inter-terminal geometry.",
    "motion_profile": "Trajectory of formation centre (CONSTANT_VELOCITY, LINEAR, CIRCULAR, SINUSOIDAL, RANDOM…).",
    "terminal_spacing_m": "Nominal separation between neighbouring terminals (metres). Tight spacing challenges association gate.",
    "speed_mps": "Formation-centre speed (m/s). High speed tests TRACK prediction and PID bandwidth.",
    "heading_deg": "Travel heading (0°=+X, 90°=+Y). Rotates formation and direction vector.",
    "start_offset_x_m": "Formation X offset from world centre at reset (m). 600 = far corner, forces SEARCH.",
    "start_offset_y_m": "Formation Y offset from world centre at reset (m). 600 = far corner, forces SEARCH.",
    # terminals
    "terminal_id": "Beacon identity transmitted in OOK frame (TID). Used for CRC/association gating.",
    "optical_power_w": "Emitted optical power (W). Dim = harder detection; bright = easier false steal.",
    "wavelength_nm": "Carrier wavelength (nm). All presets use 1550 nm (eye-safe FSOC band).",
    "spot_size_mrad": "Full angular beam width/divergence (mrad). Small = dimmer apparent spot at range.",
    "operational_state": "BEACONING allows emission; OFF/STANDBY/FAULT inhibit it.",
    "modulation": "OOK is the only end-to-end waveform; CW/PPM affect power semantics.",
    "pointing_bias_deg": "Static beam pointing offset (deg).",
    "pointing_jitter_sigma_deg": "1σ Gaussian beam pointing jitter (deg).",
    # camera
    "fov_deg_h": "Horizontal field of view (deg). Narrow 2.5° forces full 20-cell raster; wide 6° eases acquisition.",
    "fov_deg_v": "Vertical field of view (deg). Kept at 4:3 aspect of the 640×480 sensor.",
    "resolution_w": "Sensor width (px). Fixed 640 per PDF.",
    "resolution_h": "Sensor height (px). Fixed 480 per PDF.",
    "max_pan_speed_deg_s": "Max gimbal pan rate (deg/s). Limits how fast TRACK can chase.",
    "max_tilt_speed_deg_s": "Max gimbal tilt rate (deg/s). Matched to pan for symmetric tracking.",
    "max_pan_accel_deg_s2": "Max pan angular acceleration (deg/s²). Agile presets raise to 60 for 45 m/s targets.",
    "max_tilt_accel_deg_s2": "Max tilt angular acceleration (deg/s²).",
    "start_pan_deg": "Initial gimbal pan (deg). -90 = top-left park, opposite the formation.",
    "start_tilt_deg": "Initial gimbal tilt (deg). +90 = top-left park.",
    "scan_start_index": "Search grid start cell 0..19. 0 = top-left corner of the raster.",
    "use_custom_start": "When true, init/reset uses start_pan/tilt instead of home (0,0).",
    "damping_ratio": "Gimbal damping ζ — 0.707 Butterworth, 1.0 critical. Higher = less overshoot.",
    "inertia_kg_m2": "Gimbal moment of inertia (kg·m²). Affects accel-limited slews.",
    "backlash_deg": "Gear backlash / hysteresis on reversal (deg). Smaller = more precise.",
    "encoder_bits": "Encoder quantisation (bits). 16-bit ≈ 0.005° resolution.",
    # pid
    "kp_pan": "Proportional gain, pan (deg/s per deg error). Higher = faster, risks overshoot under jitter.",
    "ki_pan": "Integral gain, pan. Compensates steady-state error; clamped by max_integral_deg.",
    "kd_pan": "Derivative gain, pan. Damps velocity; filtered by tau.",
    "kp_tilt": "Proportional gain, tilt.",
    "ki_tilt": "Integral gain, tilt.",
    "kd_tilt": "Derivative gain, tilt.",
    "tau": "D-term low-pass time constant (s). Larger = smoother but slower derivative.",
    "deadband_px": "Pixel error deadband — error below this produces zero command (prevents hunting).",
    "max_integral_deg": "Integrator anti-windup clamp (deg). Prevents integral pile-up when saturated.",
    "max_output_deg_s": "Controller velocity command limit (deg/s). Matched to camera max speed.",
    "mode": "AUTO = closed-loop track, MANUAL/OFF = open loop or disabled.",
    # autonomy
    "candidate_min_snr_db": "Minimum spot SNR to become a candidate (dB). Higher = fewer stars pass.",
    "candidate_confirm_frames": "Consecutive frames a spot must persist before CONFIRMED (1–5). Higher = fewer false positives.",
    "candidate_peak_margin": "Peak must exceed background by this (DN). Rejects flat clutter.",
    "candidate_min_area_px": "Smallest accepted spot area (px). Rejects hot pixels.",
    "candidate_max_area_px": "Largest accepted spot area (px). Rejects saturated blobs.",
    "association_gate_px": "Nearest-neighbour gate radius (px). Tight 25 rejects bright impostors; loose 200 tolerates scan offset.",
    "association_mahal_threshold": "Mahalanobis χ² gate (2-DOF). 9.21 = 99%, 6 ≈ 95%. Tighter rejects jittered mismatches.",
    "kalman_process_noise_q": "Kalman Q — predicted motion uncertainty. Larger (15) holds 20px jitter; small is smoother.",
    "kalman_measurement_noise_r_base": "Base measurement noise R (px²). Scaled by SNR (low SNR → larger R).",
    "p_rx_threshold_w": "Minimum beacon P_rx to accept association (W). 0 = beacon decode alone gates; >0 adds power gate.",
    "active_target_policy": "When multiple TIDs are valid, pick: priority > strongest_prx > highest_snr.",
    "mission_priority": "Ordered TID list for priority policy. First present TID wins.",
    "search_pattern": "Raster order: systematic / last_known / predicted.",
    "search_dwell_frames": "Frames to dwell per scan cell (min 1). Higher = more integration per cell.",
    "search_extended_dwell_frames": "Extra dwell when a candidate is glimpsed before confirming. Helps in haze.",
    "coast_timeout_s": "Time a TRACK may COAST without measurement before growing uncertainty forces LOST (s).",
    "coast_max_uncertainty_px": "If coasted uncertainty exceeds this (px), declare LOST.",
    "lost_timeout_s": "Time in LOST before REACQ ladder starts expanding (s). Small = faster recovery.",
    "lost_uncertainty_threshold_px": "Uncertainty that triggers LOST (px). Tight 20 forces earlier REACQ under shake.",
    "reacq_radii_px": "Expanding search radii ladder (px): 50→800. Larger = wider net around predicted position.",
    "reacq_full_scan_enabled": "When ladder exhausts, fall back to full 20-cell raster with TID gating.",
    # disturbance channel
    "atmospheric_preset": "Haze model: Clear / Haze / Fog / Rain / Low light / User Defined. User Defined honours custom contrast/brightness.",
    "atmospheric_contrast": "Contrast reduction 0–100 % (User Defined). Drives blur sigma + bottom-heavy depth haze.",
    "atmospheric_brightness": "Brightness reduction 0–100 % (User Defined). Extra darkening + veiling luminance.",
    "channel_enabled": "Master switch for propagation channel (beam wander/spread/scintillation).",
    "channel_severity": "Overall channel strength 0–1. Scales wander/spread/attenuation. 0.85 = heavy.",
    "channel_beam_wander": "Beam centroid wander amplitude 0–2. 0.8 = strong tip/tilt under turbulence.",
    "channel_beam_spread": "Beam broadening factor 0–2. 0.8 = enlarged spot, lower peak.",
    "channel_intensity_fluctuation": "Scintillation depth 0–2. 0.8 = strong intensity flicker.",
    "channel_attenuation_enabled": "Enable path attenuation (haze absorption). On = realistic power loss with range.",
    "channel_attenuation_strength": "Attenuation strength 0–1. 0.85 = near-max extinction in haze.",
    "channel_attenuation_model": "Attenuation law: Atmospheric / Fixed / Distance Based / Custom.",
    "turbulence": "Legacy Fried-turbulence slider 0–10 (maps to r0). 2 = moderate; channel wander/spread carry the rest.",
    # disturbance shake
    "global_enabled": "Master switch for all disturbances. On = every layer active.",
    "vibration": "High-frequency mount vibration 0–10 (harmonic tones 7–150 Hz). 3 = moderate structural shake.",
    "camera_motion": "Low-frequency camera drift 0–10 (thermal/mount, τ≈6 s). 3 = steady wander.",
    "camera_jitter": "Per-frame uniform jitter amplitude 0–20 px. 6 = heavy but 60 FPS-safe (was 20 → 7 FPS).",
    "camera_jitter_enabled": "Enable per-frame jitter layer.",
    "camera_jitter_max_x": "Max jitter X per frame (px).",
    "camera_jitter_max_y": "Max jitter Y per frame (px).",
    "camera_jitter_profile": "Jitter distribution: Gaussian / Uniform. Gaussian mimics real IMU noise.",
    "camera_jitter_frequency": "Jitter update rate (Hz). 12 = high-frequency shake.",
    "platform_enabled": "Enable platform motion layer (geometry-level formation sway).",
    "platform_profile": "Platform trajectory: Random / Linear / Circular / Spiral / … Random = worst-case.",
    "platform_speed": "Platform speed 0–20 (px/frame equivalent). 6 = moderate sway.",
    "platform_amplitude_x": "Platform sway amplitude X (px/m equivalent). 120 = large lateral excursion.",
    "platform_amplitude_y": "Platform sway amplitude Y.",
    "platform_frequency": "Platform oscillation frequency (Hz). 1.8 = ~2 Hz wander.",
    "platform_direction": "Platform travel direction (deg). 0° = +X.",
    "platform_phase": "Platform phase offset (deg).",
    # sensor noise
    "enable_gaussian": "Add Gaussian read noise (σ = gaussian_sigma). Off in MAX presets for 60 FPS.",
    "gaussian_sigma": "Gaussian σ (DN/px). 12 = heavy; 20 = near-opaque (spec max).",
    "gaussian_sigma_max": "User cap for σ (0–20). Mirrors max_noise_std.",
    "enable_salt_pepper": "Add salt-&-pepper impulse noise. Off in MAX presets for 60 FPS.",
    "salt_pepper_density": "Impulse density 0–0.20 (10% = 1 in 10 px hit).",
    "salt_pepper_ratio": "Salt vs pepper split 0–1. 0.5 = equal white/black.",
    "enable_poisson": "Add Poisson shot noise (signal-dependent). Off in MAX presets for 60 FPS.",
    "poisson_scale": "Poisson λ multiplier. Higher = stronger shot grain.",
    "poisson_peak": "Poisson peak DN (30–255). Sets shot-noise saturation.",
    "max_noise_std": "Alias for gaussian_sigma_max. Kept in sync.",
    "noise": "Legacy aggregate noise slider 0–10 (kept 0 in presets; per-type toggles are authoritative).",
    # env
    "world_width": "Scene width (px). 2000 meets PDF min; 5000 = max configurable.",
    "world_height": "Scene height (px).",
    "seed": "RNG seed 0–999999. Distinct per preset so clutter pattern differs while staying reproducible.",
    "bg_top": "Zenith gradient colour (0–60). 30 = mid-grey top — brighter than clean 12 to simulate haze veiling.",
    "bg_bottom": "Horizon gradient colour (0–80). 40 = hazy horizon, reduces contrast at bottom (depth haze).",
    "vignetting_pct": "Edge darkening % (0–92). 60% follows camera FOV and darkens corners — spot must survive it.",
    "haze_pct": "Volumetric haze % (0–100). 60% = thick — dims stars via 1 − 0.4·haze, adds shimmer.",
    "star_count": "Starfield clutter count 0–4000. 1500 = dense hard-negative field (~25× clean 60).",
    "star_brightness": "Global star brightness 0.5–1.8×. 1.5× = very bright clutter, stresses peak-margin gate.",
}


def _fmt(v, unit: str = "") -> str:
    """Compact value formatter with units."""
    if isinstance(v, bool):
        return "ON" if v else "OFF"
    if v is None:
        return "—"
    if isinstance(v, float):
        # keep 2 decimals, strip trailing zeros
        s = f"{v:.3f}".rstrip("0").rstrip(".")
        return f"{s}{unit}" if unit else s
    if isinstance(v, int):
        return f"{v}{unit}" if unit else str(v)
    if isinstance(v, (list, tuple)):
        # format lists compactly
        inner = ", ".join(_fmt(x) for x in v)
        return f"[{inner}]"
    s = str(v)
    return f"{s}{unit}" if unit else s


def _bundle_to_groups(bundle: dict) -> list[tuple[str, list[tuple[str, str, str]]]]:
    """Convert a validated bundle dict into (group, [(param, value, help)]) for rendering."""
    groups: list[tuple[str, list[tuple[str, str, str]]]] = []

    # Scenario
    sc = bundle.get("scenario")
    if sc is not None:
        try:
            f = sc.formation
            rows: list[tuple[str, str, str]] = []
            for key in ["terminal_count", "formation_shape", "motion_profile", "terminal_spacing_m", "speed_mps", "heading_deg", "start_offset_x_m", "start_offset_y_m"]:
                val = getattr(f, key, None)
                # unwrap enums
                if hasattr(val, "value"):
                    val = val.value
                unit = {"terminal_spacing_m": " m", "speed_mps": " m/s", "heading_deg": "°", "start_offset_x_m": " m", "start_offset_y_m": " m"}.get(key, "")
                if key in ("formation_shape", "motion_profile"):
                    unit = ""
                rows.append((key, _fmt(val, unit), _PARAM_HELP.get(key, "")))
            groups.append(("Remote Scenario — Formation", rows))
            # terminals sub-group
            t_rows: list[tuple[str, str, str]] = []
            for t in getattr(sc, "terminals", [])[:4]:
                tid = getattr(t, "terminal_id", "?")
                t_rows.append((f"{tid} · optical_power_w", _fmt(getattr(t, "optical_power_w", 0), " W"), _PARAM_HELP["optical_power_w"]))
                t_rows.append((f"{tid} · wavelength_nm", _fmt(getattr(t, "wavelength_nm", 0), " nm"), _PARAM_HELP["wavelength_nm"]))
                t_rows.append((f"{tid} · spot_size_mrad", _fmt(getattr(t, "spot_size_mrad", 0), " mrad"), _PARAM_HELP["spot_size_mrad"]))
                # include pointing if non-default
                bj = getattr(t, "pointing_bias_deg", None)
                if bj is not None and abs(float(bj)) > 1e-9:
                    t_rows.append((f"{tid} · pointing_bias_deg", _fmt(bj, "°"), _PARAM_HELP["pointing_bias_deg"]))
            if t_rows:
                groups.append(("Remote Terminals — Emitters", t_rows))
        except Exception:
            pass

    cam = bundle.get("camera")
    if cam is not None:
        rows = []
        for key, unit in [("fov_deg_h", "°"), ("fov_deg_v", "°"), ("max_pan_speed_deg_s", "°/s"), ("max_tilt_speed_deg_s", "°/s"), ("max_pan_accel_deg_s2", "°/s²"), ("max_tilt_accel_deg_s2", "°/s²"), ("start_pan_deg", "°"), ("start_tilt_deg", "°"), ("scan_start_index", ""), ("use_custom_start", ""), ("damping_ratio", ""), ("backlash_deg", "°")]:
            if not hasattr(cam, key):
                continue
            val = getattr(cam, key)
            rows.append((key, _fmt(val, unit), _PARAM_HELP.get(key, "")))
        # resolution
        if hasattr(cam, "resolution_w"):
            rows.insert(2, ("resolution_w", _fmt(getattr(cam, "resolution_w"), " px"), _PARAM_HELP["resolution_w"]))
            rows.insert(3, ("resolution_h", _fmt(getattr(cam, "resolution_h"), " px"), _PARAM_HELP["resolution_h"]))
        groups.append(("Camera / Gimbal", rows))

    pid = bundle.get("pid")
    if pid is not None:
        rows = []
        for key, unit in [("kp_pan", ""), ("ki_pan", ""), ("kd_pan", ""), ("kp_tilt", ""), ("ki_tilt", ""), ("kd_tilt", ""), ("tau", " s"), ("deadband_px", " px"), ("max_integral_deg", "°"), ("max_output_deg_s", "°/s"), ("mode", "")]:
            if not hasattr(pid, key):
                continue
            rows.append((key, _fmt(getattr(pid, key), unit), _PARAM_HELP.get(key, "")))
        groups.append(("PID Controller", rows))

    aut = bundle.get("autonomy")
    if aut is not None:
        rows = []
        order = ["candidate_min_snr_db", "candidate_confirm_frames", "candidate_peak_margin", "candidate_min_area_px", "candidate_max_area_px", "p_rx_threshold_w", "active_target_policy", "mission_priority", "association_gate_px", "association_mahal_threshold", "kalman_process_noise_q", "kalman_measurement_noise_r_base", "search_dwell_frames", "search_extended_dwell_frames", "search_pattern", "search_start_index", "coast_timeout_s", "coast_max_uncertainty_px", "lost_timeout_s", "lost_uncertainty_threshold_px", "reacq_radii_px", "reacq_full_scan_enabled"]
        for key in order:
            if not hasattr(aut, key):
                continue
            val = getattr(aut, key)
            unit = {"candidate_min_snr_db": " dB", "candidate_peak_margin": " DN", "candidate_min_area_px": " px", "candidate_max_area_px": " px", "p_rx_threshold_w": " W", "association_gate_px": " px", "kalman_process_noise_q": "", "search_dwell_frames": " frames", "search_extended_dwell_frames": " frames", "coast_timeout_s": " s", "coast_max_uncertainty_px": " px", "lost_timeout_s": " s", "lost_uncertainty_threshold_px": " px"}.get(key, "")
            if key == "mission_priority" and isinstance(val, (list, tuple)) and len(val) == 0:
                val = "— (none)"
            rows.append((key, _fmt(val, unit), _PARAM_HELP.get(key, "")))
        groups.append(("Autonomy — Search / Detection / Association / Tracking", rows))

    dist = bundle.get("disturbance")
    if dist is not None:
        # channel
        ch_rows = []
        for key, unit in [("atmospheric_preset", ""), ("atmospheric_contrast", "%"), ("atmospheric_brightness", "%"), ("channel_enabled", ""), ("channel_severity", ""), ("channel_beam_wander", ""), ("channel_beam_spread", ""), ("channel_intensity_fluctuation", ""), ("channel_attenuation_enabled", ""), ("channel_attenuation_strength", ""), ("channel_attenuation_model", ""), ("turbulence", "")]:
            if not hasattr(dist, key):
                continue
            ch_rows.append((key, _fmt(getattr(dist, key), unit), _PARAM_HELP.get(key, "")))
        groups.append(("Disturbance — Propagation Channel", ch_rows))
        shake_rows = []
        for key, unit in [("global_enabled", ""), ("vibration", ""), ("camera_motion", ""), ("camera_jitter", " px"), ("camera_jitter_enabled", ""), ("camera_jitter_max_x", " px"), ("camera_jitter_max_y", " px"), ("camera_jitter_profile", ""), ("camera_jitter_frequency", " Hz"), ("platform_enabled", ""), ("platform_profile", ""), ("platform_speed", ""), ("platform_amplitude_x", ""), ("platform_amplitude_y", ""), ("platform_frequency", " Hz"), ("platform_direction", "°"), ("enable_gaussian", ""), ("gaussian_sigma", ""), ("enable_salt_pepper", ""), ("salt_pepper_density", ""), ("enable_poisson", ""), ("poisson_scale", "")]:
            if not hasattr(dist, key):
                continue
            shake_rows.append((key, _fmt(getattr(dist, key), unit), _PARAM_HELP.get(key, "")))
        groups.append(("Disturbance — Platform / Jitter / Sensor", shake_rows))

    env = bundle.get("env")
    if env is not None:
        rows = []
        for key, unit in [("world_width", " px"), ("world_height", " px"), ("seed", ""), ("bg_top", ""), ("bg_bottom", ""), ("vignetting_pct", "%"), ("haze_pct", "%"), ("star_count", " stars"), ("star_brightness", "×")]:
            if not hasattr(env, key):
                continue
            rows.append((key, _fmt(getattr(env, key), unit), _PARAM_HELP.get(key, "")))
        groups.append(("Environment — Sky / Stars / Atmosphere", rows))

    return groups


def _build_bundles():
    """Factory helpers for preset bundles - imported lazily to avoid circular."""
    from camera.config import CameraConfig, PIDConfig
    from disturbance.core.config import DisturbanceConfig  # keep import for type parity
    from environment.config import EnvironmentConfig
    from local_terminal.models import AutonomyConfig
    from remote_terminal.config import (
        FormationShape,
        MotionProfile,
        RemoteFormationConfig,
        RemoteScenarioConfig,
        RemoteTerminalConfig,
    )

    SEEDS = {
        "searching": 83471,
        "detection": 19283,
        "identification": 55921,
        "acquisition": 72845,
        "reacquisition": 10394,
        "tracking": 64027,
        "mixed": 91520,
    }

    def searching_max():
        return {
            "scenario": RemoteScenarioConfig(
                formation=_far_formation(
                    terminal_count=1, formation_shape=FormationShape.SINGLE,
                    motion_profile=MotionProfile.CONSTANT_VELOCITY,
                    terminal_spacing_m=100.0, speed_mps=5.0, heading_deg=0.0),
                terminals=[RemoteTerminalConfig(terminal_id="RT-001", optical_power_w=0.6, wavelength_nm=1550.0, spot_size_mrad=1.0)],
            ).validate(),
            "camera": _far_camera(fov_h=2.5, fov_v=1.875, max_pan_speed_deg_s=5.0, max_tilt_speed_deg_s=5.0),
            "pid": PIDConfig(kp_pan=1.5, ki_pan=0.1, kd_pan=0.25, kp_tilt=1.5, ki_tilt=0.1, kd_tilt=0.25, mode="AUTO").validate(),
            "autonomy": AutonomyConfig(
                candidate_min_snr_db=12.0, candidate_confirm_frames=3, candidate_peak_margin=10.0,
                p_rx_threshold_w=0.0, active_target_policy="priority", search_start_index=0,
                search_dwell_frames=2, search_extended_dwell_frames=10,
                coast_timeout_s=1.0, lost_timeout_s=0.5, lost_uncertainty_threshold_px=30.0,
            ).validate(),
            "disturbance": _max_disturbance(),
            "env": _max_env(SEEDS["searching"]),
        }

    def detection_max():
        return {
            "scenario": RemoteScenarioConfig(
                formation=_far_formation(terminal_count=1, formation_shape=FormationShape.SINGLE,
                                         motion_profile=MotionProfile.CONSTANT_VELOCITY, speed_mps=3.0),
                terminals=[RemoteTerminalConfig(terminal_id="RT-001", optical_power_w=0.12, wavelength_nm=1550.0, spot_size_mrad=0.6)],
            ).validate(),
            "camera": _far_camera(fov_h=3.0, fov_v=2.25, max_pan_speed_deg_s=5.0, max_tilt_speed_deg_s=5.0),
            "pid": PIDConfig(mode="AUTO").validate(),
            "autonomy": AutonomyConfig(
                candidate_min_snr_db=6.0, candidate_confirm_frames=2, candidate_peak_margin=8.0,
                candidate_min_area_px=4, candidate_max_area_px=4000,
                p_rx_threshold_w=0.0003, active_target_policy="priority",
                coast_timeout_s=1.0, lost_timeout_s=0.6, lost_uncertainty_threshold_px=30.0,
                search_start_index=0,
            ).validate(),
            "disturbance": _max_disturbance(),
            "env": _max_env(SEEDS["detection"]),
        }

    def identification_max():
        return {
            "scenario": RemoteScenarioConfig(
                formation=_far_formation(
                    terminal_count=3, formation_shape=FormationShape.LINE,
                    motion_profile=MotionProfile.LINEAR, terminal_spacing_m=150.0, speed_mps=6.0, heading_deg=15.0),
                terminals=[
                    RemoteTerminalConfig(terminal_id="RT-001", optical_power_w=0.45, wavelength_nm=1550.0, spot_size_mrad=1.0),
                    RemoteTerminalConfig(terminal_id="RT-002", optical_power_w=0.55, wavelength_nm=1550.0, spot_size_mrad=1.0),
                    RemoteTerminalConfig(terminal_id="RT-003", optical_power_w=0.40, wavelength_nm=1550.0, spot_size_mrad=1.0),
                ],
            ).validate(),
            "camera": _far_camera(fov_h=4.0, fov_v=3.0, max_pan_speed_deg_s=5.0, max_tilt_speed_deg_s=5.0),
            "pid": PIDConfig(mode="AUTO").validate(),
            "autonomy": AutonomyConfig(
                candidate_min_snr_db=7.0, candidate_confirm_frames=2,
                p_rx_threshold_w=0.0, active_target_policy="priority",
                mission_priority=["RT-002", "RT-001", "RT-003"],
                search_start_index=0,
            ).validate(),
            "disturbance": _max_disturbance(),
            "env": _max_env(SEEDS["identification"]),
        }

    def acquisition_max():
        return {
            "scenario": RemoteScenarioConfig(
                formation=_far_formation(
                    terminal_count=3, formation_shape=FormationShape.LINE,
                    motion_profile=MotionProfile.LINEAR, terminal_spacing_m=100.0, speed_mps=8.0, heading_deg=10.0),
                terminals=[
                    RemoteTerminalConfig(terminal_id="RT-001", optical_power_w=0.85, wavelength_nm=1550.0, spot_size_mrad=1.0),
                    RemoteTerminalConfig(terminal_id="RT-002", optical_power_w=0.55, wavelength_nm=1550.0, spot_size_mrad=1.0),
                    RemoteTerminalConfig(terminal_id="RT-003", optical_power_w=0.95, wavelength_nm=1550.0, spot_size_mrad=1.0),
                ],
            ).validate(),
            "camera": _far_camera(fov_h=4.0, fov_v=3.0, max_pan_speed_deg_s=5.0, max_tilt_speed_deg_s=5.0),
            "pid": PIDConfig(mode="AUTO").validate(),
            "autonomy": AutonomyConfig(
                candidate_min_snr_db=6.0, candidate_confirm_frames=2,
                association_gate_px=25.0, association_mahal_threshold=6.0,
                p_rx_threshold_w=0.0, active_target_policy="priority",
                mission_priority=["RT-002", "RT-001", "RT-003"],
                search_start_index=0,
            ).validate(),
            "disturbance": _max_disturbance(),
            "env": _max_env(SEEDS["acquisition"]),
        }

    def reacquisition_max():
        return {
            "scenario": RemoteScenarioConfig(
                formation=_far_formation(terminal_count=2, formation_shape=FormationShape.LINE,
                                         terminal_spacing_m=200.0, motion_profile=MotionProfile.SINUSOIDAL, speed_mps=10.0),
                terminals=[
                    RemoteTerminalConfig(terminal_id="RT-001", optical_power_w=0.6),
                    RemoteTerminalConfig(terminal_id="RT-002", optical_power_w=0.9),
                ],
            ).validate(),
            "camera": _far_camera(fov_h=4.0, fov_v=3.0, max_pan_speed_deg_s=5.0, max_tilt_speed_deg_s=5.0),
            "pid": PIDConfig(mode="AUTO").validate(),
            "autonomy": AutonomyConfig(
                candidate_min_snr_db=6.0, candidate_confirm_frames=2,
                reacq_radii_px=[50, 100, 200, 400, 800], reacq_full_scan_enabled=True,
                lost_timeout_s=0.3, lost_uncertainty_threshold_px=20.0,
                coast_timeout_s=0.8, coast_max_uncertainty_px=25.0,
                search_start_index=0,
            ).validate(),
            "disturbance": _max_disturbance(),
            "env": _max_env(SEEDS["reacquisition"]),
        }

    def tracking_max():
        return {
            "scenario": RemoteScenarioConfig(
                formation=_far_formation(terminal_count=1, formation_shape=FormationShape.SINGLE,
                                         motion_profile=MotionProfile.CIRCULAR, speed_mps=45.0),
                terminals=[RemoteTerminalConfig(terminal_id="RT-001", optical_power_w=1.0, spot_size_mrad=1.2)],
            ).validate(),
            "camera": _far_camera(fov_h=6.0, fov_v=4.5, max_pan_speed_deg_s=10.0, max_tilt_speed_deg_s=10.0,
                                   max_pan_accel_deg_s2=60.0, max_tilt_accel_deg_s2=60.0),
            "pid": PIDConfig(kp_pan=3.0, ki_pan=0.3, kd_pan=0.45, kp_tilt=3.0, ki_tilt=0.3, kd_tilt=0.45, mode="AUTO").validate(),
            "autonomy": AutonomyConfig(
                candidate_min_snr_db=6.0, candidate_confirm_frames=2,
                kalman_process_noise_q=15.0, association_mahal_threshold=12.0,
                coast_timeout_s=1.0, lost_timeout_s=0.5, search_start_index=0,
            ).validate(),
            "disturbance": _max_disturbance(),
            "env": _max_env(SEEDS["tracking"]),
        }

    def mixed_max():
        return {
            "scenario": RemoteScenarioConfig(
                formation=_far_formation(terminal_count=4, formation_shape=FormationShape.GRID,
                                         terminal_spacing_m=120.0, motion_profile=MotionProfile.RANDOM, speed_mps=10.0, heading_deg=25.0),
                terminals=[
                    RemoteTerminalConfig(terminal_id="RT-001", optical_power_w=0.35, wavelength_nm=1550.0, spot_size_mrad=1.0),
                    RemoteTerminalConfig(terminal_id="RT-002", optical_power_w=0.90, wavelength_nm=1550.0, spot_size_mrad=1.0),
                    RemoteTerminalConfig(terminal_id="RT-003", optical_power_w=0.55, wavelength_nm=1550.0, spot_size_mrad=0.9),
                    RemoteTerminalConfig(terminal_id="RT-004", optical_power_w=0.70, wavelength_nm=1550.0, spot_size_mrad=1.1),
                ],
            ).validate(),
            "camera": _far_camera(fov_h=4.0, fov_v=3.0, max_pan_speed_deg_s=6.0, max_tilt_speed_deg_s=6.0),
            "pid": PIDConfig(kp_pan=2.0, ki_pan=0.15, kd_pan=0.30, kp_tilt=2.0, ki_tilt=0.15, kd_tilt=0.30, mode="AUTO").validate(),
            "autonomy": AutonomyConfig(
                candidate_min_snr_db=8.0, candidate_confirm_frames=2,
                association_gate_px=60.0, association_mahal_threshold=9.21,
                kalman_process_noise_q=10.0, lost_timeout_s=0.5, lost_uncertainty_threshold_px=30.0,
                reacq_radii_px=[50, 100, 200, 400, 800], reacq_full_scan_enabled=True,
                active_target_policy="priority", mission_priority=["RT-002", "RT-004", "RT-001", "RT-003"],
                search_start_index=0,
            ).validate(),
            "disturbance": _max_disturbance(),
            "env": _max_env(SEEDS["mixed"]),
        }

    return {
        "searching_max": searching_max,
        "detection_max": detection_max,
        "identification_max": identification_max,
        "acquisition_max": acquisition_max,
        "reacquisition_max": reacquisition_max,
        "tracking_max": tracking_max,
        "mixed_max": mixed_max,
    }


def get_preset_definitions() -> list[PresetDefinition]:
    bundles = _build_bundles()
    return [
        PresetDefinition(
            id="searching_max", name="SEARCH — Max Stress (Raster Hunt)", category="SEARCH", difficulty="Hard",
            description="Narrow 2.5° FOV vs single far beacon buried in max clutter/haze/jitter — full 20-cell raster is mandatory.",
            goal="Prove SEARCH raster finds a beacon hidden in max clutter/haze/jitter without star-induced false IDENTIFY.",
            about=(
                "This preset isolates the SEARCH phase: one beacon (RT-001, 0.60 W) is placed 600 m off-centre (far bottom-right) "
                "while the camera is parked at the opposite extreme (-90° pan / +90° tilt, top-left). With a narrow 2.5° × 1.875° FOV the "
                "beacon is guaranteed out-of-view at start, so autonomy must raster all ~20 scan cells. The sky is MAX-STRESS — 1500 stars at 1.5× brightness, "
                "BG 30/40 veiling, 60% vignette and 60% haze, snapshot seed 83471 — plus MAX disturbances (6 px jitter @ 12 Hz, vib 3, drift 3, "
                "turbulence 2, channel 0.85 scatter, User Defined haze 50/30). Detection is deliberately strict (SNR 12 dB, confirm 3, peak margin 10) "
                "so only a persistent true spot survives; stars must not promote a false IDENTIFY."
            ),
            end_goal=(
                "Verify the autonomy leaves SEARCH, dwells correctly (2 frames normal, 10 extended) and promotes the true beacon to IDENTIFICATION "
                "within ~2 s (second scan pass tolerated in max haze), with zero star-only false triggers and tracking error converging to 5–15 px despite jitter."
            ),
            configs=[
                ("Remote", "1× SINGLE — 5 m/s — RT-001 0.60 W — offset 600,600 (far)"),
                ("Camera", "2.5°×1.875° narrow — 5°/s — parked top-left (far)"),
                ("Autonomy", "SNR 12 dB — confirm 3 — peak margin 10 — dwell 2/10"),
                ("Disturb", "MAX: jitter 6 px — vib 3 — drift 3 — turb 2 — platform 6 px Random — UserDef 50/30"),
                ("Env", "MAX: 1500×1.5 — BG 30/40 — vignette 60 — haze 60 — seed 83471"),
            ],
            expected=[
                ("Acquisition time", "< 2 s (≤ 4 s if first raster misses in max haze)"),
                ("False SEARCH→IDENTIFY", "0 — star-only spots must not cross TID gate"),
                ("Tracking error after lock", "5–15 px (degraded, still inside coast gate)"),
                ("Stability", "No stall — raster completes and re-starts if needed"),
            ],
            bundle_builder=bundles["searching_max"],
        ),
        PresetDefinition(
            id="detection_max", name="DETECTION — Max Stress (Dim vs 1500 Stars)", category="DETECTION", difficulty="Hard",
            description="Dim 0.12 W beacon with 0.6 mrad spot vs 1500 bright stars — detector must reject clutter and pass only the true beacon.",
            goal="Prove DETECTION gating rejects ~1500 hard-negative stars at 6 dB / 0.3 mW while keeping the dim true spot.",
            about=(
                "This preset isolates DETECTION: the only beacon is intentionally dim (RT-001, 0.12 W, 0.6 mrad small spot) while the sky is "
                "dense clutter — 1500 stars at 1.5× (seed 19283), 60% haze/vignette, BG 30/40, plus MAX disturbances. "
                "The camera is still parked far (3.0° narrow) so SEARCH remains required, but the challenge is not finding a cell — it is not "
                "confusing a star for the beacon. Autonomy uses a low SNR threshold (6 dB) paired with a P_rx power gate (0.3 mW), peak margin 8, "
                "area 4–4000 px and confirm 2. The dim spot is just above the gate; most stars are just below, but haze diffusion and jitter can blur that gap."
            ),
            end_goal=(
                "Verify the spot detector + confirm logic passes the dim true spot within ~3 s (dim + max haze) while keeping false detections < 1 per full scan. "
                "Coast events of 1–3 are tolerated in max jitter; what must not happen is a star being confirmed and associated as the target."
            ),
            configs=[
                ("Remote", "1× SINGLE — RT-001 0.12 W dim 0.6 mrad — offset 600,600 (far)"),
                ("Camera", "3.0° narrow — 5°/s — parked top-left (far)"),
                ("Autonomy", "SNR 6 dB — P_rx 0.3 mW — peak margin 8 — area 4–4000 — confirm 2"),
                ("Disturb", "MAX: jitter 6 — vib 3 — channel 0.85 — UserDef 50/30 — sensor capped"),
                ("Env", "MAX: 1500×1.5 — BG 30/40 — vignette 60 — haze 60 — seed 19283"),
            ],
            expected=[
                ("Acquisition time", "< 3 s (dim + max haze diffusion)"),
                ("False detections", "< 1 per full 20-cell scan despite 1500 stars"),
                ("Coast events", "1–3 expected in max jitter (tolerated)"),
                ("Miss rate", "True beacon must be confirmed ≥ once per scan pass"),
            ],
            bundle_builder=bundles["detection_max"],
        ),
        PresetDefinition(
            id="identification_max", name="IDENTIFICATION — Max Stress (TID Decode)", category="IDENTIFICATION", difficulty="Hard",
            description="Three beacons at similar powers (0.40–0.55 W) — beacon CRC/TID must pick priority RT-002, not nearest/brightest.",
            goal="Prove IDENTIFICATION CRC + priority policy picks the correct TID when neighbours are equally bright and distorted by haze/jitter.",
            about=(
                "This preset isolates IDENTIFICATION: three LINE-spaced beacons at 150 m separation with near-identical powers (RT-001 0.45 W, "
                "RT-002 0.55 W, RT-003 0.40 W) at 6 m/s, LINEAR. Under MAX sky (seed 55921, 1500×1.5, 60% haze/vignette) and MAX shake (jitter 6, vib 3, "
                "channel 0.85), spots are diffuse and dancing and all three are plausible. Beacon frames carry OOK TID + CRC; autonomy must gate on "
                "valid_crc and mission_priority [RT-002 → RT-001 → RT-003]. The priority beacon is not the nearest geometry, so a naive 'nearest peak' would steal."
            ),
            end_goal=(
                "Verify CRC-gated priority RT-002 is acquired in < 1.5 s and held without lock steal from RT-001/RT-003, even though powers are within 0.15 W. "
                "CRC failures are tolerated (haze/jitter flips bits) but must not crash or promote a wrong TID."
            ),
            configs=[
                ("Remote", "3× LINE 150 m — 6 m/s — RT-001 0.45 W / RT-002 0.55 W / RT-003 0.40 W — offset 600,600"),
                ("Camera", "4.0°×3.0° — 5°/s — parked top-left (far)"),
                ("Autonomy", "SNR 7 dB — confirm 2 — priority RT-002→001→003 — SEARCH required"),
                ("Disturb", "MAX: jitter 6 — channel 0.85 — UserDef 50/30 — 1500 stars"),
                ("Env", "MAX: 1500×1.5 — BG 30/40 — vignette 60 — haze 60 — seed 55921"),
            ],
            expected=[
                ("Acquisition", "< 1.5 s on RT-002 (priority), not RT-001/003"),
                ("Lock steal", "0 — similar-power neighbours must not steal via TID gate"),
                ("CRC behaviour", "Failures tolerated, no crash; valid frame re-locks quickly"),
                ("Power discrimination", "Priority wins even though powers differ by < 30%"),
            ],
            bundle_builder=bundles["identification_max"],
        ),
        PresetDefinition(
            id="acquisition_max", name="ACQUISITION — Max Stress (Boresight Associate)", category="ACQUISITION", difficulty="Hard",
            description="Three close targets (100 m) where brightest RT-003 (0.95 W) is NOT the priority — tight 25 px / Mahal 6 must still associate RT-002.",
            goal="Prove ACQUISITION associate (spot + TID) with a tight gate under 6 px jitter + 1500 stars still picks priority RT-002.",
            about=(
                "This preset isolates ACQUISITION association: three LINE beacons at only 100 m spacing, 8 m/s. Power is adversarial — RT-003 is "
                "brightest at 0.95 W, but the mission priority is RT-002 at 0.55 W (RT-001 0.85 W sits between). Geometry + brightness both try to steal. "
                "Autonomy is tuned tight: association gate 25 px, Mahalanobis 6 (≈95% χ²), SNR 6, confirm 2, priority RT-002. Sky is MAX (seed 72845) so "
                "spots are bloomed by 60% haze, and jitter 6 scatters centroids frame-to-frame. A loose gate would snap to RT-003; too tight would miss entirely."
            ),
            end_goal=(
                "Verify boresight association snaps to RT-002 in < 1.5 s, steal rate 0 for the brighter RT-003, and post-lock tracking error < 10 px despite jitter. "
                "The tight 25 px gate must still pass the true spot after haze diffusion."
            ),
            configs=[
                ("Remote", "3× LINE 100 m — 8 m/s — RT-003 0.95 W brightest ≠ priority — RT-002 0.55 W priority — offset 600,600"),
                ("Camera", "4.0° — 5°/s — parked top-left (far)"),
                ("Autonomy", "Gate 25 px — Mahal 6 — priority RT-002 — SNR 6 — confirm 2"),
                ("Disturb", "MAX: jitter 6 — vib 3 — channel 0.85 — UserDef 50/30"),
                ("Env", "MAX: 1500×1.5 — BG 30/40 — vignette 60 — haze 60 — seed 72845"),
            ],
            expected=[
                ("Acquisition", "< 1.5 s on RT-002 (priority, not brightest)"),
                ("Steal rate", "0 — brightest RT-003 must not steal via tight gate"),
                ("Tracking error", "< 10 px despite 6 px jitter + haze diffusion"),
                ("Gate behaviour", "No oscillation between RT-002 ↔ RT-003"),
            ],
            bundle_builder=bundles["acquisition_max"],
        ),
        PresetDefinition(
            id="reacquisition_max", name="RE-ACQUISITION — Max Stress (LOST→REACQ Ladder)", category="RE-ACQUISITION", difficulty="Hard",
            description="Sinusoidal 2-target forces TRACK→COAST→LOST→REACQ ladder 50→800 + full-scan, TID-gated so wrong RT-001 cannot steal RT-002.",
            goal="Prove LOST 0.3 s/20 px → expanding REACQ ladder under max shake recovers the correct TID, including full-scan fallback.",
            about=(
                "This preset isolates RE-ACQUISITION: two LINE beacons at 200 m, SINUSOIDAL 10 m/s (periodic cross-overs), powers 0.6/0.9 W. "
                "The motion is deliberately hard to predict, and MAX shake (seed 10394, Random platform 6, jitter 6, channel 0.85) repeatedly pushes "
                "the active track over the coast→lost boundary. Autonomy is tuned sensitive: LOST after 0.3 s or 20 px uncertainty, COAST capped 0.8 s/25 px, "
                "REACQ radii 50→100→200→400→800 with full-scan fallback. The wrong TID (RT-001) is brighter when geometry overlaps and must be gated out."
            ),
            end_goal=(
                "Verify LOST is visible in telemetry under max jitter, and REACQ recovers the correct TID in < 1.5 s (≤ 2 s in max haze) via the ladder or full-scan, "
                "with zero steal. Tests both the expanding window and the 'give up and raster again' path — both TID-gated."
            ),
            configs=[
                ("Remote", "2× LINE 200 m — sinusoidal 10 m/s — RT-001 0.6 W / RT-002 0.9 W — offset 600,600"),
                ("Camera", "4.0° — 5°/s — parked top-left (far) — SEARCH required"),
                ("Autonomy", "Reacq 50→800 + full-scan — lost 0.3 s/20 px — coast 0.8 s/25 px"),
                ("Disturb", "MAX: Random platform 6 — jitter 6 — channel 0.85 — UserDef 50/30"),
                ("Env", "MAX: 1500×1.5 — BG 30/40 — vignette 60 — haze 60 — seed 10394"),
            ],
            expected=[
                ("LOST", "Visible in telemetry under max jitter (coast→lost cycling)"),
                ("REACQ time", "< 1.5 s (≤ 2 s with max haze) — correct TID only"),
                ("Steal", "0 — wrong TID gated even when geometry overlaps"),
                ("Fallback", "Full-scan path exercised if ladder misses"),
            ],
            bundle_builder=bundles["reacquisition_max"],
        ),
        PresetDefinition(
            id="tracking_max", name="TRACKING — Max Stress (Agile 45 m/s + Max Jitter)", category="TRACKING", difficulty="Hard",
            description="Circular 45 m/s target vs wide 6° Agile camera — Agile must SEARCH wide then hold TRACK with Q 15 / Mahal 12 under max jitter.",
            goal="Prove TRACK holds < 15 px at 45 m/s despite max platform/jitter/haze via Kalman Q 15 + aggressive PID Kp 3.",
            about=(
                "This preset isolates TRACKING hold: one CIRCULAR beacon at aggressive 45 m/s (RT-001, 1.0 W, 1.2 mrad) vs a wide Agile camera "
                "(6.0°×4.5°, 10°/s, accel 60°/s², seed 64027). The wide FOV helps SEARCH (fewer cells) but hurts TRACK (more stars in gate, faster angular rates). "
                "MAX sky persists (1500×1.5, 60% haze/vignette) plus heavy shake (jitter 6, Random platform 6, channel 0.85). Kalman Q is raised to 15 "
                "(vs default 8) so prediction covariance keeps up with 6 px shake; Mahal 12 (≈99.99%) is deliberately loose to avoid dropping the agile target. "
                "PID is aggressive (Kp 3.0 / Ki 0.3 / Kd 0.45) to prevent lag at 45 m/s."
            ),
            end_goal=(
                "Verify acquisition in < 1 s (wide 6° helps), then continuous TRACK with error < 15 px (degraded but inside gate), zero loss, no PID windup. "
                "Tests that Q 15 compensates shake without letting covariance explode, and that PID does not saturate at 45 m/s."
            ),
            configs=[
                ("Remote", "1× CIRCULAR — 45 m/s — RT-001 1.0 W — offset 600,600 (far)"),
                ("Camera", "6.0°×4.5° — 10°/s Agile accel 60 — parked top-left (far)"),
                ("Autonomy", "Q 15 — Mahal 12 — SNR 6 — confirm 2"),
                ("PID", "Aggressive Kp 3.0 / Ki 0.3 / Kd 0.45 — anti-windup 10°"),
                ("Disturb", "MAX: jitter 6 — Random platform 6 — channel 0.85 — UserDef 50/30"),
                ("Env", "MAX: 1500×1.5 — BG 30/40 — vignette 60 — haze 60 — seed 64027"),
            ],
            expected=[
                ("Acquisition", "< 1 s (wide 6° FOV, fewer raster cells)"),
                ("Tracking error", "< 15 px (degraded max jitter, still inside 30 px coast gate)"),
                ("Loss", "0 — Q 15 holds; PID does not saturate or wind up"),
                ("Speed stress", "45 m/s circular = continuous angular accel, not linear"),
            ],
            bundle_builder=bundles["tracking_max"],
        ),
        PresetDefinition(
            id="mixed_max", name="MIXED — Max Stress (All Phases Combined)", category="MIXED", difficulty="Hard",
            description="GRID 4 terminals RANDOM 10 m/s, mixed powers 0.35–0.90 W — full pipeline SEARCH→TRACK→LOST→REACQ under every disturbance.",
            goal="Prove the complete pipeline survives worst-case everything: dense RANDOM clutter, power-spread beacons, and max sky/shake together.",
            about=(
                "This preset is the end-to-end stress test: GRID of 4 terminals (0.35 / 0.90 / 0.55 / 0.70 W, spot 0.9–1.1 mrad) on RANDOM 10 m/s "
                "(non-stationary, unpredictable cross-overs), formation heading 25°, seed 91520, MAX sky (1500×1.5, 60% haze/vignette, BG 30/40) and MAX "
                "shake (jitter 6, vib 3, turb 2, platform 6 Random, channel 0.85, UserDef 50/30). Every autonomy gate matters at once: SEARCH must find in "
                "4-target clutter, DETECTION must pick powers spread 2.5× apart, IDENTIFICATION CRC must honour priority RT-002, ASSOCIATION gate 60 / Mahal 9.21 "
                "must hold under jitter, and REACQ 50→800 + full-scan must recover from induced LOST. PID is balanced (Kp 2.0) to avoid windup under combined shake."
            ),
            end_goal=(
                "Verify priority RT-002 is acquired in < 2 s, retained > 80% of the run despite max everything, and the system shows no crash or integral windup under combined 6 px shake. "
                "Exercises every transition — SEARCH → DETECTION → IDENTIFICATION → ACQUISITION → TRACK → COAST → LOST → REACQ → TRACK — in one run."
            ),
            configs=[
                ("Remote", "4× GRID 120 m — RANDOM 10 m/s — 0.35/0.90/0.55/0.70 W — offset 600,600"),
                ("Camera", "4.0° — 6°/s — parked top-left (far)"),
                ("Autonomy", "SNR 8 — confirm 2 — gate 60 — Q 10 — Mahal 9.2 — REACQ 50→800 — priority RT-002"),
                ("PID", "Balanced Kp 2.0 / Ki 0.15 / Kd 0.30"),
                ("Disturb", "MAX: jitter 6 — vib 3 — turb 2 — platform 6 Random — channel 0.85 — UserDef 50/30 — sensor capped"),
                ("Env", "MAX: 1500×1.5 — BG 30/40 — vignette 60 — haze 60 — seed 91520"),
            ],
            expected=[
                ("Acquisition", "< 2 s on priority RT-002 (not brightest)"),
                ("Retention", "> 80% TRACK despite max everything"),
                ("Stability", "No crash / no integral windup under combined shake + 1500 stars"),
                ("Coverage", "All transitions exercised in one run"),
            ],
            bundle_builder=bundles["mixed_max"],
        ),
    ]


def _apply_to_session(session, key: str, cfg) -> None:
    """Dispatch apply to Session (GUI) or HeadlessSimulation (no apply_* helpers)."""
    mapper = {
        "scenario": ("apply_remote_config", "scenario_config"),
        "camera": ("apply_camera_config", "camera_config"),
        "pid": ("apply_controller_config", "pid_config"),
        "autonomy": ("apply_local_terminal_config", "autonomy_config"),
        "disturbance": ("apply_disturbance_config", "disturbance_config"),
        "env": ("apply_environment_config", "env_config"),
    }
    meth, attr = mapper[key]
    if hasattr(session, meth):
        getattr(session, meth)(cfg)
    else:
        setattr(session, attr, cfg.validate() if hasattr(cfg, "validate") else cfg)
        try:
            if key == "scenario":
                from local_terminal import SignatureRegistry
                if hasattr(session, "supervisor"):
                    session.supervisor.set_registry(SignatureRegistry.from_scenario(cfg))
        except Exception:
            pass


_LEGACY_ALIAS = {
    "baseline_clean": "searching_max",
    "multi_target_line": "identification_max",
    "low_snr_dim": "detection_max",
    "high_dynamics_agile": "tracking_max",
    "lost_and_reacq": "reacquisition_max",
    "severe_disturb": "mixed_max",
}

def apply_preset_to_session(session, preset_id: str) -> dict:
    """Apply preset bundle to a SimulationSession or HeadlessSimulation session (headless + GUI)."""
    defs = {p.id: p for p in get_preset_definitions()}
    if preset_id not in defs and preset_id in _LEGACY_ALIAS:
        preset_id = _LEGACY_ALIAS[preset_id]
    if preset_id not in defs:
        raise ValueError(f"Unknown preset {preset_id!r}. Known: {list(defs)} + legacy {list(_LEGACY_ALIAS)}")
    bundle = defs[preset_id].bundle_builder()
    applied = {}
    if bundle.get("scenario") is not None:
        _apply_to_session(session, "scenario", bundle["scenario"])
        applied["scenario"] = bundle["scenario"].formation.terminal_count
    if bundle.get("camera") is not None:
        _apply_to_session(session, "camera", bundle["camera"])
        applied["camera"] = bundle["camera"].fov_deg_h
    if bundle.get("pid") is not None:
        _apply_to_session(session, "pid", bundle["pid"])
        applied["pid"] = bundle["pid"].mode
    if bundle.get("autonomy") is not None:
        _apply_to_session(session, "autonomy", bundle["autonomy"])
        applied["autonomy"] = bundle["autonomy"].candidate_min_snr_db
    if bundle.get("disturbance") is not None:
        _apply_to_session(session, "disturbance", bundle["disturbance"])
        applied["disturbance"] = bundle["disturbance"].atmospheric_preset
    if bundle.get("env") is not None:
        _apply_to_session(session, "env", bundle["env"])
        applied["env"] = bundle["env"].seed
    return applied


# ---------------------------------------------------------------------------
# Panel UI — collapsible cards with four well-separated sections
# ---------------------------------------------------------------------------

class PresetsPanel(BaseConfigPanel):
    """Testing Presets - 7 max-stress cards (SEARCH/DETECTION/IDENTIFICATION/ACQUISITION/RE-ACQUISITION/TRACKING/MIXED)."""

    applyRequested = pyqtSignal(str)  # preset id

    def __init__(self, parent=None):
        super().__init__(parent)
        self._presets = get_preset_definitions()
        self._expanded: set[str] = set()
        self._build_ui()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(10)

        title = QLabel("TEST PRESETS — MAX STRESS")
        title.setStyleSheet("font-size:15px; font-weight:800; color:#0f172a; letter-spacing:0.3px;")
        hdr = QHBoxLayout()
        hdr.addWidget(title)
        hdr.addStretch(1)
        badge = QLabel("7 phase tests")
        badge.setStyleSheet("background:#0f172a; color:white; font-size:10px; font-weight:700; border-radius:8px; padding:3px 10px;")
        hdr.addWidget(badge)
        root.addLayout(hdr)

        sub = QLabel(
            "Each preset is fully MAX-STRESS — 1500 stars ×1.5, BG 30/40, vignette 60% + haze 60% with a fixed random seed, "
            "plus 6 px jitter @12 Hz / vib 3 / drift 3 / turb 2 / platform 6 px Random / channel 0.85 / User Defined haze 50/30. "
            "Sensor noise is capped for 60 FPS; enable Gaussian/S&P/Poisson in the Disturbances panel for even heavier stress. "
            "Phase-specific tuning isolates SEARCH → MIXED. Click ▸ to expand; Apply stops the session, loads the bundle, and restarts."
        )
        sub.setStyleSheet("color:#64748b; font-size:11px; line-height:1.35;")
        sub.setWordWrap(True)
        root.addWidget(sub)

        # shared-info banner
        banner = QFrame()
        banner.setStyleSheet("QFrame { background:#f8fafc; border:1px solid #e2e8f0; border-radius:8px; }")
        bl = QVBoxLayout(banner)
        bl.setContentsMargins(10, 8, 10, 8)
        bl.setSpacing(4)
        banner_title = QLabel("Shared MAX-STRESS baseline — every preset inherits this unless overridden")
        banner_title.setStyleSheet("color:#0f172a; font-size:11px; font-weight:700;")
        bl.addWidget(banner_title)
        banner_grid = QGridLayout()
        banner_grid.setHorizontalSpacing(12)
        banner_grid.setVerticalSpacing(2)
        shared = [
            ("Environment", "1500 stars ×1.5, BG 30/40, vignette 60%, haze 60%, world 2000×2000"),
            ("Disturbance", "jitter 6 px (Gaussian 12 Hz), vib 3, camera_motion 3, turb 2, platform Random 6 px @1.8 Hz"),
            ("Channel", "severity 0.85, wander 0.8, spread 0.8, scintillation 0.8, User Defined 50/30"),
            ("Sensor", "Gaussian / S&P / Poisson OFF (capped for 60 FPS — toggle ON to go heavier)"),
            ("Camera park", "start_pan -90°, start_tilt +90°, scan_start 0 — forces full raster hunt"),
            ("Formation offset", "start_offset 600,600 m — far corner, guarantees out-of-view at start"),
        ]
        for i, (k, v) in enumerate(shared):
            lk = QLabel(k)
            lk.setStyleSheet("color:#475569; font-size:10px; font-weight:700;")
            lv = QLabel(v)
            lv.setStyleSheet("color:#334155; font-size:10px;")
            lv.setWordWrap(True)
            banner_grid.addWidget(lk, i, 0)
            banner_grid.addWidget(lv, i, 1)
        banner_grid.setColumnStretch(1, 1)
        bl.addLayout(banner_grid)
        root.addWidget(banner)

        for preset in self._presets:
            card = self._make_card(preset)
            root.addWidget(card)

        root.addStretch(1)

    # ---- card ----

    def _make_card(self, preset: PresetDefinition) -> QFrame:
        card = QFrame()
        card.setObjectName("presetCard")
        card.setStyleSheet("QFrame#presetCard { background:#ffffff; border:1px solid #e5e7eb; border-radius:10px; }")
        lay = QVBoxLayout(card)
        lay.setContentsMargins(10, 8, 10, 8)
        lay.setSpacing(0)

        # Header row: expand toggle + category/difficulty + Apply
        head = QHBoxLayout()
        head.setSpacing(8)
        btn_expand = QPushButton(f"▸  {preset.name}")
        btn_expand.setCheckable(True)
        btn_expand.setMinimumHeight(34)
        btn_expand.setStyleSheet(
            "QPushButton { text-align:left; background:transparent; border:none; color:#0f172a; font-weight:800; font-size:12px; }"
            "QPushButton:checked { color:#1e40af; }"
        )
        cat = QLabel(f"{preset.category}  ·  {preset.difficulty}")
        cat.setStyleSheet("color:#64748b; font-size:10px; background:#f1f5f9; border:1px solid #e2e8f0; border-radius:8px; padding:3px 8px; font-weight:700;")
        cat.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        diff_color = {"Hard": "#dc2626", "Medium": "#d97706", "Easy": "#059669"}.get(preset.difficulty, "#64748b")
        cat.setStyleSheet(cat.styleSheet() + f" color:{diff_color};")
        btn_apply = QPushButton("Apply")
        btn_apply.setMinimumHeight(28)
        btn_apply.setToolTip(f"Load preset '{preset.name}' into the session (stops → resets → loads → restarts)")
        btn_apply.setStyleSheet("QPushButton { background:#0f172a; color:white; font-weight:800; border-radius:7px; padding:4px 14px; } QPushButton:hover { background:#1e293b; }")
        btn_apply.clicked.connect(lambda _, pid=preset.id: self.applyRequested.emit(pid))
        head.addWidget(btn_expand, 1)
        head.addWidget(cat)
        head.addWidget(btn_apply)
        lay.addLayout(head)

        # one-line summary under header (always visible)
        summ = QLabel(preset.description)
        summ.setWordWrap(True)
        summ.setStyleSheet("color:#475569; font-size:11px; padding:4px 2px 6px 4px;")
        lay.addWidget(summ)

        # Collapsible body
        body = QWidget()
        body.setVisible(False)
        blay = QVBoxLayout(body)
        blay.setContentsMargins(0, 8, 0, 4)
        blay.setSpacing(10)

        # ── Section 1: ABOUT ──
        about_box = self._section_frame("1  —  ABOUT THIS PRESET", "#0f172a", "#f8fafc")
        about_v = QVBoxLayout(about_box._content)  # type: ignore[attr-defined]
        about_v.setContentsMargins(10, 8, 10, 10)
        about_v.setSpacing(6)
        hint_a = QLabel("What this preset contains and why it is stressful. All presets share the MAX sky + MAX shake baseline above; this section explains what is unique.")
        hint_a.setWordWrap(True)
        hint_a.setStyleSheet("color:#94a3b8; font-size:10px; font-style:italic;")
        about_v.addWidget(hint_a)
        about_text = preset.about or preset.description
        about_lbl = QLabel(about_text)
        about_lbl.setWordWrap(True)
        about_lbl.setStyleSheet("color:#1e293b; font-size:11px; line-height:1.45;")
        about_lbl.setTextInteractionFlags(Qt.TextSelectableByMouse)
        about_v.addWidget(about_lbl)
        blay.addWidget(about_box)

        # ── Section 2: END GOAL ──
        goal_box = self._section_frame("2  —  END GOAL  ·  WHAT SUCCESS LOOKS LIKE", "#1e40af", "#eff6ff")
        goal_v = QVBoxLayout(goal_box._content)  # type: ignore[attr-defined]
        goal_v.setContentsMargins(10, 8, 10, 10)
        goal_v.setSpacing(6)
        hint_g = QLabel("The autonomy phase under test and the gating that must survive max stress. Failure here means that phase is not robust.")
        hint_g.setWordWrap(True)
        hint_g.setStyleSheet("color:#93b4ff; font-size:10px; font-style:italic;")
        goal_v.addWidget(hint_g)
        goal_text = preset.end_goal or preset.goal
        goal_lbl = QLabel(goal_text)
        goal_lbl.setWordWrap(True)
        goal_lbl.setStyleSheet("color:#1e3a8a; font-size:11px; font-weight:600; line-height:1.45;")
        goal_lbl.setTextInteractionFlags(Qt.TextSelectableByMouse)
        goal_v.addWidget(goal_lbl)
        blay.addWidget(goal_box)

        # ── Section 3: PARAMETERS — grouped tables with Value + Description ──
        params_outer = self._section_frame("3  —  PARAMETERS  ·  VALUES & WHAT EACH ONE MEANS", "#0f172a", "#ffffff")
        params_v = QVBoxLayout(params_outer._content)  # type: ignore[attr-defined]
        params_v.setContentsMargins(10, 8, 10, 10)
        params_v.setSpacing(10)
        hint_p = QLabel(
            "Every parameter the preset actually applies, grouped by subsystem. Value is the exact validated number loaded into the session; "
            "Description explains what it does and why that value is stressful. Beam, star and haze values are validated before apply."
        )
        hint_p.setWordWrap(True)
        hint_p.setStyleSheet("color:#94a3b8; font-size:10px; font-style:italic;")
        params_v.addWidget(hint_p)

        try:
            bundle = preset.bundle_builder() if callable(preset.bundle_builder) else {}
            groups = _bundle_to_groups(bundle)
        except Exception as e:
            log.debug("preset %s bundle preview failed: %s", preset.id, e)
            groups = []
            # fallback to legacy summary
            if preset.configs:
                groups = [("Summary (fallback)", [(k, v, "") for k, v in preset.configs])]

        for g_idx, (g_name, rows) in enumerate(groups):
            # group header
            g_hdr = QLabel(g_name.upper())
            g_hdr.setStyleSheet("color:#0f172a; font-size:10px; font-weight:800; letter-spacing:0.4px; padding-top:6px; border-top:1px solid #f1f5f9;")
            # subtitle with help
            g_help = QLabel(_GROUP_HELP.get(g_name, ""))
            g_help.setWordWrap(True)
            g_help.setStyleSheet("color:#64748b; font-size:10px; font-style:italic; padding-bottom:2px;")
            if g_idx == 0:
                g_hdr.setStyleSheet("color:#0f172a; font-size:10px; font-weight:800; letter-spacing:0.4px;")
            params_v.addWidget(g_hdr)
            if g_help.text():
                params_v.addWidget(g_help)
            # table
            grid = QGridLayout()
            grid.setHorizontalSpacing(8)
            grid.setVerticalSpacing(4)
            grid.setColumnStretch(0, 0)
            grid.setColumnStretch(1, 0)
            grid.setColumnStretch(2, 1)
            # column headers
            for col, txt in enumerate(["Parameter", "Value", "Description"]):
                h = QLabel(txt)
                h.setStyleSheet("color:#94a3b8; font-size:9px; font-weight:800; letter-spacing:0.5px; padding:2px 4px; border-bottom:1px solid #e2e8f0;")
                grid.addWidget(h, 0, col)
            for r, (param, value, desc) in enumerate(rows, start=1):
                p_lbl = QLabel(param)
                p_lbl.setStyleSheet("color:#334155; font-size:11px; font-weight:600; padding:2px 4px;")
                p_lbl.setTextInteractionFlags(Qt.TextSelectableByMouse)
                v_lbl = QLabel(value)
                v_lbl.setStyleSheet("color:#0f172a; font-size:11px; font-family:'Consolas','Courier New',monospace; font-weight:700; background:#f8fafc; border:1px solid #e2e8f0; border-radius:6px; padding:2px 6px;")
                v_lbl.setTextInteractionFlags(Qt.TextSelectableByMouse)
                v_lbl.setWordWrap(True)
                d_lbl = QLabel(desc)
                d_lbl.setWordWrap(True)
                d_lbl.setStyleSheet("color:#64748b; font-size:11px; padding:2px 4px;")
                d_lbl.setTextInteractionFlags(Qt.TextSelectableByMouse)
                bg = "#ffffff" if r % 2 == 1 else "#f8fafc"
                for w in (p_lbl, v_lbl, d_lbl):
                    w.setStyleSheet(w.styleSheet() + f" background:{bg};")
                grid.addWidget(p_lbl, r, 0)
                grid.addWidget(v_lbl, r, 1)
                grid.addWidget(d_lbl, r, 2)
            # wrap grid in a widget to add to vbox
            grid_w = QWidget()
            grid_w.setLayout(grid)
            params_v.addWidget(grid_w)

        blay.addWidget(params_outer)

        # ── Section 4: EXPECTED RESULTS ──
        res_outer = self._section_frame("4  —  EXPECTED RESULTS  ·  PASS CRITERIA", "#065f46", "#ecfdf5")
        res_v = QVBoxLayout(res_outer._content)  # type: ignore[attr-defined]
        res_v.setContentsMargins(10, 8, 10, 10)
        res_v.setSpacing(6)
        hint_r = QLabel("What a healthy run looks like under this stress. Times are wall-clock with the 60 FPS cap; haze may add one scan pass. Steal = wrong TID winning.")
        hint_r.setWordWrap(True)
        hint_r.setStyleSheet("color:#6ab99a; font-size:10px; font-style:italic;")
        res_v.addWidget(hint_r)
        res_grid = QGridLayout()
        res_grid.setHorizontalSpacing(8)
        res_grid.setVerticalSpacing(4)
        res_grid.setColumnStretch(1, 1)
        for col, txt in enumerate(["Metric", "Expected (pass)"]):
            h = QLabel(txt)
            h.setStyleSheet("color:#6ab99a; font-size:9px; font-weight:800; letter-spacing:0.5px; padding:2px 4px; border-bottom:1px solid #a7f3d0;")
            res_grid.addWidget(h, 0, col)
        for i, (k, v) in enumerate(preset.expected, start=1):
            k_lbl = QLabel(k)
            k_lbl.setStyleSheet("color:#064e3b; font-size:11px; font-weight:700; padding:2px 4px;")
            v_lbl = QLabel(v)
            v_lbl.setWordWrap(True)
            v_lbl.setStyleSheet("color:#065f46; font-size:11px; font-weight:700; background:#ffffff; border:1px solid #a7f3d0; border-radius:6px; padding:3px 8px;")
            v_lbl.setTextInteractionFlags(Qt.TextSelectableByMouse)
            res_grid.addWidget(k_lbl, i, 0)
            res_grid.addWidget(v_lbl, i, 1)
        res_w = QWidget()
        res_w.setLayout(res_grid)
        res_v.addWidget(res_w)

        # how to interpret note
        note = QLabel(
            "How to read this: run the preset, open Telemetry → Autonomy State. SEARCH should leave within the acquisition window; "
            "IDENTIFICATION should show correct TID; ASSOCIATION gate distance should stay inside the Value column above; "
            "LOST/REACQ counts should match Expected Results. Any steal or crash = fail."
        )
        note.setWordWrap(True)
        note.setStyleSheet("color:#047857; font-size:10px; font-style:italic; padding-top:4px;")
        res_v.addWidget(note)
        blay.addWidget(res_outer)

        # bottom Apply + hint
        bottom_row = QHBoxLayout()
        bottom_row.setSpacing(8)
        bottom_lbl = QLabel("Apply loads all parameters above into the live session (validated).")
        bottom_lbl.setStyleSheet("color:#94a3b8; font-size:10px; font-style:italic;")
        bottom_lbl.setWordWrap(True)
        bottom_apply = QPushButton("Apply this preset  →")
        bottom_apply.setMinimumHeight(32)
        bottom_apply.setStyleSheet("QPushButton { background:#0f172a; color:white; font-weight:800; border-radius:8px; padding:6px 16px; } QPushButton:hover { background:#1e293b; }")
        bottom_apply.clicked.connect(lambda _, pid=preset.id: self.applyRequested.emit(pid))
        bottom_row.addWidget(bottom_lbl, 1)
        bottom_row.addWidget(bottom_apply)
        blay.addLayout(bottom_row)

        lay.addWidget(body)

        def _toggle(checked: bool, _body=body, _btn=btn_expand, _name=preset.name):
            _body.setVisible(checked)
            _btn.setText(("▾  " if checked else "▸  ") + _name)
            if checked:
                self._expanded.add(preset.id)
            else:
                self._expanded.discard(preset.id)
        btn_expand.toggled.connect(_toggle)

        card._body = body  # type: ignore[attr-defined]
        card._expand = btn_expand  # type: ignore[attr-defined]
        card._apply = btn_apply  # type: ignore[attr-defined]
        return card

    def _section_frame(self, title: str, accent: str, bg: str) -> QFrame:
        """Helper: titled section frame with accent left border. Content goes into returned._content."""
        outer = QFrame()
        outer.setStyleSheet(f"QFrame {{ background:{bg}; border:1px solid #e2e8f0; border-left:3px solid {accent}; border-radius:8px; }}")
        lay = QVBoxLayout(outer)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        hdr = QLabel(title)
        hdr.setStyleSheet(f"color:{accent}; font-size:10px; font-weight:800; letter-spacing:0.5px; padding:8px 10px 6px 10px; border-bottom:1px solid #e2e8f0;")
        lay.addWidget(hdr)
        inner = QFrame()
        inner.setStyleSheet("QFrame { border:none; background:transparent; }")
        lay.addWidget(inner)
        outer._content = inner  # type: ignore[attr-defined]
        return outer

    # Back-compat helpers for set_config/collect if panel ever needs to be treated as config panel
    def collect_config(self):
        return None

    def set_config(self, cfg, emit: bool = False):
        pass


__all__ = ["PresetsPanel", "PresetDefinition", "get_preset_definitions", "apply_preset_to_session"]

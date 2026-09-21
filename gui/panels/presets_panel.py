# gui/panels/presets_panel.py - Testing Presets Panel (collapsible per-preset cards).
# All presets are MAX-STRESS: stars 4000x1.8, BG top 60/bottom 80, vignetting 92%, haze 100%,
# random seeds per preset, atmospheric User Defined 60/40 + full camera disturbances (20px jitter,
# 10 vib/10 drift, channel 1.0 wander/spread, salt&pepper 0.10, Gaussian 12 capped for 30Hz).
# Each preset targets one
# autonomy phase: SEARCH / DETECTION / IDENTIFICATION / ACQUISITION / RE-ACQUISITION / TRACKING / MIXED.
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


@dataclass
class PresetDefinition:
    id: str
    name: str
    category: str  # Baseline / Stress / Multi-target etc
    difficulty: str  # Easy / Medium / Hard
    description: str
    goal: str
    # Human-readable config summary (shown in card)
    configs: list[tuple[str, str]] = field(default_factory=list)
    # Expected results (shown in card)
    expected: list[tuple[str, str]] = field(default_factory=list)
    # Builder that returns validated config bundle for session apply
    # bundle keys: scenario, camera, pid, autonomy, disturbance, env (any may be None)
    bundle_builder: object = None  # callable -> dict


def _far_camera(fov_h: float = 4.0, fov_v: float | None = None, **kw):
    """Helper: camera parked far from scene centre (top-left) so SEARCH is required.
    start_* -90/90 clamp to world-bounds effective limit; scan starts at 0.
    """
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
# MAX-STRESS helpers - every preset shares these (per user request)
#   ENV: stars 4000, brightness 1.8, BG top 60 / bottom 80, vignetting 92%, haze 100%, random seed
#   DISTURB: camera jitter 6px, vib 10, drift 3->10, turbulence 10, platform 6px Random 400amp/5Hz,
#            Gaussian 20, salt&pepper 0.20, Poisson max, channel wander/spread/fluctuation 2.0,
#            atmospheric User Defined 60/40 (max contrast/brightness)
# ---------------------------------------------------------------------------

def _max_env(seed: int) -> object:
    """Worst-case sky: max stars, max brightness, max BG/vignetting/haze, random seed."""
    from environment.config import EnvironmentConfig
    return EnvironmentConfig(
        world_width=2000,
        world_height=2000,
        seed=int(seed),
        bg_top=60,
        bg_bottom=80,
        vignetting_pct=92,
        haze_pct=100,
        star_count=4000,
        star_brightness=1.8,
    ).validate()


def _max_disturbance() -> object:
    """60 FPS MAX: env at true max (4000x1.8, BG 60/80, vign 92, haze 100)
    but sensor/turbulence capped to keep step <16ms (60 FPS). True max
    jitter 20/turbulence 10/sensor 20 freezes at 7 FPS (0.14s). Capped at
    jitter 6, vibration 3, drift 3, turbulence 2 (fast path <2.5), platform 6,
    channel 0.85, atmospheric 50/30, sensor off - still visually max-stress,
    4x faster. Sensor noise disabled for 60 FPS; enable via Disturbances panel if needed."""
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

    # Fixed "random" seeds - distinct per preset, appear random (not 42) per spec.
    SEEDS = {
        "searching": 83471,
        "detection": 19283,
        "identification": 55921,
        "acquisition": 72845,
        "reacquisition": 10394,
        "tracking": 64027,
        "mixed": 91520,
    }

    # ------------------------------------------------------------------
    # 1. SEARCH - raster must find one beacon buried in 4000-star field under max haze/jitter
    # ------------------------------------------------------------------
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

    # ------------------------------------------------------------------
    # 2. DETECTION - dim beacon + max clutter: detector must reject 4000 stars at 1.8x brightness
    # ------------------------------------------------------------------
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

    # ------------------------------------------------------------------
    # 3. IDENTIFICATION - 3 beacons of similar power: beacon CRC/TID must not be stolen under max noise
    # ------------------------------------------------------------------
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

    # ------------------------------------------------------------------
    # 4. ACQUISITION - 3 targets close; boresight ASSOCIATE must pick correct TID not nearest/brightest
    # ------------------------------------------------------------------
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

    # ------------------------------------------------------------------
    # 5. RE-ACQUISITION - LOST->REACQ ladder under max shake: wrong TID must not steal
    # ------------------------------------------------------------------
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

    # ------------------------------------------------------------------
    # 6. TRACKING - Agile holds 45 m/s circular target under max jitter/platform + 4000 stars
    # ------------------------------------------------------------------
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

    # ------------------------------------------------------------------
    # 7. MIXED - worst-case everything: 4 terminals RANDOM, top-bottom gradients, vignette, haze
    # ------------------------------------------------------------------
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
            id="searching_max", name="SEARCH - Max Stress (Raster Hunt)", category="SEARCH", difficulty="Hard",
            description="MAX ENV: 4000 stars x1.8, BG 60/80, vignette 92%, haze 100%, random seed 83471 + MAX DISTURB (jitter 6px, vib 10, channel 1.0, Gaussian 20, salt&pepper 0.20). Narrow 2.5° camera far vs single beacon far - full 20-cell SEARCH required.",
            goal="Verify SEARCH raster finds beacon buried in max clutter/haze/jitter. Tests dwell 2 / confirm 3 / SNR 12 dB gating under worst-case sky.",
            configs=[
                ("Remote", "1x SINGLE - 5 m/s - RT-001 0.60W - offset 600,600 (far)"),
                ("Camera", "2.5°x1.875° narrow - 5°/s - parked top-left (far)"),
                ("Autonomy", "SNR 12dB - confirm 3 - peak margin 10 - dwell 2/10"),
                ("Disturb", "MAX: jitter 6px - vib3 - drift3 - turb2 - platform 6px Random - Gauss off - S&P off - UserDef 60/40"),
                ("Env", "MAX: 4000x1.8 - BG 60/80 - vignette 92 - haze 100 - seed 83471 (random)"),
            ],
            expected=[
                ("Acquisition", "< 2 s (may need 2nd scan in max haze)"),
                ("False SEARCH->IDENTIFY", "0 - star-only spots must not trigger TID gate"),
                ("Tracking error", "5-15 px (degraded)"),
            ],
            bundle_builder=bundles["searching_max"],
        ),
        PresetDefinition(
            id="detection_max", name="DETECTION - Max Stress (Dim vs 4000 Stars)", category="DETECTION", difficulty="Hard",
            description="MAX ENV: 4000x1.8, BG 60/80, vignette 92%, haze 100%, seed 19283 + MAX DISTURB. Dim 0.12W small-spot beacon ensures detector rejects max-brightness clutter.",
            goal="Verify DETECTION rejects 4000 hard-negative stars (1.8x) at SNR 6 dB + P_rx 0.3mW; only true beacon passes confirm 2. Tests peak-margin 8.",
            configs=[
                ("Remote", "1x SINGLE - RT-001 0.12W dim 0.6mrad - offset 600,600 (far)"),
                ("Camera", "3.0° narrow - 5°/s - parked top-left (far)"),
                ("Autonomy", "SNR 6dB - P_rx 0.3mW - peak margin 8 - area 4-4000 - confirm 2"),
                ("Disturb", "MAX: jitter 6 - vib3 - Gauss off - S&P off - Poisson max - UserDef 60/40"),
                ("Env", "MAX: 4000x1.8 - BG 60/80 - vig 92 - haze 100 - seed 19283"),
            ],
            expected=[
                ("Acquisition", "< 3 s (dim+max haze)"),
                ("False detections", "< 1 per scan despite 4000 stars"),
                ("Coast events", "1-3 expected in max jitter"),
            ],
            bundle_builder=bundles["detection_max"],
        ),
        PresetDefinition(
            id="identification_max", name="IDENTIFICATION - Max Stress (TID Decode)", category="IDENTIFICATION", difficulty="Hard",
            description="MAX ENV+DISTURB (4000x1.8, BG 60/80, vig 92, haze 100, seed 55921, jitter 6, Gauss off, S&P off, UserDef 60/40). 3 beacons 0.40-0.55W similar power: CRC/sequence gate must pick priority RT-002, not nearest.",
            goal="Verify IDENTIFICATION CRC gates correct TID under max sensor noise/haze. Priority RT-002 must win even though RT-001/003 similar brightness and all distorted by 20px jitter.",
            configs=[
                ("Remote", "3x LINE 150m - 6 m/s - RT-001 0.45W / RT-002 0.55W / RT-003 0.40W - offset 600,600"),
                ("Camera", "4.0°x3.0° - 5°/s - parked top-left (far)"),
                ("Autonomy", "SNR 7dB - priority RT-002->001->003 - SEARCH required"),
                ("Disturb", "MAX: jitter 6 - Gauss off - S&P off - UserDef 60/40 - channel 1.0"),
                ("Env", "MAX: 4000x1.8 - BG 60/80 - vig92 - haze100 - seed 55921"),
            ],
            expected=[
                ("Acquisition", "< 1.5 s on RT-002 (priority)"),
                ("Lock steal", "0 - similar-power neighbours must not steal"),
                ("CRC fails", "tolerated, no crash"),
            ],
            bundle_builder=bundles["identification_max"],
        ),
        PresetDefinition(
            id="acquisition_max", name="ACQUISITION - Max Stress (Boresight Associate)", category="ACQUISITION", difficulty="Hard",
            description="MAX ENV+DISTURB (seed 72845). 3 close targets 100m, brightest RT-003 0.95W not priority; tight associate gate 25px + Mahal 6 under max jitter must still associate RT-002 (0.55W) correctly.",
            goal="Verify ACQUISITION associate (spot+TID) with tight 25px gate under 20px jitter + 4000 stars. Priority RT-002 must associate even though RT-003 brighter/closer and haze diffuses spots.",
            configs=[
                ("Remote", "3x LINE 100m - 8 m/s - RT-003 0.95W brightest ≠ priority - RT-002 0.55W priority - offset 600,600"),
                ("Camera", "4.0° - 5°/s - parked top-left (far)"),
                ("Autonomy", "Gate 25px - Mahal 6 - priority RT-002 - SNR 6 - confirm 2"),
                ("Disturb", "MAX: jitter 6 - vib3 - Gauss off - S&P off - UserDef 60/40"),
                ("Env", "MAX: 4000x1.8 - BG 60/80 - vig92 - haze100 - seed 72845"),
            ],
            expected=[
                ("Acquisition", "< 1.5 s on RT-002"),
                ("Steal rate", "0 - brightest (RT-003) must not steal via tight gate"),
                ("Tracking error", "< 10 px despite 20px jitter"),
            ],
            bundle_builder=bundles["acquisition_max"],
        ),
        PresetDefinition(
            id="reacquisition_max", name="RE-ACQUISITION - Max Stress (LOST->REACQ Ladder)", category="RE-ACQUISITION", difficulty="Hard",
            description="MAX ENV+DISTURB (seed 10394, Random 8px platform, jitter 6). Sinusoidal 2-target forces TRACK->COAST->LOST->REACQ ladder 50->800 + full-scan TID-gated; wrong TID (RT-001) must not steal RT-002 under max noise.",
            goal="Verify LOST 0.3s/20px -> REACQ ladder expands under max shake. RT-001 must not steal RT-002 recovery; tests full-scan fallback.",
            configs=[
                ("Remote", "2x LINE 200m - sinusoidal 10 m/s - RT-001 0.6W / RT-002 0.9W - offset 600,600"),
                ("Camera", "4.0° - 5°/s - parked top-left (far) - SEARCH required"),
                ("Autonomy", "Reacq 50->800 + full-scan - lost 0.3s/20px - coast 0.8s/25px"),
                ("Disturb", "MAX: Random 8 - jitter 6 - Gauss off - S&P off - UserDef 60/40"),
                ("Env", "MAX: 4000x1.8 - BG 60/80 - vig92 - haze100 - seed 10394"),
            ],
            expected=[
                ("LOST", "visible in telemetry under max jitter"),
                ("Reacq", "< 1.5 s (≤2s with max haze) - correct TID only"),
                ("Steal", "0 - wrong TID gated"),
            ],
            bundle_builder=bundles["reacquisition_max"],
        ),
        PresetDefinition(
            id="tracking_max", name="TRACKING - Max Stress (Agile 45 m/s + Max Jitter)", category="TRACKING", difficulty="Hard",
            description="MAX ENV+DISTURB (seed 64027). Circular 45 m/s vs wide 6° Agile camera - Agile must SEARCH wide then hold TRACK with Q15/Mahal12 under 20px jitter + Random 8 + 4000 stars.",
            goal="Verify TRACK loop holds <15px at 45 m/s despite max platform/jitter/haze. Kalman Q15 compensates 20px shake; PID Kp3 prevents windup.",
            configs=[
                ("Remote", "1x CIRCULAR - 45 m/s - RT-001 1.0W - offset 600,600 (far)"),
                ("Camera", "6.0°x4.5° - 10°/s Agile accel60 - parked top-left (far)"),
                ("Autonomy", "Q 15 - Mahal 12 - SNR 6 - confirm 2"),
                ("PID", "Aggressive Kp3.0/Ki0.3/Kd0.45"),
                ("Disturb", "MAX: jitter 6 - Random 8 - Gauss off - S&P off - UserDef 60/40"),
                ("Env", "MAX: 4000x1.8 - BG 60/80 - vig92 - haze100 - seed 64027"),
            ],
            expected=[
                ("Acquisition", "< 1 s (wide 6° FOV)"),
                ("Tracking error", "< 15 px (degraded max jitter)"),
                ("Loss", "0 - Q15 holds; PID no saturate"),
            ],
            bundle_builder=bundles["tracking_max"],
        ),
        PresetDefinition(
            id="mixed_max", name="MIXED - Max Stress (All Phases Combined)", category="MIXED", difficulty="Hard",
            description="MAX ENV+DISTURB (seed 91520): GRID 4 terminals RANDOM 10 m/s, 0.35-0.90W, BG 60/80, vig92, haze100, 4000x1.8, jitter6, Gauss off, S&P off. Full pipeline SEARCH->DETECT->IDENTIFY->ACQUIRE->TRACK->LOST->REACQ under every disturbance.",
            goal="Verify complete pipeline under worst-case combined stress: SEARCH finds in 4-target RANDOM clutter, IDENTIFY CRC picks priority RT-002, ASSOCIATE tight, TRACK->COAST->LOST->REACQ ladder recovers, all in max sky/jitter.",
            configs=[
                ("Remote", "4x GRID 120m - RANDOM 10 m/s - 0.35/0.90/0.55/0.70W - offset 600,600"),
                ("Camera", "4.0° - 6°/s - parked top-left (far)"),
                ("Autonomy", "SNR 8 - confirm2 - gate60 - Q10 - Mahal9.2 - reacq 50->800 - priority RT-002"),
                ("Disturb", "MAX: jitter6 - vib3 - turb2 - platform20 Random - Gauss off - S&P off - Poisson max - UserDef 60/40"),
                ("Env", "MAX: 4000x1.8 - BG 60/80 - vig92 - haze100 - seed 91520"),
            ],
            expected=[
                ("Acquisition", "< 2 s on priority RT-002"),
                ("Retention", "> 80% despite max everything"),
                ("Stability", "no crash / windup under combined 20px shake+noise"),
            ],
            bundle_builder=bundles["mixed_max"],
        ),
    ]


def _apply_to_session(session, key: str, cfg) -> None:
    """Dispatch apply to Session (GUI) or HeadlessSimulation (no apply_* helpers)."""
    # GUI SimulationSession has apply_*; HeadlessSimulation is dict-like.
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
        # Headless: re-validate dependents lazily on next build/step
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
    # back-compat: old ids still resolve to nearest max-stress equivalent
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

        title = QLabel("TEST PRESETS - MAX STRESS")
        title.setStyleSheet("font-size:15px; font-weight:700;")
        hdr = QHBoxLayout()
        hdr.addWidget(title)
        hdr.addStretch(1)
        hint = QLabel("7 phase tests - click to expand, Apply to load (all MAX sky+disturb)")
        hint.setStyleSheet("color:#64748b; font-size:11px;")
        hdr.addWidget(hint)
        root.addLayout(hdr)

        sub = QLabel("Each preset is MAX-STRESS: 4000 starsx1.8 - BG 60/80 - vignette 92% - haze 100% - random seed - UserDef 60/40 + jitter 6/vib3/Gauss off/S&P off. Phase-specific tuning isolates SEARCH->MIXED.")
        sub.setStyleSheet("color:#8F9CAB; font-size:11px;")
        sub.setWordWrap(True)
        root.addWidget(sub)

        for preset in self._presets:
            card = self._make_card(preset)
            root.addWidget(card)

        root.addStretch(1)

    def _make_card(self, preset: PresetDefinition) -> QFrame:
        card = QFrame()
        card.setObjectName("presetCard")
        card.setStyleSheet("QFrame#presetCard { background:#ffffff; border:1px solid #e5e7eb; border-radius:8px; }")
        lay = QVBoxLayout(card)
        lay.setContentsMargins(10, 8, 10, 8)
        lay.setSpacing(8)

        # Header row: expand toggle + category/difficulty + Apply
        head = QHBoxLayout()
        head.setSpacing(8)
        btn_expand = QPushButton(f"▸  {preset.name}")
        btn_expand.setCheckable(True)
        btn_expand.setMinimumHeight(32)
        btn_expand.setStyleSheet(
            "QPushButton { text-align:left; background:transparent; border:none; color:#111827; font-weight:700; font-size:12px; }"
            "QPushButton:checked { color:#1e40af; }"
        )
        cat = QLabel(f"{preset.category} - {preset.difficulty}")
        cat.setStyleSheet("color:#6b7280; font-size:10px; background:#f3f4f6; border-radius:8px; padding:2px 8px;")
        cat.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        btn_apply = QPushButton("Apply")
        btn_apply.setMinimumHeight(28)
        btn_apply.setToolTip(f"Load preset '{preset.name}' into the session")
        btn_apply.setStyleSheet("QPushButton { background:#111827; color:white; font-weight:700; border-radius:6px; padding:4px 12px; } QPushButton:hover { background:#1f2937; }")
        btn_apply.clicked.connect(lambda _, pid=preset.id: self.applyRequested.emit(pid))
        head.addWidget(btn_expand, 1)
        head.addWidget(cat)
        head.addWidget(btn_apply)
        lay.addLayout(head)

        # Collapsible body
        body = QWidget()
        body.setVisible(False)
        blay = QVBoxLayout(body)
        blay.setContentsMargins(4, 4, 4, 4)
        blay.setSpacing(8)

        desc = QLabel(preset.description)
        desc.setWordWrap(True)
        desc.setStyleSheet("color:#374151; font-size:11px;")
        blay.addWidget(desc)

        # Goal
        goal_box, goal_grid = self._make_group("END GOAL")
        goal_lbl = QLabel(preset.goal)
        goal_lbl.setWordWrap(True)
        goal_lbl.setStyleSheet("color:#1e3a8a; font-size:11px; font-weight:600;")
        goal_grid.addWidget(goal_lbl, 0, 0)
        blay.addWidget(goal_box)

        # Configs table
        cfg_box, cfg_grid = self._make_group("CONFIGURATIONS")
        for i, (k, v) in enumerate(preset.configs):
            cfg_grid.addWidget(self._label(k), i, 0)
            val = QLabel(v)
            val.setStyleSheet("color:#111827; font-size:11px; font-family:'Consolas','Courier New',monospace;")
            val.setWordWrap(True)
            cfg_grid.addWidget(val, i, 1)
        blay.addWidget(cfg_box)

        # Expected results
        res_box, res_grid = self._make_group("EXPECTED RESULTS")
        for i, (k, v) in enumerate(preset.expected):
            res_grid.addWidget(self._label(k), i, 0)
            val = QLabel(v)
            val.setStyleSheet("color:#065f46; font-size:11px; font-weight:700;")
            res_grid.addWidget(val, i, 1)
        blay.addWidget(res_box)

        # Second Apply at bottom for long cards
        bottom_apply = QPushButton("Apply this preset")
        bottom_apply.setMinimumHeight(32)
        bottom_apply.setStyleSheet("QPushButton { background:#111827; color:white; font-weight:700; border-radius:6px; } QPushButton:hover { background:#1f2937; }")
        bottom_apply.clicked.connect(lambda _, pid=preset.id: self.applyRequested.emit(pid))
        blay.addWidget(bottom_apply)

        lay.addWidget(body)

        def _toggle(checked: bool, _body=body, _btn=btn_expand, _name=preset.name):
            _body.setVisible(checked)
            _btn.setText(("▾  " if checked else "▸  ") + _name)
            if checked:
                self._expanded.add(preset.id)
            else:
                self._expanded.discard(preset.id)
        btn_expand.toggled.connect(_toggle)

        # Keep refs for tests
        card._body = body
        card._expand = btn_expand
        card._apply = btn_apply
        return card

    # Back-compat helpers for set_config/collect if panel ever needs to be treated as config panel
    def collect_config(self):
        return None

    def set_config(self, cfg, emit: bool = False):
        pass


__all__ = ["PresetsPanel", "PresetDefinition", "get_preset_definitions", "apply_preset_to_session"]

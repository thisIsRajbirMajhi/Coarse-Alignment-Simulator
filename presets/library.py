"""
Module: presets.library
Purpose: Library of 7 curated presets covering baseline to full stress (well-commented).
Public API: PRESETS, get_preset, PRESET_CATEGORIES
Notes: Each preset configures entire software (environment, camera, beacons, disturbances, controller, overlay, detection, tracking)
       and defines a brief end goal — what to observe / expected metric.

Categories:
  baseline — ideal, should lock 100%
  turbulence — atmospheric
  vibration — platform
  distractors — multi-beacon
  dynamics — agile target
  snr — low signal
  acquisition — reacquisition cycle
  stress — all max

Goals are phrased as "Observe ... — expect ..." for quick test guidance.
"""

from presets.preset import Preset

# ============================================================
# SECTION: Presets — 7 curated test cases
# ============================================================

PRESETS: list[Preset] = [
    # 1 — Ideal Baseline (should always pass)
    Preset(
        name="1 — Ideal · Baseline",
        description="No disturbances, 1 beacon linear 40 px/s, bright (255) radius 5, FOV 250, P controller Kp 0.15.",
        goal="Goal: Verify acquisition <1s, lock retention ~100%, avg error <5 px. Baseline for all other tests.",
        category="baseline",
        environment={"world_width": 1000, "world_height": 1000, "seed": 42, "haze_pct": 15, "star_count": 40, "vignetting_pct": 0, "dynamic": False},
        camera={"fov_width": 250, "fov_height": 250, "max_slew_rate": 1000, "resolution": 0.1, "latency_ms": 10, "pixel_scale_mrad": 0.035},
        beacons={"beacon_count": 1, "target_index": 0, "beacons": [{"profile": "linear", "speed": 40, "brightness": 255, "radius": 5, "hitbox_radius": 14, "center_radius": 2, "position_seed": 42}]},
        disturbances={"Turbulence": 0, "Vibration": 0, "Camera Motion": 0, "Noise": 0},
        controller={"controller_type": "P", "kp": 0.15, "dead_zone": 2, "output_clamp": 80, "update_rate_hz": 30},
        overlay={"crosshair_style": "cross+bracket", "error_units": "px"},
        detector={"brightness_threshold": 190},
        tracker={"smoothing": 0.4, "miss_limit": 5},
        target={"profile": "linear", "speed": 40},
    ),

    # 2 — Turbulence Stress
    Preset(
        name="2 — Turbulence Stress",
        description="Turbulence 7, haze 45%, star 80, vignetting 15%, 1 beacon curved 60 px/s, FOV 220. Tests warping + scintillation.",
        goal="Goal: Observe lock jitter but retention >80%, error <12 px. Validates seeing blur + warp handling.",
        category="turbulence",
        environment={"world_width": 1000, "world_height": 1000, "seed": 101, "haze_pct": 45, "star_count": 80, "vignetting_pct": 15, "bg_top": 10, "bg_bottom": 30, "star_brightness": 1.2, "dynamic": True, "dynamic_speed": 1.0},
        camera={"fov_width": 220, "fov_height": 220, "max_slew_rate": 700, "resolution": 0.2, "latency_ms": 30, "pixel_scale_mrad": 0.035},
        beacons={"beacon_count": 1, "target_index": 0, "beacons": [{"profile": "curved", "speed": 60, "brightness": 255, "radius": 5, "hitbox_radius": 16, "center_radius": 3}]},
        disturbances={"Turbulence": 7, "Vibration": 1, "Camera Motion": 1, "Noise": 2},
        controller={"controller_type": "PI", "kp": 0.18, "ki": 0.03, "dead_zone": 2, "output_clamp": 70, "update_rate_hz": 30},
        overlay={"crosshair_style": "all", "error_units": "px+mrad"},
        detector={"brightness_threshold": 195},
        target={"profile": "curved", "speed": 60},
    ),

    # 3 — Platform Vibration & Drift
    Preset(
        name="3 — Platform Vibration",
        description="Vibration 8, Camera Motion 7, Noise 5, Turbulence 2, 1 beacon linear 70 px/s. Tests mount jitter + thermal drift (OU).",
        goal="Goal: Check vibration harmonic + OU drift: lock should hold with increased RMS but not lose. Expect reacquisition <0.5s if lost.",
        category="vibration",
        environment={"world_width": 1000, "world_height": 1000, "seed": 202, "haze_pct": 25, "star_count": 60},
        camera={"fov_width": 250, "fov_height": 250, "max_slew_rate": 900, "resolution": 0.1, "latency_ms": 40, "pixel_scale_mrad": 0.035},
        beacons={"beacon_count": 1, "target_index": 0, "beacons": [{"profile": "linear", "speed": 70, "brightness": 255, "radius": 5, "hitbox_radius": 14, "center_radius": 2}]},
        disturbances={"Turbulence": 2, "Vibration": 8, "Camera Motion": 7, "Noise": 5},
        controller={"controller_type": "PID", "kp": 0.16, "ki": 0.02, "kd": 0.04, "dead_zone": 3, "output_clamp": 90, "update_rate_hz": 40},
        overlay={"crosshair_style": "cross+bracket", "error_units": "px"},
        detector={"brightness_threshold": 200},
        target={"profile": "linear", "speed": 70},
    ),

    # 4 — Multi-Beacon Distractors
    Preset(
        name="4 — Multi-Beacon Distractors",
        description="4 beacons (target #2, hitbox 14), distractors random_walk/zigzag, Vibration 2, Turbulence 2. Tests hitbox-gated target-only tracking.",
        goal="Goal: Target #2 stays locked while distractors cross FOV — retention >90%, no false switch. Validate hitbox gating.",
        category="distractors",
        environment={"world_width": 1000, "world_height": 1000, "seed": 303, "haze_pct": 30, "star_count": 50},
        camera={"fov_width": 260, "fov_height": 260, "max_slew_rate": 800, "resolution": 0.1, "latency_ms": 25, "pixel_scale_mrad": 0.035},
        beacons={"beacon_count": 4, "target_index": 2, "beacons": [
            {"profile": "linear", "speed": 50, "brightness": 255, "radius": 5, "hitbox_radius": 14, "center_radius": 2, "position_seed": 10},
            {"profile": "random_walk", "speed": 55, "brightness": 240, "radius": 5, "hitbox_radius": 14, "center_radius": 2, "position_seed": 11},
            {"profile": "curved", "speed": 60, "brightness": 255, "radius": 5, "hitbox_radius": 14, "center_radius": 2, "position_seed": 12},
            {"profile": "zigzag", "speed": 55, "brightness": 240, "radius": 5, "hitbox_radius": 14, "center_radius": 2, "position_seed": 13},
        ]},
        disturbances={"Turbulence": 2, "Vibration": 2, "Camera Motion": 2, "Noise": 3},
        controller={"controller_type": "P", "kp": 0.15, "dead_zone": 2, "output_clamp": 80, "update_rate_hz": 30},
        overlay={"crosshair_style": "cross+bracket", "lock_circle_radius": 0, "error_units": "px"},
        detector={"brightness_threshold": 200},
        target={"profile": "curved", "speed": 60},
    ),

    # 5 — High Dynamics (agile target, PID needed)
    Preset(
        name="5 — High Dynamics",
        description="1 beacon random_walk 120 px/s, FOV 200 (tight), PID Kp 0.20 Ki 0.04 Kd 0.05, slew 400 px/s limited, latency 60 ms. Tests agility + actuator limits.",
        goal="Goal: Observe overshoot/lag with P vs PID — PID should hold <10 px avg, P would oscillate. Validates derivative damping under slew/latency.",
        category="dynamics",
        environment={"world_width": 1000, "world_height": 1000, "seed": 404, "haze_pct": 20, "star_count": 60},
        camera={"fov_width": 200, "fov_height": 200, "max_slew_rate": 400, "resolution": 0.3, "latency_ms": 60, "pixel_scale_mrad": 0.05},
        beacons={"beacon_count": 1, "target_index": 0, "beacons": [{"profile": "random_walk", "speed": 120, "brightness": 255, "radius": 5, "hitbox_radius": 14, "center_radius": 2}]},
        disturbances={"Turbulence": 3, "Vibration": 3, "Camera Motion": 3, "Noise": 2},
        controller={"controller_type": "PID", "kp": 0.20, "ki": 0.04, "kd": 0.05, "dead_zone": 2, "output_clamp": 60, "update_rate_hz": 40},
        overlay={"crosshair_style": "all", "error_units": "mrad"},
        detector={"brightness_threshold": 195},
        target={"profile": "random_walk", "speed": 120},
    ),

    # 6 — Low SNR / Dim Beacon
    Preset(
        name="6 — Low SNR · Dim Beacon",
        description="Dim beacon 180, radius 3, Noise 8, Turbulence 5, haze 40%, threshold 200 strict. Tests threshold vs false positives.",
        goal="Goal: Detection rate drops, lock may flicker — tune threshold 190->210 to see trade-off. Expect retention 60-80%, search time  up .",
        category="snr",
        environment={"world_width": 1000, "world_height": 1000, "seed": 505, "haze_pct": 40, "star_count": 90, "vignetting_pct": 20, "star_brightness": 1.3},
        camera={"fov_width": 250, "fov_height": 250, "max_slew_rate": 700, "resolution": 0.2, "latency_ms": 30, "pixel_scale_mrad": 0.035},
        beacons={"beacon_count": 1, "target_index": 0, "beacons": [{"profile": "linear", "speed": 50, "brightness": 180, "radius": 3, "hitbox_radius": 14, "center_radius": 2}]},
        disturbances={"Turbulence": 5, "Vibration": 2, "Camera Motion": 2, "Noise": 8},
        controller={"controller_type": "PI", "kp": 0.14, "ki": 0.03, "dead_zone": 4, "output_clamp": 70, "update_rate_hz": 30},
        overlay={"crosshair_style": "cross", "error_units": "px"},
        detector={"brightness_threshold": 200},
        target={"profile": "linear", "speed": 50},
    ),

    # 7 — Acquisition & Reacquisition Cycle
    Preset(
        name="7 — Acquisition Cycle",
        description="1 beacon waypoint 60 px/s, Turbulence 6, Noise 6, miss_limit 5, FOV 250. Beacon exits/enters FOV — tests SEARCHING->ACQUIRED(3 hits)->TRACKING->LOST(5 misses)->SEARCHING(10 misses) + reacquisition.",
        goal="Goal: Observe full lock state cycle: Searching (None) -> Acquired (probation) -> Tracking (locked, retention counts) -> Lost (keeps estimate, reacquires to Acquired) -> Searching (discard). Measure acquisition & reacquisition times.",
        category="acquisition",
        environment={"world_width": 1200, "world_height": 1000, "seed": 606, "haze_pct": 35, "star_count": 60},
        camera={"fov_width": 250, "fov_height": 250, "max_slew_rate": 600, "resolution": 0.2, "latency_ms": 40, "pixel_scale_mrad": 0.035},
        beacons={"beacon_count": 1, "target_index": 0, "beacons": [{"profile": "waypoint", "speed": 60, "brightness": 255, "radius": 5, "hitbox_radius": 14, "center_radius": 2}]},
        disturbances={"Turbulence": 6, "Vibration": 3, "Camera Motion": 3, "Noise": 6},
        controller={"controller_type": "P", "kp": 0.15, "dead_zone": 2, "output_clamp": 80, "update_rate_hz": 30},
        overlay={"crosshair_style": "cross+bracket", "pulse_enabled": True, "error_units": "px+mrad"},
        detector={"brightness_threshold": 200},
        tracker={"smoothing": 0.4, "miss_limit": 5, "acquire_hits": 3},
        target={"profile": "waypoint", "speed": 60},
    ),

    # 8 — Full Stress (all max)
    Preset(
        name="8 — Full Stress",
        description="All disturbances 9, 2 beacons (target #0), random_walk 80, dim 200, FOV 220, PID. Tests worst-case: expect frequent LOST, measure reacquisition time and retention drop.",
        goal="Goal: Stress test — lock retention <50%, reacquisition 1-2s, error p95  up . Use to find breaking point and tune PID vs P.",
        category="stress",
        environment={"world_width": 1000, "world_height": 1000, "seed": 707, "haze_pct": 50, "star_count": 100, "vignetting_pct": 25, "bg_top": 8, "bg_bottom": 35, "dynamic": True},
        camera={"fov_width": 220, "fov_height": 220, "max_slew_rate": 500, "resolution": 0.3, "latency_ms": 80, "pixel_scale_mrad": 0.05},
        beacons={"beacon_count": 2, "target_index": 0, "beacons": [
            {"profile": "random_walk", "speed": 80, "brightness": 200, "radius": 4, "hitbox_radius": 16, "center_radius": 3, "position_seed": 70},
            {"profile": "zigzag", "speed": 70, "brightness": 220, "radius": 4, "hitbox_radius": 16, "center_radius": 3, "position_seed": 71},
        ]},
        disturbances={"Turbulence": 9, "Vibration": 9, "Camera Motion": 9, "Noise": 9},
        controller={"controller_type": "PID", "kp": 0.18, "ki": 0.03, "kd": 0.05, "dead_zone": 3, "output_clamp": 70, "update_rate_hz": 30},
        overlay={"crosshair_style": "all", "error_units": "mrad"},
        detector={"brightness_threshold": 200},
        target={"profile": "random_walk", "speed": 80},
    ),
]

PRESET_CATEGORIES: list[str] = sorted(set(p.category for p in PRESETS))

def get_preset(name: str) -> Preset | None:
    for p in PRESETS:
        if p.name == name or p.name.lower() == name.lower():
            return p
    return None

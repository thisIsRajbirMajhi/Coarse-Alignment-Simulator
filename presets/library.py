# presets/library.py - Spec-aligned preset library per ISRO FSOC PS-4
# Covers: Sr.1 Screen≥2000, Sr.3 640×480, Sr.4 FOV 4°×3° (0.109 mrad/px), Sr.5 30Hz, Sr.6 centre,
# Sr.7-12 targets (10×10, linear/circular/fig-8/random + spiral/sinusoidal), Sr.13-15 slew 5-10°/s ≥20Hz,
# Sr.16-20 perf (acq≤2s err≤10px loss<5% reacq≤1s ≥20FPS), Sr.21 noise/jitter/platform/atmosphere.

from presets.preset import Preset

PRESETS: list[Preset] = [
    # 1 — Spec Baseline · Ideal compliance (all Sr.1-20 deterministic pass)
    Preset(
        name="1 — Spec Baseline · Ideal (2000×2000, 640×480 @4°×3°)",
        description="Sr.1 2000×2000, Sr.3-4 640×480 @0.109 mrad/px =4°×3° (≈69.8×52.4 mrad), Sr.5 30Hz centre (Sr.6), 1 beacon 10×10 (r5=10px Sr.9-10) linear 40px/s (Sr.12), slew 800px/s≈5°/s (Sr.13-14), update 30Hz (Sr.15), Clear (haze 0). No disturbances.",
        goal="Sr.16 acq ≤2s, Sr.17 err ≤10px, Sr.18 loss <5%, Sr.19 reacq ≤1s, Sr.20 ≥20FPS — expect lock ~100%, acq <0.8s, avg err <4px. Baseline for all.",
        category="baseline",
        environment={"world_width": 2000, "world_height": 2000, "seed": 42, "haze_pct": 0, "star_count": 40, "vignetting_pct": 0, "bg_top": 12, "bg_bottom": 22, "star_brightness": 1.0, "dynamic": False},
        camera={"fov_width": 640, "fov_height": 480, "max_slew_rate": 800, "resolution": 0.1, "latency_ms": 30, "pixel_scale_mrad": 0.109, "viewport_width": 640, "viewport_height": 480, "god_width": 640, "god_height": 480},
        beacons={"beacon_count": 1, "target_index": 0, "beacons": [{"profile": "linear", "speed": 40, "brightness": 255, "radius": 5, "hitbox_radius": 14, "center_radius": 2, "position_seed": 42}]},
        disturbances={"Turbulence": 0, "Vibration": 0, "Camera Motion": 0, "Noise": 0},
        controller={"controller_type": "P", "kp": 0.15, "dead_zone": 2, "output_clamp": 80, "update_rate_hz": 30},
        overlay={"crosshair_style": "cross+bracket", "error_units": "px"},
        detector={"brightness_threshold": 190},
        tracker={"smoothing": 0.4, "miss_limit": 5},
        target={"profile": "linear", "speed": 40},
    ),

    # 2 — Spec Motion · Circular (Curved alias) — Sr.12 mandatory Circular
    Preset(
        name="2 — Spec Motion · Circular (Curved) 50 px/s",
        description="Sr.12 Circular via 'curved' (orbit) 50px/s, Sr.1 2000×2000, Sr.3-4 640×480 @4°×3°, 30Hz centre, 1 beacon 10×10, slew 900≈5.6°/s (Sr.13-14 within 5-10°/s), Turb 2 mild haze 15% (Clear→Haze, Sr.21.4). Validates at least 4 motions: Straight, Circular, Fig-8, Random.",
        goal="Sr.16-19 hold: acq <1s, err <8px, loss <5%. Circular tests centripetal lag — P vs PID check.",
        category="circular",
        environment={"world_width": 2000, "world_height": 2000, "seed": 101, "haze_pct": 15, "star_count": 50, "vignetting_pct": 5, "bg_top": 12, "bg_bottom": 22, "star_brightness": 1.0, "dynamic": False},
        camera={"fov_width": 640, "fov_height": 480, "max_slew_rate": 900, "resolution": 0.1, "latency_ms": 30, "pixel_scale_mrad": 0.109, "viewport_width": 640, "viewport_height": 480, "god_width": 640, "god_height": 480},
        beacons={"beacon_count": 1, "target_index": 0, "beacons": [{"profile": "curved", "speed": 50, "brightness": 255, "radius": 5, "hitbox_radius": 14, "center_radius": 2, "position_seed": 101}]},
        disturbances={"Turbulence": 2, "Vibration": 1, "Camera Motion": 1, "Noise": 1},
        controller={"controller_type": "PI", "kp": 0.18, "ki": 0.03, "dead_zone": 2, "output_clamp": 80, "update_rate_hz": 30},
        overlay={"crosshair_style": "all", "error_units": "px+mrad"},
        detector={"brightness_threshold": 195},
        tracker={"smoothing": 0.4, "miss_limit": 5},
        target={"profile": "curved", "speed": 50},
    ),

    # 3 — Spec Motion · Figure of 8 — Sr.12 mandatory Figure of 8
    Preset(
        name="3 — Spec Motion · Figure-8 60 px/s",
        description="Sr.12 Figure of 8 (Lissajous) 60px/s, 2000×2000, 640×480 @4°×3°, 30Hz, 1 beacon 10×10, slew 900, Haze 20% moderate (Sr.21.4). Tests cross-over point where velocity reverses — checks prediction smoothing.",
        goal="Sr.17 err ≤10px through Fig-8 crossing; acq ≤2s, reacq ≤1s if occluded at crossover.",
        category="figure8",
        environment={"world_width": 2000, "world_height": 2000, "seed": 202, "haze_pct": 20, "star_count": 60, "vignetting_pct": 8, "bg_top": 12, "bg_bottom": 24, "star_brightness": 1.0, "dynamic": False},
        camera={"fov_width": 640, "fov_height": 480, "max_slew_rate": 900, "resolution": 0.1, "latency_ms": 30, "pixel_scale_mrad": 0.109, "viewport_width": 640, "viewport_height": 480, "god_width": 640, "god_height": 480},
        beacons={"beacon_count": 1, "target_index": 0, "beacons": [{"profile": "figure_eight", "speed": 60, "brightness": 255, "radius": 5, "hitbox_radius": 14, "center_radius": 2, "position_seed": 202}]},
        disturbances={"Turbulence": 2, "Vibration": 2, "Camera Motion": 2, "Noise": 2},
        controller={"controller_type": "PID", "kp": 0.16, "ki": 0.02, "kd": 0.04, "dead_zone": 2, "output_clamp": 80, "update_rate_hz": 30},
        overlay={"crosshair_style": "cross+bracket", "error_units": "px"},
        detector={"brightness_threshold": 195},
        tracker={"smoothing": 0.35, "miss_limit": 5},
        target={"profile": "figure_eight", "speed": 60},
    ),

    # 4 — Spec Motion · Random + Multi-Target (×3) — Sr.12 Random, Sr.8 multiple optional
    Preset(
        name="4 — Spec Motion · Random + Multi-Target (×3)",
        description="Sr.12 Random walk 55px/s, Sr.8 3 beacons (target #1 random_walk, distractors linear/curved) 10×10, Sr.11 random start (seeds), 2400×2000 user-defined >min (Sr.1 Optional), 640×480 @4°×3°, 30Hz. Tests hitbox-gated tracking + random predict.",
        goal="Sr.17-18: target #1 holds lock <10px while distractors cross — retention >90%, no false switch. Validates multi-beacon (Sr.8 optional).",
        category="random",
        environment={"world_width": 2400, "world_height": 2000, "seed": 303, "haze_pct": 18, "star_count": 55, "vignetting_pct": 5, "bg_top": 12, "bg_bottom": 22, "star_brightness": 1.0, "dynamic": False},
        camera={"fov_width": 640, "fov_height": 480, "max_slew_rate": 900, "resolution": 0.1, "latency_ms": 30, "pixel_scale_mrad": 0.109, "viewport_width": 640, "viewport_height": 480, "god_width": 640, "god_height": 480},
        beacons={"beacon_count": 3, "target_index": 1, "beacons": [
            {"profile": "linear", "speed": 45, "brightness": 255, "radius": 5, "hitbox_radius": 14, "center_radius": 2, "position_seed": 30},
            {"profile": "random_walk", "speed": 55, "brightness": 255, "radius": 5, "hitbox_radius": 14, "center_radius": 2, "position_seed": 31},
            {"profile": "curved", "speed": 50, "brightness": 255, "radius": 5, "hitbox_radius": 14, "center_radius": 2, "position_seed": 32},
        ]},
        disturbances={"Turbulence": 2, "Vibration": 2, "Camera Motion": 2, "Noise": 2},
        controller={"controller_type": "P", "kp": 0.15, "dead_zone": 2, "output_clamp": 80, "update_rate_hz": 30},
        overlay={"crosshair_style": "cross+bracket", "error_units": "px"},
        detector={"brightness_threshold": 195},
        tracker={"smoothing": 0.4, "miss_limit": 5},
        target={"profile": "random_walk", "speed": 55},
    ),

    # 5 — Spec Motion · Spiral + Sinusoidal (Optional Sr.12 Spiral, Sinusoidal, User-defined)
    Preset(
        name="5 — Spec Motion · Spiral + Sinusoidal (Optional)",
        description="Sr.12 Optional: Spiral 60px/s (target #0) + Sinusoidal distractor 45px/s, 2 beacons 10×10, 2000×2000, 640×480 @4°×3°, 30Hz, slew 850≈5.3°/s. Demonstrates spiral/sinusoidal/user-defined beyond mandatory 4.",
        goal="Sr.17 spiral radius pulsation + sinusoidal horizontal drift — err <10px with PID. Validates optional profiles.",
        category="spiral",
        environment={"world_width": 2000, "world_height": 2000, "seed": 404, "haze_pct": 12, "star_count": 60, "vignetting_pct": 6, "bg_top": 12, "bg_bottom": 22, "star_brightness": 1.0, "dynamic": False},
        camera={"fov_width": 640, "fov_height": 480, "max_slew_rate": 850, "resolution": 0.1, "latency_ms": 30, "pixel_scale_mrad": 0.109, "viewport_width": 640, "viewport_height": 480, "god_width": 640, "god_height": 480},
        beacons={"beacon_count": 2, "target_index": 0, "beacons": [
            {"profile": "spiral", "speed": 60, "brightness": 255, "radius": 5, "hitbox_radius": 14, "center_radius": 2, "position_seed": 40},
            {"profile": "sinusoidal", "speed": 45, "brightness": 240, "radius": 5, "hitbox_radius": 14, "center_radius": 2, "position_seed": 41},
        ]},
        disturbances={"Turbulence": 2, "Vibration": 2, "Camera Motion": 2, "Noise": 2},
        controller={"controller_type": "PID", "kp": 0.18, "ki": 0.02, "kd": 0.04, "dead_zone": 2, "output_clamp": 80, "update_rate_hz": 30},
        overlay={"crosshair_style": "all", "error_units": "px+mrad"},
        detector={"brightness_threshold": 195},
        tracker={"smoothing": 0.4, "miss_limit": 5},
        target={"profile": "spiral", "speed": 60},
    ),

    # 6 — Spec Disturbance · Image Noise (S&P ~10% + Gaussian + Poisson selectable, Sr.21.1) + Low-Light (Sr.21.4)
    Preset(
        name="6 — Spec Noise · 10% S&P + Gaussian/Poisson + Low-Light",
        description="Sr.21.1 Noise 7 → S&P ~10% + Gaussian + Poisson + PRNU + hot pixels (sensor model), Sr.21.2 σ up to 20px capable, Sr.21.4 Low-light/Haze 45% + vignetting 25% + dark bg 8→18 (contrast↓), star 100 bright 1.3, 640×480 @4°×3°, 30Hz, 1 beacon 10×10 dim 200 (6×6 min Sr.10 edge) tests threshold.",
        goal="Sr.17 err ≤10px despite noise; tune thresh 190→210: expect detection drop if >205. Demonstrates noise selectable (one/more) per Sr.21.1.",
        category="noise",
        environment={"world_width": 2000, "world_height": 2000, "seed": 505, "haze_pct": 45, "star_count": 100, "vignetting_pct": 25, "bg_top": 8, "bg_bottom": 18, "star_brightness": 1.3, "dynamic": False},
        camera={"fov_width": 640, "fov_height": 480, "max_slew_rate": 800, "resolution": 0.1, "latency_ms": 30, "pixel_scale_mrad": 0.109, "viewport_width": 640, "viewport_height": 480, "god_width": 640, "god_height": 480},
        beacons={"beacon_count": 1, "target_index": 0, "beacons": [{"profile": "linear", "speed": 45, "brightness": 200, "radius": 3, "hitbox_radius": 14, "center_radius": 2, "position_seed": 505}]},
        disturbances={"Turbulence": 3, "Vibration": 2, "Camera Motion": 2, "Noise": 7},
        controller={"controller_type": "PI", "kp": 0.14, "ki": 0.03, "dead_zone": 4, "output_clamp": 80, "update_rate_hz": 30},
        overlay={"crosshair_style": "cross", "error_units": "px"},
        detector={"brightness_threshold": 200, "min_area": 2},
        tracker={"smoothing": 0.4, "miss_limit": 5},
        target={"profile": "linear", "speed": 45},
    ),

    # 7 — Spec Jitter · Max ±20px/frame Jitter (Vib 9, Sr.21.3) + Platform ±20px/frame Linear (CamMotion 8, Sr.21.5)
    Preset(
        name="7 — Spec Jitter · ±20px Jitter + Platform ±20px (Linear)",
        description="Sr.21.3 Vibration 9 → harmonic 7-150Hz + OU ≈±20px/frame jitter, Sr.21.5 Camera Motion 8 → OU thermal drift ±20px/frame Linear (default) — optional Circular/Random/Spiral/Fig-8 available, 2000×2000, 640×480 @4°×3°, 60ms latency, PID for damping.",
        goal="Sr.17-18 jitter + drift: err ~6-10px, retention >85%, reacq <0.5s. Validates max jitter & platform motion specs.",
        category="jitter",
        environment={"world_width": 2000, "world_height": 2000, "seed": 606, "haze_pct": 20, "star_count": 60, "vignetting_pct": 10, "bg_top": 12, "bg_bottom": 22, "star_brightness": 1.0, "dynamic": False},
        camera={"fov_width": 640, "fov_height": 480, "max_slew_rate": 1200, "resolution": 0.1, "latency_ms": 40, "pixel_scale_mrad": 0.109, "viewport_width": 640, "viewport_height": 480, "god_width": 640, "god_height": 480},
        beacons={"beacon_count": 1, "target_index": 0, "beacons": [{"profile": "linear", "speed": 60, "brightness": 255, "radius": 5, "hitbox_radius": 14, "center_radius": 2, "position_seed": 606}]},
        disturbances={"Turbulence": 2, "Vibration": 9, "Camera Motion": 8, "Noise": 3},
        controller={"controller_type": "PID", "kp": 0.16, "ki": 0.02, "kd": 0.05, "dead_zone": 3, "output_clamp": 90, "update_rate_hz": 30},
        overlay={"crosshair_style": "cross+bracket", "error_units": "px"},
        detector={"brightness_threshold": 200},
        tracker={"smoothing": 0.35, "miss_limit": 5},
        target={"profile": "linear", "speed": 60},
    ),

    # 8 — Spec Acquisition · Waypoint exit/enter — validates Sr.16-19 timing precisely (SEARCH→ACQ→TRACK→LOST→SEARCH)
    Preset(
        name="8 — Spec Acquisition · Waypoint Exit/Enter (≤2s / ≤1s)",
        description="Sr.11 waypoint motion, 2500×2000 >min (user-defined size), 640×480 @4°×3°, 30Hz, beacon waypoint 65px/s exits/enters FOV — forces SEARCHING(—)→ACQUIRED(3 hits)→TRACKING→LOST(5 misses)→SEARCHING(10 misses). Measures Sr.16 acq ≤2s & Sr.19 reacq ≤1s. Clear→Haze 25%.",
        goal="Sr.16 acq ≤2s, Sr.19 reacq ≤1s on re-entry; error ≤10px while visible. Demonstrates state machine + perf log.",
        category="acquisition",
        environment={"world_width": 2500, "world_height": 2000, "seed": 707, "haze_pct": 25, "star_count": 60, "vignetting_pct": 10, "bg_top": 12, "bg_bottom": 22, "star_brightness": 1.0, "dynamic": False},
        camera={"fov_width": 640, "fov_height": 480, "max_slew_rate": 800, "resolution": 0.1, "latency_ms": 30, "pixel_scale_mrad": 0.109, "viewport_width": 640, "viewport_height": 480, "god_width": 640, "god_height": 480},
        beacons={"beacon_count": 1, "target_index": 0, "beacons": [{"profile": "waypoint", "speed": 65, "brightness": 255, "radius": 5, "hitbox_radius": 14, "center_radius": 2, "position_seed": 707}]},
        disturbances={"Turbulence": 4, "Vibration": 2, "Camera Motion": 2, "Noise": 4},
        controller={"controller_type": "P", "kp": 0.15, "dead_zone": 2, "output_clamp": 80, "update_rate_hz": 30},
        overlay={"crosshair_style": "cross+bracket", "pulse_enabled": True, "error_units": "px+mrad"},
        detector={"brightness_threshold": 200},
        tracker={"smoothing": 0.4, "miss_limit": 5, "acquire_hits": 3},
        target={"profile": "waypoint", "speed": 65},
    ),

    # 9 — Full Spec Stress · Haze/Fog/Rain/Low-light + All Noise 9 (worst-case Sr.21 combined) — Benchmark
    Preset(
        name="9 — Full Spec Stress · Haze/Fog + All Disturbance 8-9",
        description="Sr.21.4 Haze 55% Fog/Rain + Low-light (bg 8→30, vignetting 30%, star 150×1.5, dynamic True), Sr.21 all max: Turb 8 (warp+scintillation ≈atmospheric), Vib 8 (±20 jitter), CamMotion 8 (±20 platform), Noise 9 (S&P+Gaussian+Poisson). 2000×2000 640×480 @4°×3° 30Hz. 2 beacons 10×10 random_walk 70 + zigzag 65 (spec multiple).",
        goal="Benchmark Worst-case: Sr.16 acq may stretch 1-2s, Sr.17 err pushes ~10-12px, Sr.18 loss 10-30%, Sr.19 reacq 0.8-1.5s. Find breaking point; PID vs P.",
        category="stress",
        environment={"world_width": 2000, "world_height": 2000, "seed": 808, "haze_pct": 55, "star_count": 150, "vignetting_pct": 30, "bg_top": 8, "bg_bottom": 30, "star_brightness": 1.5, "dynamic": True, "dynamic_speed": 1.2},
        camera={"fov_width": 640, "fov_height": 480, "max_slew_rate": 900, "resolution": 0.2, "latency_ms": 40, "pixel_scale_mrad": 0.109, "viewport_width": 640, "viewport_height": 480, "god_width": 640, "god_height": 480},
        beacons={"beacon_count": 2, "target_index": 0, "beacons": [
            {"profile": "random_walk", "speed": 70, "brightness": 210, "radius": 5, "hitbox_radius": 14, "center_radius": 2, "position_seed": 80},
            {"profile": "zigzag", "speed": 65, "brightness": 220, "radius": 5, "hitbox_radius": 14, "center_radius": 2, "position_seed": 81},
        ]},
        disturbances={"Turbulence": 8, "Vibration": 8, "Camera Motion": 8, "Noise": 9},
        controller={"controller_type": "PID", "kp": 0.18, "ki": 0.03, "kd": 0.05, "dead_zone": 3, "output_clamp": 80, "update_rate_hz": 30},
        overlay={"crosshair_style": "all", "error_units": "mrad"},
        detector={"brightness_threshold": 200},
        tracker={"smoothing": 0.35, "miss_limit": 5},
        target={"profile": "random_walk", "speed": 70},
    ),
]

PRESET_CATEGORIES: list[str] = sorted(set(p.category for p in PRESETS))

def get_preset(name: str) -> Preset | None:
    for p in PRESETS:
        if p.name == name or p.name.lower() == name.lower():
            return p
    return None

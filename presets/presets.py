# presets/presets.py - Test preset definitions (Qt-free).
#
# Each preset fully specifies ALL modules: environment, local terminal,
# remote scenario, disturbances (+ seed, steps, pass criteria). Applying a
# preset replaces the whole configuration so cases are reproducible.
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class TestPreset:
    """One auto-configuring test case."""

    preset_id: str
    name: str
    category: str  # Nominal | Acquisition | Identification | Tracking | Disturbance | Negative
    description: str
    seed: int = 42
    steps: int = 200
    expect: dict[str, Any] = field(default_factory=dict)
    # build() returns (env_cfg, lt_cfg, scenario_cfg, dist_cfg)
    builder: Any = None


def _base_configs():
    from disturbance.core.config import DisturbanceConfig
    from environment.config import EnvironmentConfig
    from local_terminal import LocalTerminalConfig

    env = EnvironmentConfig()
    env.seed = 42
    lt = LocalTerminalConfig()
    lt.ptz.home_pan = 1000.0
    lt.ptz.home_tilt = 1000.0
    dist = DisturbanceConfig()
    return env, lt, dist


def _make_beacon(preset_id: str, wavelength_nm=1550.0, mod_type="AM",
                 mod_freq_khz=10.0, div_mrad=1.0, power_w=1.0):
    from remote_terminal.config import (
        BeaconConfig,
        CommunicationConfig,
        IdentityConfig,
        RemoteTerminalConfig,
        TargetSignatureConfig,
    )

    return RemoteTerminalConfig(
        identity=IdentityConfig(id=preset_id, name=f"Remote {preset_id}"),
        beacon=BeaconConfig(
            wavelength_nm=wavelength_nm,
            mod_type=mod_type,
            mod_freq_khz=mod_freq_khz,
            div_h_mrad=div_mrad,
            div_v_mrad=div_mrad,
            power_w=power_w,
        ),
        communication=CommunicationConfig(terminal_id=preset_id),
        target_signature=TargetSignatureConfig(),
    )


def _scenario(anchor_x, anchor_y, terminals, profile="Stationary",
              speed=0.0, formation_shape="Single", radius=60.0, spacing=40.0,
              accel=2.0):
    from remote_terminal.config import (
        FormationConfig,
        MotionConfig,
        RemoteTerminalScenarioConfig,
    )

    cfg = RemoteTerminalScenarioConfig(
        terminal_count=len(terminals),
        formation=FormationConfig(shape=formation_shape, radius_m=radius,
                                  spacing_m=spacing),
        motion=MotionConfig(profile=profile, speed_mps=speed,
                            acceleration_mps2=accel,
                            start_x=anchor_x, start_y=anchor_y),
        terminals=terminals,
    )
    return cfg.validate()


# ---------------------------------------------------------------- builders ---
def _b_nominal_lock():
    env, lt, dist = _base_configs()
    lt.acquisition.mode = "AUTO"
    lt.tracking.mode = "AUTO"
    rt = _make_beacon("RT-001")
    scen = _scenario(1000.0, 1000.0, [rt])
    return env, lt, scen, dist


def _b_search_acquire_far():
    env, lt, dist = _base_configs()
    lt.acquisition.mode = "AUTO"
    lt.acquisition.search_pattern = "RANDOM"
    lt.tracking.mode = "AUTO"
    rt = _make_beacon("RT-FAR")
    scen = _scenario(1600.0, 1600.0, [rt])
    return env, lt, scen, dist


def _b_spiral_scan():
    env, lt, dist = _base_configs()
    lt.acquisition.mode = "AUTO"
    lt.acquisition.search_pattern = "SPIRAL"
    lt.tracking.mode = "AUTO"
    rt = _make_beacon("RT-SPIRAL")
    scen = _scenario(1400.0, 1400.0, [rt])
    return env, lt, scen, dist


def _b_raster_scan():
    env, lt, dist = _base_configs()
    lt.acquisition.mode = "AUTO"
    lt.acquisition.search_pattern = "RASTER"
    lt.tracking.mode = "AUTO"
    rt = _make_beacon("RT-RASTER")
    scen = _scenario(1450.0, 1300.0, [rt])
    return env, lt, scen, dist


def _b_multi_target():
    env, lt, dist = _base_configs()
    lt.acquisition.mode = "AUTO"
    lt.tracking.mode = "AUTO"
    lt.detection.wavelength = 1550.0
    lt.detection.modulation_type = "AM"
    lt.detection.modulation_frequency = 10.0
    lt.detection.expected_spot_size = 3.0
    lt.detection.expected_spot_tolerance = 1.5
    decoy_wl = _make_beacon("RT-DECOY-WL", wavelength_nm=850.0, div_mrad=3.0)
    valid = _make_beacon("RT-MATCH-VALID", div_mrad=3.0)
    decoy_mod = _make_beacon("RT-DECOY-MOD", mod_type="PM",
                             mod_freq_khz=50.0, div_mrad=3.0)
    scen = _scenario(1000.0, 1000.0, [decoy_wl, valid, decoy_mod],
                     formation_shape="Circle", radius=60.0)
    return env, lt, scen, dist


def _b_decoy_only():
    env, lt, dist = _base_configs()
    lt.acquisition.mode = "AUTO"
    lt.tracking.mode = "AUTO"
    rt = _make_beacon("RT-DECOY", wavelength_nm=850.0)
    scen = _scenario(1000.0, 1000.0, [rt])
    return env, lt, scen, dist


def _b_beacon_dark():
    env, lt, dist = _base_configs()
    lt.acquisition.mode = "AUTO"
    lt.tracking.mode = "AUTO"
    rt = _make_beacon("RT-DARK")
    rt.beacon.enabled = False
    scen = _scenario(1000.0, 1000.0, [rt])
    return env, lt, scen, dist


def _b_reacquire_blink():
    env, lt, dist = _base_configs()
    lt.acquisition.mode = "AUTO"
    lt.tracking.mode = "AUTO"
    lt.tracking.lost_target_behavior = "RESUME_SEARCH"
    rt = _make_beacon("RT-BLINK")
    scen = _scenario(1000.0, 1000.0, [rt])
    return env, lt, scen, dist


def _b_fast_mover():
    env, lt, dist = _base_configs()
    lt.acquisition.mode = "AUTO"
    lt.tracking.mode = "AUTO"
    rt = _make_beacon("RT-FAST")
    scen = _scenario(1000.0, 1000.0, [rt], profile="Sinusoidal", speed=40.0)
    return env, lt, scen, dist


def _b_edge_target():
    env, lt, dist = _base_configs()
    lt.acquisition.mode = "AUTO"
    lt.tracking.mode = "AUTO"
    rt = _make_beacon("RT-EDGE")
    scen = _scenario(1600.0, 1500.0, [rt])
    return env, lt, scen, dist


def _b_noisy_low_snr():
    env, lt, dist = _base_configs()
    lt.acquisition.mode = "AUTO"
    lt.tracking.mode = "AUTO"
    dist.turbulence = 3
    dist.noise = 3
    dist.enable_gaussian = True
    dist.gaussian_sigma = 6.0
    dist.camera_jitter = 3.0
    rt = _make_beacon("RT-NOISY")
    scen = _scenario(1000.0, 1000.0, [rt])
    return env, lt, scen, dist


def _b_heavy_weather():
    env, lt, dist = _base_configs()
    env.haze_pct = 55
    lt.acquisition.mode = "AUTO"
    lt.tracking.mode = "AUTO"
    dist.atmospheric_preset = "Fog"
    dist.turbulence = 4
    dist.vibration = 4
    dist.camera_jitter = 5.0
    dist.platform_profile = "Random"
    dist.platform_speed = 5.0
    rt = _make_beacon("RT-FOG")
    scen = _scenario(1000.0, 1000.0, [rt])
    return env, lt, scen, dist


def _b_clutter_stars():
    env, lt, dist = _base_configs()
    env.star_count = 2500
    env.star_brightness = 1.6
    env.haze_pct = 20
    lt.acquisition.mode = "AUTO"
    lt.tracking.mode = "AUTO"
    rt = _make_beacon("RT-STAR")
    scen = _scenario(1000.0, 1000.0, [rt])
    return env, lt, scen, dist


def _b_hyper_mover():
    env, lt, dist = _base_configs()
    lt.acquisition.mode = "AUTO"
    lt.acquisition.search_pattern = "RANDOM"
    lt.tracking.mode = "AUTO"
    rt = _make_beacon("RT-HYPER")
    scen = _scenario(1000.0, 1000.0, [rt], profile="Linear",
                     speed=150.0, accel=60.0)
    return env, lt, scen, dist


def _b_random_walk():
    env, lt, dist = _base_configs()
    lt.acquisition.mode = "AUTO"
    lt.acquisition.search_pattern = "RANDOM"
    lt.tracking.mode = "AUTO"
    rt = _make_beacon("RT-ERRATIC")
    scen = _scenario(1000.0, 1000.0, [rt], profile="Random Walk",
                     speed=60.0, accel=60.0)
    return env, lt, scen, dist


def _b_random_walk_fast():
    env, lt, dist = _base_configs()
    lt.acquisition.mode = "AUTO"
    lt.acquisition.search_pattern = "RANDOM"
    lt.tracking.mode = "AUTO"
    rt = _make_beacon("RT-WILD")
    scen = _scenario(1000.0, 1000.0, [rt], profile="Random Walk",
                     speed=140.0, accel=80.0)
    return env, lt, scen, dist


def _b_figure8_mover():
    env, lt, dist = _base_configs()
    lt.acquisition.mode = "AUTO"
    lt.acquisition.search_pattern = "RANDOM"
    lt.tracking.mode = "AUTO"
    rt = _make_beacon("RT-FIG8")
    scen = _scenario(1000.0, 1000.0, [rt], profile="Figure-8",
                     speed=80.0, accel=60.0)
    return env, lt, scen, dist


def _b_figure8_scan():
    env, lt, dist = _base_configs()
    lt.acquisition.mode = "AUTO"
    lt.acquisition.search_pattern = "FIGURE_8"
    lt.tracking.mode = "AUTO"
    rt = _make_beacon("RT-FSCAN")
    scen = _scenario(1500.0, 1350.0, [rt])
    return env, lt, scen, dist


def _b_chaos_duel():
    env, lt, dist = _base_configs()
    lt.acquisition.mode = "AUTO"
    lt.acquisition.search_pattern = "FIGURE_8"
    lt.tracking.mode = "AUTO"
    rt = _make_beacon("RT-CHAOS")
    scen = _scenario(1000.0, 1000.0, [rt], profile="Random Walk",
                     speed=70.0, accel=60.0)
    return env, lt, scen, dist


def _b_agile_swarm():
    env, lt, dist = _base_configs()
    lt.acquisition.mode = "AUTO"
    lt.tracking.mode = "AUTO"
    lt.detection.wavelength = 1550.0
    lt.detection.modulation_type = "AM"
    lt.detection.modulation_frequency = 10.0
    lt.detection.expected_spot_size = 3.0
    lt.detection.expected_spot_tolerance = 1.5
    decoy_wl = _make_beacon("RT-SW-DECOY-WL", wavelength_nm=850.0, div_mrad=3.0)
    valid = _make_beacon("RT-SW-VALID", div_mrad=3.0)
    decoy_mod = _make_beacon("RT-SW-DECOY-MOD", mod_type="PM",
                             mod_freq_khz=50.0, div_mrad=3.0)
    scen = _scenario(1000.0, 1000.0, [decoy_wl, valid, decoy_mod],
                     profile="Random Walk", speed=50.0, accel=50.0,
                     formation_shape="Circle", radius=60.0)
    return env, lt, scen, dist


PRESETS: list[TestPreset] = [
    TestPreset("nominal_lock", "Nominal Lock", "Nominal",
               "Centered static target, clean channel. Must confirm + track + connect.",
               seed=42, steps=150,
               expect={"kind": "lock", "active": "RT-001"},
               builder=_b_nominal_lock),
    TestPreset("search_acquire_far", "Search & Acquire (far)", "Acquisition",
               "Stationary target outside initial FOV. RANDOM scan must find and track it.",
               seed=7, steps=1200,
               expect={"kind": "acquire"},
               builder=_b_search_acquire_far),
    TestPreset("spiral_scan", "Spiral Scan", "Acquisition",
               "Off-center target with SPIRAL pattern. Must acquire and track.",
               seed=11, steps=1500,
               expect={"kind": "acquire"},
               builder=_b_spiral_scan),
    TestPreset("raster_scan", "Raster Scan", "Acquisition",
               "Off-center target with RASTER pattern. Must acquire and track.",
               seed=13, steps=1500,
               expect={"kind": "acquire"},
               builder=_b_raster_scan),
    TestPreset("multi_target", "Multi-Target Discrimination", "Identification",
               "Valid target hidden among wavelength + modulation decoys. Must lock RT-MATCH-VALID.",
               seed=21, steps=150,
               expect={"kind": "lock", "active": "RT-MATCH-VALID"},
               builder=_b_multi_target),
    TestPreset("decoy_only", "Decoy Only (negative)", "Identification",
               "Only a wavelength-mismatched decoy is visible. Must NEVER confirm/track.",
               seed=22, steps=150,
               expect={"kind": "no_lock"},
               builder=_b_decoy_only),
    TestPreset("beacon_dark", "Beacon Dark (negative)", "Identification",
               "Target present but beacon effectively off. Must NEVER confirm/track.",
               seed=23, steps=150,
               expect={"kind": "no_lock"},
               builder=_b_beacon_dark),
    TestPreset("reacquire_blink", "Reacquire After Blink", "Tracking",
               "Beacon cut mid-run then restored. Must coast (REACQUIRING) then relock.",
               seed=31, steps=500,
               expect={"kind": "relock"},
               builder=_b_reacquire_blink),
    TestPreset("fast_mover", "Fast Sinusoidal Mover", "Tracking",
               "Agile target on sinusoidal path. Tracker must hold lock.",
               seed=32, steps=600,
               expect={"kind": "acquire"},
               builder=_b_fast_mover),
    TestPreset("edge_target", "Edge-of-Range Target", "Tracking",
               "Static target near PTZ range limit. Must acquire and hold.",
               seed=33, steps=900,
               expect={"kind": "acquire"},
               builder=_b_edge_target),
    TestPreset("noisy_low_snr", "Noisy Low-SNR Channel", "Disturbance",
               "Turbulence + sensor noise + jitter on a centered target. Must hold lock.",
               seed=41, steps=300,
               expect={"kind": "lock"},
               builder=_b_noisy_low_snr),
    TestPreset("heavy_weather", "Heavy Weather + Platform", "Disturbance",
               "Fog + haze + vibration + jitter + platform drift. Must reach at least DISCRIMINATING.",
               seed=42, steps=600,
               expect={"kind": "degraded"},
               builder=_b_heavy_weather),
    TestPreset("clutter_stars", "Star Clutter Field", "Disturbance",
               "Dense bright starfield (hard negatives). Must still lock the true beacon.",
               seed=43, steps=300,
               expect={"kind": "lock"},
               builder=_b_clutter_stars),
    TestPreset("hyper_mover", "Hypersonic Pass", "Challenging",
               "Target screaming across the world at 150 px/s on a bouncing line. Must catch and track it.",
               seed=51, steps=1200,
               expect={"kind": "acquire"},
               builder=_b_hyper_mover),
    TestPreset("random_walk", "Erratic Random Walker", "Challenging",
               "Target jinking unpredictably (OU random walk, 60 px/s envelope). Must acquire and hold.",
               seed=52, steps=1200,
               expect={"kind": "acquire"},
               builder=_b_random_walk),
    TestPreset("random_walk_fast", "Wild Random Walker", "Challenging",
               "Violent random walk at 140 px/s envelope — hardest case. Too wild to hold; must at least catch it mid-run.",
               seed=53, steps=1500,
               expect={"kind": "ever_locked"},
               builder=_b_random_walk_fast),
    TestPreset("agile_swarm", "Agile Decoy Swarm", "Challenging",
               "Valid target plus two decoys, whole formation jinking on a random walk. Must lock RT-SW-VALID.",
               seed=54, steps=1200,
               expect={"kind": "lock", "active": "RT-SW-VALID"},
               builder=_b_agile_swarm),
    TestPreset("figure8_mover", "Figure-8 Mover", "Challenging",
               "Target flying a Lissajous figure-8 through the crossover. Must acquire and hold through reversals.",
               seed=55, steps=1200,
               expect={"kind": "acquire"},
               builder=_b_figure8_mover),
    TestPreset("figure8_scan", "Figure-8 Scan", "Acquisition",
               "Static off-center target found with the FIGURE_8 sweep. Must acquire and track.",
               seed=56, steps=1500,
               expect={"kind": "acquire"},
               builder=_b_figure8_scan),
    TestPreset("chaos_duel", "Chaos Duel", "Challenging",
               "Random-walk target hunted with a figure-8 sweep — random versus random. Must acquire and hold.",
               seed=57, steps=1500,
               expect={"kind": "acquire"},
               builder=_b_chaos_duel),
]

_PRESET_MAP = {p.preset_id: p for p in PRESETS}
PRESET_IDS = [p.preset_id for p in PRESETS]


def list_presets() -> list[dict]:
    """Combo-box friendly summary."""
    return [{"id": p.preset_id, "name": p.name, "category": p.category,
             "description": p.description} for p in PRESETS]


def get_preset(preset_id: str) -> TestPreset:
    try:
        return _PRESET_MAP[str(preset_id)]
    except KeyError:
        valid = ", ".join(PRESET_IDS)
        raise KeyError(f"unknown preset '{preset_id}'. Valid: {valid}") from None


def build_configs(preset_id: str):
    """Build fresh validated configs for a preset. Returns (env, lt, scen, dist, preset)."""
    preset = get_preset(preset_id)
    env, lt, scen, dist = preset.builder()
    env.seed = preset.seed
    sw, sh = int(env.world_width), int(env.world_height)
    env = env.validate()
    lt = lt.validate((sw, sh))
    scen = scen.validate()
    dist = dist.validate()
    return env, lt, scen, dist, preset

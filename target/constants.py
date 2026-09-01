# target/constants.py - Single source of truth for Beacon/Target limits & defaults

BEACON_LIMITS: dict[str, tuple[float, float]] = {
    "brightness": (0, 255),
    "radius": (1, 15),
    "hitbox_radius": (3, 80),
    "center_radius": (1, 10),
    "speed": (5, 300),
    "position_seed": (0, 999999),
    "x": (0, 5000),
    "y": (0, 5000),
    "heading": (0, 360),
    "size_w": (5, 20),
    "size_h": (2, 20),
}

BEACON_DEFAULTS: dict = {
    "enabled": True,
    "profile": "curved",
    "position_seed": 42,
    "x": 400.0,
    "y": 300.0,
    "speed": 60.0,
    "brightness": 255,
    "radius": 5,
    "hitbox_radius": 14,
    "center_radius": 2,
    "heading": None,
    "beacon_id": 0,
    "shape": "square",
    "size_w": 10,
    "size_h": 10,
    "blinking": False,
}

MULTI_BEACON_LIMITS: dict[str, tuple[int, int]] = {
    "beacon_count": (1, 5),
    "target_index": (0, 4),
}

MULTI_BEACON_DEFAULTS: dict = {
    "beacon_count": 1,
    "target_index": 0,
    "shape": "square",
    "size_w": 10,
    "size_h": 10,
    "speed": 60.0,
    "profile": "curved",
    "x": 2500.0,
    "y": 2500.0,
    "blinking": False,
    "speed_random": False,
}

BEACON_SHAPES: list[str] = ["square", "circle", "random"]
MOTION_PROFILES_DISPLAY: list[str] = ["Straight Line", "Circular", "Figure 8", "Spiral", "Sin", "Zig-Zag", "Random"]
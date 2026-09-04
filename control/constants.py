# control/constants.py - Single source for controller limits & defaults (gains, rate, dead zone, clamp)

CONTROL_LIMITS: dict[str, tuple[float, float]] = {
    "kp": (0.0, 1.0),
    "ki": (0.0, 0.5),
    "kd": (0.0, 0.5),
    "update_rate_hz": (20.0, 120.0),
    # Dead zone — px, below this error no move (anti-jitter)
    "dead_zone": (0.0, 20.0),
    # Output clamp — px per tick, max correction magnitude (should respect camera slew)
    "output_clamp": (1.0, 500.0),
}

CONTROL_DEFAULTS: dict = {
    "controller_type": "P",   # P | PI | PID
    "kp": 0.32,               # increased 0.15→0.32 to reduce lag for fast beacon (Sr.16)
    "ki": 0.02,
    "kd": 0.03,
    "update_rate_hz": 60.0,   # 60Hz reduces throttle lag (interval 16ms) vs 30Hz
    "dead_zone": 0.8,         # 2.0→0.8 reduces steady lag while still anti-jitter
    "output_clamp": 120.0,    # 80→120 allows 40px/tick with 8°/s slew
}

CONTROLLER_TYPES: list[str] = ["P", "PI", "PID"]
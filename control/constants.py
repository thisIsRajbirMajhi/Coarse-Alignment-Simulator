# control/constants.py - Single source for controller limits & defaults (gains, rate, dead zone, clamp + AI extensions)

CONTROL_LIMITS: dict[str, tuple[float, float]] = {
    "kp": (0.0, 1.0),
    "ki": (0.0, 0.5),
    "kd": (0.0, 0.5),
    "update_rate_hz": (20.0, 120.0),
    # Dead zone — px, below this error no move (anti-jitter)
    "dead_zone": (0.0, 20.0),
    # Output clamp — px per tick, max correction magnitude (should respect camera slew)
    "output_clamp": (1.0, 500.0),
    # Feedforward & adaptive — for AI challenge and reduced lag
    "feedforward_gain": (0.0, 1.2),
    "adaptive_gain": (0.0, 0.5),
    "derivative_filter": (0.0, 0.99),
    "setpoint_weight": (0.0, 1.0),
    "smith_latency_ms": (0.0, 50.0),
}

CONTROL_DEFAULTS: dict = {
    "controller_type": "P",   # P | PI | PID
    "kp": 0.32,               # increased 0.15→0.32 to reduce lag for fast beacon (Sr.16)
    "ki": 0.02,
    "kd": 0.03,
    "update_rate_hz": 60.0,   # 60Hz reduces throttle lag (interval 16ms) vs 30Hz
    "dead_zone": 0.8,         # 2.0→0.8 reduces steady lag while still anti-jitter
    "output_clamp": 120.0,    # 80→120 allows 40px/tick with 8°/s slew
    "feedforward_gain": 0.0,  # 0=off, 0.35-0.65 for velocity feedforward (reduces 10→3px)
    "adaptive_gain": 0.0,     # 0=off, 0.15*|err|/20 adaptive multiplier
    "derivative_filter": 0.80,  # 0.80 = 0.2*raw+0.8*prev (was hardcoded)
    "setpoint_weight": 1.0,   # 1.0 = no weighting, 0.7 reduces kick on acquire
    "smith_latency_ms": 0.0,  # 0=off, 12 = Smith predictor for camera latency
}

CONTROLLER_TYPES: list[str] = ["P", "PI", "PID"]
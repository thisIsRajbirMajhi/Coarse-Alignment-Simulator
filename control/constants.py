"""
Module: control.constants
Purpose: Single source for controller limits & defaults (gains, rate, dead zone, clamp).
Public API: CONTROL_LIMITS, CONTROL_DEFAULTS, CONTROLLER_TYPES
Notes: Consumed by ControllerConfig and PIDController for consistent clamping.
"""

# ============================================================
# SECTION: Controller limits
# ============================================================

CONTROL_LIMITS: dict[str, tuple[float, float]] = {
    # Gains — per-axis, applied to px error → px correction
    "kp": (0.0, 1.0),          # Proportional
    "ki": (0.0, 0.5),          # Integral
    "kd": (0.0, 0.5),          # Derivative
    # Update rate — Hz, how often to compute (can differ from render FPS)
    "update_rate_hz": (5.0, 120.0),
    # Dead zone — px, below this error no move (anti-jitter)
    "dead_zone": (0.0, 20.0),
    # Output clamp — px per tick, max correction magnitude (should respect camera slew)
    "output_clamp": (1.0, 500.0),
}

CONTROL_DEFAULTS: dict = {
    "controller_type": "P",   # P | PI | PID
    "kp": 0.15,               # matches old gain=0.15
    "ki": 0.02,
    "kd": 0.03,
    "update_rate_hz": 30.0,   # matches TICK_MS 33 ms ≈ 30 Hz
    "dead_zone": 2.0,         # 2 px — avoids micro-jitter when centered
    "output_clamp": 80.0,     # px/tick — ~ slew 800 px/s * 0.1s, keeps within camera limit
}

CONTROLLER_TYPES: list[str] = ["P", "PI", "PID"]

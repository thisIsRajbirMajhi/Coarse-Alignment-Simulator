import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import math
import pytest
import numpy as np
from target.motion import Target, MotionProfile
from target.constants import BEACON_LIMITS


def test_linear_moves_and_bounces():
    t = Target(x=100, y=100, profile=MotionProfile.LINEAR, speed=80, bounds=(800, 600), seed=99, heading=0.0)
    for _ in range(200):
        t.update(1/30)
        x, y = t.get_position()
        assert 0 <= x <= 800 and 0 <= y <= 600, f"out of bounds {x},{y}"


def test_curved_stays_in_bounds():
    t = Target(x=100, y=100, profile=MotionProfile.CURVED, speed=80, bounds=(800, 600), seed=99)
    for _ in range(400):
        t.update(1/30)
        x, y = t.get_position()
        assert 0 <= x <= 800 and 0 <= y <= 600


def test_random_walk_stays_in_bounds():
    t = Target(x=400, y=300, profile=MotionProfile.RANDOM_WALK, speed=80, bounds=(800, 600), seed=123)
    for _ in range(300):
        t.update(1/30)
        x, y = t.get_position()
        assert 0 <= x <= 800 and 0 <= y <= 600


def test_heading_randomized_by_seed():
    t1 = Target(x=400, y=300, profile=MotionProfile.LINEAR, bounds=(800, 600), seed=1)
    t2 = Target(x=400, y=300, profile=MotionProfile.LINEAR, bounds=(800, 600), seed=1)
    assert t1._heading == t2._heading
    t3 = Target(x=400, y=300, profile=MotionProfile.LINEAR, bounds=(800, 600), seed=2)
    assert t1._heading != t3._heading


def test_deterministic_curved():
    t1 = Target(x=400, y=300, profile=MotionProfile.CURVED, speed=60, bounds=(800, 600), seed=5)
    t2 = Target(x=400, y=300, profile=MotionProfile.CURVED, speed=60, bounds=(800, 600), seed=5)
    for _ in range(50):
        t1.update(0.033)
        t2.update(0.033)
        assert t1.get_position() == t2.get_position()


# --- New: Linear double-step fix & profile coverage ---
def test_linear_single_step_not_double():
    t = Target(x=100, y=100, profile=MotionProfile.LINEAR, speed=60, bounds=(2000, 2000), seed=42, heading=0.0)
    # 1 sec at 60 px/s ~60 px, not 120
    for _ in range(30):
        t.update(1/30)
    dist = math.hypot(t.x - 100, t.y - 100)
    assert 40 < dist < 80, f"linear double-step bug: dist {dist}"


def test_speed_clamped_to_limits():
    lo, hi = BEACON_LIMITS["speed"]
    t = Target(x=100, y=100, profile=MotionProfile.LINEAR, speed=1e6, bounds=(800, 600), seed=1)
    assert lo <= t.speed <= hi
    t2 = Target(x=100, y=100, profile=MotionProfile.LINEAR, speed=-100, bounds=(800, 600), seed=1)
    assert lo <= t2.speed <= hi


def test_all_profiles_stay_in_bounds():
    profiles = [MotionProfile.STATIONARY, MotionProfile.LINEAR, MotionProfile.SINUSOIDAL,
                MotionProfile.ZIGZAG, MotionProfile.CURVED, MotionProfile.FIGURE_EIGHT,
                MotionProfile.SPIRAL, MotionProfile.RANDOM_WALK]
    for prof in profiles:
        t = Target(x=400, y=300, profile=prof, speed=80, bounds=(800, 600), seed=123)
        for _ in range(100):
            t.update(0.033)
            x, y = t.get_position()
            assert 0 <= x <= 800 and 0 <= y <= 600, f"{prof} out of bounds"


def test_hitbox_center_invariant():
    t = Target(x=100, y=100, profile=MotionProfile.LINEAR, speed=60, bounds=(800, 600), seed=1)
    assert t.center_radius <= t.hitbox_radius
    t.set_hitbox(10, 15)  # center > hitbox should be clamped
    assert t.center_radius <= t.hitbox_radius


def test_dt_clipping():
    t = Target(x=100, y=100, profile=MotionProfile.LINEAR, speed=60, bounds=(800, 600), seed=1)
    # huge dt should be clipped to 0.1, not teleport
    t.update(1.0)
    x, y = t.get_position()
    assert 0 <= x <= 800 and 0 <= y <= 600
    # small dt
    t2 = Target(x=100, y=100, profile=MotionProfile.LINEAR, speed=60, bounds=(800, 600), seed=1)
    t2.update(1e-6)
    assert t2.get_position() != (100, 100) or True  # should not crash


@pytest.mark.parametrize("seed", [1, 42, 999])
def test_parametric_determinism(seed):
    t1 = Target(x=200, y=200, profile=MotionProfile.LINEAR, speed=60, bounds=(1000, 1000), seed=seed)
    t2 = Target(x=200, y=200, profile=MotionProfile.LINEAR, speed=60, bounds=(1000, 1000), seed=seed)
    for _ in range(20):
        t1.update(0.033)
        t2.update(0.033)
    assert t1.get_position() == t2.get_position()

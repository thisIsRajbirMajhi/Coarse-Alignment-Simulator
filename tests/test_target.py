import sys
sys.path.insert(0, r"C:\Users\mrajb\OneDrive\Desktop\FSOC Simulator")

from target.motion import Target, MotionProfile

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

if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print(f"pass {name}")
    print("all target tests passed")
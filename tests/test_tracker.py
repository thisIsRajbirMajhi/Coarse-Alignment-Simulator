import sys
sys.path.insert(0, r"C:\Users\mrajb\OneDrive\Desktop\FSOC Simulator")

from tracking.tracker import Tracker, LockStatus

def test_acquisition_sequence():
    t = Tracker(smoothing=0.4, miss_limit=5)
    assert t.status == LockStatus.SEARCHING
    t.update((100, 100))
    assert t.status == LockStatus.ACQUIRED
    t.update((101, 101))
    assert t.status == LockStatus.ACQUIRED
    t.update((102, 102))
    assert t.status == LockStatus.TRACKING

def test_loss_after_misses():
    t = Tracker(smoothing=0.4, miss_limit=3)
    for _ in range(3):
        t.update((50, 50))
    assert t.status == LockStatus.TRACKING
    for _ in range(3):
        t.update(None)
    assert t.status == LockStatus.LOST
    # reacquire
    t.update((60, 60))
    assert t.status == LockStatus.ACQUIRED

def test_searching_after_double_miss():
    t = Tracker(smoothing=0.4, miss_limit=2)
    for _ in range(3):
        t.update((10, 10))
    for _ in range(2):
        t.update(None)
    assert t.status == LockStatus.LOST
    assert t.estimated_position is not None
    for _ in range(4):
        t.update(None)
    assert t.status == LockStatus.SEARCHING
    assert t.estimated_position is None

def test_smoothing():
    t = Tracker(smoothing=0.8, miss_limit=5)
    t.update((0, 0))
    est = t.update((100, 0))
    # 0.8*0 + 0.2*100 = 20
    assert abs(est[0] - 20) < 1e-6

def test_no_position_without_detection():
    t = Tracker()
    assert t.update(None) is None
    assert t.status == LockStatus.SEARCHING

if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print(f"pass {name}")
    print("all tracker tests passed")
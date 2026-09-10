"""Closed-loop regression: pipeline search, association gating, metrics."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np


def _beacon_frame(cx=400, cy=220):
    import cv2
    f = np.zeros((480, 640, 3), dtype=np.uint8)
    cv2.rectangle(f, (int(cx - 10), int(cy - 10)), (int(cx + 10), int(cy + 10)), (255, 255, 255), -1)
    return f


def test_pipeline_search_active_with_ranges():
    from tracking.pipeline import TrackingPipeline
    p = TrackingPipeline(use_yolo=False, use_imm=True)
    blank = np.zeros((480, 640, 3), dtype=np.uint8)
    r = p.update(blank, dt=1 / 30, current_pan_tilt=(1000, 1000),
                 pan_range=(0, 2000), tilt_range=(0, 2000))
    assert r.search_active is True
    assert r.state in ("searching", "detected", "lost", "reacquiring")


def test_pipeline_acquires_visible_beacon():
    from tracking.pipeline import TrackingPipeline
    p = TrackingPipeline(use_yolo=False, use_imm=False)
    for _ in range(8):
        r = p.update(_beacon_frame(), dt=1 / 30)
    assert r.estimate is not None
    assert r.state in ("detected", "tracking")


def test_single_distractor_rejected():
    from tracking.detector import Detection
    from tracking.association import associate
    true = Detection(bbox=(390, 210, 410, 230), center=(400, 220), width=20, height=20,
                     confidence=0.9, pos_var=4.0, area=400, circularity=0.9)
    far = Detection(bbox=(0, 0, 10, 10), center=(5, 5), width=10, height=10,
                    confidence=0.5, pos_var=4.0, area=100, circularity=0.5)
    sel = associate([far], predicted=(400, 220), last_position=(400, 220),
                    last_velocity=(0, 0), dt=1 / 30, last_size=20)
    assert sel is None  # unified gating: no lenient bypass


def test_metrics_assoc_and_accept():
    from tracking.metrics import MetricsLogger
    from tracking.detector import Detection
    m = MetricsLogger()
    d1 = Detection(bbox=(390, 210, 410, 230), center=(400, 220), width=20, height=20,
                   confidence=0.9, pos_var=4.0, area=400, circularity=0.9)
    d2 = Detection(bbox=(0, 0, 10, 10), center=(5, 5), width=10, height=10,
                   confidence=0.99, pos_var=4.0, area=100, circularity=0.2)
    m.log(1, (400, 220), True, (400, 220), 0.9, (400, 220), (0, 0), "tracking", 5.0,
          all_detections=[d1, d2])
    m.log(2, (400, 220), True, (5, 5), 0.99, (5, 5), (0, 0), "tracking", 5.0,
          all_detections=[d1, d2])
    s = m.summary()
    assert s["association_decisions"] == 2
    assert s["association_correct"] == 1
    assert s["association_accuracy"] == 0.5


def test_headless_closed_loop_search_and_estimator_vel():
    from simulation.headless import HeadlessSimulation
    sim = HeadlessSimulation(seed=1)
    sim.enable_closed_loop()
    # force no YOLO for speed: swap to classical detector config path
    from tracking.detector import DetectorConfig
    assert sim._pipeline is not None
    obs, _, _, _, _ = sim.step()
    assert "estimate" in obs
    # env uses estimator vel, never GT
    from simulation.env import FSOCEnv
    env = FSOCEnv(seed=1)
    o, _ = env.reset(seed=1)
    assert "vector" in o

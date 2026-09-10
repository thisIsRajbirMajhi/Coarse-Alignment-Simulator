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


def test_designated_color_beats_brighter_distractor():
    from tracking.detector import Detection, expected_color_for_target
    from tracking.association import associate, AssociationConfig
    warm = expected_color_for_target(1)
    cool = expected_color_for_target(2)
    true = Detection(bbox=(90, 90, 110, 110), center=(100, 100), width=20, height=20,
                     confidence=0.6, pos_var=4.0, area=400, circularity=0.9, color_bgr=warm)
    false = Detection(bbox=(140, 140, 160, 160), center=(150, 150), width=20, height=20,
                      confidence=0.99, pos_var=4.0, area=400, circularity=0.9, color_bgr=cool)
    sel = associate([false, true], predicted=(102, 101), last_position=(100, 100),
                    last_velocity=(0, 0), dt=1 / 30, config=AssociationConfig(),
                    last_size=20, template_color=warm, prev_center=(100, 100))
    assert sel is not None and sel.center == (100, 100)


def test_switch_hysteresis_holds_incumbent():
    from tracking.detector import Detection, expected_color_for_target
    from tracking.association import associate, AssociationConfig
    warm = expected_color_for_target(1)
    inc = Detection(bbox=(90, 90, 110, 110), center=(100, 100), width=20, height=20,
                    confidence=0.6, pos_var=4.0, area=400, circularity=0.9, color_bgr=warm)
    chal = Detection(bbox=(95, 95, 115, 115), center=(105, 105), width=20, height=20,
                     confidence=0.99, pos_var=4.0, area=400, circularity=0.9, color_bgr=warm)
    sel = associate([chal, inc], predicted=(100, 100), last_position=(100, 100),
                    last_velocity=(0, 0), dt=1 / 30, config=AssociationConfig(),
                    last_size=20, template_color=warm, prev_center=(100, 100))
    assert sel is not None and sel.center == (100, 100)


def test_multitrack_designated_identity():
    from tracking.detector import Detection, expected_color_for_target
    from tracking.multitrack import MultiBeaconTracker
    warm = expected_color_for_target(1)
    mt = MultiBeaconTracker(max_tracks=5)
    mt.set_expected_color(warm)
    d1 = Detection(bbox=(90, 90, 110, 110), center=(100, 100), width=20, height=20,
                   confidence=0.8, pos_var=4.0, area=400, circularity=0.9, color_bgr=warm)
    d2 = Detection(bbox=(300, 300, 320, 320), center=(310, 310), width=20, height=20,
                   confidence=0.9, pos_var=4.0, area=400, circularity=0.9, color_bgr=expected_color_for_target(2))
    des, _ = mt.step([d1, d2], 1 / 30)
    assert des is not None
    first_id = mt.designated_internal_id
    # Move both; designated should persist, no switch.
    d1b = Detection(bbox=(95, 95, 115, 115), center=(105, 105), width=20, height=20,
                    confidence=0.8, pos_var=4.0, area=400, circularity=0.9, color_bgr=warm)
    d2b = Detection(bbox=(305, 305, 325, 325), center=(315, 315), width=20, height=20,
                    confidence=0.9, pos_var=4.0, area=400, circularity=0.9, color_bgr=expected_color_for_target(2))
    mt.step([d1b, d2b], 1 / 30)
    assert mt.designated_internal_id == first_id
    assert mt.id_switches == 0


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

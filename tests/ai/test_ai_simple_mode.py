"""tests/ai/test_ai_simple_mode.py - Stub tests for simple reliable AI (spec). Stays green without torch."""
import numpy as np

def test_confidence_fusion_weights():
    from src.local_terminal.ai.confidence import confidence_fusion, DEFAULT_WEIGHTS, ConfidenceFusion
    assert abs(sum(DEFAULT_WEIGHTS.values()) - 1.0) < 1e-9
    # spec C_total = 0.35*AI+0.10*shape+0.15*brightness+0.20*motion+0.20*prediction
    c = confidence_fusion(p_ai=1, shape_score=1, brightness_score=1, motion_score=1, prediction_score=1)
    assert abs(c - 1.0) < 1e-9
    c2 = confidence_fusion(p_ai=0.8, shape_score=0.6, brightness_score=0.7, motion_score=0.5, prediction_score=0.9)
    expected = 0.35*0.8 + 0.10*0.6 + 0.15*0.7 + 0.20*0.5 + 0.20*0.9
    assert abs(c2 - expected) < 1e-9
    # thresholds distinct
    cf = ConfidenceFusion(c_detect=0.55, c_identify=0.75, c_track=0.60, c_lost=0.40)
    assert cf.c_detect < cf.c_track < cf.c_identify
    assert cf.c_lost < cf.c_detect
    assert cf.decide(0.8) == "identify"
    assert cf.decide(0.62) == "track"
    assert cf.decide(0.56) == "detect"
    assert cf.decide(0.3) == "lost"

def test_verifier_32_and_64():
    from src.local_terminal.ai.verifier import TinyCNNVerifier
    v32 = TinyCNNVerifier(threshold=0.6, input_size=32)
    v64 = TinyCNNVerifier(threshold=0.6, input_size=64)
    patch32 = np.zeros((32,32), dtype=np.uint8)
    patch64 = np.zeros((64,64), dtype=np.uint8)
    # centered beacon should score > noise
    patch32[14:18,14:18] = 180
    patch64[30:34,30:34] = 180
    p32 = v32.score_patch(patch32)
    p64 = v64.score_patch(patch64)
    assert 0 <= p32 <= 1
    assert 0 <= p64 <= 1
    # optional distractor output
    d = v32.score_patch_with_distractor(patch32)
    assert "p_beacon" in d and "p_noise" in d

def test_autonomy_config_ai_fields():
    from src.local_terminal.models import AutonomyConfig
    cfg = AutonomyConfig().validate()
    assert hasattr(cfg, "ai_confidence_weights")
    assert hasattr(cfg, "c_detect")
    assert hasattr(cfg, "ai_simple_mode")
    assert cfg.c_detect == 0.55
    assert cfg.c_identify == 0.75
    assert cfg.c_track == 0.60
    assert cfg.c_lost == 0.40
    # simple mode defaults false for backward compat
    assert cfg.ai_simple_mode is False
    cfg.ai_simple_mode = True
    cfg.ai_enabled = True
    cfg.validate()
    assert cfg.ai_simple_mode is True
    # weights sum 1
    assert abs(sum(cfg.ai_confidence_weights.values()) - 1.0) < 1e-6

def test_detector_confidence_fusion_exposed():
    from src.local_terminal.detector import detect_spots, confidence_fusion, AISpotDetector
    # backward compat: detect_spots still works without config
    frame = np.zeros((480,640), dtype=np.uint8)
    # no crash on empty
    spots = detect_spots(frame)
    assert isinstance(spots, list)
    # AISpotDetector single threshold path
    det = AISpotDetector(threshold=0.6)
    # should fallback to classical when no model file
    out = det.detect(frame)
    assert isinstance(out, list)

def test_supervisor_simple_mode_disables_ranker():
    from src.local_terminal.models import AutonomyConfig
    from src.local_terminal.supervisor import SupervisorV2
    cfg = AutonomyConfig(ai_enabled=True, ai_simple_mode=True)
    cfg.validate()
    sup = SupervisorV2(autonomy=cfg)
    # verifier may be present (heuristic fallback creates it), but scorer/predictor/ranker must be None in simple mode
    assert sup.ai_scorer is None
    assert sup.ai_predictor is None
    assert sup.ai_ranker is None
    # state transitions still valid
    from src.local_terminal.supervisor import is_valid_transition
    assert is_valid_transition("SEARCH", "IDENTIFY")
    assert not is_valid_transition("SEARCH", "TRACK")

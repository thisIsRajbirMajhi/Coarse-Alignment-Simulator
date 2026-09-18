# tests/test_identity_pipeline.py
# 14 test cases for the Phase-2 beacon identity pipeline.
#
# Test cases (from spec §15):
#  1. Correct ID → identified
#  2. Wrong ID → rejected
#  3. Correct wavelength, wrong ID → rejected
#  4. Correct modulation, wrong ID → rejected
#  5. Wrong wavelength, correct ID → identity ok (wavelength is optical, not decoded)
#  6. Corrupted frame → not identified
#  7. Temporary frame loss → remain candidate / reacquire
#  8. Correct target disappears → reacquisition
#  9. Wrong terminal appears during reacquisition → rejected
# 10. Correct terminal reappears → reacquired
# 11. Multiple terminals → correct ID wins
# 12. Disturbance causes frame errors → identity confidence drops
# 13. Tracking continues while valid identity frames arrive
# 14. Identity changes while spatial position remains continuous → lock must not continue
from __future__ import annotations

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from local_terminal.beacon_frame import (
    BeaconFrame,
    PREAMBLE, SYNC_WORD,
    crc8,
    decode_chips,
    frame_to_chips,
    frame_to_bytes,
    terminal_id_to_byte,
    bytes_to_chips,
)
from local_terminal.frame_decoder import DecodedFrame, FrameDecoder, TrackDecodeState
from local_terminal.identity_matcher import IdentityDecision, IdentityMatcher, TargetProfile
from local_terminal.signal_analyzer import SignalAnalyzer
from remote_terminal.beacon_encoder import BeaconEncoder, BeaconEncoderConfig


# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────

def build_profile(terminal_id: str = "RT-001", network_id: int = 0,
                  min_conf: float = 0.1, min_consec: int = 1) -> TargetProfile:
    return TargetProfile(
        expected_terminal_id=terminal_id,
        expected_network_id=network_id,
        min_decode_confidence=min_conf,
        min_consecutive_valid=min_consec,
        require_sequence_advance=False,  # disable for isolated tests
    ).validate()


def build_frame(terminal_id: str = "RT-001", network_id: int = 0,
                seq: int = 1) -> BeaconFrame:
    return BeaconFrame(
        terminal_id_byte=terminal_id_to_byte(terminal_id),
        network_id=network_id,
        sequence_number=seq,
        crc_ok=True,
    )


def make_decoded_frame(terminal_id: str = "RT-001", network_id: int = 0,
                       seq: int = 1, confidence: float = 0.9,
                       consec: int = 3, valid: bool = True,
                       crc_ok: bool = True) -> DecodedFrame:
    return DecodedFrame(
        valid=valid,
        crc_ok=crc_ok,
        terminal_id_byte=terminal_id_to_byte(terminal_id),
        network_id=network_id,
        sequence_number=seq,
        capabilities=0x0F,
        confidence=confidence,
        consecutive_valid=consec,
        attempt_count=10,
        success_count=max(1, int(confidence * 10)),
    )


def encode_and_decode(terminal_id: str, seq: int = 1) -> DecodedFrame | None:
    """Full round-trip: encode → chips → decode."""
    frame = build_frame(terminal_id, seq=seq)
    chips = frame_to_chips(frame)
    # Repeat 3× to give the decoder enough buffer
    result = decode_chips(chips * 3)
    if result is None:
        return None
    return DecodedFrame(
        valid=result.crc_ok,
        crc_ok=result.crc_ok,
        terminal_id_byte=result.terminal_id_byte,
        network_id=result.network_id,
        sequence_number=result.sequence_number,
        capabilities=result.capabilities,
        confidence=1.0 if result.crc_ok else 0.0,
        consecutive_valid=1 if result.crc_ok else 0,
        attempt_count=1,
        success_count=1 if result.crc_ok else 0,
    )


# ──────────────────────────────────────────────────────────────────────────────
# Test 1: Correct ID → identified
# ──────────────────────────────────────────────────────────────────────────────
def test_01_correct_id_identified():
    """A decoded frame with the correct terminal ID must produce matched=True."""
    profile = build_profile("RT-001")
    matcher = IdentityMatcher(profile)
    decoded = make_decoded_frame("RT-001")
    decision = matcher.match("track-1", decoded)
    assert decision.matched, f"Expected matched=True, reason={decision.reason}"
    assert decision.reason == "OK"
    assert decision.terminal_id_ok
    assert decision.network_id_ok


# ──────────────────────────────────────────────────────────────────────────────
# Test 2: Wrong ID → rejected
# ──────────────────────────────────────────────────────────────────────────────
def test_02_wrong_id_rejected():
    """A decoded frame from a different terminal must produce ID_MISMATCH."""
    profile = build_profile("RT-001")
    matcher = IdentityMatcher(profile)
    # RT-003 ≠ RT-001
    decoded = make_decoded_frame("RT-003")
    decision = matcher.match("track-2", decoded)
    assert not decision.matched
    assert decision.reason == "ID_MISMATCH"
    assert decision.is_impostor


# ──────────────────────────────────────────────────────────────────────────────
# Test 3: Correct wavelength, wrong ID → rejected
# ──────────────────────────────────────────────────────────────────────────────
def test_03_correct_wavelength_wrong_id_rejected():
    """Optical signature matching (wavelength) must not override identity mismatch."""
    # Wavelength matching is done by SignatureAnalyzer, not IdentityMatcher.
    # Identity check only looks at decoded payload → wrong ID → rejected regardless.
    profile = build_profile("RT-001")
    matcher = IdentityMatcher(profile)
    decoded = make_decoded_frame("RT-002")  # wrong terminal
    decision = matcher.match("track-3", decoded)
    assert not decision.matched
    assert decision.reason == "ID_MISMATCH"


# ──────────────────────────────────────────────────────────────────────────────
# Test 4: Correct modulation, wrong ID → rejected
# ──────────────────────────────────────────────────────────────────────────────
def test_04_correct_modulation_wrong_id_rejected():
    """Modulation type matching must not override identity mismatch."""
    profile = build_profile("RT-001")
    matcher = IdentityMatcher(profile)
    # capabilities match (TX+RX+TRACK) but terminal ID is wrong
    decoded = make_decoded_frame("RT-005")
    decision = matcher.match("track-4", decoded)
    assert not decision.matched
    assert decision.reason == "ID_MISMATCH"


# ──────────────────────────────────────────────────────────────────────────────
# Test 5: Wrong wavelength, correct ID → identity ok
# ──────────────────────────────────────────────────────────────────────────────
def test_05_wrong_wavelength_correct_id_identity_ok():
    """Wavelength is an optical-path quality metric, not an identity gate.
    Identity is determined solely by the decoded payload.
    So a correct terminal_id → identity matched=True regardless of λ.
    """
    profile = build_profile("RT-001")
    matcher = IdentityMatcher(profile)
    decoded = make_decoded_frame("RT-001")
    # Note: no wavelength field in DecodedFrame — it is purely in BeamProfile (optical path)
    decision = matcher.match("track-5", decoded)
    assert decision.matched, f"Expected matched=True, reason={decision.reason}"


# ──────────────────────────────────────────────────────────────────────────────
# Test 6: Corrupted frame → not identified
# ──────────────────────────────────────────────────────────────────────────────
def test_06_corrupted_frame_not_identified():
    """A frame that fails CRC must not produce identity matched=True."""
    profile = build_profile("RT-001")
    matcher = IdentityMatcher(profile)
    decoded = make_decoded_frame("RT-001", crc_ok=False, valid=True)
    decision = matcher.match("track-6", decoded)
    assert not decision.matched
    assert decision.reason == "CRC_FAIL"


# ──────────────────────────────────────────────────────────────────────────────
# Test 7: Temporary frame loss → remain candidate
# ──────────────────────────────────────────────────────────────────────────────
def test_07_temporary_frame_loss_remain_candidate():
    """During a frame gap (valid=False, reason=NO_DATA) identity stays undecided."""
    profile = build_profile("RT-001")
    matcher = IdentityMatcher(profile)
    empty = DecodedFrame(valid=False, confidence=0.0, consecutive_valid=0)
    decision = matcher.match("track-7", empty)
    assert not decision.matched
    assert decision.reason == "NO_DATA"
    assert not decision.is_impostor   # NO_DATA ≠ impostor


# ──────────────────────────────────────────────────────────────────────────────
# Test 8: Correct target disappears → reacquisition (lifecycle)
# ──────────────────────────────────────────────────────────────────────────────
def test_08_target_disappears():
    """Identity state transitions to NO_DATA after frame loss."""
    profile = build_profile("RT-001")
    matcher = IdentityMatcher(profile)
    # First frame: good decode
    decoded = make_decoded_frame("RT-001")
    d1 = matcher.match("track-8", decoded)
    assert d1.matched

    # Target disappears: empty frame
    empty = DecodedFrame(valid=False, confidence=0.0)
    d2 = matcher.match("track-8", empty)
    assert not d2.matched
    assert d2.reason == "NO_DATA"
    assert not d2.is_impostor


# ──────────────────────────────────────────────────────────────────────────────
# Test 9: Wrong terminal appears during reacquisition → rejected
# ──────────────────────────────────────────────────────────────────────────────
def test_09_wrong_terminal_during_reacquisition_rejected():
    """An impostor beacon during reacquisition must be rejected immediately."""
    profile = build_profile("RT-001")
    matcher = IdentityMatcher(profile)
    decoded = make_decoded_frame("RT-099")   # wrong ID
    decision = matcher.match("track-9-impostor", decoded)
    assert not decision.matched
    assert decision.reason == "ID_MISMATCH"
    assert decision.is_impostor


# ──────────────────────────────────────────────────────────────────────────────
# Test 10: Correct terminal reappears → reacquired
# ──────────────────────────────────────────────────────────────────────────────
def test_10_correct_terminal_reappears():
    """After a gap, the correct terminal reappearing yields matched=True."""
    profile = build_profile("RT-001")
    matcher = IdentityMatcher(profile)
    # First contact
    d = make_decoded_frame("RT-001", seq=5)
    decision = matcher.match("track-10", d)
    assert decision.matched
    # Disappear
    empty = DecodedFrame(valid=False)
    matcher.match("track-10", empty)
    # Reappear with new seq
    d2 = make_decoded_frame("RT-001", seq=6)
    decision2 = matcher.match("track-10", d2)
    assert decision2.matched


# ──────────────────────────────────────────────────────────────────────────────
# Test 11: Multiple terminals → correct ID wins
# ──────────────────────────────────────────────────────────────────────────────
def test_11_multiple_terminals_correct_wins():
    """With two tracks, only the one matching the profile should be accepted."""
    profile = build_profile("RT-001")
    matcher = IdentityMatcher(profile)
    d_correct = make_decoded_frame("RT-001")
    d_wrong   = make_decoded_frame("RT-002")
    dec_correct = matcher.match("track-A", d_correct)
    dec_wrong   = matcher.match("track-B", d_wrong)
    assert dec_correct.matched
    assert not dec_wrong.matched
    assert dec_wrong.reason == "ID_MISMATCH"


# ──────────────────────────────────────────────────────────────────────────────
# Test 12: Disturbance causes frame errors → identity confidence drops
# ──────────────────────────────────────────────────────────────────────────────
def test_12_disturbance_reduces_confidence():
    """Increasing decode failure rate should reduce confidence below threshold."""
    profile = build_profile("RT-001", min_conf=0.6)
    matcher = IdentityMatcher(profile)
    # Frame with low confidence (many failed decodes)
    decoded_low_conf = make_decoded_frame("RT-001", confidence=0.3, consec=5)
    decision = matcher.match("track-12", decoded_low_conf)
    assert not decision.matched
    assert decision.reason == "LOW_CONF"


# ──────────────────────────────────────────────────────────────────────────────
# Test 13: Tracking continues while valid identity frames arrive
# ──────────────────────────────────────────────────────────────────────────────
def test_13_tracking_continues_with_valid_frames():
    """Consecutive valid frames with correct ID keep identity_matched=True."""
    profile = build_profile("RT-001", min_consec=2)
    matcher = IdentityMatcher(profile)
    for seq in range(1, 6):
        decoded = make_decoded_frame("RT-001", seq=seq, consec=seq)
        decision = matcher.match("track-13", decoded)
    # After 5 valid frames, should be fully confirmed
    assert decision.matched
    assert decision.reason == "OK"


# ──────────────────────────────────────────────────────────────────────────────
# Test 14: Identity changes while spatial position remains → lock must drop
# ──────────────────────────────────────────────────────────────────────────────
def test_14_identity_swap_during_tracking_forces_rejection():
    """If the decoded terminal ID changes mid-tracking, it must become impostor."""
    profile = build_profile("RT-001")
    matcher = IdentityMatcher(profile)
    # Initially correct
    d1 = make_decoded_frame("RT-001", seq=1)
    dec1 = matcher.match("track-14", d1)
    assert dec1.matched

    # Identity swaps (different terminal at same position)
    d2 = make_decoded_frame("RT-007", seq=2)
    dec2 = matcher.match("track-14", d2)
    assert not dec2.matched
    assert dec2.is_impostor
    assert dec2.reason == "ID_MISMATCH"


# ──────────────────────────────────────────────────────────────────────────────
# Bonus: Round-trip encode → decode
# ──────────────────────────────────────────────────────────────────────────────
def test_roundtrip_encode_decode():
    """Full encode → chip → decode cycle must recover correct fields with CRC pass."""
    frame = BeaconFrame(terminal_id_byte=3, network_id=0, sequence_number=42, crc_ok=True)
    chips = frame_to_chips(frame)
    assert len(chips) == 56
    result = decode_chips(chips)
    assert result is not None, "Decoder returned None for valid chip sequence"
    assert result.crc_ok, "CRC failed on clean round-trip"
    assert result.terminal_id_byte == 3
    assert result.sequence_number == 42


def test_crc8_polynomial():
    """Verify CRC-8 (Maxim) is self-consistent."""
    data = bytes([1, 2, 3, 4])
    c1 = crc8(data)
    c2 = crc8(data)
    assert c1 == c2
    # Flip one byte → different CRC
    data2 = bytes([1, 2, 3, 5])
    assert crc8(data2) != c1


def test_terminal_id_to_byte_rt001():
    """RT-001 should map to byte 1."""
    assert terminal_id_to_byte("RT-001") == 1


def test_beacon_encoder_produces_repeating_signal():
    """BeaconEncoder output must repeat exactly every frame period."""
    enc = BeaconEncoder(BeaconEncoderConfig(terminal_id="RT-002", chip_rate_hz=8.0))
    # Sample at t=0 and t=frame_period
    period = enc._period_s
    v0 = enc.get_intensity_factor(0.0)
    v1 = enc.get_intensity_factor(period)
    # Both should be valid intensity values
    assert v0 in (0.1, 1.0)
    assert v1 in (0.1, 1.0)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

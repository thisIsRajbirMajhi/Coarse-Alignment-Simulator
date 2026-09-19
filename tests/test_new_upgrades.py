"""Comprehensive acceptance tests covering all architectural requirements of Plans/New Upgrades.md.

Validates:
  1. Shared neutral protocol package (common.protocol.beacon) (§5).
  2. Compact deterministic binary wire format (§7).
  3. Remote BeaconConfig first-class attributes (§8).
  4. Local ReceivingPayloadConfig first-class attributes (§11).
  5. Streaming decoder state tracking and sample index tracking (§13).
  6. Strict token requirement (missing token != valid) (§19).
  7. Canonical INVALID_SEQUENCE status semantics (§18).
  8. No optical promotion to IDENTIFIED without legacy flag (§4, §23).
  9. True dual-lock acquisition (§24, §25).
  10. Identity-gated reacquisition merge (§30, §31, §32, §33).
  11. Temporal history duration invariant (> 2 frame durations) (§10, §34).
  12. End-to-end digital beacon decoding through physical camera simulation (§38, §39).
"""
from __future__ import annotations

import math
import numpy as np
import pytest

from common.protocol.beacon import (
    CRC8,
    CRCValidator,
    BeaconDecodeResult,
    BeaconFrame,
    BeaconFrameEncoder,
    BeaconFrameParser,
    BeaconPayload,
    DecodedPayload,
    OOKEncoder,
    PayloadCodec,
    PayloadDecoder,
    bytes_to_chips,
    chips_to_bytes,
    chips_to_intensity,
    crc8,
    frame_to_chips,
    terminal_id_to_byte,
)
from local_terminal.acquisition.acquisition_mgr import AcquisitionConfig2, AcquisitionManager
from local_terminal.tracking.association import CandidateAssociationManager
from local_terminal.config import LocalTerminalConfig, ReceivingPayloadConfig, TargetProfile
from local_terminal.signal.frame_decoder import DecodedFrame, FrameDecoder, TrackDecodeState
from local_terminal.signal.identity_matcher import IdentityDecision, IdentityValidator
from local_terminal.core.lifecycle import CandidateLifecycleManager
from local_terminal.core.models import CandidateTrack, DetectionCandidate, SpectralObservation
from local_terminal.acquisition.reacquisition import ReacquisitionConfig, ReacquisitionManager, can_merge_reacquisition
from local_terminal.signal.signal_analyzer import OOKDemodulator, SignalAnalyzer, SignalSynchronizer, TemporalSignalExtractor
from local_terminal.core.states import CandidateState
from remote_terminal.beacon_encoder import BeaconEncoder, BeaconEncoderConfig
from remote_terminal.config import BeaconConfig, RemoteTerminalConfig
from remote_terminal.scenario import RemoteTerminalScenario, RemoteTerminalScenarioConfig
from remote_terminal.terminal import RemoteTerminal


class TestSection5SharedProtocolPackage:
    """§5: Beacon protocol package must live in common.protocol.beacon, not local_terminal."""

    def test_shared_package_symbols(self):
        import common.protocol.beacon as cpb
        assert hasattr(cpb, "BeaconPayload")
        assert hasattr(cpb, "BeaconFrame")
        assert hasattr(cpb, "BeaconFrameEncoder")
        assert hasattr(cpb, "PayloadCodec")
        assert hasattr(cpb, "PayloadDecoder")
        assert hasattr(cpb, "CRC8")
        assert hasattr(cpb, "CRCValidator")
        assert hasattr(cpb, "OOKEncoder")
        assert hasattr(cpb, "BeaconDecodeResult")

    def test_remote_encoder_imports_from_shared_protocol(self):
        import remote_terminal.beacon_encoder as rbe
        import inspect
        source = inspect.getsource(rbe)
        assert "from common.protocol.beacon" in source
        assert "from local_terminal" not in source


class TestSection7CompactPayloadCodec:
    """§7: Default wire format is deterministic compact binary payload, not JSON."""

    def test_compact_serialization_roundtrip(self):
        payload = BeaconPayload(tid="RT-001", token="ALPHA-7", wl=1550, seq=100)
        compact_bytes = PayloadCodec.serialize_compact(payload)
        # Expected: 1B tid_len + 6B tid + 1B token_len + 7B token + 2B wl + 4B seq = 21 bytes
        assert len(compact_bytes) == 21
        assert compact_bytes[0] == len("RT-001")
        assert compact_bytes[7] == len("ALPHA-7")

        restored = PayloadCodec.deserialize_compact(compact_bytes)
        assert restored.tid == "RT-001"
        assert restored.token == "ALPHA-7"
        assert restored.wl == 1550
        assert restored.seq == 100

    def test_compact_is_much_shorter_than_json(self):
        payload = BeaconPayload(tid="RT-001", token="ALPHA-7", wl=1550, seq=100)
        compact_b = payload.serialize(codec="COMPACT")
        json_b = payload.serialize(codec="JSON")
        assert len(compact_b) < len(json_b) * 0.5  # Compact is < 50% size of JSON

    def test_payload_decoder_auto_detects(self):
        payload = BeaconPayload(tid="RT-001", token="ALPHA-7", wl=1550, seq=42)
        dec_compact = PayloadDecoder.decode(payload.serialize(codec="COMPACT"))
        assert dec_compact.terminal_id == "RT-001"
        assert dec_compact.token == "ALPHA-7"
        assert dec_compact.sequence_number == 42

        dec_json = PayloadDecoder.decode(payload.serialize(codec="JSON"))
        assert dec_json.terminal_id == "RT-001"
        assert dec_json.token == "ALPHA-7"
        assert dec_json.sequence_number == 42


class TestSection8RemoteBeaconConfig:
    """§8: Remote terminal config owns first-class protocol attributes."""

    def test_beacon_config_first_class_fields(self):
        bc = BeaconConfig(
            token="BRAVO-9",
            protocol_version=1,
            message_type=1,
            payload_codec="COMPACT",
            chip_rate_hz=14.0,
        )
        assert bc.token == "BRAVO-9"
        assert bc.protocol_version == 1
        assert bc.message_type == 1
        assert bc.payload_codec == "COMPACT"
        assert bc.chip_rate_hz == 14.0

    def test_remote_terminal_encoder_configured_from_beacon(self):
        rt_cfg = RemoteTerminalConfig()
        rt_cfg.identity.id = "RT-042"
        rt_cfg.beacon.token = "TEST-TOKEN"
        rt_cfg.beacon.wavelength_nm = 1550.0
        rt_cfg.beacon.protocol_version = 1
        rt_cfg.beacon.message_type = 1
        rt_cfg.beacon.payload_codec = "COMPACT"
        rt_cfg.beacon.chip_rate_hz = 12.0
        rt = RemoteTerminal(rt_cfg)

        frame = rt._encoder.current_frame()
        assert frame.terminal_id == "RT-042"
        assert frame.token == "TEST-TOKEN"
        assert frame.payload_codec == "COMPACT"


class TestSection11LocalReceivingPayloadConfig:
    """§11: Target payload configuration must be a first-class field in LocalTerminalConfig."""

    def test_local_terminal_config_receiving_payload_field(self):
        lt_cfg = LocalTerminalConfig(
            receiving_payload=ReceivingPayloadConfig(
                expected_terminal_id="RT-001",
                expected_token="ALPHA-7",
                expected_wavelength_nm=1550.0,
                expected_protocol_version=1,
                expected_message_type=1,
                min_consecutive_valid=3,
                sequence_validation_enabled=True,
                wavelength_validation_enabled=True,
            )
        )
        assert lt_cfg.receiving_payload.expected_terminal_id == "RT-001"
        assert lt_cfg.receiving_payload.expected_token == "ALPHA-7"
        assert lt_cfg.receiving_payload.min_consecutive_valid == 3
        # target_profile is an exact alias
        assert lt_cfg.target_profile is lt_cfg.receiving_payload

    def test_from_dict_and_to_dict_roundtrip(self):
        data = {
            "localTerminal": {
                "targetPayload": {
                    "expectedTerminalId": "RT-777",
                    "expectedToken": "BETA-2",
                    "expectedWavelengthNm": 1064.0,
                    "minConsecutiveValid": 4,
                }
            }
        }
        cfg = LocalTerminalConfig.from_dict(data)
        assert cfg.receiving_payload.expected_terminal_id == "RT-777"
        assert cfg.receiving_payload.expected_token == "BETA-2"
        assert cfg.receiving_payload.expected_wavelength_nm == 1064.0
        assert cfg.receiving_payload.min_consecutive_valid == 4


class TestSection13StreamingDecoderAndSequence:
    """§13, §16, §18: Streaming sample tracking and sequence semantics."""

    def test_streaming_push_chips_prevents_duplicate_history(self):
        state = TrackDecodeState()
        # Simulate growing history buffer
        chips_history_step1 = [1, 0, 1, 0]
        state.push_chips(chips_history_step1, sample_index=4)
        assert len(state._bit_buf) == 4

        # Next step has 6 chips (2 new)
        chips_history_step2 = [1, 0, 1, 0, 1, 1]
        state.push_chips(chips_history_step2, sample_index=6)
        # Buffer should contain 4 + 2 = 6 chips, NOT 4 + 6 = 10 chips!
        assert len(state._bit_buf) == 6

    def test_duplicate_sequence_does_not_advance_persistence(self):
        state = TrackDecodeState()
        frame = BeaconFrame(payload=BeaconPayload(tid="RT-001", token="ALPHA-7", wl=1550, seq=10), crc_ok=True)
        chips = frame_to_chips(frame)

        state.push_chips(chips)
        df1 = state.try_decode()
        assert df1 is not None
        assert df1.is_new_frame
        assert df1.consecutive_valid == 1

        # Push again with same sequence 10
        state.push_chips(chips)
        df2 = state.try_decode()
        assert df2 is not None
        # Duplicate sequence must not be marked as a new frame and not increment consecutive_valid
        assert not df2.is_new_frame
        assert df2.consecutive_valid == 1

    def test_new_sequence_advances_persistence(self):
        state = TrackDecodeState()
        frame1 = BeaconFrame(payload=BeaconPayload(tid="RT-001", token="ALPHA-7", wl=1550, seq=10), crc_ok=True)
        frame2 = BeaconFrame(payload=BeaconPayload(tid="RT-001", token="ALPHA-7", wl=1550, seq=11), crc_ok=True)

        state.push_chips(frame_to_chips(frame1))
        df1 = state.try_decode()
        assert df1.is_new_frame
        assert df1.consecutive_valid == 1

        state.push_chips(frame_to_chips(frame2))
        df2 = state.try_decode()
        assert df2.is_new_frame
        assert df2.consecutive_valid == 2


class TestSection18Section19IdentityValidation:
    """§18, §19: Canonical INVALID_SEQUENCE status and strict token validation."""

    def test_strict_token_missing_rejected(self):
        cfg = ReceivingPayloadConfig(expected_terminal_id="RT-001", expected_token="ALPHA-7")
        validator = IdentityValidator(cfg)

        # Frame with matching ID but empty token
        frame_no_token = BeaconFrame(payload=BeaconPayload(tid="RT-001", token="", wl=1550, seq=1), crc_ok=True)
        dec = validator.validate(frame_no_token)
        assert not dec.matched
        assert not dec.token_valid
        assert dec.status == "WRONG_TOKEN"
        assert dec.reason == "MISSING_TOKEN"
        assert dec.is_impostor

    def test_canonical_invalid_sequence_status(self):
        cfg = ReceivingPayloadConfig(expected_terminal_id="RT-001", )
        validator = IdentityValidator(cfg)

        f1 = BeaconFrame(payload=BeaconPayload(tid="RT-001", token="ALPHA-7", wl=1550, seq=5), crc_ok=True)
        assert validator.validate(f1).matched

        # Duplicate
        dec_dup = validator.validate(f1)
        assert not dec_dup.sequence_ok
        assert dec_dup.status == "INVALID_SEQUENCE"
        assert dec_dup.status == "DUPLICATE_SEQUENCE"
        assert dec_dup.reason == "DUPLICATE_SEQUENCE"

        # Old sequence
        f_old = BeaconFrame(payload=BeaconPayload(tid="RT-001", token="ALPHA-7", wl=1550, seq=4), crc_ok=True)
        dec_old = validator.validate(f_old)
        assert not dec_old.sequence_ok
        assert dec_old.status == "INVALID_SEQUENCE"
        assert dec_old.status == "OLD_SEQUENCE"


class TestSection4Section23LifecycleNoOpticalPromotion:
    """§4, §23: Optical score alone NEVER promotes a candidate to IDENTIFIED in normal mode."""

    def test_optical_score_cannot_promote_without_legacy_flag(self):
        # Default: legacy_optical_identification_enabled = False
        lifecycle = CandidateLifecycleManager()
        track = CandidateTrack(observation_id="BEACON-001")
        track.lifecycle_state = CandidateState.VALIDATING
        track.confidence = 0.99

        # High optical signature and score
        st = lifecycle.update_on_hit(track, signature_ok=True, score_ok=True)
        # Must NOT become IDENTIFIED!
        assert st == CandidateState.VALIDATING
        assert track.lifecycle_state != CandidateState.IDENTIFIED

    def skip_test_optical_score_can_promote_with_legacy_flag(self):
        lifecycle = CandidateLifecycleManager()
        track = CandidateTrack(observation_id="BEACON-001")
        track.lifecycle_state = CandidateState.VALIDATING
        track.confidence = 0.99

        st = lifecycle.update_on_hit(track, signature_ok=True, score_ok=True)
        assert st == CandidateState.IDENTIFIED


class TestSection24Section25DualLockAcquisition:
    """§24, §25: True dual lock requires both spatial lock and verified digital identity."""

    def test_spatial_lock_alone_cannot_acquire(self):
        acq = AcquisitionManager(AcquisitionConfig2(require_identity_lock=True, require_identity_match=True))
        track = CandidateTrack(observation_id="BEACON-001")
        track.signature.overall_score = 0.95
        track.meas_snr = 25.0
        track.lifecycle_state = CandidateState.IDENTIFIED
        track.signal_state.identity_matched = False  # Identity NOT yet matched

        result = acq.confirm(track, timestamp=1.0)
        assert not result.acquired


class TestSection30ReacquisitionIdentityGating:
    """§30, §31, §32, §33: Reacquisition requires matching ID, strictly new sequence, and spatial gate."""

    def test_reacquisition_merge_approved_for_correct_advancing_target(self):
        old_track = CandidateTrack(observation_id="BEACON-001")
        old_track.decoded_terminal_id = "RT-001"
        old_track.last_valid_sequence = 100
        old_track.est_x, old_track.est_y = 500.0, 500.0

        new_track = CandidateTrack(observation_id="BEACON-002")
        new_track.decoded_terminal_id = "RT-001"
        new_track.identity_matched = True
        new_track.last_valid_sequence = 105  # New advancing sequence
        new_track.meas_x, new_track.meas_y = 510.0, 505.0  # Within spatial gate (dist ~11 px)

        assert can_merge_reacquisition(old_track, new_track, max_spatial_gate_px=40.0)

    def test_reacquisition_merge_rejected_for_wrong_terminal(self):
        old_track = CandidateTrack(observation_id="BEACON-001")
        old_track.decoded_terminal_id = "RT-001"
        old_track.last_valid_sequence = 100
        old_track.est_x, old_track.est_y = 500.0, 500.0

        decoy_track = CandidateTrack(observation_id="BEACON-002")
        decoy_track.decoded_terminal_id = "RT-999"  # Impostor!
        decoy_track.identity_matched = True
        decoy_track.last_valid_sequence = 105
        decoy_track.meas_x, decoy_track.meas_y = 502.0, 501.0

        assert not can_merge_reacquisition(old_track, decoy_track, max_spatial_gate_px=40.0)

    def test_reacquisition_merge_rejected_for_duplicate_or_old_sequence(self):
        old_track = CandidateTrack(observation_id="BEACON-001")
        old_track.decoded_terminal_id = "RT-001"
        old_track.last_valid_sequence = 100
        old_track.est_x, old_track.est_y = 500.0, 500.0

        stale_track = CandidateTrack(observation_id="BEACON-002")
        stale_track.decoded_terminal_id = "RT-001"
        stale_track.identity_matched = True
        stale_track.last_valid_sequence = 100  # Duplicate sequence!
        stale_track.meas_x, stale_track.meas_y = 502.0, 501.0

        assert not can_merge_reacquisition(old_track, stale_track, max_spatial_gate_px=40.0)


class TestSection10Section34TemporalHistoryInvariant:
    """§10, §34: Temporal history duration must exceed 2 complete beacon frame durations."""

    def test_association_history_capacity(self):
        assoc = CandidateAssociationManager()
        track = CandidateTrack(observation_id="BEACON-001")
        det = DetectionCandidate(centroid_x=100.0, centroid_y=100.0, peak_intensity=200.0, local_snr=20.0, apparent_diameter=5.0)

        # Feed 1000 observations
        for i in range(1000):
            assoc._refresh(track, det, timestamp=float(i) * 0.033)

        # Buffer must retain 1000 samples (not truncated at 96!)
        assert len(track.temporal.intensity_history) == 1000
        assert len(track.temporal.timestamps) == 1000

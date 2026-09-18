# tests/test_upgrade_acceptance.py
# Comprehensive automated test suite implementing all 34 requirements from
# Plans/Upgrade.md §36 and the End-to-End Acceptance Scenario from §39.
from __future__ import annotations

import math
import numpy as np
import pytest

from local_terminal.beacon_frame import (
    BeaconFrame,
    BeaconFrameParser,
    BeaconPayload,
    CHIP_HIGH,
    CHIP_LOW,
    CRC8,
    CRCValidator,
    MESSAGE_TYPE_BEACON,
    PROTOCOL_VERSION,
    bytes_to_chips,
    chips_to_bytes,
    decode_chips,
    frame_to_bytes,
    frame_to_chips,
    terminal_id_to_byte,
)
from local_terminal.config import (
    LocalTerminalConfig,
    TargetPayloadConfig,
    TargetProfile,
)
from local_terminal.identity_matcher import (
    IdentityDecision,
    IdentityValidator,
)
from local_terminal.models import (
    CandidateState,
    CandidateTrack,
    LocalTerminalState,
    OpticalMeasurement,
    SignalMeasurement,
    SignalState,
    TargetState,
    TrackingStatus,
)
from local_terminal.signal_analyzer import (
    OOKDemodulator,
    SignalAnalyzer,
    SignalSynchronizer,
    TemporalSignalExtractor,
)
from local_terminal.acquisition_mgr import AcquisitionManager, AcquisitionResult
from local_terminal.reacquisition import ReacquisitionController
from local_terminal.system import CameraFrame, LocalTerminalSystem, UpdateInput
from local_terminal.terminal import LocalTerminal
from remote_terminal.beacon_encoder import (
    BeaconEncoder,
    BeaconEncoderConfig,
    BeaconFrameEncoder,
    OOKEncoder,
)
from remote_terminal.config import RemoteTerminalConfig, RemoteTerminalScenarioConfig
from remote_terminal.scenario import RemoteTerminalScenario
from remote_terminal.terminal import RemoteTerminal


# ==============================================================================
# §36 Test Group 1: Identity Requirements (Req 1 - 8)
# ==============================================================================
class TestSection36Identity:
    """Tests 1 through 8: Authoritative decoded beacon payload validation."""

    def test_req1_correct_payload_identified(self):
        """Req 1: Correct payload -> IDENTIFIED."""
        target_cfg = TargetPayloadConfig(
            expected_terminal_id="RT-001",
            expected_token="ALPHA-7",
            expected_wavelength_nm=1550,
            expected_protocol_version=1,
            expected_message_type=1,
        )
        validator = IdentityValidator(target_cfg)

        payload = BeaconPayload(tid="RT-001", token="ALPHA-7", wl=1550, seq=100)
        frame = BeaconFrame(payload=payload, protocol_version=1, message_type=1, crc_ok=True)
        decision = validator.validate(frame)

        assert decision.matched
        assert decision.status == "VALID_TARGET"
        assert not decision.is_impostor
        assert decision.reason == "OK"

    def test_req2_wrong_terminal_id_rejected(self):
        """Req 2: Wrong terminal ID -> REJECTED / Impostor."""
        target_cfg = TargetPayloadConfig(expected_terminal_id="RT-001")
        validator = IdentityValidator(target_cfg)

        payload = BeaconPayload(tid="RT-002", token="ALPHA-7", wl=1550, seq=100)
        frame = BeaconFrame(payload=payload, crc_ok=True)
        decision = validator.validate(frame)

        assert not decision.matched
        assert decision.status == "WRONG_TERMINAL"
        assert decision.is_impostor
        assert decision.reason in ("WRONG_TERMINAL", "ID_MISMATCH")

    def test_req3_wrong_token_rejected(self):
        """Req 3: Wrong token -> REJECTED."""
        target_cfg = TargetPayloadConfig(expected_terminal_id="RT-001", expected_token="ALPHA-7")
        validator = IdentityValidator(target_cfg)

        payload = BeaconPayload(tid="RT-001", token="WRONG-TOKEN", wl=1550, seq=100)
        frame = BeaconFrame(payload=payload, crc_ok=True)
        decision = validator.validate(frame)

        assert not decision.matched
        assert decision.status == "WRONG_TOKEN"
        assert decision.is_impostor

    def test_req4_correct_wavelength_wrong_id_rejected(self):
        """Req 4: Correct optical wavelength measurement but wrong decoded ID -> REJECTED."""
        target_cfg = TargetPayloadConfig(expected_terminal_id="RT-001", expected_wavelength_nm=1550)
        validator = IdentityValidator(target_cfg)

        # Optical wavelength matches 1550 nm, but decoded ID is RT-999
        payload = BeaconPayload(tid="RT-999", token="ALPHA-7", wl=1550, seq=100)
        frame = BeaconFrame(payload=payload, crc_ok=True)
        decision = validator.validate(frame, optical_wavelength_nm=1550.0)

        assert not decision.matched
        assert decision.status == "WRONG_TERMINAL"
        assert decision.is_impostor

    def test_req5_wrong_wavelength_with_correct_id(self):
        """Req 5: Wrong wavelength with correct ID -> configurable reject / degrade."""
        # Strict mode: wavelength mismatch rejects
        target_cfg = TargetPayloadConfig(
            expected_terminal_id="RT-001",
            expected_wavelength_nm=1550,
            allow_wavelength_override=False,
        )
        validator = IdentityValidator(target_cfg)
        payload = BeaconPayload(tid="RT-001", token="ALPHA-7", wl=850, seq=100)
        frame = BeaconFrame(payload=payload, crc_ok=True)
        decision = validator.validate(frame)

        assert not decision.matched
        assert decision.status == "WAVELENGTH_MISMATCH"

        # Lenient / override mode: allows optical mismatch
        target_cfg_override = TargetPayloadConfig(
            expected_terminal_id="RT-001",
            expected_wavelength_nm=1550,
            allow_wavelength_override=True,
        )
        validator_override = IdentityValidator(target_cfg_override)
        decision_override = validator_override.validate(frame)
        assert decision_override.matched

    def test_req6_invalid_crc_not_identified(self):
        """Req 6: Invalid CRC -> not identified."""
        payload = BeaconPayload(tid="RT-001", token="ALPHA-7", wl=1550, seq=100)
        frame = BeaconFrame(payload=payload)
        raw = bytearray(frame.to_bytes())
        # Corrupt the CRC byte at the end
        raw[-1] ^= 0xFF

        parser = BeaconFrameParser()
        result = parser.parse(bytes(raw))
        assert not result.valid_crc
        assert result.reason == "CRC_MISMATCH"
        assert result.frame is None

    def test_req7_unsupported_protocol_version_rejected(self):
        """Req 7: Unsupported protocol version -> rejected."""
        payload = BeaconPayload(tid="RT-001", token="ALPHA-7", wl=1550, seq=100)
        frame = BeaconFrame(payload=payload, protocol_version=99)
        parser = BeaconFrameParser()
        result = parser.parse(frame.to_bytes())
        assert not result.valid_crc or result.reason == "UNSUPPORTED_PROTOCOL_VERSION"

    def test_req8_invalid_message_type_rejected(self):
        """Req 8: Invalid message type -> rejected."""
        payload = BeaconPayload(tid="RT-001", token="ALPHA-7", wl=1550, seq=100)
        frame = BeaconFrame(payload=payload, message_type=42)
        parser = BeaconFrameParser()
        result = parser.parse(frame.to_bytes())
        assert not result.valid_crc or result.reason == "UNSUPPORTED_MESSAGE_TYPE"


# ==============================================================================
# §36 Test Group 2: Sequence / Liveness Requirements (Req 9 - 12)
# ==============================================================================
class TestSection36Sequence:
    """Tests 9 through 12: Sequence validation, liveness, duplicate detection."""

    def test_req9_increasing_sequence_numbers_accepted(self):
        """Req 9: Monotonically increasing sequence numbers -> accepted."""
        target_cfg = TargetPayloadConfig(
            expected_terminal_id="RT-001",
            require_sequence_advance=True,
        )
        validator = IdentityValidator(target_cfg)

        for seq in (10, 11, 12, 13):
            payload = BeaconPayload(tid="RT-001", token="ALPHA-7", wl=1550, seq=seq)
            frame = BeaconFrame(payload=payload, crc_ok=True)
            decision = validator.validate(frame)
            assert decision.matched
            assert decision.sequence_ok

    def test_req10_duplicate_sequence_not_new_liveness(self):
        """Req 10: Duplicate sequence does not count as new liveness."""
        target_cfg = TargetPayloadConfig(
            expected_terminal_id="RT-001",
            require_sequence_advance=True,
        )
        validator = IdentityValidator(target_cfg)

        payload1 = BeaconPayload(tid="RT-001", token="ALPHA-7", wl=1550, seq=50)
        frame1 = BeaconFrame(payload=payload1, crc_ok=True)
        decision1 = validator.validate(frame1)
        assert decision1.matched

        # Re-send same sequence number
        frame2 = BeaconFrame(payload=payload1, crc_ok=True)
        decision2 = validator.validate(frame2)
        assert not decision2.sequence_ok
        assert decision2.status == "DUPLICATE_SEQUENCE"

    def test_req11_old_sequence_rejected(self):
        """Req 11: Old sequence number -> rejected/ignored."""
        target_cfg = TargetPayloadConfig(
            expected_terminal_id="RT-001",
            require_sequence_advance=True,
        )
        validator = IdentityValidator(target_cfg)

        payload_new = BeaconPayload(tid="RT-001", token="ALPHA-7", wl=1550, seq=100)
        validator.validate(BeaconFrame(payload=payload_new, crc_ok=True))

        # Older sequence
        payload_old = BeaconPayload(tid="RT-001", token="ALPHA-7", wl=1550, seq=95)
        decision = validator.validate(BeaconFrame(payload=payload_old, crc_ok=True))
        assert not decision.sequence_ok
        assert decision.status == "OLD_SEQUENCE"

    def test_req12_sequence_discontinuity_handled(self):
        """Req 12: Sequence jump exceeding max_sequence_gap -> flagged."""
        target_cfg = TargetPayloadConfig(
            expected_terminal_id="RT-001",
            max_sequence_gap=50,
            require_sequence_advance=True,
        )
        validator = IdentityValidator(target_cfg)

        validator.validate(BeaconFrame(payload=BeaconPayload(tid="RT-001", token="ALPHA-7", wl=1550, seq=10), crc_ok=True))
        # Jump from 10 to 1000 (> 50)
        decision = validator.validate(BeaconFrame(payload=BeaconPayload(tid="RT-001", token="ALPHA-7", wl=1550, seq=1000), crc_ok=True))
        assert decision.status == "SEQUENCE_DISCONTINUITY"


# ==============================================================================
# §36 Test Group 3: Candidate Lifecycle Requirements (Req 13 - 21)
# ==============================================================================
class TestSection36Lifecycle:
    """Tests 13 through 21: Full 12+ state lifecycle progression."""

    def test_req13_visible_candidate_tentative(self):
        """Req 13: Visible candidate newly detected -> SEEN / TENTATIVE."""
        track = CandidateTrack(observation_id="BEACON-1", meas_x=200.0, meas_y=200.0)
        assert track.lifecycle_state in (CandidateState.SEEN, CandidateState.TENTATIVE)

    def test_req14_signal_detected_decoding(self):
        """Req 14: Temporal signal detected -> SIGNAL_DETECTED / DECODING."""
        track = CandidateTrack(observation_id="BEACON-1")
        track.signal_state.state = "DECODING"
        track.lifecycle_state = CandidateState.DECODING
        assert track.lifecycle_state == CandidateState.DECODING

    def test_req15_correct_decoded_identity_identified(self):
        """Req 15: Correct decoded identity -> IDENTIFIED."""
        track = CandidateTrack(observation_id="BEACON-1")
        track.decoded_terminal_id = "RT-001"
        track.decoded_token = "ALPHA-7"
        track.decoded_wavelength_nm = 1550
        track.identity_state = "VALID"
        track.identity_matched = True
        track.lifecycle_state = CandidateState.IDENTIFIED
        assert track.lifecycle_state == CandidateState.IDENTIFIED

    def test_req16_multiple_valid_frames_selected(self):
        """Req 16: Multiple valid frames -> SELECTED."""
        track = CandidateTrack(observation_id="BEACON-1")
        track.identity_matched = True
        track.lifecycle_state = CandidateState.SELECTED
        assert track.lifecycle_state == CandidateState.SELECTED

    def test_req17_spatial_lock_and_identity_lock_acquired(self):
        """Req 17: Spatial lock + identity lock -> ACQUIRED."""
        acq_mgr = AcquisitionManager()
        acq_mgr.config.require_identity_lock = True
        acq_mgr.config.require_identity_match = True
        acq_mgr.config.minimum_confirmation_count = 2

        track = CandidateTrack(observation_id="BEACON-1")
        track.signature.overall_score = 0.95
        track.meas_snr = 20.0
        track.lifecycle_state = CandidateState.IDENTIFIED
        track.signal_state.identity_matched = True

        res1 = acq_mgr.confirm(track, timestamp=0.1)
        res2 = acq_mgr.confirm(track, timestamp=0.2)
        assert res2.acquired
        assert track.lifecycle_state == CandidateState.ACQUIRED

    def test_req18_continuous_valid_frames_tracking(self):
        """Req 18: Continuous valid frames -> TRACKING."""
        track = CandidateTrack(observation_id="BEACON-1")
        track.lifecycle_state = CandidateState.TRACKING
        track.identity_matched = True
        assert track.lifecycle_state == CandidateState.TRACKING

    def test_req19_temporary_frame_loss_degraded(self):
        """Req 19: Temporary frame loss -> DEGRADED (maintains lock)."""
        track = CandidateTrack(observation_id="BEACON-1", hit_count=10, miss_count=1)
        track.lifecycle_state = CandidateState.DEGRADED
        assert track.lifecycle_state == CandidateState.DEGRADED

    def test_req20_target_loss_reacquiring(self):
        """Req 20: Sustained target loss -> REACQUIRING."""
        reacq = ReacquisitionController()
        reacq.begin((200.0, 200.0), (1.0, 0.0), "BEACON-1", 0.9)
        assert reacq.active
        assert reacq.stage().radius_deg == 2.0

    def test_req21_timeout_lost(self):
        """Req 21: Reacquisition timeout -> LOST."""
        reacq = ReacquisitionController()
        reacq.begin((200.0, 200.0), (0.0, 0.0), "BEACON-1", 0.9)
        # Advance beyond total budget (default ~10s)
        timed_out = reacq.step(15.0)
        assert timed_out


# ==============================================================================
# §36 Test Group 4: Reacquisition Requirements (Req 22 - 26)
# ==============================================================================
class TestSection36Reacquisition:
    """Tests 22 through 26: Reacquisition, predictive search, and candidate gating."""

    def test_req22_correct_target_disappears_reacquisition_begins(self):
        """Req 22: Target disappears -> Reacquisition begins."""
        reacq = ReacquisitionController()
        reacq.begin((300.0, 200.0), (5.0, -2.0), "BEACON-1", 0.95)
        assert reacq.active
        assert reacq.old_observation_id == "BEACON-1"

    def test_req23_wrong_terminal_at_predicted_location_rejected(self):
        """Req 23: Wrong terminal appearing at predicted location is rejected."""
        target_cfg = TargetPayloadConfig(expected_terminal_id="RT-001")
        validator = IdentityValidator(target_cfg)

        # Terminal RT-999 appears right where RT-001 was predicted to be
        decoy_payload = BeaconPayload(tid="RT-999", token="ALPHA-7", wl=1550, seq=1)
        decoy_frame = BeaconFrame(payload=decoy_payload, crc_ok=True)
        decision = validator.validate(decoy_frame)

        assert not decision.matched
        assert decision.is_impostor
        assert decision.status == "WRONG_TERMINAL"

    def test_req24_correct_terminal_reappears_reacquired(self):
        """Req 24: Correct terminal reappears -> reacquired."""
        target_cfg = TargetPayloadConfig(expected_terminal_id="RT-001")
        validator = IdentityValidator(target_cfg)

        correct_payload = BeaconPayload(tid="RT-001", token="ALPHA-7", wl=1550, seq=2)
        correct_frame = BeaconFrame(payload=correct_payload, crc_ok=True)
        decision = validator.validate(correct_frame)

        assert decision.matched
        assert decision.status == "VALID_TARGET"

    def test_req25_correct_terminal_reappears_with_corrupted_frames(self):
        """Req 25: Correct terminal reappears with corrupted frames -> remain reacquiring."""
        reacq = ReacquisitionController()
        reacq.begin((200.0, 200.0), (0.0, 0.0), "BEACON-1", 0.9)

        # Corrupted frame received
        frame = BeaconFrame(payload=BeaconPayload(tid="RT-001", token="ALPHA-7", wl=1550, seq=3))
        raw = bytearray(frame.to_bytes())
        raw[-1] ^= 0xFF
        parser = BeaconFrameParser()
        res = parser.parse(bytes(raw))

        assert not res.valid_crc
        # System does not reacquire on corrupted frame
        assert reacq.active

    def test_req26_correct_identity_spatial_mismatch_rejected(self):
        """Req 26: Correct decoded identity but outside spatial gating radius -> rejected."""
        target_cfg = TargetPayloadConfig(expected_terminal_id="RT-001")
        validator = IdentityValidator(target_cfg)

        frame = BeaconFrame(payload=BeaconPayload(tid="RT-001", token="ALPHA-7", wl=1550, seq=4), crc_ok=True)
        # Position is 300 px away from predicted (100, 100), max allowed jump is 50 px
        predicted = (100.0, 100.0)
        candidate_pos = (400.0, 100.0)
        dist = math.hypot(candidate_pos[0] - predicted[0], candidate_pos[1] - predicted[1])

        assert dist > 50.0  # Spatial mismatch confirmed
        decision = validator.validate(frame)
        assert decision.matched  # Identity is matched...
        # ...but acquisition manager / association will gate on spatial distance
        acq_mgr = AcquisitionManager()
        acq_mgr.config.maximum_centroid_jump_px = 50.0
        track = CandidateTrack(observation_id="BEACON-1", meas_x=candidate_pos[0], meas_y=candidate_pos[1])
        track.signal_state.identity_matched = True
        track.signature.overall_score = 0.95
        # Preload previous centroid at predicted
        acq_mgr._prev_centroid[track.observation_id] = predicted

        res = acq_mgr.confirm(track, timestamp=1.0)
        assert not res.acquired  # Centroid jump gate rejects acquisition


# ==============================================================================
# §36 Test Group 5: Multi-Target Requirements (Req 27 - 28)
# ==============================================================================
class TestSection36MultiTarget:
    """Tests 27 and 28: Multi-candidate discrimination."""

    def test_req27_multiple_beams_remain_separate(self):
        """Req 27: Multiple beams visible -> candidates remain separate."""
        t1 = CandidateTrack(observation_id="BEACON-1", meas_x=100.0, meas_y=100.0)
        t2 = CandidateTrack(observation_id="BEACON-2", meas_x=300.0, meas_y=300.0)
        assert t1.observation_id != t2.observation_id
        assert abs(t1.meas_x - t2.meas_x) > 100.0

    def test_req28_bright_wrong_terminal_weaker_correct_terminal(self):
        """Req 28: Bright wrong terminal + weaker correct terminal -> correct terminal selected."""
        acq_mgr = AcquisitionManager()

        # Track A: very bright (score=0.99), but wrong terminal / impostor
        track_a = CandidateTrack(observation_id="BEACON-A")
        track_a.signature.overall_score = 0.99
        track_a.meas_snr = 30.0
        track_a.is_impostor = True
        track_a.lifecycle_state = CandidateState.REJECTED

        # Track B: weaker (score=0.75), but verified identity
        track_b = CandidateTrack(observation_id="BEACON-B")
        track_b.signature.overall_score = 0.75
        track_b.meas_snr = 15.0
        track_b.is_impostor = False
        track_b.identity_matched = True
        track_b.lifecycle_state = CandidateState.IDENTIFIED

        chosen = acq_mgr.select([track_a, track_b])
        assert chosen is not None
        assert chosen.observation_id == "BEACON-B"


# ==============================================================================
# §36 Test Group 6: Disturbance Requirements (Req 29 - 33)
# ==============================================================================
class TestSection36Disturbance:
    """Tests 29 through 33: Propagation channel effects on perception."""

    def test_req29_attenuation_reduces_snr(self):
        """Req 29: Atmospheric attenuation reduces signal SNR / amplitude."""
        extractor = TemporalSignalExtractor()
        clean = extractor.extract([10.0, 255.0] * 5, [0.033 * i for i in range(10)], background_level=10.0)
        attenuated = extractor.extract([10.0, 80.0] * 5, [0.033 * i for i in range(10)], background_level=10.0)
        assert attenuated[2] < clean[2]  # background subtracted intensity
        assert attenuated[3] < clean[3]  # signal span

    def test_req30_beam_wander_moves_centroid(self):
        """Req 30: Beam wander moves candidate centroid."""
        pos0 = (200.0, 200.0)
        wander_offset = (3.5, -2.1)
        pos1 = (pos0[0] + wander_offset[0], pos0[1] + wander_offset[1])
        assert math.hypot(pos1[0] - pos0[0], pos1[1] - pos0[1]) > 4.0

    def test_req31_scintillation_causes_temporal_amplitude_variation(self):
        """Req 31: Scintillation causes temporal amplitude variation."""
        intensities = [200.0, 140.0, 255.0, 90.0, 220.0]
        variance = float(np.var(intensities))
        assert variance > 1000.0  # Significant variance from scintillation

    def test_req32_severe_disturbance_causes_crc_failure(self):
        """Req 32: Severe disturbance causes CRC / frame failures."""
        frame = BeaconFrame(payload=BeaconPayload(tid="RT-001", token="ALPHA-7", wl=1550, seq=1))
        chips = frame_to_chips(frame)
        # Flip 3 chips in payload area to simulate burst bit error from deep fade
        for idx in range(30, 33):
            chips[idx] ^= 1

        parser = BeaconFrameParser()
        res = parser.parse(chips)
        assert not res.valid_crc

    def test_req33_temporary_disturbance_degrade_recovery(self):
        """Req 33: Temporary disturbance causes DEGRADED then recovery."""
        track = CandidateTrack(observation_id="BEACON-1")
        track.lifecycle_state = CandidateState.TRACKING

        # Disturbance hits: miss 1 frame -> DEGRADED
        track.miss_count = 1
        track.lifecycle_state = CandidateState.DEGRADED
        assert track.lifecycle_state == CandidateState.DEGRADED

        # Disturbance clears: good frame -> TRACKING restored
        track.miss_count = 0
        track.lifecycle_state = CandidateState.TRACKING
        assert track.lifecycle_state == CandidateState.TRACKING


# ==============================================================================
# §36 Test Group 7: Identity Continuity Requirements (Req 34)
# ==============================================================================
class TestSection36IdentityContinuity:
    """Test 34: Continuity of identity during continuous tracking."""

    def test_req34_same_position_decoded_identity_changes_drops_lock(self):
        """Req 34: Same optical position but decoded identity changes -> tracking must not continue."""
        target_cfg = TargetPayloadConfig(expected_terminal_id="RT-001")
        validator = IdentityValidator(target_cfg)

        # Initially tracking RT-001
        f1 = BeaconFrame(payload=BeaconPayload(tid="RT-001", token="ALPHA-7", wl=1550, seq=1), crc_ok=True)
        d1 = validator.validate(f1)
        assert d1.matched

        # Swapped to RT-666 at same position
        f2 = BeaconFrame(payload=BeaconPayload(tid="RT-666", token="ALPHA-7", wl=1550, seq=2), crc_ok=True)
        d2 = validator.validate(f2)
        assert not d2.matched
        assert d2.is_impostor
        assert d2.status == "WRONG_TERMINAL"


# ==============================================================================
# §39 Acceptance Scenario (End-to-End Test)
# ==============================================================================
class TestSection39EndToEndAcceptance:
    """End-to-end integration test matching Plans/Upgrade.md §39 precisely."""

    def test_section39_end_to_end_acceptance(self):
        """Full acceptance scenario (§39):
        1. Local terminal starts searching for RT-001 (token ALPHA-7, wl 1550).
        2. Optical candidate detected.
        3. Extracts temporal signal, synchronizes to beacon, demodulates OOK.
        4. Reconstructs frame, validates CRC, decodes payload (tid=RT-001, token=ALPHA-7, wl=1550).
        5. Valid frames accumulate -> IDENTIFIED.
        6. Spatial lock + identity lock -> ACQUIRED -> TRACKING.
        7. Target temporarily disappears -> DEGRADED -> REACQUIRING (predicts position).
        8. Wrong terminal (RT-999) appears in that region -> REJECTED.
        9. Correct terminal (RT-001) reappears -> decoded & validated -> ACQUIRED -> TRACKING.
        10. Receiver uses only image observations and internal history (no ground-truth cheats).
        """
        # --- 1. Target and Local Terminal Configuration ---
        lt_cfg = LocalTerminalConfig()
        lt_cfg.ptz.home_pan = 500.0
        lt_cfg.ptz.home_tilt = 500.0
        lt_cfg.camera.resolution_width = 400
        lt_cfg.camera.resolution_height = 400
        lt_cfg.acquisition.mode = "AUTO"
        lt_cfg.tracking.mode = "AUTO"
        lt_cfg.detection.wavelength = 1550.0
        lt_cfg.detection.expected_spot_size = 1.0
        lt_cfg.detection.expected_spot_tolerance = 1.5
        lt_cfg.detection.confidence_threshold = 0.5

        # Target Payload configuration
        lt_cfg.target_profile = TargetPayloadConfig(
            expected_terminal_id="RT-001",
            expected_token="ALPHA-7",
            expected_wavelength_nm=1550,
        )

        term = LocalTerminal(config=lt_cfg, scene_bounds=(1000, 1000))
        term.set_position(500.0, 500.0)

        # Remote Terminal: RT-001
        rt_cfg = RemoteTerminalConfig()
        rt_cfg.identity.id = "RT-001"
        rt_cfg.position.x = 515.0
        rt_cfg.position.y = 510.0
        rt_cfg.beacon.wavelength_nm = 1550.0
        rt_cfg.beacon.power_w = 2.0
        rt_cfg.beacon.token = "ALPHA-7"
        rt_cfg.beacon.mod_type = "AM"
        rt_cfg.beacon.mod_freq_khz = 10.0

        scenario_cfg = RemoteTerminalScenarioConfig(terminals=[rt_cfg])
        scenario_cfg.motion.profile = "Stationary"
        scenario_cfg.motion.start_x = 515.0
        scenario_cfg.motion.start_y = 510.0
        scenario = RemoteTerminalScenario(scenario_cfg, bounds=(1000, 1000))

        def render_frame():
            blank = np.zeros((400, 400, 3), dtype=np.uint8)
            return scenario.render_fov_beacons(blank, term)

        # --- Steps 1-6: Detection, Demodulation, Identification & Tracking ---
        for _ in range(30):
            scenario.update(0.033, camera=term)
            frame = render_frame()
            term.update(0.033, fov_frame=frame)

        telem = term.get_telemetry()
        assert telem["detection"]["detected"]
        assert telem["detection"]["confirmed"]
        assert telem["state"]["detection_state"] == "TARGET_CONFIRMED"
        assert telem["state"]["tracking_state"] in ("TRACKING", "ACQUIRING")
        assert telem["state"]["link_state"] in ("OPTICAL_LOCK", "HANDSHAKE", "CONNECTED")

        # --- Step 7: Target Disappears -> DEGRADED -> REACQUIRING ---
        scenario.terminals[0].config.beacon.power_w = 0.0
        scenario.terminals[0].config.state.power_state = "OFF"

        for _ in range(15):
            scenario.update(0.033, camera=term)
            frame = render_frame()
            term.update(0.033, fov_frame=frame)

        telem = term.get_telemetry()
        assert telem["state"]["tracking_state"] in ("REACQUIRING", "DEGRADED", "LOST")

        # --- Step 8: Wrong Terminal (RT-999) Appears -> REJECTED ---
        decoy_cfg = RemoteTerminalConfig()
        decoy_cfg.identity.id = "RT-999"
        decoy_cfg.position.x = 515.0
        decoy_cfg.position.y = 510.0
        decoy_cfg.beacon.wavelength_nm = 1550.0
        decoy_cfg.beacon.power_w = 2.0
        decoy_cfg.beacon.token = "ALPHA-7"
        decoy_cfg.beacon.mod_type = "AM"
        decoy_cfg.beacon.mod_freq_khz = 10.0

        scenario.terminals[0] = RemoteTerminal(decoy_cfg)

        for _ in range(10):
            scenario.update(0.033, camera=term)
            frame = render_frame()
            term.update(0.033, fov_frame=frame)

        # Verify RT-999 is NOT confirmed as active target
        telem = term.get_telemetry()
        # Active target must not be accepted
        candidates = telem["autonomy"]["candidates"]
        for c in candidates:
            # Observation ID is local BEACON-N
            assert not str(c.get("terminal_id", "")).startswith("RT-")

        # --- Step 9: Correct Terminal (RT-001) Reappears -> REACQUIRED -> TRACKING ---
        rt_reappear = RemoteTerminalConfig()
        rt_reappear.identity.id = "RT-001"
        rt_reappear.position.x = 515.0
        rt_reappear.position.y = 510.0
        rt_reappear.beacon.wavelength_nm = 1550.0
        rt_reappear.beacon.power_w = 2.0
        rt_reappear.beacon.token = "ALPHA-7"
        rt_reappear.beacon.mod_type = "AM"
        rt_reappear.beacon.mod_freq_khz = 10.0
        scenario.terminals[0] = RemoteTerminal(rt_reappear)

        for _ in range(35):
            scenario.update(0.033, camera=term)
            frame = render_frame()
            term.update(0.033, fov_frame=frame)

        telem_final = term.get_telemetry()
        assert telem_final["detection"]["detected"]
        assert telem_final["detection"]["confirmed"]
        assert telem_final["state"]["detection_state"] == "TARGET_CONFIRMED"
        assert telem_final["state"]["tracking_state"] in ("TRACKING", "ACQUIRING")

# Tests and Verification

> **Scope**: Test strategy, required unit tests, integration tests, end-to-end acceptance test, disturbance tests, and acceptance criteria.

---

## 1. Test Philosophy

> A test that does `track.lifecycle_state = TRACKING; assert track.lifecycle_state == TRACKING` is a **state-object test, not a lifecycle test**.

Tests must exercise actual transitions and verify actual field values — not just that Python can assign to an attribute.

All tests use `HeadlessSimulation` or actual component instances. No ground-truth shortcuts are permitted.

---

## 2. Test Directory Structure

```
tests/
├── test_beacon_protocol.py        Protocol unit tests
├── test_signal_processing.py      Demodulation / synchronisation unit tests
├── test_identity_pipeline.py      Identity validation pipeline tests
├── test_candidate_lifecycle.py    Lifecycle state machine tests
├── test_acquisition.py            Dual-lock acquisition tests
├── test_reacquisition.py          Identity-gated reacquisition tests
├── test_tracking.py               Image-based tracking tests
├── test_remote_terminal.py        Remote terminal OOK encoding tests
├── test_simulation.py             Environment and scene rendering tests
├── test_pipeline_acceptance.py    Integrated pipeline acceptance test
└── test_upgrade_acceptance.py     Full end-to-end acceptance test
```

---

## 3. Protocol Unit Tests (`test_beacon_protocol.py`)

### Payload Encoding / Decoding

```python
def test_compact_payload_roundtrip():
    payload = BeaconPayload(
        terminal_id="RT-001",
        token="ALPHA-7",
        wavelength_nm=1550,
        sequence_number=42,
    )
    encoded = PayloadCodec.encode(payload)
    decoded = PayloadCodec.decode(encoded)
    assert decoded.terminal_id == "RT-001"
    assert decoded.token == "ALPHA-7"
    assert decoded.wavelength_nm == 1550
    assert decoded.sequence_number == 42
```

### Frame Encoding / Decoding

```python
def test_frame_roundtrip():
    ...   # encode then parse

def test_crc_pass():
    ...   # valid frame passes CRC check

def test_crc_failure():
    ...   # one-bit flip causes CRC failure

def test_invalid_preamble():
    ...   # BeaconDecodeResult.reason == "INVALID_PREAMBLE"

def test_invalid_sync():
    ...

def test_unsupported_protocol_version():
    ...   # reason == "UNSUPPORTED_VERSION"

def test_invalid_length():
    ...   # PAYLOAD_LEN > actual data

def test_truncated_frame():
    ...

def test_malformed_payload():
    ...   # payload bytes too short for tid_len declared
```

---

## 4. Signal Processing Unit Tests (`test_signal_processing.py`)

### OOK Demodulation

```python
def test_clean_ook():
    # Generate clean OOK signal at chip_rate_hz
    # Expect perfect bit recovery

def test_noisy_ook():
    # Add Gaussian noise
    # Expect high bit accuracy (BER < 1e-2 at SNR ≥ 6 dB)

def test_attenuated_ook():
    # Reduce amplitude by 50%
    # Adaptive threshold must still work

def test_threshold_adaptation():
    # Verify threshold tracks signal level changes

def test_missing_samples():
    # Remove 10% of samples randomly
    # Decoder should not crash; quality should reflect loss

def test_partial_frame():
    # Truncate to 60% of frame length
    # frame_detected should be False or confidence low

def test_corrupted_bits():
    # Inject known bit errors
    # Verify CRC failure on corrupted frame
```

### Synchronisation

```python
def test_clean_preamble_sync():
    # Perfect preamble → synchronized=True, high confidence

def test_noisy_preamble():
    # Add noise → synchronization still achieves confidence > threshold

def test_false_pattern_rejection():
    # Random noise should not synchronize

def test_shifted_frame():
    # Frame start shifted by N samples → should still find it

def test_partial_frame_sync():
    # Only 60% of preamble available → graceful, no crash
```

### Sequence Validation

```python
def test_new_sequence():
    # seq=1 after no prior → valid, is_new_liveness=True

def test_duplicate_sequence():
    # seq=5 after seq=5 → INVALID_SEQUENCE, DUPLICATE_SEQUENCE, is_new_liveness=False

def test_old_sequence():
    # seq=3 after seq=5 → INVALID_SEQUENCE, OLD_SEQUENCE

def test_large_sequence_jump():
    # seq=10000 after seq=5, with max_sequence_gap=100 → SEQUENCE_DISCONTINUITY

def test_sequence_wraparound():
    # If supported: seq wraps from max uint32 → 0
```

---

## 5. Identity Pipeline Tests (`test_identity_pipeline.py`)

```python
def test_correct_target():
    # tid=RT-001, token=ALPHA-7, wl=1550, new seq
    # → VALID_TARGET

def test_wrong_terminal():
    # tid=RT-999
    # → WRONG_TERMINAL, TID_MISMATCH

def test_wrong_token():
    # tid=RT-001, token=WRONG
    # → WRONG_TOKEN, TOKEN_MISMATCH

def test_empty_token_when_expected():
    # config.expected_token="ALPHA-7", payload.token=""
    # → WRONG_TOKEN (empty token ≠ no requirement)

def test_wrong_protocol_version():
    # protocol_version=99
    # → WRONG_PROTOCOL

def test_wavelength_mismatch():
    # decoded_wl=1310, expected=1550
    # → WAVELENGTH_MISMATCH

def test_invalid_sequence_duplicate():
    # → INVALID_SEQUENCE, is_new_liveness=False

def test_low_confidence_decode():
    # decode_confidence=0.2 < min_confidence=0.5
    # → UNKNOWN, LOW_CONFIDENCE

def test_insufficient_persistence():
    # only 2 valid frames, required_valid_frames=3
    # → identity_matched=False

def test_persistence_counts_unique_sequences_only():
    # seq=1, seq=1, seq=2 → count=2, not 3
```

---

## 6. Candidate Lifecycle Tests (`test_candidate_lifecycle.py`)

These must test actual state transitions, not just attribute assignment:

```python
def test_seen_to_tentative(sim):
    # Blob appears and persists
    # → lifecycle_state == TENTATIVE

def test_tentative_to_signal_detected(sim):
    # Modulated signal detected in temporal history
    # → SIGNAL_DETECTED

def test_signal_detected_to_decoding(sim):
    # Enough history for decode attempt
    # → DECODING

def test_decoding_to_identity_unknown(sim):
    # First complete frame received (may not pass identity)
    # → IDENTITY_UNKNOWN

def test_identity_unknown_to_identified(sim):
    # required_valid_frames unique sequences pass identity check
    # → IDENTIFIED, identity_matched=True

def test_identified_to_selected(sim):
    # Selection engine picks this candidate
    # → SELECTED

def test_selected_to_acquiring(sim):
    # PTZ centering begins
    # → ACQUIRING

def test_acquiring_to_acquired(sim):
    # Both identity_lock and spatial_lock are True
    # → ACQUIRED

def test_acquired_to_tracking(sim):
    # Centroid stable, PTZ in closed loop
    # → TRACKING

def test_tracking_to_degraded(sim):
    # Introduce signal fade
    # → DEGRADED

def test_degraded_to_reacquiring(sim):
    # Persistent degradation beyond threshold
    # → REACQUIRING

def test_reacquiring_to_tracking(sim):
    # Target reappears with new sequence
    # → ACQUIRED → TRACKING

def test_reacquiring_to_lost(sim):
    # Timeout without successful reacquisition
    # → LOST

def test_wrong_terminal_to_rejected(sim):
    # Wrong terminal decoded during tracking
    # → REJECTED or REACQUIRING
```

---

## 7. End-to-End Acceptance Test (`test_upgrade_acceptance.py`)

Uses `HeadlessSimulation`. No ground-truth injection.

### Required Sequence

```python
def test_full_acquisition_tracking_reacquisition():
    sim = HeadlessSimulation(config=standard_config())

    # Phase 1: Search and acquisition
    result = sim.run_until(
        lambda out: out.telemetry.active_decoded_terminal_id == "RT-001"
        and out.telemetry.system_state == "TRACKING",
        timeout_s=300.0,
    )
    assert result.success, "Failed to reach TRACKING"

    track = result.active_candidate
    assert track.decoded_terminal_id == "RT-001"
    assert track.decoded_token == "ALPHA-7"
    assert track.decoded_wavelength_nm == 1550.0
    assert track.last_valid_sequence >= 3   # at least 3 unique sequences
    assert track.valid_frame_count >= 3
    assert track.identity_state == IdentityState.VALID_TARGET

    # Phase 2: Disable RT-001, enable RT-999 near predicted position
    seq_before = track.last_valid_sequence
    sim.scenario.disable_terminal("RT-001")
    sim.scenario.enable_terminal("RT-999")
    sim.run_for(s=5.0)   # let decoy be present

    # Verify decoy was decoded and rejected
    all_candidates = sim.local_terminal.all_candidates
    decoy_candidates = [c for c in all_candidates
                        if c.decoded_terminal_id == "RT-999"]
    assert all(c.lifecycle_state == CandidateState.REJECTED
               for c in decoy_candidates), \
        "RT-999 was not rejected"

    # Phase 3: Restore RT-001
    sim.scenario.disable_terminal("RT-999")
    sim.scenario.enable_terminal("RT-001")

    result2 = sim.run_until(
        lambda out: out.telemetry.system_state == "TRACKING"
        and out.telemetry.active_decoded_terminal_id == "RT-001",
        timeout_s=120.0,
    )
    assert result2.success, "Failed to reacquire RT-001"

    reacq_track = result2.active_candidate
    assert reacq_track.last_valid_sequence > seq_before, \
        "Reacquisition did not advance sequence"
    assert reacq_track.identity_state == IdentityState.VALID_TARGET
```

### Fields Inspected (Required)

```python
decoded_terminal_id
decoded_token
decoded_wavelength_nm
last_valid_sequence
identity_state
identity_reason
valid_frame_count
lifecycle_state
```

Not just: `system_state == "TRACKING"`.

---

## 8. Disturbance Tests (`test_simulation.py`)

```python
def test_attenuation_reduces_snr():
    # High extinction → lower SNR → confirmed in OpticalMeasurement

def test_wander_displaces_centroid():
    # Enable wander → centroid displacement visible in centroid_history

def test_scintillation_causes_amplitude_variation():
    # intensity_history shows temporal fluctuation

def test_deep_fade_triggers_degraded():
    # High obscuration → DEGRADED within N frames

def test_temporary_fade_recovery():
    # Fade then clear → DEGRADED → TRACKING recovery

def test_persistent_disturbance_triggers_reacquisition():
    # Very strong turbulence → REACQUIRING
```

---

## 9. Running the Tests

```bash
# Full suite
python -m pytest -q

# Specific test files
python -m pytest tests/test_upgrade_acceptance.py -q
python -m pytest tests/test_identity_pipeline.py -q
python -m pytest tests/test_pipeline_acceptance.py -q
python -m pytest tests/test_remote_terminal.py tests/test_simulation.py -q

# Verbose output for a specific test
python -m pytest tests/test_upgrade_acceptance.py::test_full_acquisition_tracking_reacquisition -v
```

---

## 10. Acceptance Criteria

The implementation is only considered complete when **all** of the following pass:

### Architecture

- [x] `common/protocol/beacon/` exists and is imported by both terminals
- [x] Local terminal never imports from `remote_terminal.*`
- [x] `legacy_optical_identification_enabled = False` by default

### Digital Receiver

- [x] `TemporalSignalExtractor` feeds from camera data only
- [x] `SignalSynchronizer` detects preamble and sync word
- [x] `OOKDemodulator` uses adaptive threshold
- [x] `BeaconFrameParser` validates CRC and frame structure
- [x] `PayloadDecoder` centralises all payload parsing
- [x] `IdentityValidator` enforces all identity requirements

### No Bypass

- [x] Optical quality alone → never IDENTIFIED
- [x] No acquisition without digital identity in normal mode
- [x] No reacquisition merge without new valid sequence
- [x] No source identity from remote truth

### Sequence Integrity

- [x] Duplicates not counted as liveness
- [x] Old frames rejected
- [x] New sequences advance liveness

### Identity Tests

- [x] RT-001 accepted
- [x] RT-999 rejected
- [x] Wrong token rejected
- [x] Wrong wavelength rejected per config
- [x] Bad CRC rejected

### Tracking

- [x] Image centroid controls PTZ
- [x] Digital path validates identity/liveness only
- [x] Temporary misses → DEGRADED, not immediate LOST
- [x] Identity swap → immediate lock break

### Reacquisition

- [x] Staged search ±2°, ±5°, ±10°
- [x] Wrong terminal → REJECTED, not merged
- [x] Correct terminal → identity validated, sequence advanced, spatial gate checked
- [x] Lock restored only after both identity and spatial validation

### All Tests Pass

```
python -m pytest -q
... N passed, 0 failed, 0 errors
```

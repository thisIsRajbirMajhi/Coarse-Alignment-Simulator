# Engineering Technical Report

**Document Type**: Engineering Design & Implementation Report  
**Project**: Coarse-Alignment-Simulator  
**Version**: 2.0 (Phase-2 Digital Beacon Architecture)  
**Classification**: Internal Technical Reference  

---

## Executive Summary

The Coarse-Alignment-Simulator is a physics-based, end-to-end simulation of a Free-Space Optical (FSO) communications link. It models the complete chain from remote terminal optical transmission through atmospheric propagation to camera-based acquisition and tracking at a local terminal receiver.

Phase 2 of this project introduces a **full digital beacon receiver pipeline** that replaces the previous optical-only identification approach. The receiver now performs real signal synchronisation, OOK demodulation, frame parsing, CRC checking, payload decoding, and cryptographic token validation — all from camera-derived intensity measurements alone, without access to any ground truth from the remote terminal.

This report documents the design decisions, implementation architecture, and key invariants of the Phase-2 system.

---

## 1. Problem Statement

### 1.1 Original Architecture Limitations

The Phase-1 implementation suffered from several critical deficiencies:

1. **Optical-only identification**: Candidates could be promoted to IDENTIFIED status based on optical signature scores alone, without any digital decoding. This made the system vulnerable to false identification of unrelated bright objects.

2. **Ground-truth leakage**: Parts of the codebase accessed `RemoteTerminal` attributes — position, ID, or transmitted bits — from within the local terminal processing pipeline. This is physically impossible in a real system.

3. **Non-streaming decoder**: The `FrameDecoder` repeatedly re-fed the entire accumulated history into its bit buffer each call, causing the same old samples to be counted multiple times and confounding synchronisation state.

4. **Timing incoherence**: The JSON payload format was too large for the configured chip rate and history buffer. A 200-byte JSON frame at 8 chips/second would take ~200 seconds to transmit — far exceeding the typical ~96-frame camera history.

5. **Scattered payload parsing**: Payload format knowledge was duplicated across `system.py`, `identity_matcher.py`, `frame_decoder.py`, and `telemetry_mgr.py`.

6. **Wrong architecture for protocol sharing**: The remote terminal's beacon encoder imported from `local_terminal.beacon_frame`, which is architecturally backwards.

### 1.2 Phase-2 Requirements

Phase 2 mandates:

- A neutral shared protocol package (`common/protocol/beacon/`) used by both terminals.
- Compact binary payload replacing JSON on the wire.
- A genuinely streaming, stateful, per-candidate frame decoder.
- Real signal synchronisation (preamble/sync word detection via matched filtering).
- Real OOK demodulation (adaptive threshold from local signal statistics).
- Frame parsing with full CRC-8 validation.
- Centralised `PayloadDecoder` with typed output `DecodedPayload`.
- `IdentityValidator` enforcing all identity conditions.
- Dual-lock acquisition: identity lock AND spatial lock.
- Identity-gated reacquisition with new-sequence requirement.
- Strict prohibition on ground-truth use.

---

## 2. System Architecture

### 2.1 The Two-Path Model

The fundamental architectural insight of Phase 2 is the clean separation of two parallel information channels:

```
┌──────────────────────────────────────────────────────────────────┐
│  OPTICAL PATH                                                    │
│  Camera pixels → Blob detection → Centroid → Kalman filter       │
│                                                 → PTZ control    │
│  (answers: WHERE is the target?)                                 │
└──────────────────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────────────────┐
│  DIGITAL BEACON PATH                                             │
│  Intensity history → Sync → Demodulation → Frame → Identity      │
│                                                 → Liveness       │
│  (answers: WHO is the target?)                                   │
└──────────────────────────────────────────────────────────────────┘

These two paths meet at:

CandidateLifecycle ← makes IDENTIFIED / ACQUIRED / TRACKING decisions
AcquisitionManager ← requires both locks simultaneously
TrackingController ← uses optical for PTZ; digital for identity monitoring
```

Neither path substitutes for the other. The PTZ is never commanded from decoded payload contents. Identity is never assumed from optical quality.

### 2.2 Shared Protocol Package

```
common/
└── protocol/
    └── beacon/
        ├── __init__.py       # exports + terminal_id_to_byte()
        ├── payload.py        # BeaconPayload, DecodedPayload, PayloadCodec
        ├── frame.py          # BeaconFrame, BeaconFrameEncoder, BeaconFrameParser
        ├── crc.py            # CRC8, CRCValidator
        └── ook.py            # OOKEncoder, SynchronizationResult
```

Both the remote terminal encoder and the local terminal decoder `import` from this package. No protocol definitions exist in either terminal's private modules.

### 2.3 Streaming Decoder Design

The critical design decision for the `FrameDecoder` is that it is **stateful per observation_id** and **streaming**:

```python
# Internal state per candidate:
last_processed_sample_index: int   # monotonically increasing
```

On each call:
```python
new_samples = signal.normalized_signal[state.last_processed_sample_index:]
state.last_processed_sample_index = len(signal.normalized_signal)
# only process new_samples — never re-feed old history
```

This prevents the Phase-1 bug where the accumulation of old samples produced false synchronisation hits and spurious bit sequences.

---

## 3. Wire Protocol Specification

### 3.1 Frame Structure

```
Byte offset  Field               Size  Value
───────────  ──────────────────  ────  ─────────────────────────────────────
0–7          PREAMBLE            8B    0xAA × 8 (alternating 10101010 bits)
8–9          SYNC                2B    0xEB 0x90
10           PROTOCOL_VERSION    1B    uint8, currently 0x01
11           MESSAGE_TYPE        1B    uint8, BEACON = 0x01
12           PAYLOAD_LENGTH      1B    uint8, length of PAYLOAD in bytes
13–(12+N)    PAYLOAD             NB    compact binary (see §3.2)
13+N         CRC-8               1B    CRC-8/MAXIM over bytes 0–(12+N)
```

**Total overhead** (excluding payload): 14 bytes = 112 bits.

### 3.2 Compact Payload Format

```
Offset  Field         Type    Size       Description
──────  ────────────  ──────  ─────────  ─────────────────────────────────────────
0       tid_len       uint8   1 byte     Length of terminal_id string in bytes
1       tid           bytes   tid_len    UTF-8 encoded terminal ID (e.g. "RT-001")
1+L1    token_len     uint8   1 byte     Length of token string
2+L1    token         bytes   token_len  UTF-8 encoded token (e.g. "ALPHA-7")
2+L1+L2 wavelength   uint16  2 bytes    Wavelength in nm, big-endian
4+L1+L2 sequence     uint32  4 bytes    Sequence number, big-endian
```

Example (`tid="RT-001"`, `token="ALPHA-7"`, `wl=1550`, `seq=42`):

```
06            # tid_len = 6
52 54 2D 30 30 31   # "RT-001"
07            # token_len = 7
41 4C 50 48 41 2D 37  # "ALPHA-7"
06 0E         # wavelength = 1550 (0x060E)
00 00 00 2A   # sequence = 42
```

Payload total: `1 + 6 + 1 + 7 + 2 + 4 = 21 bytes`.

Total frame: `14 (overhead) + 21 (payload) = 35 bytes = 280 bits`.

### 3.3 OOK Encoding

NRZ (Non-Return-to-Zero) at `chip_rate_hz = 12.0 Hz`:

```
bit = 1  →  optical intensity = I_on
bit = 0  →  optical intensity = I_off   (near dark current)
```

Frame duration at 12 chips/s:
```
frame_duration_s = 280 bits / 12.0 Hz ≈ 23.3 seconds
```

### 3.4 CRC-8 Specification

- Polynomial: CRC-8/MAXIM (Dallas/Maxim), `0x31`
- Initial value: `0x00`
- Input reflection: Yes
- Output reflection: Yes
- XOR out: `0x00`

---

## 4. Signal Processing Design

### 4.1 Temporal Signal Extraction

The signal extractor processes the bounded deque of per-frame intensity measurements:

**Background estimation**: 10th percentile of intensity history. Using a low percentile avoids bias from ON chips (which inflate the mean).

**Normalisation**: 90th–10th percentile range is used as the signal span. This is robust against outliers from scintillation spikes.

**SNR estimation**: Variance of the signal divided by variance of the high-frequency residual after low-pass filtering.

**Modulation depth**: `(P90 - P10) / P90`. Values < 0.2 indicate insufficient modulation for reliable decoding.

### 4.2 Preamble Detection

Matched filtering using a template generated at the nominal chip rate:

```
template = alternating [+1, -1, +1, -1, ...]  (64 bits = 8 bytes × 8 bits)
at spacing = camera_fps / chip_rate_hz samples per bit
```

Cross-correlation with the normalised signal produces peaks at preamble locations. Peaks above `sync_confidence_threshold = 0.6` are candidates.

**Chip rate estimation**: Inter-zero-crossing spacing of the preamble autocorrelation, averaged over all crossings.

### 4.3 OOK Demodulation

For each chip interval:
1. Extract the signal values within the chip window.
2. Take the local median as the chip value estimate.
3. Compare to the global adaptive threshold: `threshold = (P10 + P90) / 2`.
4. Assign: `bit = 1 if median > threshold else 0`.
5. Confidence: `|median - threshold| / (P90 - P10)`.

This adaptive approach handles:
- Intensity drift from slow atmospheric changes.
- Scintillation-induced amplitude variations.
- Attenuation without reconfiguration.

### 4.4 Why No Fixed Threshold

A fixed threshold fails whenever:
- Attenuation changes the signal level.
- Background estimation drifts.
- Scintillation raises or lowers the signal mean.

The adaptive threshold tracks the actual received signal statistics, making it self-calibrating.

---

## 5. Identity Validation Design

### 5.1 Complete Validation Chain

The validation is ordered so that computationally cheap or most-discriminating checks happen first:

```
1. Frame detected?                    → early exit on no data
2. Sync achieved?                     → early exit on sync failure
3. CRC valid?                         → early exit on corruption
4. Protocol version accepted?         → reject firmware-mismatched transmitters
5. Message type accepted?             → reject non-beacon messages
6. Payload parseable?                 → reject malformed payloads
7. Terminal ID matches?               → reject wrong targets (most common failure)
8. Token matches?                     → reject impersonators
9. Wavelength within tolerance?       → reject wrong-band sources
10. Sequence advances?                → reject replays and duplicates
11. Decode confidence sufficient?     → reject uncertain decodes
12. All checks → VALID_TARGET
```

### 5.2 Sequence Semantics

This is the most subtle design decision in the identity system:

- `seq_new > seq_old` → valid new liveness (`is_new_liveness = True`)
- `seq_new == seq_old` → `DUPLICATE_SEQUENCE` — NOT counted as liveness
- `seq_new < seq_old` → `OLD_SEQUENCE` — NOT counted
- `seq_new - seq_old > max_sequence_gap` → `SEQUENCE_DISCONTINUITY` (configurable)

**Why this matters**: Without this rule, a channel echo of sequence 100 (received twice) would count as two separate valid frames, potentially completing the `required_valid_frames = 3` count with only one real transmission. A replay attack in a real system would similarly be blocked.

### 5.3 Token Strictness

The empty-token edge case is explicitly handled:

```
config.expected_token = "ALPHA-7"
decoded_token = ""
→ WRONG_TOKEN (not "no requirement")
```

An empty decoded token is not equivalent to "the transmitter has no token". It is a parsing failure or a transmitter that failed to include a token. Both are invalid.

### 5.4 Dual-Lock Acquisition

The dual-lock requirement prevents acquisition of:
- A target that is optically stable but digitally unverified.
- A target that is digitally verified but spatially unstable (moving rapidly, out of FOV).

```python
acquired = identity_lock AND spatial_lock
# Not: identity_lock OR spatial_lock
# Not: spatial_lock alone (legacy mode only)
```

The identity lock also requires persistence — not just one valid frame, but `required_valid_frames` unique valid frames. This provides robustness against lucky CRC passes on corrupted data.

---

## 6. Reacquisition Design

### 6.1 Identity Gate is Non-Negotiable

The `can_merge_reacquisition` function embodies the core security/correctness property of the reacquisition system:

| Condition | Rationale |
|-----------|-----------|
| Old track must have been identified | Cannot restore a lock that was never established |
| New candidate must be identified | Cannot restore lock without new digital proof |
| Terminal IDs must match exactly | Prevents RT-999 from being mistaken for RT-001 |
| New sequence > old sequence | Prevents replay — duplicate seqs are not re-acquisition |
| Spatial gate | Prevents wild associations to distant objects |

Without all five conditions, reacquisition is refused and the search continues.

### 6.2 Staged Search Rationale

The ±2° / ±5° / ±10° stages reflect realistic platform dynamics:

- **±2°** covers short-term atmospheric wander and minor manoeuvres. Most transient losses are recovered here.
- **±5°** covers moderate slew offsets and medium-duration losses.
- **±10°** covers major attitude excursions. If not found here, the target is genuinely lost.

Each stage has an independent timeout. The search volume expands progressively to avoid wasting time scanning far afield when the target is probably nearby.

---

## 7. Key Design Decisions and Rationale

### 7.1 Compact Binary Protocol vs. JSON

**Decision**: Compact binary payload is the default; JSON is optional debug-only.

**Rationale**: At 12 chips/second (NRZ), a 200-byte JSON payload would require `200 × 8 / 12 = 133 seconds` per frame. At 30 fps camera, a 2000-frame history provides only `66 seconds` — insufficient for even one complete frame. The compact binary payload of ~21 bytes requires only `21 × 8 / 12 ≈ 14 seconds` per frame, fitting comfortably within a 2000-frame history.

### 7.2 Preamble Design (0xAA × 8)

**Decision**: 8 bytes of `0xAA` (alternating 10101010) as the preamble.

**Rationale**: 
- Provides 64 transitions for accurate chip rate estimation.
- The alternating pattern has a strong autocorrelation peak at lag=0 and rapid roll-off, enabling unambiguous detection.
- 8 bytes provides enough correlation gain to detect the preamble even at SNR ≈ 3 dB.

### 7.3 CRC-8/MAXIM

**Decision**: CRC-8/MAXIM polynomial `0x31`.

**Rationale**:
- Single-byte CRC overhead is minimal relative to the compact payload.
- CRC-8/MAXIM is well-characterised and detects all single-bit errors plus most multi-bit errors.
- The Hamming distance of 4 for payloads up to 119 bits is sufficient for the frame sizes used here.

### 7.4 Kalman Filter with Constant-Acceleration Model

**Decision**: 6-state Kalman filter `[cx, cy, vx, vy, ax, ay]`.

**Rationale**: 
- Pure constant-velocity (`[cx, cy, vx, vy]`) cannot predict through smooth trajectory changes.
- Constant-acceleration adds one derivative and handles manoeuvres during reacquisition intervals.
- Higher-order models add computational cost without proportional benefit at 30 fps.

### 7.5 History Buffer Sizing

**Decision**: History size is computed from protocol parameters, not hard-coded.

**Formula**:
```
required_history_s = 2 × frame_duration_s × safety_factor
required_samples = ceil(required_history_s × camera_fps)
```

**Rationale**: Hard-coded history sizes become invalid whenever chip rate, payload size, or camera fps change. Computing the requirement from actual parameters guarantees the buffer is always sufficient, and validation at config load time catches mismatches early.

---

## 8. Known Limitations and Open Issues

### 8.1 Single Active Target

The current implementation supports one active target track at a time. The selection engine chooses the best candidate; others remain in their respective lifecycle states. Multi-target tracking is not currently implemented.

**Impact**: In scenarios with multiple valid RT-001 transmitters (not typical), only one will be acquired. The other will remain IDENTIFIED but not SELECTED.

### 8.2 Chip Rate Estimation Accuracy

The chip rate estimator works from preamble zero-crossing spacing. At low SNR (< 3 dB), zero-crossing estimation is noisy and the estimated chip rate may drift ±10–15% from truth.

**Impact**: Demodulation quality degrades when chip rate estimate is inaccurate. The OOK adaptive threshold partially compensates, but very inaccurate chip timing causes systematic bit errors.

**Mitigation**: Use a larger preamble (> 8 bytes) or increase chip rate for better camera-to-chip ratio.

### 8.3 Long Frame Duration at Low Chip Rates

At `chip_rate_hz = 12.0`, a frame takes ~23 seconds. This means:
- A stationary candidate must be in FOV for 46+ seconds before the first identity is decoded.
- During search, if the scan speed is too high, the candidate will exit the FOV before accumulating enough history.

**Mitigation**: Reduce scan speed when a candidate is in TENTATIVE/SIGNAL_DETECTED state, or increase chip rate.

### 8.4 Background Star Rejection

The current star rejection relies on a static catalogue or learned-background approach. Fast-moving platforms may shift the star field faster than the learning rate, causing transient false detections.

**Mitigation**: Increase `temporal_avg_frames` in `FrameProcessor` to suppress transient stars.

### 8.5 No Frequency Domain Synchronisation Fallback

The current synchroniser uses only time-domain matched filtering. In very low SNR scenarios, frequency-domain methods (FFT-based chip rate estimation) would be more robust.

**Mitigation**: Planned for Phase 3.

---

## 9. Performance Characteristics

### Typical Acquisition Timeline

| Phase | Duration | Notes |
|-------|----------|-------|
| Search (no candidate) | Variable | Depends on scan pattern and RT position |
| SEEN → TENTATIVE | ~2 frames (~67 ms) | Must persist 2 consecutive frames |
| TENTATIVE → SIGNAL_DETECTED | ~10–30 frames | Modulation depth threshold |
| SIGNAL_DETECTED → DECODING | ~5 frames | History must reach minimum size |
| DECODING → IDENTIFIED | 1–3 frame durations (~23–70 s at 12 Hz) | Need `required_valid_frames` unique sequences |
| IDENTIFIED → ACQUIRED | ~1–5 s | PTZ centering + dual lock |
| ACQUIRED → TRACKING | ~1–2 s | Centroid stability check |

**Total from search hit to tracking**: typically 30–120 seconds at default 12 Hz chip rate.

To reduce acquisition time: increase `chip_rate_hz` (up to 30 Hz is practical at 30 fps camera).

### Processing Load per Frame (30 fps)

| Component | Operations | CPU Time (est.) |
|-----------|-----------|----------------|
| FrameProcessor | Background estimation (640×480) | ~2 ms |
| CandidateDetector | Connected components | ~1 ms |
| SignalExtractor | Per-candidate statistics (N×1000 samples) | ~0.5 ms/candidate |
| SignalSynchronizer | Cross-correlation (1000-point) | ~2 ms/candidate |
| OOKDemodulator | Per-chip threshold | ~0.5 ms/candidate |
| FrameDecoder | Bit→byte + parse | ~0.1 ms/candidate |
| IdentityValidator | Pure logic | < 0.1 ms/candidate |
| Kalman update | 6×6 matrix ops | < 0.1 ms/candidate |
| PTZ control | PID + actuator | < 0.1 ms |

**Total per frame** (3 candidates): ~10–15 ms → comfortably within 33 ms budget at 30 fps.

---

## 10. Implementation Order (Phase-2 Roadmap)

When implementing Phase 2 from the existing codebase, follow this order to avoid broken foundations:

```
 1. Audit existing beacon code locations
 2. Create common/protocol/beacon/ package
 3. Implement compact binary PayloadCodec
 4. Implement BeaconFrameEncoder (PREAMBLE+SYNC+header+payload+CRC)
 5. Implement CRC-8/MAXIM
 6. Integrate BeaconConfig into RemoteTerminalConfig
 7. Integrate TargetPayloadConfig into LocalTerminalConfig
 8. Correct remote BeaconEncoder to use shared protocol
 9. Compute and validate temporal history size
10. Rewrite TemporalSignalExtractor as proper streaming input
11. Implement SignalSynchronizer (matched filter, chip rate estimation)
12. Implement OOKDemodulator (adaptive threshold)
13. Make FrameDecoder stateful-streaming (last_processed_index)
14. Implement BeaconFrameParser with all rejection conditions
15. Implement PayloadDecoder (centralised compact binary parse)
16. Implement IdentityValidator (complete 12-step validation chain)
17. Remove optical-only IDENTIFIED transition in normal mode
18. Implement dual-lock acquisition (identity_lock AND spatial_lock)
19. Implement is_new_frame / sequence advancement tracking
20. Implement continuous identity monitoring during tracking
21. Implement identity-gated can_merge_reacquisition
22. Correct telemetry to expose all digital fields
23. Rewrite tests to prove actual digital decoding (no shortcut assertions)
24. Run full test suite and fix regressions
```

---

## 11. Acceptance Verification

The implementation is complete only when the following end-to-end flow succeeds without any ground-truth shortcut:

```
RemoteTerminal → OOK optical beam
→ Atmospheric disturbance
→ Camera rendering (no RT ground truth in CameraFrame)
→ LocalTerminal.step(camera_frame)
   → TemporalSignalExtractor (from pixel intensity only)
   → SignalSynchronizer (finds preamble and sync word)
   → OOKDemodulator (recovers bits from camera-derived signal)
   → BeaconFrameParser (validates frame structure + CRC)
   → PayloadDecoder (extracts terminal_id, token, wavelength, sequence)
   → IdentityValidator (all 12 conditions checked)
   → CandidateLifecycle transitions: SEEN → … → IDENTIFIED → ACQUIRED → TRACKING
→ Reacquisition scenario:
   RT-001 disappears → REACQUIRING
   RT-999 appears → decoded, REJECTED (WRONG_TERMINAL)
   RT-001 reappears with new sequence → identity gate passes → TRACKING
```

All field values must be verified:
- `decoded_terminal_id == "RT-001"`
- `decoded_token == "ALPHA-7"`
- `decoded_wavelength_nm == 1550.0`
- `last_valid_sequence` is advancing
- `identity_state == VALID_TARGET`
- `lifecycle_state == TRACKING`
- RT-999 candidate `lifecycle_state == REJECTED`

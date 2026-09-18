You are working on the existing repository:

`https://github.com/thisIsRajbirMajhi/Coarse-Alignment-Simulator`

Work directly on the existing architecture. **Do not rebuild the simulator from scratch. Do not replace the physical simulation, disturbance/channel model, camera model, PTZ mechanics, search system, GUI, or headless simulation unless a specific integration fix requires it.**

Your task is to finish and correct the current **search → detection → signal acquisition → digital beacon decoding → identity validation → acquisition → tracking → degradation → reacquisition** architecture.

The current repository already contains a substantial partial implementation. Your job is to **audit the current code first, then modify it to satisfy the requirements below exactly**.

---

# 1. PRIMARY OBJECTIVE

The final system must operate as:

```text
REMOTE TERMINAL
    ↓
BEAM GENERATION
    ↓
OPTICAL PROPAGATION
    ↓
DISTURBANCE / CHANNEL
    ↓
CAMERA / SENSOR
    ↓
LOCAL TERMINAL
```

The local terminal must independently perform:

```text
CameraFrame
    ↓
FrameProcessor
    ↓
CandidateDetector
    ↓
CandidateAssociation
    ↓
OpticalMeasurement
    ↓
TemporalSignalExtractor
    ↓
SignalSynchronizer
    ↓
OOKDemodulator
    ↓
BeaconFrameParser
    ↓
PayloadDecoder
    ↓
IdentityValidator
    ↓
CandidateLifecycle
    ↓
Candidate Selection
    ↓
Dual-Lock Acquisition
    ↓
Image-Based Tracking
    ↓
Identity / Liveness Monitoring
    ↓
Degradation
    ↓
Identity-Gated Reacquisition
```

The receiver must not use remote-terminal ground truth for perception or identity.

---

# 2. ABSOLUTE IMAGE-ONLY BOUNDARY

The local terminal may use only:

```text
CameraFrame
local PTZ pose
local PTZ velocity
local local configuration
local history/state
```

The local terminal must NEVER use:

```text
RemoteTerminal object
RemoteTerminal.pose
RemoteTerminal.id
remote truth position
remote truth geometry
remote scenario state
remote link state
original transmitted bitstream
original transmitted payload
```

to perform perception, identity, acquisition, tracking, or reacquisition.

Search and tracking must work entirely from camera observations.

If any old API still accepts something such as:

```python
remote_scenario=...
```

remove it or fail closed.

---

# 3. OBSERVATION IDENTITY VS SOURCE IDENTITY

Preserve the strict distinction:

```text
observation_id = BEACON-001
decoded_terminal_id = RT-001
```

`BEACON-N` is generated locally by the receiver and belongs to a local candidate track.

`RT-001` comes only from a successfully decoded beacon payload.

Never replace an observation ID with the remote terminal ID.

---

# 4. REMOVE THE CURRENT OPTICAL-ONLY IDENTITY FALLBACK

The current code still has a legacy path in which the candidate can become identified from optical signature information when digital decoding has not succeeded.

This is not allowed for the new architecture.

Add an explicit configuration:

```python
legacy_optical_identification_enabled: bool = False
```

Default must be:

```text
False
```

The normal path must require digital identity.

Therefore:

```text
visual match only
    ≠
identity
```

A candidate can be:

```text
SEEN
TENTATIVE
SIGNAL_DETECTED
DECODING
IDENTITY_UNKNOWN
```

without digital identity.

It may become:

```text
IDENTIFIED
```

only after successful framed-beacon decoding and identity validation.

Optical signature may be used for:

```text
candidate quality
plausibility
search prioritization
association
acquisition spatial quality
tracking quality
false alarm rejection
```

but never as authoritative identity.

Legacy optical identification may exist only behind the explicit legacy configuration flag.

---

# 5. CREATE A PROPER SHARED BEACON PROTOCOL PACKAGE

The beacon protocol must not live under `local_terminal`.

The current remote encoder importing beacon definitions from `local_terminal` is architecturally incorrect.

Create a neutral shared package, for example:

```text
common/
    protocol/
        beacon/
            __init__.py
            payload.py
            frame.py
            crc.py
            ook.py
```

or an equivalent shared location.

Both sides must depend on this shared protocol:

```text
remote_terminal → shared beacon protocol
local_terminal  → shared beacon protocol
```

The protocol package must contain:

```text
BeaconPayload
BeaconFrame
BeaconFrameEncoder
PayloadCodec
PayloadDecoder
CRC8
CRCValidator
OOKEncoder
BeaconDecodeResult
```

Do not duplicate protocol definitions between local and remote modules.

---

# 6. FRAME FORMAT

Implement a deterministic binary framed beacon:

```text
PREAMBLE
SYNC
PROTOCOL_VERSION
MESSAGE_TYPE
PAYLOAD_LENGTH
PAYLOAD
CRC-8
```

The framing must be deterministic and configurable.

Default protocol:

```text
protocol_version = 1
message_type = BEACON
```

The parser must reject:

```text
invalid preamble
invalid sync
unsupported protocol version
unsupported message type
invalid length
truncated frame
CRC mismatch
malformed payload
```

Return structured failure information.

---

# 7. USE A COMPACT DEFAULT PAYLOAD

Do NOT use JSON as the normal simulation wire payload.

The current JSON payload is too long for the configured chip rate and camera history.

Use a deterministic compact binary payload as the normal wire format.

Default logical fields remain:

```text
tid
token
wl
seq
```

Use a structure equivalent to:

```text
tid_len      : uint8
tid          : UTF-8 bytes
token_len    : uint8
token        : UTF-8 bytes
wavelength   : uint16
sequence     : uint32
```

For example:

```text
tid = "RT-001"
token = "ALPHA-7"
wavelength = 1550
sequence = N
```

Keep JSON only as an optional debug/reference codec if useful.

The default runtime codec must be compact.

---

# 8. REMOTE BEACON CONFIGURATION

Make the remote configuration explicitly own the beacon protocol parameters.

`remote_terminal.config.BeaconConfig` must contain first-class fields such as:

```python
enabled: bool
token: str
wavelength_nm: float
protocol_version: int
message_type: int
payload_codec: str
chip_rate_hz: float
```

Do not use the old:

```text
identification_code
```

as the primary protocol configuration.

You may retain it only for compatibility/legacy mode.

The remote encoder must be built directly from the configured beacon object.

Do not silently inject protocol values from unrelated defaults.

---

# 9. REMOTE OOK TRANSMISSION

The remote pipeline must be explicit:

```text
BeaconPayload
    ↓
Payload serialization
    ↓
BeaconFrame
    ↓
CRC
    ↓
bits
    ↓
OOK chips
    ↓
optical intensity
```

The renderer must continue to consume the resulting intensity modulation.

Do not redesign the optical renderer unless necessary.

The receiver must NEVER access the original transmitted chips/bits.

---

# 10. BEACON TIMING MUST BE PHYSICALLY CONSISTENT

The current implementation has an incompatibility:

```text
long JSON frame
+
8 chips/sec
+
~96 camera samples of history
```

This cannot work.

Replace it with a compact payload and establish a coherent timing configuration.

Use an initial debug configuration around:

```text
chip_rate_hz = 12.0
camera_rate ≈ 30 Hz
history ≈ 900 camera samples
```

or another mathematically justified configuration.

The important invariant is:

```text
receiver history duration
>
at least 2 complete beacon frame durations
```

This must be calculated from the actual configured:

```text
frame length
chip rate
camera sampling rate
```

Do not hard-code an unrelated history length.

Add validation so invalid timing configurations are rejected or automatically corrected.

---

# 11. LOCAL TARGET PAYLOAD CONFIG MUST BE FIRST-CLASS CONFIGURATION

Make the target payload configuration an actual field in `LocalTerminalConfig`.

Do NOT attach it dynamically at runtime.

Use something equivalent to:

```python
@dataclass
class TargetPayloadConfig:
    expected_terminal_id: str = "RT-001"
    expected_token: str = "ALPHA-7"
    expected_wavelength_nm: float = 1550
    expected_protocol_version: int = 1
    expected_message_type: int = 1

    required_valid_frames: int = 3

    sequence_validation_enabled: bool = True
    wavelength_validation_enabled: bool = True

    max_sequence_gap: int = 0
    identity_timeout_s: float = ...
    max_identity_fail_streak: int = ...
```

Then:

```python
LocalTerminalConfig(
    ...
    target_payload=TargetPayloadConfig(...)
)
```

must work through:

```text
constructor
validation
from_dict
to_dict
configuration reload
headless simulation
GUI configuration
```

---

# 12. TEMPORAL SIGNAL EXTRACTOR

For each candidate maintain:

```text
timestamp history
intensity history
centroid history
```

The signal extractor must produce:

```text
raw intensity
background estimate
background-subtracted signal
normalized signal
SNR
modulation depth
sample timestamps
signal quality
```

Do not read remote transmission data.

All signal information must come from the image observations.

Increase history size sufficiently for the full framed beacon.

---

# 13. REAL STREAMING DECODER

This is a critical requirement.

The current `FrameDecoder` reuses the full accumulated history and can repeatedly feed old observations into its internal bit buffer.

Fix this.

The decoder must behave like a streaming receiver.

Track the last processed sample index/time.

Only new signal samples may be appended to the decoder state.

Do not repeatedly append old history.

Maintain state per `observation_id`:

```text
last_processed_sample_index
sync state
frame start
chip timing
demodulated bits
parser state
last valid sequence
last valid frame
attempt counters
failure counters
```

---

# 14. REAL SIGNAL SYNCHRONIZATION

The existing `SignalSynchronizer` must become part of the actual decode path.

Do NOT merely leave it as an unused helper.

It must process signal samples to detect:

```text
PREAMBLE
SYNC
```

and produce:

```python
SynchronizationResult(
    synchronized: bool,
    frame_start: int,
    chip_rate_hz: float,
    confidence: float,
    reason: str,
)
```

It must tolerate:

```text
noise
attenuation
moderate sample loss
intensity variation
wander
scintillation
partial frame corruption
```

It must not immediately synchronize on a weak false match.

Use the best-confidence candidate within the search window.

---

# 15. REAL OOK DEMODULATION

The existing `OOKDemodulator` must be part of the live receiver path.

Required input:

```text
temporal intensity samples
+
timing/synchronization result
```

Required output:

```text
recovered bits
bit confidence
chip quality
threshold
```

Use adaptive local statistics such as percentiles, background, or equivalent robust thresholds.

Do not depend on a single fixed threshold.

Do not artificially force successful decoding.

A damaged optical signal must naturally be capable of causing:

```text
no synchronization
invalid bits
truncated frame
CRC failure
invalid payload
```

Do NOT inject random bit errors as part of normal receiver operation.

If synthetic BER injection is useful for unit testing, keep it in the test harness only.

---

# 16. FRAME PARSER

The frame parser must receive recovered bits/bytes from the receiver.

It must produce structured results:

```python
BeaconDecodeResult(
    frame_detected=...,
    synchronized=...,
    valid_crc=...,
    protocol_version=...,
    message_type=...,
    payload_length=...,
    payload=...,
    decode_confidence=...,
    reason=...,
    is_new_frame=...,
)
```

`is_new_frame` is mandatory.

---

# 17. PAYLOAD DECODER

Centralize payload parsing.

Create:

```text
PayloadDecoder
```

with output:

```python
DecodedPayload(
    terminal_id="RT-001",
    token="ALPHA-7",
    wavelength_nm=1550,
    sequence_number=12345,
)
```

Do not scatter payload-specific parsing across:

```text
system.py
identity matcher
frame decoder
telemetry
```

Payload format knowledge must be centralized.

---

# 18. UNIQUE FRAME / SEQUENCE SEMANTICS

This is mandatory.

The receiver must distinguish:

```text
new sequence
duplicate sequence
old sequence
large sequence jump
```

Use canonical identity status:

```text
VALID_TARGET
WRONG_TERMINAL
WRONG_TOKEN
WRONG_PROTOCOL
WAVELENGTH_MISMATCH
INVALID_SEQUENCE
UNKNOWN
```

Detailed reason codes may additionally be:

```text
DUPLICATE_SEQUENCE
OLD_SEQUENCE
SEQUENCE_DISCONTINUITY
CRC_FAILURE
LOW_CONFIDENCE
...
```

But the canonical status must include:

```text
INVALID_SEQUENCE
```

A duplicate frame must NOT count as new liveness.

A repeated detection of sequence 100 must not increment valid-frame persistence.

Only a new valid sequence may strengthen liveness.

---

# 19. IDENTITY VALIDATOR

Implement:

```text
DecodedPayload
      ↓
IdentityValidator
      ↓
IdentityDecision
```

Identity must require:

```text
valid frame
+
CRC valid
+
accepted protocol
+
accepted message type
+
terminal ID matches
+
token matches
+
wavelength valid
+
sequence valid
+
required unique valid-frame persistence
```

The token requirement is strict.

If the configured expected token is non-empty:

```text
missing token
≠
valid
```

Do not accept an empty decoded token as equivalent to no token requirement.

---

# 20. WAVELENGTH VALIDATION MUST USE REAL OPTICAL MEASUREMENT

Use three values where possible:

```text
local expected wavelength
decoded beacon wavelength
measured optical wavelength
```

The decision must distinguish:

```text
declared payload wavelength
vs
local expected wavelength
vs
actual optical measurement
```

The current implementation's pseudo-value:

```text
signature_score * 1550
```

is not acceptable as an optical wavelength estimate.

Use the existing detector/spectral observation machinery.

The candidate track should retain:

```text
measured wavelength
decoded wavelength
wavelength consistency
```

---

# 21. OPTICAL MEASUREMENT MUST BE COMPLETE

Populate `OpticalMeasurement` with actual values:

```text
centroid_x
centroid_y
bounding_box
area
apparent_diameter
peak_intensity
integrated_intensity
background_level
SNR
shape_metrics
spectral_estimate
timestamp
```

Do not fabricate fields from unrelated scores.

The optical measurement is used for candidate quality and control, not source identity.

---

# 22. CANDIDATE LIFECYCLE

Use this lifecycle:

```text
SEEN
 ↓
TENTATIVE
 ↓
SIGNAL_DETECTED
 ↓
DECODING
 ↓
IDENTITY_UNKNOWN
 ↓
IDENTIFIED
 ↓
SELECTED
 ↓
ACQUIRING
 ↓
ACQUIRED
 ↓
TRACKING
 ↓
DEGRADED
 ↓
REACQUIRING
 ↓
TRACKING
```

Failure states:

```text
REJECTED
LOST
EXPIRED
```

Rules:

### SEEN

Visual candidate appears.

### TENTATIVE

Candidate persists.

### SIGNAL_DETECTED

Temporal beacon-like modulation detected.

### DECODING

Frame decoding is being attempted.

### IDENTITY_UNKNOWN

Signal/frame exists but identity has not yet been validated.

### IDENTIFIED

Digital payload matches local target configuration.

### SELECTED

Target candidate chosen for acquisition.

### ACQUIRING

PTZ is centering the candidate.

### ACQUIRED

Both identity and spatial locks are satisfied.

### TRACKING

Stable closed-loop image tracking.

### DEGRADED

Tracking continues but identity/link/optical quality is weakening.

### REACQUIRING

Target is temporarily lost and the receiver searches around prediction.

### REJECTED

Definitively wrong identity/protocol/token/etc.

### LOST

Reacquisition timeout exceeded.

### EXPIRED

Track permanently retired.

---

# 23. NO OPTICAL PROMOTION TO IDENTIFIED

This rule is absolute:

```text
optical quality alone
    → NEVER IDENTIFIED
```

A visually excellent RT-999 candidate must remain rejected if:

```text
expected_terminal_id = RT-001
```

The optical path may say:

```text
high quality
high SNR
good shape
correct spectral appearance
```

but identity must still be:

```text
WRONG_TERMINAL
```

until a valid decoded payload proves otherwise.

---

# 24. ACQUISITION MUST BE TRUE DUAL-LOCK

Acquisition requires:

## Identity lock

```text
valid CRC
correct protocol
correct message type
correct terminal ID
correct token
valid wavelength
new sequence
required number of valid frames
```

## Spatial lock

```text
candidate visible
stable centroid
SNR sufficient
optical quality sufficient
centroid within acquisition window
motion plausible
```

Then:

```text
IDENTITY LOCK + SPATIAL LOCK = ACQUIRED
```

Do not implement this as:

```python
if require_identity_match:
    ...
else:
    acquire
```

for the normal path.

The normal digital-beacon architecture must always require identity.

Only the explicit legacy mode can bypass identity.

---

# 25. ACQUISITION MANAGER CONFIGURATION BUG MUST BE REMOVED

The current implementation contains logic equivalent to:

```python
if require_identity_lock and require_identity_match:
    id_locked = track.identity_matched
else:
    id_locked = True
```

Replace this behavior.

Normal mode must effectively be:

```python
id_locked = bool(track.identity_matched)
```

and spatial lock must be separately evaluated.

The two locks must then be ANDed.

---

# 26. SELECTION RULES

Multiple candidates may exist simultaneously.

Do NOT select:

```text
brightest candidate
highest optical score
nearest candidate
```

solely because of those properties.

Selection priority should be:

```text
correct digital identity
+
valid signal
+
spatial quality
+
tracking quality
```

A bright RT-999 must never outrank a weaker RT-001 after RT-001 has been digitally validated.

Wrong identities should be hard-excluded from acquisition.

---

# 27. TRACKING CONTROL MUST REMAIN IMAGE-BASED

Once acquired, the PTZ controller must use:

```text
camera centroid
filtered position
predicted position
velocity
acceleration
```

The PTZ must NOT move based directly on:

```text
decoded terminal ID
decoded sequence number
payload contents
remote world position
```

Digital beacon information is for:

```text
identity
liveness
frame quality
sequence validity
identity continuity
link health
```

Optical measurements control pointing.

---

# 28. CONTINUOUS IDENTITY VALIDATION DURING TRACKING

Every new valid frame must be validated.

Maintain:

```text
last_valid_sequence
last_valid_frame_time
identity_fail_streak
identity_confidence
```

Behavior:

```text
one missed frame
    → do not immediately lose target

temporary decode failure
    → DEGRADED

persistent failure
    → REACQUIRING
```

Also distinguish:

```text
no new frame
vs
bad new frame
vs
wrong terminal
```

A wrong terminal should be treated much more strongly than a temporary no-data gap.

---

# 29. IDENTITY SWAP MUST BREAK LOCK

Example:

```text
position unchanged
RT-001 → RT-007
```

The receiver must not say:

```text
same candidate → continue tracking
```

It must recognize:

```text
identity mismatch
→ reject candidate
→ drop target identity lock
→ degrade/reacquire
```

The decoded identity is authoritative.

---

# 30. REACQUISITION MUST BE IDENTITY-GATED

The current implementation performs spatial/predictive reacquisition but does not fully enforce identity-gated merging.

Implement explicit logic equivalent to:

```python
def can_merge_reacquisition(old_track, new_track):
    if old_track is None or new_track is None:
        return False

    if not old_track.decoded_terminal_id:
        return False

    if not new_track.identity_matched:
        return False

    if old_track.decoded_terminal_id != new_track.decoded_terminal_id:
        return False

    if new_track.last_valid_sequence <= old_track.last_valid_sequence:
        return False

    spatial_error = distance(
        new_track.measured_position,
        old_track.predicted_position,
    )

    if spatial_error > reacquisition_spatial_gate:
        return False

    return True
```

The exact implementation may differ, but these conditions must exist.

---

# 31. REACQUISITION SEARCH STAGES

Preserve the staged search:

```text
±2°
±5°
±10°
```

around predicted position.

Search strategy may be:

```text
predict
→ local spiral / raster / expanding search
```

but every candidate must pass:

```text
visual candidate
+
signal detection
+
frame synchronization
+
OOK decode
+
valid CRC
+
payload decode
+
correct target identity
+
new sequence
+
spatial gating
```

Only then may the old target lock be restored.

---

# 32. WRONG TERMINAL DURING REACQUISITION

Example:

```text
old target:
RT-001

target disappears

RT-999 appears near predicted position
```

Required result:

```text
RT-999
→ decode
→ WRONG_TERMINAL
→ REJECTED
→ never merged into RT-001
→ reacquisition continues
```

The system must not merely rely on spatial proximity.

---

# 33. CORRECT TERMINAL REAPPEARING

Example:

```text
old:
RT-001 seq=100

reappearance:
RT-001 seq=105
```

Required:

```text
new candidate
→ decode
→ identity valid
→ new sequence
→ spatial gate valid
→ reacquisition accepted
→ ACQUIRED
→ TRACKING
```

A duplicate sequence such as:

```text
seq=100
```

must not be enough to restore liveness.

---

# 34. TEMPORAL HISTORY SIZE

Replace the current small history limit.

The track must retain enough camera samples to support:

```text
synchronization
complete frame recovery
multiple valid frames
temporary losses
tracking continuity
```

Do not use an arbitrary fixed number.

Calculate history from:

```text
camera_fps
frame_duration
required_frame_count
reacquisition requirements
```

Use a safety factor.

Provide configuration for it.

---

# 35. TELEMETRY

Telemetry must expose, per candidate:

```text
observation_id
lifecycle
decoded_terminal_id
decoded_token
decoded_wavelength_nm
sequence_number
last_valid_sequence
identity_state
identity_reason
identity_confidence
valid_frame_count
invalid_frame_count
frame_sync_state
frame_sync_confidence
decode_state
decode_reason
estimated_chip_rate
signal_quality
optical_quality
SNR
```

Global telemetry should expose:

```text
system_state
active_observation_id
active_decoded_terminal_id
identity_state
identity_confidence
frame_sync_state
last_sequence_number
acquisition_state
tracking_state
reacquisition_state
```

Do not expose only optical scores and call the digital subsystem complete.

---

# 36. TESTS MUST PROVE REAL BEACON DECODING

Rewrite/extend the tests.

Do not create tests that simply do:

```python
track.lifecycle_state = CandidateState.TRACKING
assert track.lifecycle_state == CandidateState.TRACKING
```

Those are state-object tests, not lifecycle tests.

Test actual transitions.

---

# 37. REQUIRED UNIT TESTS

Add tests for:

### Protocol

```text
payload encode/decode
frame encode/decode
CRC pass
CRC failure
invalid length
truncated frame
wrong protocol
wrong message type
```

### Demodulation

```text
clean OOK
noise
attenuation
threshold adaptation
missing samples
partial frame
corrupted bits
```

### Synchronization

```text
clean preamble
noise around preamble
false pattern rejection
shifted frame
partial frame
```

### Sequence

```text
new sequence
duplicate
old
large jump
wraparound policy if supported
```

### Identity

```text
correct target
wrong terminal
wrong token
wrong protocol
wrong wavelength
invalid sequence
low-confidence decode
insufficient persistence
```

### Candidate lifecycle

Actually test:

```text
SEEN → TENTATIVE
TENTATIVE → SIGNAL_DETECTED
SIGNAL_DETECTED → DECODING
DECODING → IDENTITY_UNKNOWN
IDENTITY_UNKNOWN → IDENTIFIED
IDENTIFIED → SELECTED
SELECTED → ACQUIRING
ACQUIRING → ACQUIRED
ACQUIRED → TRACKING
TRACKING → DEGRADED
DEGRADED → REACQUIRING
REACQUIRING → TRACKING
REACQUIRING → LOST
```

---

# 38. REQUIRED END-TO-END ACCEPTANCE TEST

Create a genuine integrated test using the physical simulator:

```text
RemoteTerminal
→ optical beam
→ propagation
→ disturbance
→ camera rendering
→ LocalTerminal
```

Do NOT inject payloads or bits directly into the receiver.

The test must demonstrate:

```text
1. Search starts.

2. Optical candidate appears.

3. Candidate obtains temporal history.

4. Receiver detects modulation.

5. Receiver synchronizes to preamble/sync.

6. Receiver demodulates OOK from camera observations.

7. Frame parser reconstructs the frame.

8. CRC passes.

9. Payload decoder produces:
   tid = RT-001
   token = ALPHA-7
   wl = 1550
   seq = increasing number

10. At least 3 unique valid sequences are received.

11. Candidate becomes IDENTIFIED.

12. Spatial lock is established.

13. Candidate becomes ACQUIRED.

14. Candidate becomes TRACKING.

15. Target is disturbed or temporarily removed.

16. Candidate becomes DEGRADED.

17. Candidate enters REACQUIRING.

18. Receiver predicts target location.

19. RT-999 appears at that region.

20. Receiver actually decodes RT-999.

21. IdentityValidator returns WRONG_TERMINAL.

22. RT-999 candidate becomes REJECTED.

23. RT-999 never becomes active target.

24. RT-001 reappears.

25. Receiver decodes RT-001 with a new sequence.

26. Identity is revalidated.

27. Spatial gate passes.

28. Candidate is reacquired.

29. Candidate returns to TRACKING.
```

The test must inspect actual fields such as:

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

not merely:

```text
TARGET_CONFIRMED
TRACKING
```

---

# 39. DISTURBANCE TESTS MUST EXERCISE THE REAL PHYSICAL CHANNEL

Use the existing disturbance/channel system.

Verify that:

```text
attenuation
→ lower received signal
→ lower SNR

wander
→ centroid displacement

scintillation
→ temporal amplitude variation

noise/deep fades
→ incorrect recovered bits / CRC failure

temporary disturbance
→ DEGRADED
→ recovery

persistent disturbance
→ REACQUIRING
```

Do not bypass the disturbance channel with synthetic receiver-side corruption for the integration test.

---

# 40. ACCEPTANCE CRITERIA FOR THE IMPLEMENTATION

The implementation is not complete until all of the following are true:

### Architecture

```text
shared protocol package exists
remote and local both use it
local receiver remains image-only
```

### Digital receiver

```text
TemporalSignalExtractor is live
SignalSynchronizer is live
OOKDemodulator is live
BeaconFrameParser is live
PayloadDecoder is live
IdentityValidator is live
```

### No bypass

```text
no optical-only identification in normal mode
no acquisition without digital identity
no reacquisition without digital identity
no source identity from remote truth
```

### Sequence integrity

```text
duplicates are not new liveness
old frames are rejected/ignored
new sequence numbers advance liveness
```

### Identity

```text
RT-001 accepted
RT-999 rejected
wrong token rejected
wrong wavelength rejected according to configuration
wrong protocol rejected
bad CRC rejected
```

### Tracking

```text
image controls PTZ
digital path validates identity/liveness
temporary misses cause degradation
persistent identity failure causes reacquisition
```

### Reacquisition

```text
predict
search ±2°
search ±5°
search ±10°
wrong target rejected
correct target digitally validated
spatial gate checked
lock restored only after both identity and spatial validation
```

### Tests

Run:

```bash
python -m pytest tests/test_upgrade_acceptance.py -q
python -m pytest tests/test_identity_pipeline.py -q
python -m pytest tests/test_pipeline_acceptance.py -q
python -m pytest tests/test_remote_terminal.py tests/test_simulation.py -q
python -m pytest -q
```

Do not claim success unless the actual tests pass.

---

# 41. IMPLEMENTATION ORDER

Implement in this order to avoid integrating around broken foundations:

```text
1. Audit current repository and identify all existing beacon-related code.

2. Create/normalize shared beacon protocol package.

3. Replace JSON runtime payload with compact deterministic codec.

4. Integrate protocol configuration into RemoteTerminalConfig.

5. Integrate TargetPayloadConfig into LocalTerminalConfig.

6. Correct remote encoder.

7. Increase/compute temporal history correctly.

8. Rewrite TemporalSignalExtractor as proper streaming input.

9. Integrate SignalSynchronizer into FrameDecoder.

10. Integrate OOKDemodulator into FrameDecoder.

11. Make FrameDecoder streaming and incremental.

12. Add is_new_frame and sequence handling.

13. Correct PayloadDecoder.

14. Correct IdentityValidator.

15. Remove normal optical-only identity fallback.

16. Correct lifecycle transitions.

17. Correct acquisition dual-lock behavior.

18. Correct continuous identity validation.

19. Implement identity-gated reacquisition merge.

20. Correct telemetry.

21. Rewrite acceptance tests to prove actual digital decoding.

22. Run full repository test suite.

23. Fix regressions without changing the intended architecture.
```

---

# 42. CODE QUALITY REQUIREMENTS

Do not solve integration problems by adding more compatibility hacks.

Prefer:

```text
clear interfaces
single sources of truth
typed dataclasses
explicit state transitions
deterministic behavior
streaming state
testable components
```

Avoid:

```text
dynamic attributes
silent fallbacks
catch-all exceptions hiding failures
duplicated protocol definitions
optical-only shortcuts
ground-truth shortcuts
fake identity results
```

Do not use broad:

```python
except Exception:
    pass
```

around core identity/decode logic.

If something fails, surface the failure state.

---

# 43. FINAL DELIVERABLE

After implementation, provide a concise engineering report containing:

```text
1. Files created.
2. Files modified.
3. Files removed/deprecated.
4. Beacon protocol definition.
5. Receiver pipeline.
6. Candidate lifecycle.
7. Acquisition logic.
8. Reacquisition logic.
9. Identity validation rules.
10. Timing/history configuration.
11. Tests added.
12. Full test results.
13. Any remaining known limitations.
```

Do not state that the upgrade is complete unless the actual end-to-end digital beacon path has been exercised from:

```text
REMOTE OPTICAL TRANSMISSION
→ DISTURBANCE
→ CAMERA IMAGE
→ LOCAL SIGNAL EXTRACTION
→ SYNCHRONIZATION
→ OOK DEMODULATION
→ FRAME
→ CRC
→ PAYLOAD
→ IDENTITY
→ ACQUISITION
→ TRACKING
→ REACQUISITION
```

without any ground-truth shortcut.

The final architecture must preserve this fundamental separation:

```text
OPTICAL PATH
    →
candidate detection
    →
position / tracking / PTZ control

DIGITAL BEACON PATH
    →
synchronization
    →
frame decoding
    →
identity
    →
liveness
    →
link confidence

THE TWO PATHS
    →
meet at lifecycle / acquisition decisions
```

The decoded beacon identity is authoritative for **who the target is**.

The image measurement is authoritative for **where the target appears to be**.

Do not collapse these two responsibilities.

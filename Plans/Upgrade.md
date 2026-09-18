You are modifying an existing Python/PyQt coarse-alignment / optical-terminal simulator.

Repository:

`https://github.com/thisIsRajbirMajhi/Coarse-Alignment-Simulator`

Do NOT rebuild the simulator from scratch.

The existing system already contains useful components for:

* remote terminal generation
* optical beam rendering
* propagation/channel disturbances
* camera image formation
* sensor effects
* local-terminal candidate detection
* candidate association
* search patterns
* PTZ actuator dynamics
* acquisition
* tracking
* reacquisition
* lifecycle/state machine
* telemetry
* GUI
* headless simulation
* tests

Your task is to **upgrade the middle of the local-terminal perception and decision pipeline** so that target identification is based on **actual decoded beacon data**, not merely optical signature correlation.

The central requirement is:

> The local terminal must independently search the camera image, detect optical candidates, extract their temporal signal, decode the digital beacon frame, validate the payload, identify the correct remote terminal, acquire it, and then track it continuously. During tracking and reacquisition, identity must remain tied to the decoded beacon data.

The local terminal must never use remote-terminal ground truth, remote object references, remote pose, or remote identity directly for perception/identification.

---

# 1. KEEP THE EXISTING PHYSICAL ARCHITECTURE

Do not replace the existing physical simulation.

Preserve:

```text
Remote Terminal
    ↓
Beam generation
    ↓
Optical propagation
    ↓
Disturbance / channel
    ↓
Camera / sensor
    ↓
Local terminal
```

The local terminal should continue receiving only:

```text
CameraFrame
+
local PTZ pose
+
local PTZ velocity
+
local configuration
+
local history/state
```

The local terminal must not receive:

```text
RemoteTerminal object
RemoteTerminal.pose
RemoteTerminal.id
RemoteTerminal truth position
RemoteTerminal truth link state
Remote scenario geometry
```

for perception or target identification.

---

# 2. NEW TARGET-CONCEPT

Separate these concepts:

## Observation identity

The local receiver creates an internal observation ID:

```text
BEACON-001
BEACON-002
BEACON-003
```

This is NOT the remote terminal ID.

It identifies a local candidate track.

## Decoded source identity

The beacon payload contains:

```text
RT-001
RT-002
...
```

This is the actual remote terminal identity.

Never replace the internal observation ID with the decoded terminal ID because an observation exists before the terminal identity is known.

The candidate object must therefore support both:

```text
observation_id = BEACON-001
decoded_terminal_id = RT-001
```

---

# 3. BEACON DATA PROTOCOL

Implement a proper framed digital beacon.

The old:

```text
identification_code
```

based on direct OOK correlation must no longer be the authoritative identity mechanism.

It may remain temporarily for backward compatibility, testing, or legacy mode, but the new framed decoder must be the primary path.

Use this logical structure:

```text
PREAMBLE
SYNC
PROTOCOL_VERSION
MESSAGE_TYPE
PAYLOAD_LENGTH
PAYLOAD
CRC-8
```

The exact binary representation must be deterministic and configurable.

---

# 4. PAYLOAD FORMAT

Use this payload as the default:

```json
{
  "tid": "RT-001",
  "token": "ALPHA-7",
  "wl": 1550,
  "seq": 12345
}
```

Interpret the fields as follows:

```text
tid
    Remote terminal ID.
    This is the primary identity field.

token
    Pre-shared authorization token.
    Treat it as an authorization value, not as real cryptographic security.

wl
    Nominal wavelength in nanometers.
    Used as a consistency check against optical measurements.

seq
    Monotonically increasing frame sequence number.
    Used for liveness, duplicate detection and sequence validation.
```

Do not hard-code these values.

Create configuration support for:

```python
TargetPayloadConfig(
    expected_terminal_id="RT-001",
    expected_token="ALPHA-7",
    expected_wavelength_nm=1550,
)
```

Also configure protocol version and accepted message type.

---

# 5. BEACON ENCODER

Create a proper encoder abstraction on the remote side.

Suggested modules/classes:

```text
BeaconPayload
BeaconFrame
BeaconFrameEncoder
OOKEncoder
CRC8
```

The logical pipeline should be:

```text
BeaconPayload
    ↓
Payload serialization
    ↓
Frame construction
    ↓
CRC-8 generation
    ↓
Binary bitstream
    ↓
OOK chip encoding
    ↓
Optical intensity modulation
```

The existing renderer can continue using intensity modulation.

Do not unnecessarily redesign the optical renderer.

The important change is that the renderer receives a deterministic framed binary sequence instead of comparing against a raw ASCII identification string.

---

# 6. OOK TRANSMISSION

Continue using the existing OOK-style optical modulation.

The frame must become a real binary stream.

Required conceptual flow:

```text
0 bit → low optical intensity
1 bit → high optical intensity
```

The existing chip-rate configuration may continue to be used.

Create clear abstractions so that:

```text
frame → bits → chips → modulation
```

is explicit.

The frame timing and chip rate must be available to the receiver.

Do not make the receiver access the original transmitted bitstream.

The receiver must recover the signal from the simulated camera observations.

---

# 7. RECEIVER ARCHITECTURE

The new local-terminal pipeline must be:

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
CRCValidator
    ↓
PayloadDecoder
    ↓
IdentityValidator
    ↓
CandidateLifecycle
    ↓
Acquisition
    ↓
Tracking
```

Do not bypass these stages.

---

# 8. OPTICAL DETECTION

Continue using the current candidate detector for image-space detection.

For each candidate extract, at minimum:

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

shape metrics

spectral estimate

timestamp/frame index
```

These are optical measurements.

They do NOT establish remote terminal identity.

Their purpose is:

* candidate generation
* candidate quality
* tracking
* acquisition
* search prioritization
* signal extraction
* false-alarm rejection
* consistency checks

---

# 9. TEMPORAL SIGNAL EXTRACTION

For each candidate, maintain a temporal history of the optical signal.

For example:

```text
candidate_history:
    t0 → intensity
    t1 → intensity
    t2 → intensity
    ...
```

Extract the signal from a candidate ROI or local aperture around the predicted centroid.

The temporal signal extractor must support:

```text
mean intensity
background-subtracted intensity
normalized intensity
SNR
signal quality
sample timestamps
```

Do not access remote beacon data directly.

---

# 10. SIGNAL SYNCHRONIZATION

Implement a synchronization stage capable of detecting:

```text
preamble
sync word
```

The receiver should determine:

```text
synchronization_detected
symbol/chip timing
frame_start
signal_quality
```

The synchronization logic must tolerate:

* camera noise
* attenuation
* missing samples
* moderate intensity variation
* beam wander
* scintillation
* temporary signal degradation

The synchronization result must include confidence/quality.

---

# 11. OOK DEMODULATION

Implement an actual OOK demodulator.

Input:

```text
temporal intensity samples
+
timing information
```

Output:

```text
recovered bits
bit confidence
symbol/chip quality
```

The demodulator should use an adaptive or configurable threshold derived from local signal/background statistics rather than relying only on a fixed global threshold.

The demodulator must permit frame corruption when the signal quality is poor.

Do not force successful decoding.

A bad optical signal should be capable of producing:

```text
no frame
invalid frame
CRC failure
truncated frame
incorrect bits
```

---

# 12. FRAME PARSER

Implement a frame parser that recognizes:

```text
PREAMBLE
SYNC
VERSION
TYPE
LENGTH
PAYLOAD
CRC
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
```

Return structured state rather than a simple boolean.

Example:

```python
BeaconDecodeResult(
    frame_detected=True,
    synchronized=True,
    valid_crc=True,
    protocol_version=1,
    message_type=1,
    payload_length=...,
    payload=...,
    decode_confidence=...,
)
```

---

# 13. PAYLOAD DECODER

Create:

```text
PayloadDecoder
```

The decoder converts the binary payload into:

```python
DecodedPayload(
    terminal_id="RT-001",
    token="ALPHA-7",
    wavelength_nm=1550,
    sequence_number=12345,
)
```

Do not bury payload-specific parsing throughout the code.

All payload-format knowledge should be centralized in:

```text
PayloadDecoder
TargetPayloadConfig
```

Therefore, if the payload format changes later, those components are the primary modification points.

---

# 14. IDENTITY VALIDATION

Create an explicit:

```text
IdentityValidator
```

Its job is to compare decoded beacon data against the local target configuration.

Example:

```text
DecodedPayload
        ↓
IdentityValidator
        ↓
IdentityDecision
```

The decision must distinguish:

```text
VALID_TARGET
WRONG_TERMINAL
WRONG_TOKEN
WRONG_PROTOCOL
WAVELENGTH_MISMATCH
INVALID_SEQUENCE
UNKNOWN
```

The most important rule is:

> Matching optical characteristics are not sufficient for identity.

For example:

```text
wavelength correct
modulation correct
spot size correct
SNR high
CRC valid
tid = RT-999
```

must NOT become the local target if the expected terminal is:

```text
RT-001
```

That candidate must be rejected as the wrong terminal.

---

# 15. IDENTITY DECISION RULE

A candidate may become:

```text
IDENTIFIED
```

only if all required identity conditions are satisfied.

Minimum conditions:

```text
frame valid
+
CRC valid
+
protocol accepted
+
message type accepted
+
terminal ID matches expected target
+
token matches expected authorization value
+
wavelength is consistent
+
multiple valid frames received
```

The number of required consecutive valid frames must be configurable.

Example:

```text
identity_persistence = 3
```

Do not identify a candidate from a single weak decode unless explicitly configured.

---

# 16. IDENTITY VS OPTICAL SIGNATURE

Refactor the current signature system.

The existing signature scoring can remain, but it must be renamed/repositioned conceptually as:

```text
OpticalConsistencyScore
```

It can use:

```text
spectral match
modulation match
spatial profile match
SNR
spot size
temporal quality
```

But it must NOT independently establish identity.

The hierarchy must be:

```text
Optical signature
    ↓
candidate plausibility / quality
    ↓
Digital beacon decoding
    ↓
Decoded identity
    ↓
Identity validation
```

The decoded identity is authoritative.

---

# 17. CANDIDATE LIFECYCLE

Upgrade the current lifecycle.

Use approximately:

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

Meaning:

### SEEN

Visual candidate detected.

### TENTATIVE

Candidate persists over sufficient frames.

### SIGNAL_DETECTED

Temporal optical modulation appears beacon-like.

### DECODING

Receiver is attempting frame synchronization and decoding.

### IDENTITY_UNKNOWN

Signal exists, but identity has not yet been validated.

### IDENTIFIED

Decoded payload matches the configured target.

### SELECTED

This identified candidate is chosen as the target to acquire.

### ACQUIRING

PTZ moves to center the candidate.

### ACQUIRED

Identity lock and spatial lock both satisfy acquisition requirements.

### TRACKING

Stable continuous target tracking.

### DEGRADED

Target remains associated but signal/quality has weakened.

### REACQUIRING

Target temporarily lost and local receiver is searching around predicted location.

### LOST

Target is no longer recoverable through the reacquisition policy.

---

# 18. ACQUISITION

Acquisition must require two independent locks.

## Identity lock

Require:

```text
valid CRC
correct terminal ID
correct token
valid protocol
valid sequence
multiple valid frames
```

## Spatial/optical lock

Require:

```text
candidate detected
stable centroid
SNR above threshold
spot quality acceptable
centroid inside acquisition window
motion physically plausible
```

Then:

```text
IDENTITY LOCK
        +
SPATIAL LOCK
        ↓
ACQUIRED
```

Do not declare acquisition solely from visual centering.

Do not declare acquisition solely from successful decoding.

Both are required.

---

# 19. TRACKING

Once acquired, tracking should remain primarily image-based.

The tracking loop should use:

```text
camera centroid
filtered position
predicted position
velocity
acceleration
PTZ state
```

for control.

The digital beacon is used simultaneously for:

```text
identity continuity
liveness
frame quality
sequence validation
link health
target confirmation
```

Therefore:

```text
optical path → control
digital path → identity/liveness
```

This separation is important.

Do not move the PTZ based directly on decoded ID.

---

# 20. CONTINUOUS IDENTITY VALIDATION DURING TRACKING

While tracking:

```text
tracking candidate
      ↓
new frame?
      ↓
decode
      ↓
validate identity
```

Valid frames strengthen the identity lock.

Repeated decode failures should reduce identity confidence.

The tracked candidate must transition to:

```text
DEGRADED
```

when digital validation becomes unreliable.

Do not instantly lose the target due to one missed frame.

Use configurable:

```text
frame_timeout
identity_timeout
maximum_invalid_frames
```

---

# 21. SEQUENCE NUMBER VALIDATION

Use:

```text
seq
```

to provide liveness.

Maintain:

```text
last_valid_sequence
```

For each decoded frame:

```text
new sequence > previous sequence
```

should normally be accepted.

Handle:

```text
duplicate sequence
old sequence
large unexpected jump
```

according to configurable policy.

Do not treat a duplicate frame as new evidence of liveness.

This also allows tests for replay-like behavior.

---

# 22. REACQUISITION

When the tracked beam disappears:

```text
TRACKING
    ↓
DEGRADED
    ↓
REACQUIRING
```

First predict the target location from:

```text
last position
velocity
acceleration
PTZ state
```

Then search around the predicted position.

Use the existing expanding search concept:

```text
small search region
    ↓
medium region
    ↓
large region
```

or approximately:

```text
±2°
±5°
±10°
```

based on the existing implementation/configuration.

However, every reacquisition candidate must pass:

```text
visual detection
+
signal detection
+
frame decode
+
identity validation
```

A spatially nearby candidate with the wrong terminal ID must be rejected.

---

# 23. CRITICAL REACQUISITION RULE

Suppose the previously tracked target was:

```text
RT-001
```

The target disappears.

A new beam appears exactly where the predicted target should be.

The decoded payload says:

```text
RT-999
```

The local terminal must NOT reacquire it.

Correct behavior:

```text
predicted location matches
BUT identity mismatch
    ↓
REJECT
    ↓
continue reacquisition
```

If another beam subsequently decodes as:

```text
RT-001
```

and satisfies spatial checks:

```text
REACQUIRED
    ↓
TRACKING
```

Identity has priority over spatial coincidence.

---

# 24. MULTIPLE CANDIDATES

The local terminal must support multiple simultaneous optical candidates.

Example:

```text
Candidate A
    wavelength = 1550
    high SNR
    decoded ID = RT-999

Candidate B
    wavelength = 1550
    moderate SNR
    decoded ID = RT-001
```

If:

```text
expected target = RT-001
```

then:

```text
Candidate B
    → IDENTIFIED
    → SELECTED
```

Candidate A:

```text
→ WRONG_TERMINAL
→ REJECTED
```

Do not select the strongest visual candidate simply because it is brightest.

---

# 25. DISTURBANCE INTERACTION

Do not make the disturbance module directly alter identity fields.

The disturbance operates on the physical transmission.

Conceptually:

```text
Beacon frame
    ↓
OOK optical modulation
    ↓
Physical optical beam
    ↓
Disturbance/channel
    ↓
Degraded received signal
    ↓
Camera
    ↓
Temporal signal
    ↓
Decoder
```

Disturbance can cause:

```text
attenuation
beam wander
spot spreading
scintillation
temporal variation
noise
signal fading
sample loss
bit errors
frame corruption
CRC failure
frame loss
```

But disturbance should never directly say:

```text
identity = invalid
```

The decoder must discover that through degraded observations.

This is important for physical realism.

---

# 26. FAILURES THE SYSTEM MUST MODEL

The simulator should support cases such as:

```text
beam visible but no decode
beam visible but wrong terminal
beam visible and correct wavelength but wrong ID
weak signal
strong signal with corrupt frame
temporary frame loss
temporary optical loss
CRC error
invalid sequence
old/replayed sequence
candidate disappears
target reappears
wrong terminal appears during reacquisition
multiple terminals visible
target changes identity while position remains similar
```

Each should produce sensible state transitions.

---

# 27. STATE DATA MODEL

Extend the candidate track with fields similar to:

```python
CandidateTrack(
    observation_id,

    optical_measurement,

    signal_measurement,

    synchronization_state,

    decode_state,

    latest_frame,

    decoded_terminal_id,

    decoded_token,

    decoded_wavelength_nm,

    sequence_number,

    identity_state,

    identity_confidence,

    valid_frame_count,

    invalid_frame_count,

    last_valid_frame_time,

    last_valid_sequence,

    lifecycle_state,

    filtered_position,

    predicted_position,

    velocity,

    acceleration,

    optical_quality,

    signal_quality,
)
```

Use proper typed models/dataclasses where appropriate.

Do not scatter these fields across unrelated dictionaries.

---

# 28. ADD EXPLICIT RESULT TYPES

Create explicit structured result objects.

At minimum:

```text
OpticalMeasurement

SignalMeasurement

BeaconFrame

BeaconDecodeResult

DecodedPayload

IdentityDecision
```

Example:

```python
IdentityDecision(
    status="VALID_TARGET",
    terminal_id="RT-001",
    token_valid=True,
    wavelength_valid=True,
    sequence_valid=True,
    confidence=0.97,
    reason="valid target frame",
)
```

This will make the state machine and telemetry much easier to reason about.

---

# 29. LOCAL TARGET CONFIGURATION

Add a local target configuration section.

Example:

```python
TargetPayloadConfig(
    expected_terminal_id="RT-001",
    expected_token="ALPHA-7",
    expected_wavelength_nm=1550,
    expected_protocol_version=1,
    expected_message_type=1,

    required_valid_frames=3,

    sequence_validation_enabled=True,
    wavelength_validation_enabled=True,
)
```

All important thresholds should remain configurable.

Do not hard-code target identity inside algorithms.

---

# 30. REMOTE CONFIGURATION

The remote terminal already has identity configuration.

Use its configuration to generate the beacon payload.

For example:

```text
IdentityConfig.id
CommunicationConfig.terminal_id
BeaconConfig.identification_code
BeaconConfig.identification_chip_rate_hz
BeaconConfig.wavelength
```

Refactor as necessary so the actual framed payload is generated from the remote terminal configuration.

Do not introduce duplicate sources of truth.

The remote terminal's configured identity should be the source for:

```text
tid
token
wl
```

---

# 31. BACKWARD COMPATIBILITY

Keep the existing simulation working while introducing the new path.

Avoid unnecessary breaking changes.

Where practical:

```text
old API
    ↓
adapter
    ↓
new encoder/decoder
```

is preferable to deleting existing functionality.

The old identification-code logic may remain under a clearly defined:

```text
legacy_mode
```

but should not be active by default in the new identity pipeline.

---

# 32. EXISTING CODE TO REVIEW

Inspect and integrate with the existing:

```text
local_terminal/system.py
local_terminal/terminal.py
local_terminal/models.py
local_terminal/states.py
local_terminal/state_machine.py
local_terminal/lifecycle.py
local_terminal/candidate_detector.py
local_terminal/detection.py
local_terminal/signature.py
local_terminal/association.py
local_terminal/acquisition.py
local_terminal/acquisition_mgr.py
local_terminal/reacquisition.py
local_terminal/tracking.py
local_terminal/tracking_controller.py
local_terminal/estimator.py
local_terminal/frame_processor.py
local_terminal/config.py

remote_terminal/config.py
remote_terminal/terminal.py
remote_terminal/optics.py
remote_terminal/scenario.py

disturbance/optical/channel.py
disturbance/core/pipeline.py
simulation/fov_pipeline.py
simulation/headless.py
```

Do not create duplicate implementations when existing abstractions can be extended cleanly.

---

# 33. SYSTEM UPDATE ORDER

The main `LocalTerminalSystem.update()` should conceptually follow:

```text
1. Validate input frame/time
2. Process camera image
3. Detect optical candidates
4. Associate candidates with existing tracks
5. Update optical measurements
6. Extract temporal signal
7. Synchronize signal
8. Demodulate OOK
9. Parse frame
10. Validate CRC
11. Decode payload
12. Validate identity
13. Update candidate lifecycle
14. Select valid target
15. Acquire if necessary
16. Track if acquired
17. Validate identity continuously
18. Reacquire if target is lost
19. Update telemetry
20. Return local-terminal state/output
```

Do not allow lifecycle state changes to occur before the corresponding evidence has been produced.

---

# 34. OUTPUT OF THE LOCAL TERMINAL

Expose meaningful telemetry.

At minimum return:

```text
system_state

active_observation_id

decoded_terminal_id

identity_state

identity_confidence

optical_quality

signal_quality

frame_sync_state

last_sequence_number

candidate_count

selected_candidate

acquisition_state

tracking_state

reacquisition_state

PTZ command

PTZ actual state
```

This will allow the GUI and tests to inspect why the terminal believes a target is valid.

---

# 35. DEBUG/TRACE INFORMATION

Make the simulator explain decisions.

For each candidate, expose a reason such as:

```text
VISIBLE_ONLY
SIGNAL_DETECTED
DECODING
CRC_FAILURE
UNKNOWN_IDENTITY
WRONG_TERMINAL
WRONG_TOKEN
WAVELENGTH_MISMATCH
VALID_TARGET
ACQUISITION_PENDING
TRACKING_VALID
IDENTITY_DEGRADED
REACQUISITION
```

This is important for debugging the agent and for GUI visualization.

---

# 36. TESTS

Add automated tests for all of the following.

## Identity

```text
1. Correct payload → IDENTIFIED
2. Wrong terminal ID → REJECTED
3. Wrong token → REJECTED
4. Correct wavelength but wrong ID → REJECTED
5. Wrong wavelength with correct ID → configurable reject/degrade
6. Invalid CRC → not identified
7. Unsupported protocol version → rejected
8. Invalid message type → rejected
```

## Sequence/liveness

```text
9. Increasing sequence numbers → accepted
10. Duplicate sequence → does not count as new liveness
11. Old sequence → rejected/ignored
12. Sequence discontinuity → handled according to policy
```

## Lifecycle

```text
13. Visible candidate → TENTATIVE
14. Signal detected → DECODING
15. Correct decoded identity → IDENTIFIED
16. Multiple valid frames → SELECTED
17. Spatial lock + identity lock → ACQUIRED
18. Continuous valid frames → TRACKING
19. Temporary frame loss → DEGRADED
20. Target loss → REACQUIRING
21. Timeout → LOST
```

## Reacquisition

```text
22. Correct target disappears → reacquisition begins
23. Wrong terminal appears at predicted location → reject
24. Correct terminal reappears → reacquire
25. Correct terminal reappears with corrupted frames → remain reacquiring
26. Correct identity + spatial mismatch → reject candidate
```

## Multi-target

```text
27. Multiple beams visible → candidates remain separate
28. Bright wrong terminal + weaker correct terminal → correct terminal selected
```

## Disturbance

```text
29. Attenuation reduces SNR
30. Beam wander moves centroid
31. Scintillation causes temporal amplitude variation
32. Severe disturbance causes CRC/frame failures
33. Temporary disturbance causes degrade → recovery
```

## Identity continuity

```text
34. Same optical position but decoded identity changes
    → tracking identity must not silently continue
```

---

# 37. DO NOT DO THESE THINGS

Do NOT:

```text
- access RemoteTerminal from LocalTerminal for identification
- use ground-truth geometry to declare a target
- directly copy remote terminal ID into local candidate state
- classify identity solely from wavelength
- classify identity solely from modulation
- classify identity solely from spot shape
- classify identity solely from SNR
- classify identity solely from temporal correlation
- declare acquisition merely because the centroid is centered
- let a wrong terminal pass reacquisition because it is spatially close
- let disturbance code directly decide identity
- hide frame decoding inside the state machine
- hard-code RT-001 throughout the code
- remove existing physical disturbance models unnecessarily
- replace the existing PTZ/search/tracking architecture unnecessarily
```

---

# 38. IMPLEMENTATION PRIORITY

Implement in this order:

```text
Phase 1
Beacon payload model
Beacon frame model
CRC-8
Remote frame encoder
OOK encoder

Phase 2
Temporal signal extraction
Synchronization
OOK demodulator
Frame parser

Phase 3
PayloadDecoder
TargetPayloadConfig
IdentityValidator

Phase 4
CandidateTrack integration
Lifecycle integration

Phase 5
Acquisition integration

Phase 6
Tracking identity continuity

Phase 7
Reacquisition identity validation

Phase 8
Telemetry and GUI integration

Phase 9
Comprehensive automated tests

Phase 10
Remove/demote old identification correlation as authoritative identity logic
```

Do not attempt to rewrite everything in a single uncontrolled change.

---

# 39. ACCEPTANCE CRITERIA

The implementation is complete only when the following scenario works end-to-end.

Scenario:

```text
Remote terminal:
    ID = RT-001
    token = ALPHA-7
    wavelength = 1550
```

Local terminal:

```text
expected target = RT-001
expected token = ALPHA-7
expected wavelength = 1550
```

The local terminal starts searching.

It sees a bright optical candidate.

It does NOT immediately identify it.

It extracts the temporal signal.

It synchronizes to the beacon.

It demodulates OOK.

It reconstructs a frame.

It validates CRC.

It decodes:

```text
tid = RT-001
token = ALPHA-7
wl = 1550
seq = ...
```

After the configured number of valid frames:

```text
IDENTIFIED
```

It then acquires the target using spatial and optical lock.

After acquisition:

```text
ACQUIRED
→ TRACKING
```

During tracking, new frames continue arriving and sequence numbers increase.

The target temporarily disappears.

The terminal enters:

```text
DEGRADED
→ REACQUIRING
```

It predicts the target location and searches around it.

A different terminal appears in that region:

```text
tid = RT-999
```

It is rejected.

The correct terminal later reappears:

```text
tid = RT-001
```

It is decoded and validated.

The terminal reacquires it:

```text
REACQUIRING
→ ACQUIRED
→ TRACKING
```

All of this must happen using the local receiver's observations and internal history only.

---

# 40. FINAL ARCHITECTURAL PRINCIPLE

The final system must embody this exact separation:

```text
                OPTICAL PATH
Camera
  ↓
Detection
  ↓
Centroid / Spot / SNR / Optical quality
  ↓
Tracking / Acquisition control


                DIGITAL PATH
Camera ROI
  ↓
Temporal signal
  ↓
Synchronization
  ↓
OOK demodulation
  ↓
Frame decode
  ↓
CRC
  ↓
Payload
  ↓
Identity validation
  ↓
Target identity / liveness


                DECISION LAYER
Optical evidence
        +
Digital identity evidence
        ↓
Candidate lifecycle
        ↓
Selection
        ↓
Acquisition
        ↓
Tracking
        ↓
Reacquisition
```

The core rule is:

> A detected light source is only a candidate. A decoded, validated beacon payload identifies the source. Optical measurements control where the terminal points. Digital beacon data determines which source the terminal is actually tracking.

Implement this architecture cleanly, reuse the existing simulator components wherever possible, add tests before declaring the migration complete, and preserve the simulator's current headless and GUI execution paths.

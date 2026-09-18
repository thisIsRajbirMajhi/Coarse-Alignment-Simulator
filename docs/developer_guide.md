# Developer Guide

> **Scope**: How to extend, modify, and contribute to the Coarse-Alignment-Simulator codebase. Covers module responsibilities, extension points, coding conventions, and common pitfalls.

---

## 1. Prerequisites

- Python 3.10+
- Understanding of the two-path model (see [`architecture_overview.md`](./architecture_overview.md))
- Familiarity with `@dataclass` and Python type hints
- Basic knowledge of Kalman filtering and OOK digital communications

---

## 2. Codebase Orientation

### Golden Rule

> **The local terminal may only observe the world through `CameraFrame`. Any code path that reads a `RemoteTerminal` attribute inside `local_terminal/` is an architectural violation.**

Before writing any code, ask:
1. Am I adding something to `local_terminal/`? → It must not import from `remote_terminal/`.
2. Am I adding a protocol definition? → It belongs in `common/protocol/beacon/`, not in either terminal.
3. Am I touching the acquisition logic? → Both identity lock AND spatial lock must remain required.
4. Am I handling sequences? → Duplicates and old sequences must never count as liveness.

---

## 3. How to Add a New Candidate Track Feature

### Step 1 — Add the field to `CandidateTrack` in `models.py`

```python
@dataclass
class CandidateTrack:
    # ... existing fields ...
    my_new_field: float = 0.0       # add with a safe default
```

### Step 2 — Populate the field in the relevant stage

If it's computed from optical measurements:
```python
# In system.py or detection.py:
track.my_new_field = compute_my_field(measurement)
```

If it's derived from the decoded payload:
```python
# In identity_matcher.py IdentityValidator.validate():
track.my_new_field = decision.some_payload_field
```

### Step 3 — Expose it in telemetry

```python
# In telemetry_mgr.py CandidateTelemetry:
my_new_field: float = 0.0
# In TelemetryManager.collect():
tel.my_new_field = track.my_new_field
```

### Step 4 — Update tests

Add an assertion in the appropriate test file that the field is populated correctly.

---

## 4. How to Add a New Lifecycle State Transition

The lifecycle is driven by `local_terminal/lifecycle.py`. The `CandidateLifecycle.update()` method is called every frame for each track.

### Example: Adding a VERIFYING state between IDENTIFIED and SELECTED

**Step 1** — Add the state to `states.py`:
```python
class CandidateState(str, Enum):
    # ...
    VERIFYING = "VERIFYING"   # new state
```

**Step 2** — Add transition logic in `lifecycle.py`:
```python
elif track.lifecycle_state == CandidateState.IDENTIFIED:
    if should_verify(track, config):
        track.lifecycle_state = CandidateState.VERIFYING
    elif should_select(track):
        track.lifecycle_state = CandidateState.SELECTED

elif track.lifecycle_state == CandidateState.VERIFYING:
    if verification_complete(track, config):
        track.lifecycle_state = CandidateState.SELECTED
    elif verification_failed(track, config):
        track.lifecycle_state = CandidateState.REJECTED
```

**Step 3** — Update the `TrackingController` mode dispatcher if the new state needs different PTZ behaviour.

**Step 4** — Update the camera view colour code in `gui/views/camera_view.py`.

**Step 5** — Write a lifecycle test in `tests/test_candidate_lifecycle.py` that proves the actual transition occurs under the right conditions.

---

## 5. How to Modify the Beacon Protocol

### 5.1 Adding a New Payload Field

Edit `common/protocol/beacon/payload.py`:

```python
@dataclass
class BeaconPayload:
    terminal_id: str
    token: str
    wavelength_nm: float
    sequence_number: int
    my_new_field: int = 0    # add here
```

Update `PayloadCodec.encode()`:
```python
def encode(self, payload: BeaconPayload) -> bytes:
    # existing encoding...
    data += struct.pack(">H", payload.my_new_field)   # append 2-byte field
    return data
```

Update `PayloadCodec.decode()`:
```python
def decode(self, data: bytes) -> DecodedPayload:
    # existing decoding...
    offset = existing_end
    my_new_field = struct.unpack_from(">H", data, offset)[0]
    return DecodedPayload(..., my_new_field=my_new_field)
```

> **Critical**: bump `PROTOCOL_VERSION` when changing the wire format. The receiver must reject frames with the old protocol version to prevent mismatches.

### 5.2 Changing the Frame Structure

Edit `common/protocol/beacon/frame.py`. The preamble and sync bytes are constants — do not change them without also updating the `SignalSynchronizer` template generator.

---

## 6. How to Add a New Search Pattern

Search patterns are in `local_terminal/search_manager.py`.

```python
class SearchManager:
    def _generate_scan_points(self) -> list[tuple[float, float]]:
        if self.config.search_pattern == "RASTER":
            return self._raster_points()
        elif self.config.search_pattern == "SPIRAL":
            return self._spiral_points()
        elif self.config.search_pattern == "MY_PATTERN":    # new
            return self._my_pattern_points()               # add method
```

Add `"MY_PATTERN"` to the valid patterns set in `AcquisitionConfig.validate()`:
```python
patterns = {"RANDOM", "RASTER", "SPIRAL", "SECTOR", "GRID", "CUSTOM", "FIGURE_8", "MY_PATTERN"}
```

---

## 7. How to Write a Test

### Test Conventions

All tests in `tests/` follow these rules:

1. **Test actual behaviour, not attribute assignment**. Use `HeadlessSimulation` or construct real component instances.

2. **No ground-truth shortcuts**. Do not set `track.lifecycle_state = TRACKING` and then assert it. Test the transition.

3. **Use the real protocol**. Do not inject bits directly into the decoder — feed them through `BeaconFrameEncoder` → OOK → fake signal array → `SignalSynchronizer` → `OOKDemodulator` → `BeaconFrameParser`.

4. **Name tests descriptively**:
   ```python
   def test_wrong_terminal_is_rejected_during_reacquisition(): ...
   def test_duplicate_sequence_does_not_advance_valid_frame_count(): ...
   ```

### Minimal Test Fixture for Protocol

```python
from common.protocol.beacon.payload import BeaconPayload, PayloadCodec
from common.protocol.beacon.frame import BeaconFrameEncoder, BeaconFrameParser

def make_frame(tid="RT-001", token="ALPHA-7", wl=1550, seq=1):
    payload = BeaconPayload(
        terminal_id=tid, token=token,
        wavelength_nm=wl, sequence_number=seq,
    )
    codec = PayloadCodec()
    encoder = BeaconFrameEncoder()
    return encoder.encode(payload, codec)

def test_valid_frame_roundtrip():
    frame_bytes = make_frame()
    parser = BeaconFrameParser()
    result = parser.parse(frame_bytes)
    assert result.frame_detected
    assert result.valid_crc
    assert result.protocol_version == 1
```

### Minimal Test Fixture for HeadlessSimulation

```python
from simulation.headless import HeadlessSimulation
from local_terminal.config import LocalTerminalConfig, TargetPayloadConfig

def make_sim():
    cfg = LocalTerminalConfig()
    cfg.target_payload = TargetPayloadConfig(
        expected_terminal_id="RT-001",
        expected_token="ALPHA-7",
        required_valid_frames=3,
    )
    cfg.validate()
    return HeadlessSimulation(config=make_full_sim_config(local=cfg))

def test_basic_acquisition():
    sim = make_sim()
    result = sim.run_until(
        lambda out: out.telemetry.system_state == "TRACKING",
        timeout_s=300.0,
    )
    assert result.success
    assert result.active_candidate.decoded_terminal_id == "RT-001"
```

---

## 8. Code Style Conventions

### Python Style

- **Type hints everywhere**: use `str | None` (not `Optional[str]`).
- **Dataclasses** for all data structures; no dict-of-dicts for structured data.
- **No broad exception catches** around identity/decode logic:
  ```python
  # BAD:
  try:
      result = identity_validator.validate(...)
  except Exception:
      pass   # ← hides real failures

  # GOOD:
  result = identity_validator.validate(...)
  # Let it propagate; log it in the caller if needed
  ```
- **Explicit state transitions**: use named constants (`CandidateState.IDENTIFIED`) not magic strings.
- **Single source of truth**: if you need a constant in two places, define it in `common/` and import it.

### What to Avoid

| Pattern | Why Forbidden |
|---------|--------------|
| `import remote_terminal` inside `local_terminal/` | Violates image-only boundary |
| Setting `track.lifecycle_state` directly outside `lifecycle.py` | Bypasses transition rules |
| Reading `scenario.remote_terminals[0].position` in LT | Ground truth use |
| `decode_confidence = 1.0` hardcoded | Fakes successful decode |
| `track.identity_matched = True` without validation | Bypasses identity gate |

---

## 9. Extending the GUI

### Adding a New Panel

1. Create `gui/panels/my_panel.py` inheriting from `QWidget`.
2. Accept `telemetry: SystemTelemetry` in `update(self, telemetry)`.
3. Register the panel in `gui/main_window.py`:
   ```python
   self.my_panel = MyPanel(parent=self)
   self.layout.addWidget(self.my_panel)
   ```
4. Connect to the telemetry signal:
   ```python
   self.simulation_controller.telemetry_updated.connect(self.my_panel.update)
   ```

### Adding a New Plot

Plot widgets live in `gui/views/`. Use `PyQtGraph` or `matplotlib` embedded in a `QWidget`. The signal plot (`signal_plot.py`) is a good reference implementation.

---

## 10. Common Pitfalls

### Pitfall 1: Re-feeding Signal History

**Wrong**:
```python
def update(self, signal: ExtractedSignal):
    self.decoder.feed(signal.normalized_signal)  # feeds ALL history every call
```

**Correct**:
```python
def update(self, observation_id: str, signal: ExtractedSignal):
    state = self._get_state(observation_id)
    new_samples = signal.normalized_signal[state.last_processed_index:]
    state.last_processed_index = len(signal.normalized_signal)
    self.decoder.feed(new_samples)   # feeds only new samples
```

### Pitfall 2: Counting Duplicate Sequences

**Wrong**:
```python
if decision.identity_state == VALID_TARGET:
    track.valid_frame_count += 1   # counts every validation, even duplicates
```

**Correct**:
```python
if decision.identity_state == VALID_TARGET and decision.is_new_liveness:
    track.valid_frame_count += 1   # only new sequences
```

### Pitfall 3: Skipping the Identity Gate in Acquisition

**Wrong**:
```python
def check_acquired(track, config):
    if config.require_identity_lock and track.identity_matched:
        id_locked = True
    elif not config.require_identity_lock:
        id_locked = True   # ← BYPASS
    return id_locked and spatial_lock
```

**Correct**:
```python
def check_acquired(track, config):
    if config.legacy_optical_identification_enabled:
        id_locked = True   # explicitly legacy
    else:
        id_locked = bool(track.identity_matched)   # always required in normal mode
    return id_locked and spatial_lock
```

### Pitfall 4: Fabricating Optical Measurements

**Wrong**:
```python
measurement.spectral_estimate = track.decoded_wavelength_nm   # copied from payload!
```

**Correct**:
```python
measurement.spectral_estimate = spectral_model.estimate(
    blob.pixel_values, camera_config.spectral_response
)
```

### Pitfall 5: Forgetting `is_new_frame` in `BeaconDecodeResult`

`is_new_frame` must be explicitly set. A frame where `sequence == last_valid_sequence` must have `is_new_frame = False`, even if the CRC is valid.

---

## 11. Testing Checklist (Before Merging)

Run the following and confirm all pass:

```bash
# Protocol correctness
python -m pytest tests/test_beacon_protocol.py -q

# Signal processing
python -m pytest tests/test_signal_processing.py -q

# Identity pipeline
python -m pytest tests/test_identity_pipeline.py -q

# Lifecycle transitions
python -m pytest tests/test_candidate_lifecycle.py -q

# Acquisition
python -m pytest tests/test_acquisition.py -q

# Reacquisition
python -m pytest tests/test_reacquisition.py -q

# End-to-end
python -m pytest tests/test_upgrade_acceptance.py -v

# Full suite
python -m pytest -q
```

A failing test on `test_upgrade_acceptance.py` means a fundamental architectural requirement is not met. Do not mark the implementation as complete until this test passes.

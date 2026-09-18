# User Manual — Coarse-Alignment-Simulator

**Version**: 2.0  
**Product**: Coarse-Alignment-Simulator (FSO Optical Terminal Simulator)  
**Audience**: Operators, researchers, and engineers using the simulator  

---

## Table of Contents

1. [Introduction](#1-introduction)
2. [System Requirements and Installation](#2-system-requirements-and-installation)
3. [Launching the Simulator](#3-launching-the-simulator)
4. [Understanding the User Interface](#4-understanding-the-user-interface)
5. [Remote Terminal Panel — Configuration and Control](#5-remote-terminal-panel)
6. [Local Terminal Panel — Receiver Status](#6-local-terminal-panel)
7. [Camera View — Live Optical Display](#7-camera-view)
8. [Signal and Telemetry Panels](#8-signal-and-telemetry-panels)
9. [Running a Simulation — Step-by-Step Walkthrough](#9-running-a-simulation)
10. [Interpreting Candidate States](#10-interpreting-candidate-states)
11. [Interpreting Identity and Acquisition Status](#11-interpreting-identity-and-acquisition-status)
12. [Scenario Events — Disappear, Decoy, Reacquisition](#12-scenario-events)
13. [Headless (Non-GUI) Mode](#13-headless-mode)
14. [Common Issues and Troubleshooting](#14-troubleshooting)
15. [Keyboard Shortcuts and Controls](#15-keyboard-shortcuts)

---

## 1. Introduction

The **Coarse-Alignment-Simulator** is a physics-based, end-to-end simulator of a Free-Space Optical (FSO) communications link. It models the complete chain from:

```
Remote Terminal (transmitter) → Atmosphere → Camera Sensor → Local Terminal (receiver)
```

The simulator is used to study, develop, and validate **search, detection, identification, acquisition, tracking, and reacquisition** algorithms for optical pointing and tracking systems — without access to real hardware.

### What the Simulator Does

- **Remote Terminal**: transmits an OOK-modulated digital beacon encoded in a framed binary protocol.
- **Atmosphere**: applies physical disturbances — attenuation, scintillation, wander, noise.
- **Camera Sensor**: renders a realistic camera image including background stars, haze, and the modulated beacon spot.
- **Local Terminal**: autonomously detects, identifies, and tracks the remote terminal using *only* the camera image — no ground truth is used.

### Key Distinction

The simulator enforces a strict **image-only boundary**: the local terminal receiver is never given the remote terminal's position, identity, or transmitted bits. It must earn all knowledge through the camera and signal decoder, just as a real optical receiver must.

---

## 2. System Requirements and Installation

### Requirements

| Component | Minimum | Recommended |
|-----------|---------|-------------|
| Python | 3.10 | 3.11 or 3.12 |
| RAM | 4 GB | 8 GB |
| CPU | Dual-core 2 GHz | Quad-core 3 GHz |
| OS | Windows 10 / Ubuntu 20.04 | Windows 11 / Ubuntu 22.04 |
| Display | 1920×1080 | 2560×1440 |

### Python Dependencies

```
numpy >= 1.26, < 2.6
opencv-python >= 4.8, < 5.1
PyQt5 == 5.15.11
pytest >= 8.0  (for running tests)
```

### Installation

**Step 1** — Clone the repository:
```bash
git clone https://github.com/thisIsRajbirMajhi/Coarse-Alignment-Simulator.git
cd Coarse-Alignment-Simulator
```

**Step 2** — Create a virtual environment (recommended):
```bash
python -m venv .venv

# Windows:
.venv\Scripts\activate

# Linux / macOS:
source .venv/bin/activate
```

**Step 3** — Install dependencies:
```bash
pip install -r requirements.txt
```

**Step 4** — Verify installation:
```bash
python -m pytest -q
```

All tests should pass (or be marked as expected failures if implementation is incomplete).

---

## 3. Launching the Simulator

### GUI Mode (default)

```bash
python main.py
```

This opens the main application window.

### Headless Mode

To run without a GUI (for automated testing or batch runs):

```bash
python -m simulation.headless --config my_scenario.yaml --duration 300
```

See [Section 13](#13-headless-mode) for full headless usage.

---

## 4. Understanding the User Interface

The main window is divided into several key areas:

```
┌─────────────────────────────────────────────────────────────────────┐
│  Menu Bar: File │ Scenario │ Configuration │ View │ Help            │
├──────────────────────────┬──────────────────────────────────────────┤
│                          │                                          │
│   CAMERA VIEW            │   REMOTE TERMINAL PANEL                 │
│   (live optical feed)    │   (transmitter settings & status)       │
│                          │                                          │
│   + candidate overlays   │   LOCAL TERMINAL PANEL                  │
│   + centroid markers     │   (receiver pipeline status)            │
│   + PTZ crosshair        │                                          │
│                          │   CANDIDATE LIST                        │
├──────────────────────────┤   (all active/rejected tracks)          │
│   SIGNAL PLOT            │                                          │
│   (intensity vs. time)   ├──────────────────────────────────────────┤
│                          │   TELEMETRY                              │
│   METRICS PLOT           │   (digital decode status, SNR, etc.)    │
│   (tracking error, SNR)  │                                          │
└──────────────────────────┴──────────────────────────────────────────┘
```

### Panels at a Glance

| Panel | Purpose |
|-------|---------|
| Camera View | Shows the simulated camera image in real time |
| Remote Terminal Panel | Configure and monitor the beacon transmitter |
| Local Terminal Panel | Monitor the receiver's search/track/identity state |
| Candidate List | View all detected candidate tracks and their status |
| Signal Plot | Visualise the temporal beacon signal for the selected candidate |
| Telemetry | Read digital decode status, SNR, sequence numbers, identity |

---

## 5. Remote Terminal Panel

The Remote Terminal Panel configures the beacon that the local terminal must find and identify.

### Configuration Fields

| Field | Description | Default |
|-------|-------------|---------|
| **Terminal ID** | The identity string embedded in the beacon payload. The local terminal must decode this to identify the target. | `RT-001` |
| **Token** | Authentication token. The receiver must also match this to accept the identity. | `ALPHA-7` |
| **Wavelength (nm)** | Carrier wavelength of the optical beacon. | `1550` |
| **Chip Rate (Hz)** | Number of OOK chips per second. Higher = faster decoding but may require more signal quality. | `12.0` |
| **Payload Codec** | `compact` (default) for the binary protocol; `json_debug` only for diagnostics. | `compact` |
| **Beacon Enabled** | Toggle beacon transmission on/off. | `On` |

> **Important**: Changing the Terminal ID or Token while a simulation is running will cause the local receiver to eventually decode the new identity. If it does not match the local terminal's expected values, the candidate will be **rejected**.

### Status Indicators

| Indicator | Meaning |
|-----------|---------|
| Sequence Counter | Monotonically increasing frame number being transmitted |
| Current Chip | Current OOK chip value (0 = OFF, 1 = ON) |
| Frame Duration | Calculated time for one complete beacon frame (based on chip rate and payload size) |
| Angular Position | Where the RT appears in the scene (Az/El) — for diagnostics only; the LT never reads this |

### Controls

- **Disable RT** — simulates target disappearance. Use this to trigger reacquisition scenarios.
- **Enable Decoy (RT-999)** — enables a second terminal with a different identity, useful for testing identity-gated reacquisition.
- **Adjust Chip Rate** — live adjustment. Note: if reduced too much, the receiver's history buffer may become insufficient. A warning will appear.

---

## 6. Local Terminal Panel

The Local Terminal Panel is a read-only display of the receiver's current internal state.

### System State Section

| Field | Possible Values | Meaning |
|-------|----------------|---------|
| **System State** | `IDLE`, `SEARCHING`, `ACQUIRING`, `TRACKING`, `DEGRADED`, `REACQUIRING` | Overall receiver mode |
| **Active Observation ID** | e.g. `BEACON-001` | The candidate currently being tracked (locally generated ID) |
| **Decoded Terminal ID** | e.g. `RT-001` or `—` | Identity decoded from beacon payload |
| **Identity State** | `VALID_TARGET`, `WRONG_TERMINAL`, `UNKNOWN`, etc. | Result of last identity validation |
| **Identity Confidence** | 0.0 – 1.0 | How reliable the current identity assessment is |
| **Frame Sync State** | `UNSYNCHRONIZED`, `SEARCHING`, `SYNCHRONIZED` | Whether the receiver has found the beacon preamble |
| **Last Sequence** | integer or `—` | Sequence number of the last successfully decoded and validated frame |
| **Valid Frame Count** | integer | Number of unique valid sequences decoded for the current candidate |

### Understanding the Progress Flow

A normal successful acquisition looks like:

```
System State:      SEARCHING → ACQUIRING → TRACKING
Active Obs ID:     — → BEACON-001
Decoded Terminal:  — → RT-001
Identity State:    UNKNOWN → VALID_TARGET
Valid Frames:      0 → 1 → 2 → 3
```

It takes time — the receiver must accumulate enough camera frames to:
1. Detect the modulated signal.
2. Synchronise to the preamble.
3. Demodulate OOK bits.
4. Parse and CRC-check the frame.
5. Decode the payload.
6. Validate identity (at least 3 unique valid sequences by default).

### Target Payload Configuration

These settings tell the local receiver what it should be looking for:

| Setting | Description |
|---------|-------------|
| **Expected Terminal ID** | The ID the receiver must find in the decoded payload |
| **Expected Token** | The authentication token that must also match |
| **Expected Wavelength** | The wavelength the payload should declare |
| **Required Valid Frames** | Minimum number of unique valid decoded sequences before the candidate becomes IDENTIFIED |
| **Sequence Validation** | When enabled, duplicate or old sequences do not count as liveness |
| **Wavelength Validation** | When enabled, wavelength mismatch causes rejection |

> **Tip**: If `Expected Terminal ID` is left blank, the receiver will not validate terminal identity. This is only useful for raw signal testing. Leave it set to `RT-001` for normal operation.

---

## 7. Camera View

The camera view shows the simulated sensor image in real time.

### What You See

- **Background**: Simulated star field, sky gradient, and atmospheric haze.
- **Beacon Spot**: The remote terminal's optical beacon appears as a bright point source. Its intensity flickers at the chip rate as the OOK signal modulates it.
- **Candidate Overlays**: As the receiver detects and tracks candidates, coloured outlines and markers appear on the image.

### Candidate Colour Code

| Colour | State | Meaning |
|--------|-------|---------|
| Grey | SEEN / TENTATIVE | Just detected, not yet analysed |
| Yellow | SIGNAL_DETECTED / DECODING | Modulation detected, decoding in progress |
| Orange | IDENTITY_UNKNOWN | Frame decoded but identity not yet confirmed |
| Cyan | IDENTIFIED | Identity confirmed by digital decode |
| Blue | SELECTED / ACQUIRING | Target chosen, PTZ centering |
| **Green** | **ACQUIRED / TRACKING** | **Fully locked and tracking** |
| Amber | DEGRADED | Tracking but quality is dropping |
| Purple | REACQUIRING | Searching for lost target |
| Red | REJECTED | Identity mismatch — will not be acquired |
| Dark Red | LOST / EXPIRED | Track timed out |

### PTZ Crosshair

The central crosshair shows where the PTZ is currently pointing. During tracking, the beacon spot should be centred on this crosshair. The PTZ error (displacement of the spot from the crosshair) is minimised by the closed-loop tracking controller.

### Zoom and Pan

- **Scroll wheel** — zoom in/out on the camera view.
- **Right-click drag** — pan the view.
- **Double-click** on a candidate — select it to display its signal in the Signal Plot.

---

## 8. Signal and Telemetry Panels

### Signal Plot

The signal plot shows the temporal intensity history for the selected candidate (click on a candidate in the camera view or candidate list to select it).

**What you see:**
- **Raw Intensity** (grey) — raw per-frame intensity values from the candidate's blob history.
- **Background-Subtracted** (blue) — signal after background removal.
- **Normalised Signal** (green) — processed signal used by the demodulator (range ≈ 0–1).
- **Adaptive Threshold** (dashed red) — the threshold the OOK demodulator is using to decide bit = 0 or 1.
- **Bit Boundaries** (vertical grey lines) — where the demodulator believes each OOK chip starts and ends.
- **Frame Start Marker** (vertical cyan line) — where the demodulator found the preamble/sync.
- **SNR Annotation** — current SNR estimate in dB.

**Reading the signal**: A clean modulated signal looks like a square wave. Noise from scintillation adds fluctuations. A strong enough signal will show the ON/OFF chip pattern clearly. A heavily attenuated or turbulent signal will show poor modulation depth, making synchronisation and decoding unreliable.

### Telemetry Panel

The telemetry panel shows a comprehensive table of all per-candidate and global fields. Key fields to watch:

| Field | What to Look For |
|-------|-----------------|
| `frame_sync_state` | `SYNCHRONIZED` means the preamble was found |
| `frame_sync_confidence` | > 0.6 is reliable |
| `decode_state` | `FRAME_VALID` means CRC passed |
| `decode_reason` | `OK`, or the specific failure reason |
| `estimated_chip_rate_hz` | Should be close to the configured RT chip rate |
| `valid_frame_count` | Increases with each unique valid decoded frame |
| `invalid_frame_count` | Increases with CRC failures, wrong protocol, etc. |
| `identity_state` | The definitive identity verdict |
| `snr` | Signal-to-noise ratio (higher is better; < 3 dB = unreliable) |

---

## 9. Running a Simulation — Step-by-Step Walkthrough

This walkthrough guides you through a complete acquisition scenario.

### Step 1 — Set Up the Remote Terminal

1. Open the **Remote Terminal Panel**.
2. Set **Terminal ID** = `RT-001`.
3. Set **Token** = `ALPHA-7`.
4. Set **Chip Rate** = `12.0 Hz`.
5. Ensure **Beacon Enabled** = On.
6. Set the angular position so the RT is within the search field of regard.

### Step 2 — Set Up the Local Terminal

1. Open the **Local Terminal Panel → Target Payload Configuration**.
2. Set **Expected Terminal ID** = `RT-001`.
3. Set **Expected Token** = `ALPHA-7`.
4. Set **Required Valid Frames** = `3`.
5. Ensure **Sequence Validation** = On.

### Step 3 — Start the Simulation

Click **Start** in the toolbar or press `F5`.

**What happens automatically:**
1. The PTZ begins scanning the search pattern (RANDOM by default).
2. The camera renders frames at 30 fps including the RT beacon spot.
3. When the beacon enters the FOV, the candidate detector creates a new track.
4. The candidate advances through the lifecycle states (SEEN → TENTATIVE → SIGNAL_DETECTED → DECODING...).
5. As the decoder accumulates signal history, it attempts to synchronise to the preamble.
6. Once synchronised, OOK demodulation begins.
7. After 3 valid unique frames, the candidate becomes **IDENTIFIED**.
8. The PTZ begins centering the candidate (ACQUIRING).
9. When both identity and spatial locks are held simultaneously, the system transitions to **ACQUIRED** → **TRACKING**.

### Step 4 — Observe Tracking

Once in TRACKING state:
- The beacon spot should be centred on the PTZ crosshair.
- The Telemetry panel shows `identity_state = VALID_TARGET` continuously.
- The signal plot shows a clean modulated signal with the adaptive threshold correctly set.

### Step 5 — Test Disturbance

Use the **Disturbance Panel** to introduce:
- **Attenuation** — reduces signal power. The SNR drops. If severe, the system enters DEGRADED.
- **Scintillation** — adds intensity fluctuations. Watch the signal plot's raw intensity jitter.
- **Wander** — displaces the centroid. Watch the tracking error (PTZ crosshair vs. spot).

### Step 6 — Test Reacquisition

1. Click **Disable RT-001** in the Remote Terminal Panel.
2. The beacon spot disappears. The candidate quickly enters DEGRADED, then REACQUIRING.
3. The PTZ sweeps ±2°, then ±5°, then ±10° around the predicted position.
4. Click **Enable Decoy (RT-999)**. The decoy appears near the predicted position.
5. In the Candidate List, observe that RT-999 is decoded but appears with status **REJECTED** (identity mismatch).
6. Click **Enable RT-001** again (and disable decoy).
7. RT-001 is found, decoded with a new sequence number > the last seen, and reacquired.
8. The system returns to **TRACKING**.

---

## 10. Interpreting Candidate States

The **Candidate List** shows all tracks the receiver is maintaining. Here is what each state means for you:

| State | What Happened | What to Expect Next |
|-------|--------------|---------------------|
| **SEEN** | A blob was just detected in the image | Will become TENTATIVE if it persists |
| **TENTATIVE** | The blob has been stable for ≥2 frames | Signal analysis begins |
| **SIGNAL_DETECTED** | Beacon-like modulation found in intensity history | Frame decoder activates |
| **DECODING** | Actively trying to parse a complete beacon frame | Waiting for preamble, OOK decode, CRC |
| **IDENTITY_UNKNOWN** | A frame was decoded but identity not yet confirmed | Accumulating valid frame count |
| **IDENTIFIED** | ≥3 unique valid frames with correct terminal ID and token | Will be selected for acquisition |
| **SELECTED** | Chosen by the selection engine | PTZ begins centering |
| **ACQUIRING** | PTZ is moving to centre the candidate | Waiting for dual lock |
| **ACQUIRED** | Both identity and spatial locks held | Transitioning to TRACKING |
| **TRACKING** | Stable closed-loop tracking | Normal operating state |
| **DEGRADED** | Quality metrics falling | Monitoring closely; may recover or reacquire |
| **REACQUIRING** | Track lost — searching for target | Will try to re-find and re-identify |
| **REJECTED** | Wrong terminal ID, wrong token, or wrong protocol | Will not be used; track eventually expires |
| **LOST** | Reacquisition timeout exceeded | Track expired |
| **EXPIRED** | Permanently retired | Removed from list |

### Why Are There Multiple Candidates?

The detector finds all bright blobs in the image — stars, clutter, and the real RT. Each one gets its own candidate track. Most will remain SEEN or TENTATIVE and eventually expire. Only the one that passes full digital decoding and identity validation will become IDENTIFIED and ACQUIRED.

---

## 11. Interpreting Identity and Acquisition Status

### Identity States

| State | Meaning | Cause |
|-------|---------|-------|
| `VALID_TARGET` | All checks passed | Correct ID, token, wavelength, new sequence |
| `WRONG_TERMINAL` | Terminal ID mismatch | Decoded `RT-999` but expected `RT-001` |
| `WRONG_TOKEN` | Token mismatch | Token in payload doesn't match expected |
| `WRONG_PROTOCOL` | Protocol version or message type rejected | Firmware mismatch |
| `WAVELENGTH_MISMATCH` | Declared wavelength outside tolerance | Check RT wavelength config |
| `INVALID_SEQUENCE` | Duplicate or old sequence number | Same frame received twice (channel echo) |
| `UNKNOWN` | Not enough data, CRC failed, or low confidence | Signal too weak; wait for better SNR |

### Acquisition Locks

**Identity Lock** is acquired when:
- At least N unique valid frames decoded (N = `required_valid_frames`, default 3).
- All identity fields match: terminal ID, token, wavelength, sequence.
- CRC passed on all counted frames.

**Spatial Lock** is acquired when:
- Blob visible in current frame.
- SNR ≥ minimum acquisition SNR.
- Centroid within the acquisition window (close to frame centre).
- Centroid motion is physically plausible.

**ACQUIRED** = Identity Lock **AND** Spatial Lock.

> **A candidate with perfect optical quality but the wrong terminal ID will never be acquired.**

---

## 12. Scenario Events

### Disabling the Target

Click **Disable RT-001** to simulate the target going out of view (obstacle, attitude change, power-off). The receiver will:
1. Lose the optical blob (missed frames accumulate).
2. Enter DEGRADED state.
3. Enter REACQUIRING state and begin the staged search.

### Enabling a Decoy

Click **Enable Decoy** to place `RT-999` near the last known position of `RT-001`. This tests identity-gated reacquisition. The receiver will:
1. Detect the new blob.
2. Decode its payload (getting `terminal_id = RT-999`).
3. Reject it as `WRONG_TERMINAL`.
4. Continue searching for `RT-001`.

### Re-enabling the Target

When `RT-001` is re-enabled, the receiver will:
1. Detect the blob.
2. Decode the payload (now with a sequence number higher than when it disappeared).
3. Validate: correct identity + new sequence + spatial gate passes.
4. Merge back to the old track.
5. Return to TRACKING.

> **Note**: If you re-enable RT-001 with the *same* sequence number it had when it disappeared, reacquisition will fail (duplicate sequence = no new liveness). This is by design.

---

## 13. Headless Mode

Headless mode runs the full simulation without any GUI. It is used for:
- Automated acceptance testing.
- Parameter sweeps.
- Long overnight runs.
- CI/CD integration.

### Basic Usage

```bash
python -m simulation.headless --duration 300
```

### With a YAML Config File

```bash
python -m simulation.headless --config scenarios/decoy_test.yaml --duration 300
```

### Programmatic Usage

```python
from simulation.headless import HeadlessSimulation

sim = HeadlessSimulation(config=my_config)

def on_tick(t, output):
    tel = output.telemetry
    print(f"t={t:.1f}  state={tel.system_state}  "
          f"id={tel.active_decoded_terminal_id}  "
          f"seq={tel.last_sequence_number}")

result = sim.run(duration_s=300.0, callback=on_tick)
print(f"Final state: {result.final_state}")
```

### Running the Test Suite

```bash
# All tests
python -m pytest -q

# Only the acceptance test
python -m pytest tests/test_upgrade_acceptance.py -v

# Only identity pipeline tests
python -m pytest tests/test_identity_pipeline.py -v
```

---

## 14. Troubleshooting

### The receiver never finds the target

**Possible causes:**
- The RT is outside the search field of regard. Check search region bounds in the Acquisition config.
- The chip rate is too low — the beacon frame is too long for the history buffer. A warning should appear in the status bar.
- The SNR is too low (too much attenuation). Reduce atmospheric extinction or increase RT power.
- The expected terminal ID doesn't match the RT's configured ID. Check both panels.

### The candidate is stuck in IDENTITY_UNKNOWN

**Possible causes:**
- Not enough unique valid frames yet. Wait — or reduce `required_valid_frames` in the config.
- The expected token is non-empty but the RT's token is different. Check both configurations.
- Wavelength validation is enabled but wavelength values don't match. Set both to `1550`.

### The candidate keeps becoming REJECTED

**This is correct if**: the RT's terminal ID doesn't match the local terminal's `expected_terminal_id`. It is supposed to be rejected.

**If it's unexpected**: verify that the RT panel shows Terminal ID = `RT-001` and the local panel shows Expected Terminal ID = `RT-001`.

### The beacon signal never appears modulated in the Signal Plot

**Possible causes:**
- The chip rate is so low that not enough chips have arrived in the current history window. The signal plot may look flat. Increase chip rate or wait longer.
- The signal is too attenuated to show modulation depth. Reduce disturbance.

### Reacquisition never succeeds after disabling the target

**Possible causes:**
- The target was re-enabled without a sequence number advance. Check that the RT's sequence counter is advancing.
- The spatial gate is too small. The RT reappeared outside the expected position. Increase `spatial_gate_px` in Reacquisition config.
- The reacquisition timeout is too short. Increase `reacquisition_total_timeout_s`.

---

## 15. Keyboard Shortcuts

| Shortcut | Action |
|----------|--------|
| `F5` | Start / Resume simulation |
| `F6` | Pause simulation |
| `F7` | Step one frame (when paused) |
| `Escape` | Stop simulation |
| `Ctrl+R` | Reset to initial state |
| `Ctrl+S` | Save current configuration |
| `Ctrl+O` | Open configuration file |
| `Ctrl+E` | Export telemetry log to CSV |
| `Space` | Toggle beacon enable/disable |
| `D` | Toggle decoy terminal |
| `+` / `-` | Increase / decrease camera view zoom |
| `H` | Return PTZ to home position |
| `Click` on candidate | Select candidate for signal display |
| `Double-click` on candidate | Zoom camera view to candidate |

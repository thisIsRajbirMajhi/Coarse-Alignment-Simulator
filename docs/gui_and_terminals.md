# GUI and Terminals

> **Scope**: GUI architecture, remote and local terminal panels, headless simulation runner, and the controller/view pattern.

---

## 1. Overview

The GUI is a PyQt5 (or equivalent) application that visualises the simulation in real time. It does not implement any simulation logic — all physics, sensing, detection, and tracking run in the simulation layer. The GUI reads telemetry and renders it.

```
HeadlessSimulation / SimulationEnvironment
    │  simulation tick
    ▼
LocalTerminalOutput + RemoteTerminalOutput
    │  (telemetry, PTZ state, candidate data)
    ▼
GUI Controllers
    │  bridge between simulation and view
    ▼
GUI Panels / Views
    │  render telemetry to user
    ▼
User interactions → GUI Controllers → configuration changes
```

---

## 2. Directory Structure

```
gui/
├── app.py                   Application entry point (QApplication)
├── main_window.py           MainWindow — top-level window layout
├── styles.py                Stylesheet definitions
│
├── application/             Application-level controllers
│
├── controllers/             Simulation ↔ GUI bridge controllers
│   ├── simulation_controller.py
│   ├── remote_terminal_controller.py
│   └── local_terminal_controller.py
│
├── panels/                  Individual UI panels (QWidget subclasses)
│   ├── remote_terminal_panel.py
│   ├── local_terminal_panel.py
│   ├── candidate_panel.py
│   ├── telemetry_panel.py
│   ├── signal_panel.py
│   ├── acquisition_panel.py
│   └── tracking_panel.py
│
├── views/                   Plot and visualisation widgets
│   ├── camera_view.py       Live camera feed
│   ├── signal_plot.py       Intensity history plot
│   ├── lifecycle_view.py    Candidate lifecycle status
│   └── metrics_plot.py      Tracking metrics over time
│
├── windows/                 Dialog windows
│   ├── config_dialog.py
│   └── scenario_dialog.py
│
├── presentation/            View-model / data binding helpers
└── simulation/              GUI-side simulation runner wrappers
```

---

## 3. Remote Terminal Panel (`panels/remote_terminal_panel.py`)

Displays and controls the remote terminal's configuration and live status.

### Displayed Information

| Field | Source |
|-------|--------|
| Terminal ID | `RemoteTerminalConfig.beacon.tid` |
| Token | `RemoteTerminalConfig.beacon.token` |
| Chip rate (Hz) | `RemoteTerminalConfig.beacon.chip_rate_hz` |
| Wavelength (nm) | `RemoteTerminalConfig.beacon.wavelength_nm` |
| Sequence counter | `RemoteTerminal.current_sequence` |
| Current OOK chip | `RemoteTerminal.current_chip` |
| Angular position (az, el) | RT's angular position in scene (not given to LT) |
| Beacon enabled | toggle |
| Frame duration | computed from config |

### Controls

- Enable / disable beacon transmission
- Adjust chip rate (live)
- Inject scenario event (disappear / reappear)
- Trigger decoy terminal enable

> **Note**: The remote terminal panel reads from `RemoteTerminal` directly. This is allowed because it is a GUI diagnostics panel — not part of the receiver pipeline. The local terminal never reads these values.

---

## 4. Local Terminal Panel (`panels/local_terminal_panel.py`)

Displays the local terminal's receiver state and tracking status.

### System State Section

| Field | Source |
|-------|--------|
| System state | `SystemTelemetry.system_state` |
| Active observation ID | `SystemTelemetry.active_observation_id` |
| Decoded terminal ID | `SystemTelemetry.active_decoded_terminal_id` |
| Identity state | `SystemTelemetry.identity_state` |
| Identity confidence | `SystemTelemetry.identity_confidence` |
| Frame sync state | `SystemTelemetry.frame_sync_state` |
| Last sequence | `SystemTelemetry.last_sequence_number` |
| Acquisition state | `SystemTelemetry.acquisition_state` |
| Tracking state | `SystemTelemetry.tracking_state` |

### Candidate List

A scrollable list of all current candidate tracks, each showing:

| Field | Source |
|-------|--------|
| Observation ID | `CandidateTelemetry.observation_id` |
| Lifecycle state | `CandidateTelemetry.lifecycle_state` |
| Decoded terminal ID | `CandidateTelemetry.decoded_terminal_id` |
| Identity state | `CandidateTelemetry.identity_state` |
| Signal quality | `CandidateTelemetry.signal_quality` |
| SNR | `CandidateTelemetry.snr` |
| Valid frames | `CandidateTelemetry.valid_frame_count` |
| Sequence | `CandidateTelemetry.sequence_number` |

### Target Payload Configuration

Editable fields (changes applied at next simulation tick):

```
Expected Terminal ID:   [RT-001]
Expected Token:         [ALPHA-7]
Expected Wavelength:    [1550.0] nm
Required Valid Frames:  [3]
Sequence Validation:    [✓]
Wavelength Validation:  [✓]
```

---

## 5. Camera View (`views/camera_view.py`)

Renders the live camera image with overlays:

```
Raw camera frame (grayscale / false-colour)
    + detected blob outlines (dashed bounding box per candidate)
    + centroid markers (coloured by lifecycle state)
    + acquisition window indicator
    + PTZ crosshair
    + tracking error arrow
    + search scan pattern preview
```

### Candidate Colour Code

| Lifecycle State | Colour |
|----------------|--------|
| SEEN / TENTATIVE | Grey |
| SIGNAL_DETECTED / DECODING | Yellow |
| IDENTITY_UNKNOWN | Orange |
| IDENTIFIED | Cyan |
| SELECTED / ACQUIRING | Blue |
| ACQUIRED / TRACKING | Green |
| DEGRADED | Amber |
| REACQUIRING | Purple |
| REJECTED | Red |
| LOST / EXPIRED | Dark Red |

---

## 6. Signal Plot (`views/signal_plot.py`)

Plots the temporal signal for the active candidate:

- Raw intensity history (grey)
- Background-subtracted signal (blue)
- Normalised signal (green)
- Adaptive demodulation threshold (dashed red)
- Recovered bit boundaries (vertical grey lines)
- Frame start marker (vertical cyan line)
- SNR annotation

---

## 7. Telemetry Panel (`panels/telemetry_panel.py`)

Compact read-only display of all `SystemTelemetry` fields, updated every GUI frame (30 Hz or simulation rate, whichever is slower).

---

## 8. Headless Simulation (`simulation/headless.py`)

The `HeadlessSimulation` runner executes the full simulation without a GUI — used for automated tests and batch runs.

```python
class HeadlessSimulation:
    def __init__(self, config: SimulationConfig):
        self.scenario = Scenario(config.scenario)
        self.environment = SimulationEnvironment(config.environment)
        self.local_terminal = LocalTerminal(config.local_terminal)

    def run(self, duration_s: float, callback=None) -> SimulationResult:
        t = 0.0
        dt = 1.0 / config.camera.fps
        while t < duration_s:
            self.scenario.tick(dt)
            frame = self.environment.render(
                self.scenario, self.local_terminal.ptz_pose
            )
            output = self.local_terminal.step(frame)
            if callback:
                callback(t, output)
            t += dt
        return SimulationResult(...)
```

### Key Properties

- No GUI, no display
- Full physics: disturbance, OOK, sensor model
- All telemetry available via `output.telemetry`
- Reproducible via seeded RNG (`common/rng.py`)
- Used by all acceptance tests

---

## 9. SimulationController (`controllers/simulation_controller.py`)

The bridge between the simulation loop and the GUI:

```python
class SimulationController(QObject):
    telemetry_updated = pyqtSignal(SystemTelemetry)
    frame_updated = pyqtSignal(CameraFrame)

    def _on_tick(self):
        frame = self.environment.render(...)
        output = self.local_terminal.step(frame)
        self.telemetry_updated.emit(output.telemetry)
        self.frame_updated.emit(frame)
```

The simulation runs in a `QThread` at the configured frame rate. GUI updates are delivered via Qt signals to avoid threading issues.

---

## 10. Configuration Dialog (`windows/config_dialog.py`)

Allows the user to edit `LocalTerminalConfig` at runtime:

- All `TargetPayloadConfig` fields are editable
- `AcquisitionConfig`, `TrackingConfig`, `ReacquisitionConfig` sub-panels
- Timing coherence is validated before applying:
  ```
  If chip_rate_hz change would make history insufficient → warn + prevent
  ```
- Changes are serialised via `config.to_dict()` and reloaded via `LocalTerminalConfig.from_dict()`

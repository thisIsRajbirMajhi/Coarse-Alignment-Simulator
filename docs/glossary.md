# Glossary and Acronyms

> **Scope**: Definitions of all domain-specific terms, acronyms, and system-specific vocabulary used throughout the documentation and codebase.

---

## Acronyms

| Acronym | Full Form | Context |
|---------|-----------|---------|
| **ADC** | Analogue-to-Digital Converter | Sensor quantisation |
| **AOS** | Acquisition of Signal | When the beacon signal is first detected |
| **BEACON-N** | Locally generated observation identifier | e.g. `BEACON-001` |
| **BER** | Bit Error Rate | Fraction of incorrectly decoded bits |
| **CRC** | Cyclic Redundancy Check | Frame integrity verification |
| **CT** | Centroid Tracking | Tracking algorithm based on intensity centroid |
| **DN** | Digital Number | Raw pixel value (ADC output) |
| **ECEF** | Earth-Centred Earth-Fixed | Reference coordinate frame |
| **FPA** | Focal Plane Array | Detector array type |
| **FOV** | Field of View | Camera's visible angular region |
| **FOR** | Field of Regard | Total angular region the PTZ can address |
| **FSO** | Free-Space Optical | Wireless optical communication |
| **GUI** | Graphical User Interface | The simulator's visual interface |
| **ISL** | Inter-Satellite Link | Optical communication between platforms |
| **KF** | Kalman Filter | Recursive optimal state estimator |
| **LOS** | Line of Sight | Direct optical path between terminals |
| **LT** | Local Terminal | The receiver / camera platform |
| **NRZ** | Non-Return-to-Zero | OOK encoding where bit persists for full chip period |
| **OOK** | On-Off Keying | Binary amplitude modulation: full intensity = 1, dark = 0 |
| **PAT** | Pointing, Acquisition, and Tracking | The complete PTZ control problem |
| **PID** | Proportional-Integral-Derivative | Closed-loop control algorithm |
| **PRNU** | Photo-Response Non-Uniformity | Per-pixel gain variation in the sensor |
| **PSF** | Point Spread Function | The optical blur kernel of the camera |
| **PTZ** | Pan-Tilt-Zoom | The gimbal/actuator system |
| **RT** | Remote Terminal | The transmitter |
| **RT-001** | Remote Terminal, unit 001 | Default target terminal ID |
| **RT-999** | Remote Terminal, unit 999 | Default decoy terminal ID in tests |
| **RX** | Receive / Receiver | |
| **SNR** | Signal-to-Noise Ratio | Signal power divided by noise power |
| **TX** | Transmit / Transmitter | |
| **UTC** | Coordinated Universal Time | Time reference |

---

## Domain Terms

### A

**Acquisition**
The process of bringing a detected and identified target into stable closed-loop tracking. Requires both identity lock and spatial lock simultaneously (dual lock). Progresses the candidate state from IDENTIFIED → SELECTED → ACQUIRING → ACQUIRED.

**Acquisition Window**
The pixel region around the frame centre within which the candidate centroid must fall for spatial lock to be granted. Typically a circle or square of radius `acquisition_window_px`.

**Adaptive Threshold**
A demodulation threshold estimated from local signal statistics (e.g., midpoint of 10th and 90th percentile of intensity history) rather than a fixed preset value. Self-calibrates to the current signal level.

**Angular Model**
The conversion between pixel coordinates in the sensor image and angular offsets in the world. Derived from `fov / resolution`. Units: μrad/pixel.

### B

**Background Estimation**
The process of estimating and removing the slowly-varying scene background from the camera image before detecting candidates. Uses morphological operations or percentile statistics over a local neighbourhood.

**Background-Subtracted Signal**
The temporal intensity signal after subtracting the estimated background level. Isolates the modulated beacon component from the steady-state background.

**Backlash**
Mechanical dead zone in the PTZ actuator when reversing direction. Modelled as a minimum displacement that must be overcome before motion resumes.

**Beacon**
The modulated optical signal transmitted by the Remote Terminal, encoded as a framed binary message using OOK modulation.

**Beacon Frame**
One complete encoded transmission unit: `PREAMBLE + SYNC + PROTOCOL_VERSION + MESSAGE_TYPE + PAYLOAD_LENGTH + PAYLOAD + CRC-8`.

**Beam Wander**
Low-frequency random displacement of the optical beam's pointing direction due to large-scale atmospheric turbulence eddies. Appears as slow centroid drift in the camera image.

### C

**Candidate**
A locally tracked blob in the camera image that the receiver is evaluating as a potential target. Each candidate has its own `CandidateTrack` data record and `CandidateState`.

**Candidate Association**
The process of matching newly detected blobs in a camera frame to existing candidate track records, using spatial proximity and appearance similarity.

**Candidate Lifecycle**
The complete set of states a candidate track can occupy, from first detection (`SEEN`) to stable tracking (`TRACKING`), rejection (`REJECTED`), or loss (`LOST`/`EXPIRED`).

**Chip**
One OOK symbol (duration = 1/chip_rate_hz seconds). Corresponds to one bit in NRZ encoding.

**Chip Rate**
The number of OOK chips transmitted per second (Hz). Determines how fast the beacon data is transmitted. Also determines how many camera frames correspond to one chip at a given fps.

**Compact Binary Payload**
The production-mode beacon payload format. A deterministic binary structure encoding terminal_id, token, wavelength, and sequence_number without JSON overhead.

**CRC-8/MAXIM**
The specific CRC-8 variant (polynomial `0x31`, Dallas/Maxim) used for frame integrity checking. Detects all single-bit errors and most multi-bit errors in the frame.

### D

**Dark Current**
Thermally generated electrons in the sensor in the absence of photons. Adds a slow, temperature-dependent noise floor to the pixel values.

**Decoded Terminal ID**
The terminal ID string (`e.g. "RT-001"`) extracted from a successfully decoded beacon payload. Distinct from the locally generated `observation_id`.

**Degradation**
A candidate/system state indicating that tracking is continuing but quality metrics are falling below thresholds. May recover or escalate to reacquisition.

**Disturbance / Channel**
The atmospheric layer between the remote and local terminals. Applies attenuation, scintillation, beam wander, and noise to the optical beam.

**Dual Lock**
The simultaneous satisfaction of both identity lock and spatial lock. Required for a candidate to transition from ACQUIRING to ACQUIRED.

### E

**Encoder Noise**
Random error in the PTZ position encoder's reported angle. Modelled as Gaussian with σ = `encoder_sigma`.

**Extinction Coefficient**
The atmospheric parameter (dB/km) governing exponential power attenuation along the propagation path.

**Expired**
Terminal candidate state. The track record has been permanently removed from the active pool. No further updates occur.

### F

**False Alarm**
A detected blob that is not the real beacon target. Examples: stars, lens flares, noise clusters. The receiver must suppress or eventually reject these.

**Field of Regard (FOR)**
The total angular region that the PTZ can point to given its mechanical limits. Larger than the instantaneous FOV.

**Field of View (FOV)**
The instantaneous angular region visible to the camera at its current PTZ pointing. Size determined by focal length, sensor dimensions, and pixel pitch.

**Frame Duration**
The time required to transmit one complete beacon frame at the configured chip rate: `n_bits / chip_rate_hz` seconds.

**Frame Start**
The sample index in the normalised signal array where the synchroniser has determined the beacon frame begins (after the preamble).

### G

**God View**
A top-down omniscient view of the simulation scene showing both terminals and the propagation geometry. This is a diagnostic GUI display only — the local terminal does not receive this information.

### H

**History Buffer**
The bounded circular deque of per-frame measurements (intensity, centroid, timestamp) maintained for each candidate track. Size is computed to ensure coverage of at least two complete beacon frames.

**Home Position**
The PTZ default pointing angle when no target is being tracked. Defined by `home_pan` and `home_tilt` in `PTZConfig`.

### I

**Identity**
The verified knowledge of which remote terminal is being tracked, derived solely from a successfully decoded beacon payload. Not derivable from optical appearance alone.

**Identity Confidence**
A scalar 0–1 representing the receiver's current level of certainty in the target's identity. Increments on valid frames, decrements on failures.

**Identity Fail Streak**
The count of consecutive frames on which identity validation failed. Used to trigger degradation and reacquisition.

**Identity Lock**
The state in which `valid_frame_count >= required_valid_frames` and all identity fields have matched. One of the two conditions for dual-lock acquisition.

**Identity Swap**
An event where the decoded `terminal_id` changes mid-tracking (e.g., RT-001 → RT-007). This immediately breaks the identity lock and triggers reacquisition.

**Identity-Gated Reacquisition**
The requirement that reacquisition can only restore a lock if the newly found candidate's decoded identity matches the old target and provides a new (advancing) sequence number.

**Integrated Intensity**
The sum of pixel values over the candidate's bounding box, minus background. Proportional to total optical power collected.

**is_new_frame**
A mandatory boolean field in `BeaconDecodeResult`. True only if the decoded sequence_number is strictly greater than the track's `last_valid_sequence`. Duplicate or old frames have `is_new_frame = False`.

### K

**Kalman Filter**
A recursive Bayesian estimator used for centroid and velocity estimation. Maintains a state estimate and covariance, predicting the next position and updating from measurements.

### L

**Legacy Optical Identification**
The (disabled by default) fallback mode in which a candidate can be promoted to IDENTIFIED based on optical quality without digital decoding. Controlled by `legacy_optical_identification_enabled`. Must be `False` in all production runs.

**Liveness**
The evidence that the target is currently alive and transmitting, provided by a new, unique, valid decoded sequence number. Duplicate sequences do not provide liveness.

**Local Terminal**
The receiver platform. Processes camera images to detect, identify, and track the remote terminal. Never uses ground truth from the remote terminal.

**Lost**
A terminal candidate/system state indicating that reacquisition failed (timeout). The target is no longer being searched for from this track.

### M

**Matched Filtering**
Signal processing technique for detecting a known pattern (preamble) by cross-correlating the received signal with a template of the expected pattern.

**Modulation Depth**
The relative amplitude of the OOK signal modulation: `(I_high - I_low) / I_high`. Low modulation depth (< 0.2) makes OOK demodulation unreliable.

**Modulation Detection**
A lightweight heuristic check (before full synchronisation) that determines whether the candidate's intensity history shows any beacon-like modulation pattern.

### N

**NRZ (Non-Return-to-Zero)**
OOK encoding where the optical intensity remains at the chip value (HIGH or LOW) for the full chip period. The simpler of the two common OOK encoding schemes.

### O

**Observation ID**
Locally generated identifier for a candidate track. Format: `BEACON-N`. Never derived from the remote terminal's identity — assigned sequentially when a new track is created.

**OOK (On-Off Keying)**
Binary amplitude modulation. `bit = 1` → optical intensity ON. `bit = 0` → optical intensity OFF (near dark current).

**OOK Demodulator**
The component that converts a synchronised, normalised signal into a recovered bit sequence by comparing each chip's intensity to an adaptive threshold.

**Optical Measurement**
A structured record of the photometric and geometric properties of a detected blob in one camera frame: centroid, SNR, area, spectral estimate, etc.

**Optical Path**
The information channel from camera pixels through blob detection, centroid estimation, Kalman filter, to PTZ control. Answers "where is the target?"

### P

**Payload**
The data content of a beacon frame, carrying terminal_id, token, wavelength_nm, and sequence_number.

**Payload Codec**
The serialisation/deserialisation implementation for the beacon payload. `PayloadCodec` handles compact binary format.

**Persistence**
The requirement that a candidate must satisfy identity conditions for multiple consecutive unique frames before being considered IDENTIFIED. Prevents lucky single-frame CRC passes from triggering acquisition.

**Photon Shot Noise**
Fundamental quantum noise in photon detection, following Poisson statistics. Proportional to the square root of the photon count.

**Point Spread Function (PSF)**
The optical impulse response of the camera system — how a perfect point source appears spread over pixels due to diffraction and aberrations.

**Preamble**
The leading sequence of a beacon frame: 8 bytes of `0xAA` (alternating `10101010` bits). Used by the synchroniser for timing recovery and chip rate estimation.

**Predicted Position**
The Kalman filter's estimate of where the candidate centroid will be in the *next* camera frame, based on current position and velocity estimates.

**Protocol Version**
A byte in the beacon frame header indicating the beacon protocol version. The receiver rejects frames with unsupported versions.

**PTZ (Pan-Tilt-Zoom)**
The gimbal actuator system that points the camera. In this simulator, typically pan-tilt only (no zoom). Controlled by the tracking PID controller.

### Q

**Quantum Efficiency (QE)**
The fraction of incident photons that generate electron-hole pairs in the sensor. Typical values: 0.4–0.8 for silicon-based sensors at 1550 nm (InGaAs).

### R

**Read Noise**
Electronic noise introduced during the pixel readout process, independent of illumination level. Dominates at low light levels.

**Reacquisition**
The process of recovering tracking lock after it has been broken. Involves a staged spatial search around the predicted position, followed by identity gating before lock restoration.

**Reacquisition Spatial Gate**
The maximum distance (in pixels) between a new candidate's measured position and the old track's predicted position for a reacquisition merge to be accepted.

**Remote Terminal**
The transmitter platform. Generates the beacon signal, applies OOK modulation to the optical beam, and models platform motion and beam geometry.

**Rejected**
Terminal candidate state for tracks that have been definitively identified as belonging to the wrong terminal (WRONG_TERMINAL, WRONG_TOKEN, WRONG_PROTOCOL).

**Rhythmic Jitter**
Timing uncertainty in the PTZ actuator latency. Modelled as Gaussian with σ = `latency_jitter`.

**Rytov Variance**
A measure of scintillation strength: `σ_χ² = 1.23 Cn² k^(7/6) L^(11/6)`. Determines the statistical distribution of received intensity fluctuations.

### S

**Scintillation**
Random temporal and spatial fluctuations in received optical intensity caused by refractive index variations in the turbulent atmosphere.

**Search Manager**
The module responsible for generating PTZ scan commands during the SEARCHING phase and during reacquisition staged search.

**Selection Engine**
The component that chooses which candidate to acquire from among multiple IDENTIFIED candidates. Prioritises correct digital identity over optical brightness.

**Sequence Number**
A monotonically increasing integer in the beacon payload. Each new beacon frame transmission increments this counter. Used to detect duplicates and verify liveness.

**Signal Quality**
A scalar 0–1 representing the quality of the temporal signal for a candidate: combination of SNR, modulation depth, and sample count.

**Spatial Lock**
The state in which the candidate is visible, stable, and centred within the acquisition window. One of the two conditions for dual-lock acquisition.

**Spectral Estimate**
An estimate of the beacon's wavelength derived from the optical measurements (spectral response, colour ratio, etc.), not from the decoded payload.

**Streaming Decoder**
A decoder that processes only new signal samples since its last update, maintaining an internal `last_processed_sample_index` to avoid re-feeding old history.

**Sub-Pixel Centroid**
A centroid position estimated with resolution finer than one pixel, computed by intensity-weighted averaging of pixel coordinates within the blob.

**SYNC Word**
A 2-byte sequence (`0xEB 0x90`) immediately following the preamble in the beacon frame. Marks the definitive start of the frame header.

**System State Machine**
The top-level state machine governing the local terminal's overall mode: IDLE, SEARCHING, ACQUIRING, TRACKING, DEGRADED, REACQUIRING, LOST, FAULT.

### T

**Target Payload Config** (`TargetPayloadConfig`)
The configuration structure defining what the local terminal expects to decode from the beacon: expected terminal ID, token, wavelength, required frame count, etc. A first-class field of `LocalTerminalConfig`.

**Telemetry**
Runtime data exported by the local terminal describing the current state of all candidate tracks and the overall system. Consumed by the GUI and available to test harnesses.

**Temporal Signal Extractor**
The component that processes the bounded history of per-frame intensity measurements for a candidate and produces background-subtracted, normalised signal and SNR estimates.

**Token**
An authentication string included in the beacon payload that the receiver must match to validate identity. Prevents impersonation by other terminals transmitting the correct terminal ID.

**Track**
A `CandidateTrack` record — the data structure representing the receiver's complete knowledge about one detected object.

**Tracking**
The stable closed-loop PTZ control phase. The PTZ is driven by the Kalman-filtered centroid of the target. Identity monitoring continues in the background.

### U

**Update Rate**
The frequency (Hz) at which the PTZ control loop executes. Independent of camera frame rate; typically the same (30 Hz).

### V

**Valid Frame Count**
The count of unique valid beacon frames (passing all identity checks with a new sequence number) for a candidate. Must reach `required_valid_frames` for identity lock.

**Vignetting**
Radial intensity roll-off from the centre to the edges of the sensor image, caused by optical geometry. Modelled in `environment/vignetting.py`.

### W

**Wander**
See *Beam Wander*.

**Wavelength Consistency**
A measure of agreement between the decoded beacon wavelength (from payload) and the measured wavelength (from spectral estimate). Used for supplementary quality scoring, not primary identity.

**Wavelength Tolerance**
The acceptance window (nm) around `expected_wavelength_nm` within which the decoded payload wavelength is considered valid.

### Z

**Zero-Crossing**
A point where the preamble autocorrelation crosses zero. The spacing between zero-crossings is used to estimate the chip rate.

# Coarse-Alignment-Simulator — Documentation

This documentation provides a complete, deep reference for the **Coarse-Alignment-Simulator** system — a high-fidelity end-to-end optical-communication acquisition and tracking simulator.

---

## Document Index

### 📖 User Documentation

| File | Scope |
|------|-------|
| [`user_manual.md`](./user_manual.md) | Complete operator manual: installation, GUI usage, interpreting states, running scenarios, troubleshooting |
| [`configuration_reference.md`](./configuration_reference.md) | Every configuration parameter: type, unit, valid range, default, and description |
| [`glossary.md`](./glossary.md) | All domain terms, acronyms, and system-specific vocabulary |

### 🔧 Technical Documentation

| File | Scope |
|------|-------|
| [`engineering_report.md`](./engineering_report.md) | Design decisions, Phase-2 rationale, wire protocol spec, signal processing analysis, known limitations |
| [`architecture_overview.md`](./architecture_overview.md) | Top-level system architecture, signal flow, two-path model, module map |
| [`remote_terminal.md`](./remote_terminal.md) | Remote terminal: beacon generation, OOK transmission, optics, motion, scenario |
| [`local_terminal.md`](./local_terminal.md) | Local terminal: full receiver pipeline from camera frame to tracking state |
| [`camera_and_sensor_system.md`](./camera_and_sensor_system.md) | Camera model, sensor physics, frame pipeline, optical measurement |
| [`detection_and_searching.md`](./detection_and_searching.md) | Search management, candidate detection, frame processing |
| [`candidate_system.md`](./candidate_system.md) | Candidate data model, association, lifecycle state machine, telemetry |
| [`signal_processing_pipeline.md`](./signal_processing_pipeline.md) | Temporal signal extraction, synchronisation, OOK demodulation, streaming decoder |
| [`beacon_protocol.md`](./beacon_protocol.md) | Shared beacon protocol: frame format, compact payload codec, CRC-8, timing |
| [`identity_and_acquisition.md`](./identity_and_acquisition.md) | Frame parsing, payload decoding, identity validation, dual-lock acquisition |
| [`tracking.md`](./tracking.md) | Image-based tracking, PTZ control, identity monitoring, identity swap, degradation |
| [`reacquisition.md`](./reacquisition.md) | Identity-gated reacquisition, staged ±2°/5°/10° search, merge rules |
| [`disturbance_and_channel.md`](./disturbance_and_channel.md) | Physical channel model: attenuation, scintillation, wander, test scenarios |
| [`gui_and_terminals.md`](./gui_and_terminals.md) | GUI architecture, remote/local terminal panels, headless simulation |
| [`tests_and_verification.md`](./tests_and_verification.md) | Test strategy, unit tests, end-to-end acceptance test, acceptance criteria |

### 👩‍💻 Developer Documentation

| File | Scope |
|------|-------|
| [`developer_guide.md`](./developer_guide.md) | How to extend the codebase, add states, modify the protocol, write tests, common pitfalls |
| [`api_reference.md`](./api_reference.md) | Public class and method signatures for all major modules |

---

## System Topology

```
┌─────────────────────────────────────────────────────────────────┐
│                        REMOTE TERMINAL                          │
│  BeaconPayload → Serialize → Frame → CRC → OOK chips → Light   │
└────────────────────────────┬────────────────────────────────────┘
                             │ Optical Beam
                             ▼
                    ┌────────────────┐
                    │   PROPAGATION  │
                    │   DISTURBANCE  │
                    │   CHANNEL      │
                    └───────┬────────┘
                            │ Photons + Noise
                            ▼
┌─────────────────────────────────────────────────────────────────┐
│                    CAMERA / SENSOR                              │
│  Raw sensor → Frame rendering → CameraFrame                     │
└────────────────────────────┬────────────────────────────────────┘
                             │ CameraFrame (image only)
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│                        LOCAL TERMINAL                           │
│                                                                 │
│  FrameProcessor → CandidateDetector → CandidateAssociation      │
│       → OpticalMeasurement → TemporalSignalExtractor            │
│       → SignalSynchronizer → OOKDemodulator                     │
│       → BeaconFrameParser → PayloadDecoder → IdentityValidator  │
│       → CandidateLifecycle → Selection → Dual-Lock Acquisition  │
│       → Image-Based Tracking → Identity/Liveness Monitoring     │
│       → Degradation → Identity-Gated Reacquisition              │
└─────────────────────────────────────────────────────────────────┘
```

---

## Core Architecture Principles

1. **Absolute image-only boundary** — the local terminal receives **only** `CameraFrame`, local PTZ pose/velocity, and local config. No remote truth is ever used.

2. **Digital identity is authoritative** — a candidate is never `IDENTIFIED` without a successfully decoded beacon payload. Optical quality alone is insufficient.

3. **Optical path controls pointing** — the PTZ is driven by camera centroid / filtered position. The digital beacon path only validates identity and liveness.

4. **Shared protocol package** — `common/protocol/beacon/` is the single source of truth for frame format, codec, and CRC. Both terminals depend on it.

5. **Streaming decoder** — the frame decoder is incremental; it never re-feeds old history samples.

---

## Terminology

| Term | Meaning |
|------|---------|
| `observation_id` | Locally generated ID for a candidate track (e.g., `BEACON-001`) |
| `decoded_terminal_id` | Remote terminal ID extracted from a decoded payload (e.g., `RT-001`) |
| `identity lock` | All digital fields match and required persistence is met |
| `spatial lock` | Centroid is stable, visible, and within acquisition window |
| `dual lock` | Identity lock **AND** spatial lock simultaneously held |
| `liveness` | Ongoing stream of new, unique, valid decoded sequences |
| `degradation` | Tracking continues but quality metrics are deteriorating |
| `reacquisition` | Recovering the lock after a temporary loss |

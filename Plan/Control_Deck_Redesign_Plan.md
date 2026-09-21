# Control Deck Redesign Plan — Camera, Local Terminal, Remote Terminal

**Status:** Draft for review  
**Scope:** `gui/panels/camera_panel.py`, `gui/panels/controller_panel.py`, `gui/panels/local_terminal_panel.py`, `gui/panels/remote_terminal_panel.py`, `gui/views/settings_dialog.py`, `camera/config.py`, `camera/constants.py`, `local_terminal/models.py`, `remote_terminal/config.py`, `gui/application/session.py` (wiring only)  
**Out of scope:** `environment_panel.py`, `disturbances_panel.py` (left as-is, noted only for tab budget)  
**Reference:** `Requirements.pdf` Sr 1-20, `Plan/Implementation_plan_V2.md` §6.5/§18-§20, `camera/constants.py`, `remote_terminal/config.py:352` FIELD_METADATA

---

## 1. Goal

Make the Control Deck operable by a demo operator in <30s while keeping expert tunables one click away. Today each of the three requested panels exposes ~12-19 controls flat, mixing **mission/task** knobs (FOV, target count, motion) with **physics/debug** knobs (inertia, token, pointing bias). The PDF only mandates ~8 user-defined values; the rest are tuning/debug.

**Target IA:** 3 tabs, each with `Primary` (PDF/operator) group + collapsible `Advanced` group. No control is deleted from the config model; unnecessary ones are moved to `Advanced` (collapsed by default) or to a hidden dev preset.

---

## 2. Ground Truth: What the PDF Actually Requires

| PDF Sr | User-definable parameter | Current exposer | Verdict |
|---|---|---|---|
| 1 | Screen size 2000×2000 min | `environment` | OOS |
| 3 | Camera resolution 640×480 (Fixed) | `camera_panel: label` | Keep as read-only |
| 4 | Camera FOV (default 4°×3°) | `camera_panel: fov_h/v` | **Keep Primary** |
| 5 | Camera update rate ≥30Hz | `camera_panel: update_rate` slider | **Remove from Primary** — fix at 30Hz, advanced only |
| 6 | Initial camera position = centre | `camera_panel: home/start/scan_start` (7 controls) | **Remove** — centre is (0,0); keep hidden dev override |
| 9 | Target shape/size 5-20px default 10×10 | `remote: spot_size_mrad` | **Keep Primary** (rename to "Beam width / Spot size") |
| 11 | Initial target location = Random/User-defined | `remote: start_offset_x/y` | **Keep Primary** (already in Formation) |
| 12 | Motion ≥4: Straight, Circular, Figure-8, Random | `remote: motion_profile` | **Keep Primary** |
| 13/14 | Max pan/tilt 5-10°/s default 5 | `camera: pan_speed / tilt_speed` | **Keep Primary** but as one linked "Slew rate" |
| 15 | Update interval ≥20Hz | = update_rate | — |
| 21.x | Disturbances selectable | `disturbances` tab | OOS |

**Implication:** ~70% of current Camera panel and ~40% of Remote panel are **not PDF-mandated** and should not be Primary.

---

## 3. Audit: Remove / Keep / Introduce

### 3.1 Camera & PTZ Gimbal (`camera/config.py` + `camera_panel.py`)

**Current Primary groups (4 groups, 19 widgets):**
`CAMERA OPTICS & VIEWPORT` (fov_h, fov_v, resolution label, update_rate), `GIMBAL KINEMATICS & LIMITS` (pan_speed, tilt_speed, pan_accel, tilt_accel, pan_range, tilt_range), `MECHANICAL DYNAMICS & ENCODERS` (backlash, damping, encoder_noise, measured_feedback), `STARTING POSITIONS` (home_pan/tilt, start_pan/tilt, use_custom_start, scan_start_index).

| Control | Model field | Disposition | Rationale |
|---|---|---|---|
| **Horizontal FOV** | `fov_deg_h` | **Keep Primary** | PDF Sr4 |
| **Vertical FOV** | `fov_deg_v` | **Keep Primary** with `🔗 Link` (keeps 4:3, unlink for expert) | PDF Sr4; two independent sliders confuse aspect |
| Resolution label | `resolution_w/h` | **Keep** read-only badge `640×480 Monochrome` | PDF fixed |
| **Update Rate** | `update_rate_hz` | **Remove from Primary → Advanced** | PDF ≥30Hz is a floor, not a tuning knob; fix 30 |
| Max Pan Speed | `max_pan_speed_deg_s` | **Keep Primary as "Slew rate"** (single slider drives both) | PDF Sr13/14 |
| Max Tilt Speed | `max_tilt_speed_deg_s` | **Keep Primary via link** — unlink in Advanced to split | PDF Sr13/14 symmetric by default |
| Max Pan/Tilt Accel | `max_pan_accel_deg_s2` | **Move to Advanced** | Not in PDF; second-order feel |
| Pan/Tilt Range (±) | `pan_min/max`, `tilt_min/max` | **Remove** (compute from world bounds) | Effective limits already clamp to world; operator never needs this |
| Backlash | `backlash_deg` | **Remove → Advanced / Expert** | Gear hysteresis debug |
| Damping Ratio | `damping_ratio` | **Remove → Advanced** | Butterworth tuning, not operator |
| Inertia | `inertia_kg_m2` | **Remove from GUI** (keep model default 0.02) | Not in panel today anyway (only constant) — keep hidden |
| Encoder Noise | `encoder_noise_deg` | **Move to Advanced** | Sensor debug; disturbance tab already has camera shake |
| Encoder Bits | `encoder_bits` | **Remove from GUI** (fixed 16) | Never exposed today, keep hidden |
| Measured feedback | `use_measured_feedback` | **Remove → Advanced (toggle)** | Stage-2 measured-pose mode, expert |
| Home Pan/Tilt | `home_pan_deg` / `home_tilt_deg` | **Remove** | Home = centre per PDF Sr6 |
| Start Pan/Tilt + Use custom | `start_pan_deg`/`start_tilt_deg`/`use_custom_start` | **Remove** | Test harness, not mission |
| Scan Start Cell | `scan_start_index` | **Move to Local Terminal → Search** | Belongs to `ScanController`, not camera |
| Presets | `CAMERA_PRESETS` | **Keep** but prune to 3 chips: `Default (4°/5°/s)`, `Agile (6°/10°/s)`, `Narrow (2°/3°/s)` | Current 3 presets already map well |

**Net:** Primary collapses from 13 sliders + 2 checks + 4 start widgets → **3 sliders + 1 link toggle + presets**. Advanced holds 6 sliders + 1 toggle collapsed.

### 3.2 PID Tracking Controller (`camera/config.py:PIDConfig`, `controller_panel.py`)

Not explicitly requested but is the **HOW STRONG** half of Local. Current panel has 10 sliders (6 gains + 4 robustness) + Mode + Presets. This is correctly exposed but too granular for Primary.

| Control | Disposition | Rationale |
|---|---|---|
| Mode AUTO/MANUAL/OFF | **Keep Primary** (chip) | Operator needs to disable loop |
| Kp pan / Kp tilt | **Merge to Primary "Kp"** (single slider drives both, Advanced splits) | Symmetric plant by default |
| Ki, Kd likewise | **Merge to Primary "Ki", "Kd"** | Same |
| Deadband | **Keep Primary** (1px) | PDF tracking error 10px; hunting visible |
| tau, max_integral, max_output | **Move to Advanced** | Filter / anti-windup tuning |
| Presets Balanced/Aggressive/Smooth | **Keep** | Already good |

**Alternative if strict scope (camera/local/remote only):** merge PID into `Local Terminal → Tracking` as `Controller` subgroup rather than a separate 6th tab — saves a tab and matches V2 pipeline (`tracker → PID → PTZ`). Decision deferred to review.

### 3.3 Local Terminal — Autonomy (`local_terminal/models.py:AutonomyConfig`, `local_terminal_panel.py`)

**Current:** 18 widgets flat across 5 groups (Search 3, Detection 5, Tracking 4, Lost/Reacq 4, Selector 1). No hierarchy; duplicates (`coast_*` vs `lost_*` both 30px/1s/0.5s) confuse.

| Field | Current | Disposition | Rationale |
|---|---|---|---|
| `search_pattern` | Combo | **Keep Primary** | V2 systematic/last_known/predicted |
| `search_dwell_frames` | Spin 1-10 | **Advanced** (default 1) | Frame dwell rarely changed |
| `search_extended_dwell_frames` | Spin 1-30 | **Advanced** (default 10) | P_rx candidate dwell |
| `candidate_min_snr_db` | Spin 0-40 | **Keep Primary — "Detection sensitivity"** | Core Sr21 detection gate |
| `candidate_peak_margin` | Spin 0-50 | **Advanced** | Threshold is background+margin |
| `candidate_confirm_frames` | Spin 1-5 | **Keep Primary (2-3)** | Hot-pixel reject; PDF-relevant |
| `candidate_min/max_area_px` | Spin | **Advanced** | Expert spot filter |
| `association_gate_px` | Spin | **Remove — keep `mahal` only** | Fixed pixel gate is acquisition fallback only; `mahal_threshold` is V2 gate (§11.4) |
| `association_mahal_threshold` | Spin | **Advanced** (default 9.21) | Chi² 99%; expert |
| `kalman_process_noise_q` | Spin | **Advanced** | Q tuning |
| `kalman_measurement_noise_r_base` | Spin | **Advanced** | R base |
| `kalman_r_scale_low/high` | *(not in panel!)* | **Introduce in Advanced** | Model has them, panel hides them — add |
| `coast_max_uncertainty_px` / `coast_timeout_s` | Spin | **Consolidate with LOST** — single `Lost threshold` pair | Spec §5: LOST needs AND(uncertainty, time); coast is internal |
| `lost_uncertainty_threshold_px` / `lost_timeout_s` | Spin | **Keep Primary** | §5/§12.5 |
| `reacq_radii_px` | *(not in panel!)* | **Introduce Primary as preset** `Local → Aggressive` chips: `Default [50,100,200,400,800]` vs `Narrow` | Spec §15 ladder; panel currently no control at all |
| `reacq_full_scan_enabled` | *(not in panel!)* | **Introduce Advanced toggle** | Spec §15 |
| `active_target_policy` | Combo | **Keep Primary** | priority / strongest_prx / highest_snr |
| `p_rx_threshold_w` | *(not in panel!)* | **Introduce Primary** (mW slider, default 0.0) | Spec §10.1 — currently 0, operator cannot set power floor |
| **Missing:** Mission priority list | *(implicit via scenario order)* | **Introduce Primary** — draggable list `RT-001 > RT-002 > ...` | V2 `SignatureRegistry` + `select_active_v2` priority mode has no UI |

**Net:** Primary = 6 controls (SNR, confirm, pattern, lost pair, p_rx threshold, policy + priority list, reacq preset). Advanced = ~10 controls collapsed.

### 3.4 Remote Terminal (`remote_terminal/config.py`, `remote_terminal_panel.py`)

**Current:** 5 groups + payload/pointing/telemetry (≈22 widgets). Well-structured but mixes mission/payload/expert.

| Group / Control | Disposition | Rationale |
|---|---|---|
| **Formation:** terminal_count, formation_shape, terminal_spacing | **Keep Primary** | PDF §8-11 |
| **Motion:** motion_profile, speed_mps, heading_deg | **Keep Primary** | PDF Sr12 |
| **Starting Position:** start_offset_x/y | **Keep Primary** | PDF Sr11; already primary |
| Active Terminal selector | **Keep Primary** | Essential |
| **Terminal Identity:** terminal_id | **Keep Primary** | WHO signal |
| **Terminal Optics:** optical_power_w, wavelength_nm, spot_size_mrad | **Keep Primary** | HOW STRONG / beam |
| Modulation | **Move to Advanced** (default OOK) | Fix 4.9 note: always OOK waveform |
| **Emission:** power_enabled + beacon_enabled + operational_state | **Simplify Primary to one "Emission" row:** `State` dropdown + `Beacon` toggle; keep `Power` toggle in Advanced | Current 3 toggles + dropdown is noisy; BEACONING/LINKED already gate emission |
| **Beacon Payload:** token, network_id, enable_nav | **Move to Advanced** (collapsed) | Wire auth/debug; not PDF |
| **Pointing:** pointing_bias, pointing_jitter_sigma | **Move to Advanced** | Per-terminal beam error §47 — expert |
| Telemetry card | **Keep** read-only (already) | Live feedback |
| Randomize Terminals button | **Keep** | Useful |
| **Missing:** Formation preview minimap | **Introduce** (small canvas in Formation group) | Operator cannot picture LINE vs GRID vs V at given spacing |

No new model fields needed for Remote; all §3.4 signals already exist.

---

## 4. Proposed Control Deck IA (After)

**Tabs (5, not 6):**
```
[ Remote Terminals ] [ Camera & Gimbal ] [ Tracking ] [ Environment ] [ Disturbances ]
                                          ^^^^^^^^^^^
                                   Local + PID combined
```
*If strict "don't merge PID"*: keep 6 tabs but rename `Local Terminal → Autonomy` and keep `PID Controller`.

### 4.1 Remote Terminals — Wireframe

```
REMOTE TERMINALS                                   [🎲 Randomize] [Reset]
Formation, motion & per-terminal optics — live telemetry below

┌─ FORMATION ──────────────────────┐  ┌─ MOTION ─────────────────┐
│ Count [1..8]  Shape [Grid ▾]      │  │ Profile [Constant Vel ▾] │
│ Spacing [100.0 m]  [Preview ◫]    │  │ Speed [10.0 m/s]  Heading [0°] │
└──────────────────────────────────┘  └──────────────────────────┘
┌─ STARTING POSITION ──────────────┐
│ Start X [0.0 m]  Start Y [0.0 m]  │  hint: (0,0)=scene centre
└──────────────────────────────────┘
┌─ TERMINAL ───────────────────────┐  Selector [RT-001 ▾]  ID [RT-001]
│ State [BEACONING ▾]  Beacon [◉ ON]│  Power [0.5 W]  Wavelength [1550 nm]
│ Spot / Beam width [1.0 mrad]     │  hint: full angular width
│ ▸ Advanced: Power switch · Modulation [OOK ▾] · Token/Network/NAV │
│ ▸ Pointing (bias/jitter)                                │
└──────────────────────────────────┘
┌─ TELEMETRY — read-only ──────────┐  Position / Velocity / Range / Beam / Footprint …
└──────────────────────────────────┘
```

### 4.2 Camera & Gimbal — Wireframe

```
CAMERA & GIMBAL                           Presets: [Default] [Agile] [Narrow] [Reset]
Virtual PTZ — monochrome 640×480 @30Hz

┌─ OPTICS ─────────────────────────┐
│ H-FOV [4.0°]  V-FOV [3.0°]  [🔗] │  res: 640×480 Mono · 30Hz fixed
└──────────────────────────────────┘
┌─ GIMBAL ─────────────────────────┐
│ Slew rate [5.0 °/s]  [🔗 Pan/Tilt]│  accel/limits computed from world size
│ ▸ Advanced: Accel Pan/Tilt, Encoder noise, Measured feedback │
└──────────────────────────────────┘
```

*Starting Positions group removed.* `scan_start_index` moves to Tracking → Search.

### 4.3 Tracking (Local Autonomy + PID) — Wireframe

```
TRACKING — Autonomy + Controller          [Reset Autonomy]  [Reset PID]
FSM: SEARCH → IDENTIFY → ASSOCIATE → TRACK ⇄ COAST → LOST → REACQUIRE

┌─ SEARCH & DETECTION ─────────────┐
│ Pattern [systematic ▾]  Confirm [2 frames]  Scan start [0 ▾]
│ Detection SNR [6.0 dB]  P_rx floor [0.00 mW]
│ ▸ Advanced: dwell/ext_dwell, peak margin, min/max area │
└──────────────────────────────────┘
┌─ TRACKING ───────────────────────┐
│ Lost if: uncertainty [30.0 px] AND time [0.50 s]
│ ▸ Advanced: Q/R, R scales (low 6.0 / high 0.5), Mahalanobis 9.21 │
└──────────────────────────────────┘
┌─ REACQUISITION ──────────────────┐
│ Ladder [Default 50→800 ▾]  Full-scan [◉ ON]
│ ▸ Advanced: edit radii [50,100,200,400,800]
└──────────────────────────────────┘
┌─ SELECTOR ───────────────────────┐
│ Policy [priority ▾]  Priority order: [RT-001 ▲▼] [RT-002] [+ reorder]
└──────────────────────────────────┘
┌─ CONTROLLER (PID) ───────────────┐
│ Mode [AUTO ▾]  Kp [1.50]  Ki [0.10]  Kd [0.25]  Deadband [1.0 px]
│ Presets: [Balanced] [Aggressive] [Smooth]
│ ▸ Advanced: Tau, Max integral, Max output
└──────────────────────────────────┘
```

---

## 5. Config Model Changes (Minimal, Additive Only)

*Principle:* GUI may hide a field, never rename/remove it from the dataclass — old scenarios stay loadable.

| File | Change |
|---|---|
| `camera/config.py:CameraConfig` | No field removed. Add `validate()` warning when `update_rate_hz !=30` (future fixed). Deprecate `scan_start_index` with `__getattr__` shim → `AutonomyConfig.search_start_index` (or keep but ignore). |
| `camera/constants.py` | No change to `CAMERA_LIMITS` (keep for headless). Add `CAMERA_PRIMARY_FIELDS = ["fov_deg_h","fov_deg_v","max_pan_speed_deg_s","max_tilt_speed_deg_s"]` for panel whitelisting (optional). |
| `local_terminal/models.py:AutonomyConfig` | Add `search_start_index: int = 0` (0..19) field, add to `validate()`; keep `search_dwell_frames` etc. No removals. Add helper `primary_dict()` / `advanced_dict()` if desired. |
| `camera/config.py:PIDConfig` | No field removed. Optionally add `linked_gains: bool = True` transient (not persisted) for UI link toggle. |
| `remote_terminal/config.py` | No field removed. Add `FIELD_METADATA["..."]["tier"] = "primary"|"advanced"` so panel can auto-build sections from metadata instead of hard-coded grid. |

No DB/migration — `from_dict()` already ignores unknown keys; new keys get defaults.

---

## 6. Panel Implementation Plan (File-by-File)

### 6.1 `gui/panels/camera_panel.py` (largest cut)

- Replace 4 groups with 2 groups (`OPTICS`, `GIMBAL`) + one `Advanced` `QToolBox`/`QCheckBox("Show advanced")`.
- Keep `_make_float_slider` helpers; introduce linked slew `QSlider` + `QCheckBox(🔗)` that writes both pan/tilt fields when linked.
- Remove `mech_box` widgets (backlash/damping/noise/measured_feedback) from primary construction; re-add under `advanced_box` lazy-created.
- Remove `start_box` entirely; migrate `scan_start_index` handling to `local_terminal_panel`.
- Presets stay but `CAMERA_PRESETS` entries keep full dict — panel only applies `fov_*` + `max_*_speed` in Primary mode; advanced mode applies all.

### 6.2 `gui/panels/local_terminal_panel.py`

- Rewrite `_build_ui` to 5 collapsible cards as per wireframe; use `QCheckBox("Show advanced")` per card or one global `Advanced` toggle (pick one — recommend per-card to avoid scrolling).
- Introduce missing widgets: `spin_p_rx` (DoubleSpin 0..10 mW), `combo_reacq_preset`, `list_priority` (QListWidget with drag-drop), `combo_search_start` (0..19).
- Hide `spin_peak_margin/area/gate/Q/R` in advanced QWidget.
- `collect_config()` builds `AutonomyConfig` with new fields; `set_config()` mirrors.

### 6.3 `gui/panels/remote_terminal_panel.py`

- Add tier to `FIELD_METADATA` and split `_build_ui` into Primary vs Advanced containers.
- Keep Formation/Motion/Starting Position as Primary (no change except add minimap widget).
- In TERMINAL card: render `terminal_id / state / beacon / optical_power / wavelength / spot_size` in Primary grid; move `token / network_id / enable_nav / modulation / pointing_* / power_enabled` to Advanced `QWidget` toggled by `QCheckBox("Show beacon & pointing details")`.
- Add `FormationPreview` canvas (20px per cell, 4×5 grid) under Formation group — pure view, no model change.

### 6.4 `gui/panels/controller_panel.py`

- If merging into Tracking: delete file and move `ControllerPanel._build_ui` as `TrackingPanel._build_controller_subgroup`. If keeping tab: shrink to Primary `Kp/Ki/Kd/Deadband/Mode` + Advanced collapsed.

### 6.5 `gui/views/settings_dialog.py`

- Tab order becomes `Remote Terminals`, `Camera & Gimbal`, `Tracking`, `Environment`, `Disturbances` (was 6). Update `_add_scrolled_tab` calls, `reset_to_defaults` to include new fields, `sync_from_session` to handle `search_start_index` migration.
- Update header subtitle to `"Remote Terminals • Camera & Gimbal • Tracking • Environment • Disturbances"`.

### 6.6 `gui/application/session.py` + `simulation/headless.py`

- `apply_camera_config` no longer expects `scan_start_index`; add `apply_local_terminal_config` handling for `search_start_index → ScanController.plan_schedule / _schedule_ptr`.
- `SimulationSession._apply_scan_start_index` reads from `autonomy_config.search_start_index` first, falls back to `camera_config.scan_start_index` for backward compat.

---

## 7. Alternatives Considered

| Alt | Why rejected |
|---|---|
| Delete fields from dataclasses | Breaks headless `scenario.json` / reproducibility; validation already handles missing keys. Hiding in GUI is cheaper and reversible. |
| Keep all sliders but add search/filter | Still overwhelms first-time demo; tiered disclosure is standard for PAT consoles. |
| Move PID into Camera panel | PID is tracking law, not optics — belongs with autonomy per V2 pipeline; keep with Tracking. |
| Single "Expert mode" global toggle | Per-card Advanced keeps Primary scannable while letting an expert open just one section (e.g. Kalman) without exposing everything. |

---

## 8. Risks & Mitigations

| Risk | Mitigation |
|---|---|
| Operator hides a needed knob (e.g. P_rx floor) | P_rx floor is Primary; advanced defaults are sane and validated (`AutonomyConfig.validate` clamps). |
| Old `camera_config.scan_start_index` scenarios break | Shim: `CameraConfig.__getattr__` + `_apply_scan_start_index` fallback keeps load. |
| Tests assert `camera_panel.slider_backlash` exists | Keep attribute but `hide()` in Advanced — `getattr(panel, "slider_backlash", None)` still passes; or emit deprecation alias. |
| Formation preview off by one cell | Share `local_terminal/scan.py: X_STARTS/Y_STARTS` constants, don't recompute. |
| Tab reorder confuses muscle memory | Keep `Environment`/`Disturbances` tabs at end in same order; only middle tabs reorder. Announce in changelog. |

---

## 9. Validation

- **Automated:** `pytest tests/test_gui_application.py tests/test_lifecycle_buttons.py tests/test_gui_camera.py` — panels must still `collect_config().validate()` and `set_config(..., emit=False)` round-trip. Add new tests: `test_control_deck_tiers.py` asserts primary-only `collect_config()` equals full default when advanced untouched.
- **Manual:** Demo script (15 min): Randomize Remote → set FOV 4° → Tracking SNR 6dB → Start → assert acquisition <2s, error <10px (PDF §16-17). Heavy scene rebuild only on release (already wired via `sliderReleased`).
- **Determinism:** Same seed + same Primary values → identical run even if Advanced collapsed (hidden widgets still hold defaults).

---

## 10. Rollout Order

1. **Remote Terminal tier split** (low risk, metadata-driven, no headless change).
2. **Camera panel shrink + slew link** (move start widgets, no model change).
3. **Local Terminal new fields** (`p_rx_threshold`, `reacq`, `priority list`, `search_start_index`) — model + panel together.
4. **PID merge / shrink** (if approved) — panel move, no model change.
5. **Formation preview** (pure view) — last, visual only.
6. **Deprecate `camera.scan_start_index` shim** — after rollout, doc removal in next minor.

---

## 11. Open Questions for Review

- [ ] Merge PID into Tracking tab vs keep separate `PID Controller` tab? (Recommend merge.)
- [ ] Fix `update_rate_hz` at 30Hz (remove slider) or keep as Advanced 10-120Hz for stress testing?
- [ ] Keep `damping_ratio`/`backlash` in GUI at all, or hide completely (headless constant)?
- [ ] Priority list source: formation order vs explicit `mission_priority` editable list — confirm desired semantics for `select_active_v2`.

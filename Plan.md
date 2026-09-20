# Coarse Alignment & Tracking — System Operational Plan (v2, fixed)

> **Status:** design specification. Implementation coverage is currently ~0% for
> Phases 0–6 (only the beacon encode/decode protocol in `common/protocol/beacon/`
> and the disturbance/camera plant exist). Do not code directly from v1 of this
> document — it contained contradictions, all fixed below and marked **[FIX]**.
>
> **Conventions:** sim time in seconds, angles in degrees, pixels in FOV/world px
> (1 m = 1 px per `remote_terminal/scenario.py`). "Frame" = one camera frame at
> 30 Hz (33.3 ms) unless "beacon frame" (one OOK message) is stated explicitly.

---

## 0. Glossary

| Term | Meaning |
|---|---|
| Camera frame | One 640×480 capture, 33.3 ms at 30 Hz |
| Beacon frame | One complete OOK message: **42 bytes → 336 chips → 336 ms ≈ 10 camera frames** (measured from `BeaconGenerator`; §2.7) |
| Candidate | A bright region passing detection thresholds, not yet validated |
| Track | A validated target with an active motion model and locked Terminal ID |
| Ground truth | True simulator state; the local terminal may **never** read it — only the degraded beam (§1.3) |
| Dwell | Consecutive camera frames spent on one scan position (needed for multi-frame checks) |

---

## 1. System overview

### 1.1 Pipeline

```text
Remote terminal(s) ──optical beam──▶ [Channel: attenuation, wander, spread,
  scintillation, blur] ──degraded beam──▶ Local terminal:
  SEARCH ─▶ DETECT ─▶ VALIDATE ─▶ SELECT ─▶ TRACK ──(lost)──▶ RE-ACQUIRE ──┐
     ▲                                                                    │
     └────────────── full reset (only if re-acquisition exhausts) ─────────┘
```

### 1.2 Modules and ownership

| Module | Owns | Must never touch |
|---|---|---|
| Scan controller | Camera pose schedule, visited registry | Pixel data, validation state |
| Detector | Thresholds, centroiding, candidate list | Beacon decoding, tracking commands |
| Validator | Lifecycle state machine, blacklist, scores | Camera pose, PID gains |
| Tracker | Motion model, PID error source, lock state | Ground-truth positions |
| Re-acquisition manager | Escalation ladder, standby pool | Blacklist (read-only here) |
| Autonomy supervisor | Phase transitions, watchdogs, reset policy | Everything else's internals |

### 1.3 Ground-truth isolation (non-negotiable)

The local terminal's **only** input is the received beam after the disturbance
channel. It knows a remote terminal's position, state, ID, and parameters
exclusively through decoded photons. Any design or test that feeds telemetry
positions into tracking violates this spec. (The current codebase tracks from
telemetry — closing the loop through the image is implementation Stage 1, §11.)

### 1.4 Key architectural note

The sensor never receives the undisturbed source beam. Every stage below is
specified against degraded, noisy input. Thresholds in §4 are defaults pending
ROC calibration in-sim (§9.4), not constants of nature.

---

## 2. Optical signature model (8 properties)

Each remote terminal presents a composite signature. Properties 1–7 are physics
and protocol (implemented in `remote_terminal/`); property 8 is display-only.

### 2.1 Carrier wavelength
- Default **1550 nm**, valid band **800–1700 nm** (`SUPPORTED_WAVELENGTH_*_NM`).
- Out-of-band emission is rejected at the first validation gate (§5.2).
- *Example:* RT-001 at 1550 nm passes; a 750 nm source is dropped before decoding.

### 2.2 Optical power
- Default **0.5 W**, GUI range 0–10 W (`optical_power_w`).
- Instantaneous emitted power follows the current chip (see 2.3).

### 2.3 Modulation format
- `CW` (continuous), `OOK` (default), `PPM`. Chip rate **1 kHz** (1 ms/chip,
  `CHIP_DURATION_S` — internal, not user-configurable).
- OOK/PPM gate power per chip; CW ignores chips.
- **[FIX] Extinction ratio.** v1 said low chips emit "zero". The protocol layer
  defines `CHIP_HIGH=1.0 / CHIP_LOW=0.45` (`ook.py`) while `BeamModel`
  emits 0 on low chips (`optics.py`). **Specified: finite extinction
  1.0 : 0.45.** Code-alignment action: update `BeamModel.emission` and spot
  rendering to the 0.45 low level; low chips dim the spot, they do not erase it.
  Detection thresholds (§4.1) are set against the *low-chip* level for this reason.

### 2.4 Beam divergence
- Default **1.0 mrad full angular width** (never FWHM/radius/half-angle).
- Footprint: `beam_diameter_m = range_m × width_rad`.
- *Example:* at 2000 m range with 1.0 mrad → 2.0 m footprint → σ ≈ 1.0 px,
  floored to the 3.0 px visibility minimum at render (§2.8).

### 2.5 Beam pointing geometry (runtime, per frame)
- Beam centre angle, line-of-sight angle, range to reference, pointing error =
  static bias + per-frame Gaussian jitter (`pointing.py`). This is why the spot
  wanders even when the transmitter is correctly aimed.

### 2.6 Emission gating
Emit **iff** `power_enabled AND beacon_enabled AND state ∈ {BEACONING, LINKED}`.
`OFF`, `STANDBY`, `FAULT` → no photons at all. A FAULT terminal is
indistinguishable from empty sky — the receiver must handle "nothing there"
as a normal outcome, not an error.

### 2.7 Encoded beacon payload (measured reference frame)
Wire layout: `PREAMBLE(0xAA) | SYNC(0xD5) | VER | TYPE | LEN(2B) | PAYLOAD | CRC-8`.
Default payload: 6-byte TID + 6-byte token + 2-byte wavelength + 4-byte sequence
+ 3-byte net/caps + 12-byte nav extension = 35 bytes → **42 wire bytes =
336 chips = 336 ms ≈ 10 camera frames.** Header-only prefix (preamble through
length field) is 6 bytes = **48 chips ≈ 48 ms ≈ 2 camera frames** — this is the
fastest any ID-bearing information can physically arrive (§7.2 builds on this).
First frames are staggered 16 chips per terminal so co-located terminals do not
blink in lockstep. Sequence wraps mod-256; freshness MUST use modular
`sequence_is_newer`, never naive `>` comparison.

### 2.8 Rendered spot (visualisation only — not physics, not a validation input)
2D Gaussian marker, σ = max(footprint/2, **3.0 px**), peak =
`(power / 1.0 W) × 255` (`POWER_REF_W`). Physics lives in telemetry and
`OpticalEmission`, never in this marker.

### 2.9 Validation implication (fixed)
The receiver decodes properties **1, 3, 7** from the beam and checks them
against the Phase 0 registry. Properties **2 and 5** feed SNR/centroid-quality
scoring via the radiometric model (§5.4), **not** the display formula.
Properties **6 and 8** are state/display concerns and never validation inputs.
**[FIX]** v1 scored power consistency against the display formula while
declaring the display "not physics" — resolved by §5.4.

---

## 3. Phase 0 — System initialisation

Before any scan, the local terminal loads two things:

### 3.1 Expected-signature registry **[FIX — was missing entirely]**
v1 checked "self-reported vs. locally expected wavelength ±50 nm" and
"Terminal ID exact match" without defining where expectations come from.
Specified source: the **mission file** (scenario configuration), loaded here:

| Parameter | Expected value | Hard-reject condition |
|---|---|---|
| Carrier wavelength band | 800–1700 nm | Outside band |
| Per-terminal wavelength | Registry value ± 50 nm | Outside tolerance |
| Modulation format | CW / OOK / PPM | Unrecognised encoding |
| Terminal ID | In registry, ≠ self ID, not blacklisted | Unknown / self / blacklisted |
| Sequence | Modular-incrementing per §5.2 | Stale / static |
| Emission state (decoded nav flag) | BEACONING or LINKED | OFF / STANDBY / FAULT |
| Beacon CRC-8 | Must pass | Any failure |

Unknown IDs are **ignored, not blacklisted** (they may be non-cooperative
traffic, not faults). Self-ID reception is a loopback fault → flag, ignore.

### 3.2 Validator profile
Score weights (§5.3), thresholds (§4.1), blacklist policy (§5.5), watchdog
timeouts (§8.2). All configurable; all logged at startup.

---

## 4. Phase 1 — Search & scan

### 4.1 Scan grid (fixed geometry) **[FIX]**
Scene 2000×2000, FOV 640×480. v1's "non-overlapping, never revisit" grid
cannot tile 2000/640 = 3.125 × 2000/480 = 4.17. Specified: **10% overlap**,
edge-anchored final row/column:

- Step: 576 px horizontal, 432 px vertical → **4 columns × 5 rows = 20 positions**.
- Column x-starts: 0, 576, 1152, 1360 (= 2000−640, edge-anchored).
- Row y-starts: 0, 432, 864, 1296, 1520 (= 2000−480, edge-anchored).
- Visited registry: 20-bit mask. A position is marked visited only after its
  dwell completes, never when queued.

### 4.2 Priority order
1. **Last-known region** (prior session): 3×3 FOV patch centred on last position.
2. **Predicted region** (motion model exists): sector along predicted velocity.
3. **Systematic scan**: raster by default; spiral or sector sweep configurable.

### 4.3 Dwell rule **[FIX]**
v1 forbade revisits yet required sequence checks across ≥2 frames. Resolved:
default dwell = **1 frame** per position for photometry; dwell extends to
**≥10 frames** only on positions yielding a DECODING candidate (one full
336 ms beacon frame must be observable). Dwell is an explicit exception to
no-revisit, recorded in the registry.

### 4.4 Scan timing budget
20 positions × 1 frame @30 Hz = **0.67 s per clean cycle**. Each candidate
adds ≤10 dwell frames (0.33 s). Worst-case single cycle with 3 candidates ≈
1.7 s. These numbers feed the autonomy watchdogs (§8.2).

---

## 5. Phase 2 — Detection & candidate validation

Detection runs every frame, before validation.

### 5.1 Spot detection thresholds (defaults — calibrate per §9.4)

| Criterion | Threshold | Rationale |
|---|---|---|
| Peak pixel intensity | ≥ 30/255 | Above noise floor at *low-chip* level (§2.3) |
| Spot σ | ≥ 3.0 px | `MIN_SPOT_SIGMA_PX`; smaller = sub-resolution artefact |
| Compactness | Gaussian fit R² ≥ 0.75 | Rejects streaks / hot-pixel clusters |
| SNR | ≥ 6 dB above local background | Local background estimated per-frame in an annulus around the region |
| Spatial isolation | Centroid separation ≥ 10 px | Merges split artefacts from scintillation |

Regions failing any criterion are **discarded silently**: not logged, not
blacklisted, not re-examined this frame. **[FIX]** This discarding is a
*detection* outcome; only *validation* failures can blacklist (§5.5). v1
stated both "permanently blacklisted" and "not blacklisted" for failures —
the split above is the resolution.

### 5.2 Centroid localisation
Intensity-weighted centre of mass in the region bounding box:

```text
centroid_x = Σ(x · I(x,y)) / ΣI(x,y),   centroid_y = Σ(y · I(x,y)) / ΣI(x,y)
```

Centroid history (last N = 10 frames) feeds the motion model and the
stability score. Sub-pixel arithmetic; FOV position rounded only at render.

### 5.3 Validation lifecycle (strict, linear, no skips)

```text
[DETECTED] → [DECODING] → [SIGNATURE_CHECK] → [SCORED] → [SELECTED | REJECTED → strike/blacklist]
```

| State | Entry | Pass → | Fail → |
|---|---|---|---|
| DETECTED | §5.1 all pass | Modulation pattern identified (preamble/sync correlation) | No pattern → silent discard, **never blacklisted** |
| DECODING | Pattern present | Full beacon frame received, **CRC passes** | Timeout (§8.2) or CRC fail → 1 strike (§5.5), candidate dropped |
| SIGNATURE_CHECK | CRC passed | All §5.2-table checks pass | Any fail → 1 strike, dropped |
| SCORED | Signature valid | Score ≥ 0.60 → selection pool | Score < 0.60 → 1 strike, dropped |

Checks at SIGNATURE_CHECK (all must pass): wavelength in band; wavelength
within ±50 nm of registry; modulation known; TID in registry, ≠ self, not
blacklisted; sequence modular-newer across ≥2 decoded frames (implies the
10-frame dwell of §4.3); decoded emission flag ∈ {BEACONING, LINKED};
capability/nav extension well-formed (malformed → treated as absent per
legacy-tolerance rule, **not** a failure — absence only fails if the registry
*requires* nav for that terminal).

### 5.4 Confidence score (fixed weights) **[FIX]**
v1 gave CRC a 0.20 score weight while also hard-rejecting CRC failures, so the
weight could never vary. CRC is now a **pre-scoring gate only**; weights
renormalised to 1.00:

```text
score = 0.30·wavelength_match + 0.25·snr + 0.20·sequence_continuity
      + 0.15·centroid_stability + 0.10·power_consistency
```

- *wavelength_match:* 1 − |reported − expected|/50, clipped [0,1].
- *snr:* min(1, (SNR_dB − 6)/12).
- *sequence_continuity:* consecutive cleanly-advancing frames / 5, capped at 1.
- *centroid_stability:* 1 − min(1, variance_px / 25) over last ≤10 frames.
- *power_consistency:* agreement of received peak with the **radiometric
  expectation** `P_rx ∝ P_tx · attenuation(range, channel) / footprint²`,
  computed from telemetry + channel state — never the display formula (§2.9).
- Pool threshold: **≥ 0.60**.

*Worked example:* RT-001 reports 1552 nm (expected 1550 → 0.96), SNR 14 dB
(→ 0.67), 4 clean sequences (→ 0.8), centroid variance 4 px² (→ 0.84),
power agreement 0.9 → score = 0.30·0.96+0.25·0.67+0.20·0.8+0.15·0.84+0.10·0.9
= **0.83** → enters pool.

### 5.5 Strike-based blacklist **[FIX — replaces "permanent on any failure"]**
A scintillating channel *will* corrupt OOK frames; permanently blacklisting on
the first CRC failure would eventually exile every real target. Specified:

- Validation failure (DECODING / SIGNATURE_CHECK / score) = **1 strike** on
  that Terminal ID, timestamped.
- **3 strikes within a 30 s sliding window → session blacklist.** Registry
  checked at DETECTED; blacklisted spots dropped before decode.
- Detection-stage misses never strike. Unknown IDs never strike (ignored).
- Blacklist clears **only on full reset** (§8.3). It is *preserved* across
  tracking loss and re-acquisition escalation.
- *Example:* RT-002 fails CRC twice during a 2 s fade (2 strikes), then
  decodes cleanly — no blacklist, 3rd-frame continuity resumes. A spoofer
  with static sequence numbers strikes out within ~1 s of observation.

---

## 6. Phase 3 — Target selection

`selected = argmax(score)` over SCORED candidates. Tie within 0.05 → higher
sequence-continuity wins (longer stable history). On selection, lock TID,
signature, motion model, centroid into the tracker. Non-selected SCORED
candidates enter the **standby pool** (not blacklisted) as re-acquisition
alternates. Empty pool after a full cycle → autonomy supervisor decides
(§8.3), never the selector.

---

## 7. Phase 4 — Continuous tracking

### 7.1 Tracking loop (runs every camera frame, ≥30 Hz)
1. Predict centroid from motion model (§7.3) with uncertainty window.
2. Search predicted region in current frame. Found → update centroid, model,
   and pan/tilt command (existing PID: filtered-D, anti-windup, deadband).
3. Not found → coast (hold last command), expand radius incrementally around
   prediction, cap **±30 px**.
4. Missed > **10 consecutive frames (~333 ms ≈ one 336-chip beacon period)**
   → declare lost → Phase 6. The horizon spans OOK blink plus the header's
   long zero-runs (version/type/length bytes hide the spot for whole camera
   frames on real frames — verified on live beacon traffic); counting every
   dark frame as lost would flap lock on clean air. Chip-aware miss gating
   (the decoder knows chip phase) tightens this in Stage 3.

### 7.2 Tracking quality table

| Metric | In-spec | Action on breach |
|---|---|---|
| Centroid error ≤ 10 px | Nominal | — |
| Error 10–30 px | Warning | Tighten prediction (raise α temporarily), flag telemetry |
| Misses > 10 consecutive (~333 ms) | Lost | → Phase 6 (blink-bridged per §7.1 step 4) |
| Session loss rate < 5% | Healthy | Breach → widen re-acq window defaults, log |

### 7.3 Motion model (specified) **[FIX — was "motion model" with no model]**
Constant-velocity **α-β filter** per axis, updated on each associated
detection at frame dt:

```text
predict:  x_p = x + v·dt
update:   x = x_p + α·(z − x_p);   v = v + (β/dt)·(z − x_p)
defaults: α = 0.4, β = 0.05 at 30 Hz; initialise v = 0 on first two associations.
```

Prediction uncertainty σ grows +2 px per coasted frame, capped by the ±30 px
search cap. The α-β tracker is deliberately simple (no full Kalman matrices)
so it stays deterministic and testable; upgrade path is documented in §11.

### 7.4 In-track signature re-check
Every **30 frames** (~1 s): verify sequence-newer + TID on the newest decoded
beacon frame. Failure → immediate re-acquisition (§8), **not** a strike, **not**
a reset (the target was already validated; this guards substitution, not identity).

---

## 8. Phase 5 — Re-acquisition

### 8.1 Entry
> 10 consecutive centroid misses (~333 ms) with a known TID + motion model. (Contrast with
§4: no model there → full scan, not re-acquisition.)

### 8.2 Localised procedure
1. Predict location at current timestamp; slew directly there.
2. Search window: radius 50 px, +20 px per step on miss.
3. **Provisional resume gate (honest lightweight check) [FIX]:** resume
   tracking provisionally on photometric detection + TID bytes from the
   48-chip header prefix + motion-gate agreement. v1 claimed "CRC without
   DECODING", which is impossible — CRC spans the whole frame.
4. **Confirm** on the next full-frame CRC pass (≤336 ms later). No confirm →
   drop back to step 2 with expanded window.
5. Standby pool (§6) is searched in parallel by score order.

### 8.3 Escalation ladder (blacklist and motion model preserved throughout)
1. Predicted-location window (≤ half scene).
2. Standby-pool candidates.
3. Last-known 3×3 priority scan.
4. Full systematic scan (§4) with motion-weighted order — **not** a reset.
5. Only if the full scan yields no SCORED candidate → supervisor's reset
   policy (§9.3).

### 8.4 Timing budget (≤1 s spec, honest breakdown at 30 Hz)
Slew (distance-limited by 5°/s gimbal — a full-scene slew alone can exceed
1 s; the spec binds the *local* procedure) + detect ≤3 frames (100 ms) +
header-prefix observe ≤2 frames (67 ms) + confirm ≤10 frames (336 ms).
Typical local case ≈ **0.5 s**; the budget table must be re-proven by test
after implementation (acceptance test in §10).

---

## 9. Autonomy supervisor (new — v1 had triggers but no supervisor)

### 9.1 Transition table (all autonomous, all logged with sim timestamp)

| Transition | Trigger |
|---|---|
| Search → Detection | Photometric threshold crossed |
| Detection → Validation | Preamble/sync correlated |
| Validation → Selection | Score ≥ 0.60 |
| Selection → Tracking | Target locked, model initialised |
| Tracking → Re-acquisition | > 10 consecutive misses (~333 ms) |
| Re-acquisition → Tracking | Provisional gate, then CRC confirm |
| Any → Full reset | §9.3 policy only |

### 9.2 Watchdogs (no state may wait forever)
DECODING ≤ 672 ms (2 beacon periods); selection decided each scan cycle;
re-acq window bounded by half scene; OOK-low silence is *expected* physics,
never a fault — only the supervisor's timers interpret absence.

### 9.3 Reset policy (two levels — fixes v1's §3.5/§6.3 ambiguity)
- **Escalation scan:** clears visited registry and candidates; **preserves**
  blacklist, motion model, standby pool.
- **Full reset:** additionally clears blacklist/model/standby, centres camera,
  restarts Phase 1. Allowed only after escalation scan finds nothing, rate-
  limited to **3 per 5 min**; beyond that, hold wide-scan and raise a fault
  flag instead of reset-looping.

### 9.4 Calibration procedure (thresholds are hypotheses until this runs)
ROC sweep of §5.1 thresholds against scripted scenes (clean / haze / fog /
high jitter / multi-terminal + spoofers). Ship the sweep as a test; freeze
thresholds only when detection ≥95% at ≤1 false candidate per scan cycle on
the calibration set.

---

## 10. Telemetry & acceptance tests

Every phase transition emits timestamped telemetry (the dashboard's
acquisition/reacquisition/loss counters are currently hardcoded zeros —
wiring them is part of Stage 1, §11). Acceptance criteria:

1. Clean scene: acquire default terminal in ≤1 scan cycle, lock error ≤10 px.
2. Fog + jitter: acquisition succeeds, loss rate <5%, re-acq ≤1 s (local case).
3. Spoofer (wrong TID, static sequence): never selected; strikes out, blacklisted.
4. FAULT terminal: no photons, no candidates, no strikes, no blacklist entries.
5. Full-scene empty: escalation → rate-limited full reset, no reset loop.
6. Determinism: identical seeds → identical phase-transition logs.

## 11. Implementation roadmap (maps to prior fix list 1, 2, 6, 4, 3)

- **Stage 1 (camera/control #1,#2):** centroid detector + §5.1 thresholds;
  PID error sourced from detected centroid; coast on miss; wire real
  acquisition/loss metrics. Proves the loop can see.
- **Stage 2 (control #6, autonomy):** α-β motion model (§7.3), ±30 px
  prediction search, 3-miss loss rule, encoder-measured feedback toggle.
- **Stage 3 (validation):** lifecycle machine, strike blacklist, scoring —
  requires §3 registry and §5.4 radiometric model.
- **Stage 4 (search/re-acq):** §4 grid controller, escalation ladder, standby
  pool, supervisor + watchdogs + reset policy.
- **Later (#4 rate, #3 jog/zoom):** enforce `update_rate_hz` in the tick,
  MANUAL jog inputs, zoom only if scenarios demand wide-to-narrow handoff.

## 12. Open code-alignment items (do not lose)
1. `BeamModel` low-chip power 0 vs specified 0.45 extinction (§2.3).
2. Tracking still telemetry-driven — Stage 1 closes it through the image.
3. `update_rate_hz` unenforced; MANUAL has no inputs; no zoom (accepted PT-only scope until §11 revisits).
4. Re-prove §8.4 timing by test; freeze §5.1 thresholds only after §9.4 ROC sweep.

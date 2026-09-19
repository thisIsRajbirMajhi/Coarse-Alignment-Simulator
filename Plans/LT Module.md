# LT Module — Deep Analysis & Robust Improvement Plan

Complete analysis of the Local Terminal system covering all subsystems: search, detection, identification, acquisition, reacquisition, tracking, lost-target handling, candidate lifecycle, and payload receiving.

---

## Executive Summary

The LT module is architecturally sound — a thirteen-module image-only pipeline with strict no-cheat boundaries, Phase-2 identity gates, and dual-lock acquisition. However, deep code analysis reveals **42 specific issues** across robustness, correctness, reliability, and maintainability. These range from silent exception swallowing that hides real bugs, to race-like timing holes in state transitions, to missing edge-case handling that can strand the system in zombie states.

---

## User Review Required

> [!IMPORTANT]
> This plan proposes changes across **18 files** in the LT module. Some fixes (especially items in the "Critical" category) are safety-critical and could change the observable behavior of the system. Review the priority tiers carefully — Critical items should be addressed first, then High, then Medium.

> [!WARNING]
> Several proposed changes modify the core state machine transitions and lifecycle rules. These will require re-running all existing tests (`test_local_terminal.py`, `test_identity_pipeline.py`, `test_pipeline_acceptance.py`, `test_upgrade_acceptance.py`, `test_new_upgrades.py`) to validate no regressions.

---

## Analysis By Subsystem

### 🔍 1. SEARCHING ([search_manager.py](file:///c:/Users/mrajb/OneDrive/Desktop/Coarse-Alignment-Simulator/local_terminal/acquisition/search_manager.py) + [acquisition.py](file:///c:/Users/mrajb/OneDrive/Desktop/Coarse-Alignment-Simulator/local_terminal/acquisition/acquisition.py))

#### Current State
- 5 search patterns: RANDOM, RASTER, SPIRAL, SECTOR, GRID, FIGURE_8
- Suspend/resume on candidate appearance
- Hold-and-servo when validating candidates (anti-pin watchdog, 1.5s hold / 1.0s cooldown)
- Search-to-REACQ handoff via `start_at()`

#### Issues Found

| # | Severity | Issue | Location |
|---|----------|-------|----------|
| S1 | 🔴 Critical | **Search never resumes after sensor FAULT recovery.** When `sensor_fault` fires, `search.suspend()` is called. After FAULT→SEARCHING, the scanner is never restarted — `search.scanner.active` is false, `search.suspended` is true, and the `resume()` path at L986–989 only calls `start()` when `scanner.active` is false, but `suspended` is still true from the FAULT handler. The system sits idle forever. | [system.py:1042](file:///c:/Users/mrajb/OneDrive/Desktop/Coarse-Alignment-Simulator/local_terminal/core/system.py#L1042) |
| S2 | 🟡 Medium | **RASTER tilt stepping is fragile.** The 15% step (`t_span * 0.15`) doesn't guarantee full coverage — if `t_span` is small the step can undershoot, and if non-integer the tilt never exactly reaches `t_max`, causing repeated wraps without covering the bottom strip. | [acquisition.py:158](file:///c:/Users/mrajb/OneDrive/Desktop/Coarse-Alignment-Simulator/local_terminal/acquisition/acquisition.py#L158) |
| S3 | 🟡 Medium | **No search coverage tracking.** The scanner has no memory of visited regions. After a suspend+resume cycle (candidate evaluated and rejected), the scan restarts from wherever it was, potentially re-scanning the same area while leaving other regions unexplored. | [acquisition.py](file:///c:/Users/mrajb/OneDrive/Desktop/Coarse-Alignment-Simulator/local_terminal/acquisition/acquisition.py) |
| S4 | 🟢 Low | **`elapsed_time` wraps on timeout for RANDOM/SPIRAL but other patterns silently wrap.** GRID uses `elapsed_time` as its position counter — a timeout wrap resets the grid walk from cell 0, which is correct, but undocumented and inconsistent with how RASTER ignores the timeout entirely. | [acquisition.py:115-122](file:///c:/Users/mrajb/OneDrive/Desktop/Coarse-Alignment-Simulator/local_terminal/acquisition/acquisition.py#L115) |

---

### 🔎 2. DETECTION ([detection.py](file:///c:/Users/mrajb/OneDrive/Desktop/Coarse-Alignment-Simulator/local_terminal/optical/detection.py) + [candidate_detector.py](file:///c:/Users/mrajb/OneDrive/Desktop/Coarse-Alignment-Simulator/local_terminal/optical/candidate_detector.py) + [frame_processor.py](file:///c:/Users/mrajb/OneDrive/Desktop/Coarse-Alignment-Simulator/local_terminal/signal/frame_processor.py))

#### Issues Found

| # | Severity | Issue | Location |
|---|----------|-------|----------|
| D1 | 🔴 Critical | **Silent `except Exception: pass` on detection pipeline.** If `detect_beacon_candidates()` or `frame_processor.process()` throws, the frame is silently dropped with `detections = []`. This includes real bugs like shape mismatches that should crash loudly. At minimum, errors should be logged/counted for diagnostics. | [system.py:276-287](file:///c:/Users/mrajb/OneDrive/Desktop/Coarse-Alignment-Simulator/local_terminal/core/system.py#L276) |
| D2 | 🟡 Medium | **Hot-pixel rejection floor is too aggressive.** `area < 2` rejects single-pixel detections. At long range or with a small spot, a real beacon could present as a 1-pixel source. The floor should be configurable. | [detection.py:57](file:///c:/Users/mrajb/OneDrive/Desktop/Coarse-Alignment-Simulator/local_terminal/optical/detection.py#L57) |
| D3 | 🟡 Medium | **No exposure/gain adaptation.** The detection threshold is `max(minimum_peak, bg + max(12.0, 4.0*noise))`. In a bright scene (high bg), the threshold rises, but `minimum_peak` is static. A weak beacon in a bright scene gets masked. There's no feedback to adjust camera `exposure`/`gain`. | [detection.py:37](file:///c:/Users/mrajb/OneDrive/Desktop/Coarse-Alignment-Simulator/local_terminal/optical/detection.py#L37) |
| D4 | 🟢 Low | **`_next_measurement` counter in `CandidateDetector` never resets.** Over very long sessions, `M-{N}` grows unbounded. Not a correctness issue but leaks diagnostic intent. | [candidate_detector.py:15](file:///c:/Users/mrajb/OneDrive/Desktop/Coarse-Alignment-Simulator/local_terminal/optical/candidate_detector.py#L15) |

---

### 🪪 3. IDENTIFICATION ([signal_analyzer.py](file:///c:/Users/mrajb/OneDrive/Desktop/Coarse-Alignment-Simulator/local_terminal/signal/signal_analyzer.py) + [frame_decoder.py](file:///c:/Users/mrajb/OneDrive/Desktop/Coarse-Alignment-Simulator/local_terminal/signal/frame_decoder.py) + [identity_matcher.py](file:///c:/Users/mrajb/OneDrive/Desktop/Coarse-Alignment-Simulator/local_terminal/signal/identity_matcher.py))

#### Issues Found

| # | Severity | Issue | Location |
|---|----------|-------|----------|
| I1 | 🔴 Critical | **`FrameDecoder._states` leaks memory.** Per-track `TrackDecodeState` entries are created in `self._states[observation_id]` but never cleaned up when tracks are EXPIRED/REJECTED/purged. Over long sessions with many candidates, this dict grows unbounded. | [frame_decoder.py:193-205](file:///c:/Users/mrajb/OneDrive/Desktop/Coarse-Alignment-Simulator/local_terminal/signal/frame_decoder.py#L193) |
| I2 | 🔴 Critical | **`IdentityMatcher._last_seq` also leaks memory.** Same issue: per-track sequence tracking is never pruned. | [identity_matcher.py:79](file:///c:/Users/mrajb/OneDrive/Desktop/Coarse-Alignment-Simulator/local_terminal/signal/identity_matcher.py#L79) |
| I3 | 🟠 High | **Sequence validation is track-scoped but not cross-validated.** If a beacon's sequence resets (power cycle), old `_last_seq` entries cause valid frames to be rejected as `OLD_SEQUENCE`. There's no mechanism to detect a legitimate sequence reset. | [identity_matcher.py:228-242](file:///c:/Users/mrajb/OneDrive/Desktop/Coarse-Alignment-Simulator/local_terminal/signal/identity_matcher.py#L228) |
| I4 | 🟠 High | **Chip resampling loses sync precision.** `SignalAnalyzer.analyze()` resamples to the chip grid using `round()` indexing, which can misalign by up to half a chip period. This degrades the demodulator's hard decisions especially at low SNR. | [signal_analyzer.py:250-254](file:///c:/Users/mrajb/OneDrive/Desktop/Coarse-Alignment-Simulator/local_terminal/signal/signal_analyzer.py#L250) |
| I5 | 🟡 Medium | **`FrameDecoder.update()` always passes `sample_index=len(signal.chip_samples)`.** The `TrackDecodeState.push_chips()` interprets `sample_index` as an absolute position — but on every call, the signal's `chip_samples` list is freshly computed from the latest history window. This means `last_processed_sample_index` tracking is fragile: if the window shrinks (history trimmed), samples may be skipped or double-counted. | [frame_decoder.py:217](file:///c:/Users/mrajb/OneDrive/Desktop/Coarse-Alignment-Simulator/local_terminal/signal/frame_decoder.py#L217) |
| I6 | 🟡 Medium | **OOK demodulator uses `random.Random` with seed derived from… nothing.** The `rng_seed` parameter is `None` by default, making bit error injection non-deterministic between runs. This breaks test reproducibility. | [signal_analyzer.py:157](file:///c:/Users/mrajb/OneDrive/Desktop/Coarse-Alignment-Simulator/local_terminal/signal/signal_analyzer.py#L157) |
| I7 | 🟡 Medium | **`CanonicalStatus.__eq__` is asymmetric.** `CanonicalStatus("DUPLICATE_SEQUENCE") == "INVALID_SEQUENCE"` is True, but `"INVALID_SEQUENCE" == CanonicalStatus("DUPLICATE_SEQUENCE")` is False. This can cause subtle bugs in any dict/set/if chain that reverses the comparison order. | [identity_matcher.py:22-36](file:///c:/Users/mrajb/OneDrive/Desktop/Coarse-Alignment-Simulator/local_terminal/signal/identity_matcher.py#L22) |

---

### 🎯 4. ACQUISITION ([acquisition_mgr.py](file:///c:/Users/mrajb/OneDrive/Desktop/Coarse-Alignment-Simulator/local_terminal/acquisition/acquisition_mgr.py))

#### Issues Found

| # | Severity | Issue | Location |
|---|----------|-------|----------|
| A1 | 🟠 High | **SELECTED state is immediately overwritten to ACQUIRED.** Lines 172–175: `if acquired and track.lifecycle_state == IDENTIFIED: track.lifecycle_state = SELECTED` followed immediately by `if acquired: track.lifecycle_state = ACQUIRED`. The SELECTED state exists for exactly zero frames. This makes the SELECTED→ACQUIRING→ACQUIRED documented lifecycle impossible. | [acquisition_mgr.py:172-175](file:///c:/Users/mrajb/OneDrive/Desktop/Coarse-Alignment-Simulator/local_terminal/acquisition/acquisition_mgr.py#L172) |
| A2 | 🟠 High | **ACQUIRING state is never entered.** The documented lifecycle shows `SELECTED → ACQUIRING → ACQUIRED`, but no code ever sets `CandidateState.ACQUIRING`. The PTZ centering manoeuvre is supposed to happen in ACQUIRING, but the state is skipped entirely. | Entire codebase (grep for ACQUIRING) |
| A3 | 🟡 Medium | **Confirmation window bounded at 32 but checked over `minimum_confirmation_count * 5`.** If `minimum_confirmation_count` is large (e.g., 10), the check window is 50, but only 32 entries are kept. This means the window can never accumulate enough positives. | [acquisition_mgr.py:161-163](file:///c:/Users/mrajb/OneDrive/Desktop/Coarse-Alignment-Simulator/local_terminal/acquisition/acquisition_mgr.py#L161) |
| A4 | 🟡 Medium | **`_prev_centroid` dict also leaks memory.** Never pruned for dead tracks. | [acquisition_mgr.py:57](file:///c:/Users/mrajb/OneDrive/Desktop/Coarse-Alignment-Simulator/local_terminal/acquisition/acquisition_mgr.py#L57) |
| A5 | 🟡 Medium | **Dual-lock bypass path is opaque.** When `legacy_optical_mode=True`, `id_locked` is set to True, bypassing identity entirely. But the lifecycle still advances through comm-path states (SIGNAL_DETECTED→DECODING→IDENTITY_UNKNOWN) which can stall the candidate. The legacy path and comm path can fight. | [acquisition_mgr.py:153-156](file:///c:/Users/mrajb/OneDrive/Desktop/Coarse-Alignment-Simulator/local_terminal/acquisition/acquisition_mgr.py#L153) |

---

### 🔄 5. REACQUISITION ([reacquisition.py](file:///c:/Users/mrajb/OneDrive/Desktop/Coarse-Alignment-Simulator/local_terminal/acquisition/reacquisition.py))

#### Issues Found

| # | Severity | Issue | Location |
|---|----------|-------|----------|
| R1 | 🔴 Critical | **`predict()` mutates `last_known` — called once per frame in coast, but also called implicitly by `can_merge()` via `self.last_known`.** If `can_merge()` is called before the coast prediction, the prediction double-steps. The comment at L753 warns about this but the protection is fragile. | [reacquisition.py:55-63](file:///c:/Users/mrajb/OneDrive/Desktop/Coarse-Alignment-Simulator/local_terminal/acquisition/reacquisition.py#L55) |
| R2 | 🟠 High | **Velocity model is zero-order hold — no decay.** During coast, the velocity at loss time is held constant forever. A decelerating target overshoots the prediction cone, and the spiral dither may not compensate because `stage_r_deg` grows slowly (2°→5° over 0.5s). | [reacquisition.py:60-62](file:///c:/Users/mrajb/OneDrive/Desktop/Coarse-Alignment-Simulator/local_terminal/acquisition/reacquisition.py#L60) |
| R3 | 🟠 High | **Reacquisition merge requires `new_seq > old_seq`, but sequence may wrap at 255→0.** The beacon protocol uses an 8-bit counter. `can_merge_reacquisition()` requires `new_seq > old_seq`, which fails on legitimate wrap: old_seq=254, new_seq=1 → merge rejected → false LOST. | [reacquisition.py:131-134](file:///c:/Users/mrajb/OneDrive/Desktop/Coarse-Alignment-Simulator/local_terminal/acquisition/reacquisition.py#L131) |
| R4 | 🟡 Medium | **`validate_reobserved()` is never called.** The public method exists but `system.py` only uses `can_merge_reacquisition()` for the merge decision. The SNR and spatial gate in `validate_reobserved()` are therefore dead code. | [reacquisition.py:79-88](file:///c:/Users/mrajb/OneDrive/Desktop/Coarse-Alignment-Simulator/local_terminal/acquisition/reacquisition.py#L79) |
| R5 | 🟡 Medium | **1.5s timeout is hardcoded** at `ReacquisitionConfig(lost_target_timeout=1.5)` in `system.py` even though the config class supports custom values. The config from `config.py` is never propagated. | [system.py:96-97](file:///c:/Users/mrajb/OneDrive/Desktop/Coarse-Alignment-Simulator/local_terminal/core/system.py#L96) |

---

### 📡 6. TRACKING ([tracking.py](file:///c:/Users/mrajb/OneDrive/Desktop/Coarse-Alignment-Simulator/local_terminal/tracking/tracking.py) + [estimator.py](file:///c:/Users/mrajb/OneDrive/Desktop/Coarse-Alignment-Simulator/local_terminal/tracking/estimator.py) + [tracking_controller.py](file:///c:/Users/mrajb/OneDrive/Desktop/Coarse-Alignment-Simulator/local_terminal/tracking/tracking_controller.py))

#### Issues Found

| # | Severity | Issue | Location |
|---|----------|-------|----------|
| T1 | 🟠 High | **Dual estimator incoherence.** `system.py` maintains its own velocity estimate at L316-321 (`tr.est_vx = 0.5*inst_vx + 0.5*tr.est_vx`) AND delegates to `TrackStateEstimator.update()` at L643, which also computes `self._vx`. These two estimates diverge because they use different smoothing constants (0.5 vs 0.2) and different base signals (raw measurement vs filtered). The coast prediction in reacquisition uses the system.py estimate, while the tracking error uses the estimator's. | [system.py:316-322](file:///c:/Users/mrajb/OneDrive/Desktop/Coarse-Alignment-Simulator/local_terminal/core/system.py#L316) + [estimator.py:40-46](file:///c:/Users/mrajb/OneDrive/Desktop/Coarse-Alignment-Simulator/local_terminal/tracking/estimator.py#L40) |
| T2 | 🟠 High | **PID integral windup on lock loss.** When the target is lost, `TargetTracker.update()` returns without resetting the integral accumulators. If the target reappears at a very different position, the accumulated integral drives a huge transient. The `reset()` method zeros them, but it's only called on full reacquisition timeout, not on brief losses. | [tracking.py:91-106](file:///c:/Users/mrajb/OneDrive/Desktop/Coarse-Alignment-Simulator/local_terminal/tracking/tracking.py#L91) |
| T3 | 🟡 Medium | **EMA smoothing constant is inverted.** `alpha = 1.0 - smoothing` means `smoothing=0.2` gives `alpha=0.8`, which is actually very responsive. The parameter name is misleading — higher "smoothing" = smoother = less responsive, which is intuitive, but the code comment says "Exponential smoothing" suggesting alpha IS the smoothing factor. | [tracking.py:159](file:///c:/Users/mrajb/OneDrive/Desktop/Coarse-Alignment-Simulator/local_terminal/tracking/tracking.py#L159) |
| T4 | 🟡 Medium | **Derivative filter alpha (0.3) is hardcoded.** In `compute_control()`, the low-pass derivative filter constant is fixed at 0.3 — not tunable via config. For different mechanical systems this needs to vary. | [tracking.py:226](file:///c:/Users/mrajb/OneDrive/Desktop/Coarse-Alignment-Simulator/local_terminal/tracking/tracking.py#L226) |

---

### 💀 7. LOST TARGET HANDLING

#### Issues Found

| # | Severity | Issue | Location |
|---|----------|-------|----------|
| L1 | 🔴 Critical | **LOST→SEARCHING transition can orphan internal state.** When `active_track.lifecycle_state == LOST`, the system clears `active_observation_id` and resets the reacquisition timer, but does NOT call `self._frame_decoder.reset_track()` or `self._id_matcher.reset_track()`. The stale decode state persists — if a new candidate gets the same `observation_id` (impossible with monotonic BEACON-N), it would inherit old state. More critically, the stale entries leak. | [system.py:597-604](file:///c:/Users/mrajb/OneDrive/Desktop/Coarse-Alignment-Simulator/local_terminal/core/system.py#L597) |
| L2 | 🟠 High | **3-frame loss streak requirement before reacquisition.** L718: `if self._loss_streak >= 3`. During fast PTZ motion, a single missed frame is expected (motion blur), but 3 consecutive misses ≈ 100ms at 30fps. This means a ~100ms blind window where no reacquisition coast begins, and the prediction starts from a 100ms-stale position. | [system.py:718-720](file:///c:/Users/mrajb/OneDrive/Desktop/Coarse-Alignment-Simulator/local_terminal/core/system.py#L718) |
| L3 | 🟡 Medium | **`_loss_streak` initialized via `getattr(self, "_loss_streak", 0)`.** This attribute is not in `__init__`, so the first access creates it lazily. While not a bug per se, it's a maintenance trap — adding a `reset()` method would miss it. | [system.py:718](file:///c:/Users/mrajb/OneDrive/Desktop/Coarse-Alignment-Simulator/local_terminal/core/system.py#L718) |

---

### 🔄 8. CANDIDATE LIFECYCLE ([lifecycle.py](file:///c:/Users/mrajb/OneDrive/Desktop/Coarse-Alignment-Simulator/local_terminal/core/lifecycle.py) + [states.py](file:///c:/Users/mrajb/OneDrive/Desktop/Coarse-Alignment-Simulator/local_terminal/core/states.py))

#### Issues Found

| # | Severity | Issue | Location |
|---|----------|-------|----------|
| C1 | 🔴 Critical | **VALIDATING state exists in `CandidateState` enum but is NOT in the documentation's lifecycle diagram.** The doc says: `SEEN → TENTATIVE → SIGNAL_DETECTED → ... → IDENTIFIED`. But the code has a branch where `TENTATIVE → VALIDATING` (optical path, L127). This undocumented state creates a fork: the comm-path skips it, the optical-path requires it. Candidates in VALIDATING can stall if identity data arrives but isn't applied (the `apply_identity_result` method handles VALIDATING at L65, but only advances to SIGNAL_DETECTED). | [lifecycle.py:127-128](file:///c:/Users/mrajb/OneDrive/Desktop/Coarse-Alignment-Simulator/local_terminal/core/lifecycle.py#L127) + [states.py:46](file:///c:/Users/mrajb/OneDrive/Desktop/Coarse-Alignment-Simulator/local_terminal/core/states.py#L46) |
| C2 | 🟠 High | **Early-stage miss threshold (10 frames) is too generous.** A candidate in SEEN/TENTATIVE/SIGNAL_DETECTED that misses 10 frames is rejected. But at 30fps, 10 misses = 333ms — a star that flickers due to atmospheric scintillation can persist for that long, wasting pipeline resources. And a real beacon behind a brief occlusion gets killed too fast. The threshold should be state-dependent. | [lifecycle.py:166](file:///c:/Users/mrajb/OneDrive/Desktop/Coarse-Alignment-Simulator/local_terminal/core/lifecycle.py#L166) |
| C3 | 🟠 High | **Miss counter in lifecycle.py vs system.py is entangled.** `lifecycle.update_on_miss()` increments `track.miss_count` (L162). But `association._refresh()` resets `track.miss_count = 0` on hit (L95). And `system.py` at L464 only resets streaks for misses > 3. This creates a window where `miss_count` is 0 (association reset it) but the lifecycle saw the miss and already transitioned. | [lifecycle.py:162](file:///c:/Users/mrajb/OneDrive/Desktop/Coarse-Alignment-Simulator/local_terminal/core/lifecycle.py#L162) + [association.py:95](file:///c:/Users/mrajb/OneDrive/Desktop/Coarse-Alignment-Simulator/local_terminal/tracking/association.py#L95) |
| C4 | 🟡 Medium | **`update_on_hit()` directly mutates `lifecycle_state` in multiple places, bypassing the state machine.** Both `lifecycle.py` and `system.py` directly assign `track.lifecycle_state`. There's no central transition validator — illegal transitions (e.g., REJECTED→TRACKING) are theoretically possible via race-like sequences of `update_on_hit()` and direct assignment in `system.py:674-678`. | Multiple locations |
| C5 | 🟡 Medium | **No explicit EXPIRED→cleanup pipeline.** Tracks in EXPIRED state are purged only when `miss_count > 60` (system.py L469). But `update_on_miss()` transitions LOST→EXPIRED at `miss_count > 90`. So EXPIRED tracks linger for 60 more misses (2 seconds). The confirm_streak and acquisition windows for these tracks are cleaned at purge, not at EXPIRED transition. | [system.py:467-471](file:///c:/Users/mrajb/OneDrive/Desktop/Coarse-Alignment-Simulator/local_terminal/core/system.py#L467) |

---

### 📦 9. PAYLOAD RECEIVING & SIGNAL PROCESSING

#### Issues Found

| # | Severity | Issue | Location |
|---|----------|-------|----------|
| P1 | 🟠 High | **Signal analysis runs only on matched tracks.** The `_signal_analyzer.analyze()` call at L354 is inside the `if miss_count == 0 and last_seen_timestamp == ts:` block. This means signal analysis stops the instant a detection miss occurs, even during a brief AM null. The decoder loses chip continuity and must re-sync, adding ~1 second to reacquisition. | [system.py:349-354](file:///c:/Users/mrajb/OneDrive/Desktop/Coarse-Alignment-Simulator/local_terminal/core/system.py#L349) |
| P2 | 🟠 High | **`valid_frame_count` only increments, never resets or decays.** Once a track accumulates valid frames, even if the identity later fails repeatedly, the count remains high. This inflates apparent track quality for stale/drifted links. | [system.py:420-421](file:///c:/Users/mrajb/OneDrive/Desktop/Coarse-Alignment-Simulator/local_terminal/core/system.py#L420) |
| P3 | 🟡 Medium | **BER estimation uses SNR in dB but applies a linear formula.** `snr_lin = 10^(snr_db / 20)` is correct for amplitude. But the `erfc()` formula expects Eb/N0, not raw SNR. This overestimates the BER at high SNR and underestimates at low SNR. The error is minor in simulation but would matter for real links. | [signal_analyzer.py:209-211](file:///c:/Users/mrajb/OneDrive/Desktop/Coarse-Alignment-Simulator/local_terminal/signal/signal_analyzer.py#L209) |
| P4 | 🟡 Medium | **Synchronizer sliding match is O(n²).** For each of the ~1200 buffer positions, it slides a 16-element sync word. With 120 chips per frame (typical), this is fine, but for larger buffers (1600 chips in `TrackDecodeState.WINDOW`) it's unnecessarily slow. | [signal_analyzer.py:110-115](file:///c:/Users/mrajb/OneDrive/Desktop/Coarse-Alignment-Simulator/local_terminal/signal/signal_analyzer.py#L110) |

---

### 🏗️ 10. SYSTEM-WIDE ARCHITECTURAL ISSUES

| # | Severity | Issue | Location |
|---|----------|-------|----------|
| X1 | 🔴 Critical | **Pervasive bare `except Exception: pass`.** Counted **37 instances** in `system.py` alone. These silently swallow TypeErrors, ValueErrors, and logic bugs. A misspelled attribute, a None-dereference, or a shape mismatch all produce the same behavior as "no data." | [system.py](file:///c:/Users/mrajb/OneDrive/Desktop/Coarse-Alignment-Simulator/local_terminal/core/system.py) (throughout) |
| X2 | 🔴 Critical | **`system.py:update()` is a 870-line monolithic method.** All 13 modules execute as inline code in a single method. This makes unit testing of individual stages impossible without running the entire pipeline, and a bug in step 4c can corrupt state for step 7b. | [system.py:214-1079](file:///c:/Users/mrajb/OneDrive/Desktop/Coarse-Alignment-Simulator/local_terminal/core/system.py#L214) |
| X3 | 🟠 High | **No transition logging/audit trail.** State transitions in both the global state machine and candidate lifecycle are not logged. When the system gets stuck in an unexpected state, there's no diagnostic trace. | All state machines |
| X4 | 🟠 High | **Telemetry manager doesn't report FAULT state properly.** During FAULT, `candidate_tracks` may be stale. The telemetry reports stale positions as current. | [telemetry_mgr.py](file:///c:/Users/mrajb/OneDrive/Desktop/Coarse-Alignment-Simulator/local_terminal/telemetry/telemetry_mgr.py) |
| X5 | 🟡 Medium | **Config refresh silently catches all errors.** `refresh_config()` has 5 bare `except Exception: pass` blocks. If a config update partially applies (e.g., tracking updates but acquisition doesn't), the system runs in a half-new, half-old config. | [system.py:175-210](file:///c:/Users/mrajb/OneDrive/Desktop/Coarse-Alignment-Simulator/local_terminal/core/system.py#L175) |

---

## Proposed Changes

### Phase 1: Critical Fixes (Safety & Correctness)

---

#### [MODIFY] [system.py](file:///c:/Users/mrajb/OneDrive/Desktop/Coarse-Alignment-Simulator/local_terminal/core/system.py)

**Fix S1: Search resume after FAULT recovery**
- After the FAULT→SEARCHING state transition (L1036), explicitly call `self.search.suspended = False` and `self.search.start()` to ensure search resumes.

**Fix L1: Cleanup stale decoder/matcher state on track death**
- When `active_observation_id` is cleared (L598), call `self._frame_decoder.reset_track(old_id)` and `self._id_matcher.reset_track(old_id)`.

**Fix I1 + I2: Prune decoder/matcher state on track purge**
- In the purge loop at L467-471, when a track is deleted, also call `self._frame_decoder.reset_track(tid)` and `self._id_matcher.reset_track(tid)`.

**Fix D1: Replace bare exception handlers with error counting**
- Add a `self._error_counts: dict[str, int]` counter. Replace the 37 bare `except Exception: pass` blocks with `except Exception as e: self._error_counts[stage_name] = self._error_counts.get(stage_name, 0) + 1`. Critical stages (detection, signal analysis, identity matching) should propagate the count into telemetry.

**Fix X1: Selective exception handling**
- Replace `except Exception: pass` in detection/signal/identity paths with `except (ValueError, TypeError, IndexError, KeyError)` to avoid masking logic bugs like `AttributeError`.

**Fix L3: Initialize `_loss_streak` in `__init__`**
- Add `self._loss_streak = 0` to `__init__`.

---

#### [MODIFY] [lifecycle.py](file:///c:/Users/mrajb/OneDrive/Desktop/Coarse-Alignment-Simulator/local_terminal/core/lifecycle.py)

**Fix C1: Unify VALIDATING with the comm-path**
- In `apply_identity_result()`, handle the VALIDATING state explicitly: if identity data arrives for a VALIDATING track, transition it through the comm-path states (SIGNAL_DETECTED→DECODING→IDENTITY_UNKNOWN) rather than leaving it stranded.

**Fix C4: Add transition validation**
- Add a `_VALID_TRANSITIONS` dict mapping each state to its allowed successors. Wrap all `track.lifecycle_state = X` assignments with a `_transition(track, X)` helper that asserts the transition is valid and logs it.

---

#### [MODIFY] [acquisition_mgr.py](file:///c:/Users/mrajb/OneDrive/Desktop/Coarse-Alignment-Simulator/local_terminal/acquisition/acquisition_mgr.py)

**Fix A1 + A2: Implement SELECTED → ACQUIRING → ACQUIRED properly**
- Remove the immediate overwrite at L175. Instead: `IDENTIFIED → SELECTED` (when acquisition manager selects). `SELECTED → ACQUIRING` (when PTZ command is issued). `ACQUIRING → ACQUIRED` (when dual lock confirms).

**Fix A3: Bound confirmation window correctly**
- Change the window size from 32 to `max(32, minimum_confirmation_count * 5 + 4)`.

---

#### [MODIFY] [reacquisition.py](file:///c:/Users/mrajb/OneDrive/Desktop/Coarse-Alignment-Simulator/local_terminal/acquisition/reacquisition.py)

**Fix R1: Make prediction non-mutating**
- Change `predict()` to return the prediction without modifying `self.last_known`. Add a separate `advance()` method that both predicts and updates. Only call `advance()` from the single authorized coast path.

**Fix R3: Handle sequence wrap**
- Replace `new_seq > old_seq` with a modular comparison: `(new_seq - old_seq) % 256 < 128` to handle the 8-bit wrap.

---

### Phase 2: High-Priority Improvements (Reliability)

---

#### [MODIFY] [system.py](file:///c:/Users/mrajb/OneDrive/Desktop/Coarse-Alignment-Simulator/local_terminal/core/system.py)

**Fix T1: Unify velocity estimation**
- Remove the inline velocity estimate at L316-322. Let the `TrackStateEstimator` be the single source of truth. Expose `est_vx/est_vy` via the estimator's output rather than computing them in two places.

**Fix P1: Continue signal analysis during brief misses**
- Move the `_signal_analyzer.analyze()` call outside the `miss_count == 0` guard. Use the track's `temporal.intensity_history` (which persists across misses) so the decoder maintains chip continuity.

**Fix L2: Reduce loss streak threshold**
- Change `_loss_streak >= 3` to `_loss_streak >= 2` for tracks in TRACKING state (where prediction is reliable). Keep 3 for ACQUIRED (less stable velocity estimate).

**Fix P2: Add valid_frame_count decay**
- Every N frames without a valid frame, decrement `valid_frame_count` by 1. This naturally ages out stale validity.

---

#### [MODIFY] [reacquisition.py](file:///c:/Users/mrajb/OneDrive/Desktop/Coarse-Alignment-Simulator/local_terminal/acquisition/reacquisition.py)

**Fix R2: Velocity decay during coast**
- Apply exponential decay to velocity during coast: `self.velocity = (vx * 0.98, vy * 0.98)` per step. This avoids persistent overshoot for decelerating targets.

**Fix R5: Propagate reacquisition timeout from config**
- In `system.py`, read `lost_target_timeout` from `config.acquisition.reacquisition_timeout` if present.

---

#### [MODIFY] [identity_matcher.py](file:///c:/Users/mrajb/OneDrive/Desktop/Coarse-Alignment-Simulator/local_terminal/signal/identity_matcher.py)

**Fix I3: Sequence reset detection**
- If `new_seq < old_seq` AND `new_seq < 5` AND `old_seq > 250`, treat as a legitimate wrap/reset rather than `OLD_SEQUENCE`. Log a warning.

---

#### [MODIFY] [tracking.py](file:///c:/Users/mrajb/OneDrive/Desktop/Coarse-Alignment-Simulator/local_terminal/tracking/tracking.py)

**Fix T2: Conditional integral reset on reacquisition**
- When `target_in_fov` transitions from False→True after `lost_time > 0.5`, scale the integral accumulators by `max(0.0, 1.0 - lost_time)` to prevent windup transients.

---

#### [NEW] [system_stages.py](file:///c:/Users/mrajb/OneDrive/Desktop/Coarse-Alignment-Simulator/local_terminal/core/system_stages.py)

**Fix X2: Extract pipeline stages from `update()`**
- Extract the monolithic `update()` into named stage methods:
  - `_stage_preprocess(inp, dt, ts)` → sanitize inputs, frame validation
  - `_stage_detect(frame, cfg, ts)` → frame processing + detection
  - `_stage_associate(detections, cfg, dt, ts, cam_vel)` → association + scoring
  - `_stage_identify(track, cfg, ts)` → signal analysis + decode + identity
  - `_stage_select(alive, ts)` → selection + acquisition confirmation
  - `_stage_track_or_search(...)` → tracking/reacquisition/search dispatch
  - `_stage_state_machine(...)` → global state transition
  - `_stage_telemetry(...)` → output construction
- Each stage has a well-defined input/output and its own exception handling.

---

### Phase 3: Medium-Priority Polish (Maintainability & Diagnostics)

---

#### [MODIFY] [state_machine.py](file:///c:/Users/mrajb/OneDrive/Desktop/Coarse-Alignment-Simulator/local_terminal/core/state_machine.py)

**Fix X3: Add transition logging**
- Log every state transition with: `prev_state → new_state, trigger={has_candidates, acquired, etc.}`. Store in a bounded deque for diagnostic access.

---

#### [MODIFY] [acquisition.py](file:///c:/Users/mrajb/OneDrive/Desktop/Coarse-Alignment-Simulator/local_terminal/acquisition/acquisition.py)

**Fix S2: Correct RASTER tilt stepping**
- Use `int(round(t_span / step_size))` rows and iterate exactly, guaranteeing full coverage.

**Fix S3: Add visited-sector bitfield**
- Track which angular sectors have been scanned. After suspend→resume, prefer unvisited sectors.

---

#### [MODIFY] [detection.py](file:///c:/Users/mrajb/OneDrive/Desktop/Coarse-Alignment-Simulator/local_terminal/optical/detection.py)

**Fix D2: Make hot-pixel area threshold configurable**
- Accept `min_area` parameter (default 2), but allow 1 for long-range mode.

---

#### [MODIFY] [telemetry_mgr.py](file:///c:/Users/mrajb/OneDrive/Desktop/Coarse-Alignment-Simulator/local_terminal/telemetry/telemetry_mgr.py)

**Fix X4: Add FAULT state handling**
- When `system_state == FAULT`, annotate telemetry with `fault_reason`, `bad_frame_streak`, and clear stale position data.

**Add error_counts to telemetry output**
- Expose the error counters from X1 so the GUI/logs show which pipeline stages are failing.

---

## Open Questions

> [!IMPORTANT]
> **Q1:** The `ACQUIRING` state exists in the enum and documentation but is never entered. Should we implement the full SELECTED→ACQUIRING→ACQUIRED flow with actual PTZ centering criteria, or keep the current direct IDENTIFIED→ACQUIRED shortcut?

> [!IMPORTANT]
> **Q2:** The `VALIDATING` state is a legacy optical-path state not in the Phase-2 documentation. Should it be deprecated and removed, or kept for backward compatibility with wildcard profiles?

> [!IMPORTANT]
> **Q3:** The 1.5s reacquisition timeout is quite aggressive. For a satellite scenario with slow dynamics, should this be increased? What should the default be?

> [!IMPORTANT]
> **Q4:** The monolithic `system.py:update()` refactor (X2) is the largest change. Should we do it in this pass, or defer it to a separate follow-up to minimize risk?

---

## Verification Plan

### Automated Tests
```bash
# Run all existing tests to verify no regressions
python -m pytest tests/ -v --tb=long

# Specific test suites that exercise the modified paths
python -m pytest tests/test_local_terminal.py -v
python -m pytest tests/test_identity_pipeline.py -v
python -m pytest tests/test_pipeline_acceptance.py -v
python -m pytest tests/test_upgrade_acceptance.py -v
python -m pytest tests/test_new_upgrades.py -v
```

### New Tests Required
- **FAULT recovery test:** Assert search resumes after FAULT→SEARCHING.
- **Decoder/matcher memory leak test:** Run 1000 candidates through the pipeline, verify `_states` and `_last_seq` dicts don't grow beyond active track count.
- **Sequence wrap test:** Verify reacquisition merge succeeds across 255→0 sequence boundary.
- **SELECTED→ACQUIRING→ACQUIRED lifecycle test:** Verify all three states are visited in order.
- **Loss-streak test:** Verify reacquisition begins within 2 frames (not 3) for TRACKING state.

### Manual Verification
- Run the full simulation (`python main.py`) and observe:
  - Search sweep completes full coverage before repeat
  - Target acquisition with identity matching
  - Target loss → reacquisition coast → recovery
  - Deliberate sensor blackout → FAULT → recovery → search resumes
  - Impostor rejection (wrong terminal ID)

# Signal Processing Pipeline

> **Scope**: Temporal signal extraction, signal synchronisation, and OOK demodulation — converting raw intensity history into recovered bits.

---

## 1. Overview

The signal processing pipeline operates on the **temporal intensity history** accumulated for each candidate track. It extracts the modulated beacon signal from noisy camera measurements and converts it to a bit stream for frame parsing.

```
CandidateTrack.intensity_history  (deque of float, per camera frame)
    │
    ▼
TemporalSignalExtractor
    │  raw_signal, background_estimate, snr, normalized_signal
    │
    ▼
SignalSynchronizer
    │  SynchronizationResult (frame_start, chip_rate, confidence)
    │
    ▼
OOKDemodulator
    │  recovered_bits, bit_confidence, chip_quality, threshold
    │
    ▼
BeaconFrameParser  (see identity_and_acquisition.md)
```

All components operate **exclusively** on camera-derived data. No transmitted bits are accessible.

---

## 2. TemporalSignalExtractor (`signal_analyzer.py`)

### 2.1 Input

For each candidate, the extractor reads:
- `intensity_history` — peak or integrated intensity per frame
- `timestamp_history` — wall-clock time of each frame
- `centroid_history` — (x, y) centroid per frame

### 2.2 Processing Steps

```
intensity_history  [I₀, I₁, I₂, … I_N]
    │
    ▼  1. Background estimation
    │       background_estimate = percentile(intensity_history, 10)
    │       (uses low-percentile to avoid bias from ON chips)
    │
    ▼  2. Background subtraction
    │       signal = intensity_history - background_estimate
    │
    ▼  3. Signal normalisation
    │       signal_range = percentile(signal, 95) - percentile(signal, 5)
    │       normalized = signal / max(signal_range, ε)
    │
    ▼  4. SNR estimation
    │       signal_power = var(signal)
    │       noise_power  = var(signal - lowpass_filter(signal))
    │       snr_db = 10 * log10(signal_power / max(noise_power, ε))
    │
    ▼  5. Modulation depth estimation
    │       depth = (percentile(signal, 90) - percentile(signal, 10))
    │               / (percentile(signal, 90) + ε)
    │
    ▼  6. Signal quality score
    │       quality = f(snr_db, modulation_depth, sample_count)
    │
    ▼
ExtractedSignal
    ├── raw_intensity: np.ndarray
    ├── background_estimate: float
    ├── background_subtracted: np.ndarray
    ├── normalized_signal: np.ndarray
    ├── snr_db: float
    ├── modulation_depth: float
    ├── sample_timestamps: np.ndarray
    └── signal_quality: float
```

### 2.3 Output: `ExtractedSignal`

```python
@dataclass
class ExtractedSignal:
    raw_intensity: np.ndarray          # original values from history
    background_estimate: float
    background_subtracted: np.ndarray
    normalized_signal: np.ndarray      # range ≈ [0, 1]
    snr_db: float
    modulation_depth: float
    sample_timestamps: np.ndarray
    signal_quality: float              # 0–1 aggregate quality
    sample_count: int
```

### 2.4 Streaming Invariant

The extractor **only** reads samples in the candidate's history. It does not access any transmitted data. The history deque is bounded by the computed `history_size` (see `candidate_system.md §5`).

---

## 3. SignalSynchronizer (`signal_analyzer.py`)

### 3.1 Purpose

Detect the **preamble** and **sync word** in the normalized signal time series to determine:
- Where a beacon frame starts in the sample history.
- The effective chip rate (may differ slightly from the nominal rate due to camera jitter).
- The confidence level of the synchronisation.

### 3.2 Preamble Detection

The preamble is an alternating `10101010…` pattern at the chip rate. Detection uses **matched filtering**:

```python
# 1. Build preamble template at nominal chip rate
template = generate_preamble_template(
    chip_rate_hz=config.chip_rate_hz,
    camera_fps=camera_fps,
    n_preamble_bits=N_PREAMBLE_BITS,
)

# 2. Cross-correlate with normalized signal
correlation = correlate(normalized_signal, template, mode='valid')

# 3. Find peaks above sync_confidence_threshold
peaks = find_peaks(
    abs(correlation),
    threshold=sync_confidence_threshold,
    min_separation=min_chip_samples,
)
```

### 3.3 Sync Word Detection

After a preamble candidate, the next `len(SYNC_WORD) × samples_per_chip` samples should match `0xEB 0x90` in NRZ form:

```python
sync_template = bits_to_template(
    bytes_to_bits(SYNC_BYTES),
    samples_per_chip,
)
sync_match = correlate(
    signal[preamble_end : preamble_end + sync_len],
    sync_template,
)
sync_confidence = max(sync_match) / max_possible
```

### 3.4 Chip Rate Estimation

Using the inter-peak spacing of the preamble autocorrelation:

```python
chip_period_samples = mean(diff(preamble_zero_crossings)) / 2
estimated_chip_rate = camera_fps / chip_period_samples
```

### 3.5 Output: `SynchronizationResult`

```python
@dataclass
class SynchronizationResult:
    synchronized: bool
    frame_start_sample: int           # index in signal array
    estimated_chip_rate_hz: float
    confidence: float                 # 0–1
    reason: str
```

### 3.6 Robustness Requirements

The synchronizer must tolerate:

| Perturbation | Tolerance |
|-------------|-----------|
| Additive noise | SNR ≥ 3 dB |
| Attenuation | Up to 50% intensity reduction |
| Missing samples | Up to 10% of preamble |
| Wander | Centroid drift ≤ 1 px between frames |
| Scintillation | Amplitude variation ≤ 30% |
| Partial frame | Handle gracefully, do not crash |

**Must not** immediately synchronise on a weak false match — use the best-confidence candidate across the full search window.

---

## 4. OOKDemodulator (`signal_analyzer.py`)

### 4.1 Purpose

Given the synchronized signal and a frame-start sample index, recover the bitstream by demodulating each chip.

### 4.2 Input

```python
class OOKDemodulator:
    def demodulate(
        self,
        signal: np.ndarray,           # normalized signal
        sync_result: SynchronizationResult,
        config: DemodulatorConfig,
    ) -> OOKDecodeResult: ...
```

### 4.3 Adaptive Threshold

The demodulator uses **local statistics** rather than a fixed threshold:

```python
# Per-chip window (± half chip on each side)
chip_samples = signal[chip_start : chip_end]
local_median = median(chip_samples)

# Global adaptive threshold from signal statistics
p_low  = percentile(signal, 10)   # estimate of LOW level
p_high = percentile(signal, 90)   # estimate of HIGH level
threshold = (p_low + p_high) / 2.0

bit = 1 if local_median > threshold else 0
confidence = abs(local_median - threshold) / max(abs(p_high - p_low), ε)
```

### 4.4 Output: `OOKDecodeResult`

```python
@dataclass
class OOKDecodeResult:
    bits: list[int]                   # recovered {0, 1}
    bit_confidence: list[float]       # per-bit confidence 0–1
    chip_quality: float               # aggregate quality across all chips
    threshold: float                  # applied adaptive threshold
    n_chips: int
    n_high_confidence_chips: int
```

### 4.5 Failure Modes

A damaged signal naturally produces:
- `SynchronizationResult.synchronized = False` → no frame recovery
- Recovered bits with low `bit_confidence` → `BeaconDecodeResult.decode_confidence` low
- CRC failure on the parsed frame
- `BeaconDecodeResult.frame_detected = False`

**No synthetic bit errors are injected** during normal operation. BER injection is test-harness only.

---

## 5. Streaming Decoder State (`frame_decoder.py`)

The `FrameDecoder` is **stateful and streaming**. It tracks the last processed sample index to ensure each sample is fed to the decoder exactly once.

### Per-Candidate Decoder State

```python
@dataclass
class DecoderState:
    observation_id: str
    last_processed_sample_index: int   # increments monotonically
    sync_state: SyncState
    frame_start_sample: int | None
    chip_timing: ChipTimingState | None
    demodulated_bits: list[int]
    parser_state: ParserState
    last_valid_sequence: int | None
    last_valid_frame: BeaconDecodeResult | None
    attempt_count: int
    failure_count: int
    consecutive_failure_count: int
```

### Update Loop

```python
def update(
    self,
    observation_id: str,
    signal: ExtractedSignal,
) -> BeaconDecodeResult:

    state = self._get_state(observation_id)

    # Only process NEW samples
    new_start = state.last_processed_sample_index
    new_samples = signal.normalized_signal[new_start:]
    new_timestamps = signal.sample_timestamps[new_start:]

    if len(new_samples) == 0:
        return BeaconDecodeResult(frame_detected=False, ...)

    # Update processed index FIRST to prevent re-feeding
    state.last_processed_sample_index = len(signal.normalized_signal)

    # Synchronize
    sync_result = self.synchronizer.synchronize(new_samples, new_timestamps)

    if not sync_result.synchronized:
        return BeaconDecodeResult(frame_detected=False,
                                  synchronized=False, ...)

    # Demodulate
    ook_result = self.demodulator.demodulate(new_samples, sync_result)

    # Parse frame
    recovered_bytes = bits_to_bytes(ook_result.bits)
    parse_result = self.parser.parse(recovered_bytes)

    # Check is_new_frame
    if parse_result.frame_detected and parse_result.valid_crc:
        payload = self.payload_decoder.decode(parse_result.payload_bytes)
        is_new = (payload.sequence_number > (state.last_valid_sequence or -1))
        parse_result.is_new_frame = is_new
        if is_new:
            state.last_valid_sequence = payload.sequence_number
            state.last_valid_frame = parse_result
            state.failure_count = 0
            state.consecutive_failure_count = 0
        else:
            parse_result.is_new_frame = False   # duplicate or old
    else:
        state.failure_count += 1
        state.consecutive_failure_count += 1

    return parse_result
```

---

## 6. Modulation Detection Heuristic

Before activating the full synchronizer+demodulator chain, a lightweight **modulation detector** checks whether the signal even looks modulated:

```python
def is_modulated(signal: np.ndarray, config: ModulationDetectorConfig) -> bool:
    if len(signal) < config.min_samples:
        return False
    depth = (percentile(signal, 90) - percentile(signal, 10))
    snr = estimate_snr(signal)
    freq_peak = dominant_frequency(signal, camera_fps)
    in_range = config.min_chip_rate_hz <= freq_peak * 2 <= config.max_chip_rate_hz
    return depth > config.min_modulation_depth and snr > config.min_snr and in_range
```

Only candidates passing this check advance to `SIGNAL_DETECTED` state.

---

## 7. Configuration

```python
@dataclass
class SignalProcessingConfig:
    # Temporal signal extractor
    background_percentile: float = 10.0
    signal_normalisation_percentile_lo: float = 5.0
    signal_normalisation_percentile_hi: float = 95.0
    min_snr_for_modulation: float = 3.0
    min_modulation_depth: float = 0.2

    # Synchronizer
    preamble_correlation_threshold: float = 0.6
    sync_confidence_threshold: float = 0.5
    chip_rate_search_tolerance: float = 0.2   # ±20% of nominal

    # Demodulator
    adaptive_threshold_percentile_lo: float = 10.0
    adaptive_threshold_percentile_hi: float = 90.0
    min_chip_confidence: float = 0.3

    # Streaming decoder
    min_new_samples_to_process: int = 10
```

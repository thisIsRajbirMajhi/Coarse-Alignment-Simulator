"""Temporal signal extraction, synchronization, and OOK demodulation per Plans/Upgrade.md §§7-11.

Separates:
  - OpticalMeasurement: image-space optical characteristics (§8)
  - SignalMeasurement: temporal communication path statistics (§9)
  - TemporalSignalExtractor: extracting signal from intensity history (§9)
  - SignalSynchronizer: frame preamble & sync word detection (§10)
  - OOKDemodulator: adaptive thresholding & bit recovery (§11)
"""
from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from typing import Any

import numpy as np


@dataclass
class OpticalMeasurement:
    """Image-space optical measurements per Upgrade.md §8 & §28."""

    centroid_x: float = 0.0
    centroid_y: float = 0.0
    bounding_box: tuple[float, float, float, float] = (0.0, 0.0, 0.0, 0.0)
    area: float = 0.0
    apparent_diameter: float = 0.0
    peak_intensity: float = 0.0
    integrated_intensity: float = 0.0
    background_level: float = 0.0
    snr: float = 0.0
    shape_metrics: dict[str, Any] = field(default_factory=dict)
    spectral_estimate: float = 1550.0
    timestamp: float = 0.0


@dataclass
class SignalMeasurement:
    """Characterisation of the optical communication signal for one track (§9 & §28)."""

    chip_samples: list[float] = field(default_factory=list)
    mean_intensity: float = 0.0
    background_subtracted_intensity: float = 0.0
    normalized_intensity: list[float] = field(default_factory=list)
    estimated_chip_rate_hz: float = 8.0
    modulation_depth: float = 0.0
    chip_snr_db: float = 0.0
    snr: float = 0.0
    signal_quality: float = 0.0
    sufficient_data: bool = False
    num_samples: int = 0
    bit_error_estimate: float = 1.0
    sample_timestamps: list[float] = field(default_factory=list)
    raw_intensity: list[float] = field(default_factory=list)


class TemporalSignalExtractor:
    """Extracts normalized and background-subtracted signal from intensity history (§9)."""

    def extract(
        self,
        intensity_history: list[float],
        timestamps: list[float],
        background_level: float = 0.0,
    ) -> tuple[np.ndarray, float, float, float, float]:
        """Returns: (normed_samples, mean_intensity, bg_sub_intensity, span, snr_db)."""
        if not intensity_history:
            return np.zeros(0), 0.0, 0.0, 0.0, 0.0

        samples = np.asarray(intensity_history, dtype=float)
        mean_val = float(np.mean(samples))
        bg_sub = float(max(0.0, mean_val - background_level))

        lo = float(np.percentile(samples, 5))
        hi = float(np.percentile(samples, 95))
        span = max(hi - lo, 1.0)
        normed = np.clip((samples - lo) / span, 0.0, 1.0)

        noise_std = float(np.std(normed - np.round(normed)))
        ideal_std = 0.5
        if noise_std < 1e-6:
            snr_db = 30.0
        else:
            snr_db = float(20.0 * math.log10(max(ideal_std / noise_std, 1e-6)))
        snr_db = float(np.clip(snr_db, 0.0, 30.0))

        return normed, mean_val, bg_sub, span, snr_db


class SignalSynchronizer:
    """Frame synchronization detecting preamble (0xAA) and sync word (0xD5) (§10)."""

    SYNC_PATTERN = [1, 0, 1, 0, 1, 0, 1, 0, 1, 1, 0, 1, 0, 1, 0, 1]

    def synchronize(self, chips: list[int] | list[float]) -> tuple[bool, int, float]:
        """Searches chip stream for sync word.

        Returns: (sync_detected, frame_start_index, sync_confidence)
        """
        if len(chips) < len(self.SYNC_PATTERN):
            return False, -1, 0.0

        bin_chips = [1 if float(c) >= 0.5 else 0 for c in chips]
        p_len = len(self.SYNC_PATTERN)

        best_score = 0
        best_idx = -1
        # Sliding match
        for i in range(len(bin_chips) - p_len + 1):
            window = bin_chips[i : i + p_len]
            matches = sum(1 for a, b in zip(window, self.SYNC_PATTERN) if a == b)
            if matches > best_score:
                best_score = matches
                best_idx = i

        confidence = best_score / p_len
        # Strict match or at most 1 bit error in preamble/sync
        if best_score >= p_len - 1 and best_idx >= 0:
            return True, best_idx, confidence

        return False, -1, confidence


class OOKDemodulator:
    """Demodulates temporal intensity samples to recovered binary chips (§11).

    Uses an adaptive threshold and injects bit errors when signal quality/SNR is poor.
    """

    def demodulate(
        self,
        chip_samples: list[float],
        chip_snr_db: float,
        bit_error_estimate: float,
        rng_seed: int | None = None,
    ) -> tuple[list[int], float]:
        """Converts analog chip samples [0..1] into binary bits {0, 1}.

        Returns: (recovered_bits, bit_confidence)
        """
        if not chip_samples:
            return [], 0.0

        arr = np.asarray(chip_samples, dtype=float)
        # Adaptive threshold: Otsu-like or mid-point between 25th and 75th percentiles
        p25 = float(np.percentile(arr, 25))
        p75 = float(np.percentile(arr, 75))
        threshold = (p25 + p75) / 2.0 if (p75 - p25) > 0.1 else 0.5

        # Decision
        raw_bits = [1 if float(s) >= threshold else 0 for s in chip_samples]

        # Natural corruption if BER is significant
        recovered_bits = list(raw_bits)
        if bit_error_estimate > 0.05:
            rng = random.Random(rng_seed)
            for idx in range(len(recovered_bits)):
                if rng.random() < bit_error_estimate:
                    recovered_bits[idx] = 1 - recovered_bits[idx]

        conf = float(np.clip(chip_snr_db / 20.0, 0.0, 1.0))
        return recovered_bits, conf


class SignalAnalyzer:
    """Extracts SignalMeasurement from CandidateTrack temporal history.

    Integrates TemporalSignalExtractor, SignalSynchronizer, and OOKDemodulator (§§9-11).
    """

    MIN_SAMPLES_FOR_SYNC = 40

    def __init__(self) -> None:
        self.extractor = TemporalSignalExtractor()
        self.synchronizer = SignalSynchronizer()
        self.demodulator = OOKDemodulator()

    def analyze(
        self,
        intensity_history: list[float],
        timestamps: list[float],
        expected_chip_rate_hz: float = 8.0,
        background_level: float = 0.0,
    ) -> SignalMeasurement:
        n = len(intensity_history)
        meas = SignalMeasurement(
            num_samples=n,
            sample_timestamps=list(timestamps[-120:]),
            raw_intensity=list(intensity_history[-120:]),
        )

        if n < 4:
            return meas

        normed, mean_val, bg_sub, span, snr_db = self.extractor.extract(
            intensity_history, timestamps, background_level
        )
        meas.mean_intensity = mean_val
        meas.background_subtracted_intensity = bg_sub
        meas.normalized_intensity = list(normed[-120:])
        meas.chip_snr_db = snr_db
        meas.snr = snr_db

        hi = float(np.percentile(intensity_history, 95))
        meas.modulation_depth = float(np.clip(span / max(hi, 1.0), 0.0, 1.0))

        # BER estimate from SNR
        snr_lin = 10.0 ** (meas.chip_snr_db / 20.0)
        meas.bit_error_estimate = float(0.5 * math.erfc(snr_lin / (2.0 * math.sqrt(2.0))))
        meas.bit_error_estimate = float(np.clip(meas.bit_error_estimate, 0.0, 0.5))

        # Signal quality
        meas.signal_quality = float(np.clip((meas.chip_snr_db / 20.0) * meas.modulation_depth, 0.0, 1.0))

        # Frame rate / dt
        if len(timestamps) >= 2:
            dts = np.diff(np.asarray(timestamps[-min(n, 60):], dtype=float))
            dt_med = float(np.median(dts[dts > 1e-6])) if dts.size > 0 else 0.033
        else:
            dt_med = 0.033
        frame_rate = 1.0 / max(dt_med, 1e-4)

        # Autocorrelation to estimate chip period
        chip_rate = float(max(0.5, expected_chip_rate_hz))
        if n >= self.MIN_SAMPLES_FOR_SYNC:
            try:
                lag_samples = max(1, int(round(frame_rate / chip_rate)))
                corr_len = min(n // 2, int(lag_samples * 4))
                if corr_len >= 2:
                    normed_ac = normed[-min(n, 120):]
                    normed_ac = normed_ac - normed_ac.mean()
                    ac = np.correlate(normed_ac, normed_ac, mode="full")
                    ac = ac[len(ac) // 2 :]
                    search_start = max(1, lag_samples // 2)
                    search_end = min(len(ac) - 1, lag_samples * 3)
                    if search_end > search_start:
                        peak_lag = int(np.argmax(ac[search_start:search_end])) + search_start
                        if peak_lag > 0:
                            chip_rate = float(frame_rate / peak_lag)
                            chip_rate = float(np.clip(chip_rate, 0.5, 30.0))
            except Exception:
                pass
        meas.estimated_chip_rate_hz = chip_rate

        # Resample to chip rate grid
        samples_per_chip = max(1.0, frame_rate / chip_rate)
        n_chips_avail = int(n / samples_per_chip)
        chip_vals: list[float] = []
        for ci in range(n_chips_avail):
            i0 = int(round(ci * samples_per_chip))
            i1 = min(n, int(round((ci + 1) * samples_per_chip)))
            if i1 > i0:
                chip_vals.append(float(normed[i0:i1].mean()))
        meas.chip_samples = chip_vals
        meas.sufficient_data = len(chip_vals) >= 40
        return meas

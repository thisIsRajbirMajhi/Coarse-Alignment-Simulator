# local_terminal/signal_analyzer.py - Module: Signal Analyzer
#
# Extracts and characterises the communication signal embedded in a candidate
# track's intensity history.  Operates purely on sampled intensity values —
# no world coordinates, no remote terminal objects.
#
# Output: SignalMeasurement — used by FrameDecoder as its raw input.
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

import numpy as np


@dataclass
class SignalMeasurement:
    """Characterisation of the optical communication signal for one track."""
    # Raw normalised chip samples (each in [0, 1])
    chip_samples:       list[float] = field(default_factory=list)
    # Estimated chip rate (Hz) derived from autocorrelation / zero-crossing
    estimated_chip_rate_hz: float = 0.0
    # Modulation depth: (peak - floor) / peak; 0 = CW, 1 = full OOK
    modulation_depth:   float = 0.0
    # Signal SNR at the chip level (dB)
    chip_snr_db:        float = 0.0
    # Whether there is enough data to attempt decoding
    sufficient_data:    bool  = False
    # Number of samples in the window
    num_samples:        int   = 0
    # Bit-error estimate from chip noise (0..1)
    bit_error_estimate: float = 1.0
    # Raw history snapshot (for debug / telemetry)
    raw_intensity:      list[float] = field(default_factory=list)


class SignalAnalyzer:
    """Extracts SignalMeasurement from a CandidateTrack's temporal history.

    Called once per frame for each active track.  Designed to be stateless
    between calls so it works in parallel on multiple candidates.

    Minimum samples before attempting decode:  2 × FRAME_BITS / chip_rate_hz × frame_rate
    At 8 Hz chip rate, 30 fps: 2 × 56 / 8 × 30 = 420 frames ≈ 14 s
    That is conservative; in practice one full frame (56 chips × 3.75 samples = 210 samples ≈ 7 s)
    is enough once synchronisation is found.
    """

    # Minimum samples for synchronisation attempt
    MIN_SAMPLES_FOR_SYNC = 60   # ≈ 2 s at 30 fps

    def analyze(
        self,
        intensity_history: list[float],
        timestamps: list[float],
        expected_chip_rate_hz: float = 8.0,
    ) -> SignalMeasurement:
        """Produce a SignalMeasurement from raw intensity history.

        Args:
            intensity_history: sampled peak intensity values per camera frame.
            timestamps:        corresponding frame timestamps.
            expected_chip_rate_hz: nominal chip rate from DetectionConfig.
        """
        n = len(intensity_history)
        meas = SignalMeasurement(num_samples=n, raw_intensity=list(intensity_history[-120:]))

        if n < 4:
            return meas  # not enough data

        samples = np.asarray(intensity_history, dtype=float)

        # ── Normalise to [0, 1] ──────────────────────────────────────────
        lo = float(np.percentile(samples, 5))
        hi = float(np.percentile(samples, 95))
        span = max(hi - lo, 1.0)
        normed = np.clip((samples - lo) / span, 0.0, 1.0)

        # ── Modulation depth ─────────────────────────────────────────────
        meas.modulation_depth = float(np.clip(span / max(hi, 1.0), 0.0, 1.0))

        # ── Chip SNR ─────────────────────────────────────────────────────
        # Estimate SNR from bimodal separation: ideal OOK has two clusters
        # near 0 and 1. Noise blurs them. We use std of the normalised signal
        # compared to ideal OOK std (0.5).
        noise_std = float(np.std(normed - np.round(normed)))
        ideal_std = 0.5
        if noise_std < 1e-6:
            chip_snr = 30.0
        else:
            chip_snr = float(20.0 * math.log10(max(ideal_std / noise_std, 1e-6)))
        meas.chip_snr_db = float(np.clip(chip_snr, 0.0, 30.0))

        # Bit-error estimate: Gaussian approximation Q(SNR_linear / 2)
        snr_lin = 10.0 ** (meas.chip_snr_db / 20.0)
        meas.bit_error_estimate = float(0.5 * math.erfc(snr_lin / (2.0 * math.sqrt(2.0))))
        meas.bit_error_estimate = float(np.clip(meas.bit_error_estimate, 0.0, 0.5))

        # ── Chip-rate estimation via autocorrelation ─────────────────────
        # Estimate inter-sample dt
        if len(timestamps) >= 2:
            dts = np.diff(np.asarray(timestamps[-min(n, 60):], dtype=float))
            dt_med = float(np.median(dts[dts > 1e-6])) if dts.size > 0 else 0.033
        else:
            dt_med = 0.033
        frame_rate = 1.0 / max(dt_med, 1e-4)

        # Autocorrelation to find chip period
        chip_rate = float(max(0.5, expected_chip_rate_hz))
        if n >= self.MIN_SAMPLES_FOR_SYNC:
            try:
                lag_samples = max(1, int(round(frame_rate / chip_rate)))
                corr_len = min(n // 2, int(lag_samples * 4))
                if corr_len >= 2:
                    normed_ac = normed[-min(n, 120):]
                    normed_ac = normed_ac - normed_ac.mean()
                    ac = np.correlate(normed_ac, normed_ac, mode="full")
                    ac = ac[len(ac) // 2:]    # positive lags only
                    # find first peak after lag 1
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

        # ── Resample to chip-rate grid ────────────────────────────────────
        # Down-sample the normalised signal to one sample per chip via averaging
        # over a sliding window of width = frame_rate / chip_rate samples.
        samples_per_chip = max(1.0, frame_rate / chip_rate)
        n_chips_avail = int(n / samples_per_chip)
        chip_vals: list[float] = []
        for ci in range(n_chips_avail):
            i0 = int(round(ci * samples_per_chip))
            i1 = min(n, int(round((ci + 1) * samples_per_chip)))
            if i1 > i0:
                chip_vals.append(float(normed[i0:i1].mean()))
        meas.chip_samples = chip_vals
        meas.sufficient_data = len(chip_vals) >= 56  # at least one full frame worth
        return meas

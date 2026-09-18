# local_terminal/detection.py - Optical detection and beacon matching engine per LocalTerminal.md
from __future__ import annotations

import math
from typing import Any

from local_terminal.config import DetectionConfig


class DetectionEngine:
    """
    Evaluates detected optical beacon spots in FOV against configured target signature.
    Performs spectral matching, spot size estimation, modulation analysis, and SNR tests.
    """

    def __init__(self, config: DetectionConfig | None = None):
        self.config = (config or DetectionConfig()).validate()

    def evaluate_target(
        self,
        in_fov: bool,
        beacon_power: float,
        beacon_wavelength: float,
        beacon_bandwidth: float,
        beacon_divergence_mrad: float,
        modulation_type: str,
        modulation_freq_khz: float,
        estimated_snr_db: float = 12.0,
        estimated_dn: float = 100.0,
    ) -> dict[str, Any]:
        """
        Evaluate optical spot parameters against local detection criteria.
        Returns evaluation dict with confidence score, confirmation status, and match breakdown.
        """
        if not in_fov or beacon_power <= 1e-6:
            return {
                "detected": False,
                "confirmed": False,
                "confidence": 0.0,
                "snr_db": 0.0,
                "wavelength_match": False,
                "modulation_match": False,
                "spot_size_match": False,
                "intensity_match": False,
                "reason": "Not in FOV or beacon extinguished",
            }

        # 1. Wavelength match
        wl_diff = abs(beacon_wavelength - self.config.wavelength)
        wl_match = wl_diff <= (self.config.bandwidth + beacon_bandwidth) * 0.5
        wl_score = max(0.0, 1.0 - wl_diff / max(1.0, self.config.bandwidth * 2.0))

        # 2. Modulation match
        is_any_mod = self.config.modulation_type.upper() in ("ANY", "ALL", "")
        if is_any_mod:
            mod_type_match = True
            freq_match = True
            mod_match = True
            mod_score = 1.0
        else:
            mod_type_match = modulation_type.upper() == self.config.modulation_type.upper()
            freq_diff = abs(modulation_freq_khz - self.config.modulation_frequency)
            freq_match = freq_diff <= max(1.0, self.config.modulation_frequency * 0.25)
            mod_match = mod_type_match and freq_match
            mod_score = (1.0 if mod_type_match else 0.0) * max(0.0, 1.0 - freq_diff / max(1.0, self.config.modulation_frequency))

        # 3. Spot size match
        spot_diff = abs(beacon_divergence_mrad - self.config.expected_spot_size)
        spot_match = spot_diff <= self.config.expected_spot_tolerance
        spot_score = max(0.0, 1.0 - spot_diff / max(0.1, self.config.expected_spot_tolerance * 2.0))

        # 4. SNR and Intensity match
        snr_match = estimated_snr_db >= self.config.minimum_snr
        snr_score = min(1.0, max(0.0, estimated_snr_db / max(1.0, self.config.minimum_snr * 1.5)))

        intensity_match = estimated_dn >= self.config.intensity_threshold
        intensity_score = 1.0 if intensity_match else 0.0

        # Weighted aggregate confidence
        confidence = (
            0.35 * wl_score
            + 0.25 * mod_score
            + 0.20 * spot_score
            + 0.20 * snr_score
        ) * intensity_score

        confirmed = confidence >= self.config.confidence_threshold and wl_match and snr_match

        return {
            "detected": in_fov,
            "confirmed": confirmed,
            "confidence": float(confidence),
            "snr_db": float(estimated_snr_db),
            "wavelength_match": wl_match,
            "modulation_match": mod_match,
            "spot_size_match": spot_match,
            "intensity_match": intensity_match,
            "reason": "OK" if confirmed else "Confidence below threshold",
        }

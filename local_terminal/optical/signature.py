# local_terminal/signature.py - Module 5: Signature Analyzer (§§14-16).
from __future__ import annotations

import math
from typing import Any

import numpy as np

from local_terminal.core.models import (
    CandidateTrack,
    OpticalConsistencyScore,
    SignatureScores,
    TargetIdentificationSignature,
)


class SignatureAnalyzer:
    """Compare OBSERVED measurements against LOCAL signature config.

    Never retrieves config from a RemoteTerminal object. Produces
    spectral/temporal/spatial/code/quality + overall scores in [0,1].
    Brightness/SNR feed quality only, not identity (§15).
    """

    def __init__(self, signature: TargetIdentificationSignature | None = None):
        self.signature = signature or TargetIdentificationSignature()

    def _expected_visual_hz(self) -> float:
        """Video-rate envelope the renderer exposes for the configured carrier.

        Mirrors remote_terminal.optics.compute_temporal_factor: the sensor
        sees min(carrier/2, cap) Hz, not the kHz carrier itself. Comparing
        FFT estimates against the carrier directly always yields ~0.
        """
        req = self.signature.temporal_type.upper()
        fkhz = float(self.signature.temporal_freq_khz)
        if req in ("", "ANY", "ALL", "NONE"):
            return 0.0
        if req == "AM":
            return min(fkhz * 0.5, 8.0)
        if req in ("PM", "OOK"):
            return min(fkhz * 0.5, 10.0)
        if req == "PPM":
            return min(fkhz * 0.5, 12.0)
        return min(fkhz * 0.5, 8.0)

    def _temporal_scores(self, track: CandidateTrack) -> tuple[float, float, float, float, float]:
        hist = track.temporal.intensity_history
        if len(hist) < 4:
            return 0.0, 0.0, 0.0, 0.0, 0.0
        samples = np.asarray(hist, dtype=float)
        mean = max(1.0, float(np.mean(samples)))
        mod_conf = float(np.clip(np.std(samples) / mean * 3.0, 0.0, 1.0))
        est_hz, freq_conf = 0.0, 0.0
        if len(hist) >= 8 and mod_conf >= 0.03:
            try:
                ts = np.asarray(track.temporal.timestamps, dtype=float)
                sdt = float(np.median(np.diff(ts))) if len(ts) > 1 else 0.033
                if sdt > 1e-5:
                    spec = np.abs(np.fft.rfft(samples - samples.mean()))
                    if spec.size > 1:
                        peak = int(np.argmax(spec[1:]) + 1)
                        est_hz = float(np.fft.rfftfreq(samples.size, sdt)[peak])
                        freq_conf = float(np.clip(spec[peak] / max(1e-6, spec.sum()), 0.0, 1.0) * 4.0)
                        freq_conf = float(np.clip(freq_conf, 0.0, 1.0))
            except Exception:
                pass
        # Compare the observed video-rate envelope against the expected
        # video-rate envelope (both in Hz), not against the kHz carrier.
        exp_hz = self._expected_visual_hz()
        req = self.signature.temporal_type.upper()
        recent_std = float(np.std(samples[-8:])) / max(1.0, float(np.mean(samples[-8:]))) if len(samples) >= 8 else mod_conf
        if req in ("", "ANY", "ALL"):
            temporal = 1.0 if mod_conf > 0.0 else 0.3
        elif req == "NONE":
            temporal = 1.0 if (mod_conf < 0.03 or recent_std < 0.02) else 0.0
        else:
            is_modulating = (mod_conf >= 0.03 and (len(samples) < 8 or recent_std >= 0.02))
            observed_mod = "AM" if is_modulating else "NONE"
            # AM-family envelopes are all variance; discriminate by rate.
            freq_score = max(0.0, 1.0 - abs(est_hz - exp_hz) / max(1.0, 4.0))
            temporal = (0.4 + 0.6 * freq_score) if is_modulating else 0.0
            if req != observed_mod and req in ("PM", "OOK", "PPM") and observed_mod == "AM":
                # Variance alone cannot separate AM from PM/OOK: demand rate.
                temporal = 0.6 * freq_score if is_modulating else 0.0
        track.temporal.estimated_frequency = est_hz
        track.temporal.frequency_confidence = freq_conf
        track.temporal.modulation_confidence = mod_conf
        return temporal, est_hz, freq_conf, mod_conf, est_hz

    def _code_score(self, track: CandidateTrack) -> float | None:
        code = self.signature.identification_code
        if not code:
            return None
        hist_ts = track.temporal.timestamps
        hist_v = track.temporal.intensity_history
        if len(hist_v) < 12:
            return None
        try:
            bits = "".join(f"{ord(c):08b}" for c in code)
            rate = float(self.signature.code_chip_rate_hz)
            t0 = hist_ts[0]
            expected = np.asarray([1.0 if bits[int((t - t0) * rate) % len(bits)] == "1" else 0.25 for t in hist_ts])
            observed = np.asarray(hist_v, dtype=float)
            expected -= expected.mean()
            observed -= observed.mean()
            denom = float(np.linalg.norm(expected) * np.linalg.norm(observed))
            return float(np.clip(np.dot(expected, observed) / denom, -1.0, 1.0)) if denom > 1e-6 else 0.0
        except Exception:
            return 0.0

    def score_track(self, track: CandidateTrack, pixel_to_angle_mrad: float = 0.109) -> SignatureScores:
        sig = self.signature
        # spectral: majority vote over recent WELL-EXPOSED history.
        # Adjacent bands (850 vs 1550 nm) render to nearly identical BGR
        # tints, and mid/dim envelope frames dilute the hue toward the
        # wrong class with high confidence. Voting only on frames near the
        # track's own observed peak keeps the class stable; dim frames
        # hold the prior vote. Gate is relative (60% of track max) so it
        # adapts to beacon power and channel attenuation.
        wl = 1550.0
        try:
            feats = [f for f in track.feature_history[-12:] if isinstance(f, dict)]
            maxpk = max([float(f.get("peak", 0.0)) for f in feats] + [0.0])
            well = [float(f.get("spectral", 1550.0)) for f in feats
                    if float(f.get("peak", 0.0)) >= 0.6 * maxpk]
            pool = well if len(well) >= 3 else [
                float(f.get("spectral", 1550.0)) for f in feats]
            if pool:
                s = sorted(pool)
                n = len(s)
                # Proper median (average middle two for even n): a split
                # vote must not round up to a false match.
                wl = s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2.0
        except Exception:
            pass
        wl_diff = abs(wl - sig.spectral_center_nm)
        spectral = max(0.0, 1.0 - wl_diff / max(1.0, sig.spectral_tolerance_nm * 2.0))
        # spectral ambiguous gate handled by caller; keep raw score here
        temporal, _, _, _, _ = self._temporal_scores(track)
        # spatial: spot size mrad
        spot_mrad = float(track.meas_spot_px * pixel_to_angle_mrad)
        spatial = max(0.0, 1.0 - abs(spot_mrad - sig.expected_spot_mrad) / max(0.1, sig.expected_spot_tol_mrad * 2.0))
        code = self._code_score(track)
        # quality: SNR gate, not identity
        quality = float(np.clip(track.meas_snr / max(1.0, sig.minimum_snr_db * 1.5), 0.0, 1.0))
        overall = sig.overall(spectral, temporal, spatial, code, quality)
        # code-required blending (legacy behavior preserved as config-driven)
        if sig.identification_code and code is not None:
            overall = 0.80 * overall + 0.20 * max(0.0, code)
        scores = SignatureScores(spectral_score=float(spectral), temporal_score=float(temporal),
                                 spatial_score=float(spatial), code_score=code,
                                 quality_score=float(quality), overall_score=float(overall))
        track.signature = scores
        track.confidence = float(overall)
        return scores

    def confirmed(self, track: CandidateTrack) -> tuple[bool, str]:
        """Check whether the track passes the identification gate.

        Phase-2 priority logic:
        - identity_matched=True  → immediately confirmed (identity is authoritative)
        - is_impostor=True       → immediately rejected (wrong ID, hard fail)
        - identity_reason=NO_DATA → fall back to optical signature scoring (Phase-1)
        - BUILDING / LOW_CONF    → allow optical path as interim gate
        """
        # Phase-2: identity lock shortcut
        ss = track.signal_state
        if track.identity_matched:
            # Decoded identity confirmed — pass with identity confidence
            return True, "Identity confirmed: " + ss.identity_reason
        if track.is_impostor:
            return False, "Identity REJECTED: " + ss.identity_reason

        # Phase-1 optical fallback (used when no beacon protocol configured or
        # identity data still accumulating)
        sig = self.signature
        s = track.signature
        if s.spectral_score < 0.25:
            return False, "Spectral signature ambiguous"
        # Stability: adjacent bands (850 vs 1550 nm) render to nearly
        # identical tints, so single frames flap. Demand a stable class
        # over recent history before confirming.
        try:
            centers = [float(f.get("spectral", 1550.0)) for f in track.feature_history[-8:]
                       if isinstance(f, dict)]
            if len(centers) >= 4:
                import numpy as _np
                if float(_np.std(centers)) > 250.0:
                    return False, "Spectral signature unstable"
        except Exception:
            pass
        req = sig.temporal_type.upper()
        if req not in ("", "ANY", "ALL"):
            # need a short trace before AM claim
            if len(track.temporal.intensity_history) < 4:
                return False, "Temporal signature not yet confirmed"
            if s.temporal_score < 0.05:
                return False, "Temporal signature mismatch"
        if sig.identification_code and (s.code_score is None or s.code_score < sig.code_threshold):
            return False, "Identification code not correlated"
        if track.meas_snr < sig.minimum_snr_db:
            return False, "SNR below minimum"
        if s.overall_score < sig.minimum_score:
            return False, "Combined signature confidence below threshold"
        return True, "OK"


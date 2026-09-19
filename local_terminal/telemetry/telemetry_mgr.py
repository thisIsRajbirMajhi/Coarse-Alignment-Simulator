"""Telemetry Manager: builds UI-visualizable telemetry and overlay data per Plans/Upgrade.md §§34, 35."""
from __future__ import annotations

from typing import Any

from local_terminal.core.models import CandidateTrack, TargetState, UpdateOutput


def candidate_reason(t: CandidateTrack) -> str:
    """Computes diagnostic reason for candidate per Upgrade.md §35."""
    st = t.lifecycle_state.value if hasattr(t.lifecycle_state, "value") else str(t.lifecycle_state)
    reason = str(getattr(t.signal_state, "identity_reason", "") or "")
    if st == "REJECTED":
        if reason in ("ID_MISMATCH", "NET_MISMATCH"):
            return "WRONG_TERMINAL"
        if reason == "WRONG_TOKEN":
            return "WRONG_TOKEN"
        if reason == "WAVELENGTH_MISMATCH":
            return "WAVELENGTH_MISMATCH"
        if reason == "CRC_FAIL":
            return "CRC_FAILURE"
        return "WRONG_TERMINAL"
    if st == "DEGRADED":
        return "IDENTITY_DEGRADED"
    if st == "REACQUIRING":
        return "REACQUISITION"
    if st == "TRACKING":
        return "TRACKING_VALID"
    if st in ("ACQUIRED", "SELECTED", "ACQUIRING"):
        return "ACQUISITION_PENDING"
    if st == "IDENTIFIED":
        return "VALID_TARGET"
    if st == "IDENTITY_UNKNOWN":
        return "UNKNOWN_IDENTITY"
    if st == "DECODING":
        if reason == "CRC_FAIL":
            return "CRC_FAILURE"
        return "DECODING"
    if st == "SIGNAL_DETECTED":
        return "SIGNAL_DETECTED"
    return "VISIBLE_ONLY"


class TelemetryManager:
    """Builds telemetry exposing §34 output fields and §35 explainability."""

    def __init__(self):
        self.last: dict[str, Any] = {}

    def build(self, output: UpdateOutput, extra: dict[str, Any] | None = None) -> dict[str, Any]:
        extra = extra or {}
        cands = []
        active_track: CandidateTrack | None = None

        for t in output.candidate_tracks:
            if t.observation_id == output.active_observation_id:
                active_track = t
            creason = candidate_reason(t)
            cands.append({
                "observation_id": t.observation_id,
                "lifecycle": t.lifecycle_state.value if hasattr(t.lifecycle_state, "value") else str(t.lifecycle_state),
                "reason": creason,
                "x": t.meas_x,
                "y": t.meas_y,
                "est_x": t.est_x,
                "est_y": t.est_y,
                "snr_db": t.meas_snr,
                "intensity": t.meas_intensity,
                "spot_px": t.meas_spot_px,
                "spectral_score": t.signature.spectral_score,
                "temporal_score": t.signature.temporal_score,
                "spatial_score": t.signature.spatial_score,
                "code_score": t.signature.code_score,
                "quality_score": t.signature.quality_score,
                "overall_score": t.signature.overall_score,
                "confidence": t.confidence,
                "hits": t.hit_count,
                "misses": t.miss_count,
                "decoded_terminal_id": getattr(t, "decoded_terminal_id", "") or getattr(t.signal_state, "decoded_terminal_id_str", ""),
                "sequence_number": getattr(t, "sequence_number", -1) if getattr(t, "sequence_number", -1) >= 0 else getattr(t.signal_state, "decoded_sequence", -1),
                "identity_state": getattr(t, "identity_state", "UNKNOWN") or getattr(t.signal_state, "state", "IDLE"),
                "identity_confidence": getattr(t, "identity_confidence", 0.0) or getattr(t.signal_state, "identity_confidence", 0.0),
                "optical_quality": getattr(t, "optical_quality", 0.0) or t.signature.overall_score,
                "signal_quality": getattr(t, "signal_quality", 0.0) or getattr(t.signal_measurement, "signal_quality", 0.0),
            })

        ts: TargetState = output.target_state

        decoded_tid = ""
        id_state = "IDLE"
        id_conf = 0.0
        opt_qual = 0.0
        sig_qual = 0.0
        sync_state = False
        last_seq = -1

        if active_track is not None:
            decoded_tid = getattr(active_track, "decoded_terminal_id", "") or getattr(active_track.signal_state, "decoded_terminal_id_str", "")
            id_state = getattr(active_track, "identity_state", "UNKNOWN") or getattr(active_track.signal_state, "state", "IDLE")
            id_conf = float(getattr(active_track, "identity_confidence", 0.0) or getattr(active_track.signal_state, "identity_confidence", 0.0))
            opt_qual = float(getattr(active_track, "optical_quality", 0.0) or active_track.signature.overall_score)
            sig_qual = float(getattr(active_track, "signal_quality", 0.0) or getattr(active_track.signal_measurement, "signal_quality", 0.0))
            sync_state = bool(active_track.synchronization_state.get("synced", False) or active_track.signal_state.state in ("VALID", "DECODING"))
            last_seq = int(getattr(active_track, "sequence_number", -1) if getattr(active_track, "sequence_number", -1) >= 0 else getattr(active_track.signal_state, "decoded_sequence", -1))

        telem = {
            # Section 34 required output fields
            "system_state": output.local_terminal_state.value,
            "global_state": output.local_terminal_state.value,
            "active_observation_id": output.active_observation_id,
            "active_observation": output.active_observation_id,
            "decoded_terminal_id": decoded_tid,
            "identity_state": id_state,
            "identity_confidence": id_conf,
            "optical_quality": opt_qual,
            "signal_quality": sig_qual,
            "frame_sync_state": sync_state,
            "last_sequence_number": last_seq,
            "candidate_count": len(output.candidate_tracks),
            "selected_candidate": output.active_observation_id,
            "acquisition_state": output.tracking_status.target_acquired,
            "tracking_state": output.tracking_status.target_visible,
            "reacquisition_state": (output.local_terminal_state.value == "REACQUIRING"),
            "ptz_command": (
                {
                    "target_pan": output.ptz_command.target_pan,
                    "target_tilt": output.ptz_command.target_tilt,
                }
                if output.ptz_command
                else None
            ),
            "ptz_actual_state": extra.get("ptz_actual_state", None),
            # Detailed candidate metrics
            "candidates": cands,
            "target": {
                "valid": ts.valid,
                "observation": ts.observation_id,
                "measured": (ts.measured_x, ts.measured_y),
                "filtered": (ts.filtered_x, ts.filtered_y),
                "predicted": (ts.predicted_x, ts.predicted_y),
                "velocity": (ts.velocity_x, ts.velocity_y),
                "confidence": ts.confidence,
                "snr": ts.snr,
            },
            "tracking": {
                "visible": output.tracking_status.target_visible,
                "identified": output.tracking_status.target_identified,
                "acquired": output.tracking_status.target_acquired,
                "centered": output.tracking_status.target_centered,
                "error": (
                    output.tracking_status.tracking_error_x,
                    output.tracking_status.tracking_error_y,
                ),
            },
            "search": (
                {
                    "pan": output.search_command.desired_pan,
                    "tilt": output.search_command.desired_tilt,
                }
                if output.search_command
                else None
            ),
            "overlay": [
                {
                    "id": c["observation_id"],
                    "label": f"{c['observation_id']} {c['lifecycle']} ({c['reason']}) SNR {c['snr_db']:.1f}dB",
                    "x": c["x"],
                    "y": c["y"],
                    "ex": c["est_x"],
                    "ey": c["est_y"],
                }
                for c in cands
            ],
        }
        telem.update(extra)
        self.last = telem
        return telem

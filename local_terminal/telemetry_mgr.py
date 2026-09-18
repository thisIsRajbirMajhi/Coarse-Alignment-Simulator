# local_terminal/telemetry_mgr.py - Module 13: Debug/Telemetry Manager (§§31-32).
from __future__ import annotations

from typing import Any

from local_terminal.models import CandidateTrack, TargetState, UpdateOutput


class TelemetryManager:
    """Builds UI-visualizable debug telemetry (§31) + overlay data (§32)."""

    def __init__(self):
        self.last: dict[str, Any] = {}

    def build(self, output: UpdateOutput, extra: dict[str, Any] | None = None) -> dict[str, Any]:
        extra = extra or {}
        cands = []
        for t in output.candidate_tracks:
            cands.append({
                "observation_id": t.observation_id,
                "lifecycle": t.lifecycle_state.value if hasattr(t.lifecycle_state, "value") else str(t.lifecycle_state),
                "x": t.meas_x, "y": t.meas_y,
                "est_x": t.est_x, "est_y": t.est_y,
                "snr_db": t.meas_snr, "intensity": t.meas_intensity,
                "spot_px": t.meas_spot_px,
                "spectral_score": t.signature.spectral_score,
                "temporal_score": t.signature.temporal_score,
                "spatial_score": t.signature.spatial_score,
                "code_score": t.signature.code_score,
                "quality_score": t.signature.quality_score,
                "overall_score": t.signature.overall_score,
                "confidence": t.confidence,
                "hits": t.hit_count, "misses": t.miss_count,
            })
        ts: TargetState = output.target_state
        telem = {
            "global_state": output.local_terminal_state.value,
            "active_observation": output.active_observation_id,
            "candidates": cands,
            "target": {
                "valid": ts.valid, "observation": ts.observation_id,
                "measured": (ts.measured_x, ts.measured_y),
                "filtered": (ts.filtered_x, ts.filtered_y),
                "predicted": (ts.predicted_x, ts.predicted_y),
                "velocity": (ts.velocity_x, ts.velocity_y),
                "confidence": ts.confidence, "snr": ts.snr,
            },
            "tracking": {
                "visible": output.tracking_status.target_visible,
                "identified": output.tracking_status.target_identified,
                "acquired": output.tracking_status.target_acquired,
                "centered": output.tracking_status.target_centered,
                "error": (output.tracking_status.tracking_error_x,
                          output.tracking_status.tracking_error_y),
            },
            "ptz_command": ({"target_pan": output.ptz_command.target_pan,
                             "target_tilt": output.ptz_command.target_tilt}
                            if output.ptz_command else None),
            "search": ({"pan": output.search_command.desired_pan,
                        "tilt": output.search_command.desired_tilt}
                       if output.search_command else None),
            "overlay": [
                {"id": c["observation_id"], "label": f"{c['observation_id']} {c['lifecycle']} SNR {c['snr_db']:.1f}dB Score {c['overall_score']:.2f}",
                 "x": c["x"], "y": c["y"], "ex": c["est_x"], "ey": c["est_y"]}
                for c in cands
            ],
        }
        telem.update(extra)
        self.last = telem
        return telem

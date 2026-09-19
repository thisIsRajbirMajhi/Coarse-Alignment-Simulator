# local_terminal/reacquisition.py - Module 11: Reacquisition Manager (§§26-27).
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

SEQ_MODULUS = 256  # 8-bit beacon sequence counter
SEQ_FORWARD_WINDOW = 128  # forward distances below this count as advancing


def seq_is_newer(new_seq: int, old_seq: int) -> bool:
    """Modular strictly-advancing check handling 255→0 wrap and reboot.

    old_seq < 0 (unknown) accepts anything. Duplicate (distance 0) is not
    newer. Forward distance in 1..127 counts as advancing; anything else
    (replay, stale) does not.
    """
    if old_seq is None or int(old_seq) < 0:
        return True
    if new_seq is None or int(new_seq) < 0:
        return False
    return 1 <= (int(new_seq) - int(old_seq)) % SEQ_MODULUS <= SEQ_FORWARD_WINDOW - 1


@dataclass
class ReacquisitionStage:
    radius_deg: float = 2.0
    label: str = "stage-1"


@dataclass
class ReacquisitionConfig:
    lost_target_timeout: float = 1.5
    velocity_decay_tau_s: float = 2.0  # coast velocity decay (zero-order hold otherwise)
    stages: list[ReacquisitionStage] = field(default_factory=lambda: [
        ReacquisitionStage(2.0, "±2° around prediction"),
        ReacquisitionStage(5.0, "±5°"),
        ReacquisitionStage(10.0, "±10°"),
    ])


class ReacquisitionManager:
    """Predict/coast + progressively expanding local search (§26).

    Validation for re-observed candidates (§27): spatial consistency,
    signature match, temporal confirmation, quality threshold. New
    candidates get fresh BEACON-N IDs; merge only if criteria pass.
    """

    def __init__(self, config: ReacquisitionConfig | None = None):
        self.config = config or ReacquisitionConfig()
        self.active = False
        self.elapsed = 0.0
        self.last_known: tuple[float, float] | None = None  # FOV px
        self.velocity: tuple[float, float] = (0.0, 0.0)
        self.old_observation_id: str | None = None
        self.old_signature: float = 0.0

    def begin(self, last_px: tuple[float, float] | None, velocity: tuple[float, float],
              observation_id: str | None, signature: float) -> None:
        self.active = True
        self.elapsed = 0.0
        self.last_known = last_px
        self.velocity = velocity
        self.old_observation_id = observation_id
        self.old_signature = float(signature)

    def reset(self) -> None:
        self.active = False
        self.elapsed = 0.0
        self.last_known = None
        self.old_observation_id = None

    def predict(self, dt: float) -> tuple[float, float] | None:
        """Non-mutating prediction (safe to call any number of times)."""
        if not self.active or self.last_known is None:
            return None
        dt = max(0.0, float(dt))
        lx, ly = self.last_known
        vx, vy = self.velocity
        return (lx + vx * dt, ly + vy * dt)

    def advance(self, dt: float) -> tuple[float, float] | None:
        """Predict AND commit (single authorized coast step per frame).

        Velocity decays exponentially (tau from config) so a decelerating
        target does not overshoot the prediction cone forever.
        """
        pred = self.predict(dt)
        if pred is None:
            return None
        self.last_known = pred
        try:
            tau = max(0.2, float(self.config.velocity_decay_tau_s))
            decay = math.exp(-max(0.0, float(dt)) / tau)
        except (TypeError, ValueError):
            decay = 0.98
        vx, vy = self.velocity
        self.velocity = (vx * decay, vy * decay)
        return pred

    def stage(self) -> ReacquisitionStage:
        t = self.elapsed
        stages = self.config.stages
        if t < 0.5:
            return stages[0]
        if t < 1.0:
            return stages[1] if len(stages) > 1 else stages[0]
        return stages[2] if len(stages) > 2 else stages[-1]

    def step(self, dt: float) -> bool:
        """Returns True if timed out (-> LOST)."""
        self.elapsed += float(dt)
        return self.elapsed > float(self.config.lost_target_timeout)

    def validate_reobserved(self, spatial_err_px: float, signature_score: float,
                            confirmations: int, snr_db: float,
                            min_snr: float = 8.0) -> bool:
        stage = self.stage()
        # spatial gate scales with stage radius (px approx: deg*px_per_deg unknown here;
        # caller passes px error; allow generous gate that tightens early)
        spatial_ok = spatial_err_px <= (30.0 + 20.0 * self.config.stages.index(stage)
                                       if stage in self.config.stages else 40.0)
        return bool(spatial_ok and signature_score >= 0.80
                    and confirmations >= 1 and snr_db >= min_snr)

    def can_merge(self, old_track: Any, new_track: Any, max_spatial_gate_px: float = 60.0) -> bool:
        """Evaluate whether new_track can merge into old_track per Plans/New Upgrades.md §30."""
        return can_merge_reacquisition(
            old_track=old_track,
            new_track=new_track,
            predicted_pos=self.last_known,
            max_spatial_gate_px=max_spatial_gate_px,
        )


def can_merge_reacquisition(
    old_track: Any,
    new_track: Any,
    predicted_pos: tuple[float, float] | None = None,
    max_spatial_gate_px: float = 60.0,
) -> bool:
    """Authoritative check if new_track can merge with old_track during reacquisition (§30).

    Requires:
      1. Both tracks have non-empty decoded_terminal_id.
      2. new_track has verified identity_matched == True.
      3. old_track and new_track decoded_terminal_id match.
      4. new_track.last_valid_sequence > old_track.last_valid_sequence (strictly advancing).
      5. Spatial distance to predicted position <= max_spatial_gate_px.
    """
    if old_track is None or new_track is None:
        return False

    old_tid = getattr(old_track, "decoded_terminal_id", "") or getattr(getattr(old_track, "signal_state", None), "decoded_terminal_id", "")
    new_tid = getattr(new_track, "decoded_terminal_id", "") or getattr(getattr(new_track, "signal_state", None), "decoded_terminal_id", "")

    if not old_tid or not new_tid:
        return False

    new_matched = getattr(new_track, "identity_matched", False) or getattr(getattr(new_track, "signal_state", None), "identity_matched", False)
    if not new_matched:
        return False

    if old_tid != new_tid:
        return False

    old_seq = int(getattr(old_track, "last_valid_sequence", -1))
    new_seq = int(getattr(new_track, "last_valid_sequence", -1))
    if not seq_is_newer(new_seq, old_seq):
        return False

    # Spatial check
    pred = predicted_pos if predicted_pos is not None else (float(getattr(old_track, "est_x", 0.0)), float(getattr(old_track, "est_y", 0.0)))
    new_pos = (float(getattr(new_track, "meas_x", 0.0)), float(getattr(new_track, "meas_y", 0.0)))
    spatial_err = ((new_pos[0] - pred[0]) ** 2 + (new_pos[1] - pred[1]) ** 2) ** 0.5
    if spatial_err > float(max_spatial_gate_px):
        return False

    return True


# Spec alias (§28/§32)
ReacquisitionController = ReacquisitionManager

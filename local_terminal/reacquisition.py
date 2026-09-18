# local_terminal/reacquisition.py - Module 11: Reacquisition Manager (§§26-27).
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ReacquisitionStage:
    radius_deg: float = 2.0
    label: str = "stage-1"


@dataclass
class ReacquisitionConfig:
    lost_target_timeout: float = 1.5
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
        if not self.active or self.last_known is None:
            return None
        dt = max(0.0, float(dt))
        lx, ly = self.last_known
        vx, vy = self.velocity
        px, py = lx + vx * dt, ly + vy * dt
        self.last_known = (px, py)
        return (px, py)

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


# Spec alias (§28/§32)
ReacquisitionController = ReacquisitionManager

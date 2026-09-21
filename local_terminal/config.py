# local_terminal/config.py - Aggregated local-terminal autonomy configuration.
#
# Single Qt-free owner for every local-terminal tunable that was previously
# an internal default: detection gates (§5.1), validation policy (§5.3-5.5),
# image-tracker association (§7.1), α-β motion model (§7.3), scan schedule
# (§4), re-acquisition ladder (§8), supervisor watchdogs/resets (§9), and
# the standby pool (§6). The GUI edits this object; the session pushes it
# into AutonomySupervisor via apply_local_config().
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from local_terminal.detector import DetectorConfig
from local_terminal.motion import AlphaBetaConfig
from local_terminal.reacquisition import ReacquisitionConfig
from local_terminal.scan import ScanConfig
from local_terminal.supervisor import SupervisorConfig
from local_terminal.tracker import TrackerConfig
from local_terminal.validator import ValidationConfig


@dataclass
class LocalTerminalConfig:
    """All local-terminal autonomy tunables (detection → validation → track)."""

    detector: DetectorConfig = field(default_factory=DetectorConfig)
    tracker: TrackerConfig = field(default_factory=TrackerConfig)
    motion: AlphaBetaConfig = field(default_factory=AlphaBetaConfig)
    validation: ValidationConfig = field(default_factory=ValidationConfig)
    scan: ScanConfig = field(default_factory=ScanConfig)
    reacquisition: ReacquisitionConfig = field(default_factory=ReacquisitionConfig)
    supervisor: SupervisorConfig = field(default_factory=SupervisorConfig)
    # Standby pool (§6): alternate-candidate retention.
    standby_max_age_s: float = 10.0
    standby_max_size: int = 8

    def validate(self) -> "LocalTerminalConfig":
        self.detector = (self.detector or DetectorConfig()).validate()
        self.tracker = (self.tracker or TrackerConfig()).validate()
        self.motion = (self.motion or AlphaBetaConfig()).validate()
        self.validation = (self.validation or ValidationConfig()).validate()
        self.scan = (self.scan or ScanConfig()).validate()
        self.reacquisition = (self.reacquisition or ReacquisitionConfig()).validate()
        self.supervisor = (self.supervisor or SupervisorConfig()).validate()
        try:
            age = float(self.standby_max_age_s)
        except (TypeError, ValueError):
            age = 10.0
        self.standby_max_age_s = max(1.0, age)
        try:
            size = int(self.standby_max_size)
        except (TypeError, ValueError):
            size = 8
        self.standby_max_size = max(1, min(64, size))
        return self

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "LocalTerminalConfig":
        data = dict(data or {})
        try:
            det = data.get("detector", {})
            trk = data.get("tracker", {})
            mot = data.get("motion", {})
            val = data.get("validation", {})
            scn = data.get("scan", {})
            rea = data.get("reacquisition", {})
            sup = data.get("supervisor", {})
            obj = cls(
                detector=DetectorConfig(**det) if isinstance(det, dict) else DetectorConfig(),
                tracker=TrackerConfig(**trk) if isinstance(trk, dict) else TrackerConfig(),
                motion=AlphaBetaConfig(**mot) if isinstance(mot, dict) else AlphaBetaConfig(),
                validation=ValidationConfig(**val) if isinstance(val, dict) else ValidationConfig(),
                scan=ScanConfig(**scn) if isinstance(scn, dict) else ScanConfig(),
                reacquisition=ReacquisitionConfig(**rea) if isinstance(rea, dict) else ReacquisitionConfig(),
                supervisor=SupervisorConfig(**sup) if isinstance(sup, dict) else SupervisorConfig(),
                standby_max_age_s=float(data.get("standby_max_age_s", 10.0)),
                standby_max_size=int(data.get("standby_max_size", 8)),
            )
        except (TypeError, ValueError) as e:
            raise ValueError(f"Invalid local-terminal configuration: {e}") from e
        return obj.validate()


def make_default_local_terminal() -> LocalTerminalConfig:
    """Validated defaults matching all module-level Stage defaults."""
    return LocalTerminalConfig().validate()


__all__ = ["LocalTerminalConfig", "make_default_local_terminal"]

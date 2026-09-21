# local_terminal/identity.py - V2 lightweight identity validation (Plan V2 §10).
#
# Gates only, no composite score:
#   valid_crc AND known_tid AND tid != local_id AND wl in tolerance
#   AND modulation acceptable AND sequence fresh AND P_rx above floor.
# Strikes are lightweight: repeated invalid from known TID -> session blacklist.
# Detector misses never strike. Unknown IDs ignored, never blacklisted.

from __future__ import annotations

from dataclasses import dataclass, field

from common.protocol.beacon.navigation import sequence_is_newer
from local_terminal.models import AutonomyConfig, BeaconObservation
from local_terminal.registry import SignatureRegistry

ALLOWED_MODULATIONS = {"OOK", "PPM", "CW"}


@dataclass
class IdentityResult:
    accepted: bool = False
    terminal_id: str | None = None
    reason: str = "no_observation"
    strikes: int = 0
    blacklisted: bool = False


@dataclass
class IdentityConfig:
    strikes_to_blacklist: int = 3
    strike_window_s: float = 30.0
    p_rx_threshold_w: float = 0.0

    def validate(self) -> "IdentityConfig":
        self.strikes_to_blacklist = int(max(1, self.strikes_to_blacklist))
        self.strike_window_s = float(max(1.0, self.strike_window_s))
        self.p_rx_threshold_w = float(max(0.0, self.p_rx_threshold_w))
        return self


class IdentityValidator:
    """Stateless-gate validator with strike memory (V2 §10.3)."""

    def __init__(self, registry: SignatureRegistry | None = None,
                 config: IdentityConfig | None = None):
        self.registry = registry or SignatureRegistry()
        self.config = (config or IdentityConfig()).validate()
        self.strikes: dict[str, list[float]] = {}
        self.blacklist: set[str] = set()
        self.last_seq: dict[str, int] = {}

    def set_registry(self, registry: SignatureRegistry) -> None:
        self.registry = registry

    @classmethod
    def from_autonomy(cls, registry: SignatureRegistry | None,
                      cfg: AutonomyConfig) -> "IdentityValidator":
        cfg = (cfg or AutonomyConfig()).validate()
        return cls(registry, IdentityConfig(p_rx_threshold_w=cfg.p_rx_threshold_w))

    def _prune(self, tid: str, now: float) -> list[float]:
        keep = [t for t in self.strikes.get(tid, []) if now - t <= self.config.strike_window_s]
        self.strikes[tid] = keep
        return keep

    def _strike(self, tid: str, now: float) -> int:
        keep = self._prune(tid, now) + [float(now)]
        self.strikes[tid] = keep
        if len(keep) >= self.config.strikes_to_blacklist:
            self.blacklist.add(tid)
        return len(keep)

    def check(self, obs: BeaconObservation | None, now_s: float) -> IdentityResult:
        now = float(now_s)
        if obs is None or not obs.valid_crc:
            return IdentityResult(False, None, "no_valid_crc")
        tid = str(obs.terminal_id or "")
        if not tid:
            return IdentityResult(False, None, "empty_tid")
        if self.registry.is_self(tid):
            return IdentityResult(False, tid, "loopback_self_id", 0, False)
        if tid in self.blacklist:
            return IdentityResult(False, tid, "blacklisted", len(self._prune(tid, now)), True)
        if not self.registry.is_known(tid):
            return IdentityResult(False, tid, "unknown_id")
        # Wavelength gate (None = no evidence -> fail closed only if registry demands? V2: check within tolerance)
        if obs.wavelength_nm is not None:
            score = self.registry.wavelength_match_score(tid, float(obs.wavelength_nm))
            if score < 0.0:
                n = self._strike(tid, now)
                return IdentityResult(False, tid, "wavelength_out_of_spec", n, tid in self.blacklist)
        # Modulation gate (None = decoder silent -> pass; known-bad -> strike)
        if obs.modulation is not None and str(obs.modulation).upper() not in ALLOWED_MODULATIONS:
            n = self._strike(tid, now)
            return IdentityResult(False, tid, "modulation_unacceptable", n, tid in self.blacklist)
        # Power floor gate
        if float(obs.p_rx_w) < float(self.config.p_rx_threshold_w):
            return IdentityResult(False, tid, "below_p_rx_floor")
        # Sequence freshness (first sighting records, needs advance on second)
        seq = obs.sequence
        if seq is None:
            n = self._strike(tid, now)
            return IdentityResult(False, tid, "missing_sequence", n, tid in self.blacklist)
        try:
            seq_i = int(seq)
        except (TypeError, ValueError):
            n = self._strike(tid, now)
            return IdentityResult(False, tid, "missing_sequence", n, tid in self.blacklist)
        if tid in self.last_seq and not sequence_is_newer(seq_i, self.last_seq[tid]):
            self._strike(tid, now)
            return IdentityResult(False, tid, "stale_sequence",
                                  len(self._prune(tid, now)), tid in self.blacklist)
        self.last_seq[tid] = seq_i
        return IdentityResult(True, tid, "accepted",
                              len(self._prune(tid, now)), tid in self.blacklist)


__all__ = ["IdentityValidator", "IdentityConfig", "IdentityResult", "ALLOWED_MODULATIONS"]

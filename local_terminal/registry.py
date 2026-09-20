# local_terminal/registry.py - Expected-signature registry (Plan.md §3.1).
#
# Source of truth for "locally expected" values: built from the mission file
# (RemoteScenarioConfig), loaded at Phase 0. Unknown IDs are ignored, never
# blacklisted; self-ID reception is a loopback fault.

from __future__ import annotations

from dataclasses import dataclass, field


WAVELENGTH_BAND_MIN_NM: float = 800.0
WAVELENGTH_BAND_MAX_NM: float = 1700.0
WAVELENGTH_TOLERANCE_NM: float = 50.0


@dataclass
class ExpectedSignature:
    terminal_id: str
    wavelength_nm: float
    require_nav: bool = False


@dataclass
class SignatureRegistry:
    """Mission-file expectations for validation (Plan.md §3.1)."""

    entries: dict[str, ExpectedSignature] = field(default_factory=dict)
    local_id: str | None = None

    @classmethod
    def from_scenario(cls, scenario, local_id: str | None = None) -> "SignatureRegistry":
        """Build from a validated RemoteScenarioConfig (mission file)."""
        entries: dict[str, ExpectedSignature] = {}
        for term in getattr(scenario, "terminals", []):
            tid = str(getattr(term, "terminal_id", "")).strip()
            if not tid or tid in entries:
                continue
            entries[tid] = ExpectedSignature(
                terminal_id=tid,
                wavelength_nm=float(getattr(term, "wavelength_nm", 1550.0)),
                require_nav=False,
            )
        return cls(entries=entries, local_id=local_id)

    def is_known(self, terminal_id: str) -> bool:
        return str(terminal_id) in self.entries

    def is_self(self, terminal_id: str) -> bool:
        return self.local_id is not None and str(terminal_id) == str(self.local_id)

    def wavelength_match_score(self, terminal_id: str, reported_nm: float) -> float:
        """1 − |Δ|/tolerance over [0,1]; −1.0 when out of band or unknown."""
        wl = float(reported_nm)
        if not (WAVELENGTH_BAND_MIN_NM <= wl <= WAVELENGTH_BAND_MAX_NM):
            return -1.0
        exp = self.entries.get(str(terminal_id))
        if exp is None:
            return -1.0
        delta = abs(wl - exp.wavelength_nm)
        if delta > WAVELENGTH_TOLERANCE_NM:
            return -1.0
        return float(max(0.0, min(1.0, 1.0 - delta / WAVELENGTH_TOLERANCE_NM)))


__all__ = [
    "ExpectedSignature",
    "SignatureRegistry",
    "WAVELENGTH_BAND_MIN_NM",
    "WAVELENGTH_BAND_MAX_NM",
    "WAVELENGTH_TOLERANCE_NM",
]

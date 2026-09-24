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
    wl_tolerance_nm: float = WAVELENGTH_TOLERANCE_NM

    @classmethod
    def from_scenario(
        cls,
        scenario,
        local_id: str | None = None,
        wl_tolerance_nm: float | None = None,
        require_nav: bool = False,
    ) -> "SignatureRegistry":
        """Build from a validated RemoteScenarioConfig (mission file)."""
        entries: dict[str, ExpectedSignature] = {}
        for term in getattr(scenario, "terminals", []):
            tid = str(getattr(term, "terminal_id", "")).strip()
            if not tid or tid in entries:
                continue
            entries[tid] = ExpectedSignature(
                terminal_id=tid,
                wavelength_nm=float(getattr(term, "wavelength_nm", 1550.0)),
                require_nav=bool(require_nav),
            )
        tol = float(wl_tolerance_nm) if wl_tolerance_nm is not None else WAVELENGTH_TOLERANCE_NM
        tol = max(1.0, min(tol, 200.0))
        lid = str(local_id).strip() if local_id else None
        return cls(entries=entries, local_id=lid or None, wl_tolerance_nm=tol)

    def apply_expected_overrides(
        self,
        expected_tid: str | None = None,
        expected_wavelength_nm: float | None = None,
        wl_tolerance_nm: float | None = None,
        require_nav: bool | None = None,
        local_id: str | None = None,
    ) -> "SignatureRegistry":
        """Apply camera-control Expected Payload overrides in place.

        - Ensures ``expected_tid`` exists as a known entry (seeded with the
          expected wavelength when the mission file lacks it).
        - Overrides the entry wavelength / require_nav when given.
        - Updates registry-wide wavelength tolerance and self-ID.
        Returns self for chaining.
        """
        if wl_tolerance_nm is not None:
            try:
                self.wl_tolerance_nm = max(1.0, min(float(wl_tolerance_nm), 200.0))
            except (TypeError, ValueError):
                pass
        if local_id is not None:
            lid = str(local_id).strip()
            self.local_id = lid or None
        tid = str(expected_tid or "").strip()
        if tid:
            if tid not in self.entries:
                try:
                    wl = float(expected_wavelength_nm) if expected_wavelength_nm is not None else 1550.0
                except (TypeError, ValueError):
                    wl = 1550.0
                self.entries[tid] = ExpectedSignature(
                    terminal_id=tid,
                    wavelength_nm=wl,
                    require_nav=bool(require_nav) if require_nav is not None else False,
                )
            else:
                if expected_wavelength_nm is not None:
                    try:
                        self.entries[tid].wavelength_nm = float(expected_wavelength_nm)
                    except (TypeError, ValueError):
                        pass
                if require_nav is not None:
                    self.entries[tid].require_nav = bool(require_nav)
        elif require_nav is not None:
            for e in self.entries.values():
                e.require_nav = bool(require_nav)
        return self

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
        tol = max(1e-6, float(getattr(self, "wl_tolerance_nm", WAVELENGTH_TOLERANCE_NM)))
        delta = abs(wl - exp.wavelength_nm)
        if delta > tol:
            return -1.0
        return float(max(0.0, min(1.0, 1.0 - delta / tol)))


__all__ = [
    "ExpectedSignature",
    "SignatureRegistry",
    "WAVELENGTH_BAND_MIN_NM",
    "WAVELENGTH_BAND_MAX_NM",
    "WAVELENGTH_TOLERANCE_NM",
]

# local_terminal/models.py - V2 data contracts (Plan/Implementation_plan_V2.md §6, §19).
#
# Single owner for autonomy data classes. Logic-free: validation + ser/deser only.
# Ground-truth isolation: these structs carry sensor observations, never truth.

from __future__ import annotations

from dataclasses import asdict, dataclass, field


@dataclass
class SpotCandidate:
    """Camera-only observation. No identity belongs here (§6.1)."""

    x: float = 0.0
    y: float = 0.0
    peak: float = 0.0
    snr_db: float = 0.0
    area_px: int = 0
    sigma_px: float | None = None

    def validate(self) -> "SpotCandidate":
        self.x = float(self.x)
        self.y = float(self.y)
        self.peak = float(self.peak)
        self.snr_db = float(self.snr_db)
        self.area_px = int(max(0, self.area_px))
        if self.sigma_px is not None:
            self.sigma_px = float(self.sigma_px)
        return self

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "SpotCandidate":
        data = dict(data or {})
        return cls(
            x=float(data.get("x", 0.0)),
            y=float(data.get("y", 0.0)),
            peak=float(data.get("peak", 0.0)),
            snr_db=float(data.get("snr_db", 0.0)),
            area_px=int(data.get("area_px", 0)),
            sigma_px=None if data.get("sigma_px") is None else float(data["sigma_px"]),
        ).validate()


@dataclass
class BeaconObservation:
    """Photodiode/beacon decoder output (§6.2). Slot model: one per decoded frame."""

    terminal_id: str = ""
    valid_crc: bool = False
    sequence: int | None = None
    wavelength_nm: float | None = None
    modulation: str | None = None
    p_rx_w: float = 0.0
    snr_db: float = 0.0
    timestamp_s: float = 0.0

    def validate(self) -> "BeaconObservation":
        self.terminal_id = str(self.terminal_id or "")
        self.valid_crc = bool(self.valid_crc)
        if self.sequence is not None:
            self.sequence = int(self.sequence)
        if self.wavelength_nm is not None:
            self.wavelength_nm = float(self.wavelength_nm)
        if self.modulation is not None:
            self.modulation = str(self.modulation)
        self.p_rx_w = float(max(0.0, self.p_rx_w))
        self.snr_db = float(self.snr_db)
        self.timestamp_s = float(self.timestamp_s)
        return self

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "BeaconObservation":
        data = dict(data or {})
        return cls(
            terminal_id=str(data.get("terminal_id", "")),
            valid_crc=bool(data.get("valid_crc", False)),
            sequence=None if data.get("sequence") is None else int(data["sequence"]),
            wavelength_nm=None if data.get("wavelength_nm") is None else float(data["wavelength_nm"]),
            modulation=None if data.get("modulation") is None else str(data["modulation"]),
            p_rx_w=float(data.get("p_rx_w", 0.0)),
            snr_db=float(data.get("snr_db", 0.0)),
            timestamp_s=float(data.get("timestamp_s", 0.0)),
        ).validate()


@dataclass
class TargetObservation:
    """Merged TID + spot observation crossing sensor-autonomy boundary (§6.3, §7)."""

    terminal_id: str = ""
    fov_x: float = 0.0
    fov_y: float = 0.0
    p_rx_w: float = 0.0
    snr_db: float = 0.0
    timestamp_s: float = 0.0

    def validate(self) -> "TargetObservation":
        self.terminal_id = str(self.terminal_id or "")
        self.fov_x = float(self.fov_x)
        self.fov_y = float(self.fov_y)
        self.p_rx_w = float(max(0.0, self.p_rx_w))
        self.snr_db = float(self.snr_db)
        self.timestamp_s = float(self.timestamp_s)
        if not self.terminal_id:
            raise ValueError("TargetObservation requires terminal_id")
        return self

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "TargetObservation":
        data = dict(data or {})
        return cls(
            terminal_id=str(data.get("terminal_id", "")),
            fov_x=float(data.get("fov_x", 0.0)),
            fov_y=float(data.get("fov_y", 0.0)),
            p_rx_w=float(data.get("p_rx_w", 0.0)),
            snr_db=float(data.get("snr_db", 0.0)),
            timestamp_s=float(data.get("timestamp_s", 0.0)),
        ).validate()


@dataclass
class TargetTrack:
    """Active Kalman track state for one target (§6.4)."""

    terminal_id: str = ""
    x: float = 0.0
    y: float = 0.0
    vx: float = 0.0
    vy: float = 0.0
    uncertainty_px: float = 0.0
    last_measurement_time_s: float = 0.0
    last_beacon_time_s: float | None = None
    p_rx_w: float = 0.0
    misses: int = 0
    status: str = "LOST"  # TRACKING | COASTING | LOST

    def validate(self) -> "TargetTrack":
        self.terminal_id = str(self.terminal_id or "")
        self.x = float(self.x)
        self.y = float(self.y)
        self.vx = float(self.vx)
        self.vy = float(self.vy)
        self.uncertainty_px = float(max(0.0, self.uncertainty_px))
        self.last_measurement_time_s = float(self.last_measurement_time_s)
        if self.last_beacon_time_s is not None:
            self.last_beacon_time_s = float(self.last_beacon_time_s)
        self.p_rx_w = float(max(0.0, self.p_rx_w))
        self.misses = int(max(0, self.misses))
        if self.status not in ("TRACKING", "COASTING", "LOST"):
            raise ValueError(f"Invalid TargetTrack.status: {self.status}")
        return self

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "TargetTrack":
        data = dict(data or {})
        return cls(
            terminal_id=str(data.get("terminal_id", "")),
            x=float(data.get("x", 0.0)),
            y=float(data.get("y", 0.0)),
            vx=float(data.get("vx", 0.0)),
            vy=float(data.get("vy", 0.0)),
            uncertainty_px=float(data.get("uncertainty_px", 0.0)),
            last_measurement_time_s=float(data.get("last_measurement_time_s", 0.0)),
            last_beacon_time_s=None if data.get("last_beacon_time_s") is None else float(data["last_beacon_time_s"]),
            p_rx_w=float(data.get("p_rx_w", 0.0)),
            misses=int(data.get("misses", 0)),
            status=str(data.get("status", "LOST")),
        ).validate()


@dataclass
class AutonomyConfig:
    """Single source of all V2 autonomy tuning parameters (Plan Hybrid-AI §2)."""

    # Search (pattern removed — AI ranker owns scheduling; keep dwell)
    search_dwell_frames: int = 1
    search_extended_dwell_frames: int = 10
    search_start_index: int = 0
    # AI toggles (Plan Hybrid-AI §2 + simple reliable AI spec)
    ai_enabled: bool = False
    ai_verifier_threshold: float = 0.6
    ai_simple_mode: bool = False  # when True, disable scorer/predictor/ranker, only verifier
    # Confidence fusion weights per spec: 0.35/0.10/0.15/0.20/0.20 (ai/shape/brightness/motion/prediction)
    ai_confidence_weights: dict = field(default_factory=lambda: {"ai": 0.35, "shape": 0.10, "brightness": 0.15, "motion": 0.20, "prediction": 0.20})
    # Distinct thresholds for state decisions (spec)
    c_detect: float = 0.55
    c_identify: float = 0.75
    c_track: float = 0.60
    c_lost: float = 0.40

    # Detection — BUG-03 fix: detector now respects these directly (no hidden max(12,)/min(250,) override).
    # Defaults set to star-robust beacon range (12-250) so nominal behavior preserved; user can still configure 4-4000-wide range.
    candidate_min_snr_db: float = 6.0
    candidate_peak_margin: float = 8.0
    candidate_confirm_frames: int = 2
    candidate_min_area_px: int = 12
    candidate_max_area_px: int = 250

    # Association - gate must be large enough for initial acquisition when FOV is 100+px off (scan offset)
    # 60 was too small for 115px offset seen in headless tests (640 gate was too large, 60 too small)
    # 200 is balanced: allows 150px acquisition but still rejects far corners (400px) and keeps X/Y gates meaningful
    association_gate_px: float = 200.0
    association_mahal_threshold: float = 9.21  # chi2 2-dof 99%

    # Kalman
    kalman_process_noise_q: float = 8.0
    kalman_measurement_noise_r_base: float = 4.0
    kalman_r_scale_low_snr: float = 6.0
    kalman_r_scale_high_snr: float = 0.5

    # Coast / Lost thresholds
    coast_max_uncertainty_px: float = 30.0
    coast_timeout_s: float = 1.0
    lost_uncertainty_threshold_px: float = 30.0
    lost_timeout_s: float = 0.5

    # Reacquisition
    reacq_radii_px: list[float] = field(default_factory=lambda: [50.0, 100.0, 200.0, 400.0, 800.0])
    reacq_full_scan_enabled: bool = True

    # Selector
    active_target_policy: str = "priority"  # priority | strongest_prx | highest_snr
    mission_priority: list[str] = field(default_factory=list)  # ordered TID list for priority policy

    # Power gate (physical telemetry, not hardcoded blind threshold)
    p_rx_threshold_w: float = 0.0

    def validate(self) -> "AutonomyConfig":
        # Backward compat: ignore old search_pattern if present
        if hasattr(self, "search_pattern"):
            try:
                delattr(self, "search_pattern")
            except Exception:
                pass
        self.search_dwell_frames = int(max(1, self.search_dwell_frames))
        self.search_extended_dwell_frames = int(max(self.search_dwell_frames, self.search_extended_dwell_frames))
        self.candidate_min_snr_db = float(max(0.0, self.candidate_min_snr_db))
        self.candidate_peak_margin = float(max(0.0, self.candidate_peak_margin))
        self.candidate_confirm_frames = int(max(1, min(5, self.candidate_confirm_frames)))
        self.candidate_min_area_px = int(max(1, self.candidate_min_area_px))
        self.candidate_max_area_px = int(max(self.candidate_min_area_px, self.candidate_max_area_px))
        self.association_gate_px = float(max(1.0, self.association_gate_px))
        self.association_mahal_threshold = float(max(0.5, self.association_mahal_threshold))
        self.kalman_process_noise_q = float(max(1e-6, self.kalman_process_noise_q))
        self.kalman_measurement_noise_r_base = float(max(1e-6, self.kalman_measurement_noise_r_base))
        self.kalman_r_scale_low_snr = float(max(1.0, self.kalman_r_scale_low_snr))
        self.kalman_r_scale_high_snr = float(min(1.0, max(1e-3, self.kalman_r_scale_high_snr)))
        self.coast_max_uncertainty_px = float(max(1.0, self.coast_max_uncertainty_px))
        self.coast_timeout_s = float(max(0.05, self.coast_timeout_s))
        self.lost_uncertainty_threshold_px = float(max(1.0, self.lost_uncertainty_threshold_px))
        self.lost_timeout_s = float(max(0.05, self.lost_timeout_s))
        try:
            radii = [float(max(1.0, r)) for r in (self.reacq_radii_px or [50.0])]
        except (TypeError, ValueError):
            radii = [50.0, 100.0, 200.0, 400.0, 800.0]
        self.reacq_radii_px = sorted(radii)
        self.reacq_full_scan_enabled = bool(self.reacq_full_scan_enabled)
        self.active_target_policy = str(self.active_target_policy or "priority").lower()
        if self.active_target_policy not in ("priority", "strongest_prx", "highest_snr"):
            self.active_target_policy = "priority"
        # mission priority list: strip empties, keep order, de-duplicate preserving order
        try:
            raw = [str(x).strip() for x in (self.mission_priority or []) if str(x).strip()]
            seen = set()
            uniq = []
            for tid in raw:
                if tid not in seen:
                    seen.add(tid)
                    uniq.append(tid)
            self.mission_priority = uniq
        except (TypeError, ValueError):
            self.mission_priority = []
        self.p_rx_threshold_w = float(max(0.0, self.p_rx_threshold_w))
        self.search_start_index = int(max(0, min(int(self.search_start_index), 19)))
        self.ai_enabled = bool(getattr(self, "ai_enabled", False))
        self.ai_verifier_threshold = float(max(0.0, min(float(getattr(self, "ai_verifier_threshold", 0.6)), 1.0)))
        self.ai_simple_mode = bool(getattr(self, "ai_simple_mode", False))
        # confidence weights: normalize if sum deviates
        try:
            w = getattr(self, "ai_confidence_weights", None) or {"ai": 0.35, "shape": 0.10, "brightness": 0.15, "motion": 0.20, "prediction": 0.20}
            w = {str(k): float(v) for k, v in dict(w).items()}
            for req in ("ai", "shape", "brightness", "motion", "prediction"):
                if req not in w:
                    w[req] = {"ai": 0.35, "shape": 0.10, "brightness": 0.15, "motion": 0.20, "prediction": 0.20}[req]
            s = sum(w.values())
            if s > 1e-9 and abs(s - 1.0) > 1e-6:
                w = {k: v / s for k, v in w.items()}
            self.ai_confidence_weights = w
        except Exception:
            self.ai_confidence_weights = {"ai": 0.35, "shape": 0.10, "brightness": 0.15, "motion": 0.20, "prediction": 0.20}
        self.c_detect = float(max(0.0, min(float(getattr(self, "c_detect", 0.55)), 1.0)))
        self.c_identify = float(max(0.0, min(float(getattr(self, "c_identify", 0.75)), 1.0)))
        self.c_track = float(max(0.0, min(float(getattr(self, "c_track", 0.60)), 1.0)))
        self.c_lost = float(max(0.0, min(float(getattr(self, "c_lost", 0.40)), 1.0)))
        return self

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "AutonomyConfig":
        data = dict(data or {})
        obj = cls()
        for key, value in data.items():
            if hasattr(obj, key):
                setattr(obj, key, value)
        return obj.validate()


__all__ = [
    "SpotCandidate",
    "BeaconObservation",
    "TargetObservation",
    "TargetTrack",
    "AutonomyConfig",
]

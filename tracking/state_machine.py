# tracking/state_machine — acquisition / tracking / loss supervision
#
# States: SEARCHING -> DETECTED (acquiring) -> TRACKING -> LOST -> REACQUIRING -> TRACKING
# Spec mapping (§32 + §24):
#   spec SEARCH         -> SEARCHING (systematic scan, target unknown)
#   spec ACQUISITION    -> DETECTED  (valid detection seen, track confirming
#                          over N frames; single hit is NOT enough, §25)
#   spec TRACK / LOCK   -> TRACKING  (confirmed lock; PID authorised ONLY here)
#   spec RE-ACQUISITION -> LOST + REACQUIRING (prediction-guided local search
#                          first, global SEARCH fallback after max_lost_time)
# - PID is authorised ONLY in TRACKING (control gating principle)
# - Short dropouts are bridged by tracker, not immediate LOST
# - N-consecutive gate converts single-frame hits (reflections) into confirmed lock
# - Timing: acquisition <= 2s, reacquisition measured from state timestamps
#   (acquisition_time, reacquisition_time; see MetricsLogger)

from __future__ import annotations

from dataclasses import dataclass, field

from common.config_base import BaseValidatedConfig, clip_field

SEARCHING = "searching"
DETECTED = "detected"  # acquiring, not yet stable
TRACKING = "tracking"
LOST = "lost"
REACQUIRING = "reacquiring"

VALID_STATES = (SEARCHING, DETECTED, TRACKING, LOST, REACQUIRING)

# Spec §32 aliases (read-only convenience; canonical values stay lowercase).
SEARCH = SEARCHING
ACQUISITION = DETECTED
TRACK = TRACKING
LOCK = TRACKING
RE_ACQUISITION = REACQUIRING
REACQUISITION = REACQUIRING

# Spec (§32) -> code mapping for docs / logs.
SPEC_TO_CODE = {
    "SEARCH": SEARCHING,
    "ACQUISITION": DETECTED,
    "TRACK": TRACKING,
    "LOCK": TRACKING,
    "TRACK / LOCK": TRACKING,
    "RE-ACQUISITION": REACQUIRING,
    "REACQUISITION": REACQUIRING,
}

STATE_LIMITS = {
    "n_confirm": (2, 10),
    "n_reconfirm": (1, 10),
    "dropout_max": (3, 60),
    "dt_nominal": (0.005, 0.2),
    "miss_tolerance": (0, 5),
    "max_search_time": (1.0, 120.0),
    "max_lost_time": (0.5, 60.0),
}

STATE_DEFAULTS = {
    "n_confirm": 4,
    "n_reconfirm": 3,
    "dropout_max": 10,
    "dt_nominal": 1 / 30,
    "miss_tolerance": 1,  # M/N hysteresis: tolerate 1 miss during confirm
    "max_search_time": 30.0,  # give up raster sweep guard (caller may reset)
    "max_lost_time": 5.0,  # LOST -> SEARCHING full re-acquire after this
}


@dataclass
class StateMachineConfig(BaseValidatedConfig):
    LIMITS = STATE_LIMITS
    DEFAULTS = STATE_DEFAULTS

    n_confirm: int = STATE_DEFAULTS["n_confirm"]
    n_reconfirm: int = STATE_DEFAULTS["n_reconfirm"]
    dropout_max: int = STATE_DEFAULTS["dropout_max"]
    dt_nominal: float = STATE_DEFAULTS["dt_nominal"]
    miss_tolerance: int = STATE_DEFAULTS["miss_tolerance"]
    max_search_time: float = STATE_DEFAULTS["max_search_time"]
    max_lost_time: float = STATE_DEFAULTS["max_lost_time"]

    def validate(self) -> "StateMachineConfig":
        self.n_confirm = int(clip_field(int(self.n_confirm), *self.LIMITS["n_confirm"]))
        self.n_reconfirm = int(clip_field(int(self.n_reconfirm), *self.LIMITS["n_reconfirm"]))
        self.dropout_max = int(clip_field(int(self.dropout_max), *self.LIMITS["dropout_max"]))
        self.dt_nominal = float(clip_field(float(self.dt_nominal), *self.LIMITS["dt_nominal"]))
        self.miss_tolerance = int(clip_field(int(self.miss_tolerance), *self.LIMITS["miss_tolerance"]))
        self.max_search_time = float(clip_field(float(self.max_search_time), *self.LIMITS["max_search_time"]))
        self.max_lost_time = float(clip_field(float(self.max_lost_time), *self.LIMITS["max_lost_time"]))
        return self


class AcquisitionStateMachine:
    """Gates when full tracking control is allowed and manages loss."""

    def __init__(self, config: StateMachineConfig | None = None):
        self.config = (config or StateMachineConfig()).validate()
        self.state: str = SEARCHING
        self.confirm_count = 0
        self.miss_count = 0
        self.reconfirm_count = 0
        self.consec_miss = 0
        self.elapsed = 0.0
        self.searching_entry_t = 0.0
        self.state_entry_t = 0.0
        self.lost_entry_t: float | None = None
        self.acquisition_time: float | None = None
        self.reacquisition_time: float | None = None
        self.acquisitions = 0
        self.losses = 0
        self.reacq_attempts = 0
        self.reacq_successes = 0
        self.history: list[tuple[float, str]] = [(0.0, SEARCHING)]

    def reset(self) -> None:
        cfg = self.config
        self.state = SEARCHING
        self.confirm_count = 0
        self.miss_count = 0
        self.reconfirm_count = 0
        self.consec_miss = 0  # hysteresis counter for DETECTED/REACQUIRING
        self.elapsed = 0.0
        self.searching_entry_t = 0.0
        self.state_entry_t = 0.0
        self.lost_entry_t: float | None = None
        self.acquisition_time: float | None = None
        self.reacquisition_time: float | None = None
        self.acquisitions = 0
        self.losses = 0
        self.reacq_attempts = 0
        self.reacq_successes = 0
        self.history = [(0.0, SEARCHING)]

    def _enter(self, nxt: str) -> None:
        if nxt == self.state:
            return
        prev = self.state
        self.state = nxt
        self.state_entry_t = self.elapsed
        self.history.append((self.elapsed, nxt))
        if nxt == SEARCHING:
            self.searching_entry_t = self.elapsed
            self.confirm_count = 0
            self.miss_count = 0
            self.reconfirm_count = 0
            self.consec_miss = 0
        elif nxt == DETECTED:
            self.confirm_count = 1 if prev == SEARCHING else self.confirm_count
            self.miss_count = 0
            self.consec_miss = 0
        elif nxt == TRACKING:
            if prev in (DETECTED, REACQUIRING, SEARCHING):
                if self.acquisition_time is None:
                    self.acquisition_time = self.elapsed - self.searching_entry_t
                if prev == REACQUIRING and self.lost_entry_t is not None:
                    self.reacquisition_time = self.elapsed - self.lost_entry_t
                    self.reacq_successes += 1
                self.acquisitions += 1
            self.confirm_count = 0
            self.miss_count = 0
            self.reconfirm_count = 0
            self.consec_miss = 0
        elif nxt == LOST:
            self.lost_entry_t = self.elapsed
            self.losses += 1
            self.miss_count = 0
            self.reconfirm_count = 0
            self.consec_miss = 0
        elif nxt == REACQUIRING:
            self.reconfirm_count = 1
            self.consec_miss = 0
            if prev == LOST:
                self.reacq_attempts += 1

    @property
    def allow_control(self) -> bool:
        """PID authorised only after lock."""
        return self.state == TRACKING

    def step(self, detected: bool, tracker_stale: bool = False, dt: float | None = None,
             quality: float | None = None) -> str:
        """Advance one frame. detected = associated target present this frame.

        quality (optional, [0,1] lock quality): weak detections (quality<0.25)
        don't confirm acquisition — prevents reflection/false lock.
        """
        dt = float(dt if dt is not None else self.config.dt_nominal)
        dt = float(min(max(dt, 1e-4), 0.5))
        self.elapsed += dt
        det = bool(detected)
        stale = bool(tracker_stale)
        try:
            q = float(quality) if quality is not None else 1.0
        except Exception:
            q = 1.0
        # Weak detection counts as miss for confirmation purposes
        det_strong = bool(det and q >= 0.25)
        tol = int(self.config.miss_tolerance)

        if self.state == SEARCHING:
            if det_strong:
                self._enter(DETECTED)
            return self.state

        if self.state == DETECTED:
            if det_strong:
                self.confirm_count += 1
                self.consec_miss = 0
                if self.confirm_count >= int(self.config.n_confirm):
                    self._enter(TRACKING)
            else:
                # M/N hysteresis: tolerate `miss_tolerance` misses before abort
                self.consec_miss += 1
                if self.consec_miss > tol:
                    self._enter(SEARCHING)
            return self.state

        if self.state == TRACKING:
            if det and not stale:
                self.miss_count = 0
                return self.state
            self.miss_count += 1
            if self.miss_count > int(self.config.dropout_max) or stale:
                self._enter(LOST)
            return self.state

        if self.state == LOST:
            if det_strong:
                self._enter(REACQUIRING)
            elif (self.elapsed - self.state_entry_t) > float(self.config.max_lost_time):
                self._enter(SEARCHING)  # full re-acquire after timeout
            return self.state

        if self.state == REACQUIRING:
            if det_strong:
                self.reconfirm_count += 1
                self.consec_miss = 0
                if self.reconfirm_count >= int(self.config.n_reconfirm):
                    self._enter(TRACKING)
            else:
                self.consec_miss += 1
                if self.consec_miss > tol:
                    self._enter(LOST)
            return self.state

        self._enter(SEARCHING)
        return self.state

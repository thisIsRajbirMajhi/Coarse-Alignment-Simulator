# tracking/state_machine — acquisition / tracking / loss supervision
#
# States: SEARCHING -> DETECTED (acquiring) -> TRACKING -> LOST -> REACQUIRING -> TRACKING
# - PID is authorised ONLY in TRACKING (control gating principle)
# - Short dropouts are bridged by tracker, not immediate LOST
# - N-consecutive gate converts single-frame hits (reflections) into confirmed lock
# - Timing: acquisition <= 2s, reacquisition <= 1s measured from state timestamps

from __future__ import annotations

from dataclasses import dataclass, field

from common.config_base import BaseValidatedConfig, clip_field

SEARCHING = "searching"
DETECTED = "detected"  # acquiring, not yet stable
TRACKING = "tracking"
LOST = "lost"
REACQUIRING = "reacquiring"

VALID_STATES = (SEARCHING, DETECTED, TRACKING, LOST, REACQUIRING)

STATE_LIMITS = {
    "n_confirm": (2, 10),
    "n_reconfirm": (1, 10),
    "dropout_max": (3, 60),
    "dt_nominal": (0.005, 0.2),
}

STATE_DEFAULTS = {
    "n_confirm": 4,
    "n_reconfirm": 3,
    "dropout_max": 10,
    "dt_nominal": 1 / 30,
}


@dataclass
class StateMachineConfig(BaseValidatedConfig):
    LIMITS = STATE_LIMITS
    DEFAULTS = STATE_DEFAULTS

    n_confirm: int = STATE_DEFAULTS["n_confirm"]
    n_reconfirm: int = STATE_DEFAULTS["n_reconfirm"]
    dropout_max: int = STATE_DEFAULTS["dropout_max"]
    dt_nominal: float = STATE_DEFAULTS["dt_nominal"]

    def validate(self) -> "StateMachineConfig":
        self.n_confirm = int(clip_field(int(self.n_confirm), *self.LIMITS["n_confirm"]))
        self.n_reconfirm = int(clip_field(int(self.n_reconfirm), *self.LIMITS["n_reconfirm"]))
        self.dropout_max = int(clip_field(int(self.dropout_max), *self.LIMITS["dropout_max"]))
        self.dt_nominal = float(clip_field(float(self.dt_nominal), *self.LIMITS["dt_nominal"]))
        return self


class AcquisitionStateMachine:
    """Gates when full tracking control is allowed and manages loss."""

    def __init__(self, config: StateMachineConfig | None = None):
        self.config = (config or StateMachineConfig()).validate()
        self.state: str = SEARCHING
        self.confirm_count = 0
        self.miss_count = 0
        self.reconfirm_count = 0
        self.elapsed = 0.0
        self.searching_entry_t = 0.0
        self.lost_entry_t: float | None = None
        self.acquisition_time: float | None = None
        self.reacquisition_time: float | None = None
        self.acquisitions = 0
        self.losses = 0
        self.history: list[tuple[float, str]] = [(0.0, SEARCHING)]

    def reset(self) -> None:
        cfg = self.config
        self.state = SEARCHING
        self.confirm_count = 0
        self.miss_count = 0
        self.reconfirm_count = 0
        self.elapsed = 0.0
        self.searching_entry_t = 0.0
        self.lost_entry_t = None
        self.acquisition_time = None
        self.reacquisition_time = None
        self.acquisitions = 0
        self.losses = 0
        self.history = [(0.0, SEARCHING)]

    def _enter(self, nxt: str) -> None:
        if nxt == self.state:
            return
        prev = self.state
        self.state = nxt
        self.history.append((self.elapsed, nxt))
        if nxt == SEARCHING:
            self.searching_entry_t = self.elapsed
            self.confirm_count = 0
            self.miss_count = 0
            self.reconfirm_count = 0
        elif nxt == DETECTED:
            self.confirm_count = 1 if prev == SEARCHING else self.confirm_count
            self.miss_count = 0
        elif nxt == TRACKING:
            if prev in (DETECTED, REACQUIRING, SEARCHING):
                if self.acquisition_time is None:
                    self.acquisition_time = self.elapsed - self.searching_entry_t
                if prev == REACQUIRING and self.lost_entry_t is not None:
                    self.reacquisition_time = self.elapsed - self.lost_entry_t
                self.acquisitions += 1
            self.confirm_count = 0
            self.miss_count = 0
            self.reconfirm_count = 0
        elif nxt == LOST:
            self.lost_entry_t = self.elapsed
            self.losses += 1
            self.miss_count = 0
            self.reconfirm_count = 0
        elif nxt == REACQUIRING:
            self.reconfirm_count = 1

    @property
    def allow_control(self) -> bool:
        """PID authorised only after lock."""
        return self.state == TRACKING

    def step(self, detected: bool, tracker_stale: bool = False, dt: float | None = None) -> str:
        """Advance one frame. detected = associated target present this frame."""
        dt = float(dt if dt is not None else self.config.dt_nominal)
        dt = float(min(max(dt, 1e-4), 0.5))
        self.elapsed += dt
        det = bool(detected)
        stale = bool(tracker_stale)

        if self.state == SEARCHING:
            if det:
                self._enter(DETECTED)
            return self.state

        if self.state == DETECTED:
            if det:
                self.confirm_count += 1
                if self.confirm_count >= int(self.config.n_confirm):
                    self._enter(TRACKING)
            else:
                # Single miss during acquiring -> back to searching (avoid false lock)
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
            if det:
                self._enter(REACQUIRING)
            return self.state

        if self.state == REACQUIRING:
            if det:
                self.reconfirm_count += 1
                if self.reconfirm_count >= int(self.config.n_reconfirm):
                    self._enter(TRACKING)
            else:
                self._enter(LOST)
            return self.state

        self._enter(SEARCHING)
        return self.state

# local_terminal/state_machine.py - Module 12: State Machine (§28).
from __future__ import annotations

from local_terminal.core.states import LocalTerminalState


class LocalStateMachine:
    """Global LocalTerminal state machine.

    IDLE->SEARCHING->DETECTING->VERIFYING->ACQUIRED->TRACKING->DEGRADED->
    REACQUIRING--success-->TRACKING, --timeout-->LOST->SEARCHING.
    Hysteresis via separate thresholds (config-driven by caller).
    """

    def __init__(self, initial: LocalTerminalState = LocalTerminalState.SEARCHING):
        self.state = initial
        self.centered_hold = 0.0  # hysteresis timer

    def reset(self, state: LocalTerminalState = LocalTerminalState.SEARCHING) -> None:
        self.state = state
        self.centered_hold = 0.0

    def step(self, *, has_candidates: bool, has_identified: bool,
             acquired: bool, tracking_ok: bool, degraded: bool,
             reacquiring: bool, reacq_timeout: bool,
             power_on: bool = True,
             sensor_fault: bool = False) -> LocalTerminalState:
        if not power_on:
            self.state = LocalTerminalState.IDLE
            return self.state
        # Sensor failure latches FAULT (§36); recovery returns to SEARCHING.
        if sensor_fault:
            self.state = LocalTerminalState.FAULT
            return self.state
        if self.state == LocalTerminalState.FAULT:
            self.state = LocalTerminalState.SEARCHING
            return self.state
        s = self.state
        if s == LocalTerminalState.IDLE:
            self.state = LocalTerminalState.SEARCHING
        elif s == LocalTerminalState.SEARCHING:
            if acquired and tracking_ok:
                self.state = LocalTerminalState.TRACKING
            elif acquired:
                self.state = LocalTerminalState.ACQUIRED
            elif has_identified:
                self.state = LocalTerminalState.VERIFYING
            elif has_candidates:
                self.state = LocalTerminalState.DETECTING
        elif s == LocalTerminalState.DETECTING:
            if acquired and tracking_ok:
                self.state = LocalTerminalState.TRACKING
            elif acquired:
                self.state = LocalTerminalState.ACQUIRED
            elif has_identified:
                self.state = LocalTerminalState.VERIFYING
            elif not has_candidates:
                self.state = LocalTerminalState.SEARCHING
        elif s == LocalTerminalState.VERIFYING:
            if acquired and tracking_ok:
                self.state = LocalTerminalState.TRACKING
            elif acquired:
                self.state = LocalTerminalState.ACQUIRED
            elif not has_identified and not has_candidates:
                self.state = LocalTerminalState.SEARCHING
            elif not has_identified:
                self.state = LocalTerminalState.DETECTING
        elif s == LocalTerminalState.ACQUIRED:
            if tracking_ok:
                self.state = LocalTerminalState.TRACKING
            elif degraded or reacquiring:
                self.state = LocalTerminalState.DEGRADED
            elif not acquired:
                self.state = LocalTerminalState.VERIFYING if has_identified else LocalTerminalState.SEARCHING
        elif s == LocalTerminalState.TRACKING:
            if reacquiring or degraded:
                self.state = LocalTerminalState.DEGRADED if not reacquiring else LocalTerminalState.REACQUIRING
            elif not tracking_ok:
                self.state = LocalTerminalState.DEGRADED
        elif s == LocalTerminalState.DEGRADED:
            if tracking_ok and acquired:
                self.state = LocalTerminalState.TRACKING
            elif reacquiring:
                self.state = LocalTerminalState.REACQUIRING
            elif not has_candidates and not acquired:
                self.state = LocalTerminalState.SEARCHING
        elif s == LocalTerminalState.REACQUIRING:
            if tracking_ok and acquired:
                self.state = LocalTerminalState.TRACKING
            elif reacq_timeout:
                self.state = LocalTerminalState.LOST
        elif s == LocalTerminalState.LOST:
            self.state = LocalTerminalState.SEARCHING
        elif s == LocalTerminalState.FAULT:
            pass
        return self.state

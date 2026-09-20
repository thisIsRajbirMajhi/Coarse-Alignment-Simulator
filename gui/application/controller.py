# gui/application/controller.py - ApplicationController: lifecycle + stepping + snapshots.
from __future__ import annotations

import logging
import time

from PyQt5.QtCore import QObject, pyqtSignal

from gui.application.commands import ApplyConfigCommand, PauseCommand, ResetCommand, ResumeCommand, StartCommand, StopCommand
from gui.application.session import FrameSnapshot, SimulationSession
from gui.application.state import LifecycleState

log = logging.getLogger(__name__)


class ApplicationController(QObject):
    stateChanged = pyqtSignal(str)  # LifecycleState value
    snapshotReady = pyqtSignal(object)  # FrameSnapshot
    errorRaised = pyqtSignal(str)

    def __init__(self, session: SimulationSession, parent=None):
        super().__init__(parent)
        self.session = session
        self.lifecycle: LifecycleState = LifecycleState.STOPPED
        self.last_error: str | None = None
        self._frames = 0
        self._sim_time = 0.0
        self._proc_ms: list[float] = []
        self._last_step_wall: float | None = None
        self._last_snapshot: FrameSnapshot | None = None

    # -- error / transition helpers ----------------------------------
    def _fail(self, message: str) -> None:
        """Enter ERROR: remember the message and notify (state + error)."""
        self.lifecycle = LifecycleState.ERROR
        self.last_error = message
        self.stateChanged.emit(self.lifecycle.value)
        self.errorRaised.emit(message)
        log.error("%s", message)

    def _warn(self, message: str) -> None:
        """Non-fatal problem: remember + notify, lifecycle unchanged."""
        self.last_error = message
        self.errorRaised.emit(message)
        log.warning("%s", message)

    def _enter(self, state: LifecycleState) -> None:
        self.lifecycle = state
        self.last_error = None
        self.stateChanged.emit(state.value)

    def _clear_counters(self) -> None:
        self._frames = 0
        self._sim_time = 0.0
        self._proc_ms = []
        self._last_snapshot = None
        self._last_step_wall = None

    # -- lifecycle ---------------------------------------------------
    def start(self) -> bool:
        """Enter RUNNING. Returns True if a transition happened.

        From ERROR a full rebuild is forced — the session may be flagged
        built yet broken, so ``ensure_built`` alone would not recover it.
        From PAUSED this resumes. Already RUNNING is a no-op (False).
        """
        if self.lifecycle == LifecycleState.RUNNING:
            return False
        if self.lifecycle == LifecycleState.PAUSED:
            return self.resume()
        try:
            if self.lifecycle == LifecycleState.ERROR:
                self.session.build()
            else:
                self.session.ensure_built()
        except Exception as e:
            self._fail(f"Simulation init failed ({type(e).__name__}): {e}")
            log.exception("start failed")
            return False
        self._clear_counters()
        self._enter(LifecycleState.RUNNING)
        return True

    def stop(self) -> bool:
        """Enter STOPPED and clear runtime stats. No-op (False) if already there."""
        if self.lifecycle == LifecycleState.STOPPED:
            return False
        self._clear_counters()
        self._enter(LifecycleState.STOPPED)
        return True

    def pause(self) -> bool:
        """Pause a running sim. Returns False unless RUNNING -> PAUSED."""
        if self.lifecycle != LifecycleState.RUNNING:
            log.debug("pause ignored in state %s", self.lifecycle)
            return False
        self._enter(LifecycleState.PAUSED)
        return True

    def resume(self) -> bool:
        """Resume a paused sim. Returns False unless PAUSED -> RUNNING."""
        if self.lifecycle != LifecycleState.PAUSED:
            log.debug("resume ignored in state %s", self.lifecycle)
            return False
        self._last_step_wall = None
        self._enter(LifecycleState.RUNNING)
        return True

    def toggle_pause(self) -> bool:
        """Pause <-> resume. Returns False in states where neither applies."""
        if self.lifecycle == LifecycleState.PAUSED:
            return self.resume()
        if self.lifecycle == LifecycleState.RUNNING:
            return self.pause()
        return False

    def reset(self, seed: int | None = None) -> bool:
        """Rebuild the session, keeping configs; zero counters.

        RUNNING stays RUNNING (restart in place); every other state lands
        on STOPPED (explicit Start required). Returns False on failure
        (controller is then in ERROR).
        """
        was_running = self.lifecycle == LifecycleState.RUNNING
        try:
            self.session.reset(seed=seed)
        except Exception as e:
            self._fail(f"Reset failed ({type(e).__name__}): {e}")
            log.exception("reset failed")
            return False
        self._clear_counters()
        # After reset return to STOPPED (explicit Start required) unless was running.
        self._enter(LifecycleState.RUNNING if was_running else LifecycleState.STOPPED)
        return True

    def full_reset(self) -> bool:
        """Drop the session for a fresh default one; always lands on STOPPED.

        Used by the Reset button ("reset EVERYTHING"). The old session is
        kept on build failure (controller goes to ERROR instead).
        """
        try:
            session = SimulationSession()
            session.ensure_built()
        except Exception as e:
            self._fail(f"Reset failed ({type(e).__name__}): {e}")
            log.exception("full reset failed")
            return False
        self.session = session
        self._clear_counters()
        self._enter(LifecycleState.STOPPED)
        return True

    # -- commands ----------------------------------------------------
    def dispatch(self, cmd) -> None:
        """Dispatch an intent command (single entry for all GUI intents)."""
        if isinstance(cmd, StartCommand):
            self.start()
        elif isinstance(cmd, StopCommand):
            self.stop()
        elif isinstance(cmd, PauseCommand):
            self.pause()
        elif isinstance(cmd, ResumeCommand):
            self.resume()
        elif isinstance(cmd, ResetCommand):
            self.reset(seed=cmd.seed)
        elif isinstance(cmd, ApplyConfigCommand):
            self.apply_config(cmd)
        else:
            raise ValueError(f"unknown command: {type(cmd).__name__}")

    def apply_config(self, cmd: ApplyConfigCommand) -> None:
        try:
            if cmd.section == "camera":
                self.session.apply_camera_config(cmd.config)
            elif cmd.section == "control":
                self.session.apply_controller_config(cmd.config)
            elif cmd.section == "environment":
                self.session.apply_environment_config(cmd.config)
            elif cmd.section == "disturbances":
                self.session.apply_disturbance_config(cmd.config)
            elif cmd.section == "remote_terminal":
                self.session.apply_remote_config(cmd.config)
            else:
                raise ValueError(f"unknown config section: {cmd.section}")
        except Exception as e:
            self._warn(f"Invalid {cmd.section} config ({type(e).__name__}): {e}")
            log.exception("apply_config failed")

    # -- stepping (called by thin QTimer) ----------------------------
    def step(self) -> FrameSnapshot | None:
        if self.lifecycle != LifecycleState.RUNNING:
            return self._last_snapshot
        import numpy as np
        now = time.time()
        dt = 1 / 30 if self._last_step_wall is None else float(np.clip(now - self._last_step_wall, 0.005, 0.1))
        self._last_step_wall = now
        try:
            snap = self.session.step(dt)
        except Exception as e:
            self._fail(f"Step failed ({type(e).__name__}): {e}")
            log.exception("step failed")
            return self._last_snapshot
        self._frames += 1
        self._sim_time += float(snap.dt)
        self._proc_ms.append((time.time() - now) * 1000.0)
        if len(self._proc_ms) > 200:
            self._proc_ms.pop(0)
        self._last_snapshot = snap
        self.snapshotReady.emit(snap)
        return snap

    # -- derived runtime (sim-time; independent of wall/GUI refresh) ----
    @property
    def duration_s(self) -> float:
        return float(getattr(self, "_sim_time", 0.0) or 0.0)

    @property
    def fps(self) -> float:
        d = self.duration_s
        return (self._frames / d) if d > 1e-6 else 0.0

    @property
    def jitter_ms(self) -> float | None:
        if len(self._proc_ms) < 2:
            return None
        import math
        m = sum(self._proc_ms) / len(self._proc_ms)
        return math.sqrt(sum((x - m) ** 2 for x in self._proc_ms) / len(self._proc_ms))

    def button_states(self) -> dict:
        """Single source for Start/Stop/Pause/Reset enabled flags."""
        if self.lifecycle == LifecycleState.RUNNING:
            return {"start": False, "stop": True, "pause": True, "reset": True, "pause_text": "Pause"}
        if self.lifecycle == LifecycleState.PAUSED:
            return {"start": False, "stop": True, "pause": True, "reset": True, "pause_text": "Resume"}
        if self.lifecycle == LifecycleState.ERROR:
            return {"start": True, "stop": False, "pause": False, "reset": True, "pause_text": "Pause"}
        return {"start": True, "stop": False, "pause": False, "reset": True, "pause_text": "Pause"}

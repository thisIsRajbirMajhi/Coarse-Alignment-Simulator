# gui/application/controller.py - ApplicationController: lifecycle + stepping + snapshots.
from __future__ import annotations

import logging
import time

from PyQt5.QtCore import QObject, pyqtSignal

from gui.application.commands import (
    ApplyConfigCommand, ResetCommand, SelectTargetCommand, SetDetectorThresholdCommand,
)
from gui.application.session import FrameSnapshot, SimulationSession
from gui.application.state import LifecycleState, UIState

log = logging.getLogger(__name__)


class ApplicationController(QObject):
    stateChanged = pyqtSignal(str)  # LifecycleState value
    snapshotReady = pyqtSignal(object)  # FrameSnapshot
    errorRaised = pyqtSignal(str)

    def __init__(self, session: SimulationSession, parent=None):
        super().__init__(parent)
        self.session = session
        self.lifecycle: LifecycleState = LifecycleState.STOPPED
        self.ui = UIState()
        self._frames = 0
        self._sim_time = 0.0
        self._proc_ms: list[float] = []
        self._last_step_wall: float | None = None
        self._last_snapshot: FrameSnapshot | None = None

    # -- lifecycle ---------------------------------------------------
    def start(self) -> None:
        try:
            self.session.ensure_built()
        except Exception as e:
            self.lifecycle = LifecycleState.ERROR
            self.stateChanged.emit(self.lifecycle.value)
            self.errorRaised.emit(f"Simulation init failed: {e}")
            log.exception("start failed")
            return
        if self.lifecycle == LifecycleState.RUNNING:
            return
        if self.lifecycle == LifecycleState.PAUSED:
            self.resume()
            return
        if self.lifecycle == LifecycleState.STOPPED:
            self._frames = 0
            self._sim_time = 0.0
            self._proc_ms = []
        self.lifecycle = LifecycleState.RUNNING
        self._last_step_wall = None
        self.stateChanged.emit(self.lifecycle.value)

    def stop(self) -> None:
        self.lifecycle = LifecycleState.STOPPED
        self._frames = 0
        self._sim_time = 0.0
        self._proc_ms = []
        self._last_snapshot = None
        self._last_step_wall = None
        self.stateChanged.emit(self.lifecycle.value)

    def pause(self) -> None:
        if self.lifecycle != LifecycleState.RUNNING:
            return
        self.lifecycle = LifecycleState.PAUSED
        self.stateChanged.emit(self.lifecycle.value)

    def resume(self) -> None:
        if self.lifecycle != LifecycleState.PAUSED:
            return
        self.lifecycle = LifecycleState.RUNNING
        self._last_step_wall = None
        self.stateChanged.emit(self.lifecycle.value)

    def reset(self, seed: int | None = None) -> None:
        was_running = self.lifecycle == LifecycleState.RUNNING
        try:
            self.session.reset(seed=seed)
        except Exception as e:
            self.lifecycle = LifecycleState.ERROR
            self.stateChanged.emit(self.lifecycle.value)
            self.errorRaised.emit(f"Reset failed: {e}")
            log.exception("reset failed")
            return
        self._frames = 0
        self._sim_time = 0.0
        self._proc_ms = []
        self._last_snapshot = None
        # After reset return to STOPPED (explicit Start required) unless was running.
        self.lifecycle = LifecycleState.RUNNING if was_running else LifecycleState.STOPPED
        self.stateChanged.emit(self.lifecycle.value)

    # -- commands ----------------------------------------------------
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
            elif cmd.section == "beacons":
                self.session.apply_beacon_config(cmd.config)
            else:
                raise ValueError(f"unknown config section: {cmd.section}")
        except Exception as e:
            self.errorRaised.emit(f"Invalid {cmd.section} config: {e}")
            log.exception("apply_config failed")

    def select_target(self, cmd: SelectTargetCommand) -> None:
        try:
            self.session.select_target(cmd.target_index)
            self.ui.selected_target = int(cmd.target_index)
        except Exception as e:
            self.errorRaised.emit(f"Target select failed: {e}")
            log.exception("select_target failed")

    def set_detector_threshold(self, cmd: SetDetectorThresholdCommand) -> None:
        try:
            self.session.set_detector_threshold(cmd.threshold)
        except Exception as e:
            self.errorRaised.emit(f"Threshold rejected: {e}")
            log.exception("set_detector_threshold failed")

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
            self.lifecycle = LifecycleState.ERROR
            self.stateChanged.emit(self.lifecycle.value)
            self.errorRaised.emit(f"Step failed: {e}")
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

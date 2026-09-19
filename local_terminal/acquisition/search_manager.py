# local_terminal/search_manager.py - Module 1: Search Manager (§5).
from __future__ import annotations

from typing import Any

from local_terminal.acquisition.acquisition import AcquisitionScanner
from local_terminal.core.models import SearchCommand
from local_terminal.core.states import LocalTerminalState


class SearchManager:
    """Generates scanning trajectory when no confirmed target.

    Never knows where the Remote Terminal is. Runs concurrently with
    image processing: move->capture->detect->evaluate->move... Suspends
    immediately when an acceptable candidate appears.
    """

    def __init__(self, acquisition_config: Any = None, rng: Any = None):
        self.scanner = AcquisitionScanner(acquisition_config, rng=rng)
        self.suspended = False

    @property
    def active(self) -> bool:
        return self.scanner.active and not self.suspended

    def start(self) -> None:
        self.suspended = False
        self.scanner.start()

    def start_at(self, pan_deg: float, tilt_deg: float) -> None:
        self.suspended = False
        self.scanner.start_at(pan_deg, tilt_deg)

    def stop(self) -> None:
        self.scanner.stop()

    def suspend(self) -> None:
        self.suspended = True

    def resume(self) -> None:
        self.suspended = False
        if not self.scanner.active:
            self.scanner.start()

    def step(self, dt: float) -> tuple[SearchCommand, bool]:
        if self.suspended or not self.scanner.active:
            return SearchCommand(), False
        pan_deg, tilt_deg, timed_out = self.scanner.update(float(dt))
        return SearchCommand(desired_pan=float(pan_deg), desired_tilt=float(tilt_deg)), bool(timed_out)

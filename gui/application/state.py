# gui/application/state.py - Explicit lifecycle + UI state (Qt-free).
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class LifecycleState(str, Enum):
    STOPPED = "STOPPED"
    RUNNING = "RUNNING"
    PAUSED = "PAUSED"
    ERROR = "ERROR"


@dataclass
class UIState:
    """UI-only state. Never simulation truth."""
    selected_target: int = 0
    show_settings: bool = False
    active_dashboard_section: str = "all"


@dataclass
class RuntimeStats:
    """Timing owned by controller/session, not widgets."""
    frames: int = 0
    start_time: float | None = None
    elapsed_s: float = 0.0
    fps: float = 0.0
    proc_times_ms: list = field(default_factory=list)

    @property
    def jitter_ms(self) -> float | None:
        if len(self.proc_times_ms) < 2:
            return None
        import math
        m = sum(self.proc_times_ms) / len(self.proc_times_ms)
        return math.sqrt(sum((x - m) ** 2 for x in self.proc_times_ms) / len(self.proc_times_ms))

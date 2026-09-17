# gui/application/commands.py - Intent objects GUI -> controller -> session (Qt-free).
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class StartCommand:
    pass


@dataclass(frozen=True)
class StopCommand:
    pass


@dataclass(frozen=True)
class PauseCommand:
    pass


@dataclass(frozen=True)
class ResumeCommand:
    pass


@dataclass(frozen=True)
class ResetCommand:
    pass


@dataclass(frozen=True)
class ApplyConfigCommand:
    section: str  # camera|control|environment|disturbances
    config: Any

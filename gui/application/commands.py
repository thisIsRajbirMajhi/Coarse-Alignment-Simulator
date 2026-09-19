# gui/application/commands.py - Intent objects GUI -> controller -> session (Qt-free).
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Union


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
    seed: int | None = None


@dataclass(frozen=True)
class ApplyConfigCommand:
    section: str  # camera|control|environment|disturbances
    config: Any


# Union of all dispatchable intents (see ApplicationController.dispatch).
Command = Union[StartCommand, StopCommand, PauseCommand, ResumeCommand, ResetCommand, ApplyConfigCommand]

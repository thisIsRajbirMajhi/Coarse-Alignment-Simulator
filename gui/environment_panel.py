# gui/environment_panel.py - Backwards-compat shim
# Canonical location is now gui/panels/environment_panel.py
# This shim re-exports EnvironmentPanel so `from gui.environment_panel import EnvironmentPanel` still works.

from gui.panels.environment_panel import EnvironmentPanel  # noqa: F401

__all__ = ["EnvironmentPanel"]

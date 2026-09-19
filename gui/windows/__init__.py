# gui/windows/__init__.py - Secondary top-level windows.
from __future__ import annotations


def __getattr__(name: str):
    if name == "DashboardWindow":
        from gui.windows.dashboard_window import DashboardWindow as _DW
        globals()[name] = _DW
        return _DW
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = ["DashboardWindow"]

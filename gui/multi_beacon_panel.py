# gui/multi_beacon_panel.py - Backwards-compat shim
# Canonical location is now gui/panels/multi_beacon_panel.py
# This shim re-exports MultiBeaconPanel so `from gui.multi_beacon_panel import MultiBeaconPanel` still works.

from gui.panels.multi_beacon_panel import MultiBeaconPanel  # noqa: F401

__all__ = ["MultiBeaconPanel"]

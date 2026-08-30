"""
Package: presets
Purpose: Preconfigured test presets — one-click configure entire simulator + auto-run.
Public API: Preset, PRESETS, get_preset, apply_preset
Notes: Each preset defines end goal and full config (environment, camera, beacons, disturbances, controller, overlay, detection).
"""

from presets.preset import Preset
from presets.library import PRESETS, get_preset

__all__ = ["Preset", "PRESETS", "get_preset"]

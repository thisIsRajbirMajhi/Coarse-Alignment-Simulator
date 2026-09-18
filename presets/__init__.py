# presets/__init__.py - One-click testing presets (Qt-free).
#
# Each preset auto-configures ALL modules (environment, local terminal,
# remote scenario, disturbances) and can auto-start the simulation.
# GUI: ControlView combo + "Load & Start" (see MainWindow._on_preset_run).
# Headless: presets.runner.run_headless(preset_id) / python -m presets.runner.

from presets.presets import (
    PRESETS,
    PRESET_IDS,
    TestPreset,
    build_configs,
    get_preset,
    list_presets,
)
from presets.runner import (
    apply_to_session,
    evaluate_telemetry,
    run_headless,
)

__all__ = [
    "PRESETS",
    "PRESET_IDS",
    "TestPreset",
    "build_configs",
    "get_preset",
    "list_presets",
    "apply_to_session",
    "evaluate_telemetry",
    "run_headless",
]

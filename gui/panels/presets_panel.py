# gui/panels/presets_panel.py - Scenario presets for control deck
# Provides one-click full-system configurations (Nominal / Stress / High-Speed / Low-Light)
# Previously no presets existed; users had to tweak each tab manually.
# Now single signal drives Environment+Camera+Control+Disturbance+Beacon configs together.

from PyQt5.QtCore import pyqtSignal
from PyQt5.QtWidgets import (
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
)

from gui.panels.base import BaseConfigPanel


PRESETS = {
    "Nominal": {
        "desc": "Clear 2000, P 0.32, 1 beacon 60 px/s, no disturbances — baseline for Sr.16-20",
        "env": {"world_width": 2000, "world_height": 2000, "haze_pct": 10, "star_count": 40, "vignetting_pct": 0},
        "camera": {"fov_width": 640, "fov_height": 480, "max_pan_speed_deg": 8, "latency_ms": 12},
        "control": {"controller_type": "P", "kp": 0.32},
        "disturb": {"atmospheric_preset": "Clear", "camera_jitter": 0, "platform_speed": 0},
        "beacon": {"beacon_count": 1, "speed": 60, "profile": "curved"},
    },
    "Urban Clutter": {
        "desc": "Haze, 300 stars, 3000 world, moderate jitter — tests detection vs clutter",
        "env": {"world_width": 3000, "world_height": 3000, "haze_pct": 35, "star_count": 320, "star_brightness": 1.1, "vignetting_pct": 12},
        "camera": {"fov_width": 640, "fov_height": 480, "max_pan_speed_deg": 8, "latency_ms": 12},
        "control": {"controller_type": "PI", "kp": 0.28, "ki": 0.02},
        "disturb": {"atmospheric_preset": "Haze", "camera_jitter": 2.5, "enable_gaussian": True, "gaussian_sigma": 6},
        "beacon": {"beacon_count": 2, "speed": 70, "profile": "sinusoidal"},
    },
    "Stress Test": {
        "desc": "Fog + S&P 10% + Gaussian 12 + Jitter 8 + Platform 12 — worst-case tracking",
        "env": {"world_width": 2000, "world_height": 2000, "haze_pct": 55, "star_count": 800, "vignetting_pct": 25},
        "camera": {"fov_width": 640, "fov_height": 480, "max_pan_speed_deg": 8, "latency_ms": 18, "backlash_px": 0.5, "encoder_sigma_px": 0.08},
        "control": {"controller_type": "PID", "kp": 0.35, "kd": 0.04, "dead_zone": 1.2},
        "disturb": {"atmospheric_preset": "Fog", "camera_jitter": 8, "enable_salt_pepper": True, "enable_gaussian": True, "gaussian_sigma": 12, "platform_speed": 12, "platform_profile": "Random"},
        "beacon": {"beacon_count": 3, "speed": 90, "profile": "random"},
    },
    "High Speed": {
        "desc": "Fast beacon 120 px/s, 5000 world, needs feedforward 0.45 + Smith 12 ms",
        "env": {"world_width": 5000, "world_height": 5000, "haze_pct": 20, "star_count": 120},
        "camera": {"fov_width": 640, "fov_height": 480, "max_pan_speed_deg": 10, "latency_ms": 12},
        "control": {"controller_type": "PID", "kp": 0.40, "kd": 0.05, "feedforward_gain": 0.45, "smith_latency_ms": 12},
        "disturb": {"atmospheric_preset": "Clear", "camera_jitter": 1.0},
        "beacon": {"beacon_count": 1, "speed": 120, "profile": "linear"},
    },
    "Low Light": {
        "desc": "Dim background, low contrast, high detector threshold — tests sensitivity",
        "env": {"world_width": 2000, "world_height": 2000, "bg_top": 18, "bg_bottom": 28, "haze_pct": 15, "star_brightness": 0.7},
        "camera": {"fov_width": 640, "fov_height": 480},
        "control": {"controller_type": "P", "kp": 0.32},
        "disturb": {"atmospheric_preset": "Low Light"},
        "beacon": {"beacon_count": 1, "speed": 55, "profile": "curved"},
    },
}


class PresetsPanel(BaseConfigPanel):
    """Presets tab — one-click full-system scenario presets."""

    presetRequested = pyqtSignal(str)  # emits preset name
    randomizeRequested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(10)

        hdr = QLabel("Scenario Presets — one-click full-system setup")
        hdr.setStyleSheet("color:#111827; font-weight:700; font-size:11px; background:#f9fafb; border:1px solid #e5e7eb; border-radius:4px; padding:6px 8px;")
        hdr.setWordWrap(True)
        layout.addWidget(hdr)

        box = QGroupBox("Presets — Nominal → Stress → High Speed → Low Light")
        grid = QGridLayout(box)
        grid.setContentsMargins(12, 18, 12, 12)
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(8)
        grid.setColumnStretch(0, 1)

        row = 0
        self._buttons: dict[str, QPushButton] = {}
        for name, spec in PRESETS.items():
            btn = QPushButton(name)
            btn.setMinimumHeight(32)
            # Nominal = dark primary, others = light
            if name == "Nominal":
                btn.setStyleSheet("background:#111827; color:#ffffff; border:1px solid #111827; border-radius:4px; padding:6px 10px; font-weight:600;")
            else:
                btn.setStyleSheet("background:#ffffff; border:1px solid #d1d5db; border-radius:4px; padding:6px 10px; font-weight:500;")
            btn.setToolTip(spec["desc"])
            btn.clicked.connect(lambda _, n=name: self.presetRequested.emit(n))
            grid.addWidget(btn, row, 0)
            desc = QLabel(spec["desc"])
            desc.setWordWrap(True)
            desc.setStyleSheet("color:#6b7280; font-size:10px; font-style:italic;")
            grid.addWidget(desc, row, 1)
            self._buttons[name] = btn
            row += 1

        # Randomize all (domain randomization)
        rnd_btn = QPushButton("Randomize All (Domain Randomization)")
        rnd_btn.setMinimumHeight(32)
        rnd_btn.setStyleSheet("background:#fef3c7; border:1px solid #fcd34d; border-radius:4px; padding:6px 10px; font-weight:600; color:#92400e;")
        rnd_btn.setToolTip("Randomize Environment+Disturbance+Camera for AI training — mixed difficulty")
        rnd_btn.clicked.connect(self.randomizeRequested.emit)
        grid.addWidget(rnd_btn, row, 0, 1, 2)
        row += 1

        hint = QLabel("Presets set Environment+Camera+Control+Disturbance+Beacons together. They emit via MainWindow → all panels update; HUD shows confirmation. Use Randomize for training data.")
        hint.setWordWrap(True)
        hint.setStyleSheet("color:#64748b; font-size:10px; font-style:italic; background:#ffffff; border:1px solid #e5e7eb; border-radius:4px; padding:6px;")
        grid.addWidget(hint, row, 0, 1, 2)

        layout.addWidget(box)
        layout.addStretch()

    def get_preset(self, name: str) -> dict | None:
        return PRESETS.get(name)

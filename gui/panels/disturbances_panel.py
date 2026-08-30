"""
Module: gui.panels.disturbances_panel
Purpose: Disturbance intensity sliders (Turbulence, Vibration, Camera Motion, Noise).
Public API: DisturbancesPanel
Notes: Extracted from gui.app — modular, well-commented.
       Each slider 0..10 maps to physics models in disturbance.disturbances.
"""

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QGridLayout, QGroupBox, QLabel, QSlider, QVBoxLayout, QWidget

# ============================================================
# SECTION: DisturbancesPanel — Physics impairments
# ============================================================

class DisturbancesPanel(QWidget):
    """
    Disturbances tab — 4 sliders + numeric badges.

    Exposed:
      sliders: dict[str, QSlider]  — keys "Turbulence", "Vibration", "Camera Motion", "Noise"
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.sliders: dict[str, QSlider] = {}
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(10)

        box = QGroupBox("Disturbances  •  0–10  (Physics-based)")
        grid = QGridLayout(box)
        grid.setContentsMargins(12, 18, 12, 12)
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(8)
        grid.setColumnStretch(1, 1)

        for i, key in enumerate(["Turbulence", "Vibration", "Camera Motion", "Noise"]):
            lbl = QLabel(key)
            lbl.setStyleSheet("color:#334155;")
            lbl.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
            lbl.setMinimumWidth(98)
            grid.addWidget(lbl, i, 0)

            slider = QSlider(Qt.Horizontal)
            slider.setRange(0, 10)
            slider.setValue(0)
            slider.setTickPosition(QSlider.TicksBelow)
            slider.setTickInterval(1)
            slider.setMinimumHeight(18)
            grid.addWidget(slider, i, 1)

            v = QLabel("0")
            v.setFixedWidth(22)
            v.setAlignment(Qt.AlignCenter)
            v.setStyleSheet("color:#2563eb; font-weight:700; background:#eff6ff; border:1px solid #dbeafe; border-radius:6px; padding:2px;")
            grid.addWidget(v, i, 2)

            slider.valueChanged.connect(lambda val, l=v: l.setText(str(val)))
            self.sliders[key] = slider

        layout.addWidget(box)
        layout.addStretch()

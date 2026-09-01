"""
Module: gui.panels.disturbances_panel
Purpose: Disturbance intensity sliders (Turbulence, Vibration, Camera Motion, Noise).
Public API: DisturbancesPanel
Notes: Extracted from gui.app — modular, well-commented.
       Each slider 0..10 maps to physics models in disturbance.disturbances.
"""

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QFrame, QGridLayout, QGroupBox, QHBoxLayout, QLabel, QSlider, QVBoxLayout, QWidget

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
        layout.setSpacing(12)

        # Banner — atmospheric impairments
        banner = QFrame()
        banner.setStyleSheet("QFrame { background: qlineargradient(x1:0,y1:0,x2:1,y2:0, stop:0 #fff7ed, stop:1 #eff6ff); border:1px solid #fed7aa; border-radius:10px; }")
        bl = QVBoxLayout(banner)
        bl.setContentsMargins(12, 10, 12, 10)
        bl.setSpacing(3)
        bt = QLabel("⚡  DISTURBANCES  —  PHYSICS-BASED  IMPAIRMENTS")
        bt.setStyleSheet("color:#9a3412; font-weight:900; font-size:11px; letter-spacing:0.6px; background: transparent;")
        bt.setAlignment(Qt.AlignCenter)
        bl.addWidget(bt)
        bs = QLabel("0 = pristine  ·  10 = severe  •  Each slider drives a distinct model (turbulence blur, jitter, drift, noise)")
        bs.setStyleSheet("color:#475569; font-size:10px; background: transparent;")
        bs.setWordWrap(True)
        bs.setAlignment(Qt.AlignCenter)
        bl.addWidget(bs)
        layout.addWidget(banner)

        box = QGroupBox("Impairment Intensity  •  0–10")
        grid = QGridLayout(box)
        grid.setContentsMargins(12, 20, 12, 12)
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(10)
        grid.setColumnStretch(1, 1)

        meta = {
            "Turbulence": ("◈", "Atmospheric blur + warp + scintillation", "#2563eb"),
            "Vibration": ("◎", "High-freq platform shake (jitter)", "#7c3aed"),
            "Camera Motion": ("⬢", "Low-freq correlated drift (mount)", "#059669"),
            "Noise": ("▣", "Additive sensor Gaussian noise", "#64748b"),
        }

        for i, key in enumerate(["Turbulence", "Vibration", "Camera Motion", "Noise"]):
            icon, tip, accent = meta[key]
            row = QFrame()
            row.setStyleSheet(f"QFrame {{ background:#ffffff; border:1px solid #e2e8f0; border-radius:8px; }} QFrame:hover {{ border-color:{accent}; }}")
            # Use grid positions: icon+label on left, slider middle, value badge right
            # Icon
            icon_lbl = QLabel(icon)
            icon_lbl.setStyleSheet(f"background:{accent}15; color:{accent}; border:1px solid {accent}30; border-radius:5px; padding:2px 6px; font-weight:800; font-size:11px;")
            icon_lbl.setFixedSize(26, 22)
            icon_lbl.setAlignment(Qt.AlignCenter)
            icon_lbl.setToolTip(tip)
            grid.addWidget(icon_lbl, i, 0)

            lbl = QLabel(key)
            lbl.setStyleSheet("color:#0f172a; font-weight:700; font-size:11px;")
            lbl.setToolTip(tip)
            lbl.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
            lbl.setMinimumWidth(96)
            grid.addWidget(lbl, i, 1)

            slider = QSlider(Qt.Horizontal)
            slider.setRange(0, 10)
            slider.setValue(0)
            slider.setTickPosition(QSlider.TicksBelow)
            slider.setTickInterval(1)
            slider.setMinimumHeight(18)
            slider.setToolTip(tip)
            grid.addWidget(slider, i, 2)

            v = QLabel("0")
            v.setFixedWidth(34)
            v.setFixedHeight(24)
            v.setAlignment(Qt.AlignCenter)
            v.setStyleSheet(f"color:{accent}; font-weight:800; background:#f8fafc; border:1px solid #e2e8f0; border-radius:7px; padding:2px; font-family:'Consolas','Courier New',monospace; font-size:11px;")
            grid.addWidget(v, i, 3)

            def _on_val(val, lbl=v, accent_c=accent):
                lbl.setText(str(val))
                # color intensity by value
                if val == 0:
                    lbl.setStyleSheet(f"color:{accent_c}; font-weight:800; background:#f8fafc; border:1px solid #e2e8f0; border-radius:7px; padding:2px; font-family:'Consolas','Courier New',monospace; font-size:11px;")
                elif val <= 3:
                    lbl.setStyleSheet("color:#16a34a; font-weight:800; background:#f0fdf4; border:1px solid #bbf7d0; border-radius:7px; padding:2px; font-family:'Consolas','Courier New',monospace; font-size:11px;")
                elif val <= 7:
                    lbl.setStyleSheet("color:#d97706; font-weight:800; background:#fffbeb; border:1px solid #fde68a; border-radius:7px; padding:2px; font-family:'Consolas','Courier New',monospace; font-size:11px;")
                else:
                    lbl.setStyleSheet("color:#dc2626; font-weight:800; background:#fef2f2; border:1px solid #fecaca; border-radius:7px; padding:2px; font-family:'Consolas','Courier New',monospace; font-size:11px;")

            slider.valueChanged.connect(_on_val)
            self.sliders[key] = slider

        layout.addWidget(box)
        # Hint footer
        hint = QLabel("Tip: start at 0 for baseline, ramp to 6–8 to stress tracking. Disturbances evolve with sim-speed.")
        hint.setWordWrap(True)
        hint.setStyleSheet("color:#64748b; font-size:10px; font-style:italic; background:#f8fafc; border:1px solid #e2e8f0; border-radius:7px; padding:6px 8px;")
        layout.addWidget(hint)
        layout.addStretch()

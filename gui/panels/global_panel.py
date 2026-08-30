"""
Module: gui.panels.global_panel
Purpose: Global controls — motion profile, speed, detector threshold, Start/Pause/Reset/Export.
Public API: GlobalPanel
Notes: Extracted from gui.app — modular, well-commented.
       Exposes widgets as attributes for backward compat wiring in MainWindow,
       but also provides helper to build slider rows internally.
"""

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from target.motion import MotionProfile

# ============================================================
# SECTION: GlobalPanel — Target + System global controls
# ============================================================

class GlobalPanel(QWidget):
    """
    Global tab panel.

    Widgets exposed for MainWindow wiring (legacy attribute compatibility):
      motion_combo, speed_slider, thresh_slider, start_btn, pause_btn, reset_btn, export_btn
    Signals for cleaner connection (optional):
      motionChanged(str), startRequested, pauseRequested, resetRequested, exportRequested
    """

    motionChanged = pyqtSignal(str)
    startRequested = pyqtSignal()
    pauseRequested = pyqtSignal()
    resetRequested = pyqtSignal()
    exportRequested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._build_ui()

    # ========================================================
    # Build UI
    # ========================================================

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(10)

        # Target motion profile
        motion_hdr = QHBoxLayout()
        motion_hdr.setSpacing(8)
        motion_lbl = QLabel("Target motion profile")
        motion_lbl.setStyleSheet("font-weight:600; color:#0f172a;")
        motion_hdr.addWidget(motion_lbl)
        motion_hdr.addStretch()
        layout.addLayout(motion_hdr)

        self.motion_combo = QComboBox()
        self.motion_combo.addItems([p.value for p in MotionProfile])
        self.motion_combo.setCurrentText(MotionProfile.CURVED.value)
        self.motion_combo.setMinimumHeight(28)
        self.motion_combo.currentTextChanged.connect(self.motionChanged.emit)
        layout.addWidget(self.motion_combo)

        # Sliders — helper builds label + slider + value label
        self.speed_slider = self._add_slider_row(layout, "Target speed (px/s)", 10, 150, 60)
        self.thresh_slider = self._add_slider_row(layout, "Detector threshold", 100, 255, 200)

        # Global controls row — Start / Pause / Reset / Export
        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)
        self.start_btn = QPushButton("▶ Start")
        self.start_btn.setMinimumHeight(34)
        self.start_btn.setStyleSheet("background:#16a34a; color:white; font-weight:700; border:none; border-radius:8px;")
        self.pause_btn = QPushButton("⏸ Pause")
        self.pause_btn.setMinimumHeight(34)
        self.reset_btn = QPushButton("↺ Reset")
        self.reset_btn.setMinimumHeight(34)
        self.start_btn.clicked.connect(self.startRequested.emit)
        self.pause_btn.clicked.connect(self.pauseRequested.emit)
        self.reset_btn.clicked.connect(self.resetRequested.emit)
        for b in (self.start_btn, self.pause_btn, self.reset_btn):
            btn_row.addWidget(b, 1)
        layout.addLayout(btn_row)

        self.export_btn = QPushButton("⬇ Export performance log")
        self.export_btn.setMinimumHeight(32)
        self.export_btn.clicked.connect(self.exportRequested.emit)
        layout.addWidget(self.export_btn)

        layout.addStretch()

    # --------------------------------------------------------
    # Helper — slider row with value label
    # --------------------------------------------------------

    def _add_slider_row(self, layout: QVBoxLayout, label: str, vmin: int, vmax: int, vinit: int) -> QSlider:
        lab = QLabel(label)
        lab.setStyleSheet("color:#334155; font-weight:500;")
        layout.addWidget(lab)
        h = QHBoxLayout()
        h.setSpacing(8)
        slider = QSlider(Qt.Horizontal)
        slider.setRange(vmin, vmax)
        slider.setValue(vinit)
        slider.setTickPosition(QSlider.TicksBelow)
        slider.setTickInterval(max(1, (vmax - vmin) // 5))
        slider.setMinimumHeight(18)
        val = QLabel(str(vinit))
        val.setFixedWidth(36)
        val.setAlignment(Qt.AlignCenter)
        val.setStyleSheet("color:#2563eb; font-weight:700; background:#eff6ff; border:1px solid #dbeafe; border-radius:6px; padding:2px;")
        slider.valueChanged.connect(lambda v, l=val: l.setText(str(v)))
        h.addWidget(slider, 1)
        h.addWidget(val)
        layout.addLayout(h)
        # Keep reference to label for external wiring if needed
        slider._value_label = val  # type: ignore
        return slider

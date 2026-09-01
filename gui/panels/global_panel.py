# gui/panels/global_panel.py - Global controls — motion profile, speed, detector threshold, Start/Pause/Reset/E

from PyQt5.QtCore import Qt, pyqtSignal
from gui.panels.base import BaseConfigPanel
from PyQt5.QtWidgets import (
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from target.motion import MotionProfile

class GlobalPanel(BaseConfigPanel):
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
    dashboardRequested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._build_ui()

    # Build UI

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(12)

        # Motion and tuning moved to Beacons panel — keep hidden dummies for backward compat
        self.motion_combo = QComboBox()
        self.motion_combo.addItems([p.value for p in MotionProfile])
        self.motion_combo.setCurrentText(MotionProfile.CURVED.value)
        self.motion_combo.hide()
        self.motion_combo.currentTextChanged.connect(self.motionChanged.emit)
        self.speed_slider = self._add_slider_row(layout, "Target speed (px/s)", 10, 150, 60)
        self.speed_slider.hide()
        self.speed_slider._value_label.hide()  # type: ignore
        self.thresh_slider = self._add_slider_row(layout, "Detector threshold", 100, 255, 200)
        self.thresh_slider.hide()
        self.thresh_slider._value_label.hide()  # type: ignore
        # Hide the labels for those hidden sliders (they are the last two labels added)
        # Find and hide the labels
        for i in range(layout.count()):
            item = layout.itemAt(i)
            w = item.widget()
            if w and isinstance(w, QLabel) and w.text() in ("Target speed (px/s)", "Detector threshold"):
                w.hide()

        transport_card = QFrame()
        transport_card.setStyleSheet("QFrame { background:#ffffff; border:1px solid #e5e7eb; border-radius:8px; }")
        tl = QVBoxLayout(transport_card)
        tl.setContentsMargins(16, 16, 16, 16)
        tl.setSpacing(14)
        trans_title = QLabel("Transport")
        trans_title.setStyleSheet("color:#111827; font-weight:700; font-size:12px; background: transparent; letter-spacing: 0.3px;")
        trans_title.setAlignment(Qt.AlignCenter)
        tl.addWidget(trans_title)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(12)
        self.start_btn = QPushButton("Start")
        self.start_btn.setMinimumHeight(52)
        self.start_btn.setMinimumWidth(90)
        self.start_btn.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.start_btn.setStyleSheet("QPushButton { background: #111827; color:white; font-weight:700; border:1px solid #111827; border-radius:8px; font-size:13px; padding:10px 16px; } QPushButton:hover { background:#1f2937; } QPushButton:pressed { background:#000000; }")
        self.pause_btn = QPushButton("Pause")
        self.pause_btn.setMinimumHeight(52)
        self.pause_btn.setMinimumWidth(90)
        self.pause_btn.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.pause_btn.setStyleSheet("QPushButton { background:#ffffff; color:#374151; font-weight:600; border:1.5px solid #d1d5db; border-radius:8px; font-size:13px; padding:10px 16px; } QPushButton:hover { background:#f9fafb; border-color:#9ca3af; } QPushButton:pressed { background:#f3f4f6; }")
        self.reset_btn = QPushButton("Reset")
        self.reset_btn.setMinimumHeight(52)
        self.reset_btn.setMinimumWidth(90)
        self.reset_btn.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.reset_btn.setStyleSheet("QPushButton { background:#ffffff; color:#374151; font-weight:600; border:1.5px solid #d1d5db; border-radius:8px; font-size:13px; padding:10px 16px; } QPushButton:hover { background:#fef2f2; border-color:#fca5a5; color:#dc2626; } QPushButton:pressed { background:#fee2e2; }")
        self.start_btn.clicked.connect(self.startRequested.emit)
        self.pause_btn.clicked.connect(self.pauseRequested.emit)
        self.reset_btn.clicked.connect(self.resetRequested.emit)
        for b in (self.start_btn, self.pause_btn, self.reset_btn):
            btn_row.addWidget(b, 1)
        tl.addLayout(btn_row)
        # Hint for transport
        hint = QLabel("Use Start to run, Pause to hold, Reset to restore defaults")
        hint.setStyleSheet("color:#6b7280; font-size:10px; font-style:italic; background: transparent;")
        hint.setAlignment(Qt.AlignCenter)
        hint.setWordWrap(True)
        tl.addWidget(hint)

        # Export / Open Dashboard buttons removed entirely per user request (dashboard now in MainWindow, graph removed)
        # Kept as hidden dummies for backward compat so MainWindow wiring does not break
        self.export_btn = QPushButton()
        self.export_btn.hide()
        self.export_btn.clicked.connect(self.exportRequested.emit)
        self.dashboard_btn = QPushButton()
        self.dashboard_btn.hide()
        self.dashboard_btn.clicked.connect(self.dashboardRequested.emit)

        layout.addWidget(transport_card)

        layout.addStretch()

    # Helper — slider row with value label

    def _add_slider_row(self, layout: QVBoxLayout, label: str, vmin: int, vmax: int, vinit: int) -> QSlider:
        lab = QLabel(label)
        lab.setStyleSheet("color:#374151; font-weight:500; font-size:11px;")
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
        val.setFixedWidth(42)
        val.setMinimumHeight(24)
        val.setAlignment(Qt.AlignCenter)
        val.setStyleSheet("color:#111827; font-weight:600; background:#f9fafb; border:1px solid #e5e7eb; border-radius:4px; padding:2px 4px; font-family:'Consolas','Courier New',monospace; font-size:11px;")
        slider.valueChanged.connect(lambda v, l=val: l.setText(str(v)))
        h.addWidget(slider, 1)
        h.addWidget(val)
        layout.addLayout(h)
        slider._value_label = val  # type: ignore
        return slider
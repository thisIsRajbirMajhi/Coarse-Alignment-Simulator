# gui/panels/global_panel.py - Global controls — motion profile, speed, detector threshold, Start/Pause/Reset/E

from PyQt5.QtCore import Qt, pyqtSignal
from gui.panels.base import BaseConfigPanel
from PyQt5.QtWidgets import (
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
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

        # Header banner — mission controls
        banner = QFrame()
        banner.setStyleSheet("QFrame { background: qlineargradient(x1:0,y1:0,x2:1,y2:0, stop:0 #eff6ff, stop:1 #f0fdf4); border:1px solid #dbeafe; border-radius:10px; }")
        bl = QVBoxLayout(banner)
        bl.setContentsMargins(12, 10, 12, 10)
        bl.setSpacing(4)
        b_title = QLabel("◈  GLOBAL  MISSION  CONTROLS")
        b_title.setStyleSheet("color:#1e40af; font-weight:900; font-size:11px; letter-spacing:0.6px; background: transparent;")
        b_title.setAlignment(Qt.AlignCenter)
        bl.addWidget(b_title)
        b_sub = QLabel("Motion · Speed · Detection  •  Master transport for simulation")
        b_sub.setStyleSheet("color:#475569; font-size:10px; background: transparent;")
        b_sub.setAlignment(Qt.AlignCenter)
        bl.addWidget(b_sub)
        layout.addWidget(banner)

        # Target motion profile — card
        motion_card = QFrame()
        motion_card.setStyleSheet("QFrame { background:#ffffff; border:1px solid #e2e8f0; border-radius:10px; }")
        mc_lay = QVBoxLayout(motion_card)
        mc_lay.setContentsMargins(12, 12, 12, 12)
        mc_lay.setSpacing(8)
        motion_hdr = QHBoxLayout()
        motion_hdr.setSpacing(8)
        motion_icon = QLabel("⬢")
        motion_icon.setStyleSheet("background:#eff6ff; color:#2563eb; border:1px solid #dbeafe; border-radius:6px; padding:3px 7px; font-weight:800; font-size:11px;")
        motion_icon.setFixedSize(26, 22)
        motion_icon.setAlignment(Qt.AlignCenter)
        motion_hdr.addWidget(motion_icon)
        motion_lbl = QLabel("Target motion profile")
        motion_lbl.setStyleSheet("font-weight:800; color:#0f172a; font-size:11px;")
        motion_hdr.addWidget(motion_lbl)
        motion_hdr.addStretch()
        live_hint = QLabel("HOT")
        live_hint.setStyleSheet("background:#eff6ff; color:#2563eb; border:1px solid #dbeafe; border-radius:4px; padding:2px 6px; font-size:9px; font-weight:800; letter-spacing:0.5px;")
        motion_hdr.addWidget(live_hint)
        mc_lay.addLayout(motion_hdr)

        self.motion_combo = QComboBox()
        self.motion_combo.addItems([p.value for p in MotionProfile])
        self.motion_combo.setCurrentText(MotionProfile.CURVED.value)
        self.motion_combo.setMinimumHeight(30)
        self.motion_combo.currentTextChanged.connect(self.motionChanged.emit)
        mc_lay.addWidget(self.motion_combo)
        # Quick hint
        motion_hint = QLabel("Curved = orbit with drift · Random-walk = diffusion · Linear = constant heading")
        motion_hint.setStyleSheet("color:#64748b; font-size:10px; font-style:italic; background: transparent;")
        motion_hint.setWordWrap(True)
        mc_lay.addWidget(motion_hint)
        layout.addWidget(motion_card)

        # Sliders — card
        sliders_card = QFrame()
        sliders_card.setStyleSheet("QFrame { background:#ffffff; border:1px solid #e2e8f0; border-radius:10px; }")
        sl = QVBoxLayout(sliders_card)
        sl.setContentsMargins(12, 12, 12, 12)
        sl.setSpacing(10)
        sliders_title = QLabel("▣  TUNING")
        sliders_title.setStyleSheet("color:#1e40af; font-weight:800; font-size:10px; letter-spacing:0.5px; background: transparent;")
        sl.addWidget(sliders_title)
        self.speed_slider = self._add_slider_row(sl, "Target speed (px/s)", 10, 150, 60)
        self.thresh_slider = self._add_slider_row(sl, "Detector threshold", 100, 255, 200)
        layout.addWidget(sliders_card)

        # Transport controls — premium grouped
        transport_card = QFrame()
        transport_card.setStyleSheet("QFrame { background:#ffffff; border:1px solid #e2e8f0; border-radius:10px; }")
        tl = QVBoxLayout(transport_card)
        tl.setContentsMargins(12, 12, 12, 12)
        tl.setSpacing(10)
        trans_title = QLabel("▶  TRANSPORT")
        trans_title.setStyleSheet("color:#0f172a; font-weight:800; font-size:10px; letter-spacing:0.5px; background: transparent;")
        tl.addWidget(trans_title)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)
        self.start_btn = QPushButton("▶ Start")
        self.start_btn.setMinimumHeight(36)
        self.start_btn.setStyleSheet("QPushButton { background: qlineargradient(x1:0,y1:0,x2:1,y2:0, stop:0 #16a34a, stop:1 #15803d); color:white; font-weight:800; border:none; border-radius:8px; font-size:11px; letter-spacing:0.4px; } QPushButton:hover { background:#15803d; }")
        self.pause_btn = QPushButton("⏸ Pause")
        self.pause_btn.setMinimumHeight(36)
        self.pause_btn.setStyleSheet("QPushButton { background:#f8fafc; color:#334155; font-weight:700; border:1px solid #cbd5e1; border-radius:8px; } QPushButton:hover { background:#f1f5f9; border-color:#94a3b8; }")
        self.reset_btn = QPushButton("↺ Reset")
        self.reset_btn.setMinimumHeight(36)
        self.reset_btn.setStyleSheet("QPushButton { background:#ffffff; color:#475569; font-weight:700; border:1px solid #cbd5e1; border-radius:8px; } QPushButton:hover { background:#fef2f2; border-color:#fca5a5; color:#dc2626; }")
        self.start_btn.clicked.connect(self.startRequested.emit)
        self.pause_btn.clicked.connect(self.pauseRequested.emit)
        self.reset_btn.clicked.connect(self.resetRequested.emit)
        for b in (self.start_btn, self.pause_btn, self.reset_btn):
            btn_row.addWidget(b, 1)
        tl.addLayout(btn_row)

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
        lab.setStyleSheet("color:#0f172a; font-weight:700; font-size:11px; letter-spacing:0.2px;")
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
        val.setStyleSheet("color:#1e40af; font-weight:800; background:#eff6ff; border:1px solid #bfdbfe; border-radius:7px; padding:2px 4px; font-family:'Consolas','Courier New',monospace; font-size:11px;")
        slider.valueChanged.connect(lambda v, l=val: l.setText(str(v)))
        h.addWidget(slider, 1)
        h.addWidget(val)
        layout.addLayout(h)
        slider._value_label = val  # type: ignore
        return slider
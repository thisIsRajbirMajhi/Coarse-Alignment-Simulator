# gui/panels/presets_panel.py - One-click presets — configure entire software + auto-run, with goal description

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtWidgets import (
    QFrame,
    QGridLayout,
    QGroupBox,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from presets.library import PRESETS, PRESET_CATEGORIES
from presets.preset import Preset

class PresetsPanel(QWidget):
    """
    Presets tab — 9 spec-aligned presets per ISRO FSOC PS-4, one click configures entire simulator and runs.
    Covers: 2000×2000, 640×480 @4°×3° (0.109 mrad/px), 30Hz, centre, 10×10 beacon, linear/circular/fig8/random + spiral/sinusoidal,
            5-10°/s slew, disturbances (Noise S&P/Gauss/Poisson, ±20 jitter/platform, Haze/Fog/Low-light).

    Each preset card shows:
      [Button: "1 — Spec Baseline ..."]
      Description: what it configures (disturbances, beacons, speed, etc. + Sr. refs)
      Goal: brief end goal — what to observe / expected metric (Sr.16-20)

    Emits presetSelected(Preset) — MainWindow applies via presets.applier.apply_preset()
    """

    presetSelected = pyqtSignal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._build_ui()

    # Build UI — scrollable preset cards

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(10)

        # Premium header — command presets banner
        banner = QFrame()
        banner.setStyleSheet("QFrame { background: qlineargradient(x1:0,y1:0,x2:1,y2:0, stop:0 #0f172a, stop:1 #1e3a8a); border-radius: 10px; border: 1px solid #1e293b; }")
        bl = QVBoxLayout(banner)
        bl.setContentsMargins(12, 10, 12, 10)
        bl.setSpacing(4)
        title = QLabel("⬢  MISSION  PRESETS  —  ONE-CLICK  AUTO-RUN")
        title.setStyleSheet("color:#f8fafc; font-weight:900; font-size:11px; letter-spacing:0.8px; background: transparent; border: none;")
        title.setAlignment(Qt.AlignCenter)
        bl.addWidget(title)
        sub = QLabel("Configure entire stack + launch — environment · camera · beacons · disturbances · control · overlay")
        sub.setStyleSheet("color:#93c5fd; font-size:9px; font-weight:600; letter-spacing:0.3px; background: transparent;")
        sub.setAlignment(Qt.AlignCenter)
        sub.setWordWrap(True)
        bl.addWidget(sub)
        layout.addWidget(banner)

        hint = QLabel("▸ Click any preset to hot-configure the simulator and immediately run. Goal shows expected metric.")
        hint.setWordWrap(True)
        hint.setStyleSheet("color:#64748b; font-size:10px; font-style:italic; background:#f8fafc; border:1px solid #e2e8f0; border-radius:7px; padding:6px 8px;")
        layout.addWidget(hint)

        # Scroll area for preset cards — elevated deck
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setStyleSheet("QScrollArea { border: 1px solid #e2e8f0; border-radius: 10px; background: #ffffff; }")
        container = QWidget()
        container.setStyleSheet("background: transparent;")
        container_layout = QVBoxLayout(container)
        container_layout.setContentsMargins(6, 6, 6, 6)
        container_layout.setSpacing(8)
        container_layout.setAlignment(Qt.AlignTop)

        for preset in PRESETS:
            card = self._create_preset_card(preset)
            container_layout.addWidget(card)

        scroll.setWidget(container)
        layout.addWidget(scroll, 1)

        # Category legend — dynamic from actual presets (spec-aligned)
        cats = " · ".join(PRESET_CATEGORIES) if PRESET_CATEGORIES else "no presets"
        legend = QLabel(f"Categories: {cats}  —  9 spec presets (Sr.1-21) · ISRO PS-4")
        legend.setStyleSheet("color:#94a3b8; font-size:9px; font-style:italic;")
        legend.setWordWrap(True)
        layout.addWidget(legend)

    def _create_preset_card(self, preset: Preset) -> QGroupBox:
        box = QGroupBox()
        box.setStyleSheet("QGroupBox { background: #ffffff; border: 1px solid #e2e8f0; border-radius: 10px; margin-top: 8px; padding-top: 6px; } QGroupBox::title { background: transparent; border: none; }")
        v = QVBoxLayout(box)
        v.setContentsMargins(10, 10, 10, 10)
        v.setSpacing(7)

        # Button — name with category chip feel
        btn = QPushButton(f"  {preset.name}")
        btn.setMinimumHeight(32)
        # Color by category — spec palette (9 presets) + legacy fallback
        cat_colors = {
            "baseline": "#16a34a", "circular": "#2563eb", "figure8": "#7c3aed",
            "random": "#ea580c", "spiral": "#db2777", "noise": "#475569",
            "jitter": "#e11d48", "acquisition": "#0891b2", "stress": "#dc2626",
            # legacy aliases
            "turbulence": "#2563eb", "vibration": "#7c3aed", "distractors": "#ea580c",
            "dynamics": "#db2777", "snr": "#475569", "general": "#334155"
        }
        col = cat_colors.get(preset.category, "#2563eb")
        btn.setStyleSheet(f"QPushButton {{ background:{col}; color:white; font-weight:800; border:none; border-radius:7px; padding:7px 12px; text-align:left; font-size:11px; letter-spacing:0.2px; }} QPushButton:hover {{ background: #000000; }}")
        # hover override handled inline: darken via opacity? keep simple brighter on hover via stylesheet above overridden
        btn.setStyleSheet(f"background:{col}; color:white; font-weight:800; border:none; border-radius:7px; padding:7px 12px; text-align:left; font-size:11px;")
        btn.setToolTip(f"Apply preset: {preset.name}\n{preset.description}\nGoal: {preset.goal}")
        btn.clicked.connect(lambda _, p=preset: self.presetSelected.emit(p))
        v.addWidget(btn)

        # Description
        desc = QLabel(preset.description)
        desc.setWordWrap(True)
        desc.setStyleSheet("color:#334155; font-size:10px; background:#f8fafc; border:1px solid #e2e8f0; border-radius:4px; padding:4px;")
        v.addWidget(desc)

        # Goal — highlighted
        goal = QLabel(f"▶ Goal: {preset.goal}")
        goal.setWordWrap(True)
        goal.setStyleSheet("color:#0f172a; font-size:10px; font-weight:600; background:#eff6ff; border:1px solid #dbeafe; border-radius:4px; padding:4px;")
        v.addWidget(goal)

        return box
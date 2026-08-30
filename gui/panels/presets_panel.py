"""
Module: gui.panels.presets_panel
Purpose: One-click presets — configure entire software + auto-run, with goal description.
Public API: PresetsPanel
Notes: Modular, well-commented, intuitive. Each button shows name, description, and brief end goal.
       Emits presetSelected(Preset) when clicked — MainWindow then applies via presets.applier.
"""

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

from presets.library import PRESETS
from presets.preset import Preset

# ============================================================
# SECTION: PresetsPanel — curated test cases
# ============================================================

class PresetsPanel(QWidget):
    """
    Presets tab — 7 curated presets, one click configures entire simulator and runs.

    Each preset card shows:
      [Button: "1 — Ideal · Baseline"]
      Description: what it configures (disturbances, beacons, speed, etc.)
      Goal: brief end goal — what to observe / expected metric

    Emits presetSelected(Preset) — MainWindow applies via presets.applier.apply_preset()
    """

    presetSelected = pyqtSignal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._build_ui()

    # ========================================================
    # Build UI — scrollable preset cards
    # ========================================================

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(10)

        # Header
        title = QLabel("One-Click Presets — Configure Entire Software + Auto-Run")
        title.setStyleSheet("color:#0f172a; font-weight:800; font-size:12px; padding:6px; background:#eff6ff; border:1px solid #dbeafe; border-radius:8px;")
        title.setAlignment(Qt.AlignCenter)
        title.setWordWrap(True)
        layout.addWidget(title)

        hint = QLabel("Click any preset to configure environment, camera, beacons, disturbances, controller, overlay, detection and immediately run. Goal tells what to observe.")
        hint.setWordWrap(True)
        hint.setStyleSheet("color:#64748b; font-size:10px; font-style:italic; background:#f1f5f9; border:1px solid #e2e8f0; border-radius:6px; padding:4px;")
        layout.addWidget(hint)

        # Scroll area for preset cards
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setStyleSheet("QScrollArea { border: 1px solid #e2e8f0; border-radius: 8px; background: #f8fafc; }")
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

        # Category legend
        legend = QLabel("Categories: baseline · turbulence · vibration · distractors · dynamics · snr · acquisition · stress")
        legend.setStyleSheet("color:#94a3b8; font-size:9px; font-style:italic;")
        legend.setWordWrap(True)
        layout.addWidget(legend)

    def _create_preset_card(self, preset: Preset) -> QGroupBox:
        box = QGroupBox()
        box.setStyleSheet("QGroupBox { background: #ffffff; border: 1px solid #e2e8f0; border-radius: 8px; margin-top: 6px; padding-top: 6px; }")
        v = QVBoxLayout(box)
        v.setContentsMargins(8, 8, 8, 8)
        v.setSpacing(6)

        # Button — name
        btn = QPushButton(preset.name)
        btn.setMinimumHeight(30)
        # Color by category
        cat_colors = {
            "baseline": "#16a34a", "turbulence": "#2563eb", "vibration": "#7c3aed",
            "distractors": "#ea580c", "dynamics": "#db2777", "snr": "#64748b",
            "acquisition": "#0891b2", "stress": "#dc2626", "general": "#334155"
        }
        col = cat_colors.get(preset.category, "#2563eb")
        btn.setStyleSheet(f"background:{col}; color:white; font-weight:700; border:none; border-radius:6px; padding:6px 10px; text-align:left;")
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

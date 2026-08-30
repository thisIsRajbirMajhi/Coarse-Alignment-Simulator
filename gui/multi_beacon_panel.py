"""
Module: gui.multi_beacon_panel
Purpose: Multi-beacon manager — counts, target selection, and per-beacon collection.
Public API: MultiBeaconPanel
Params:
  1) Beacon Count  — 1..16 (GUI 1..12) total beacons
  2) Target Index  — 0..beacon_count-1 tracked beacon (others = distractors)
  3) Randomize All — reroll every per-beacon parameter at once
Also owns:
  - Scrollable list of BeaconPanel (one per beacon, 8 params each)
  - Per-beacon Random Position handling via seed + bounds
Notes: Emits multiConfigChanged(MultiBeaconConfig) HOT. Modular, grouped, well commented.
"""

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtWidgets import (
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSpinBox,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from gui.beacon_panel import BeaconPanel
from target.config import BeaconConfig, MultiBeaconConfig
from target.constants import MULTI_BEACON_LIMITS

# ============================================================
# SECTION: MultiBeaconPanel — Collection manager
# ============================================================

class MultiBeaconPanel(QWidget):
    """
    Manager for multi-beacon controls + per-beacon panels.

    Signals:
      multiConfigChanged(MultiBeaconConfig) — on any beacon or meta change (HOT)
      targetChanged(int)                    — when target index changes
      randomizeAllRequested()               — when Randomize All clicked
    """

    multiConfigChanged = pyqtSignal(object)
    targetChanged = pyqtSignal(int)
    randomizeAllRequested = pyqtSignal()
    randomizePositionRequested = pyqtSignal(int)

    def __init__(self, initial: MultiBeaconConfig | None = None, world_bounds: tuple[int, int] = (1000, 1000), parent=None):
        super().__init__(parent)
        self._world_bounds = world_bounds
        self._config = (initial or MultiBeaconConfig(beacon_count=1, target_index=0, beacons=[BeaconConfig(beacon_id=0)])).validate()
        self._beacon_panels: list[BeaconPanel] = []
        self._build_ui()
        self.set_config(self._config, emit=False)

    # ========================================================
    # SECTION: UI — Header + Scrollable per-beacon list
    # ========================================================

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(10)

        # ----------------------------------------------------
        # Header: Beacon Count + Target Index + Randomize All
        # ----------------------------------------------------
        # Multi-beacon controls — grouped in one QGroupBox for clear separation
        header_box = QGroupBox("Multi-Beacon — Count & Target")
        header_grid = QGridLayout(header_box)
        header_grid.setContentsMargins(12, 18, 12, 12)
        header_grid.setHorizontalSpacing(8)
        header_grid.setVerticalSpacing(8)
        header_grid.setColumnStretch(1, 1)
        header_grid.setColumnStretch(3, 1)

        # 1) Beacon Count — total beacons, drives factory + panel rebuild
        header_grid.addWidget(self._label("Beacons"), 0, 0)
        self.spin_beacon_count = QSpinBox()
        lo, hi = MULTI_BEACON_LIMITS["beacon_count"]
        # GUI caps at 12 for UI sanity (factory allows 16)
        self.spin_beacon_count.setRange(int(lo), 12)
        self.spin_beacon_count.setToolTip("Total beacons in scene (1..12) — first beacon uses primary profile, others random for realism.")
        self.spin_beacon_count.setMinimumHeight(26)
        header_grid.addWidget(self.spin_beacon_count, 0, 1)

        # Hitbox / Center quick header (global, live) — kept for convenience
        # 2) Target Index — which beacon is tracked
        header_grid.addWidget(self._label("Target"), 0, 2)
        self.spin_target_index = QSpinBox()
        self.spin_target_index.setRange(0, 11)
        self.spin_target_index.setToolTip("Which beacon is the real target being tracked — others act as distractors (hitbox-gated).")
        self.spin_target_index.setMinimumHeight(26)
        header_grid.addWidget(self.spin_target_index, 0, 3)

        # 3) Randomize All — reroll every per-beacon param at once
        self.btn_randomize_all = QPushButton("⟲ Randomize All Beacons")
        self.btn_randomize_all.setMinimumHeight(28)
        self.btn_randomize_all.setToolTip("Reroll every per-beacon parameter (profile, position seed, speed, brightness, radius, hitbox, center, heading) for all beacons — seeded, deterministic.")
        self.btn_randomize_all.setStyleSheet("background:#f1f5f9; border:1px solid #cbd5e1; border-radius:6px; padding:4px 10px; font-weight:600;")
        header_grid.addWidget(self.btn_randomize_all, 1, 0, 1, 4)

        # Status label — beacon count + target summary
        self.lbl_status = QLabel("1 beacon • Target #0")
        self.lbl_status.setStyleSheet("color:#64748b; font-size:10px;")
        header_grid.addWidget(self.lbl_status, 2, 0, 1, 4)

        # Quick hitbox summary hint
        self.lbl_hint = QLabel("Target-only: if target leaves FOV → SEARCHING — distractors ignored (hitbox-gated).")
        self.lbl_hint.setWordWrap(True)
        self.lbl_hint.setStyleSheet("color:#2563eb; font-size:10px; font-style:italic; background:#eff6ff; border:1px solid #dbeafe; border-radius:6px; padding:4px;")
        header_grid.addWidget(self.lbl_hint, 3, 0, 1, 4)

        root.addWidget(header_box)

        # ----------------------------------------------------
        # Per-Beacon scroll area — one BeaconPanel per beacon
        # ----------------------------------------------------
        # Each BeaconPanel exposes 8 per-beacon params (toggle, profile, seed, speed, brightness, radius, hitbox, center)
        self.per_beacon_box = QGroupBox("Per-Beacon — Every Parameter Dynamic (Live)")
        per_outer = QVBoxLayout(self.per_beacon_box)
        per_outer.setContentsMargins(8, 14, 8, 8)
        per_outer.setSpacing(6)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.NoFrame)
        self.scroll.setMinimumHeight(180)
        self.scroll.setMaximumHeight(420)
        self.scroll.setStyleSheet("QScrollArea { border: 1px solid #e2e8f0; border-radius: 8px; background: #f8fafc; }")

        self.container = QWidget()
        self.container.setStyleSheet("background: transparent;")
        self.container_layout = QVBoxLayout(self.container)
        self.container_layout.setContentsMargins(6, 6, 6, 6)
        self.container_layout.setSpacing(8)
        self.container_layout.setAlignment(Qt.AlignTop)
        self.scroll.setWidget(self.container)

        per_outer.addWidget(self.scroll)
        root.addWidget(self.per_beacon_box)
        root.addStretch()

        # Wiring — header emits
        self.spin_beacon_count.valueChanged.connect(self._on_beacon_count_changed)
        self.spin_target_index.valueChanged.connect(self._on_target_changed)
        self.btn_randomize_all.clicked.connect(self.randomizeAllRequested.emit)
        self.btn_randomize_all.clicked.connect(self._emit_multi_config)

    # ========================================================
    # SECTION: Helpers
    # ========================================================

    def _label(self, text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setStyleSheet("color:#334155; font-size:11px;")
        return lbl

    def _on_beacon_count_changed(self, v: int) -> None:
        # Clamp target index to new count
        self.spin_target_index.setMaximum(max(0, int(v) - 1))
        if self.spin_target_index.value() >= int(v):
            self.spin_target_index.setValue(int(v) - 1)
        self._update_status()
        # Rebuild panels to match count (creates default configs for new beacons)
        self._rebuild_panels()
        self._emit_multi_config()

    def _on_target_changed(self, idx: int) -> None:
        # Highlight target panel
        self._update_target_highlight()
        self._update_status()
        self.targetChanged.emit(int(idx))
        self._emit_multi_config()

    def _update_status(self) -> None:
        try:
            n = int(self.spin_beacon_count.value())
            tid = int(self.spin_target_index.value())
            # Summarize hitbox from first panel if available
            hb = self._beacon_panels[0].spin_hitbox.value() if self._beacon_panels else 14
            cr = self._beacon_panels[0].spin_center.value() if self._beacon_panels else 2
            self.lbl_status.setText(f"{n} beacon{'s' if n!=1 else ''} • Target #{tid} • hitbox {hb}px center {cr}px")
        except Exception:
            pass

    def _update_target_highlight(self) -> None:
        try:
            tid = int(self.spin_target_index.value())
            for i, panel in enumerate(self._beacon_panels):
                panel.set_target_highlight(i == tid)
                # Update title to include ★ TARGET
                cfg = panel.collect_config()
                suffix = " ★ TARGET" if i == tid else (" — OFF" if not cfg.enabled else " — ON")
                panel.setTitle(f"Beacon #{panel.beacon_id}{suffix}")
        except Exception:
            pass

    # ========================================================
    # SECTION: Per-Beacon Panel Management
    # ========================================================

    def _rebuild_panels(self, beacons: list[BeaconConfig] | None = None) -> None:
        """Rebuild BeaconPanel list to match beacon_count (preserves configs if given)."""
        # Clear old
        while self.container_layout.count():
            item = self.container_layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
        self._beacon_panels = []

        count = int(self.spin_beacon_count.value())
        # Source configs — either passed in or current panels' configs
        if beacons is None:
            # Generate defaults if no explicit list
            beacons = [BeaconConfig(beacon_id=i).validate() for i in range(count)]
        # Ensure length == count
        if len(beacons) < count:
            beacons = list(beacons) + [BeaconConfig(beacon_id=i).validate() for i in range(len(beacons), count)]
        else:
            beacons = beacons[:count]
            for i, b in enumerate(beacons):
                b.beacon_id = i

        for i, cfg in enumerate(beacons):
            panel = BeaconPanel(beacon_id=i, initial=cfg, world_bounds=self._world_bounds)
            panel.beaconConfigChanged.connect(self._emit_multi_config)
            panel.randomizePositionRequested.connect(self._forward_randomize_position)
            self.container_layout.addWidget(panel)
            self._beacon_panels.append(panel)

        # Adaptive scroll height
        n = len(self._beacon_panels)
        self.scroll.setMaximumHeight(min(420, 86 + n * 122))
        self.scroll.setMinimumHeight(min(220, 86 + n * 122))
        self._update_target_highlight()
        self._update_status()

    def _forward_randomize_position(self, beacon_id: int) -> None:
        """Bubble per-panel randomize up — emits dedicated signal for MainWindow to handle."""
        self.randomizePositionRequested.emit(int(beacon_id))
        # Also emit multi config for dirty tracking
        self._emit_multi_config()

    # ========================================================
    # SECTION: Config ↔ UI Sync
    # ========================================================

    def collect_multi_config(self) -> MultiBeaconConfig:
        """Read current UI (header + per-beacon) into validated MultiBeaconConfig."""
        beacons: list[BeaconConfig] = []
        for panel in self._beacon_panels:
            beacons.append(panel.collect_config())
        # If panels not yet built, fall back to stored _config beacons
        if not beacons and self._config.beacons:
            beacons = self._config.beacons
        return MultiBeaconConfig(
            beacon_count=int(self.spin_beacon_count.value()),
            target_index=int(self.spin_target_index.value()),
            beacons=beacons,
        ).validate()

    def set_config(self, cfg: MultiBeaconConfig, emit: bool = False) -> None:
        """Populate UI from a MultiBeaconConfig (blocks signals)."""
        cfg = cfg.validate()
        self._config = cfg
        self.spin_beacon_count.blockSignals(True)
        self.spin_target_index.blockSignals(True)
        try:
            self.spin_beacon_count.setValue(int(cfg.beacon_count))
            self.spin_target_index.setMaximum(max(0, int(cfg.beacon_count)-1))
            self.spin_target_index.setValue(int(cfg.target_index))
        finally:
            self.spin_beacon_count.blockSignals(False)
            self.spin_target_index.blockSignals(False)
        # Rebuild per-beacon panels from cfg.beacons
        self._rebuild_panels(beacons=cfg.beacons)
        self._update_target_highlight()
        if emit:
            self._emit_multi_config()

    def set_world_bounds(self, bounds: tuple[int, int]) -> None:
        """Update world bounds for all per-beacon X/Y ranges (HOT)."""
        self._world_bounds = bounds
        for panel in self._beacon_panels:
            panel.set_world_bounds(bounds)

    def get_per_beacon_panels(self) -> list[BeaconPanel]:
        return list(self._beacon_panels)

    def _emit_multi_config(self) -> None:
        try:
            cfg = self.collect_multi_config()
            self._config = cfg
            self._update_status()
            self.multiConfigChanged.emit(cfg)
        except Exception:
            pass

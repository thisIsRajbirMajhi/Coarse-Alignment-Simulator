# gui/beacon_panel.py - Per-beacon control panel — 8 parameters for one Target/Beacon

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtWidgets import (
    QCheckBox,
    QComboBox,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from target.config import BeaconConfig
from target.constants import BEACON_LIMITS
from target.motion import MotionProfile

class BeaconPanel(QGroupBox):
    """
    Per-beacon grouped controls.

    Emits:
      beaconConfigChanged(BeaconConfig) — on any of 8 params changed (HOT)
      randomizePositionRequested(int)   — beacon_id when position randomize clicked
    """

    beaconConfigChanged = pyqtSignal(object)
    randomizePositionRequested = pyqtSignal(int)

    def __init__(self, beacon_id: int, initial: BeaconConfig | None = None, world_bounds: tuple[int, int] = (1000, 1000), parent=None):
        title = f"Beacon #{beacon_id} — ON" if (initial.enabled if initial else True) else f"Beacon #{beacon_id} — OFF"
        super().__init__(title, parent)
        self.beacon_id = int(beacon_id)
        self._world_bounds = world_bounds
        self._initial = (initial or BeaconConfig(beacon_id=beacon_id)).validate()
        self._build_ui()
        self.set_config(self._initial, emit=False)
        self.setStyleSheet("QGroupBox { background: #ffffff; border: 1px solid #e2e8f0; border-radius: 10px; margin-top: 12px; padding-top: 10px; } QGroupBox::title { color: #1e40af; font-size:10px; font-weight:800; background:#eff6ff; border:1px solid #dbeafe; border-radius:6px; padding:2px 8px; }")

    def _build_ui(self) -> None:
        grid = QGridLayout(self)
        grid.setContentsMargins(8, 12, 8, 8)
        grid.setHorizontalSpacing(6)
        grid.setVerticalSpacing(6)
        grid.setColumnStretch(1, 1)
        grid.setColumnStretch(3, 1)

        # Row 0: Enabled toggle + Motion profile
        # 1) Toggle beacon on/off — disabled beacons are excluded from
        #    detection/tracking but retain state for re-enable.
        self.chk_enabled = QCheckBox("Enabled")
        self.chk_enabled.setChecked(True)
        self.chk_enabled.setToolTip("Toggle beacon on/off — OFF beacons are frozen and ignored by detector (distractors disabled).")
        self.chk_enabled.setStyleSheet("font-size:11px;")
        grid.addWidget(self.chk_enabled, 0, 0)

        # 2) Motion profile — enum-driven, back-compat aliases handled by MotionProfile._missing
        self.combo_profile = QComboBox()
        self.combo_profile.addItems([p.value for p in MotionProfile])
        self.combo_profile.setMinimumHeight(24)
        self.combo_profile.setToolTip("Motion profile — how the beacon moves (linear, curved, random_walk, etc.).")
        grid.addWidget(self._label("Profile"), 0, 1)
        grid.addWidget(self.combo_profile, 0, 2, 1, 2)

        # Row 1: Position Seed + Speed
        # 3) Starting Position Seed — drives deterministic placement via RNG(seed)
        #    Also stored as _seed on Target for round-trip. Reroll via Random button.
        grid.addWidget(self._label("Pos Seed"), 1, 0)
        self.spin_seed = QSpinBox()
        lo, hi = BEACON_LIMITS["position_seed"]
        self.spin_seed.setRange(int(lo), int(hi))
        self.spin_seed.setToolTip("Random seed for starting position (0..999999) — same seed → same initial (x,y). Use ↻ to reroll position.")
        self.spin_seed.setMinimumHeight(24)
        grid.addWidget(self.spin_seed, 1, 1)

        # 4) Speed — px/s with heading diffusion
        grid.addWidget(self._label("Speed"), 1, 2)
        self.spin_speed = QSpinBox()
        lo, hi = BEACON_LIMITS["speed"]
        self.spin_speed.setRange(int(lo), int(hi))
        self.spin_speed.setSuffix(" px/s")
        self.spin_speed.setToolTip("Motion speed (5..300 px/s) — scales dynamics per profile (e.g., orbit ω = speed/r).")
        self.spin_speed.setMinimumHeight(24)
        grid.addWidget(self.spin_speed, 1, 3)

        # Row 2: Brightness + Radius (photometric)
        # 5) Brightness — beacon intensity 0–255; scintillation modulates 180–255
        grid.addWidget(self._label("Bright"), 2, 0)
        self.spin_brightness = QSpinBox()
        lo, hi = BEACON_LIMITS["brightness"]
        self.spin_brightness.setRange(int(lo), int(hi))
        self.spin_brightness.setToolTip("Beacon intensity (0–255) — higher = easier detection, scintillation clips 180–255.")
        self.spin_brightness.setMinimumHeight(24)
        grid.addWidget(self.spin_brightness, 2, 1)

        # 6) Radius — visual size of beacon spot
        grid.addWidget(self._label("Radius"), 2, 2)
        self.spin_radius = QSpinBox()
        lo, hi = BEACON_LIMITS["radius"]
        self.spin_radius.setRange(int(lo), int(hi))
        self.spin_radius.setSuffix(" px")
        self.spin_radius.setToolTip("Visual size of the beacon (1..15 px) — drawn as solid circle + 1px hot center.")
        self.spin_radius.setMinimumHeight(24)
        grid.addWidget(self.spin_radius, 2, 3)

        # Row 3: Hit Box + Center Hit (detection geometry)
        # 7) Hit Box Radius — valid detection radius (≥ visual radius)
        grid.addWidget(self._label("Hitbox"), 3, 0)
        self.spin_hitbox = QSpinBox()
        lo, hi = BEACON_LIMITS["hitbox_radius"]
        self.spin_hitbox.setRange(int(lo), int(hi))
        self.spin_hitbox.setSuffix(" px")
        self.spin_hitbox.setToolTip("Hit Box Radius — counted as valid 'detected' hit (3..80 px). Typically ≥ visual radius. Used for coarse acquisition.")
        self.spin_hitbox.setMinimumHeight(24)
        grid.addWidget(self.spin_hitbox, 3, 1)

        # 8) Center Hit Radius — tighter precise hit (≤ hitbox)
        grid.addWidget(self._label("Center"), 3, 2)
        self.spin_center = QSpinBox()
        lo, hi = BEACON_LIMITS["center_radius"]
        self.spin_center.setRange(int(lo), int(hi))
        self.spin_center.setSuffix(" px")
        self.spin_center.setToolTip("Centre Hit Radius — tighter radius for precise/centered hit (1..10 px). Must be ≤ hitbox. Used for RMS/p95 accuracy.")
        self.spin_center.setMinimumHeight(24)
        grid.addWidget(self.spin_center, 3, 3)

        # Row 4: Heading + X/Y (position placement)
        grid.addWidget(self._label("Heading"), 4, 0)
        self.spin_heading = QSpinBox()
        lo, hi = BEACON_LIMITS["heading"]
        self.spin_heading.setRange(int(lo), int(hi))
        self.spin_heading.setSuffix("°")
        self.spin_heading.setToolTip("Initial heading (0..360°) — direction of motion for linear/zigzag/accelerating.")
        self.spin_heading.setMinimumHeight(24)
        grid.addWidget(self.spin_heading, 4, 1)

        grid.addWidget(self._label("X"), 4, 2)
        self.spin_x = QSpinBox()
        self.spin_x.setRange(0, self._world_bounds[0])
        self.spin_x.setToolTip("Starting X position (px) — clamped to world bounds 0..W. Seed-driven randomize available.")
        self.spin_x.setMinimumHeight(24)
        grid.addWidget(self.spin_x, 4, 3)

        grid.addWidget(self._label("Y"), 5, 0)
        self.spin_y = QSpinBox()
        self.spin_y.setRange(0, self._world_bounds[1])
        self.spin_y.setToolTip("Starting Y position (px) — clamped to world bounds 0..H.")
        self.spin_y.setMinimumHeight(24)
        grid.addWidget(self.spin_y, 5, 1)

        # Random Position button — uses seed to reroll (x,y) deterministically
        self.btn_rand_pos = QPushButton("↻ Random Position")
        self.btn_rand_pos.setMinimumHeight(24)
        self.btn_rand_pos.setToolTip("Reroll starting position via current seed + beacon_id offset — deterministic, non-overlapping.")
        self.btn_rand_pos.setStyleSheet("font-size:10px; padding:4px; background:#f1f5f9; border:1px solid #cbd5e1; border-radius:4px;")
        grid.addWidget(self.btn_rand_pos, 5, 2, 1, 2)

        # Wiring — each edit emits HOT config
        self.chk_enabled.toggled.connect(self._emit_config)
        self.combo_profile.currentTextChanged.connect(self._emit_config)
        self.spin_seed.valueChanged.connect(self._emit_config)
        self.spin_speed.valueChanged.connect(self._emit_config)
        self.spin_brightness.valueChanged.connect(self._emit_config)
        self.spin_radius.valueChanged.connect(self._emit_config)
        self.spin_hitbox.valueChanged.connect(self._on_hitbox_changed)
        self.spin_center.valueChanged.connect(self._on_center_changed)
        self.spin_heading.valueChanged.connect(self._emit_config)
        self.spin_x.valueChanged.connect(self._emit_config)
        self.spin_y.valueChanged.connect(self._emit_config)
        self.btn_rand_pos.clicked.connect(lambda: self.randomizePositionRequested.emit(self.beacon_id))

    def _on_hitbox_changed(self, val: int) -> None:
        """Ensure center ≤ hitbox when hitbox shrinks."""
        if self.spin_center.value() > int(val):
            self.spin_center.blockSignals(True)
            self.spin_center.setValue(int(val))
            self.spin_center.blockSignals(False)
        self._emit_config()

    def _on_center_changed(self, val: int) -> None:
        """Ensure hitbox ≥ center when center grows."""
        if int(val) > self.spin_hitbox.value():
            self.spin_hitbox.blockSignals(True)
            self.spin_hitbox.setValue(int(val))
            self.spin_hitbox.blockSignals(False)
        self._emit_config()

    def _label(self, text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setStyleSheet("color:#334155; font-size:11px;")
        return lbl

    def collect_config(self) -> BeaconConfig:
        """Read current UI into a validated BeaconConfig."""
        return BeaconConfig(
            enabled=bool(self.chk_enabled.isChecked()),
            beacon_id=int(self.beacon_id),
            profile=str(self.combo_profile.currentText()),
            position_seed=int(self.spin_seed.value()),
            x=float(self.spin_x.value()),
            y=float(self.spin_y.value()),
            heading=float(self.spin_heading.value()),
            speed=float(self.spin_speed.value()),
            brightness=int(self.spin_brightness.value()),
            radius=int(self.spin_radius.value()),
            hitbox_radius=int(self.spin_hitbox.value()),
            center_radius=int(self.spin_center.value()),
        ).validate()

    def set_config(self, cfg: BeaconConfig, emit: bool = False) -> None:
        """Populate UI from a BeaconConfig (blocks signals)."""
        cfg = cfg.validate()
        for w in [self.chk_enabled, self.combo_profile, self.spin_seed, self.spin_speed,
                  self.spin_brightness, self.spin_radius, self.spin_hitbox, self.spin_center,
                  self.spin_heading, self.spin_x, self.spin_y]:
            w.blockSignals(True)
        try:
            self.beacon_id = int(cfg.beacon_id)
            self.chk_enabled.setChecked(bool(cfg.enabled))
            # Update title to reflect enabled + target highlight (set externally)
            base_title = f"Beacon #{self.beacon_id} — {'ON' if cfg.enabled else 'OFF'}"
            self.setTitle(base_title)
            # Profile
            idx = self.combo_profile.findText(cfg.profile)
            if idx >= 0:
                self.combo_profile.setCurrentIndex(idx)
            else:
                self.combo_profile.setCurrentText(cfg.profile)
            self.spin_seed.setValue(int(cfg.position_seed))
            self.spin_speed.setValue(int(cfg.speed))
            self.spin_brightness.setValue(int(cfg.brightness))
            self.spin_radius.setValue(int(cfg.radius))
            self.spin_hitbox.setValue(int(cfg.hitbox_radius))
            self.spin_center.setValue(int(cfg.center_radius))
            self.spin_heading.setValue(int(float(cfg.heading) % 360) if cfg.heading is not None else 0)
            # World bounds may have changed — update X/Y ranges
            self.spin_x.setRange(0, self._world_bounds[0])
            self.spin_y.setRange(0, self._world_bounds[1])
            self.spin_x.setValue(int(float(cfg.x)))
            self.spin_y.setValue(int(float(cfg.y)))
        finally:
            for w in [self.chk_enabled, self.combo_profile, self.spin_seed, self.spin_speed,
                      self.spin_brightness, self.spin_radius, self.spin_hitbox, self.spin_center,
                      self.spin_heading, self.spin_x, self.spin_y]:
                w.blockSignals(False)
        if emit:
            self._emit_config()

    def set_world_bounds(self, bounds: tuple[int, int]) -> None:
        """Update X/Y spin ranges when world size changes (HOT)."""
        self._world_bounds = bounds
        self.spin_x.setRange(0, bounds[0])
        self.spin_y.setRange(0, bounds[1])

    def set_target_highlight(self, is_target: bool) -> None:
        """Highlight this panel if it's the tracked target (star)."""
        if is_target:
            self.setStyleSheet("QGroupBox { background: qlineargradient(x1:0,y1:0,x2:1,y2:0, stop:0 #eff6ff, stop:1 #dbeafe); border: 1.5px solid #2563eb; border-radius: 10px; margin-top: 12px; padding-top: 10px; } QGroupBox::title { color: #ffffff; font-size:10px; font-weight:800; background:#2563eb; border:none; border-radius:6px; padding:2px 8px; }")
        else:
            enabled = self.chk_enabled.isChecked()
            if not enabled:
                self.setStyleSheet("QGroupBox { background: #f8fafc; border: 1px dashed #94a3b8; border-radius: 10px; margin-top: 12px; padding-top: 10px; } QGroupBox::title { color: #64748b; font-size:10px; background:#f1f5f9; border:1px solid #e2e8f0; border-radius:6px; padding:2px 8px; }")
            else:
                self.setStyleSheet("QGroupBox { background: #ffffff; border: 1px solid #e2e8f0; border-radius: 10px; margin-top: 12px; padding-top: 10px; } QGroupBox::title { color: #1e40af; font-size:10px; font-weight:800; background:#eff6ff; border:1px solid #dbeafe; border-radius:6px; padding:2px 8px; }")

    def _emit_config(self) -> None:
        """Emit validated config for HOT apply."""
        try:
            cfg = self.collect_config()
            # Update title live
            self.setTitle(f"Beacon #{self.beacon_id} — {'ON' if cfg.enabled else 'OFF'}")
            self.beaconConfigChanged.emit(cfg)
        except Exception:
            pass
"""
Module: gui.environment_panel
Purpose: Grouped control panel for all 10 Environment parameters — immediate migration.
Public API: EnvironmentPanel
Sections (grouping chosen per user request):
  A) World        — World Width / Height
  B) Seed         — Seed + Randomize button
  C) Atmosphere   — BG Top / Bottom, Vignetting, Haze
  D) Starfield    — Star count, Star brightness
  E) Dynamics     — Dynamic toggle, Dynamic speed
Notes:
  - HOT-reloaded: every change emits configChanged(EnvironmentConfig) debounced
    by MainWindow (520ms / 380ms) — no restart.
  - Immediate migration: MainWindow stores self.env_config: EnvironmentConfig.
  - Structured comments per Section: sub-header + widget purpose.
"""

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtWidgets import (
    QCheckBox,
    QDoubleSpinBox,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from environment.config import EnvironmentConfig
from environment.constants import DEFAULTS, LIMITS, MAX_RES, MIN_RES

# ============================================================
# SECTION: EnvironmentPanel — Grouped Control Widget
# ============================================================

class EnvironmentPanel(QWidget):
    """
    Grouped Environment controls for the Environment tab.

    Emits:
      configChanged(EnvironmentConfig) — on any of the 10 params changed
      randomizeRequested()             — when Randomize clicked
    """

    # Emitted with a validated EnvironmentConfig snapshot
    configChanged = pyqtSignal(object)
    randomizeRequested = pyqtSignal()

    def __init__(self, parent=None, initial: EnvironmentConfig | None = None):
        super().__init__(parent)
        self._initial = (initial or EnvironmentConfig()).validate()
        self._build_ui()
        self.set_config(self._initial, emit=False)

    # ========================================================
    # SECTION: UI Construction — 5 Grouped Sections
    # ========================================================

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(10)

        # ----------------------------------------------------
        # Section A: World — Full 2D scene size
        # ----------------------------------------------------
        # World width/height drive Scene resolution; also clamp
        # FOV and beacon bounds. Step 50 for 5000-range usability.
        world_box = QGroupBox("Set World Size  (Full 2D Scene)")
        world_grid = QGridLayout(world_box)
        world_grid.setContentsMargins(12, 18, 12, 12)
        world_grid.setHorizontalSpacing(8)
        world_grid.setVerticalSpacing(8)
        world_grid.setColumnStretch(1, 1)
        world_grid.setColumnStretch(3, 1)

        world_grid.addWidget(self._label("World W"), 0, 0)
        self.scene_w_spin = QSpinBox()
        self.scene_w_spin.setRange(MIN_RES, MAX_RES)
        self.scene_w_spin.setSingleStep(50)
        self.scene_w_spin.setSuffix(" px")
        self.scene_w_spin.setToolTip("Full scene width (px) — 50..5000, validated & clamped. Affects world bounds and minimap scale.")
        self.scene_w_spin.setMinimumHeight(26)
        world_grid.addWidget(self.scene_w_spin, 0, 1)

        world_grid.addWidget(self._label("H"), 0, 2)
        self.scene_h_spin = QSpinBox()
        self.scene_h_spin.setRange(MIN_RES, MAX_RES)
        self.scene_h_spin.setSingleStep(50)
        self.scene_h_spin.setSuffix(" px")
        self.scene_h_spin.setToolTip("Full scene height (px) — 50..5000.")
        self.scene_h_spin.setMinimumHeight(26)
        world_grid.addWidget(self.scene_h_spin, 0, 3)

        world_hint = QLabel("Size of the full 2D scene — beacons and camera bounds adapt instantly (HOT).")
        world_hint.setWordWrap(True)
        world_hint.setStyleSheet("color:#64748b; font-size:10px; font-style:italic;")
        world_grid.addWidget(world_hint, 1, 0, 1, 4)

        root.addWidget(world_box)

        # ----------------------------------------------------
        # Section B: Seed — Reproducible generation
        # ----------------------------------------------------
        # Seed drives np.random.default_rng(seed) for gradient/haze/stars.
        # Same seed → identical background (reproducibility).
        seed_box = QGroupBox("Set Random Seed  (Reproducible Scenes)")
        seed_grid = QGridLayout(seed_box)
        seed_grid.setContentsMargins(12, 18, 12, 12)
        seed_grid.setHorizontalSpacing(8)
        seed_grid.setVerticalSpacing(8)
        seed_grid.setColumnStretch(1, 1)

        seed_grid.addWidget(self._label("Seed"), 0, 0)
        self.seed_spin = QSpinBox()
        self.seed_spin.setRange(*LIMITS["seed"])
        self.seed_spin.setToolTip("Random seed for reproducible scenes — 0..999999. Use Randomize to reroll.")
        self.seed_spin.setMinimumHeight(26)
        seed_grid.addWidget(self.seed_spin, 0, 1)

        self.random_seed_btn = QPushButton("Randomize")
        self.random_seed_btn.setMinimumHeight(26)
        self.random_seed_btn.setToolTip("Reroll seed to a random value (0..999999) and regenerate — HOT, next tick.")
        self.random_seed_btn.setStyleSheet("background:#f1f5f9; border:1px solid #cbd5e1; border-radius:6px; padding:4px 10px;")
        seed_grid.addWidget(self.random_seed_btn, 0, 2, 1, 2)

        seed_hint = QLabel("Deterministic: same seed → identical sky, haze, and stars.")
        seed_hint.setWordWrap(True)
        seed_hint.setStyleSheet("color:#64748b; font-size:10px; font-style:italic;")
        seed_grid.addWidget(seed_hint, 1, 0, 1, 4)

        root.addWidget(seed_box)

        # ----------------------------------------------------
        # Section C: Atmosphere — Gradient + fog + vignetting
        # ----------------------------------------------------
        atmo_box = QGroupBox("Set Atmosphere")
        atmo_grid = QGridLayout(atmo_box)
        atmo_grid.setContentsMargins(12, 18, 12, 12)
        atmo_grid.setHorizontalSpacing(8)
        atmo_grid.setVerticalSpacing(8)
        atmo_grid.setColumnStretch(1, 1)
        atmo_grid.setColumnStretch(3, 1)

        atmo_grid.addWidget(self._label("BG Top"), 0, 0)
        self.env_bg_top_spin = QSpinBox()
        self.env_bg_top_spin.setRange(*LIMITS["bg_top"])
        self.env_bg_top_spin.setToolTip("Top (zenith) gradient color — 0..60 darker. Horizon blend is automatic.")
        self.env_bg_top_spin.setMinimumHeight(26)
        atmo_grid.addWidget(self.env_bg_top_spin, 0, 1)

        atmo_grid.addWidget(self._label("BG Bottom"), 0, 2)
        self.env_bg_bottom_spin = QSpinBox()
        self.env_bg_bottom_spin.setRange(*LIMITS["bg_bottom"])
        self.env_bg_bottom_spin.setToolTip("Bottom (horizon) gradient color — 0..80 brighter.")
        self.env_bg_bottom_spin.setMinimumHeight(26)
        atmo_grid.addWidget(self.env_bg_bottom_spin, 0, 3)

        atmo_grid.addWidget(self._label("Vignetting"), 1, 0)
        self.env_vignetting_spin = QSpinBox()
        self.env_vignetting_spin.setRange(*LIMITS["vignetting_pct"])
        self.env_vignetting_spin.setSuffix("%")
        self.env_vignetting_spin.setToolTip("Edge darkening — radial falloff 1 - strength*(r/R)^1.8 clamped [0.35,1]. 0%=off, 92%=max.")
        self.env_vignetting_spin.setMinimumHeight(26)
        atmo_grid.addWidget(self.env_vignetting_spin, 1, 1)

        atmo_grid.addWidget(self._label("Haze"), 1, 2)
        self.haze_spin = QSpinBox()
        self.haze_spin.setRange(*LIMITS["haze_pct"])
        self.haze_spin.setSuffix("%")
        self.haze_spin.setToolTip("Overall fog/haze level — filtered white noise (H/8 × W/8 → blur σ=12) scaled ×8. 0%=clear, 100%=dense.")
        self.haze_spin.setMinimumHeight(26)
        atmo_grid.addWidget(self.haze_spin, 1, 3)

        root.addWidget(atmo_box)

        # ----------------------------------------------------
        # Section D: Starfield / Clutter
        # ----------------------------------------------------
        stars_box = QGroupBox("Set Starfield")
        stars_grid = QGridLayout(stars_box)
        stars_grid.setContentsMargins(12, 18, 12, 12)
        stars_grid.setHorizontalSpacing(8)
        stars_grid.setVerticalSpacing(8)
        stars_grid.setColumnStretch(1, 1)
        stars_grid.setColumnStretch(3, 1)

        stars_grid.addWidget(self._label("Stars"), 0, 0)
        self.env_star_count_spin = QSpinBox()
        self.env_star_count_spin.setRange(*LIMITS["star_count"])
        self.env_star_count_spin.setToolTip("Star / clutter count — 0..4000. Magnitude tiers via exponential distribution + 2% rare-bright tail.")
        self.env_star_count_spin.setMinimumHeight(26)
        stars_grid.addWidget(self.env_star_count_spin, 0, 1)

        stars_grid.addWidget(self._label("Brightness"), 0, 2)
        self.env_star_brightness_spin = QDoubleSpinBox()
        self.env_star_brightness_spin.setRange(*LIMITS["star_brightness"])
        self.env_star_brightness_spin.setSingleStep(0.1)
        self.env_star_brightness_spin.setDecimals(1)
        self.env_star_brightness_spin.setToolTip("Global star brightness scale — 0.5..1.8× base mag 35-130. Affects detection vs clutter tradeoff.")
        self.env_star_brightness_spin.setMinimumHeight(26)
        stars_grid.addWidget(self.env_star_brightness_spin, 0, 3)

        root.addWidget(stars_box)

        # ----------------------------------------------------
        # Section E: Dynamics — Time-varying animation
        # ----------------------------------------------------
        dyn_box = QGroupBox("Background Dynamics")
        dyn_grid = QGridLayout(dyn_box)
        dyn_grid.setContentsMargins(12, 18, 12, 12)
        dyn_grid.setHorizontalSpacing(8)
        dyn_grid.setVerticalSpacing(8)
        dyn_grid.setColumnStretch(1, 1)
        dyn_grid.setColumnStretch(3, 1)

        self.dynamic_check = QCheckBox("Dynamic scene")
        self.dynamic_check.setToolTip("When enabled, stars twinkle ±18% and haze shimmers — time advances at dynamic_speed × dt.")
        self.dynamic_check.setStyleSheet("font-size:11px; color:#0f172a;")
        dyn_grid.addWidget(self.dynamic_check, 0, 0, 1, 2)

        dyn_grid.addWidget(self._label("Speed"), 0, 2)
        self.env_dynamic_speed_spin = QDoubleSpinBox()
        self.env_dynamic_speed_spin.setRange(*LIMITS["dynamic_speed"])
        self.env_dynamic_speed_spin.setSingleStep(0.1)
        self.env_dynamic_speed_spin.setDecimals(1)
        self.env_dynamic_speed_spin.setSuffix(" x")
        self.env_dynamic_speed_spin.setToolTip("Animation speed multiplier — 0.1..5.0 ×. Effective only when Dynamic is on; drives update(dt * speed).")
        self.env_dynamic_speed_spin.setMinimumHeight(26)
        dyn_grid.addWidget(self.env_dynamic_speed_spin, 0, 3)

        dyn_hint = QLabel("Whether background elements move/animate — disable for static bench, enable for realism.")
        dyn_hint.setWordWrap(True)
        dyn_hint.setStyleSheet("color:#64748b; font-size:10px; font-style:italic;")
        dyn_grid.addWidget(dyn_hint, 1, 0, 1, 4)

        root.addWidget(dyn_box)

        # ----------------------------------------------------
        # Wiring — emit validated config on any change
        # ----------------------------------------------------
        for w in [
            self.scene_w_spin,
            self.scene_h_spin,
            self.seed_spin,
            self.env_bg_top_spin,
            self.env_bg_bottom_spin,
            self.env_vignetting_spin,
            self.haze_spin,
            self.env_star_count_spin,
            self.env_star_brightness_spin,
            self.env_dynamic_speed_spin,
        ]:
            w.valueChanged.connect(self._emit_config)

        self.dynamic_check.toggled.connect(self._on_dynamic_toggled)
        self.random_seed_btn.clicked.connect(self.randomizeRequested.emit)
        # Dynamic speed disabled when toggle off (clear UX)
        self._sync_dynamic_speed_enabled()

        root.addStretch()

    # ========================================================
    # SECTION: Helpers
    # ========================================================

    def _label(self, text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setStyleSheet("color:#334155; font-size:11px;")
        return lbl

    def _on_dynamic_toggled(self, checked: bool) -> None:
        """Enable/disable speed spin for clarity, then emit config."""
        self._sync_dynamic_speed_enabled()
        self._emit_config()

    def _sync_dynamic_speed_enabled(self) -> None:
        enabled = self.dynamic_check.isChecked()
        self.env_dynamic_speed_spin.setEnabled(enabled)
        # Visual cue: dim label not needed — disabled spin is sufficient

    # ========================================================
    # SECTION: Config ↔ UI Sync
    # ========================================================

    def collect_config(self) -> EnvironmentConfig:
        """Read current UI into a validated EnvironmentConfig."""
        return EnvironmentConfig(
            world_width=int(self.scene_w_spin.value()),
            world_height=int(self.scene_h_spin.value()),
            seed=int(self.seed_spin.value()),
            bg_top=int(self.env_bg_top_spin.value()),
            bg_bottom=int(self.env_bg_bottom_spin.value()),
            vignetting_pct=int(self.env_vignetting_spin.value()),
            haze_pct=int(self.haze_spin.value()),
            star_count=int(self.env_star_count_spin.value()),
            star_brightness=float(self.env_star_brightness_spin.value()),
            dynamic=bool(self.dynamic_check.isChecked()),
            dynamic_speed=float(self.env_dynamic_speed_spin.value()),
        ).validate()

    def set_config(self, cfg: EnvironmentConfig, emit: bool = False) -> None:
        """Populate UI from a config (blocks signals to avoid spurious emits)."""
        cfg = cfg.validate()
        # Block signals during bulk update
        for w in [
            self.scene_w_spin,
            self.scene_h_spin,
            self.seed_spin,
            self.env_bg_top_spin,
            self.env_bg_bottom_spin,
            self.env_vignetting_spin,
            self.haze_spin,
            self.env_star_count_spin,
            self.env_star_brightness_spin,
            self.env_dynamic_speed_spin,
            self.dynamic_check,
        ]:
            w.blockSignals(True)
        try:
            self.scene_w_spin.setValue(int(cfg.world_width))
            self.scene_h_spin.setValue(int(cfg.world_height))
            self.seed_spin.setValue(int(cfg.seed) if cfg.seed is not None else int(DEFAULTS["seed"]))
            self.env_bg_top_spin.setValue(int(cfg.bg_top))
            self.env_bg_bottom_spin.setValue(int(cfg.bg_bottom))
            self.env_vignetting_spin.setValue(int(cfg.vignetting_pct))
            self.haze_spin.setValue(int(cfg.haze_pct))
            self.env_star_count_spin.setValue(int(cfg.star_count))
            self.env_star_brightness_spin.setValue(float(cfg.star_brightness))
            self.dynamic_check.setChecked(bool(cfg.dynamic))
            self.env_dynamic_speed_spin.setValue(float(cfg.dynamic_speed))
            self._sync_dynamic_speed_enabled()
        finally:
            for w in [
                self.scene_w_spin,
                self.scene_h_spin,
                self.seed_spin,
                self.env_bg_top_spin,
                self.env_bg_bottom_spin,
                self.env_vignetting_spin,
                self.haze_spin,
                self.env_star_count_spin,
                self.env_star_brightness_spin,
                self.env_dynamic_speed_spin,
                self.dynamic_check,
            ]:
                w.blockSignals(False)
        if emit:
            self._emit_config()

    def _emit_config(self) -> None:
        """Emit a validated config snapshot (connected to MainWindow debounced HOT)."""
        try:
            cfg = self.collect_config()
            self.configChanged.emit(cfg)
        except Exception:
            pass

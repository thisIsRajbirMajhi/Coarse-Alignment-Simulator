# gui/panels/environment_panel.py - Grouped control panel for all 10 Environment parameters (canonical location)
# Replaces gui/environment_panel.py (now a shim). Import via gui.panels.environment_panel preferred,
# but gui.environment_panel remains for backwards compat.

from PyQt5.QtCore import Qt, pyqtSignal
from gui.panels.base import BaseConfigPanel
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

class EnvironmentPanel(BaseConfigPanel):
    """
    Grouped Environment controls for the Environment tab.

    Emits:
      configChanged(EnvironmentConfig) — on any of the 10 params changed
      randomizeRequested()             — when Randomize clicked
    """

    # Emitted with a validated EnvironmentConfig snaps
    configChanged = pyqtSignal(object)
    randomizeRequested = pyqtSignal()

    def __init__(self, parent=None, initial: EnvironmentConfig | None = None):
        super().__init__(parent)
        self._initial = (initial or EnvironmentConfig()).validate()
        self._build_ui()
        self.set_config(self._initial, emit=False)

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(10)

        world_box = QGroupBox("World — Size (PDF min 2000×2000, up to 5000×5000)")
        world_grid = QGridLayout(world_box)
        world_grid.setContentsMargins(12, 18, 12, 12)
        world_grid.setHorizontalSpacing(8)
        world_grid.setVerticalSpacing(8)
        world_grid.setColumnStretch(1, 1)
        world_grid.setColumnStretch(3, 1)
        world_grid.addWidget(self._label("Width"), 0, 0)
        self.scene_w_spin = QSpinBox()
        self.scene_w_spin.setRange(2000, 5000)
        self.scene_w_spin.setSingleStep(500)
        self.scene_w_spin.setSuffix(" px")
        self.scene_w_spin.setValue(2000)
        self.scene_w_spin.setToolTip("World width 2000..5000 per PDF. 2000 recommended for 30 FPS; 5000 heavy (~6× slower).")
        self.scene_w_spin.setMinimumHeight(26)
        world_grid.addWidget(self.scene_w_spin, 0, 1)
        world_grid.addWidget(self._label("Height"), 0, 2)
        self.scene_h_spin = QSpinBox()
        self.scene_h_spin.setRange(2000, 5000)
        self.scene_h_spin.setSingleStep(500)
        self.scene_h_spin.setSuffix(" px")
        self.scene_h_spin.setValue(2000)
        self.scene_h_spin.setToolTip("World height 2000..5000. Keep square for God View.")
        self.scene_h_spin.setMinimumHeight(26)
        world_grid.addWidget(self.scene_h_spin, 0, 3)
        world_hint = QLabel("Default 2000×2000 (PDF min) for 30 FPS. Raise to 5000 for larger FOV range — FPS will drop (~6× pixels).")
        world_hint.setWordWrap(True)
        world_hint.setStyleSheet("color:#64748b; font-size:10px; font-style:italic;")
        world_grid.addWidget(world_hint, 1, 0, 1, 4)
        # World presets — one-click scene sizes
        preset_row = QHBoxLayout()
        preset_row.setSpacing(6)
        self.btn_world_2k = QPushButton("2K (2000)")
        self.btn_world_2k.setMinimumHeight(28)
        self.btn_world_2k.setToolTip("Set world to 2000×2000 — fastest 30 Hz, PDF minimum")
        self.btn_world_2k.setStyleSheet("background:#ffffff; border:1px solid #d1d5db; border-radius:4px; padding:4px 8px; font-weight:500;")
        self.btn_world_3k = QPushButton("3K (3000)")
        self.btn_world_3k.setMinimumHeight(28)
        self.btn_world_3k.setToolTip("Set world to 3000×3000 — balanced")
        self.btn_world_3k.setStyleSheet("background:#ffffff; border:1px solid #d1d5db; border-radius:4px; padding:4px 8px; font-weight:500;")
        self.btn_world_5k = QPushButton("5K (5000)")
        self.btn_world_5k.setMinimumHeight(28)
        self.btn_world_5k.setToolTip("Set world to 5000×5000 — largest, heavy (~6× slower, 15 FPS)")
        self.btn_world_5k.setStyleSheet("background:#111827; color:#ffffff; border:1px solid #111827; border-radius:4px; padding:4px 8px; font-weight:600;")
        for b in (self.btn_world_2k, self.btn_world_3k, self.btn_world_5k):
            preset_row.addWidget(b)
        world_grid.addLayout(preset_row, 2, 0, 1, 4)
        # Wire presets
        self.btn_world_2k.clicked.connect(lambda: self._apply_world_preset(2000))
        self.btn_world_3k.clicked.connect(lambda: self._apply_world_preset(3000))
        self.btn_world_5k.clicked.connect(lambda: self._apply_world_preset(5000))
        root.addWidget(world_box)

        seed_box = QGroupBox("Seed — Reproducible Scenes")
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
        self.random_seed_btn.setToolTip("Reroll seed to a random value (0..999999) and regenerate.")
        self.random_seed_btn.setStyleSheet("background:#ffffff; border:1px solid #d1d5db; border-radius:4px; padding:4px 10px;")
        seed_grid.addWidget(self.random_seed_btn, 0, 2, 1, 2)
        seed_hint = QLabel("Deterministic: same seed → identical sky, haze, and stars.")
        seed_hint.setWordWrap(True)
        seed_hint.setStyleSheet("color:#64748b; font-size:10px; font-style:italic;")
        seed_grid.addWidget(seed_hint, 1, 0, 1, 4)
        root.addWidget(seed_box)

        atmo_box = QGroupBox("Atmosphere — Gradient + Haze")
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
        self.env_vignetting_spin.setToolTip("Camera lens vignetting (image-space) — radial falloff 1 - strength*(r/R)^1.8 centered on FOV, not world. 0%=off, 92%=max. Follows camera pan/tilt.")
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

        stars_box = QGroupBox("Starfield / Clutter")
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
        ]:
            w.valueChanged.connect(self._emit_config)

        self.random_seed_btn.clicked.connect(self.randomizeRequested.emit)
        root.addStretch()

    def _label(self, text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setStyleSheet("color:#374151; font-size:11px;")
        return lbl

    def _apply_world_preset(self, size: int) -> None:
        """One-click world size preset (square)."""
        for w in [self.scene_w_spin, self.scene_h_spin]:
            w.blockSignals(True)
        self.scene_w_spin.setValue(int(size))
        self.scene_h_spin.setValue(int(size))
        for w in [self.scene_w_spin, self.scene_h_spin]:
            w.blockSignals(False)
        self._emit_config()

    def collect_config(self) -> EnvironmentConfig:
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
        ).validate()

    def set_config(self, cfg: EnvironmentConfig, emit: bool = False) -> None:
        cfg = cfg.validate()
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
            ]:
                w.blockSignals(False)
        if emit:
            self._emit_config()

    def _emit_config(self) -> None:
        try:
            cfg = self.collect_config()
            self.configChanged.emit(cfg)
        except Exception:
            pass

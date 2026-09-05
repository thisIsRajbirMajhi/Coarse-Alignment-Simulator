# gui/panels/environment_panel.py - Grouped control panel — slider-based intuitive UI

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtWidgets import (
    QDoubleSpinBox,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
)

from environment.config import EnvironmentConfig
from environment.constants import DEFAULTS, LIMITS
from gui.panels.base import BaseConfigPanel


class EnvironmentPanel(BaseConfigPanel):
    """
    Environment controls — all parameters are sliders + live value (highlighted on drag).
    Reset button per panel.
    Keeps spin aliases hidden for backward compat.
    """

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

        # World — slider 2000-5000
        world_box, world_grid = self._make_group("World — Size (PDF min 2000×2000, up to 5000×5000)")
        self.slider_world_w, self.label_world_w_val = self._make_int_slider(2000, 5000, 2000, tooltip="World width 2000..5000")
        self.scene_w_spin = QSpinBox(); self.scene_w_spin.setRange(2000, 5000); self.scene_w_spin.setValue(2000); self.scene_w_spin.hide()
        world_grid.addWidget(self._label("Width"), 0, 0)
        world_grid.addWidget(self.slider_world_w, 0, 1)
        world_grid.addWidget(self.label_world_w_val, 0, 2)
        self.slider_world_h, self.label_world_h_val = self._make_int_slider(2000, 5000, 2000, tooltip="World height")
        self.scene_h_spin = QSpinBox(); self.scene_h_spin.setRange(2000, 5000); self.scene_h_spin.setValue(2000); self.scene_h_spin.hide()
        world_grid.addWidget(self._label("Height"), 0, 3)
        world_grid.addWidget(self.slider_world_h, 0, 4)
        world_grid.addWidget(self.label_world_h_val, 0, 5)
        world_hint = QLabel("Default 2000×2000 (PDF min) for 30 FPS. Raise to 5000 for larger FOV range — FPS will drop (~6× pixels).")
        world_hint.setWordWrap(True)
        world_hint.setStyleSheet("color:#64748b; font-size:10px; font-style:italic;")
        world_grid.addWidget(world_hint, 1, 0, 1, 6)
        preset_row = QHBoxLayout()
        preset_row.setSpacing(6)
        self.btn_world_2k = QPushButton("2K (2000)")
        self.btn_world_2k.setMinimumHeight(28)
        self.btn_world_3k = QPushButton("3K (3000)")
        self.btn_world_3k.setMinimumHeight(28)
        self.btn_world_5k = QPushButton("5K (5000)")
        self.btn_world_5k.setMinimumHeight(28)
        self.btn_world_5k.setStyleSheet("background:#111827; color:#ffffff; border:1px solid #111827; border-radius:4px; padding:4px 8px; font-weight:600;")
        for b in (self.btn_world_2k, self.btn_world_3k, self.btn_world_5k):
            preset_row.addWidget(b)
        world_grid.addLayout(preset_row, 2, 0, 1, 6)
        self.btn_world_2k.clicked.connect(lambda: self._apply_world_preset(2000))
        self.btn_world_3k.clicked.connect(lambda: self._apply_world_preset(3000))
        self.btn_world_5k.clicked.connect(lambda: self._apply_world_preset(5000))
        root.addWidget(world_box)

        # Seed — slider 0-999999 but slider range large, use int slider directly
        seed_box, seed_grid = self._make_group("Seed — Reproducible Scenes")
        self.slider_seed, self.label_seed_val = self._make_int_slider(0, 999999, 42, tooltip="Random seed 0..999999")
        self.seed_spin = QSpinBox(); self.seed_spin.setRange(*LIMITS["seed"]); self.seed_spin.setValue(42); self.seed_spin.hide()
        seed_grid.addWidget(self._label("Seed"), 0, 0)
        seed_grid.addWidget(self.slider_seed, 0, 1)
        seed_grid.addWidget(self.label_seed_val, 0, 2)
        self.random_seed_btn = QPushButton("Randomize")
        self.random_seed_btn.setMinimumHeight(26)
        seed_grid.addWidget(self.random_seed_btn, 0, 3, 1, 2)
        seed_hint = QLabel("Deterministic: same seed → identical sky, haze, and stars.")
        seed_hint.setWordWrap(True)
        seed_hint.setStyleSheet("color:#64748b; font-size:10px; font-style:italic;")
        seed_grid.addWidget(seed_hint, 1, 0, 1, 5)
        root.addWidget(seed_box)

        # Atmosphere
        atmo_box, atmo_grid = self._make_group("Atmosphere — Gradient + Haze")
        self.slider_bg_top, self.label_bg_top_val = self._make_int_slider(0, 60, 12, tooltip="Top zenith gradient 0..60")
        self.env_bg_top_spin = QSpinBox(); self.env_bg_top_spin.setRange(*LIMITS["bg_top"]); self.env_bg_top_spin.hide()
        atmo_grid.addWidget(self._label("BG Top"), 0, 0)
        atmo_grid.addWidget(self.slider_bg_top, 0, 1)
        atmo_grid.addWidget(self.label_bg_top_val, 0, 2)
        self.slider_bg_bottom, self.label_bg_bottom_val = self._make_int_slider(0, 80, 22, tooltip="Bottom horizon gradient 0..80")
        self.env_bg_bottom_spin = QSpinBox(); self.env_bg_bottom_spin.setRange(*LIMITS["bg_bottom"]); self.env_bg_bottom_spin.hide()
        atmo_grid.addWidget(self._label("BG Bottom"), 0, 3)
        atmo_grid.addWidget(self.slider_bg_bottom, 0, 4)
        atmo_grid.addWidget(self.label_bg_bottom_val, 0, 5)

        self.slider_vignetting, self.label_vignetting_val = self._make_int_slider(0, 92, 0, tooltip="Vignetting 0-92% image-space")
        self.env_vignetting_spin = QSpinBox(); self.env_vignetting_spin.setRange(*LIMITS["vignetting_pct"]); self.env_vignetting_spin.hide()
        atmo_grid.addWidget(self._label("Vignetting"), 1, 0)
        atmo_grid.addWidget(self.slider_vignetting, 1, 1)
        atmo_grid.addWidget(self.label_vignetting_val, 1, 2)
        self.slider_haze, self.label_haze_val = self._make_int_slider(0, 100, 35, tooltip="Haze 0-100%")
        self.haze_spin = QSpinBox(); self.haze_spin.setRange(*LIMITS["haze_pct"]); self.haze_spin.hide()
        atmo_grid.addWidget(self._label("Haze"), 1, 3)
        atmo_grid.addWidget(self.slider_haze, 1, 4)
        atmo_grid.addWidget(self.label_haze_val, 1, 5)
        root.addWidget(atmo_box)

        # Starfield
        stars_box, stars_grid = self._make_group("Starfield / Clutter")
        self.slider_star_count, self.label_star_count_val = self._make_int_slider(0, 4000, 60, tooltip="Star/clutter count 0..4000")
        self.env_star_count_spin = QSpinBox(); self.env_star_count_spin.setRange(*LIMITS["star_count"]); self.env_star_count_spin.hide()
        stars_grid.addWidget(self._label("Stars"), 0, 0)
        stars_grid.addWidget(self.slider_star_count, 0, 1)
        stars_grid.addWidget(self.label_star_count_val, 0, 2)
        lo, hi = LIMITS["star_brightness"]
        self.slider_star_brightness, self.label_star_brightness_val, self.star_brightness_factor = self._make_float_slider(lo, hi, 1.0, decimals=1, tooltip="Star brightness 0.5..1.8")
        self.env_star_brightness_spin = QDoubleSpinBox(); self.env_star_brightness_spin.setRange(lo, hi); self.env_star_brightness_spin.setValue(1.0); self.env_star_brightness_spin.hide()
        stars_grid.addWidget(self._label("Brightness"), 0, 3)
        stars_grid.addWidget(self.slider_star_brightness, 0, 4)
        stars_grid.addWidget(self.label_star_brightness_val, 0, 5)
        root.addWidget(stars_box)

        # Reset button
        self.btn_reset = self._make_reset_button("Reset Environment")
        root.addWidget(self.btn_reset)
        root.addStretch()

        # Wiring — slider -> spin sync
        self.slider_world_w.valueChanged.connect(lambda v: self._sync_int(v, self.scene_w_spin, self.label_world_w_val))
        self.slider_world_h.valueChanged.connect(lambda v: self._sync_int(v, self.scene_h_spin, self.label_world_h_val))
        self.slider_seed.valueChanged.connect(lambda v: self._sync_int(v, self.seed_spin, self.label_seed_val))
        self.slider_bg_top.valueChanged.connect(lambda v: self._sync_int(v, self.env_bg_top_spin, self.label_bg_top_val))
        self.slider_bg_bottom.valueChanged.connect(lambda v: self._sync_int(v, self.env_bg_bottom_spin, self.label_bg_bottom_val))
        self.slider_vignetting.valueChanged.connect(lambda v: self._sync_int(v, self.env_vignetting_spin, self.label_vignetting_val))
        self.slider_haze.valueChanged.connect(lambda v: self._sync_int(v, self.haze_spin, self.label_haze_val))
        self.slider_star_count.valueChanged.connect(lambda v: self._sync_int(v, self.env_star_count_spin, self.label_star_count_val))
        self.slider_star_brightness.valueChanged.connect(lambda v: self._sync_float(v, self.env_star_brightness_spin, self.label_star_brightness_val, self.star_brightness_factor, 1))

        self.random_seed_btn.clicked.connect(self.randomizeRequested.emit)
        self.btn_reset.clicked.connect(self._on_reset)

    def _sync_int(self, val: int, spin, label):
        spin.blockSignals(True)
        spin.setValue(int(val))
        spin.blockSignals(False)
        label.setText(str(int(val)))
        self._emit_config()

    def _sync_float(self, val: int, spin: QDoubleSpinBox, label: QLabel, factor: int, decimals: int):
        fval = val / factor
        spin.blockSignals(True)
        spin.setValue(float(fval))
        spin.blockSignals(False)
        label.setText(f"{fval:.{decimals}f}")
        self._emit_config()

    def _label(self, text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setStyleSheet("color:#374151; font-size:11px;")
        return lbl

    def _apply_world_preset(self, size: int) -> None:
        self.slider_world_w.setValue(int(size))
        self.slider_world_h.setValue(int(size))

    def _on_reset(self):
        self.set_config(EnvironmentConfig().validate(), emit=True)

    def collect_config(self) -> EnvironmentConfig:
        return EnvironmentConfig(
            world_width=int(self.slider_world_w.value()),
            world_height=int(self.slider_world_h.value()),
            seed=int(self.slider_seed.value()),
            bg_top=int(self.slider_bg_top.value()),
            bg_bottom=int(self.slider_bg_bottom.value()),
            vignetting_pct=int(self.slider_vignetting.value()),
            haze_pct=int(self.slider_haze.value()),
            star_count=int(self.slider_star_count.value()),
            star_brightness=float(self.slider_star_brightness.value() / self.star_brightness_factor),
        ).validate()

    def set_config(self, cfg: EnvironmentConfig, emit: bool = False) -> None:
        cfg = cfg.validate()
        sliders = [self.slider_world_w, self.slider_world_h, self.slider_seed, self.slider_bg_top, self.slider_bg_bottom, self.slider_vignetting, self.slider_haze, self.slider_star_count, self.slider_star_brightness]
        for w in sliders:
            w.blockSignals(True)
        for s in [self.scene_w_spin, self.scene_h_spin, self.seed_spin, self.env_bg_top_spin, self.env_bg_bottom_spin, self.env_vignetting_spin, self.haze_spin, self.env_star_count_spin, self.env_star_brightness_spin]:
            s.blockSignals(True)
        try:
            self.slider_world_w.setValue(int(cfg.world_width)); self.scene_w_spin.setValue(int(cfg.world_width)); self.label_world_w_val.setText(str(int(cfg.world_width)))
            self.slider_world_h.setValue(int(cfg.world_height)); self.scene_h_spin.setValue(int(cfg.world_height)); self.label_world_h_val.setText(str(int(cfg.world_height)))
            self.slider_seed.setValue(int(cfg.seed) if cfg.seed is not None else int(DEFAULTS["seed"])); self.seed_spin.setValue(int(cfg.seed) if cfg.seed is not None else int(DEFAULTS["seed"])); self.label_seed_val.setText(str(int(cfg.seed) if cfg.seed is not None else int(DEFAULTS["seed"])))
            self.slider_bg_top.setValue(int(cfg.bg_top)); self.env_bg_top_spin.setValue(int(cfg.bg_top)); self.label_bg_top_val.setText(str(int(cfg.bg_top)))
            self.slider_bg_bottom.setValue(int(cfg.bg_bottom)); self.env_bg_bottom_spin.setValue(int(cfg.bg_bottom)); self.label_bg_bottom_val.setText(str(int(cfg.bg_bottom)))
            self.slider_vignetting.setValue(int(cfg.vignetting_pct)); self.env_vignetting_spin.setValue(int(cfg.vignetting_pct)); self.label_vignetting_val.setText(str(int(cfg.vignetting_pct)))
            self.slider_haze.setValue(int(cfg.haze_pct)); self.haze_spin.setValue(int(cfg.haze_pct)); self.label_haze_val.setText(str(int(cfg.haze_pct)))
            self.slider_star_count.setValue(int(cfg.star_count)); self.env_star_count_spin.setValue(int(cfg.star_count)); self.label_star_count_val.setText(str(int(cfg.star_count)))
            self.slider_star_brightness.setValue(int(round(float(cfg.star_brightness) * self.star_brightness_factor))); self.env_star_brightness_spin.setValue(float(cfg.star_brightness)); self.label_star_brightness_val.setText(f"{float(cfg.star_brightness):.1f}")
        finally:
            for w in sliders:
                w.blockSignals(False)
            for s in [self.scene_w_spin, self.scene_h_spin, self.seed_spin, self.env_bg_top_spin, self.env_bg_bottom_spin, self.env_vignetting_spin, self.haze_spin, self.env_star_count_spin, self.env_star_brightness_spin]:
                s.blockSignals(False)
        if emit:
            self._emit_config()

    def _emit_config(self) -> None:
        try:
            cfg = self.collect_config()
            self.configChanged.emit(cfg)
        except Exception:
            pass

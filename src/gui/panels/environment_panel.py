# gui/panels/environment_panel.py - Environment Control Deck (Plans/Design.md §3).
from __future__ import annotations

import numpy as np
from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtWidgets import (
    QDoubleSpinBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
)

from src.environment.config import EnvironmentConfig
from src.environment.constants import DEFAULTS, LIMITS
from src.gui.components import EditableValue, PresetSegment
from src.gui.panels.base import BaseConfigPanel


class EnvironmentPanel(BaseConfigPanel):
    """
    Environment deck — World / Seed / Atmosphere / Starfield cards.

    Release-gated emits (scene regen is expensive); labels update live and
    every value is click-to-edit. Keeps spin aliases for backward compat.
    """

    configChanged = pyqtSignal(object)
    randomizeRequested = pyqtSignal()

    def __init__(self, parent=None, initial: EnvironmentConfig | None = None):
        super().__init__(parent)
        self._initial = (initial or EnvironmentConfig()).validate()
        # (seed, non-seed signature) at the last clean point — drives Modified.
        self._env_baseline: tuple | None = None
        self._build_ui()
        self.set_config(self._initial, emit=False)

    def _editable(self, text: str) -> EditableValue:
        return EditableValue(text, self)

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(10)

        # Page header: title + Modified flag + Randomize Environment
        header_row = QHBoxLayout()
        header_row.setSpacing(8)
        title = QLabel("ENVIRONMENT")
        title.setStyleSheet("font-size:15px; font-weight:700;")
        header_row.addWidget(title)
        self.seed_modified = QLabel("• Modified")
        self.seed_modified.setStyleSheet("color:#F2B84B; font-size:11px; font-weight:700;")
        self.seed_modified.setVisible(False)
        self.seed_modified.setToolTip("Environment changed after the seed was set")
        header_row.addWidget(self.seed_modified)
        header_row.addStretch(1)
        self.header_randomize_btn = QPushButton("🎲 Randomize Environment")
        self.header_randomize_btn.setMinimumHeight(28)
        self.header_randomize_btn.setToolTip("Randomize atmosphere, starfield and seed (world size kept)")
        header_row.addWidget(self.header_randomize_btn)
        root.addLayout(header_row)
        desc = QLabel("Scene generation, atmosphere and star distribution")
        desc.setStyleSheet("color:#8F9CAB; font-size:11px;")
        root.addWidget(desc)

        # World card — editable dimensions + preset chips
        world_box, world_grid = self._make_group("WORLD — Render dimensions")
        self.slider_world_w, _ = self._make_int_slider(2000, 5000, 2000, tooltip="World width 2000..5000")
        self.scene_w_spin = QSpinBox(); self.scene_w_spin.setRange(2000, 5000); self.scene_w_spin.setValue(2000); self.scene_w_spin.hide()
        self.label_world_w_val = self._editable("2000 px")
        world_grid.addWidget(self._label("Width"), 0, 0)
        world_grid.addWidget(self.slider_world_w, 0, 1)
        world_grid.addWidget(self.label_world_w_val, 0, 2)
        self.slider_world_h, _ = self._make_int_slider(2000, 5000, 2000, tooltip="World height")
        self.scene_h_spin = QSpinBox(); self.scene_h_spin.setRange(2000, 5000); self.scene_h_spin.setValue(2000); self.scene_h_spin.hide()
        self.label_world_h_val = self._editable("2000 px")
        world_grid.addWidget(self._label("Height"), 1, 0)
        world_grid.addWidget(self.slider_world_h, 1, 1)
        world_grid.addWidget(self.label_world_h_val, 1, 2)
        world_hint = QLabel("Default 2000×2000 (PDF min) for 30 FPS. Raise to 5000 for larger FOV range — FPS will drop (~6× pixels).")
        world_hint.setWordWrap(True)
        world_hint.setStyleSheet("color:#64748b; font-size:10px; font-style:italic;")
        world_grid.addWidget(world_hint, 2, 0, 1, 3)
        self.world_presets = PresetSegment(["2K", "3K", "5K"])
        self.world_presets.set_active("2K")
        self.world_presets.presetSelected.connect(self._on_world_preset_picked)
        world_grid.addWidget(self.world_presets, 3, 0, 1, 3)
        root.addWidget(world_box)

        # Seed card — numeric input + Generate (Design.md §3.2)
        seed_box, seed_grid = self._make_group("SEED — Reproduce the exact same scene")
        self.slider_seed, _ = self._make_int_slider(0, 999999, 42, tooltip="Random seed 0..999999")
        self.seed_spin = QSpinBox(); self.seed_spin.setRange(*LIMITS["seed"]); self.seed_spin.setValue(42); self.seed_spin.hide()
        self.label_seed_val = self._editable("42")
        self.seed_edit = QLineEdit("42")
        self.seed_edit.setMinimumHeight(26)
        self.seed_edit.setToolTip("Type an exact seed 0..999999, Enter to apply")
        try:
            self.seed_edit.setAccessibleName("Seed")
            self.seed_edit.setAccessibleDescription("Deterministic scene seed 0 to 999999")
        except Exception:
            pass
        seed_grid.addWidget(self._label("Seed"), 0, 0)
        seed_grid.addWidget(self.slider_seed, 0, 1)
        seed_grid.addWidget(self.label_seed_val, 0, 2)
        seed_grid.addWidget(self.seed_edit, 1, 0, 1, 2)
        self.random_seed_btn = QPushButton("🎲 Generate")
        self.random_seed_btn.setMinimumHeight(28)
        self.random_seed_btn.setToolTip("Generate a random seed")
        seed_grid.addWidget(self.random_seed_btn, 1, 2)
        seed_hint = QLabel("Deterministic: same seed → identical sky, haze, and stars.")
        seed_hint.setWordWrap(True)
        seed_hint.setStyleSheet("color:#64748b; font-size:10px; font-style:italic;")
        seed_grid.addWidget(seed_hint, 2, 0, 1, 3)
        root.addWidget(seed_box)

        # Atmosphere card — 2-column grid (Design.md §3.3 / §25)
        atmo_box, atmo_grid = self._make_group("ATMOSPHERE — Gradient, haze and depth")
        self.slider_bg_top, _ = self._make_int_slider(0, 60, 12, tooltip="Top zenith gradient 0..60")
        self.env_bg_top_spin = QSpinBox(); self.env_bg_top_spin.setRange(*LIMITS["bg_top"]); self.env_bg_top_spin.hide()
        self.label_bg_top_val = self._editable("12")
        atmo_grid.addWidget(self._label("BG Top"), 0, 0)
        atmo_grid.addWidget(self.slider_bg_top, 0, 1)
        atmo_grid.addWidget(self.label_bg_top_val, 0, 2)
        self.slider_bg_bottom, _ = self._make_int_slider(0, 80, 22, tooltip="Bottom horizon gradient 0..80")
        self.env_bg_bottom_spin = QSpinBox(); self.env_bg_bottom_spin.setRange(*LIMITS["bg_bottom"]); self.env_bg_bottom_spin.hide()
        self.label_bg_bottom_val = self._editable("22")
        atmo_grid.addWidget(self._label("BG Bottom"), 0, 3)
        atmo_grid.addWidget(self.slider_bg_bottom, 0, 4)
        atmo_grid.addWidget(self.label_bg_bottom_val, 0, 5)

        self.slider_vignetting, _ = self._make_int_slider(0, 92, 0, tooltip="Vignetting 0-92% image-space")
        self.env_vignetting_spin = QSpinBox(); self.env_vignetting_spin.setRange(*LIMITS["vignetting_pct"]); self.env_vignetting_spin.hide()
        self.label_vignetting_val = self._editable("0%")
        atmo_grid.addWidget(self._label("Vignette"), 1, 0)
        atmo_grid.addWidget(self.slider_vignetting, 1, 1)
        atmo_grid.addWidget(self.label_vignetting_val, 1, 2)
        self.slider_haze, _ = self._make_int_slider(0, 100, 35, tooltip="Haze 0-100%")
        self.haze_spin = QSpinBox(); self.haze_spin.setRange(*LIMITS["haze_pct"]); self.haze_spin.hide()
        self.label_haze_val = self._editable("35%")
        atmo_grid.addWidget(self._label("Haze"), 1, 3)
        atmo_grid.addWidget(self.slider_haze, 1, 4)
        atmo_grid.addWidget(self.label_haze_val, 1, 5)
        root.addWidget(atmo_box)

        # Starfield card — compact (Design.md §3.4)
        stars_box, stars_grid = self._make_group("★ STARFIELD")
        self.slider_star_count, _ = self._make_int_slider(0, 4000, 60, tooltip="Star/clutter count 0..4000")
        self.env_star_count_spin = QSpinBox(); self.env_star_count_spin.setRange(*LIMITS["star_count"]); self.env_star_count_spin.hide()
        self.label_star_count_val = self._editable("60")
        stars_grid.addWidget(self._label("Stars"), 0, 0)
        stars_grid.addWidget(self.slider_star_count, 0, 1)
        stars_grid.addWidget(self.label_star_count_val, 0, 2)
        lo, hi = LIMITS["star_brightness"]
        self.slider_star_brightness, _, self.star_brightness_factor = self._make_float_slider(lo, hi, 1.0, decimals=1, tooltip="Star brightness 0.5..1.8")
        self.env_star_brightness_spin = QDoubleSpinBox(); self.env_star_brightness_spin.setRange(lo, hi); self.env_star_brightness_spin.setValue(1.0); self.env_star_brightness_spin.hide()
        self.label_star_brightness_val = self._editable("1.0×")
        stars_grid.addWidget(self._label("Brightness"), 0, 3)
        stars_grid.addWidget(self.slider_star_brightness, 0, 4)
        stars_grid.addWidget(self.label_star_brightness_val, 0, 5)
        root.addWidget(stars_box)

        # Reset button
        self.btn_reset = self._make_reset_button("Reset Environment")
        root.addWidget(self.btn_reset)
        root.addStretch()

        # Wiring — valueChanged updates the pill label only (cheap); the config
        # is emitted on sliderReleased or for non-drag changes (keyboard,
        # programmatic). Heavy scene rebuilds thus fire once per gesture.
        self.slider_world_w.valueChanged.connect(lambda v: self._sync_int(self.slider_world_w, v, self.scene_w_spin, self.label_world_w_val, " px", world=True))
        self.slider_world_h.valueChanged.connect(lambda v: self._sync_int(self.slider_world_h, v, self.scene_h_spin, self.label_world_h_val, " px", world=True))
        self.slider_seed.valueChanged.connect(lambda v: self._sync_int(self.slider_seed, v, self.seed_spin, self.label_seed_val, "", seed=True))
        self.slider_bg_top.valueChanged.connect(lambda v: self._sync_int(self.slider_bg_top, v, self.env_bg_top_spin, self.label_bg_top_val))
        self.slider_bg_bottom.valueChanged.connect(lambda v: self._sync_int(self.slider_bg_bottom, v, self.env_bg_bottom_spin, self.label_bg_bottom_val))
        self.slider_vignetting.valueChanged.connect(lambda v: self._sync_int(self.slider_vignetting, v, self.env_vignetting_spin, self.label_vignetting_val, "%"))
        self.slider_haze.valueChanged.connect(lambda v: self._sync_int(self.slider_haze, v, self.haze_spin, self.label_haze_val, "%"))
        self.slider_star_count.valueChanged.connect(lambda v: self._sync_int(self.slider_star_count, v, self.env_star_count_spin, self.label_star_count_val))
        self.slider_star_brightness.valueChanged.connect(lambda v: self._sync_float(self.slider_star_brightness, v, self.env_star_brightness_spin, self.label_star_brightness_val, self.star_brightness_factor, 1, "×"))
        for _s in (self.slider_world_w, self.slider_world_h, self.slider_seed,
                   self.slider_bg_top, self.slider_bg_bottom, self.slider_vignetting,
                   self.slider_haze, self.slider_star_count, self.slider_star_brightness):
            _s.sliderReleased.connect(self._emit_config)
        # Click-to-edit values commit back to their slider.
        self._wire_editor(self.label_world_w_val, self.slider_world_w, 1, "")
        self._wire_editor(self.label_world_h_val, self.slider_world_h, 1, "")
        self._wire_editor(self.label_seed_val, self.slider_seed, 1, "")
        self._wire_editor(self.label_bg_top_val, self.slider_bg_top, 1, "")
        self._wire_editor(self.label_bg_bottom_val, self.slider_bg_bottom, 1, "")
        self._wire_editor(self.label_vignetting_val, self.slider_vignetting, 1, "%")
        self._wire_editor(self.label_haze_val, self.slider_haze, 1, "%")
        self._wire_editor(self.label_star_count_val, self.slider_star_count, 1, "")
        self._wire_editor(self.label_star_brightness_val, self.slider_star_brightness,
                          self.star_brightness_factor, "×")

        self.random_seed_btn.clicked.connect(self._randomize_seed)
        self.header_randomize_btn.clicked.connect(self._randomize_all)
        self.seed_edit.editingFinished.connect(self._on_seed_edit_committed)
        self.btn_reset.clicked.connect(self._on_reset)

    def _wire_editor(self, editor: EditableValue, slider, factor: int, unit: str) -> None:
        def _commit(text: str) -> None:
            try:
                raw = str(text).strip()
                if unit and raw.endswith(unit):
                    raw = raw[: -len(unit)].strip()
                v = int(round(float(raw) * factor))
                v = max(slider.minimum(), min(slider.maximum(), v))
                slider.setValue(v)  # valueChanged syncs spin/label; emits unless dragging
                if slider.isSliderDown():
                    self._emit_config()
            except (TypeError, ValueError):
                pass
        editor.committed.connect(_commit)

    def _randomize_seed(self):
        """Random seed 0..999999 (widget updates, config emitted)."""
        import random
        self.slider_seed.setValue(random.randint(0, 999999))
        self._emit_config()

    def _randomize_all(self):
        """Randomize atmosphere + starfield + seed (world size kept)."""
        rng = np.random.default_rng()
        cfg = self.collect_config().randomize_for_training(rng, "mixed")
        cfg.world_width = int(self.slider_world_w.value())
        cfg.world_height = int(self.slider_world_h.value())
        self.set_config(cfg.validate(), emit=True)
        self.randomizeRequested.emit()

    def _on_seed_edit_committed(self) -> None:
        try:
            v = int(str(self.seed_edit.text()).strip())
        except (TypeError, ValueError):
            self.seed_edit.setText(str(self.slider_seed.value()))
            return
        v = max(self.slider_seed.minimum(), min(self.slider_seed.maximum(), v))
        self.slider_seed.setValue(v)
        self._emit_config()

    def _sync_int(self, slider, val: int, spin, label, unit: str = "", world: bool = False, seed: bool = False):
        spin.blockSignals(True)
        spin.setValue(int(val))
        spin.blockSignals(False)
        label.setText(f"{int(val)}{unit}")
        if seed:
            self.seed_edit.blockSignals(True)
            self.seed_edit.setText(str(int(val)))
            self.seed_edit.blockSignals(False)
        if world:
            self.world_presets.mark_custom()
        if not slider.isSliderDown():
            self._emit_config()

    def _sync_float(self, slider, val: int, spin: QDoubleSpinBox, label: QLabel, factor: int, decimals: int, unit: str = ""):
        fval = val / factor
        spin.blockSignals(True)
        spin.setValue(float(fval))
        spin.blockSignals(False)
        label.setText(f"{fval:.{decimals}f}{unit}")
        if not slider.isSliderDown():
            self._emit_config()

    def _label(self, text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setStyleSheet("color:#374151; font-size:11px;")
        return lbl

    def _on_world_preset_picked(self, name: str) -> None:
        self._apply_world_preset({"2K": 2000, "3K": 3000, "5K": 5000}.get(name, 2000))

    def _apply_world_preset(self, size: int) -> None:
        self.slider_world_w.setValue(int(size))
        self.slider_world_h.setValue(int(size))
        self.world_presets.set_active({2000: "2K", 3000: "3K", 5000: "5K"}.get(int(size)))

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
            seed_val = int(cfg.seed) if cfg.seed is not None else int(DEFAULTS["seed"])
            self.slider_world_w.setValue(int(cfg.world_width)); self.scene_w_spin.setValue(int(cfg.world_width)); self.label_world_w_val.setText(f"{int(cfg.world_width)} px")
            self.slider_world_h.setValue(int(cfg.world_height)); self.scene_h_spin.setValue(int(cfg.world_height)); self.label_world_h_val.setText(f"{int(cfg.world_height)} px")
            self.slider_seed.setValue(seed_val); self.seed_spin.setValue(seed_val); self.label_seed_val.setText(str(seed_val))
            self.seed_edit.setText(str(seed_val))
            self.slider_bg_top.setValue(int(cfg.bg_top)); self.env_bg_top_spin.setValue(int(cfg.bg_top)); self.label_bg_top_val.setText(str(int(cfg.bg_top)))
            self.slider_bg_bottom.setValue(int(cfg.bg_bottom)); self.env_bg_bottom_spin.setValue(int(cfg.bg_bottom)); self.label_bg_bottom_val.setText(str(int(cfg.bg_bottom)))
            self.slider_vignetting.setValue(int(cfg.vignetting_pct)); self.env_vignetting_spin.setValue(int(cfg.vignetting_pct)); self.label_vignetting_val.setText(f"{int(cfg.vignetting_pct)}%")
            self.slider_haze.setValue(int(cfg.haze_pct)); self.haze_spin.setValue(int(cfg.haze_pct)); self.label_haze_val.setText(f"{int(cfg.haze_pct)}%")
            self.slider_star_count.setValue(int(cfg.star_count)); self.env_star_count_spin.setValue(int(cfg.star_count)); self.label_star_count_val.setText(str(int(cfg.star_count)))
            self.slider_star_brightness.setValue(int(round(float(cfg.star_brightness) * self.star_brightness_factor))); self.env_star_brightness_spin.setValue(float(cfg.star_brightness)); self.label_star_brightness_val.setText(f"{float(cfg.star_brightness):.1f}×")
            self._env_baseline = self._baseline_of(cfg)
            self.seed_modified.setVisible(False)
            if int(cfg.world_width) == int(cfg.world_height):
                self.world_presets.set_active({2000: "2K", 3000: "3K", 5000: "5K"}.get(int(cfg.world_width)))
            else:
                self.world_presets.mark_custom()
        finally:
            for w in sliders:
                w.blockSignals(False)
            for s in [self.scene_w_spin, self.scene_h_spin, self.seed_spin, self.env_bg_top_spin, self.env_bg_bottom_spin, self.env_vignetting_spin, self.haze_spin, self.env_star_count_spin, self.env_star_brightness_spin]:
                s.blockSignals(False)
        if emit:
            self._emit_config()

    @staticmethod
    def _baseline_of(cfg: EnvironmentConfig) -> tuple:
        """(seed, non-seed signature) — Modified shows when the signature
        drifts after the seed was established (Design.md §3.2)."""
        seed = int(cfg.seed) if cfg.seed is not None else -1
        sig = (int(cfg.world_width), int(cfg.world_height), int(cfg.bg_top),
               int(cfg.bg_bottom), int(cfg.vignetting_pct), int(cfg.haze_pct),
               int(cfg.star_count), round(float(cfg.star_brightness), 3))
        return (seed, sig)

    def _emit_config(self) -> None:
        try:
            cfg = self.collect_config()
            try:
                cur = self._baseline_of(cfg)
                if self._env_baseline is None:
                    self._env_baseline = cur
                    self.seed_modified.setVisible(False)
                elif cur[1] != self._env_baseline[1]:
                    self.seed_modified.setVisible(True)
                else:
                    self._env_baseline = cur  # seed-only change stays clean
                    self.seed_modified.setVisible(False)
            except Exception:
                pass
            self.configChanged.emit(cfg)
        except Exception as e:
            import logging
            logging.getLogger(__name__).warning("environment config invalid, not applied: %s", e)

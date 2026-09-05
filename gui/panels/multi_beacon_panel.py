# gui/panels/multi_beacon_panel.py - Single unified beacon panel: intuitive sliders, reset, highlighted

from PyQt5.QtCore import pyqtSignal
from PyQt5.QtWidgets import (
    QCheckBox,
    QComboBox,
    QGridLayout,
    QGroupBox,
    QLabel,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from target.config import MultiBeaconConfig
from target.constants import BEACON_SHAPES, MOTION_PROFILES_DISPLAY, MULTI_BEACON_LIMITS
from gui.panels.base import BaseConfigPanel


class MultiBeaconPanel(BaseConfigPanel):
    """
    Single panel for all beacon/target settings — now slider-based.
    All numeric params are sliders + live value (highlighted on drag).
    Reset button restores defaults.
    Keeps spinbox aliases hidden for backward compat (spin_* still exists).
    """

    multiConfigChanged = pyqtSignal(object)
    targetChanged = pyqtSignal(int)
    randomizeAllRequested = pyqtSignal()
    randomizeMotionRequested = pyqtSignal()
    threshChanged = pyqtSignal(int)

    def __init__(self, initial: MultiBeaconConfig | None = None, world_bounds: tuple[int, int] = (5000, 5000), parent=None):
        super().__init__(parent)
        self._world_bounds = world_bounds
        self._config = (initial or MultiBeaconConfig(beacon_count=1, target_index=0)).validate()
        self._build_ui()
        self.set_config(self._config, emit=False)

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(10)

        box, grid = self._make_group("Beacon / Target — sliders (highlighted on use)")

        # Count slider (1-5)
        lo, hi = MULTI_BEACON_LIMITS["beacon_count"]
        self.slider_beacon_count, self.label_beacon_count_val = self._make_int_slider(int(lo), int(hi), 1, tooltip="Number of targets 1-5")
        # Hidden spin for compat
        self.spin_beacon_count = QSpinBox(); self.spin_beacon_count.setRange(int(lo), int(hi)); self.spin_beacon_count.setValue(1); self.spin_beacon_count.hide()
        grid.addWidget(self._label("Count"), 0, 0)
        grid.addWidget(self.slider_beacon_count, 0, 1)
        grid.addWidget(self.label_beacon_count_val, 0, 2)
        # Target
        self.slider_target_index, self.label_target_val = self._make_int_slider(0, 4, 0, tooltip="Which beacon is target")
        self.spin_target_index = QSpinBox(); self.spin_target_index.setRange(0, 4); self.spin_target_index.hide()
        grid.addWidget(self._label("Target"), 0, 3)
        grid.addWidget(self.slider_target_index, 0, 4)
        grid.addWidget(self.label_target_val, 0, 5)

        # Shape + Blinking
        grid.addWidget(self._label("Shape"), 1, 0)
        self.combo_shape = QComboBox()
        self.combo_shape.addItems([s.capitalize() for s in BEACON_SHAPES])
        self.combo_shape.setToolTip("Square, Circle, Random")
        self.combo_shape.setMinimumHeight(26)
        grid.addWidget(self.combo_shape, 1, 1)
        self.chk_blinking = QCheckBox("Blinking")
        self.chk_blinking.setToolTip("Toggle blinking")
        grid.addWidget(self.chk_blinking, 1, 2, 1, 2)
        # keep layout filler
        grid.addWidget(QLabel(""), 1, 4, 1, 2)

        # Size W/H sliders 5-20 and 2-20
        self.slider_size_w, self.label_size_w_val = self._make_int_slider(5, 20, 10, tooltip="Target width 5-20 px")
        self.spin_size_w = QSpinBox(); self.spin_size_w.setRange(5, 20); self.spin_size_w.setValue(10); self.spin_size_w.hide()
        grid.addWidget(self._label("Size W"), 2, 0)
        grid.addWidget(self.slider_size_w, 2, 1)
        grid.addWidget(self.label_size_w_val, 2, 2)
        self.slider_size_h, self.label_size_h_val = self._make_int_slider(2, 20, 10, tooltip="Target height 2-20 px")
        self.spin_size_h = QSpinBox(); self.spin_size_h.setRange(2, 20); self.spin_size_h.setValue(10); self.spin_size_h.hide()
        grid.addWidget(self._label("H"), 2, 3)
        grid.addWidget(self.slider_size_h, 2, 4)
        grid.addWidget(self.label_size_h_val, 2, 5)

        # X/Y sliders 0-5000
        self.slider_x, self.label_x_val = self._make_int_slider(0, 5000, 2500, tooltip="Initial X")
        self.spin_x = QSpinBox(); self.spin_x.setRange(0, 5000); self.spin_x.setValue(2500); self.spin_x.hide()
        grid.addWidget(self._label("Init X"), 3, 0)
        grid.addWidget(self.slider_x, 3, 1)
        grid.addWidget(self.label_x_val, 3, 2)
        self.slider_y, self.label_y_val = self._make_int_slider(0, 5000, 2500, tooltip="Initial Y")
        self.spin_y = QSpinBox(); self.spin_y.setRange(0, 5000); self.spin_y.setValue(2500); self.spin_y.hide()
        grid.addWidget(self._label("Y"), 3, 3)
        grid.addWidget(self.slider_y, 3, 4)
        grid.addWidget(self.label_y_val, 3, 5)

        self.btn_random_loc = QPushButton("Random Location")
        self.btn_random_loc.setMinimumHeight(26)
        self.btn_random_loc.setToolTip("Randomize initial location")
        grid.addWidget(self.btn_random_loc, 4, 0, 1, 6)

        # Motion
        grid.addWidget(self._label("Motion"), 5, 0)
        self.combo_motion = QComboBox()
        self.combo_motion.addItems(MOTION_PROFILES_DISPLAY)
        self.combo_motion.setToolTip("Motion: applies to all; Random per beacon")
        self.combo_motion.setMinimumHeight(26)
        grid.addWidget(self.combo_motion, 5, 1, 1, 5)

        # Speed slider 5-300
        self.slider_speed, self.label_speed_val = self._make_int_slider(5, 300, 60, tooltip="Beacon speed px/s")
        self.spin_speed = QSpinBox(); self.spin_speed.setRange(5, 300); self.spin_speed.setValue(60); self.spin_speed.hide()
        grid.addWidget(self._label("Speed"), 6, 0)
        grid.addWidget(self.slider_speed, 6, 1)
        grid.addWidget(self.label_speed_val, 6, 2)
        self.chk_random_speed = QCheckBox("Random")
        self.chk_random_speed.setToolTip("Randomize speed per beacon")
        grid.addWidget(self.chk_random_speed, 6, 3)
        # Threshold slider 100-255
        self.slider_thresh, self.label_thresh_val = self._make_int_slider(100, 255, 200, tooltip="Detector threshold")
        self.spin_thresh = QSpinBox(); self.spin_thresh.setRange(100, 255); self.spin_thresh.setValue(200); self.spin_thresh.hide()
        grid.addWidget(self._label("Threshold"), 7, 0)
        grid.addWidget(self.slider_thresh, 7, 1)
        grid.addWidget(self.label_thresh_val, 7, 2)
        grid.addWidget(self._label("Tuning"), 7, 3, 1, 3)

        self.btn_randomize_motion = QPushButton("Randomize Motion")
        self.btn_randomize_motion.setMinimumHeight(28)
        grid.addWidget(self.btn_randomize_motion, 8, 0, 1, 3)
        self.btn_randomize_all = QPushButton("Randomize Parameters")
        self.btn_randomize_all.setMinimumHeight(28)
        self.btn_randomize_all.setStyleSheet("QPushButton { background:#111827; color:#ffffff; border:1px solid #111827; border-radius:4px; padding:4px 10px; font-weight:600; } QPushButton:hover { background:#1f2937; }")
        grid.addWidget(self.btn_randomize_all, 8, 3, 1, 3)

        # Status
        self.lbl_status = QLabel("1 beacon, Target #0")
        self.lbl_status.setStyleSheet("color:#6b7280; font-size:10px;")
        grid.addWidget(self.lbl_status, 9, 0, 1, 6)
        self.lbl_hint = QLabel("All beacons follow same rules; Random distributes per beacon.")
        self.lbl_hint.setWordWrap(True)
        self.lbl_hint.setStyleSheet("color:#6b7280; font-size:10px; font-style:italic; background:#ffffff; border:1px solid #e5e7eb; border-radius:4px; padding:4px;")
        grid.addWidget(self.lbl_hint, 10, 0, 1, 6)

        # Reset button
        self.btn_reset = self._make_reset_button("Reset Beacons")
        grid.addWidget(self.btn_reset, 11, 0, 1, 6)

        root.addWidget(box)
        root.addStretch()

        # Wiring — slider -> spin sync + emit
        self.slider_beacon_count.valueChanged.connect(self._on_beacon_count_changed)
        self.slider_target_index.valueChanged.connect(self._on_target_changed)
        self.slider_size_w.valueChanged.connect(lambda v: self._sync_int(v, self.spin_size_w))
        self.slider_size_h.valueChanged.connect(lambda v: self._sync_int(v, self.spin_size_h))
        self.slider_x.valueChanged.connect(lambda v: self._sync_int(v, self.spin_x))
        self.slider_y.valueChanged.connect(lambda v: self._sync_int(v, self.spin_y))
        self.combo_shape.currentTextChanged.connect(self._emit_multi_config)
        self.combo_motion.currentTextChanged.connect(self._emit_multi_config)
        self.slider_speed.valueChanged.connect(lambda v: self._sync_int(v, self.spin_speed))
        self.chk_random_speed.toggled.connect(self._emit_multi_config)
        self.chk_blinking.toggled.connect(self._emit_multi_config)
        self.slider_thresh.valueChanged.connect(lambda v: self._sync_thresh(v))
        self.btn_random_loc.clicked.connect(self._randomize_location)
        self.btn_randomize_all.clicked.connect(self.randomizeAllRequested.emit)
        self.btn_randomize_motion.clicked.connect(self.randomizeMotionRequested.emit)
        self.btn_reset.clicked.connect(self._on_reset)

        # Also keep spin -> slider sync for set_config path (blocked signals normally, but handle external spin changes)
        for sld, sp in [
            (self.slider_size_w, self.spin_size_w),
            (self.slider_size_h, self.spin_size_h),
            (self.slider_x, self.spin_x),
            (self.slider_y, self.spin_y),
            (self.slider_speed, self.spin_speed),
            (self.slider_thresh, self.spin_thresh),
            (self.slider_beacon_count, self.spin_beacon_count),
            (self.slider_target_index, self.spin_target_index),
        ]:
            sp.valueChanged.connect(lambda v, sl=sld: sl.setValue(int(v)) if sl.value() != int(v) else None)

    def _sync_int(self, val: int, spin: QSpinBox):
        spin.blockSignals(True)
        spin.setValue(int(val))
        spin.blockSignals(False)
        self._emit_multi_config()

    def _sync_thresh(self, val: int):
        self.spin_thresh.blockSignals(True)
        self.spin_thresh.setValue(int(val))
        self.spin_thresh.blockSignals(False)
        self.threshChanged.emit(int(val))
        self._emit_multi_config()

    def _label(self, text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setStyleSheet("color:#374151; font-size:11px;")
        return lbl

    def _on_beacon_count_changed(self, v: int) -> None:
        self.spin_beacon_count.blockSignals(True)
        self.spin_beacon_count.setValue(int(v))
        self.spin_beacon_count.blockSignals(False)
        self.slider_target_index.setMaximum(max(0, int(v) - 1))
        self.spin_target_index.setMaximum(max(0, int(v) - 1))
        if self.slider_target_index.value() >= int(v):
            self.slider_target_index.setValue(int(v) - 1)
        self.label_beacon_count_val.setText(str(int(v)))
        self._update_status()
        self._emit_multi_config()

    def _on_target_changed(self, idx: int) -> None:
        self.spin_target_index.blockSignals(True)
        self.spin_target_index.setValue(int(idx))
        self.spin_target_index.blockSignals(False)
        self.label_target_val.setText(str(int(idx)))
        self._update_status()
        self.targetChanged.emit(int(idx))
        self._emit_multi_config()

    def _randomize_location(self):
        import random
        self.slider_x.blockSignals(True)
        self.slider_y.blockSignals(True)
        self.slider_x.setValue(random.randint(200, 4800))
        self.slider_y.setValue(random.randint(200, 4800))
        self.slider_x.blockSignals(False)
        self.slider_y.blockSignals(False)
        self._sync_int(self.slider_x.value(), self.spin_x)
        self._sync_int(self.slider_y.value(), self.spin_y)

    def _on_reset(self):
        self.set_config(MultiBeaconConfig(beacon_count=1, target_index=0, shape="square", size_w=10, size_h=10, x=2500, y=2500, profile="curved", speed=60, blinking=False, speed_random=False).validate(), emit=True)

    def _update_status(self) -> None:
        try:
            n = int(self.slider_beacon_count.value())
            tid = int(self.slider_target_index.value())
            shape = self.combo_shape.currentText()
            motion = self.combo_motion.currentText()
            self.lbl_status.setText(f"{n} beacons, Target #{tid}, {shape}, {motion}")
        except Exception:
            pass

    def collect_multi_config(self) -> MultiBeaconConfig:
        mapping = {
            "Straight Line": "linear",
            "Circular": "curved",
            "Figure 8": "figure_eight",
            "Spiral": "spiral",
            "Sin": "sinusoidal",
            "Zig-Zag": "zigzag",
            "Random": "random",
        }
        motion_display = self.combo_motion.currentText()
        profile = mapping.get(motion_display, "curved")
        shape = self.combo_shape.currentText().lower()
        return MultiBeaconConfig(
            beacon_count=int(self.slider_beacon_count.value()),
            target_index=int(self.slider_target_index.value()),
            shape=shape,
            size_w=int(self.slider_size_w.value()),
            size_h=int(self.slider_size_h.value()),
            x=float(self.slider_x.value()),
            y=float(self.slider_y.value()),
            profile=profile,
            speed=float(self.slider_speed.value()),
            blinking=bool(self.chk_blinking.isChecked()),
            speed_random=bool(self.chk_random_speed.isChecked()),
        ).validate()

    def set_config(self, cfg: MultiBeaconConfig, emit: bool = False) -> None:
        cfg = cfg.validate()
        self._config = cfg
        for w in [self.slider_beacon_count, self.slider_target_index, self.slider_size_w, self.slider_size_h, self.slider_x, self.slider_y, self.slider_speed, self.slider_thresh]:
            w.blockSignals(True)
        for s in [self.spin_beacon_count, self.spin_target_index, self.spin_size_w, self.spin_size_h, self.spin_x, self.spin_y, self.spin_speed, self.spin_thresh]:
            s.blockSignals(True)
        self.combo_shape.blockSignals(True)
        self.combo_motion.blockSignals(True)
        self.chk_random_speed.blockSignals(True)
        self.chk_blinking.blockSignals(True)
        try:
            self.slider_beacon_count.setValue(int(cfg.beacon_count)); self.spin_beacon_count.setValue(int(cfg.beacon_count)); self.label_beacon_count_val.setText(str(int(cfg.beacon_count)))
            self.slider_target_index.setMaximum(max(0, int(cfg.beacon_count)-1)); self.spin_target_index.setMaximum(max(0, int(cfg.beacon_count)-1))
            self.slider_target_index.setValue(int(cfg.target_index)); self.spin_target_index.setValue(int(cfg.target_index)); self.label_target_val.setText(str(int(cfg.target_index)))
            shape_cap = str(cfg.shape).capitalize()
            idx = self.combo_shape.findText(shape_cap)
            if idx >= 0:
                self.combo_shape.setCurrentIndex(idx)
            self.slider_size_w.setValue(int(cfg.size_w)); self.spin_size_w.setValue(int(cfg.size_w)); self.label_size_w_val.setText(str(int(cfg.size_w)))
            self.slider_size_h.setValue(int(cfg.size_h)); self.spin_size_h.setValue(int(cfg.size_h)); self.label_size_h_val.setText(str(int(cfg.size_h)))
            self.slider_x.setValue(int(cfg.x)); self.spin_x.setValue(int(cfg.x)); self.label_x_val.setText(str(int(cfg.x)))
            self.slider_y.setValue(int(cfg.y)); self.spin_y.setValue(int(cfg.y)); self.label_y_val.setText(str(int(cfg.y)))
            rev = {
                "linear": "Straight Line",
                "curved": "Circular",
                "figure_eight": "Figure 8",
                "spiral": "Spiral",
                "sinusoidal": "Sin",
                "zigzag": "Zig-Zag",
                "random": "Random",
                "random_walk": "Random",
            }
            motion_disp = rev.get(str(cfg.profile).lower(), "Circular")
            idx = self.combo_motion.findText(motion_disp)
            if idx >= 0:
                self.combo_motion.setCurrentIndex(idx)
            self.slider_speed.setValue(int(cfg.speed)); self.spin_speed.setValue(int(cfg.speed)); self.label_speed_val.setText(str(int(cfg.speed)))
            self.chk_random_speed.setChecked(bool(getattr(cfg, "speed_random", False)))
            self.chk_blinking.setChecked(bool(cfg.blinking))
            self.slider_thresh.setValue(int(getattr(cfg, "threshold", 200)) if hasattr(cfg, "threshold") else 200)
        finally:
            for w in [self.slider_beacon_count, self.slider_target_index, self.slider_size_w, self.slider_size_h, self.slider_x, self.slider_y, self.slider_speed, self.slider_thresh]:
                w.blockSignals(False)
            for s in [self.spin_beacon_count, self.spin_target_index, self.spin_size_w, self.spin_size_h, self.spin_x, self.spin_y, self.spin_speed, self.spin_thresh]:
                s.blockSignals(False)
            self.combo_shape.blockSignals(False)
            self.combo_motion.blockSignals(False)
            self.chk_random_speed.blockSignals(False)
            self.chk_blinking.blockSignals(False)
        self._update_status()
        if emit:
            self._emit_multi_config()

    def set_world_bounds(self, bounds: tuple[int, int]) -> None:
        self._world_bounds = bounds
        try:
            w, h = bounds
            self.slider_x.setRange(0, w); self.spin_x.setRange(0, w)
            self.slider_y.setRange(0, h); self.spin_y.setRange(0, h)
        except Exception:
            pass

    def get_per_beacon_panels(self):
        return []

    def _emit_multi_config(self) -> None:
        try:
            cfg = self.collect_multi_config()
            self._config = cfg
            self._update_status()
            self.multiConfigChanged.emit(cfg)
        except Exception:
            pass

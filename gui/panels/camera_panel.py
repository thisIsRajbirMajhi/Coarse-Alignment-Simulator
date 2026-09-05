# gui/panels/camera_panel.py - Camera controls — intuitive slider-based UI (light theme, highlighted interactions)

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtWidgets import (
    QDoubleSpinBox,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QSlider,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from camera.config import CameraConfig
from camera.constants import CAMERA_LIMITS, DISPLAY_LIMITS
from environment.constants import MAX_RES
from gui.panels.base import BaseConfigPanel


class CameraPanel(BaseConfigPanel):
    """
    Camera tab — intuitive sliders for all parameters, grouped, light theme.

    Groups:
      A Sensor & FOV  B Pan-Tilt Mechanics  C Display  D Units  E Realism
    Every numeric field is a slider + live value label (highlighted on drag).
    Reset button per panel restores defaults.
    Backward-compat aliases kept: fov_w_spin etc. now point to sliders (int) or
    hidden spinboxes synced to sliders (float) so existing MainWindow code keeps working.
    """

    configChanged = pyqtSignal()

    def __init__(
        self,
        initial: CameraConfig | None = None,
        scene_bounds: tuple[int, int] = (1000, 1000),
        parent=None,
    ):
        super().__init__(parent)
        self._scene_bounds = scene_bounds
        self._initial = (initial or CameraConfig()).validate(scene_bounds)
        self._build_ui()
        self.set_config(self._initial, emit=False)

    # --- Build UI ---
    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(10)

        type_lbl = QLabel("Camera Type: Monochrome, Focal Plane Array")
        type_lbl.setStyleSheet("color:#374151; font-size:10px; font-weight:600; background:#f9fafb; border:1px solid #e5e7eb; border-radius:4px; padding:4px 8px;")
        layout.addWidget(type_lbl)

        # ---- A: Sensor & FOV ----
        fov_box, fov_grid = self._make_group("A — Sensor Resolution & FOV")
        # FOV width slider (int 100-2000)
        lo, hi = CAMERA_LIMITS["fov_width"]
        self.fov_w_slider, self.fov_w_label = self._make_int_slider(int(lo), int(hi), 640, tooltip="Sensor resolution width")
        self.fov_w_spin = self.fov_w_slider  # alias for compat (QSlider has value()/setValue())
        fov_grid.addWidget(self._label("Res W"), 0, 0)
        fov_grid.addWidget(self.fov_w_slider, 0, 1)
        fov_grid.addWidget(self.fov_w_label, 0, 2)
        fov_grid.addWidget(self._label("H"), 0, 3)
        lo2, hi2 = CAMERA_LIMITS["fov_height"]
        self.fov_h_slider, self.fov_h_label = self._make_int_slider(int(lo2), int(hi2), 480, tooltip="Sensor resolution height")
        self.fov_h_spin = self.fov_h_slider
        fov_grid.addWidget(self.fov_h_slider, 0, 4)
        fov_grid.addWidget(self.fov_h_label, 0, 5)

        # FOV deg X/Y sliders (float 1.0-10.0)
        lo, hi = CAMERA_LIMITS["fov_deg_x"]
        self.fov_deg_x_slider, self.fov_deg_x_label, self.fov_deg_x_factor = self._make_float_slider(lo, hi, 4.0, decimals=1, suffix=" deg", tooltip="Horizontal FOV degrees")
        self.fov_deg_x_spin = QDoubleSpinBox(); self.fov_deg_x_spin.setRange(lo, hi); self.fov_deg_x_spin.setValue(4.0); self.fov_deg_x_spin.hide()
        fov_grid.addWidget(self._label("FOV X"), 1, 0)
        fov_grid.addWidget(self.fov_deg_x_slider, 1, 1)
        fov_grid.addWidget(self.fov_deg_x_label, 1, 2)
        lo, hi = CAMERA_LIMITS["fov_deg_y"]
        self.fov_deg_y_slider, self.fov_deg_y_label, self.fov_deg_y_factor = self._make_float_slider(lo, hi, 3.0, decimals=1, suffix=" deg", tooltip="Vertical FOV degrees")
        self.fov_deg_y_spin = QDoubleSpinBox(); self.fov_deg_y_spin.setRange(lo, hi); self.fov_deg_y_spin.setValue(3.0); self.fov_deg_y_spin.hide()
        fov_grid.addWidget(self._label("Y"), 1, 3)
        fov_grid.addWidget(self.fov_deg_y_slider, 1, 4)
        fov_grid.addWidget(self.fov_deg_y_label, 1, 5)
        layout.addWidget(fov_box)

        # ---- B: Pan-Tilt Mechanics ----
        mech_box, mech_grid = self._make_group("B — Pan-Tilt Mechanics")
        # Pan Min/Max
        self.pan_min_slider, self.pan_min_label = self._make_int_slider(0, MAX_RES, 0, tooltip="Pan minimum (0=auto FOV/2)")
        self.pan_min_spin = self.pan_min_slider
        mech_grid.addWidget(self._label("Pan Min"), 0, 0)
        mech_grid.addWidget(self.pan_min_slider, 0, 1)
        mech_grid.addWidget(self.pan_min_label, 0, 2)
        self.pan_max_slider, self.pan_max_label = self._make_int_slider(0, MAX_RES, 0, tooltip="Pan maximum (0=auto W-FOV/2)")
        self.pan_max_spin = self.pan_max_slider
        mech_grid.addWidget(self._label("Max"), 0, 3)
        mech_grid.addWidget(self.pan_max_slider, 0, 4)
        mech_grid.addWidget(self.pan_max_label, 0, 5)

        self.tilt_min_slider, self.tilt_min_label = self._make_int_slider(0, MAX_RES, 0)
        self.tilt_min_spin = self.tilt_min_slider
        mech_grid.addWidget(self._label("Tilt Min"), 1, 0)
        mech_grid.addWidget(self.tilt_min_slider, 1, 1)
        mech_grid.addWidget(self.tilt_min_label, 1, 2)
        self.tilt_max_slider, self.tilt_max_label = self._make_int_slider(0, MAX_RES, 0)
        self.tilt_max_spin = self.tilt_max_slider
        mech_grid.addWidget(self._label("Max"), 1, 3)
        mech_grid.addWidget(self.tilt_max_slider, 1, 4)
        mech_grid.addWidget(self.tilt_max_label, 1, 5)

        # Home fixed centre (disabled display, but keep sliders disabled)
        self.home_pan_slider, self.home_pan_label = self._make_int_slider(0, MAX_RES, 1000)
        self.home_pan_slider.setEnabled(False)
        self.home_pan_spin = QSpinBox(); self.home_pan_spin.setRange(0, MAX_RES); self.home_pan_spin.setValue(1000); self.home_pan_spin.setEnabled(False); self.home_pan_spin.hide()
        self.home_pan_spin = self.home_pan_slider  # alias after hide handling, keep slider alias
        # Need hidden spin for compat: create separate
        self._home_pan_spin_hidden = QSpinBox(); self._home_pan_spin_hidden.setRange(0, MAX_RES); self._home_pan_spin_hidden.hide()
        self.home_pan_spin = self._home_pan_spin_hidden
        mech_grid.addWidget(self._label("Home Pan"), 2, 0)
        mech_grid.addWidget(self.home_pan_slider, 2, 1)
        mech_grid.addWidget(self.home_pan_label, 2, 2)
        self.home_tilt_slider, self.home_tilt_label = self._make_int_slider(0, MAX_RES, 1000)
        self.home_tilt_slider.setEnabled(False)
        self._home_tilt_spin_hidden = QSpinBox(); self._home_tilt_spin_hidden.setRange(0, MAX_RES); self._home_tilt_spin_hidden.hide()
        self.home_tilt_spin = self._home_tilt_spin_hidden
        mech_grid.addWidget(self._label("Tilt"), 2, 3)
        mech_grid.addWidget(self.home_tilt_slider, 2, 4)
        mech_grid.addWidget(self.home_tilt_label, 2, 5)

        # Pan/Tilt speed deg/s (float 5-10)
        lo, hi = CAMERA_LIMITS["max_pan_speed_deg"]
        self.pan_speed_deg_slider, self.pan_speed_deg_label, self.pan_speed_deg_factor = self._make_float_slider(lo, hi, 8.0, decimals=1, suffix=" deg/s", tooltip="Max pan speed 5-10 deg/s")
        self.pan_speed_deg_spin = QDoubleSpinBox(); self.pan_speed_deg_spin.setRange(lo, hi); self.pan_speed_deg_spin.setValue(8.0); self.pan_speed_deg_spin.hide()
        mech_grid.addWidget(self._label("Pan Speed"), 3, 0)
        mech_grid.addWidget(self.pan_speed_deg_slider, 3, 1)
        mech_grid.addWidget(self.pan_speed_deg_label, 3, 2)
        lo, hi = CAMERA_LIMITS["max_tilt_speed_deg"]
        self.tilt_speed_deg_slider, self.tilt_speed_deg_label, self.tilt_speed_deg_factor = self._make_float_slider(lo, hi, 8.0, decimals=1, suffix=" deg/s", tooltip="Max tilt speed")
        self.tilt_speed_deg_spin = QDoubleSpinBox(); self.tilt_speed_deg_spin.setRange(lo, hi); self.tilt_speed_deg_spin.setValue(8.0); self.tilt_speed_deg_spin.hide()
        mech_grid.addWidget(self._label("Tilt Speed"), 3, 3)
        mech_grid.addWidget(self.tilt_speed_deg_slider, 3, 4)
        mech_grid.addWidget(self.tilt_speed_deg_label, 3, 5)

        # Hidden slew for compat
        self.slew_spin = QSpinBox(); lo, hi = CAMERA_LIMITS["max_slew_rate"]; self.slew_spin.setRange(int(lo), int(hi)); self.slew_spin.setValue(800); self.slew_spin.hide()

        # Resolution float 0.01-5.0
        lo, hi = CAMERA_LIMITS["resolution"]
        self.res_slider, self.res_label, self.res_factor = self._make_float_slider(lo, hi, 0.1, decimals=2, suffix=" px", tooltip="Positional resolution — smallest step")
        self.res_spin = QDoubleSpinBox(); self.res_spin.setRange(lo, hi); self.res_spin.setValue(0.1); self.res_spin.hide()
        mech_grid.addWidget(self._label("Resolution"), 4, 0)
        mech_grid.addWidget(self.res_slider, 4, 1)
        mech_grid.addWidget(self.res_label, 4, 2)
        # Latency int 0-500
        lo, hi = CAMERA_LIMITS["latency_ms"]
        self.latency_slider, self.latency_label = self._make_int_slider(int(lo), int(hi), 12, tooltip="Response latency ms")
        self.latency_spin = self.latency_slider
        mech_grid.addWidget(self._label("Latency"), 4, 3)
        mech_grid.addWidget(self.latency_slider, 4, 4)
        mech_grid.addWidget(self.latency_label, 4, 5)

        # Update rate 20-120
        lo, hi = CAMERA_LIMITS["update_rate_hz"]
        self.update_rate_slider, self.update_rate_label = self._make_int_slider(int(lo), int(hi), 30, tooltip="Camera update rate Hz")
        self.update_rate_spin = self.update_rate_slider
        mech_grid.addWidget(self._label("Update Rate"), 5, 0)
        mech_grid.addWidget(self.update_rate_slider, 5, 1)
        mech_grid.addWidget(self.update_rate_label, 5, 2)
        self.update_rate_lbl = QLabel("30 Hz"); self.update_rate_lbl.hide()
        layout.addWidget(mech_box)

        # ---- C: Display ----
        disp_box, disp_grid = self._make_group("C — Display / Screen Sizes")
        lo, hi = DISPLAY_LIMITS["viewport_width"]
        self.viewport_w_slider, self.viewport_w_label = self._make_int_slider(lo, hi, 2000, tooltip="Camera Screen width 2000-5000")
        self.viewport_w_spin = self.viewport_w_slider
        disp_grid.addWidget(self._label("Camera W"), 0, 0)
        disp_grid.addWidget(self.viewport_w_slider, 0, 1)
        disp_grid.addWidget(self.viewport_w_label, 0, 2)
        lo, hi = DISPLAY_LIMITS["viewport_height"]
        self.viewport_h_slider, self.viewport_h_label = self._make_int_slider(lo, hi, 2000)
        self.viewport_h_spin = self.viewport_h_slider
        disp_grid.addWidget(self._label("H"), 0, 3)
        disp_grid.addWidget(self.viewport_h_slider, 0, 4)
        disp_grid.addWidget(self.viewport_h_label, 0, 5)

        lo, hi = DISPLAY_LIMITS["god_width"]
        self.god_w_slider, self.god_w_label = self._make_int_slider(lo, hi, 2000, tooltip="God View = World size, synced")
        self.god_w_slider.setEnabled(False)
        self._god_w_spin_hidden = QSpinBox(); self._god_w_spin_hidden.setRange(lo, hi); self._god_w_spin_hidden.hide()
        self.god_w_spin = self._god_w_spin_hidden
        disp_grid.addWidget(self._label("God W"), 1, 0)
        disp_grid.addWidget(self.god_w_slider, 1, 1)
        disp_grid.addWidget(self.god_w_label, 1, 2)
        lo, hi = DISPLAY_LIMITS["god_height"]
        self.god_h_slider, self.god_h_label = self._make_int_slider(lo, hi, 2000)
        self.god_h_slider.setEnabled(False)
        self._god_h_spin_hidden = QSpinBox(); self._god_h_spin_hidden.setRange(lo, hi); self._god_h_spin_hidden.hide()
        self.god_h_spin = self._god_h_spin_hidden
        disp_grid.addWidget(self._label("H"), 1, 3)
        disp_grid.addWidget(self.god_h_slider, 1, 4)
        disp_grid.addWidget(self.god_h_label, 1, 5)

        disp_hint = QLabel("God View = World size (2000..5000), Camera Screen 2000..5000 configurable")
        disp_hint.setStyleSheet("color:#6b7280; font-size:10px; font-style:italic;")
        disp_grid.addWidget(disp_hint, 2, 0, 1, 6)
        layout.addWidget(disp_box)

        # ---- D: Units ----
        units_box, units_grid = self._make_group("D — Units / Pixel to Angle")
        lo, hi = CAMERA_LIMITS["pixel_scale_mrad"]
        self.scale_slider, self.scale_label, self.scale_factor = self._make_float_slider(lo, hi, 0.109, decimals=3, suffix=" mrad/px", tooltip="Derived from FOV deg / resolution")
        self.scale_slider.setEnabled(False)
        self.scale_spin = QDoubleSpinBox(); self.scale_spin.setRange(lo, hi); self.scale_spin.setValue(0.109); self.scale_spin.setEnabled(False); self.scale_spin.hide()
        units_grid.addWidget(self._label("Scale"), 0, 0)
        units_grid.addWidget(self.scale_slider, 0, 1)
        units_grid.addWidget(self.scale_label, 0, 2)
        self.scale_hint = QLabel("4.0 deg / 640 px = 0.109 mrad/px")
        self.scale_hint.setStyleSheet("color:#6b7280; font-size:10px; font-style:italic;")
        units_grid.addWidget(self.scale_hint, 0, 3, 1, 3)
        layout.addWidget(units_box)

        # ---- E: Realism ----
        realism_box, realism_grid = self._make_group("E — Realism & Mechanical Errors")
        lo, hi = CAMERA_LIMITS["max_accel_deg"]
        self.accel_slider, self.accel_label, self.accel_factor = self._make_float_slider(lo, hi, 120.0, decimals=1, suffix=" deg/s²", tooltip="Slew acceleration limit")
        self.accel_spin = QDoubleSpinBox(); self.accel_spin.setRange(lo, hi); self.accel_spin.setValue(120.0); self.accel_spin.hide()
        realism_grid.addWidget(self._label("Max Accel"), 0, 0)
        realism_grid.addWidget(self.accel_slider, 0, 1)
        realism_grid.addWidget(self.accel_label, 0, 2)
        lo, hi = CAMERA_LIMITS["backlash_px"]
        self.backlash_slider, self.backlash_label, self.backlash_factor = self._make_float_slider(lo, hi, 0.25, decimals=2, suffix=" px", tooltip="Gear backlash dead band")
        self.backlash_spin = QDoubleSpinBox(); self.backlash_spin.setRange(lo, hi); self.backlash_spin.setValue(0.25); self.backlash_spin.hide()
        realism_grid.addWidget(self._label("Backlash"), 0, 3)
        realism_grid.addWidget(self.backlash_slider, 0, 4)
        realism_grid.addWidget(self.backlash_label, 0, 5)

        lo, hi = CAMERA_LIMITS["encoder_sigma_px"]
        self.encoder_slider, self.encoder_label, self.encoder_factor = self._make_float_slider(lo, hi, 0.04, decimals=3, suffix=" px", tooltip="Encoder noise σ")
        self.encoder_spin = QDoubleSpinBox(); self.encoder_spin.setRange(lo, hi); self.encoder_spin.setValue(0.04); self.encoder_spin.hide()
        realism_grid.addWidget(self._label("Encoder σ"), 1, 0)
        realism_grid.addWidget(self.encoder_slider, 1, 1)
        realism_grid.addWidget(self.encoder_label, 1, 2)
        lo, hi = CAMERA_LIMITS["latency_jitter_ms"]
        self.latency_jitter_slider, self.latency_jitter_label, self.latency_jitter_factor = self._make_float_slider(lo, hi, 1.2, decimals=1, suffix=" ms", tooltip="Latency jitter σ")
        self.latency_jitter_spin = QDoubleSpinBox(); self.latency_jitter_spin.setRange(lo, hi); self.latency_jitter_spin.setValue(1.2); self.latency_jitter_spin.hide()
        realism_grid.addWidget(self._label("Latency Jitter"), 1, 3)
        realism_grid.addWidget(self.latency_jitter_slider, 1, 4)
        realism_grid.addWidget(self.latency_jitter_label, 1, 5)

        realism_hint = QLabel("Realism adds accel-limited slew, reversal backlash, encoder noise, and stochastic latency.")
        realism_hint.setWordWrap(True)
        realism_hint.setStyleSheet("color:#64748b; font-size:10px; font-style:italic;")
        realism_grid.addWidget(realism_hint, 2, 0, 1, 7)
        layout.addWidget(realism_box)

        # Hidden gain (moved to Control)
        gain_box = QGroupBox("E — Controller Gain (MOVED to Control tab)")
        gain_layout = QVBoxLayout(gain_box)
        gain_layout.setContentsMargins(10, 14, 10, 10)
        gain_layout.setSpacing(6)
        self._add_gain_row(gain_layout)
        gain_box.hide()
        layout.addWidget(gain_box)
        moved_hint = QLabel("Gain is now in Control → Gains / Kp. This box is hidden.")
        moved_hint.setStyleSheet("color:#6b7280; font-size:9px; font-style:italic;")
        moved_hint.setWordWrap(True)
        moved_hint.hide()
        layout.addWidget(moved_hint)

        # Reset button
        self.btn_reset = self._make_reset_button("Reset Camera")
        layout.addWidget(self.btn_reset)

        layout.addStretch()
        self._wire_signals()

    def _add_gain_row(self, layout: QVBoxLayout) -> None:
        lab = QLabel("Controller gain")
        lab.setStyleSheet("color:#374151; font-weight:500;")
        layout.addWidget(lab)
        row = QHBoxLayout(); row.setSpacing(8)
        self.gain_slider = QSlider(Qt.Horizontal); self.gain_slider.setRange(2, 50); self.gain_slider.setValue(15); self.gain_slider.setMinimumHeight(18)
        self.gain_spin = QDoubleSpinBox(); self.gain_spin.setRange(0.02, 0.50); self.gain_spin.setSingleStep(0.01); self.gain_spin.setValue(0.15); self.gain_spin.setDecimals(2); self.gain_spin.setMinimumHeight(26); self.gain_spin.setFixedWidth(78)
        row.addWidget(self.gain_slider, 1); row.addWidget(self.gain_spin)
        layout.addLayout(row)
        self.gain_spin.valueChanged.connect(self._on_gain_spin)
        self.gain_slider.valueChanged.connect(self._on_gain_slider)

    def _on_gain_spin(self, value: float) -> None:
        iv = int(round(value * 100))
        if self.gain_slider.value() != iv:
            self.gain_slider.blockSignals(True); self.gain_slider.setValue(iv); self.gain_slider.blockSignals(False)
        self.configChanged.emit()

    def _on_gain_slider(self, value: int) -> None:
        f = value / 100.0
        if abs(self.gain_spin.value() - f) > 1e-9:
            self.gain_spin.blockSignals(True); self.gain_spin.setValue(f); self.gain_spin.blockSignals(False)
        self.configChanged.emit()

    def _label(self, text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setStyleSheet("color:#374151; font-size:11px; font-weight:500;")
        return lbl

    # Wiring
    def _wire_all(self):
        # Int sliders emit directly
        for w in [self.fov_w_slider, self.fov_h_slider, self.pan_min_slider, self.pan_max_slider, self.tilt_min_slider, self.tilt_max_slider,
                  self.viewport_w_slider, self.viewport_h_slider, self.latency_slider, self.update_rate_slider]:
            w.valueChanged.connect(lambda _: self.configChanged.emit())
        # Float sliders sync to hidden spins and emit
        self.fov_deg_x_slider.valueChanged.connect(lambda v: self._sync_float_slider(v, self.fov_deg_x_spin, self.fov_deg_x_factor))
        self.fov_deg_y_slider.valueChanged.connect(lambda v: self._sync_float_slider(v, self.fov_deg_y_spin, self.fov_deg_y_factor))
        self.pan_speed_deg_slider.valueChanged.connect(lambda v: self._sync_float_slider(v, self.pan_speed_deg_spin, self.pan_speed_deg_factor))
        self.tilt_speed_deg_slider.valueChanged.connect(lambda v: self._sync_float_slider(v, self.tilt_speed_deg_spin, self.tilt_speed_deg_factor))
        self.res_slider.valueChanged.connect(lambda v: self._sync_float_slider(v, self.res_spin, self.res_factor))
        self.accel_slider.valueChanged.connect(lambda v: self._sync_float_slider(v, self.accel_spin, self.accel_factor))
        self.backlash_slider.valueChanged.connect(lambda v: self._sync_float_slider(v, self.backlash_spin, self.backlash_factor))
        self.encoder_slider.valueChanged.connect(lambda v: self._sync_float_slider(v, self.encoder_spin, self.encoder_factor))
        self.latency_jitter_slider.valueChanged.connect(lambda v: self._sync_float_slider(v, self.latency_jitter_spin, self.latency_jitter_factor))
        # FOV deg also updates scale
        for w in [self.fov_deg_x_slider, self.fov_deg_y_slider, self.fov_w_slider]:
            w.valueChanged.connect(self._update_scale_from_fov)
        self.gain_slider.valueChanged.connect(lambda _: self.configChanged.emit())
        self.btn_reset.clicked.connect(self._on_reset)

    def _sync_float_slider(self, int_val: int, spin: QDoubleSpinBox, factor: int):
        val = int_val / factor
        spin.blockSignals(True)
        spin.setValue(float(val))
        spin.blockSignals(False)
        self.configChanged.emit()

    def _update_scale_from_fov(self, _=None) -> None:
        try:
            deg = float(self.fov_deg_x_slider.value() / self.fov_deg_x_factor)
            res = int(self.fov_w_slider.value())
            mrad = (deg * 17.453292519943295) / max(1, res)
            # Update disabled scale slider/label
            self.scale_slider.blockSignals(True)
            self.scale_slider.setValue(int(round(mrad * self.scale_factor)))
            self.scale_slider.blockSignals(False)
            self.scale_label.setText(f"{mrad:.3f} mrad/px")
            self.scale_spin.blockSignals(True)
            self.scale_spin.setValue(float(mrad))
            self.scale_spin.blockSignals(False)
            urad = mrad * 1000
            self.scale_hint.setText(f"{deg:.1f} deg / {res} px = {mrad:.3f} mrad/px ({urad:.0f} urad/px)")
        except Exception:
            pass
        self.configChanged.emit()

    def _on_scale_changed(self, v: float) -> None:
        urad = v * 1000
        self.scale_hint.setText(f"{v:.3f} mrad/px — 10 px = {v*10:.3f} mrad = {urad*10:.0f} urad")
        self.configChanged.emit()

    def _on_reset(self):
        self.set_config(CameraConfig().validate(self._scene_bounds), emit=True)

    def _wire_signals(self):
        self._wire_all()

    # Config <-> UI
    def collect_config(self) -> CameraConfig:
        pan_min = int(self.pan_min_slider.value()) if self.pan_min_slider.value() != 0 else None
        pan_max = int(self.pan_max_slider.value()) if self.pan_max_slider.value() != 0 else None
        tilt_min = int(self.tilt_min_slider.value()) if self.tilt_min_slider.value() != 0 else None
        tilt_max = int(self.tilt_max_slider.value()) if self.tilt_max_slider.value() != 0 else None
        home_pan = None
        home_tilt = None
        try:
            deg = float(self.fov_deg_x_slider.value() / self.fov_deg_x_factor)
            res = int(self.fov_w_slider.value())
            pixel_scale = (deg * 17.453292519943295) / max(1, res)
        except Exception:
            pixel_scale = float(self.scale_spin.value())
        try:
            pan_deg = float(self.pan_speed_deg_slider.value() / self.pan_speed_deg_factor)
            tilt_deg = float(self.tilt_speed_deg_slider.value() / self.tilt_speed_deg_factor)
            px_per_deg = 17.453292519943295 / max(1e-6, pixel_scale)
            max_slew = max(pan_deg * px_per_deg, tilt_deg * px_per_deg)
        except Exception:
            max_slew = 800.0
        return CameraConfig(
            fov_width=int(self.fov_w_slider.value()),
            fov_height=int(self.fov_h_slider.value()),
            fov_deg_x=float(self.fov_deg_x_slider.value() / self.fov_deg_x_factor),
            fov_deg_y=float(self.fov_deg_y_slider.value() / self.fov_deg_y_factor),
            pan_min=pan_min, pan_max=pan_max,
            tilt_min=tilt_min, tilt_max=tilt_max,
            home_pan=home_pan, home_tilt=home_tilt,
            max_pan_speed_deg=float(self.pan_speed_deg_slider.value() / self.pan_speed_deg_factor),
            max_tilt_speed_deg=float(self.tilt_speed_deg_slider.value() / self.tilt_speed_deg_factor),
            max_slew_rate=float(max_slew),
            resolution=float(self.res_slider.value() / self.res_factor),
            latency_ms=int(self.latency_slider.value()),
            viewport_width=int(self.viewport_w_slider.value()),
            viewport_height=int(self.viewport_h_slider.value()),
            god_width=int(self.god_w_slider.value()) if self.god_w_slider.isEnabled() else int(self._god_w_spin_hidden.value()),
            god_height=int(self.god_h_slider.value()) if self.god_h_slider.isEnabled() else int(self._god_h_spin_hidden.value()),
            pixel_scale_mrad=float(pixel_scale),
            update_rate_hz=int(self.update_rate_slider.value()),
            max_accel_deg=float(self.accel_slider.value() / self.accel_factor),
            backlash_px=float(self.backlash_slider.value() / self.backlash_factor),
            encoder_sigma_px=float(self.encoder_slider.value() / self.encoder_factor),
            latency_jitter_ms=float(self.latency_jitter_slider.value() / self.latency_jitter_factor),
        ).validate(self._scene_bounds)

    def set_config(self, cfg: CameraConfig, emit: bool = False) -> None:
        cfg = cfg.validate(self._scene_bounds)
        # Block signals
        sliders_int = [self.fov_w_slider, self.fov_h_slider, self.pan_min_slider, self.pan_max_slider, self.tilt_min_slider, self.tilt_max_slider,
                       self.viewport_w_slider, self.viewport_h_slider, self.latency_slider, self.update_rate_slider]
        sliders_float = [self.fov_deg_x_slider, self.fov_deg_y_slider, self.pan_speed_deg_slider, self.tilt_speed_deg_slider,
                         self.res_slider, self.accel_slider, self.backlash_slider, self.encoder_slider, self.latency_jitter_slider, self.scale_slider]
        for w in sliders_int + sliders_float:
            w.blockSignals(True)
        for spin in [self.fov_deg_x_spin, self.fov_deg_y_spin, self.pan_speed_deg_spin, self.tilt_speed_deg_spin, self.res_spin,
                     self.scale_spin, self.accel_spin, self.backlash_spin, self.encoder_spin, self.latency_jitter_spin]:
            spin.blockSignals(True)
        try:
            self.fov_w_slider.setValue(int(cfg.fov_width)); self.fov_h_slider.setValue(int(cfg.fov_height))
            self.fov_w_label.setText(str(int(cfg.fov_width))); self.fov_h_label.setText(str(int(cfg.fov_height)))
            self.fov_deg_x_slider.setValue(int(round(float(getattr(cfg, 'fov_deg_x', 4.0)) * self.fov_deg_x_factor)))
            self.fov_deg_y_slider.setValue(int(round(float(getattr(cfg, 'fov_deg_y', 3.0)) * self.fov_deg_y_factor)))
            self.fov_deg_x_spin.setValue(float(getattr(cfg, 'fov_deg_x', 4.0))); self.fov_deg_y_spin.setValue(float(getattr(cfg, 'fov_deg_y', 3.0)))
            self.fov_deg_x_label.setText(f"{float(getattr(cfg, 'fov_deg_x', 4.0)):.1f} deg"); self.fov_deg_y_label.setText(f"{float(getattr(cfg, 'fov_deg_y', 3.0)):.1f} deg")
            self.pan_min_slider.setValue(int(cfg.pan_min) if cfg.pan_min is not None else 0)
            self.pan_max_slider.setValue(int(cfg.pan_max) if cfg.pan_max is not None else 0)
            self.tilt_min_slider.setValue(int(cfg.tilt_min) if cfg.tilt_min is not None else 0)
            self.tilt_max_slider.setValue(int(cfg.tilt_max) if cfg.tilt_max is not None else 0)
            sw, sh = self._scene_bounds
            self.home_pan_slider.setValue(int(sw/2)); self.home_tilt_slider.setValue(int(sh/2))
            self._home_pan_spin_hidden.setValue(int(sw/2)); self._home_tilt_spin_hidden.setValue(int(sh/2))
            self.home_pan_label.setText(str(int(sw/2))); self.home_tilt_label.setText(str(int(sh/2)))
            self.pan_speed_deg_slider.setValue(int(round(float(getattr(cfg, 'max_pan_speed_deg', 5.0)) * self.pan_speed_deg_factor)))
            self.tilt_speed_deg_slider.setValue(int(round(float(getattr(cfg, 'max_tilt_speed_deg', 5.0)) * self.tilt_speed_deg_factor)))
            self.pan_speed_deg_spin.setValue(float(getattr(cfg, 'max_pan_speed_deg', 5.0))); self.tilt_speed_deg_spin.setValue(float(getattr(cfg, 'max_tilt_speed_deg', 5.0)))
            self.pan_speed_deg_label.setText(f"{float(getattr(cfg, 'max_pan_speed_deg', 5.0)):.1f} deg/s"); self.tilt_speed_deg_label.setText(f"{float(getattr(cfg, 'max_tilt_speed_deg', 5.0)):.1f} deg/s")
            self.slew_spin.setValue(int(cfg.max_slew_rate))
            self.res_slider.setValue(int(round(float(cfg.resolution) * self.res_factor))); self.res_spin.setValue(float(cfg.resolution))
            self.res_label.setText(f"{float(cfg.resolution):.2f} px")
            self.latency_slider.setValue(int(cfg.latency_ms)); self.latency_label.setText(f"{int(cfg.latency_ms)} ms")
            self.update_rate_slider.setValue(int(getattr(cfg, 'update_rate_hz', 30))); self.update_rate_label.setText(f"{int(getattr(cfg, 'update_rate_hz', 30))} Hz")
            self.viewport_w_slider.setValue(int(cfg.viewport_width)); self.viewport_h_slider.setValue(int(cfg.viewport_height))
            self.viewport_w_label.setText(str(int(cfg.viewport_width))); self.viewport_h_label.setText(str(int(cfg.viewport_height)))
            self.god_w_slider.setValue(int(cfg.god_width)); self.god_h_slider.setValue(int(cfg.god_height))
            self._god_w_spin_hidden.setValue(int(cfg.god_width)); self._god_h_spin_hidden.setValue(int(cfg.god_height))
            self.god_w_label.setText(str(int(cfg.god_width))); self.god_h_label.setText(str(int(cfg.god_height)))
            self.scale_slider.setValue(int(round(float(cfg.pixel_scale_mrad) * self.scale_factor))); self.scale_spin.setValue(float(cfg.pixel_scale_mrad))
            self.scale_label.setText(f"{float(cfg.pixel_scale_mrad):.3f} mrad/px")
            self.accel_slider.setValue(int(round(float(getattr(cfg, 'max_accel_deg', 120.0)) * self.accel_factor))); self.accel_spin.setValue(float(getattr(cfg, 'max_accel_deg', 120.0)))
            self.accel_label.setText(f"{float(getattr(cfg, 'max_accel_deg', 120.0)):.1f} deg/s²")
            self.backlash_slider.setValue(int(round(float(getattr(cfg, 'backlash_px', 0.25)) * self.backlash_factor))); self.backlash_spin.setValue(float(getattr(cfg, 'backlash_px', 0.25)))
            self.backlash_label.setText(f"{float(getattr(cfg, 'backlash_px', 0.25)):.2f} px")
            self.encoder_slider.setValue(int(round(float(getattr(cfg, 'encoder_sigma_px', 0.04)) * self.encoder_factor))); self.encoder_spin.setValue(float(getattr(cfg, 'encoder_sigma_px', 0.04)))
            self.encoder_label.setText(f"{float(getattr(cfg, 'encoder_sigma_px', 0.04)):.3f} px")
            self.latency_jitter_slider.setValue(int(round(float(getattr(cfg, 'latency_jitter_ms', 1.2)) * self.latency_jitter_factor))); self.latency_jitter_spin.setValue(float(getattr(cfg, 'latency_jitter_ms', 1.2)))
            self.latency_jitter_label.setText(f"{float(getattr(cfg, 'latency_jitter_ms', 1.2)):.1f} ms")
            self._update_scale_from_fov()
        finally:
            for w in sliders_int + sliders_float:
                w.blockSignals(False)
            for spin in [self.fov_deg_x_spin, self.fov_deg_y_spin, self.pan_speed_deg_spin, self.tilt_speed_deg_spin, self.res_spin,
                         self.scale_spin, self.accel_spin, self.backlash_spin, self.encoder_spin, self.latency_jitter_spin]:
                spin.blockSignals(False)
            self.gain_spin.blockSignals(False); self.gain_slider.blockSignals(False)
        if emit:
            self.configChanged.emit()

    def set_scene_bounds(self, bounds: tuple[int, int]) -> None:
        self._scene_bounds = bounds
        try:
            w, h = bounds
            self.god_w_slider.blockSignals(True); self.god_h_slider.blockSignals(True)
            self.god_w_slider.setValue(int(w)); self.god_h_slider.setValue(int(h))
            self.god_w_label.setText(str(int(w))); self.god_h_label.setText(str(int(h)))
            self._god_w_spin_hidden.setValue(int(w)); self._god_h_spin_hidden.setValue(int(h))
            self.home_pan_slider.setValue(int(w//2)); self.home_tilt_slider.setValue(int(h//2))
            self.home_pan_label.setText(str(int(w//2))); self.home_tilt_label.setText(str(int(h//2)))
            self._home_pan_spin_hidden.setValue(int(w//2)); self._home_tilt_spin_hidden.setValue(int(h//2))
        except Exception:
            pass
        finally:
            try:
                self.god_w_slider.blockSignals(False); self.god_h_slider.blockSignals(False)
            except Exception:
                pass

    def showEvent(self, e):
        super().showEvent(e)
        try:
            self._wire_signals()
        except Exception:
            pass

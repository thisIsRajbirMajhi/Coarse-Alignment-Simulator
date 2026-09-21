# gui/panels/camera_panel.py - Camera & PTZ Mechanism Control Deck panel (Redesign).
# Primary = PDF-mandated (FOV + slew rate + presets). Advanced = tuning/debug (collapsible).
from __future__ import annotations

import logging
from typing import Any

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
    QSlider,
)

from camera.config import CameraConfig
from camera.constants import CAMERA_DEFAULTS, CAMERA_LIMITS, CAMERA_PRESETS
from gui.panels.base import BaseConfigPanel

log = logging.getLogger(__name__)


class CameraPanel(BaseConfigPanel):
    """
    Configuration panel for virtual Camera Optics and PTZ Gimbal.
    Primary (always visible): FOV, linked slew rate, presets, 640×480 badge.
    Advanced (collapsed by default): accel, travel limits, damping/backlash/noise,
                                     measured-feedback, home/start/scan-start, update-rate.
    All 19 legacy sliders/attrs are retained (hidden) for backward compat & tests.
    """

    configChanged = pyqtSignal(object)

    def __init__(self, parent=None, initial: CameraConfig | None = None):
        super().__init__(parent)
        self._initial = (initial or CameraConfig()).validate()
        self._updating_link = False
        self._build_ui()
        self.set_config(self._initial, emit=False)

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(10)

        # Header Row
        header_row = QHBoxLayout()
        header_row.setSpacing(8)
        title = QLabel("CAMERA & PTZ GIMBAL")
        title.setStyleSheet("font-size:15px; font-weight:700; color:#111827;")
        header_row.addWidget(title)
        header_row.addStretch(1)

        preset_lbl = QLabel("Preset:")
        preset_lbl.setStyleSheet("font-size:11px; font-weight:600; color:#4b5563;")
        header_row.addWidget(preset_lbl)
        self.combo_presets = QComboBox()
        self.combo_presets.setMinimumHeight(28)
        self.combo_presets.addItem("Custom...")
        for name in CAMERA_PRESETS.keys():
            self.combo_presets.addItem(name)
        self.combo_presets.currentTextChanged.connect(self._on_preset_selected)
        header_row.addWidget(self.combo_presets)

        self.btn_reset = self._make_reset_button("Reset Camera")
        self.btn_reset.clicked.connect(self.reset_to_defaults)
        header_row.addWidget(self.btn_reset)
        root.addLayout(header_row)

        desc = QLabel("Primary: optics & slew rate  ·  Advanced: dynamics & test knobs")
        desc.setStyleSheet("color:#64748b; font-size:11px;")
        root.addWidget(desc)

        # ========== PRIMARY: OPTICS ==========
        optics_box, optics_grid = self._make_group("OPTICS — Primary")
        self.slider_fov_h, self.lbl_fov_h, self.factor_fov_h = self._make_float_slider(
            0.5, 30.0, 4.0, decimals=1, suffix="°", tooltip="Horizontal FOV (PDF default 4.0°)"
        )
        optics_grid.addWidget(self._label("Horizontal FOV"), 0, 0)
        optics_grid.addWidget(self.slider_fov_h, 0, 1)
        optics_grid.addWidget(self.lbl_fov_h, 0, 2)

        self.slider_fov_v, self.lbl_fov_v, self.factor_fov_v = self._make_float_slider(
            0.5, 30.0, 3.0, decimals=1, suffix="°", tooltip="Vertical FOV (PDF default 3.0°)"
        )
        optics_grid.addWidget(self._label("Vertical FOV"), 1, 0)
        optics_grid.addWidget(self.slider_fov_v, 1, 1)
        optics_grid.addWidget(self.lbl_fov_v, 1, 2)

        # Link toggle keeps 4:3 aspect unless expert unlinks.
        self.chk_fov_link = QCheckBox("🔗 4:3")
        self.chk_fov_link.setChecked(True)
        self.chk_fov_link.setToolTip("Link H/V to 4:3 aspect (uncheck for independent)")
        self.chk_fov_link.setStyleSheet("color:#374151; font-size:11px;")
        optics_grid.addWidget(self.chk_fov_link, 2, 0, 1, 1)
        res_label = QLabel("640 × 480 px  ·  Monochrome  ·  30 Hz (fixed)")
        res_label.setStyleSheet("color:#111827; font-weight:700; font-size:11px; padding:2px;")
        optics_grid.addWidget(res_label, 2, 1, 1, 2)

        # Keep update-rate slider for back-compat but HIDE it from Primary;
        # it lives in Advanced. Create it here so attribute exists for tests.
        self.slider_rate, self.lbl_rate = self._make_int_slider(
            10, 120, 30, tooltip="Camera update rate (fixed 30Hz in Primary)"
        )
        # not added to optics_grid — will be added to advanced
        root.addWidget(optics_box)

        # ========== PRIMARY: GIMBAL ==========
        gimbal_box, gimbal_grid = self._make_group("GIMBAL — Primary")
        # Single linked slew rate (drives both pan/tilt); Advanced allows split.
        self.slider_slew, self.lbl_slew, self.factor_slew = self._make_float_slider(
            0.5, 30.0, 5.0, decimals=1, suffix=" °/s", tooltip="Slew rate (pan + tilt, PDF 5-10°/s)"
        )
        self.chk_slew_link = QCheckBox("🔗 Pan/Tilt")
        self.chk_slew_link.setChecked(True)
        self.chk_slew_link.setToolTip("Link pan & tilt max speeds (uncheck to tune separately in Advanced)")
        self.chk_slew_link.setStyleSheet("color:#374151; font-size:11px;")
        gimbal_grid.addWidget(self._label("Slew Rate"), 0, 0)
        gimbal_grid.addWidget(self.slider_slew, 0, 1)
        gimbal_grid.addWidget(self.lbl_slew, 0, 2)
        gimbal_grid.addWidget(self.chk_slew_link, 1, 0, 1, 3)

        # Keep legacy pan/tilt sliders for back-compat — hide in Advanced later
        self.slider_pan_speed, self.lbl_pan_speed, self.factor_pan_speed = self._make_float_slider(
            0.5, 30.0, 5.0, decimals=1, suffix=" °/s", tooltip="Max pan rate"
        )
        self.slider_tilt_speed, self.lbl_tilt_speed, self.factor_tilt_speed = self._make_float_slider(
            0.5, 30.0, 5.0, decimals=1, suffix=" °/s", tooltip="Max tilt rate"
        )
        self.slider_pan_accel, self.lbl_pan_accel, self.factor_pan_accel = self._make_float_slider(
            1.0, 100.0, 25.0, decimals=0, suffix=" °/s²", tooltip="Max pan accel"
        )
        self.slider_tilt_accel, self.lbl_tilt_accel, self.factor_tilt_accel = self._make_float_slider(
            1.0, 100.0, 25.0, decimals=0, suffix=" °/s²", tooltip="Max tilt accel"
        )
        self.slider_pan_range, self.lbl_pan_range = self._make_int_slider(10, 180, 90)
        self.slider_tilt_range, self.lbl_tilt_range = self._make_int_slider(5, 90, 45)
        root.addWidget(gimbal_box)

        # ========== ADVANCED (collapsed) ==========
        self.chk_advanced = QCheckBox("Show advanced tuning & test knobs")
        self.chk_advanced.setStyleSheet("color:#4b5563; font-size:11px; font-weight:600;")
        root.addWidget(self.chk_advanced)

        self.advanced_widget = QWidget()
        adv = QVBoxLayout(self.advanced_widget)
        adv.setContentsMargins(0, 0, 0, 0)
        adv.setSpacing(10)

        # Accel + Limits (Advanced)
        kin_box, kin_grid = self._make_group("GIMBAL — Advanced (accel & travel)")
        kin_grid.addWidget(self._label("Max Pan Speed"), 0, 0)
        kin_grid.addWidget(self.slider_pan_speed, 0, 1)
        kin_grid.addWidget(self.lbl_pan_speed, 0, 2)
        kin_grid.addWidget(self._label("Max Tilt Speed"), 1, 0)
        kin_grid.addWidget(self.slider_tilt_speed, 1, 1)
        kin_grid.addWidget(self.lbl_tilt_speed, 1, 2)
        kin_grid.addWidget(self._label("Max Pan Accel"), 2, 0)
        kin_grid.addWidget(self.slider_pan_accel, 2, 1)
        kin_grid.addWidget(self.lbl_pan_accel, 2, 2)
        kin_grid.addWidget(self._label("Max Tilt Accel"), 3, 0)
        kin_grid.addWidget(self.slider_tilt_accel, 3, 1)
        kin_grid.addWidget(self.lbl_tilt_accel, 3, 2)
        kin_grid.addWidget(self._label("Pan Range (±)"), 4, 0)
        kin_grid.addWidget(self.slider_pan_range, 4, 1)
        kin_grid.addWidget(self.lbl_pan_range, 4, 2)
        kin_grid.addWidget(self._label("Tilt Range (±)"), 5, 0)
        kin_grid.addWidget(self.slider_tilt_range, 5, 1)
        kin_grid.addWidget(self.lbl_tilt_range, 5, 2)
        kin_grid.addWidget(self._label("Update Rate"), 6, 0)
        kin_grid.addWidget(self.slider_rate, 6, 1)
        kin_grid.addWidget(self.lbl_rate, 6, 2)
        kin_grid.addWidget(self._hint("Update rate is 30Hz fixed — change only for stress testing."), 7, 0, 1, 3)
        adv.addWidget(kin_box)

        # Mechanical
        mech_box, mech_grid = self._make_group("MECHANICS — Advanced")
        self.slider_backlash, self.lbl_backlash, self.factor_backlash = self._make_float_slider(
            0.0, 0.1, 0.005, decimals=3, suffix="°", tooltip="Backlash"
        )
        mech_grid.addWidget(self._label("Gear Backlash"), 0, 0)
        mech_grid.addWidget(self.slider_backlash, 0, 1)
        mech_grid.addWidget(self.lbl_backlash, 0, 2)
        self.slider_damping, self.lbl_damping, self.factor_damping = self._make_float_slider(
            0.1, 2.0, 0.71, decimals=2, suffix="", tooltip="Damping ratio"
        )
        mech_grid.addWidget(self._label("Damping Ratio"), 1, 0)
        mech_grid.addWidget(self.slider_damping, 1, 1)
        mech_grid.addWidget(self.lbl_damping, 1, 2)
        self.slider_noise, self.lbl_noise, self.factor_noise = self._make_float_slider(
            0.0, 0.02, 0.001, decimals=4, suffix="°", tooltip="Encoder noise"
        )
        mech_grid.addWidget(self._label("Encoder Noise"), 2, 0)
        mech_grid.addWidget(self.slider_noise, 2, 1)
        mech_grid.addWidget(self.lbl_noise, 2, 2)
        self.chk_measured_feedback = QCheckBox("Measured feedback")
        self.chk_measured_feedback.setToolTip("Disturb encoder-measured pose instead of truth")
        self.chk_measured_feedback.setStyleSheet("color:#374151; font-size:11px;")
        mech_grid.addWidget(self.chk_measured_feedback, 3, 0, 1, 3)
        adv.addWidget(mech_box)

        # Starting Positions (Advanced — test harness)
        start_box, start_grid = self._make_group("STARTING POSITIONS — Advanced (test harness)")
        self.slider_home_pan, self.lbl_home_pan, self.factor_home_pan = self._make_float_slider(
            -180.0, 180.0, 0.0, decimals=1, suffix="°", tooltip="Home pan"
        )
        start_grid.addWidget(self._label("Home Pan"), 0, 0)
        start_grid.addWidget(self.slider_home_pan, 0, 1)
        start_grid.addWidget(self.lbl_home_pan, 0, 2)
        self.slider_home_tilt, self.lbl_home_tilt, self.factor_home_tilt = self._make_float_slider(
            -90.0, 90.0, 0.0, decimals=1, suffix="°", tooltip="Home tilt"
        )
        start_grid.addWidget(self._label("Home Tilt"), 1, 0)
        start_grid.addWidget(self.slider_home_tilt, 1, 1)
        start_grid.addWidget(self.lbl_home_tilt, 1, 2)
        self.slider_start_pan, self.lbl_start_pan, self.factor_start_pan = self._make_float_slider(
            -180.0, 180.0, 0.0, decimals=1, suffix="°", tooltip="Start pan"
        )
        start_grid.addWidget(self._label("Start Pan"), 2, 0)
        start_grid.addWidget(self.slider_start_pan, 2, 1)
        start_grid.addWidget(self.lbl_start_pan, 2, 2)
        self.slider_start_tilt, self.lbl_start_tilt, self.factor_start_tilt = self._make_float_slider(
            -90.0, 90.0, 0.0, decimals=1, suffix="°", tooltip="Start tilt"
        )
        start_grid.addWidget(self._label("Start Tilt"), 3, 0)
        start_grid.addWidget(self.slider_start_tilt, 3, 1)
        start_grid.addWidget(self.lbl_start_tilt, 3, 2)
        self.chk_custom_start = QCheckBox("Use custom start pose on init/reset")
        self.chk_custom_start.setStyleSheet("color:#374151; font-size:11px;")
        start_grid.addWidget(self.chk_custom_start, 4, 0, 1, 3)
        self.slider_scan_start, self.lbl_scan_start = self._make_int_slider(0, 19, 0)
        start_grid.addWidget(self._label("Scan Start Cell"), 5, 0)
        start_grid.addWidget(self.slider_scan_start, 5, 1)
        start_grid.addWidget(self.lbl_scan_start, 5, 2)
        start_grid.addWidget(
            self._hint("Scan start is also in Local Terminal → Search. Camera copy kept for back-compat."),
            6, 0, 1, 3,
        )
        adv.addWidget(start_box)

        self.advanced_widget.setVisible(False)
        root.addWidget(self.advanced_widget)
        self.chk_advanced.toggled.connect(self.advanced_widget.setVisible)

        root.addStretch(1)

        # Connect signals — primary + advanced
        primary_sliders = [self.slider_fov_h, self.slider_fov_v, self.slider_slew]
        advanced_sliders = [
            self.slider_rate, self.slider_pan_speed, self.slider_tilt_speed,
            self.slider_pan_accel, self.slider_tilt_accel,
            self.slider_pan_range, self.slider_tilt_range,
            self.slider_backlash, self.slider_damping, self.slider_noise,
            self.slider_home_pan, self.slider_home_tilt,
            self.slider_start_pan, self.slider_start_tilt,
            self.slider_scan_start,
        ]
        for s in primary_sliders + advanced_sliders:
            s.valueChanged.connect(self._on_control_changed)
            s.sliderReleased.connect(self._on_control_changed)
        self.chk_measured_feedback.toggled.connect(self._on_control_changed)
        self.chk_custom_start.toggled.connect(self._on_control_changed)
        self.chk_fov_link.toggled.connect(self._on_control_changed)
        self.chk_slew_link.toggled.connect(self._on_slew_link_toggled)
        # Link behaviours
        self.slider_fov_h.valueChanged.connect(self._on_fov_h_changed)
        self.slider_fov_v.valueChanged.connect(self._on_fov_v_changed)
        self.slider_slew.valueChanged.connect(self._on_slew_changed)
        self.slider_pan_speed.valueChanged.connect(self._on_pan_speed_changed)
        self.slider_tilt_speed.valueChanged.connect(self._on_tilt_speed_changed)

    # --- link handlers ---
    def _on_fov_h_changed(self, v: int):
        if self._updating_link or not self.chk_fov_link.isChecked():
            return
        # keep 4:3: v_v = v_h * 3/4  (factor same 10)
        try:
            v_h = float(v) / self.factor_fov_h
            target_v = int(round(v_h * 0.75 * self.factor_fov_v))
            self._updating_link = True
            self.slider_fov_v.setValue(target_v)
        finally:
            self._updating_link = False

    def _on_fov_v_changed(self, v: int):
        if self._updating_link or not self.chk_fov_link.isChecked():
            return
        try:
            v_v = float(v) / self.factor_fov_v
            target_h = int(round(v_v * (4.0/3.0) * self.factor_fov_h))
            self._updating_link = True
            self.slider_fov_h.setValue(target_h)
        finally:
            self._updating_link = False

    def _on_slew_changed(self, v: int):
        if self._updating_link or not self.chk_slew_link.isChecked():
            return
        try:
            self._updating_link = True
            self.slider_pan_speed.setValue(int(round(float(v) / self.factor_slew * self.factor_pan_speed)))
            self.slider_tilt_speed.setValue(int(round(float(v) / self.factor_slew * self.factor_tilt_speed)))
        finally:
            self._updating_link = False

    def _on_pan_speed_changed(self, v: int):
        if self._updating_link:
            return
        if self.chk_slew_link.isChecked():
            try:
                self._updating_link = True
                # mirror pan to slew + tilt
                self.slider_slew.setValue(int(round(float(v) / self.factor_pan_speed * self.factor_slew)))
                self.slider_tilt_speed.setValue(v)
            finally:
                self._updating_link = False

    def _on_tilt_speed_changed(self, v: int):
        if self._updating_link:
            return
        if self.chk_slew_link.isChecked():
            try:
                self._updating_link = True
                self.slider_slew.setValue(int(round(float(v) / self.factor_tilt_speed * self.factor_slew)))
                self.slider_pan_speed.setValue(v)
            finally:
                self._updating_link = False

    def _on_slew_link_toggled(self, checked: bool):
        if checked:
            # snap to pan value
            self._on_slew_changed(self.slider_slew.value())
        self._on_control_changed()

    def _on_control_changed(self) -> None:
        try:
            sender = self.sender()
            from PyQt5.QtWidgets import QSlider as _QSlider
            if isinstance(sender, _QSlider) and sender.isSliderDown():
                return
        except Exception:
            pass
        cfg = self.collect_config()
        self.configChanged.emit(cfg)

    def _on_preset_selected(self, name: str) -> None:
        if name in CAMERA_PRESETS:
            preset = CAMERA_PRESETS[name]
            try:
                current = self.collect_config()
            except Exception:
                current = None
            kwargs = dict(preset)
            if current is not None:
                for k in ("home_pan_deg", "home_tilt_deg",
                          "start_pan_deg", "start_tilt_deg", "use_custom_start",
                          "scan_start_index", "use_measured_feedback"):
                    kwargs[k] = getattr(current, k)
            cfg = CameraConfig(**kwargs).validate()
            self.set_config(cfg, emit=True)

    def collect_config(self) -> CameraConfig:
        pan_r = float(self.slider_pan_range.value())
        tilt_r = float(self.slider_tilt_range.value())
        # Primary slew drives pan/tilt when linked; otherwise use individual
        if self.chk_slew_link.isChecked():
            slew = float(self.slider_slew.value()) / self.factor_slew
            pan_speed = slew
            tilt_speed = slew
        else:
            pan_speed = float(self.slider_pan_speed.value()) / self.factor_pan_speed
            tilt_speed = float(self.slider_tilt_speed.value()) / self.factor_tilt_speed
        cfg = CameraConfig(
            fov_deg_h=float(self.slider_fov_h.value()) / self.factor_fov_h,
            fov_deg_v=float(self.slider_fov_v.value()) / self.factor_fov_v,
            resolution_w=640,
            resolution_h=480,
            update_rate_hz=float(self.slider_rate.value()),
            max_pan_speed_deg_s=pan_speed,
            max_tilt_speed_deg_s=tilt_speed,
            max_pan_accel_deg_s2=float(self.slider_pan_accel.value()) / self.factor_pan_accel,
            max_tilt_accel_deg_s2=float(self.slider_tilt_accel.value()) / self.factor_tilt_accel,
            pan_min_deg=-pan_r,
            pan_max_deg=pan_r,
            tilt_min_deg=-tilt_r,
            tilt_max_deg=tilt_r,
            home_pan_deg=float(self.slider_home_pan.value()) / self.factor_home_pan,
            home_tilt_deg=float(self.slider_home_tilt.value()) / self.factor_home_tilt,
            backlash_deg=float(self.slider_backlash.value()) / self.factor_backlash,
            damping_ratio=float(self.slider_damping.value()) / self.factor_damping,
            encoder_noise_deg=float(self.slider_noise.value()) / self.factor_noise,
            use_measured_feedback=bool(self.chk_measured_feedback.isChecked()),
            start_pan_deg=float(self.slider_start_pan.value()) / self.factor_start_pan,
            start_tilt_deg=float(self.slider_start_tilt.value()) / self.factor_start_tilt,
            use_custom_start=bool(self.chk_custom_start.isChecked()),
            scan_start_index=int(self.slider_scan_start.value()),
        )
        return cfg.validate()

    def set_config(self, cfg: CameraConfig, emit: bool = False) -> None:
        c = cfg.validate()
        sliders = [
            self.slider_fov_h, self.slider_fov_v, self.slider_rate,
            self.slider_pan_speed, self.slider_tilt_speed,
            self.slider_pan_accel, self.slider_tilt_accel,
            self.slider_pan_range, self.slider_tilt_range,
            self.slider_backlash, self.slider_damping, self.slider_noise,
            self.slider_home_pan, self.slider_home_tilt,
            self.slider_start_pan, self.slider_start_tilt,
            self.slider_scan_start, self.slider_slew,
        ]
        for s in sliders:
            s.blockSignals(True)
        self.chk_measured_feedback.blockSignals(True)
        self.chk_custom_start.blockSignals(True)
        self.chk_fov_link.blockSignals(True)
        self.chk_slew_link.blockSignals(True)
        try:
            self.slider_fov_h.setValue(int(round(c.fov_deg_h * self.factor_fov_h)))
            self.lbl_fov_h.setText(f"{c.fov_deg_h:.1f}°")
            self.slider_fov_v.setValue(int(round(c.fov_deg_v * self.factor_fov_v)))
            self.lbl_fov_v.setText(f"{c.fov_deg_v:.1f}°")
            self.slider_rate.setValue(int(c.update_rate_hz))
            self.lbl_rate.setText(str(int(c.update_rate_hz)))
            # slew
            slew = (c.max_pan_speed_deg_s + c.max_tilt_speed_deg_s) / 2.0
            self.slider_slew.setValue(int(round(slew * self.factor_slew)))
            self.lbl_slew.setText(f"{slew:.1f} °/s")
            self.slider_pan_speed.setValue(int(round(c.max_pan_speed_deg_s * self.factor_pan_speed)))
            self.lbl_pan_speed.setText(f"{c.max_pan_speed_deg_s:.1f} °/s")
            self.slider_tilt_speed.setValue(int(round(c.max_tilt_speed_deg_s * self.factor_tilt_speed)))
            self.lbl_tilt_speed.setText(f"{c.max_tilt_speed_deg_s:.1f} °/s")
            self.slider_pan_accel.setValue(int(round(c.max_pan_accel_deg_s2 * self.factor_pan_accel)))
            self.lbl_pan_accel.setText(f"{c.max_pan_accel_deg_s2:.0f} °/s²")
            self.slider_tilt_accel.setValue(int(round(c.max_tilt_accel_deg_s2 * self.factor_tilt_accel)))
            self.lbl_tilt_accel.setText(f"{c.max_tilt_accel_deg_s2:.0f} °/s²")
            pan_span = int(round(c.pan_max_deg))
            self.slider_pan_range.setValue(pan_span)
            self.lbl_pan_range.setText(str(pan_span))
            tilt_span = int(round(c.tilt_max_deg))
            self.slider_tilt_range.setValue(tilt_span)
            self.lbl_tilt_range.setText(str(tilt_span))
            self.slider_backlash.setValue(int(round(c.backlash_deg * self.factor_backlash)))
            self.lbl_backlash.setText(f"{c.backlash_deg:.3f}°")
            self.slider_damping.setValue(int(round(c.damping_ratio * self.factor_damping)))
            self.lbl_damping.setText(f"{c.damping_ratio:.2f}")
            self.slider_noise.setValue(int(round(c.encoder_noise_deg * self.factor_noise)))
            self.lbl_noise.setText(f"{c.encoder_noise_deg:.4f}°")
            self.chk_measured_feedback.setChecked(bool(getattr(c, "use_measured_feedback", False)))
            self.slider_home_pan.setValue(int(round(float(c.home_pan_deg) * self.factor_home_pan)))
            self.lbl_home_pan.setText(f"{float(c.home_pan_deg):.1f}°")
            self.slider_home_tilt.setValue(int(round(float(c.home_tilt_deg) * self.factor_home_tilt)))
            self.lbl_home_tilt.setText(f"{float(c.home_tilt_deg):.1f}°")
            self.slider_start_pan.setValue(int(round(float(getattr(c, "start_pan_deg", 0.0)) * self.factor_start_pan)))
            self.lbl_start_pan.setText(f"{float(getattr(c, 'start_pan_deg', 0.0)):.1f}°")
            self.slider_start_tilt.setValue(int(round(float(getattr(c, "start_tilt_deg", 0.0)) * self.factor_start_tilt)))
            self.lbl_start_tilt.setText(f"{float(getattr(c, 'start_tilt_deg', 0.0)):.1f}°")
            self.chk_custom_start.setChecked(bool(getattr(c, "use_custom_start", False)))
            self.slider_scan_start.setValue(int(getattr(c, "scan_start_index", 0)))
            self.lbl_scan_start.setText(str(int(getattr(c, "scan_start_index", 0))))
            # link state: if pan==tilt within epsilon, keep linked
            linked = abs(c.max_pan_speed_deg_s - c.max_tilt_speed_deg_s) < 1e-6
            self.chk_slew_link.setChecked(linked)
        finally:
            for s in sliders:
                s.blockSignals(False)
            self.chk_measured_feedback.blockSignals(False)
            self.chk_custom_start.blockSignals(False)
            self.chk_fov_link.blockSignals(False)
            self.chk_slew_link.blockSignals(False)
        if emit:
            self.configChanged.emit(c)

    def reset_to_defaults(self) -> None:
        self.set_config(CameraConfig().validate(), emit=True)
        self.combo_presets.setCurrentIndex(0)

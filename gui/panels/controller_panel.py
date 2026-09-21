# gui/panels/controller_panel.py - PID Controller (Redesign: Primary linked + Advanced)
from __future__ import annotations

import logging

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtWidgets import (
    QCheckBox,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from camera.config import PIDConfig
from camera.constants import PID_DEFAULTS, PID_LIMITS, PID_PRESETS
from gui.panels.base import BaseConfigPanel

log = logging.getLogger(__name__)


class ControllerPanel(BaseConfigPanel):
    """
    PID — Primary (mode, linked Kp/Ki/Kd + deadband + presets) + Advanced (per-axis + filter).
    Legacy per-axis sliders retained (hidden) for test back-compat.
    """

    configChanged = pyqtSignal(object)

    def __init__(self, parent=None, initial: PIDConfig | None = None):
        super().__init__(parent)
        self._initial = (initial or PIDConfig()).validate()
        self._updating_link = False
        self._build_ui()
        self.set_config(self._initial, emit=False)

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(10)

        header_row = QHBoxLayout()
        header_row.setSpacing(8)
        title = QLabel("PID TRACKING CONTROLLER")
        title.setStyleSheet("font-size:15px; font-weight:700; color:#111827;")
        header_row.addWidget(title)
        header_row.addStretch(1)
        mode_lbl = QLabel("Mode:")
        mode_lbl.setStyleSheet("font-size:11px; font-weight:600; color:#4b5563;")
        header_row.addWidget(mode_lbl)
        self.combo_mode = QComboBox()
        self.combo_mode.setMinimumHeight(28)
        self.combo_mode.addItems(["AUTO", "MANUAL", "OFF"])
        self.combo_mode.currentTextChanged.connect(self._on_mode_changed)
        header_row.addWidget(self.combo_mode)
        preset_lbl = QLabel("Preset:")
        preset_lbl.setStyleSheet("font-size:11px; font-weight:600; color:#4b5563;")
        header_row.addWidget(preset_lbl)
        self.combo_presets = QComboBox()
        self.combo_presets.setMinimumHeight(28)
        self.combo_presets.addItem("Custom...")
        for name in PID_PRESETS.keys():
            self.combo_presets.addItem(name)
        self.combo_presets.currentTextChanged.connect(self._on_preset_selected)
        header_row.addWidget(self.combo_presets)
        self.btn_reset = self._make_reset_button("Reset PID")
        self.btn_reset.clicked.connect(self.reset_to_defaults)
        header_row.addWidget(self.btn_reset)
        root.addLayout(header_row)
        desc = QLabel("Primary: linked gains + deadband  ·  Advanced: per-axis + filter/anti-windup")
        desc.setStyleSheet("color:#64748b; font-size:11px;")
        root.addWidget(desc)

        # ========== PRIMARY: linked gains ==========
        prim_box, prim_grid = self._make_group("GAINS — Primary (pan + tilt linked)")
        self.slider_kp, self.lbl_kp, self.factor_kp = self._make_float_slider(0.0, 10.0, 1.5, decimals=2, tooltip="Kp linked")
        self.slider_ki, self.lbl_ki, self.factor_ki = self._make_float_slider(0.0, 5.0, 0.1, decimals=2, tooltip="Ki linked")
        self.slider_kd, self.lbl_kd, self.factor_kd = self._make_float_slider(0.0, 3.0, 0.25, decimals=2, tooltip="Kd linked")
        self.chk_gain_link = QCheckBox("🔗 Pan/Tilt gains")
        self.chk_gain_link.setChecked(True)
        self.chk_gain_link.setStyleSheet("color:#374151; font-size:11px;")
        self.chk_gain_link.setToolTip("Link pan & tilt gains (uncheck for per-axis in Advanced)")
        self.slider_deadband, self.lbl_deadband, self.factor_deadband = self._make_float_slider(0.0, 10.0, 1.0, decimals=1, suffix=" px", tooltip="Deadband")
        prim_grid.addWidget(self._label("Kp"), 0, 0)
        prim_grid.addWidget(self.slider_kp, 0, 1)
        prim_grid.addWidget(self.lbl_kp, 0, 2)
        prim_grid.addWidget(self._label("Ki"), 1, 0)
        prim_grid.addWidget(self.slider_ki, 1, 1)
        prim_grid.addWidget(self.lbl_ki, 1, 2)
        prim_grid.addWidget(self._label("Kd"), 2, 0)
        prim_grid.addWidget(self.slider_kd, 2, 1)
        prim_grid.addWidget(self.lbl_kd, 2, 2)
        prim_grid.addWidget(self._label("Deadband"), 3, 0)
        prim_grid.addWidget(self.slider_deadband, 3, 1)
        prim_grid.addWidget(self.lbl_deadband, 3, 2)
        prim_grid.addWidget(self.chk_gain_link, 4, 0, 1, 3)
        root.addWidget(prim_box)

        # Create legacy per-axis sliders (for back-compat) but do NOT add to primary layout
        self.slider_kp_pan, self.lbl_kp_pan, self.factor_kp_pan = self._make_float_slider(0.0, 10.0, 1.5, decimals=2, tooltip="Kp pan")
        self.slider_ki_pan, self.lbl_ki_pan, self.factor_ki_pan = self._make_float_slider(0.0, 5.0, 0.1, decimals=2, tooltip="Ki pan")
        self.slider_kd_pan, self.lbl_kd_pan, self.factor_kd_pan = self._make_float_slider(0.0, 3.0, 0.25, decimals=2, tooltip="Kd pan")
        self.slider_kp_tilt, self.lbl_kp_tilt, self.factor_kp_tilt = self._make_float_slider(0.0, 10.0, 1.5, decimals=2, tooltip="Kp tilt")
        self.slider_ki_tilt, self.lbl_ki_tilt, self.factor_ki_tilt = self._make_float_slider(0.0, 5.0, 0.1, decimals=2, tooltip="Ki tilt")
        self.slider_kd_tilt, self.lbl_kd_tilt, self.factor_kd_tilt = self._make_float_slider(0.0, 3.0, 0.25, decimals=2, tooltip="Kd tilt")
        self.slider_tau, self.lbl_tau, self.factor_tau = self._make_float_slider(0.002, 0.2, 0.02, decimals=3, suffix=" s", tooltip="Tau")
        self.slider_max_int, self.lbl_max_int, self.factor_max_int = self._make_float_slider(1.0, 30.0, 10.0, decimals=1, suffix="°", tooltip="Max integral")
        self.slider_max_out, self.lbl_max_out, self.factor_max_out = self._make_float_slider(0.5, 20.0, 5.0, decimals=1, suffix=" °/s", tooltip="Max output")

        # ========== ADVANCED (collapsed) ==========
        self.chk_advanced = QCheckBox("Show advanced (per-axis gains · filter · limits)")
        self.chk_advanced.setStyleSheet("color:#4b5563; font-size:11px; font-weight:600;")
        root.addWidget(self.chk_advanced)
        self.advanced_widget = QWidget()
        adv = QVBoxLayout(self.advanced_widget)
        adv.setContentsMargins(0, 0, 0, 0)
        adv.setSpacing(10)
        pan_box, pan_grid = self._make_group("PAN GAINS — Advanced")
        pan_grid.addWidget(self._label("Kp Pan"), 0, 0)
        pan_grid.addWidget(self.slider_kp_pan, 0, 1)
        pan_grid.addWidget(self.lbl_kp_pan, 0, 2)
        pan_grid.addWidget(self._label("Ki Pan"), 1, 0)
        pan_grid.addWidget(self.slider_ki_pan, 1, 1)
        pan_grid.addWidget(self.lbl_ki_pan, 1, 2)
        pan_grid.addWidget(self._label("Kd Pan"), 2, 0)
        pan_grid.addWidget(self.slider_kd_pan, 2, 1)
        pan_grid.addWidget(self.lbl_kd_pan, 2, 2)
        adv.addWidget(pan_box)
        tilt_box, tilt_grid = self._make_group("TILT GAINS — Advanced")
        tilt_grid.addWidget(self._label("Kp Tilt"), 0, 0)
        tilt_grid.addWidget(self.slider_kp_tilt, 0, 1)
        tilt_grid.addWidget(self.lbl_kp_tilt, 0, 2)
        tilt_grid.addWidget(self._label("Ki Tilt"), 1, 0)
        tilt_grid.addWidget(self.slider_ki_tilt, 1, 1)
        tilt_grid.addWidget(self.lbl_ki_tilt, 1, 2)
        tilt_grid.addWidget(self._label("Kd Tilt"), 2, 0)
        tilt_grid.addWidget(self.slider_kd_tilt, 2, 1)
        tilt_grid.addWidget(self.lbl_kd_tilt, 2, 2)
        adv.addWidget(tilt_box)
        rob_box, rob_grid = self._make_group("FILTER & LIMITS — Advanced")
        rob_grid.addWidget(self._label("Tau"), 0, 0)
        rob_grid.addWidget(self.slider_tau, 0, 1)
        rob_grid.addWidget(self.lbl_tau, 0, 2)
        rob_grid.addWidget(self._label("Max Integral"), 1, 0)
        rob_grid.addWidget(self.slider_max_int, 1, 1)
        rob_grid.addWidget(self.lbl_max_int, 1, 2)
        rob_grid.addWidget(self._label("Max Output"), 2, 0)
        rob_grid.addWidget(self.slider_max_out, 2, 1)
        rob_grid.addWidget(self.lbl_max_out, 2, 2)
        adv.addWidget(rob_box)
        self.advanced_widget.setVisible(False)
        root.addWidget(self.advanced_widget)
        self.chk_advanced.toggled.connect(self.advanced_widget.setVisible)

        root.addStretch(1)

        # Wiring: primary + advanced sync
        for s in [self.slider_kp, self.slider_ki, self.slider_kd, self.slider_deadband,
                  self.slider_kp_pan, self.slider_ki_pan, self.slider_kd_pan,
                  self.slider_kp_tilt, self.slider_ki_tilt, self.slider_kd_tilt,
                  self.slider_tau, self.slider_max_int, self.slider_max_out]:
            s.valueChanged.connect(self._on_control_changed)
            s.sliderReleased.connect(self._on_control_changed)
        # Link behaviours: primary -> per-axis when linked
        self.slider_kp.valueChanged.connect(self._on_kp_link)
        self.slider_ki.valueChanged.connect(self._on_ki_link)
        self.slider_kd.valueChanged.connect(self._on_kd_link)
        self.chk_gain_link.toggled.connect(self._on_gain_link_toggled)

    def _on_kp_link(self, v):
        if self._updating_link or not self.chk_gain_link.isChecked():
            return
        try:
            self._updating_link = True
            self.slider_kp_pan.setValue(int(round(float(v) / self.factor_kp * self.factor_kp_pan)))
            self.slider_kp_tilt.setValue(int(round(float(v) / self.factor_kp * self.factor_kp_tilt)))
        finally:
            self._updating_link = False

    def _on_ki_link(self, v):
        if self._updating_link or not self.chk_gain_link.isChecked():
            return
        try:
            self._updating_link = True
            self.slider_ki_pan.setValue(int(round(float(v) / self.factor_ki * self.factor_ki_pan)))
            self.slider_ki_tilt.setValue(int(round(float(v) / self.factor_ki * self.factor_ki_tilt)))
        finally:
            self._updating_link = False

    def _on_kd_link(self, v):
        if self._updating_link or not self.chk_gain_link.isChecked():
            return
        try:
            self._updating_link = True
            self.slider_kd_pan.setValue(int(round(float(v) / self.factor_kd * self.factor_kd_pan)))
            self.slider_kd_tilt.setValue(int(round(float(v) / self.factor_kd * self.factor_kd_tilt)))
        finally:
            self._updating_link = False

    def _on_gain_link_toggled(self, checked: bool):
        if checked:
            self._on_kp_link(self.slider_kp.value())
            self._on_ki_link(self.slider_ki.value())
            self._on_kd_link(self.slider_kd.value())
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

    def _on_mode_changed(self, mode: str) -> None:
        cfg = self.collect_config()
        self.configChanged.emit(cfg)

    def _on_preset_selected(self, name: str) -> None:
        if name in PID_PRESETS:
            preset = PID_PRESETS[name]
            cfg = PIDConfig(**preset, mode=self.combo_mode.currentText()).validate()
            self.set_config(cfg, emit=True)

    def collect_config(self) -> PIDConfig:
        if self.chk_gain_link.isChecked():
            kp = float(self.slider_kp.value()) / self.factor_kp
            ki = float(self.slider_ki.value()) / self.factor_ki
            kd = float(self.slider_kd.value()) / self.factor_kd
            kp_pan = kp_tilt = kp
            ki_pan = ki_tilt = ki
            kd_pan = kd_tilt = kd
        else:
            kp_pan = float(self.slider_kp_pan.value()) / self.factor_kp_pan
            ki_pan = float(self.slider_ki_pan.value()) / self.factor_ki_pan
            kd_pan = float(self.slider_kd_pan.value()) / self.factor_kd_pan
            kp_tilt = float(self.slider_kp_tilt.value()) / self.factor_kp_tilt
            ki_tilt = float(self.slider_ki_tilt.value()) / self.factor_ki_tilt
            kd_tilt = float(self.slider_kd_tilt.value()) / self.factor_kd_tilt
        cfg = PIDConfig(
            kp_pan=kp_pan, ki_pan=ki_pan, kd_pan=kd_pan,
            kp_tilt=kp_tilt, ki_tilt=ki_tilt, kd_tilt=kd_tilt,
            tau=float(self.slider_tau.value()) / self.factor_tau,
            deadband_px=float(self.slider_deadband.value()) / self.factor_deadband,
            max_integral_deg=float(self.slider_max_int.value()) / self.factor_max_int,
            max_output_deg_s=float(self.slider_max_out.value()) / self.factor_max_out,
            mode=self.combo_mode.currentText(),
        )
        return cfg.validate()

    def set_config(self, cfg: PIDConfig, emit: bool = False) -> None:
        c = cfg.validate()
        sliders = [self.slider_kp, self.slider_ki, self.slider_kd, self.slider_deadband,
                   self.slider_kp_pan, self.slider_ki_pan, self.slider_kd_pan,
                   self.slider_kp_tilt, self.slider_ki_tilt, self.slider_kd_tilt,
                   self.slider_tau, self.slider_max_int, self.slider_max_out]
        for s in sliders:
            s.blockSignals(True)
        self.combo_mode.blockSignals(True)
        try:
            self.combo_mode.setCurrentText(c.mode)
            # primary linked is avg of pan/tilt
            kp_avg = (c.kp_pan + c.kp_tilt) / 2.0
            ki_avg = (c.ki_pan + c.ki_tilt) / 2.0
            kd_avg = (c.kd_pan + c.kd_tilt) / 2.0
            self.slider_kp.setValue(int(round(kp_avg * self.factor_kp)))
            self.lbl_kp.setText(f"{kp_avg:.2f}")
            self.slider_ki.setValue(int(round(ki_avg * self.factor_ki)))
            self.lbl_ki.setText(f"{ki_avg:.2f}")
            self.slider_kd.setValue(int(round(kd_avg * self.factor_kd)))
            self.lbl_kd.setText(f"{kd_avg:.2f}")
            self.slider_kp_pan.setValue(int(round(c.kp_pan * self.factor_kp_pan)))
            self.lbl_kp_pan.setText(f"{c.kp_pan:.2f}")
            self.slider_ki_pan.setValue(int(round(c.ki_pan * self.factor_ki_pan)))
            self.lbl_ki_pan.setText(f"{c.ki_pan:.2f}")
            self.slider_kd_pan.setValue(int(round(c.kd_pan * self.factor_kd_pan)))
            self.lbl_kd_pan.setText(f"{c.kd_pan:.2f}")
            self.slider_kp_tilt.setValue(int(round(c.kp_tilt * self.factor_kp_tilt)))
            self.lbl_kp_tilt.setText(f"{c.kp_tilt:.2f}")
            self.slider_ki_tilt.setValue(int(round(c.ki_tilt * self.factor_ki_tilt)))
            self.lbl_ki_tilt.setText(f"{c.ki_tilt:.2f}")
            self.slider_kd_tilt.setValue(int(round(c.kd_tilt * self.factor_kd_tilt)))
            self.lbl_kd_tilt.setText(f"{c.kd_tilt:.2f}")
            self.slider_tau.setValue(int(round(c.tau * self.factor_tau)))
            self.lbl_tau.setText(f"{c.tau:.3f} s")
            self.slider_deadband.setValue(int(round(c.deadband_px * self.factor_deadband)))
            self.lbl_deadband.setText(f"{c.deadband_px:.1f} px")
            self.slider_max_int.setValue(int(round(c.max_integral_deg * self.factor_max_int)))
            self.lbl_max_int.setText(f"{c.max_integral_deg:.1f}°")
            self.slider_max_out.setValue(int(round(c.max_output_deg_s * self.factor_max_out)))
            self.lbl_max_out.setText(f"{c.max_output_deg_s:.1f} °/s")
            linked = abs(c.kp_pan - c.kp_tilt) < 1e-9 and abs(c.ki_pan - c.ki_tilt) < 1e-9 and abs(c.kd_pan - c.kd_tilt) < 1e-9
            self.chk_gain_link.setChecked(linked)
        finally:
            for s in sliders:
                s.blockSignals(False)
            self.combo_mode.blockSignals(False)
        if emit:
            self.configChanged.emit(c)

    def reset_to_defaults(self) -> None:
        self.set_config(PIDConfig().validate(), emit=True)
        self.combo_presets.setCurrentIndex(0)

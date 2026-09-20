# gui/panels/controller_panel.py - PID Tracking Controller Control Deck panel.
from __future__ import annotations

import logging

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
)

from camera.config import PIDConfig
from camera.constants import PID_DEFAULTS, PID_LIMITS, PID_PRESETS
from gui.panels.base import BaseConfigPanel

log = logging.getLogger(__name__)


class ControllerPanel(BaseConfigPanel):
    """
    Configuration panel for the Dual-Axis PID Tracking Controller.
    
    Provides controls for:
    - Operating Mode (AUTO, MANUAL, OFF)
    - Independent Pan & Tilt PID gains (Kp, Ki, Kd)
    - Filtered derivative time constant tau (low-pass filter on D-term)
    - Pixel deadband zone
    - Anti-windup integral limit and max velocity output
    - Presets for balanced, aggressive, and conservative tuning
    """

    configChanged = pyqtSignal(object)

    def __init__(self, parent=None, initial: PIDConfig | None = None):
        super().__init__(parent)
        self._initial = (initial or PIDConfig()).validate()
        self._build_ui()
        self.set_config(self._initial, emit=False)

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(10)

        # Header Row
        header_row = QHBoxLayout()
        header_row.setSpacing(8)
        title = QLabel("PID TRACKING CONTROLLER")
        title.setStyleSheet("font-size:15px; font-weight:700; color:#111827;")
        header_row.addWidget(title)
        header_row.addStretch(1)

        # Mode Selector
        mode_lbl = QLabel("Mode:")
        mode_lbl.setStyleSheet("font-size:11px; font-weight:600; color:#4b5563;")
        header_row.addWidget(mode_lbl)
        self.combo_mode = QComboBox()
        self.combo_mode.setMinimumHeight(28)
        self.combo_mode.addItems(["AUTO", "MANUAL", "OFF"])
        self.combo_mode.currentTextChanged.connect(self._on_mode_changed)
        header_row.addWidget(self.combo_mode)

        # Presets
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

        desc = QLabel("Dual-axis closed-loop tracking with filtered derivative and anti-windup")
        desc.setStyleSheet("color:#64748b; font-size:11px;")
        root.addWidget(desc)

        # --- 1. Pan Axis PID Group ---
        pan_box, pan_grid = self._make_group("PAN AXIS GAINS (AZIMUTH)")

        self.slider_kp_pan, self.lbl_kp_pan, self.factor_kp_pan = self._make_float_slider(
            0.0, 10.0, 1.5, decimals=2, tooltip="Pan proportional gain Kp (deg/s per deg error)"
        )
        pan_grid.addWidget(self._label("Kp (Proportional)"), 0, 0)
        pan_grid.addWidget(self.slider_kp_pan, 0, 1)
        pan_grid.addWidget(self.lbl_kp_pan, 0, 2)

        self.slider_ki_pan, self.lbl_ki_pan, self.factor_ki_pan = self._make_float_slider(
            0.0, 5.0, 0.1, decimals=2, tooltip="Pan integral gain Ki"
        )
        pan_grid.addWidget(self._label("Ki (Integral)"), 1, 0)
        pan_grid.addWidget(self.slider_ki_pan, 1, 1)
        pan_grid.addWidget(self.lbl_ki_pan, 1, 2)

        self.slider_kd_pan, self.lbl_kd_pan, self.factor_kd_pan = self._make_float_slider(
            0.0, 3.0, 0.25, decimals=2, tooltip="Pan derivative gain Kd"
        )
        pan_grid.addWidget(self._label("Kd (Derivative)"), 2, 0)
        pan_grid.addWidget(self.slider_kd_pan, 2, 1)
        pan_grid.addWidget(self.lbl_kd_pan, 2, 2)

        root.addWidget(pan_box)

        # --- 2. Tilt Axis PID Group ---
        tilt_box, tilt_grid = self._make_group("TILT AXIS GAINS (ELEVATION)")

        self.slider_kp_tilt, self.lbl_kp_tilt, self.factor_kp_tilt = self._make_float_slider(
            0.0, 10.0, 1.5, decimals=2, tooltip="Tilt proportional gain Kp (deg/s per deg error)"
        )
        tilt_grid.addWidget(self._label("Kp (Proportional)"), 0, 0)
        tilt_grid.addWidget(self.slider_kp_tilt, 0, 1)
        tilt_grid.addWidget(self.lbl_kp_tilt, 0, 2)

        self.slider_ki_tilt, self.lbl_ki_tilt, self.factor_ki_tilt = self._make_float_slider(
            0.0, 5.0, 0.1, decimals=2, tooltip="Tilt integral gain Ki"
        )
        tilt_grid.addWidget(self._label("Ki (Integral)"), 1, 0)
        tilt_grid.addWidget(self.slider_ki_tilt, 1, 1)
        tilt_grid.addWidget(self.lbl_ki_tilt, 1, 2)

        self.slider_kd_tilt, self.lbl_kd_tilt, self.factor_kd_tilt = self._make_float_slider(
            0.0, 3.0, 0.25, decimals=2, tooltip="Tilt derivative gain Kd"
        )
        tilt_grid.addWidget(self._label("Kd (Derivative)"), 2, 0)
        tilt_grid.addWidget(self.slider_kd_tilt, 2, 1)
        tilt_grid.addWidget(self.lbl_kd_tilt, 2, 2)

        root.addWidget(tilt_box)

        # --- 3. Filter & Robustness Group ---
        rob_box, rob_grid = self._make_group("DERIVATIVE FILTER & ANTI-WINDUP")

        # Derivative Filter tau (1 .. 200 ms)
        self.slider_tau, self.lbl_tau, self.factor_tau = self._make_float_slider(
            0.002, 0.2, 0.02, decimals=3, suffix=" s", tooltip="Low-pass filter time constant tau on derivative term"
        )
        rob_grid.addWidget(self._label("Derivative Filter (τ)"), 0, 0)
        rob_grid.addWidget(self.slider_tau, 0, 1)
        rob_grid.addWidget(self.lbl_tau, 0, 2)

        # Pixel Deadband (0.0 .. 10.0 px)
        self.slider_deadband, self.lbl_deadband, self.factor_deadband = self._make_float_slider(
            0.0, 10.0, 1.0, decimals=1, suffix=" px", tooltip="Pixel tracking deadband to prevent hunting"
        )
        rob_grid.addWidget(self._label("Error Deadband"), 1, 0)
        rob_grid.addWidget(self.slider_deadband, 1, 1)
        rob_grid.addWidget(self.lbl_deadband, 1, 2)

        # Max Integral (1.0 .. 30.0 deg)
        self.slider_max_int, self.lbl_max_int, self.factor_max_int = self._make_float_slider(
            1.0, 30.0, 10.0, decimals=1, suffix="°", tooltip="Integrator anti-windup clamp limit"
        )
        rob_grid.addWidget(self._label("Max Integral Clamp"), 2, 0)
        rob_grid.addWidget(self.slider_max_int, 2, 1)
        rob_grid.addWidget(self.lbl_max_int, 2, 2)

        # Max Output Rate (0.5 .. 20.0 °/s)
        self.slider_max_out, self.lbl_max_out, self.factor_max_out = self._make_float_slider(
            0.5, 20.0, 5.0, decimals=1, suffix=" °/s", tooltip="Maximum commanded slewing rate"
        )
        rob_grid.addWidget(self._label("Max Output Rate"), 3, 0)
        rob_grid.addWidget(self.slider_max_out, 3, 1)
        rob_grid.addWidget(self.lbl_max_out, 3, 2)

        root.addWidget(rob_box)
        root.addStretch(1)

        # Connect change signals — release-gated like CameraPanel: drags
        # coalesce into one sliderReleased emit instead of one per tick.
        sliders = [
            self.slider_kp_pan, self.slider_ki_pan, self.slider_kd_pan,
            self.slider_kp_tilt, self.slider_ki_tilt, self.slider_kd_tilt,
            self.slider_tau, self.slider_deadband, self.slider_max_int, self.slider_max_out,
        ]
        for s in sliders:
            s.valueChanged.connect(self._on_control_changed)
            s.sliderReleased.connect(self._on_control_changed)

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
        cfg = PIDConfig(
            kp_pan=float(self.slider_kp_pan.value()) / self.factor_kp_pan,
            ki_pan=float(self.slider_ki_pan.value()) / self.factor_ki_pan,
            kd_pan=float(self.slider_kd_pan.value()) / self.factor_kd_pan,
            kp_tilt=float(self.slider_kp_tilt.value()) / self.factor_kp_tilt,
            ki_tilt=float(self.slider_ki_tilt.value()) / self.factor_ki_tilt,
            kd_tilt=float(self.slider_kd_tilt.value()) / self.factor_kd_tilt,
            tau=float(self.slider_tau.value()) / self.factor_tau,
            deadband_px=float(self.slider_deadband.value()) / self.factor_deadband,
            max_integral_deg=float(self.slider_max_int.value()) / self.factor_max_int,
            max_output_deg_s=float(self.slider_max_out.value()) / self.factor_max_out,
            mode=self.combo_mode.currentText(),
        )
        return cfg.validate()

    def set_config(self, cfg: PIDConfig, emit: bool = False) -> None:
        c = cfg.validate()

        sliders = [
            self.slider_kp_pan, self.slider_ki_pan, self.slider_kd_pan,
            self.slider_kp_tilt, self.slider_ki_tilt, self.slider_kd_tilt,
            self.slider_tau, self.slider_deadband, self.slider_max_int, self.slider_max_out,
        ]
        for s in sliders:
            s.blockSignals(True)
        self.combo_mode.blockSignals(True)

        try:
            self.combo_mode.setCurrentText(c.mode)

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
        finally:
            for s in sliders:
                s.blockSignals(False)
            self.combo_mode.blockSignals(False)

        if emit:
            self.configChanged.emit(c)

    def reset_to_defaults(self) -> None:
        self.set_config(PIDConfig().validate(), emit=True)
        self.combo_presets.setCurrentIndex(0)

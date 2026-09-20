# gui/panels/camera_panel.py - Camera & PTZ Mechanism Control Deck panel.
from __future__ import annotations

import logging
from typing import Any

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtWidgets import (
    QCheckBox,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
)

from camera.config import CameraConfig
from camera.constants import CAMERA_DEFAULTS, CAMERA_LIMITS, CAMERA_PRESETS
from gui.panels.base import BaseConfigPanel

log = logging.getLogger(__name__)


class CameraPanel(BaseConfigPanel):
    """
    Configuration panel for virtual Camera Optics and PTZ Gimbal Mechanism.
    
    Provides controls for:
    - Optical FOV (degrees) and Sensor resolution (fixed 640x480)
    - Gimbal kinematics: max pan/tilt speeds, accelerations, and limits
    - Mechanical dynamics: damping, inertia, backlash hysteresis, and encoder noise
    - Industry standard PAT presets
    """

    configChanged = pyqtSignal(object)

    def __init__(self, parent=None, initial: CameraConfig | None = None):
        super().__init__(parent)
        self._initial = (initial or CameraConfig()).validate()
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

        # Preset Selector
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

        desc = QLabel("Virtual PTZ Camera optics, gimbal rate limits, and mechanical dynamics")
        desc.setStyleSheet("color:#64748b; font-size:11px;")
        root.addWidget(desc)

        # --- 1. Optics & Viewport Group ---
        optics_box, optics_grid = self._make_group("CAMERA OPTICS & VIEWPORT")
        
        # Horizontal FOV (0.5 .. 30.0 deg)
        self.slider_fov_h, self.lbl_fov_h, self.factor_fov_h = self._make_float_slider(
            0.5, 30.0, 4.0, decimals=1, suffix="°", tooltip="Horizontal Field of View (PDF default 4.0°)"
        )
        optics_grid.addWidget(self._label("Horizontal FOV"), 0, 0)
        optics_grid.addWidget(self.slider_fov_h, 0, 1)
        optics_grid.addWidget(self.lbl_fov_h, 0, 2)

        # Vertical FOV (0.5 .. 30.0 deg)
        self.slider_fov_v, self.lbl_fov_v, self.factor_fov_v = self._make_float_slider(
            0.5, 30.0, 3.0, decimals=1, suffix="°", tooltip="Vertical Field of View (PDF default 3.0°)"
        )
        optics_grid.addWidget(self._label("Vertical FOV"), 1, 0)
        optics_grid.addWidget(self.slider_fov_v, 1, 1)
        optics_grid.addWidget(self.lbl_fov_v, 1, 2)

        # Resolution (Fixed 640x480 per requirements)
        res_label = QLabel("640 × 480 px (Fixed Monochrome)")
        res_label.setStyleSheet("color:#111827; font-weight:700; font-size:11px; padding:2px;")
        optics_grid.addWidget(self._label("Resolution"), 2, 0)
        optics_grid.addWidget(res_label, 2, 1)

        # Update Rate (Hz)
        self.slider_rate, self.lbl_rate = self._make_int_slider(
            10, 120, 30, tooltip="Camera capture update rate (≥30 Hz per PDF)"
        )
        optics_grid.addWidget(self._label("Update Rate"), 3, 0)
        optics_grid.addWidget(self.slider_rate, 3, 1)
        optics_grid.addWidget(self.lbl_rate, 3, 2)

        root.addWidget(optics_box)

        # --- 2. PTZ Gimbal Kinematics Group ---
        kin_box, kin_grid = self._make_group("GIMBAL KINEMATICS & LIMITS")

        # Max Pan Speed (0.5 .. 30.0 °/s, PDF default 5.0)
        self.slider_pan_speed, self.lbl_pan_speed, self.factor_pan_speed = self._make_float_slider(
            0.5, 30.0, 5.0, decimals=1, suffix=" °/s", tooltip="Maximum pan slewing rate (PDF: 5-10 °/s)"
        )
        kin_grid.addWidget(self._label("Max Pan Speed"), 0, 0)
        kin_grid.addWidget(self.slider_pan_speed, 0, 1)
        kin_grid.addWidget(self.lbl_pan_speed, 0, 2)

        # Max Tilt Speed (0.5 .. 30.0 °/s, PDF default 5.0)
        self.slider_tilt_speed, self.lbl_tilt_speed, self.factor_tilt_speed = self._make_float_slider(
            0.5, 30.0, 5.0, decimals=1, suffix=" °/s", tooltip="Maximum tilt slewing rate (PDF: 5-10 °/s)"
        )
        kin_grid.addWidget(self._label("Max Tilt Speed"), 1, 0)
        kin_grid.addWidget(self.slider_tilt_speed, 1, 1)
        kin_grid.addWidget(self.lbl_tilt_speed, 1, 2)

        # Max Pan Accel (1.0 .. 100.0 °/s²)
        self.slider_pan_accel, self.lbl_pan_accel, self.factor_pan_accel = self._make_float_slider(
            1.0, 100.0, 25.0, decimals=0, suffix=" °/s²", tooltip="Maximum pan angular acceleration"
        )
        kin_grid.addWidget(self._label("Max Pan Accel"), 2, 0)
        kin_grid.addWidget(self.slider_pan_accel, 2, 1)
        kin_grid.addWidget(self.lbl_pan_accel, 2, 2)

        # Max Tilt Accel (1.0 .. 100.0 °/s²)
        self.slider_tilt_accel, self.lbl_tilt_accel, self.factor_tilt_accel = self._make_float_slider(
            1.0, 100.0, 25.0, decimals=0, suffix=" °/s²", tooltip="Maximum tilt angular acceleration"
        )
        kin_grid.addWidget(self._label("Max Tilt Accel"), 3, 0)
        kin_grid.addWidget(self.slider_tilt_accel, 3, 1)
        kin_grid.addWidget(self.lbl_tilt_accel, 3, 2)

        # Pan Travel Range (±180°)
        self.slider_pan_range, self.lbl_pan_range = self._make_int_slider(
            10, 180, 90, tooltip="Pan travel range (±deg from center)"
        )
        kin_grid.addWidget(self._label("Pan Range (±)"), 4, 0)
        kin_grid.addWidget(self.slider_pan_range, 4, 1)
        kin_grid.addWidget(self.lbl_pan_range, 4, 2)

        # Tilt Travel Range (±90°)
        self.slider_tilt_range, self.lbl_tilt_range = self._make_int_slider(
            5, 90, 45, tooltip="Tilt travel range (±deg from center)"
        )
        kin_grid.addWidget(self._label("Tilt Range (±)"), 5, 0)
        kin_grid.addWidget(self.slider_tilt_range, 5, 1)
        kin_grid.addWidget(self.lbl_tilt_range, 5, 2)

        root.addWidget(kin_box)

        # --- 3. Mechanical Dynamics & Encoders Group ---
        mech_box, mech_grid = self._make_group("MECHANICAL DYNAMICS & ENCODERS")

        # Backlash (0.0 .. 0.1 deg)
        self.slider_backlash, self.lbl_backlash, self.factor_backlash = self._make_float_slider(
            0.0, 0.1, 0.005, decimals=3, suffix="°", tooltip="Gimbal gear backlash / hysteresis"
        )
        mech_grid.addWidget(self._label("Gear Backlash"), 0, 0)
        mech_grid.addWidget(self.slider_backlash, 0, 1)
        mech_grid.addWidget(self.lbl_backlash, 0, 2)

        # Damping Ratio (0.1 .. 2.0)
        self.slider_damping, self.lbl_damping, self.factor_damping = self._make_float_slider(
            0.1, 2.0, 0.71, decimals=2, suffix="", tooltip="Damping ratio zeta (0.7 = critically damped)"
        )
        mech_grid.addWidget(self._label("Damping Ratio"), 1, 0)
        mech_grid.addWidget(self.slider_damping, 1, 1)
        mech_grid.addWidget(self.lbl_damping, 1, 2)

        # Encoder Noise (0.0 .. 0.02 deg)
        self.slider_noise, self.lbl_noise, self.factor_noise = self._make_float_slider(
            0.0, 0.02, 0.001, decimals=4, suffix="°", tooltip="Optical encoder 1-sigma angular noise"
        )
        mech_grid.addWidget(self._label("Encoder Noise"), 2, 0)
        mech_grid.addWidget(self.slider_noise, 2, 1)
        mech_grid.addWidget(self.lbl_noise, 2, 2)

        # Measured feedback (Plan Stage 2): disturb-pose input from
        # encoder-measured angles (quantized + noisy) instead of truth.
        self.chk_measured_feedback = QCheckBox("Measured feedback")
        self.chk_measured_feedback.setToolTip(
            "Disturb the encoder-measured pose instead of the true pose")
        self.chk_measured_feedback.setStyleSheet("color:#374151; font-size:11px;")
        mech_grid.addWidget(self.chk_measured_feedback, 3, 0, 1, 3)

        root.addWidget(mech_box)
        root.addStretch(1)

        # Connect change signals — release-gated: valueChanged updates the
        # pill label (cheap, wired in BaseConfigPanel); the config emits on
        # sliderReleased or for non-drag changes so a drag coalesces into
        # one hot-reload apply instead of one per tick.
        sliders = [
            self.slider_fov_h, self.slider_fov_v, self.slider_rate,
            self.slider_pan_speed, self.slider_tilt_speed,
            self.slider_pan_accel, self.slider_tilt_accel,
            self.slider_pan_range, self.slider_tilt_range,
            self.slider_backlash, self.slider_damping, self.slider_noise,
        ]
        for s in sliders:
            s.valueChanged.connect(self._on_control_changed)
            s.sliderReleased.connect(self._on_control_changed)
        self.chk_measured_feedback.toggled.connect(self._on_control_changed)

    def _on_control_changed(self) -> None:
        """Handle live changes from sliders (skipped mid-drag)."""
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
            cfg = CameraConfig(**preset).validate()
            self.set_config(cfg, emit=True)

    def collect_config(self) -> CameraConfig:
        pan_r = float(self.slider_pan_range.value())
        tilt_r = float(self.slider_tilt_range.value())

        cfg = CameraConfig(
            fov_deg_h=float(self.slider_fov_h.value()) / self.factor_fov_h,
            fov_deg_v=float(self.slider_fov_v.value()) / self.factor_fov_v,
            resolution_w=640,
            resolution_h=480,
            update_rate_hz=float(self.slider_rate.value()),
            max_pan_speed_deg_s=float(self.slider_pan_speed.value()) / self.factor_pan_speed,
            max_tilt_speed_deg_s=float(self.slider_tilt_speed.value()) / self.factor_tilt_speed,
            max_pan_accel_deg_s2=float(self.slider_pan_accel.value()) / self.factor_pan_accel,
            max_tilt_accel_deg_s2=float(self.slider_tilt_accel.value()) / self.factor_tilt_accel,
            pan_min_deg=-pan_r,
            pan_max_deg=pan_r,
            tilt_min_deg=-tilt_r,
            tilt_max_deg=tilt_r,
            backlash_deg=float(self.slider_backlash.value()) / self.factor_backlash,
            damping_ratio=float(self.slider_damping.value()) / self.factor_damping,
            encoder_noise_deg=float(self.slider_noise.value()) / self.factor_noise,
            use_measured_feedback=bool(self.chk_measured_feedback.isChecked()),
        )
        return cfg.validate()

    def set_config(self, cfg: CameraConfig, emit: bool = False) -> None:
        c = cfg.validate()

        # Block signals during bulk programmatic update
        sliders = [
            self.slider_fov_h, self.slider_fov_v, self.slider_rate,
            self.slider_pan_speed, self.slider_tilt_speed,
            self.slider_pan_accel, self.slider_tilt_accel,
            self.slider_pan_range, self.slider_tilt_range,
            self.slider_backlash, self.slider_damping, self.slider_noise,
        ]
        for s in sliders:
            s.blockSignals(True)
        self.chk_measured_feedback.blockSignals(True)

        try:
            self.slider_fov_h.setValue(int(round(c.fov_deg_h * self.factor_fov_h)))
            self.lbl_fov_h.setText(f"{c.fov_deg_h:.1f}°")

            self.slider_fov_v.setValue(int(round(c.fov_deg_v * self.factor_fov_v)))
            self.lbl_fov_v.setText(f"{c.fov_deg_v:.1f}°")

            self.slider_rate.setValue(int(c.update_rate_hz))
            self.lbl_rate.setText(str(int(c.update_rate_hz)))

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
        finally:
            for s in sliders:
                s.blockSignals(False)
            self.chk_measured_feedback.blockSignals(False)

        if emit:
            self.configChanged.emit(c)

    def reset_to_defaults(self) -> None:
        self.set_config(CameraConfig().validate(), emit=True)
        self.combo_presets.setCurrentIndex(0)

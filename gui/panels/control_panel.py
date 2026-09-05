# gui/panels/control_panel.py - Controller controls — intuitive slider UI, light theme, reset per panel

import numpy as np
from PyQt5.QtCore import pyqtSignal
from PyQt5.QtWidgets import (
    QComboBox,
    QDoubleSpinBox,
    QGridLayout,
    QGroupBox,
    QLabel,
    QVBoxLayout,
)

from control.config import ControllerConfig
from control.constants import CONTROL_LIMITS, CONTROLLER_TYPES
from gui.panels.base import BaseConfigPanel


class ControlPanel(BaseConfigPanel):
    """
    Control tab — slider-based intuitive UI.
    Every numeric field is a slider + live value (highlighted on drag).
    Reset button restores defaults.
    Keeps spinbox aliases hidden for backward compat.
    """

    configChanged = pyqtSignal(object)

    def __init__(self, initial: ControllerConfig | None = None, parent=None):
        super().__init__(parent)
        self._initial = (initial or ControllerConfig()).validate()
        self._build_ui()
        self.set_config(self._initial, emit=False)

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(10)

        # Type
        type_box, type_grid = self._make_group("A — Controller Type")
        type_grid.addWidget(self._label("Type"), 0, 0)
        self.type_combo = QComboBox()
        self.type_combo.addItems(CONTROLLER_TYPES)
        self.type_combo.setToolTip("P, PI, PID")
        self.type_combo.setMinimumHeight(26)
        type_grid.addWidget(self.type_combo, 0, 1)
        hint = QLabel("P: simple. PI: fixes steady offset. PID: damps overshoot with slew/latency.")
        hint.setWordWrap(True)
        hint.setStyleSheet("color:#64748b; font-size:10px; font-style:italic;")
        type_grid.addWidget(hint, 1, 0, 1, 2)
        layout.addWidget(type_box)

        # Gains
        gains_box, gains_grid = self._make_group("B — Gains (slider + highlighted value)")
        # Kp
        lo, hi = CONTROL_LIMITS["kp"]
        self.kp_slider, self.kp_label, self.kp_factor = self._make_float_slider(lo, hi, 0.15, decimals=3, tooltip="Proportional gain")
        self.kp_spin = QDoubleSpinBox(); self.kp_spin.setRange(lo, hi); self.kp_spin.setValue(0.15); self.kp_spin.hide()
        gains_grid.addWidget(self._label("Kp (P)"), 0, 0)
        gains_grid.addWidget(self.kp_slider, 0, 1)
        gains_grid.addWidget(self.kp_label, 0, 2)
        # Ki
        lo, hi = CONTROL_LIMITS["ki"]
        self.ki_slider, self.ki_label, self.ki_factor = self._make_float_slider(lo, hi, 0.0, decimals=3, tooltip="Integral gain")
        self.ki_spin = QDoubleSpinBox(); self.ki_spin.setRange(lo, hi); self.ki_spin.setValue(0.0); self.ki_spin.hide()
        gains_grid.addWidget(self._label("Ki (I)"), 0, 3)
        gains_grid.addWidget(self.ki_slider, 0, 4)
        gains_grid.addWidget(self.ki_label, 0, 5)

        lo, hi = CONTROL_LIMITS["kd"]
        self.kd_slider, self.kd_label, self.kd_factor = self._make_float_slider(lo, hi, 0.0, decimals=3, tooltip="Derivative gain")
        self.kd_spin = QDoubleSpinBox(); self.kd_spin.setRange(lo, hi); self.kd_spin.setValue(0.0); self.kd_spin.hide()
        gains_grid.addWidget(self._label("Kd (D)"), 1, 0)
        gains_grid.addWidget(self.kd_slider, 1, 1)
        gains_grid.addWidget(self.kd_label, 1, 2)
        # Gain alias hidden
        self.gain_spin = QDoubleSpinBox(); self.gain_spin.setRange(0.02, 0.50); self.gain_spin.setValue(0.15); self.gain_spin.hide()
        # Hidden gain label to keep grid
        gains_grid.addWidget(self._label("Gain alias"), 1, 3)
        # dummy slider for gain alias? just show kd is enough, keep hidden
        self._gain_alias_slider = self.kp_slider  # alias
        gains_grid.addWidget(QLabel(""), 1, 4, 1, 2)
        layout.addWidget(gains_box)

        # Timing and limits
        limits_box, limits_grid = self._make_group("C — Timing and Limits")
        lo, hi = CONTROL_LIMITS["update_rate_hz"]
        self.rate_slider, self.rate_label, self.rate_factor = self._make_float_slider(lo, hi, 30.0, decimals=1, suffix=" Hz", tooltip="Update rate")
        self.rate_spin = QDoubleSpinBox(); self.rate_spin.setRange(lo, hi); self.rate_spin.setValue(30.0); self.rate_spin.hide()
        limits_grid.addWidget(self._label("Update Rate"), 0, 0)
        limits_grid.addWidget(self.rate_slider, 0, 1)
        limits_grid.addWidget(self.rate_label, 0, 2)
        lo, hi = CONTROL_LIMITS["dead_zone"]
        self.dead_slider, self.dead_label, self.dead_factor = self._make_float_slider(lo, hi, 0.0, decimals=1, suffix=" px", tooltip="Dead zone")
        self.dead_spin = QDoubleSpinBox(); self.dead_spin.setRange(lo, hi); self.dead_spin.setValue(0.0); self.dead_spin.hide()
        limits_grid.addWidget(self._label("Dead Zone"), 0, 3)
        limits_grid.addWidget(self.dead_slider, 0, 4)
        limits_grid.addWidget(self.dead_label, 0, 5)

        lo, hi = CONTROL_LIMITS["output_clamp"]
        self.clamp_slider, self.clamp_label, self.clamp_factor = self._make_float_slider(lo, hi, 100.0, decimals=1, suffix=" px", tooltip="Output clamp")
        self.clamp_spin = QDoubleSpinBox(); self.clamp_spin.setRange(lo, hi); self.clamp_spin.setValue(100.0); self.clamp_spin.hide()
        limits_grid.addWidget(self._label("Output Clamp"), 1, 0)
        limits_grid.addWidget(self.clamp_slider, 1, 1)
        limits_grid.addWidget(self.clamp_label, 1, 2)
        clamp_hint = QLabel("Clamp capped by camera max_slew*dt if tighter.")
        clamp_hint.setWordWrap(True)
        clamp_hint.setStyleSheet("color:#64748b; font-size:10px; font-style:italic;")
        limits_grid.addWidget(clamp_hint, 1, 3, 1, 3)
        layout.addWidget(limits_box)

        # Advanced
        adv_box, adv_grid = self._make_group("D — Feedforward & Adaptive (slider)")
        lo, hi = CONTROL_LIMITS["feedforward_gain"]
        self.ff_slider, self.ff_label, self.ff_factor = self._make_float_slider(lo, hi, 0.0, decimals=2, tooltip="Feedforward 0..1.2")
        self.ff_spin = QDoubleSpinBox(); self.ff_spin.setRange(lo, hi); self.ff_spin.setValue(0.0); self.ff_spin.hide()
        adv_grid.addWidget(self._label("Feedforward"), 0, 0)
        adv_grid.addWidget(self.ff_slider, 0, 1)
        adv_grid.addWidget(self.ff_label, 0, 2)
        lo, hi = CONTROL_LIMITS["adaptive_gain"]
        self.adaptive_slider, self.adaptive_label, self.adaptive_factor = self._make_float_slider(lo, hi, 0.0, decimals=2, tooltip="Adaptive gain")
        self.adaptive_spin = QDoubleSpinBox(); self.adaptive_spin.setRange(lo, hi); self.adaptive_spin.setValue(0.0); self.adaptive_spin.hide()
        adv_grid.addWidget(self._label("Adaptive"), 0, 3)
        adv_grid.addWidget(self.adaptive_slider, 0, 4)
        adv_grid.addWidget(self.adaptive_label, 0, 5)

        lo, hi = CONTROL_LIMITS["derivative_filter"]
        self.dfilter_slider, self.dfilter_label, self.dfilter_factor = self._make_float_slider(lo, hi, 0.80, decimals=2, tooltip="Derivative filter")
        self.dfilter_spin = QDoubleSpinBox(); self.dfilter_spin.setRange(lo, hi); self.dfilter_spin.setValue(0.80); self.dfilter_spin.hide()
        adv_grid.addWidget(self._label("D Filter"), 1, 0)
        adv_grid.addWidget(self.dfilter_slider, 1, 1)
        adv_grid.addWidget(self.dfilter_label, 1, 2)
        lo, hi = CONTROL_LIMITS["smith_latency_ms"]
        self.smith_slider, self.smith_label = self._make_int_slider(int(lo), int(hi), 0, tooltip="Smith predictor ms")
        self.smith_spin = QDoubleSpinBox(); self.smith_spin.setRange(lo, hi); self.smith_spin.setValue(0); self.smith_spin.hide()
        adv_grid.addWidget(self._label("Smith (ms)"), 1, 3)
        adv_grid.addWidget(self.smith_slider, 1, 4)
        adv_grid.addWidget(self.smith_label, 1, 5)

        lo, hi = CONTROL_LIMITS["setpoint_weight"]
        self.setpoint_slider, self.setpoint_label, self.setpoint_factor = self._make_float_slider(lo, hi, 1.0, decimals=2, tooltip="Setpoint weight 0..1")
        self.setpoint_spin = QDoubleSpinBox(); self.setpoint_spin.setRange(lo, hi); self.setpoint_spin.setValue(1.0); self.setpoint_spin.hide()
        adv_grid.addWidget(self._label("Setpoint W"), 2, 0)
        adv_grid.addWidget(self.setpoint_slider, 2, 1)
        adv_grid.addWidget(self.setpoint_label, 2, 2)
        ff_hint = QLabel("Use 0.45/12ms for 80 px/s curved. Setpoint 0.7-1.0 reduces overshoot.")
        ff_hint.setWordWrap(True)
        ff_hint.setStyleSheet("color:#64748b; font-size:10px; font-style:italic;")
        adv_grid.addWidget(ff_hint, 3, 0, 1, 6)
        layout.addWidget(adv_box)

        # Reset button
        self.btn_reset = self._make_reset_button("Reset Control")
        layout.addWidget(self.btn_reset)
        layout.addStretch()

        # Wiring
        self.type_combo.currentTextChanged.connect(self._on_type_changed)
        for sld, spin, factor in [
            (self.kp_slider, self.kp_spin, self.kp_factor),
            (self.ki_slider, self.ki_spin, self.ki_factor),
            (self.kd_slider, self.kd_spin, self.kd_factor),
            (self.rate_slider, self.rate_spin, self.rate_factor),
            (self.dead_slider, self.dead_spin, self.dead_factor),
            (self.clamp_slider, self.clamp_spin, self.clamp_factor),
            (self.ff_slider, self.ff_spin, self.ff_factor),
            (self.adaptive_slider, self.adaptive_spin, self.adaptive_factor),
            (self.dfilter_slider, self.dfilter_spin, self.dfilter_factor),
            (self.setpoint_slider, self.setpoint_spin, self.setpoint_factor),
        ]:
            sld.valueChanged.connect(lambda v, sp=spin, f=factor: self._sync_float(v, sp, f))
        self.smith_slider.valueChanged.connect(lambda v: self._sync_int(v, self.smith_spin))
        self.btn_reset.clicked.connect(self._on_reset)

    def _sync_float(self, int_val: int, spin: QDoubleSpinBox, factor: int):
        val = int_val / factor
        spin.blockSignals(True)
        spin.setValue(float(val))
        spin.blockSignals(False)
        # Gain alias sync
        if spin is self.kp_spin:
            self.gain_spin.blockSignals(True)
            self.gain_spin.setValue(float(np.clip(val, 0.02, 0.50)))
            self.gain_spin.blockSignals(False)
        self._emit_config()

    def _sync_int(self, int_val: int, spin: QDoubleSpinBox):
        spin.blockSignals(True)
        spin.setValue(float(int_val))
        spin.blockSignals(False)
        self._emit_config()

    def _on_type_changed(self, txt: str) -> None:
        txt = str(txt)
        self.ki_slider.setEnabled(txt in ("PI", "PID"))
        self.ki_spin.setEnabled(txt in ("PI", "PID"))
        self.ki_label.setEnabled(txt in ("PI", "PID"))
        self.kd_slider.setEnabled(txt == "PID")
        self.kd_spin.setEnabled(txt == "PID")
        self.kd_label.setEnabled(txt == "PID")
        # Highlight disabled as deactivated
        self._emit_config()

    def _on_gain_alias(self, v: float) -> None:
        if abs(self.kp_spin.value() - float(v)) > 1e-9:
            self.kp_slider.blockSignals(True)
            self.kp_slider.setValue(int(round(float(v) * self.kp_factor)))
            self.kp_slider.blockSignals(False)
            self.kp_spin.blockSignals(True)
            self.kp_spin.setValue(float(v))
            self.kp_spin.blockSignals(False)

    def _on_kp_sync_gain(self, v: float) -> None:
        if abs(self.gain_spin.value() - float(v)) > 1e-9:
            gv = float(np.clip(float(v), 0.02, 0.50))
            self.gain_spin.blockSignals(True)
            self.gain_spin.setValue(gv)
            self.gain_spin.blockSignals(False)

    def _on_reset(self):
        self.set_config(ControllerConfig().validate(), emit=True)

    def collect_config(self) -> ControllerConfig:
        return ControllerConfig(
            controller_type=str(self.type_combo.currentText()),
            kp=float(self.kp_slider.value() / self.kp_factor),
            ki=float(self.ki_slider.value() / self.ki_factor),
            kd=float(self.kd_slider.value() / self.kd_factor),
            update_rate_hz=float(self.rate_slider.value() / self.rate_factor),
            dead_zone=float(self.dead_slider.value() / self.dead_factor),
            output_clamp=float(self.clamp_slider.value() / self.clamp_factor),
            feedforward_gain=float(self.ff_slider.value() / self.ff_factor),
            adaptive_gain=float(self.adaptive_slider.value() / self.adaptive_factor),
            derivative_filter=float(self.dfilter_slider.value() / self.dfilter_factor),
            smith_latency_ms=float(self.smith_slider.value()),
            setpoint_weight=float(self.setpoint_slider.value() / self.setpoint_factor),
        ).validate()

    def set_config(self, cfg: ControllerConfig, emit: bool = False) -> None:
        cfg = cfg.validate()
        widgets = [self.type_combo, self.kp_slider, self.ki_slider, self.kd_slider, self.rate_slider, self.dead_slider, self.clamp_slider,
                   self.ff_slider, self.adaptive_slider, self.dfilter_slider, self.smith_slider, self.setpoint_slider]
        for w in widgets:
            w.blockSignals(True)
        spins = [self.kp_spin, self.ki_spin, self.kd_spin, self.rate_spin, self.dead_spin, self.clamp_spin, self.gain_spin,
                 self.ff_spin, self.adaptive_spin, self.dfilter_spin, self.smith_spin, self.setpoint_spin]
        for s in spins:
            s.blockSignals(True)
        try:
            idx = self.type_combo.findText(cfg.controller_type)
            if idx >= 0:
                self.type_combo.setCurrentIndex(idx)
            self.kp_slider.setValue(int(round(float(cfg.kp) * self.kp_factor))); self.kp_spin.setValue(float(cfg.kp)); self.kp_label.setText(f"{float(cfg.kp):.3f}")
            self.ki_slider.setValue(int(round(float(cfg.ki) * self.ki_factor))); self.ki_spin.setValue(float(cfg.ki)); self.ki_label.setText(f"{float(cfg.ki):.3f}")
            self.kd_slider.setValue(int(round(float(cfg.kd) * self.kd_factor))); self.kd_spin.setValue(float(cfg.kd)); self.kd_label.setText(f"{float(cfg.kd):.3f}")
            self.rate_slider.setValue(int(round(float(cfg.update_rate_hz) * self.rate_factor))); self.rate_spin.setValue(float(cfg.update_rate_hz)); self.rate_label.setText(f"{float(cfg.update_rate_hz):.1f} Hz")
            self.dead_slider.setValue(int(round(float(cfg.dead_zone) * self.dead_factor))); self.dead_spin.setValue(float(cfg.dead_zone)); self.dead_label.setText(f"{float(cfg.dead_zone):.1f} px")
            self.clamp_slider.setValue(int(round(float(cfg.output_clamp) * self.clamp_factor))); self.clamp_spin.setValue(float(cfg.output_clamp)); self.clamp_label.setText(f"{float(cfg.output_clamp):.1f} px")
            self.ff_slider.setValue(int(round(float(getattr(cfg, "feedforward_gain", 0.0)) * self.ff_factor))); self.ff_spin.setValue(float(getattr(cfg, "feedforward_gain", 0.0))); self.ff_label.setText(f"{float(getattr(cfg, 'feedforward_gain', 0.0)):.2f}")
            self.adaptive_slider.setValue(int(round(float(getattr(cfg, "adaptive_gain", 0.0)) * self.adaptive_factor))); self.adaptive_spin.setValue(float(getattr(cfg, "adaptive_gain", 0.0))); self.adaptive_label.setText(f"{float(getattr(cfg, 'adaptive_gain', 0.0)):.2f}")
            self.dfilter_slider.setValue(int(round(float(getattr(cfg, "derivative_filter", 0.80)) * self.dfilter_factor))); self.dfilter_spin.setValue(float(getattr(cfg, "derivative_filter", 0.80))); self.dfilter_label.setText(f"{float(getattr(cfg, 'derivative_filter', 0.80)):.2f}")
            self.smith_slider.setValue(int(getattr(cfg, "smith_latency_ms", 0.0))); self.smith_spin.setValue(float(getattr(cfg, "smith_latency_ms", 0.0))); self.smith_label.setText(f"{int(getattr(cfg, 'smith_latency_ms', 0.0))} ms")
            self.setpoint_slider.setValue(int(round(float(getattr(cfg, "setpoint_weight", 1.0)) * self.setpoint_factor))); self.setpoint_spin.setValue(float(getattr(cfg, "setpoint_weight", 1.0))); self.setpoint_label.setText(f"{float(getattr(cfg, 'setpoint_weight', 1.0)):.2f}")
            self.gain_spin.setValue(float(np.clip(cfg.kp, 0.02, 0.50)))
            self._on_type_changed(cfg.controller_type)
        finally:
            for w in widgets:
                w.blockSignals(False)
            for s in spins:
                s.blockSignals(False)
        if emit:
            self._emit_config()

    def _emit_config(self) -> None:
        try:
            cfg = self.collect_config()
            self.configChanged.emit(cfg)
        except Exception:
            pass

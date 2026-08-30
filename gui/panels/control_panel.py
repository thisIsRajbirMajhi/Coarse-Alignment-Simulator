"""
Module: gui.panels.control_panel
Purpose: Controller controls — type, gains, update rate, dead zone, output clamp.
Public API: ControlPanel
Groups:
  A) Controller Type — P / PI / PID
  B) Gains — Kp, Ki, Kd (Ki/Kd enabled per type)
  C) Timing & Limits — Update rate (Hz), Dead zone (px), Output clamp (px/tick)
Notes: Modular, well-commented, HOT via configChanged. Single source ControllerConfig.
       Output clamp respects camera max_slew — panel shows hint "should be ≤ camera slew*dt".
"""

import numpy as np
from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtWidgets import (
    QComboBox,
    QDoubleSpinBox,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from control.config import ControllerConfig
from control.constants import CONTROL_LIMITS, CONTROLLER_TYPES

# ============================================================
# SECTION: ControlPanel — PID controller tuning
# ============================================================

class ControlPanel(QWidget):
    """
    Control tab — PID tuning for pan-tilt.

    Exposed for MainWindow:
      type_combo, kp_spin, ki_spin, kd_spin, rate_spin, dead_spin, clamp_spin
      + gain_slider/spin aliases for backward compat (kp)
    Signal:
      configChanged(ControllerConfig) — on any param change (HOT)
    """

    configChanged = pyqtSignal(object)

    def __init__(self, initial: ControllerConfig | None = None, parent=None):
        super().__init__(parent)
        self._initial = (initial or ControllerConfig()).validate()
        self._build_ui()
        self.set_config(self._initial, emit=False)

    # ========================================================
    # Build UI — 3 groups
    # ========================================================

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(10)

        # ----------------------------------------------------
        # Group A: Controller Type
        # ----------------------------------------------------
        type_box = QGroupBox("A — Controller Type")
        type_layout = QGridLayout(type_box)
        type_layout.setContentsMargins(12, 18, 12, 12)
        type_layout.setHorizontalSpacing(8)
        type_layout.setVerticalSpacing(8)
        type_layout.setColumnStretch(1, 1)

        type_layout.addWidget(self._label("Type"), 0, 0)
        self.type_combo = QComboBox()
        self.type_combo.addItems(CONTROLLER_TYPES)
        self.type_combo.setToolTip("Controller type — P (proportional), PI (+integral), PID (+derivative). PID matters when camera has slew/latency (overshoot). P suffices for brief.")
        self.type_combo.setMinimumHeight(26)
        type_layout.addWidget(self.type_combo, 0, 1)

        hint = QLabel("P: simple, no windup. PI: fixes steady offset. PID: damps overshoot with slew/latency.")
        hint.setWordWrap(True)
        hint.setStyleSheet("color:#64748b; font-size:10px; font-style:italic;")
        type_layout.addWidget(hint, 1, 0, 1, 2)

        layout.addWidget(type_box)

        # ----------------------------------------------------
        # Group B: Gains — Kp, Ki, Kd
        # ----------------------------------------------------
        gains_box = QGroupBox("B — Gains")
        gains_grid = QGridLayout(gains_box)
        gains_grid.setContentsMargins(12, 18, 12, 12)
        gains_grid.setHorizontalSpacing(8)
        gains_grid.setVerticalSpacing(8)
        gains_grid.setColumnStretch(1, 1)
        gains_grid.setColumnStretch(3, 1)

        # Kp — how strongly current error drives correction
        gains_grid.addWidget(self._label("Kp (P)"), 0, 0)
        self.kp_spin = QDoubleSpinBox()
        lo, hi = CONTROL_LIMITS["kp"]
        self.kp_spin.setRange(lo, hi); self.kp_spin.setSingleStep(0.01); self.kp_spin.setDecimals(3)
        self.kp_spin.setToolTip("Proportional gain — how strongly current error drives correction (px error → px correction).")
        self.kp_spin.setMinimumHeight(26)
        gains_grid.addWidget(self.kp_spin, 0, 1)

        # Ki — corrects persistent steady-state offset (accumulated error)
        gains_grid.addWidget(self._label("Ki (I)"), 0, 2)
        self.ki_spin = QDoubleSpinBox()
        lo, hi = CONTROL_LIMITS["ki"]
        self.ki_spin.setRange(lo, hi); self.ki_spin.setSingleStep(0.005); self.ki_spin.setDecimals(3)
        self.ki_spin.setToolTip("Integral gain — corrects persistent steady-state offset (∫e·dt).")
        self.ki_spin.setMinimumHeight(26)
        gains_grid.addWidget(self.ki_spin, 0, 3)

        # Kd — dampens oscillation by reacting to rate-of-change
        gains_grid.addWidget(self._label("Kd (D)"), 1, 0)
        self.kd_spin = QDoubleSpinBox()
        lo, hi = CONTROL_LIMITS["kd"]
        self.kd_spin.setRange(lo, hi); self.kd_spin.setSingleStep(0.005); self.kd_spin.setDecimals(3)
        self.kd_spin.setToolTip("Derivative gain — dampens oscillation/overshoot by reacting to de/dt.")
        self.kd_spin.setMinimumHeight(26)
        gains_grid.addWidget(self.kd_spin, 1, 1)

        # Legacy aliases for MainWindow: gain_slider/spin → kp
        # Provide dummy slider/spin that mirror kp for backward compat
        # (Old code did gain_slider 2..50 → 0.02..0.50)
        gains_grid.addWidget(self._label("Gain alias"), 1, 2)
        self.gain_spin = QDoubleSpinBox()
        self.gain_spin.setRange(0.02, 0.50); self.gain_spin.setSingleStep(0.01); self.gain_spin.setDecimals(2)
        self.gain_spin.setToolTip("Legacy alias for Kp (0.02..0.50) — kept for code that reads gain_spin/gain_slider.")
        self.gain_spin.setMinimumHeight(26)
        gains_grid.addWidget(self.gain_spin, 1, 3)

        layout.addWidget(gains_box)

        # ----------------------------------------------------
        # Group C: Timing & Limits — update rate, dead zone, clamp
        # ----------------------------------------------------
        limits_box = QGroupBox("C — Timing & Limits")
        limits_grid = QGridLayout(limits_box)
        limits_grid.setContentsMargins(12, 18, 12, 12)
        limits_grid.setHorizontalSpacing(8)
        limits_grid.setVerticalSpacing(8)
        limits_grid.setColumnStretch(1, 1)
        limits_grid.setColumnStretch(3, 1)

        limits_grid.addWidget(self._label("Update Rate"), 0, 0)
        self.rate_spin = QDoubleSpinBox()
        lo, hi = CONTROL_LIMITS["update_rate_hz"]
        self.rate_spin.setRange(lo, hi); self.rate_spin.setSingleStep(1.0); self.rate_spin.setDecimals(1)
        self.rate_spin.setSuffix(" Hz")
        self.rate_spin.setToolTip("Control update rate — Hz, how often controller computes correction (can differ from render FPS). Interval = 1/Hz.")
        self.rate_spin.setMinimumHeight(26)
        limits_grid.addWidget(self.rate_spin, 0, 1)

        limits_grid.addWidget(self._label("Dead Zone"), 0, 2)
        self.dead_spin = QDoubleSpinBox()
        lo, hi = CONTROL_LIMITS["dead_zone"]
        self.dead_spin.setRange(lo, hi); self.dead_spin.setSingleStep(0.5); self.dead_spin.setDecimals(1)
        self.dead_spin.setSuffix(" px")
        self.dead_spin.setToolTip("Dead zone — minimum error (px) before camera moves; avoids micro-jitter when centered.")
        self.dead_spin.setMinimumHeight(26)
        limits_grid.addWidget(self.dead_spin, 0, 3)

        limits_grid.addWidget(self._label("Output Clamp"), 1, 0)
        self.clamp_spin = QDoubleSpinBox()
        lo, hi = CONTROL_LIMITS["output_clamp"]
        self.clamp_spin.setRange(lo, hi); self.clamp_spin.setSingleStep(5.0); self.clamp_spin.setDecimals(1)
        self.clamp_spin.setSuffix(" px")
        self.clamp_spin.setToolTip("Max correction per tick — should respect camera max_slew_rate*dt, not double-define it. Clamped to camera limit if tighter.")
        self.clamp_spin.setMinimumHeight(26)
        limits_grid.addWidget(self.clamp_spin, 1, 1)

        # Hint for clamp vs camera
        clamp_hint = QLabel("Output clamp is capped by camera max_slew*dt if tighter — no double define.")
        clamp_hint.setWordWrap(True)
        clamp_hint.setStyleSheet("color:#64748b; font-size:10px; font-style:italic;")
        limits_grid.addWidget(clamp_hint, 1, 2, 1, 2)

        layout.addWidget(limits_box)
        layout.addStretch()

        # Wire — all emit configChanged, with Ki/Kd enable per type
        self.type_combo.currentTextChanged.connect(self._on_type_changed)
        for w in [self.kp_spin, self.ki_spin, self.kd_spin, self.rate_spin, self.dead_spin, self.clamp_spin, self.gain_spin]:
            w.valueChanged.connect(self._emit_config)
        # Gain alias syncs to Kp
        self.gain_spin.valueChanged.connect(self._on_gain_alias)
        self.kp_spin.valueChanged.connect(self._on_kp_sync_gain)

    # ========================================================
    # Helpers
    # ========================================================

    def _label(self, text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setStyleSheet("color:#334155; font-size:11px;")
        return lbl

    def _on_type_changed(self, txt: str) -> None:
        # Enable Ki/Kd per type
        txt = str(txt)
        self.ki_spin.setEnabled(txt in ("PI", "PID"))
        self.kd_spin.setEnabled(txt == "PID")
        self._emit_config()

    def _on_gain_alias(self, v: float) -> None:
        # Gain alias → Kp, avoid loop
        if abs(self.kp_spin.value() - float(v)) > 1e-9:
            self.kp_spin.blockSignals(True)
            self.kp_spin.setValue(float(v))
            self.kp_spin.blockSignals(False)
        self._emit_config()

    def _on_kp_sync_gain(self, v: float) -> None:
        if abs(self.gain_spin.value() - float(v)) > 1e-9:
            # Clamp gain alias to 0.02..0.50 range
            gv = float(np.clip(float(v), 0.02, 0.50))
            self.gain_spin.blockSignals(True)
            self.gain_spin.setValue(gv)
            self.gain_spin.blockSignals(False)

    # ========================================================
    # Config ↔ UI
    # ========================================================

    def collect_config(self) -> ControllerConfig:
        return ControllerConfig(
            controller_type=str(self.type_combo.currentText()),
            kp=float(self.kp_spin.value()),
            ki=float(self.ki_spin.value()),
            kd=float(self.kd_spin.value()),
            update_rate_hz=float(self.rate_spin.value()),
            dead_zone=float(self.dead_spin.value()),
            output_clamp=float(self.clamp_spin.value()),
        ).validate()

    def set_config(self, cfg: ControllerConfig, emit: bool = False) -> None:
        cfg = cfg.validate()
        for w in [self.type_combo, self.kp_spin, self.ki_spin, self.kd_spin, self.rate_spin, self.dead_spin, self.clamp_spin, self.gain_spin]:
            w.blockSignals(True)
        try:
            idx = self.type_combo.findText(cfg.controller_type)
            if idx >= 0:
                self.type_combo.setCurrentIndex(idx)
            self.kp_spin.setValue(float(cfg.kp))
            self.ki_spin.setValue(float(cfg.ki))
            self.kd_spin.setValue(float(cfg.kd))
            self.rate_spin.setValue(float(cfg.update_rate_hz))
            self.dead_spin.setValue(float(cfg.dead_zone))
            self.clamp_spin.setValue(float(cfg.output_clamp))
            self.gain_spin.setValue(float(np.clip(cfg.kp, 0.02, 0.50)))
            self._on_type_changed(cfg.controller_type)
        finally:
            for w in [self.type_combo, self.kp_spin, self.ki_spin, self.kd_spin, self.rate_spin, self.dead_spin, self.clamp_spin, self.gain_spin]:
                w.blockSignals(False)
        if emit:
            self._emit_config()

    def _emit_config(self) -> None:
        try:
            cfg = self.collect_config()
            self.configChanged.emit(cfg)
        except: pass

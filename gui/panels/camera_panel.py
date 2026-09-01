"""
Module: gui.panels.camera_panel
Purpose: Camera controls — grouped into FOV/Optics, Pan-Tilt Mechanics, Display, Units.
Public API: CameraPanel
Params (11):
  FOV/Optics: fov_width, fov_height
  Pan-Tilt: pan_min/max, tilt_min/max, home_pan/tilt, max_slew_rate, resolution, latency_ms
  Display: viewport_width/height, god_width/height
  Units: pixel_scale_mrad (px → mrad/µrad)
Notes: Modular, well-commented, HOT via configChanged. Each section is a QGroupBox.
"""

from PyQt5.QtCore import Qt, pyqtSignal
from gui.panels.base import BaseConfigPanel
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

# ============================================================
# SECTION: CameraPanel — 11 camera/viewport params (grouped)
# ============================================================

class CameraPanel(BaseConfigPanel):
    """
    Camera tab — 4 grouped sections, 11 params.

    Exposed for MainWindow HOT wiring (back-compat aliases):
      fov_w_spin, fov_h_spin,
      pan_min_spin, pan_max_spin, tilt_min_spin, tilt_max_spin,
      home_pan_spin, home_tilt_spin, slew_spin, res_spin, latency_spin,
      viewport_w_spin, viewport_h_spin, god_w_spin, god_h_spin,
      scale_spin, gain_slider, gain_spin
    Signals:
      configChanged() — on any of 11 params or gain change (debounced HOT)
    """

    configChanged = pyqtSignal()

    def __init__(
        self,
        initial: CameraConfig | None = None,
        scene_bounds: tuple[int,int] = (1000, 1000),
        parent=None,
    ):
        super().__init__(parent)
        self._scene_bounds = scene_bounds
        self._initial = (initial or CameraConfig()).validate(scene_bounds)
        self._build_ui()
        self.set_config(self._initial, emit=False)

    # ========================================================
    # Build UI — 4 groups
    # ========================================================

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(10)

        # ----------------------------------------------------
        # Group A: Field of View / Optics
        # ----------------------------------------------------
        fov_box = QGroupBox("⬢  A  —  FIELD OF VIEW  •  OPTICS")
        fov_grid = QGridLayout(fov_box)
        fov_grid.setContentsMargins(12, 18, 12, 12)
        fov_grid.setHorizontalSpacing(8)
        fov_grid.setVerticalSpacing(8)
        fov_grid.setColumnStretch(1, 1)
        fov_grid.setColumnStretch(3, 1)
        fov_grid.addWidget(self._label("FOV W"), 0, 0)
        self.fov_w_spin = QSpinBox(); self.fov_w_spin.setRange(*CAMERA_LIMITS["fov_width"]); self.fov_w_spin.setSingleStep(10); self.fov_w_spin.setSuffix(" px"); self.fov_w_spin.setToolTip("FOV width — actual sensor resolution (px), independent of display size."); self.fov_w_spin.setMinimumHeight(26)
        fov_grid.addWidget(self.fov_w_spin, 0, 1)
        fov_grid.addWidget(self._label("H"), 0, 2)
        self.fov_h_spin = QSpinBox(); self.fov_h_spin.setRange(*CAMERA_LIMITS["fov_height"]); self.fov_h_spin.setSingleStep(10); self.fov_h_spin.setSuffix(" px"); self.fov_h_spin.setToolTip("FOV height — sensor resolution."); self.fov_h_spin.setMinimumHeight(26)
        fov_grid.addWidget(self.fov_h_spin, 0, 3)
        layout.addWidget(fov_box)

        # ----------------------------------------------------
        # Group B: Pan-Tilt Mechanics
        # ----------------------------------------------------
        mech_box = QGroupBox("◈  B  —  PAN-TILT MECHANICS")
        mech_grid = QGridLayout(mech_box)
        mech_grid.setContentsMargins(12, 18, 12, 12)
        mech_grid.setHorizontalSpacing(8)
        mech_grid.setVerticalSpacing(8)
        mech_grid.setColumnStretch(1, 1)
        mech_grid.setColumnStretch(3, 1)

        # Pan range
        mech_grid.addWidget(self._label("Pan Min"), 0, 0)
        self.pan_min_spin = QSpinBox(); self.pan_min_spin.setRange(0, MAX_RES); self.pan_min_spin.setToolTip("Pan minimum — mechanical limit (px scene). Auto = FOV/2 if 0."); self.pan_min_spin.setMinimumHeight(26)
        mech_grid.addWidget(self.pan_min_spin, 0, 1)
        mech_grid.addWidget(self._label("Max"), 0, 2)
        self.pan_max_spin = QSpinBox(); self.pan_max_spin.setRange(0, MAX_RES); self.pan_max_spin.setToolTip("Pan maximum — auto = W - FOV/2 if 0."); self.pan_max_spin.setMinimumHeight(26)
        mech_grid.addWidget(self.pan_max_spin, 0, 3)

        # Tilt range
        mech_grid.addWidget(self._label("Tilt Min"), 1, 0)
        self.tilt_min_spin = QSpinBox(); self.tilt_min_spin.setRange(0, MAX_RES); self.tilt_min_spin.setMinimumHeight(26)
        mech_grid.addWidget(self.tilt_min_spin, 1, 1)
        mech_grid.addWidget(self._label("Max"), 1, 2)
        self.tilt_max_spin = QSpinBox(); self.tilt_max_spin.setRange(0, MAX_RES); self.tilt_max_spin.setMinimumHeight(26)
        mech_grid.addWidget(self.tilt_max_spin, 1, 3)

        # Home / centre
        mech_grid.addWidget(self._label("Home Pan"), 2, 0)
        self.home_pan_spin = QSpinBox(); self.home_pan_spin.setRange(0, MAX_RES); self.home_pan_spin.setToolTip("Home/Centre pan — default on start/reset (None → W/2)."); self.home_pan_spin.setMinimumHeight(26)
        mech_grid.addWidget(self.home_pan_spin, 2, 1)
        mech_grid.addWidget(self._label("Tilt"), 2, 2)
        self.home_tilt_spin = QSpinBox(); self.home_tilt_spin.setRange(0, MAX_RES); self.home_tilt_spin.setToolTip("Home tilt — None → H/2."); self.home_tilt_spin.setMinimumHeight(26)
        mech_grid.addWidget(self.home_tilt_spin, 2, 3)

        # Slew rate
        mech_grid.addWidget(self._label("Slew Rate"), 3, 0)
        self.slew_spin = QSpinBox(); lo,hi = CAMERA_LIMITS["max_slew_rate"]; self.slew_spin.setRange(int(lo), int(hi)); self.slew_spin.setSuffix(" px/s"); self.slew_spin.setToolTip("Max slew rate — caps per-tick delta (|Δ| ≤ rate*dt), simulates actuator limit."); self.slew_spin.setMinimumHeight(26)
        mech_grid.addWidget(self.slew_spin, 3, 1)
        # Resolution
        mech_grid.addWidget(self._label("Resolution"), 3, 2)
        self.res_spin = QDoubleSpinBox(); lo,hi = CAMERA_LIMITS["resolution"]; self.res_spin.setRange(lo, hi); self.res_spin.setSingleStep(0.05); self.res_spin.setDecimals(2); self.res_spin.setSuffix(" px"); self.res_spin.setToolTip("Positional resolution — smallest step, quantizes moves (round(Δ/res)*res)."); self.res_spin.setMinimumHeight(26)
        mech_grid.addWidget(self.res_spin, 3, 3)

        # Latency
        mech_grid.addWidget(self._label("Latency"), 4, 0)
        self.latency_spin = QSpinBox(); lo,hi = CAMERA_LIMITS["latency_ms"]; self.latency_spin.setRange(int(lo), int(hi)); self.latency_spin.setSuffix(" ms"); self.latency_spin.setToolTip("Response latency — queued delay between commanded move and execution (0 = immediate)."); self.latency_spin.setMinimumHeight(26)
        mech_grid.addWidget(self.latency_spin, 4, 1)
        # Spacer
        mech_grid.addWidget(QLabel(""), 4, 2, 1, 2)

        layout.addWidget(mech_box)

        # ----------------------------------------------------
        # Group C: Display — viewport / God view on-screen sizes
        # ----------------------------------------------------
        disp_box = QGroupBox("▣  C  —  DISPLAY  •  ON-SCREEN RENDERING")
        disp_grid = QGridLayout(disp_box)
        disp_grid.setContentsMargins(12, 18, 12, 12)
        disp_grid.setHorizontalSpacing(8)
        disp_grid.setVerticalSpacing(8)
        disp_grid.setColumnStretch(1, 1)
        disp_grid.setColumnStretch(3, 1)
        disp_grid.addWidget(self._label("Viewport W"), 0, 0)
        self.viewport_w_spin = QSpinBox(); lo,hi = DISPLAY_LIMITS["viewport_width"]; self.viewport_w_spin.setRange(lo, hi); self.viewport_w_spin.setSuffix(" px"); self.viewport_w_spin.setToolTip("On-screen size for FOV feed — independent of FOV resolution (scaled)."); self.viewport_w_spin.setMinimumHeight(26)
        disp_grid.addWidget(self.viewport_w_spin, 0, 1)
        disp_grid.addWidget(self._label("H"), 0, 2)
        self.viewport_h_spin = QSpinBox(); lo,hi = DISPLAY_LIMITS["viewport_height"]; self.viewport_h_spin.setRange(lo, hi); self.viewport_h_spin.setSuffix(" px"); self.viewport_h_spin.setMinimumHeight(26)
        disp_grid.addWidget(self.viewport_h_spin, 0, 3)

        disp_grid.addWidget(self._label("God W"), 1, 0)
        self.god_w_spin = QSpinBox(); lo,hi = DISPLAY_LIMITS["god_width"]; self.god_w_spin.setRange(lo, hi); self.god_w_spin.setSuffix(" px"); self.god_w_spin.setMinimumHeight(26)
        disp_grid.addWidget(self.god_w_spin, 1, 1)
        disp_grid.addWidget(self._label("H"), 1, 2)
        self.god_h_spin = QSpinBox(); lo,hi = DISPLAY_LIMITS["god_height"]; self.god_h_spin.setRange(lo, hi); self.god_h_spin.setSuffix(" px"); self.god_h_spin.setMinimumHeight(26)
        disp_grid.addWidget(self.god_h_spin, 1, 3)
        layout.addWidget(disp_box)

        # ----------------------------------------------------
        # Group D: Units / Reporting — pixel → angle
        # ----------------------------------------------------
        units_box = QGroupBox("◎  D  —  UNITS  •  PIXEL → ANGLE")
        units_grid = QGridLayout(units_box)
        units_grid.setContentsMargins(12, 18, 12, 12)
        units_grid.setHorizontalSpacing(8)
        units_grid.setVerticalSpacing(8)
        units_grid.addWidget(self._label("Scale"), 0, 0)
        self.scale_spin = QDoubleSpinBox(); lo,hi = CAMERA_LIMITS["pixel_scale_mrad"]; self.scale_spin.setRange(lo, hi); self.scale_spin.setSingleStep(0.005); self.scale_spin.setDecimals(3); self.scale_spin.setSuffix(" mrad/px"); self.scale_spin.setToolTip("Pixel to angle — converts tracking error px → mrad/µrad for FSOC reporting (e.g., 0.035 mrad/px = 35 µrad)."); self.scale_spin.setMinimumHeight(26)
        units_grid.addWidget(self.scale_spin, 0, 1)
        self.scale_hint = QLabel("35 µrad/px → 10 px = 0.350 mrad = 350 µrad")
        self.scale_hint.setStyleSheet("color:#64748b; font-size:10px; font-style:italic;")
        units_grid.addWidget(self.scale_hint, 0, 2, 1, 2)
        layout.addWidget(units_box)

        # ----------------------------------------------------
        # Group E: Control Gain (kept here for cohesion)
        # ----------------------------------------------------
        gain_box = QGroupBox("⟡  E  —  CONTROLLER GAIN")
        gain_box.setStyleSheet("QGroupBox { padding-top: 14px; }")
        gain_layout = QVBoxLayout(gain_box)
        gain_layout.setContentsMargins(10, 14, 10, 10)
        gain_layout.setSpacing(6)
        self._add_gain_row(gain_layout)
        layout.addWidget(gain_box)

        layout.addStretch()
        self._wire_signals()

    def _add_gain_row(self, layout: QVBoxLayout) -> None:
        lab = QLabel("Controller gain")
        lab.setStyleSheet("color:#334155; font-weight:500;")
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
        lbl.setStyleSheet("color:#334155; font-size:11px; font-weight:600;")
        return lbl


    # ========================================================
    # Wiring — emit on any change (HOT, debounced in MainWindow)
    # ========================================================

    def _wire_all(self):
        for w in [self.fov_w_spin, self.fov_h_spin, self.pan_min_spin, self.pan_max_spin, self.tilt_min_spin, self.tilt_max_spin, self.home_pan_spin, self.home_tilt_spin, self.viewport_w_spin, self.viewport_h_spin, self.god_w_spin, self.god_h_spin]:
            w.valueChanged.connect(lambda _: self.configChanged.emit())
        for w in [self.slew_spin, self.latency_spin]:
            w.valueChanged.connect(lambda _: self.configChanged.emit())
        self.res_spin.valueChanged.connect(lambda _: self.configChanged.emit())
        self.scale_spin.valueChanged.connect(self._on_scale_changed)
        self.gain_slider.valueChanged.connect(lambda _: self.configChanged.emit())

    def _on_scale_changed(self, v: float) -> None:
        urad = v * 1000
        self.scale_hint.setText(f"{v:.3f} mrad/px → 10 px = {v*10:.3f} mrad = {urad*10:.0f} µrad")
        self.configChanged.emit()

    # Call after _build_ui to wire
    def _wire_signals(self):
        self._wire_all()

    # ========================================================
    # Config ↔ UI
    # ========================================================

    def collect_config(self) -> CameraConfig:
        # Pan/Tilt ranges: 0 means auto → store as None
        pan_min = int(self.pan_min_spin.value()) if self.pan_min_spin.value() != 0 else None
        pan_max = int(self.pan_max_spin.value()) if self.pan_max_spin.value() != 0 else None
        tilt_min = int(self.tilt_min_spin.value()) if self.tilt_min_spin.value() != 0 else None
        tilt_max = int(self.tilt_max_spin.value()) if self.tilt_max_spin.value() != 0 else None
        home_pan = float(self.home_pan_spin.value()) if self.home_pan_spin.value() != 0 else None
        home_tilt = float(self.home_tilt_spin.value()) if self.home_tilt_spin.value() != 0 else None
        return CameraConfig(
            fov_width=int(self.fov_w_spin.value()),
            fov_height=int(self.fov_h_spin.value()),
            pan_min=pan_min, pan_max=pan_max,
            tilt_min=tilt_min, tilt_max=tilt_max,
            home_pan=home_pan, home_tilt=home_tilt,
            max_slew_rate=float(self.slew_spin.value()),
            resolution=float(self.res_spin.value()),
            latency_ms=int(self.latency_spin.value()),
            viewport_width=int(self.viewport_w_spin.value()),
            viewport_height=int(self.viewport_h_spin.value()),
            god_width=int(self.god_w_spin.value()),
            god_height=int(self.god_h_spin.value()),
            pixel_scale_mrad=float(self.scale_spin.value()),
        ).validate(self._scene_bounds)

    def set_config(self, cfg: CameraConfig, emit: bool = False) -> None:
        cfg = cfg.validate(self._scene_bounds)
        for w in [self.fov_w_spin, self.fov_h_spin, self.pan_min_spin, self.pan_max_spin, self.tilt_min_spin, self.tilt_max_spin, self.home_pan_spin, self.home_tilt_spin, self.slew_spin, self.res_spin, self.latency_spin, self.viewport_w_spin, self.viewport_h_spin, self.god_w_spin, self.god_h_spin, self.scale_spin, self.gain_spin, self.gain_slider]:
            w.blockSignals(True)
        try:
            self.fov_w_spin.setValue(int(cfg.fov_width)); self.fov_h_spin.setValue(int(cfg.fov_height))
            self.pan_min_spin.setValue(int(cfg.pan_min) if cfg.pan_min is not None else 0)
            self.pan_max_spin.setValue(int(cfg.pan_max) if cfg.pan_max is not None else 0)
            self.tilt_min_spin.setValue(int(cfg.tilt_min) if cfg.tilt_min is not None else 0)
            self.tilt_max_spin.setValue(int(cfg.tilt_max) if cfg.tilt_max is not None else 0)
            self.home_pan_spin.setValue(int(cfg.home_pan) if cfg.home_pan is not None else 0)
            self.home_tilt_spin.setValue(int(cfg.home_tilt) if cfg.home_tilt is not None else 0)
            self.slew_spin.setValue(int(cfg.max_slew_rate)); self.res_spin.setValue(float(cfg.resolution)); self.latency_spin.setValue(int(cfg.latency_ms))
            self.viewport_w_spin.setValue(int(cfg.viewport_width)); self.viewport_h_spin.setValue(int(cfg.viewport_height))
            self.god_w_spin.setValue(int(cfg.god_width)); self.god_h_spin.setValue(int(cfg.god_height))
            self.scale_spin.setValue(float(cfg.pixel_scale_mrad))
            self._on_scale_changed(float(cfg.pixel_scale_mrad))
        finally:
            for w in [self.fov_w_spin, self.fov_h_spin, self.pan_min_spin, self.pan_max_spin, self.tilt_min_spin, self.tilt_max_spin, self.home_pan_spin, self.home_tilt_spin, self.slew_spin, self.res_spin, self.latency_spin, self.viewport_w_spin, self.viewport_h_spin, self.god_w_spin, self.god_h_spin, self.scale_spin]:
                w.blockSignals(False)
            self.gain_spin.blockSignals(False); self.gain_slider.blockSignals(False)
        if emit:
            self.configChanged.emit()

    def set_scene_bounds(self, bounds: tuple[int,int]) -> None:
        self._scene_bounds = bounds
        # Update home/range hints but keep current values

    # Ensure wiring after build
    def showEvent(self, e):
        super().showEvent(e)
        # Ensure signals wired once
        try:
            self._wire_signals()
        except: pass

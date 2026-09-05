# gui/panels/camera_panel.py - Camera controls — grouped into FOV/Optics, Pan-Tilt Mechanics, Display, Units

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

    # Build UI — 4 groups

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(10)

        # Camera type header
        type_lbl = QLabel("Camera Type: Monochrome, Focal Plane Array")
        type_lbl.setStyleSheet("color:#374151; font-size:10px; font-weight:600; background:#f9fafb; border:1px solid #e5e7eb; border-radius:4px; padding:4px 8px;")
        layout.addWidget(type_lbl)

        fov_box = QGroupBox("A — Sensor Resolution & FOV (degree)")
        fov_grid = QGridLayout(fov_box)
        fov_grid.setContentsMargins(12, 18, 12, 12)
        fov_grid.setHorizontalSpacing(8)
        fov_grid.setVerticalSpacing(8)
        fov_grid.setColumnStretch(1, 1)
        fov_grid.setColumnStretch(3, 1)
        fov_grid.addWidget(self._label("Res W"), 0, 0)
        self.fov_w_spin = QSpinBox(); self.fov_w_spin.setRange(*CAMERA_LIMITS["fov_width"]); self.fov_w_spin.setSingleStep(10); self.fov_w_spin.setSuffix(" px"); self.fov_w_spin.setToolTip("Sensor resolution width — 640x640 default, user defined."); self.fov_w_spin.setMinimumHeight(26)
        fov_grid.addWidget(self.fov_w_spin, 0, 1)
        fov_grid.addWidget(self._label("H"), 0, 2)
        self.fov_h_spin = QSpinBox(); self.fov_h_spin.setRange(*CAMERA_LIMITS["fov_height"]); self.fov_h_spin.setSingleStep(10); self.fov_h_spin.setSuffix(" px"); self.fov_h_spin.setToolTip("Sensor resolution height."); self.fov_h_spin.setMinimumHeight(26)
        fov_grid.addWidget(self.fov_h_spin, 0, 3)
        fov_grid.addWidget(self._label("FOV X"), 1, 0)
        self.fov_deg_x_spin = QDoubleSpinBox(); lo,hi = CAMERA_LIMITS["fov_deg_x"]; self.fov_deg_x_spin.setRange(lo, hi); self.fov_deg_x_spin.setSingleStep(0.1); self.fov_deg_x_spin.setDecimals(2); self.fov_deg_x_spin.setSuffix(" deg"); self.fov_deg_x_spin.setToolTip("Horizontal FOV in degrees — default 4.0 deg."); self.fov_deg_x_spin.setMinimumHeight(26)
        fov_grid.addWidget(self.fov_deg_x_spin, 1, 1)
        fov_grid.addWidget(self._label("Y"), 1, 2)
        self.fov_deg_y_spin = QDoubleSpinBox(); lo,hi = CAMERA_LIMITS["fov_deg_y"]; self.fov_deg_y_spin.setRange(lo, hi); self.fov_deg_y_spin.setSingleStep(0.1); self.fov_deg_y_spin.setDecimals(2); self.fov_deg_y_spin.setSuffix(" deg"); self.fov_deg_y_spin.setToolTip("Vertical FOV in degrees — default 3.0 deg."); self.fov_deg_y_spin.setMinimumHeight(26)
        fov_grid.addWidget(self.fov_deg_y_spin, 1, 3)
        layout.addWidget(fov_box)

        mech_box = QGroupBox("B — Pan-Tilt Mechanics")
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

        # Home fixed centre
        mech_grid.addWidget(self._label("Home Pan"), 2, 0)
        self.home_pan_spin = QSpinBox(); self.home_pan_spin.setRange(0, MAX_RES); self.home_pan_spin.setEnabled(False); self.home_pan_spin.setToolTip("Initial position fixed to centre — not configurable."); self.home_pan_spin.setMinimumHeight(26)
        mech_grid.addWidget(self.home_pan_spin, 2, 1)
        mech_grid.addWidget(self._label("Tilt"), 2, 2)
        self.home_tilt_spin = QSpinBox(); self.home_tilt_spin.setRange(0, MAX_RES); self.home_tilt_spin.setEnabled(False); self.home_tilt_spin.setToolTip("Initial position fixed to centre."); self.home_tilt_spin.setMinimumHeight(26)
        mech_grid.addWidget(self.home_tilt_spin, 2, 3)
        # Pan/Tilt max speeds in degree/sec
        mech_grid.addWidget(self._label("Pan Speed"), 3, 0)
        self.pan_speed_deg_spin = QDoubleSpinBox(); lo,hi = CAMERA_LIMITS["max_pan_speed_deg"]; self.pan_speed_deg_spin.setRange(lo, hi); self.pan_speed_deg_spin.setSingleStep(0.5); self.pan_speed_deg_spin.setDecimals(1); self.pan_speed_deg_spin.setSuffix(" deg/s"); self.pan_speed_deg_spin.setToolTip("Max pan speed 5-10 deg/sec — actuator limit."); self.pan_speed_deg_spin.setMinimumHeight(26)
        mech_grid.addWidget(self.pan_speed_deg_spin, 3, 1)
        mech_grid.addWidget(self._label("Tilt Speed"), 3, 2)
        self.tilt_speed_deg_spin = QDoubleSpinBox(); lo,hi = CAMERA_LIMITS["max_tilt_speed_deg"]; self.tilt_speed_deg_spin.setRange(lo, hi); self.tilt_speed_deg_spin.setSingleStep(0.5); self.tilt_speed_deg_spin.setDecimals(1); self.tilt_speed_deg_spin.setSuffix(" deg/s"); self.tilt_speed_deg_spin.setToolTip("Max tilt speed 5-10 deg/sec."); self.tilt_speed_deg_spin.setMinimumHeight(26)
        mech_grid.addWidget(self.tilt_speed_deg_spin, 3, 3)
        # Hidden legacy slew for compat (px/s)
        self.slew_spin = QSpinBox(); lo,hi = CAMERA_LIMITS["max_slew_rate"]; self.slew_spin.setRange(int(lo), int(hi)); self.slew_spin.setValue(800); self.slew_spin.hide()

        # Resolution
        mech_grid.addWidget(self._label("Resolution"), 4, 0)
        self.res_spin = QDoubleSpinBox(); lo,hi = CAMERA_LIMITS["resolution"]; self.res_spin.setRange(lo, hi); self.res_spin.setSingleStep(0.05); self.res_spin.setDecimals(2); self.res_spin.setSuffix(" px"); self.res_spin.setToolTip("Positional resolution — smallest step, quantizes moves (round(Δ/res)*res)."); self.res_spin.setMinimumHeight(26)
        mech_grid.addWidget(self.res_spin, 4, 1)
        mech_grid.addWidget(self._label("Latency"), 4, 2)
        self.latency_spin = QSpinBox(); lo,hi = CAMERA_LIMITS["latency_ms"]; self.latency_spin.setRange(int(lo), int(hi)); self.latency_spin.setSuffix(" ms"); self.latency_spin.setToolTip("Response latency — queued delay between commanded move and execution (0 = immediate)."); self.latency_spin.setMinimumHeight(26)
        mech_grid.addWidget(self.latency_spin, 4, 3)

        # Update interval >=20 Hz
        mech_grid.addWidget(self._label("Update Rate"), 5, 0)
        self.update_rate_spin = QSpinBox(); lo,hi = CAMERA_LIMITS["update_rate_hz"]; self.update_rate_spin.setRange(int(lo), int(hi)); self.update_rate_spin.setSuffix(" Hz"); self.update_rate_spin.setToolTip("Camera update interval >=20 Hz — fixed 30Hz default."); self.update_rate_spin.setMinimumHeight(26)
        mech_grid.addWidget(self.update_rate_spin, 5, 1)
        mech_grid.addWidget(QLabel(""), 5, 2, 1, 2)
        # Keep old label for compat hidden
        self.update_rate_lbl = QLabel("30 Hz")
        self.update_rate_lbl.hide()

        layout.addWidget(mech_box)

        disp_box = QGroupBox("C — Display / Screen Sizes")
        disp_grid = QGridLayout(disp_box)
        disp_grid.setContentsMargins(12, 18, 12, 12)
        disp_grid.setHorizontalSpacing(8)
        disp_grid.setVerticalSpacing(8)
        disp_grid.setColumnStretch(1, 1)
        disp_grid.setColumnStretch(3, 1)
        disp_grid.addWidget(self._label("Camera W"), 0, 0)
        self.viewport_w_spin = QSpinBox(); lo,hi = DISPLAY_LIMITS["viewport_width"]; self.viewport_w_spin.setRange(lo, hi); self.viewport_w_spin.setSingleStep(100); self.viewport_w_spin.setSuffix(" px"); self.viewport_w_spin.setToolTip("Camera Screen Size — 2000-5000 configurable."); self.viewport_w_spin.setMinimumHeight(26)
        disp_grid.addWidget(self.viewport_w_spin, 0, 1)
        disp_grid.addWidget(self._label("H"), 0, 2)
        self.viewport_h_spin = QSpinBox(); lo,hi = DISPLAY_LIMITS["viewport_height"]; self.viewport_h_spin.setRange(lo, hi); self.viewport_h_spin.setSingleStep(100); self.viewport_h_spin.setSuffix(" px"); self.viewport_h_spin.setMinimumHeight(26)
        disp_grid.addWidget(self.viewport_h_spin, 0, 3)

        disp_grid.addWidget(self._label("God W"), 1, 0)
        self.god_w_spin = QSpinBox(); lo,hi = DISPLAY_LIMITS["god_width"]; self.god_w_spin.setRange(lo, hi); self.god_w_spin.setSuffix(" px"); self.god_w_spin.setToolTip("God View size — follows World size (2000..5000). Synced to Environment."); self.god_w_spin.setEnabled(False); self.god_w_spin.setMinimumHeight(26)
        disp_grid.addWidget(self.god_w_spin, 1, 1)
        disp_grid.addWidget(self._label("H"), 1, 2)
        self.god_h_spin = QSpinBox(); lo,hi = DISPLAY_LIMITS["god_height"]; self.god_h_spin.setRange(lo, hi); self.god_h_spin.setSuffix(" px"); self.god_h_spin.setToolTip("God View — synced to World size."); self.god_h_spin.setEnabled(False); self.god_h_spin.setMinimumHeight(26)
        disp_grid.addWidget(self.god_h_spin, 1, 3)
        disp_hint = QLabel("God View = World size (2000..5000), Camera Screen 2000..5000 configurable")
        disp_hint.setStyleSheet("color:#6b7280; font-size:10px; font-style:italic;")
        disp_grid.addWidget(disp_hint, 2, 0, 1, 4)
        layout.addWidget(disp_box)

        units_box = QGroupBox("D — Units / Pixel to Angle (degree)")
        units_grid = QGridLayout(units_box)
        units_grid.setContentsMargins(12, 18, 12, 12)
        units_grid.setHorizontalSpacing(8)
        units_grid.setVerticalSpacing(8)
        units_grid.addWidget(self._label("Scale"), 0, 0)
        self.scale_spin = QDoubleSpinBox(); lo,hi = CAMERA_LIMITS["pixel_scale_mrad"]; self.scale_spin.setRange(lo, hi); self.scale_spin.setSingleStep(0.005); self.scale_spin.setDecimals(3); self.scale_spin.setSuffix(" mrad/px"); self.scale_spin.setToolTip("Derived from FOV deg / resolution — degree unit."); self.scale_spin.setEnabled(False); self.scale_spin.setMinimumHeight(26)
        units_grid.addWidget(self.scale_spin, 0, 1)
        self.scale_hint = QLabel("4.0 deg / 640 px = 0.109 mrad/px")
        self.scale_hint.setStyleSheet("color:#6b7280; font-size:10px; font-style:italic;")
        units_grid.addWidget(self.scale_hint, 0, 2, 1, 2)
        layout.addWidget(units_box)

        # — NEW: Realism & Mechanical Errors (previously hidden constants — now user-tunable)
        realism_box = QGroupBox("E — Realism & Mechanical Errors")
        realism_grid = QGridLayout(realism_box)
        realism_grid.setContentsMargins(12, 18, 12, 12)
        realism_grid.setHorizontalSpacing(8)
        realism_grid.setVerticalSpacing(8)
        realism_grid.setColumnStretch(1, 1)
        realism_grid.setColumnStretch(3, 1)

        realism_grid.addWidget(self._label("Max Accel"), 0, 0)
        self.accel_spin = QDoubleSpinBox(); lo,hi = CAMERA_LIMITS["max_accel_deg"]; self.accel_spin.setRange(lo, hi); self.accel_spin.setSingleStep(10.0); self.accel_spin.setDecimals(1); self.accel_spin.setSuffix(" deg/s²"); self.accel_spin.setToolTip("Slew acceleration limit — px/s² = deg/s² * px/deg. 120 deg/s² ≈ 2040 px/s² at 0.109 mrad/px; lower → smoother, higher → snappier."); self.accel_spin.setMinimumHeight(26)
        realism_grid.addWidget(self.accel_spin, 0, 1)

        realism_grid.addWidget(self._label("Backlash"), 0, 2)
        self.backlash_spin = QDoubleSpinBox(); lo,hi = CAMERA_LIMITS["backlash_px"]; self.backlash_spin.setRange(lo, hi); self.backlash_spin.setSingleStep(0.05); self.backlash_spin.setDecimals(2); self.backlash_spin.setSuffix(" px"); self.backlash_spin.setToolTip("Gear backlash — dead band on reversal. 0 = ideal, 2 px worst. Overcome by moving through backlash before motion starts."); self.backlash_spin.setMinimumHeight(26)
        realism_grid.addWidget(self.backlash_spin, 0, 3)

        realism_grid.addWidget(self._label("Encoder σ"), 1, 0)
        self.encoder_spin = QDoubleSpinBox(); lo,hi = CAMERA_LIMITS["encoder_sigma_px"]; self.encoder_spin.setRange(lo, hi); self.encoder_spin.setSingleStep(0.01); self.encoder_spin.setDecimals(3); self.encoder_spin.setSuffix(" px"); self.encoder_spin.setToolTip("Encoder noise σ — Gaussian jitter on reported pan/tilt (not executed). 0 = perfect, 0.5 px worst."); self.encoder_spin.setMinimumHeight(26)
        realism_grid.addWidget(self.encoder_spin, 1, 1)

        realism_grid.addWidget(self._label("Latency Jitter"), 1, 2)
        self.latency_jitter_spin = QDoubleSpinBox(); lo,hi = CAMERA_LIMITS["latency_jitter_ms"]; self.latency_jitter_spin.setRange(lo, hi); self.latency_jitter_spin.setSingleStep(0.2); self.latency_jitter_spin.setDecimals(1); self.latency_jitter_spin.setSuffix(" ms"); self.latency_jitter_spin.setToolTip("Latency jitter σ — Gaussian variation on queue delay (e.g., 12 ± 1.2 ms). 0 = deterministic."); self.latency_jitter_spin.setMinimumHeight(26)
        realism_grid.addWidget(self.latency_jitter_spin, 1, 3)

        realism_hint = QLabel("Realism adds accel-limited slew, reversal backlash, encoder noise, and stochastic latency. Increase for stress-testing.")
        realism_hint.setWordWrap(True)
        realism_hint.setStyleSheet("color:#64748b; font-size:10px; font-style:italic;")
        realism_grid.addWidget(realism_hint, 2, 0, 1, 4)
        layout.addWidget(realism_box)

        # Controller Gain moved to Control tab — keep hidden aliases for MainWindow backward compat
        gain_box = QGroupBox("E — Controller Gain (MOVED to Control tab)")
        gain_box.setStyleSheet("QGroupBox { padding-top: 14px; }")
        gain_layout = QVBoxLayout(gain_box)
        gain_layout.setContentsMargins(10, 14, 10, 10)
        gain_layout.setSpacing(6)
        self._add_gain_row(gain_layout)
        gain_box.hide()  # hidden — Control tab is single source for Kp
        layout.addWidget(gain_box)
        # Keep hidden hint for clarity when debugging
        moved_hint = QLabel("Gain is now in Control → Gains / Kp. This box is hidden for spec compliance.")
        moved_hint.setStyleSheet("color:#6b7280; font-size:9px; font-style:italic;")
        moved_hint.setWordWrap(True)
        moved_hint.hide()
        layout.addWidget(moved_hint)

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

    # Wiring — emit on any change (, debounced in MainWindow)

    def _wire_all(self):
        for w in [self.fov_w_spin, self.fov_h_spin, self.fov_deg_x_spin, self.fov_deg_y_spin, self.pan_min_spin, self.pan_max_spin, self.tilt_min_spin, self.tilt_max_spin, self.viewport_w_spin, self.viewport_h_spin]:
            w.valueChanged.connect(lambda _: self.configChanged.emit())
        for w in [self.pan_speed_deg_spin, self.tilt_speed_deg_spin, self.latency_spin, self.update_rate_spin]:
            w.valueChanged.connect(lambda _: self.configChanged.emit())
        self.res_spin.valueChanged.connect(lambda _: self.configChanged.emit())
        for w in [self.fov_deg_x_spin, self.fov_deg_y_spin, self.fov_w_spin]:
            w.valueChanged.connect(self._update_scale_from_fov)
        self.gain_slider.valueChanged.connect(lambda _: self.configChanged.emit())
        for w in [self.accel_spin, self.backlash_spin, self.encoder_spin, self.latency_jitter_spin]:
            w.valueChanged.connect(lambda _: self.configChanged.emit())

    def _update_scale_from_fov(self, _=None) -> None:
        try:
            deg = float(self.fov_deg_x_spin.value())
            res = int(self.fov_w_spin.value())
            mrad = (deg * 17.453292519943295) / max(1, res)
            self.scale_spin.blockSignals(True)
            self.scale_spin.setValue(float(mrad))
            self.scale_spin.blockSignals(False)
            urad = mrad * 1000
            self.scale_hint.setText(f"{deg:.1f} deg / {res} px = {mrad:.3f} mrad/px ({urad:.0f} urad/px)")
        except: pass
        self.configChanged.emit()

    def _on_scale_changed(self, v: float) -> None:
        urad = v * 1000
        self.scale_hint.setText(f"{v:.3f} mrad/px — 10 px = {v*10:.3f} mrad = {urad*10:.0f} urad")
        self.configChanged.emit()

    # Call after _build_ui to wire
    def _wire_signals(self):
        self._wire_all()

    # Config ↔ UI

    def collect_config(self) -> CameraConfig:
        pan_min = int(self.pan_min_spin.value()) if self.pan_min_spin.value() != 0 else None
        pan_max = int(self.pan_max_spin.value()) if self.pan_max_spin.value() != 0 else None
        tilt_min = int(self.tilt_min_spin.value()) if self.tilt_min_spin.value() != 0 else None
        tilt_max = int(self.tilt_max_spin.value()) if self.tilt_max_spin.value() != 0 else None
        home_pan = None
        home_tilt = None
        try:
            deg = float(self.fov_deg_x_spin.value())
            res = int(self.fov_w_spin.value())
            pixel_scale = (deg * 17.453292519943295) / max(1, res)
        except:
            pixel_scale = float(self.scale_spin.value())
        # Pan/tilt deg/sec to px/s for legacy max_slew_rate
        try:
            pan_deg = float(self.pan_speed_deg_spin.value())
            tilt_deg = float(self.tilt_speed_deg_spin.value())
            px_per_deg = 17.453292519943295 / max(1e-6, pixel_scale)
            max_slew = max(pan_deg * px_per_deg, tilt_deg * px_per_deg)
        except:
            max_slew = 800.0
        return CameraConfig(
            fov_width=int(self.fov_w_spin.value()),
            fov_height=int(self.fov_h_spin.value()),
            fov_deg_x=float(self.fov_deg_x_spin.value()),
            fov_deg_y=float(self.fov_deg_y_spin.value()),
            pan_min=pan_min, pan_max=pan_max,
            tilt_min=tilt_min, tilt_max=tilt_max,
            home_pan=home_pan, home_tilt=home_tilt,
            max_pan_speed_deg=float(self.pan_speed_deg_spin.value()),
            max_tilt_speed_deg=float(self.tilt_speed_deg_spin.value()),
            max_slew_rate=float(max_slew),
            resolution=float(self.res_spin.value()),
            latency_ms=int(self.latency_spin.value()),
            viewport_width=int(self.viewport_w_spin.value()),
            viewport_height=int(self.viewport_h_spin.value()),
            god_width=int(self.god_w_spin.value()),
            god_height=int(self.god_h_spin.value()),
            pixel_scale_mrad=float(pixel_scale),
            update_rate_hz=int(self.update_rate_spin.value()),
            max_accel_deg=float(self.accel_spin.value()),
            backlash_px=float(self.backlash_spin.value()),
            encoder_sigma_px=float(self.encoder_spin.value()),
            latency_jitter_ms=float(self.latency_jitter_spin.value()),
        ).validate(self._scene_bounds)

    def set_config(self, cfg: CameraConfig, emit: bool = False) -> None:
        cfg = cfg.validate(self._scene_bounds)
        for w in [self.fov_w_spin, self.fov_h_spin, self.fov_deg_x_spin, self.fov_deg_y_spin, self.pan_min_spin, self.pan_max_spin, self.tilt_min_spin, self.tilt_max_spin, self.home_pan_spin, self.home_tilt_spin, self.pan_speed_deg_spin, self.tilt_speed_deg_spin, self.slew_spin, self.res_spin, self.latency_spin, self.update_rate_spin, self.viewport_w_spin, self.viewport_h_spin, self.god_w_spin, self.god_h_spin, self.scale_spin, self.gain_spin, self.gain_slider, self.accel_spin, self.backlash_spin, self.encoder_spin, self.latency_jitter_spin]:
            w.blockSignals(True)
        try:
            self.fov_w_spin.setValue(int(cfg.fov_width)); self.fov_h_spin.setValue(int(cfg.fov_height))
            self.fov_deg_x_spin.setValue(float(getattr(cfg, 'fov_deg_x', 4.0))); self.fov_deg_y_spin.setValue(float(getattr(cfg, 'fov_deg_y', 3.0)))
            self.pan_min_spin.setValue(int(cfg.pan_min) if cfg.pan_min is not None else 0)
            self.pan_max_spin.setValue(int(cfg.pan_max) if cfg.pan_max is not None else 0)
            self.tilt_min_spin.setValue(int(cfg.tilt_min) if cfg.tilt_min is not None else 0)
            self.tilt_max_spin.setValue(int(cfg.tilt_max) if cfg.tilt_max is not None else 0)
            sw, sh = self._scene_bounds
            self.home_pan_spin.setValue(int(sw/2)); self.home_tilt_spin.setValue(int(sh/2))
            self.pan_speed_deg_spin.setValue(float(getattr(cfg, 'max_pan_speed_deg', 5.0)))
            self.tilt_speed_deg_spin.setValue(float(getattr(cfg, 'max_tilt_speed_deg', 5.0)))
            self.slew_spin.setValue(int(cfg.max_slew_rate))
            self.res_spin.setValue(float(cfg.resolution)); self.latency_spin.setValue(int(cfg.latency_ms))
            self.update_rate_spin.setValue(int(getattr(cfg, 'update_rate_hz', 30)))
            self.viewport_w_spin.setValue(int(cfg.viewport_width)); self.viewport_h_spin.setValue(int(cfg.viewport_height))
            self.god_w_spin.setValue(int(cfg.god_width)); self.god_h_spin.setValue(int(cfg.god_height))
            self.scale_spin.setValue(float(cfg.pixel_scale_mrad))
            self.accel_spin.setValue(float(getattr(cfg, 'max_accel_deg', 120.0)))
            self.backlash_spin.setValue(float(getattr(cfg, 'backlash_px', 0.25)))
            self.encoder_spin.setValue(float(getattr(cfg, 'encoder_sigma_px', 0.04)))
            self.latency_jitter_spin.setValue(float(getattr(cfg, 'latency_jitter_ms', 1.2)))
            self._update_scale_from_fov()
        finally:
            for w in [self.fov_w_spin, self.fov_h_spin, self.fov_deg_x_spin, self.fov_deg_y_spin, self.pan_min_spin, self.pan_max_spin, self.tilt_min_spin, self.tilt_max_spin, self.home_pan_spin, self.home_tilt_spin, self.pan_speed_deg_spin, self.tilt_speed_deg_spin, self.slew_spin, self.res_spin, self.latency_spin, self.update_rate_spin, self.viewport_w_spin, self.viewport_h_spin, self.god_w_spin, self.god_h_spin, self.scale_spin, self.accel_spin, self.backlash_spin, self.encoder_spin, self.latency_jitter_spin]:
                w.blockSignals(False)
            self.gain_spin.blockSignals(False); self.gain_slider.blockSignals(False)
        if emit:
            self.configChanged.emit()

    def set_scene_bounds(self, bounds: tuple[int,int]) -> None:
        self._scene_bounds = bounds
        # Sync God View to world size (spec: God View = World size)
        try:
            w, h = bounds
            self.god_w_spin.blockSignals(True)
            self.god_h_spin.blockSignals(True)
            self.god_w_spin.setValue(int(w))
            self.god_h_spin.setValue(int(h))
            self.home_pan_spin.setValue(int(w//2))
            self.home_tilt_spin.setValue(int(h//2))
        except Exception:
            pass
        finally:
            try:
                self.god_w_spin.blockSignals(False)
                self.god_h_spin.blockSignals(False)
            except Exception:
                pass

    # Ensure wiring after build
    def showEvent(self, e):
        super().showEvent(e)
        # Ensure signals wired once
        try:
            self._wire_signals()
        except: pass
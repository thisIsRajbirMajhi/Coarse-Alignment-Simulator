# gui/panels/disturbances_panel.py - Disturbance & Noise — preset-first, tabbed UI
#
# Design: most users only need a scenario preset + strength. The panel is
# therefore organized as:
#   1. Header card: master switch + scenario preset + live summary + reset
#   2. Three tabs following the physics pipeline: Air & Light → Camera & Motion → Sensor Noise
#   3. "Details" toggles reveal expert sliders (attenuation model, beam gains,
#      noise ratios/peaks, platform amplitude) instead of showing ~19 sliders at once.
#
# Back-compat: every config widget keeps its attribute name, `sliders` dict
# remains (hidden 0 values) so `disturbances_panel.sliders['Vibration']` etc
# still exist, and collect_config()/set_config()/get_config()/configChanged
# behave exactly as before.

from PyQt5.QtCore import Qt, pyqtSignal

import logging

from src.gui.panels.base import BaseConfigPanel
from PyQt5.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTabWidget,
    QVBoxLayout,
    QWidget,
    QSlider,
)

from src.disturbance.core.config import DisturbanceConfig
from src.disturbance.core.constants import (
    ATMOSPHERIC_PRESETS,
    PLATFORM_PROFILES,
)
from src.gui.components import (
    PresetSegment,
    Toggle,
    expansion_state,
    set_expansion_state,
)

log = logging.getLogger(__name__)

class DisturbancesPanel(BaseConfigPanel):
    """
    Preset-first disturbances tab.

    Tabs:
      Air & Light — weather condition + severity + turbulence (beam path)
      Camera & Motion — jitter + platform trajectory (camera geometry)
      Sensor Noise — Gaussian / Salt & Pepper / Poisson toggles (sensor)

    Expert sliders live behind per-tab "Details" checkboxes.
    """

    configChanged = pyqtSignal(object)

    def __init__(self, parent=None, initial: DisturbanceConfig | None = None):
        super().__init__(parent)
        self._initial = (initial or DisturbanceConfig()).validate()
        # Hidden legacy sliders for back-compat (not shown) — keep 0
        from PyQt5.QtWidgets import QSlider
        self.sliders: dict[str, QSlider] = {}
        for key in ["Turbulence", "Vibration", "Camera Motion", "Noise"]:
            s = QSlider(Qt.Horizontal)
            s.setRange(0, 10)
            s.setValue(0)
            s.hide()
            self.sliders[key] = s
            s.valueChanged.connect(lambda _: self._emit_config())
        self._building = False
        self._applying_preset = False
        self._build_ui()
        self.set_config(self._initial, emit=False)

    # ------------------------------------------------------------------ build
    def _build_ui(self) -> None:
        self._building = True
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(10)

        # ── Header: preset-first control ──
        hero = QFrame()
        hero.setStyleSheet("QFrame { background: #ffffff; border:1px solid #e5e7eb; border-radius:6px; }")
        hl = QVBoxLayout(hero)
        hl.setContentsMargins(10, 8, 10, 8)
        hl.setSpacing(6)
        bt = QLabel("Disturbance & Noise")
        bt.setStyleSheet("color:#111827; font-weight:700; font-size:11px; background: transparent;")
        bt.setAlignment(Qt.AlignCenter)
        hl.addWidget(bt)
        bs = QLabel("Air & Light → Camera & Motion → Sensor Noise")
        bs.setStyleSheet("color:#6b7280; font-size:10px; background: transparent;")
        bs.setWordWrap(True)
        bs.setAlignment(Qt.AlignCenter)
        hl.addWidget(bs)

        row = QHBoxLayout()
        row.setSpacing(8)
        self.chk_global_enabled = Toggle("Disturbances", checked=True)
        self.chk_global_enabled.setToolTip("Master switch — bypasses channel, camera and sensor stages")
        row.addWidget(self.chk_global_enabled)
        row.addWidget(self._label("Scenario"))
        self.combo_channel_preset = QComboBox()
        try:
            from src.disturbance.core.config import CHANNEL_PRESETS as _CHP
            self.combo_channel_preset.addItems(list(_CHP))
        except Exception:
            self.combo_channel_preset.addItems(["Clear", "Haze", "Fog", "Rain", "Low Light", "Moderate", "Severe", "Custom"])
        self.combo_channel_preset.setCurrentText("Clear")
        self.combo_channel_preset.setMinimumHeight(26)
        self.combo_channel_preset.setToolTip("One-click setup: Clear/Haze/Fog/Rain/Low Light/Moderate/Severe/Custom")
        row.addWidget(self.combo_channel_preset, 1)
        self.btn_reset = self._make_reset_button("Reset")
        self.btn_reset.setMaximumWidth(90)
        row.addWidget(self.btn_reset)
        hl.addLayout(row)

        # Quick preset chips (Design.md §15) + module nav (Design.md §5)
        self.quick_presets = PresetSegment(["Clear", "Fog", "Rain", "Shake", "Low Light", "Custom"])
        self.quick_presets.presetSelected.connect(self._on_quick_preset)
        hl.addWidget(self.quick_presets)
        nav_row = QHBoxLayout()
        nav_row.setSpacing(8)
        self.nav_air = QPushButton()
        self.nav_camera = QPushButton()
        self.nav_sensor = QPushButton()
        for _nb in (self.nav_air, self.nav_camera, self.nav_sensor):
            _nb.setMinimumHeight(40)
            _nb.setToolTip("Jump to this module tab")
            nav_row.addWidget(_nb)
        hl.addLayout(nav_row)
        self.nav_air.clicked.connect(lambda: self.tabs.setCurrentIndex(0))
        self.nav_camera.clicked.connect(lambda: self.tabs.setCurrentIndex(1))
        self.nav_sensor.clicked.connect(lambda: self.tabs.setCurrentIndex(2))

        self.label_summary = QLabel("")
        self.label_summary.setStyleSheet("color:#1e40af; font-size:10px; background: transparent;")
        self.label_summary.setWordWrap(True)
        self.label_summary.setAlignment(Qt.AlignCenter)
        hl.addWidget(self.label_summary)
        layout.addWidget(hero)

        # ── Tabs ──
        self.tabs = QTabWidget()
        self.tabs.setUsesScrollButtons(True)
        self.tabs.setElideMode(Qt.ElideRight)
        self.tabs.setDocumentMode(False)
        layout.addWidget(self.tabs, 1)
        self._build_air_tab()
        self._build_camera_tab()
        self._build_sensor_tab()

        layout.addStretch()
        self._wire_signals()
        self._building = False
        # Restore persisted Advanced states (default collapsed per spec).
        try:
            if expansion_state("dist/air_details", False):
                self.chk_air_details.setChecked(True)
            if expansion_state("dist/cam_details", False):
                self.chk_cam_details.setChecked(True)
            if expansion_state("dist/sensor_details", False):
                self.chk_sensor_details.setChecked(True)
        except Exception as e:
            log.debug("expansion restore skipped: %s", e)
        self._sync_atmo_enabled()
        self._sync_image_noise_visibility()
        self._refresh_summary()
        # Highlight sliders on drag + connect reset
        self._enhance_slider_highlight()
        self.btn_reset.clicked.connect(self._on_reset)

    # ------------------------------------------------------------ tab: air --
    def _build_air_tab(self) -> None:
        tab = QWidget()
        tl = QVBoxLayout(tab)
        tl.setContentsMargins(4, 6, 4, 6)
        tl.setSpacing(10)

        # Weather — the only two controls most users need
        wx_box = QGroupBox("Weather")
        wx = QGridLayout(wx_box)
        wx.setContentsMargins(12, 18, 12, 12)
        wx.setHorizontalSpacing(8)
        wx.setVerticalSpacing(8)
        wx.setColumnStretch(1, 1)
        wx.addWidget(self._label("Condition"), 0, 0)
        self.combo_atmospheric = QComboBox()
        self.combo_atmospheric.addItems(list(ATMOSPHERIC_PRESETS))
        self.combo_atmospheric.setCurrentText("Clear")
        self.combo_atmospheric.setMinimumHeight(26)
        self.combo_atmospheric.setToolTip("Beam path: Clear / Haze / Fog / Rain / Low light / User Defined")
        wx.addWidget(self.combo_atmospheric, 0, 1)
        wx.addWidget(self._label("Severity"), 1, 0)
        self.slider_channel_severity = QSlider(Qt.Horizontal)
        self.slider_channel_severity.setRange(0, 100)
        self.slider_channel_severity.setValue(100)
        self.slider_channel_severity.setToolTip("Severity 0..100% — scales attenuation/contrast/visibility loss")
        self.label_channel_severity_val = QLabel("100%")
        self.label_channel_severity_val.setMinimumHeight(26)
        self.label_channel_severity_val.setStyleSheet("color:#374151; font-size:11px;")
        wx.addWidget(self.slider_channel_severity, 1, 1)
        wx.addWidget(self.label_channel_severity_val, 1, 2)
        wx.addWidget(self._label("Contrast ↓"), 2, 0)
        self.slider_atmo_contrast = QSlider(Qt.Horizontal)
        self.slider_atmo_contrast.setRange(0, 100)
        self.slider_atmo_contrast.setValue(0)
        self.slider_atmo_contrast.setToolTip("Contrast reduction 0..100% (editable when User Defined)")
        self.label_atmo_contrast_val = QLabel("0%")
        self.label_atmo_contrast_val.setMinimumHeight(26)
        self.label_atmo_contrast_val.setStyleSheet("color:#374151; font-size:11px;")
        wx.addWidget(self.slider_atmo_contrast, 2, 1)
        wx.addWidget(self.label_atmo_contrast_val, 2, 2)
        wx.addWidget(self._label("Brightness ↓"), 3, 0)
        self.slider_atmo_brightness = QSlider(Qt.Horizontal)
        self.slider_atmo_brightness.setRange(0, 100)
        self.slider_atmo_brightness.setValue(0)
        self.slider_atmo_brightness.setToolTip("Brightness reduction 0..100% (editable when User Defined)")
        self.label_atmo_brightness_val = QLabel("0%")
        self.label_atmo_brightness_val.setMinimumHeight(26)
        self.label_atmo_brightness_val.setStyleSheet("color:#374151; font-size:11px;")
        wx.addWidget(self.slider_atmo_brightness, 3, 1)
        wx.addWidget(self.label_atmo_brightness_val, 3, 2)
        self.label_atmo_hint = QLabel("Clear 0/0 · Haze 15/10 · Fog 38/22 · Rain 22/14 · Low light 28/38")
        self.label_atmo_hint.setStyleSheet("color:#64748b; font-size:10px; font-style:italic;")
        self.label_atmo_hint.setWordWrap(True)
        wx.addWidget(self.label_atmo_hint, 4, 0, 1, 3)
        # Weather context summary (Design.md §6): current state at a glance.
        self.label_weather_context = QLabel("")
        self.label_weather_context.setStyleSheet("color:#1e40af; font-size:10px; font-weight:700;")
        self.label_weather_context.setWordWrap(True)
        wx.addWidget(self.label_weather_context, 5, 0, 1, 3)
        tl.addWidget(wx_box)

        # Turbulence — single beam-distortion slider
        tb_box = QGroupBox("Turbulence — beam distortion")
        tb = QGridLayout(tb_box)
        tb.setContentsMargins(12, 18, 12, 12)
        tb.setHorizontalSpacing(8)
        tb.setVerticalSpacing(8)
        tb.setColumnStretch(1, 1)
        tb.addWidget(self._label("Strength"), 0, 0)
        self.slider_turbulence = QSlider(Qt.Horizontal)
        self.slider_turbulence.setRange(0, 10)
        self.slider_turbulence.setValue(0)
        self.slider_turbulence.setToolTip("Turbulence 0..10 — drives seeing blur, wander, scintillation")
        self.label_turbulence_val = QLabel("0")
        self.label_turbulence_val.setMinimumHeight(26)
        self.label_turbulence_val.setStyleSheet("color:#374151; font-size:11px;")
        tb.addWidget(self.slider_turbulence, 0, 1)
        tb.addWidget(self.label_turbulence_val, 0, 2)
        tb.addWidget(self._hint("Shimmers the beacon: the spot wobbles and twinkles."), 1, 0, 1, 3)
        tl.addWidget(tb_box)

        # Details — expert beam controls, hidden by default
        self.chk_channel_enabled = Toggle("Optical channel", checked=True)
        self.chk_channel_enabled.setToolTip("Ideal beam → channel → received signal")
        tl.addWidget(self.chk_channel_enabled)
        self.chk_air_details = QCheckBox("Show beam details (attenuation, wander, spread)")
        self.chk_air_details.setStyleSheet("color:#64748b; font-size:11px;")
        tl.addWidget(self.chk_air_details)
        self.air_details = QWidget()
        ad = QGridLayout(self.air_details)
        ad.setContentsMargins(0, 0, 0, 0)
        ad.setHorizontalSpacing(8)
        ad.setVerticalSpacing(8)
        ad.setColumnStretch(1, 1)
        det_box = QGroupBox("Beam details")
        dg = QGridLayout(det_box)
        dg.setContentsMargins(12, 18, 12, 12)
        dg.setHorizontalSpacing(8)
        dg.setVerticalSpacing(8)
        dg.setColumnStretch(1, 1)
        dg.addWidget(self._label("Attenuation"), 0, 0)
        self.slider_channel_attenuation = QSlider(Qt.Horizontal)
        self.slider_channel_attenuation.setRange(0, 100)
        self.slider_channel_attenuation.setValue(100)
        self.slider_channel_attenuation.setToolTip("Attenuation strength 0..1 (received = emitted × factor)")
        self.label_channel_attenuation_val = QLabel("1.00")
        self.label_channel_attenuation_val.setMinimumHeight(26)
        self.label_channel_attenuation_val.setStyleSheet("color:#374151; font-size:11px;")
        dg.addWidget(self.slider_channel_attenuation, 0, 1)
        self.combo_attenuation_model = QComboBox()
        self.combo_attenuation_model.addItems(["Fixed", "Distance Based", "Atmospheric", "Custom"])
        self.combo_attenuation_model.setCurrentText("Atmospheric")
        self.combo_attenuation_model.setMinimumHeight(26)
        dg.addWidget(self.combo_attenuation_model, 0, 2)
        dg.addWidget(self.label_channel_attenuation_val, 0, 3)
        dg.addWidget(self._label("Wander"), 1, 0)
        self.slider_beam_wander = QSlider(Qt.Horizontal)
        self.slider_beam_wander.setRange(0, 200)
        self.slider_beam_wander.setValue(100)
        self.slider_beam_wander.setToolTip("Beam wander gain 0..2 — shifts the spot (light path, not camera)")
        self.label_beam_wander_val = QLabel("1.00×")
        self.label_beam_wander_val.setMinimumHeight(26)
        self.label_beam_wander_val.setStyleSheet("color:#374151; font-size:11px;")
        dg.addWidget(self.slider_beam_wander, 1, 1)
        dg.addWidget(self.label_beam_wander_val, 1, 2)
        dg.addWidget(self._label("Spread"), 2, 0)
        self.slider_beam_spread = QSlider(Qt.Horizontal)
        self.slider_beam_spread.setRange(0, 200)
        self.slider_beam_spread.setValue(100)
        self.slider_beam_spread.setToolTip("Beam spread gain 0..2 — widens the apparent spot")
        self.label_beam_spread_val = QLabel("1.00×")
        self.label_beam_spread_val.setMinimumHeight(26)
        self.label_beam_spread_val.setStyleSheet("color:#374151; font-size:11px;")
        dg.addWidget(self.slider_beam_spread, 2, 1)
        dg.addWidget(self.label_beam_spread_val, 2, 2)
        dg.addWidget(self._label("Twinkle"), 3, 0)
        self.slider_intensity_fluct = QSlider(Qt.Horizontal)
        self.slider_intensity_fluct.setRange(0, 200)
        self.slider_intensity_fluct.setValue(100)
        self.slider_intensity_fluct.setToolTip("Intensity fluctuation gain 0..2 (scintillation)")
        self.label_intensity_fluct_val = QLabel("1.00×")
        self.label_intensity_fluct_val.setMinimumHeight(26)
        self.label_intensity_fluct_val.setStyleSheet("color:#374151; font-size:11px;")
        dg.addWidget(self.slider_intensity_fluct, 3, 1)
        dg.addWidget(self.label_intensity_fluct_val, 3, 2)
        ad.addWidget(det_box)
        self.air_details.setLayout(ad)
        self.air_details.setVisible(False)
        tl.addWidget(self.air_details)
        tl.addStretch()
        self.tabs.addTab(tab, "Air & Light")

    # --------------------------------------------------------- tab: camera --
    def _build_camera_tab(self) -> None:
        tab = QWidget()
        tl = QVBoxLayout(tab)
        tl.setContentsMargins(4, 6, 4, 6)
        tl.setSpacing(10)

        jit_box = QGroupBox("Camera shake — ± px / frame")
        jg = QGridLayout(jit_box)
        jg.setContentsMargins(12, 18, 12, 12)
        jg.setHorizontalSpacing(8)
        jg.setVerticalSpacing(8)
        jg.setColumnStretch(1, 1)
        self.chk_jitter_enabled = Toggle("Shake", checked=True)
        self.chk_jitter_enabled.setToolTip("Camera shake on/off")
        jg.addWidget(self.chk_jitter_enabled, 0, 0)
        jg.addWidget(self._label("Amount"), 0, 1)
        self.slider_jitter = QSlider(Qt.Horizontal)
        self.slider_jitter.setRange(0, 200)  # 0.0 to 20.0 per spec Sr21.3 step 0.1
        self.slider_jitter.setValue(0)
        self.slider_jitter.setToolTip("Jitter ±0..20 px/frame — shakes the camera (different from beam wander)")
        self.label_jitter_val = QLabel("0.0 px")
        self.label_jitter_val.setMinimumHeight(26)
        self.label_jitter_val.setStyleSheet("color:#374151; font-size:11px;")
        jg.addWidget(self.slider_jitter, 0, 2)
        jg.addWidget(self.label_jitter_val, 0, 3)
        tl.addWidget(jit_box)

        plat_box = QGroupBox("Platform motion — ±20 px/frame max")
        pg = QGridLayout(plat_box)
        pg.setContentsMargins(12, 18, 12, 12)
        pg.setHorizontalSpacing(8)
        pg.setVerticalSpacing(8)
        pg.setColumnStretch(2, 1)
        self.chk_platform_enabled = Toggle("Drift", checked=True)
        self.chk_platform_enabled.setToolTip("Platform motion on/off")
        pg.addWidget(self.chk_platform_enabled, 0, 0)
        pg.addWidget(self._label("Path"), 0, 1)
        self.combo_platform = QComboBox()
        self.combo_platform.addItems(list(PLATFORM_PROFILES))
        self.combo_platform.setCurrentText("Linear")
        self.combo_platform.setMinimumHeight(26)
        self.combo_platform.setToolTip("Linear (default) + Circular / Random / Spiral / Figure 8 / Sin / Zig-Zag")
        pg.addWidget(self.combo_platform, 0, 2)
        pg.addWidget(self._label("Speed"), 1, 0)
        self.slider_platform_speed = QSlider(Qt.Horizontal)
        self.slider_platform_speed.setRange(0, 200)  # 0.0 to 20.0 per spec Sr21.5 step 0.1
        self.slider_platform_speed.setValue(0)
        self.slider_platform_speed.setToolTip("Platform speed 0..20 px/frame")
        self.label_platform_speed_val = QLabel("0.0 px/f")
        self.label_platform_speed_val.setMinimumHeight(26)
        self.label_platform_speed_val.setStyleSheet("color:#374151; font-size:11px;")
        pg.addWidget(self.slider_platform_speed, 1, 1, 1, 2)
        pg.addWidget(self.label_platform_speed_val, 1, 3)
        pg.addWidget(self._hint("Linear drifts straight; Random jitters the path; Figure 8 sweeps loops."), 2, 0, 1, 4)
        tl.addWidget(plat_box)

        vib_box = QGroupBox("Mount vibration & slow drift — 0..10")
        vg = QGridLayout(vib_box)
        vg.setContentsMargins(12, 18, 12, 12)
        vg.setHorizontalSpacing(8)
        vg.setVerticalSpacing(8)
        vg.setColumnStretch(1, 1)
        vg.addWidget(self._label("Vibration"), 0, 0)
        self.slider_vibration = QSlider(Qt.Horizontal)
        self.slider_vibration.setRange(0, 100)  # 0.0 to 10.0 step 0.1
        self.slider_vibration.setValue(0)
        self.slider_vibration.setToolTip("Harmonic mount vibration 0..10 — high-frequency shake")
        self.label_vibration_val = QLabel("0.0")
        self.label_vibration_val.setMinimumHeight(26)
        self.label_vibration_val.setStyleSheet("color:#374151; font-size:11px;")
        vg.addWidget(self.slider_vibration, 0, 1)
        vg.addWidget(self.label_vibration_val, 0, 2)
        vg.addWidget(self._label("Slow drift"), 1, 0)
        self.slider_cam_drift = QSlider(Qt.Horizontal)
        self.slider_cam_drift.setRange(0, 100)  # 0.0 to 10.0 step 0.1
        self.slider_cam_drift.setValue(0)
        self.slider_cam_drift.setToolTip("Thermal/mount drift 0..10 — slow OU wander of the view")
        self.label_cam_drift_val = QLabel("0.0")
        self.label_cam_drift_val.setMinimumHeight(26)
        self.label_cam_drift_val.setStyleSheet("color:#374151; font-size:11px;")
        vg.addWidget(self.slider_cam_drift, 1, 1)
        vg.addWidget(self.label_cam_drift_val, 1, 2)
        vg.addWidget(self._hint("Vibration rattles the mount; drift slowly walks the view (thermal)."), 2, 0, 1, 3)
        tl.addWidget(vib_box)

        self.chk_cam_details = QCheckBox("Show motion details (amplitude, direction)")
        self.chk_cam_details.setStyleSheet("color:#64748b; font-size:11px;")
        tl.addWidget(self.chk_cam_details)
        self.cam_details = QWidget()
        cd = QGridLayout(self.cam_details)
        cd.setContentsMargins(0, 0, 0, 0)
        cd.setHorizontalSpacing(8)
        cd.setVerticalSpacing(8)
        cd.setColumnStretch(1, 1)
        det_box = QGroupBox("Motion details")
        mg = QGridLayout(det_box)
        mg.setContentsMargins(12, 18, 12, 12)
        mg.setHorizontalSpacing(8)
        mg.setVerticalSpacing(8)
        mg.setColumnStretch(1, 1)
        mg.addWidget(self._label("Amplitude X"), 0, 0)
        self.slider_platform_amp_x = QSlider(Qt.Horizontal)
        self.slider_platform_amp_x.setRange(0, 400)
        self.slider_platform_amp_x.setValue(110)
        self.slider_platform_amp_x.setToolTip("Platform amplitude X (px)")
        self.label_platform_amp_x_val = QLabel("110 px")
        self.label_platform_amp_x_val.setMinimumHeight(26)
        self.label_platform_amp_x_val.setStyleSheet("color:#374151; font-size:11px;")
        mg.addWidget(self.slider_platform_amp_x, 0, 1)
        mg.addWidget(self.label_platform_amp_x_val, 0, 2)
        mg.addWidget(self._label("Amplitude Y"), 1, 0)
        self.slider_platform_amp_y = QSlider(Qt.Horizontal)
        self.slider_platform_amp_y.setRange(0, 400)
        self.slider_platform_amp_y.setValue(110)
        self.slider_platform_amp_y.setToolTip("Platform amplitude Y (px)")
        self.label_platform_amp_y_val = QLabel("110 px")
        self.label_platform_amp_y_val.setMinimumHeight(26)
        self.label_platform_amp_y_val.setStyleSheet("color:#374151; font-size:11px;")
        mg.addWidget(self.slider_platform_amp_y, 1, 1)
        mg.addWidget(self.label_platform_amp_y_val, 1, 2)
        mg.addWidget(self._label("Direction"), 2, 0)
        self.slider_platform_direction = QSlider(Qt.Horizontal)
        self.slider_platform_direction.setRange(-180, 180)
        self.slider_platform_direction.setValue(0)
        self.slider_platform_direction.setToolTip("Platform direction (deg)")
        self.label_platform_direction_val = QLabel("0°")
        self.label_platform_direction_val.setMinimumHeight(26)
        self.label_platform_direction_val.setStyleSheet("color:#374151; font-size:11px;")
        mg.addWidget(self.slider_platform_direction, 2, 1)
        mg.addWidget(self.label_platform_direction_val, 2, 2)
        cd.addWidget(det_box)
        self.cam_details.setLayout(cd)
        self.cam_details.setVisible(False)
        tl.addWidget(self.cam_details)
        tl.addStretch()
        self.tabs.addTab(tab, "Camera & Motion")

    # --------------------------------------------------------- tab: sensor --
    def _build_sensor_tab(self) -> None:
        tab = QWidget()
        tl = QVBoxLayout(tab)
        tl.setContentsMargins(4, 6, 4, 6)
        tl.setSpacing(10)

        tl.addWidget(self._hint("Pick one or more noise types — they stack as Gaussian → Poisson → Salt & Pepper."))

        # Gaussian card
        g_box = QGroupBox("Smooth grain")
        gg = QGridLayout(g_box)
        gg.setContentsMargins(12, 18, 12, 12)
        gg.setHorizontalSpacing(8)
        gg.setVerticalSpacing(8)
        gg.setColumnStretch(1, 1)
        self.chk_gaussian = QCheckBox("Gaussian")
        self.chk_gaussian.setToolTip("Smooth static — strength sets grain size (σ)")
        self.chk_gaussian.setStyleSheet("color:#374151; font-size:11px; font-weight:700;")
        gg.addWidget(self.chk_gaussian, 0, 0)
        self.label_gaussian_sigma = self._label("Strength")
        gg.addWidget(self.label_gaussian_sigma, 0, 1)
        self.slider_gaussian_sigma = QSlider(Qt.Horizontal)
        self.slider_gaussian_sigma.setRange(0, 200)  # 0.0 to 20.0 step 0.1
        self.slider_gaussian_sigma.setValue(80)
        self.slider_gaussian_sigma.setToolTip("Grain strength σ 0..20")
        self.label_gaussian_sigma_val = QLabel("8.0 px")
        self.label_gaussian_sigma_val.setMinimumHeight(26)
        self.label_gaussian_sigma_val.setStyleSheet("color:#374151; font-size:11px;")
        gg.addWidget(self.slider_gaussian_sigma, 0, 2)
        gg.addWidget(self.label_gaussian_sigma_val, 0, 3)
        self.label_gaussian_max = self._label("Max σ")
        gg.addWidget(self.label_gaussian_max, 1, 1)
        self.slider_gaussian_max = QSlider(Qt.Horizontal)
        self.slider_gaussian_max.setRange(10, 200)
        self.slider_gaussian_max.setValue(200)
        self.slider_gaussian_max.setToolTip("Allowed ceiling for grain strength")
        self.label_gaussian_max_val = QLabel("20.0 px")
        self.label_gaussian_max_val.setMinimumHeight(26)
        self.label_gaussian_max_val.setStyleSheet("color:#374151; font-size:11px;")
        gg.addWidget(self.slider_gaussian_max, 1, 2)
        gg.addWidget(self.label_gaussian_max_val, 1, 3)
        self.label_gaussian_off_hint = self._hint("Off — enable Gaussian to reveal strength controls.")
        gg.addWidget(self.label_gaussian_off_hint, 2, 0, 1, 4)
        tl.addWidget(g_box)

        # Salt & pepper card
        sp_box = QGroupBox("Dead / hot pixels")
        sg = QGridLayout(sp_box)
        sg.setContentsMargins(12, 18, 12, 12)
        sg.setHorizontalSpacing(8)
        sg.setVerticalSpacing(8)
        sg.setColumnStretch(1, 1)
        self.chk_salt_pepper = QCheckBox("Salt && Pepper")
        self.chk_salt_pepper.setToolTip("Random black/white speckles — strength sets how many")
        self.chk_salt_pepper.setStyleSheet("color:#374151; font-size:11px; font-weight:700;")
        sg.addWidget(self.chk_salt_pepper, 0, 0)
        self.label_salt_density = self._label("Amount")
        sg.addWidget(self.label_salt_density, 0, 1)
        self.slider_salt_density = QSlider(Qt.Horizontal)
        self.slider_salt_density.setRange(0, 20)  # 0.0 to 0.20 step 0.01
        self.slider_salt_density.setValue(10)
        self.slider_salt_density.setToolTip("Speckle amount 0..20% — 10 = 10% of pixels")
        self.label_salt_density_val = QLabel("0.10")
        self.label_salt_density_val.setMinimumHeight(26)
        self.label_salt_density_val.setStyleSheet("color:#374151; font-size:11px;")
        sg.addWidget(self.slider_salt_density, 0, 2)
        sg.addWidget(self.label_salt_density_val, 0, 3)
        self.label_salt_ratio = self._label("White/black")
        sg.addWidget(self.label_salt_ratio, 1, 1)
        self.slider_salt_ratio = QSlider(Qt.Horizontal)
        self.slider_salt_ratio.setRange(0, 100)
        self.slider_salt_ratio.setValue(50)
        self.slider_salt_ratio.setToolTip("Balance of white vs black speckles")
        self.label_salt_ratio_val = QLabel("0.50")
        self.label_salt_ratio_val.setMinimumHeight(26)
        self.label_salt_ratio_val.setStyleSheet("color:#374151; font-size:11px;")
        sg.addWidget(self.slider_salt_ratio, 1, 2)
        sg.addWidget(self.label_salt_ratio_val, 1, 3)
        self.label_salt_off_hint = self._hint("Off — enable Salt & Pepper to reveal amount controls.")
        sg.addWidget(self.label_salt_off_hint, 2, 0, 1, 4)
        tl.addWidget(sp_box)

        # Poisson card
        p_box = QGroupBox("Low-light flicker")
        pg = QGridLayout(p_box)
        pg.setContentsMargins(12, 18, 12, 12)
        pg.setHorizontalSpacing(8)
        pg.setVerticalSpacing(8)
        pg.setColumnStretch(1, 1)
        self.chk_poisson = QCheckBox("Poisson")
        self.chk_poisson.setToolTip("Photon shot noise — visible in dark scenes")
        self.chk_poisson.setStyleSheet("color:#374151; font-size:11px; font-weight:700;")
        pg.addWidget(self.chk_poisson, 0, 0)
        self.label_poisson_scale = self._label("Strength")
        pg.addWidget(self.label_poisson_scale, 0, 1)
        self.slider_poisson_scale = QSlider(Qt.Horizontal)
        self.slider_poisson_scale.setRange(5, 50)  # 0.5 to 5.0 step 0.1
        self.slider_poisson_scale.setValue(10)
        self.slider_poisson_scale.setToolTip("Flicker strength 0.5..5.0")
        self.label_poisson_scale_val = QLabel("1.0×")
        self.label_poisson_scale_val.setMinimumHeight(26)
        self.label_poisson_scale_val.setStyleSheet("color:#374151; font-size:11px;")
        pg.addWidget(self.slider_poisson_scale, 0, 2)
        pg.addWidget(self.label_poisson_scale_val, 0, 3)
        self.label_poisson_peak = self._label("Peak")
        pg.addWidget(self.label_poisson_peak, 1, 1)
        self.slider_poisson_peak = QSlider(Qt.Horizontal)
        self.slider_poisson_peak.setRange(30, 255)
        self.slider_poisson_peak.setValue(100)
        self.slider_poisson_peak.setToolTip("Brightness level the flicker is calibrated to")
        self.label_poisson_peak_val = QLabel("100")
        self.label_poisson_peak_val.setMinimumHeight(26)
        self.label_poisson_peak_val.setStyleSheet("color:#374151; font-size:11px;")
        pg.addWidget(self.slider_poisson_peak, 1, 2)
        pg.addWidget(self.label_poisson_peak_val, 1, 3)
        self.label_poisson_off_hint = self._hint("Off — enable Poisson to reveal flicker controls.")
        pg.addWidget(self.label_poisson_off_hint, 2, 0, 1, 4)
        tl.addWidget(p_box)

        self.chk_sensor_details = QCheckBox("Show fine-tuning (ceilings, balance, peak)")
        self.chk_sensor_details.setStyleSheet("color:#64748b; font-size:11px;")
        tl.addWidget(self.chk_sensor_details)
        tl.addStretch()
        self.tabs.addTab(tab, "Sensor Noise")
        self._sync_sensor_details(False)

    # ---------------------------------------------------------------- wiring
    def _wire_signals(self) -> None:
        for cb in [self.chk_salt_pepper, self.chk_gaussian, self.chk_poisson]:
            cb.toggled.connect(lambda _: self._sync_image_noise_visibility())
            cb.toggled.connect(lambda _: self._emit_config())
        self.chk_global_enabled.toggled.connect(lambda _: self._emit_config())
        self.chk_channel_enabled.toggled.connect(lambda _: self._emit_config())
        self.chk_jitter_enabled.toggled.connect(lambda _: self._emit_config())
        self.chk_platform_enabled.toggled.connect(lambda _: self._emit_config())
        self.combo_channel_preset.currentTextChanged.connect(self._on_channel_preset_changed)
        self.combo_attenuation_model.currentTextChanged.connect(lambda _: self._emit_config())
        self.slider_channel_severity.valueChanged.connect(lambda _: self._emit_config())
        self.slider_channel_severity.valueChanged.connect(lambda val: self.label_channel_severity_val.setText(f"{val}%"))
        self.slider_channel_attenuation.valueChanged.connect(lambda _: self._emit_config())
        self.slider_channel_attenuation.valueChanged.connect(lambda val: self.label_channel_attenuation_val.setText(f"{val/100:.2f}"))
        self.slider_turbulence.valueChanged.connect(lambda _: self._emit_config())
        self.slider_turbulence.valueChanged.connect(lambda val: self.label_turbulence_val.setText(str(val)))
        self.slider_beam_wander.valueChanged.connect(lambda _: self._emit_config())
        self.slider_beam_wander.valueChanged.connect(lambda val: self.label_beam_wander_val.setText(f"{val/100:.2f}×"))
        self.slider_beam_spread.valueChanged.connect(lambda _: self._emit_config())
        self.slider_beam_spread.valueChanged.connect(lambda val: self.label_beam_spread_val.setText(f"{val/100:.2f}×"))
        self.slider_intensity_fluct.valueChanged.connect(lambda _: self._emit_config())
        self.slider_intensity_fluct.valueChanged.connect(lambda val: self.label_intensity_fluct_val.setText(f"{val/100:.2f}×"))
        self.slider_salt_density.valueChanged.connect(lambda _: self._emit_config())
        self.slider_salt_density.valueChanged.connect(lambda val: self.label_salt_density_val.setText(f"{val/100:.2f}"))
        self.slider_salt_ratio.valueChanged.connect(lambda _: self._emit_config())
        self.slider_salt_ratio.valueChanged.connect(lambda val: self.label_salt_ratio_val.setText(f"{val/100:.2f}"))
        self.slider_gaussian_sigma.valueChanged.connect(lambda _: self._on_gaussian_sigma_changed())
        self.slider_gaussian_sigma.valueChanged.connect(lambda val: self.label_gaussian_sigma_val.setText(f"{val/10:.1f} px"))
        self.slider_gaussian_max.valueChanged.connect(lambda _: self._on_gaussian_max_changed())
        self.slider_gaussian_max.valueChanged.connect(lambda val: self.label_gaussian_max_val.setText(f"{val/10:.1f} px"))
        self.slider_poisson_scale.valueChanged.connect(lambda _: self._emit_config())
        self.slider_poisson_scale.valueChanged.connect(lambda val: self.label_poisson_scale_val.setText(f"{val/10:.1f}×"))
        self.slider_poisson_peak.valueChanged.connect(lambda _: self._emit_config())
        self.slider_poisson_peak.valueChanged.connect(lambda val: self.label_poisson_peak_val.setText(str(val)))
        self.slider_jitter.valueChanged.connect(lambda _: self._emit_config())
        self.slider_jitter.valueChanged.connect(lambda val: self.label_jitter_val.setText(f"{val/10:.1f} px"))
        self.slider_vibration.valueChanged.connect(lambda _: self._emit_config())
        self.slider_vibration.valueChanged.connect(lambda val: self.label_vibration_val.setText(f"{val/10:.1f}"))
        self.slider_cam_drift.valueChanged.connect(lambda _: self._emit_config())
        self.slider_cam_drift.valueChanged.connect(lambda val: self.label_cam_drift_val.setText(f"{val/10:.1f}"))
        self.combo_atmospheric.currentTextChanged.connect(self._on_atmo_preset_changed)
        self.slider_atmo_contrast.valueChanged.connect(lambda _: self._emit_config())
        self.slider_atmo_contrast.valueChanged.connect(lambda val: self.label_atmo_contrast_val.setText(f"{val}%"))
        self.slider_atmo_brightness.valueChanged.connect(lambda _: self._emit_config())
        self.slider_atmo_brightness.valueChanged.connect(lambda val: self.label_atmo_brightness_val.setText(f"{val}%"))
        self.combo_platform.currentTextChanged.connect(lambda _: self._emit_config())
        self.slider_platform_speed.valueChanged.connect(lambda _: self._emit_config())
        self.slider_platform_speed.valueChanged.connect(lambda val: self.label_platform_speed_val.setText(f"{val/10:.1f} px/f"))
        self.slider_platform_amp_x.valueChanged.connect(lambda _: self._emit_config())
        self.slider_platform_amp_x.valueChanged.connect(lambda val: self.label_platform_amp_x_val.setText(f"{val} px"))
        self.slider_platform_amp_y.valueChanged.connect(lambda _: self._emit_config())
        self.slider_platform_amp_y.valueChanged.connect(lambda val: self.label_platform_amp_y_val.setText(f"{val} px"))
        self.slider_platform_direction.valueChanged.connect(lambda _: self._emit_config())
        self.slider_platform_direction.valueChanged.connect(lambda val: self.label_platform_direction_val.setText(f"{val}°"))
        self.chk_air_details.toggled.connect(lambda on: self.air_details.setVisible(bool(on)))
        self.chk_cam_details.toggled.connect(lambda on: self.cam_details.setVisible(bool(on)))
        self.chk_sensor_details.toggled.connect(lambda on: self._sync_sensor_details(bool(on)))
        # Persist Advanced disclosure states across runs (Design.md §50.7).
        self.chk_air_details.toggled.connect(lambda on: set_expansion_state("dist/air_details", bool(on)))
        self.chk_cam_details.toggled.connect(lambda on: set_expansion_state("dist/cam_details", bool(on)))
        self.chk_sensor_details.toggled.connect(lambda on: set_expansion_state("dist/sensor_details", bool(on)))
        # Release-only heavy emits: valueChanged updates the pill label (cheap,
        # wired above); the config itself fires on sliderReleased or for
        # non-drag changes (keyboard, programmatic). _emit_config() gates
        # in-flight drags via sender().isSliderDown().
        for _s in (
            self.slider_channel_severity, self.slider_channel_attenuation,
            self.slider_turbulence, self.slider_beam_wander, self.slider_beam_spread,
            self.slider_intensity_fluct, self.slider_salt_density, self.slider_salt_ratio,
            self.slider_gaussian_sigma, self.slider_gaussian_max,
            self.slider_poisson_scale, self.slider_poisson_peak, self.slider_jitter,
            self.slider_vibration, self.slider_cam_drift,
            self.slider_atmo_contrast, self.slider_atmo_brightness,
            self.slider_platform_speed, self.slider_platform_amp_x,
            self.slider_platform_amp_y, self.slider_platform_direction,
        ):
            _s.sliderReleased.connect(self._emit_config)

    def _sync_sensor_details(self, show: bool) -> None:
        """Fine-tuning rows are hidden until the user asks for them."""
        for w in [self.label_gaussian_max, self.slider_gaussian_max, self.label_gaussian_max_val,
                  self.label_salt_ratio, self.slider_salt_ratio, self.label_salt_ratio_val,
                  self.label_poisson_scale, self.slider_poisson_scale, self.label_poisson_scale_val,
                  self.label_poisson_peak, self.slider_poisson_peak, self.label_poisson_peak_val]:
            w.setVisible(show)
        # Strength rows still follow their noise-type toggle.
        self._sync_image_noise_visibility()

    def _on_channel_preset_changed(self, preset: str):
        # Apply the §15 disturbance preset to the whole panel, then refresh.
        self._applying_preset = True
        try:
            cfg = self.collect_config().apply_preset(preset)
        except Exception:
            self._applying_preset = False
            return
        # Keep the preset combo on the chosen entry while other widgets sync.
        self.set_config(cfg, emit=False)
        try:
            self.combo_channel_preset.blockSignals(True)
            idx = self.combo_channel_preset.findText(str(preset))
            if idx >= 0:
                self.combo_channel_preset.setCurrentIndex(idx)
            else:
                self.combo_channel_preset.setCurrentText(str(preset))
        finally:
            self.combo_channel_preset.blockSignals(False)
            self._applying_preset = False
        self._sync_quick_presets(str(preset))
        self._emit_config()

    def _on_quick_preset(self, name: str) -> None:
        """Quick preset chips (Design.md §15): Clear/Fog/Rain/Low Light map to
        channel presets; Shake enables camera shake; Custom just marks."""
        if name == "Shake":
            self._applying_preset = True
            try:
                self.chk_jitter_enabled.setChecked(True)
                self.slider_jitter.setValue(80)  # 8.0 px
                self.slider_platform_speed.setValue(50)  # 5.0 px/f
            finally:
                self._applying_preset = False
            self._sync_quick_presets("Custom")
            self._emit_config()
            return
        if name == "Custom":
            self._sync_quick_presets("Custom")
            return
        self._on_channel_preset_changed(name)

    def _sync_quick_presets(self, preset: str) -> None:
        """Mirror the scenario combo into the quick chips (incl. Custom •)."""
        try:
            key = {"Haze": "Haze", "Fog": "Fog", "Rain": "Rain",
                   "Low Light": "Low Light", "Low light": "Low Light",
                   "Clear": "Clear"}.get(str(preset), "Custom")
            self.quick_presets.set_active(key if key != "Custom" else None)
            if key == "Custom":
                self.quick_presets.mark_custom()
        except Exception as e:
            log.debug("quick preset sync skipped: %s", e)

    def _on_gaussian_sigma_changed(self):
        if self.slider_gaussian_sigma.value() > self.slider_gaussian_max.value():
            self.slider_gaussian_sigma.blockSignals(True)
            self.slider_gaussian_sigma.setValue(self.slider_gaussian_max.value())
            self.slider_gaussian_sigma.blockSignals(False)
        self._emit_config()

    def _on_gaussian_max_changed(self):
        if self.slider_gaussian_sigma.value() > self.slider_gaussian_max.value():
            self.slider_gaussian_sigma.blockSignals(True)
            self.slider_gaussian_sigma.setValue(self.slider_gaussian_max.value())
            self.slider_gaussian_sigma.blockSignals(False)
        self._emit_config()

    def _sync_image_noise_visibility(self):
        """Only selected types show their strength rows; unchecked cards show a hint."""
        show_details = bool(getattr(self, "chk_sensor_details", None) is not None
                            and self.chk_sensor_details.isChecked())
        is_sp = bool(self.chk_salt_pepper.isChecked())
        is_g = bool(self.chk_gaussian.isChecked())
        is_p = bool(self.chk_poisson.isChecked())
        self.label_salt_density.setVisible(is_sp)
        self.slider_salt_density.setVisible(is_sp)
        self.label_salt_density_val.setVisible(is_sp)
        for w in [self.label_salt_ratio, self.slider_salt_ratio, self.label_salt_ratio_val]:
            w.setVisible(is_sp and show_details)
        self.label_gaussian_sigma.setVisible(is_g)
        self.slider_gaussian_sigma.setVisible(is_g)
        self.label_gaussian_sigma_val.setVisible(is_g)
        for w in [self.label_gaussian_max, self.slider_gaussian_max, self.label_gaussian_max_val]:
            w.setVisible(is_g and show_details)
        for w in [self.label_poisson_scale, self.slider_poisson_scale, self.label_poisson_scale_val]:
            w.setVisible(is_p)
        for w in [self.label_poisson_peak, self.slider_poisson_peak, self.label_poisson_peak_val]:
            w.setVisible(is_p and show_details)
        # Empty-state hints (guarded for set_config paths before build finishes)
        try:
            self.label_gaussian_off_hint.setVisible(not is_g)
            self.label_salt_off_hint.setVisible(not is_sp)
            self.label_poisson_off_hint.setVisible(not is_p)
        except AttributeError:
            pass

    def _sync_atmo_enabled(self):
        is_user = str(self.combo_atmospheric.currentText()) == "User Defined"
        self.slider_atmo_contrast.setEnabled(is_user)
        self.slider_atmo_brightness.setEnabled(is_user)
        self.slider_atmo_contrast.setToolTip("User Defined only" if not is_user else "Contrast reduction 0..100%")
        self.slider_atmo_brightness.setToolTip("User Defined only" if not is_user else "Brightness reduction 0..100%")

    def _on_atmo_preset_changed(self, preset: str):
        from src.disturbance.core.constants import ATMOSPHERIC_PRESET_MAP
        if preset in ATMOSPHERIC_PRESET_MAP:
            mp = ATMOSPHERIC_PRESET_MAP[preset]
            if preset != "User Defined":
                self.slider_atmo_contrast.blockSignals(True)
                self.slider_atmo_brightness.blockSignals(True)
                self.slider_atmo_contrast.setValue(int(mp.get("contrast", 0)))
                self.slider_atmo_brightness.setValue(int(mp.get("brightness", 0)))
                self.slider_atmo_contrast.blockSignals(False)
                self.slider_atmo_brightness.blockSignals(False)
        self._sync_atmo_enabled()
        self._emit_config()

    def _refresh_summary(self) -> None:
        """One-line plain-language recap of what is currently active."""
        try:
            cfg = self.collect_config()
        except Exception:
            return
        if not bool(getattr(cfg, "global_enabled", True)):
            self.label_summary.setText("All disturbances off — clean signal.")
            return
        parts = [str(cfg.atmospheric_preset)]
        try:
            sev = int(float(getattr(cfg, "channel_severity", 1.0)) * 100)
            if str(cfg.atmospheric_preset) != "Clear":
                parts.append(f"{sev}%")
        except Exception:
            pass
        if int(getattr(cfg, "turbulence", 0)):
            parts.append(f"turbulence {int(cfg.turbulence)}")
        if float(getattr(cfg, "camera_jitter", 0.0)) > 1e-9:
            parts.append(f"shake {float(cfg.camera_jitter):.1f}px")
        if float(getattr(cfg, "vibration", 0.0)) > 1e-9:
            parts.append(f"vibration {float(cfg.vibration):.1f}")
        if float(getattr(cfg, "camera_motion", 0.0)) > 1e-9:
            parts.append(f"drift {float(cfg.camera_motion):.1f}")
        noises = []
        if bool(cfg.enable_gaussian):
            noises.append(f"grain σ{float(cfg.gaussian_sigma):.1f}")
        if bool(cfg.enable_salt_pepper):
            noises.append(f"speckle {float(cfg.salt_pepper_density) * 100:.0f}%")
        if bool(cfg.enable_poisson):
            noises.append("flicker")
        if noises:
            parts.append(" + ".join(noises))
        if float(getattr(cfg, "platform_speed", 0.0)) > 1e-9:
            parts.append(f"drift {cfg.platform_profile} {float(cfg.platform_speed):.1f}px/f")
        if len(parts) <= 1 and str(cfg.atmospheric_preset) == "Clear":
            self.label_summary.setText("Clear air — no visible effect.")
        else:
            self.label_summary.setText(" · ".join(parts))
        self._refresh_module_nav(cfg)

    def _refresh_module_nav(self, cfg) -> None:
        """Module status at a glance without opening tabs (Design.md §5)."""
        try:
            preset = str(cfg.atmospheric_preset)
            try:
                sev = int(float(getattr(cfg, "channel_severity", 1.0)) * 100)
            except (TypeError, ValueError):
                sev = 100
            turb = int(getattr(cfg, "turbulence", 0))
            air_on = preset != "Clear" or turb > 0
            air_sub = f"{preset} · {sev}%" if air_on else "Clear"
            if air_on and turb > 0:
                air_sub += f" · turb {turb}"
            jit = float(getattr(cfg, "camera_jitter", 0.0))
            spd = float(getattr(cfg, "platform_speed", 0.0))
            vib = float(getattr(cfg, "vibration", 0.0))
            drf = float(getattr(cfg, "camera_motion", 0.0))
            cam_on = jit > 1e-9 or spd > 1e-9 or vib > 1e-9 or drf > 1e-9
            cam_sub = f"shake {jit:.1f}px" if jit > 1e-9 else ""
            if vib > 1e-9:
                cam_sub = (cam_sub + " · " if cam_sub else "") + f"vib {vib:.1f}"
            if drf > 1e-9:
                cam_sub = (cam_sub + " · " if cam_sub else "") + f"drift {drf:.1f}"
            if spd > 1e-9:
                cam_sub = (cam_sub + " · " if cam_sub else "") + f"drift {spd:.1f}px/f"
            cam_sub = cam_sub or "Off"
            noises = []
            if bool(cfg.enable_gaussian):
                noises.append(f"grain σ{float(cfg.gaussian_sigma):.1f}")
            if bool(cfg.enable_salt_pepper):
                noises.append(f"speckle {float(cfg.salt_pepper_density) * 100:.0f}%")
            if bool(cfg.enable_poisson):
                noises.append("flicker")
            sen_on = bool(noises)
            sen_sub = " + ".join(noises) if noises else "Off"
            self.nav_air.setText(f"Air & Light\n{'● ' + air_sub if air_on else '○ Off'}")
            self.nav_camera.setText(f"Camera Motion\n{'● ' + cam_sub if cam_on else '○ Off'}")
            self.nav_sensor.setText(f"Sensor Noise\n{'● ' + sen_sub if sen_on else '○ Off'}")
            # Weather context line under the Weather card (§6).
            try:
                self.label_weather_context.setText(
                    f"{preset} · severity {sev}% · contrast {int(cfg.atmospheric_contrast)}% · "
                    f"brightness {int(cfg.atmospheric_brightness)}%"
                    if air_on else "Clear air — no weather effect.")
            except (TypeError, ValueError, AttributeError):
                pass
            # Mirror scenario combo into quick chips (manual edits → Custom).
            if not getattr(self, "_applying_preset", False):
                combo_txt = ""
                try:
                    combo_txt = str(self.combo_channel_preset.currentText())
                except Exception:
                    pass
                self._sync_quick_presets(combo_txt or preset)
        except Exception as e:
            log.debug("module nav refresh skipped: %s", e)

    def collect_config(self) -> DisturbanceConfig:
        # Hidden legacy sliders are back-compat mirrors (kept synced in
        # set_config); the visible turbulence/vibration/drift sliders below
        # are authoritative.
        cfg = DisturbanceConfig(
            turbulence=int(self.slider_turbulence.value()),
            vibration=float(self.slider_vibration.value()) / 10.0,
            camera_motion=float(self.slider_cam_drift.value()) / 10.0,
            noise=int(self.sliders["Noise"].value()),
            enable_salt_pepper=bool(self.chk_salt_pepper.isChecked()),
            enable_gaussian=bool(self.chk_gaussian.isChecked()),
            enable_poisson=bool(self.chk_poisson.isChecked()),
            salt_pepper_density=self.slider_salt_density.value() / 100.0,
            salt_pepper_ratio=self.slider_salt_ratio.value() / 100.0,
            gaussian_sigma=self.slider_gaussian_sigma.value() / 10.0,
            gaussian_sigma_max=self.slider_gaussian_max.value() / 10.0,
            poisson_scale=self.slider_poisson_scale.value() / 10.0,
            poisson_peak=self.slider_poisson_peak.value(),
            max_noise_std=self.slider_gaussian_max.value() / 10.0,
            camera_jitter=self.slider_jitter.value() / 10.0,
            camera_jitter_enabled=bool(self.chk_jitter_enabled.isChecked()),
            atmospheric_preset=str(self.combo_atmospheric.currentText()),
            atmospheric_contrast=self.slider_atmo_contrast.value(),
            atmospheric_brightness=self.slider_atmo_brightness.value(),
            platform_enabled=bool(self.chk_platform_enabled.isChecked()),
            platform_profile=str(self.combo_platform.currentText()),
            platform_speed=self.slider_platform_speed.value() / 10.0,
            platform_amplitude_x=float(self.slider_platform_amp_x.value()),
            platform_amplitude_y=float(self.slider_platform_amp_y.value()),
            platform_direction=float(self.slider_platform_direction.value()),
            global_enabled=bool(self.chk_global_enabled.isChecked()),
            channel_enabled=bool(self.chk_channel_enabled.isChecked()),
            channel_severity=self.slider_channel_severity.value() / 100.0,
            channel_attenuation_strength=self.slider_channel_attenuation.value() / 100.0,
            channel_attenuation_model=str(self.combo_attenuation_model.currentText()),
            channel_beam_wander=self.slider_beam_wander.value() / 100.0,
            channel_beam_spread=self.slider_beam_spread.value() / 100.0,
            channel_intensity_fluctuation=self.slider_intensity_fluct.value() / 100.0,
        )
        return cfg.validate()

    def set_config(self, cfg: DisturbanceConfig, emit: bool = False) -> None:
        cfg = cfg.validate()
        widgets = [
            self.chk_salt_pepper, self.chk_gaussian, self.chk_poisson,
            self.chk_global_enabled, self.chk_channel_enabled, self.chk_jitter_enabled,
            self.chk_platform_enabled, self.combo_channel_preset, self.combo_attenuation_model,
            self.slider_channel_severity, self.slider_channel_attenuation,
            self.slider_turbulence, self.slider_beam_wander, self.slider_beam_spread,
            self.slider_intensity_fluct,
            self.slider_salt_density, self.slider_salt_ratio,
            self.slider_gaussian_sigma, self.slider_gaussian_max,
            self.slider_poisson_scale, self.slider_poisson_peak,
            self.slider_jitter, self.slider_vibration, self.slider_cam_drift,
            self.combo_atmospheric, self.slider_atmo_contrast, self.slider_atmo_brightness,
            self.combo_platform, self.slider_platform_speed,
            self.slider_platform_amp_x, self.slider_platform_amp_y, self.slider_platform_direction,
        ]
        for w in widgets:
            w.blockSignals(True)
        for s in self.sliders.values():
            s.blockSignals(True)
        try:
            for k in ["Turbulence", "Vibration", "Camera Motion", "Noise"]:
                # hidden sliders mirror cfg (back-compat for external readers)
                if k == "Turbulence": self.sliders[k].setValue(int(cfg.turbulence))
                elif k == "Vibration": self.sliders[k].setValue(int(float(cfg.vibration)))
                elif k == "Camera Motion": self.sliders[k].setValue(int(float(cfg.camera_motion)))
                elif k == "Noise": self.sliders[k].setValue(int(cfg.noise))
            self.chk_salt_pepper.setChecked(bool(cfg.enable_salt_pepper))
            self.chk_gaussian.setChecked(bool(cfg.enable_gaussian))
            self.chk_poisson.setChecked(bool(cfg.enable_poisson))
            self.slider_salt_density.setValue(int(cfg.salt_pepper_density * 100))
            self.label_salt_density_val.setText(f"{cfg.salt_pepper_density:.2f}")
            self.slider_salt_ratio.setValue(int(getattr(cfg, "salt_pepper_ratio", 0.5) * 100))
            self.label_salt_ratio_val.setText(f"{getattr(cfg, 'salt_pepper_ratio', 0.5):.2f}")
            self.slider_gaussian_sigma.setValue(int(cfg.gaussian_sigma * 10))
            self.label_gaussian_sigma_val.setText(f"{cfg.gaussian_sigma:.1f} px")
            self.slider_gaussian_max.setValue(int(cfg.gaussian_sigma_max * 10))
            self.label_gaussian_max_val.setText(f"{cfg.gaussian_sigma_max:.1f} px")
            self.slider_poisson_scale.setValue(int(getattr(cfg, "poisson_scale", 1.0) * 10))
            self.label_poisson_scale_val.setText(f"{getattr(cfg, 'poisson_scale', 1.0):.1f}×")
            self.slider_poisson_peak.setValue(int(getattr(cfg, "poisson_peak", 100)))
            self.label_poisson_peak_val.setText(str(getattr(cfg, "poisson_peak", 100)))
            self.slider_jitter.setValue(int(cfg.camera_jitter * 10))
            self.label_jitter_val.setText(f"{cfg.camera_jitter:.1f} px")
            self.slider_vibration.setValue(int(round(float(cfg.vibration) * 10)))
            self.label_vibration_val.setText(f"{float(cfg.vibration):.1f}")
            self.slider_cam_drift.setValue(int(round(float(cfg.camera_motion) * 10)))
            self.label_cam_drift_val.setText(f"{float(cfg.camera_motion):.1f}")
            self.chk_jitter_enabled.setChecked(bool(getattr(cfg, "camera_jitter_enabled", True)))
            self.chk_global_enabled.setChecked(bool(getattr(cfg, "global_enabled", True)))
            self.chk_channel_enabled.setChecked(bool(getattr(cfg, "channel_enabled", True)))
            self.chk_platform_enabled.setChecked(bool(getattr(cfg, "platform_enabled", True)))
            self.slider_channel_severity.setValue(int(float(getattr(cfg, "channel_severity", 1.0)) * 100))
            self.label_channel_severity_val.setText(f"{int(float(getattr(cfg, 'channel_severity', 1.0)) * 100)}%")
            self.slider_channel_attenuation.setValue(int(float(getattr(cfg, "channel_attenuation_strength", 1.0)) * 100))
            self.label_channel_attenuation_val.setText(f"{float(getattr(cfg, 'channel_attenuation_strength', 1.0)):.2f}")
            idxm = self.combo_attenuation_model.findText(str(getattr(cfg, "channel_attenuation_model", "Atmospheric")))
            if idxm >= 0:
                self.combo_attenuation_model.setCurrentIndex(idxm)
            self.slider_turbulence.setValue(int(cfg.turbulence))
            self.label_turbulence_val.setText(str(int(cfg.turbulence)))
            self.sliders["Turbulence"].setValue(int(cfg.turbulence))
            self.slider_beam_wander.setValue(int(float(getattr(cfg, "channel_beam_wander", 1.0)) * 100))
            self.label_beam_wander_val.setText(f"{float(getattr(cfg, 'channel_beam_wander', 1.0)):.2f}×")
            self.slider_beam_spread.setValue(int(float(getattr(cfg, "channel_beam_spread", 1.0)) * 100))
            self.label_beam_spread_val.setText(f"{float(getattr(cfg, 'channel_beam_spread', 1.0)):.2f}×")
            self.slider_intensity_fluct.setValue(int(float(getattr(cfg, "channel_intensity_fluctuation", 1.0)) * 100))
            self.label_intensity_fluct_val.setText(f"{float(getattr(cfg, 'channel_intensity_fluctuation', 1.0)):.2f}×")
            idx = self.combo_atmospheric.findText(str(cfg.atmospheric_preset))
            if idx >= 0:
                self.combo_atmospheric.setCurrentIndex(idx)
            else:
                self.combo_atmospheric.setCurrentText(str(cfg.atmospheric_preset))
            if str(cfg.atmospheric_preset) != "User Defined":
                from src.disturbance.core.constants import ATMOSPHERIC_PRESET_MAP as _AMap
                mp = _AMap.get(str(cfg.atmospheric_preset), {})
                self.slider_atmo_contrast.setValue(int(mp.get("contrast", int(cfg.atmospheric_contrast))))
                self.label_atmo_contrast_val.setText(f"{int(mp.get('contrast', int(cfg.atmospheric_contrast)))}%")
                self.slider_atmo_brightness.setValue(int(mp.get("brightness", int(cfg.atmospheric_brightness))))
                self.label_atmo_brightness_val.setText(f"{int(mp.get('brightness', int(cfg.atmospheric_brightness)))}%")
            else:
                self.slider_atmo_contrast.setValue(int(cfg.atmospheric_contrast))
                self.label_atmo_contrast_val.setText(f"{int(cfg.atmospheric_contrast)}%")
                self.slider_atmo_brightness.setValue(int(cfg.atmospheric_brightness))
                self.label_atmo_brightness_val.setText(f"{int(cfg.atmospheric_brightness)}%")
            idx2 = self.combo_platform.findText(str(cfg.platform_profile))
            if idx2 >= 0:
                self.combo_platform.setCurrentIndex(idx2)
            else:
                self.combo_platform.setCurrentText(str(cfg.platform_profile))
            self.slider_platform_speed.setValue(int(cfg.platform_speed * 10))
            self.label_platform_speed_val.setText(f"{cfg.platform_speed:.1f} px/f")
            self.slider_platform_amp_x.setValue(int(float(getattr(cfg, "platform_amplitude_x", 110.0))))
            self.label_platform_amp_x_val.setText(f"{float(getattr(cfg, 'platform_amplitude_x', 110.0)):.0f} px")
            self.slider_platform_amp_y.setValue(int(float(getattr(cfg, "platform_amplitude_y", 110.0))))
            self.label_platform_amp_y_val.setText(f"{float(getattr(cfg, 'platform_amplitude_y', 110.0)):.0f} px")
            self.slider_platform_direction.setValue(int(float(getattr(cfg, "platform_direction", 0.0))))
            self.label_platform_direction_val.setText(f"{float(getattr(cfg, 'platform_direction', 0.0)):.0f}°")
            self._sync_atmo_enabled()
            self._sync_sensor_details(bool(self.chk_sensor_details.isChecked()))
        finally:
            for w in widgets:
                w.blockSignals(False)
            for s in self.sliders.values():
                s.blockSignals(False)
        self._refresh_summary()
        if emit:
            self._emit_config()

    def _enhance_slider_highlight(self):
        # Add pressed/released highlighting for all sliders (light theme highlight)
        for slider, label in [
            (self.slider_channel_severity, self.label_channel_severity_val),
            (self.slider_channel_attenuation, self.label_channel_attenuation_val),
            (self.slider_turbulence, self.label_turbulence_val),
            (self.slider_beam_wander, self.label_beam_wander_val),
            (self.slider_beam_spread, self.label_beam_spread_val),
            (self.slider_intensity_fluct, self.label_intensity_fluct_val),
            (self.slider_salt_density, self.label_salt_density_val),
            (self.slider_salt_ratio, self.label_salt_ratio_val),
            (self.slider_gaussian_sigma, self.label_gaussian_sigma_val),
            (self.slider_gaussian_max, self.label_gaussian_max_val),
            (self.slider_poisson_scale, self.label_poisson_scale_val),
            (self.slider_poisson_peak, self.label_poisson_peak_val),
            (self.slider_jitter, self.label_jitter_val),
            (self.slider_vibration, self.label_vibration_val),
            (self.slider_cam_drift, self.label_cam_drift_val),
            (self.slider_atmo_contrast, self.label_atmo_contrast_val),
            (self.slider_atmo_brightness, self.label_atmo_brightness_val),
            (self.slider_platform_speed, self.label_platform_speed_val),
            (self.slider_platform_amp_x, self.label_platform_amp_x_val),
            (self.slider_platform_amp_y, self.label_platform_amp_y_val),
            (self.slider_platform_direction, self.label_platform_direction_val),
        ]:
            slider.sliderPressed.connect(lambda lbl=label: lbl.setStyleSheet("color:#1e40af; font-weight:700; background:#dbeafe; border:2px solid #3b82f6; border-radius:4px; padding:2px 4px; font-size:11px;"))
            slider.sliderReleased.connect(lambda lbl=label: lbl.setStyleSheet("color:#374151; font-size:11px;"))

    def _on_reset(self):
        self.set_config(DisturbanceConfig().validate(), emit=True)

    def _emit_config(self) -> None:
        if getattr(self, "_building", False):
            return
        # Release-gated: coalesce slider drags into the sliderReleased
        # emit. valueChanged during a drag only updates the pill label
        # (wired separately); the config itself fires on release or for
        # non-drag changes (keyboard, programmatic, toggles, combos).
        try:
            sender = self.sender()
            from PyQt5.QtWidgets import QSlider as _QSlider
            if isinstance(sender, _QSlider) and sender.isSliderDown():
                return
        except Exception:
            pass
        # Live-apply (Design.md §15): disturbance changes cost no rebuild —
        # they take effect on the next frame, so every gesture step emits and
        # MainWindow's 250 ms coalescer bounds the apply rate. sliderReleased
        # re-emits the final value as a guarantee.
        # Any manual tweak means the setup no longer matches a named preset.
        if not getattr(self, "_applying_preset", False):
            try:
                combo = getattr(self, "combo_channel_preset", None)
                if combo is not None and str(combo.currentText()) != "Custom":
                    combo.blockSignals(True)
                    idx = combo.findText("Custom")
                    if idx >= 0:
                        combo.setCurrentIndex(idx)
                    combo.blockSignals(False)
            except Exception:
                pass
        try:
            cfg = self.collect_config()
            try:
                self._refresh_summary()
            except Exception as e:
                log.debug("disturbances summary refresh skipped: %s", e)
            self.configChanged.emit(cfg)
        except Exception as e:
            log.warning("disturbances config invalid, not applied: %s", e)

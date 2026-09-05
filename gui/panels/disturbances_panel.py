# gui/panels/disturbances_panel.py - Disturbance & Noise — Simplified (no redundant params)

from PyQt5.QtCore import Qt, pyqtSignal

from gui.panels.base import BaseConfigPanel
from PyQt5.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFrame,
    QGridLayout,
    QGroupBox,
    QLabel,
    QSpinBox,
    QVBoxLayout,
    QSlider,
)

from disturbance.config import DisturbanceConfig
from disturbance.constants import (
    ATMOSPHERIC_PRESETS,
    PLATFORM_PROFILES,
)

class DisturbancesPanel(BaseConfigPanel):
    """
    Simplified Disturbances tab — spec-only, no redundant controls.

    Groups:
      B Image Noise — S&P 10% + Gaussian σ (20px + user 1..50) + Poisson (multi-select, one or more at once)
      C Camera Jitter — ±20 px/frame + user to 50
      D Atmospheric — Clear/Haze/Fog/User Defined + contrast/brightness (user only when User Defined)
      E Platform Motion — Linear (default mandatory) + 6 optionals + speed 0..20 (+user 50)

    Removed redundant:
      - Legacy 0..10 Turbulence/Vibration/Camera Motion/Noise sliders (superseded by new precise controls)
      - Alias Max Std spin (mirrors Gaussian max)
      - Duplicate slider+spin pairs (kept single spin per param)
      - Poisson scale (Poisson is toggle-only per spec)
    Back-compat: `sliders` dict remains (hidden 0 values) so `disturbances_panel.sliders['Vibration']` etc still exist.
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
        self._build_ui()
        self.set_config(self._initial, emit=False)

    def _build_ui(self) -> None:
        self._building = True
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(10)

        banner = QFrame()
        banner.setStyleSheet("QFrame { background: #ffffff; border:1px solid #e5e7eb; border-radius:6px; }")
        bl = QVBoxLayout(banner)
        bl.setContentsMargins(10, 8, 10, 8)
        bl.setSpacing(3)
        bt = QLabel("Disturbance & Noise")
        bt.setStyleSheet("color:#111827; font-weight:700; font-size:11px; background: transparent;")
        bt.setAlignment(Qt.AlignCenter)
        bl.addWidget(bt)
        bs = QLabel("S&P 10% · Gaussian σ 20px+User · Poisson · Jitter ±20px · Atmosphere 4 presets · Platform 7 profiles")
        bs.setStyleSheet("color:#6b7280; font-size:10px; background: transparent;")
        bs.setWordWrap(True)
        bs.setAlignment(Qt.AlignCenter)
        bl.addWidget(bs)
        layout.addWidget(banner)

        # ── B — Image Noise ──
        img_box = QGroupBox("Image Noise — one or more at once")
        img_grid = QGridLayout(img_box)
        img_grid.setContentsMargins(12, 18, 12, 12)
        img_grid.setHorizontalSpacing(8)
        img_grid.setVerticalSpacing(8)
        img_grid.setColumnStretch(1, 1)

        self.chk_salt_pepper = QCheckBox("Salt && Pepper (~10%)")
        self.chk_salt_pepper.setToolTip("10% of pixels to 0/255 (density configurable)")
        self.chk_gaussian = QCheckBox("Gaussian")
        self.chk_gaussian.setToolTip("Additive N(0,σ²), σ=StdDev")
        self.chk_poisson = QCheckBox("Poisson")
        self.chk_poisson.setToolTip("Shot noise — Poisson(rate) scaled")
        for cb in [self.chk_salt_pepper, self.chk_gaussian, self.chk_poisson]:
            cb.setStyleSheet("color:#374151; font-size:11px;")
        img_grid.addWidget(self.chk_salt_pepper, 0, 0)
        img_grid.addWidget(self.chk_gaussian, 0, 1)
        img_grid.addWidget(self.chk_poisson, 0, 2)

        # S&P params — only visible when S&P checked
        self.label_salt_density = self._label("S&P density")
        img_grid.addWidget(self.label_salt_density, 1, 0)
        self.slider_salt_density = QSlider(Qt.Horizontal)
        self.slider_salt_density.setRange(0, 20)  # 0.0 to 0.20 step 0.01
        self.slider_salt_density.setValue(10)
        self.slider_salt_density.setToolTip("Salt & Pepper density 0..0.20 — 10 = 10%")
        self.label_salt_density_val = QLabel("0.10")
        self.label_salt_density_val.setMinimumHeight(26)
        self.label_salt_density_val.setStyleSheet("color:#374151; font-size:11px;")
        img_grid.addWidget(self.slider_salt_density, 1, 1)
        img_grid.addWidget(self.label_salt_density_val, 1, 2)
        
        # extra S&P param: salt vs pepper ratio
        self.label_salt_ratio = self._label("S/P ratio")
        img_grid.addWidget(self.label_salt_ratio, 1, 3)
        self.slider_salt_ratio = QSlider(Qt.Horizontal)
        self.slider_salt_ratio.setRange(0, 100)  # 0.0 to 1.0 step 0.01
        self.slider_salt_ratio.setValue(50)
        self.slider_salt_ratio.setToolTip("Salt vs Pepper ratio 0..1")
        self.label_salt_ratio_val = QLabel("0.50")
        self.label_salt_ratio_val.setMinimumHeight(26)
        self.label_salt_ratio_val.setStyleSheet("color:#374151; font-size:11px;")
        img_grid.addWidget(self.slider_salt_ratio, 1, 4)
        img_grid.addWidget(self.label_salt_ratio_val, 1, 5)

        # Gaussian params — only visible when Gaussian checked
        self.label_gaussian_sigma = self._label("Gaussian σ")
        img_grid.addWidget(self.label_gaussian_sigma, 2, 0)
        self.slider_gaussian_sigma = QSlider(Qt.Horizontal)
        self.slider_gaussian_sigma.setRange(0, 500)  # 0.0 to 50.0 step 0.1
        self.slider_gaussian_sigma.setValue(80)
        self.slider_gaussian_sigma.setToolTip("Gaussian σ 0..50 px")
        self.label_gaussian_sigma_val = QLabel("8.0 px")
        self.label_gaussian_sigma_val.setMinimumHeight(26)
        self.label_gaussian_sigma_val.setStyleSheet("color:#374151; font-size:11px;")
        img_grid.addWidget(self.slider_gaussian_sigma, 2, 1)
        img_grid.addWidget(self.label_gaussian_sigma_val, 2, 2)

        self.label_gaussian_max = self._label("Max σ (User)")
        img_grid.addWidget(self.label_gaussian_max, 2, 3)
        self.slider_gaussian_max = QSlider(Qt.Horizontal)
        self.slider_gaussian_max.setRange(10, 500)  # 1.0 to 50.0 step 0.1
        self.slider_gaussian_max.setValue(200)
        self.slider_gaussian_max.setToolTip("Gaussian max σ 1..50 px")
        self.label_gaussian_max_val = QLabel("20.0 px")
        self.label_gaussian_max_val.setMinimumHeight(26)
        self.label_gaussian_max_val.setStyleSheet("color:#374151; font-size:11px;")
        img_grid.addWidget(self.slider_gaussian_max, 2, 4)
        img_grid.addWidget(self.label_gaussian_max_val, 2, 5)

        # Poisson params — only visible when Poisson checked
        self.label_poisson_scale = self._label("Poisson scale")
        img_grid.addWidget(self.label_poisson_scale, 3, 0)
        self.slider_poisson_scale = QSlider(Qt.Horizontal)
        self.slider_poisson_scale.setRange(5, 50)  # 0.5 to 5.0 step 0.1
        self.slider_poisson_scale.setValue(10)
        self.slider_poisson_scale.setToolTip("Poisson scale 0.5..5.0")
        self.label_poisson_scale_val = QLabel("1.0×")
        self.label_poisson_scale_val.setMinimumHeight(26)
        self.label_poisson_scale_val.setStyleSheet("color:#374151; font-size:11px;")
        img_grid.addWidget(self.slider_poisson_scale, 3, 1)
        img_grid.addWidget(self.label_poisson_scale_val, 3, 2)

        self.label_poisson_peak = self._label("Peak")
        img_grid.addWidget(self.label_poisson_peak, 3, 3)
        self.slider_poisson_peak = QSlider(Qt.Horizontal)
        self.slider_poisson_peak.setRange(30, 255)
        self.slider_poisson_peak.setValue(100)
        self.slider_poisson_peak.setToolTip("Poisson peak 30..255")
        self.label_poisson_peak_val = QLabel("100")
        self.label_poisson_peak_val.setMinimumHeight(26)
        self.label_poisson_peak_val.setStyleSheet("color:#374151; font-size:11px;")
        img_grid.addWidget(self.slider_poisson_peak, 3, 4)
        img_grid.addWidget(self.label_poisson_peak_val, 3, 5)

        hint = QLabel("Only selected types show params — select multiple to stack as Gaussian → Poisson → S&P.")
        hint.setWordWrap(True)
        hint.setStyleSheet("color:#64748b; font-size:10px; font-style:italic;")
        img_grid.addWidget(hint, 4, 0, 1, 6)
        layout.addWidget(img_box)

        # ── C — Camera Jitter ──
        jitter_box = QGroupBox("Camera Jitter — ± px / frame")
        jitter_grid = QGridLayout(jitter_box)
        jitter_grid.setContentsMargins(12, 18, 12, 12)
        jitter_grid.setHorizontalSpacing(8)
        jitter_grid.setVerticalSpacing(8)
        jitter_grid.setColumnStretch(1, 1)
        jitter_grid.addWidget(self._label("Jitter"), 0, 0)
        self.slider_jitter = QSlider(Qt.Horizontal)
        self.slider_jitter.setRange(0, 500)  # 0.0 to 50.0 step 0.1
        self.slider_jitter.setValue(0)
        self.slider_jitter.setToolTip("Jitter ±0..50 px/frame")
        self.label_jitter_val = QLabel("0.0 px")
        self.label_jitter_val.setMinimumHeight(26)
        self.label_jitter_val.setStyleSheet("color:#374151; font-size:11px;")
        jitter_grid.addWidget(self.slider_jitter, 0, 1)
        jitter_grid.addWidget(self.label_jitter_val, 0, 2)
        layout.addWidget(jitter_box)

        # ── D — Atmospheric ──
        atmo_box = QGroupBox("Atmospheric — Clear / Haze / Fog / User Defined")
        atmo_grid = QGridLayout(atmo_box)
        atmo_grid.setContentsMargins(12, 18, 12, 12)
        atmo_grid.setHorizontalSpacing(8)
        atmo_grid.setVerticalSpacing(8)
        atmo_grid.setColumnStretch(1, 1)
        atmo_grid.addWidget(self._label("Preset"), 0, 0)
        self.combo_atmospheric = QComboBox()
        self.combo_atmospheric.addItems(list(ATMOSPHERIC_PRESETS))
        self.combo_atmospheric.setCurrentText("Clear")
        self.combo_atmospheric.setMinimumHeight(26)
        atmo_grid.addWidget(self.combo_atmospheric, 0, 1)
        atmo_grid.addWidget(self._label("Contrast ↓"), 0, 2)
        self.slider_atmo_contrast = QSlider(Qt.Horizontal)
        self.slider_atmo_contrast.setRange(0, 100)
        self.slider_atmo_contrast.setValue(0)
        self.slider_atmo_contrast.setToolTip("Atmosphere contrast 0..100%")
        self.label_atmo_contrast_val = QLabel("0%")
        self.label_atmo_contrast_val.setMinimumHeight(26)
        self.label_atmo_contrast_val.setStyleSheet("color:#374151; font-size:11px;")
        atmo_grid.addWidget(self.slider_atmo_contrast, 0, 3)
        atmo_grid.addWidget(self.label_atmo_contrast_val, 0, 4)
        atmo_grid.addWidget(self._label("Brightness ↓"), 1, 0)
        self.slider_atmo_brightness = QSlider(Qt.Horizontal)
        self.slider_atmo_brightness.setRange(0, 100)
        self.slider_atmo_brightness.setValue(0)
        self.slider_atmo_brightness.setToolTip("Atmosphere brightness 0..100%")
        self.label_atmo_brightness_val = QLabel("0%")
        self.label_atmo_brightness_val.setMinimumHeight(26)
        self.label_atmo_brightness_val.setStyleSheet("color:#374151; font-size:11px;")
        atmo_grid.addWidget(self.slider_atmo_brightness, 1, 1)
        atmo_grid.addWidget(self.label_atmo_brightness_val, 1, 2)
        self.label_atmo_hint = QLabel("Clear 0/0 · Haze 15/10 · Fog 38/22")
        self.label_atmo_hint.setStyleSheet("color:#64748b; font-size:10px; font-style:italic;")
        self.label_atmo_hint.setWordWrap(True)
        atmo_grid.addWidget(self.label_atmo_hint, 2, 0, 1, 4)
        layout.addWidget(atmo_box)

        # ── E — Platform Motion ──
        plat_box = QGroupBox("Platform Motion — Linear (Default) + 6 optionals — ±20 px/frame MAX")
        plat_grid = QGridLayout(plat_box)
        plat_grid.setContentsMargins(12, 18, 12, 12)
        plat_grid.setHorizontalSpacing(8)
        plat_grid.setVerticalSpacing(8)
        plat_grid.setColumnStretch(1, 1)
        plat_grid.addWidget(self._label("Profile"), 0, 0)
        self.combo_platform = QComboBox()
        self.combo_platform.addItems(list(PLATFORM_PROFILES))
        self.combo_platform.setCurrentText("Linear")
        self.combo_platform.setMinimumHeight(26)
        plat_grid.addWidget(self.combo_platform, 0, 1)
        plat_grid.addWidget(self._label("Speed"), 0, 2)
        self.slider_platform_speed = QSlider(Qt.Horizontal)
        self.slider_platform_speed.setRange(0, 500)  # 0.0 to 50.0 step 0.1
        self.slider_platform_speed.setValue(0)
        self.slider_platform_speed.setToolTip("Platform speed 0..50 px/f")
        self.label_platform_speed_val = QLabel("0.0 px/f")
        self.label_platform_speed_val.setMinimumHeight(26)
        self.label_platform_speed_val.setStyleSheet("color:#374151; font-size:11px;")
        plat_grid.addWidget(self.slider_platform_speed, 0, 3)
        plat_grid.addWidget(self.label_platform_speed_val, 0, 4)
        plat_hint = QLabel("Linear is mandatory default. All profiles dt-aware.")
        plat_hint.setStyleSheet("color:#64748b; font-size:10px; font-style:italic;")
        plat_hint.setWordWrap(True)
        plat_grid.addWidget(plat_hint, 1, 0, 1, 5)
        layout.addWidget(plat_box)

        layout.addStretch()
        self._wire_signals()
        self._building = False
        self._sync_atmo_enabled()
        self._sync_image_noise_visibility()

    def _wire_signals(self) -> None:
        for cb in [self.chk_salt_pepper, self.chk_gaussian, self.chk_poisson]:
            cb.toggled.connect(lambda _: self._sync_image_noise_visibility())
            cb.toggled.connect(lambda _: self._emit_config())
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
        self.combo_atmospheric.currentTextChanged.connect(self._on_atmo_preset_changed)
        self.slider_atmo_contrast.valueChanged.connect(lambda _: self._emit_config())
        self.slider_atmo_contrast.valueChanged.connect(lambda val: self.label_atmo_contrast_val.setText(f"{val}%"))
        self.slider_atmo_brightness.valueChanged.connect(lambda _: self._emit_config())
        self.slider_atmo_brightness.valueChanged.connect(lambda val: self.label_atmo_brightness_val.setText(f"{val}%"))
        self.combo_platform.currentTextChanged.connect(lambda _: self._emit_config())
        self.slider_platform_speed.valueChanged.connect(lambda _: self._emit_config())
        self.slider_platform_speed.valueChanged.connect(lambda val: self.label_platform_speed_val.setText(f"{val/10:.1f} px/f"))

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
        """Only selected types show their parameter rows."""
        is_sp = bool(self.chk_salt_pepper.isChecked())
        is_g = bool(self.chk_gaussian.isChecked())
        is_p = bool(self.chk_poisson.isChecked())
        for w in [self.label_salt_density, self.slider_salt_density, self.label_salt_ratio, self.slider_salt_ratio]:
            w.setVisible(is_sp)
        for w in [self.label_gaussian_sigma, self.slider_gaussian_sigma, self.label_gaussian_max, self.slider_gaussian_max]:
            w.setVisible(is_g)
        for w in [self.label_poisson_scale, self.slider_poisson_scale, self.label_poisson_peak, self.slider_poisson_peak]:
            w.setVisible(is_p)

    def _sync_atmo_enabled(self):
        is_user = str(self.combo_atmospheric.currentText()) == "User Defined"
        self.slider_atmo_contrast.setEnabled(is_user)
        self.slider_atmo_brightness.setEnabled(is_user)
        self.slider_atmo_contrast.setToolTip("User Defined only" if not is_user else "Contrast reduction 0..100%")
        self.slider_atmo_brightness.setToolTip("User Defined only" if not is_user else "Brightness reduction 0..100%")

    def _on_atmo_preset_changed(self, preset: str):
        from disturbance.constants import ATMOSPHERIC_PRESET_MAP
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

    def collect_config(self) -> DisturbanceConfig:
        # Hidden legacy sliders are 0 (removed from UI)
        cfg = DisturbanceConfig(
            turbulence=int(self.sliders["Turbulence"].value()),
            vibration=int(self.sliders["Vibration"].value()),
            camera_motion=int(self.sliders["Camera Motion"].value()),
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
            atmospheric_preset=str(self.combo_atmospheric.currentText()),
            atmospheric_contrast=self.slider_atmo_contrast.value(),
            atmospheric_brightness=self.slider_atmo_brightness.value(),
            platform_profile=str(self.combo_platform.currentText()),
            platform_speed=self.slider_platform_speed.value() / 10.0,
        )
        return cfg.validate()

    def set_config(self, cfg: DisturbanceConfig, emit: bool = False) -> None:
        cfg = cfg.validate()
        widgets = [
            self.chk_salt_pepper, self.chk_gaussian, self.chk_poisson,
            self.slider_salt_density, self.slider_salt_ratio,
            self.slider_gaussian_sigma, self.slider_gaussian_max,
            self.slider_poisson_scale, self.slider_poisson_peak,
            self.slider_jitter, self.combo_atmospheric, self.slider_atmo_contrast, self.slider_atmo_brightness,
            self.combo_platform, self.slider_platform_speed,
        ]
        for w in widgets:
            w.blockSignals(True)
        for s in self.sliders.values():
            s.blockSignals(True)
        try:
            for k in ["Turbulence", "Vibration", "Camera Motion", "Noise"]:
                # keep hidden sliders at cfg value (normally 0)
                if k == "Turbulence": self.sliders[k].setValue(int(cfg.turbulence))
                elif k == "Vibration": self.sliders[k].setValue(int(cfg.vibration))
                elif k == "Camera Motion": self.sliders[k].setValue(int(cfg.camera_motion))
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
            idx = self.combo_atmospheric.findText(str(cfg.atmospheric_preset))
            if idx >= 0:
                self.combo_atmospheric.setCurrentIndex(idx)
            else:
                self.combo_atmospheric.setCurrentText(str(cfg.atmospheric_preset))
            if str(cfg.atmospheric_preset) != "User Defined":
                from disturbance.constants import ATMOSPHERIC_PRESET_MAP as _AMap
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
            self._sync_atmo_enabled()
            self._sync_image_noise_visibility()
        finally:
            for w in widgets:
                w.blockSignals(False)
            for s in self.sliders.values():
                s.blockSignals(False)
        if emit:
            self._emit_config()

    def _emit_config(self) -> None:
        if getattr(self, "_building", False):
            return
        try:
            cfg = self.collect_config()
            self.configChanged.emit(cfg)
        except Exception:
            pass

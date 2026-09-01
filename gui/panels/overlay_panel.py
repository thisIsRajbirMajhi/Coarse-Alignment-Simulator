"""
Module: gui.panels.overlay_panel
Purpose: Crosshair / tracking overlay controls — intuitive grouped sections.
Public API: OverlayPanel
Groups:
  A) Crosshair — style, size, gap, thickness, centre dot
  B) Lock Status — colors per state, circle radius/thickness, pulse
  C) Error Visualization — line, text, units
Notes: Modular, well-commented, HOT via configChanged. Each control emits validated OverlayConfig.
"""

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtGui import QColor
from PyQt5.QtWidgets import (
    QCheckBox,
    QColorDialog,
    QComboBox,
    QDoubleSpinBox,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from overlay.config import OverlayConfig
from overlay.constants import CROSSHAIR_STYLES, ERROR_UNITS_OPTIONS, LOCK_COLOR_DEFAULTS, OVERLAY_LIMITS

# ============================================================
# SECTION: OverlayPanel — Crosshair / Tracking Overlay
# ============================================================

class OverlayPanel(QWidget):
    """
    Overlay tab — controls for crosshair, lock, and error.

    Exposed:
      All spins/combos/checks as attributes for MainWindow wiring (optional)
    Signal:
      configChanged(OverlayConfig) — on any param change (HOT, debounced)
    """

    configChanged = pyqtSignal(object)

    def __init__(self, initial: OverlayConfig | None = None, parent=None):
        super().__init__(parent)
        self._initial = (initial or OverlayConfig()).validate()
        self._build_ui()
        self.set_config(self._initial, emit=False)

    # ========================================================
    # Build UI — 3 grouped sections
    # ========================================================

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(10)

        # ----------------------------------------------------
        # Group A: Crosshair / Tracking Overlay
        # ----------------------------------------------------
        cross_box = QGroupBox("◈  A  —  CROSSHAIR  •  TRACKING OVERLAY")
        cross_grid = QGridLayout(cross_box)
        cross_grid.setContentsMargins(12, 18, 12, 12)
        cross_grid.setHorizontalSpacing(8)
        cross_grid.setVerticalSpacing(8)
        cross_grid.setColumnStretch(1, 1)
        cross_grid.setColumnStretch(3, 1)

        # 1) Style
        cross_grid.addWidget(self._label("Style"), 0, 0)
        self.style_combo = QComboBox()
        self.style_combo.addItems(CROSSHAIR_STYLES)
        self.style_combo.setToolTip("Crosshair style: Cross (+), Bracket corners, Circle, or combination")
        self.style_combo.setMinimumHeight(26)
        cross_grid.addWidget(self.style_combo, 0, 1, 1, 3)

        # 2) Size
        cross_grid.addWidget(self._label("Size"), 1, 0)
        self.size_spin = QSpinBox()
        lo, hi = OVERLAY_LIMITS["crosshair_size"]
        self.size_spin.setRange(int(lo), int(hi))
        self.size_spin.setSuffix(" px")
        self.size_spin.setToolTip("Arm length — size of crosshair arms (px)")
        self.size_spin.setMinimumHeight(26)
        cross_grid.addWidget(self.size_spin, 1, 1)

        # 3) Gap
        cross_grid.addWidget(self._label("Gap"), 1, 2)
        self.gap_spin = QSpinBox()
        lo, hi = OVERLAY_LIMITS["crosshair_gap"]
        self.gap_spin.setRange(int(lo), int(hi))
        self.gap_spin.setSuffix(" px")
        self.gap_spin.setToolTip("Gap from centre to arm start (px)")
        self.gap_spin.setMinimumHeight(26)
        cross_grid.addWidget(self.gap_spin, 1, 3)

        # 4) Thickness
        cross_grid.addWidget(self._label("Thickness"), 2, 0)
        self.thick_spin = QSpinBox()
        lo, hi = OVERLAY_LIMITS["crosshair_thickness"]
        self.thick_spin.setRange(int(lo), int(hi))
        self.thick_spin.setSuffix(" px")
        self.thick_spin.setMinimumHeight(26)
        cross_grid.addWidget(self.thick_spin, 2, 1)

        # 5) Centre dot
        self.dot_check = QCheckBox("Centre dot")
        self.dot_check.setToolTip("Toggle centre dot at FOV centre")
        self.dot_check.setStyleSheet("font-size:11px;")
        cross_grid.addWidget(self.dot_check, 2, 2)
        self.dot_radius_spin = QSpinBox()
        lo, hi = OVERLAY_LIMITS["centre_dot_radius"]
        self.dot_radius_spin.setRange(int(lo), int(hi))
        self.dot_radius_spin.setSuffix(" px")
        self.dot_radius_spin.setToolTip("Centre dot radius (0=off, 1..4 px)")
        self.dot_radius_spin.setMinimumHeight(26)
        cross_grid.addWidget(self.dot_radius_spin, 2, 3)

        layout.addWidget(cross_box)

        # ----------------------------------------------------
        # Group B: Lock Status Indication
        # ----------------------------------------------------
        lock_box = QGroupBox("◎  B  —  LOCK  STATUS")
        lock_grid = QGridLayout(lock_box)
        lock_grid.setContentsMargins(12, 18, 12, 12)
        lock_grid.setHorizontalSpacing(8)
        lock_grid.setVerticalSpacing(8)
        lock_grid.setColumnStretch(1, 1)
        lock_grid.setColumnStretch(3, 1)

        # Colors per state — compact row with color buttons
        lock_grid.addWidget(self._label("Colors per state"), 0, 0)
        self.color_buttons: dict[str, QPushButton] = {}
        colors_layout = QHBoxLayout()
        colors_layout.setSpacing(4)
        for key in ["searching", "acquired", "tracking", "lost", "detecting"]:
            btn = QPushButton()
            btn.setFixedSize(28, 22)
            btn.setToolTip(f"{key.capitalize()} color — click to change")
            btn.setStyleSheet("border:1px solid #cbd5e1; border-radius:4px;")
            # Store key
            btn._lock_key = key  # type: ignore
            btn.clicked.connect(lambda _, k=key, b=btn: self._pick_color(k, b))
            colors_layout.addWidget(btn)
            self.color_buttons[key] = btn
            lbl = QLabel(key[:4])
            lbl.setStyleSheet("color:#64748b; font-size:9px;")
            colors_layout.addWidget(lbl)
        colors_layout.addStretch()
        lock_grid.addLayout(colors_layout, 0, 1, 1, 3)

        # Lock circle radius
        lock_grid.addWidget(self._label("Lock Radius"), 1, 0)
        self.lock_radius_spin = QSpinBox()
        lo, hi = OVERLAY_LIMITS["lock_circle_radius"]
        self.lock_radius_spin.setRange(int(lo), int(hi))
        self.lock_radius_spin.setSuffix(" px")
        self.lock_radius_spin.setToolTip("Lock circle radius — 0 = use hitbox radius, else fixed px")
        self.lock_radius_spin.setSpecialValueText("hitbox")
        self.lock_radius_spin.setMinimumHeight(26)
        lock_grid.addWidget(self.lock_radius_spin, 1, 1)

        lock_grid.addWidget(self._label("Thickness"), 1, 2)
        self.lock_thick_spin = QSpinBox()
        lo, hi = OVERLAY_LIMITS["lock_circle_thickness"]
        self.lock_thick_spin.setRange(int(lo), int(hi))
        self.lock_thick_spin.setSuffix(" px")
        self.lock_thick_spin.setMinimumHeight(26)
        lock_grid.addWidget(self.lock_thick_spin, 1, 3)

        # Pulse / animate
        self.pulse_check = QCheckBox("Pulse / animate on state change")
        self.pulse_check.setToolTip("Brief flash/pulse when lock state transitions (gray→cyan→green→red)")
        self.pulse_check.setStyleSheet("font-size:11px;")
        lock_grid.addWidget(self.pulse_check, 2, 0, 1, 2)
        lock_grid.addWidget(self._label("Duration"), 2, 2)
        self.pulse_duration_spin = QSpinBox()
        lo, hi = OVERLAY_LIMITS["pulse_duration_ms"]
        self.pulse_duration_spin.setRange(int(lo), int(hi))
        self.pulse_duration_spin.setSuffix(" ms")
        self.pulse_duration_spin.setMinimumHeight(26)
        lock_grid.addWidget(self.pulse_duration_spin, 2, 3)

        layout.addWidget(lock_box)

        # ----------------------------------------------------
        # Group C: Error Visualization
        # ----------------------------------------------------
        err_box = QGroupBox("⬢  C  —  ERROR  VISUALIZATION")
        err_grid = QGridLayout(err_box)
        err_grid.setContentsMargins(12, 18, 12, 12)
        err_grid.setHorizontalSpacing(8)
        err_grid.setVerticalSpacing(8)
        err_grid.setColumnStretch(1, 1)

        self.error_line_check = QCheckBox("Error vector line (FOV centre → estimate)")
        self.error_line_check.setToolTip("Toggle line from FOV centre to detected position, showing offset direction")
        self.error_line_check.setStyleSheet("font-size:11px;")
        err_grid.addWidget(self.error_line_check, 0, 0, 1, 2)

        self.error_text_check = QCheckBox("Error text label")
        self.error_text_check.setToolTip("Show live numeric error near crosshair (e.g. '14.8px')")
        self.error_text_check.setStyleSheet("font-size:11px;")
        err_grid.addWidget(self.error_text_check, 1, 0)

        err_grid.addWidget(self._label("Units"), 1, 1)
        self.error_units_combo = QComboBox()
        self.error_units_combo.addItems(ERROR_UNITS_OPTIONS)
        self.error_units_combo.setToolTip("Error units — px or angular (mrad/µrad), matching camera's pixel-to-angle scale")
        self.error_units_combo.setMinimumHeight(26)
        err_grid.addWidget(self.error_units_combo, 1, 2)

        layout.addWidget(err_box)
        layout.addStretch()

        # Wire — all emit configChanged
        for w in [self.style_combo, self.error_units_combo]:
            w.currentTextChanged.connect(lambda _: self._emit_config())
        for w in [self.size_spin, self.gap_spin, self.thick_spin, self.dot_radius_spin, self.lock_radius_spin, self.lock_thick_spin, self.pulse_duration_spin]:
            w.valueChanged.connect(lambda _: self._emit_config())
        for w in [self.dot_check, self.pulse_check, self.error_line_check, self.error_text_check]:
            w.toggled.connect(lambda _: self._emit_config())
        # Dot radius enabled only if dot checked
        self.dot_check.toggled.connect(lambda checked: self.dot_radius_spin.setEnabled(checked))

    # ========================================================
    # Helpers
    # ========================================================

    def _label(self, text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setStyleSheet("color:#334155; font-size:11px;")
        return lbl

    def _pick_color(self, key: str, btn: QPushButton) -> None:
        # Open color dialog
        current = btn.palette().color(btn.backgroundRole())
        color = QColorDialog.getColor(current, self, f"Pick {key} color")
        if color.isValid():
            bgr = (color.blue(), color.green(), color.red())  # QColor RGB -> BGR for cv2
            btn.setStyleSheet(f"background:{color.name()}; border:1px solid #cbd5e1; border-radius:4px;")
            btn._bgr = bgr  # type: ignore
            self._emit_config()

    def _update_color_buttons(self, cfg) -> None:
        for key, btn in self.color_buttons.items():
            bgr = getattr(cfg.lock_colors, key, LOCK_COLOR_DEFAULTS[key])
            # BGR to QColor
            qcolor = QColor(int(bgr[2]), int(bgr[1]), int(bgr[0]))
            btn.setStyleSheet(f"background:{qcolor.name()}; border:1px solid #cbd5e1; border-radius:4px;")
            btn._bgr = tuple(int(x) for x in bgr)  # type: ignore

    # ========================================================
    # Config ↔ UI
    # ========================================================

    def collect_config(self) -> OverlayConfig:
        # Gather colors from buttons
        from overlay.config import LockColors
        lc_kwargs = {}
        for key, btn in self.color_buttons.items():
            bgr = getattr(btn, "_bgr", LOCK_COLOR_DEFAULTS[key])
            lc_kwargs[key] = tuple(int(x) for x in bgr)
        lc = LockColors(**lc_kwargs)
        return OverlayConfig(
            crosshair_style=str(self.style_combo.currentText()).lower(),
            crosshair_size=int(self.size_spin.value()),
            crosshair_gap=int(self.gap_spin.value()),
            crosshair_thickness=int(self.thick_spin.value()),
            centre_dot=bool(self.dot_check.isChecked()),
            centre_dot_radius=int(self.dot_radius_spin.value()),
            crosshair_color=(230, 230, 230),  # fixed for now, could add picker
            lock_colors=lc,
            lock_circle_radius=int(self.lock_radius_spin.value()),
            lock_circle_thickness=int(self.lock_thick_spin.value()),
            pulse_enabled=bool(self.pulse_check.isChecked()),
            pulse_duration_ms=int(self.pulse_duration_spin.value()),
            show_error_line=bool(self.error_line_check.isChecked()),
            show_error_text=bool(self.error_text_check.isChecked()),
            error_units=str(self.error_units_combo.currentText()).lower(),
        ).validate()

    def set_config(self, cfg: OverlayConfig, emit: bool = False) -> None:
        cfg = cfg.validate()
        for w in [self.style_combo, self.size_spin, self.gap_spin, self.thick_spin, self.dot_check, self.dot_radius_spin, self.lock_radius_spin, self.lock_thick_spin, self.pulse_check, self.pulse_duration_spin, self.error_line_check, self.error_text_check, self.error_units_combo]:
            w.blockSignals(True)
        try:
            idx = self.style_combo.findText(cfg.crosshair_style)
            if idx >= 0:
                self.style_combo.setCurrentIndex(idx)
            self.size_spin.setValue(int(cfg.crosshair_size))
            self.gap_spin.setValue(int(cfg.crosshair_gap))
            self.thick_spin.setValue(int(cfg.crosshair_thickness))
            self.dot_check.setChecked(bool(cfg.centre_dot))
            self.dot_radius_spin.setValue(int(cfg.centre_dot_radius))
            self.dot_radius_spin.setEnabled(bool(cfg.centre_dot))
            self.lock_radius_spin.setValue(int(cfg.lock_circle_radius))
            self.lock_thick_spin.setValue(int(cfg.lock_circle_thickness))
            self.pulse_check.setChecked(bool(cfg.pulse_enabled))
            self.pulse_duration_spin.setValue(int(cfg.pulse_duration_ms))
            self.pulse_duration_spin.setEnabled(bool(cfg.pulse_enabled))
            self.error_line_check.setChecked(bool(cfg.show_error_line))
            self.error_text_check.setChecked(bool(cfg.show_error_text))
            idx = self.error_units_combo.findText(cfg.error_units)
            if idx >= 0:
                self.error_units_combo.setCurrentIndex(idx)
            self._update_color_buttons(cfg)
        finally:
            for w in [self.style_combo, self.size_spin, self.gap_spin, self.thick_spin, self.dot_check, self.dot_radius_spin, self.lock_radius_spin, self.lock_thick_spin, self.pulse_check, self.pulse_duration_spin, self.error_line_check, self.error_text_check, self.error_units_combo]:
                w.blockSignals(False)
        if emit:
            self._emit_config()

    def _emit_config(self) -> None:
        try:
            cfg = self.collect_config()
            # Enable/disable pulse duration
            self.pulse_duration_spin.setEnabled(cfg.pulse_enabled)
            self.dot_radius_spin.setEnabled(cfg.centre_dot)
            self.configChanged.emit(cfg)
        except: pass

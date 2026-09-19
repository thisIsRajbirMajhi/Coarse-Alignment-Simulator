# gui/panels/remote_terminal_panel.py - Remote Terminal Control Deck (2D-minimal).
from __future__ import annotations

import copy
import logging
import random
from typing import Any

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from gui.panels.base import BaseConfigPanel
from remote_terminal.config import (
    BeaconConfig,
    FormationConfig,
    IdentityConfig,
    MotionConfig,
    PositionConfig,
    RemoteTerminalConfig,
    RemoteTerminalScenarioConfig,
    StateConfig,
)

log = logging.getLogger(__name__)

# 2D-minimal option sets (payload-ready). Legacy values map onto these on load:
#   mod PM/PPM/CUSTOM -> OOK (identical physics: framed-OOK truth).
#   op MAINTENANCE/FAULT -> ACTIVE.
MOD_2D = ["OOK", "AM", "NONE"]
OP_2D = ["ACTIVE", "STANDBY", "OFF"]
_LEGACY_MOD_TO_2D = {"PM": "OOK", "PPM": "OOK", "CUSTOM": "OOK"}


class RemoteTerminalPanel(BaseConfigPanel):
    """
    Remote Terminal Control Deck tab (2D-minimal, payload-ready):

      Top bar: terminal switcher tabs, live status badge, Randomize button.
      Quick Setup (always visible) — the only fields the 2D sim reads:
        Scenario: count, formation shape/spacing, motion profile/speed/heading.
        Beacon: id (read-only), network id, op state, power/beacon switches,
          auth token (-> beacon.token), optical power, wavelength,
          modulation (OOK/AM/NONE), OOK chip rate, spot size, AM carrier freq.
      Advanced (collapsed): motion accel, live position/link telemetry,
        protocol + capabilities (compat, required by wire/matcher tests).

    Everything else from the legacy deck (platform/type/frames, pointing
    sliders, beam profile/polarization, pulse engine, remote signature
    tolerances) is intentionally not shown — values are preserved untouched
    on collect so old configs round-trip without silent rewrites.
    """

    configChanged = pyqtSignal(object)

    def __init__(self, initial: RemoteTerminalScenarioConfig | None = None, parent=None):
        super().__init__(parent)
        self._scenario_config = (initial or RemoteTerminalScenarioConfig()).validate()
        self._selected_idx = 0
        self._updating = False
        self._advanced_visible = False
        self._build_ui()
        # Restore persisted Advanced state (default collapsed per spec).
        try:
            from gui.components import expansion_state as _exp_state
            if _exp_state("remote/advanced", False):
                self.toggle_advanced()
        except Exception:
            pass
        self.set_config(self._scenario_config, emit=False)

    def _build_ui(self) -> None:
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(12, 12, 12, 12)
        main_layout.setSpacing(12)

        # -------------------------------------------------------------
        # TOP TOOLBAR: TERMINAL SWITCHER & QUICK ACTIONS
        # -------------------------------------------------------------
        switcher_box = QWidget()
        s_layout = QVBoxLayout(switcher_box)
        s_layout.setContentsMargins(0, 0, 0, 0)
        s_layout.setSpacing(6)

        top_row = QHBoxLayout()
        top_row.setContentsMargins(0, 0, 0, 0)
        top_row.setSpacing(8)

        lbl_term = QLabel("Active Remote Terminal:")
        lbl_term.setStyleSheet("font-weight:700; color:#1e293b; font-size:12px;")
        lbl_term.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        top_row.addWidget(lbl_term)

        # Scrollable switcher — up to 8 terminals never push actions off-screen
        self.terminal_buttons_scroll = QScrollArea()
        self.terminal_buttons_scroll.setWidgetResizable(True)
        self.terminal_buttons_scroll.setFrameShape(QScrollArea.NoFrame)
        self.terminal_buttons_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.terminal_buttons_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.terminal_buttons_scroll.setFixedHeight(34)
        self.terminal_buttons_scroll.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        _switcher_inner = QWidget()
        self.terminal_buttons_layout = QHBoxLayout(_switcher_inner)
        self.terminal_buttons_layout.setContentsMargins(0, 0, 0, 0)
        self.terminal_buttons_layout.setSpacing(6)
        self.terminal_buttons_scroll.setWidget(_switcher_inner)
        top_row.addWidget(self.terminal_buttons_scroll, 1)

        self.btn_randomize_remote = QPushButton("🎲 Randomize Remote")
        self.btn_randomize_remote.setObjectName("randomizeRemoteButton")
        self.btn_randomize_remote.setToolTip("Randomize 2D scenario + beacon parameters")
        self.btn_randomize_remote.setMinimumHeight(28)
        self.btn_randomize_remote.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self.btn_randomize_remote.setStyleSheet(
            "QPushButton { background:#111827; color:#ffffff; font-weight:700; font-size:11px; "
            "border:1px solid #111827; border-radius:6px; padding:5px 12px; } "
            "QPushButton:hover { background:#1f2937; border-color:#1f2937; } "
            "QPushButton:pressed { background:#030712; }"
        )
        self.btn_randomize_remote.clicked.connect(lambda: self.randomize(emit=True))
        top_row.addWidget(self.btn_randomize_remote)
        s_layout.addLayout(top_row)

        self.live_status_badge = QLabel("STATUS: ACTIVE | EMITTING | NO LINK")
        self.live_status_badge.setWordWrap(True)
        self.live_status_badge.setAlignment(Qt.AlignCenter)
        self.live_status_badge.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.live_status_badge.setMinimumHeight(24)
        self.live_status_badge.setStyleSheet(
            "color:#1e3a8a; background:#eff6ff; border:1px solid #bfdbfe; "
            "font-family:'Consolas','Courier New',monospace; "
            "font-size:11px; font-weight:700; border-radius:6px; padding:5px 10px;"
        )
        s_layout.addWidget(self.live_status_badge)
        main_layout.addWidget(switcher_box)

        # -------------------------------------------------------------
        # 1. QUICK SETUP: 2D-MAJOR PARAMETERS (ALWAYS VISIBLE)
        # -------------------------------------------------------------
        quick_box, quick_grid = self._make_group("⚡ Quick Setup — 2D Beacon")
        quick_grid.setSpacing(10)
        quick_grid.setColumnStretch(1, 2)
        quick_grid.setColumnStretch(4, 2)

        # Row 0: scenario size + formation
        quick_grid.addWidget(self._label("Terminal Count"), 0, 0)
        self.count_slider, self.count_label = self._make_int_slider(1, 8, 1, tooltip="Number of active remote terminals")
        quick_grid.addWidget(self.count_slider, 0, 1)
        quick_grid.addWidget(self.count_label, 0, 2)

        quick_grid.addWidget(self._label("Formation Shape"), 0, 3)
        self.formation_shape = QComboBox()
        self.formation_shape.addItems(["Single", "Line", "Circle", "Arc", "Grid", "Rectangle", "V-Formation", "Custom"])
        self.formation_shape.setMinimumHeight(26)
        quick_grid.addWidget(self.formation_shape, 0, 4, 1, 2)

        # Row 1: spacing + motion
        quick_grid.addWidget(self._label("Terminal Spacing (m)"), 1, 0)
        self.spacing_slider, self.spacing_label, self.spacing_factor = self._make_float_slider(10.0, 300.0, 50.0, decimals=1, suffix=" m")
        quick_grid.addWidget(self.spacing_slider, 1, 1)
        quick_grid.addWidget(self.spacing_label, 1, 2)
        # Radius kept for Circle/Arc compat (hidden from 2D layout, value preserved).
        self.radius_slider, self.radius_label, self.radius_factor = self._make_float_slider(10.0, 500.0, 100.0, decimals=1, suffix=" m")

        quick_grid.addWidget(self._label("Motion Profile"), 1, 3)
        self.motion_profile = QComboBox()
        self.motion_profile.addItems(["Stationary", "Constant Velocity", "Linear", "Circular", "Sinusoidal", "Figure-8", "Random Walk", "Waypoint"])
        self.motion_profile.setMinimumHeight(26)
        quick_grid.addWidget(self.motion_profile, 1, 4, 1, 2)

        # Row 2: speed + heading
        quick_grid.addWidget(self._label("Speed (m/s)"), 2, 0)
        self.speed_slider, self.speed_label, self.speed_factor = self._make_float_slider(0.0, 100.0, 10.0, decimals=1, suffix=" m/s")
        quick_grid.addWidget(self.speed_slider, 2, 1)
        quick_grid.addWidget(self.speed_label, 2, 2)

        quick_grid.addWidget(self._label("Heading (deg)"), 2, 3)
        self.dir_slider, self.dir_label, self.dir_factor = self._make_float_slider(0.0, 360.0, 45.0, decimals=1, suffix=" deg")
        quick_grid.addWidget(self.dir_slider, 2, 4)
        quick_grid.addWidget(self.dir_label, 2, 5)

        # Separator line
        sep = QLabel()
        sep.setFixedHeight(1)
        sep.setStyleSheet("background:#e2e8f0; margin:4px 0px;")
        quick_grid.addWidget(sep, 3, 0, 1, 6)

        # Row 4: identity + op state
        quick_grid.addWidget(self._label("Terminal ID / Net"), 4, 0)
        id_h = QHBoxLayout()
        self.id_edit = QLineEdit("RT-001")
        self.id_edit.setReadOnly(True)
        self.id_edit.setFixedWidth(75)
        self.id_edit.setStyleSheet("background:#e5e7eb; color:#374151; font-weight:700; font-family:Consolas,monospace;")
        id_h.addWidget(self.id_edit)
        self.net_slider, self.net_label = self._make_int_slider(0, 255, 0, tooltip="Network ID (0 = any)")
        id_h.addWidget(self.net_slider)
        id_h.addWidget(self.net_label)
        quick_grid.addLayout(id_h, 4, 1, 1, 2)

        quick_grid.addWidget(self._label("Operational State"), 4, 3)
        self.op_mode_combo = QComboBox()
        self.op_mode_combo.addItems(OP_2D)
        self.op_mode_combo.setMinimumHeight(26)
        quick_grid.addWidget(self.op_mode_combo, 4, 4, 1, 2)

        # Row 5: switches + token (exclusive ON/OFF pairs — never both off)
        quick_grid.addWidget(self._label("Power & Emission"), 5, 0)
        pwr_h = QHBoxLayout()
        pwr_h.setSpacing(4)
        self.btn_power_on = QPushButton("POWER ON")
        self.btn_power_off = QPushButton("POWER OFF")
        self.btn_power_on.setCheckable(True)
        self.btn_power_off.setCheckable(True)
        self.btn_power_on.setChecked(True)
        self.btn_power_on.setMinimumHeight(26)
        self.btn_power_off.setMinimumHeight(26)
        self.btn_power_on.setToolTip("Power the selected terminal on")
        self.btn_power_off.setToolTip("Power the selected terminal off")
        pwr_h.addWidget(self.btn_power_on)
        pwr_h.addWidget(self.btn_power_off)

        self.btn_beacon_on = QPushButton("BEACON ON")
        self.btn_beacon_off = QPushButton("BEACON OFF")
        self.btn_beacon_on.setCheckable(True)
        self.btn_beacon_off.setCheckable(True)
        self.btn_beacon_on.setChecked(True)
        self.btn_beacon_on.setMinimumHeight(26)
        self.btn_beacon_off.setMinimumHeight(26)
        self.btn_beacon_on.setToolTip("Enable beacon emission")
        self.btn_beacon_off.setToolTip("Disable beacon emission")
        pwr_h.addWidget(self.btn_beacon_on)
        pwr_h.addWidget(self.btn_beacon_off)
        quick_grid.addLayout(pwr_h, 5, 1, 1, 2)

        # Exclusive groups guard against both-off / both-on clicks
        self._power_group = QButtonGroup(self)
        self._power_group.setExclusive(True)
        self._power_group.addButton(self.btn_power_on)
        self._power_group.addButton(self.btn_power_off)
        self._beacon_group = QButtonGroup(self)
        self._beacon_group.setExclusive(True)
        self._beacon_group.addButton(self.btn_beacon_on)
        self._beacon_group.addButton(self.btn_beacon_off)

        quick_grid.addWidget(self._label("Auth Token"), 5, 3)
        self.sig_code_edit = QLineEdit("ALPHA-7")
        self.sig_code_edit.setPlaceholderText("Beacon auth token")
        quick_grid.addWidget(self.sig_code_edit, 5, 4, 1, 2)

        # Row 6: optical physics
        quick_grid.addWidget(self._label("Optical Power (W)"), 6, 0)
        self.power_slider, self.power_label, self.power_factor = self._make_float_slider(0.01, 5.0, 1.0, decimals=2, suffix=" W")
        quick_grid.addWidget(self.power_slider, 6, 1)
        quick_grid.addWidget(self.power_label, 6, 2)

        quick_grid.addWidget(self._label("Wavelength (nm)"), 6, 3)
        self.wl_slider, self.wl_label, self.wl_factor = self._make_float_slider(800.0, 1650.0, 1550.0, decimals=1, suffix=" nm")
        quick_grid.addWidget(self.wl_slider, 6, 4)
        quick_grid.addWidget(self.wl_label, 6, 5)

        # Row 7: modulation truth
        quick_grid.addWidget(self._label("Modulation"), 7, 0)
        self.mod_type_combo = QComboBox()
        self.mod_type_combo.addItems(MOD_2D)
        self.mod_type_combo.setMinimumHeight(26)
        quick_grid.addWidget(self.mod_type_combo, 7, 1, 1, 2)

        quick_grid.addWidget(self._label("OOK Chip Rate (Hz)"), 7, 3)
        self.chip_rate_slider, self.chip_rate_label, self.chip_rate_factor = self._make_float_slider(0.5, 60.0, 12.0, decimals=1, suffix=" Hz")
        quick_grid.addWidget(self.chip_rate_slider, 7, 4)
        quick_grid.addWidget(self.chip_rate_label, 7, 5)

        # Row 8: spot + AM carrier (visual)
        quick_grid.addWidget(self._label("Spot Size (mrad)"), 8, 0)
        self.div_slider, self.div_label, self.div_factor = self._make_float_slider(0.1, 10.0, 1.0, decimals=2, suffix=" mrad")
        quick_grid.addWidget(self.div_slider, 8, 1)
        quick_grid.addWidget(self.div_label, 8, 2)

        quick_grid.addWidget(self._label("AM Carrier (kHz)"), 8, 3)
        self.mod_freq_slider, self.mod_freq_label, self.mod_freq_factor = self._make_float_slider(0.1, 50.0, 10.0, decimals=1, suffix=" kHz")
        quick_grid.addWidget(self.mod_freq_slider, 8, 4)
        quick_grid.addWidget(self.mod_freq_label, 8, 5)

        main_layout.addWidget(quick_box)

        # -------------------------------------------------------------
        # 2. ADVANCED (COLLAPSED): motion detail + telemetry + protocol
        # -------------------------------------------------------------
        self.btn_toggle_advanced = QPushButton("▶ ⚙️ Advanced Parameters (Motion Detail, Telemetry, Protocol) [Click to Expand]")
        self.btn_toggle_advanced.setStyleSheet(
            "QPushButton { background:#f1f5f9; border:1px solid #cbd5e1; border-radius:6px; padding:8px 14px; "
            "font-weight:700; color:#1e293b; text-align:left; font-size:12px; } "
            "QPushButton:hover { background:#e2e8f0; border-color:#94a3b8; }"
        )
        self.btn_toggle_advanced.clicked.connect(self.toggle_advanced)
        main_layout.addWidget(self.btn_toggle_advanced)

        self.adv_container = QWidget()
        self.adv_container.setVisible(False)
        adv_layout = QVBoxLayout(self.adv_container)
        adv_layout.setContentsMargins(0, 4, 0, 4)
        adv_layout.setSpacing(12)

        cards_grid = QGridLayout()
        cards_grid.setContentsMargins(0, 0, 0, 0)
        cards_grid.setHorizontalSpacing(12)
        cards_grid.setVerticalSpacing(12)
        cards_grid.setColumnStretch(0, 1)
        cards_grid.setColumnStretch(1, 1)

        cards_grid.addWidget(self._build_advanced_motion_card(), 0, 0)
        cards_grid.addWidget(self._build_advanced_comm_card(), 0, 1)

        adv_layout.addLayout(cards_grid)
        main_layout.addWidget(self.adv_container)

        main_layout.addStretch(1)
        self._connect_signals()

    def toggle_advanced(self) -> None:
        self._advanced_visible = not getattr(self, "_advanced_visible", False)
        self.adv_container.setVisible(self._advanced_visible)
        if self._advanced_visible:
            self.btn_toggle_advanced.setText("▼ ⚙️ Advanced Parameters [Click to Collapse]")
        else:
            self.btn_toggle_advanced.setText("▶ ⚙️ Advanced Parameters (Motion Detail, Telemetry, Protocol) [Click to Expand]")
        try:
            from gui.components import set_expansion_state as _save_exp
            _save_exp("remote/advanced", bool(self._advanced_visible))
        except Exception:
            pass

    # --- ADVANCED CARD BUILDERS --------------------------------------

    def _build_advanced_motion_card(self) -> QGroupBox:
        box, grid = self._make_group("A. Motion Detail & Live Telemetry")
        grid.addWidget(self._label("Acceleration (m/s2)"), 0, 0)
        self.accel_slider, self.accel_label, self.accel_factor = self._make_float_slider(0.1, 20.0, 2.0, decimals=1, suffix=" m/s2")
        grid.addWidget(self.accel_slider, 0, 1)
        grid.addWidget(self.accel_label, 0, 2)

        grid.addWidget(self._label("Sim Position (X, Y)"), 1, 0)
        pos_h = QHBoxLayout()
        self.pos_x_lbl = QLabel("X: 1000.0")
        self.pos_x_lbl.setStyleSheet(self._PILL_IDLE)
        self.pos_y_lbl = QLabel("Y: 1000.0")
        self.pos_y_lbl.setStyleSheet(self._PILL_IDLE)
        pos_h.addWidget(self.pos_x_lbl)
        pos_h.addWidget(self.pos_y_lbl)
        grid.addLayout(pos_h, 1, 1, 1, 2)

        grid.addWidget(self._label("Telemetry: Link State"), 2, 0)
        self.telemetry_link_lbl = QLabel("NO LINK")
        self.telemetry_link_lbl.setStyleSheet(
            "color:#3b82f6; font-weight:700; background:#eff6ff; border:1px solid #bfdbfe; "
            "border-radius:6px; padding:3px 8px; font-family:Consolas,monospace;"
        )
        grid.addWidget(self.telemetry_link_lbl, 2, 1, 1, 2)

        grid.addWidget(self._label("Telemetry: Beacon State"), 3, 0)
        self.telemetry_beacon_lbl = QLabel("EMITTING")
        self.telemetry_beacon_lbl.setStyleSheet(
            "color:#059669; font-weight:700; background:#ecfdf5; border:1px solid #a7f3d0; "
            "border-radius:6px; padding:3px 8px; font-family:Consolas,monospace;"
        )
        grid.addWidget(self.telemetry_beacon_lbl, 3, 1, 1, 2)
        return box

    def _build_advanced_comm_card(self) -> QGroupBox:
        box, grid = self._make_group("B. Protocol (Compat)")
        grid.addWidget(self._label("Protocol"), 0, 0)
        self.protocol_edit = QLineEdit("OPTICAL_LINK v1.0")
        grid.addWidget(self.protocol_edit, 0, 1, 1, 2)

        grid.addWidget(self._label("Capabilities"), 1, 0)
        cap_h = QHBoxLayout()
        self.cap_tx = QCheckBox("TX")
        self.cap_rx = QCheckBox("RX")
        self.cap_beacon = QCheckBox("Beacon")
        self.cap_track = QCheckBox("Tracking")
        self.cap_tx.setChecked(True)
        self.cap_rx.setChecked(True)
        self.cap_beacon.setChecked(True)
        self.cap_track.setChecked(True)
        for c in (self.cap_tx, self.cap_rx, self.cap_beacon, self.cap_track):
            cap_h.addWidget(c)
        grid.addLayout(cap_h, 1, 1, 1, 2)
        return box

    # --- SIGNAL HOOKUPS ----------------------------------------------

    def _connect_signals(self) -> None:
        # Scenario signals (2D subset). Sliders: labels update live via
        # valueChanged internals; the config emits on release (or immediately
        # for keyboard/programmatic steps) — see _on_any_change gate.
        self.count_slider.valueChanged.connect(self._on_count_changed)
        self.formation_shape.currentIndexChanged.connect(self._on_any_change)
        self.spacing_slider.valueChanged.connect(self._on_any_change)
        self.motion_profile.currentIndexChanged.connect(self._on_any_change)
        self.speed_slider.valueChanged.connect(self._on_any_change)
        self.dir_slider.valueChanged.connect(self._on_any_change)
        self.accel_slider.valueChanged.connect(self._on_any_change)

        # Terminal state buttons
        self.btn_power_on.clicked.connect(lambda: self._set_power(True))
        self.btn_power_off.clicked.connect(lambda: self._set_power(False))
        self.btn_beacon_on.clicked.connect(lambda: self._set_beacon(True))
        self.btn_beacon_off.clicked.connect(lambda: self._set_beacon(False))
        self.op_mode_combo.currentIndexChanged.connect(self._on_any_change)

        # Beacon physics (2D subset)
        self.power_slider.valueChanged.connect(self._on_any_change)
        self.wl_slider.valueChanged.connect(self._on_any_change)
        self.div_slider.valueChanged.connect(self._on_any_change)
        self.net_slider.valueChanged.connect(self._on_any_change)
        self.chip_rate_slider.valueChanged.connect(self._on_any_change)

        # Modulation
        self.mod_type_combo.currentIndexChanged.connect(self._on_mod_type_changed)
        self.mod_freq_slider.valueChanged.connect(self._on_any_change)

        # Identity + protocol (validated on focus-out/Enter, not per keystroke)
        self.sig_code_edit.editingFinished.connect(self._on_any_change)
        self.protocol_edit.editingFinished.connect(self._on_any_change)
        self.cap_tx.toggled.connect(self._on_any_change)
        self.cap_rx.toggled.connect(self._on_any_change)
        self.cap_beacon.toggled.connect(self._on_any_change)
        self.cap_track.toggled.connect(self._on_any_change)
        # Release-only heavy emits for all sliders (labels stay live).
        for _s in (self.count_slider, self.spacing_slider, self.speed_slider,
                   self.dir_slider, self.accel_slider, self.power_slider,
                   self.wl_slider, self.div_slider, self.net_slider,
                   self.chip_rate_slider, self.mod_freq_slider):
            _s.sliderReleased.connect(self._on_release_emit)

    def _set_power(self, on: bool) -> None:
        self.btn_power_on.setChecked(on)
        self.btn_power_off.setChecked(not on)
        if not on:
            self.op_mode_combo.setCurrentText("OFF")
            self.btn_beacon_on.setChecked(False)
            self.btn_beacon_off.setChecked(True)
        else:
            if self.op_mode_combo.currentText() == "OFF":
                self.op_mode_combo.setCurrentText("ACTIVE")
            self.btn_beacon_on.setChecked(True)
            self.btn_beacon_off.setChecked(False)
        self._on_any_change()

    def _set_beacon(self, on: bool) -> None:
        self.btn_beacon_on.setChecked(on)
        self.btn_beacon_off.setChecked(not on)
        self._on_any_change()

    def _on_mod_type_changed(self) -> None:
        # Chip rate is always live (OOK truth); carrier freq only matters for AM.
        is_am = (self.mod_type_combo.currentText() == "AM")
        self.mod_freq_slider.setEnabled(is_am)
        self._on_any_change()

    def _on_count_changed(self, val: int) -> None:
        if self._updating:
            return
        self._scenario_config.terminal_count = int(val)
        self._scenario_config.validate()
        if self.count_slider.isSliderDown():
            return  # structural refresh + emit on release
        if self._selected_idx >= len(self._scenario_config.terminals):
            self._selected_idx = max(0, len(self._scenario_config.terminals) - 1)
        self._refresh_terminal_buttons()
        self._load_selected_terminal()
        try:
            self.configChanged.emit(self.collect_config())
        except Exception as e:
            log.warning("remote terminal config invalid, not applied: %s", e)

    def _on_release_emit(self) -> None:
        """sliderReleased handler: finish the deferred drag emit."""
        if self._updating:
            return
        sender = self.sender()
        if sender is self.count_slider:
            self._on_count_changed(self.count_slider.value())
            return
        self._on_any_change()

    def _on_any_change(self, *args) -> None:
        # Live-apply (Design.md §15): scenario/beacon edits cost no rebuild.
        # Terminal-count drags stay release-gated (structural refresh).
        if self._updating:
            return
        self._save_selected_terminal()
        try:
            self.configChanged.emit(self.collect_config())
        except Exception as e:
            log.warning("remote terminal config invalid, not applied: %s", e)

    # --- RANDOMIZE FEATURE -------------------------------------------

    def randomize(
        self,
        token: str | None = None,
        wavelength: float | None = None,
        mod_type: str | None = None,
        mod_freq: float | None = None,
        emit: bool = True,
    ) -> None:
        """Randomize the 2D scenario + beacon parameters on the fly."""
        was_updating = self._updating
        self._updating = True
        try:
            new_count = random.randint(1, 4)
            self.count_slider.setValue(new_count)
            self._scenario_config.terminal_count = new_count
            self._scenario_config.validate()

            shapes = ["Single", "Line", "Circle", "Arc", "Grid", "V-Formation"]
            self.formation_shape.setCurrentText(random.choice(shapes))
            self.spacing_slider.setValue(int(random.uniform(30.0, 120.0) * self.spacing_factor))

            profiles = ["Stationary", "Constant Velocity", "Circular", "Sinusoidal", "Figure-8", "Random Walk"]
            self.motion_profile.setCurrentText(random.choice(profiles))
            self.speed_slider.setValue(int(random.uniform(4.0, 35.0) * self.speed_factor))
            self.dir_slider.setValue(int(random.uniform(0.0, 360.0) * self.dir_factor))
            self.accel_slider.setValue(int(random.uniform(1.0, 6.0) * self.accel_factor))

            laser_lines = [850.0, 980.0, 1064.0, 1310.0, 1550.0]
            tokens = ["ALPHA-7", "BRAVO-2", "ECHO-9", "SIERRA-4", "OMEGA-1", "KILO-6"]
            mod_types = ["AM", "OOK"]

            for i, term in enumerate(self._scenario_config.terminals):
                term.state.power_state = "ON"
                term.state.operational_state = "ACTIVE"
                term.beacon.enabled = True
                term.beacon.power_w = round(random.uniform(0.8, 3.5), 2)
                term.beacon.wavelength_nm = (wavelength if (i == 0 and wavelength is not None) else random.choice(laser_lines))
                picked_mod = (mod_type if (i == 0 and mod_type is not None) else random.choice(mod_types))
                term.beacon.mod_type = picked_mod if picked_mod in MOD_2D else "OOK"
                picked_freq = (mod_freq if (i == 0 and mod_freq is not None) else round(random.uniform(5.0, 25.0), 1))
                term.beacon.mod_freq_khz = picked_freq
                term.beacon.chip_rate_hz = picked_freq
                term.beacon.div_h_mrad = round(random.uniform(0.8, 2.5), 2)
                term.beacon.div_v_mrad = term.beacon.div_h_mrad
                t_token = (token if (i == 0 and token is not None) else tokens[i % len(tokens)])
                term.beacon.token = t_token
                term.identity.name = f"Remote Terminal {i+1} ({t_token})"

            self._refresh_terminal_buttons()
            self._load_selected_terminal()
        finally:
            self._updating = was_updating

        if emit:
            self.configChanged.emit(self.collect_config())

    # --- TERMINAL SWITCHER HELPERS -----------------------------------

    def _refresh_terminal_buttons(self) -> None:
        while self.terminal_buttons_layout.count() > 0:
            item = self.terminal_buttons_layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()

        count = len(self._scenario_config.terminals)
        for i in range(count):
            tid = self._scenario_config.terminals[i].identity.id
            btn = QPushButton(tid)
            btn.setCheckable(True)
            btn.setChecked(i == self._selected_idx)
            btn.setMinimumWidth(72)
            btn.setMinimumHeight(24)
            btn.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
            btn.setToolTip(f"Edit {tid}")
            btn.setStyleSheet(
                "QPushButton { padding: 4px 10px; font-weight:700; font-family:Consolas,monospace; } "
                "QPushButton:checked { background:#111827; color:#ffffff; border:1px solid #111827; }"
            )
            btn.clicked.connect(lambda checked, idx=i: self._select_terminal(idx))
            self.terminal_buttons_layout.addWidget(btn)
        # Keep scroll content tight; stretch pushes buttons left
        self.terminal_buttons_layout.addStretch(1)

    def _select_terminal(self, idx: int) -> None:
        self._save_selected_terminal()
        self._selected_idx = idx
        self._refresh_terminal_buttons()
        self._load_selected_terminal()
        if not self._updating:
            self.configChanged.emit(self.collect_config())

    @staticmethod
    def _map_mod_to_2d(mod: str) -> str:
        m = str(mod or "OOK").upper()
        if m in MOD_2D:
            return m
        return _LEGACY_MOD_TO_2D.get(m, "OOK")

    def _load_selected_terminal(self) -> None:
        if self._selected_idx >= len(self._scenario_config.terminals):
            return
        t = self._scenario_config.terminals[self._selected_idx]
        self._updating = True
        try:
            # Identity (2D)
            self.id_edit.setText(t.identity.id)
            self.net_slider.setValue(int(max(0, min(int(getattr(t.beacon, "network_id", 0) or 0), 255))))

            # Position readout
            self.pos_x_lbl.setText(f"X: {t.position.x:.1f}")
            self.pos_y_lbl.setText(f"Y: {t.position.y:.1f}")

            # State
            pwr_on = (t.state.power_state == "ON")
            self.btn_power_on.setChecked(pwr_on)
            self.btn_power_off.setChecked(not pwr_on)
            op = str(t.state.operational_state or "ACTIVE")
            self.op_mode_combo.setCurrentText(op if op in OP_2D else "ACTIVE")
            bc_on = t.beacon.enabled
            self.btn_beacon_on.setChecked(bc_on)
            self.btn_beacon_off.setChecked(not bc_on)
            self.telemetry_link_lbl.setText(t.state.communication_state)
            self.telemetry_beacon_lbl.setText(t.state.beacon_state)

            # Beacon (2D)
            self.power_slider.setValue(int(round(t.beacon.power_w * self.power_factor)))
            self.wl_slider.setValue(int(round(t.beacon.wavelength_nm * self.wl_factor)))
            self.div_slider.setValue(int(round(t.beacon.div_h_mrad * self.div_factor)))
            self.sig_code_edit.setText(str(getattr(t.beacon, "token", "") or ""))

            # Modulation truth: framed OOK chip rate + AM carrier visual
            self.mod_type_combo.setCurrentText(self._map_mod_to_2d(t.beacon.mod_type))
            self.mod_freq_slider.setValue(int(round(t.beacon.mod_freq_khz * self.mod_freq_factor)))
            self.chip_rate_slider.setValue(int(round(float(getattr(t.beacon, "chip_rate_hz", 12.0)) * self.chip_rate_factor)))
            self._on_mod_type_changed()

            # Protocol (capabilities stored as beacon.capabilities bitmask)
            self.protocol_edit.setText(f"OPTICAL_LINK v{t.beacon.protocol_version}")
            caps_int = int(getattr(t.beacon, "capabilities", 0) or 0)
            self.cap_tx.setChecked(bool(caps_int & 0x01))
            self.cap_rx.setChecked(bool(caps_int & 0x02))
            self.cap_beacon.setChecked(bool(caps_int & 0x04))
            self.cap_track.setChecked(bool(caps_int & 0x08))
        finally:
            self._updating = False

    def _save_selected_terminal(self) -> None:
        if self._selected_idx >= len(self._scenario_config.terminals):
            return
        t = self._scenario_config.terminals[self._selected_idx]
        # NOTE: legacy fields (name/type/platform/frames/pointing/profile/
        # polarization/pulse/signature-tolerances) are preserved untouched.

        t.state.power_state = "ON" if self.btn_power_on.isChecked() else "OFF"
        t.state.operational_state = self.op_mode_combo.currentText()
        t.beacon.enabled = self.btn_beacon_on.isChecked()

        t.beacon.power_w = self.power_slider.value() / float(self.power_factor)
        t.beacon.wavelength_nm = self.wl_slider.value() / float(self.wl_factor)
        t.beacon.div_h_mrad = self.div_slider.value() / float(self.div_factor)
        t.beacon.div_v_mrad = t.beacon.div_h_mrad
        t.beacon.network_id = int(self.net_slider.value())

        token = self.sig_code_edit.text().strip() or "ALPHA-7"
        t.beacon.token = token

        t.beacon.mod_type = self.mod_type_combo.currentText()
        t.beacon.mod_freq_khz = self.mod_freq_slider.value() / float(self.mod_freq_factor)
        t.beacon.chip_rate_hz = self.chip_rate_slider.value() / float(self.chip_rate_factor)

        # Capabilities bitmask: TX=0x01, RX=0x02, Beacon=0x04, Tracking=0x08
        caps = 0
        if self.cap_tx.isChecked():
            caps |= 0x01
        if self.cap_rx.isChecked():
            caps |= 0x02
        if self.cap_beacon.isChecked():
            caps |= 0x04
        if self.cap_track.isChecked():
            caps |= 0x08
        t.beacon.capabilities = caps
        t.validate()

    def collect_config(self) -> RemoteTerminalScenarioConfig:
        self._save_selected_terminal()
        scen = self._scenario_config
        scen.terminal_count = self.count_slider.value()
        scen.formation.shape = self.formation_shape.currentText()
        scen.formation.radius_m = self.radius_slider.value() / float(self.radius_factor)
        scen.formation.spacing_m = self.spacing_slider.value() / float(self.spacing_factor)
        scen.motion.profile = self.motion_profile.currentText()
        scen.motion.speed_mps = self.speed_slider.value() / float(self.speed_factor)
        scen.motion.direction_deg = self.dir_slider.value() / float(self.dir_factor)
        scen.motion.acceleration_mps2 = self.accel_slider.value() / float(self.accel_factor)
        return copy.deepcopy(scen.validate())

    def set_config(self, cfg: RemoteTerminalScenarioConfig, emit: bool = False) -> None:
        self._updating = True
        try:
            self._scenario_config = copy.deepcopy(cfg.validate())
            self.count_slider.setValue(self._scenario_config.terminal_count)
            self.formation_shape.setCurrentText(self._scenario_config.formation.shape)
            self.radius_slider.setValue(int(round(self._scenario_config.formation.radius_m * self.radius_factor)))
            self.spacing_slider.setValue(int(round(self._scenario_config.formation.spacing_m * self.spacing_factor)))
            self.motion_profile.setCurrentText(self._scenario_config.motion.profile)
            self.speed_slider.setValue(int(round(self._scenario_config.motion.speed_mps * self.speed_factor)))
            self.dir_slider.setValue(int(round(self._scenario_config.motion.direction_deg * self.dir_factor)))
            self.accel_slider.setValue(int(round(self._scenario_config.motion.acceleration_mps2 * self.accel_factor)))
            self._refresh_terminal_buttons()
            self._load_selected_terminal()
        finally:
            self._updating = False
        if emit:
            self.configChanged.emit(self.collect_config())

    def update_telemetry(self, telemetry: dict[str, Any]) -> None:
        """Called by presenter / GUI timer to update live link states."""
        if not telemetry or not isinstance(telemetry, dict):
            return
        best = telemetry.get("best_link", "NO_LINK")
        emitting = telemetry.get("emitting_count", 0)
        total = telemetry.get("terminal_count", len(self._scenario_config.terminals))
        # Compact identity strip (Design.md §30.1): id · state · beacon · link.
        sel_id, sel_beacon = "RT-?", "—"
        try:
            term_list = telemetry.get("terminals", [])
            if isinstance(term_list, list) and 0 <= self._selected_idx < len(term_list):
                td0 = term_list[self._selected_idx]
                if isinstance(td0, dict):
                    sel_id = str(td0.get("id", sel_id))
                    sel_beacon = str(td0.get("beacon_state", sel_beacon))
        except (TypeError, ValueError, AttributeError, IndexError):
            pass
        self.live_status_badge.setText(
            f"{sel_id} · {emitting}/{total} EMITTING · BEACON: {sel_beacon} · LINK: {best}")

        term_list = telemetry.get("terminals", [])
        if not isinstance(term_list, list) or self._selected_idx >= len(term_list):
            return
        td = term_list[self._selected_idx]
        if not isinstance(td, dict):
            return
        try:
            cstate = td.get("communication_state", "NO_LINK")
            bstate = td.get("beacon_state", "OFF")
            self.telemetry_link_lbl.setText(str(cstate))
            self.telemetry_beacon_lbl.setText(str(bstate))
            pos = td.get("position", (0, 0))
            self.pos_x_lbl.setText(f"X: {float(pos[0]):.1f}")
            self.pos_y_lbl.setText(f"Y: {float(pos[1]):.1f}")
        except (TypeError, ValueError, IndexError):
            pass

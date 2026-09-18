# gui/panels/remote_terminal_panel.py - Remote Terminal Control Deck per RemoteTerminal.md
from __future__ import annotations

import copy
import logging
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
    CommunicationConfig,
    FormationConfig,
    IdentityConfig,
    MotionConfig,
    PositionConfig,
    RemoteTerminalConfig,
    RemoteTerminalScenarioConfig,
    StateConfig,
    TargetSignatureConfig,
)

log = logging.getLogger(__name__)


class RemoteTerminalPanel(BaseConfigPanel):
    """
    Remote Terminal Control Deck tab matching RemoteTerminal.md specifications:
      1. Scenario / Formation controls at the top (Count, Shape, Size, Spacing, Motion, Speed, Dir, Accel)
      2. Multi-terminal switcher bar (RT-001, RT-002, ...)
      3. Six modular cards matching the data model:
         - Card 1: Identity
         - Card 2: Position & Pointing
         - Card 3: Operational State
         - Card 4: Optical Beacon
         - Card 5: Modulation & Pulse
         - Card 6: Communication & Target Signature
    """

    configChanged = pyqtSignal(object)

    def __init__(self, initial: RemoteTerminalScenarioConfig | None = None, parent=None):
        super().__init__(parent)
        self._scenario_config = (initial or RemoteTerminalScenarioConfig()).validate()
        self._selected_idx = 0
        self._updating = False
        self._build_ui()
        self.set_config(self._scenario_config, emit=False)

    def _build_ui(self) -> None:
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(12, 12, 12, 12)
        main_layout.setSpacing(14)

        # -------------------------------------------------------------
        # TOP: SCENARIO & FORMATION SECTION
        # -------------------------------------------------------------
        scen_box, scen_grid = self._make_group("Remote Terminal Scenario & Formation Controls")
        scen_box.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)

        # Row 0: Count & Formation Shape
        scen_grid.addWidget(self._label("Terminal Count"), 0, 0)
        self.count_slider, self.count_label = self._make_int_slider(1, 8, 1, tooltip="Number of active remote terminals")
        scen_grid.addWidget(self.count_slider, 0, 1)
        scen_grid.addWidget(self.count_label, 0, 2)

        scen_grid.addWidget(self._label("Formation Shape"), 0, 3)
        self.formation_shape = QComboBox()
        self.formation_shape.addItems(["Single", "Line", "Circle", "Arc", "Grid", "Rectangle", "V-Formation", "Custom"])
        self.formation_shape.setMinimumHeight(26)
        scen_grid.addWidget(self.formation_shape, 0, 4)

        # Row 1: Formation Size & Spacing
        scen_grid.addWidget(self._label("Formation Radius (m)"), 1, 0)
        self.radius_slider, self.radius_label, self.radius_factor = self._make_float_slider(10.0, 500.0, 100.0, decimals=1, suffix=" m")
        scen_grid.addWidget(self.radius_slider, 1, 1)
        scen_grid.addWidget(self.radius_label, 1, 2)

        scen_grid.addWidget(self._label("Terminal Spacing (m)"), 1, 3)
        self.spacing_slider, self.spacing_label, self.spacing_factor = self._make_float_slider(10.0, 300.0, 50.0, decimals=1, suffix=" m")
        scen_grid.addWidget(self.spacing_slider, 1, 4)
        scen_grid.addWidget(self.spacing_label, 1, 5)

        # Row 2: Motion Profile & Speed
        scen_grid.addWidget(self._label("Motion Profile"), 2, 0)
        self.motion_profile = QComboBox()
        self.motion_profile.addItems(["Stationary", "Constant Velocity", "Linear", "Circular", "Sinusoidal", "Figure-8", "Random Walk", "Waypoint"])
        self.motion_profile.setMinimumHeight(26)
        scen_grid.addWidget(self.motion_profile, 2, 1)

        scen_grid.addWidget(self._label("Speed (m/s)"), 2, 3)
        self.speed_slider, self.speed_label, self.speed_factor = self._make_float_slider(0.0, 100.0, 10.0, decimals=1, suffix=" m/s")
        scen_grid.addWidget(self.speed_slider, 2, 4)
        scen_grid.addWidget(self.speed_label, 2, 5)

        # Row 3: Heading Direction & Acceleration
        scen_grid.addWidget(self._label("Heading / Direction (deg)"), 3, 0)
        self.dir_slider, self.dir_label, self.dir_factor = self._make_float_slider(0.0, 360.0, 45.0, decimals=1, suffix=" deg")
        scen_grid.addWidget(self.dir_slider, 3, 1)
        scen_grid.addWidget(self.dir_label, 3, 2)

        scen_grid.addWidget(self._label("Acceleration (m/s2)"), 3, 3)
        self.accel_slider, self.accel_label, self.accel_factor = self._make_float_slider(0.1, 20.0, 2.0, decimals=1, suffix=" m/s2")
        scen_grid.addWidget(self.accel_slider, 3, 4)
        scen_grid.addWidget(self.accel_label, 3, 5)

        scen_grid.setColumnStretch(0, 0)
        scen_grid.setColumnStretch(1, 1)
        scen_grid.setColumnStretch(2, 0)
        scen_grid.setColumnStretch(3, 0)
        scen_grid.setColumnStretch(4, 1)
        scen_grid.setColumnStretch(5, 0)

        main_layout.addWidget(scen_box)

        # -------------------------------------------------------------
        # MIDDLE: TERMINAL SELECTOR TABS / SWITCHER BAR
        # -------------------------------------------------------------
        switcher_box = QWidget()
        s_layout = QHBoxLayout(switcher_box)
        s_layout.setContentsMargins(0, 0, 0, 0)
        s_layout.setSpacing(6)
        s_layout.addWidget(self._label("Active Terminal Config:"))

        self.terminal_buttons_layout = QHBoxLayout()
        self.terminal_buttons_layout.setSpacing(6)
        s_layout.addLayout(self.terminal_buttons_layout)
        s_layout.addStretch(1)

        self.live_status_badge = QLabel("STATUS: ACTIVE | EMITTING | NO LINK")
        self.live_status_badge.setStyleSheet(
            "background:#111827; color:#38bdf8; font-family:'Consolas','Courier New',monospace; "
            "font-size:11px; font-weight:700; border-radius:6px; padding:4px 10px;"
        )
        s_layout.addWidget(self.live_status_badge)
        main_layout.addWidget(switcher_box)

        # -------------------------------------------------------------
        # SIX MODULAR CARDS: RESPONSIVE MULTI-COLUMN GRID
        # -------------------------------------------------------------
        cards_widget = QWidget()
        cards_grid = QGridLayout(cards_widget)
        cards_grid.setContentsMargins(0, 0, 0, 28)
        cards_grid.setHorizontalSpacing(14)
        cards_grid.setVerticalSpacing(14)
        cards_grid.setColumnStretch(0, 1)
        cards_grid.setColumnStretch(1, 1)

        # CARD 1: Identity
        card1 = self._build_identity_card()
        cards_grid.addWidget(card1, 0, 0)

        # CARD 2: Position & Optical Pointing
        card2 = self._build_position_card()
        cards_grid.addWidget(card2, 0, 1)

        # CARD 3: Operational State
        card3 = self._build_state_card()
        cards_grid.addWidget(card3, 1, 0)

        # CARD 4: Optical Beacon
        card4 = self._build_beacon_card()
        cards_grid.addWidget(card4, 1, 1)

        # CARD 5: Modulation & Pulse
        card5 = self._build_modulation_card()
        cards_grid.addWidget(card5, 2, 0)

        # CARD 6: Communication & Target Signature
        card6 = self._build_comm_signature_card()
        cards_grid.addWidget(card6, 2, 1)

        main_layout.addWidget(cards_widget)
        main_layout.addStretch(1)

        self._connect_signals()

    # --- CARD BUILDERS -----------------------------------------------

    def _build_identity_card(self) -> QGroupBox:
        box, grid = self._make_group("1. Terminal Identity & Platform")
        grid.addWidget(self._label("Terminal ID"), 0, 0)
        self.id_edit = QLineEdit("RT-001")
        self.id_edit.setReadOnly(True)
        self.id_edit.setStyleSheet("background:#e5e7eb; color:#374151; font-weight:700; font-family:Consolas,monospace;")
        grid.addWidget(self.id_edit, 0, 1)

        grid.addWidget(self._label("Terminal Name"), 1, 0)
        self.name_edit = QLineEdit("Remote Optical Terminal 001")
        grid.addWidget(self.name_edit, 1, 1)

        grid.addWidget(self._label("Terminal Type"), 2, 0)
        self.type_combo = QComboBox()
        self.type_combo.addItems(["REMOTE_TERMINAL", "OPTICAL_TERMINAL", "GROUND_TERMINAL", "AIRBORNE_TERMINAL", "SPACE_TERMINAL"])
        grid.addWidget(self.type_combo, 2, 1)

        grid.addWidget(self._label("Platform ID"), 3, 0)
        self.platform_edit = QLineEdit("PLATFORM-001")
        grid.addWidget(self.platform_edit, 3, 1)
        return box

    def _build_position_card(self) -> QGroupBox:
        box, grid = self._make_group("2. Position & Optical Pointing")
        grid.addWidget(self._label("Position (X, Y)"), 0, 0)
        pos_h = QHBoxLayout()
        self.pos_x_lbl = QLabel("X: 1000.0")
        self.pos_x_lbl.setStyleSheet(self._PILL_IDLE)
        self.pos_y_lbl = QLabel("Y: 1000.0")
        self.pos_y_lbl.setStyleSheet(self._PILL_IDLE)
        pos_h.addWidget(self.pos_x_lbl)
        pos_h.addWidget(self.pos_y_lbl)
        grid.addLayout(pos_h, 0, 1)

        grid.addWidget(self._label("Reference Frame"), 1, 0)
        self.pos_ref_combo = QComboBox()
        self.pos_ref_combo.addItems(["LOCAL", "PLATFORM", "ECI", "ECEF", "ENU", "NED"])
        grid.addWidget(self.pos_ref_combo, 1, 1)

        grid.addWidget(self._label("Beam Azimuth (deg)"), 2, 0)
        self.azimuth_slider, self.azimuth_label, self.azimuth_factor = self._make_float_slider(-180.0, 180.0, 0.0, decimals=1, suffix=" deg")
        grid.addWidget(self.azimuth_slider, 2, 1)
        grid.addWidget(self.azimuth_label, 2, 2)

        grid.addWidget(self._label("Beam Elevation (deg)"), 3, 0)
        self.elevation_slider, self.elevation_label, self.elevation_factor = self._make_float_slider(-90.0, 90.0, 0.0, decimals=1, suffix=" deg")
        grid.addWidget(self.elevation_slider, 3, 1)
        grid.addWidget(self.elevation_label, 3, 2)

        pt_btns = QHBoxLayout()
        self.btn_point_boresight = QPushButton("Boresight (0 deg)")
        self.btn_point_target = QPushButton("Point at Target")
        pt_btns.addWidget(self.btn_point_boresight)
        pt_btns.addWidget(self.btn_point_target)
        grid.addLayout(pt_btns, 4, 0, 1, 3)
        return box

    def _build_state_card(self) -> QGroupBox:
        box, grid = self._make_group("3. Operational State & Link Telemetry")
        grid.addWidget(self._label("Power Control"), 0, 0)
        pwr_h = QHBoxLayout()
        self.btn_power_on = QPushButton("POWER ON")
        self.btn_power_off = QPushButton("POWER OFF")
        self.btn_power_on.setCheckable(True)
        self.btn_power_off.setCheckable(True)
        self.btn_power_on.setChecked(True)
        pwr_h.addWidget(self.btn_power_on)
        pwr_h.addWidget(self.btn_power_off)
        grid.addLayout(pwr_h, 0, 1)

        grid.addWidget(self._label("Operational Mode"), 1, 0)
        self.op_mode_combo = QComboBox()
        self.op_mode_combo.addItems(["ACTIVE", "STANDBY", "OFF", "MAINTENANCE", "FAULT"])
        grid.addWidget(self.op_mode_combo, 1, 1)

        grid.addWidget(self._label("Optical Beacon"), 2, 0)
        bc_h = QHBoxLayout()
        self.btn_beacon_on = QPushButton("BEACON ON")
        self.btn_beacon_off = QPushButton("BEACON OFF")
        self.btn_beacon_on.setCheckable(True)
        self.btn_beacon_off.setCheckable(True)
        self.btn_beacon_on.setChecked(True)
        bc_h.addWidget(self.btn_beacon_on)
        bc_h.addWidget(self.btn_beacon_off)
        grid.addLayout(bc_h, 2, 1)

        # Read-only Telemetry display
        grid.addWidget(self._label("Telemetry: Link State"), 3, 0)
        self.telemetry_link_lbl = QLabel("NO LINK")
        self.telemetry_link_lbl.setStyleSheet(
            "color:#3b82f6; font-weight:700; background:#eff6ff; border:1px solid #bfdbfe; "
            "border-radius:6px; padding:3px 8px; font-family:Consolas,monospace;"
        )
        grid.addWidget(self.telemetry_link_lbl, 3, 1)

        grid.addWidget(self._label("Telemetry: Beacon State"), 4, 0)
        self.telemetry_beacon_lbl = QLabel("EMITTING")
        self.telemetry_beacon_lbl.setStyleSheet(
            "color:#059669; font-weight:700; background:#ecfdf5; border:1px solid #a7f3d0; "
            "border-radius:6px; padding:3px 8px; font-family:Consolas,monospace;"
        )
        grid.addWidget(self.telemetry_beacon_lbl, 4, 1)
        return box

    def _build_beacon_card(self) -> QGroupBox:
        box, grid = self._make_group("4. Optical Beacon Physics")
        grid.addWidget(self._label("Optical Power (W)"), 0, 0)
        self.power_slider, self.power_label, self.power_factor = self._make_float_slider(0.01, 5.0, 1.0, decimals=2, suffix=" W")
        grid.addWidget(self.power_slider, 0, 1)
        grid.addWidget(self.power_label, 0, 2)

        grid.addWidget(self._label("Wavelength (nm)"), 1, 0)
        self.wl_slider, self.wl_label, self.wl_factor = self._make_float_slider(800.0, 1650.0, 1550.0, decimals=1, suffix=" nm")
        grid.addWidget(self.wl_slider, 1, 1)
        grid.addWidget(self.wl_label, 1, 2)

        grid.addWidget(self._label("Beam Divergence (mrad)"), 2, 0)
        self.div_slider, self.div_label, self.div_factor = self._make_float_slider(0.1, 10.0, 1.0, decimals=2, suffix=" mrad")
        grid.addWidget(self.div_slider, 2, 1)
        grid.addWidget(self.div_label, 2, 2)

        grid.addWidget(self._label("Beam Profile"), 3, 0)
        self.profile_combo = QComboBox()
        self.profile_combo.addItems(["GAUSSIAN", "TOP_HAT", "CUSTOM"])
        grid.addWidget(self.profile_combo, 3, 1)

        grid.addWidget(self._label("Polarization"), 4, 0)
        self.pol_combo = QComboBox()
        self.pol_combo.addItems(["UNPOLARIZED", "LINEAR", "CIRCULAR", "ELLIPTICAL"])
        grid.addWidget(self.pol_combo, 4, 1)
        return box

    def _build_modulation_card(self) -> QGroupBox:
        box, grid = self._make_group("5. Modulation & Pulse Temporal Behavior")
        grid.addWidget(self._label("Modulation Type"), 0, 0)
        self.mod_type_combo = QComboBox()
        self.mod_type_combo.addItems(["AM", "NONE", "PM", "OOK", "PPM", "CUSTOM"])
        grid.addWidget(self.mod_type_combo, 0, 1)

        grid.addWidget(self._label("Modulation Freq (kHz)"), 1, 0)
        self.mod_freq_slider, self.mod_freq_label, self.mod_freq_factor = self._make_float_slider(0.1, 50.0, 10.0, decimals=1, suffix=" kHz")
        grid.addWidget(self.mod_freq_slider, 1, 1)
        grid.addWidget(self.mod_freq_label, 1, 2)

        grid.addWidget(self._label("Modulation Depth (%)"), 2, 0)
        self.mod_depth_slider, self.mod_depth_label, self.mod_depth_factor = self._make_float_slider(0.0, 100.0, 100.0, decimals=0, suffix=" %")
        grid.addWidget(self.mod_depth_slider, 2, 1)
        grid.addWidget(self.mod_depth_label, 2, 2)

        grid.addWidget(self._label("Pulse Operation"), 3, 0)
        self.pulse_enable_chk = QCheckBox("Enable Pulsed Emission")
        grid.addWidget(self.pulse_enable_chk, 3, 1)

        grid.addWidget(self._label("Pulse Rep Rate (kHz)"), 4, 0)
        self.pulse_rate_slider, self.pulse_rate_label, self.pulse_rate_factor = self._make_float_slider(0.1, 50.0, 10.0, decimals=1, suffix=" kHz")
        grid.addWidget(self.pulse_rate_slider, 4, 1)
        grid.addWidget(self.pulse_rate_label, 4, 2)

        grid.addWidget(self._label("Pulse Width (us)"), 5, 0)
        self.pulse_width_slider, self.pulse_width_label, self.pulse_width_factor = self._make_float_slider(1.0, 200.0, 50.0, decimals=1, suffix=" us")
        grid.addWidget(self.pulse_width_slider, 5, 1)
        grid.addWidget(self.pulse_width_label, 5, 2)

        grid.addWidget(self._label("Calculated Duty Cycle"), 6, 0)
        self.duty_cycle_label = QLabel("50.0 % (auto-calculated)")
        self.duty_cycle_label.setStyleSheet(self._PILL_IDLE)
        grid.addWidget(self.duty_cycle_label, 6, 1)
        return box

    def _build_comm_signature_card(self) -> QGroupBox:
        box, grid = self._make_group("6. Communication & Target Signature")
        grid.addWidget(self._label("Protocol"), 0, 0)
        self.protocol_edit = QLineEdit("OPTICAL_LINK v1.0")
        grid.addWidget(self.protocol_edit, 0, 1)

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
        grid.addLayout(cap_h, 1, 1)

        grid.addWidget(self._label("Expected Wavelength (nm)"), 2, 0)
        self.sig_wl_slider, self.sig_wl_label, self.sig_wl_factor = self._make_float_slider(800.0, 1650.0, 1550.0, decimals=1, suffix=" nm")
        grid.addWidget(self.sig_wl_slider, 2, 1)
        grid.addWidget(self.sig_wl_label, 2, 2)

        grid.addWidget(self._label("Wavelength Tolerance (+/- nm)"), 3, 0)
        self.sig_tol_slider, self.sig_tol_label, self.sig_tol_factor = self._make_float_slider(0.2, 10.0, 2.0, decimals=1, suffix=" nm")
        grid.addWidget(self.sig_tol_slider, 3, 1)
        grid.addWidget(self.sig_tol_label, 3, 2)

        grid.addWidget(self._label("Minimum SNR Threshold (dB)"), 4, 0)
        self.sig_snr_slider, self.sig_snr_label, self.sig_snr_factor = self._make_float_slider(1.0, 30.0, 8.0, decimals=1, suffix=" dB")
        grid.addWidget(self.sig_snr_slider, 4, 1)
        grid.addWidget(self.sig_snr_label, 4, 2)

        grid.addWidget(self._label("Identification Code"), 5, 0)
        self.sig_code_edit = QLineEdit("RT001")
        grid.addWidget(self.sig_code_edit, 5, 1)
        return box

    # --- SIGNAL HOOKUPS ----------------------------------------------

    def _connect_signals(self) -> None:
        # Scenario signals
        self.count_slider.valueChanged.connect(self._on_count_changed)
        self.formation_shape.currentIndexChanged.connect(self._on_any_change)
        self.radius_slider.valueChanged.connect(self._on_any_change)
        self.spacing_slider.valueChanged.connect(self._on_any_change)
        self.motion_profile.currentIndexChanged.connect(self._on_any_change)
        self.speed_slider.valueChanged.connect(self._on_any_change)
        self.dir_slider.valueChanged.connect(self._on_any_change)
        self.accel_slider.valueChanged.connect(self._on_any_change)

        # Terminal buttons
        self.btn_power_on.clicked.connect(lambda: self._set_power(True))
        self.btn_power_off.clicked.connect(lambda: self._set_power(False))
        self.btn_beacon_on.clicked.connect(lambda: self._set_beacon(True))
        self.btn_beacon_off.clicked.connect(lambda: self._set_beacon(False))
        self.op_mode_combo.currentIndexChanged.connect(self._on_any_change)

        self.btn_point_boresight.clicked.connect(self._point_boresight)
        self.btn_point_target.clicked.connect(self._point_target)

        # Beacon physics
        self.power_slider.valueChanged.connect(self._on_any_change)
        self.wl_slider.valueChanged.connect(self._on_any_change)
        self.div_slider.valueChanged.connect(self._on_any_change)
        self.profile_combo.currentIndexChanged.connect(self._on_any_change)
        self.pol_combo.currentIndexChanged.connect(self._on_any_change)

        # Modulation & Pulse
        self.mod_type_combo.currentIndexChanged.connect(self._on_mod_type_changed)
        self.mod_freq_slider.valueChanged.connect(self._on_any_change)
        self.mod_depth_slider.valueChanged.connect(self._on_any_change)
        self.pulse_enable_chk.toggled.connect(self._on_pulse_toggled)
        self.pulse_rate_slider.valueChanged.connect(self._on_pulse_params_changed)
        self.pulse_width_slider.valueChanged.connect(self._on_pulse_params_changed)

        # Signature & Comm
        self.name_edit.textChanged.connect(self._on_any_change)
        self.type_combo.currentIndexChanged.connect(self._on_any_change)
        self.protocol_edit.textChanged.connect(self._on_any_change)
        self.cap_tx.toggled.connect(self._on_any_change)
        self.cap_rx.toggled.connect(self._on_any_change)
        self.cap_beacon.toggled.connect(self._on_any_change)
        self.cap_track.toggled.connect(self._on_any_change)
        self.sig_wl_slider.valueChanged.connect(self._on_any_change)
        self.sig_tol_slider.valueChanged.connect(self._on_any_change)
        self.sig_snr_slider.valueChanged.connect(self._on_any_change)
        self.sig_code_edit.textChanged.connect(self._on_any_change)

    def _point_boresight(self) -> None:
        self.azimuth_slider.setValue(0)
        self.elevation_slider.setValue(0)
        self._on_any_change()

    def _point_target(self) -> None:
        # Orient beam directly towards scene center / camera
        self.azimuth_slider.setValue(0)
        self.elevation_slider.setValue(0)
        self._on_any_change()

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
        mtype = self.mod_type_combo.currentText()
        is_none = (mtype == "NONE")
        self.mod_freq_slider.setEnabled(not is_none)
        self.mod_depth_slider.setEnabled(not is_none)
        self._on_any_change()

    def _on_pulse_toggled(self, checked: bool) -> None:
        self.pulse_rate_slider.setEnabled(checked)
        self.pulse_width_slider.setEnabled(checked)
        self._on_pulse_params_changed()

    def _on_pulse_params_changed(self) -> None:
        # Calculate D = f * tau
        f_khz = self.pulse_rate_slider.value() / float(self.pulse_rate_factor)
        w_us = self.pulse_width_slider.value() / float(self.pulse_width_factor)
        d_pct = min(100.0, f_khz * w_us * 0.1)
        self.duty_cycle_label.setText(f"{d_pct:.1f} % (auto-calculated)")
        self._on_any_change()

    def _on_count_changed(self, val: int) -> None:
        if self._updating:
            return
        self._scenario_config.terminal_count = int(val)
        self._scenario_config.validate()
        if self._selected_idx >= len(self._scenario_config.terminals):
            self._selected_idx = max(0, len(self._scenario_config.terminals) - 1)
        self._refresh_terminal_buttons()
        self._load_selected_terminal()
        self.configChanged.emit(self.collect_config())

    def _on_any_change(self, *args) -> None:
        if self._updating:
            return
        self._save_selected_terminal()
        self.configChanged.emit(self.collect_config())

    # --- TERMINAL SWITCHER HELPERS -----------------------------------

    def _refresh_terminal_buttons(self) -> None:
        # Clear existing buttons
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
            btn.setStyleSheet(
                "QPushButton { padding: 4px 10px; font-weight:700; font-family:Consolas,monospace; } "
                "QPushButton:checked { background:#111827; color:#ffffff; border:1px solid #111827; }"
            )
            btn.clicked.connect(lambda checked, idx=i: self._select_terminal(idx))
            self.terminal_buttons_layout.addWidget(btn)

    def _select_terminal(self, idx: int) -> None:
        self._save_selected_terminal()
        self._selected_idx = idx
        self._refresh_terminal_buttons()
        self._load_selected_terminal()

    def _load_selected_terminal(self) -> None:
        if self._selected_idx >= len(self._scenario_config.terminals):
            return
        t = self._scenario_config.terminals[self._selected_idx]
        self._updating = True
        try:
            # Identity
            self.id_edit.setText(t.identity.id)
            self.name_edit.setText(t.identity.name)
            self.type_combo.setCurrentText(t.identity.terminal_type)
            self.platform_edit.setText(t.identity.platform_id)

            # Position
            self.pos_x_lbl.setText(f"X: {t.position.x:.1f}")
            self.pos_y_lbl.setText(f"Y: {t.position.y:.1f}")
            self.pos_ref_combo.setCurrentText(t.position.reference_frame)
            self.azimuth_slider.setValue(int(round(t.beacon.azimuth_deg * self.azimuth_factor)))
            self.elevation_slider.setValue(int(round(t.beacon.elevation_deg * self.elevation_factor)))

            # State
            pwr_on = (t.state.power_state == "ON")
            self.btn_power_on.setChecked(pwr_on)
            self.btn_power_off.setChecked(not pwr_on)
            self.op_mode_combo.setCurrentText(t.state.operational_state)
            bc_on = t.beacon.enabled
            self.btn_beacon_on.setChecked(bc_on)
            self.btn_beacon_off.setChecked(not bc_on)
            self.telemetry_link_lbl.setText(t.state.communication_state)
            self.telemetry_beacon_lbl.setText(t.state.beacon_state)

            # Beacon
            self.power_slider.setValue(int(round(t.beacon.power_w * self.power_factor)))
            self.wl_slider.setValue(int(round(t.beacon.wavelength_nm * self.wl_factor)))
            self.div_slider.setValue(int(round(t.beacon.div_h_mrad * self.div_factor)))
            self.profile_combo.setCurrentText(t.beacon.profile_type)
            self.pol_combo.setCurrentText(t.beacon.polarization_type)

            # Mod
            self.mod_type_combo.setCurrentText(t.beacon.mod_type)
            self.mod_freq_slider.setValue(int(round(t.beacon.mod_freq_khz * self.mod_freq_factor)))
            self.mod_depth_slider.setValue(int(round(t.beacon.mod_depth * 100.0)))
            self.pulse_enable_chk.setChecked(t.beacon.pulse_enabled)
            self.pulse_rate_slider.setValue(int(round(t.beacon.pulse_rate_khz * self.pulse_rate_factor)))
            self.pulse_width_slider.setValue(int(round(t.beacon.pulse_width_us * self.pulse_width_factor)))
            self._on_pulse_params_changed()
            self._on_mod_type_changed()

            # Comm & Sig
            self.protocol_edit.setText(t.communication.protocol_name)
            caps = set(t.communication.capabilities or [])
            self.cap_tx.setChecked("OPTICAL_TX" in caps or "TX" in caps)
            self.cap_rx.setChecked("OPTICAL_RX" in caps or "RX" in caps)
            self.cap_beacon.setChecked("BEACON" in caps)
            self.cap_track.setChecked("TRACKING" in caps or "TRACK" in caps)
            self.sig_wl_slider.setValue(int(round(t.target_signature.wavelength_nm * self.sig_wl_factor)))
            self.sig_tol_slider.setValue(int(round(t.target_signature.wavelength_tol_nm * self.sig_tol_factor)))
            self.sig_snr_slider.setValue(int(round(t.target_signature.minimum_snr_db * self.sig_snr_factor)))
            self.sig_code_edit.setText(t.target_signature.code or "")
        finally:
            self._updating = False

    def _save_selected_terminal(self) -> None:
        if self._selected_idx >= len(self._scenario_config.terminals):
            return
        t = self._scenario_config.terminals[self._selected_idx]
        t.identity.name = self.name_edit.text()
        t.identity.terminal_type = self.type_combo.currentText()
        t.identity.platform_id = self.platform_edit.text()

        t.position.reference_frame = self.pos_ref_combo.currentText()
        t.beacon.azimuth_deg = self.azimuth_slider.value() / float(self.azimuth_factor)
        t.beacon.elevation_deg = self.elevation_slider.value() / float(self.elevation_factor)

        t.state.power_state = "ON" if self.btn_power_on.isChecked() else "OFF"
        t.state.operational_state = self.op_mode_combo.currentText()
        t.beacon.enabled = self.btn_beacon_on.isChecked()

        t.beacon.power_w = self.power_slider.value() / float(self.power_factor)
        t.beacon.wavelength_nm = self.wl_slider.value() / float(self.wl_factor)
        t.beacon.div_h_mrad = self.div_slider.value() / float(self.div_factor)
        t.beacon.div_v_mrad = t.beacon.div_h_mrad
        t.beacon.profile_type = self.profile_combo.currentText()
        t.beacon.polarization_type = self.pol_combo.currentText()

        t.beacon.mod_type = self.mod_type_combo.currentText()
        t.beacon.mod_freq_khz = self.mod_freq_slider.value() / float(self.mod_freq_factor)
        t.beacon.mod_depth = self.mod_depth_slider.value() / 100.0
        t.beacon.pulse_enabled = self.pulse_enable_chk.isChecked()
        t.beacon.pulse_rate_khz = self.pulse_rate_slider.value() / float(self.pulse_rate_factor)
        t.beacon.pulse_width_us = self.pulse_width_slider.value() / float(self.pulse_width_factor)

        t.communication.protocol_name = self.protocol_edit.text()
        new_caps = []
        if self.cap_beacon.isChecked():
            new_caps.append("BEACON")
        if self.cap_rx.isChecked():
            new_caps.append("OPTICAL_RX")
        if self.cap_tx.isChecked():
            new_caps.append("OPTICAL_TX")
        if self.cap_track.isChecked():
            new_caps.append("TRACKING")
        t.communication.capabilities = new_caps
        t.target_signature.wavelength_nm = self.sig_wl_slider.value() / float(self.sig_wl_factor)
        t.target_signature.wavelength_tol_nm = self.sig_tol_slider.value() / float(self.sig_tol_factor)
        t.target_signature.minimum_snr_db = self.sig_snr_slider.value() / float(self.sig_snr_factor)
        t.target_signature.code = self.sig_code_edit.text()
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
        self.live_status_badge.setText(f"SCENARIO: {emitting}/{total} EMITTING | LINK: {best}")

        term_list = telemetry.get("terminals", [])
        if self._selected_idx < len(term_list):
            td = term_list[self._selected_idx]
            cstate = td.get("communication_state", "NO_LINK")
            bstate = td.get("beacon_state", "OFF")
            self.telemetry_link_lbl.setText(cstate)
            self.telemetry_beacon_lbl.setText(bstate)
            pos = td.get("position", (0, 0, 0))
            self.pos_x_lbl.setText(f"X: {pos[0]:.1f}")
            self.pos_y_lbl.setText(f"Y: {pos[1]:.1f}")

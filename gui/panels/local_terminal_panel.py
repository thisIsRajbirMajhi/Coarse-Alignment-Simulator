# gui/panels/local_terminal_panel.py - Local Terminal Control Deck per LocalTerminal.md
from __future__ import annotations

import copy
import logging
from typing import Any

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSlider,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from gui.panels.base import BaseConfigPanel
from local_terminal.config import (
    AcquisitionConfig,
    AngularModelConfig,
    DetectionConfig,
    DisplayConfig,
    IdentityConfig,
    LocalCameraConfig,
    LocalCommunicationConfig,
    LocalStateConfig,
    LocalTerminalConfig,
    PositionConfig,
    PTZConfig,
    RealismConfig,
    TrackingConfig,
)

log = logging.getLogger(__name__)


class LocalTerminalPanel(BaseConfigPanel):
    """
    Local Terminal Control Deck matching LocalTerminal.md specifications:
      Top: Terminal Identity Banner & Live Telemetry Chips (Power, Op, PTZ, Acq, Det, Trk, Link)
      Two Major Operational Sub-Tabs:
        1. CONFIGURATION:
           - A: Sensor Resolution & FOV
           - B: Pan-Tilt Mechanics
           - C: Display & Screen Sizes
           - D: Derived Pixel -> Angle (Angular Model)
           - E: Realism & Mechanical Errors
        2. OPERATIONS:
           - F: Acquisition (Raster, Spiral, etc.)
           - G: Detection (Spectral, Spot Size, Modulation, SNR)
           - H: Tracking (Centroid, Prediction, Smoothing)
           - I: Communication (Capabilities, Protocol, Link State)
    """

    configChanged = pyqtSignal(object)

    def __init__(
        self,
        initial: LocalTerminalConfig | None = None,
        scene_bounds: tuple[int, int] = (2000, 2000),
        parent=None,
    ):
        super().__init__(parent)
        self._scene_bounds = scene_bounds
        self._config = (initial or LocalTerminalConfig()).validate(scene_bounds)
        self._updating = False
        self._build_ui()
        self.set_scene_bounds(scene_bounds)
        self.set_config(self._config, emit=False)

    # -----------------------------------------------------------------
    # UI CONSTRUCTION
    # -----------------------------------------------------------------
    def _build_ui(self) -> None:
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(10, 10, 10, 10)
        main_layout.setSpacing(12)

        # -------------------------------------------------------------
        # TOP BANNER: IDENTITY & LIVE STATUS BADGES
        # -------------------------------------------------------------
        banner = QGroupBox("Local Terminal System Identity & Real-Time Status")
        banner.setStyleSheet(
            "QGroupBox { background:#ffffff; border:1px solid #d1d5db; border-radius:8px; padding:12px 14px 10px 14px; margin-top:6px; font-weight:700; }"
            "QGroupBox::title { subcontrol-origin:margin; top:-3px; left:12px; padding:1px 6px; background:#ffffff; color:#1e293b; font-size:11px; }"
        )
        b_layout = QVBoxLayout(banner)
        b_layout.setSpacing(8)

        # Row 1: Identity info
        id_row = QHBoxLayout()
        self.lbl_id = QLabel("ID: <b>LT-001</b>")
        self.lbl_id.setStyleSheet("font-size:12px; color:#1e3a8a; padding:3px 8px; background:#eff6ff; border-radius:4px; border:1px solid #bfdbfe;")
        id_row.addWidget(self.lbl_id)

        self.lbl_name = QLabel("Local PTZ Camera 01")
        self.lbl_name.setStyleSheet("font-size:12px; font-weight:700; color:#0f172a; margin-left:4px;")
        id_row.addWidget(self.lbl_name)

        self.lbl_platform = QLabel("Platform: PLATFORM-001 • World Frame")
        self.lbl_platform.setStyleSheet("font-size:11px; color:#64748b; margin-left:8px;")
        id_row.addWidget(self.lbl_platform)
        id_row.addStretch(1)

        self.btn_reset_all = self._make_reset_button("Reset Local Terminal")
        self.btn_reset_all.clicked.connect(self._on_reset_clicked)
        id_row.addWidget(self.btn_reset_all)
        b_layout.addLayout(id_row)

        # Row 2: Live Status Badges
        chips_row = QHBoxLayout()
        chips_row.setSpacing(8)
        self.badge_power = self._make_badge("Power: ON", "#059669", "#ecfdf5", "#a7f3d0")
        self.badge_op = self._make_badge("Op: STANDBY", "#0284c7", "#f0f9ff", "#bae6fd")
        self.badge_ptz = self._make_badge("PTZ: IDLE", "#4b5563", "#f9fafb", "#e5e7eb")
        self.badge_acq = self._make_badge("Acq: IDLE", "#4b5563", "#f9fafb", "#e5e7eb")
        self.badge_det = self._make_badge("Det: NO TARGET", "#d97706", "#fffbeb", "#fde68a")
        self.badge_trk = self._make_badge("Trk: OFF", "#6b7280", "#f3f4f6", "#e5e7eb")
        self.badge_link = self._make_badge("Link: NO LINK", "#dc2626", "#fef2f2", "#fecaca")
        self.badge_autonomy = self._make_badge("Auto: SEARCHING", "#7c3aed", "#f5f3ff", "#ddd6fe")

        for b in (self.badge_power, self.badge_op, self.badge_ptz, self.badge_acq, self.badge_det, self.badge_trk, self.badge_link, self.badge_autonomy):
            chips_row.addWidget(b)
        chips_row.addStretch(1)
        b_layout.addLayout(chips_row)

        main_layout.addWidget(banner)

        # -------------------------------------------------------------
        # SUB-TABS: CONFIGURATION (A–E) & OPERATIONS (F–I)
        # -------------------------------------------------------------
        self.sub_tabs = QTabWidget(self)
        self.sub_tabs.setStyleSheet(
            "QTabBar::tab { font-size:12px; font-weight:700; padding:8px 18px; min-width:140px; }"
        )

        # 1. Configuration Tab Widget
        config_tab = QWidget()
        config_layout = QVBoxLayout(config_tab)
        config_layout.setContentsMargins(4, 8, 4, 8)
        config_layout.setSpacing(12)
        self._build_configuration_tab(config_layout)
        self.sub_tabs.addTab(config_tab, "⚙️ Configuration (A–E)")

        # 2. Operations Tab Widget
        ops_tab = QWidget()
        ops_layout = QVBoxLayout(ops_tab)
        ops_layout.setContentsMargins(4, 8, 4, 8)
        ops_layout.setSpacing(12)
        self._build_operations_tab(ops_layout)
        self.sub_tabs.addTab(ops_tab, "🎯 Operations & Mission (F–I)")

        main_layout.addWidget(self.sub_tabs, 1)

    # -----------------------------------------------------------------
    # CONFIGURATION SECTION (GROUPS A–E)
    # -----------------------------------------------------------------
    def _build_configuration_tab(self, layout: QVBoxLayout) -> None:
        # ---- A: Sensor Resolution & FOV ----
        fov_box, fov_grid = self._make_group("A — Sensor Resolution & Optical Field of View (FOV)")
        fov_grid.setColumnStretch(1, 2)
        fov_grid.setColumnStretch(4, 2)

        fov_grid.addWidget(self._label("Resolution W (px)"), 0, 0)
        self.fov_w_slider, self.fov_w_label = self._make_int_slider(320, 5000, 640, tooltip="Sensor pixel resolution width (default 640)")
        fov_grid.addWidget(self.fov_w_slider, 0, 1)
        fov_grid.addWidget(self.fov_w_label, 0, 2)

        fov_grid.addWidget(self._label("Resolution H (px)"), 0, 3)
        self.fov_h_slider, self.fov_h_label = self._make_int_slider(240, 5000, 480, tooltip="Sensor pixel resolution height (default 480)")
        fov_grid.addWidget(self.fov_h_slider, 0, 4)
        fov_grid.addWidget(self.fov_h_label, 0, 5)

        fov_grid.addWidget(self._label("FOV X (deg)"), 1, 0)
        self.fov_x_slider, self.fov_x_label, self.fov_x_factor = self._make_float_slider(0.5, 20.0, 4.0, decimals=1, suffix=" deg", tooltip="Horizontal field of view")
        fov_grid.addWidget(self.fov_x_slider, 1, 1)
        fov_grid.addWidget(self.fov_x_label, 1, 2)

        fov_grid.addWidget(self._label("FOV Y (deg)"), 1, 3)
        self.fov_y_slider, self.fov_y_label, self.fov_y_factor = self._make_float_slider(0.5, 20.0, 3.0, decimals=1, suffix=" deg", tooltip="Vertical field of view")
        fov_grid.addWidget(self.fov_y_slider, 1, 4)
        fov_grid.addWidget(self.fov_y_label, 1, 5)

        type_lbl = QLabel("Camera Type: Monochrome • Sensor Type: Focal Plane Array (FPA) NIR-Sensitive")
        type_lbl.setStyleSheet("color:#475569; font-size:10px; font-style:italic; padding-top:2px;")
        fov_grid.addWidget(type_lbl, 2, 0, 1, 6)
        layout.addWidget(fov_box)

        # ---- B: Pan-Tilt Mechanics ----
        mech_box, mech_grid = self._make_group("B — Pan-Tilt Mechanics & Actuator Specifications")
        mech_grid.setColumnStretch(1, 2)
        mech_grid.setColumnStretch(4, 2)

        mech_grid.addWidget(self._label("Pan Min (px)"), 0, 0)
        self.pan_min_slider, self.pan_min_label = self._make_int_slider(0, 5000, 0, tooltip="Pan minimum (0 = auto FOV/2)")
        mech_grid.addWidget(self.pan_min_slider, 0, 1)
        mech_grid.addWidget(self.pan_min_label, 0, 2)

        mech_grid.addWidget(self._label("Pan Max (px)"), 0, 3)
        self.pan_max_slider, self.pan_max_label = self._make_int_slider(0, 5000, 0, tooltip="Pan maximum (0 = auto W - FOV/2)")
        mech_grid.addWidget(self.pan_max_slider, 0, 4)
        mech_grid.addWidget(self.pan_max_label, 0, 5)

        mech_grid.addWidget(self._label("Tilt Min (px)"), 1, 0)
        self.tilt_min_slider, self.tilt_min_label = self._make_int_slider(0, 5000, 0, tooltip="Tilt minimum (0 = auto FOV/2)")
        mech_grid.addWidget(self.tilt_min_slider, 1, 1)
        mech_grid.addWidget(self.tilt_min_label, 1, 2)

        mech_grid.addWidget(self._label("Tilt Max (px)"), 1, 3)
        self.tilt_max_slider, self.tilt_max_label = self._make_int_slider(0, 5000, 0, tooltip="Tilt maximum (0 = auto H - FOV/2)")
        mech_grid.addWidget(self.tilt_max_slider, 1, 4)
        mech_grid.addWidget(self.tilt_max_label, 1, 5)

        mech_grid.addWidget(self._label("Home Pan (px)"), 2, 0)
        self.home_pan_slider, self.home_pan_label = self._make_int_slider(0, 5000, 1000, tooltip="Boresight home position")
        self.home_pan_slider.setEnabled(False)
        mech_grid.addWidget(self.home_pan_slider, 2, 1)
        mech_grid.addWidget(self.home_pan_label, 2, 2)

        mech_grid.addWidget(self._label("Home Tilt (px)"), 2, 3)
        self.home_tilt_slider, self.home_tilt_label = self._make_int_slider(0, 5000, 1000)
        self.home_tilt_slider.setEnabled(False)
        mech_grid.addWidget(self.home_tilt_slider, 2, 4)
        mech_grid.addWidget(self.home_tilt_label, 2, 5)

        mech_grid.addWidget(self._label("Pan Speed (deg/s)"), 3, 0)
        self.pan_speed_slider, self.pan_speed_label, self.pan_speed_factor = self._make_float_slider(1.0, 30.0, 8.0, decimals=1, suffix=" deg/s")
        mech_grid.addWidget(self.pan_speed_slider, 3, 1)
        mech_grid.addWidget(self.pan_speed_label, 3, 2)

        mech_grid.addWidget(self._label("Tilt Speed (deg/s)"), 3, 3)
        self.tilt_speed_slider, self.tilt_speed_label, self.tilt_speed_factor = self._make_float_slider(1.0, 30.0, 8.0, decimals=1, suffix=" deg/s")
        mech_grid.addWidget(self.tilt_speed_slider, 3, 4)
        mech_grid.addWidget(self.tilt_speed_label, 3, 5)

        mech_grid.addWidget(self._label("Actuator Res (px)"), 4, 0)
        self.res_slider, self.res_label, self.res_factor = self._make_float_slider(0.01, 2.0, 0.10, decimals=2, suffix=" px")
        mech_grid.addWidget(self.res_slider, 4, 1)
        mech_grid.addWidget(self.res_label, 4, 2)

        mech_grid.addWidget(self._label("Latency (ms)"), 4, 3)
        self.latency_slider, self.latency_label = self._make_int_slider(0, 500, 12, tooltip="Command queue delay")
        mech_grid.addWidget(self.latency_slider, 4, 4)
        mech_grid.addWidget(self.latency_label, 4, 5)

        mech_grid.addWidget(self._label("Update Rate (Hz)"), 5, 0)
        self.update_rate_slider, self.update_rate_label = self._make_int_slider(20, 120, 30, tooltip="Actuator refresh frequency")
        mech_grid.addWidget(self.update_rate_slider, 5, 1)
        mech_grid.addWidget(self.update_rate_label, 5, 2)

        mech_grid.addWidget(self._label("Control Mode"), 5, 3)
        self.combo_ctrl_mode = QComboBox()
        self.combo_ctrl_mode.addItems(["MANUAL", "SEARCH", "AUTO", "TRACKING"])
        self.combo_ctrl_mode.setMinimumHeight(26)
        mech_grid.addWidget(self.combo_ctrl_mode, 5, 4, 1, 2)

        layout.addWidget(mech_box)

        # ---- C: Display / Screen Sizes ----
        disp_box, disp_grid = self._make_group("C — Display & Screen Viewport Dimensions")
        disp_grid.setColumnStretch(1, 2)
        disp_grid.setColumnStretch(4, 2)

        disp_grid.addWidget(self._label("Camera Screen W"), 0, 0)
        self.viewport_w_slider, self.viewport_w_label = self._make_int_slider(500, 5000, 2000, tooltip="Camera Screen viewport width")
        disp_grid.addWidget(self.viewport_w_slider, 0, 1)
        disp_grid.addWidget(self.viewport_w_label, 0, 2)

        disp_grid.addWidget(self._label("Camera Screen H"), 0, 3)
        self.viewport_h_slider, self.viewport_h_label = self._make_int_slider(500, 5000, 2000)
        disp_grid.addWidget(self.viewport_h_slider, 0, 4)
        disp_grid.addWidget(self.viewport_h_label, 0, 5)

        disp_grid.addWidget(self._label("God View W"), 1, 0)
        self.god_w_slider, self.god_w_label = self._make_int_slider(2000, 5000, 2000, tooltip="Synced to World size")
        self.god_w_slider.setEnabled(False)
        disp_grid.addWidget(self.god_w_slider, 1, 1)
        disp_grid.addWidget(self.god_w_label, 1, 2)

        disp_grid.addWidget(self._label("God View H"), 1, 3)
        self.god_h_slider, self.god_h_label = self._make_int_slider(2000, 5000, 2000)
        self.god_h_slider.setEnabled(False)
        disp_grid.addWidget(self.god_h_slider, 1, 4)
        disp_grid.addWidget(self.god_h_label, 1, 5)
        layout.addWidget(disp_box)

        # ---- D: Pixel -> Angle (Derived Angular Model) ----
        ang_box, ang_grid = self._make_group("D — Derived Pixel ↔ Angle Model (Dynamically Computed)")
        ang_grid.setColumnStretch(1, 1)
        ang_grid.setColumnStretch(3, 1)

        ang_grid.addWidget(self._label("Pixel to Angle X:"), 0, 0)
        self.lbl_ang_x = QLabel("109.083 µrad/px")
        self.lbl_ang_x.setStyleSheet("font-size:12px; font-weight:700; color:#1e3a8a; background:#eff6ff; padding:3px 8px; border-radius:4px; border:1px solid #bfdbfe;")
        ang_grid.addWidget(self.lbl_ang_x, 0, 1)

        ang_grid.addWidget(self._label("Pixel to Angle Y:"), 0, 2)
        self.lbl_ang_y = QLabel("109.083 µrad/px")
        self.lbl_ang_y.setStyleSheet("font-size:12px; font-weight:700; color:#1e3a8a; background:#eff6ff; padding:3px 8px; border-radius:4px; border:1px solid #bfdbfe;")
        ang_grid.addWidget(self.lbl_ang_y, 0, 3)

        ang_grid.addWidget(self._label("Angle to Pixel X:"), 1, 0)
        self.lbl_inv_x = QLabel("0.00917 px/µrad")
        self.lbl_inv_x.setStyleSheet("font-size:11px; color:#475569;")
        ang_grid.addWidget(self.lbl_inv_x, 1, 1)

        ang_grid.addWidget(self._label("Angle to Pixel Y:"), 1, 2)
        self.lbl_inv_y = QLabel("0.00917 px/µrad")
        self.lbl_inv_y.setStyleSheet("font-size:11px; color:#475569;")
        ang_grid.addWidget(self.lbl_inv_y, 1, 3)

        ang_hint = QLabel("Derived automatically from optical geometry: θ = FOV / Resolution. (4.0° / 640 px = 109.083 µrad/px).")
        ang_hint.setStyleSheet("color:#64748b; font-size:10px; font-style:italic;")
        ang_grid.addWidget(ang_hint, 2, 0, 1, 4)
        layout.addWidget(ang_box)

        # ---- E: Realism & Mechanical Errors ----
        real_box, real_grid = self._make_group("E — Actuator Realism & Mechanical Imperfections")
        real_grid.setColumnStretch(1, 2)
        real_grid.setColumnStretch(4, 2)

        real_grid.addWidget(self._label("Max Accel (deg/s²)"), 0, 0)
        self.accel_slider, self.accel_label, self.accel_factor = self._make_float_slider(1.0, 100.0, 20.0, decimals=1, suffix=" deg/s²")
        real_grid.addWidget(self.accel_slider, 0, 1)
        real_grid.addWidget(self.accel_label, 0, 2)

        real_grid.addWidget(self._label("Backlash (px)"), 0, 3)
        self.backlash_slider, self.backlash_label, self.backlash_factor = self._make_float_slider(0.0, 2.0, 0.25, decimals=2, suffix=" px")
        real_grid.addWidget(self.backlash_slider, 0, 4)
        real_grid.addWidget(self.backlash_label, 0, 5)

        real_grid.addWidget(self._label("Encoder σ (px)"), 1, 0)
        self.encoder_slider, self.encoder_label, self.encoder_factor = self._make_float_slider(0.0, 0.5, 0.040, decimals=3, suffix=" px")
        real_grid.addWidget(self.encoder_slider, 1, 1)
        real_grid.addWidget(self.encoder_label, 1, 2)

        real_grid.addWidget(self._label("Latency Jitter (ms)"), 1, 3)
        self.jitter_slider, self.jitter_label, self.jitter_factor = self._make_float_slider(0.0, 20.0, 1.2, decimals=1, suffix=" ms")
        real_grid.addWidget(self.jitter_slider, 1, 4)
        real_grid.addWidget(self.jitter_label, 1, 5)
        layout.addWidget(real_box)

        layout.addStretch(1)

    # -----------------------------------------------------------------
    # OPERATIONS SECTION (GROUPS F–I)
    # -----------------------------------------------------------------
    def _build_operations_tab(self, layout: QVBoxLayout) -> None:
        # ---- F: Acquisition ----
        acq_box, acq_grid = self._make_group("F — Target Acquisition & Spatial Scanning")
        acq_grid.setColumnStretch(1, 2)
        acq_grid.setColumnStretch(4, 2)

        acq_grid.addWidget(self._label("Acquisition Mode"), 0, 0)
        self.combo_acq_mode = QComboBox()
        self.combo_acq_mode.addItems(["AUTO", "SEARCH", "AUTO_ACQUISITION", "MANUAL", "TARGET_POINTING"])
        self.combo_acq_mode.setMinimumHeight(26)
        acq_grid.addWidget(self.combo_acq_mode, 0, 1, 1, 2)

        acq_grid.addWidget(self._label("Search Pattern"), 0, 3)
        self.combo_acq_pattern = QComboBox()
        self.combo_acq_pattern.addItems(["RANDOM", "RASTER", "SPIRAL", "SECTOR", "GRID", "CUSTOM", "FIGURE_8"])
        self.combo_acq_pattern.setMinimumHeight(26)
        acq_grid.addWidget(self.combo_acq_pattern, 0, 4, 1, 2)

        acq_grid.addWidget(self._label("Pan Search Min (deg)"), 1, 0)
        self.acq_pmin_slider, self.acq_pmin_label, self.acq_pmin_factor = self._make_float_slider(-45.0, 0.0, -20.0, decimals=1, suffix=" deg")
        acq_grid.addWidget(self.acq_pmin_slider, 1, 1)
        acq_grid.addWidget(self.acq_pmin_label, 1, 2)

        acq_grid.addWidget(self._label("Pan Search Max (deg)"), 1, 3)
        self.acq_pmax_slider, self.acq_pmax_label, self.acq_pmax_factor = self._make_float_slider(0.0, 45.0, 20.0, decimals=1, suffix=" deg")
        acq_grid.addWidget(self.acq_pmax_slider, 1, 4)
        acq_grid.addWidget(self.acq_pmax_label, 1, 5)

        acq_grid.addWidget(self._label("Tilt Search Min (deg)"), 2, 0)
        self.acq_tmin_slider, self.acq_tmin_label, self.acq_tmin_factor = self._make_float_slider(-30.0, 0.0, -10.0, decimals=1, suffix=" deg")
        acq_grid.addWidget(self.acq_tmin_slider, 2, 1)
        acq_grid.addWidget(self.acq_tmin_label, 2, 2)

        acq_grid.addWidget(self._label("Tilt Search Max (deg)"), 2, 3)
        self.acq_tmax_slider, self.acq_tmax_label, self.acq_tmax_factor = self._make_float_slider(0.0, 30.0, 10.0, decimals=1, suffix=" deg")
        acq_grid.addWidget(self.acq_tmax_slider, 2, 4)
        acq_grid.addWidget(self.acq_tmax_label, 2, 5)

        acq_grid.addWidget(self._label("Scan Speed (deg/s)"), 3, 0)
        self.acq_speed_slider, self.acq_speed_label, self.acq_speed_factor = self._make_float_slider(1.0, 30.0, 15.0, decimals=1, suffix=" deg/s")
        acq_grid.addWidget(self.acq_speed_slider, 3, 1)
        acq_grid.addWidget(self.acq_speed_label, 3, 2)

        acq_grid.addWidget(self._label("Timeout (s)"), 3, 3)
        self.acq_timeout_slider, self.acq_timeout_label = self._make_int_slider(5, 120, 30, tooltip="Search sweep timeout duration")
        acq_grid.addWidget(self.acq_timeout_slider, 3, 4)
        acq_grid.addWidget(self.acq_timeout_label, 3, 5)
        layout.addWidget(acq_box)

        # ---- G: Detection ----
        det_box, det_grid = self._make_group("G — Optical Detection & Spectral Matching")
        det_grid.setColumnStretch(1, 2)
        det_grid.setColumnStretch(4, 2)

        det_grid.addWidget(self._label("Center Wavelength (nm)"), 0, 0)
        self.det_wl_slider, self.det_wl_label, self.det_wl_factor = self._make_float_slider(800.0, 1650.0, 1550.0, decimals=1, suffix=" nm")
        det_grid.addWidget(self.det_wl_slider, 0, 1)
        det_grid.addWidget(self.det_wl_label, 0, 2)

        det_grid.addWidget(self._label("Bandwidth (nm)"), 0, 3)
        self.det_bw_slider, self.det_bw_label, self.det_bw_factor = self._make_float_slider(1.0, 50.0, 10.0, decimals=1, suffix=" nm")
        det_grid.addWidget(self.det_bw_slider, 0, 4)
        det_grid.addWidget(self.det_bw_label, 0, 5)

        det_grid.addWidget(self._label("Minimum SNR (dB)"), 1, 0)
        self.det_snr_slider, self.det_snr_label, self.det_snr_factor = self._make_float_slider(1.0, 30.0, 8.0, decimals=1, suffix=" dB")
        det_grid.addWidget(self.det_snr_slider, 1, 1)
        det_grid.addWidget(self.det_snr_label, 1, 2)

        det_grid.addWidget(self._label("Intensity Thresh (DN)"), 1, 3)
        self.det_int_slider, self.det_int_label, self.det_int_factor = self._make_float_slider(0.0, 100.0, 0.0, decimals=1, suffix=" DN")
        det_grid.addWidget(self.det_int_slider, 1, 4)
        det_grid.addWidget(self.det_int_label, 1, 5)

        det_grid.addWidget(self._label("Expected Spot (mrad)"), 2, 0)
        self.det_spot_slider, self.det_spot_label, self.det_spot_factor = self._make_float_slider(0.5, 10.0, 3.0, decimals=1, suffix=" mrad")
        det_grid.addWidget(self.det_spot_slider, 2, 1)
        det_grid.addWidget(self.det_spot_label, 2, 2)

        det_grid.addWidget(self._label("Spot Tolerance (mrad)"), 2, 3)
        self.det_tol_slider, self.det_tol_label, self.det_tol_factor = self._make_float_slider(0.1, 2.0, 0.5, decimals=1, suffix=" mrad")
        det_grid.addWidget(self.det_tol_slider, 2, 4)
        det_grid.addWidget(self.det_tol_label, 2, 5)

        det_grid.addWidget(self._label("Modulation Type"), 3, 0)
        self.combo_mod_type = QComboBox()
        self.combo_mod_type.addItems(["AM", "PM", "OOK", "PPM", "ANY"])
        self.combo_mod_type.setMinimumHeight(26)
        det_grid.addWidget(self.combo_mod_type, 3, 1, 1, 2)

        det_grid.addWidget(self._label("Modulation Freq (kHz)"), 3, 3)
        self.det_mod_freq_slider, self.det_mod_freq_label, self.det_mod_freq_factor = self._make_float_slider(0.1, 50.0, 10.0, decimals=1, suffix=" kHz")
        det_grid.addWidget(self.det_mod_freq_slider, 3, 4)
        det_grid.addWidget(self.det_mod_freq_label, 3, 5)

        det_grid.addWidget(self._label("Confidence Thresh"), 4, 0)
        self.det_conf_slider, self.det_conf_label, self.det_conf_factor = self._make_float_slider(0.5, 1.0, 0.85, decimals=2)
        det_grid.addWidget(self.det_conf_slider, 4, 1)
        det_grid.addWidget(self.det_conf_label, 4, 2)

        det_grid.addWidget(self._label("Live Confidence"), 4, 3)
        self.prog_confidence = QProgressBar()
        self.prog_confidence.setRange(0, 100)
        self.prog_confidence.setValue(0)
        self.prog_confidence.setTextVisible(True)
        self.prog_confidence.setFormat("%v%")
        self.prog_confidence.setStyleSheet(
            "QProgressBar { border:1px solid #d1d5db; border-radius:4px; text-align:center; height:18px; font-weight:700; }"
            "QProgressBar::chunk { background:#059669; border-radius:3px; }"
        )
        det_grid.addWidget(self.prog_confidence, 4, 4, 1, 2)

        self.lbl_target_ident = QLabel("Target Discrimination: Autonomous scan active • Candidates in FOV: 0 | Identified Target: None")
        self.lbl_target_ident.setStyleSheet("color:#4338ca; font-weight:600; font-size:11px; padding-top:4px;")
        det_grid.addWidget(self.lbl_target_ident, 5, 0, 1, 6)

        layout.addWidget(det_box)

        # ---- H: Tracking ----
        trk_box, trk_grid = self._make_group("H — Centroid Target Tracking & Predictive Filtering")
        trk_grid.setColumnStretch(1, 2)
        trk_grid.setColumnStretch(4, 2)

        trk_grid.addWidget(self._label("Tracking Mode"), 0, 0)
        self.combo_trk_mode = QComboBox()
        self.combo_trk_mode.addItems(["OFF", "TRACKING", "AUTO"])
        self.combo_trk_mode.setMinimumHeight(26)
        trk_grid.addWidget(self.combo_trk_mode, 0, 1, 1, 2)

        trk_grid.addWidget(self._label("Algorithm"), 0, 3)
        self.combo_trk_algo = QComboBox()
        self.combo_trk_algo.addItems(["CENTROID", "PEAK", "KALMAN"])
        self.combo_trk_algo.setMinimumHeight(26)
        trk_grid.addWidget(self.combo_trk_algo, 0, 4, 1, 2)

        trk_grid.addWidget(self._label("Update Rate (Hz)"), 1, 0)
        self.trk_rate_slider, self.trk_rate_label = self._make_int_slider(10, 120, 30)
        trk_grid.addWidget(self.trk_rate_slider, 1, 1)
        trk_grid.addWidget(self.trk_rate_label, 1, 2)

        trk_grid.addWidget(self._label("Prediction Horizon (s)"), 1, 3)
        self.trk_horiz_slider, self.trk_horiz_label, self.trk_horiz_factor = self._make_float_slider(0.0, 2.0, 0.5, decimals=2, suffix=" s")
        trk_grid.addWidget(self.trk_horiz_slider, 1, 4)
        trk_grid.addWidget(self.trk_horiz_label, 1, 5)

        trk_grid.addWidget(self._label("Smoothing (0..1)"), 2, 0)
        self.trk_smooth_slider, self.trk_smooth_label, self.trk_smooth_factor = self._make_float_slider(0.0, 0.9, 0.2, decimals=2)
        trk_grid.addWidget(self.trk_smooth_slider, 2, 1)
        trk_grid.addWidget(self.trk_smooth_label, 2, 2)

        trk_grid.addWidget(self._label("Lost Target Action"), 2, 3)
        self.combo_lost_action = QComboBox()
        self.combo_lost_action.addItems(["RESUME_SEARCH", "HOLD_POSITION", "RETURN_HOME"])
        self.combo_lost_action.setMinimumHeight(26)
        trk_grid.addWidget(self.combo_lost_action, 2, 4, 1, 2)

        trk_grid.addWidget(self._label("Servo Kp (Prop Gain)"), 3, 0)
        self.trk_kp_slider, self.trk_kp_label, self.trk_kp_factor = self._make_float_slider(0.01, 1.0, 0.25, decimals=2)
        trk_grid.addWidget(self.trk_kp_slider, 3, 1)
        trk_grid.addWidget(self.trk_kp_label, 3, 2)

        trk_grid.addWidget(self._label("Servo Ki (Integ Gain)"), 3, 3)
        self.trk_ki_slider, self.trk_ki_label, self.trk_ki_factor = self._make_float_slider(0.0, 0.5, 0.05, decimals=3)
        trk_grid.addWidget(self.trk_ki_slider, 3, 4)
        trk_grid.addWidget(self.trk_ki_label, 3, 5)

        trk_grid.addWidget(self._label("Servo Kd (Deriv Gain)"), 4, 0)
        self.trk_kd_slider, self.trk_kd_label, self.trk_kd_factor = self._make_float_slider(0.0, 0.2, 0.02, decimals=3)
        trk_grid.addWidget(self.trk_kd_slider, 4, 1)
        trk_grid.addWidget(self.trk_kd_label, 4, 2)

        trk_grid.addWidget(self._label("Dead Zone (px)"), 4, 3)
        self.trk_dz_slider, self.trk_dz_label, self.trk_dz_factor = self._make_float_slider(0.0, 5.0, 0.5, decimals=1, suffix=" px")
        trk_grid.addWidget(self.trk_dz_slider, 4, 4)
        trk_grid.addWidget(self.trk_dz_label, 4, 5)

        self.lbl_trk_offsets = QLabel("Tracking Error: Δx = 0.0 px (0.0 µrad) • Δy = 0.0 px (0.0 µrad)")
        self.lbl_trk_offsets.setStyleSheet("color:#1e3a8a; font-weight:600; font-size:11px; padding-top:4px;")
        trk_grid.addWidget(self.lbl_trk_offsets, 5, 0, 1, 6)

        layout.addWidget(trk_box)

        # ---- I: Communication ----
        comm_box, comm_grid = self._make_group("I — Optical Communication & Transceiver Link")
        comm_grid.setColumnStretch(1, 2)
        comm_grid.setColumnStretch(3, 2)

        comm_grid.addWidget(self._label("Terminal ID"), 0, 0)
        self.txt_comm_id = QLineEdit("LT-001")
        self.txt_comm_id.setReadOnly(True)
        self.txt_comm_id.setMinimumHeight(24)
        comm_grid.addWidget(self.txt_comm_id, 0, 1)

        comm_grid.addWidget(self._label("Protocol"), 0, 2)
        self.txt_comm_proto = QLineEdit("OPTICAL_LINK")
        self.txt_comm_proto.setMinimumHeight(24)
        comm_grid.addWidget(self.txt_comm_proto, 0, 3)

        comm_grid.addWidget(self._label("Capabilities"), 1, 0)
        caps_layout = QHBoxLayout()
        self.chk_cap_rx = QCheckBox("OPTICAL_RX")
        self.chk_cap_rx.setChecked(True)
        self.chk_cap_tx = QCheckBox("OPTICAL_TX")
        self.chk_cap_tx.setChecked(True)
        self.chk_cap_trk = QCheckBox("TRACKING")
        self.chk_cap_trk.setChecked(True)
        caps_layout.addWidget(self.chk_cap_rx)
        caps_layout.addWidget(self.chk_cap_tx)
        caps_layout.addWidget(self.chk_cap_trk)
        caps_layout.addStretch(1)
        comm_grid.addLayout(caps_layout, 1, 1, 1, 3)

        layout.addWidget(comm_box)
        layout.addStretch(1)

        self._setup_backward_compatibility_aliases()
        self._wire_signals()

    # -----------------------------------------------------------------
    # HELPERS & COMPATIBILITY ALIASES
    # -----------------------------------------------------------------
    def _make_badge(self, text: str, fg: str, bg: str, border: str) -> QLabel:
        b = QLabel(text)
        b.setStyleSheet(
            f"color:{fg}; background:{bg}; border:1px solid {border}; "
            "border-radius:4px; font-weight:700; font-size:11px; padding:3px 8px;"
        )
        return b

    def _setup_backward_compatibility_aliases(self) -> None:
        """Provide alias attributes so existing MainWindow and test suites work unchanged."""
        self.fov_w_spin = self.fov_w_slider
        self.fov_h_spin = self.fov_h_slider
        self.pan_min_spin = self.pan_min_slider
        self.pan_max_spin = self.pan_max_slider
        self.tilt_min_spin = self.tilt_min_slider
        self.tilt_max_spin = self.tilt_max_slider
        self.home_pan_spin = self.home_pan_slider
        self.home_tilt_spin = self.home_tilt_slider
        self.pan_speed_deg_spin = self.pan_speed_slider
        self.tilt_speed_deg_spin = self.tilt_speed_slider
        self.res_spin = self.res_slider
        self.latency_spin = self.latency_slider
        self.update_rate_spin = self.update_rate_slider
        self.viewport_w_spin = self.viewport_w_slider
        self.viewport_h_spin = self.viewport_h_slider
        self.god_w_spin = self.god_w_slider
        self.god_h_spin = self.god_h_slider
        self.accel_spin = self.accel_slider
        self.backlash_spin = self.backlash_slider
        self.encoder_spin = self.encoder_slider
        self.latency_jitter_spin = self.jitter_slider
        self.scale_slider = self.lbl_ang_x  # display alias
        self.btn_reset = self.btn_reset_all

    def _wire_signals(self) -> None:
        # All sliders, combos, checkboxes connect to _on_change
        sliders = [
            self.fov_w_slider, self.fov_h_slider, self.fov_x_slider, self.fov_y_slider,
            self.pan_min_slider, self.pan_max_slider, self.tilt_min_slider, self.tilt_max_slider,
            self.pan_speed_slider, self.tilt_speed_slider, self.res_slider, self.latency_slider,
            self.update_rate_slider, self.viewport_w_slider, self.viewport_h_slider,
            self.accel_slider, self.backlash_slider, self.encoder_slider, self.jitter_slider,
            self.acq_pmin_slider, self.acq_pmax_slider, self.acq_tmin_slider, self.acq_tmax_slider,
            self.acq_speed_slider, self.acq_timeout_slider, self.det_wl_slider, self.det_bw_slider,
            self.det_snr_slider, self.det_int_slider, self.det_spot_slider, self.det_tol_slider,
            self.det_mod_freq_slider, self.det_conf_slider, self.trk_rate_slider,
            self.trk_horiz_slider, self.trk_smooth_slider,
            self.trk_kp_slider, self.trk_ki_slider, self.trk_kd_slider, self.trk_dz_slider,
        ]
        for s in sliders:
            s.valueChanged.connect(self._on_change)

        combos = [
            self.combo_ctrl_mode, self.combo_acq_mode, self.combo_acq_pattern,
            self.combo_mod_type, self.combo_trk_mode, self.combo_trk_algo, self.combo_lost_action,
        ]
        for c in combos:
            c.currentIndexChanged.connect(self._on_change)

        for chk in (self.chk_cap_rx, self.chk_cap_tx, self.chk_cap_trk):
            chk.toggled.connect(self._on_change)

        self.txt_comm_proto.textChanged.connect(self._on_change)

    def _on_change(self) -> None:
        if self._updating:
            return
        self._update_derived_angular_labels()
        self.configChanged.emit(self.collect_config())

    def _update_derived_angular_labels(self) -> None:
        """Dynamically compute and display angular model values per LocalTerminal.md."""
        fw = max(1, self.fov_w_slider.value())
        fh = max(1, self.fov_h_slider.value())
        fx = self.fov_x_slider.value() / self.fov_x_factor
        fy = self.fov_y_slider.value() / self.fov_y_factor

        import math
        x_urad = (math.radians(fx) * 1e6) / fw
        y_urad = (math.radians(fy) * 1e6) / fh
        inv_x = 1.0 / x_urad if x_urad > 0 else 0.0
        inv_y = 1.0 / y_urad if y_urad > 0 else 0.0

        self.lbl_ang_x.setText(f"{x_urad:.3f} µrad/px")
        self.lbl_ang_y.setText(f"{y_urad:.3f} µrad/px")
        self.lbl_inv_x.setText(f"{inv_x:.5f} px/µrad")
        self.lbl_inv_y.setText(f"{inv_y:.5f} px/µrad")

    def _on_reset_clicked(self) -> None:
        self.set_config(LocalTerminalConfig().validate(self._scene_bounds), emit=True)

    # -----------------------------------------------------------------
    # CONFIG COLLECTION & POPULATION
    # -----------------------------------------------------------------
    def collect_config(self) -> LocalTerminalConfig:
        cfg = copy.deepcopy(self._config)

        # A: Camera Sensor
        cfg.camera.resolution_width = int(self.fov_w_slider.value())
        cfg.camera.resolution_height = int(self.fov_h_slider.value())
        cfg.camera.fov_x = float(self.fov_x_slider.value() / self.fov_x_factor)
        cfg.camera.fov_y = float(self.fov_y_slider.value() / self.fov_y_factor)

        # B: PTZ Mechanics
        cfg.ptz.pan_min = float(self.pan_min_slider.value())
        cfg.ptz.pan_max = float(self.pan_max_slider.value())
        cfg.ptz.tilt_min = float(self.tilt_min_slider.value())
        cfg.ptz.tilt_max = float(self.tilt_max_slider.value())
        cfg.ptz.home_pan = float(self.home_pan_slider.value())
        cfg.ptz.home_tilt = float(self.home_tilt_slider.value())
        cfg.ptz.pan_speed = float(self.pan_speed_slider.value() / self.pan_speed_factor)
        cfg.ptz.tilt_speed = float(self.tilt_speed_slider.value() / self.tilt_speed_factor)
        cfg.ptz.resolution = float(self.res_slider.value() / self.res_factor)
        cfg.ptz.latency = int(self.latency_slider.value())
        cfg.ptz.update_rate = int(self.update_rate_slider.value())
        cfg.ptz.control_mode = self.combo_ctrl_mode.currentText()

        # C: Display
        cfg.display.camera_screen_width = int(self.viewport_w_slider.value())
        cfg.display.camera_screen_height = int(self.viewport_h_slider.value())
        cfg.display.god_view_width = int(self.god_w_slider.value())
        cfg.display.god_view_height = int(self.god_h_slider.value())

        # E: Realism
        cfg.realism.max_acceleration = float(self.accel_slider.value() / self.accel_factor)
        cfg.realism.backlash = float(self.backlash_slider.value() / self.backlash_factor)
        cfg.realism.encoder_sigma = float(self.encoder_slider.value() / self.encoder_factor)
        cfg.realism.latency_jitter = float(self.jitter_slider.value() / self.jitter_factor)

        # F: Acquisition
        cfg.acquisition.mode = self.combo_acq_mode.currentText()
        cfg.acquisition.search_pattern = self.combo_acq_pattern.currentText()
        cfg.acquisition.search_region_pan_min = float(self.acq_pmin_slider.value() / self.acq_pmin_factor)
        cfg.acquisition.search_region_pan_max = float(self.acq_pmax_slider.value() / self.acq_pmax_factor)
        cfg.acquisition.search_region_tilt_min = float(self.acq_tmin_slider.value() / self.acq_tmin_factor)
        cfg.acquisition.search_region_tilt_max = float(self.acq_tmax_slider.value() / self.acq_tmax_factor)
        cfg.acquisition.search_speed = float(self.acq_speed_slider.value() / self.acq_speed_factor)
        cfg.acquisition.timeout = float(self.acq_timeout_slider.value())

        # G: Detection
        cfg.detection.wavelength = float(self.det_wl_slider.value() / self.det_wl_factor)
        cfg.detection.bandwidth = float(self.det_bw_slider.value() / self.det_bw_factor)
        cfg.detection.minimum_snr = float(self.det_snr_slider.value() / self.det_snr_factor)
        cfg.detection.intensity_threshold = float(self.det_int_slider.value() / self.det_int_factor)
        cfg.detection.expected_spot_size = float(self.det_spot_slider.value() / self.det_spot_factor)
        cfg.detection.expected_spot_tolerance = float(self.det_tol_slider.value() / self.det_tol_factor)
        cfg.detection.modulation_type = self.combo_mod_type.currentText()
        cfg.detection.modulation_frequency = float(self.det_mod_freq_slider.value() / self.det_mod_freq_factor)
        cfg.detection.confidence_threshold = float(self.det_conf_slider.value() / self.det_conf_factor)

        # H: Tracking
        cfg.tracking.mode = self.combo_trk_mode.currentText()
        cfg.tracking.algorithm = self.combo_trk_algo.currentText()
        cfg.tracking.update_rate = int(self.trk_rate_slider.value())
        cfg.tracking.prediction_horizon = float(self.trk_horiz_slider.value() / self.trk_horiz_factor)
        cfg.tracking.smoothing = float(self.trk_smooth_slider.value() / self.trk_smooth_factor)
        cfg.tracking.lost_target_behavior = self.combo_lost_action.currentText()
        cfg.tracking.kp = float(self.trk_kp_slider.value() / self.trk_kp_factor)
        cfg.tracking.ki = float(self.trk_ki_slider.value() / self.trk_ki_factor)
        cfg.tracking.kd = float(self.trk_kd_slider.value() / self.trk_kd_factor)
        cfg.tracking.dead_zone = float(self.trk_dz_slider.value() / self.trk_dz_factor)

        # I: Communication
        caps = []
        if self.chk_cap_rx.isChecked(): caps.append("OPTICAL_RX")
        if self.chk_cap_tx.isChecked(): caps.append("OPTICAL_TX")
        if self.chk_cap_trk.isChecked(): caps.append("TRACKING")
        cfg.communication.capabilities = caps
        cfg.communication.protocol = self.txt_comm_proto.text().strip()

        cfg.validate(self._scene_bounds)
        self._config = cfg
        return cfg

    def set_config(self, config: LocalTerminalConfig | Any, emit: bool = True) -> None:
        if config is None:
            return
        if not isinstance(config, LocalTerminalConfig):
            config = LocalTerminalConfig.from_camera_config(config)

        self._updating = True
        try:
            cfg = config.validate(self._scene_bounds)
            self._config = cfg

            # A: Sensor
            self.fov_w_slider.setValue(cfg.camera.resolution_width)
            self.fov_h_slider.setValue(cfg.camera.resolution_height)
            self.fov_x_slider.setValue(int(round(cfg.camera.fov_x * self.fov_x_factor)))
            self.fov_y_slider.setValue(int(round(cfg.camera.fov_y * self.fov_y_factor)))

            # B: PTZ
            self.pan_min_slider.setValue(int(cfg.ptz.pan_min))
            self.pan_max_slider.setValue(int(cfg.ptz.pan_max))
            self.tilt_min_slider.setValue(int(cfg.ptz.tilt_min))
            self.tilt_max_slider.setValue(int(cfg.ptz.tilt_max))
            self.home_pan_slider.setValue(int(cfg.ptz.home_pan))
            self.home_tilt_slider.setValue(int(cfg.ptz.home_tilt))
            self.pan_speed_slider.setValue(int(round(cfg.ptz.pan_speed * self.pan_speed_factor)))
            self.tilt_speed_slider.setValue(int(round(cfg.ptz.tilt_speed * self.tilt_speed_factor)))
            self.res_slider.setValue(int(round(cfg.ptz.resolution * self.res_factor)))
            self.latency_slider.setValue(int(cfg.ptz.latency))
            self.update_rate_slider.setValue(int(cfg.ptz.update_rate))
            idx = self.combo_ctrl_mode.findText(cfg.ptz.control_mode)
            if idx >= 0: self.combo_ctrl_mode.setCurrentIndex(idx)

            # C: Display
            self.viewport_w_slider.setValue(int(cfg.display.camera_screen_width))
            self.viewport_h_slider.setValue(int(cfg.display.camera_screen_height))
            self.god_w_slider.setValue(int(cfg.display.god_view_width))
            self.god_h_slider.setValue(int(cfg.display.god_view_height))

            # E: Realism
            self.accel_slider.setValue(int(round(cfg.realism.max_acceleration * self.accel_factor)))
            self.backlash_slider.setValue(int(round(cfg.realism.backlash * self.backlash_factor)))
            self.encoder_slider.setValue(int(round(cfg.realism.encoder_sigma * self.encoder_factor)))
            self.jitter_slider.setValue(int(round(cfg.realism.latency_jitter * self.jitter_factor)))

            # F: Acquisition
            idx = self.combo_acq_mode.findText(cfg.acquisition.mode)
            if idx >= 0: self.combo_acq_mode.setCurrentIndex(idx)
            idx = self.combo_acq_pattern.findText(cfg.acquisition.search_pattern)
            if idx >= 0: self.combo_acq_pattern.setCurrentIndex(idx)
            self.acq_pmin_slider.setValue(int(round(cfg.acquisition.search_region_pan_min * self.acq_pmin_factor)))
            self.acq_pmax_slider.setValue(int(round(cfg.acquisition.search_region_pan_max * self.acq_pmax_factor)))
            self.acq_tmin_slider.setValue(int(round(cfg.acquisition.search_region_tilt_min * self.acq_tmin_factor)))
            self.acq_tmax_slider.setValue(int(round(cfg.acquisition.search_region_tilt_max * self.acq_tmax_factor)))
            self.acq_speed_slider.setValue(int(round(cfg.acquisition.search_speed * self.acq_speed_factor)))
            self.acq_timeout_slider.setValue(int(cfg.acquisition.timeout))

            # G: Detection
            self.det_wl_slider.setValue(int(round(cfg.detection.wavelength * self.det_wl_factor)))
            self.det_bw_slider.setValue(int(round(cfg.detection.bandwidth * self.det_bw_factor)))
            self.det_snr_slider.setValue(int(round(cfg.detection.minimum_snr * self.det_snr_factor)))
            self.det_int_slider.setValue(int(round(cfg.detection.intensity_threshold * self.det_int_factor)))
            self.det_spot_slider.setValue(int(round(cfg.detection.expected_spot_size * self.det_spot_factor)))
            self.det_tol_slider.setValue(int(round(cfg.detection.expected_spot_tolerance * self.det_tol_factor)))
            idx = self.combo_mod_type.findText(cfg.detection.modulation_type)
            if idx >= 0: self.combo_mod_type.setCurrentIndex(idx)
            self.det_mod_freq_slider.setValue(int(round(cfg.detection.modulation_frequency * self.det_mod_freq_factor)))
            self.det_conf_slider.setValue(int(round(cfg.detection.confidence_threshold * self.det_conf_factor)))

            # H: Tracking
            idx = self.combo_trk_mode.findText(cfg.tracking.mode)
            if idx >= 0: self.combo_trk_mode.setCurrentIndex(idx)
            idx = self.combo_trk_algo.findText(cfg.tracking.algorithm)
            if idx >= 0: self.combo_trk_algo.setCurrentIndex(idx)
            self.trk_rate_slider.setValue(int(cfg.tracking.update_rate))
            self.trk_horiz_slider.setValue(int(round(cfg.tracking.prediction_horizon * self.trk_horiz_factor)))
            self.trk_smooth_slider.setValue(int(round(cfg.tracking.smoothing * self.trk_smooth_factor)))
            idx = self.combo_lost_action.findText(cfg.tracking.lost_target_behavior)
            if idx >= 0: self.combo_lost_action.setCurrentIndex(idx)
            self.trk_kp_slider.setValue(int(round(cfg.tracking.kp * self.trk_kp_factor)))
            self.trk_ki_slider.setValue(int(round(cfg.tracking.ki * self.trk_ki_factor)))
            self.trk_kd_slider.setValue(int(round(cfg.tracking.kd * self.trk_kd_factor)))
            self.trk_dz_slider.setValue(int(round(cfg.tracking.dead_zone * self.trk_dz_factor)))

            # I: Communication
            self.txt_comm_id.setText(cfg.identity.id)
            self.txt_comm_proto.setText(cfg.communication.protocol)
            caps = cfg.communication.capabilities or []
            self.chk_cap_rx.setChecked("OPTICAL_RX" in caps)
            self.chk_cap_tx.setChecked("OPTICAL_TX" in caps)
            self.chk_cap_trk.setChecked("TRACKING" in caps)

            self._update_derived_angular_labels()
        finally:
            self._updating = False

        if emit:
            self.configChanged.emit(self._config)

    def set_scene_bounds(self, scene_bounds: tuple[int, int]) -> None:
        self._scene_bounds = scene_bounds
        sw, sh = scene_bounds
        self.fov_w_slider.setMaximum(sw - 10)
        self.fov_h_slider.setMaximum(sh - 10)
        self.pan_min_slider.setMaximum(sw)
        self.pan_max_slider.setMaximum(sw)
        self.tilt_min_slider.setMaximum(sh)
        self.tilt_max_slider.setMaximum(sh)
        self.home_pan_slider.setMaximum(sw)
        self.home_tilt_slider.setMaximum(sh)
        cur_pan = self.home_pan_slider.value()
        if cur_pan <= 0 or cur_pan > sw:
            self.home_pan_slider.setValue(sw // 2)
        cur_tilt = self.home_tilt_slider.value()
        if cur_tilt <= 0 or cur_tilt > sh:
            self.home_tilt_slider.setValue(sh // 2)
        self.god_w_slider.setValue(sw)
        self.god_h_slider.setValue(sh)

    # -----------------------------------------------------------------
    # REAL-TIME TELEMETRY MONITORING
    # -----------------------------------------------------------------
    def update_telemetry(self, telemetry: dict[str, Any] | None) -> None:
        """Update live status chips, confidence progress, and tracking offsets."""
        if not isinstance(telemetry, dict):
            return
        st = telemetry.get("state", {})
        det = telemetry.get("detection", {})
        trk = telemetry.get("tracking", {})
        comm = telemetry.get("communication", {})

        # Power
        pwr = st.get("power_state", "ON")
        self.badge_power.setText(f"Power: {pwr}")
        self.badge_power.setStyleSheet(
            "color:#059669; background:#ecfdf5; border:1px solid #a7f3d0; border-radius:4px; font-weight:700; font-size:11px; padding:3px 8px;"
            if pwr == "ON" else
            "color:#dc2626; background:#fef2f2; border:1px solid #fecaca; border-radius:4px; font-weight:700; font-size:11px; padding:3px 8px;"
        )

        # Operational
        op = st.get("operational_state", "STANDBY")
        self.badge_op.setText(f"Op: {op}")

        # PTZ
        ptz = st.get("ptz_state", "IDLE")
        self.badge_ptz.setText(f"PTZ: {ptz}")

        # Acquisition
        acq = st.get("acquisition_state", "IDLE")
        self.badge_acq.setText(f"Acq: {acq}")
        self.badge_acq.setStyleSheet(
            "color:#2563eb; background:#eff6ff; border:1px solid #bfdbfe; border-radius:4px; font-weight:700; font-size:11px; padding:3px 8px;"
            if acq in ("SEARCHING", "ACQUIRING") else
            "color:#059669; background:#ecfdf5; border:1px solid #a7f3d0; border-radius:4px; font-weight:700; font-size:11px; padding:3px 8px;"
            if acq == "ACQUIRED" else
            "color:#4b5563; background:#f9fafb; border:1px solid #e5e7eb; border-radius:4px; font-weight:700; font-size:11px; padding:3px 8px;"
        )

        # Detection
        d_st = st.get("detection_state", "NO_TARGET")
        self.badge_det.setText(f"Det: {d_st}")
        self.badge_det.setStyleSheet(
            "color:#059669; background:#ecfdf5; border:1px solid #a7f3d0; border-radius:4px; font-weight:700; font-size:11px; padding:3px 8px;"
            if d_st == "CONFIRMED" else
            "color:#7c3aed; background:#f5f3ff; border:1px solid #ddd6fe; border-radius:4px; font-weight:700; font-size:11px; padding:3px 8px;"
            if d_st == "DISCRIMINATING" else
            "color:#d97706; background:#fffbeb; border:1px solid #fde68a; border-radius:4px; font-weight:700; font-size:11px; padding:3px 8px;"
            if d_st == "DETECTED" else
            "color:#4b5563; background:#f9fafb; border:1px solid #e5e7eb; border-radius:4px; font-weight:700; font-size:11px; padding:3px 8px;"
        )
        conf = float(det.get("confidence", 0.0))
        self.prog_confidence.setValue(int(round(conf * 100.0)))

        # Tracking
        t_st = st.get("tracking_state", "OFF")
        self.badge_trk.setText(f"Trk: {t_st}")
        self.badge_trk.setStyleSheet(
            "color:#059669; background:#ecfdf5; border:1px solid #a7f3d0; border-radius:4px; font-weight:700; font-size:11px; padding:3px 8px;"
            if t_st == "TRACKING" else
            "color:#d97706; background:#fffbeb; border:1px solid #fde68a; border-radius:4px; font-weight:700; font-size:11px; padding:3px 8px;"
            if t_st == "REACQUIRING" else
            "color:#6b7280; background:#f3f4f6; border:1px solid #e5e7eb; border-radius:4px; font-weight:700; font-size:11px; padding:3px 8px;"
        )
        err_px = trk.get("error_px", (0.0, 0.0))
        err_urad = trk.get("error_urad", (0.0, 0.0))
        self.lbl_trk_offsets.setText(
            f"Tracking Error: Δx = {err_px[0]:+.1f} px ({err_urad[0]:+.1f} µrad) • Δy = {err_px[1]:+.1f} px ({err_urad[1]:+.1f} µrad)"
        )

        # Autonomy Status & Target Discrimination
        aut = telemetry.get("autonomy", {})
        aut_state = aut.get("state", "SEARCHING")
        active_id = aut.get("active_target_id")
        cand_count = aut.get("candidate_count", 0)

        if aut_state == "LOCKED":
            self.badge_autonomy.setText(f"Auto: LOCKED [{active_id}]")
            self.badge_autonomy.setStyleSheet("color:#059669; background:#ecfdf5; border:1px solid #a7f3d0; border-radius:4px; font-weight:700; font-size:11px; padding:3px 8px;")
        elif aut_state == "DISCRIMINATING":
            self.badge_autonomy.setText(f"Auto: DISCRIMINATING ({cand_count})")
            self.badge_autonomy.setStyleSheet("color:#7c3aed; background:#f5f3ff; border:1px solid #ddd6fe; border-radius:4px; font-weight:700; font-size:11px; padding:3px 8px;")
        elif aut_state == "REACQUIRING":
            self.badge_autonomy.setText("Auto: REACQUIRING")
            self.badge_autonomy.setStyleSheet("color:#d97706; background:#fffbeb; border:1px solid #fde68a; border-radius:4px; font-weight:700; font-size:11px; padding:3px 8px;")
        elif aut_state == "SEARCHING":
            self.badge_autonomy.setText("Auto: RANDOM SEARCH")
            self.badge_autonomy.setStyleSheet("color:#2563eb; background:#eff6ff; border:1px solid #bfdbfe; border-radius:4px; font-weight:700; font-size:11px; padding:3px 8px;")
        else:
            self.badge_autonomy.setText(f"Auto: {aut_state}")
            self.badge_autonomy.setStyleSheet("color:#4b5563; background:#f9fafb; border:1px solid #e5e7eb; border-radius:4px; font-weight:700; font-size:11px; padding:3px 8px;")

        if active_id:
            self.lbl_target_ident.setText(f"Target Discrimination: Confirmed Optical Lock: {active_id} | Candidates Evaluated: {cand_count}")
        elif cand_count > 0:
            self.lbl_target_ident.setText(f"Target Discrimination: Evaluating {cand_count} visible optical beacons... (Validating signatures)")
        else:
            self.lbl_target_ident.setText("Target Discrimination: Autonomous search active • Scanning for compatible optical beacons...")

        # Link
        lnk = comm.get("link_state") or st.get("link_state", "NO_LINK")
        self.badge_link.setText(f"Link: {lnk}")
        self.badge_link.setStyleSheet(
            "color:#059669; background:#ecfdf5; border:1px solid #a7f3d0; border-radius:4px; font-weight:700; font-size:11px; padding:3px 8px;"
            if lnk == "CONNECTED" else
            "color:#d97706; background:#fffbeb; border:1px solid #fde68a; border-radius:4px; font-weight:700; font-size:11px; padding:3px 8px;"
            if lnk in ("OPTICAL_LOCK", "HANDSHAKE") else
            "color:#dc2626; background:#fef2f2; border:1px solid #fecaca; border-radius:4px; font-weight:700; font-size:11px; padding:3px 8px;"
        )

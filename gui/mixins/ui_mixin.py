# gui/mixins/ui_mixin.py - UI construction for MainWindow
# Extracted from gui/main_window.py (267 + 189 + helpers). Single Responsibility: Build Qt layouts.

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QHBoxLayout, QLabel, QVBoxLayout, QWidget, QTabWidget, QScrollArea, QSplitter, QFrame
)
from gui.panels.environment_panel import EnvironmentPanel  # canonical (shim at gui/environment_panel.py for compat)
from gui.panels.multi_beacon_panel import MultiBeaconPanel  # canonical (shim at gui/multi_beacon_panel.py for compat)
from gui.panels.camera_panel import CameraPanel
from gui.panels.control_panel import ControlPanel
from gui.panels.dashboard_panel import DashboardPanel
from gui.panels.disturbances_panel import DisturbancesPanel
from gui.panels.global_panel import GlobalPanel
from gui.windows.control_window import ControlDashboardWindow
from gui.widgets.camera_card import create_camera_card


class UIMixin:
    """Mixin: Builds MainWindow visual layout (video stage + dashboard + control deck)."""

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QHBoxLayout(central)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(12)

        main_splitter = QSplitter(Qt.Horizontal)
        main_splitter.setHandleWidth(6)
        main_splitter.setChildrenCollapsible(False)

        # ——— Left: Video Stage ———
        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(10)

        # App header — simple light banner
        header_bar = QFrame()
        header_bar.setObjectName("appHeader")
        header_bar.setFixedHeight(48)
        hdr = QHBoxLayout(header_bar)
        hdr.setContentsMargins(12, 8, 12, 8)
        hdr.setSpacing(12)
        title_col = QVBoxLayout()
        title_col.setSpacing(1)
        title_col.setContentsMargins(0, 0, 0, 0)
        app_title = QLabel("FSOC Coarse Alignment")
        app_title.setObjectName("appTitle")
        app_sub = QLabel("Virtual PAT Simulator — Closed-Loop Tracking")
        app_sub.setObjectName("appSubtitle")
        title_col.addWidget(app_title)
        title_col.addWidget(app_sub)
        hdr.addLayout(title_col)
        hdr.addStretch()
        self._hdr_mode_badge = QLabel("STANDBY")
        self._hdr_mode_badge.setObjectName("headerBadge")
        self._hdr_mode_badge.setAlignment(Qt.AlignCenter)
        hdr.addWidget(self._hdr_mode_badge)
        self._hdr_fov_badge = QLabel(f"FOV {self._fov_size[0]}x{self._fov_size[1]}")
        self._hdr_fov_badge.setObjectName("headerBadge")
        hdr.addWidget(self._hdr_fov_badge)
        self._hdr_world_badge = QLabel(f"WORLD {self._scene_size[0]}x{self._scene_size[1]}")
        self._hdr_world_badge.setObjectName("headerBadge")
        hdr.addWidget(self._hdr_world_badge)
        left_layout.addWidget(header_bar)

        # Videos — two premium camera cards
        video_container = QWidget()
        video_layout = QHBoxLayout(video_container)
        video_layout.setContentsMargins(0, 0, 0, 0)
        video_layout.setSpacing(10)
        video_splitter = QSplitter(Qt.Horizontal)
        video_splitter.setHandleWidth(6)
        video_splitter.setChildrenCollapsible(False)

        # Camera (monochrome) — 640x640 default, FOV 4x3 deg
        # Delegates to widgets.camera_card.create_camera_card for SRP (was nested _make_camera_card)
        fov_card, self.viewport_label, self.fov_res_lbl, self._fov_live_badge, self._fov_footer_info, self._fov_footer = create_camera_card("Camera", f"{self._fov_size[0]}x{self._fov_size[1]}", True)
        # God View — size = World (2000..5000 configurable per PDF)
        god_card, self.minimap_label, self.god_res_lbl, self._god_live_badge, self._god_footer_info, self._god_footer = create_camera_card("God View", "5000x5000", False)

        # Ensure res badges keep expected objectName for external styling
        self.fov_res_lbl.setObjectName("resBadge")
        self.god_res_lbl.setObjectName("resBadge")

        video_splitter.addWidget(fov_card)
        video_splitter.addWidget(god_card)
        video_splitter.setSizes([520, 520])
        video_splitter.setStretchFactor(0, 1)
        video_splitter.setStretchFactor(1, 1)

        video_layout.addWidget(video_splitter)
        left_layout.addWidget(video_container, 1)

        telemetry = QFrame()
        telemetry.setObjectName("telemetryStrip")
        telemetry.setFixedHeight(42)
        tlay = QHBoxLayout(telemetry)
        tlay.setContentsMargins(10, 6, 10, 6)
        tlay.setSpacing(10)
        dot_wrap = QHBoxLayout()
        dot_wrap.setSpacing(6)
        self.lock_dot = QLabel("")
        self.lock_dot.setFixedWidth(8)
        self.lock_dot.setStyleSheet("background: #9ca3af; border-radius: 4px;")
        dot_wrap.addWidget(self.lock_dot)
        self.footer_lock = QLabel("SEARCHING")
        self.footer_lock.setStyleSheet("font-weight:600; color:#374151; background:#f9fafb; border:1px solid #e5e7eb; border-radius:4px; padding:4px 10px; font-size:11px;")
        self.footer_lock.setMinimumWidth(110)
        self.footer_lock.setAlignment(Qt.AlignCenter)
        dot_wrap.addWidget(self.footer_lock)
        tlay.addLayout(dot_wrap)
        sep1 = QFrame()
        sep1.setFrameShape(QFrame.VLine)
        sep1.setStyleSheet("color:#e5e7eb;")
        sep1.setFixedWidth(1)
        tlay.addWidget(sep1)
        self.footer_fps = QLabel("FPS —")
        self.footer_fps.setObjectName("telemetryValue")
        self.footer_fps.setToolTip("Real-time render FPS")
        tlay.addWidget(self.footer_fps)
        self.footer_info = QLabel("Pan/Tilt —  Error —")
        self.footer_info.setObjectName("telemetryValue")
        self.footer_info.setToolTip("Current pan/tilt and tracking error")
        tlay.addWidget(self.footer_info, 1)
        hint_lbl = QLabel("No restart required")
        hint_lbl.setStyleSheet("color:#6b7280; font-size:10px; background:#f9fafb; border:1px solid #e5e7eb; border-radius:4px; padding:4px 8px;")
        tlay.addWidget(hint_lbl)
        left_layout.addWidget(telemetry)

        main_splitter.addWidget(left_panel)

        # ——— Right: Dashboard (metrics only, graph removed) — replaces command deck per consolidation
        self._build_dashboard_widget()
        right_scroll_dashboard = QScrollArea()
        right_scroll_dashboard.setWidgetResizable(True)
        right_scroll_dashboard.setWidget(self.dashboard_panel)
        right_scroll_dashboard.setMinimumWidth(420)
        right_scroll_dashboard.setMaximumWidth(520)
        right_scroll_dashboard.setStyleSheet("QScrollArea { border: none; background: #f9fafb; }")
        main_splitter.addWidget(right_scroll_dashboard)
        main_splitter.setSizes([920, 420])
        main_splitter.setStretchFactor(0, 1)
        main_splitter.setStretchFactor(1, 0)

        # ——— Detached: Command Deck — separate window (control deck detached per user request)
        self._build_control_panel_widget()
        # Host control deck in separate window (ControlDashboardWindow)
        try:
            self.control_deck_window = ControlDashboardWindow(self, self._control_widget)
            self.control_deck_window.show()
        except Exception:
            self.control_deck_window = None
        # Keep legacy alias for compat (old code used dashboard_window)
        try:
            self.dashboard_window = None
            class _DummyDashboardWindow:
                def __init__(self, panel): self.dashboard_panel = panel
                def show(self): pass
                def hide(self): pass
                def showMaximized(self): pass
                def update_live_status(self, s): pass
                def repaint(self): pass
            self.dashboard_window = _DummyDashboardWindow(self.dashboard_panel)
        except Exception:
            pass

        root.addWidget(main_splitter)

        self.control_window = None
        self.control_dock = None
        self.main_splitter = main_splitter
        self.video_splitter = video_splitter
        self.video_container = video_container
        # keep refs for programmatic updates
        self._fov_card = fov_card
        self._god_card = god_card
        self._telemetry_strip = telemetry
        # Dashboard-only consolidation: hide external metric strips/footers (all metrics now in DashboardPanel)
        # Telemetry strip and per-card footers previously duplicated dashboard metrics — hidden
        try:
            self._telemetry_strip.hide()
            self._fov_footer.hide()
            self._god_footer.hide()
            # Header badges duplicated lock/FOV/world — hidden; dashboard's Live System Pose is single source
            if hasattr(self, "_hdr_mode_badge"):
                self._hdr_mode_badge.hide()
            if hasattr(self, "_hdr_fov_badge"):
                self._hdr_fov_badge.hide()
            if hasattr(self, "_hdr_world_badge"):
                self._hdr_world_badge.hide()
            # Keep footer widgets exist for backward compat but not visible (tests still find them)
            self.footer_lock.hide()
            self.lock_dot.hide()
            self.footer_fps.hide()
            self.footer_info.hide()
            self._fov_footer_info.hide()
            self._god_footer_info.hide()
        except Exception:
            pass

        self._target_speed = 60
        self._det_thresh = 200
        self._ctrl_gain = 0.15
        # populate per-beacon dynamic panels now that beacons exist
        try:
            self._rebuild_per_beacon_panels()
        except Exception:
            pass
        # keep per-beacon X/Y ranges in sync with current world
        try:
            self._sync_per_beacon_xy_ranges()
        except Exception:
            pass

    def _build_dashboard_widget(self):
        """Build dashboard widget for MainWindow right side (metrics only, graph removed).
        Dashboard replaces command deck per consolidation; command deck detached to separate window.
        """
        self.dashboard_panel = DashboardPanel()
        self.stat_labels = self.dashboard_panel.stat_labels
        # Dashboard now lives in MainWindow right side; no separate window needed for it
        # Keep alias for backward compat
        self.dashboard_window = None

    def _build_control_panel_widget(self):
        """Build the entire control panel as a separate widget
        that will be hosted in the detached ControlDashboardWindow.
        Tabs: Global | Beacons | Camera | Control | Environment | Disturbances
        Dashboard is now in MainWindow, not here.
        """
        # Root container for control deck — premium header + pill tabs
        self._control_widget = QWidget()
        cw_layout = QVBoxLayout(self._control_widget)
        cw_layout.setContentsMargins(10, 10, 10, 10)
        cw_layout.setSpacing(10)

        # Control Deck header removed per user request

        tabs = QTabWidget()
        tabs.setDocumentMode(False)
        cw_layout.addWidget(tabs, 1)

        # ── Global Tab — Modular (GlobalPanel) ──
        self.global_panel = GlobalPanel()
        # Back-compat aliases — handlers expect these attrs on MainWindow
        self.motion_combo = self.global_panel.motion_combo
        self.speed_slider = self.global_panel.speed_slider
        self.thresh_slider = self.global_panel.thresh_slider
        self.start_btn = self.global_panel.start_btn
        self.pause_btn = self.global_panel.pause_btn
        self.reset_btn = self.global_panel.reset_btn
        self.export_btn = self.global_panel.export_btn
        # Wire global signals —
        self.global_panel.motionChanged.connect(self._on_motion_change)
        self.global_panel.speed_slider.valueChanged.connect(self._on_speed_change)
        self.global_panel.startRequested.connect(self._start)
        self.global_panel.pauseRequested.connect(self._pause)
        self.global_panel.resetRequested.connect(self._reset)
        self.global_panel.exportRequested.connect(self._export_log)
        self.global_panel.dashboardRequested.connect(self._show_dashboard_window)
        tabs.addTab(self.global_panel, "Global")

        # ── Beacons Tab — Simplified: only count, target, randomize motion ──
        beacons_tab = QWidget()
        beacons_layout_outer = QVBoxLayout(beacons_tab)
        beacons_layout_outer.setContentsMargins(8, 8, 8, 8)
        beacons_layout_outer.setSpacing(10)
        self.beacon_manager = MultiBeaconPanel(initial=self.beacon_config, world_bounds=self._scene_size)
        beacons_layout_outer.addWidget(self.beacon_manager)
        self.beacon_count_spin = self.beacon_manager.spin_beacon_count
        self.target_beacon_spin = self.beacon_manager.spin_target_index
        self.beacon_count_label = self.beacon_manager.lbl_status
        self.per_randomize_btn = self.beacon_manager.btn_randomize_all
        self.per_beacon_panels = []
        self.beacon_manager.multiConfigChanged.connect(self._on_multi_beacon_config_changed)
        self.beacon_manager.targetChanged.connect(self._on_target_beacon_change)
        self.beacon_manager.randomizeAllRequested.connect(self._randomize_all_beacons)
        self.beacon_manager.randomizeMotionRequested.connect(self._randomize_beacon_motion)
        try:
            self.beacon_manager.multiConfigChanged.connect(self._sync_beacon_to_global)
        except Exception: pass
        beacons_layout_outer.addStretch()
        tabs.addTab(beacons_tab, "Beacons")

        # ── Tuning Tab removed (beacon_tracker removed) ──
        self.tuning_panel = None
        self.thresh_spin = None
        self.detector_min_area_spin = None
        self.tracker_smoothing_spin = None
        self.tracker_miss_spin = None

        # ── Camera Tab — Modular (CameraPanel, 11 params) ──
        # 4 groups: A FOV/Optics, B Pan-Tilt Mechanics, C Display, D Units, E Gain
        self.camera_panel = CameraPanel(initial=self.camera_config, scene_bounds=self._scene_size)
        # Back-compat aliases — handlers and legacy code expect these attrs
        self.fov_w_spin = self.camera_panel.fov_w_spin
        self.fov_h_spin = self.camera_panel.fov_h_spin
        self.viewport_w_spin = self.camera_panel.viewport_w_spin
        self.viewport_h_spin = self.camera_panel.viewport_h_spin
        self.god_w_spin = self.camera_panel.god_w_spin
        self.god_h_spin = self.camera_panel.god_h_spin
        self.gain_slider = self.camera_panel.gain_slider
        self.gain_spin = self.camera_panel.gain_spin
        # New mechanics aliases for legacy access
        self.pan_min_spin = self.camera_panel.pan_min_spin
        self.pan_max_spin = self.camera_panel.pan_max_spin
        self.tilt_min_spin = self.camera_panel.tilt_min_spin
        self.tilt_max_spin = self.camera_panel.tilt_max_spin
        self.home_pan_spin = self.camera_panel.home_pan_spin
        self.home_tilt_spin = self.camera_panel.home_tilt_spin
        self.slew_spin = self.camera_panel.slew_spin
        self.pan_speed_deg_spin = getattr(self.camera_panel, 'pan_speed_deg_spin', self.slew_spin)
        self.tilt_speed_deg_spin = getattr(self.camera_panel, 'tilt_speed_deg_spin', self.slew_spin)
        self.update_rate_spin = getattr(self.camera_panel, 'update_rate_spin', None)
        self.res_spin = self.camera_panel.res_spin
        self.latency_spin = self.camera_panel.latency_spin
        self.scale_spin = self.camera_panel.scale_spin
        # NEW: realism aliases (now exposed, previously constants)
        self.accel_spin = getattr(self.camera_panel, 'accel_spin', None)
        self.backlash_spin = getattr(self.camera_panel, 'backlash_spin', None)
        self.encoder_spin = getattr(self.camera_panel, 'encoder_spin', None)
        self.latency_jitter_spin = getattr(self.camera_panel, 'latency_jitter_spin', None)
        self._cam_gain_box = None
        # wiring — debounced (single signal covers all 11 params + gain)
        self.camera_panel.configChanged.connect(lambda: self._schedule_auto("camera", self._apply_camera_hot, 420))
        tabs.addTab(self.camera_panel, "Camera")

        # ── Control Tab — Modular (P/PI/PID, dead zone, clamp, update rate) — upgraded with Setpoint Weight ──
        self.control_panel = ControlPanel(initial=self.controller_config)
        tabs.addTab(self.control_panel, "Control")
        # Back-compat aliases for new setpoint weight
        self.setpoint_spin = getattr(self.control_panel, 'setpoint_spin', None)
        self.control_kp_spin = getattr(self.control_panel, 'kp_spin', None)
        self.control_ki_spin = getattr(self.control_panel, 'ki_spin', None)
        self.control_kd_spin = getattr(self.control_panel, 'kd_spin', None)
        # wiring — controller tuning
        self.control_panel.configChanged.connect(self._on_control_config_changed)
        # Keep camera gain in sync with control Kp (bidirectional)
        self.control_panel.kp_spin.valueChanged.connect(lambda v: self._sync_control_gain_to_camera(v))
        self.camera_panel.gain_spin.valueChanged.connect(lambda v: self._sync_camera_gain_to_control(v))
        self.camera_panel.gain_slider.valueChanged.connect(lambda v: self._sync_camera_gain_to_control(v/100.0))

        # ── Environment Tab — Grouped, Modular (10 params) ──
        # Uses EnvironmentPanel (gui/environment_panel.py) — grouped into 5 sections
        # A) World  B) Seed  C) Atmosphere  D) Starfield  E) Dynamics
        # Immediate migration: self.env_config is single source of truth.
        env_tab = QWidget()
        env_layout = QVBoxLayout(env_tab)
        env_layout.setContentsMargins(8, 8, 8, 8)
        env_layout.setSpacing(10)
        # Create panel with current env_config (initialized in __init__)
        self.env_panel = EnvironmentPanel(initial=self.env_config)
        env_layout.addWidget(self.env_panel)
        # Back-compat aliases — legacy code (and tests) may reference these attrs directly
        # They now point into the panel's internal widgets.
        self.scene_w_spin = self.env_panel.scene_w_spin
        self.scene_h_spin = self.env_panel.scene_h_spin
        self.seed_spin = self.env_panel.seed_spin
        self.random_seed_btn = self.env_panel.random_seed_btn
        self.dynamic_check = getattr(self.env_panel, "dynamic_check", None)
        self.haze_spin = self.env_panel.haze_spin
        self.env_star_count_spin = self.env_panel.env_star_count_spin
        self.env_star_brightness_spin = self.env_panel.env_star_brightness_spin
        self.env_bg_top_spin = self.env_panel.env_bg_top_spin
        self.env_bg_bottom_spin = self.env_panel.env_bg_bottom_spin
        self.env_vignetting_spin = self.env_panel.env_vignetting_spin
        self.env_dynamic_speed_spin = getattr(self.env_panel, "env_dynamic_speed_spin", None)
        # Wire Randomize button
        self.env_panel.randomizeRequested.connect(self._randomize_seed)
        # Panel's configChanged is throttled — keep dirty tracking + auto-
        self.env_panel.configChanged.connect(lambda cfg: self._on_env_config_changed(cfg))
        # Also keep camera dirty when world size changes (affects FOV clamping)
        for w in [self.scene_w_spin, self.scene_h_spin]:
            try: w.valueChanged.connect(lambda _, s="camera": self._mark_dirty(s))
            except Exception: pass
        env_layout.addStretch()
        tabs.addTab(env_tab, "Environment")

        # ── Disturbances Tab — Modular (DisturbancesPanel, full spec) ──
        # Image Noise (S&P 10%, Gaussian, Poisson multi) + Max StdDev 20+User + Jitter ±20 + Atmosphere 4 presets + Platform 7 profiles
        try:
            from disturbance.config import DisturbanceConfig as _DC2
            init_dc = getattr(self, "disturbance_config", _DC2().validate())
        except Exception:
            init_dc = None
        self.disturbances_panel = DisturbancesPanel(initial=init_dc)
        self.sliders = self.disturbances_panel.sliders
        # Wire configChanged → disturbance dirty + auto (debounced)
        try:
            self.disturbances_panel.configChanged.connect(self._on_disturbance_config_changed)
        except Exception: pass
        tabs.addTab(self.disturbances_panel, "Disturbances")

        # initial snapshots for dirty tracking — then clear so deck starts clean (no dirty badge)
        for sec in ["global", "beacons", "camera", "control", "environment", "disturbances"]:
            try: self._snapshot_section(sec)
            except Exception: pass
        try:
            self._dirty_tabs.clear()
        except Exception:
            pass

        return

    def _show_control_panel(self):
        if hasattr(self, "control_window") and self.control_window:
            self.control_window.show()
            self.control_window.raise_()
            self.control_window.activateWindow()
        # New detached command deck window (control deck)
        if hasattr(self, "control_deck_window") and self.control_deck_window:
            try:
                self.control_deck_window.show()
                self.control_deck_window.raise_()
                self.control_deck_window.activateWindow()
            except Exception:
                pass

    def _show_control_deck_window(self):
        """Show the detached command deck (control panels) window."""
        if hasattr(self, "control_deck_window") and self.control_deck_window:
            try:
                self.control_deck_window.show()
                self.control_deck_window.raise_()
                self.control_deck_window.activateWindow()
            except Exception:
                pass
        elif hasattr(self, "_control_widget") and self._control_widget:
            # Fallback: show via old control_window
            self._show_control_panel()

    def _show_dashboard_window(self):
        # Dashboard now lives in MainWindow right side (graph removed) — just raise main
        try:
            self.show()
            self.raise_()
            self.activateWindow()
            if hasattr(self, "dashboard_panel"):
                self.dashboard_panel.show()
                self.dashboard_panel.raise_()
        except Exception:
            pass
        # Backward compat: if a real dashboard_window still exists, show it
        try:
            if hasattr(self, "dashboard_window") and hasattr(self.dashboard_window, "showMaximized"):
                # dummy does nothing; real window would show
                self.dashboard_window.showMaximized()
                self.dashboard_window.raise_()
                self.dashboard_window.activateWindow()
        except Exception:
            pass

    def _sync_per_beacon_xy_ranges(self):
        """Keep X/Y spin max in sync with current world size (dynamic) — modular."""
        w, h = self._scene_size
        # Manager handles world bounds for new panels
        if hasattr(self, "beacon_manager") and self.beacon_manager is not None:
            try:
                self.beacon_manager.set_world_bounds(self._scene_size)
                return
            except Exception: pass
        for panel in getattr(self, "per_beacon_panels", []):
            try:
                if isinstance(panel, dict):
                    panel["x"].setRange(0, w)
                    panel["y"].setRange(0, h)
                else:
                    panel.set_world_bounds(self._scene_size)
            except Exception: pass

    def _update_live_indicators(self):
        """Dashboard-only: all live metrics are in DashboardPanel; external header/footer badges hidden."""
        # Previously updated header mode/FOV/world and LIVE badges with metrics — now hidden
        # Keep method for compat but ensure external badges stay hidden (dashboard is single source)
        try:
            for attr in ["_hdr_mode_badge", "_hdr_fov_badge", "_hdr_world_badge", "_telemetry_strip", "_fov_footer", "_god_footer"]:
                w = getattr(self, attr, None)
                if w is not None:
                    try:
                        w.hide()
                    except Exception:
                        pass
            for badge in [getattr(self, "_fov_live_badge", None), getattr(self, "_god_live_badge", None)]:
                if badge is not None:
                    try:
                        badge.hide()
                    except Exception:
                        pass
        except Exception:
            pass



"""
Module: gui.main_window
Purpose: Main application window — orchestrates video, control panels, and simulation tick.
Architecture (modular refactor):
  - gui.styles          : APP_STYLE, SCENE_SIZE, FOV_SIZE, TICK_MS
  - gui.windows.control_window : ControlDashboardWindow
  - gui.panels.*        : Dashboard, Global, Camera, Disturbances, Environment, Beacons
  - gui.core.renderer   : Renderer (viewport/minimap drawing)
  - gui.mixins.state_mixin : dirty/HOT/snapshot handling
  - target/environment  : typed configs (immediate migration)
Public API: MainWindow
Notes: Thin orchestrator — delegates panel building, rendering, and simulation
       to modular helpers. Keeps ~2300-line monolith split into focused modules
       with structured section comments.
"""

import math
import random
import time

import cv2
import numpy as np
from PyQt5.QtCore import Qt, QTimer, QSize
from PyQt5.QtGui import QImage, QPixmap, QFont
from PyQt5.QtWidgets import (
    QCheckBox, QComboBox, QFileDialog, QGridLayout, QGroupBox, QHBoxLayout, QLabel,
    QMainWindow, QMessageBox, QPushButton, QSlider, QVBoxLayout, QWidget, QTabWidget,
    QSpinBox, QDoubleSpinBox, QScrollArea, QSplitter, QFrame, QSizePolicy, QStatusBar
)

from camera.ptz_camera import PTZCamera
from control.controller import ProportionalController
from detection.detector import BeaconDetector
from disturbance import disturbances as dist
from environment.config import EnvironmentConfig
from environment.constants import MAX_RES, MIN_RES
from environment.scene import Scene
from gui.beacon_panel import BeaconPanel
from gui.core.renderer import Renderer
from gui.environment_panel import EnvironmentPanel
from gui.mixins.state_mixin import StateMixin
from gui.multi_beacon_panel import MultiBeaconPanel
from gui.panels.camera_panel import CameraPanel
from gui.panels.dashboard_panel import DashboardPanel
from gui.panels.disturbances_panel import DisturbancesPanel
from gui.panels.global_panel import GlobalPanel
from gui.panels.overlay_panel import OverlayPanel
from gui.styles import APP_STYLE, FOV_SIZE, SCENE_SIZE, TICK_MS
from gui.windows.control_window import ControlDashboardWindow
from overlay.config import OverlayConfig
from overlay.renderer import PulseState
from perf_log.metrics import PerformanceLogger
from target.config import BeaconConfig, MultiBeaconConfig
from target.motion import MotionProfile, Target, create_beacons
from tracking.tracker import LockStatus, Tracker

class MainWindow(StateMixin, QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("FSOC Coarse Alignment Simulator")
        self.setMinimumSize(1150, 760)
        self.resize(1350, 860)
        self.setStyleSheet(APP_STYLE)

        self._camera_drift_state: dict = {}
        self._scene_size = SCENE_SIZE
        self._fov_size = FOV_SIZE
        self._viewport_display_size = (400, 300)
        self._god_display_size = (400, 300)
        # Beacon/Target — immediate migration: typed MultiBeaconConfig (8 per-beacon params + 3 multi)
        self.beacon_config = MultiBeaconConfig(
            beacon_count=1, target_index=0,
            beacons=[BeaconConfig(beacon_id=0, speed=60, brightness=255, radius=5, hitbox_radius=14, center_radius=2, profile="curved", position_seed=42)].copy()
        ).validate()
        # Legacy mirror attrs for back-compat fallback
        self._beacon_count = int(self.beacon_config.beacon_count)
        self._hitbox_radius = int(self.beacon_config.beacons[0].hitbox_radius)
        self._center_radius = int(self.beacon_config.beacons[0].center_radius)
        self._target_beacon_id = int(self.beacon_config.target_index)
        # Global tuning defaults — now fully configurable
        self._tracker_smoothing = 0.4
        self._tracker_miss_limit = 5
        self._detector_min_area = 2
        self._sim_speed = 1.0
        self._global_brightness = 255
        self._global_radius = 5
        # Environment — immediate migration: single typed config (replaces _env_* attrs)
        self.env_config = EnvironmentConfig().validate()
        self._scene_size = (int(self.env_config.world_width), int(self.env_config.world_height))
        # Camera — immediate migration: 11 params (FOV, mechanics, display, units)
        from camera.config import CameraConfig
        self.camera_config = CameraConfig(
            fov_width=self._fov_size[0], fov_height=self._fov_size[1],
            viewport_width=self._viewport_display_size[0], viewport_height=self._viewport_display_size[1],
            god_width=self._god_display_size[0], god_height=self._god_display_size[1],
        ).validate(self._scene_size)
        # Overlay — crosshair / lock / error (modular, intuitive)
        self.overlay_config = OverlayConfig().validate()
        self._overlay_pulse = PulseState()
        self._last_viewport_frame = None
        self._last_god_frame = None
        # Dirty tracking for HOT Apply per-section (now auto-HOT, but kept for Master confirm)
        self._dirty_tabs: set[str] = set()
        self._applied_snapshot: dict = {}
        # Debounced auto-HOT timers per section (so every single spin is HOT without spamming)
        self._auto_timers: dict[str, QTimer] = {}
        self._build_simulation()
        self._build_ui()

        self.timer = QTimer(self)
        self.timer.timeout.connect(self._tick)
        self._running = False
        self._last_tick_time = None
        self._last_rgb: np.ndarray | None = None
        self._pause_time = None

        # status bar
        sb = QStatusBar()
        sb.showMessage("Ready — configure scene/viewport (up to 5000×5000) then Start")
        self.setStatusBar(sb)

    # ---------- simulation setup ----------
    def _build_simulation(self):
        speed = getattr(self, "_target_speed", 100)
        thresh = getattr(self, "_det_thresh", 200)
        gain = getattr(self, "_ctrl_gain", 0.15)
        # Global tuning — use live widget values if available, else stored defaults
        try:
            smoothing = float(self.tracker_smoothing_spin.value()) if hasattr(self, "tracker_smoothing_spin") else float(getattr(self, "_tracker_smoothing", 0.4))  # type: ignore
        except:
            smoothing = float(getattr(self, "_tracker_smoothing", 0.4))
        try:
            miss_limit = int(self.tracker_miss_spin.value()) if hasattr(self, "tracker_miss_spin") else int(getattr(self, "_tracker_miss_limit", 5))  # type: ignore
        except:
            miss_limit = int(getattr(self, "_tracker_miss_limit", 5))
        try:
            min_area = int(self.detector_min_area_spin.value()) if hasattr(self, "detector_min_area_spin") else int(getattr(self, "_detector_min_area", 2))  # type: ignore
        except:
            min_area = int(getattr(self, "_detector_min_area", 2))
        try:
            sim_speed = float(self.sim_speed_spin.value()) if hasattr(self, "sim_speed_spin") else float(getattr(self, "_sim_speed", 1.0))  # type: ignore
        except:
            sim_speed = float(getattr(self, "_sim_speed", 1.0))
        try:
            g_bright = int(self.global_brightness_spin.value()) if hasattr(self, "global_brightness_spin") else int(getattr(self, "_global_brightness", 255))  # type: ignore
        except:
            g_bright = int(getattr(self, "_global_brightness", 255))
        try:
            g_radius = int(self.global_radius_spin.value()) if hasattr(self, "global_radius_spin") else int(getattr(self, "_global_radius", 5))  # type: ignore
        except:
            g_radius = int(getattr(self, "_global_radius", 5))
        try:
            profile = MotionProfile(self.motion_combo.currentText())  # type: ignore
        except Exception:
            profile = MotionProfile.CURVED
        # ----------------------------------------------------
        # Environment — collect validated config (panel if available, else env_config)
        # ----------------------------------------------------
        try:
            if hasattr(self, "env_panel") and self.env_panel is not None:
                cfg = self.env_panel.collect_config().validate()
                self.env_config = cfg
            else:
                cfg = self.env_config.validate()
        except Exception:
            cfg = self.env_config.validate()
        # Sync scene size from config (single source)
        scene_w, scene_h = int(cfg.world_width), int(cfg.world_height)
        self._scene_size = (scene_w, scene_h)

        # ----------------------------------------------------
        # Camera — collect validated CameraConfig (11 params: FOV, mechanics, display, units)
        # ----------------------------------------------------
        try:
            if hasattr(self, "camera_panel") and self.camera_panel is not None:
                cam_cfg = self.camera_panel.collect_config().validate((scene_w, scene_h))
                self.camera_config = cam_cfg
            else:
                cam_cfg = self.camera_config.validate((scene_w, scene_h))
        except Exception:
            cam_cfg = self.camera_config.validate((scene_w, scene_h))
        fov_w, fov_h = int(cam_cfg.fov_width), int(cam_cfg.fov_height)
        fov_w = min(fov_w, scene_w - 10)
        fov_h = min(fov_h, scene_h - 10)
        # Keep legacy _fov_size and display sizes in sync for renderer
        self._fov_size = (fov_w, fov_h)
        self._viewport_display_size = (int(cam_cfg.viewport_width), int(cam_cfg.viewport_height))
        self._god_display_size = (int(cam_cfg.god_width), int(cam_cfg.god_height))
        # Clamp FOV to scene and update config (handles FOV > scene case)
        cam_cfg.fov_width = int(fov_w); cam_cfg.fov_height = int(fov_h)
        self.camera_config = cam_cfg

        # Build scene via typed config (preferred) — keeps gradient/haze/star modularity
        self.scene = Scene(config=cfg)
        # ----------------------------------------------------
        # Multi-beacon — collect validated MultiBeaconConfig (8 per-beacon + 3 multi)
        # ----------------------------------------------------
        beacon_count = int(getattr(self, "_beacon_count", 1))
        hb = int(getattr(self, "_hitbox_radius", 14))
        cr = int(getattr(self, "_center_radius", 2))
        tgt_id = int(getattr(self, "_target_beacon_id", 0))
        # Prefer manager's live config if UI already built (immediate migration)
        try:
            if hasattr(self, "beacon_manager") and self.beacon_manager is not None:
                multi_cfg = self.beacon_manager.collect_multi_config().validate()
                self.beacon_config = multi_cfg
                beacon_count = int(multi_cfg.beacon_count)
                tgt_id = int(multi_cfg.target_index)
                # Use per-beacon configs for creation if available
                if multi_cfg.beacons and len(multi_cfg.beacons) == beacon_count:
                    # Keep global hb/cr for fallback but per-beacon will overlay
                    hb = int(multi_cfg.beacons[0].hitbox_radius)
                    cr = int(multi_cfg.beacons[0].center_radius)
            elif hasattr(self, "beacon_config"):
                multi_cfg = self.beacon_config.validate()
                beacon_count = int(multi_cfg.beacon_count)
                tgt_id = int(multi_cfg.target_index)
            else:
                multi_cfg = None
        except Exception:
            multi_cfg = None
        # Legacy fallback: spins (only before manager exists, e.g., first _build_simulation in __init__)
        try:
            # Only use spins if manager not yet created (first init)
            if not hasattr(self, "beacon_manager"):
                beacon_count = int(self.beacon_count_spin.value())  # type: ignore
                hb = int(self.hitbox_spin.value())  # type: ignore
                cr = int(self.center_spin.value())  # type: ignore
                tgt_id = int(self.target_beacon_spin.value())  # type: ignore
        except:
            pass
        # Offset seed per reset to vary placement but keep primary deterministic
        base_seed = int(cfg.seed) + int(self.perf.frame_count if hasattr(self, "perf") else 0) % 997 if 'cfg' in locals() else 42
        # Factory — respects global profile/speed but per-beacon overlay follows
        self.beacons: list[Target] = create_beacons(beacon_count, (scene_w, scene_h), profile, speed,
                                                     seed=base_seed, hitbox_radius=hb, center_radius=cr,
                                                     brightness=g_bright, radius=g_radius)
        # Overlay per-beacon configs (8 params) if available — HOT, preserves positions etc.
        try:
            if hasattr(self, "beacon_manager") and self.beacon_manager is not None:
                multi_cfg = self.beacon_manager.collect_multi_config().validate()
                for i, b_cfg in enumerate(multi_cfg.beacons):
                    if i < len(self.beacons):
                        try:
                            b_cfg.beacon_id = int(i)
                            b_cfg.apply_to_target(self.beacons[i])
                            # Position already clamped via apply_to_target
                        except Exception:
                            pass
                tgt_id = int(multi_cfg.target_index)
        except Exception:
            pass
        tgt_id = int(np.clip(int(tgt_id), 0, max(0, len(self.beacons)-1)))
        self._target_beacon_id = int(tgt_id)
        self._beacon_count = int(beacon_count)
        self._hitbox_radius = int(hb); self._center_radius = int(cr)
        # Sync beacon_config to reflect live beacons
        try:
            from target.config import BeaconConfig as _BC
            live_cfgs = [_BC.from_target(b).validate() for b in self.beacons]
            from target.config import MultiBeaconConfig as _MBC
            self.beacon_config = _MBC(beacon_count=len(self.beacons), target_index=int(tgt_id), beacons=live_cfgs).validate()
        except Exception:
            pass
        self.target = self.beacons[tgt_id] if self.beacons else self.beacons[0]
        # Keep hitbox sync (redundant after per-beacon apply, but ensures consistency)
        for b in self.beacons:
            try:
                if hasattr(self, "beacon_manager"):
                    continue
                b.set_hitbox(int(hb), int(cr))
            except: pass
        # Camera — full mechanics (slew, resolution, latency, ranges, home, optics)
        self.camera = PTZCamera(config=cam_cfg, scene_bounds=(scene_w, scene_h))
        self.detector = BeaconDetector(brightness_threshold=thresh, min_area=min_area)
        self.tracker = Tracker(smoothing=smoothing, miss_limit=miss_limit)
        self.controller = ProportionalController(gain=gain)
        # store sim speed for tick
        self._sim_speed = float(sim_speed)
        if not hasattr(self, "perf"):
            self.perf = PerformanceLogger()
        self._camera_drift_state = {}
        # stats for multi
        self._hitbox_hits = 0
        self._center_hits = 0
        self._frames_with_detections = 0

    # ---------- UI layout ----------
    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QHBoxLayout(central)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(12)

        # ——— Left: single separate dynamic & responsive video window (side-by-side) ———
        video_container = QFrame()
        video_container.setStyleSheet("QFrame { background: transparent; border: none; }")
        vc_layout = QVBoxLayout(video_container)
        vc_layout.setContentsMargins(0, 0, 0, 0)
        vc_layout.setSpacing(10)

        # Splitter horizontal — FOV + God's-eye side-by-side (responsive)
        splitter = QSplitter(Qt.Horizontal)
        splitter.setHandleWidth(6)
        splitter.setChildrenCollapsible(False)

        # FOV panel
        fov_frame = QFrame()
        fov_frame.setStyleSheet("QFrame { background: #ffffff; border: 1px solid #e2e8f0; border-radius: 10px; }")
        fov_layout = QVBoxLayout(fov_frame)
        fov_layout.setContentsMargins(10, 10, 10, 10)
        fov_layout.setSpacing(8)
        fov_hdr = QHBoxLayout()
        fov_hdr.setSpacing(8)
        fov_title = QLabel("▣ Camera FOV ")
        fov_title.setStyleSheet("color: #0f172a; font-weight: 600;")
        fov_hdr.addWidget(fov_title)
        self.fov_res_lbl = QLabel(f"{self._fov_size[0]}×{self._fov_size[1]}")
        self.fov_res_lbl.setStyleSheet("color:#64748b; font-size:10px; background:#f1f5f9; border:1px solid #e2e8f0; border-radius:4px; padding:2px 6px;")
        fov_hdr.addStretch(); fov_hdr.addWidget(self.fov_res_lbl)
        fov_layout.addLayout(fov_hdr)
        self.viewport_label = QLabel()
        self.viewport_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.viewport_label.setMinimumSize(320, 200)
        self.viewport_label.setAlignment(Qt.AlignCenter)
        self.viewport_label.setStyleSheet("background: #06080c; border: 1px solid #334155; border-radius: 8px;")
        self.viewport_label.setScaledContents(False)
        fov_layout.addWidget(self.viewport_label, 1)
        splitter.addWidget(fov_frame)

        # God's-eye panel
        god_frame = QFrame()
        god_frame.setStyleSheet("QFrame { background: #ffffff; border: 1px solid #e2e8f0; border-radius: 10px; }")
        god_layout = QVBoxLayout(god_frame)
        god_layout.setContentsMargins(10, 10, 10, 10)
        god_layout.setSpacing(8)
        god_hdr = QHBoxLayout()
        god_hdr.setSpacing(8)
        god_title = QLabel("◉ God's-Eye")
        god_title.setStyleSheet("color: #0f172a; font-weight: 600;")
        god_hdr.addWidget(god_title)
        self.god_res_lbl = QLabel(f"{self._scene_size[0]}×{self._scene_size[1]}")
        self.god_res_lbl.setStyleSheet("color:#64748b; font-size:10px; background:#f1f5f9; border:1px solid #e2e8f0; border-radius:4px; padding:2px 6px;")
        god_hdr.addStretch(); god_hdr.addWidget(self.god_res_lbl)
        god_layout.addLayout(god_hdr)
        self.minimap_label = QLabel()
        self.minimap_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.minimap_label.setMinimumSize(320, 200)
        self.minimap_label.setAlignment(Qt.AlignCenter)
        self.minimap_label.setStyleSheet("background: #06080c; border: 1px solid #334155; border-radius: 8px;")
        god_layout.addWidget(self.minimap_label, 1)
        splitter.addWidget(god_frame)

        splitter.setSizes([520, 520])
        vc_layout.addWidget(splitter, 1)

        # Footer stats inside video window for at-a-glance
        footer = QHBoxLayout()
        footer.setSpacing(8)
        footer.setContentsMargins(4, 6, 4, 2)
        self.lock_dot = QLabel("●")
        self.lock_dot.setStyleSheet("color: #64748b; font-size: 14px;")
        footer.addWidget(self.lock_dot)
        self.footer_lock = QLabel("SEARCHING")
        self.footer_lock.setStyleSheet("color: #475569; font-weight:700; font-size:11px;")
        footer.addWidget(self.footer_lock)
        footer.addSpacing(16)
        self.footer_fps = QLabel("FPS —")
        self.footer_fps.setStyleSheet("color:#475569; background:#f1f5f9; border:1px solid #e2e8f0; border-radius:6px; padding:4px 8px;")
        footer.addWidget(self.footer_fps)
        footer.addStretch()
        self.footer_info = QLabel("Pan/Tilt —  •  Error —")
        self.footer_info.setStyleSheet("color:#64748b; font-size:10px; background:#f8fafc; border:1px solid #e2e8f0; border-radius:6px; padding:4px 8px;")
        footer.addWidget(self.footer_info)
        vc_layout.addLayout(footer)

        # Keep reference
        self.video_splitter = splitter
        self.video_container = video_container

        # Build Control Panel + Live Dashboard as separate window (distinguished sections)
        # We build the right-side content as a standalone widget that will be hosted
        # in ControlDashboardWindow. All groups are clearly distinguished with icons/tabs.
        self._build_control_panel_widget()

        # Assemble root — Main Window is now VIDEO ONLY (controls live in separate window)
        # Keep a top bar with button to open controls
        top_bar = QHBoxLayout()
        top_bar.setSpacing(8)
        open_ctrl_btn = QPushButton("Open Control Panel")
        open_ctrl_btn.setMinimumHeight(30)
        open_ctrl_btn.setStyleSheet("background:#2563eb; color:white; font-weight:700; border:none; border-radius:8px; padding:6px 12px;")
        open_ctrl_btn.clicked.connect(self._show_control_panel)
        top_bar.addWidget(open_ctrl_btn)
        top_bar.addStretch()
        vc_layout.insertLayout(0, top_bar)

        root.addWidget(video_container, 1)

        # Create and show separate control window
        self.control_window = ControlDashboardWindow(self, self._control_widget)
        self.control_window.show()

        # keep old attribute for compatibility (some code expects self.stat_labels etc. still on MainWindow — they are, because widget was built with MainWindow as logical owner)
        self.main_splitter = None

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

    def _build_control_panel_widget(self):
        """Build the entire control panel + live dashboard as a single widget
        that will be hosted in the separate ControlDashboardWindow.
        Groups are clearly distinguished with icon headers and a QTabWidget:
        Dashboard | Global | Beacons | Camera | Environment | Disturbances
        """
        # Root container for control window
        self._control_widget = QWidget()
        cw_layout = QVBoxLayout(self._control_widget)
        cw_layout.setContentsMargins(10, 10, 10, 10)
        cw_layout.setSpacing(10)

        # Title
        title = QLabel("Control Panel")
        title.setStyleSheet("color:#0f172a; font-weight:800; font-size:13px; padding:6px; background:#eff6ff; border:1px solid #dbeafe; border-radius:8px;")
        title.setAlignment(Qt.AlignCenter)
        cw_layout.addWidget(title)

        hint = QLabel("All changes are HOT reloaded.")
        hint.setWordWrap(True); hint.setStyleSheet("color:#64748b; font-size:10px; font-style:italic; background:#f1f5f9; border:1px solid #e2e8f0; border-radius:6px; padding:4px;")
        cw_layout.addWidget(hint)

        tabs = QTabWidget()
        tabs.setStyleSheet("QTabWidget::pane { border: 1px solid #e2e8f0; border-radius: 8px; background: white; }")
        cw_layout.addWidget(tabs, 1)

        # ── Dashboard Tab — Modular (DashboardPanel) ──
        self.dashboard_panel = DashboardPanel()
        self.stat_labels = self.dashboard_panel.stat_labels
        tabs.addTab(self.dashboard_panel, "Dashboard")

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
        # Wire global signals — HOT
        self.global_panel.motionChanged.connect(self._on_motion_change)
        self.global_panel.speed_slider.valueChanged.connect(self._on_speed_change)
        self.global_panel.thresh_slider.valueChanged.connect(self._on_thresh_change)
        self.global_panel.startRequested.connect(self._start)
        self.global_panel.pauseRequested.connect(self._pause)
        self.global_panel.resetRequested.connect(self._reset)
        self.global_panel.exportRequested.connect(self._export_log)
        tabs.addTab(self.global_panel, "Global")

        # ── Beacons Tab — Modular (8 per-beacon + 3 multi) ──
        # Uses MultiBeaconPanel (gui/multi_beacon_panel.py) which owns BeaconPanel per beacon.
        # Immediate migration: self.beacon_config: MultiBeaconConfig is single source.
        beacons_tab = QWidget()
        beacons_layout_outer = QVBoxLayout(beacons_tab)
        beacons_layout_outer.setContentsMargins(8, 8, 8, 8)
        beacons_layout_outer.setSpacing(10)
        # Create manager with current beacon_config + world bounds
        self.beacon_manager = MultiBeaconPanel(initial=self.beacon_config, world_bounds=self._scene_size)
        beacons_layout_outer.addWidget(self.beacon_manager)
        # Back-compat aliases — legacy code (and external tests) may reference these attrs
        # They now proxy into the manager's internal widgets.
        self.beacon_count_spin = self.beacon_manager.spin_beacon_count
        self.target_beacon_spin = self.beacon_manager.spin_target_index
        # Hitbox/center global proxies — map to first beacon's hitbox/center for legacy reads
        # Provide dummy spins that sync to first beacon if legacy code writes to them.
        # We expose read-through properties via helper methods, but alias to first panel for now.
        # After manager is built, panels exist — alias hitbox/center to first panel's spins.
        try:
            first_panel = self.beacon_manager.get_per_beacon_panels()[0] if self.beacon_manager.get_per_beacon_panels() else None
            if first_panel:
                self.hitbox_spin = first_panel.spin_hitbox
                self.center_spin = first_panel.spin_center
            else:
                self.hitbox_spin = QSpinBox(); self.hitbox_spin.setRange(3,80); self.hitbox_spin.setValue(self._hitbox_radius)
                self.center_spin = QSpinBox(); self.center_spin.setRange(1,10); self.center_spin.setValue(self._center_radius)
        except Exception:
            self.hitbox_spin = QSpinBox(); self.hitbox_spin.setRange(3,80); self.hitbox_spin.setValue(self._hitbox_radius)
            self.center_spin = QSpinBox(); self.center_spin.setRange(1,10); self.center_spin.setValue(self._center_radius)
        # Additional aliases for legacy per-beacon container access
        self.per_beacon_scroll = self.beacon_manager.scroll
        self.per_beacon_container = self.beacon_manager.container
        self.per_beacon_layout = self.beacon_manager.container_layout
        # per_beacon_panels was list[dict] legacy — now expose as list[BeaconPanel] via property
        # Keep legacy list for handlers that expect dicts: create shim that maps BeaconPanel
        self.per_beacon_panels = self.beacon_manager.get_per_beacon_panels()  # type: ignore
        self.beacon_count_label = self.beacon_manager.lbl_status
        self.per_randomize_btn = self.beacon_manager.btn_randomize_all
        self.per_beacon_box = self.beacon_manager.per_beacon_box
        # Wire manager signals — HOT, immediate
        self.beacon_manager.multiConfigChanged.connect(self._on_multi_beacon_config_changed)
        self.beacon_manager.targetChanged.connect(self._on_target_beacon_change)
        self.beacon_manager.randomizeAllRequested.connect(self._randomize_all_beacons)
        self.beacon_manager.randomizePositionRequested.connect(self._randomize_single_beacon_pos)
        # Also handle per-panel randomize position via manager forwarding
        beacons_layout_outer.addStretch()
        tabs.addTab(beacons_tab, "Beacons")

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
        self.res_spin = self.camera_panel.res_spin
        self.latency_spin = self.camera_panel.latency_spin
        self.scale_spin = self.camera_panel.scale_spin
        self._cam_gain_box = None
        # HOT wiring — debounced (single signal covers all 11 params + gain)
        self.camera_panel.configChanged.connect(lambda: self._schedule_auto("camera", self._apply_camera_hot, 420))
        tabs.addTab(self.camera_panel, "Camera")

        # ── Overlay Tab — Modular (Crosshair / Lock / Error) ──
        self.overlay_panel = OverlayPanel(initial=self.overlay_config)
        tabs.addTab(self.overlay_panel, "Overlay")
        # HOT wiring
        self.overlay_panel.configChanged.connect(self._on_overlay_config_changed)

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
        self.dynamic_check = self.env_panel.dynamic_check
        self.haze_spin = self.env_panel.haze_spin
        self.env_star_count_spin = self.env_panel.env_star_count_spin
        self.env_star_brightness_spin = self.env_panel.env_star_brightness_spin
        self.env_bg_top_spin = self.env_panel.env_bg_top_spin
        self.env_bg_bottom_spin = self.env_panel.env_bg_bottom_spin
        self.env_vignetting_spin = self.env_panel.env_vignetting_spin
        self.env_dynamic_speed_spin = self.env_panel.env_dynamic_speed_spin
        # Wire Randomize button
        self.env_panel.randomizeRequested.connect(self._randomize_seed)
        # Panel's configChanged is throttled HOT — keep dirty tracking + auto-HOT
        self.env_panel.configChanged.connect(lambda cfg: self._on_env_config_changed(cfg))
        # Also keep camera dirty when world size changes (affects FOV clamping)
        for w in [self.scene_w_spin, self.scene_h_spin]:
            try: w.valueChanged.connect(lambda _, s="camera": self._mark_dirty(s))
            except: pass
        env_layout.addStretch()
        tabs.addTab(env_tab, "Environment")

        # ── Disturbances Tab — Modular (DisturbancesPanel) ──
        self.disturbances_panel = DisturbancesPanel()
        self.sliders = self.disturbances_panel.sliders
        tabs.addTab(self.disturbances_panel, "Disturbances")

        # initial snapshots for dirty tracking (HOT) — includes overlay
        for sec in ["global", "beacons", "camera", "overlay", "environment", "disturbances"]:
            try: self._snapshot_section(sec)
            except: pass

        return

    def _show_control_panel(self):
        if hasattr(self, "control_window") and self.control_window:
            self.control_window.show()
            self.control_window.raise_()
            self.control_window.activateWindow()

    def _sync_per_beacon_xy_ranges(self):
        """Keep X/Y spin max in sync with current world size (dynamic) — modular."""
        w, h = self._scene_size
        # Manager handles world bounds for new panels
        if hasattr(self, "beacon_manager") and self.beacon_manager is not None:
            try:
                self.beacon_manager.set_world_bounds(self._scene_size)
                return
            except: pass
        for panel in getattr(self, "per_beacon_panels", []):
            try:
                if isinstance(panel, dict):
                    panel["x"].setRange(0, w)
                    panel["y"].setRange(0, h)
                else:
                    panel.set_world_bounds(self._scene_size)
            except: pass

    def _add_slider_row(self, layout, label, vmin, vmax, vinit, callback, key):
        # Deprecated — GlobalPanel now owns slider rows (modular). Kept for backward compat.
        lab = QLabel(label)
        lab.setStyleSheet("color:#334155; font-weight:500;")
        layout.addWidget(lab)
        h = QHBoxLayout()
        h.setSpacing(8)
        slider = QSlider(Qt.Horizontal); slider.setRange(vmin, vmax); slider.setValue(vinit)
        slider.setTickPosition(QSlider.TicksBelow); slider.setTickInterval(max(1, (vmax-vmin)//5))
        slider.setMinimumHeight(18)
        val = QLabel(str(vinit)); val.setFixedWidth(36); val.setAlignment(Qt.AlignCenter)
        val.setStyleSheet("color:#2563eb; font-weight:700; background:#eff6ff; border:1px solid #dbeafe; border-radius:6px; padding:2px;")
        slider.valueChanged.connect(lambda v, l=val: l.setText(str(v)))
        slider.valueChanged.connect(callback)
        h.addWidget(slider, 1); h.addWidget(val)
        layout.addLayout(h)
        if key == "Speed": self.speed_slider = slider
        elif key == "Threshold": self.thresh_slider = slider

    def _add_gain_row(self, layout):
        # Deprecated — CameraPanel now owns gain row. Kept for backward compat.
        lab = QLabel("Controller gain")
        lab.setStyleSheet("color:#334155; font-weight:500;")
        layout.addWidget(lab)
        row = QHBoxLayout()
        row.setSpacing(8)
        self.gain_slider = QSlider(Qt.Horizontal); self.gain_slider.setRange(2, 50); self.gain_slider.setValue(15); self.gain_slider.valueChanged.connect(self._on_gain_change_slider)
        self.gain_slider.setMinimumHeight(18)
        self.gain_spin = QDoubleSpinBox(); self.gain_spin.setRange(0.02, 0.50); self.gain_spin.setSingleStep(0.01); self.gain_spin.setValue(0.15); self.gain_spin.setDecimals(2); self.gain_spin.setMinimumHeight(26); self.gain_spin.setFixedWidth(78)
        self.gain_spin.valueChanged.connect(self._on_gain_change_spin)
        row.addWidget(self.gain_slider, 1); row.addWidget(self.gain_spin)
        layout.addLayout(row)

    # ---------- handlers ----------
    def _on_motion_change(self, value: str):
        try:
            prof = MotionProfile(value)
            # Apply to primary always; if multiple beacons, optionally apply to all for uniform test
            # Keep varied beacons realistic: only primary follows combo, others keep their random profiles
            # Uncomment next two lines to force all:
            # for b in getattr(self, "beacons", []):
            #     b.profile = prof
            self.target.profile = prof
        except: pass

    def _on_speed_change(self, value: int):
        self._target_speed = int(value)
        if hasattr(self, "target"): self.target.speed = float(value)
        for b in getattr(self, "beacons", []):
            # keep relative speed ratios but scale primary exactly
            if b is getattr(self, "target", None):
                b.speed = float(value)
            else:
                # scale proportionally to keep diversity
                b.speed = float(np.clip(float(value) * (0.85 + 0.30*(b.beacon_id % 3)/2), 12, 180))

    def _on_thresh_change(self, value: int):
        self._det_thresh = int(value)
        if hasattr(self, "detector"): self.detector.brightness_threshold = int(value)

    def _on_tracker_smoothing_change(self, value: float):
        self._tracker_smoothing = float(value)
        if hasattr(self, "tracker"): self.tracker.smoothing = float(value)

    def _on_tracker_miss_change(self, value: int):
        self._tracker_miss_limit = int(value)
        if hasattr(self, "tracker"): self.tracker.miss_limit = int(value)

    def _on_detector_min_area_change(self, value: int):
        self._detector_min_area = int(value)
        if hasattr(self, "detector"): self.detector.min_area = int(value)

    def _on_sim_speed_change(self, value: float):
        self._sim_speed = float(value)
        # dt is scaled in _tick by sim_speed

    def _on_global_brightness_change(self, value: int):
        self._global_brightness = int(value)
        for b in getattr(self, "beacons", []):
            b.brightness = int(value)
            b.current_brightness = float(value)

    def _on_global_radius_change(self, value: int):
        self._global_radius = int(value)
        for b in getattr(self, "beacons", []):
            b.radius = int(value)

    def _apply_global_tuning(self):
        # Recreate tracker/detector with new params (live values already applied, this ensures fresh state)
        try:
            smoothing = float(self.tracker_smoothing_spin.value())
            miss = int(self.tracker_miss_spin.value())
            min_area = int(self.detector_min_area_spin.value())
            thresh = int(self.thresh_slider.value()) if hasattr(self, "thresh_slider") else int(self._det_thresh)
            self._tracker_smoothing = smoothing; self._tracker_miss_limit = miss
            self._detector_min_area = min_area
            self.tracker = Tracker(smoothing=smoothing, miss_limit=miss)
            self.detector = BeaconDetector(brightness_threshold=thresh, min_area=min_area)
            self.statusBar().showMessage(f"Global tuning applied — tracker smooth {smoothing:.2f} miss {miss} minArea {min_area}", 3000)
        except Exception as e:
            QMessageBox.warning(self, "Global Tuning", f"Failed: {e}")

    def _on_gain_change_spin(self, value: float):
        self._ctrl_gain = float(value)
        if hasattr(self, "controller"): self.controller.gain = float(value)
        iv = int(round(value*100))
        if self.gain_slider.value() != iv:
            self.gain_slider.blockSignals(True); self.gain_slider.setValue(iv); self.gain_slider.blockSignals(False)

    def _on_gain_change_slider(self, value: int):
        f = value/100.0
        if abs(self.gain_spin.value()-f) > 1e-9:
            self.gain_spin.blockSignals(True); self.gain_spin.setValue(f); self.gain_spin.blockSignals(False)
        self._ctrl_gain = f
        if hasattr(self, "controller"): self.controller.gain = f
    def _randomize_seed(self): self.seed_spin.setValue(random.randint(0, 999999))

    def _on_env_config_changed(self, cfg):
        """Immediate HOT handler — panel emitted a validated EnvironmentConfig."""
        try:
            cfg = cfg.validate()
            self.env_config = cfg
            self._scene_size = (int(cfg.world_width), int(cfg.world_height))
        except Exception:
            pass
        self._mark_dirty("environment")
        # Debounced HOT apply (520ms) — every single spin is HOT without spamming
        self._schedule_auto("environment", self._apply_scene_settings_hot, 520)

    def _on_overlay_config_changed(self, cfg):
        """HOT handler — OverlayPanel emitted validated OverlayConfig."""
        try:
            cfg = cfg.validate()
            self.overlay_config = cfg
        except Exception:
            pass
        self._mark_dirty("overlay")
        # Overlay is pure rendering — no heavy rebuild, instant next tick
        self._schedule_auto("overlay", self._apply_overlay_hot, 80)

    def _apply_overlay_hot(self):
        """Apply overlay config — lightweight, just clear dirty and snapshot."""
        try:
            # Already stored in self.overlay_config via _on_overlay_config_changed
            # Re-collect to ensure panel and config in sync (handles color pickers)
            if hasattr(self, "overlay_panel"):
                cfg = self.overlay_panel.collect_config().validate()
                self.overlay_config = cfg
            self._clear_dirty("overlay")
            self._snapshot_section("overlay")
            self.statusBar().showMessage(f"Overlay HOT — {self.overlay_config.crosshair_style} gap {self.overlay_config.crosshair_gap} lock {self.overlay_config.lock_circle_radius} {self.overlay_config.error_units}", 2000)
        except Exception as e:
            QMessageBox.warning(self, "Overlay", f"Failed: {e}")

    def _update_beacon_count_label(self, v: int):
        try:
            tgt = int(getattr(self, "target_beacon_spin", self).value()) if hasattr(self, "target_beacon_spin") else int(getattr(self, "_target_beacon_id", 0))
            self.beacon_count_label.setText(f"{v} beacon{'s' if v!=1 else ''}  •  Target #{tgt}  •  hitbox {self.hitbox_spin.value()}px  center {self.center_spin.value()}px")
        except:
            try: self.beacon_count_label.setText(f"{v} beacon{'s' if v!=1 else ''}  •  hitbox {self.hitbox_spin.value()}px  center {self.center_spin.value()}px")
            except: pass

    def _on_hitbox_change(self, _v=None):
        # live update hitbox/center radii for all beacons without full rebuild
        try:
            hb = int(self.hitbox_spin.value())
            cr = int(self.center_spin.value())
            self._hitbox_radius = hb; self._center_radius = cr
            for b in getattr(self, "beacons", []):
                b.set_hitbox(hb, cr)
            self._update_beacon_count_label(int(self.beacon_count_spin.value()))
            # keep target spin max in sync
            try:
                self.target_beacon_spin.setMaximum(max(0, int(self.beacon_count_spin.value()) - 1))
                if self.target_beacon_spin.value() >= int(self.beacon_count_spin.value()):
                    self.target_beacon_spin.setValue(int(self.beacon_count_spin.value()) - 1)
            except: pass
        except: pass

    def _on_beacon_count_changed(self, v: int):
        try:
            self.target_beacon_spin.setMaximum(max(0, v - 1))
            if self.target_beacon_spin.value() >= v:
                self.target_beacon_spin.setValue(v - 1)
            self._update_beacon_count_label(v)
        except: pass

    def _on_target_beacon_change(self, idx: int):
        """Target index changed — update tracked beacon + highlight panels (modular)."""
        try:
            idx = int(np.clip(int(idx), 0, max(0, len(getattr(self, "beacons", [])) - 1)))
            self._target_beacon_id = idx
            # Keep beacon_config in sync (immediate migration)
            try:
                self.beacon_config.target_index = int(idx)
                if hasattr(self, "beacon_manager"):
                    self.beacon_manager.spin_target_index.blockSignals(True)
                    self.beacon_manager.spin_target_index.setValue(int(idx))
                    self.beacon_manager.spin_target_index.blockSignals(False)
            except Exception:
                pass
            if hasattr(self, "beacons") and 0 <= idx < len(self.beacons):
                self.target = self.beacons[idx]
                # Highlight per-beacon panels — supports both legacy dict and new BeaconPanel
                for i, panel in enumerate(getattr(self, "per_beacon_panels", [])):
                    try:
                        is_tgt = (i == idx)
                        if isinstance(panel, dict):
                            panel["box"].setStyleSheet(
                                "QGroupBox { background: %s; border: 1px solid %s; border-radius: 8px; margin-top: 8px; padding-top: 8px; } QGroupBox::title { color: %s; font-size:10px; font-weight:%s; }"
                                % ("#eff6ff" if is_tgt else "#f8fafc", "#2563eb" if is_tgt else "#e2e8f0", "#1d4ed8" if is_tgt else "#0f172a", "700" if is_tgt else "600")
                            )
                            b = self.beacons[i]
                            panel["box"].setTitle(f"Beacon #{b.beacon_id} {'★ TARGET' if is_tgt else '— ON' if b.enabled else '— OFF'}")
                        else:
                            # New BeaconPanel object
                            try:
                                panel.set_target_highlight(is_tgt)
                                b = self.beacons[i]
                                suffix = " ★ TARGET" if is_tgt else (" — OFF" if not b.enabled else " — ON")
                                panel.setTitle(f"Beacon #{b.beacon_id}{suffix}")
                            except Exception:
                                pass
                    except Exception:
                        pass
                # Also delegate to manager if it has highlight helper
                try:
                    if hasattr(self, "beacon_manager") and hasattr(self.beacon_manager, "_update_target_highlight"):
                        self.beacon_manager._update_target_highlight()
                except Exception:
                    pass
                try: self.tracker = Tracker(smoothing=0.4, miss_limit=5)
                except: pass
                self.statusBar().showMessage(f"Target → Beacon #{idx}", 2500)
                # Update status label via manager or legacy
                try:
                    if hasattr(self, "beacon_manager"):
                        self.beacon_manager._update_status()
                    else:
                        self._update_beacon_count_label(int(self.beacon_count_spin.value()))
                except Exception:
                    pass
        except: pass

    def _on_multi_beacon_config_changed(self, cfg):
        """
        HOT handler for MultiBeaconPanel — 8 per-beacon + 3 multi params.

        - If beacon_count changed → schedule rebuild via _apply_beacons_hot (debounced)
        - Else per-beacon fields (profile/speed/brightness/radius/hitbox/center/heading/seed/x/y/enabled)
          are hot-applied directly onto live Target objects via BeaconConfig.apply_to_target.
        """
        try:
            # Validate and store as single source
            try:
                cfg = cfg.validate() if hasattr(cfg, "validate") else cfg
            except Exception:
                pass
            self.beacon_config = cfg
            self._beacon_count = int(cfg.beacon_count)
            self._target_beacon_id = int(cfg.target_index)
            # Mirror legacy attrs for snapshot/dirty
            try:
                if cfg.beacons:
                    self._hitbox_radius = int(cfg.beacons[0].hitbox_radius)
                    self._center_radius = int(cfg.beacons[0].center_radius)
            except Exception:
                pass
            self._mark_dirty("beacons")
            # If count differs from live beacons, need factory rebuild (debounced)
            live_n = len(getattr(self, "beacons", []))
            if live_n != int(cfg.beacon_count):
                self._schedule_auto("beacons", self._apply_beacons_hot, 500)
            else:
                # Per-beacon hot-apply without rebuild — immediate, no pause
                self._schedule_auto("beacons", self._apply_beacon_configs_hot, 120)
                # Also schedule a quick highlight refresh
                try:
                    self._schedule_auto("beacons_highlight", lambda: self._on_target_beacon_change(int(cfg.target_index)), 80)
                except Exception:
                    pass
        except Exception as e:
            # Fallback to full rebuild
            try:
                self._schedule_auto("beacons", self._apply_beacons_hot, 500)
            except: pass

    def _apply_beacon_configs_hot(self):
        """HOT per-beacon apply — no factory rebuild, just BeaconConfig → Target."""
        try:
            cfg = self.beacon_manager.collect_multi_config().validate() if hasattr(self, "beacon_manager") else self.beacon_config.validate()
            self.beacon_config = cfg
            # Ensure per_beacon_panels alias stays in sync with manager
            try:
                self.per_beacon_panels = self.beacon_manager.get_per_beacon_panels()  # type: ignore
            except Exception:
                pass
            # Apply each BeaconConfig onto live Target (preserves velocity, t, etc.)
            for i, beacon_cfg in enumerate(cfg.beacons):
                if i < len(getattr(self, "beacons", [])):
                    try:
                        beacon_cfg.apply_to_target(self.beacons[i])
                    except Exception:
                        # Fallback: direct field copy
                        try:
                            t = self.beacons[i]
                            t.enabled = bool(beacon_cfg.enabled)
                            t.brightness = int(beacon_cfg.brightness)
                            t.radius = int(beacon_cfg.radius)
                            t.hitbox_radius = int(beacon_cfg.hitbox_radius)
                            t.center_radius = int(beacon_cfg.center_radius)
                            t.speed = float(beacon_cfg.speed)
                        except: pass
                    # Sync X/Y and heading for immediate visual (position seed already handled via apply)
                    try:
                        # World bounds clamp for X/Y
                        w, h = self._scene_size
                        self.beacons[i].x = float(max(0, min(beacon_cfg.x, w)))
                        self.beacons[i].y = float(max(0, min(beacon_cfg.y, h)))
                    except: pass
            # Update target alias
            tid = int(np.clip(int(cfg.target_index), 0, max(0, len(self.beacons)-1)))
            self._target_beacon_id = tid
            if 0 <= tid < len(getattr(self, "beacons", [])):
                self.target = self.beacons[tid]
            self._clear_dirty("beacons")
            self._snapshot_section("beacons")
        except Exception as e:
            # On failure, fallback to factory
            try: self._apply_beacons_hot()
            except: pass

    def _apply_beacons(self):
        # Modular path via manager (8 per-beacon + 3 multi) if available
        if hasattr(self, "beacon_manager") and self.beacon_manager is not None:
            try:
                multi_cfg = self.beacon_manager.collect_multi_config().validate()
                self.beacon_config = multi_cfg
                was_running = getattr(self, "_running", False)
                if was_running: self._pause()
                # Rebuild via factory then overlay per-beacon configs
                try: profile = MotionProfile(self.motion_combo.currentText())
                except: profile = self.target.profile if hasattr(self, "target") else MotionProfile.CURVED
                speed = float(getattr(self, "_target_speed", 60))
                scene_w, scene_h = self._scene_size
                seed = int(self.seed_spin.value()) + int(time.time()) % 1000 if hasattr(self, "seed_spin") else int(multi_cfg.beacons[0].position_seed) if multi_cfg.beacons else 42
                self.beacons = create_beacons(int(multi_cfg.beacon_count), (scene_w, scene_h), profile, speed,
                                               seed=seed, hitbox_radius=int(multi_cfg.beacons[0].hitbox_radius) if multi_cfg.beacons else 14, center_radius=int(multi_cfg.beacons[0].center_radius) if multi_cfg.beacons else 2)
                for i, b_cfg in enumerate(multi_cfg.beacons):
                    if i < len(self.beacons):
                        try: b_cfg.apply_to_target(self.beacons[i])
                        except: pass
                tid = int(np.clip(int(multi_cfg.target_index), 0, max(0, len(self.beacons)-1)))
                self._target_beacon_id = tid; self._beacon_count = int(multi_cfg.beacon_count)
                self.target = self.beacons[tid] if self.beacons else self.beacons[0]
                self.statusBar().showMessage(f"Beacons: {self._beacon_count}  Target #{tid} (manager, 8 params)", 3000)
                try: self.tracker = Tracker(smoothing=0.4, miss_limit=5)
                except: pass
                self._rebuild_per_beacon_panels()
                try: self._on_target_beacon_change(tid)
                except: pass
                if was_running: self._start()
                return
            except Exception:
                pass
        # Legacy path
        try:
            self._beacon_count = int(self.beacon_count_spin.value())
            self._hitbox_radius = int(self.hitbox_spin.value())
            self._center_radius = int(self.center_spin.value())
        except: return
        was_running = getattr(self, "_running", False)
        if was_running: self._pause()
        try: profile = MotionProfile(self.motion_combo.currentText())
        except: profile = self.target.profile if hasattr(self, "target") else MotionProfile.CURVED
        speed = float(getattr(self, "_target_speed", 60))
        scene_w, scene_h = self._scene_size
        seed = int(self.seed_spin.value()) + int(time.time()) % 1000
        self.beacons = create_beacons(self._beacon_count, (scene_w, scene_h), profile, speed,
                                       seed=seed, hitbox_radius=self._hitbox_radius, center_radius=self._center_radius)
        # respect selected target id
        try:
            tid = int(self.target_beacon_spin.value())
        except:
            tid = int(getattr(self, "_target_beacon_id", 0))
        tid = int(np.clip(tid, 0, max(0, len(self.beacons)-1)))
        self._target_beacon_id = tid
        self.target = self.beacons[tid] if self.beacons else self.beacons[0]
        self.statusBar().showMessage(f"Beacons: {self._beacon_count}  Target #{tid}  hitbox {self._hitbox_radius}px  center {self._center_radius}px", 3000)
        try: self.tracker = Tracker(smoothing=0.4, miss_limit=5)
        except: pass
        self._rebuild_per_beacon_panels()
        # highlight target
        try: self._on_target_beacon_change(tid)
        except: pass
        if was_running: self._start()

    def _apply_beacons_hot(self):
        """HOT — rebuild via factory but preserve per-beacon 8 params from manager (modular)."""
        # Prefer manager-driven path (8 per-beacon params + 3 multi)
        try:
            if hasattr(self, "beacon_manager") and self.beacon_manager is not None:
                multi_cfg = self.beacon_manager.collect_multi_config().validate()
                self.beacon_config = multi_cfg
                self._beacon_count = int(multi_cfg.beacon_count)
                self._hitbox_radius = int(multi_cfg.beacons[0].hitbox_radius) if multi_cfg.beacons else 14
                self._center_radius = int(multi_cfg.beacons[0].center_radius) if multi_cfg.beacons else 2
                tid = int(multi_cfg.target_index)
                # Factory with global profile/speed but per-beacon overlay follows
                try: profile = MotionProfile(self.motion_combo.currentText())
                except: profile = self.target.profile if hasattr(self, "target") else MotionProfile.CURVED
                speed = float(getattr(self, "_target_speed", 60))
                scene_w, scene_h = self._scene_size
                seed = int(self.seed_spin.value()) + int(time.time()) % 1000 if hasattr(self, "seed_spin") else int(multi_cfg.beacons[0].position_seed) if multi_cfg.beacons else 42
                self.beacons = create_beacons(self._beacon_count, (scene_w, scene_h), profile, speed,
                                               seed=seed, hitbox_radius=self._hitbox_radius, center_radius=self._center_radius)
                # Overlay per-beacon configs (keeps user-edited brightness/radius/seed etc.)
                for i, b_cfg in enumerate(multi_cfg.beacons):
                    if i < len(self.beacons):
                        try: b_cfg.apply_to_target(self.beacons[i])
                        except: pass
                tid = int(np.clip(int(tid), 0, max(0, len(self.beacons)-1)))
                self._target_beacon_id = tid
                self.target = self.beacons[tid] if self.beacons else self.beacons[0]
                try: self.tracker = Tracker(smoothing=0.4, miss_limit=5)
                except: pass
                self._rebuild_per_beacon_panels()
                try: self._on_target_beacon_change(tid)
                except: pass
                self.statusBar().showMessage(f"Beacons HOT — {self._beacon_count} beacons Target #{tid} (manager, 8 params)", 2000)
                try: self._snapshot_section("beacons"); self._clear_dirty("beacons")
                except: pass
                return
        except Exception:
            pass
        # Legacy fallback (no manager yet, e.g., first init)
        try:
            self._beacon_count = int(self.beacon_count_spin.value())
            self._hitbox_radius = int(self.hitbox_spin.value())
            self._center_radius = int(self.center_spin.value())
        except: return
        try: profile = MotionProfile(self.motion_combo.currentText())
        except: profile = self.target.profile if hasattr(self, "target") else MotionProfile.CURVED
        speed = float(getattr(self, "_target_speed", 60))
        scene_w, scene_h = self._scene_size
        seed = int(self.seed_spin.value()) + int(time.time()) % 1000
        self.beacons = create_beacons(self._beacon_count, (scene_w, scene_h), profile, speed,
                                       seed=seed, hitbox_radius=self._hitbox_radius, center_radius=self._center_radius)
        try: tid = int(self.target_beacon_spin.value())
        except: tid = int(getattr(self, "_target_beacon_id", 0))
        tid = int(np.clip(tid, 0, max(0, len(self.beacons)-1)))
        self._target_beacon_id = tid
        self.target = self.beacons[tid] if self.beacons else self.beacons[0]
        try: self.tracker = Tracker(smoothing=0.4, miss_limit=5)
        except: pass
        self._rebuild_per_beacon_panels()
        try: self._on_target_beacon_change(tid)
        except: pass
        self.statusBar().showMessage(f"Beacons HOT — {self._beacon_count} beacons Target #{tid} (auto)", 2000)
        try: self._snapshot_section("beacons"); self._clear_dirty("beacons")
        except: pass

    # ── Per-Beacon dynamic — every parameter live (modular) ──
    def _rebuild_per_beacon_panels(self):
        """Rebuild per-beacon panels — delegates to MultiBeaconPanel if available, else legacy."""
        # New modular path: sync MultiBeaconPanel from live beacons
        if hasattr(self, "beacon_manager") and self.beacon_manager is not None:
            try:
                # Build MultiBeaconConfig from current live beacons (preserves per-beacon 8 params)
                cfgs = []
                for b in getattr(self, "beacons", []):
                    try:
                        cfgs.append(BeaconConfig.from_target(b).validate())
                    except Exception:
                        cfgs.append(BeaconConfig(beacon_id=getattr(b, "beacon_id", len(cfgs)), speed=getattr(b, "speed", 60)).validate())
                # Ensure count matches
                n_beacons = len(getattr(self, "beacons", [])) or int(getattr(self, "_beacon_count", 1))
                tid = int(getattr(self, "_target_beacon_id", 0))
                multi = MultiBeaconConfig(beacon_count=n_beacons, target_index=tid, beacons=cfgs).validate()
                self.beacon_config = multi
                self.beacon_manager.set_config(multi, emit=False)
                # Keep alias for legacy handlers
                self.per_beacon_panels = self.beacon_manager.get_per_beacon_panels()  # type: ignore
                # Update world bounds for X/Y clamping
                try:
                    self.beacon_manager.set_world_bounds(self._scene_size)
                except: pass
                return
            except Exception as e:
                # Fallback to legacy
                pass
        # Legacy fallback — clear old dict-based panels
        try:
            while self.per_beacon_layout.count():
                item = self.per_beacon_layout.takeAt(0)
                w = item.widget()
                if w is not None:
                    w.deleteLater()
        except Exception:
            return
        self.per_beacon_panels = []
        beacons = getattr(self, "beacons", [])
        if not beacons:
            lbl = QLabel("No beacons — click Apply Beacons")
            lbl.setStyleSheet("color:#94a3b8; font-style:italic;")
            try:
                self.per_beacon_layout.addWidget(lbl)
            except: pass
            return
        for idx, b in enumerate(beacons):
            panel = self._create_single_beacon_panel(idx, b)
            try:
                self.per_beacon_layout.addWidget(panel)
            except: pass
        n = len(beacons)
        try:
            self.per_beacon_scroll.setMaximumHeight(min(420, 86 + n * 118))
            self.per_beacon_scroll.setMinimumHeight(min(220, 86 + n * 118))
        except: pass

    def _create_single_beacon_panel(self, idx: int, beacon) -> QGroupBox:
        box = QGroupBox(f"Beacon #{beacon.beacon_id} — {'ON' if beacon.enabled else 'OFF'}")
        box.setStyleSheet("QGroupBox { background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 8px; margin-top: 8px; padding-top: 8px; } QGroupBox::title { color: #0f172a; font-size:10px; }")
        grid = QGridLayout(box)
        grid.setContentsMargins(8, 12, 8, 8)
        grid.setHorizontalSpacing(6)
        grid.setVerticalSpacing(6)
        grid.setColumnStretch(1, 1)
        grid.setColumnStretch(3, 1)

        # Row 0: Enabled | Profile
        chk = QCheckBox("Enabled"); chk.setChecked(bool(beacon.enabled)); chk.setStyleSheet("font-size:11px;")
        grid.addWidget(chk, 0, 0)
        # Profile combo per beacon
        prof_combo = QComboBox(); prof_combo.addItems([p.value for p in MotionProfile]); prof_combo.setCurrentText(beacon.profile.value); prof_combo.setMinimumHeight(24)
        grid.addWidget(QLabel("Profile"), 0, 1); grid.addWidget(prof_combo, 0, 2, 1, 2)

        # Row 1: Speed | Brightness | Radius
        grid.addWidget(QLabel("Speed"), 1, 0)
        sp_speed = QSpinBox(); sp_speed.setRange(5, 300); sp_speed.setValue(int(beacon.speed)); sp_speed.setSuffix(" px/s"); sp_speed.setMinimumHeight(24)
        grid.addWidget(sp_speed, 1, 1)
        grid.addWidget(QLabel("Bright"), 1, 2)
        sp_bright = QSpinBox(); sp_bright.setRange(50, 255); sp_bright.setValue(int(beacon.brightness)); sp_bright.setMinimumHeight(24)
        grid.addWidget(sp_bright, 1, 3)

        grid.addWidget(QLabel("Radius"), 2, 0)
        sp_radius = QSpinBox(); sp_radius.setRange(1, 15); sp_radius.setValue(int(beacon.radius)); sp_radius.setSuffix(" px"); sp_radius.setMinimumHeight(24)
        grid.addWidget(sp_radius, 2, 1)
        grid.addWidget(QLabel("Hitbox"), 2, 2)
        sp_hit = QSpinBox(); sp_hit.setRange(3, 80); sp_hit.setValue(int(beacon.hitbox_radius)); sp_hit.setSuffix(" px"); sp_hit.setMinimumHeight(24)
        grid.addWidget(sp_hit, 2, 3)

        grid.addWidget(QLabel("Center"), 3, 0)
        sp_center = QSpinBox(); sp_center.setRange(1, 10); sp_center.setValue(int(beacon.center_radius)); sp_center.setSuffix(" px"); sp_center.setMinimumHeight(24)
        grid.addWidget(sp_center, 3, 1)
        grid.addWidget(QLabel("Heading"), 3, 2)
        sp_head = QSpinBox(); sp_head.setRange(0, 360); sp_head.setValue(int(math.degrees(beacon._heading)) % 360); sp_head.setSuffix("°"); sp_head.setMinimumHeight(24)
        grid.addWidget(sp_head, 3, 3)

        # Row 4: X | Y
        grid.addWidget(QLabel("X"), 4, 0)
        sp_x = QSpinBox(); sp_x.setRange(0, self._scene_size[0]); sp_x.setValue(int(beacon.x)); sp_x.setMinimumHeight(24)
        grid.addWidget(sp_x, 4, 1)
        grid.addWidget(QLabel("Y"), 4, 2)
        sp_y = QSpinBox(); sp_y.setRange(0, self._scene_size[1]); sp_y.setValue(int(beacon.y)); sp_y.setMinimumHeight(24)
        grid.addWidget(sp_y, 4, 3)

        # Row 5: Random Position — live, auto-HOT (no Apply needed)
        btn_rand = QPushButton("↻ Random Position"); btn_rand.setMinimumHeight(24); btn_rand.setStyleSheet("font-size:10px; padding:4px; background:#f1f5f9; border:1px solid #cbd5e1; border-radius:4px;")
        grid.addWidget(btn_rand, 5, 0, 1, 4)

        # Wire live updates — capture idx via default arg (live + dirty for HOT confirmation)
        chk.toggled.connect(lambda checked, i=idx: self._on_per_beacon_enabled(i, checked))
        chk.toggled.connect(lambda _, s="beacons": self._mark_dirty(s))
        prof_combo.currentTextChanged.connect(lambda txt, i=idx: self._on_per_beacon_profile(i, txt))
        prof_combo.currentTextChanged.connect(lambda _, s="beacons": self._mark_dirty(s))
        sp_speed.valueChanged.connect(lambda v, i=idx: self._on_per_beacon_speed(i, v))
        sp_speed.valueChanged.connect(lambda _, s="beacons": self._mark_dirty(s))
        sp_bright.valueChanged.connect(lambda v, i=idx: self._on_per_beacon_brightness(i, v))
        sp_bright.valueChanged.connect(lambda _, s="beacons": self._mark_dirty(s))
        sp_radius.valueChanged.connect(lambda v, i=idx: self._on_per_beacon_radius(i, v))
        sp_radius.valueChanged.connect(lambda _, s="beacons": self._mark_dirty(s))
        sp_hit.valueChanged.connect(lambda v, i=idx: self._on_per_beacon_hitbox(i, v))
        sp_hit.valueChanged.connect(lambda _, s="beacons": self._mark_dirty(s))
        sp_center.valueChanged.connect(lambda v, i=idx: self._on_per_beacon_center(i, v))
        sp_center.valueChanged.connect(lambda _, s="beacons": self._mark_dirty(s))
        sp_x.valueChanged.connect(lambda v, i=idx: self._on_per_beacon_x(i, v))
        sp_x.valueChanged.connect(lambda _, s="beacons": self._mark_dirty(s))
        sp_y.valueChanged.connect(lambda v, i=idx: self._on_per_beacon_y(i, v))
        sp_y.valueChanged.connect(lambda _, s="beacons": self._mark_dirty(s))
        sp_head.valueChanged.connect(lambda v, i=idx: self._on_per_beacon_heading(i, v))
        sp_head.valueChanged.connect(lambda _, s="beacons": self._mark_dirty(s))
        btn_rand.clicked.connect(lambda _, i=idx: self._randomize_single_beacon_pos(i))

        # store refs for external updates (e.g., after scene resize)
        panel_ref = {"box": box, "chk": chk, "prof": prof_combo, "speed": sp_speed, "bright": sp_bright,
                     "radius": sp_radius, "hitbox": sp_hit, "center": sp_center, "x": sp_x, "y": sp_y, "heading": sp_head}
        self.per_beacon_panels.append(panel_ref)
        return box

    def _on_per_beacon_enabled(self, idx: int, checked: bool):
        try:
            b = self.beacons[idx]; b.enabled = bool(checked)
            self.per_beacon_panels[idx]["box"].setTitle(f"Beacon #{b.beacon_id} — {'ON' if checked else 'OFF'}")
        except: pass

    def _on_per_beacon_profile(self, idx: int, txt: str):
        try: self.beacons[idx].profile = MotionProfile(txt)
        except: pass

    def _on_per_beacon_speed(self, idx: int, v: int):
        try: self.beacons[idx].speed = float(v)
        except: pass

    def _on_per_beacon_brightness(self, idx: int, v: int):
        try: self.beacons[idx].brightness = int(v); self.beacons[idx].current_brightness = float(v)
        except: pass

    def _on_per_beacon_radius(self, idx: int, v: int):
        try: self.beacons[idx].radius = int(v)
        except: pass

    def _on_per_beacon_hitbox(self, idx: int, v: int):
        try: self.beacons[idx].hitbox_radius = int(v)
        except: pass

    def _on_per_beacon_center(self, idx: int, v: int):
        try: self.beacons[idx].center_radius = int(v)
        except: pass

    def _on_per_beacon_x(self, idx: int, v: int):
        try: self.beacons[idx].x = float(np.clip(v, 0, self._scene_size[0]))
        except: pass

    def _on_per_beacon_y(self, idx: int, v: int):
        try: self.beacons[idx].y = float(np.clip(v, 0, self._scene_size[1]))
        except: pass

    def _on_per_beacon_heading(self, idx: int, deg: int):
        try: self.beacons[idx]._heading = math.radians(int(deg) % 360)
        except: pass
        try:
            # keep panel display in sync if heading wrapped
            panel = self.per_beacon_panels[idx]
            # no extra
            pass
        except: pass

    def _randomize_single_beacon_pos(self, idx: int):
        """Randomize single beacon position — seed-driven, HOT (modular)."""
        try:
            b = self.beacons[idx]
            import random as rnd
            # Use modular Target.randomize_position if available (seed-driven)
            try:
                b.randomize_position(seed=int(rnd.randint(0, 999999)))
            except Exception:
                b.x = float(rnd.uniform(60, self._scene_size[0]-60))
                b.y = float(rnd.uniform(60, self._scene_size[1]-60))
            # Reflect in UI — supports both legacy dict and new BeaconPanel
            panel = self.per_beacon_panels[idx] if idx < len(getattr(self, "per_beacon_panels", [])) else None
            if panel is None:
                return
            if isinstance(panel, dict):
                panel["x"].blockSignals(True); panel["x"].setValue(int(b.x)); panel["x"].blockSignals(False)
                panel["y"].blockSignals(True); panel["y"].setValue(int(b.y)); panel["y"].blockSignals(False)
            else:
                # BeaconPanel — update via seed + x/y
                try:
                    panel.spin_seed.blockSignals(True); panel.spin_seed.setValue(int(getattr(b, "_seed", 42) or 42)); panel.spin_seed.blockSignals(False)
                except: pass
                try:
                    panel.spin_x.blockSignals(True); panel.spin_x.setValue(int(b.x)); panel.spin_x.blockSignals(False)
                    panel.spin_y.blockSignals(True); panel.spin_y.setValue(int(b.y)); panel.spin_y.blockSignals(False)
                except: pass
                # Also sync manager's per-beacon config store
                try:
                    if hasattr(self, "beacon_manager"):
                        self.beacon_manager.get_per_beacon_panels()[idx].spin_x.setValue(int(b.x))
                except: pass
        except: pass

    def _randomize_all_beacons(self):
        """Randomize All — reroll every per-beacon parameter (8 + motion) for all beacons."""
        # Modular path: use Target.randomize_all (covers all 8 params + profile/seed)
        if hasattr(self, "beacon_manager") and self.beacon_manager is not None:
            try:
                import random as _rnd
                for i, b in enumerate(getattr(self, "beacons", [])):
                    try:
                        b.randomize_all(seed=int(_rnd.randint(0, 999999)))
                    except Exception:
                        # Fallback manual
                        b.speed = float(np.clip(b.speed * _rnd.uniform(0.7, 1.3), 8, 250))
                        b.x = float(_rnd.uniform(60, self._scene_size[0]-60))
                        b.y = float(_rnd.uniform(60, self._scene_size[1]-60))
                # Sync manager panels from live beacons
                self._rebuild_per_beacon_panels()
                # Also push to beacon_config
                try:
                    self.beacon_config = self.beacon_manager.collect_multi_config().validate()
                except: pass
                self.statusBar().showMessage(f"Randomized {len(self.beacons)} beacons (all 8 params)", 2500)
                return
            except Exception:
                pass
        # Legacy fallback
        for i in range(len(getattr(self, "beacons", []))):
            self._randomize_single_beacon_pos(i)
            import random as rnd
            b = self.beacons[i]
            b.speed = float(np.clip(b.speed * rnd.uniform(0.7, 1.3), 8, 250))
            try:
                panel = self.per_beacon_panels[i]
                if isinstance(panel, dict):
                    panel["speed"].blockSignals(True); panel["speed"].setValue(int(b.speed)); panel["speed"].blockSignals(False)
                else:
                    panel.spin_speed.blockSignals(True); panel.spin_speed.setValue(int(b.speed)); panel.spin_speed.blockSignals(False)
            except: pass
        self.statusBar().showMessage(f"Randomized {len(self.beacons)} beacons", 2500)

    def _on_per_beacon_apply(self, idx: int):
        """Per-panel Apply — both live (already applied) + explicit confirmation (HOT)."""
        try:
            b = self.beacons[idx]
            self.statusBar().showMessage(f"Beacon #{b.beacon_id} applied — {b.profile.value} {int(b.speed)}px/s hb {b.hitbox_radius}px (HOT, next tick)", 2500)
            # flash the panel border to confirm
            box = self.per_beacon_panels[idx]["box"]
            orig = box.styleSheet()
            box.setStyleSheet(orig + " QGroupBox { border: 1px solid #22c55e; }")
            from PyQt5.QtCore import QTimer as _QTimer
            _QTimer.singleShot(700, lambda: box.setStyleSheet(orig))
            # per-panel Apply also confirms the whole Beacons section (HOT)
            self._clear_dirty("beacons")
            self._snapshot_section("beacons")
        except: pass

    # ── Per-section HOT Apply / Discard + Master ──
    # NOTE: State handling (dirty/HOT/snapshot) delegated to gui.mixins.state_mixin.StateMixin
    # Methods inherited: _mark_dirty, _clear_dirty, _apply_section, _discard_section,
    # _master_apply_all, _master_discard_all, _snapshot_section, _schedule_auto

    def _apply_scene_settings_hot(self):
        """HOT — applies Environment from EnvironmentPanel + EnvironmentConfig (modular, no pause)."""
        # ------------------------------------------------------------
        # Collect validated EnvironmentConfig (single source of truth)
        # ------------------------------------------------------------
        try:
            cfg = self.env_panel.collect_config().validate() if hasattr(self, "env_panel") else self.env_config.validate()
            self.env_config = cfg
        except Exception:
            cfg = self.env_config.validate()
        sw, sh = int(cfg.world_width), int(cfg.world_height)
        # Camera / display sizes still live in Camera tab spins (not env) — read directly
        fw = int(np.clip(self.fov_w_spin.value(), 20, MAX_RES))
        fh = int(np.clip(self.fov_h_spin.value(), 20, MAX_RES))
        vw = int(np.clip(self.viewport_w_spin.value(), 50, MAX_RES))
        vh = int(np.clip(self.viewport_h_spin.value(), 50, MAX_RES))
        gw = int(np.clip(self.god_w_spin.value(), 50, MAX_RES))
        gh = int(np.clip(self.god_h_spin.value(), 50, MAX_RES))
        fw = min(fw, sw-10); fh = min(fh, sh-10)
        if fw<20: fw=20
        if fh<20: fh=20
        if sw*sh > 16_000_000:
            if QMessageBox.warning(self, "Large world", f"World {sw}×{sh} = {sw*sh/1e6:.1f} MP heavy — FPS will drop. Continue?", QMessageBox.Yes|QMessageBox.No, QMessageBox.No) != QMessageBox.Yes:
                return
        self._scene_size = (sw, sh); self._fov_size = (fw, fh)
        self._viewport_display_size = (vw, vh); self._god_display_size = (gw, gh)
        self.fov_res_lbl.setText(f"{fw}×{fh}"); self.god_res_lbl.setText(f"{sw}×{sh}")
        self.viewport_label.setMinimumSize(max(200, min(vw, 900)), max(140, min(vh, 700)))
        self.minimap_label.setMinimumSize(max(200, min(gw, 900)), max(140, min(gh, 700)))
        self.fov_w_spin.blockSignals(True); self.fov_w_spin.setValue(fw); self.fov_w_spin.blockSignals(False)
        self.fov_h_spin.blockSignals(True); self.fov_h_spin.setValue(fh); self.fov_h_spin.blockSignals(False)
        # Apply scene via typed config — delegates to scene.regenerate_from_config (modular builders)
        try:
            self.scene.regenerate_from_config(cfg)
        except Exception:
            # Fallback: legacy regenerate with explicit fields
            try:
                self.scene.regenerate(
                    width=sw, height=sh, seed=int(cfg.seed), dynamic=bool(cfg.dynamic),
                    haze_strength=float(cfg.haze_pct)/100.0,
                    bg_top=int(cfg.bg_top), bg_bottom=int(cfg.bg_bottom),
                    vignetting=float(cfg.vignetting_pct)/100.0,
                    star_count=int(cfg.star_count),
                    star_brightness_scale=float(cfg.star_brightness),
                    dynamic_speed=float(cfg.dynamic_speed),
                )
            except Exception:
                self._build_simulation()
                self.scene.regenerate_from_config(cfg)
        # Camera — update scene bounds and re-validate ranges/home against new world (modular)
        try:
            if hasattr(self, "camera_panel"):
                self.camera_panel.set_scene_bounds((sw, sh))
                cam_cfg2 = self.camera_panel.collect_config().validate((sw, sh))
                self.camera_config = cam_cfg2
            else:
                cam_cfg2 = self.camera_config.validate((sw, sh))
            self.camera.apply_config(cam_cfg2, scene_bounds=(sw, sh))
            self._fov_size = (int(cam_cfg2.fov_width), int(cam_cfg2.fov_height))
            self._viewport_display_size = (int(cam_cfg2.viewport_width), int(cam_cfg2.viewport_height))
            self._god_display_size = (int(cam_cfg2.god_width), int(cam_cfg2.god_height))
            from gui.core.renderer import Renderer as _R3, ScreenSpec as _S3
            try:
                spec = _S3(viewport_w=int(cam_cfg2.viewport_width), viewport_h=int(cam_cfg2.viewport_height), god_w=int(cam_cfg2.god_width), god_h=int(cam_cfg2.god_height))
                _R3.apply_screen_sizes(self.viewport_label, self.minimap_label, spec)
                self.fov_res_lbl.setText(f"{int(cam_cfg2.fov_width)}x{int(cam_cfg2.fov_height)}")
                self.god_res_lbl.setText(f"{sw}x{sh}")
            except: pass
        except Exception:
            self.camera.scene_bounds = (sw, sh)
            self.camera.fov_width = fw; self.camera.fov_height = fh
            try:
                self.camera.go_home()
            except:
                self.camera.set_position(sw/2, sh/2)
        for b in getattr(self, "beacons", [self.target]):
            b.bounds = (sw, sh)
            b.x = float(np.clip(b.x, 0, sw)); b.y = float(np.clip(b.y, 0, sh))
        self._camera_drift_state = {}
        try:
            self._sync_per_beacon_xy_ranges()
            for idx, b in enumerate(getattr(self, "beacons", [])):
                panel = self.per_beacon_panels[idx] if idx < len(getattr(self, "per_beacon_panels", [])) else None
                if not panel:
                    continue
                if isinstance(panel, dict):
                    panel["x"].blockSignals(True); panel["x"].setValue(int(b.x)); panel["x"].blockSignals(False)
                    panel["y"].blockSignals(True); panel["y"].setValue(int(b.y)); panel["y"].blockSignals(False)
                else:
                    panel.spin_x.blockSignals(True); panel.spin_x.setValue(int(b.x)); panel.spin_x.blockSignals(False)
                    panel.spin_y.blockSignals(True); panel.spin_y.setValue(int(b.y)); panel.spin_y.blockSignals(False)
        except: pass
        self._snapshot_section("environment"); self._snapshot_section("camera")
        try:
            cam_scale = float(self.camera_config.pixel_scale_mrad)
            self.statusBar().showMessage(f"Environment/Camera HOT — world {sw}x{sh} FOV {self.camera_config.fov_width}x{self.camera_config.fov_height} pan {self.camera_config.pan_min}:{self.camera_config.pan_max} scale {cam_scale:.3f}mrad/px", 3000)
        except:
            self.statusBar().showMessage(f"Environment/Camera HOT applied — world {sw}x{sh} FOV {fw}x{fh}", 3000)

    def _apply_camera_hot(self):
        """HOT — apply full CameraConfig (11 params: FOV, mechanics, display, units + gain)."""
        try:
            # Collect validated camera config (all 11 params) against current scene
            sw, sh = self._scene_size
            try:
                cam_cfg = self.camera_panel.collect_config().validate((sw, sh))
                self.camera_config = cam_cfg
            except Exception:
                cam_cfg = self.camera_config.validate((sw, sh))
            # Clamp FOV to scene (handles FOV > scene case)
            fw, fh = int(cam_cfg.fov_width), int(cam_cfg.fov_height)
            fw = min(fw, sw-10); fh = min(fh, sh-10)
            if fw<20: fw=20
            if fh<20: fh=20
            cam_cfg.fov_width = int(fw); cam_cfg.fov_height = int(fh)
            self.camera_config = cam_cfg
            # Legacy mirrors for renderer
            self._fov_size = (fw, fh)
            self._viewport_display_size = (int(cam_cfg.viewport_width), int(cam_cfg.viewport_height))
            self._god_display_size = (int(cam_cfg.god_width), int(cam_cfg.god_height))
            vw, vh = self._viewport_display_size; gw, gh = self._god_display_size
            # Update display labels
            self.fov_res_lbl.setText(f"{fw}x{fh}")
            # Screens — on-screen sizes independent of FOV resolution
            from gui.core.renderer import ScreenSpec
            spec = ScreenSpec(viewport_w=vw, viewport_h=vh, god_w=gw, god_h=gh)
            from gui.core.renderer import Renderer as _R
            try:
                _R.apply_screen_sizes(self.viewport_label, self.minimap_label, spec)
            except:
                self.viewport_label.setMinimumSize(max(200, min(vw, 900)), max(140, min(vh, 700)))
                self.minimap_label.setMinimumSize(max(200, min(gw, 900)), max(140, min(gh, 700)))
            # Reflect clamped FOV back to panel without re-triggering
            self.camera_panel.fov_w_spin.blockSignals(True); self.camera_panel.fov_w_spin.setValue(int(fw)); self.camera_panel.fov_w_spin.blockSignals(False)
            self.camera_panel.fov_h_spin.blockSignals(True); self.camera_panel.fov_h_spin.setValue(int(fh)); self.camera_panel.fov_h_spin.blockSignals(False)
            # Apply to PTZCamera — handles pan/tilt ranges, home, slew, resolution, latency, pixel scale
            try:
                self.camera.apply_config(cam_cfg, scene_bounds=(sw, sh))
                # Sync panel scene bounds for range validation
                self.camera_panel.set_scene_bounds((sw, sh))
            except Exception:
                # Fallback legacy direct assignment
                self.camera.fov_width = int(fw); self.camera.fov_height = int(fh)
                self.camera.scene_bounds = (sw, sh)
            # Gain — controller
            try: self.controller.gain = float(self.camera_panel.gain_spin.value())
            except: pass
            self._snapshot_section("camera")
            # Report includes angular scale for units verification
            scale = float(cam_cfg.pixel_scale_mrad)
            self.statusBar().showMessage(f"Camera HOT — FOV {fw}x{fh} pan [{int(cam_cfg.pan_min or 0)}:{int(cam_cfg.pan_max or sw)}] slew {cam_cfg.max_slew_rate:.0f}px/s lat {cam_cfg.latency_ms}ms scale {scale:.3f}mrad/px gain {self.controller.gain:.2f}", 3000)
        except Exception as e:
            QMessageBox.warning(self, "Camera Apply", f"Failed: {e}")

    def _apply_scene_settings(self):
        sw = int(np.clip(self.scene_w_spin.value(), MIN_RES, MAX_RES))
        sh = int(np.clip(self.scene_h_spin.value(), MIN_RES, MAX_RES))
        fw = int(np.clip(self.fov_w_spin.value(), 20, MAX_RES))
        fh = int(np.clip(self.fov_h_spin.value(), 20, MAX_RES))
        vw = int(np.clip(self.viewport_w_spin.value(), 50, MAX_RES))
        vh = int(np.clip(self.viewport_h_spin.value(), 50, MAX_RES))
        gw = int(np.clip(self.god_w_spin.value(), 50, MAX_RES))
        gh = int(np.clip(self.god_h_spin.value(), 50, MAX_RES))
        fw = min(fw, sw-10); fh = min(fh, sh-10)
        if fw<20: fw=20
        if fh<20: fh=20
        total_px = sw*sh
        if total_px > 16_000_000:
            if QMessageBox.warning(self, "Large world", f"World {sw}×{sh} = {total_px/1e6:.1f} MP heavy — FPS will drop. Continue?", QMessageBox.Yes|QMessageBox.No, QMessageBox.No) != QMessageBox.Yes:
                return
        self._scene_size = (sw, sh)
        self._fov_size = (fw, fh)
        self._viewport_display_size = (vw, vh)
        self._god_display_size = (gw, gh)
        # Update labels and minimums (responsive — minimum grows, but window remains resizable)
        self.fov_res_lbl.setText(f"{fw}×{fh}")
        self.god_res_lbl.setText(f"{sw}×{sh}")
        self.viewport_label.setMinimumSize(max(200, min(vw, 900)), max(140, min(vh, 700)))
        self.minimap_label.setMinimumSize(max(200, min(gw, 900)), max(140, min(gh, 700)))
        # reflect clamped FOV
        self.fov_w_spin.blockSignals(True); self.fov_w_spin.setValue(fw); self.fov_w_spin.blockSignals(False)
        self.fov_h_spin.blockSignals(True); self.fov_h_spin.setValue(fh); self.fov_h_spin.blockSignals(False)
        was_running = self._running
        if was_running: self._pause()
        # Use validated EnvironmentConfig for full fidelity (10 params, not just 3)
        try:
            cfg = self.env_panel.collect_config().validate() if hasattr(self, "env_panel") else self.env_config.validate()
            self.env_config = cfg
            # Overwrite cfg world size with the clamped sw/sh already computed above
            cfg.world_width = sw; cfg.world_height = sh
            self.scene.regenerate_from_config(cfg)
        except Exception:
            seed = int(self.seed_spin.value()); dynamic = bool(self.dynamic_check.isChecked()); haze = float(self.haze_spin.value())/100.0
            try:
                self.scene.regenerate(width=sw, height=sh, seed=seed, dynamic=dynamic, haze_strength=haze)
            except:
                self._build_simulation()
                self.scene.regenerate(width=sw, height=sh, seed=seed, dynamic=dynamic, haze_strength=haze)
        # Camera — apply full config (FOV, mechanics, display, units) with new scene bounds
        try:
            if hasattr(self, "camera_panel"):
                self.camera_panel.set_scene_bounds((sw, sh))
                cam_cfg2 = self.camera_panel.collect_config().validate((sw, sh))
                self.camera_config = cam_cfg2
            else:
                cam_cfg2 = self.camera_config.validate((sw, sh))
            self.camera.apply_config(cam_cfg2, scene_bounds=(sw, sh))
            self._fov_size = (int(cam_cfg2.fov_width), int(cam_cfg2.fov_height))
            self._viewport_display_size = (int(cam_cfg2.viewport_width), int(cam_cfg2.viewport_height))
            self._god_display_size = (int(cam_cfg2.god_width), int(cam_cfg2.god_height))
            from gui.core.renderer import Renderer as _R4, ScreenSpec as _S4
            try:
                spec = _S4(viewport_w=int(cam_cfg2.viewport_width), viewport_h=int(cam_cfg2.viewport_height), god_w=int(cam_cfg2.god_width), god_h=int(cam_cfg2.god_height))
                _R4.apply_screen_sizes(self.viewport_label, self.minimap_label, spec)
                self.fov_res_lbl.setText(f"{int(cam_cfg2.fov_width)}x{int(cam_cfg2.fov_height)}")
                self.god_res_lbl.setText(f"{sw}x{sh}")
            except: pass
        except Exception:
            self.camera.scene_bounds = (sw, sh)
            self.camera.fov_width = fw; self.camera.fov_height = fh
            try:
                self.camera.go_home()
            except:
                self.camera.set_position(sw/2, sh/2)
        for b in getattr(self, "beacons", [self.target]):
            b.bounds = (sw, sh)
            b.x = float(np.clip(b.x, 0, sw)); b.y = float(np.clip(b.y, 0, sh))
        self._camera_drift_state = {}
        try:
            self._sync_per_beacon_xy_ranges()
            for idx, b in enumerate(getattr(self, "beacons", [])):
                panel = self.per_beacon_panels[idx] if idx < len(getattr(self, "per_beacon_panels", [])) else None
                if not panel:
                    continue
                if isinstance(panel, dict):
                    panel["x"].blockSignals(True); panel["x"].setValue(int(b.x)); panel["x"].blockSignals(False)
                    panel["y"].blockSignals(True); panel["y"].setValue(int(b.y)); panel["y"].blockSignals(False)
                else:
                    panel.spin_x.blockSignals(True); panel.spin_x.setValue(int(b.x)); panel.spin_x.blockSignals(False)
                    panel.spin_y.blockSignals(True); panel.spin_y.setValue(int(b.y)); panel.spin_y.blockSignals(False)
        except: pass
        try:
            scale = float(self.camera_config.pixel_scale_mrad)
            self.statusBar().showMessage(f"Applied world {sw}x{sh} FOV {self.camera_config.fov_width}x{self.camera_config.fov_height} scale {scale:.3f}mrad/px seed {seed} dynamic={dynamic}", 4000)
        except:
            self.statusBar().showMessage(f"Applied world {sw}x{sh} FOV {fw}x{fh} seed {seed} dynamic={dynamic}", 4000)
        if was_running: self._start()

    def _start(self):
        if not self._running:
            if self.perf.start_time is None: self.perf.start()
            self._last_tick_time = time.time()
            if getattr(self, "_pause_time", None) is not None and self.perf.start_time is not None:
                self.perf.start_time += time.time() - self._pause_time
                self._pause_time = None
            self.timer.start(TICK_MS); self._running = True
            self.statusBar().showMessage("Running — tracking…", 2000)
    def _pause(self):
        if self._running:
            self.timer.stop(); self._running = False; self._pause_time = time.time()
            self.statusBar().showMessage("Paused", 2000)
        else: self._pause_time = None
    def _reset(self):
        self.timer.stop(); self._running=False; self._pause_time=None
        cur=self.motion_combo.currentText()
        self._build_simulation()
        try:
            self._rebuild_per_beacon_panels()
            self._sync_per_beacon_xy_ranges()
        except: pass
        self.motion_combo.blockSignals(True); self.motion_combo.setCurrentText(cur); self.motion_combo.blockSignals(False)
        try: self.target.profile=MotionProfile(cur)
        except: pass
        for b in getattr(self, "beacons", []):
            try: b.profile = MotionProfile(cur)
            except: pass
        self.perf=PerformanceLogger(); self._camera_drift_state={}; self._last_tick_time=None
        # Reset disturbance global state — fixes stale phase/velocity on fresh run (reproducibility)
        try:
            dist.reset_disturbance_state()
            # Also clear per-instance drift dict (already {}) and any module globals
            self._camera_drift_state.clear()
        except Exception:
            pass
        for l in self.stat_labels.values(): l.setText("-")
        self.footer_lock.setText("SEARCHING"); self.lock_dot.setStyleSheet("color:#64748b; font-size:14px;")
        self.viewport_label.clear(); self.minimap_label.clear()
        self.statusBar().showMessage("Reset — ready", 2000)
    def _export_log(self):
        path,_=QFileDialog.getSaveFileName(self,"Export performance log","performance_log.csv","CSV (*.csv);;JSON (*.json)")
        if path:
            try: self.perf.export_report(path); QMessageBox.information(self,"Export", f"Saved to:\n{path}")
            except Exception as e: QMessageBox.critical(self,"Export failed", str(e))

    # ---------- tick ----------
    def _tick(self):
        frame_start=time.time()
        dt = TICK_MS/1000.0 if self._last_tick_time is None else float(np.clip(frame_start-self._last_tick_time,0.005,0.1))
        self._last_tick_time=frame_start
        # Global sim speed scales physics dt (realtime configurable 0.2–3.0x)
        try:
            sim_speed = float(self.sim_speed_spin.value()) if hasattr(self, "sim_speed_spin") else float(getattr(self, "_sim_speed", 1.0))
        except:
            sim_speed = float(getattr(self, "_sim_speed", 1.0))
        self._sim_speed = float(sim_speed)
        dt_eff = dt * sim_speed
        # Update all enabled beacons (single update, dt_eff scaled by sim_speed)
        for b in getattr(self, "beacons", [self.target]):
            if getattr(b, "enabled", True):
                b.update(dt_eff)
        # Keep target alias exactly as user-selected (realtime, not auto-switching to distractor)
        if hasattr(self, "beacons") and self.beacons:
            try:
                tid = int(self.target_beacon_spin.value()) if hasattr(self, "target_beacon_spin") else int(getattr(self, "_target_beacon_id", 0))
            except:
                tid = int(getattr(self, "_target_beacon_id", 0))
            tid = int(np.clip(tid, 0, len(self.beacons)-1))
            self._target_beacon_id = tid
            self.target = self.beacons[tid]
        # keep per-beacon X/Y spins in sync if beacons moved (optional live readout) — modular
        try:
            for idx, b in enumerate(getattr(self, "beacons", [])):
                panel = self.per_beacon_panels[idx] if idx < len(getattr(self, "per_beacon_panels", [])) else None
                if not panel:
                    continue
                if isinstance(panel, dict):
                    if not panel["x"].hasFocus() and not panel["y"].hasFocus():
                        panel["x"].blockSignals(True); panel["x"].setValue(int(b.x)); panel["x"].blockSignals(False)
                        panel["y"].blockSignals(True); panel["y"].setValue(int(b.y)); panel["y"].blockSignals(False)
                else:
                    # BeaconPanel object
                    if not panel.spin_x.hasFocus() and not panel.spin_y.hasFocus():
                        panel.spin_x.blockSignals(True); panel.spin_x.setValue(int(b.x)); panel.spin_x.blockSignals(False)
                        panel.spin_y.blockSignals(True); panel.spin_y.setValue(int(b.y)); panel.spin_y.blockSignals(False)
        except: pass
        try: self.scene.update(dt_eff)
        except: pass
        # Camera latency queue — advance time and execute due moves
        try:
            self.camera.update(dt)
        except: pass
        scene_frame=self.scene.get_frame()
        self._draw_targets(scene_frame)
        # Platform disturbances — dt_eff ensures sim-speed lockstep (fixes wall-clock decoupling)
        # All four disturbances now evolve with same sim-speed-scaled dt
        pan_vib, tilt_vib = dist.apply_platform_vibration(self.camera.pan, self.camera.tilt, self.sliders["Vibration"].value(), dt=dt_eff)
        pan_dist, tilt_dist = dist.apply_camera_motion_with_state(pan_vib, tilt_vib, self.sliders["Camera Motion"].value(), self._camera_drift_state, dt=dt_eff)
        rp, rt = self.camera.pan, self.camera.tilt
        self.camera.pan, self.camera.tilt = pan_dist, tilt_dist
        fov_frame=self.camera.capture(scene_frame)
        self.camera.pan, self.camera.tilt = rp, rt
        fov_frame=dist.apply_turbulence(fov_frame, self.sliders["Turbulence"].value(), dt=dt_eff)
        fov_frame=dist.apply_sensor_noise(fov_frame, self.sliders["Noise"].value())
        # ── Target-only realtime check (not hardcoded, hitbox-gated) ──
        all_dets = self.detector.detect_all(fov_frame)
        self._last_all_detections = all_dets
        fov_x0, fov_y0, _, _ = self.camera.get_fov_rect()
        primary = self.target
        # If target beacon itself is disabled, treat as not in viewport — ignore distractors
        if not getattr(primary, "enabled", True):
            detection = None
            proj_x = proj_y = float("nan")
            target_in_fov = False
        else:
            proj_x = primary.x - fov_x0
            proj_y = primary.y - fov_y0
            # Realtime hitbox-aware FOV test (large hitbox, not single pixel; dynamic per beacon)
            target_in_fov = (
                -primary.hitbox_radius <= proj_x <= self.camera.fov_width + primary.hitbox_radius and
                -primary.hitbox_radius <= proj_y <= self.camera.fov_height + primary.hitbox_radius
            )
            if not target_in_fov:
                # Target leaves viewport — do NOT bother with distractors, report miss
                detection = None
            else:
                # Target is in viewport — look ONLY for a detection inside its hitbox (realtime, per-beacon radius)
                # No hardcoded 40px or brightest fallback; purely hitbox-gated and distance-sorted
                detection = None
                best_hit = None
                min_dist = float("inf")
                for d in all_dets:
                    dist_c = math.hypot(d["x"] - proj_x, d["y"] - proj_y)
                    if dist_c <= primary.hitbox_radius and dist_c < min_dist:
                        min_dist = dist_c
                        best_hit = d
                        detection = (d["x"], d["y"])
                # Stats: hitbox vs perfect center (for analysis)
                if detection is not None:
                    if min_dist <= primary.hitbox_radius:
                        self._hitbox_hits += 1
                    if min_dist <= primary.center_radius:
                        self._center_hits += 1
                    self._frames_with_detections += 1
                else:
                    # Target in FOV but no blob inside its hitbox → true miss (even if distractors visible, ignore them)
                    detection = None
        estimate=self.tracker.update(detection)
        tracking_error_px=None
        # Error to perfect center (not hitbox edge) for precision metrics
        if estimate is not None:
            cx, cy = self.camera.fov_width/2, self.camera.fov_height/2
            err_x, err_y = estimate[0]-cx, estimate[1]-cy
            tracking_error_px=float(np.hypot(err_x, err_y))
            # Also compute to perfect center
            # Use center error for control — passes dt for slew/resolution/latency handling
            d_pan,d_tilt=self.controller.compute_correction(err_x, err_y)
            try:
                self.camera.move(d_pan, d_tilt, dt)
            except TypeError:
                # Back-compat fallback (PTZCamera without dt)
                self.camera.move(d_pan, d_tilt)
        is_locked=self.tracker.status==LockStatus.TRACKING
        # extended metrics for logger
        detected_any = len(all_dets) > 0 if 'all_dets' in locals() else False
        # hitbox/center hit based on last detection vs target
        hitbox_hit = False
        center_hit = False
        if 'detection' in locals() and detection is not None and 'primary' in locals():
            try:
                d = math.hypot(detection[0] - (primary.x - fov_x0), detection[1] - (primary.y - fov_y0))
                hitbox_hit = d <= primary.hitbox_radius
                center_hit = d <= primary.center_radius
            except: pass
        self.perf.log_frame(is_locked, tracking_error_px, time.time()-frame_start,
                            detected=detected_any, hitbox_hit=hitbox_hit, center_hit=center_hit,
                            lock_state=self.tracker.status.value)
        self._render_viewport(fov_frame, estimate, all_dets)
        self._render_minimap(scene_frame)
        self._update_stats(tracking_error_px)

    # ========================================================
    # SECTION: Rendering — delegated to gui.core.renderer.Renderer
    # ========================================================

    def _beacon_vibrant_color(self, beacon_id: int, brightness: float) -> tuple[int,int,int]:
        return Renderer.beacon_vibrant_color(beacon_id, brightness)

    def _draw_targets(self, scene_frame: np.ndarray):
        Renderer.draw_targets(scene_frame, getattr(self, "beacons", [self.target]), self.target)

    def _draw_target(self, scene_frame: np.ndarray):
        return self._draw_targets(scene_frame)

    def _draw_reticle(self, img, center, gap=10, arm=16, color=(255, 255, 255), thickness=1):
        return Renderer.draw_reticle(img, center, gap, arm, color, thickness)

    def _draw_corner_brackets(self, img, margin=6, length=10, color=(200, 200, 200), thickness=1):
        return Renderer.draw_corner_brackets(img, margin, length, color, thickness)

    def _render_viewport(self, fov_frame: np.ndarray, estimate, all_dets: list[dict] | None = None):
        # Overlay-aware — pulse animation + error units + camera scale
        pulse = 0.0
        try:
            pulse = self._overlay_pulse.update(self.tracker.status.value, getattr(self.overlay_config, "pulse_enabled", True), getattr(self.overlay_config, "pulse_duration_ms", 300))
        except: pass
        pixel_scale = 0.035
        try:
            pixel_scale = float(getattr(getattr(self, "camera", None).config, "pixel_scale_mrad", 0.035))
        except: pass
        try:
            overlay = getattr(self, "overlay_config", None)
            display = Renderer.render_viewport(fov_frame, self.camera, getattr(self, "beacons", [self.target]), self.target, self.tracker, all_dets, overlay=overlay, pulse_progress=pulse, pixel_scale_mrad=pixel_scale)
        except Exception:
            display = Renderer.render_viewport(fov_frame, self.camera, getattr(self, "beacons", [self.target]), self.target, self.tracker, all_dets)
        self._last_viewport_frame = display
        self._set_pixmap(self.viewport_label, display)

    def _render_minimap(self, scene_frame: np.ndarray):
        lw = self.minimap_label.width() if self.minimap_label.width()>10 else self._god_display_size[0]
        lh = self.minimap_label.height() if self.minimap_label.height()>10 else self._god_display_size[1]
        display = Renderer.render_minimap(scene_frame, self.camera, getattr(self, "beacons", [self.target]), self.target, self.tracker, (lw, lh), self._scene_size)
        self._last_god_frame = display
        self._set_pixmap(self.minimap_label, display)

    def _set_pixmap(self, label, bgr_frame: np.ndarray):
        # Delegate to Renderer (handles QImage copy + scaling)
        rgb = Renderer.set_pixmap(label, bgr_frame)
        self._last_rgb = rgb
        return rgb

    def _update_stats(self, tracking_error_px):
        # Delegate dashboard metrics to DashboardPanel (modular)
        s = self.perf.summary()
        try:
            if hasattr(self, "dashboard_panel"):
                self.dashboard_panel.update_from_summary(s, self.tracker.status.value, tracking_error_px)
            else:
                # Fallback legacy direct label updates
                for k in ["fps","simulation_duration_s","acquisition_time_s","avg_processing_time_ms","avg_tracking_error_px","max_tracking_error_px","tracking_error_pct","lock_retention_rate_pct","acquisitions","detection_rate_pct","detection_time_s","searching_rate_pct","searching_time_s","center_hit_rate_pct","center_hit_time_s"]:
                    if k in getattr(self, "stat_labels", {}):
                        self.stat_labels[k].setText(str(s.get(k, "-")))
                if "lock_status" in getattr(self, "stat_labels", {}):
                    self.stat_labels["lock_status"].setText(self.tracker.status.value)
        except: pass
        # Footer + statusBar — now with angular units (px/mrad/µrad) via camera scale + overlay
        try:
            col={"tracking":"#22c55e","acquired":"#06b6d4","lost":"#ef4444","searching":"#64748b"}[self.tracker.status.value]
            self.lock_dot.setStyleSheet(f"color:{col}; font-size:16px;")
            self.footer_lock.setText(self.tracker.status.value.upper())
            self.footer_lock.setStyleSheet(f"color:{col}; font-weight:700;")
            self.footer_fps.setText(f"FPS {s['fps']}  •  {s['frame_count']} frames  •  Det {s['detection_rate_pct']}%")
            pan,tilt=self.camera.pan,self.camera.tilt
            # Error label respects overlay error_units and camera pixel_scale
            err_label = "-"
            if tracking_error_px is not None:
                try:
                    units = getattr(getattr(self, "overlay_config", None), "error_units", "px")
                    scale = float(getattr(getattr(self.camera, "config", None), "pixel_scale_mrad", 0.035))
                    if units == "mrad":
                        err_label = f"{tracking_error_px*scale:.3f}mrad"
                    elif units == "urad":
                        err_label = f"{tracking_error_px*scale*1000:.0f}µrad"
                    elif units == "px+mrad":
                        err_label = f"{tracking_error_px:.1f}px {tracking_error_px*scale:.2f}mrad"
                    else:
                        err_label = f"{tracking_error_px:.1f}px"
                except:
                    err_label = f"{tracking_error_px:.1f}px"
            self.footer_info.setText(f"Pan {pan:.0f} Tilt {tilt:.0f}  •  Err {err_label}  •  RMS {s['rms_tracking_error_px']}  •  Jit {s['jitter_ms']}ms" if tracking_error_px is not None else f"Pan {pan:.0f} Tilt {tilt:.0f}  •  No lock  •  Jit {s['jitter_ms']}ms")
            self.statusBar().showMessage(f"{self.tracker.status.value.upper()}  •  FPS {s['fps']}  •  Err {err_label}  •  Det {s['detection_rate_pct']}%" if tracking_error_px is not None else f"{self.tracker.status.value.upper()}  •  FPS {s['fps']}  •  Det {s['detection_rate_pct']}%", 1500)
        except: pass

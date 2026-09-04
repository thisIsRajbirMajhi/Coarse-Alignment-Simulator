# gui/main_window.py - Main application window — orchestrates video, control panels, and simulation tic

import os
import math
import random
import time
from datetime import datetime 

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
from control.config import ControllerConfig
from control.controller import PIDController, ProportionalController
from detection.detector import BeaconDetector
from disturbance import disturbances as dist
from environment.config import EnvironmentConfig
from environment.constants import MAX_RES, MIN_RES
from environment.scene import Scene
from gui.core.renderer import Renderer
from gui.environment_panel import EnvironmentPanel
from gui.mixins.state_mixin import StateMixin
from gui.multi_beacon_panel import MultiBeaconPanel
from gui.panels.camera_panel import CameraPanel
from gui.panels.control_panel import ControlPanel
from gui.panels.dashboard_panel import DashboardPanel
from gui.panels.disturbances_panel import DisturbancesPanel
from gui.panels.global_panel import GlobalPanel
from gui.styles import APP_STYLE, FOV_SIZE, SCENE_SIZE, TICK_MS
from gui.windows.control_window import ControlDashboardWindow
from gui.windows.dashboard_window import DashboardWindow
from perf_log.metrics import PerformanceLogger
from target.config import MultiBeaconConfig
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
        self._platform_motion_state: dict = {}
        self._jitter_state: dict = {}
        self._scene_size = SCENE_SIZE
        self._fov_size = FOV_SIZE
        self._viewport_display_size = (400, 300)
        self._god_display_size = (400, 300)
        # Beacon/Target — simplified: only count and target index, fixed defaults
        self.beacon_config = MultiBeaconConfig(beacon_count=1, target_index=0).validate()
        self._beacon_count = int(self.beacon_config.beacon_count)
        self._hitbox_radius = 14
        self._center_radius = 2
        self._target_beacon_id = int(self.beacon_config.target_index)
        # Global tuning defaults — now fully configurable
        self._tracker_smoothing = 0.25
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
        # Controller — P/PI/PID, dead zone, clamp, update rate (robust, modular)
        self.controller_config = ControllerConfig().validate()
        # Disturbance & Noise — full spec suite (Image Noise, Jitter, Atmosphere, Platform Motion)
        from disturbance.config import DisturbanceConfig as _DC
        self.disturbance_config = _DC().validate()
        self._last_viewport_frame = None
        self._last_god_frame = None
        # Dirty tracking for Apply per-section (now auto-, but kept for Master confirm)
        self._dirty_tabs: set[str] = set()
        self._applied_snapshot: dict = {}
        # Debounced auto- timers per section (so every single spin is without spamming)
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

        # Initial dashboard populate so no field appears empty ("-" -> "— S")
        try:
            if hasattr(self, "dashboard_panel"):
                cam_scale = 0.035
                try:
                    if hasattr(self, "camera") and hasattr(self.camera, "config") and getattr(self.camera.config, "pixel_scale_mrad", None) is not None:
                        cam_scale = float(self.camera.config.pixel_scale_mrad)
                except Exception:
                    pass
                self.dashboard_panel.update_from_summary(self.perf.summary(), self.tracker.status.value, None, camera_scale_mrad=cam_scale)
        except Exception:
            pass

    def _build_simulation(self):
        speed = getattr(self, "_target_speed", 100)
        thresh = getattr(self, "_det_thresh", 200)
        gain = getattr(self, "_ctrl_gain", 0.15)
        # Global tuning — use live widget values if available, else stored defaults
        try:
            smoothing = float(self.tracker_smoothing_spin.value()) if hasattr(self, "tracker_smoothing_spin") else float(getattr(self, "_tracker_smoothing", 0.25))  # type: ignore
        except:
            smoothing = float(getattr(self, "_tracker_smoothing", 0.25))
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
        # Disturbances — collect validated DisturbanceConfig if panel available (single source)
        try:
            if hasattr(self, "disturbances_panel") and self.disturbances_panel is not None:
                dcfg = self.disturbances_panel.collect_config().validate()
                self.disturbance_config = dcfg
        except Exception:
            pass
        # Environment — collect validated config (panel if available, else env_config)
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

        # Camera — collect validated CameraConfig (11 params: FOV, mechanics, display, units)
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

        # Build scene via typed config
        self.scene = Scene(config=cfg)
        # Beacons — single panel, all beacons share same rules
        beacon_count = int(getattr(self, "_beacon_count", 1))
        hb = int(np.clip(14, 3, 80))
        cr = int(np.clip(2, 1, hb))
        tgt_id = int(getattr(self, "_target_beacon_id", 0))
        shape = "square"
        size_w = 10
        size_h = 10
        blinking = False
        speed_random = False
        tgt_x = None
        tgt_y = None
        try:
            if hasattr(self, "beacon_manager") and self.beacon_manager is not None:
                multi_cfg = self.beacon_manager.collect_multi_config().validate()
                self.beacon_config = multi_cfg
                beacon_count = int(multi_cfg.beacon_count)
                tgt_id = int(multi_cfg.target_index)
                shape = str(getattr(multi_cfg, "shape", "square"))
                size_w = int(getattr(multi_cfg, "size_w", 10))
                size_h = int(getattr(multi_cfg, "size_h", 10))
                blinking = bool(getattr(multi_cfg, "blinking", False))
                speed_random = bool(getattr(multi_cfg, "speed_random", False))
                tgt_x = float(getattr(multi_cfg, "x", 2500))
                tgt_y = float(getattr(multi_cfg, "y", 2500))
                try:
                    profile = multi_cfg.profile
                except: pass
                speed = float(getattr(multi_cfg, "speed", speed))
            elif hasattr(self, "beacon_config"):
                multi_cfg = self.beacon_config.validate()
                beacon_count = int(multi_cfg.beacon_count)
                tgt_id = int(multi_cfg.target_index)
                shape = str(getattr(multi_cfg, "shape", shape))
                size_w = int(getattr(multi_cfg, "size_w", size_w))
                size_h = int(getattr(multi_cfg, "size_h", size_h))
                blinking = bool(getattr(multi_cfg, "blinking", blinking))
                speed_random = bool(getattr(multi_cfg, "speed_random", speed_random))
                tgt_x = float(getattr(multi_cfg, "x", 2500)) if beacon_count == 1 else None
                tgt_y = float(getattr(multi_cfg, "y", 2500)) if beacon_count == 1 else None
        except Exception:
            pass
        base_seed = int(cfg.seed) + int(self.perf.frame_count if hasattr(self, "perf") else 0) % 997 if 'cfg' in locals() else 42
        self.beacons: list[Target] = create_beacons(beacon_count, (scene_w, scene_h), profile, speed,
                                                     seed=base_seed, hitbox_radius=hb, center_radius=cr,
                                                     brightness=g_bright, radius=g_radius,
                                                     shape=shape, size_w=size_w, size_h=size_h, blinking=blinking,
                                                     x=tgt_x if beacon_count == 1 else None, y=tgt_y if beacon_count == 1 else None,
                                                     speed_random=speed_random)
        tgt_id = int(np.clip(int(tgt_id), 0, max(0, len(self.beacons)-1)))
        self._target_beacon_id = int(tgt_id)
        self._beacon_count = int(beacon_count)
        self._hitbox_radius = int(hb); self._center_radius = int(cr)
        self.beacon_config = MultiBeaconConfig(beacon_count=len(self.beacons), target_index=int(tgt_id), shape=shape, size_w=size_w, size_h=size_h, x=float(tgt_x) if tgt_x is not None else 2500, y=float(tgt_y) if tgt_y is not None else 2500, profile=str(profile) if isinstance(profile, str) else profile.value if hasattr(profile, 'value') else "curved", speed=float(speed), blinking=bool(blinking), speed_random=bool(speed_random)).validate()
        self.target = self.beacons[tgt_id] if self.beacons else self.beacons[0]
        # Camera — full mechanics (slew, resolution, latency, ranges, home, optics)
        self.camera = PTZCamera(config=cam_cfg, scene_bounds=(scene_w, scene_h))
        # Sync vignetting (camera image-space, follows FOV — not world)
        try:
            vig = float(getattr(cfg, 'vignetting_pct', 0) if 'cfg' in locals() else getattr(self.env_config, 'vignetting_pct', 0)) / 100.0
            self.camera.set_vignetting(vig)
        except:
            pass
        self.detector = BeaconDetector(brightness_threshold=thresh, min_area=min_area)
        self.tracker = Tracker(smoothing=smoothing, miss_limit=miss_limit)
        # Controller — P/PI/PID with dead zone, clamp, update rate (robust, modular)
        # Collect from ControlPanel if UI exists, else from stored controller_config
        try:
            if hasattr(self, "control_panel") and self.control_panel is not None:
                ctrl_cfg = self.control_panel.collect_config().validate()
                self.controller_config = ctrl_cfg
            else:
                ctrl_cfg = self.controller_config.validate()
                # Also sync legacy gain variable if present (old _ctrl_gain)
                try:
                    if 'gain' in locals():
                        ctrl_cfg.kp = float(gain)
                        ctrl_cfg.validate()
                        self.controller_config = ctrl_cfg
                except: pass
        except Exception:
            ctrl_cfg = self.controller_config.validate()
        # Sync camera panel gain alias for backward compat (if exists)
        try:
            if hasattr(self, "camera_panel") and hasattr(self.camera_panel, "gain_spin"):
                self.camera_panel.gain_spin.blockSignals(True)
                self.camera_panel.gain_spin.setValue(float(np.clip(ctrl_cfg.kp, 0.02, 0.50)))
                self.camera_panel.gain_slider.blockSignals(True)
                self.camera_panel.gain_slider.setValue(int(round(float(ctrl_cfg.kp)*100)))
                self.camera_panel.gain_spin.blockSignals(False)
                self.camera_panel.gain_slider.blockSignals(False)
        except: pass
        self.controller = PIDController(config=ctrl_cfg)
        # store sim speed for tick
        self._sim_speed = float(sim_speed)
        if not hasattr(self, "perf"):
            self.perf = PerformanceLogger()
        self._camera_drift_state = {}
        # Minimap cache — pre-resized thumb of static background (avoids 5000×5000 copy+resize each tick)
        self._minimap_thumb: np.ndarray | None = None
        self._minimap_thumb_size: tuple[int,int] | None = None
        self._minimap_scene_id: int | None = None
        # P1 Autonomous search scanner — moves camera randomly when SEARCHING/LOST until target found
        # Uses SearchingStrategy random pattern, respects camera slew via camera.move(d_pan,d_tilt,dt)
        try:
            from searching.scanner import Scanner, ScanPattern
            from searching.config import SearchingConfig
            # P2 fix: force random per spec (was spiral default causing center shake)
            # Random waypoint pursuit moves gradually toward uniform waypoints, not small spiral jitter
            s_cfg = SearchingConfig().validate()
            pat = "random"  # force random per user spec: must move gradually until found
            self.scanner = Scanner(pattern=pat, scan_radius=120.0, dwell_frames=1, seed=int(getattr(self.env_config, "seed", 42) or 42) + 7919)
            self._last_search_status = None
            self._last_est_world = None
        except Exception:
            self.scanner = None
            self._last_search_status = None
            self._last_est_world = None

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

        def _make_camera_card(title_text: str, res_text: str, is_primary: bool):
            card = QFrame()
            card.setObjectName("cameraCard")
            card_layout = QVBoxLayout(card)
            card_layout.setContentsMargins(0, 0, 0, 0)
            card_layout.setSpacing(0)

            # Header — refined light with monochrome type hint
            card_hdr = QFrame()
            card_hdr.setObjectName("cameraCardHeader")
            card_hdr.setFixedHeight(42)
            h = QHBoxLayout(card_hdr)
            h.setContentsMargins(12, 8, 12, 8)
            h.setSpacing(8)
            title_col = QVBoxLayout()
            title_col.setSpacing(1)
            ttl = QLabel(title_text)
            ttl.setObjectName("cameraTitle")
            title_col.addWidget(ttl)
            sub = QLabel("Monochrome Focal Plane Array" if is_primary else "Overview — World Size")
            sub.setStyleSheet("color:#6b7280; font-size:9px; background: transparent;")
            title_col.addWidget(sub)
            h.addLayout(title_col)
            h.addStretch()
            live = QLabel("LIVE")
            live.setObjectName("liveBadge")
            live.setProperty("active", False)
            card._live_badge = live  # type: ignore
            h.addWidget(live)
            # Resolution badge hidden per spec — keep for compat but not visible
            res = QLabel(res_text)
            res.setObjectName("resBadge")
            res.hide()
            card._res_badge = res  # type: ignore
            card_layout.addWidget(card_hdr)

            # Video viewport — pitch black with thin monochrome frame
            wrap = QFrame()
            wrap.setObjectName("videoFrameWrap")
            wrap.setStyleSheet("QFrame#videoFrameWrap { background: #000000; border: 1px solid #1f2937; border-radius: 4px; }")
            wl = QVBoxLayout(wrap)
            wl.setContentsMargins(1, 1, 1, 1)
            wl.setSpacing(0)
            vid = QLabel()
            vid.setObjectName("videoFeed")
            vid.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
            vid.setAlignment(Qt.AlignCenter)
            vid.setScaledContents(False)
            vid.setMinimumSize(260, 260)
            vid.setStyleSheet("QLabel#videoFeed { background: #000000; border: none; color: #6b7280; }")
            wl.addWidget(vid, 1)
            card_layout.addWidget(wrap, 1)

            # Footer — minimal, hidden per spec (no in-screen details)
            foot = QFrame()
            foot.setObjectName("cameraCardFooter")
            foot.setFixedHeight(22)
            fl = QHBoxLayout(foot)
            fl.setContentsMargins(10, 4, 10, 4)
            fl.setSpacing(8)
            info = QLabel("—")
            info.setStyleSheet("color:#6b7280; font-size:10px; font-family:'Consolas','Courier New',monospace; background: transparent; border: none;")
            info.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
            card._footer_info = info  # type: ignore
            fl.addWidget(info, 1)
            hint = QLabel("30 Hz" if is_primary else "5000 x 5000")
            hint.setStyleSheet("color:#9ca3af; font-size:9px; background: transparent;")
            fl.addWidget(hint)
            foot.hide()
            card_layout.addWidget(foot)

            return card, vid, res, live, info, foot

        # Camera (monochrome) — 640x640 default, FOV 4x3 deg
        fov_card, self.viewport_label, self.fov_res_lbl, self._fov_live_badge, self._fov_footer_info, self._fov_footer = _make_camera_card("Camera", f"{self._fov_size[0]}x{self._fov_size[1]}", True)
        # God View — size = World (2000..5000 configurable per PDF)
        god_card, self.minimap_label, self.god_res_lbl, self._god_live_badge, self._god_footer_info, self._god_footer = _make_camera_card("God View", "5000x5000", False)

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
        self.global_panel.thresh_slider.valueChanged.connect(self._on_thresh_change)
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
        # Tuning: threshold in beacon panel controls detector
        try:
            self.beacon_manager.threshChanged.connect(self._on_thresh_change)
            # Keep global hidden thresh in sync for compat
            self.beacon_manager.threshChanged.connect(lambda v: (self.thresh_slider.blockSignals(True), self.thresh_slider.setValue(int(v)), self.thresh_slider.blockSignals(False)))
            # Also sync global motion/speed to beacon motion for single-panel consistency
            self.beacon_manager.multiConfigChanged.connect(self._sync_beacon_to_global)
        except: pass
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
        self.pan_speed_deg_spin = getattr(self.camera_panel, 'pan_speed_deg_spin', self.slew_spin)
        self.tilt_speed_deg_spin = getattr(self.camera_panel, 'tilt_speed_deg_spin', self.slew_spin)
        self.update_rate_spin = getattr(self.camera_panel, 'update_rate_spin', None)
        self.res_spin = self.camera_panel.res_spin
        self.latency_spin = self.camera_panel.latency_spin
        self.scale_spin = self.camera_panel.scale_spin
        self._cam_gain_box = None
        # wiring — debounced (single signal covers all 11 params + gain)
        self.camera_panel.configChanged.connect(lambda: self._schedule_auto("camera", self._apply_camera_hot, 420))
        tabs.addTab(self.camera_panel, "Camera")

        # ── Control Tab — Modular (P/PI/PID, dead zone, clamp, update rate) ──
        self.control_panel = ControlPanel(initial=self.controller_config)
        tabs.addTab(self.control_panel, "Control")
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
        # Panel's configChanged is throttled — keep dirty tracking + auto-
        self.env_panel.configChanged.connect(lambda cfg: self._on_env_config_changed(cfg))
        # Also keep camera dirty when world size changes (affects FOV clamping)
        for w in [self.scene_w_spin, self.scene_h_spin]:
            try: w.valueChanged.connect(lambda _, s="camera": self._mark_dirty(s))
            except: pass
        env_layout.addStretch()
        tabs.addTab(env_tab, "Environment")

        # ── Disturbances Tab — Modular (DisturbancesPanel, full spec) ──
        # Image Noise (S&P 10%, Gaussian, Poisson multi) + Max StdDev 20+User + Jitter ±20 + Atmosphere 6 presets + Platform 7 profiles
        try:
            from disturbance.config import DisturbanceConfig as _DC2
            init_dc = getattr(self, "disturbance_config", _DC2().validate())
        except:
            init_dc = None
        self.disturbances_panel = DisturbancesPanel(initial=init_dc)
        self.sliders = self.disturbances_panel.sliders
        # Wire configChanged → disturbance dirty + auto (debounced)
        try:
            self.disturbances_panel.configChanged.connect(self._on_disturbance_config_changed)
        except: pass
        tabs.addTab(self.disturbances_panel, "Disturbances")

        # initial snapss for dirty tracking ()
        for sec in ["global", "beacons", "camera", "control", "environment", "disturbances"]:
            try: self._snapshot_section(sec)
            except: pass

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
            except: pass
        for panel in getattr(self, "per_beacon_panels", []):
            try:
                if isinstance(panel, dict):
                    panel["x"].setRange(0, w)
                    panel["y"].setRange(0, h)
                else:
                    panel.set_world_bounds(self._scene_size)
            except: pass

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
        # No external metric updates — dashboard handles all via _update_stats

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
        val.setStyleSheet("color:#111827; font-weight:600; background:#f9fafb; border:1px solid #e5e7eb; border-radius:4px; padding:2px;")
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
        """Immediate handler — panel emitted a validated EnvironmentConfig."""
        try:
            cfg = cfg.validate()
            self.env_config = cfg
            self._scene_size = (int(cfg.world_width), int(cfg.world_height))
        except Exception:
            pass
        self._mark_dirty("environment")
        # Debounced apply (520ms) — every single spin is without spamming
        self._schedule_auto("environment", self._apply_scene_settings_hot, 520)

    def _on_disturbance_config_changed(self, cfg):
        """Immediate handler — DisturbancesPanel emitted validated DisturbanceConfig (full spec)."""
        try:
            cfg = cfg.validate() if hasattr(cfg, "validate") else cfg
            self.disturbance_config = cfg
        except Exception:
            pass
        self._mark_dirty("disturbances")
        self._schedule_auto("disturbances", self._apply_disturbances_hot, 120)

    def _apply_disturbances_hot(self):
        """Apply disturbances — , validates, snapss, no rebuild needed."""
        try:
            if hasattr(self, "disturbances_panel"):
                cfg = self.disturbances_panel.collect_config().validate()
                self.disturbance_config = cfg
            else:
                cfg = self.disturbance_config.validate()
            self._clear_dirty("disturbances")
            self._snapshot_section("disturbances")
            # Summary for status bar
            parts = []
            if cfg.turbulence or cfg.vibration or cfg.camera_motion or cfg.noise:
                parts.append(f"Legacy T{cfg.turbulence} V{cfg.vibration} C{cfg.camera_motion} N{cfg.noise}")
            if cfg.image_noise_enabled():
                en = []
                if cfg.enable_salt_pepper: en.append(f"S&P{cfg.salt_pepper_density*100:.0f}%")
                if cfg.enable_gaussian: en.append(f"Gaussσ{cfg.gaussian_sigma:.0f}")
                if cfg.enable_poisson: en.append("Poisson")
                parts.append("Img: " + "+".join(en) + f" maxσ{cfg.gaussian_sigma_max:.0f}")
            if cfg.camera_jitter > 0:
                parts.append(f"Jitter±{cfg.camera_jitter:.1f}px")
            if str(cfg.atmospheric_preset) != "Clear":
                parts.append(f"Atmo {cfg.atmospheric_preset} C{cfg.atmospheric_contrast:.0f}% B{cfg.atmospheric_brightness:.0f}%")
            if cfg.platform_speed > 0:
                parts.append(f"Plat {cfg.platform_profile} {cfg.platform_speed:.1f}px/f")
            msg = "Disturbances — " + " • ".join(parts) if parts else "Disturbances — pristine (Clear)"
            self.statusBar().showMessage(msg, 2500)
        except Exception as e:
            QMessageBox.warning(self, "Disturbances", f"Failed: {e}")

    def _on_control_config_changed(self, cfg):
        """ handler — ControlPanel emitted validated ControllerConfig."""
        try:
            cfg = cfg.validate()
            self.controller_config = cfg
            # Apply to live controller without rebuild
            if hasattr(self, "controller"):
                self.controller.apply_config(cfg)
        except Exception:
            pass
        self._mark_dirty("control")
        self._schedule_auto("control", self._apply_control_hot, 80)

    def _apply_control_hot(self):
        """Apply controller config — , validates, syncs gain alias, snapss."""
        try:
            if hasattr(self, "control_panel"):
                cfg = self.control_panel.collect_config().validate()
                self.controller_config = cfg
            else:
                cfg = self.controller_config.validate()
            self.controller.apply_config(cfg)
            # Sync camera gain alias (bidirectional, but avoid loop)
            try:
                if hasattr(self, "camera_panel"):
                    self.camera_panel.gain_spin.blockSignals(True)
                    self.camera_panel.gain_spin.setValue(float(np.clip(cfg.kp, 0.02, 0.50)))
                    self.camera_panel.gain_slider.blockSignals(True)
                    self.camera_panel.gain_slider.setValue(int(round(float(cfg.kp)*100)))
                    self.camera_panel.gain_spin.blockSignals(False)
                    self.camera_panel.gain_slider.blockSignals(False)
            except: pass
            self._clear_dirty("control")
            self._snapshot_section("control")
            self.statusBar().showMessage(f"Control — {cfg.controller_type} Kp {cfg.kp:.3f} Ki {cfg.ki:.3f} Kd {cfg.kd:.3f} dead {cfg.dead_zone:.1f}px clamp {cfg.output_clamp:.0f}px rate {cfg.update_rate_hz:.0f}Hz", 2000)
        except Exception as e:
            QMessageBox.warning(self, "Control", f"Failed: {e}")

    def _sync_control_gain_to_camera(self, v: float) -> None:
        # Control Kp → Camera gain alias (no loop)
        try:
            if hasattr(self, "camera_panel"):
                self.camera_panel.gain_spin.blockSignals(True)
                self.camera_panel.gain_spin.setValue(float(np.clip(float(v), 0.02, 0.50)))
                self.camera_panel.gain_slider.blockSignals(True)
                self.camera_panel.gain_slider.setValue(int(round(float(v)*100)))
                self.camera_panel.gain_spin.blockSignals(False)
                self.camera_panel.gain_slider.blockSignals(False)
        except: pass

    def _sync_camera_gain_to_control(self, v: float) -> None:
        # Camera gain → Control Kp
        try:
            if hasattr(self, "control_panel"):
                self.control_panel.kp_spin.blockSignals(True)
                self.control_panel.kp_spin.setValue(float(v))
                self.control_panel.kp_spin.blockSignals(False)
                # Also sync gain alias
                self.control_panel.gain_spin.blockSignals(True)
                self.control_panel.gain_spin.setValue(float(np.clip(float(v), 0.02, 0.50)))
                self.control_panel.gain_spin.blockSignals(False)
                # Update controller directly for immediate response
                if hasattr(self, "controller"):
                    self.controller.config.kp = float(v)
        except: pass
        # Mark dirty for 
        self._mark_dirty("control")
        self._schedule_auto("control", self._apply_control_hot, 80)

    def _update_beacon_count_label(self, v: int):
        try:
            tgt = int(getattr(self, "target_beacon_spin", self).value()) if hasattr(self, "target_beacon_spin") else int(getattr(self, "_target_beacon_id", 0))
            self.beacon_count_label.setText(f"{v} beacon{'s' if v!=1 else ''}, Target #{tgt}")
        except:
            try: self.beacon_count_label.setText(f"{v} beacon{'s' if v!=1 else ''}")
            except: pass

    def _on_hitbox_change(self, _v=None):
        pass

    def _on_beacon_count_changed(self, v: int):
        try:
            self.target_beacon_spin.setMaximum(max(0, v - 1))
            if self.target_beacon_spin.value() >= v:
                self.target_beacon_spin.setValue(v - 1)
            self._update_beacon_count_label(v)
        except: pass

    def _on_target_beacon_change(self, idx: int):
        try:
            idx = int(np.clip(int(idx), 0, max(0, len(getattr(self, "beacons", [])) - 1)))
            self._target_beacon_id = idx
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
                try: self.tracker = Tracker(smoothing=0.25, miss_limit=5)
                except: pass
                self.statusBar().showMessage(f"Target -> Beacon #{idx}", 2500)
                try:
                    if hasattr(self, "beacon_manager"):
                        self.beacon_manager._update_status()
                except: pass
        except: pass

    def _on_multi_beacon_config_changed(self, cfg):
        try:
            cfg = cfg.validate() if hasattr(cfg, "validate") else cfg
            self.beacon_config = cfg
            self._beacon_count = int(cfg.beacon_count)
            self._target_beacon_id = int(cfg.target_index)
            self._mark_dirty("beacons")
            self._schedule_auto("beacons", self._apply_beacons_hot, 400)
            try:
                self._schedule_auto("beacons_highlight", lambda: self._on_target_beacon_change(int(cfg.target_index)), 80)
            except: pass
        except:
            try: self._schedule_auto("beacons", self._apply_beacons_hot, 400)
            except: pass

    def _sync_beacon_to_global(self, cfg):
        try:
            # Keep hidden global motion/speed in sync with beacon panel (single source)
            cfg = cfg.validate() if hasattr(cfg, "validate") else cfg
            # Map beacon profile to global MotionProfile string
            rev = {"linear": "linear", "curved": "curved", "figure_eight": "figure_eight", "spiral": "spiral", "sinusoidal": "sinusoidal", "zigzag": "zigzag", "random": "curved"}
            prof = rev.get(str(getattr(cfg, "profile", "curved")).lower(), "curved")
            if hasattr(self, "motion_combo"):
                self.motion_combo.blockSignals(True)
                idx = self.motion_combo.findText(prof)
                if idx >= 0:
                    self.motion_combo.setCurrentIndex(idx)
                else:
                    self.motion_combo.setCurrentText(prof)
                self.motion_combo.blockSignals(False)
            if hasattr(self, "speed_slider"):
                self.speed_slider.blockSignals(True)
                self.speed_slider.setValue(int(getattr(cfg, "speed", 60)))
                if hasattr(self.speed_slider, "_value_label"):
                    self.speed_slider._value_label.setText(str(int(getattr(cfg, "speed", 60))))
                self.speed_slider.blockSignals(False)
        except: pass

    def _apply_beacon_configs_hot(self):
        try:
            self._clear_dirty("beacons")
            self._snapshot_section("beacons")
        except: pass

    def _apply_beacons(self):
        if hasattr(self, "beacon_manager") and self.beacon_manager is not None:
            try:
                multi_cfg = self.beacon_manager.collect_multi_config().validate()
                self.beacon_config = multi_cfg
                was_running = getattr(self, "_running", False)
                if was_running: self._pause()
                profile = str(getattr(multi_cfg, "profile", "curved"))
                speed = float(getattr(multi_cfg, "speed", 60))
                shape = str(getattr(multi_cfg, "shape", "square"))
                size_w = int(getattr(multi_cfg, "size_w", 10))
                size_h = int(getattr(multi_cfg, "size_h", 10))
                blinking = bool(getattr(multi_cfg, "blinking", False))
                speed_random = bool(getattr(multi_cfg, "speed_random", False))
                tgt_x = float(getattr(multi_cfg, "x", 2500)) if multi_cfg.beacon_count == 1 else None
                tgt_y = float(getattr(multi_cfg, "y", 2500)) if multi_cfg.beacon_count == 1 else None
                scene_w, scene_h = self._scene_size
                seed = int(self.seed_spin.value()) + int(time.time()) % 1000 if hasattr(self, "seed_spin") else 42
                self.beacons = create_beacons(int(multi_cfg.beacon_count), (scene_w, scene_h), profile, speed,
                                               seed=seed, hitbox_radius=14, center_radius=2, shape=shape, size_w=size_w, size_h=size_h, blinking=blinking, x=tgt_x, y=tgt_y, speed_random=speed_random)
                tid = int(np.clip(int(multi_cfg.target_index), 0, max(0, len(self.beacons)-1)))
                self._target_beacon_id = tid; self._beacon_count = int(multi_cfg.beacon_count)
                self.target = self.beacons[tid] if self.beacons else self.beacons[0]
                self.statusBar().showMessage(f"Beacons: {self._beacon_count} Target #{tid} {shape} {size_w}x{size_h}", 3000)
                try: self.tracker = Tracker(smoothing=0.25, miss_limit=5)
                except: pass
                self._rebuild_per_beacon_panels()
                try: self._on_target_beacon_change(tid)
                except: pass
                if was_running: self._start()
                return
            except Exception:
                pass
        try:
            self._beacon_count = int(self.beacon_count_spin.value())
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
        try: self.tracker = Tracker(smoothing=0.25, miss_limit=5)
        except: pass
        self._rebuild_per_beacon_panels()
        # highlight target
        try: self._on_target_beacon_change(tid)
        except: pass
        if was_running: self._start()

    def _apply_beacons_hot(self):
        try:
            if hasattr(self, "beacon_manager") and self.beacon_manager is not None:
                multi_cfg = self.beacon_manager.collect_multi_config().validate()
                self.beacon_config = multi_cfg
                self._beacon_count = int(multi_cfg.beacon_count)
                tid = int(multi_cfg.target_index)
                profile = str(getattr(multi_cfg, "profile", "curved"))
                speed = float(getattr(multi_cfg, "speed", 60))
                shape = str(getattr(multi_cfg, "shape", "square"))
                size_w = int(getattr(multi_cfg, "size_w", 10))
                size_h = int(getattr(multi_cfg, "size_h", 10))
                blinking = bool(getattr(multi_cfg, "blinking", False))
                speed_random = bool(getattr(multi_cfg, "speed_random", False))
                tgt_x = float(getattr(multi_cfg, "x", 2500)) if multi_cfg.beacon_count == 1 else None
                tgt_y = float(getattr(multi_cfg, "y", 2500)) if multi_cfg.beacon_count == 1 else None
                scene_w, scene_h = self._scene_size
                seed = int(self.seed_spin.value()) + int(time.time()) % 1000 if hasattr(self, "seed_spin") else 42
                self.beacons = create_beacons(self._beacon_count, (scene_w, scene_h), profile, speed,
                                               seed=seed, hitbox_radius=14, center_radius=2, shape=shape, size_w=size_w, size_h=size_h, blinking=blinking, x=tgt_x, y=tgt_y, speed_random=speed_random)
                tid = int(np.clip(int(tid), 0, max(0, len(self.beacons)-1)))
                self._target_beacon_id = tid
                self.target = self.beacons[tid] if self.beacons else self.beacons[0]
                try: self.tracker = Tracker(smoothing=0.25, miss_limit=5)
                except: pass
                self._rebuild_per_beacon_panels()
                try: self._on_target_beacon_change(tid)
                except: pass
                self.statusBar().showMessage(f"Beacons — {self._beacon_count} {shape} {size_w}x{size_h} Target #{tid}", 2000)
                try: self._snapshot_section("beacons"); self._clear_dirty("beacons")
                except: pass
                return
        except Exception:
            pass
        try:
            self._beacon_count = int(self.beacon_count_spin.value())
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
        try: self.tracker = Tracker(smoothing=0.25, miss_limit=5)
        except: pass
        self._rebuild_per_beacon_panels()
        try: self._on_target_beacon_change(tid)
        except: pass
        self.statusBar().showMessage(f"Beacons — {self._beacon_count} beacons Target #{tid} (auto)", 2000)
        try: self._snapshot_section("beacons"); self._clear_dirty("beacons")
        except: pass

    def _rebuild_per_beacon_panels(self):
        # Single panel — no per-beacon rebuild needed, keep current beacon config
        try:
            if hasattr(self, "beacon_manager"):
                self.beacon_manager._update_status()
        except: pass

    def _create_single_beacon_panel(self, idx, beacon):
        return QGroupBox(f"Beacon #{idx}")

    def _on_per_beacon_enabled(self, idx, checked): pass
    def _on_per_beacon_profile(self, idx, txt): pass
    def _on_per_beacon_speed(self, idx, v): pass
    def _on_per_beacon_brightness(self, idx, v): pass
    def _on_per_beacon_radius(self, idx, v): pass
    def _on_per_beacon_hitbox(self, idx, v): pass
    def _on_per_beacon_center(self, idx, v): pass
    def _on_per_beacon_x(self, idx, v): pass
    def _on_per_beacon_y(self, idx, v): pass
    def _on_per_beacon_heading(self, idx, deg): pass
    def _randomize_single_beacon_pos(self, idx): pass
    def _randomize_all_beacons(self):
        try:
            import random
            # Randomize all beacon parameters via panel
            if hasattr(self, "beacon_manager"):
                bm = self.beacon_manager
                # Random shape
                try:
                    bm.combo_shape.setCurrentIndex(random.randint(0, bm.combo_shape.count()-1))
                except: pass
                try:
                    bm.spin_size_w.setValue(random.randint(5, 20))
                    bm.spin_size_h.setValue(random.randint(2, 20))
                except: pass
                try:
                    bm.spin_x.setValue(random.randint(200, 4800))
                    bm.spin_y.setValue(random.randint(200, 4800))
                except: pass
                try:
                    bm.combo_motion.setCurrentIndex(random.randint(0, bm.combo_motion.count()-1))
                except: pass
                try:
                    bm.spin_speed.setValue(random.randint(20, 150))
                    bm.chk_random_speed.setChecked(random.choice([True, False]))
                except: pass
                try:
                    bm.chk_blinking.setChecked(random.choice([True, False]))
                except: pass
                self.statusBar().showMessage(f"Randomized parameters for {len(getattr(self,'beacons',[]))} beacons", 2500)
                return
            # Fallback: randomize live beacons directly
            import random as _rnd
            for b in getattr(self, "beacons", []):
                try:
                    b.profile = _rnd.choice(list(MotionProfile))
                except: pass
                try:
                    b.shape = _rnd.choice(["square", "circle"])
                    b.size_w = _rnd.randint(5, 20)
                    b.size_h = _rnd.randint(2, 20)
                    b.speed = float(_rnd.randint(20, 150))
                    b.blinking = _rnd.choice([True, False])
                    b.randomize_position(seed=int(_rnd.randint(0, 999999)))
                except:
                    try:
                        b.x = float(_rnd.uniform(60, self._scene_size[0]-60))
                        b.y = float(_rnd.uniform(60, self._scene_size[1]-60))
                    except: pass
            self.statusBar().showMessage(f"Randomized parameters for {len(self.beacons)} beacons", 2500)
        except: pass

    def _randomize_beacon_motion(self):
        try:
            import random
            if hasattr(self, "beacon_manager"):
                bm = self.beacon_manager
                bm.combo_motion.setCurrentIndex(random.randint(0, bm.combo_motion.count()-1))
                self.statusBar().showMessage(f"Randomized motion for {len(getattr(self,'beacons',[]))} beacons", 2500)
                return
            import random as _rnd
            for b in getattr(self, "beacons", []):
                try:
                    b.profile = _rnd.choice(list(MotionProfile))
                    b.randomize_position(seed=int(_rnd.randint(0, 999999)))
                except: pass
            self.statusBar().showMessage(f"Randomized motion for {len(self.beacons)} beacons", 2500)
        except: pass
    def _on_per_beacon_apply(self, idx): pass

    # ── Per-section Apply / Discard + Master ──
    # NOTE: State handling (dirty//snaps) delegated to gui.mixins.state_mixin.StateMixin
    # Methods inherited: _mark_dirty, _clear_dirty, _apply_section, _discard_section,
    # _master_apply_all, _master_discard_all, _snapshot_section, _schedule_auto

    def _apply_scene_settings_hot(self):
        """ — applies Environment from EnvironmentPanel + EnvironmentConfig (modular, no pause)."""
        # Collect validated EnvironmentConfig (single source of truth)
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
            self.statusBar().showMessage(f"Large world {sw}×{sh} = {sw*sh/1e6:.1f} MP — cached thumb active", 3000)
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
        try:
            self._invalidate_minimap_cache()
        except: pass
        # Camera — update scene bounds and re-validate ranges/home against new world (modular)
        # Sync vignetting (camera image-space) from env config to camera
        try:
            vig = float(cfg.vignetting_pct) / 100.0 if 'cfg' in locals() else float(getattr(self.env_config, 'vignetting_pct', 0)) / 100.0
            self.camera.set_vignetting(vig)
        except:
            pass
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
            try:
                if hasattr(b, "set_bounds"):
                    b.set_bounds((sw, sh))
                else:
                    b.bounds = (sw, sh)
                    b.x = float(np.clip(b.x, 0, sw)); b.y = float(np.clip(b.y, 0, sh))
            except Exception:
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
            self.statusBar().showMessage(f"Environment/Camera — world {sw}x{sh} FOV {self.camera_config.fov_width}x{self.camera_config.fov_height} pan {self.camera_config.pan_min}:{self.camera_config.pan_max} scale {cam_scale:.3f}mrad/px", 3000)
        except:
            self.statusBar().showMessage(f"Environment/Camera applied — world {sw}x{sh} FOV {fw}x{fh}", 3000)

    def _apply_camera_hot(self):
        """ — apply full CameraConfig (11 params: FOV, mechanics, display, units + gain)."""
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
            fw_raw, fh_raw = fw, fh
            fw = min(fw, sw-10); fh = min(fh, sh-10)
            if fw<20: fw=20
            if fh<20: fh=20
            if fw != fw_raw or fh != fh_raw:
                self.statusBar().showMessage(f"FOV {fw_raw}x{fh_raw} clipped to {fw}x{fh} to fit world {sw}x{sh}", 3000)
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
            self.statusBar().showMessage(f"Camera — FOV {fw}x{fh} pan [{int(cam_cfg.pan_min or 0)}:{int(cam_cfg.pan_max or sw)}] slew {cam_cfg.max_slew_rate:.0f}px/s lat {cam_cfg.latency_ms}ms scale {scale:.3f}mrad/px gain {self.controller.gain:.2f}", 3000)
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
            self.statusBar().showMessage(f"Large world {sw}×{sh} = {total_px/1e6:.1f} MP — cached thumb active", 3000)
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
        try:
            self._invalidate_minimap_cache()
        except: pass
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
            try:
                if hasattr(b, "set_bounds"):
                    b.set_bounds((sw, sh))
                else:
                    b.bounds = (sw, sh)
                    b.x = float(np.clip(b.x, 0, sw)); b.y = float(np.clip(b.y, 0, sh))
            except Exception:
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
            # FIX: use monotonic pause offset via logger.adjust_for_pause; start fresh if never started
            if self.perf.start_time is None and getattr(self.perf, "_start_mono", None) is None:
                # capture config snapshot for reproducibility
                try:
                    cfg_snap = {}
                    if hasattr(self, "env_config"):
                        cfg_snap.update({f"env_{k}": v for k, v in self.env_config.to_dict().items()})
                    if hasattr(self, "camera_config"):
                        cfg_snap.update({f"cam_{k}": v for k, v in self.camera_config.to_dict().items()})
                    if hasattr(self, "controller_config"):
                        cfg_snap.update({f"ctrl_{k}": v for k, v in self.controller_config.to_dict().items()})
                    if hasattr(self, "disturbance_config"):
                        try:
                            cfg_snap.update({f"dist_{k}": v for k, v in self.disturbance_config.to_dict().items()})
                        except: pass
                    cfg_snap["world_size"] = getattr(self, "_scene_size", None)
                    cfg_snap["fov_size"] = getattr(self, "_fov_size", None)
                    self.perf.start(prefix="simulation", config=cfg_snap)
                except Exception:
                    self.perf.start()
            self._last_tick_time = time.time()
            if getattr(self, "_pause_time", None) is not None:
                # adjust logger elapsed to exclude paused wall time (monotonic)
                try:
                    pause_dur = time.time() - self._pause_time
                    if hasattr(self.perf, "adjust_for_pause"):
                        self.perf.adjust_for_pause(pause_dur)
                    else:
                        # fallback wall adjustment
                        self.perf.start_time += pause_dur
                        if hasattr(self.perf, "_start_mono") and self.perf._start_mono is not None:
                            self.perf._start_mono += pause_dur
                except Exception:
                    pass
                self._pause_time = None
            self.timer.start(TICK_MS); self._running = True
            try: self._update_live_indicators()
            except: pass
            self.statusBar().showMessage("Running — tracking…", 2000)
    def _pause(self):
        if self._running:
            self.timer.stop(); self._running = False; self._pause_time = time.time()
            try: self._update_live_indicators()
            except: pass
            self.statusBar().showMessage("Paused", 2000)
        else: self._pause_time = None
    def _reset(self):
        self.timer.stop(); self._running=False; self._pause_time=None
        try: self._update_live_indicators()
        except: pass
        try:
            if hasattr(self, "perf") and hasattr(self.perf, "close"):
                self.perf.close()
        except: pass
        # Reset all panels to defaults
        try:
            from environment.config import EnvironmentConfig as _EC
            from camera.config import CameraConfig as _CC
            from target.config import MultiBeaconConfig as _MBC
            from control.config import ControllerConfig as _CtrlC
            # Environment to defaults (world 2000 per PDF min, configurable 2000..5000)
            if hasattr(self, "env_panel"):
                self.env_panel.set_config(_EC().validate(), emit=False)
                self.env_config = _EC().validate()
                self._scene_size = (int(self.env_config.world_width), int(self.env_config.world_height))
            # Camera to defaults (640x640, 4x3 deg, viewport 2000, god = world size, centre locked, 30Hz)
            if hasattr(self, "camera_panel"):
                self.camera_panel.set_config(_CC().validate(self._scene_size), emit=False)
                self.camera_config = _CC().validate(self._scene_size)
            # Beacons to defaults (1, square 10x10, Circular, 60, threshold 200, no blink, no random, centre 2500)
            if hasattr(self, "beacon_manager"):
                self.beacon_manager.set_config(_MBC(beacon_count=1, target_index=0, shape="square", size_w=10, size_h=10, x=2500, y=2500, profile="curved", speed=60, blinking=False, speed_random=False).validate(), emit=False)
                self.beacon_config = _MBC(beacon_count=1, target_index=0, shape="square", size_w=10, size_h=10, x=2500, y=2500, profile="curved", speed=60, blinking=False, speed_random=False).validate()
                self._beacon_count = 1; self._target_beacon_id = 0
                try:
                    self.beacon_manager.spin_thresh.setValue(200)
                except: pass
            # Disturbances to 0 — full spec reset (all new modules to Clear/Off)
            try:
                from disturbance.config import DisturbanceConfig as _DCReset
                _dc_default = _DCReset().validate()
                self.disturbance_config = _dc_default
                if hasattr(self, "disturbances_panel") and hasattr(self.disturbances_panel, "set_config"):
                    self.disturbances_panel.set_config(_dc_default, emit=False)
                    # keep legacy alias in sync
                    try:
                        self.sliders = self.disturbances_panel.sliders
                    except: pass
            except:
                if hasattr(self, "sliders"):
                    for s in self.sliders.values():
                        try:
                            s.blockSignals(True); s.setValue(0); s.blockSignals(False)
                        except: pass
                if hasattr(self, "disturbances_panel"):
                    for s in self.disturbances_panel.sliders.values():
                        try:
                            s.blockSignals(True); s.setValue(0); s.blockSignals(False)
                        except: pass
            # Clear per-instance platform/jitter states
            try:
                if hasattr(self, "_platform_motion_state"): self._platform_motion_state.clear()
                if hasattr(self, "_jitter_state"): self._jitter_state.clear()
            except: pass
            # Control to defaults (P, kp 0.15, 30Hz fixed)
            if hasattr(self, "control_panel"):
                self.control_panel.set_config(_CtrlC().validate(), emit=False)
                self.controller_config = _CtrlC().validate()
            # Global hidden tuning to defaults (motion curved, speed 60, thresh 200)
            if hasattr(self, "motion_combo"):
                self.motion_combo.blockSignals(True); self.motion_combo.setCurrentText("curved"); self.motion_combo.blockSignals(False)
            if hasattr(self, "speed_slider"):
                self.speed_slider.blockSignals(True); self.speed_slider.setValue(60); self.speed_slider.blockSignals(False)
                try: self.speed_slider._value_label.setText("60")
                except: pass
            if hasattr(self, "thresh_slider"):
                self.thresh_slider.blockSignals(True); self.thresh_slider.setValue(200); self.thresh_slider.blockSignals(False)
                try: self.thresh_slider._value_label.setText("200")
                except: pass
            self._target_speed = 60; self._det_thresh = 200; self._ctrl_gain = 0.15
            self._tracker_smoothing = 0.25; self._tracker_miss_limit = 5; self._detector_min_area = 2; self._sim_speed = 1.0; self._global_brightness = 255; self._global_radius = 5
            self._hitbox_radius = 14; self._center_radius = 2
            # Clear dirty
            try:
                self._dirty_tabs.clear(); self._applied_snapshot.clear()
            except: pass
        except Exception as e:
            print(f"Reset defaults error: {e}")
        self._build_simulation()
        try:
            self._invalidate_minimap_cache()
        except: pass
        try:
            self._rebuild_per_beacon_panels()
            self._sync_per_beacon_xy_ranges()
        except: pass
        self.perf=PerformanceLogger(); self._camera_drift_state={}; self._platform_motion_state={}; self._jitter_state={}; self._last_tick_time=None
        # FIX: reset dashboard history immediately so graph clears on reset (not lazy on next tick)
        try:
            if hasattr(self, "dashboard_panel") and hasattr(self.dashboard_panel, "reset_history"):
                self.dashboard_panel.reset_history()
        except Exception:
            pass
        # Reset disturbance global state — fixes stale phase/velocity on fresh run (reproducibility)
        try:
            dist.reset_disturbance_state()
            # Also clear per-instance drift / platform / jitter dicts (already {}) and any module globals
            self._camera_drift_state.clear()
            if hasattr(self, "_platform_motion_state"): self._platform_motion_state.clear()
            if hasattr(self, "_jitter_state"): self._jitter_state.clear()
        except Exception:
            pass
        # Proper reset: show initial 0 values with correct units (not "-") so no field appears empty
        try:
            if hasattr(self, "dashboard_panel") and hasattr(self.dashboard_panel, "update_from_summary"):
                # tracker is newly created via _build_simulation, use its status
                init_status = getattr(getattr(self, "tracker", None), "status", None)
                init_status = init_status.value if hasattr(init_status, "value") else "searching"
                cam_scale = 0.035
                try:
                    if hasattr(self, "camera") and hasattr(self.camera, "config") and getattr(self.camera.config, "pixel_scale_mrad", None) is not None:
                        cam_scale = float(self.camera.config.pixel_scale_mrad)
                except Exception:
                    pass
                self.dashboard_panel.update_from_summary(self.perf.summary(), init_status, None, camera_scale_mrad=cam_scale)
        except Exception:
            # Fallback: set labels to 0 with units
            for lbl in self.stat_labels.values():
                try:
                    lbl.setText("0.0")
                except: pass
        self.footer_lock.setText("SEARCHING"); self.lock_dot.setStyleSheet("color:#64748b; font-size:14px;")
        self.viewport_label.clear(); self.minimap_label.clear()
        # Force repaint for immediate visibility
        try:
            if hasattr(self, "dashboard_panel"):
                self.dashboard_panel.repaint()
                if hasattr(self.dashboard_panel, "graph"):
                    self.dashboard_panel.graph.plot.repaint()
            if hasattr(self, "dashboard_window"):
                self.dashboard_window.repaint()
        except Exception:
            pass
        self.statusBar().showMessage("Reset — ready", 2000)
    def _export_log(self):
        log_dir = getattr(self.perf, "log_dir", "log")
        default_name = os.path.join(log_dir, f"simulation_export_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv")
        path, _ = QFileDialog.getSaveFileName(self, "Export performance log", default_name, "CSV (*.csv);;JSON (*.json)")
        if path:
            try:
                self.perf.export_report(path)
                QMessageBox.information(self, "Export", f"Saved to:\n{path}")
            except Exception as e:
                QMessageBox.critical(self, "Export failed", str(e))

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
        dt_eff = float(np.clip(dt * sim_speed, 1e-4, 0.1))
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
        # ── PERFORMANCE FIX: Optimized FOV rendering — crop first (640×640 ≈1.2M px)
        #   instead of rebuilding full 5000×5000 (75M px, 300 MB float32) every 33 ms.
        #   Scene.get_region(x0,y0,x1,y1) applies haze shimmer + twinkle only to
        #   visible FOV stars. Vignetting is now camera image-space (follows FOV),
        #   applied AFTER beacon photometry at capture stage.
        #   God-view (minimap) uses a lightweight static-background path.
        # ── Disturbances (full spec) — dt_eff ensures sim-speed lockstep ──
        # Order positional: Vibration → Platform Motion → Jitter → Drift (OU)
        # Order image: Vignetting (camera) → Turbulence → Atmospheric → Sensor/Image Noise
        # Try to use DisturbanceConfig as single source; fallback to legacy sliders
        try:
            dc = getattr(self, "disturbance_config", None)
            if dc is not None:
                dc = dc.validate() if hasattr(dc, "validate") else dc
        except:
            dc = None
        if dc is None and hasattr(self, "sliders") and self.sliders:
            try:
                from disturbance.config import DisturbanceConfig as _FallbackDC
                dc = _FallbackDC(
                    turbulence=int(self.sliders["Turbulence"].value()) if "Turbulence" in self.sliders else 0,
                    vibration=int(self.sliders["Vibration"].value()) if "Vibration" in self.sliders else 0,
                    camera_motion=int(self.sliders["Camera Motion"].value()) if "Camera Motion" in self.sliders else 0,
                    noise=int(self.sliders["Noise"].value()) if "Noise" in self.sliders else 0,
                ).validate()
            except:
                dc = None

        # Determine vignetting strength for camera image-space (follows FOV)
        try:
            vig_strength = float(getattr(self.scene, 'vignetting', 0.0) or 0.0)
            if hasattr(self, 'env_config') and hasattr(self.env_config, 'vignetting_pct'):
                vig_strength = float(self.env_config.vignetting_pct) / 100.0
        except:
            vig_strength = 0.0
        try:
            self.camera.set_vignetting(vig_strength)
        except:
            pass
        # Decide path: optimized if Scene has get_region
        use_optimized = hasattr(self.scene, 'get_region')
        # For detection, remember disturbed FOV origin (camera-stage vignetting follows disturbed pose)
        fov_capture_x0 = None
        fov_capture_y0 = None

        # Helper to get base FOV (gradient+haze+stars, no beacons, no vignetting)
        def _get_fov_base(disturbed_pan, disturbed_tilt):
            if use_optimized:
                # Temporarily set camera to disturbed pose to get correct FOV rect,
                # then fetch cropped region (only 640×640 work)
                rp2, rt2 = self.camera.pan, self.camera.tilt
                self.camera.pan, self.camera.tilt = float(disturbed_pan), float(disturbed_tilt)
                try:
                    x0, y0, x1, y1 = self.camera.get_fov_rect()
                    base = self.scene.get_region(int(x0), int(y0), int(x1), int(y1))
                finally:
                    self.camera.pan, self.camera.tilt = rp2, rt2
                return base, (x0, y0)
            else:
                # Fallback heavy path: full frame then crop (for compat without get_region)
                full = self.scene.get_frame()
                return full, None

        # For god-view minimap — use cached low-res thumb (no 5000×5000 copy).
        # Legacy full-copy path kept as fallback but not used in optimized render.
        scene_frame = None  # No longer needed; _render_minimap() uses cached thumb internally.
        # _draw_targets on full world skipped — minimap draws hitboxes via renderer on thumb.

        # Now handle disturbances + FOV capture
        if dc is not None:
            if not hasattr(self, "_platform_motion_state") or self._platform_motion_state is None:
                self._platform_motion_state = {}
            if not hasattr(self, "_camera_drift_state") or self._camera_drift_state is None:
                self._camera_drift_state = {}
            pan_a, tilt_a = dist.apply_platform_vibration(self.camera.pan, self.camera.tilt, int(getattr(dc, "vibration", 0)), dt=dt_eff)
            if float(getattr(dc, "platform_speed", 0.0)) > 1e-9:
                pan_b, tilt_b = dist.apply_platform_motion(
                    pan_a, tilt_a,
                    profile=str(getattr(dc, "platform_profile", "Linear")),
                    speed_px_per_frame=float(getattr(dc, "platform_speed", 0.0)),
                    dt=dt_eff,
                    state=self._platform_motion_state,
                    bounds=self._scene_size,
                )
            else:
                pan_b, tilt_b = pan_a, tilt_a
            if float(getattr(dc, "camera_jitter", 0.0)) > 1e-9:
                pan_c, tilt_c = dist.apply_camera_jitter(pan_b, tilt_b, jitter_px=float(getattr(dc, "camera_jitter")))
            else:
                pan_c, tilt_c = pan_b, tilt_b
            pan_dist, tilt_dist = dist.apply_camera_motion_with_state(
                pan_c, tilt_c, int(getattr(dc, "camera_motion", 0)), self._camera_drift_state, dt=dt_eff
            )
            # Optimized FOV base fetch
            if use_optimized:
                fov_frame, fov_origin = _get_fov_base(pan_dist, tilt_dist)
                fov_x0, fov_y0 = int(fov_origin[0]), int(fov_origin[1])
                fov_capture_x0, fov_capture_y0 = fov_x0, fov_y0
                # Draw beacons in FOV coords (projected)
                self._draw_targets_fov(fov_frame, fov_x0, fov_y0)
                # Vignetting camera-stage (image-space, follows FOV)
                if vig_strength > 1e-3:
                    from environment.vignetting import apply_vignetting
                    fov_frame = apply_vignetting(fov_frame, vig_strength)
            else:
                # Heavy fallback
                rp, rt = self.camera.pan, self.camera.tilt
                self.camera.pan, self.camera.tilt = pan_dist, tilt_dist
                fov_frame = self.camera.capture(scene_frame)
                self.camera.pan, self.camera.tilt = rp, rt
                # vignetting already applied via camera.capture if set
                fov_capture_x0, fov_capture_y0 = None, None
            # Image disturbances after vignetting
            fov_frame = dist.apply_turbulence(fov_frame, int(getattr(dc, "turbulence", 0)), dt=dt_eff)
            preset = str(getattr(dc, "atmospheric_preset", "Clear"))
            contrast = float(getattr(dc, "atmospheric_contrast", 0.0))
            brightness = float(getattr(dc, "atmospheric_brightness", 0.0))
            if preset != "Clear" or contrast > 1e-9 or brightness > 1e-9:
                fov_frame = dist.apply_atmospheric_disturbance(
                    fov_frame, preset=preset, contrast_reduction=contrast, brightness_reduction=brightness
                )
            if int(getattr(dc, "noise", 0)) > 0:
                fov_frame = dist.apply_sensor_noise(fov_frame, int(getattr(dc, "noise")))
            if bool(getattr(dc, "enable_salt_pepper", False) or getattr(dc, "enable_gaussian", False) or getattr(dc, "enable_poisson", False)):
                fov_frame = dist.apply_image_noise(
                    fov_frame,
                    enable_salt_pepper=bool(getattr(dc, "enable_salt_pepper", False)),
                    enable_gaussian=bool(getattr(dc, "enable_gaussian", False)),
                    enable_poisson=bool(getattr(dc, "enable_poisson", False)),
                    salt_pepper_density=float(getattr(dc, "salt_pepper_density", 0.10)),
                    salt_pepper_ratio=float(getattr(dc, "salt_pepper_ratio", 0.50)),
                    gaussian_sigma=float(getattr(dc, "gaussian_sigma", 8.0)),
                    gaussian_sigma_max=float(getattr(dc, "gaussian_sigma_max", 20.0)),
                    poisson_scale=float(getattr(dc, "poisson_scale", 1.0)),
                    poisson_peak=float(getattr(dc, "poisson_peak", 100.0)),
                )
        else:
            # Legacy fallback (no config)
            pan_vib, tilt_vib = dist.apply_platform_vibration(self.camera.pan, self.camera.tilt, self.sliders["Vibration"].value(), dt=dt_eff)
            pan_dist, tilt_dist = dist.apply_camera_motion_with_state(pan_vib, tilt_vib, self.sliders["Camera Motion"].value(), self._camera_drift_state, dt=dt_eff)
            if use_optimized:
                fov_frame, fov_origin = _get_fov_base(pan_dist, tilt_dist)
                fov_x0, fov_y0 = int(fov_origin[0]), int(fov_origin[1])
                fov_capture_x0, fov_capture_y0 = fov_x0, fov_y0
                self._draw_targets_fov(fov_frame, fov_x0, fov_y0)
                if vig_strength > 1e-3:
                    from environment.vignetting import apply_vignetting
                    fov_frame = apply_vignetting(fov_frame, vig_strength)
            else:
                rp, rt = self.camera.pan, self.camera.tilt
                self.camera.pan, self.camera.tilt = pan_dist, tilt_dist
                fov_frame = self.camera.capture(scene_frame)
                self.camera.pan, self.camera.tilt = rp, rt
                fov_capture_x0, fov_capture_y0 = None, None
            fov_frame = dist.apply_turbulence(fov_frame, self.sliders["Turbulence"].value(), dt=dt_eff)
            fov_frame = dist.apply_sensor_noise(fov_frame, self.sliders["Noise"].value())
        # ── Target-only realtime check (not hardcoded, hitbox-gated) ──
        all_dets = self.detector.detect_all(fov_frame)
        self._last_all_detections = all_dets
        # Use disturbed FOV origin for detection when optimized path was used (camera moved)
        if fov_capture_x0 is not None and fov_capture_y0 is not None:
            fov_x0, fov_y0 = int(fov_capture_x0), int(fov_capture_y0)
        else:
            fov_x0, fov_y0, _, _ = self.camera.get_fov_rect()
        # ── P0 Blind PAT: no truth oracle for association ──
        # Association uses only detector output + Kalman prediction, no target.x/y.
        # Truth is used only post-hoc for scoring (hitbox_hit/center_hit), not gating.
        _det_dict = None
        _det_area = None
        _det_peak = None
        try:
            from tracking.association import associate_detections
            pred_xy = self.tracker.peek_predict(float(dt_eff)) if hasattr(self.tracker, "peek_predict") else getattr(self.tracker, "estimated_position", None)
            cov = self.tracker.get_innovation_cov() if hasattr(self.tracker, "get_innovation_cov") else None
            # P1: adaptive gate — tight when TRACKING, loose during SEARCH/ACQUIRED/LOST
            # so camera motion during search/acquisition does not reject true beacon
            _st = getattr(self.tracker, "status", None)
            try:
                _st_val = _st.value if hasattr(_st, "value") else str(_st)
            except Exception:
                _st_val = "searching"
            if _st_val == "tracking":
                _chi2, _fb = 9.21, 35.0
            elif _st_val == "lost":
                _chi2, _fb = 16.0, 60.0
            else:  # searching / acquired
                _chi2, _fb = 25.0, 80.0
            # Phase 3: signature pre-filter when locked (rejects distractors with very different area/peak)
            _filtered_dets = all_dets
            try:
                if _st_val == "tracking" and hasattr(self.tracker, "is_signature_locked") and self.tracker.is_signature_locked():
                    tmp = []
                    for d in all_dets:
                        try:
                            s = float(self.tracker.get_signature_score(float(d.get("area", 0)), float(d.get("peak", 0))))
                        except Exception:
                            s = 1.0
                        if s > 0.30:
                            tmp.append(d)
                    if tmp:
                        _filtered_dets = tmp
            except Exception:
                _filtered_dets = all_dets
            detection = associate_detections(_filtered_dets, pred_xy, cov, chi2_threshold=_chi2, fallback_radius_px=_fb)
            # keep detection dict for signature area/peak
            if detection is not None:
                for d in _filtered_dets:
                    try:
                        if abs(float(d["x"]) - float(detection[0])) < 1e-6 and abs(float(d["y"]) - float(detection[1])) < 1e-6:
                            _det_dict = d
                            break
                    except Exception:
                        continue
                if _det_dict is not None:
                    try:
                        _det_area = float(_det_dict.get("area", 0))
                        _det_peak = float(_det_dict.get("peak", 0))
                    except Exception:
                        _det_area = _det_peak = None
            # Note: associate already does circular fallback (fallback_radius) for
            # SEARCH/ACQUIRED/LOST so camera-motion shift (~30px) is tolerated
            # without jumping to distant distractor (>80px). No extra brightest fallback.
        except Exception:
            # Fallback: brightest blob (detector already sorted by confidence)
            try:
                detection = (float(all_dets[0]["x"]), float(all_dets[0]["y"])) if all_dets else None
                if detection is not None and all_dets:
                    try:
                        _det_dict = all_dets[0]
                        _det_area = float(_det_dict.get("area", 0))
                        _det_peak = float(_det_dict.get("peak", 0))
                    except Exception:
                        _det_area = _det_peak = None
            except Exception:
                detection = None
                _det_area = _det_peak = None
        # Truth-based scoring for metrics only (does not influence detection)
        try:
            primary = self.target
            proj_x = float(primary.x) - float(fov_x0)
            proj_y = float(primary.y) - float(fov_y0)
            if detection is not None:
                dist_to_truth = math.hypot(float(detection[0]) - proj_x, float(detection[1]) - proj_y)
                hitbox_hit = dist_to_truth <= float(getattr(primary, "hitbox_radius", 14))
                center_hit = dist_to_truth <= float(getattr(primary, "center_radius", 2))
            else:
                hitbox_hit = False
                center_hit = False
            # If target beacon disabled, it is truly not beaconing: score as miss
            # (blind association may still latch onto distractor — scored as miss correctly)
            if not getattr(primary, "enabled", True):
                hitbox_hit = False
                center_hit = False
        except Exception:
            hitbox_hit = False
            center_hit = False
        # Phase 4: coarse-to-fine FOV — coarse 640 for search, fine 320 for lock
        try:
            _cur_fov = int(getattr(self.camera, "fov_width", 640))
            _desired_fov = 320 if getattr(self.tracker, "status", None) and self.tracker.status.value == "tracking" else 640
            # only adjust when status stable for 3 frames to avoid flicker
            if not hasattr(self, "_fov_stable_count"):
                self._fov_stable_count = 0
                self._last_fov_status = None
            _st_val2 = getattr(self.tracker, "status", None).value if hasattr(getattr(self.tracker, "status", None), "value") else "searching"
            if _st_val2 != getattr(self, "_last_fov_status", None):
                self._fov_stable_count = 0
                self._last_fov_status = _st_val2
            else:
                self._fov_stable_count += 1
            if _cur_fov != _desired_fov and self._fov_stable_count >= 3:
                # apply coarse-to-fine: update camera FOV, keep center
                try:
                    self.camera.fov_width = int(_desired_fov)
                    self.camera.fov_height = int(_desired_fov * 480 / 640)  # keep aspect 4:3 -> 320x240 or 640x480
                    self.camera._sync_fov_from_config() if hasattr(self.camera, "_sync_fov_from_config") else None
                    # keep config in sync
                    try:
                        self.camera.config.fov_width = int(self.camera.fov_width)
                        self.camera.config.fov_height = int(self.camera.fov_height)
                    except Exception:
                        pass
                    self._fov_size = (int(self.camera.fov_width), int(self.camera.fov_height))
                    # re-clamp pan/tilt
                    try:
                        self.camera._clamp_to_range()
                    except Exception:
                        pass
                    # reset scanner visited when FOV changes (coverage changes)
                    try:
                        if hasattr(self, "scanner") and self.scanner is not None:
                            self.scanner._visited = np.zeros((self.scanner._grid_n, self.scanner._grid_n), dtype=int)
                    except Exception:
                        pass
                except Exception:
                    pass
        except Exception:
            pass
        # Kalman-aware update: pass dt_eff so filter can coast through dropout/occlusion
        try:
            # Phase 3: pass area/peak for signature learning
            estimate = self.tracker.update(detection, dt=float(dt_eff), area=_det_area, peak=_det_peak)
        except TypeError:
            try:
                estimate = self.tracker.update(detection, dt=float(dt_eff))
            except TypeError:
                estimate = self.tracker.update(detection)
        tracking_error_px=None
        # Error to perfect center (not hitbox edge) for precision metrics
        if estimate is not None:
            cx, cy = self.camera.fov_width/2, self.camera.fov_height/2
            err_x, err_y = estimate[0]-cx, estimate[1]-cy
            tracking_error_px=float(np.hypot(err_x, err_y))
            # Phase 5: auto-tune Kp based on tracking error (keep <5px)
            try:
                if self.tracker.status.value == "tracking" and tracking_error_px is not None:
                    err = float(tracking_error_px)
                    kp = float(self.controller.config.kp)
                    if err > 12 and kp < 0.45:
                        self.controller.config.kp = float(min(0.50, kp * 1.008))
                    elif err < 4 and kp > 0.18:
                        self.controller.config.kp = float(max(0.15, kp * 0.998))
                    # also nudge dead_zone if error noisy
            except Exception:
                pass
            # Control — PID + velocity feedforward (Phase 5) with dead zone, output clamp respecting camera slew
            try:
                cam_slew = float(self.camera_config.max_slew_rate) if hasattr(self, "camera_config") else None
            except: cam_slew = None
            # Phase 5: get velocity from IMM for feedforward (px/s in FOV)
            _vel_x = _vel_y = None
            try:
                vel = self.tracker.get_velocity()
                if vel is not None:
                    _vel_x, _vel_y = float(vel[0]), float(vel[1])
                    # clamp insane velocity (outlier rejection was 800)
                    if abs(_vel_x) > 800 or abs(_vel_y) > 800:
                        _vel_x = _vel_y = None
            except Exception:
                _vel_x = _vel_y = None
            try:
                d_pan,d_tilt=self.controller.compute_correction(err_x, err_y, dt=dt, camera_max_slew=cam_slew, vel_x=_vel_x, vel_y=_vel_y)
            except TypeError:
                try:
                    d_pan,d_tilt=self.controller.compute_correction(err_x, err_y, dt=dt, camera_max_slew=cam_slew)
                except TypeError:
                    d_pan,d_tilt=self.controller.compute_correction(err_x, err_y)
            try:
                self.camera.move(d_pan, d_tilt, dt)
            except TypeError:
                # Back-compat fallback (PTZCamera without dt)
                self.camera.move(d_pan, d_tilt)
        # ── P1/P2 Autonomous search + LOST prediction chase ──
        # SEARCHING: no estimate -> random waypoint search (blind, covers world)
        # LOST: has coasting estimate (Kalman predicts) -> chase prediction via PID above,
        #       plus tiny expanding spiral if coast drifts (not random uniform)
        # ACQUIRED/TRACKING: PID only (probation/locked)
        try:
            status = self.tracker.status
            is_searching = (status == LockStatus.SEARCHING)
            is_lost = (status == LockStatus.LOST)
            # Only SEARCHING (or no estimate at all) gets random scanner drive.
            # LOST with coasting estimate is handled by PID chase above, not random.
            should_search = is_searching or (estimate is None and status != LockStatus.TRACKING and status != LockStatus.LOST)
            # Special: if LOST but estimate is None (grace expired -> SEARCHING soon) treat as SEARCHING
            if is_lost and estimate is None:
                should_search = True
                is_searching = True
            # Keep last estimate world for reacquisition bias (P2)
            try:
                if estimate is not None:
                    # estimate is FOV coords, convert to world via current fov origin
                    _est_wx = float(fov_x0) + float(estimate[0])
                    _est_wy = float(fov_y0) + float(estimate[1])
                    self._last_est_world = (_est_wx, _est_wy)
                elif not hasattr(self, "_last_est_world"):
                    self._last_est_world = None
            except Exception:
                pass
            if should_search and hasattr(self, "scanner") and self.scanner is not None:
                if getattr(self, "_last_search_status", None) != status:
                    if status == LockStatus.SEARCHING or (is_lost and estimate is None):
                        try:
                            self.scanner.reset()
                        except Exception:
                            pass
                        # P2: bias search around last predicted world (if we have it) for reacquisition
                        try:
                            if getattr(self, "_last_est_world", None) is not None and status == LockStatus.SEARCHING:
                                # only bias if we recently lost (not cold start)
                                prev = getattr(self, "_last_search_status", None)
                                if prev == LockStatus.LOST or prev == LockStatus.ACQUIRED:
                                    wx, wy = self._last_est_world  # type: ignore
                                    self.scanner.set_search_center(float(wx), float(wy))
                        except Exception:
                            pass
                try:
                    dx, dy = self.scanner.next(dt=float(dt), fov_w=float(self.camera.fov_width), fov_h=float(self.camera.fov_height), current_pan=float(self.camera.pan), current_tilt=float(self.camera.tilt), scene_bounds=self._scene_size)
                except TypeError:
                    dx, dy = self.scanner.next(dt=float(dt), fov_w=float(self.camera.fov_width), fov_h=float(self.camera.fov_height))
                try:
                    self.camera.move(float(dx), float(dy), float(dt))
                except TypeError:
                    self.camera.move(float(dx), float(dy))
            elif is_lost and estimate is not None:
                # LOST with coast: PID above already chased predicted position.
                # Add tiny expanding search bias only if coast is stale (misses >5)
                # so FOV spirals around predicted point to reacquire after occlusion.
                try:
                    misses = int(getattr(self.tracker._state, "misses", 0) or getattr(self.tracker, "_consecutive_misses", 0))
                except Exception:
                    misses = 6
                if misses > 7:
                    # small spiral around predicted point (expanding)
                    import math
                    r = 12.0 * math.sqrt(max(0, misses - 7))
                    theta = misses * 1.2
                    sx = r * math.cos(theta)
                    sy = r * math.sin(theta)
                    try:
                        self.camera.move(float(sx) * 0.15, float(sy) * 0.15, float(dt))
                    except Exception:
                        pass
            self._last_search_status = status
        except Exception:
            pass
        is_locked=self.tracker.status==LockStatus.TRACKING
        # Real-time accurate: detected = blind association hit (penalizes distractor latch) + dt for time accounting
        self.perf.log_frame(is_locked, tracking_error_px, time.time()-frame_start,
                            detected=hitbox_hit, hitbox_hit=hitbox_hit, center_hit=center_hit,
                            lock_state=self.tracker.status.value, dt=dt)
        # Rendering must not block dashboard — ensure _update_stats always runs
        try:
            self._render_viewport(fov_frame, estimate, all_dets)
        except Exception:
            pass
        try:
            self._render_minimap(scene_frame)
        except Exception:
            pass
        try:
            self._update_stats(tracking_error_px)
        except Exception:
            pass
        # Force dashboard repaint for real-time visibility
        try:
            if hasattr(self, "dashboard_panel"):
                self.dashboard_panel.repaint()
                if hasattr(self.dashboard_panel, "graph"):
                    self.dashboard_panel.graph.plot.repaint()
        except Exception:
            pass

    def _beacon_vibrant_color(self, beacon_id: int, brightness: float) -> tuple[int,int,int]:
        return Renderer.beacon_vibrant_color(beacon_id, brightness)

    def _draw_targets(self, scene_frame: np.ndarray):
        Renderer.draw_targets(scene_frame, getattr(self, "beacons", [self.target]), self.target)

    def _draw_targets_fov(self, fov_frame: np.ndarray, fov_x0: int, fov_y0: int):
        """Draw beacon photometry onto a 640×640 FOV frame (projected, optimized).

        This is the optimized equivalent of _draw_targets for the cropped path:
        draws each beacon at (beacon.x - fov_x0, beacon.y - fov_y0) so we avoid
        drawing on a 5000×5000 world buffer just to crop to 640×640.
        """
        beacons = getattr(self, "beacons", [self.target]) if hasattr(self, "beacons") else [self.target]
        h, w = fov_frame.shape[:2]
        for beacon in beacons:
            if not getattr(beacon, "enabled", True):
                continue
            if getattr(beacon, "blinking", False) and not getattr(beacon, "_blink_visible", True):
                continue
            try:
                px = float(beacon.x) - float(fov_x0)
                py = float(beacon.y) - float(fov_y0)
            except:
                continue
            # Cull far outside view (+ margin for size)
            if px < -40 or px > w + 40 or py < -40 or py > h + 40:
                continue
            try:
                brightness, radius = beacon.get_photometry()
            except:
                brightness, radius = float(getattr(beacon, "brightness", 200)), float(getattr(beacon, "radius", 5))
            ix, iy = int(round(px)), int(round(py))
            try:
                vib = Renderer.beacon_vibrant_color(int(getattr(beacon, "beacon_id", 0)), float(brightness))
            except:
                vib = (0, 255, 255)
            shape = str(getattr(beacon, "shape", "square"))
            size_w = int(getattr(beacon, "size_w", 10))
            size_h = int(getattr(beacon, "size_h", 10))
            if shape == "square":
                hw, hh = size_w // 2, size_h // 2
                if max(size_w, size_h) > 6:
                    glow = tuple(int(c * 0.55) for c in vib)
                    cv2.rectangle(fov_frame, (ix - hw - 1, iy - hh - 1), (ix + hw + 1, iy + hh + 1), glow, -1, cv2.LINE_AA)
                cv2.rectangle(fov_frame, (ix - hw, iy - hh), (ix + hw, iy + hh), vib, -1, cv2.LINE_AA)
                cv2.rectangle(fov_frame, (ix - hw, iy - hh), (ix + hw, iy + hh), (255, 255, 255), 1, cv2.LINE_AA)
            else:
                r = max(1, int(round(max(size_w, size_h) / 2)) if size_w and size_h else int(round(radius)))
                if r > 3:
                    glow = tuple(int(c * 0.55) for c in vib)
                    cv2.circle(fov_frame, (ix, iy), r+1, glow, -1, cv2.LINE_AA)
                cv2.circle(fov_frame, (ix, iy), max(1, r), vib, -1, cv2.LINE_AA)
                cv2.circle(fov_frame, (ix, iy), 1, (255, 255, 255), -1, cv2.LINE_AA)

    def _draw_target(self, scene_frame: np.ndarray):
        return self._draw_targets(scene_frame)

    def _draw_reticle(self, img, center, gap=10, arm=16, color=(255, 255, 255), thickness=1):
        return Renderer.draw_reticle(img, center, gap, arm, color, thickness)

    def _draw_corner_brackets(self, img, margin=6, length=10, color=(200, 200, 200), thickness=1):
        return Renderer.draw_corner_brackets(img, margin, length, color, thickness)

    def _render_viewport(self, fov_frame: np.ndarray, estimate, all_dets: list[dict] | None = None):
        # Standard crosshair only — no overlay configuration
        pixel_scale = 0.035
        try:
            pixel_scale = float(getattr(getattr(self, "camera", None).config, "pixel_scale_mrad", 0.035))
        except: pass
        try:
            display = Renderer.render_viewport(fov_frame, self.camera, getattr(self, "beacons", [self.target]), self.target, self.tracker, all_dets, pixel_scale_mrad=pixel_scale)
        except Exception:
            display = Renderer.render_viewport(fov_frame, self.camera, getattr(self, "beacons", [self.target]), self.target, self.tracker, all_dets)
        self._last_viewport_frame = display
        self._set_pixmap(self.viewport_label, display)

    def _get_minimap_thumb(self, lw: int, lh: int) -> np.ndarray:
        """Return cached low-res thumb of static background (rebuild only on size/scene change).
        Saves 11 ms copy + 3 ms resize of 5000×5000 each tick → 0.2 ms copy of 0.16 MP thumb."""
        lw = max(50, int(lw)); lh = max(50, int(lh))
        scene_id = id(getattr(self.scene, '_static_background', None))
        if (self._minimap_thumb is not None and self._minimap_thumb_size == (lw, lh)
                and self._minimap_scene_id == scene_id):
            return self._minimap_thumb
        try:
            base = getattr(self.scene, '_static_background', None)
            if base is None:
                base = self.scene.get_frame()
            # For 5000×5000 → 400×300, INTER_AREA is sharper and faster than LINEAR for downscale
            self._minimap_thumb = cv2.resize(base, (lw, lh), interpolation=cv2.INTER_AREA)
        except Exception:
            self._minimap_thumb = np.zeros((lh, lw, 3), dtype=np.uint8)
        self._minimap_thumb_size = (lw, lh)
        self._minimap_scene_id = scene_id
        return self._minimap_thumb

    def _invalidate_minimap_cache(self):
        self._minimap_thumb = None
        self._minimap_thumb_size = None
        self._minimap_scene_id = None

    def _render_minimap(self, scene_frame: np.ndarray | None = None):
        lw = self.minimap_label.width() if self.minimap_label.width()>10 else self._god_display_size[0]
        lh = self.minimap_label.height() if self.minimap_label.height()>10 else self._god_display_size[1]
        # Optimized path: use cached thumb (no 5000×5000 copy/resize). Fallback to legacy if needed.
        if hasattr(self, '_get_minimap_thumb'):
            try:
                thumb = self._get_minimap_thumb(lw, lh)
                display = Renderer.render_minimap_cached(thumb, self.camera, getattr(self, "beacons", [self.target]), self.target, self.tracker, (lw, lh), self._scene_size)
                self._last_god_frame = display
                self._set_pixmap(self.minimap_label, display)
                return
            except Exception:
                pass
        # Legacy fallback (heavy)
        if scene_frame is None:
            try:
                scene_frame = self.scene._static_background.copy() if hasattr(self.scene, '_static_background') and self.scene._static_background is not None else self.scene.get_frame()
            except:
                scene_frame = self.scene.get_frame()
        display = Renderer.render_minimap(scene_frame, self.camera, getattr(self, "beacons", [self.target]), self.target, self.tracker, (lw, lh), self._scene_size)
        self._last_god_frame = display
        self._set_pixmap(self.minimap_label, display)

    def _set_pixmap(self, label, bgr_frame: np.ndarray):
        # Delegate to Renderer (handles QImage copy + scaling)
        rgb = Renderer.set_pixmap(label, bgr_frame)
        self._last_rgb = rgb
        return rgb

    def closeEvent(self, event):
        # FIX: ensure logger file closed on app exit (prevents leak / data loss)
        try:
            if hasattr(self, "perf") and hasattr(self.perf, "close"):
                self.perf.close()
        except Exception:
            pass
        try:
            if hasattr(self, "timer"):
                self.timer.stop()
        except Exception:
            pass
        try:
            for t in getattr(self, "_auto_timers", {}).values():
                try:
                    t.stop()
                except Exception:
                    pass
        except Exception:
            pass
        super().closeEvent(event)

    def _update_stats(self, tracking_error_px):
        # Dashboard-only: all metrics consolidated in DashboardPanel (single source)
        try:
            s = self.perf.summary()
        except Exception:
            return
        # Inject live system pose metrics (previously footer/header) into summary for dashboard
        try:
            pan = float(getattr(self.camera, "pan", 0) if hasattr(self, "camera") else 0)
            tilt = float(getattr(self.camera, "tilt", 0) if hasattr(self, "camera") else 0)
            s["live_pan"] = round(pan, 1)
            s["live_tilt"] = round(tilt, 1)
            s["live_fov"] = f"{self._fov_size[0]}×{self._fov_size[1]}"
            s["live_world"] = f"{self._scene_size[0]}×{self._scene_size[1]}"
            try:
                s["live_pixel_scale"] = float(getattr(getattr(self.camera, "config", {}), "pixel_scale_mrad", 0.035))
            except Exception:
                s["live_pixel_scale"] = float(getattr(self.camera_config, "pixel_scale_mrad", 0.035)) if hasattr(self, "camera_config") else 0.035
            s["live_error_px"] = float(tracking_error_px) if tracking_error_px is not None else None
            # Config snaps — entire system (for dashboard G, dashboard-only)
            try:
                s["config_haze_pct"] = int(getattr(self.env_config, "haze_pct", 0)) if hasattr(self, "env_config") else 0
                s["config_star_count"] = int(getattr(self.env_config, "star_count", 0)) if hasattr(self, "env_config") else 0
                s["config_max_slew"] = float(getattr(self.camera_config, "max_slew_rate", 0)) if hasattr(self, "camera_config") else 0
                s["config_latency_ms"] = int(getattr(self.camera_config, "latency_ms", 0)) if hasattr(self, "camera_config") else 0
                s["config_beacon_count"] = f"{self._beacon_count} (target #{self._target_beacon_id})" if hasattr(self, "_beacon_count") else str(getattr(self.beacon_config, "beacon_count", 1)) if hasattr(self, "beacon_config") else "—"
                try:
                    prof = getattr(self.target, "profile", None)
                    prof_str = prof.value if hasattr(prof, "value") else str(prof) if prof else "—"
                    speed = getattr(self.target, "speed", 0)
                    s["config_beacon_profile"] = f"{prof_str} @ {float(speed):.0f} px/s"
                except Exception:
                    s["config_beacon_profile"] = "—"
                try:
                    if hasattr(self, "disturbance_config") and self.disturbance_config is not None:
                        dc = self.disturbance_config
                        parts = [f"T{int(getattr(dc,'turbulence',0))} V{int(getattr(dc,'vibration',0))} C{int(getattr(dc,'camera_motion',0))} N{int(getattr(dc,'noise',0))}"]
                        if bool(getattr(dc,'enable_salt_pepper',False) or getattr(dc,'enable_gaussian',False) or getattr(dc,'enable_poisson',False)):
                            en=[]
                            if getattr(dc,'enable_salt_pepper',False): en.append(f"S&P{getattr(dc,'salt_pepper_density',0)*100:.0f}%")
                            if getattr(dc,'enable_gaussian',False): en.append(f"Gσ{getattr(dc,'gaussian_sigma',0):.0f}")
                            if getattr(dc,'enable_poisson',False): en.append("Poisson")
                            parts.append("+".join(en) + f"/max{getattr(dc,'gaussian_sigma_max',20):.0f}")
                        if float(getattr(dc,'camera_jitter',0))>0:
                            parts.append(f"J±{float(getattr(dc,'camera_jitter',0)):.1f}px")
                        preset = str(getattr(dc,'atmospheric_preset','Clear'))
                        if preset!="Clear":
                            parts.append(f"Atmo{preset[:4]} C{int(getattr(dc,'atmospheric_contrast',0))} B{int(getattr(dc,'atmospheric_brightness',0))}")
                        if float(getattr(dc,'platform_speed',0))>0:
                            parts.append(f"Plat{str(getattr(dc,'platform_profile','Lin'))[:4]} {float(getattr(dc,'platform_speed',0)):.0f}px/f")
                        s["config_disturbances"] = " • ".join(parts)
                    else:
                        turb = self.sliders["Turbulence"].value() if hasattr(self, "sliders") and "Turbulence" in self.sliders else 0
                        vib = self.sliders["Vibration"].value() if hasattr(self, "sliders") and "Vibration" in self.sliders else 0
                        cam = self.sliders["Camera Motion"].value() if hasattr(self, "sliders") and "Camera Motion" in self.sliders else 0
                        noise = self.sliders["Noise"].value() if hasattr(self, "sliders") and "Noise" in self.sliders else 0
                        s["config_disturbances"] = f"T{turb} V{vib} C{cam} N{noise}"
                except Exception:
                    s["config_disturbances"] = "—"
                try:
                    ctrl_type = getattr(self.controller_config, "controller_type", "P") if hasattr(self, "controller_config") else "P"
                    kp = getattr(self.controller_config, "kp", 0) if hasattr(self, "controller_config") else 0
                    rate = getattr(self.controller_config, "update_rate_hz", 0) if hasattr(self, "controller_config") else 0
                    s["config_controller"] = f"{ctrl_type} Kp{kp:.2f} @ {rate:.0f}Hz"
                except Exception:
                    s["config_controller"] = "—"
            except Exception:
                pass
        except Exception:
            pass
        try:
            if hasattr(self, "dashboard_panel"):
                cam_scale = s.get("live_pixel_scale")
                if cam_scale is None:
                    try:
                        cam_scale = float(getattr(getattr(self, "camera", None).config, "pixel_scale_mrad", None))
                    except: pass
                self.dashboard_panel.update_from_summary(s, self.tracker.status.value, tracking_error_px, camera_scale_mrad=cam_scale)
                # Inform dashboard window status bar (intuitive live indicator)
                try:
                    if hasattr(self, "dashboard_window") and hasattr(self.dashboard_window, "update_live_status"):
                        self.dashboard_window.update_live_status(s)
                except: pass
            else:
                # Fallback legacy direct label updates
                for k in ["fps","simulation_duration_s","acquisition_time_s","avg_processing_time_ms","avg_tracking_error_px","max_tracking_error_px","tracking_error_pct","lock_retention_rate_pct","acquisitions","detection_rate_pct","detection_time_s","searching_rate_pct","searching_time_s","center_hit_rate_pct","center_hit_time_s"]:
                    if k in getattr(self, "stat_labels", {}):
                        self.stat_labels[k].setText(str(s.get(k, "-")))
                if "lock_status" in getattr(self, "stat_labels", {}):
                    self.stat_labels["lock_status"].setText(self.tracker.status.value)
        except: pass

        # Dashboard-only: external telemetry/header/footer metric displays hidden; dashboard is single source
        try:
            for attr in ["_telemetry_strip", "_fov_footer", "_god_footer", "_hdr_mode_badge", "_hdr_fov_badge", "_hdr_world_badge", "footer_lock", "lock_dot", "footer_fps", "footer_info", "_fov_footer_info", "_god_footer_info"]:
                w = getattr(self, attr, None)
                if w is not None:
                    try:
                        w.hide()
                    except: pass
            # Status bar no longer shows metric values outside dashboard — points to dashboard (metrics dashboard-only)
            self.statusBar().showMessage("Metrics -> Dashboard only -- see Dashboard tab/window for live FPS, error, retention, reacq, etc. (Sr.16-20)", 2000)
        except: pass
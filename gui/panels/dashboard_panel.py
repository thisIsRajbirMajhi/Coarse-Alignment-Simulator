# gui/panels/dashboard_panel.py - Dashboard (graph removed, metrics only, dashboard-only per consolidation)
# All system metrics displayed here; graph removed per user request.

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

STATUS_COLOR = {
    "tracking": "#22c55e",
    "acquired": "#06b6d4",
    "lost": "#ef4444",
    "searching": "#64748b",
}

def _color_for_rate(pct: float) -> str:
    # Spec Sr.18 retention: green ≥95% (pass), yellow ≥80% (marginal), red else
    if pct >= 95:
        return "#22c55e"
    if pct >= 80:
        return "#eab308"
    return "#ef4444"

def _color_for_error(err_px: float) -> str:
    # Spec Sr.17 tracking error ≤10px strict: green ≤10 pass, red >10 fail (yellow removed for strict spec)
    if err_px <= 10:
        return "#22c55e"
    return "#ef4444"

def _color_for_error_pct(pct: float) -> str:
    """High error % is bad (red). 15px ~=100% per thresholds."""
    if pct <= 25:
        return "#22c55e"
    if pct <= 60:
        return "#eab308"
    return "#ef4444"

def _color_for_fps(fps: float) -> str:
    # Spec Sr.20 processing speed ≥20 FPS strict: green ≥20 pass, red <20 fail
    if fps >= 20:
        return "#22c55e"
    return "#ef4444"

def _color_for_reacq(sec: float) -> str:
    """Spec Sr.19 reacquisition ≤1s green, ≤2s yellow, >2s red."""
    if sec is None:
        return "#64748b"
    if sec <= 1.0:
        return "#22c55e"
    if sec <= 2.0:
        return "#eab308"
    return "#ef4444"

def _color_for_target_loss(pct: float) -> str:
    """Spec Sr.18 target loss <5% green, <10% yellow, >=10% red."""
    if pct is None:
        return "#64748b"
    if pct < 5.0:
        return "#22c55e"
    if pct < 10.0:
        return "#eab308"
    return "#ef4444"

def _status_color(s: str) -> str:
    return STATUS_COLOR.get(s.lower(), "#64748b")


def _value_style(color: str = "#0f172a", bg: str = "#ffffff") -> str:
    return (
        f"font-weight:600; color:{color}; background:{bg}; border:1px solid #e2e8f0;"
        " border-radius:6px; padding:3px 6px; font-size:11px;"
    )

class DashboardPanel(QWidget):
    """
    Modular dashboard — metrics only (graph removed per consolidation).
    All system metrics displayed here (dashboard-only per user request).
    Sections (properly grouped, no redundancies, spec-referenced):
      A. Timing & Processing — (≥20 FPS, <33ms) & Log
      B. Acquisition — (≤2s) & Re-acquisition (≤1s)
      C. Lock & Retention — (<5% Loss, >95% Retention)
      D. Tracking & Centroiding — (≤10px) & Benchmark RMSE
      E. Detection & Coverage — Rate & Time (only primary, no hitbox duplicate)
      F. Live System Pose — Camera & Scene (from telemetry/header)
      G. System Configuration — Snapshot (entire system, from control panels)
    Graph removed: metrics only, dashboard placed in MainWindow right side (replaces command deck).
    Command deck detached to separate window (ControlDashboardWindow).
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.stat_labels: dict[str, QLabel] = {}
        class _CompatProgressDict(dict):
            def __getitem__(self, key):
                if key in self:
                    return super().__getitem__(key)
                class _Dummy:
                    def setValue(self, v): pass
                    def setStyleSheet(self, s): pass
                    def setRange(self, a, b): pass
                    def setFixedHeight(self, h): pass
                    def setTextVisible(self, v): pass
                    def setFormat(self, s): pass
                    def value(self): return 0
                dummy = _Dummy()
                super().__setitem__(key, dummy)
                return dummy
        self.progress_bars: dict = _CompatProgressDict()  # type: ignore
        # Dummy graph attributes for backward compat (tests may check)
        from collections import deque
        self.graph = None
        self.time_data = deque()
        self.fps_data = deque()
        self.retention_data = deque()
        self.error_data = deque()
        self.center_hit_data = deque()
        self.detection_data = deque()
        self.searching_data = deque()
        self._last_graph_update = 0.0
        # Dummy plot attributes
        class _DummyPlot:
            def enableAutoRange(self, *a, **kw): pass
            def getViewBox(self): return self
            def updateAutoRange(self, *a, **kw): pass
            def setData(self, *a, **kw): pass
        self.plot_widget = _DummyPlot()
        self.fps_curve = _DummyPlot()
        self.retention_curve = _DummyPlot()
        self.error_curve = _DummyPlot()
        self.center_hit_curve = _DummyPlot()
        self.detection_curve = _DummyPlot()
        self.searching_curve = _DummyPlot()
        self._graph_box = None
        self._build_ui()
        # Expose graph shortcuts for legacy tests (dummy)
        self.graph = self._graph_dummy if hasattr(self, '_graph_dummy') else None

    def _color_for_rate(self, pct: float) -> str:
        return _color_for_rate(pct)

    def _color_for_error(self, err_px: float) -> str:
        return _color_for_error(err_px)

    def _color_for_fps(self, fps: float) -> str:
        return _color_for_fps(fps)

    def _color_for_error_pct(self, pct: float) -> str:
        return _color_for_error_pct(pct)

    def _status_color(self, status: str) -> str:
        return _status_color(status)

    def reset_history(self):
        # Graph removed — no history to clear, but keep method for compat
        pass

    # Build UI — metrics only, no graph
    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        # LEFT: metrics scroll (now full dashboard, graph removed)
        metrics_container = QWidget()
        metrics_layout = QVBoxLayout(metrics_container)
        metrics_layout.setContentsMargins(10, 10, 10, 10)
        metrics_layout.setSpacing(12)

        # Title
        hdr = QLabel("Dashboard")
        hdr.setStyleSheet("color:#0f172a; font-weight:800; font-size:13px; background:transparent;")
        hdr.setToolTip("All system metrics displayed here (dashboard-only); graph removed per consolidation")
        metrics_layout.addWidget(hdr)

        # System Health — Live section removed per user request
        self.health_card = QFrame()
        self.health_card.hide()
        self.health_lock_dot = QLabel("●")
        self.health_lock_dot.hide()
        self.health_lock_text = QLabel("SEARCHING")
        self.health_lock_text.hide()
        self.health_retention_val = QLabel("—")
        self.health_retention_val.hide()
        self.health_retention_bar = self.health_retention_val
        try:
            self.health_retention_bar.setValue = lambda v: None  # type: ignore
            self.health_retention_bar.setRange = lambda a, b: None  # type: ignore
            self.health_retention_bar.setTextVisible = lambda v: None  # type: ignore
            self.health_retention_bar.setFormat = lambda s: None  # type: ignore
            self.health_retention_bar.setFixedHeight = lambda h: None  # type: ignore
        except Exception:
            pass
        self.health_fps = QLabel("FPS —")
        self.health_fps.hide()
        self.health_error = QLabel("Err —")
        self.health_error.hide()

        self._make_section(metrics_layout, "A. Timing and Processing", [
            ("Duration (S)", "simulation_duration_s", "Duration", "Wall time since Start (s) — performance log", False, None),
            ("Processing Speed (FPS)", "fps", "FPS", "Sr.20 processing speed — spec >=20 FPS (green>=20, yellow>=15)", True, "fps"),
            ("Avg Processing Time (ms)", "avg_processing_time_ms", "Avg Proc", "Average per-frame time — Sr.20 <33ms real-time", True, "avg_processing_time_ms"),
            ("Min Processing Time (ms)", "min_processing_time_ms", "Min Proc", "Minimum latency — best case", False, None),
            ("Max Processing Time (ms)", "max_processing_time_ms", "Max Proc", "Maximum latency — worst case", False, None),
            ("Jitter (ms)", "jitter_ms", "Jitter", "Processing time std dev — stability, <2ms good", True, "jitter_ms"),
            ("P95 Processing Time (ms)", "p95_processing_time_ms", "P95 Proc", "95th percentile latency — worst-case", True, "p95_processing_time_ms"),
        ])
        self._make_section(metrics_layout, "B. Acquisition", [
            ("Acquisition Time (S)", "acquisition_time_s", "Acq", "Sr.16 time to first TRACKING lock — spec <=2s", True, "acquisition_time_s"),
            ("Re-acquisition Avg (S)", "avg_reacquisition_time_s", "Re-acq Avg", "Sr.19 avg after loss — spec <=1s", True, "avg_reacquisition_time_s"),
            ("Re-acquisition Min (S)", "min_reacquisition_time_s", "Min", "Fastest reacquisition — stability", False, None),
            ("Re-acquisition Max (S)", "max_reacquisition_time_s", "Max", "Worst reacquisition — worst-case recovery", False, None),
            ("Total Acquisitions (count)", "acquisitions", "Acqs", "Count of entries into TRACKING — stability", False, None),
            ("Lock Losses (count)", "lock_losses", "Losses", "Times TRACKING to LOST — lower is better, 0 ideal", False, None),
        ])
        self._make_section(metrics_layout, "C. Lock and Retention", [
            ("Lock Status", "lock_status", "Status", "Detection state: SEARCHING / TRACKING", False, None),
            ("Retention Rate (%)", "lock_retention_rate_pct", "Retention", "Frames in TRACKING / total — spec >95%", True, "lock_retention_rate_pct"),
            ("Target Loss (%)", "target_loss_pct", "Loss", "Sr.18 target loss =100-retention — spec <5%", True, "target_loss_pct"),
            ("State — Acquired (%)", "state_acquired_pct", "Acquired", "Frames in ACQUIRED (deprecated — always 0)", True, "state_acquired_pct"),
            ("State — Lost (%)", "state_lost_pct", "Lost", "Frames in LOST (deprecated — always 0)", True, "state_lost_pct"),
        ])
        self._make_section(metrics_layout, "D. Tracking and Centroiding", [
            ("Average Error (px / mrad)", "avg_tracking_error_px", "Avg Err", "Sr.17 avg tracking error — spec <=10px", True, "avg_tracking_error_px"),
            ("RMS / RMSE (px / mrad) — Benchmark", "rms_tracking_error_px", "RMS", "Benchmark RMSE — root-mean-square, spec <=10px", True, "rms_tracking_error_px"),
            ("Maximum Error (px)", "max_tracking_error_px", "Max Err", "Peak error — worst case tail", True, "max_tracking_error_px"),
            ("P95 Error (px)", "p95_tracking_error_px", "P95", "95th percentile — 95% of errors below, robustness", True, "p95_tracking_error_px"),
            ("Std Dev (px)", "std_tracking_error_px", "Std", "Standard deviation — error jitter", True, "std_tracking_error_px"),
            ("Median Error (px)", "median_tracking_error_px", "Median", "Median — typical error, 50th percentile", False, None),
            ("Minimum Error (px)", "min_tracking_error_px", "Min", "Best-case error — lower bound", False, None),
            ("Live Error (px / mrad)", "live_error_px", "Live Err", "Current frame instantaneous error — from telemetry", True, "live_error_px"),
        ])
        self._make_section(metrics_layout, "E. Detection and Coverage", [
            ("Detection Rate (%)", "detection_rate_pct", "Detect Rate", "Primary target hitbox hits / total frames — detection success", True, "detection_rate_pct"),
            ("Detection Time (S)", "detection_time_s", "Detect Time", "Total time target was detected (s)", False, None),
            ("Detection Count", "detection_count", "# Det Cnt", "Frames with primary detection — count", False, None),
            ("Center Hit Rate (%)", "center_hit_rate_pct", "Center Rate", "Precise center hits (<=2px) / total — accuracy", True, "center_hit_rate_pct"),
            ("Center Hit Time (S)", "center_hit_time_s", "Center Time", "Total time in precise center (s)", False, None),
            ("Center Hits (count)", "center_hit_count", "# Center Hits", "Precise center hit frames — count", False, None),
            ("Searching Rate (%)", "searching_rate_pct", "Search Rate", "Frames in SEARCHING / total — lower is better when locked", True, "searching_rate_pct"),
            ("Searching Time (S)", "searching_time_s", "Search Time", "Total time searching (s)", False, None),
            ("Frame Count", "frame_count", "# Frames", "Total frames processed — throughput (Sr.20)", False, None),
        ])
        self._make_section(metrics_layout, "F. Live System Pose", [
            ("Pan (px)", "live_pan", "Pan", "Camera pan in world px", False, None),
            ("Tilt (px)", "live_tilt", "Tilt", "Camera tilt in world px", False, None),
            ("FOV Size (px)", "live_fov", "FOV", "Camera FOV WxH in px (640x480 spec 4deg x 3deg)", False, None),
            ("World Size (px)", "live_world", "World", "Scene world WxH in px (spec >=2000)", False, None),
            ("Pixel Scale (mrad/px)", "live_pixel_scale", "Scale", "Pixel to angle — mrad per px (0.109=4deg x 3deg for 640x480)", False, None),
        ])
        self._make_section(metrics_layout, "G. System Configuration", [
            ("World — Haze (%)", "config_haze_pct", "Haze", "Environment haze % — from Environment panel (Sr.21.4)", True, "config_haze_pct"),
            ("World — Star Count", "config_star_count", "Stars", "Star/clutter count — from Environment panel", False, None),
            ("Camera — Max Slew (px/s)", "config_max_slew", "Slew", "Camera max slew — from Camera panel (Sr.13-14, 5-10deg/s)", True, "config_max_slew"),
            ("Camera — Latency (ms)", "config_latency_ms", "Latency", "Camera latency — from Camera panel", False, None),
            ("Beacons — Count / Target", "config_beacon_count", "Beacons", "Beacon count and target index — from Beacons panel (Sr.8)", False, None),
            ("Beacons — Target Profile / Speed", "config_beacon_profile", "Profile", "Target profile and speed — from Beacons panel (Sr.12)", False, None),
            ("Disturbances — Turb/Vib/Cam/Noise", "config_disturbances", "Disturb", "Intensities 0-10 — from Disturbances panel (Sr.21)", False, None),
            ("Controller — Type and Kp (Hz)", "config_controller", "Ctrl", "Controller type, Kp, update rate — from Control panel (Sr.15)", False, None),
        ])

        metrics_layout.addStretch()

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(metrics_container)
        scroll.setStyleSheet("QScrollArea { border:none; background:#f8fafc; }")
        outer.addWidget(scroll)

        # Dummy graph box for backward compat (hidden, graph removed)
        self._graph_box = QGroupBox("Graph removed — metrics only (dashboard in MainWindow)")
        self._graph_box.hide()
        # Dummy graph for compat
        from collections import deque
        class _DummyGraph:
            def __init__(self):
                self.time = deque()
                self.fps = deque()
                self.retention = deque()
                self.error = deque()
                self.center = deque()
                self.detection = deque()
                self.searching = deque()
                self._last_draw = 0.0
                self.plot = self
            def clear(self): pass
            def append(self, *a, **kw): pass
            def enableAutoRange(self, *a, **kw): pass
            def getViewBox(self): return self
            def updateAutoRange(self, *a, **kw): pass
            def setData(self, *a, **kw): pass
        self._graph_dummy = _DummyGraph()
        self.graph = self._graph_dummy
        self.time_data = self._graph_dummy.time
        self.fps_data = self._graph_dummy.fps
        self.retention_data = self._graph_dummy.retention
        self.error_data = self._graph_dummy.error
        self.center_hit_data = self._graph_dummy.center
        self.detection_data = self._graph_dummy.detection
        self.searching_data = self._graph_dummy.searching
        self.plot_widget = self._graph_dummy
        self.fps_curve = self._graph_dummy
        self.retention_curve = self._graph_dummy
        self.error_curve = self._graph_dummy
        self.center_hit_curve = self._graph_dummy
        self.detection_curve = self._graph_dummy
        self.searching_curve = self._graph_dummy

    def _make_section(self, layout: QVBoxLayout, title: str, rows: list[tuple[str, str, str, str, bool, str | None]]) -> None:
        box = QGroupBox(title)
        box.setStyleSheet("QGroupBox { background:#ffffff; border:1px solid #e5e7eb; border-radius:6px; margin-top:14px; padding-top:12px; } QGroupBox::title { color:#111827; font-weight:600; left:10px; }")
        grid = QGridLayout(box)
        grid.setContentsMargins(10, 14, 10, 10)
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(6)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)
        for i, (label, key, icon_label, tooltip, with_progress, progress_key) in enumerate(rows):
            lk = QLabel(label)
            lk.setStyleSheet("color:#374151; font-size:11px; font-weight:500;")
            lk.setToolTip(tooltip)
            lk.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
            grid.addWidget(lk, i, 0)

            val = QLabel("-")
            val.setAlignment(Qt.AlignCenter)
            val.setMinimumHeight(26)
            val.setToolTip(tooltip)
            if key == "lock_status":
                val.setStyleSheet("font-weight:600; color:#6b7280; background:#f9fafb; border:1px solid #e5e7eb; border-radius:4px; padding:4px 8px; font-size:11px;")
            else:
                val.setStyleSheet(_value_style())
            self.stat_labels[key] = val
            grid.addWidget(val, i, 1)

        layout.addWidget(box)

    # Update — , real-time, informative

    def update_from_summary(self, summary: dict, tracker_status: str, tracking_error_px: float | None = None, camera_scale_mrad: float | None = None) -> None:
        """Update all labels from summary dict. Real-time at ~30 Hz. Graph removed."""
        status = str(tracker_status)
        color = _status_color(status)

        def set_val(key: str, text: str, col: str | None = None, bg: str = "#ffffff"):
            if key in self.stat_labels:
                lbl = self.stat_labels[key]
                c = col or "#0f172a"
                lbl.setText(text)
                if key == "lock_status":
                    lbl.setStyleSheet(f"font-weight:800; color:{c}; background:#f1f5f9; border:1px solid #e2e8f0; border-radius:6px; padding:4px 8px; font-size:11px;")
                else:
                    lbl.setStyleSheet(_value_style(c, bg))

        # Health header (hidden but kept for compat)
        try:
            if hasattr(self, "health_lock_dot"):
                self.health_lock_dot.setStyleSheet(f"color:{color}; font-size:18px; background:transparent; border:none;")
                self.health_lock_text.setText(status.upper())
                self.health_lock_text.setStyleSheet(f"color:{color}; font-weight:800; font-size:11px; background:transparent; border:none;")
                retention_h = float(summary.get("lock_retention_rate_pct", 0) or 0)
                self.health_retention_val.setText(f"{retention_h:.1f}%")
                self.health_retention_val.setStyleSheet(f"color:{_color_for_rate(retention_h)}; font-weight:700; font-size:11px; background:#ffffff; border:1px solid #e2e8f0; border-radius:6px; padding:3px 6px;")
                fps_h = float(summary.get("fps", 0) or 0)
                self.health_fps.setText(f"FPS {fps_h:.1f}")
                self.health_fps.setStyleSheet(f"color:{_color_for_fps(fps_h)}; font-weight:700; font-size:11px; background:#ffffff; border:1px solid #e2e8f0; border-radius:6px; padding:3px 6px;")
                if tracking_error_px is not None:
                    try:
                        scale = float(camera_scale_mrad) if camera_scale_mrad is not None else 0.035
                        mrad = tracking_error_px * scale
                        self.health_error.setText(f"Err {tracking_error_px:.1f}px {mrad:.2f}mrad")
                        self.health_error.setStyleSheet(f"color:{_color_for_error(tracking_error_px)}; font-weight:700; font-size:11px; background:#ffffff; border:1px solid #e2e8f0; border-radius:6px; padding:3px 6px;")
                    except Exception:
                        self.health_error.setText(f"Err {tracking_error_px:.1f}px")
                else:
                    self.health_error.setText("Err —")
                    self.health_error.setStyleSheet("color:#64748b; font-size:11px; background:#ffffff; border:1px solid #e2e8f0; border-radius:6px; padding:3px 6px;")
        except Exception:
            pass

        # A. Timing & Processing
        try:
            fps = float(summary.get("fps", 0) or 0)
            set_val("fps", f"{fps:.1f} FPS", _color_for_fps(fps))
            dur = summary.get("simulation_duration_s")
            try:
                set_val("simulation_duration_s", f"{float(dur):.2f} S" if dur is not None else "0.00 S", "#0f172a")
            except Exception:
                set_val("simulation_duration_s", "0.00 S")
            # Avg processing time already in ms, direct
            avg_ms = summary.get("avg_processing_time_ms")
            if avg_ms is not None:
                try:
                    fval = float(avg_ms)
                    col = "#22c55e" if fval < 33 else "#eab308" if fval < 60 else "#ef4444"
                    set_val("avg_processing_time_ms", f"{fval:.1f} ms", col)
                except Exception:
                    set_val("avg_processing_time_ms", "0.0 ms")
            else:
                set_val("avg_processing_time_ms", "0.0 ms")
            for k in ["min_processing_time_ms", "max_processing_time_ms", "jitter_ms", "p95_processing_time_ms"]:
                v = summary.get(k)
                try:
                    fval = float(v) if v is not None else 0.0
                    if k == "jitter_ms":
                        col = "#22c55e" if fval < 2 else "#eab308" if fval < 5 else "#ef4444"
                    else:
                        col = "#22c55e" if fval < 33 else "#eab308" if fval < 60 else "#ef4444"
                    set_val(k, f"{fval:.1f} ms", col)
                except Exception:
                    set_val(k, "0.0 ms")
        except Exception:
            pass

        # B. Acquisition — Sr.16 & Sr.19
        try:
            acq = summary.get("acquisition_time_s")
            if acq is not None:
                try:
                    fval = float(acq)
                    col = "#22c55e" if fval <= 2 else "#eab308" if fval <= 3 else "#ef4444"
                    set_val("acquisition_time_s", f"{fval:.2f} S", col)
                except Exception:
                    set_val("acquisition_time_s", "— S", "#64748b")
            else:
                set_val("acquisition_time_s", "— S", "#64748b")
            for k in ["avg_reacquisition_time_s", "min_reacquisition_time_s", "max_reacquisition_time_s"]:
                v = summary.get(k)
                try:
                    if v is None:
                        set_val(k, "— S", "#64748b")
                    else:
                        fval = float(v)
                        col = _color_for_reacq(fval)
                        set_val(k, f"{fval:.2f} S", col)
                except Exception:
                    set_val(k, "— S", "#64748b")
            for k in ["acquisitions", "lock_losses"]:
                v = summary.get(k)
                try:
                    set_val(k, f"{int(v)}" if v is not None else "0", "#0f172a" if k == "acquisitions" else ("#ef4444" if int(v or 0) > 3 else "#0f172a"))
                except Exception:
                    set_val(k, "0")
        except Exception:
            pass

        # C. Lock & Retention — Sr.18
        try:
            set_val("lock_status", status.upper(), color, "#f1f5f9")
            retention = float(summary.get("lock_retention_rate_pct", 0) or 0)
            set_val("lock_retention_rate_pct", f"{retention:.1f} %", _color_for_rate(retention))
            tloss = float(summary.get("target_loss_pct", 0) or 0)
            set_val("target_loss_pct", f"{tloss:.1f} %", _color_for_target_loss(tloss))
            for k in ["state_acquired_pct", "state_lost_pct"]:
                v = summary.get(k)
                try:
                    fval = float(v) if v is not None else 0.0
                    col = "#0f172a" if k == "state_acquired_pct" else _color_for_error_pct(fval)
                    set_val(k, f"{fval:.1f} %", col)
                except Exception:
                    set_val(k, "0.0 %")
        except Exception:
            pass

        # D. Tracking & Centroiding — Sr.17
        try:
            avg_px = summary.get("avg_tracking_error_px")
            max_px = summary.get("max_tracking_error_px")
            def _col_spec(px: float) -> str:
                if px <= 10:
                    return "#22c55e"
                if px <= 15:
                    return "#eab308"
                return "#ef4444"
            if avg_px is not None:
                try:
                    fval = float(avg_px)
                    txt = f"{fval:.1f} px"
                    if camera_scale_mrad is not None:
                        try:
                            mrad = fval * float(camera_scale_mrad)
                            txt = f"{fval:.1f} px · {mrad:.2f} mrad"
                        except Exception:
                            pass
                    set_val("avg_tracking_error_px", txt, _col_spec(fval))
                except Exception:
                    set_val("avg_tracking_error_px", "0.0 px", "#22c55e")
            else:
                set_val("avg_tracking_error_px", "0.0 px", "#22c55e")
            if max_px is not None:
                try:
                    fval = float(max_px)
                    txt = f"{fval:.1f} px"
                    if camera_scale_mrad is not None:
                        try:
                            mrad = fval * float(camera_scale_mrad)
                            txt = f"{fval:.1f} px · {mrad:.2f} mrad"
                        except Exception:
                            pass
                    set_val("max_tracking_error_px", txt, _col_spec(fval))
                except Exception:
                    set_val("max_tracking_error_px", "0.0 px", "#22c55e")
            else:
                set_val("max_tracking_error_px", "0.0 px", "#22c55e")
            for k, v in [
                ("rms_tracking_error_px", summary.get("rms_tracking_error_px")),
                ("p95_tracking_error_px", summary.get("p95_tracking_error_px")),
                ("std_tracking_error_px", summary.get("std_tracking_error_px")),
                ("median_tracking_error_px", summary.get("median_tracking_error_px")),
                ("min_tracking_error_px", summary.get("min_tracking_error_px")),
                ("live_error_px", summary.get("live_error_px")),
            ]:
                try:
                    if v is None:
                        col = "#64748b" if k == "live_error_px" else "#0f172a"
                        set_val(k, "— px" if k == "live_error_px" else "0.0 px", col)
                    else:
                        fval = float(v)
                        col = _col_spec(fval) if k != "std_tracking_error_px" else "#0f172a"
                        if k == "live_error_px" and fval == 0 and summary.get("live_error_px") is None:
                            col = "#64748b"
                        txt = f"{fval:.1f} px"
                        if camera_scale_mrad is not None and k in ["rms_tracking_error_px", "p95_tracking_error_px", "live_error_px"]:
                            try:
                                mrad = fval * float(camera_scale_mrad)
                                txt = f"{fval:.1f} px · {mrad:.2f} mrad"
                            except Exception:
                                pass
                        set_val(k, txt, col)
                except Exception:
                    set_val(k, "0.0 px")
        except Exception:
            pass

        # E. Detection & Coverage
        try:
            for k in ["detection_rate_pct", "center_hit_rate_pct", "searching_rate_pct"]:
                v = summary.get(k)
                try:
                    pct = float(v) if v is not None else 0.0
                    col = _color_for_rate(pct) if k != "searching_rate_pct" else (_color_for_error_pct(pct) if pct > 30 else _color_for_rate(100 - pct))
                    set_val(k, f"{pct:.1f} %", col)
                except Exception:
                    set_val(k, "0.0 %")
            for k in ["detection_time_s", "center_hit_time_s", "searching_time_s"]:
                v = summary.get(k)
                try:
                    set_val(k, f"{float(v):.2f} S" if v is not None else "0.00 S")
                except Exception:
                    set_val(k, "0.00 S")
            for k in ["detection_count", "center_hit_count", "frame_count"]:
                v = summary.get(k)
                try:
                    set_val(k, f"{int(v)}" if v is not None else "0")
                except Exception:
                    set_val(k, "0")
        except Exception:
            pass

        # F. Live System Pose
        try:
            pan = summary.get("live_pan")
            tilt = summary.get("live_tilt")
            fov = summary.get("live_fov")
            world = summary.get("live_world")
            scale = summary.get("live_pixel_scale")
            if pan is not None:
                set_val("live_pan", f"{float(pan):.0f} px")
            else:
                set_val("live_pan", "— px", "#64748b")
            if tilt is not None:
                set_val("live_tilt", f"{float(tilt):.0f} px")
            else:
                set_val("live_tilt", "— px", "#64748b")
            if fov is not None:
                set_val("live_fov", str(fov))
            else:
                set_val("live_fov", "—", "#64748b")
            if world is not None:
                set_val("live_world", str(world))
            else:
                set_val("live_world", "—", "#64748b")
            if scale is not None:
                try:
                    set_val("live_pixel_scale", f"{float(scale):.3f} mrad/px")
                except Exception:
                    set_val("live_pixel_scale", str(scale))
            else:
                set_val("live_pixel_scale", "—", "#64748b")
        except Exception:
            pass

        # G. System Configuration Snaps
        try:
            haze = summary.get("config_haze_pct")
            if haze is not None:
                try:
                    fval = float(haze)
                    col = "#eab308" if fval > 30 else "#22c55e" if fval < 10 else "#64748b"
                    set_val("config_haze_pct", f"{fval:.0f} %", col)
                except Exception:
                    set_val("config_haze_pct", str(haze))
            else:
                set_val("config_haze_pct", "— %", "#64748b")
            sc = summary.get("config_star_count")
            set_val("config_star_count", f"{int(sc)}" if sc is not None else "—")
            slew = summary.get("config_max_slew")
            if slew is not None:
                try:
                    fval = float(slew)
                    col = "#22c55e" if 500 <= fval <= 2000 else "#eab308"
                    set_val("config_max_slew", f"{fval:.0f} px/s", col)
                except Exception:
                    set_val("config_max_slew", str(slew))
            else:
                set_val("config_max_slew", "— px/s", "#64748b")
            lat = summary.get("config_latency_ms")
            set_val("config_latency_ms", f"{int(lat)} ms" if lat is not None else "— ms")
            bc = summary.get("config_beacon_count")
            set_val("config_beacon_count", str(bc) if bc is not None else "—")
            bp = summary.get("config_beacon_profile")
            set_val("config_beacon_profile", str(bp) if bp is not None else "—")
            dist = summary.get("config_disturbances")
            set_val("config_disturbances", str(dist) if dist is not None else "—")
            ctrl = summary.get("config_controller")
            set_val("config_controller", str(ctrl) if ctrl is not None else "—")
        except Exception:
            pass

        # No hidden-label leak: stat_labels only contains visible Section rows.


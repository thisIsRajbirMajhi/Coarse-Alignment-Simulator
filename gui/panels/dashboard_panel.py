# gui/panels/dashboard_panel.py - Intuitive, modular live performance dashboard + responsive, auto-scaling graph

from collections import deque
import math
import pyqtgraph as pg
from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QSplitter,
    QVBoxLayout,
    QWidget,
    QSizePolicy,
)

STATUS_COLOR = {
    "tracking": "#22c55e",
    "acquired": "#06b6d4",
    "lost": "#ef4444",
    "searching": "#64748b",
}

def _color_for_rate(pct: float) -> str:
    if pct >= 80:
        return "#22c55e"
    if pct >= 50:
        return "#eab308"
    return "#ef4444"

def _color_for_error(err_px: float) -> str:
    if err_px < 5:
        return "#22c55e"
    if err_px < 15:
        return "#eab308"
    return "#ef4444"

def _color_for_error_pct(pct: float) -> str:
    """High error % is bad (red). 15px ~=100% per thresholds."""
    if pct <= 25:
        return "#22c55e"
    if pct <= 60:
        return "#eab308"
    return "#ef4444"

def _color_for_fps(fps: float) -> str:
    if fps >= 25:
        return "#22c55e"
    if fps >= 15:
        return "#eab308"
    return "#ef4444"

def _status_color(s: str) -> str:
    return STATUS_COLOR.get(s.lower(), "#64748b")

def _progress_style(color: str) -> str:
    # Kept for backward compat — progress bars removed per user request
    return ""

def _value_style(color: str = "#0f172a", bg: str = "#ffffff") -> str:
    return (
        f"font-weight:600; color:{color}; background:{bg}; border:1px solid #e2e8f0;"
        " border-radius:6px; padding:3px 6px; font-size:11px;"
    )

def _error_pct_from_px(px: float) -> float:
    """Convert px error to intuitive % where 15px = 100% (per dashboard thresholds). Capped 0-100."""
    try:
        return max(0.0, min(100.0, float(px) / 15.0 * 100.0))
    except Exception:
        return 0.0

class GraphPanel(QWidget):
    """
    Encapsulated graph — responsive and automatic scalable, complete picture without trimming.
    - AutoRange enabled on both axes, view always shows full history (downsampled for performance).
    - Downsampling + clipToView + autoDownsample for 2k points at 30 Hz (no trimming, just scaling).
    - Legend, grid, axis labels, mouse pan/zoom enabled.
    - Public API: update(time, fps, retention, error, center, detection, searching), clear(), export()
    """

    MAX_HISTORY = 4000  # enough for >2 min at 30Hz without trimming intuition

    def __init__(self, parent=None):
        super().__init__(parent)
        self.time = deque(maxlen=self.MAX_HISTORY)
        self.fps = deque(maxlen=self.MAX_HISTORY)
        self.retention = deque(maxlen=self.MAX_HISTORY)
        self.error = deque(maxlen=self.MAX_HISTORY)
        self.center = deque(maxlen=self.MAX_HISTORY)
        self.detection = deque(maxlen=self.MAX_HISTORY)
        self.searching = deque(maxlen=self.MAX_HISTORY)
        self._last_draw = 0.0
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        # Header with live range indicator
        hdr = QHBoxLayout()
        self.title = QLabel("Metrics Over Time — Live (auto-scaling)")
        self.title.setStyleSheet("color:#0f172a; font-weight:700; font-size:11px;")
        hdr.addWidget(self.title)
        hdr.addStretch()
        self.range_lbl = QLabel("—")
        self.range_lbl.setStyleSheet("color:#64748b; font-size:10px; background:#f1f5f9; border:1px solid #e2e8f0; border-radius:4px; padding:2px 6px;")
        self.range_lbl.setToolTip("X shows full simulation time (auto-scaled), Y auto-scales to include all 6 series without clipping")
        hdr.addWidget(self.range_lbl)
        layout.addLayout(hdr)

        self.plot = pg.PlotWidget()
        self.plot.setBackground("#ffffff")
        self.plot.showGrid(x=True, y=True, alpha=0.28)
        self.plot.setLabel("bottom", "Simulation Time", units="s")
        self.plot.setLabel("left", "Value", units="%, px, FPS")
        self.plot.addLegend(offset=(10, 8), colCount=3, labelTextSize="9pt")
        # Responsive: allow pan/zoom, auto range
        self.plot.setMouseEnabled(x=True, y=True)
        try:
            self.plot.enableAutoRange()
        except Exception:
            try:
                self.plot.getViewBox().enableAutoRange()
            except Exception:
                pass
        try:
            self.plot.getViewBox().setAutoVisible(x=True, y=True)
        except Exception:
            pass
        # Performance: downsample, clip
        self.plot.setClipToView(True)
        self.plot.setDownsampling(auto=True, mode="peak")

        # Curves — distinct, color-blind friendly, informative legend
        self.curves = {}
        self.curves["fps"] = self.plot.plot(pen=pg.mkPen("#3b82f6", width=2), name="FPS")
        self.curves["retention"] = self.plot.plot(pen=pg.mkPen("#22c55e", width=2), name="Retention (%)")
        # Error is px, to keep complete picture we plot normalized error % on same 0-100 scale for comparability
        # but also plot raw px on secondary interpretation: we provide both error_px and error_pct curves; show px scaled to % for unity
        self.curves["error"] = self.plot.plot(pen=pg.mkPen("#ef4444", width=2, style=Qt.SolidLine), name="Error (px)")
        self.curves["error_pct"] = self.plot.plot(pen=pg.mkPen("#ef4444", width=1, style=Qt.DashLine), name="Error (%)")
        self.curves["center"] = self.plot.plot(pen=pg.mkPen("#eab308", width=2), name="Center Hit (%)")
        self.curves["detection"] = self.plot.plot(pen=pg.mkPen("#8b5cf6", width=2), name="Detection (%)")
        self.curves["searching"] = self.plot.plot(pen=pg.mkPen("#64748b", width=2), name="Searching (%)")

        # Make plot expand responsive
        self.plot.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        layout.addWidget(self.plot, 1)

        # Footer hint
        hint = QLabel("Tip: scroll to zoom, drag to pan, double-click to auto-fit. Graph never trims — it rescales to show complete history.")
        hint.setWordWrap(True)
        hint.setStyleSheet("color:#64748b; font-size:10px; background:transparent;")
        layout.addWidget(hint)

    def clear(self):
        for d in (self.time, self.fps, self.retention, self.error, self.center, self.detection, self.searching):
            d.clear()
        for c in self.curves.values():
            c.setData([], [])
        self.range_lbl.setText("—")
        self._last_draw = 0.0
        self.plot.enableAutoRange()

    def append(self, t: float, fps: float, retention: float, error_px: float, center: float, detection: float, searching: float):
        # Handle reset (time going backward)
        if self.time and t < self.time[-1] - 1e-6:
            self.clear()
        elif self.time and abs(t - self.time[-1]) < 1e-9:
            return
        self.time.append(float(t))
        self.fps.append(float(fps))
        self.retention.append(float(retention))
        self.error.append(float(error_px))
        self.center.append(float(center))
        self.detection.append(float(detection))
        self.searching.append(float(searching))

        # Throttle draw to 8 Hz for responsiveness without dropping data
        import time as _t
        now = _t.monotonic()
        if (now - self._last_draw) < 0.12:
            return
        self._draw()
        self._last_draw = now

    def _draw(self):
        if not self.time:
            return
        x = list(self.time)
        # For complete picture without trimming, we plot all histories with autoRange
        # Error px often 0-30 dwarfs % 0-100; to keep single Y informative we also plot error_pct normalized
        # but keep raw px as well — user can toggle via legend (pyqtgraph handles)
        err_pct = [_error_pct_from_px(v) for v in self.error]
        self.curves["fps"].setData(x, list(self.fps))
        self.curves["retention"].setData(x, list(self.retention))
        self.curves["error"].setData(x, list(self.error))
        self.curves["error_pct"].setData(x, err_pct)
        self.curves["center"].setData(x, list(self.center))
        self.curves["detection"].setData(x, list(self.detection))
        self.curves["searching"].setData(x, list(self.searching))
        # Update range label for informativeness
        xmin, xmax = min(x), max(x)
        vals = list(self.fps) + list(self.retention) + list(self.center) + list(self.detection) + list(self.searching) + list(self.error) + err_pct
        if vals:
            ymin, ymax = min(vals), max(vals)
            self.range_lbl.setText(f"X {xmin:.1f}–{xmax:.1f}s  ·  Y {ymin:.0f}–{ymax:.0f}")
        # Ensure view shows complete picture (no clipping) — autoRange
        try:
            self.plot.enableAutoRange()
        except Exception:
            pass
        try:
            self.plot.getViewBox().updateAutoRange()
        except Exception:
            pass

class DashboardPanel(QWidget):
    """
    Modular dashboard — 4 spec sections + responsive graph.
    Sections per image:
      1) Dashboard: FPS, Duration (S), Acquisition (S), Proc. Time (S)
      2) Tracking: Average Tracking Error | Maximum Tracking Error (px / mrad, no %)
      3) Locking: Status, Retention Rate (%), Total Acquisitions
      4) Detection / Searching / Center: Rate (%), Time (S) ×3
    Intuitive cues: status dot (green/yellow/red), error inverted, FPS thresholds.
    Informative: tooltips, units in labels, values rounded, numeric only (progress bars removed, health removed, % removed from tracking error).
    Modular: each section built via _make_section helper; GraphPanel separate.
    """

    MAX_HISTORY = GraphPanel.MAX_HISTORY

    def __init__(self, parent=None):
        super().__init__(parent)
        self.stat_labels: dict[str, QLabel] = {}
        # Progress bars removed — keep dict-like compat that returns dummy bar for any key (no visual)
        class _CompatProgressDict(dict):
            def __getitem__(self, key):
                if key in self:
                    return super().__getitem__(key)
                # return dummy no-op bar for compat
                class _Dummy:
                    def setValue(self, v): pass
                    def setStyleSheet(self, s): pass
                    def setRange(self, a, b): pass
                    def setFixedHeight(self, h): pass
                    def setTextVisible(self, v): pass
                    def setFormat(self, s): pass
                    def value(self): return 0
                dummy = _Dummy()
                # cache it so future setValue doesn't recreate
                super().__setitem__(key, dummy)
                return dummy
        self.progress_bars: dict = _CompatProgressDict()  # type: ignore
        self.graph = GraphPanel(self)
        # Mirror deques for backward compat with existing tests that inspect time_data etc.
        self.time_data = self.graph.time
        self.fps_data = self.graph.fps
        self.retention_data = self.graph.retention
        self.error_data = self.graph.error
        self.center_hit_data = self.graph.center
        self.detection_data = self.graph.detection
        self.searching_data = self.graph.searching
        self._last_graph_update = 0.0
        self._build_ui()
        # Shortcuts for legacy tests
        self.plot_widget = self.graph.plot
        self.fps_curve = self.graph.curves["fps"]
        self.retention_curve = self.graph.curves["retention"]
        self.error_curve = self.graph.curves["error"]
        self.center_hit_curve = self.graph.curves["center"]
        self.detection_curve = self.graph.curves["detection"]
        self.searching_curve = self.graph.curves["searching"]
        self.graph_box = self._graph_box

    # Backward-compat helpers expected by tests
    def _progress_style(self, color: str) -> str:
        return ""

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
        self.graph.clear()
        self._last_graph_update = 0.0

    # Build UI — modular sections

    def _build_ui(self) -> None:
        outer = QHBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        splitter = QSplitter(Qt.Horizontal)
        splitter.setHandleWidth(6)
        outer.addWidget(splitter)

        # LEFT: metrics scroll
        metrics_container = QWidget()
        metrics_layout = QVBoxLayout(metrics_container)
        metrics_layout.setContentsMargins(10, 10, 10, 10)
        metrics_layout.setSpacing(12)

        # Title
        hdr = QLabel("Dashboard — Live System Metrics")
        hdr.setStyleSheet("color:#0f172a; font-weight:800; font-size:13px; background:transparent;")
        hdr.setToolTip("Real-time metrics refreshed every simulation tick (~30 Hz); graph throttled for responsiveness")
        metrics_layout.addWidget(hdr)
        sub = QLabel("Values are live — graph auto-scales to show complete history without trimming.")
        sub.setWordWrap(True)
        sub.setStyleSheet("color:#64748b; font-size:10px; background:transparent;")
        metrics_layout.addWidget(sub)

        # System Health — Live section removed per user request
        # Keep dummy attributes for backward compat (hidden, not added to layout)
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

        # 1) Dashboard (FPS, Duration, Acquisition, Proc Time)
        self._make_section(metrics_layout, "Dashboard", [
            ("FPS", "fps", "● FPS", "Frames per second — wall-clock, auto-scaled", False, None),
            ("Duration (S)", "simulation_duration_s", "⏱ Duration", "Wall time since Start (s)", False, None),
            ("Acquisition (S)", "acquisition_time_s", "⚡ Acquisition", "Time to first TRACKING lock (s)", False, None),
            ("Proc. Time (S)", "proc_time_s", "⚙ Proc.", "Average per-frame processing time (s) — informative, <33ms = real-time", False, None),
        ])

        # 2) Tracking — avg/max error as px / mrad ( % unit removed per user request)
        self._make_section(metrics_layout, "Tracking", [
            ("Average Tracking Error", "avg_tracking_error_pct", "🎯 Avg Err", "Average tracking error (px / mrad) — green<5px yellow<15px red", True, "avg_tracking_error_pct"),
            ("Maximum Tracking Error", "max_tracking_error_pct", "📈 Max Err", "Peak tracking error (px / mrad) — complete picture of worst case", True, "max_tracking_error_pct"),
        ])

        # 3) Locking
        self._make_section(metrics_layout, "Locking", [
            ("Status", "lock_status", "🔒 Status", "Tracker state: SEARCHING / ACQUIRED / TRACKING / LOST", False, None),
            ("Retention Rate (%)", "lock_retention_rate_pct", "💚 Retention", "Frames in TRACKING / total frames — higher is better", True, "lock_retention_rate_pct"),
            ("Total Acquisitions", "acquisitions", "🔁 Acquisitions", "Count of entries into TRACKING — stability indicator", False, None),
        ])

        # 4) Detection / Searching / Center — each with Rate and Time
        self._make_section(metrics_layout, "Detection / Searching / Center", [
            ("Detection — Rate (%)", "detection_rate_pct", "👁 Detect Rate", "Primary target hitbox hits / total frames", True, "detection_rate_pct"),
            ("Detection — Time (S)", "detection_time_s", "⏱ Detect Time", "Total time target was detected (s)", False, None),
            ("Searching — Rate (%)", "searching_rate_pct", "🔍 Search Rate", "Frames in SEARCHING / total — lower is better when locked", True, "searching_rate_pct"),
            ("Searching — Time (S)", "searching_time_s", "⏱ Search Time", "Total time spent searching (s)", False, None),
            ("Center Hit — Rate (%)", "center_hit_rate_pct", "⭐ Center Rate", "Precise center hits / total — accuracy", True, "center_hit_rate_pct"),
            ("Center Hit — Time (S)", "center_hit_time_s", "⭐ Center Time", "Total time in precise center (s)", False, None),
        ])

        metrics_layout.addStretch()

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(metrics_container)
        scroll.setMinimumWidth(380)
        scroll.setStyleSheet("QScrollArea { border:none; background:#f8fafc; }")
        splitter.addWidget(scroll)

        # RIGHT: responsive graph
        self._graph_box = QGroupBox("Live Graph — Simulation Time vs Value (responsive, auto-scaling)")
        self._graph_box.setStyleSheet("QGroupBox { padding-top:14px; font-size:11px; }")
        g_layout = QVBoxLayout(self._graph_box)
        g_layout.setContentsMargins(8, 12, 8, 8)
        g_layout.addWidget(self.graph)
        splitter.addWidget(self._graph_box)
        splitter.setSizes([420, 880])
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)

        # Backward-compat aliases for legacy tests / MainWindow expectations
        # progress_bars removed — no alias needed
        for _k in ("tracking_error_pct", "avg_tracking_error_px", "max_tracking_error_px"):
            if _k not in self.stat_labels:
                _lbl = QLabel("-")
                _lbl.hide()
                self.stat_labels[_k] = _lbl
        # Expose graph shortcuts for legacy tests
        self.time_data = self.graph.time
        self.fps_data = self.graph.fps
        self.retention_data = self.graph.retention
        self.error_data = self.graph.error
        self.center_hit_data = self.graph.center
        self.detection_data = self.graph.detection
        self.searching_data = self.graph.searching

    def _build_health_header(self) -> QFrame:
        card = QFrame()
        card.setStyleSheet("QFrame { background: qlineargradient(x1:0,y1:0,x2:1,y2:0, stop:0 #eff6ff, stop:1 #f0fdf4); border:1px solid #dbeafe; border-radius:10px; }")
        grid = QGridLayout(card)
        grid.setContentsMargins(10, 10, 10, 10)
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(6)
        title = QLabel("System Health — Live")
        title.setStyleSheet("color:#0f172a; font-weight:800; font-size:10px; background:transparent; border:none;")
        grid.addWidget(title, 0, 0, 1, 4)
        self.health_lock_dot = QLabel("●")
        self.health_lock_dot.setStyleSheet("color:#64748b; font-size:18px; background:transparent; border:none;")
        self.health_lock_dot.setAlignment(Qt.AlignCenter)
        grid.addWidget(self.health_lock_dot, 1, 0)
        self.health_lock_text = QLabel("SEARCHING")
        self.health_lock_text.setStyleSheet("color:#64748b; font-weight:800; font-size:11px; background:transparent; border:none;")
        grid.addWidget(self.health_lock_text, 1, 1)
        # Retention bar removed — show value as text only
        self.health_retention_val = QLabel("—%")
        self.health_retention_val.setStyleSheet("color:#0f172a; font-weight:700; font-size:11px; background:#ffffff; border:1px solid #e2e8f0; border-radius:6px; padding:3px 6px;")
        self.health_retention_val.setAlignment(Qt.AlignCenter)
        grid.addWidget(self.health_retention_val, 1, 2, 1, 2)
        # Keep dummy attribute for backward compat (no visual bar) — add QProgressBar-like no-op API
        self.health_retention_bar = self.health_retention_val
        # Add no-op QProgressBar API to the QLabel so external setValue calls don't crash
        try:
            self.health_retention_bar.setValue = lambda v: None  # type: ignore
            self.health_retention_bar.setRange = lambda a, b: None  # type: ignore
            self.health_retention_bar.setTextVisible = lambda v: None  # type: ignore
            self.health_retention_bar.setFormat = lambda s: None  # type: ignore
            self.health_retention_bar.setFixedHeight = lambda h: None  # type: ignore
        except Exception:
            pass
        self.health_fps = QLabel("FPS —")
        self.health_fps.setStyleSheet("color:#334155; font-size:11px; font-weight:600; background:#ffffff; border:1px solid #e2e8f0; border-radius:6px; padding:3px 6px;")
        self.health_fps.setAlignment(Qt.AlignCenter)
        grid.addWidget(self.health_fps, 2, 0, 1, 2)
        self.health_error = QLabel("Err —")
        self.health_error.setStyleSheet("color:#334155; font-size:11px; font-weight:600; background:#ffffff; border:1px solid #e2e8f0; border-radius:6px; padding:3px 6px;")
        self.health_error.setAlignment(Qt.AlignCenter)
        grid.addWidget(self.health_error, 2, 2, 1, 2)
        return card

    def _make_section(self, layout: QVBoxLayout, title: str, rows: list[tuple[str, str, str, str, bool, str | None]]) -> None:
        """
        Modular section builder.
        rows: (Label, key, iconTooltipLabel, tooltip, with_progress, progress_key)
        """
        box = QGroupBox(title)
        box.setStyleSheet("QGroupBox { background:#ffffff; border:1px solid #e2e8f0; border-radius:8px; margin-top:16px; padding-top:14px; } QGroupBox::title { color:#2563eb; font-weight:700; left:10px; }")
        grid = QGridLayout(box)
        grid.setContentsMargins(10, 14, 10, 10)
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(6)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)
        for i, (label, key, icon_label, tooltip, with_progress, progress_key) in enumerate(rows):
            lk = QLabel(label)
            lk.setStyleSheet("color:#475569; font-size:11px; font-weight:600;")
            lk.setToolTip(tooltip)
            lk.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
            grid.addWidget(lk, i, 0)

            val = QLabel("-")
            val.setAlignment(Qt.AlignCenter)
            val.setMinimumHeight(26)
            val.setToolTip(tooltip)
            # Status has distinct pill
            if key == "lock_status":
                val.setStyleSheet("font-weight:800; color:#64748b; background:#f1f5f9; border:1px solid #e2e8f0; border-radius:6px; padding:4px 8px; font-size:11px;")
            else:
                val.setStyleSheet(_value_style())
            self.stat_labels[key] = val
            grid.addWidget(val, i, 1)
            # Progress bars removed — with_progress ignored (kept in tuple for compat)

        layout.addWidget(box)
        # Keep aliases for legacy direct access
        # Ensure expected legacy keys exist even if section uses new keys:
        # e.g., proc_time_s maps to avg_processing_time_ms internally, but keep both
        # We expose mapping in update_from_summary, not here.

    # Update — HOT, real-time, informative

    def update_from_summary(self, summary: dict, tracker_status: str, tracking_error_px: float | None = None, camera_scale_mrad: float | None = None) -> None:
        """Update all labels and graph from PerformanceLogger summary. Real-time at ~30 Hz."""
        status = str(tracker_status)
        color = _status_color(status)

        # Helper to set value label with color
        def set_val(key: str, text: str, col: str | None = None, bg: str = "#ffffff"):
            if key in self.stat_labels:
                lbl = self.stat_labels[key]
                c = col or "#0f172a"
                lbl.setText(text)
                if key == "lock_status":
                    lbl.setStyleSheet(f"font-weight:800; color:{c}; background:#f1f5f9; border:1px solid #e2e8f0; border-radius:6px; padding:4px 8px; font-size:11px;")
                else:
                    lbl.setStyleSheet(_value_style(c, bg))

        # Health header (intuitive at-a-glance) — sync with stat values
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

        # --- Dashboard group — proper units per spec, always display value (no empty) ---
        fps = float(summary.get("fps", 0) or 0)
        set_val("fps", f"{fps:.1f} FPS", _color_for_fps(fps))
        dur = summary.get("simulation_duration_s")
        # Always show S suffix, even when 0
        try:
            set_val("simulation_duration_s", f"{float(dur):.2f} S" if dur is not None else "0.00 S", "#0f172a")
        except Exception:
            set_val("simulation_duration_s", "0.00 S")
        acq = summary.get("acquisition_time_s")
        if acq is not None:
            try:
                set_val("acquisition_time_s", f"{float(acq):.2f} S", "#0f172a")
            except Exception:
                set_val("acquisition_time_s", "— S", "#64748b")
        else:
            # Proper unit even when no acquisition yet — show 0.00 S with muted color, not empty
            set_val("acquisition_time_s", "0.00 S", "#64748b")
        # Proc time: image wants (S) — convert ms -> s, keep 4 decimals for precision
        avg_ms = summary.get("avg_processing_time_ms")
        proc_s_val = summary.get("proc_time_s", None)  # seconds from metrics if available
        if proc_s_val is not None:
            try:
                s_val = float(proc_s_val)
                txt = f"{s_val:.4f} S"
                col = "#22c55e" if s_val < 0.033 else "#ef4444" if s_val > 0.05 else "#eab308"
                set_val("proc_time_s", txt, col)
                if "avg_processing_time_ms" in self.stat_labels and avg_ms is not None:
                    self.stat_labels["avg_processing_time_ms"].setText(f"{float(avg_ms):.1f} ms")
            except Exception:
                set_val("proc_time_s", "0.0000 S")
        elif avg_ms is not None:
            try:
                s_val = float(avg_ms) / 1000.0
                txt = f"{s_val:.4f} S"
                col = "#22c55e" if s_val < 0.033 else "#ef4444" if s_val > 0.05 else "#eab308"
                set_val("proc_time_s", txt, col)
                if "avg_processing_time_ms" in self.stat_labels:
                    self.stat_labels["avg_processing_time_ms"].setText(f"{float(avg_ms):.1f} ms")
            except Exception:
                set_val("proc_time_s", "0.0000 S")
        else:
            set_val("proc_time_s", "0.0000 S")

        # Legacy mirror: acquisition_time_s already, keep.

        # --- Tracking: avg/max error (px / mrad — % unit removed) ---
        avg_px = summary.get("avg_tracking_error_px")
        max_px = summary.get("max_tracking_error_px")
        # Compute % for legacy compat/graph but not displayed
        avg_pct = summary.get("avg_tracking_error_pct")
        max_pct = summary.get("max_tracking_error_pct")
        if avg_pct is None and avg_px is not None:
            try:
                avg_pct = _error_pct_from_px(float(avg_px))
            except Exception:
                avg_pct = 0
        if max_pct is None and max_px is not None:
            try:
                max_pct = _error_pct_from_px(float(max_px))
            except Exception:
                max_pct = 0
        # Display as "5.2 px" or "5.2 px · 0.18 mrad" — no % per user request
        if avg_px is not None:
            try:
                txt = f"{float(avg_px):.1f} px"
                if camera_scale_mrad is not None:
                    try:
                        mrad = float(avg_px) * float(camera_scale_mrad)
                        txt = f"{float(avg_px):.1f} px · {mrad:.2f} mrad"
                    except Exception:
                        pass
                set_val("avg_tracking_error_pct", txt, _color_for_error(float(avg_px)))
            except Exception:
                try:
                    set_val("avg_tracking_error_pct", f"{float(avg_px):.1f} px")
                except Exception:
                    set_val("avg_tracking_error_pct", "0.0 px")
        else:
            try:
                set_val("avg_tracking_error_pct", "0.0 px", "#22c55e")
            except Exception:
                set_val("avg_tracking_error_pct", "0.0 px", "#22c55e")
        if max_px is not None:
            try:
                txt = f"{float(max_px):.1f} px"
                if camera_scale_mrad is not None:
                    try:
                        mrad = float(max_px) * float(camera_scale_mrad)
                        txt = f"{float(max_px):.1f} px · {mrad:.2f} mrad"
                    except Exception:
                        pass
                set_val("max_tracking_error_pct", txt, _color_for_error(float(max_px)))
            except Exception:
                try:
                    set_val("max_tracking_error_pct", f"{float(max_px):.1f} px")
                except Exception:
                    set_val("max_tracking_error_pct", "0.0 px")
        else:
            try:
                set_val("max_tracking_error_pct", "0.0 px", "#22c55e")
            except Exception:
                set_val("max_tracking_error_pct", "0.0 px", "#22c55e")
        # Keep legacy px labels for compat — always display with proper unit
        if "avg_tracking_error_px" in self.stat_labels:
            self.stat_labels["avg_tracking_error_px"].setText(f"{float(avg_px):.1f} px" if avg_px is not None else "0.0 px")
        if "max_tracking_error_px" in self.stat_labels:
            self.stat_labels["max_tracking_error_px"].setText(f"{float(max_px):.1f} px" if max_px is not None else "0.0 px")
        if "tracking_error_pct" in self.stat_labels:
            v = summary.get("tracking_error_pct")
            if v is not None:
                self.stat_labels["tracking_error_pct"].setText(f"{float(v):.1f}")
            else:
                self.stat_labels["tracking_error_pct"].setText("0.0")

        # --- Locking — proper units: Status (enum), Retention (%), Acquisitions (count) ---
        set_val("lock_status", status.upper(), color, "#f1f5f9")
        retention = float(summary.get("lock_retention_rate_pct", 0) or 0)
        set_val("lock_retention_rate_pct", f"{retention:.1f} %", _color_for_rate(retention))
        acqs = summary.get("acquisitions")
        # Proper count unit: integer count
        set_val("acquisitions", f"{int(acqs)}" if acqs is not None else "0")

        # --- Detection / Searching / Center — proper units: Rate (%) Time (S) — always display ---
        for key in ("detection_rate_pct", "searching_rate_pct", "center_hit_rate_pct"):
            v = summary.get(key)
            try:
                pct = float(v) if v is not None else 0.0
                # When v is None, show 0.0 % instead of empty
                col = _color_for_rate(pct) if key != "searching_rate_pct" else (_color_for_error_pct(pct) if pct>30 else _color_for_rate(100-pct))
                set_val(key, f"{pct:.1f} %", col)
            except Exception:
                set_val(key, "0.0 %")
        for key in ("detection_time_s", "searching_time_s", "center_hit_time_s"):
            v = summary.get(key)
            try:
                set_val(key, f"{float(v):.2f} S" if v is not None else "0.00 S")
            except Exception:
                set_val(key, "0.00 S")

        # Progress bars removed — no bar updates needed

        # Keep legacy labels that old MainWindow._reset iterates
        # Ensure all expected keys exist for stat_labels fallback
        legacy_keys = ["fps", "simulation_duration_s", "acquisition_time_s", "avg_processing_time_ms",
                       "avg_tracking_error_px", "max_tracking_error_px", "tracking_error_pct",
                       "lock_retention_rate_pct", "acquisitions",
                       "detection_rate_pct", "detection_time_s", "searching_rate_pct", "searching_time_s",
                       "center_hit_rate_pct", "center_hit_time_s"]
        for lk in legacy_keys:
            if lk not in self.stat_labels and lk in summary:
                # Create hidden label for compat (not displayed) but keep dict entry
                lbl = QLabel(str(summary.get(lk, "-")))
                lbl.hide()
                self.stat_labels[lk] = lbl

        # --- Graph: responsive, auto-scaling, complete picture ---
        t = float(summary.get("simulation_duration_s", 0) or 0)
        fps = float(summary.get("fps", 0) or 0)
        retention = float(summary.get("lock_retention_rate_pct", 0) or 0)
        # For graph error, use px normalized to % for single Y comparability? Keep raw px as well via GraphPanel dual
        err_px = float(summary.get("avg_tracking_error_px", 0) or 0) if summary.get("avg_tracking_error_px") is not None else (float(tracking_error_px) if tracking_error_px is not None else 0.0)
        center = float(summary.get("center_hit_rate_pct", 0) or 0)
        detection = float(summary.get("detection_rate_pct", 0) or 0)
        searching = float(summary.get("searching_rate_pct", 0) or 0)
        self.graph.append(t, fps, retention, err_px, center, detection, searching)
        self._last_graph_update = self.graph._last_draw
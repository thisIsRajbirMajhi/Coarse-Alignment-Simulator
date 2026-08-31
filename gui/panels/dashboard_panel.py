"""
Module: gui.panels.dashboard_panel
Purpose: Intuitive live performance dashboard — health overview + grouped cards with visual indicators.
Public API: DashboardPanel
Sections (intuitive, 6 groups + health header):
  - Health header: large lock status + retention progress + FPS + avg error (color-coded)
  - Timing & Rate: FPS, duration, acquisition, processing (with jitter)
  - Tracking Error: avg/max/error% with color + angular mrad if available
  - Lock Status: status, retention, acquisitions (with progress & pulse)
  - Detection/Searching/Center: rates as progress bars + times
Notes: Modular, well-commented, HOT via update_from_summary(summary, tracker_status, error_px, camera_scale).
       Keeps stat_labels dict for backward compat, but new code uses progress bars and health.
       Rebuild 2026-08-31: fixes real-time, calc bugs, rate-limit, unbounded history, precedence, color inversion.
"""

from collections import deque
import pyqtgraph as pg
from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QScrollArea,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

# ============================================================
# SECTION: DashboardPanel — intuitive, visual (rebuilt)
# ============================================================

class DashboardPanel(QWidget):
    """
    Intuitive dashboard — health header + 6 grouped cards with icons, progress, color.

    Visual cues:
      - Lock colors: tracking=green, acquired=cyan, lost=red, searching=gray
      - Retention/Detection/Center progress: green >80, yellow 50-80, red <50
      - Error: green <5px, yellow 5-15, red >15 (inverted vs retention)
      - FPS: green >25, yellow 15-25, red <15
    Real-time: _update_stats every tick drives labels/health immediately; graph throttled to 5 Hz.
    History: capped deques (MAX_HISTORY) to prevent memory bloat.
    """

    # keep last 60 seconds at 30 Hz ≈ 1800 points; cap at 2000 for safety
    MAX_HISTORY = 2000

    def __init__(self, parent=None):
        super().__init__(parent)
        self.stat_labels: dict[str, QLabel] = {}
        self.progress_bars: dict[str, QProgressBar] = {}

        # History buffers — deques with maxlen to bound memory (FIX: was unbounded list)
        self.time_data = deque(maxlen=self.MAX_HISTORY)
        self.fps_data = deque(maxlen=self.MAX_HISTORY)
        self.retention_data = deque(maxlen=self.MAX_HISTORY)
        self.error_data = deque(maxlen=self.MAX_HISTORY)
        self.center_hit_data = deque(maxlen=self.MAX_HISTORY)
        self.detection_data = deque(maxlen=self.MAX_HISTORY)
        self.searching_data = deque(maxlen=self.MAX_HISTORY)

        self._last_graph_update = 0.0
        self._build_ui()

    def reset_history(self):
        """Clear graph history — called on simulation reset for instant visual reset."""
        self.time_data.clear()
        self.fps_data.clear()
        self.retention_data.clear()
        self.error_data.clear()
        self.center_hit_data.clear()
        self.detection_data.clear()
        self.searching_data.clear()
        # reset rate limiter so next tick draws immediately
        self._last_graph_update = 0.0
        try:
            # clear curves visually
            self.fps_curve.setData([], [])
            self.retention_curve.setData([], [])
            self.error_curve.setData([], [])
            self.center_hit_curve.setData([], [])
            self.detection_curve.setData([], [])
            self.searching_curve.setData([], [])
        except Exception:
            pass

    # ========================================================
    # Build UI — health header + 6 cards
    # ========================================================

    def _build_ui(self) -> None:
        main_layout = QHBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)

        splitter = QSplitter(Qt.Horizontal)
        main_layout.addWidget(splitter)

        # --- LEFT PANEL: Metrics ---
        metrics_container = QWidget()
        metrics_layout = QVBoxLayout(metrics_container)
        metrics_layout.setContentsMargins(8, 8, 8, 8)
        metrics_layout.setSpacing(10)

        # Health header — large, at-a-glance
        self.health_card = self._build_health_header()
        metrics_layout.addWidget(self.health_card)

        self._make_section(metrics_layout, "Timing & Rate", [
            ("FPS", "fps", "📊"),
            ("Duration (s)", "simulation_duration_s", "⏱"),
            ("Acquisition (s)", "acquisition_time_s", "⚡"),
            ("Proc. Time (ms)", "avg_processing_time_ms", "⚙"),
        ], with_progress=False)

        self._make_section(metrics_layout, "Tracking Error", [
            ("Avg Error (px)", "avg_tracking_error_px", "🎯"),
            ("Max Error (px)", "max_tracking_error_px", "📈"),
            ("Error (%)", "tracking_error_pct", "📊"),
        ], with_progress=True, progress_key="tracking_error_pct")

        self._make_section(metrics_layout, "Lock Status", [
            ("Status", "lock_status", "🔒"),
            ("Retention (%)", "lock_retention_rate_pct", "💚"),
            ("Acquisitions", "acquisitions", "🔁"),
        ], with_progress=True, progress_key="lock_retention_rate_pct")

        self._make_section(metrics_layout, "Detection", [
            ("Rate (%)", "detection_rate_pct", "👁"),
            ("Time (s)", "detection_time_s", "⏱"),
        ], with_progress=True, progress_key="detection_rate_pct")

        self._make_section(metrics_layout, "Searching", [
            ("Rate (%)", "searching_rate_pct", "🔍"),
            ("Time (s)", "searching_time_s", "⏱"),
        ], with_progress=True, progress_key="searching_rate_pct")

        self._make_section(metrics_layout, "Center Hit", [
            ("Rate (%)", "center_hit_rate_pct", "🎯"),
            ("Time (s)", "center_hit_time_s", "⭐"),
        ], with_progress=True, progress_key="center_hit_rate_pct")

        metrics_layout.addStretch()

        metrics_scroll = QScrollArea()
        metrics_scroll.setWidgetResizable(True)
        metrics_scroll.setWidget(metrics_container)
        metrics_scroll.setMinimumWidth(350)
        metrics_scroll.setStyleSheet("QScrollArea { border: none; background: #f8fafc; }")

        splitter.addWidget(metrics_scroll)

        # --- RIGHT PANEL: Graph ---
        self.graph_box = QGroupBox("Metrics Over Time")
        self.graph_box.setStyleSheet("QGroupBox { padding-top: 14px; font-size: 11px; }")
        graph_layout = QVBoxLayout(self.graph_box)
        graph_layout.setContentsMargins(10, 12, 10, 8)

        self.plot_widget = pg.PlotWidget()
        self.plot_widget.setBackground('#ffffff')
        self.plot_widget.showGrid(x=True, y=True, alpha=0.3)
        self.plot_widget.setLabel('bottom', 'Simulation Time (s)')
        self.plot_widget.setLabel('left', 'Value (%, px, FPS)')
        self.plot_widget.addLegend(offset=(10, 10))

        self.fps_curve = self.plot_widget.plot(pen=pg.mkPen('#3b82f6', width=2), name='FPS')
        self.retention_curve = self.plot_widget.plot(pen=pg.mkPen('#22c55e', width=2), name='Retention (%)')
        self.error_curve = self.plot_widget.plot(pen=pg.mkPen('#ef4444', width=2), name='Error (px)')
        self.center_hit_curve = self.plot_widget.plot(pen=pg.mkPen('#eab308', width=2), name='Center Hit (%)')
        self.detection_curve = self.plot_widget.plot(pen=pg.mkPen('#8b5cf6', width=2), name='Detection (%)')
        self.searching_curve = self.plot_widget.plot(pen=pg.mkPen('#64748b', width=2), name='Searching (%)')

        graph_layout.addWidget(self.plot_widget)
        splitter.addWidget(self.graph_box)

        # Give graph more space by default
        splitter.setSizes([350, 900])

    def _build_health_header(self) -> QFrame:
        card = QFrame()
        card.setStyleSheet("QFrame { background: qlineargradient(x1:0,y1:0,x2:1,y2:0, stop:0 #eff6ff, stop:1 #f0fdf4); border: 1px solid #dbeafe; border-radius: 10px; }")
        grid = QGridLayout(card)
        grid.setContentsMargins(12, 12, 12, 12)
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(6)

        title = QLabel("System Health — Live")
        title.setStyleSheet("color:#0f172a; font-weight:800; font-size:11px; background:transparent; border:none;")
        grid.addWidget(title, 0, 0, 1, 4)

        self.health_lock_dot = QLabel("●")
        self.health_lock_dot.setStyleSheet("color:#64748b; font-size:22px; background:transparent; border:none;")
        self.health_lock_dot.setAlignment(Qt.AlignCenter)
        grid.addWidget(self.health_lock_dot, 1, 0)

        self.health_lock_text = QLabel("SEARCHING")
        self.health_lock_text.setStyleSheet("color:#0f172a; font-weight:800; font-size:13px; background:transparent; border:none;")
        self.health_lock_text.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        grid.addWidget(self.health_lock_text, 1, 1)

        self.health_retention_bar = QProgressBar()
        self.health_retention_bar.setRange(0, 100)
        self.health_retention_bar.setValue(0)
        self.health_retention_bar.setTextVisible(True)
        self.health_retention_bar.setFormat("%p% retention")
        self.health_retention_bar.setFixedHeight(18)
        self.health_retention_bar.setStyleSheet(self._progress_style("#22c55e"))
        grid.addWidget(self.health_retention_bar, 1, 2)

        self.health_retention_val = QLabel("—%")
        self.health_retention_val.setStyleSheet("color:#0f172a; font-weight:700; font-size:11px; background:transparent; border:none;")
        grid.addWidget(self.health_retention_val, 1, 3)

        self.health_fps = QLabel("FPS —")
        self.health_fps.setStyleSheet("color:#334155; font-size:11px; font-weight:600; background:#ffffff; border:1px solid #e2e8f0; border-radius:6px; padding:4px 6px;")
        self.health_fps.setAlignment(Qt.AlignCenter)
        grid.addWidget(self.health_fps, 2, 0, 1, 2)

        self.health_error = QLabel("Err —")
        self.health_error.setStyleSheet("color:#334155; font-size:11px; font-weight:600; background:#ffffff; border:1px solid #e2e8f0; border-radius:6px; padding:4px 6px;")
        self.health_error.setAlignment(Qt.AlignCenter)
        grid.addWidget(self.health_error, 2, 2, 1, 2)

        return card

    def _make_section(self, layout: QVBoxLayout, title: str, rows: list[tuple[str, str, str]], with_progress: bool = False, progress_key: str | None = None) -> None:
        box = QGroupBox(title)
        box.setStyleSheet("QGroupBox { padding-top: 14px; font-size: 11px; }")
        grid = QGridLayout(box)
        grid.setContentsMargins(10, 12, 10, 8)
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(5)
        grid.setColumnStretch(0, 0)
        grid.setColumnStretch(1, 1)
        grid.setColumnStretch(2, 1)
        for i, (label, key, icon) in enumerate(rows):
            lk = QLabel(f"{icon} {label}")
            lk.setStyleSheet("color:#475569; font-size:11px;")
            lk.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
            grid.addWidget(lk, i, 0)
            val = QLabel("-")
            val.setAlignment(Qt.AlignCenter)
            val.setMinimumHeight(24)
            if key == "lock_status":
                val.setStyleSheet("font-weight:700; color:#0f172a; background:#f1f5f9; border:1px solid #e2e8f0; border-radius:6px; padding:3px 6px; font-size:11px;")
            else:
                val.setStyleSheet("font-weight:600; color:#0f172a; background:#ffffff; border:1px solid #e2e8f0; border-radius:6px; padding:3px 6px; font-size:11px;")
            self.stat_labels[key] = val
            grid.addWidget(val, i, 1)
            # FIX: precedence bug — was `with_progress and "rate" in key or "pct" in key` (pct always true)
            # Correct: with_progress and ("rate" in key or "pct" in key)
            if with_progress and key == progress_key:
                bar = QProgressBar()
                bar.setRange(0, 100)
                bar.setValue(0)
                bar.setTextVisible(False)
                bar.setFixedHeight(8)
                bar.setStyleSheet(self._progress_style("#3b82f6"))
                grid.addWidget(bar, i, 2)
                self.progress_bars[key] = bar
            elif with_progress and ("rate" in key or "pct" in key):
                bar = QProgressBar()
                bar.setRange(0, 100)
                bar.setValue(0)
                bar.setTextVisible(False)
                bar.setFixedHeight(8)
                bar.setStyleSheet(self._progress_style("#64748b"))
                grid.addWidget(bar, i, 2)
                self.progress_bars[key] = bar
        layout.addWidget(box)

    def _progress_style(self, color: str) -> str:
        return f"QProgressBar {{ border:1px solid #e2e8f0; border-radius:4px; background:#f1f5f9; }} QProgressBar::chunk {{ background:{color}; border-radius:3px; }}"

    def _color_for_rate(self, pct: float) -> str:
        if pct >= 80:
            return "#22c55e"
        if pct >= 50:
            return "#eab308"
        return "#ef4444"

    def _color_for_error(self, err_px: float) -> str:
        if err_px < 5:
            return "#22c55e"
        if err_px < 15:
            return "#eab308"
        return "#ef4444"

    def _color_for_fps(self, fps: float) -> str:
        if fps >= 25:
            return "#22c55e"
        if fps >= 15:
            return "#eab308"
        return "#ef4444"

    def _color_for_error_pct(self, pct: float) -> str:
        """Inverted: high error % is BAD (red), low is good (green)."""
        if pct <= 20:
            return "#22c55e"
        if pct <= 50:
            return "#eab308"
        return "#ef4444"

    def _status_color(self, status: str) -> str:
        return {"tracking": "#22c55e", "acquired": "#06b6d4", "lost": "#ef4444", "searching": "#64748b"}.get(status.lower(), "#64748b")

    # ========================================================
    # Update — called from MainWindow._update_stats (every tick)
    # ========================================================

    def update_from_summary(self, summary: dict, tracker_status: str, tracking_error_px: float | None = None, camera_scale_mrad: float | None = None) -> None:
        """Update all labels, progress, and health header from PerformanceLogger summary.
        Real-time: health + labels update every call (~30 Hz); graph throttled to 5 Hz.
        """
        # Health header — lock + retention + fps + error
        status = str(tracker_status)
        color = self._status_color(status)
        self.health_lock_dot.setStyleSheet(f"color:{color}; font-size:22px; background:transparent; border:none;")
        self.health_lock_text.setText(status.upper())
        self.health_lock_text.setStyleSheet(f"color:{color}; font-weight:800; font-size:13px; background:transparent; border:none;")

        retention = float(summary.get("lock_retention_rate_pct", 0) or 0)
        self.health_retention_bar.setValue(int(max(0, min(100, retention))))
        self.health_retention_bar.setStyleSheet(self._progress_style(self._color_for_rate(retention)))
        self.health_retention_val.setText(f"{retention:.1f}%")

        fps = float(summary.get("fps", 0) or 0)
        self.health_fps.setText(f"FPS {fps:.1f}")
        self.health_fps.setStyleSheet(f"color:{self._color_for_fps(fps)}; font-weight:700; font-size:11px; background:#ffffff; border:1px solid #e2e8f0; border-radius:6px; padding:4px 6px;")

        if tracking_error_px is not None:
            try:
                scale = float(camera_scale_mrad) if camera_scale_mrad is not None else 0.035
                mrad = tracking_error_px * scale
                label = f"Err {tracking_error_px:.1f}px {mrad:.2f}mrad"
                self.health_error.setText(label)
                self.health_error.setStyleSheet(f"color:{self._color_for_error(tracking_error_px)}; font-weight:700; font-size:11px; background:#ffffff; border:1px solid #e2e8f0; border-radius:6px; padding:4px 6px;")
            except Exception:
                self.health_error.setText(f"Err {tracking_error_px:.1f}px")
        else:
            self.health_error.setText("Err —")
            self.health_error.setStyleSheet("color:#64748b; font-size:11px; background:#ffffff; border:1px solid #e2e8f0; border-radius:6px; padding:4px 6px;")

        # Update all stat_labels (backward compat)
        for key in ["fps", "simulation_duration_s", "acquisition_time_s", "avg_processing_time_ms",
                    "avg_tracking_error_px", "max_tracking_error_px", "tracking_error_pct",
                    "lock_retention_rate_pct", "acquisitions",
                    "detection_rate_pct", "detection_time_s", "searching_rate_pct", "searching_time_s",
                    "center_hit_rate_pct", "center_hit_time_s"]:
            if key in self.stat_labels:
                v = summary.get(key)
                txt = str(v) if v is not None else "-"
                if key in ("avg_tracking_error_px", "max_tracking_error_px") and v is not None and camera_scale_mrad is not None:
                    try:
                        mrad = float(v) * float(camera_scale_mrad)
                        txt = f"{v} ({mrad:.2f} mrad)"
                    except Exception:
                        pass
                self.stat_labels[key].setText(txt)
                if key in ("avg_tracking_error_px", "max_tracking_error_px") and v is not None:
                    try:
                        self.stat_labels[key].setStyleSheet(f"font-weight:700; color:{self._color_for_error(float(v))}; background:#ffffff; border:1px solid #e2e8f0; border-radius:6px; padding:3px 6px; font-size:11px;")
                    except Exception:
                        pass
                # Fix: tracking_error_pct progress should be inverted color (high error = red)
                if key == "tracking_error_pct" and v is not None:
                    try:
                        # keep label color as error scale too
                        self.stat_labels[key].setStyleSheet(f"font-weight:700; color:{self._color_for_error_pct(float(v))}; background:#ffffff; border:1px solid #e2e8f0; border-radius:6px; padding:3px 6px; font-size:11px;")
                    except Exception:
                        pass
        if "lock_status" in self.stat_labels:
            self.stat_labels["lock_status"].setText(status)
            self.stat_labels["lock_status"].setStyleSheet(f"font-weight:700; color:{color}; background:#f1f5f9; border:1px solid #e2e8f0; border-radius:6px; padding:3px 6px; font-size:11px;")

        # Progress bars — update from summary rates (FIX: inverted for error)
        for key, bar in self.progress_bars.items():
            v = summary.get(key)
            if v is not None:
                try:
                    pct = float(v)
                    pct = max(0, min(100, pct))
                    bar.setValue(int(pct))
                    if key == "tracking_error_pct":
                        bar.setStyleSheet(self._progress_style(self._color_for_error_pct(pct)))
                    else:
                        bar.setStyleSheet(self._progress_style(self._color_for_rate(pct)))
                except Exception:
                    pass
            else:
                bar.setValue(0)

        # Update graph data — FIX: bounded deques, handle reset, throttle draw
        t = float(summary.get("simulation_duration_s", 0) or 0)
        fps = float(summary.get("fps", 0) or 0)
        retention = float(summary.get("lock_retention_rate_pct", 0) or 0)
        err = summary.get("avg_tracking_error_px", 0)
        err = float(err) if err is not None else 0.0
        center_hit = float(summary.get("center_hit_rate_pct", 0) or 0)
        detection = float(summary.get("detection_rate_pct", 0) or 0)
        searching = float(summary.get("searching_rate_pct", 0) or 0)
        # Handle resets (time went backwards) — clear history
        if self.time_data and len(self.time_data) > 0:
            last_t = self.time_data[-1]
            if t < last_t - 1e-6:
                self.reset_history()
            elif abs(t - last_t) < 1e-9:
                # Paused: same timestamp, skip appending but health already updated
                return

        self.time_data.append(t)
        self.fps_data.append(fps)
        self.retention_data.append(retention)
        self.error_data.append(err)
        self.center_hit_data.append(center_hit)
        self.detection_data.append(detection)
        self.searching_data.append(searching)

        # Throttle graph rendering to 5 Hz (every 200 ms) — FIX: use monotonic time, not wall
        import time
        now = time.monotonic()
        if (now - self._last_graph_update) > 0.2:
            # Deques -> lists for pyqtgraph
            self.fps_curve.setData(list(self.time_data), list(self.fps_data))
            self.retention_curve.setData(list(self.time_data), list(self.retention_data))
            self.error_curve.setData(list(self.time_data), list(self.error_data))
            self.center_hit_curve.setData(list(self.time_data), list(self.center_hit_data))
            self.detection_curve.setData(list(self.time_data), list(self.detection_data))
            self.searching_curve.setData(list(self.time_data), list(self.searching_data))
            self._last_graph_update = now

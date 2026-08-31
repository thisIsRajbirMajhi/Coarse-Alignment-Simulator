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
"""

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QVBoxLayout,
    QWidget,
)

# ============================================================
# SECTION: DashboardPanel — intuitive, visual
# ============================================================

class DashboardPanel(QWidget):
    """
    Intuitive dashboard — health header + 6 grouped cards with icons, progress, color.

    Visual cues:
      - Lock colors: tracking=green, acquired=cyan, lost=red, searching=gray
      - Retention/Detection/Center progress: green >80, yellow 50-80, red <50
      - Error: green <5px, yellow 5-15, red >15
      - FPS: green >25, yellow 15-25, red <15
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.stat_labels: dict[str, QLabel] = {}
        self.progress_bars: dict[str, QProgressBar] = {}
        self._build_ui()

    # ========================================================
    # Build UI — health header + 6 cards
    # ========================================================

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(10)

        # Health header — large, at-a-glance
        self.health_card = self._build_health_header()
        layout.addWidget(self.health_card)

        # Two-column grid for 6 cards (more compact, intuitive)
        self._make_section(layout, "Timing & Rate", [
            ("FPS", "fps", "📊"),
            ("Duration (s)", "simulation_duration_s", "⏱"),
            ("Acquisition (s)", "acquisition_time_s", "⚡"),
            ("Proc. Time (ms)", "avg_processing_time_ms", "⚙"),
        ], with_progress=False)

        self._make_section(layout, "Tracking Error", [
            ("Avg Error (px)", "avg_tracking_error_px", "🎯"),
            ("Max Error (px)", "max_tracking_error_px", "📈"),
            ("Error (%)", "tracking_error_pct", "📊"),
        ], with_progress=True, progress_key="tracking_error_pct")

        self._make_section(layout, "Lock Status", [
            ("Status", "lock_status", "🔒"),
            ("Retention (%)", "lock_retention_rate_pct", "💚"),
            ("Acquisitions", "acquisitions", "🔁"),
        ], with_progress=True, progress_key="lock_retention_rate_pct")

        self._make_section(layout, "Detection", [
            ("Rate (%)", "detection_rate_pct", "👁"),
            ("Time (s)", "detection_time_s", "⏱"),
        ], with_progress=True, progress_key="detection_rate_pct")

        self._make_section(layout, "Searching", [
            ("Rate (%)", "searching_rate_pct", "🔍"),
            ("Time (s)", "searching_time_s", "⏱"),
        ], with_progress=True, progress_key="searching_rate_pct")

        self._make_section(layout, "Center Hit", [
            ("Rate (%)", "center_hit_rate_pct", "🎯"),
            ("Time (s)", "center_hit_time_s", "⭐"),
        ], with_progress=True, progress_key="center_hit_rate_pct")

        layout.addStretch()

    def _build_health_header(self) -> QFrame:
        card = QFrame()
        card.setStyleSheet("QFrame { background: qlineargradient(x1:0,y1:0,x2:1,y2:0, stop:0 #eff6ff, stop:1 #f0fdf4); border: 1px solid #dbeafe; border-radius: 10px; }")
        grid = QGridLayout(card)
        grid.setContentsMargins(12, 12, 12, 12)
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(6)

        # Title
        title = QLabel("System Health — Live")
        title.setStyleSheet("color:#0f172a; font-weight:800; font-size:11px; background:transparent; border:none;")
        grid.addWidget(title, 0, 0, 1, 4)

        # LOCK — large dot + text
        self.health_lock_dot = QLabel("●")
        self.health_lock_dot.setStyleSheet("color:#64748b; font-size:22px; background:transparent; border:none;")
        self.health_lock_dot.setAlignment(Qt.AlignCenter)
        grid.addWidget(self.health_lock_dot, 1, 0)

        self.health_lock_text = QLabel("SEARCHING")
        self.health_lock_text.setStyleSheet("color:#0f172a; font-weight:800; font-size:13px; background:transparent; border:none;")
        self.health_lock_text.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        grid.addWidget(self.health_lock_text, 1, 1)

        # Retention — progress + value
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

        # FPS + Error row
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
            # Icon + label
            lk = QLabel(f"{icon} {label}")
            lk.setStyleSheet("color:#475569; font-size:11px;")
            lk.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
            grid.addWidget(lk, i, 0)
            # Value
            val = QLabel("-")
            val.setAlignment(Qt.AlignCenter)
            val.setMinimumHeight(24)
            if key == "lock_status":
                val.setStyleSheet("font-weight:700; color:#0f172a; background:#f1f5f9; border:1px solid #e2e8f0; border-radius:6px; padding:3px 6px; font-size:11px;")
            else:
                val.setStyleSheet("font-weight:600; color:#0f172a; background:#ffffff; border:1px solid #e2e8f0; border-radius:6px; padding:3px 6px; font-size:11px;")
            self.stat_labels[key] = val
            grid.addWidget(val, i, 1)
            # Progress for rates (intuitive bar)
            if with_progress and key == progress_key:
                bar = QProgressBar()
                bar.setRange(0, 100)
                bar.setValue(0)
                bar.setTextVisible(False)
                bar.setFixedHeight(8)
                bar.setStyleSheet(self._progress_style("#3b82f6"))
                grid.addWidget(bar, i, 2)
                self.progress_bars[key] = bar
            elif with_progress and "rate" in key or "pct" in key:
                # Also add bar for any rate/pct in this section if not already
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

    def _status_color(self, status: str) -> str:
        return {"tracking": "#22c55e", "acquired": "#06b6d4", "lost": "#ef4444", "searching": "#64748b"}.get(status.lower(), "#64748b")

    # ========================================================
    # Update — called from MainWindow._update_stats
    # ========================================================

    def update_from_summary(self, summary: dict, tracker_status: str, tracking_error_px: float | None = None, camera_scale_mrad: float | None = None) -> None:
        """Update all labels, progress, and health header from PerformanceLogger summary."""
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
            except:
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
                # Add angular for avg/max error if scale available
                if key in ("avg_tracking_error_px", "max_tracking_error_px") and v is not None and camera_scale_mrad is not None:
                    try:
                        mrad = float(v) * float(camera_scale_mrad)
                        txt = f"{v} ({mrad:.2f} mrad)"
                    except: pass
                self.stat_labels[key].setText(txt)
                # Color error values
                if key in ("avg_tracking_error_px", "max_tracking_error_px") and v is not None:
                    try:
                        self.stat_labels[key].setStyleSheet(f"font-weight:700; color:{self._color_for_error(float(v))}; background:#ffffff; border:1px solid #e2e8f0; border-radius:6px; padding:3px 6px; font-size:11px;")
                    except: pass
        if "lock_status" in self.stat_labels:
            self.stat_labels["lock_status"].setText(status)
            self.stat_labels["lock_status"].setStyleSheet(f"font-weight:700; color:{color}; background:#f1f5f9; border:1px solid #e2e8f0; border-radius:6px; padding:3px 6px; font-size:11px;")

        # Progress bars — update from summary rates
        for key, bar in self.progress_bars.items():
            v = summary.get(key)
            if v is not None:
                try:
                    pct = float(v) if "pct" in key or "rate" in key else float(v)
                    # Error pct is 0-100 as well
                    pct = max(0, min(100, pct))
                    bar.setValue(int(pct))
                    bar.setStyleSheet(self._progress_style(self._color_for_rate(pct)))
                except: pass
            else:
                bar.setValue(0)

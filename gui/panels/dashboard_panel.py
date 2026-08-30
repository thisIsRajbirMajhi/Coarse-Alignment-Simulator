"""
Module: gui.panels.dashboard_panel
Purpose: Live performance dashboard — 6 sections exactly as specified.
Public API: DashboardPanel
Sections:
  Timing & rate | Tracking error | Lock status | Detection | Searching | Center hit
Notes: Extracted from gui.app monolith — modular, well-commented.
       Provides update_from_summary(summary, tracker_status) for HOT live updates.
"""

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QGridLayout, QGroupBox, QLabel, QVBoxLayout, QWidget

# ============================================================
# SECTION: DashboardPanel — Live metrics display
# ============================================================

class DashboardPanel(QWidget):
    """
    Dashboard displaying 6 requested sections (14 metrics).

    - No controls, only labels updated via update_from_summary().
    - Styles kept consistent with APP_STYLE (white cards, blue headers).
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.stat_labels: dict[str, QLabel] = {}
        self._build_ui()

    # ========================================================
    # Build UI — 6 grouped sections
    # ========================================================

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(10)

        self._make_section(layout, "Timing & rate", [
            ("FPS", "fps"),
            ("Simulation duration (s)", "simulation_duration_s"),
            ("Acquisition time (s)", "acquisition_time_s"),
            ("Processing time (ms)", "avg_processing_time_ms"),
        ])
        self._make_section(layout, "Tracking error", [
            ("Average tracking error (px)", "avg_tracking_error_px"),
            ("Maximum tracking error (px)", "max_tracking_error_px"),
            ("Tracking error (%)", "tracking_error_pct"),
        ])
        self._make_section(layout, "Lock status", [
            ("Lock status", "lock_status"),
            ("Lock retention rate (%)", "lock_retention_rate_pct"),
            ("Acquisitions (count)", "acquisitions"),
        ])
        self._make_section(layout, "Detection", [
            ("Detection rate (%)", "detection_rate_pct"),
            ("Detection time (s)", "detection_time_s"),
        ])
        self._make_section(layout, "Searching", [
            ("Searching rate (%)", "searching_rate_pct"),
            ("Searching time (s)", "searching_time_s"),
        ])
        self._make_section(layout, "Center hit", [
            ("Center hit rate (%)", "center_hit_rate_pct"),
            ("Center hit time (s)", "center_hit_time_s"),
        ])
        layout.addStretch()

    def _make_section(self, layout: QVBoxLayout, title: str, rows: list[tuple[str, str]]) -> None:
        box = QGroupBox(title)
        box.setStyleSheet("QGroupBox { padding-top: 14px; font-size: 11px; }")
        grid = QGridLayout(box)
        grid.setContentsMargins(10, 12, 10, 8)
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(5)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)
        for i, (label, key) in enumerate(rows):
            lk = QLabel(label)
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
        layout.addWidget(box)

    # ========================================================
    # Update — called from MainWindow._update_stats
    # ========================================================

    def update_from_summary(self, summary: dict, tracker_status: str, tracking_error_px: float | None = None) -> None:
        """Update all label texts from PerformanceLogger summary + tracker status."""
        # Timing & rate
        if "fps" in self.stat_labels:
            self.stat_labels["fps"].setText(str(summary.get("fps", "-")))
        if "simulation_duration_s" in self.stat_labels:
            self.stat_labels["simulation_duration_s"].setText(str(summary.get("simulation_duration_s", "-")))
        if "acquisition_time_s" in self.stat_labels:
            v = summary.get("acquisition_time_s")
            self.stat_labels["acquisition_time_s"].setText(str(v) if v is not None else "-")
        if "avg_processing_time_ms" in self.stat_labels:
            self.stat_labels["avg_processing_time_ms"].setText(str(summary.get("avg_processing_time_ms", "-")))
        # Tracking error
        if "avg_tracking_error_px" in self.stat_labels:
            self.stat_labels["avg_tracking_error_px"].setText(str(summary.get("avg_tracking_error_px", "-")))
        if "max_tracking_error_px" in self.stat_labels:
            self.stat_labels["max_tracking_error_px"].setText(str(summary.get("max_tracking_error_px", "-")))
        if "tracking_error_pct" in self.stat_labels:
            self.stat_labels["tracking_error_pct"].setText(str(summary.get("tracking_error_pct", "-")))
        # Lock
        if "lock_status" in self.stat_labels:
            self.stat_labels["lock_status"].setText(str(tracker_status))
        if "lock_retention_rate_pct" in self.stat_labels:
            self.stat_labels["lock_retention_rate_pct"].setText(str(summary.get("lock_retention_rate_pct", "-")))
        if "acquisitions" in self.stat_labels:
            self.stat_labels["acquisitions"].setText(str(summary.get("acquisitions", "-")))
        # Detection / Searching / Center
        if "detection_rate_pct" in self.stat_labels:
            self.stat_labels["detection_rate_pct"].setText(str(summary.get("detection_rate_pct", "-")))
        if "detection_time_s" in self.stat_labels:
            self.stat_labels["detection_time_s"].setText(str(summary.get("detection_time_s", "-")))
        if "searching_rate_pct" in self.stat_labels:
            self.stat_labels["searching_rate_pct"].setText(str(summary.get("searching_rate_pct", "-")))
        if "searching_time_s" in self.stat_labels:
            self.stat_labels["searching_time_s"].setText(str(summary.get("searching_time_s", "-")))
        if "center_hit_rate_pct" in self.stat_labels:
            self.stat_labels["center_hit_rate_pct"].setText(str(summary.get("center_hit_rate_pct", "-")))
        if "center_hit_time_s" in self.stat_labels:
            self.stat_labels["center_hit_time_s"].setText(str(summary.get("center_hit_time_s", "-")))

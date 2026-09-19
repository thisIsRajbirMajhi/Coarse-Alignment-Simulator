from __future__ import annotations

import logging

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QFrame, QGridLayout, QLabel, QVBoxLayout, QWidget

from gui.presentation.view_state import DashboardState, fmt_px_mrad

log = logging.getLogger(__name__)

# Pill colours for values
_GREEN = ("#1a7f37", "white")
_AMBER = ("#9a6700", "white")
_RED = ("#b42318", "white")
_BLUE = ("#0969da", "white")


def _pill_style(color: tuple[str, str] | None) -> str:
    if color is None:
        return "background:#c6c6c6; color:#111827; border-radius:10px; padding:4px 12px; font-weight:700;"
    bg, fg = color
    return f"background:{bg}; color:{fg}; border-radius:10px; padding:4px 12px; font-weight:700;"


class DashboardView(QWidget):
    """Renders DashboardState telemetry. Never queries sim objects."""

    METRIC_GROUPS = [
        ["Status"],
        ["Duration (S)", "FPS", "Jitter (ms)", "RMS (px)", "RMSE (mrad)"],
        ["Searching (s)", "Acquisition Time (s)", "Re-Acquisition Time (S)"],
        ["Detection Rate (%)", "Retention Rate (%)", "Center Hit rate (%)"],
        ["Average Tracking Error (px | mrad)", "Average Loss rate (/min)"],
    ]

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("liveDashboard")
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        self._pills: dict[str, QLabel] = {}
        
        grid = QGridLayout()
        grid.setVerticalSpacing(24)
        grid.setHorizontalSpacing(16)

        for row_idx, group in enumerate(self.METRIC_GROUPS):
            for col_idx, name in enumerate(group):
                cell_layout = QVBoxLayout()
                cell_layout.setSpacing(4)
                
                lab = QLabel(name)
                lab.setAlignment(Qt.AlignCenter)
                lab.setObjectName("metricLabel")
                lab.setStyleSheet("font-weight: bold;")
                
                pill = QLabel("—")
                pill.setAlignment(Qt.AlignCenter)
                pill.setObjectName("metricPill")
                pill.setMinimumWidth(80)
                
                cell_layout.addWidget(lab)
                cell_layout.addWidget(pill)
                cell_layout.setAlignment(Qt.AlignTop)
                
                grid.addLayout(cell_layout, row_idx, col_idx, Qt.AlignTop)
                self._pills[name] = pill
        # Change-detection caches: text/color writes only on actual change
        # (was 15× setText + 8× setStyleSheet+repolish every render).
        self._last_text: dict[str, str] = {}
        self._last_color: dict[str, tuple[str, str] | None] = {}

        for i in range(5):
            grid.setColumnStretch(i, 1)

        frame = QFrame()
        frame.setObjectName("dashboardCard")
        frame.setLayout(grid)
        root.addWidget(frame)

    def render(self, state: DashboardState) -> None:
        if state is None or not isinstance(state, DashboardState):
            return
        s = {
            "Status": state.status,
            "Duration (S)": f"{state.duration_s:.0f}",
            "FPS": f"{state.fps:.1f}",
            "Jitter (ms)": f"{state.jitter_ms:.0f}" if state.jitter_ms is not None else "—",
            "RMS (px)": f"{state.rms_px:.1f}" if state.rms_px is not None else "—",
            "RMSE (mrad)": f"{state.rms_mrad:.2f}" if state.rms_mrad is not None else "—",
            "Searching (s)": f"{state.searching_time_s:.1f}" if state.searching_time_s is not None else "—",
            "Acquisition Time (s)": f"{state.acquisition_time_s:.1f}" if state.acquisition_time_s is not None else "—",
            "Re-Acquisition Time (S)": f"{state.reacquisition_time_s:.1f}" if state.reacquisition_time_s is not None else "—",
            "Detection Rate (%)": f"{state.detection_rate_pct:.0f}" if state.detection_rate_pct is not None else "—",
            "Retention Rate (%)": f"{state.retention_rate_pct:.0f}" if state.retention_rate_pct is not None else "—",
            "Center Hit rate (%)": f"{state.center_hit_rate_pct:.0f}" if state.center_hit_rate_pct is not None else "—",
            "Average Tracking Error (px | mrad)": fmt_px_mrad(state.avg_track_err_px, state.avg_track_err_mrad),
            "Average Loss rate (/min)": f"{state.target_loss_rate_pct:.2f}" if state.target_loss_rate_pct is not None else "—",
        }
        for k, v in s.items():
            if k in self._pills and self._last_text.get(k) != v:
                self._pills[k].setText(v)
                self._last_text[k] = v

        def _rate_color(v: float | None, good_high: bool = True):
            if v is None:
                return None
            if good_high:
                return _GREEN if v >= 80 else (_AMBER if v >= 50 else _RED)
            return _GREEN if v <= 0 else (_AMBER if v <= 1.0 else _RED)

        def _err_color(px: float | None):
            if px is None:
                return None
            return _GREEN if px <= 5.0 else (_AMBER if px <= 15.0 else _RED)

        try:
            colors = {
                "Status": {
                    "RUNNING": _GREEN,
                    "PAUSED": _AMBER,
                    "STOPPED": None,
                    "ERROR": _RED,
                }.get(state.status),
                "FPS": _GREEN if state.fps >= 24 else (_AMBER if state.fps >= 10 else (_RED if state.fps > 0 else None)),
                "Jitter (ms)": _GREEN if state.jitter_ms is not None and state.jitter_ms <= 16.7
                               else (_AMBER if state.jitter_ms is not None and state.jitter_ms <= 33.0
                                     else (_RED if state.jitter_ms is not None else None)),
                "Retention Rate (%)": _rate_color(state.retention_rate_pct, True),
                "Detection Rate (%)": _rate_color(state.detection_rate_pct, True),
                "Center Hit rate (%)": _rate_color(state.center_hit_rate_pct, True),
                "Average Loss rate (/min)": _rate_color(state.target_loss_rate_pct, False),
                "Average Tracking Error (px | mrad)": _err_color(state.avg_track_err_px),
                "RMS (px)": _err_color(state.rms_px),
                "RMSE (mrad)": _err_color(state.rms_mrad),
            }
            for k, c in colors.items():
                if k in self._pills and self._last_color.get(k) != c:
                    self._pills[k].setStyleSheet(_pill_style(c))
                    self._last_color[k] = c
        except Exception as e:
            log.debug("pill colour update skipped: %s", e)

from __future__ import annotations

import logging

from PyQt5.QtWidgets import QFrame, QGridLayout, QLabel, QVBoxLayout, QWidget

from gui.presentation.view_state import DashboardState, fmt_ms, fmt_pct, fmt_px_mrad, fmt_time_s

log = logging.getLogger(__name__)

# Pill colours for changing values (PDF gray is the neutral default).
_GREEN = ("#1a7f37", "white")
_AMBER = ("#9a6700", "white")
_RED = ("#b42318", "white")


def _pill_style(color: tuple[str, str] | None) -> str:
    if color is None:
        return ""  # fall back to gray metricPill stylesheet
    bg, fg = color
    return f"background:{bg}; color:{fg}; border-radius:10px; padding:4px 12px; font-weight:700;"


def _rate_color(v: float | None, invert: bool = False) -> tuple[str, str] | None:
    if v is None:
        return None
    good = (v <= 5) if invert else (v >= 80)
    ok = (v <= 20) if invert else (v >= 50)
    if good:
        return _GREEN
    if ok:
        return _AMBER
    return _RED


def _error_color(px: float | None) -> tuple[str, str] | None:
    if px is None:
        return None
    if px <= 10:
        return _GREEN
    if px <= 30:
        return _AMBER
    return _RED


class DashboardView(QWidget):
    """Renders DashboardState only. Never queries sim objects."""

    # Left column: PDF order. Right column: runtime trio at the top rows.
    LEFT_METRICS = [
        "Jitter",
        "Acquisition Time",
        "Re-Acquisition Time",
        "Searching Time",
        "Retention Rate",
        "Detection Rate",
        "Center Hit Rate",
        "Average Target Loss Rate",
        "Average Tracking Error",
        "Total Re-Acquisition Count",
        "Total Target Loss Count",
        "Total Target Switches Count",
        "RMS / RMSE",
    ]
    RIGHT_METRICS = [
        "Status",
        "Duration (s)",
        "Frames Per Second (FPS)",
    ]

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("liveDashboard")
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        self._pills: dict[str, QLabel] = {}
        grid = QGridLayout()
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)
        grid.setColumnStretch(2, 1)
        grid.setColumnStretch(3, 1)
        for row, name in enumerate(self.LEFT_METRICS):
            lab = QLabel(name)
            lab.setObjectName("metricLabel")
            pill = QLabel("—")
            pill.setObjectName("metricPill")
            pill.setMinimumWidth(170)
            grid.addWidget(lab, row, 0)
            grid.addWidget(pill, row, 1)
            self._pills[name] = pill
        for row, name in enumerate(self.RIGHT_METRICS):
            lab = QLabel(name)
            lab.setObjectName("metricLabelEmph")
            pill = QLabel("—")
            pill.setObjectName("metricPill")
            pill.setMinimumWidth(170)
            grid.addWidget(lab, row, 2)
            grid.addWidget(pill, row, 3)
            self._pills[name] = pill
        frame = QFrame()
        frame.setObjectName("dashboardCard")
        frame.setLayout(grid)
        root.addWidget(frame)

    def render(self, state: DashboardState) -> None:
        s = {
            "Jitter": fmt_ms(state.jitter_ms),
            "Acquisition Time": fmt_time_s(state.acquisition_time_s),
            "Re-Acquisition Time": fmt_time_s(state.reacquisition_time_s),
            "Searching Time": fmt_time_s(state.searching_time_s),
            "Retention Rate": fmt_pct(state.retention_rate_pct),
            "Detection Rate": fmt_pct(state.detection_rate_pct),
            "Center Hit Rate": fmt_pct(state.center_hit_rate_pct),
            "Average Target Loss Rate": fmt_pct(state.target_loss_rate_pct),
            "Average Tracking Error": fmt_px_mrad(state.avg_track_err_px, state.avg_track_err_mrad),
            "Total Re-Acquisition Count": str(state.reacquisition_count),
            "Total Target Loss Count": str(state.target_loss_count),
            "Total Target Switches Count": str(state.target_switch_count),
            "RMS / RMSE": fmt_px_mrad(state.rms_px, state.rms_mrad),
            "Status": state.status,
            "Duration (s)": f"{state.duration_s:.0f} Sec",
            "Frames Per Second (FPS)": f"{state.fps:.1f}",
        }
        for k, v in s.items():
            if k in self._pills:
                self._pills[k].setText(v)
        # Value colours: status + rates + errors + jitter + FPS.
        try:
            colors = {
                "Jitter": _GREEN if state.jitter_ms is not None and state.jitter_ms <= 16.7
                          else (_AMBER if state.jitter_ms is not None and state.jitter_ms <= 33.0
                                else (_RED if state.jitter_ms is not None else None)),
                "Retention Rate": _rate_color(state.retention_rate_pct),
                "Detection Rate": _rate_color(state.detection_rate_pct),
                "Center Hit Rate": _rate_color(state.center_hit_rate_pct),
                "Average Target Loss Rate": _rate_color(state.target_loss_rate_pct, invert=True),
                "Average Tracking Error": _error_color(state.avg_track_err_px),
                "RMS / RMSE": _error_color(state.rms_px),
                "Status": {"TRACKING": _GREEN, "DETECTED": _GREEN, "SEARCHING": _AMBER,
                           "REACQUIRING": _AMBER, "LOST": _RED}.get(state.status),
                "Frames Per Second (FPS)": _GREEN if state.fps >= 24 else (_AMBER if state.fps >= 10 else _RED),
            }
            for k, c in colors.items():
                if k in self._pills:
                    self._pills[k].setStyleSheet(_pill_style(c))
        except Exception as e:
            log.debug("pill colour update skipped: %s", e)

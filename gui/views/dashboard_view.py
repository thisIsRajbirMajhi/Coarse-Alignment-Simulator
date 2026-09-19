# gui/views/dashboard_view.py - Live Dashboard telemetry surface (Plans/Design.md §29).
from __future__ import annotations

import logging

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QFrame, QGridLayout, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from gui.components import StatusChip
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


class MetricCard(QFrame):
    """Compact metric card: name + value + unit + state (Design.md §29.2)."""

    def __init__(self, name: str, unit: str = "", parent=None):
        super().__init__(parent)
        self.setProperty("card", True)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 10, 12, 10)
        lay.setSpacing(2)
        self.name_label = QLabel(name)
        self.name_label.setAlignment(Qt.AlignCenter)
        self.name_label.setObjectName("metricLabel")
        lay.addWidget(self.name_label)
        self.value_label = QLabel("—")
        self.value_label.setAlignment(Qt.AlignCenter)
        self.value_label.setObjectName("metricPill")
        lay.addWidget(self.value_label)
        self.state_label = QLabel("waiting")
        self.state_label.setAlignment(Qt.AlignCenter)
        self.state_label.setStyleSheet("font-size:10px; color:#8F9CAB;")
        lay.addWidget(self.state_label)
        self._unit = str(unit)

    def set_value(self, text: str, live: bool) -> None:
        self.value_label.setText(text)
        self.state_label.setText("live" if live else "waiting")


class DashboardView(QWidget):
    """Renders DashboardState telemetry. Never queries sim objects."""

    # (metric name, unit) per operator-task group (Design.md §29.3).
    OPTICAL_QUALITY = [
        ("RMS (px)", "px"),
        ("RMSE (mrad)", "mrad"),
        ("Average Tracking Error (px | mrad)", ""),
    ]
    ACQUISITION = [
        ("Searching (s)", "s"),
        ("Acquisition Time (s)", "s"),
        ("Re-Acquisition Time (S)", "s"),
        ("Detection Rate (%)", "%"),
    ]
    TRACKING = [
        ("Retention Rate (%)", "%"),
        ("Center Hit rate (%)", "%"),
        ("Average Loss rate (/min)", "/min"),
    ]

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("liveDashboard")
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(12)
        # Value labels by metric name (kept for tests + incremental updates).
        self._pills: dict[str, QLabel] = {}
        self._cards: dict[str, MetricCard] = {}

        # --- System state header (§29.1): status + runtime, no giant bar ---
        status_row = QHBoxLayout()
        status_row.setSpacing(10)
        self.status_chip = StatusChip("STOPPED", "off")
        status_row.addWidget(self.status_chip)
        self.header_duration = QLabel("Duration —")
        self.header_fps = QLabel("FPS —")
        self.header_jitter = QLabel("Jitter —")
        for _w in (self.header_duration, self.header_fps, self.header_jitter):
            _w.setStyleSheet("font-size:12px; font-weight:600;")
            status_row.addWidget(_w)
        status_row.addStretch(1)
        root.addLayout(status_row)

        grid = QGridLayout()
        grid.setVerticalSpacing(12)
        grid.setHorizontalSpacing(12)
        row = 0
        row = self._add_group(grid, row, "OPTICAL QUALITY", self.OPTICAL_QUALITY)
        row = self._add_group(grid, row, "ACQUISITION / DETECTION", self.ACQUISITION)
        row = self._add_group(grid, row, "TRACKING STABILITY", self.TRACKING)
        for i in range(4):
            grid.setColumnStretch(i, 1)

        frame = QFrame()
        frame.setObjectName("dashboardCard")
        frame.setLayout(grid)
        root.addWidget(frame)

        # --- Diagnostics strip (§29.6): one secondary line ---
        self.diag_strip = QLabel("")
        self.diag_strip.setStyleSheet("font-size:10px; color:#8F9CAB;")
        self.diag_strip.setWordWrap(True)
        root.addWidget(self.diag_strip)

        # Change-detection caches (text/color writes only on actual change).
        self._last_text: dict[str, str] = {}
        self._last_color: dict[str, tuple[str, str] | None] = {}

    def _add_group(self, grid: QGridLayout, row: int, title: str,
                   metrics: list[tuple[str, str]]) -> int:
        header = QLabel(title)
        header.setStyleSheet("font-size:12px; font-weight:700;")
        grid.addWidget(header, row, 0, 1, 4)
        row += 1
        for col, (name, unit) in enumerate(metrics):
            card = MetricCard(name, unit)
            grid.addWidget(card, row, col)
            self._cards[name] = card
            self._pills[name] = card.value_label
        # Status/Duration/FPS/Jitter live in the header but keep pill entries
        # so external readers (tests, presenters) see a complete mapping.
        for extra in ("Status", "Duration (S)", "FPS", "Jitter (ms)"):
            if extra not in self._pills:
                hidden = QLabel("—")
                hidden.setVisible(False)
                self._pills[extra] = hidden
        return row + 1

    # -- rendering ------------------------------------------------------
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
                if k in self._cards:
                    self._cards[k].set_value(v, v != "—")

        # Status header: chip + runtime (no saturated fills everywhere).
        try:
            kind = {"RUNNING": "ok", "PAUSED": "warn", "ERROR": "bad",
                    "STOPPED": "off"}.get(str(state.status), "info")
            self.status_chip.set_state(kind, str(state.status))
            dur = f"{state.duration_s:.0f}s"
            if self.header_duration.text() != f"Duration {dur}":
                self.header_duration.setText(f"Duration {dur}")
            fps_t = f"FPS {state.fps:.1f}"
            if self.header_fps.text() != fps_t:
                self.header_fps.setText(fps_t)
            jit_t = f"Jitter {state.jitter_ms:.0f} ms" if state.jitter_ms is not None else "Jitter —"
            if self.header_jitter.text() != jit_t:
                self.header_jitter.setText(jit_t)
        except Exception as e:
            log.debug("dashboard header update skipped: %s", e)

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

        # Diagnostics strip: source/target/link/beacon/frame (when known).
        try:
            diag = (f"SOURCE: {state.source_id}   TARGET: {state.target_id}   "
                    f"LINK: {state.link_state}   BEACON: {state.beacon_state}   "
                    f"FRAME: {state.frame_id}")
            if self.diag_strip.text() != diag:
                self.diag_strip.setText(diag)
        except Exception as e:
            log.debug("diagnostics strip update skipped: %s", e)

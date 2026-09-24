# gui/views/dashboard_view.py - Live Dashboard telemetry surface (Plans/Design.md §29).
from __future__ import annotations

import logging

from PyQt5.QtCore import Qt
from PyQt5.QtGui import QBrush, QColor
from PyQt5.QtWidgets import (
    QAbstractItemView, QFrame, QGridLayout, QGroupBox, QHBoxLayout, QLabel,
    QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from src.gui.components import StatusChip
from src.gui.presentation.view_state import (
    DashboardState, fmt_deg, fmt_on_off, fmt_range_m, fmt_xy, fmt_px_mrad,
    short_op_state,
)

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

        # --- LIVE STATE: first emitting terminal (else first terminal) ---
        live_box = QGroupBox("LIVE STATE")
        live_grid = QGridLayout(live_box)
        live_grid.setColumnStretch(1, 1)
        self.live_id_label = QLabel("—")
        self.live_id_label.setStyleSheet("font-size:13px; font-weight:700;")
        live_grid.addWidget(self.live_id_label, 0, 0, 1, 2)
        self._live_labels: dict[str, QLabel] = {}
        live_rows = [
            ("position", "Position"),
            ("velocity", "Velocity"),
            ("los", "LOS"),
            ("beam", "Beam Direction"),
            ("pointing", "Pointing Error"),
            ("range", "Range"),
            ("diameter", "Beam Diameter"),
            ("emission", "Emission"),
        ]
        for i, (key, title_text) in enumerate(live_rows, start=1):
            name = QLabel(title_text)
            name.setStyleSheet("font-size:11px; color:#8F9CAB;")
            live_grid.addWidget(name, i, 0)
            val = QLabel("—")
            val.setStyleSheet("font-size:12px; font-weight:600;")
            live_grid.addWidget(val, i, 1)
            self._live_labels[key] = val
            self._pills[f"Live {title_text}"] = val
        root.addWidget(live_box)

        # --- TERMINALS: per-terminal config + switch state table ---
        term_box = QGroupBox("TERMINALS")
        term_lay = QVBoxLayout(term_box)
        self.terminals_table = QTableWidget(0, 6)
        self.terminals_table.setHorizontalHeaderLabels(
            ["ID", "Power", "Beacon", "State", "Power(W)", "λ (nm)"])
        self.terminals_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.terminals_table.setSelectionMode(QAbstractItemView.NoSelection)
        self.terminals_table.verticalHeader().setVisible(False)
        self.terminals_table.horizontalHeader().setStretchLastSection(True)
        self.terminals_table.setMinimumHeight(80)
        term_lay.addWidget(self.terminals_table)
        root.addWidget(term_box)
        self._last_table: dict[tuple[int, int], str] = {}

        # --- COMMUNICATION STATUS: link/beacon/fleet roll-up ---
        comm_box = QGroupBox("COMMUNICATION STATUS")
        comm_grid = QGridLayout(comm_box)
        comm_grid.setColumnStretch(1, 1)
        self._comm_labels: dict[str, QLabel] = {}
        comm_rows = [
            ("link", "Link"),
            ("beacon", "Beacon"),
            ("fleet", "Terminals"),
            ("target", "Active Target"),
            ("seq", "Beacon Seq"),
            ("navtime", "Nav Timestamp"),
            ("simtime", "Sim Time"),
        ]
        for i, (key, title_text) in enumerate(comm_rows):
            name = QLabel(title_text)
            name.setStyleSheet("font-size:11px; color:#8F9CAB;")
            comm_grid.addWidget(name, i, 0)
            val = QLabel("—")
            val.setStyleSheet("font-size:12px; font-weight:600;")
            comm_grid.addWidget(val, i, 1)
            self._comm_labels[key] = val
            self._pills[f"Comm {title_text}"] = val
        root.addWidget(comm_box)

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

        self._render_live_state(state)
        self._render_terminals_table(state)
        self._render_comm_status(state)

    # -- remote-terminal sections ----------------------------------------
    def _set_cached(self, label: QLabel, key: str, text: str) -> None:
        if self._last_text.get(key) != text:
            label.setText(text)
            self._last_text[key] = text

    def _render_live_state(self, state: DashboardState) -> None:
        """LIVE STATE card: first emitting terminal, else first terminal."""
        try:
            live = state.live_terminal
            tid = getattr(live, "terminal_id", None) if live is not None else None
            self._set_cached(self.live_id_label, "live_id", str(tid) if tid else "—")
            vals = {
                "position": fmt_xy(getattr(live, "pos_x_m", None), getattr(live, "pos_y_m", None), "m"),
                "velocity": fmt_xy(getattr(live, "vel_x_mps", None), getattr(live, "vel_y_mps", None), "m/s"),
                "los": fmt_deg(getattr(live, "los_deg", None)),
                "beam": fmt_deg(getattr(live, "beam_deg", None)),
                "pointing": fmt_deg(getattr(live, "pointing_err_deg", None)),
                "range": fmt_range_m(getattr(live, "range_m", None)),
                "diameter": f"{live.beam_diameter_m:.2f} m" if live is not None and live.beam_diameter_m is not None else "—",
                "emission": "ACTIVE" if live is not None and live.emitting else ("INACTIVE" if live is not None and live.emitting is not None else "—"),
            }
            for key, text in vals.items():
                self._set_cached(self._live_labels[key], f"live_{key}", text)
            emitting = bool(live is not None and live.emitting)
            color = _GREEN if emitting else None
            if live is None or live.emitting is None:
                color = None
            if self._last_color.get("Live Emission") != color:
                self._live_labels["emission"].setStyleSheet(
                    f"font-size:12px; font-weight:700; color:{color[0]};" if color
                    else "font-size:12px; font-weight:600;")
                self._last_color["Live Emission"] = color
        except Exception as e:
            log.debug("live state update skipped: %s", e)

    def _render_terminals_table(self, state: DashboardState) -> None:
        """TERMINALS table: one row per terminal (ID/Power/Beacon/State/W/λ)."""
        try:
            rows = list(getattr(state, "terminals", None) or ())
            table = self.terminals_table
            if table.rowCount() != len(rows):
                table.setRowCount(len(rows))
            for r, t in enumerate(rows):
                cells = [
                    str(t.terminal_id) if t.terminal_id else "—",
                    fmt_on_off(t.power_on),
                    fmt_on_off(t.beacon_on),
                    short_op_state(t.op_state),
                    f"{t.power_w:.2f}" if t.power_w is not None else "—",
                    f"{t.wavelength_nm:.0f}" if t.wavelength_nm is not None else "—",
                ]
                for c, text in enumerate(cells):
                    if self._last_table.get((r, c)) != text:
                        item = QTableWidgetItem(text)
                        item.setFlags(item.flags() & ~Qt.ItemIsEditable)
                        table.setItem(r, c, item)
                        self._last_table[(r, c)] = text
                try:
                    em_item = table.item(r, 3)
                    if em_item is not None:
                        st = (t.op_state or "").lower()
                        color = _GREEN[0] if st in ("beaconing", "linked") else (
                            _RED[0] if st == "fault" else None)
                        em_item.setForeground(QBrush(QColor(color)) if color else QBrush())
                except Exception:
                    pass
            # Drop stale cache keys when the table shrinks.
            for key in [k for k in self._last_table if k[0] >= len(rows)]:
                del self._last_table[key]
        except Exception as e:
            log.debug("terminals table update skipped: %s", e)

    def _render_comm_status(self, state: DashboardState) -> None:
        """COMMUNICATION STATUS card: link/beacon/fleet roll-up."""
        try:
            live = state.live_terminal
            seq = getattr(live, "beacon_seq", None) if live is not None else None
            nav_ms = getattr(live, "nav_timestamp_ms", None) if live is not None else None
            vals = {
                "link": str(state.link_state),
                "beacon": str(state.beacon_state),
                "fleet": f"{int(state.emitting_count)}/{int(state.terminal_count)} emitting"
                         if state.terminal_count else "—",
                "target": str(state.target_id),
                "seq": f"#{int(seq)}" if seq is not None else "—",
                "navtime": f"{int(nav_ms)} ms" if nav_ms is not None else "—",
                "simtime": f"{float(state.sim_time_s):.1f} s",
            }
            for key, text in vals.items():
                self._set_cached(self._comm_labels[key], f"comm_{key}", text)
        except Exception as e:
            log.debug("comm status update skipped: %s", e)

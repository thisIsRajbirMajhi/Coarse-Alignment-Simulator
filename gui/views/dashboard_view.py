from __future__ import annotations

import logging

from PyQt5.QtWidgets import QFrame, QGridLayout, QLabel, QVBoxLayout, QWidget

from gui.presentation.view_state import DashboardState, fmt_dim, fmt_ms, fmt_px

log = logging.getLogger(__name__)

# Pill colours for values
_GREEN = ("#1a7f37", "white")
_AMBER = ("#9a6700", "white")
_RED = ("#b42318", "white")
_BLUE = ("#0969da", "white")


def _pill_style(color: tuple[str, str] | None) -> str:
    if color is None:
        return ""
    bg, fg = color
    return f"background:{bg}; color:{fg}; border-radius:10px; padding:4px 12px; font-weight:700;"


class DashboardView(QWidget):
    """Renders DashboardState telemetry. Never queries sim objects."""

    LEFT_METRICS = [
        "Status",
        "Duration (s)",
        "Frames Per Second (FPS)",
        "Jitter",
        "Camera Pan",
        "Camera Tilt",
        "FOV Size",
        "World Size",
    ]
    RIGHT_METRICS = [
        "Atmospheric Preset",
        "Platform Profile",
        "Platform Speed",
        "Optical Turbulence",
        "Platform Vibration",
        "Camera Motion",
        "Sensor Noise",
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
            "Status": state.status,
            "Duration (s)": f"{state.duration_s:.0f} Sec",
            "Frames Per Second (FPS)": f"{state.fps:.1f}",
            "Jitter": fmt_ms(state.jitter_ms),
            "Camera Pan": fmt_px(state.pan),
            "Camera Tilt": fmt_px(state.tilt),
            "FOV Size": fmt_dim(state.fov_w, state.fov_h),
            "World Size": fmt_dim(state.world_w, state.world_h),
            "Atmospheric Preset": state.atmospheric_preset,
            "Platform Profile": state.platform_profile,
            "Platform Speed": f"{state.platform_speed:.1f} px/s",
            "Optical Turbulence": str(state.turbulence),
            "Platform Vibration": str(state.vibration),
            "Camera Motion": str(state.camera_motion),
            "Sensor Noise": str(state.noise),
        }
        for k, v in s.items():
            if k in self._pills:
                self._pills[k].setText(v)

        try:
            colors = {
                "Status": {
                    "RUNNING": _GREEN,
                    "PAUSED": _AMBER,
                    "STOPPED": None,
                    "ERROR": _RED,
                }.get(state.status),
                "Frames Per Second (FPS)": _GREEN if state.fps >= 24 else (_AMBER if state.fps >= 10 else (_RED if state.fps > 0 else None)),
                "Jitter": _GREEN if state.jitter_ms is not None and state.jitter_ms <= 16.7
                          else (_AMBER if state.jitter_ms is not None and state.jitter_ms <= 33.0
                                else (_RED if state.jitter_ms is not None else None)),
            }
            for k, c in colors.items():
                if k in self._pills:
                    self._pills[k].setStyleSheet(_pill_style(c))
        except Exception as e:
            log.debug("pill colour update skipped: %s", e)

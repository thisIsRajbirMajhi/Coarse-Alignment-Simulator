# gui/panels/global_panel.py - Global / System controls — transport
from __future__ import annotations

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
)

from src.gui.panels.base import BaseConfigPanel


class GlobalPanel(BaseConfigPanel):
    """
    Global / System panel — transport controls.
    """

    startRequested = pyqtSignal()
    pauseRequested = pyqtSignal()
    resetRequested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(12)

        transport_card = QFrame()
        transport_card.setStyleSheet("QFrame { background:#ffffff; border:1px solid #e5e7eb; border-radius:8px; }")
        tl = QVBoxLayout(transport_card)
        tl.setContentsMargins(16, 16, 16, 16)
        tl.setSpacing(14)
        trans_title = QLabel("Transport")
        trans_title.setStyleSheet("color:#111827; font-weight:700; font-size:12px; background: transparent; letter-spacing: 0.3px;")
        trans_title.setAlignment(Qt.AlignCenter)
        tl.addWidget(trans_title)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(12)
        self.start_btn = QPushButton("Start")
        self.start_btn.setMinimumHeight(52)
        self.start_btn.setMinimumWidth(90)
        self.start_btn.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.start_btn.setStyleSheet("QPushButton { background: #111827; color:white; font-weight:700; border:1px solid #111827; border-radius:8px; font-size:13px; padding:10px 16px; } QPushButton:hover { background:#1f2937; } QPushButton:pressed { background:#000000; }")

        self.pause_btn = QPushButton("Pause")
        self.pause_btn.setMinimumHeight(52)
        self.pause_btn.setMinimumWidth(90)
        self.pause_btn.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.pause_btn.setStyleSheet("QPushButton { background:#ffffff; color:#374151; font-weight:600; border:1.5px solid #d1d5db; border-radius:8px; font-size:13px; padding:10px 16px; } QPushButton:hover { background:#f9fafb; border-color:#9ca3af; } QPushButton:pressed { background:#f3f4f6; }")

        self.reset_btn = QPushButton("Reset")
        self.reset_btn.setMinimumHeight(52)
        self.reset_btn.setMinimumWidth(90)
        self.reset_btn.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.reset_btn.setStyleSheet("QPushButton { background:#ffffff; color:#374151; font-weight:600; border:1.5px solid #d1d5db; border-radius:8px; font-size:13px; padding:10px 16px; } QPushButton:hover { background:#fef2f2; border-color:#fca5a5; color:#dc2626; } QPushButton:pressed { background:#fee2e2; }")

        self.start_btn.clicked.connect(self.startRequested.emit)
        self.pause_btn.clicked.connect(self.pauseRequested.emit)
        self.reset_btn.clicked.connect(self.resetRequested.emit)

        for b in (self.start_btn, self.pause_btn, self.reset_btn):
            btn_row.addWidget(b, 1)
        tl.addLayout(btn_row)

        hint = QLabel("Use Start to run, Pause to hold, Reset to restore defaults")
        hint.setStyleSheet("color:#6b7280; font-size:10px; font-style:italic; background: transparent;")
        hint.setAlignment(Qt.AlignCenter)
        hint.setWordWrap(True)
        tl.addWidget(hint)

        layout.addWidget(transport_card)
        layout.addStretch()
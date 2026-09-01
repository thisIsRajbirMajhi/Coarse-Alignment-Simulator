# gui/panels/base.py - Shared base for all config panels — eliminates duplication of

from __future__ import annotations

from contextlib import contextmanager
from typing import Any, Generator

from PyQt5.QtWidgets import QGridLayout, QGroupBox, QLabel, QWidget

class BaseConfigPanel(QWidget):
    """
    Base for config panels — DRY helpers for grouped QGroupBox panels.

    Provides:
      - _label(text): styled QLabel (#334155, 11px, 600)
      - _make_group(title): QGroupBox with standardized margins 12,18,12,12 and spacings 8
      - _block_signals(widgets, block): context manager for signal blocking
      - _hint(text): italic hint QLabel (#64748b, 10px)
    Subclasses must implement:
      - _build_ui()
      - collect_config() -> Config
      - set_config(cfg, emit=False)
    """

    def _label(self, text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setStyleSheet("color:#334155; font-size:11px; font-weight:600;")
        return lbl

    def _hint(self, text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setWordWrap(True)
        lbl.setStyleSheet("color:#64748b; font-size:10px; font-style:italic;")
        return lbl

    def _make_group(self, title: str) -> tuple[QGroupBox, QGridLayout]:
        box = QGroupBox(title)
        grid = QGridLayout(box)
        grid.setContentsMargins(12, 18, 12, 12)
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(8)
        grid.setColumnStretch(1, 1)
        grid.setColumnStretch(3, 1)
        return box, grid

    @contextmanager
    def _blocked(self, widgets: list[Any]) -> Generator[None, None, None]:
        for w in widgets:
            try:
                w.blockSignals(True)
            except Exception:
                pass
        try:
            yield
        finally:
            for w in widgets:
                try:
                    w.blockSignals(False)
                except Exception:
                    pass

    def _all_widgets(self) -> list[Any]:
        # Subclasses override to return list of widgets for blocking
        return []
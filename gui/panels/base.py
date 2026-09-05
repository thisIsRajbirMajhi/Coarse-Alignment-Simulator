# gui/panels/base.py - Shared base for all config panels — eliminates duplication of

from __future__ import annotations

from contextlib import contextmanager
from typing import Any, Generator

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QGridLayout, QGroupBox, QHBoxLayout, QLabel, QPushButton, QSlider, QWidget

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

    # --- Intuitive slider helpers (light theme, highlighted on interaction) ---
    def _make_int_slider(
        self,
        min_val: int,
        max_val: int,
        init_val: int,
        tooltip: str = "",
        tick: bool = True,
    ) -> tuple[QSlider, QLabel]:
        """Create an int slider + value label with light-theme highlighting."""
        slider = QSlider(Qt.Horizontal)
        slider.setRange(int(min_val), int(max_val))
        slider.setValue(int(init_val))
        if tick:
            slider.setTickPosition(QSlider.TicksBelow)
            step = max(1, (max_val - min_val) // 5)
            slider.setTickInterval(int(step))
        slider.setMinimumHeight(18)
        if tooltip:
            slider.setToolTip(tooltip)
        val_label = QLabel(str(int(init_val)))
        val_label.setFixedWidth(48)
        val_label.setMinimumHeight(22)
        val_label.setAlignment(Qt.AlignCenter)
        val_label.setStyleSheet(
            "color:#111827; font-weight:600; background:#f9fafb; border:1px solid #e5e7eb; "
            "border-radius:4px; padding:2px 4px; font-family:'Consolas','Courier New',monospace; font-size:11px;"
        )
        # Highlight value label when slider is pressed/dragged
        def _on_slider_pressed():
            val_label.setStyleSheet(
                "color:#1e40af; font-weight:700; background:#dbeafe; border:2px solid #3b82f6; "
                "border-radius:4px; padding:2px 4px; font-family:'Consolas','Courier New',monospace; font-size:11px;"
            )
        def _on_slider_released():
            val_label.setStyleSheet(
                "color:#111827; font-weight:600; background:#f9fafb; border:1px solid #e5e7eb; "
                "border-radius:4px; padding:2px 4px; font-family:'Consolas','Courier New',monospace; font-size:11px;"
            )
        slider.sliderPressed.connect(_on_slider_pressed)
        slider.sliderReleased.connect(_on_slider_released)
        # Update label on value change
        slider.valueChanged.connect(lambda v, lbl=val_label: lbl.setText(str(int(v))))
        return slider, val_label

    def _make_float_slider(
        self,
        min_val: float,
        max_val: float,
        init_val: float,
        decimals: int = 2,
        suffix: str = "",
        tooltip: str = "",
        factor: int | None = None,
    ) -> tuple[QSlider, QLabel, int]:
        """Create a float slider (scaled int) + value label. Returns (slider, label, factor)."""
        if factor is None:
            factor = 10 ** decimals
        factor = int(factor)
        slider = QSlider(Qt.Horizontal)
        slider.setRange(int(round(min_val * factor)), int(round(max_val * factor)))
        slider.setValue(int(round(init_val * factor)))
        slider.setTickPosition(QSlider.TicksBelow)
        step = max(1, (int(round(max_val * factor)) - int(round(min_val * factor))) // 5)
        slider.setTickInterval(int(step))
        slider.setMinimumHeight(18)
        if tooltip:
            slider.setToolTip(tooltip)
        fmt = f"{{:.{decimals}f}}{{}}"
        val_label = QLabel(fmt.format(init_val, suffix))
        val_label.setFixedWidth(64)
        val_label.setMinimumHeight(22)
        val_label.setAlignment(Qt.AlignCenter)
        val_label.setStyleSheet(
            "color:#111827; font-weight:600; background:#f9fafb; border:1px solid #e5e7eb; "
            "border-radius:4px; padding:2px 4px; font-family:'Consolas','Courier New',monospace; font-size:11px;"
        )
        def _on_pressed():
            val_label.setStyleSheet(
                "color:#1e40af; font-weight:700; background:#dbeafe; border:2px solid #3b82f6; "
                "border-radius:4px; padding:2px 4px; font-family:'Consolas','Courier New',monospace; font-size:11px;"
            )
        def _on_released():
            val_label.setStyleSheet(
                "color:#111827; font-weight:600; background:#f9fafb; border:1px solid #e5e7eb; "
                "border-radius:4px; padding:2px 4px; font-family:'Consolas','Courier New',monospace; font-size:11px;"
            )
        slider.sliderPressed.connect(_on_pressed)
        slider.sliderReleased.connect(_on_released)
        slider.valueChanged.connect(lambda v, lbl=val_label, f=factor, d=decimals, s=suffix: lbl.setText(f"{v/f:.{d}f}{s}"))
        return slider, val_label, factor

    def _make_reset_button(self, text: str = "Reset") -> QPushButton:
        btn = QPushButton(text)
        btn.setMinimumHeight(28)
        btn.setToolTip(f"Reset {text.lower()} to defaults")
        btn.setStyleSheet(
            "QPushButton { background:#ffffff; color:#374151; font-weight:600; border:1px solid #d1d5db; "
            "border-radius:6px; padding:6px 12px; font-size:11px; }"
            "QPushButton:hover { background:#fef2f2; border-color:#fca5a5; color:#dc2626; }"
            "QPushButton:pressed { background:#fee2e2; border-color:#ef4444; color:#991b1b; }"
        )
        return btn

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
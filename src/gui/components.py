# gui/components.py - Shared Control Deck primitives (Plans/Design.md §44, §52).
from __future__ import annotations

import logging

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtWidgets import (
    QCheckBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSizePolicy,
    QSlider,
    QVBoxLayout,
    QWidget,
)

log = logging.getLogger(__name__)

_EXPANSION_ORG = "CoarseAlignmentSim"
_EXPANSION_APP = "ControlDeck"


def expansion_state(key: str, default: bool = False) -> bool:
    """Persisted disclosure open/closed state (Design.md §50.7)."""
    try:
        from PyQt5.QtCore import QSettings
        v = QSettings(_EXPANSION_ORG, _EXPANSION_APP).value(f"ui/expanded/{key}", default)
        if isinstance(v, str):
            return v.lower() in ("1", "true", "yes")
        return bool(v)
    except Exception:
        return bool(default)


def set_expansion_state(key: str, open_: bool) -> None:
    try:
        from PyQt5.QtCore import QSettings
        QSettings(_EXPANSION_ORG, _EXPANSION_APP).setValue(f"ui/expanded/{key}", bool(open_))
    except Exception:
        pass


class EditableValue(QLabel):
    """Click-to-edit numeric value (Design.md §44.2 DISPLAY/HOVER/EDIT).

    Displays ``value+unit`` right-aligned in mono; click (or Enter when
    focused) swaps in a QLineEdit. Enter commits via ``committed(str)``,
    Escape restores. Focus ring visible; keyboard reachable (Tab + Enter).
    """

    committed = pyqtSignal(str)

    def __init__(self, text: str = "", parent=None):
        super().__init__(text, parent)
        self.setObjectName("editableValue")
        self.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.setMinimumWidth(84)
        self.setMinimumHeight(22)
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setToolTip("Click to edit, Enter to commit, Escape to cancel")
        f = self.font()
        f.setFamily("JetBrains Mono, SFMono-Regular, Consolas, monospace")
        self.setFont(f)
        self._editor: QLineEdit | None = None

    def mousePressEvent(self, event) -> None:  # noqa: N802
        self.start_editing()
        super().mousePressEvent(event)

    def keyPressEvent(self, event) -> None:  # noqa: N802
        if event.key() in (Qt.Key_Return, Qt.Key_Enter):
            self.start_editing()
        else:
            super().keyPressEvent(event)

    def start_editing(self) -> None:
        if self._editor is not None:
            return
        ed = QLineEdit(self.text(), self.parentWidget())
        ed.setObjectName("editableValueEditor")
        ed.setGeometry(self.geometry())
        ed.setMinimumWidth(self.minimumWidth())
        ed.selectAll()
        ed.editingFinished.connect(self._finish_editing)
        self._editor = ed
        try:
            self.setVisible(False)
        except Exception:
            pass
        ed.setVisible(True)
        ed.setFocus(Qt.MouseFocusReason)

    def _finish_editing(self) -> None:
        ed, self._editor = self._editor, None
        if ed is None:
            return
        try:
            text = ed.text()
            ed.deleteLater()
            self.setVisible(True)
            self.setFocus(Qt.OtherFocusReason)
            self.committed.emit(text)
        except Exception as e:
            log.debug("editable value commit skipped: %s", e)


class SliderField(QWidget):
    """Standard slider row (Design.md §44.1): label + slider + editable value.

    Exposes ``.slider`` (QSlider) so existing valueChanged/sliderReleased
    wiring keeps working, plus ``committed`` (release or editor-Enter) and
    ``previewed`` (any change, for live labels). Units stay attached to the
    value; tooltips carry min/max + one-line definition.
    """

    previewed = pyqtSignal(int)
    committed = pyqtSignal(int)

    def __init__(self, label: str, min_val: int, max_val: int, init_val: int,
                 unit: str = "", tooltip: str = "", decimals: int = 0,
                 factor: int = 1, parent=None):
        super().__init__(parent)
        self._factor = max(1, int(factor))
        self._decimals = int(decimals)
        self._unit = str(unit)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(8)
        self._label = QLabel(label)
        self._label.setMinimumWidth(110)
        lay.addWidget(self._label)
        self.slider = QSlider(Qt.Horizontal)
        self.slider.setRange(int(min_val), int(max_val))
        self.slider.setValue(int(init_val))
        self.slider.setTickPosition(QSlider.TicksBelow)
        step = max(1, (int(max_val) - int(min_val)) // 5)
        self.slider.setTickInterval(int(step))
        self.slider.setMinimumHeight(18)
        if tooltip:
            tip = f"{tooltip} ({min_val}..{max_val}{(' ' + unit) if unit else ''})"
            self.slider.setToolTip(tip)
            self._label.setToolTip(tip)
        lay.addWidget(self.slider, 1)
        self.value = EditableValue(self._fmt(init_val))
        self.value.setToolTip((tooltip + " — click to type a precise value") if tooltip else "Click to type a precise value")
        lay.addWidget(self.value)
        self.slider.valueChanged.connect(self._on_moved)
        self.slider.sliderReleased.connect(lambda: self.committed.emit(self.slider.value()))
        self.value.committed.connect(self._on_editor_committed)
        # Accessible name/value for assistive tech (Design.md §49).
        try:
            self.slider.setAccessibleName(label)
            self.slider.setAccessibleDescription(f"{tooltip} {min_val} to {max_val} {unit}".strip())
        except Exception:
            pass

    def _fmt(self, v: int) -> str:
        if self._decimals > 0:
            return f"{v / self._factor:.{self._decimals}f}{self._unit}"
        scaled = v / self._factor if self._factor != 1 else v
        if isinstance(scaled, float) and not scaled.is_integer():
            return f"{scaled:.{self._decimals}f}{self._unit}"
        return f"{int(round(scaled))}{self._unit}"

    def _on_moved(self, v: int) -> None:
        self.value.setText(self._fmt(v))
        self.previewed.emit(int(v))

    def _on_editor_committed(self, text: str) -> None:
        try:
            raw = str(text).strip()
            for u in (self._unit, "px", "%", "×", "°", "m", "s", "Hz", "dB", "nm"):
                if u and raw.endswith(u):
                    raw = raw[: -len(u)].strip()
                    break
            fval = float(raw)
            v = int(round(fval * self._factor))
            v = max(self.slider.minimum(), min(self.slider.maximum(), v))
            self.slider.setValue(v)  # emits previewed; committed below
            self.committed.emit(v)
        except (TypeError, ValueError):
            self.value.setText(self._fmt(self.slider.value()))

    def setValue(self, v: int) -> None:  # noqa: N802 (Qt-style alias)
        self.slider.setValue(int(v))

    def value_int(self) -> int:
        return int(self.slider.value())


class Toggle(QCheckBox):
    """Master/feature toggle (Design.md §44.4): ``Label  ● ON / ○ OFF``."""

    def __init__(self, label: str = "", checked: bool = True, parent=None):
        super().__init__(parent)
        self.setProperty("toggle", True)
        self._label = str(label)
        self.setChecked(bool(checked))
        self._refresh_text()
        self.toggled.connect(lambda _on: self._refresh_text())
        self.setMinimumHeight(22)

    def _refresh_text(self) -> None:
        state = "● ON" if self.isChecked() else "○ OFF"
        self.setText(f"{self._label}  {state}" if self._label else state)


class StatusChip(QLabel):
    """Status chip: icon + text + color, never color-alone (Design.md §45)."""

    STYLES = {
        "ok": ("●", "#57D38C"),
        "warn": ("●", "#F2B84B"),
        "bad": ("×", "#F06D7A"),
        "info": ("●", "#61D6FF"),
        "off": ("○", "#8F9CAB"),
        "na": ("—", "#647182"),
    }

    def __init__(self, text: str = "", kind: str = "off", parent=None):
        super().__init__(parent)
        self.setAlignment(Qt.AlignCenter)
        self.setMinimumHeight(22)
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self.set_state(kind, text)

    def set_state(self, kind: str, text: str) -> None:
        icon, color = self.STYLES.get(str(kind), self.STYLES["off"])
        self.setText(f"{icon} {text}")
        self.setStyleSheet(
            f"color:{color}; border:1px solid {color}; border-radius:10px; "
            "padding:2px 10px; font-weight:700; font-size:11px; background:transparent;"
        )
        try:
            self.setAccessibleDescription(f"status {text}")
        except Exception:
            pass


class Disclosure(QWidget):
    """Collapsible Advanced section with persisted open state (§50.7)."""

    toggled = pyqtSignal(bool)

    def __init__(self, title: str, key: str, summary: str = "", parent=None):
        super().__init__(parent)
        self._key = str(key)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)
        self.header = QPushButton(parent)
        self.header.setCheckable(True)
        self.header.setObjectName("disclosureHeader")
        self.header.setMinimumHeight(30)
        lay.addWidget(self.header)
        self.body = QWidget(self)
        self._body_lay = QVBoxLayout(self.body)
        self._body_lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self.body)
        self._title = str(title)
        self._summary = str(summary)
        is_open = expansion_state(self._key, False)
        self.header.setChecked(bool(is_open))
        self.body.setVisible(bool(is_open))
        self.header.toggled.connect(self._on_toggled)
        self._refresh_header()

    def _refresh_header(self) -> None:
        arrow = "▾" if self.header.isChecked() else "▸"
        txt = f"{arrow}  {self._title}"
        if self._summary:
            txt += f"   ·   {self._summary}"
        self.header.setText(txt)

    def set_summary(self, summary: str) -> None:
        self._summary = str(summary)
        self._refresh_header()

    def _on_toggled(self, on: bool) -> None:
        self.body.setVisible(bool(on))
        set_expansion_state(self._key, bool(on))
        self._refresh_header()
        self.toggled.emit(bool(on))

    def add_widget(self, w: QWidget) -> None:
        self._body_lay.addWidget(w)


class PresetSegment(QWidget):
    """Compact preset chips with Custom auto-state (Design.md §15)."""

    presetSelected = pyqtSignal(str)

    def __init__(self, presets: list[str], parent=None):
        super().__init__(parent)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)
        self._buttons: dict[str, QPushButton] = {}
        for name in presets:
            b = QPushButton(str(name))
            b.setProperty("chip", True)
            b.setCheckable(True)
            b.setMinimumHeight(28)
            b.clicked.connect(lambda _c=False, n=str(name): self._on_pick(n))
            lay.addWidget(b)
            self._buttons[str(name)] = b
        lay.addStretch(1)
        self._active: str | None = None

    def _on_pick(self, name: str) -> None:
        self.set_active(name)
        self.presetSelected.emit(name)

    def set_active(self, name: str | None) -> None:
        self._active = name
        for n, b in self._buttons.items():
            is_on = (n == name)
            b.setChecked(is_on)
            b.setProperty("active", is_on)
            try:
                b.style().unpolish(b)
                b.style().polish(b)
            except Exception:
                pass

    def mark_custom(self) -> None:
        """Dot indicator when manual edits diverge from the preset (§20)."""
        if self._active is not None and self._active != "Custom":
            self.set_active(None)
        for n, b in self._buttons.items():
            if n == "Custom" and self._active is None:
                b.setText("Custom •")
            elif n == "Custom":
                b.setText("Custom")


__all__ = [
    "EditableValue", "SliderField", "Toggle", "StatusChip", "Disclosure",
    "PresetSegment", "expansion_state", "set_expansion_state",
]

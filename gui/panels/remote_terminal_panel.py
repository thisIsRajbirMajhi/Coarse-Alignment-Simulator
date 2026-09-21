# gui/panels/remote_terminal_panel.py - Remote Terminal Control Deck (Plan/RemoteTerminal.md §§54-57).
#
# Formation/motion card (metadata-driven from FIELD_METADATA) + per-terminal
# editor + read-only runtime telemetry. Emits validated RemoteScenarioConfig;
# invalid input shows an inline message and is never emitted (§78).
from __future__ import annotations

import copy
import logging

from PyQt5.QtCore import pyqtSignal
from PyQt5.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
)

from gui.panels.base import BaseConfigPanel
from remote_terminal.config import (
    FIELD_METADATA,
    FORMATION_SHAPE_LABELS,
    MAX_TERMINALS,
    MODULATION_LABELS,
    MOTION_PROFILE_LABELS,
    OPERATIONAL_STATE_LABELS,
    FormationShape,
    ModulationType,
    MotionProfile,
    OperationalState,
    RemoteFormationConfig,
    RemoteScenarioConfig,
    RemoteTerminalConfig,
    coerce_enum,
    make_default_scenario,
)

log = logging.getLogger(__name__)

# Wavelength choices for randomization (supported near-infrared FSOC bands).
_RANDOM_WAVELENGTHS = (850.0, 980.0, 1064.0, 1310.0, 1550.0)


def _meta(key: str) -> dict:
    return FIELD_METADATA.get(key, {})


def _tooltip(key: str) -> str:
    m = _meta(key)
    desc = str(m.get("description", ""))
    unit = str(m.get("unit", ""))
    extra = ""
    if m.get("min") is not None and m.get("max") is not None:
        extra = f" [{m['min']}..{m['max']}{(' ' + unit) if unit else ''}]"
    unit_t = f" ({unit})" if unit else ""
    return f"{m.get('label', key)}{unit_t}{extra}. {desc}".strip()


class RemoteTerminalPanel(BaseConfigPanel):
    """Remote Terminal scenario editor (formation + terminals + telemetry)."""

    configChanged = pyqtSignal(object)

    def __init__(self, initial: RemoteScenarioConfig | None = None, parent=None):
        super().__init__(parent)
        try:
            self._config = (initial or make_default_scenario()).validate()
        except ValueError:
            self._config = make_default_scenario()
        self._selected = 0
        self._updating = False
        self._build_ui()
        self.set_config(self._config, emit=False)

    # -- UI ----------------------------------------------------------
    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(10)

        title = QLabel("REMOTE TERMINAL SCENARIO")
        title.setStyleSheet("font-size:15px; font-weight:700;")
        header_row = QHBoxLayout()
        header_row.addWidget(title)
        header_row.addStretch(1)
        self.btn_randomize_terminals = QPushButton("🎲 Randomize Terminals")
        self.btn_randomize_terminals.setMinimumHeight(28)
        self.btn_randomize_terminals.setToolTip(
            "Randomize formation, motion and every terminal's parameters")
        self.btn_randomize_terminals.clicked.connect(lambda: self.randomize(emit=True))
        header_row.addWidget(self.btn_randomize_terminals)
        root.addLayout(header_row)
        desc = QLabel("Formation, motion, per-terminal optical setup and live telemetry")
        desc.setStyleSheet("color:#8F9CAB; font-size:11px;")
        root.addWidget(desc)

        # FORMATION card (schema-driven labels/units/ranges).
        form_box, form_grid = self._make_group("FORMATION")
        self.spin_count = QSpinBox()
        self.spin_count.setRange(int(_meta("terminal_count")["min"]),
                                 int(_meta("terminal_count")["max"]))
        self.spin_count.setToolTip(_tooltip("terminal_count"))
        self.combo_shape = QComboBox()
        for value, label in FORMATION_SHAPE_LABELS.items():
            self.combo_shape.addItem(label, value)
        self.combo_shape.setToolTip(_tooltip("formation_shape"))
        self.spin_spacing = QDoubleSpinBox()
        self.spin_spacing.setRange(float(_meta("terminal_spacing_m")["min"]),
                                   float(_meta("terminal_spacing_m")["max"]))
        self.spin_spacing.setSingleStep(float(_meta("terminal_spacing_m")["step"]))
        self.spin_spacing.setSuffix(" m")
        self.spin_spacing.setToolTip(_tooltip("terminal_spacing_m"))
        form_grid.addWidget(self._label("Terminal Count"), 0, 0)
        form_grid.addWidget(self.spin_count, 0, 1)
        form_grid.addWidget(self._label("Formation Shape"), 1, 0)
        form_grid.addWidget(self.combo_shape, 1, 1)
        form_grid.addWidget(self._label("Terminal Spacing"), 2, 0)
        form_grid.addWidget(self.spin_spacing, 2, 1)
        root.addWidget(form_box)

        # MOTION card.
        mot_box, mot_grid = self._make_group("MOTION")
        self.combo_motion = QComboBox()
        for value, label in MOTION_PROFILE_LABELS.items():
            self.combo_motion.addItem(label, value)
        self.combo_motion.setToolTip(_tooltip("motion_profile"))
        self.spin_speed = QDoubleSpinBox()
        self.spin_speed.setRange(float(_meta("speed_mps")["min"]),
                                 float(_meta("speed_mps")["max"]))
        self.spin_speed.setSingleStep(float(_meta("speed_mps")["step"]))
        self.spin_speed.setSuffix(" m/s")
        self.spin_speed.setToolTip(_tooltip("speed_mps"))
        self.spin_heading = QDoubleSpinBox()
        self.spin_heading.setRange(float(_meta("heading_deg")["min"]),
                                   float(_meta("heading_deg")["max"]))
        self.spin_heading.setSingleStep(float(_meta("heading_deg")["step"]))
        self.spin_heading.setSuffix(" deg")
        self.spin_heading.setToolTip(_tooltip("heading_deg"))
        mot_grid.addWidget(self._label("Motion Profile"), 0, 0)
        mot_grid.addWidget(self.combo_motion, 0, 1)
        mot_grid.addWidget(self._label("Speed"), 1, 0)
        mot_grid.addWidget(self.spin_speed, 1, 1)
        mot_grid.addWidget(self._label("Heading"), 2, 0)
        mot_grid.addWidget(self.spin_heading, 2, 1)
        mot_grid.addWidget(
            self._hint("Velocity is derived from speed + heading (read-only telemetry below)."),
            3, 0, 1, 2,
        )
        root.addWidget(mot_box)

        # STARTING POSITION card (formation-center offset from world center).
        start_box, start_grid = self._make_group("STARTING POSITION")
        self.spin_start_x = QDoubleSpinBox()
        self.spin_start_x.setRange(float(_meta("start_offset_x_m")["min"]),
                                   float(_meta("start_offset_x_m")["max"]))
        self.spin_start_x.setSingleStep(float(_meta("start_offset_x_m")["step"]))
        self.spin_start_x.setSuffix(" m")
        self.spin_start_x.setToolTip(_tooltip("start_offset_x_m"))
        self.spin_start_y = QDoubleSpinBox()
        self.spin_start_y.setRange(float(_meta("start_offset_y_m")["min"]),
                                   float(_meta("start_offset_y_m")["max"]))
        self.spin_start_y.setSingleStep(float(_meta("start_offset_y_m")["step"]))
        self.spin_start_y.setSuffix(" m")
        self.spin_start_y.setToolTip(_tooltip("start_offset_y_m"))
        start_grid.addWidget(self._label("Start Offset X"), 0, 0)
        start_grid.addWidget(self.spin_start_x, 0, 1)
        start_grid.addWidget(self._label("Start Offset Y"), 1, 0)
        start_grid.addWidget(self.spin_start_y, 1, 1)
        start_grid.addWidget(
            self._hint("Formation-center offset from world center at build/reset. "
                       "(0, 0) = scene center."),
            2, 0, 1, 2,
        )
        root.addWidget(start_box)

        # TERMINAL card.
        term_box, term_grid = self._make_group("TERMINAL")
        self.combo_terminal = QComboBox()
        self.combo_terminal.setToolTip("Select the terminal to edit")
        self.edit_tid = QLineEdit("RT-001")
        self.edit_tid.setToolTip(_tooltip("terminal_id"))
        self.chk_power = QCheckBox("ON")
        self.chk_power.setToolTip(_tooltip("power_enabled"))
        self.chk_beacon = QCheckBox("ON")
        self.chk_beacon.setToolTip(_tooltip("beacon_enabled"))
        self.combo_state = QComboBox()
        for value, label in OPERATIONAL_STATE_LABELS.items():
            self.combo_state.addItem(label, value)
        self.combo_state.setToolTip(_tooltip("operational_state"))
        self.spin_opt_power = QDoubleSpinBox()
        self.spin_opt_power.setRange(float(_meta("optical_power_w")["min"]),
                                     float(_meta("optical_power_w")["max"]))
        self.spin_opt_power.setSingleStep(float(_meta("optical_power_w")["step"]))
        self.spin_opt_power.setSuffix(" W")
        self.spin_opt_power.setToolTip(_tooltip("optical_power_w"))
        self.spin_wavelength = QDoubleSpinBox()
        self.spin_wavelength.setRange(float(_meta("wavelength_nm")["min"]),
                                      float(_meta("wavelength_nm")["max"]))
        self.spin_wavelength.setSingleStep(float(_meta("wavelength_nm")["step"]))
        self.spin_wavelength.setSuffix(" nm")
        self.spin_wavelength.setToolTip(_tooltip("wavelength_nm"))
        self.combo_mod = QComboBox()
        for value, label in MODULATION_LABELS.items():
            self.combo_mod.addItem(label, value)
        self.combo_mod.setToolTip(_tooltip("modulation"))
        self.spin_spot = QDoubleSpinBox()
        self.spin_spot.setRange(float(_meta("spot_size_mrad")["min"]),
                                float(_meta("spot_size_mrad")["max"]))
        self.spin_spot.setSingleStep(float(_meta("spot_size_mrad")["step"]))
        self.spin_spot.setSuffix(" mrad")
        self.spin_spot.setToolTip(_tooltip("spot_size_mrad"))
        term_grid.addWidget(self._label("Active Terminal"), 0, 0)
        term_grid.addWidget(self.combo_terminal, 0, 1)
        term_grid.addWidget(self._label("Terminal ID"), 1, 0)
        term_grid.addWidget(self.edit_tid, 1, 1)
        em_row = QHBoxLayout()
        em_row.addWidget(self._label("Power"))
        em_row.addWidget(self.chk_power)
        em_row.addWidget(self._label("Beacon"))
        em_row.addWidget(self.chk_beacon)
        em_row.addStretch(1)
        term_grid.addLayout(em_row, 2, 0, 1, 2)
        term_grid.addWidget(self._label("Operational State"), 3, 0)
        term_grid.addWidget(self.combo_state, 3, 1)
        term_grid.addWidget(self._label("Optical Power"), 4, 0)
        term_grid.addWidget(self.spin_opt_power, 4, 1)
        term_grid.addWidget(self._label("Wavelength"), 5, 0)
        term_grid.addWidget(self.spin_wavelength, 5, 1)
        term_grid.addWidget(self._label("Modulation"), 6, 0)
        term_grid.addWidget(self.combo_mod, 6, 1)
        term_grid.addWidget(self._label("Spot Size"), 7, 0)
        term_grid.addWidget(self.spin_spot, 7, 1)
        term_grid.addWidget(
            self._hint("Spot size = full angular beam width/divergence."),
            8, 0, 1, 2,
        )
        root.addWidget(term_box)

        # TELEMETRY card (read-only, §56).
        tele_box, tele_grid = self._make_group("TELEMETRY — read-only")
        self.tele_labels: dict[str, QLabel] = {}
        rows = [
            ("position", "Position (m)"), ("velocity", "Velocity (m/s)"),
            ("geometry", "Range / LOS"), ("beam", "Beam / Pointing Err"),
            ("footprint", "Beam Width / Diameter"), ("beacon", "Beacon Seq / Nav Time"),
            ("emission", "Emission / Power"),
        ]
        for i, (key, title_text) in enumerate(rows):
            tele_grid.addWidget(self._label(title_text), i, 0)
            lbl = QLabel("—")
            lbl.setStyleSheet("color:#111827; font-size:11px; font-family:'Consolas','Courier New',monospace;")
            tele_grid.addWidget(lbl, i, 1)
            self.tele_labels[key] = lbl
        root.addWidget(tele_box)

        self.error_label = QLabel("")
        self.error_label.setWordWrap(True)
        self.error_label.setStyleSheet("color:#B91C1C; font-size:11px;")
        self.error_label.setVisible(False)
        root.addWidget(self.error_label)
        root.addStretch(1)

        # Signals → collect + emit (invalid input shows a message, no emit).
        self.spin_count.valueChanged.connect(self._on_formation_changed)
        self.combo_shape.currentIndexChanged.connect(self._on_formation_changed)
        self.spin_spacing.valueChanged.connect(self._on_formation_changed)
        self.combo_motion.currentIndexChanged.connect(self._on_formation_changed)
        self.spin_speed.valueChanged.connect(self._on_formation_changed)
        self.spin_heading.valueChanged.connect(self._on_formation_changed)
        self.spin_start_x.valueChanged.connect(self._on_formation_changed)
        self.spin_start_y.valueChanged.connect(self._on_formation_changed)
        self.combo_terminal.currentIndexChanged.connect(self._on_terminal_selected)
        self.edit_tid.editingFinished.connect(self._on_terminal_edited)
        self.chk_power.toggled.connect(self._on_terminal_edited)
        self.chk_beacon.toggled.connect(self._on_terminal_edited)
        self.combo_state.currentIndexChanged.connect(self._on_terminal_edited)
        self.spin_opt_power.valueChanged.connect(self._on_terminal_edited)
        self.spin_wavelength.valueChanged.connect(self._on_terminal_edited)
        self.combo_mod.currentIndexChanged.connect(self._on_terminal_edited)
        self.spin_spot.valueChanged.connect(self._on_terminal_edited)

    # -- config ------------------------------------------------------
    def collect_config(self) -> RemoteScenarioConfig:
        """Validated scenario from widgets (raises ValueError if invalid)."""
        formation = RemoteFormationConfig(
            terminal_count=int(self.spin_count.value()),
            formation_shape=coerce_enum(
                FormationShape, self.combo_shape.currentData(), "formation shape"),
            motion_profile=coerce_enum(
                MotionProfile, self.combo_motion.currentData(), "motion profile"),
            terminal_spacing_m=float(self.spin_spacing.value()),
            speed_mps=float(self.spin_speed.value()),
            heading_deg=float(self.spin_heading.value()),
            start_offset_x_m=float(self.spin_start_x.value()),
            start_offset_y_m=float(self.spin_start_y.value()),
        )
        self._config.formation = formation
        self._sync_terminal_count(int(self.spin_count.value()))
        self._read_terminal_editor()
        return self._config.validate()

    def set_config(self, cfg: RemoteScenarioConfig, emit: bool = False) -> None:
        cfg = cfg.validate()
        self._config = copy.deepcopy(cfg)
        self._selected = min(self._selected, len(self._config.terminals) - 1)
        self._updating = True
        try:
            form = self._config.formation
            self.spin_count.setValue(int(form.terminal_count))
            self._set_combo(self.combo_shape, form.formation_shape.value)
            self.spin_spacing.setValue(float(form.terminal_spacing_m))
            self._set_combo(self.combo_motion, form.motion_profile.value)
            self.spin_speed.setValue(float(form.speed_mps))
            self.spin_heading.setValue(float(form.heading_deg))
            self.spin_start_x.setValue(float(getattr(form, "start_offset_x_m", 0.0)))
            self.spin_start_y.setValue(float(getattr(form, "start_offset_y_m", 0.0)))
            self._refresh_terminal_selector()
            self._load_terminal_editor()
            self._show_error("")
        finally:
            self._updating = False
        if emit:
            self._emit_config()

    def randomize(self, emit: bool = True) -> RemoteScenarioConfig:
        """Randomize formation, motion and every terminal's parameters.

        Returns the validated scenario. Shape/count stay consistent (SINGLE
        only with count 1) and IDs stay unique.
        """
        import random as _random

        count = _random.randint(1, MAX_TERMINALS)
        shapes = [s for s in FormationShape if s != FormationShape.SINGLE]
        shape = FormationShape.SINGLE if count == 1 else _random.choice(shapes)
        formation = RemoteFormationConfig(
            terminal_count=count,
            formation_shape=shape,
            motion_profile=_random.choice(list(MotionProfile)),
            terminal_spacing_m=round(_random.uniform(10.0, 500.0), 1),
            speed_mps=round(_random.uniform(0.0, 100.0), 1),
            heading_deg=round(_random.uniform(-180.0, 180.0), 1),
            start_offset_x_m=round(_random.uniform(-500.0, 500.0), 1),
            start_offset_y_m=round(_random.uniform(-500.0, 500.0), 1),
        )
        terminals = [
            RemoteTerminalConfig(
                terminal_id=f"RT-{i + 1:03d}",
                power_enabled=_random.random() < 0.8,
                beacon_enabled=_random.random() < 0.8,
                operational_state=_random.choice(list(OperationalState)),
                optical_power_w=round(_random.uniform(0.1, 2.0), 2),
                wavelength_nm=float(_random.choice(_RANDOM_WAVELENGTHS)),
                modulation=_random.choice(list(ModulationType)),
                spot_size_mrad=round(_random.uniform(0.2, 5.0), 2),
            )
            for i in range(count)
        ]
        cfg = RemoteScenarioConfig(formation=formation, terminals=terminals).validate()
        self._selected = 0
        self.set_config(cfg, emit=emit)
        return cfg

    def update_telemetry(self, telemetry: dict) -> None:
        """Render read-only runtime values (§56); never raises."""
        try:
            if not isinstance(telemetry, dict):
                return
            terms = telemetry.get("terminals") or []
            if not terms:
                return
            idx = min(max(0, self._selected), len(terms) - 1)
            t = terms[idx]
            pos = t.get("position_m", (0.0, 0.0))
            vel = t.get("velocity_mps", (0.0, 0.0))
            nav = t.get("beacon_navigation") or {}
            self.tele_labels["position"].setText(f"X {pos[0]:.1f}  Y {pos[1]:.1f}")
            self.tele_labels["velocity"].setText(f"Vx {vel[0]:.2f}  Vy {vel[1]:.2f}")
            self.tele_labels["geometry"].setText(
                f"{t.get('range_m', 0.0):.1f} m / {t.get('los_angle_deg', 0.0):.2f}°")
            self.tele_labels["beam"].setText(
                f"{t.get('beam_angle_deg', 0.0):.2f}° / {t.get('pointing_error_deg', 0.0):.3f}°")
            self.tele_labels["footprint"].setText(
                f"{t.get('beam_width_rad', 0.0) * 1000.0:.2f} mrad / "
                f"{t.get('beam_diameter_m', 0.0):.2f} m")
            self.tele_labels["beacon"].setText(
                f"#{t.get('beacon_sequence', 0)} / {nav.get('timestamp_ms', '—')} ms")
            self.tele_labels["emission"].setText(
                f"{'ON' if t.get('emitting') else 'OFF'} / "
                f"{t.get('instantaneous_power_w', 0.0):.3f} W")
        except Exception as e:
            log.debug("remote terminal telemetry update skipped: %s", e)

    # -- internals ---------------------------------------------------
    @staticmethod
    def _set_combo(combo: QComboBox, value: str) -> None:
        idx = combo.findData(value)
        if idx < 0:
            idx = 0
        combo.setCurrentIndex(idx)

    def _refresh_terminal_selector(self) -> None:
        self.combo_terminal.blockSignals(True)
        try:
            self.combo_terminal.clear()
            for t in self._config.terminals:
                self.combo_terminal.addItem(str(t.terminal_id))
            self.combo_terminal.setCurrentIndex(min(self._selected,
                                                    self.combo_terminal.count() - 1))
        finally:
            self.combo_terminal.blockSignals(False)

    def _load_terminal_editor(self) -> None:
        if not self._config.terminals:
            return
        t = self._config.terminals[self._selected]
        self.edit_tid.setText(str(t.terminal_id))
        self.chk_power.setChecked(bool(t.power_enabled))
        self.chk_beacon.setChecked(bool(t.beacon_enabled))
        self._set_combo(self.combo_state, t.operational_state.value)
        self.spin_opt_power.setValue(float(t.optical_power_w))
        self.spin_wavelength.setValue(float(t.wavelength_nm))
        self._set_combo(self.combo_mod, t.modulation.value)
        self.spin_spot.setValue(float(t.spot_size_mrad))

    def _read_terminal_editor(self) -> None:
        if not self._config.terminals:
            return
        t = self._config.terminals[self._selected]
        t.terminal_id = self.edit_tid.text().strip() or t.terminal_id
        t.power_enabled = bool(self.chk_power.isChecked())
        t.beacon_enabled = bool(self.chk_beacon.isChecked())
        t.operational_state = coerce_enum(
            OperationalState, self.combo_state.currentData(), "operational state")
        t.modulation = coerce_enum(
            ModulationType, self.combo_mod.currentData(), "modulation")
        t.optical_power_w = float(self.spin_opt_power.value())
        t.wavelength_nm = float(self.spin_wavelength.value())
        t.spot_size_mrad = float(self.spin_spot.value())

    def _sync_terminal_count(self, count: int) -> None:
        terms = self._config.terminals
        while len(terms) < count:
            n = len(terms) + 1
            tid = f"RT-{n:03d}"
            existing = {str(t.terminal_id) for t in terms}
            while tid in existing:
                n += 1
                tid = f"RT-{n:03d}"
            terms.append(RemoteTerminalConfig(terminal_id=tid))
        if len(terms) > count:
            del terms[count:]
        self._selected = min(self._selected, len(terms) - 1)

    def _show_error(self, message: str) -> None:
        self.error_label.setText(message)
        self.error_label.setVisible(bool(message))

    def _on_formation_changed(self) -> None:
        if self._updating:
            return
        self._sync_terminal_count(int(self.spin_count.value()))
        self._refresh_terminal_selector()
        self._emit_config()

    def _on_terminal_selected(self, index: int) -> None:
        if self._updating or index < 0:
            return
        # Persist the previously edited terminal before switching; refuse to
        # leave it in an invalid state (e.g. duplicated ID).
        try:
            self._read_terminal_editor()
            self._config.validate()
        except ValueError as e:
            self._show_error(str(e))
            # Revert the visual selection: still editing the previous terminal.
            self._updating = True
            try:
                self.combo_terminal.setCurrentIndex(self._selected)
            finally:
                self._updating = False
            return
        self._selected = min(index, len(self._config.terminals) - 1)
        self._updating = True
        try:
            self._load_terminal_editor()
        finally:
            self._updating = False
        self._emit_config()

    def _on_terminal_edited(self) -> None:
        if self._updating:
            return
        self._emit_config()

    def _emit_config(self) -> None:
        try:
            cfg = self.collect_config()
        except ValueError as e:
            self._show_error(str(e))
            return
        self._show_error("")
        self._refresh_terminal_selector()
        try:
            self.configChanged.emit(cfg)
        except Exception as e:
            log.debug("remote terminal config emit skipped: %s", e)


__all__ = ["RemoteTerminalPanel"]

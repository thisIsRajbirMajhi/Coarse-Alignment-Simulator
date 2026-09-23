# gui/panels/local_terminal_panel.py - V2 autonomy tunables (Redesign: Primary + Advanced tiers).
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
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from gui.panels.base import BaseConfigPanel
from local_terminal.models import AutonomyConfig

log = logging.getLogger(__name__)

_REACQ_PRESETS: dict[str, list[float]] = {
    "Default (50→800)": [50.0, 100.0, 200.0, 400.0, 800.0],
    "Narrow (50→200)": [50.0, 100.0, 200.0],
    "Wide (100→800)": [100.0, 200.0, 400.0, 800.0],
    "Agile (25→400)": [25.0, 50.0, 100.0, 200.0, 400.0],
}


def _dspin(minv: float, maxv: float, step: float, suffix: str = "", decimals: int = 2, tooltip: str = "") -> QDoubleSpinBox:
    w = QDoubleSpinBox()
    w.setRange(float(minv), float(maxv))
    w.setSingleStep(float(step))
    w.setDecimals(int(decimals))
    if suffix:
        w.setSuffix(suffix)
    if tooltip:
        w.setToolTip(tooltip)
    return w


def _ispin(minv: int, maxv: int, tooltip: str = "") -> QSpinBox:
    w = QSpinBox()
    w.setRange(int(minv), int(maxv))
    if tooltip:
        w.setToolTip(tooltip)
    return w


class LocalTerminalPanel(BaseConfigPanel):
    """V2 autonomy editor — Primary (operator) + Advanced (collapsed) tiers."""

    configChanged = pyqtSignal(object)

    def __init__(self, initial: AutonomyConfig | None = None, parent=None):
        super().__init__(parent)
        try:
            self._config = (initial or AutonomyConfig()).validate()
        except ValueError:
            self._config = AutonomyConfig().validate()
        self._updating = False
        self._build_ui()
        self.set_config(self._config, emit=False)

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(10)

        title = QLabel("AUTONOMY — Tracking & Acquisition")
        title.setStyleSheet("font-size:15px; font-weight:700;")
        header_row = QHBoxLayout()
        header_row.addWidget(title)
        header_row.addStretch(1)
        self.btn_reset = self._make_reset_button("Reset")
        self.btn_reset.clicked.connect(self.reset_to_defaults)
        header_row.addWidget(self.btn_reset)
        root.addLayout(header_row)
        hint = QLabel("Primary: SNR · P_rx · Lost · Reacq · Policy  ·  Advanced: Kalman, gating, dwell")
        hint.setStyleSheet("color:#64748b; font-size:11px;")
        root.addWidget(hint)

        # ========== AI TOGGLE (Plan Hybrid-AI §2 — 1-frame fallback to pure classical) ==========
        ai_box, ai_grid = self._make_group("AI HYBRID — OFF = pure classical, ON = AI + classical veto")
        self.chk_ai = QCheckBox("AI ON (Tiny-CNN verifier · MLP scorer · Temporal-MLP predictor · Ranker)")
        self.chk_ai.setStyleSheet("color:#0f766e; font-size:12px; font-weight:600;")
        self.chk_ai.setToolTip("OFF: deterministic V2 FSM only. ON: AI scores but classical gate always vetoes. One-frame fallback.")
        self.spin_ai_thr = _dspin(0.3, 0.9, 0.05, decimals=2, tooltip="AI verifier threshold p(beacon) — 0.6 default")
        self.spin_ai_thr.setValue(0.6)
        ai_grid.addWidget(self.chk_ai, 0, 0, 1, 2)
        ai_grid.addWidget(self._label("Verifier Thr"), 0, 2)
        ai_grid.addWidget(self.spin_ai_thr, 0, 3)
        ai_grid.addWidget(self._hint("AI is advisory: classical FSM wins. FPS ≥28 ON, ≥35 OFF. No GPU."), 1, 0, 1, 4)
        root.addWidget(ai_box)

        # ========== PRIMARY: SEARCH & DETECTION ==========
        s_box, s_grid = self._make_group("SEARCH & DETECTION — Primary")
        self.combo_search = QComboBox()
        self.combo_search.addItems(["systematic", "last_known", "predicted"])
        self.combo_search.setToolTip("Search priority: systematic raster / last-known / Kalman predicted")
        self.spin_snr = _dspin(0.0, 40.0, 0.5, suffix=" dB", decimals=1, tooltip="Min SNR gate (6dB default)")
        self.spin_confirm = _ispin(1, 5, tooltip="Confirm frames — reject 1-frame hot pixel")
        # NEW: P_rx floor (mW for UI, stored as W) + Scan start cell (migrated from Camera)
        self.spin_p_rx = _dspin(0.0, 100.0, 0.5, suffix=" mW", decimals=2, tooltip="P_rx floor — signal-strength gate (0=disabled)")
        self.spin_scan_start = _ispin(0, 19, tooltip="Scan grid start cell (0..19)")
        s_grid.addWidget(self._label("Search Pattern"), 0, 0)
        s_grid.addWidget(self.combo_search, 0, 1)
        s_grid.addWidget(self._label("Scan Start"), 0, 2)
        s_grid.addWidget(self.spin_scan_start, 0, 3)
        s_grid.addWidget(self._label("Min SNR"), 1, 0)
        s_grid.addWidget(self.spin_snr, 1, 1)
        s_grid.addWidget(self._label("Confirm Frames"), 1, 2)
        s_grid.addWidget(self.spin_confirm, 1, 3)
        s_grid.addWidget(self._label("P_rx Floor"), 2, 0)
        s_grid.addWidget(self.spin_p_rx, 2, 1)
        s_grid.addWidget(self._hint("P_rx=0 disables power gate; SNR is primary gate."), 2, 2, 1, 2)
        root.addWidget(s_box)

        # ========== PRIMARY: LOST & REACQ ==========
        lr_box, lr_grid = self._make_group("LOST & REACQUISITION — Primary")
        self.spin_lost_unc = _dspin(1.0, 100.0, 1.0, suffix=" px", decimals=1, tooltip="Lost if uncertainty > this")
        self.spin_lost_t = _dspin(0.05, 5.0, 0.05, suffix=" s", decimals=2, tooltip="Lost if time since meas > this (AND with uncertainty)")
        self.combo_reacq = QComboBox()
        self.combo_reacq.addItems(list(_REACQ_PRESETS.keys()) + ["Custom"])
        self.combo_reacq.setToolTip("Escalation ladder radii (px)")
        self.chk_full_scan = QCheckBox("Full-scan fallback")
        self.chk_full_scan.setToolTip("After ladder, fall back to 20-cell raster")
        self.chk_full_scan.setStyleSheet("color:#374151; font-size:11px;")
        self.edit_reacq = QLineEdit("50, 100, 200, 400, 800")
        self.edit_reacq.setPlaceholderText("50, 100, 200, 400, 800")
        self.edit_reacq.setToolTip("Custom radii csv (px) — pick 'Custom' to edit")
        lr_grid.addWidget(self._label("Lost Unc"), 0, 0)
        lr_grid.addWidget(self.spin_lost_unc, 0, 1)
        lr_grid.addWidget(self._label("Lost Time"), 0, 2)
        lr_grid.addWidget(self.spin_lost_t, 0, 3)
        lr_grid.addWidget(self._label("Reacq Ladder"), 1, 0)
        lr_grid.addWidget(self.combo_reacq, 1, 1)
        lr_grid.addWidget(self.chk_full_scan, 1, 2, 1, 2)
        lr_grid.addWidget(self.edit_reacq, 2, 0, 1, 4)
        root.addWidget(lr_box)

        # ========== PRIMARY: SELECTOR ==========
        sel_box, sel_grid = self._make_group("SELECTOR — Primary")
        self.combo_policy = QComboBox()
        self.combo_policy.addItems(["priority"])
        self.combo_policy.setToolTip("Pruned: priority only (strongest_prx/highest_snr removed per Plan)")
        self.edit_priority = QLineEdit("")
        self.edit_priority.setPlaceholderText("Priority TID order: RT-001, RT-002, … (empty = formation order)")
        self.edit_priority.setToolTip("Mission priority list (comma-separated TID, index 0 = highest)")
        sel_grid.addWidget(self._label("Policy"), 0, 0)
        sel_grid.addWidget(self.combo_policy, 0, 1)
        sel_grid.addWidget(self._label("Priority Order"), 1, 0)
        sel_grid.addWidget(self.edit_priority, 1, 1)
        root.addWidget(sel_box)

        # ========== ADVANCED (collapsed) ==========
        self.chk_advanced = QCheckBox("Show advanced (Kalman · gating · dwell · R scales)")
        self.chk_advanced.setStyleSheet("color:#4b5563; font-size:11px; font-weight:600;")
        root.addWidget(self.chk_advanced)
        self.advanced_widget = QWidget()
        adv = QVBoxLayout(self.advanced_widget)
        adv.setContentsMargins(0, 0, 0, 0)
        adv.setSpacing(10)

        # Advanced: dwell + peak/area
        adv_s_box, adv_s_grid = self._make_group("SEARCH — Advanced")
        self.spin_dwell = _ispin(1, 10, tooltip="Frames per cell")
        self.spin_ext_dwell = _ispin(1, 30, tooltip="Extended dwell on P_rx candidate")
        self.spin_margin = _dspin(0.0, 50.0, 1.0, decimals=1, tooltip="Peak above background (threshold = bg + margin)")
        self.spin_min_area = _ispin(1, 100, tooltip="Min spot area")
        self.spin_max_area = _ispin(10, 10000, tooltip="Max spot area")
        adv_s_grid.addWidget(self._label("Dwell"), 0, 0)
        adv_s_grid.addWidget(self.spin_dwell, 0, 1)
        adv_s_grid.addWidget(self._label("Ext Dwell"), 0, 2)
        adv_s_grid.addWidget(self.spin_ext_dwell, 0, 3)
        adv_s_grid.addWidget(self._label("Peak Margin"), 1, 0)
        adv_s_grid.addWidget(self.spin_margin, 1, 1)
        adv_s_grid.addWidget(self._label("Min Area"), 1, 2)
        adv_s_grid.addWidget(self.spin_min_area, 1, 3)
        adv_s_grid.addWidget(self._label("Max Area"), 2, 0)
        adv_s_grid.addWidget(self.spin_max_area, 2, 1)
        adv.addWidget(adv_s_box)

        # Advanced: Kalman & gating
        k_box, k_grid = self._make_group("TRACKING — Kalman & Association — Advanced")
        self.spin_q = _dspin(1e-6, 100.0, 1.0, decimals=2, tooltip="Process noise Q")
        self.spin_r = _dspin(1e-6, 100.0, 1.0, decimals=2, tooltip="R base")
        self.spin_r_low = _dspin(1.0, 20.0, 0.5, decimals=2, tooltip="R scale when SNR poor (×)")
        self.spin_r_high = _dspin(0.05, 1.0, 0.05, decimals=2, tooltip="R scale when SNR high (×, <1)")
        self.spin_gate_px = _dspin(1.0, 200.0, 1.0, suffix=" px", decimals=1, tooltip="Fixed gate (acquisition only) — Mahalanobis is tracking gate")
        self.spin_mahal = _dspin(0.5, 20.0, 0.5, decimals=2, tooltip="Mahal d² threshold (9.21 = χ² 99% 2-dof)")
        k_grid.addWidget(self._label("Process Q"), 0, 0)
        k_grid.addWidget(self.spin_q, 0, 1)
        k_grid.addWidget(self._label("Meas R Base"), 0, 2)
        k_grid.addWidget(self.spin_r, 0, 3)
        k_grid.addWidget(self._label("R scale Low SNR"), 1, 0)
        k_grid.addWidget(self.spin_r_low, 1, 1)
        k_grid.addWidget(self._label("R scale High SNR"), 1, 2)
        k_grid.addWidget(self.spin_r_high, 1, 3)
        k_grid.addWidget(self._label("Fixed Gate"), 2, 0)
        k_grid.addWidget(self.spin_gate_px, 2, 1)
        k_grid.addWidget(self._label("Mahal Thresh"), 2, 2)
        k_grid.addWidget(self.spin_mahal, 2, 3)
        adv.addWidget(k_box)

        # Advanced: Coast (legacy, consolidated with Lost in Primary)
        c_box, c_grid = self._make_group("COAST — Advanced (legacy)")
        self.spin_coast_unc = _dspin(1.0, 100.0, 1.0, suffix=" px", decimals=1)
        self.spin_coast_t = _dspin(0.05, 5.0, 0.05, suffix=" s", decimals=2)
        c_grid.addWidget(self._label("Coast Unc"), 0, 0)
        c_grid.addWidget(self.spin_coast_unc, 0, 1)
        c_grid.addWidget(self._label("Coast Time"), 0, 2)
        c_grid.addWidget(self.spin_coast_t, 0, 3)
        c_grid.addWidget(self._hint("Coast is internal; Lost (Primary) is the operator gate (AND)."), 1, 0, 1, 4)
        adv.addWidget(c_box)

        self.advanced_widget.setVisible(False)
        adv.addStretch(1)
        root.addWidget(self.advanced_widget)
        self.chk_advanced.toggled.connect(self.advanced_widget.setVisible)

        root.addStretch(1)

        for w in self._watched_widgets():
            if isinstance(w, QComboBox):
                w.currentIndexChanged.connect(self._on_changed)
            elif isinstance(w, QCheckBox):
                w.toggled.connect(self._on_changed)
            elif isinstance(w, QLineEdit):
                w.editingFinished.connect(self._on_changed)
            else:
                try:
                    w.valueChanged.connect(self._on_changed)
                except AttributeError:
                    pass
        self.combo_reacq.currentIndexChanged.connect(self._on_reacq_preset)
        self.edit_priority.editingFinished.connect(self._on_changed)

    def _watched_widgets(self):
        base = [
            self.chk_ai, self.spin_ai_thr,
            self.combo_search, self.spin_scan_start,
            self.spin_snr, self.spin_confirm, self.spin_p_rx,
            self.spin_lost_unc, self.spin_lost_t, self.combo_reacq, self.chk_full_scan, self.edit_reacq,
            self.combo_policy, self.edit_priority,
            self.spin_dwell, self.spin_ext_dwell, self.spin_margin, self.spin_min_area, self.spin_max_area,
            self.spin_q, self.spin_r, self.spin_r_low, self.spin_r_high, self.spin_gate_px, self.spin_mahal,
            self.spin_coast_unc, self.spin_coast_t,
        ]
        return base

    def _on_reacq_preset(self, idx: int):
        if self._updating:
            return
        name = self.combo_reacq.currentText()
        if name in _REACQ_PRESETS:
            self.edit_reacq.setText(", ".join(str(int(v)) for v in _REACQ_PRESETS[name]))
            self.edit_reacq.setEnabled(False)
        else:
            self.edit_reacq.setEnabled(True)
        self._on_changed()

    def collect_config(self) -> AutonomyConfig:
        # Reacq radii: preset or custom csv
        name = self.combo_reacq.currentText()
        if name in _REACQ_PRESETS:
            radii = list(_REACQ_PRESETS[name])
        else:
            try:
                radii = [float(x.strip()) for x in self.edit_reacq.text().split(",") if x.strip()]
                if not radii:
                    radii = [50.0, 100.0, 200.0, 400.0, 800.0]
            except (TypeError, ValueError):
                radii = [50.0, 100.0, 200.0, 400.0, 800.0]
        # p_rx displayed as mW
        # priority csv -> list
        prio = [x.strip() for x in self.edit_priority.text().split(",") if x.strip()]
        cfg = AutonomyConfig(
            ai_enabled=bool(self.chk_ai.isChecked()),
            ai_verifier_threshold=float(self.spin_ai_thr.value()),
            search_dwell_frames=int(self.spin_dwell.value()),
            search_extended_dwell_frames=int(self.spin_ext_dwell.value()),
            search_start_index=int(self.spin_scan_start.value()),
            candidate_min_snr_db=float(self.spin_snr.value()),
            candidate_peak_margin=float(self.spin_margin.value()),
            candidate_confirm_frames=int(self.spin_confirm.value()),
            candidate_min_area_px=int(self.spin_min_area.value()),
            candidate_max_area_px=int(self.spin_max_area.value()),
            association_gate_px=float(self.spin_gate_px.value()),
            association_mahal_threshold=float(self.spin_mahal.value()),
            kalman_process_noise_q=float(self.spin_q.value()),
            kalman_measurement_noise_r_base=float(self.spin_r.value()),
            kalman_r_scale_low_snr=float(self.spin_r_low.value()),
            kalman_r_scale_high_snr=float(self.spin_r_high.value()),
            coast_max_uncertainty_px=float(self.spin_coast_unc.value()),
            coast_timeout_s=float(self.spin_coast_t.value()),
            lost_uncertainty_threshold_px=float(self.spin_lost_unc.value()),
            lost_timeout_s=float(self.spin_lost_t.value()),
            reacq_radii_px=radii,
            reacq_full_scan_enabled=bool(self.chk_full_scan.isChecked()),
            active_target_policy=str(self.combo_policy.currentText()),
            mission_priority=prio,
            p_rx_threshold_w=float(self.spin_p_rx.value()) / 1000.0,
        )
        return cfg.validate()

    def set_config(self, cfg, emit: bool = False) -> None:
        try:
            if hasattr(cfg, "detector"):
                from local_terminal.models import AutonomyConfig as _AC
                cfg = _AC().validate()
            else:
                cfg = cfg.validate()
        except Exception:
            from local_terminal.models import AutonomyConfig as _AC
            cfg = _AC().validate()
        self._config = copy.deepcopy(cfg)
        self._updating = True
        try:
            for w in self._watched_widgets():
                w.blockSignals(True)
            self.chk_ai.setChecked(bool(getattr(cfg, "ai_enabled", False)))
            self.spin_ai_thr.setValue(float(getattr(cfg, "ai_verifier_threshold", 0.6)))
            self.spin_dwell.setValue(int(cfg.search_dwell_frames))
            self.spin_ext_dwell.setValue(int(cfg.search_extended_dwell_frames))
            self.spin_scan_start.setValue(int(getattr(cfg, "search_start_index", 0)))
            # search_pattern removed — AI ranker owns schedule; keep combo as legacy display
            try:
                self.combo_search.setEnabled(False)
                self.combo_search.setToolTip("Pruned: AI Ranker owns schedule (systematic fallback)")
            except Exception:
                pass
            self.spin_snr.setValue(float(cfg.candidate_min_snr_db))
            self.spin_margin.setValue(float(cfg.candidate_peak_margin))
            self.spin_confirm.setValue(int(cfg.candidate_confirm_frames))
            self.spin_min_area.setValue(int(cfg.candidate_min_area_px))
            self.spin_max_area.setValue(int(cfg.candidate_max_area_px))
            self.spin_q.setValue(float(cfg.kalman_process_noise_q))
            self.spin_r.setValue(float(cfg.kalman_measurement_noise_r_base))
            self.spin_r_low.setValue(float(getattr(cfg, "kalman_r_scale_low_snr", 6.0)))
            self.spin_r_high.setValue(float(getattr(cfg, "kalman_r_scale_high_snr", 0.5)))
            self.spin_gate_px.setValue(float(cfg.association_gate_px))
            self.spin_mahal.setValue(float(cfg.association_mahal_threshold))
            self.spin_coast_unc.setValue(float(cfg.coast_max_uncertainty_px))
            self.spin_coast_t.setValue(float(cfg.coast_timeout_s))
            self.spin_lost_unc.setValue(float(cfg.lost_uncertainty_threshold_px))
            self.spin_lost_t.setValue(float(cfg.lost_timeout_s))
            # reacq preset or custom
            radii = list(cfg.reacq_radii_px or [50.0, 100.0, 200.0, 400.0, 800.0])
            matched = None
            for k, v in _REACQ_PRESETS.items():
                if radii == v:
                    matched = k
                    break
            if matched is not None:
                self.combo_reacq.setCurrentText(matched)
                self.edit_reacq.setText(", ".join(str(int(v)) for v in radii))
                self.edit_reacq.setEnabled(False)
            else:
                idx = self.combo_reacq.findText("Custom")
                if idx >= 0:
                    self.combo_reacq.setCurrentIndex(idx)
                self.edit_reacq.setText(", ".join(str(int(v)) for v in radii))
                self.edit_reacq.setEnabled(True)
            self.chk_full_scan.setChecked(bool(cfg.reacq_full_scan_enabled))
            self.spin_p_rx.setValue(float(cfg.p_rx_threshold_w) * 1000.0)
            idx2 = self.combo_policy.findText(str(cfg.active_target_policy))
            self.combo_policy.setCurrentIndex(max(0, idx2))
            try:
                prio = getattr(cfg, "mission_priority", []) or []
                self.edit_priority.setText(", ".join(str(x) for x in prio))
            except Exception:
                pass
        finally:
            for w in self._watched_widgets():
                w.blockSignals(False)
            self._updating = False
        if emit:
            self._emit_config()

    def reset_to_defaults(self) -> None:
        from local_terminal.models import AutonomyConfig
        self.set_config(AutonomyConfig().validate(), emit=True)

    def _on_changed(self) -> None:
        if self._updating:
            return
        self._emit_config()

    def _emit_config(self) -> None:
        try:
            cfg = self.collect_config()
        except ValueError as e:
            log.debug("local terminal config invalid: %s", e)
            return
        try:
            self.configChanged.emit(cfg)
        except Exception as e:
            log.debug("local terminal config emit skipped: %s", e)


__all__ = ["LocalTerminalPanel"]

# gui/panels/local_terminal_panel.py - Local Terminal autonomy tunables.
#
# Grid-format groups for every local-terminal stage that was previously an
# internal default: detection gates (§5.1), validation policy (§5.3-5.5),
# image-tracker association (§7.1), α-β motion model (§7.3), scan schedule
# (§4), re-acquisition ladder (§8), and supervisor/standby policy (§6, §9).
# Emits a validated LocalTerminalConfig; never touches simulation directly.
from __future__ import annotations

import copy
import logging

from PyQt5.QtCore import pyqtSignal
from PyQt5.QtWidgets import (
    QComboBox,
    QDoubleSpinBox,
    QHBoxLayout,
    QLabel,
    QSpinBox,
    QVBoxLayout,
)

from gui.panels.base import BaseConfigPanel
from local_terminal.config import LocalTerminalConfig, make_default_local_terminal

log = logging.getLogger(__name__)


def _dspin(minv: float, maxv: float, step: float, suffix: str = "",
           decimals: int = 2, tooltip: str = "") -> QDoubleSpinBox:
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
    """Local-terminal autonomy editor (detection → validation → track)."""

    configChanged = pyqtSignal(object)

    def __init__(self, initial: LocalTerminalConfig | None = None, parent=None):
        super().__init__(parent)
        try:
            self._config = (initial or make_default_local_terminal()).validate()
        except ValueError:
            self._config = make_default_local_terminal()
        self._updating = False
        self._build_ui()
        self.set_config(self._config, emit=False)

    # -- UI (grid format) ------------------------------------------
    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(10)

        title = QLabel("LOCAL TERMINAL AUTONOMY")
        title.setStyleSheet("font-size:15px; font-weight:700;")
        header_row = QHBoxLayout()
        header_row.addWidget(title)
        header_row.addStretch(1)
        self.btn_reset = self._make_reset_button("Reset Local")
        self.btn_reset.setToolTip("Reset all local-terminal tunables to defaults")
        self.btn_reset.clicked.connect(self.reset_to_defaults)
        header_row.addWidget(self.btn_reset)
        root.addLayout(header_row)
        desc = QLabel("Detection gates, validation, tracking, scan, re-acquisition, supervisor")
        desc.setStyleSheet("color:#8F9CAB; font-size:11px;")
        root.addWidget(desc)

        # 1. DETECTION (photometric gates, §5.1).
        det_box, det_grid = self._make_group("DETECTION — photometric gates")
        self.spin_peak = _dspin(1.0, 255.0, 1.0, decimals=1,
            tooltip="Peak pixel intensity floor (/255)")
        self.spin_sigma = _dspin(0.5, 50.0, 0.1, suffix=" px",
            tooltip="Spot sigma floor (px)")
        self.spin_r2 = _dspin(0.0, 1.0, 0.01,
            tooltip="Gaussian-fit compactness floor")
        self.spin_snr = _dspin(0.0, 40.0, 0.5, suffix=" dB", decimals=1,
            tooltip="SNR above local background floor")
        self.spin_isolation = _dspin(1.0, 100.0, 1.0, suffix=" px", decimals=1,
            tooltip="Merge candidates closer than this")
        self.spin_bg = _ispin(1, 32, "Background ring width around region (px)")
        self.spin_maxcand = _ispin(1, 64, "Candidate cap, brightest-first")
        det_grid.addWidget(self._label("Peak Min"), 0, 0)
        det_grid.addWidget(self.spin_peak, 0, 1)
        det_grid.addWidget(self._label("Sigma Min"), 1, 0)
        det_grid.addWidget(self.spin_sigma, 1, 1)
        det_grid.addWidget(self._label("Compactness R² Min"), 2, 0)
        det_grid.addWidget(self.spin_r2, 2, 1)
        det_grid.addWidget(self._label("SNR Min"), 3, 0)
        det_grid.addWidget(self.spin_snr, 3, 1)
        det_grid.addWidget(self._label("Isolation"), 4, 0)
        det_grid.addWidget(self.spin_isolation, 4, 1)
        det_grid.addWidget(self._label("BG Annulus"), 5, 0)
        det_grid.addWidget(self.spin_bg, 5, 1)
        det_grid.addWidget(self._label("Max Candidates"), 6, 0)
        det_grid.addWidget(self.spin_maxcand, 6, 1)
        root.addWidget(det_box)

        # 2. VALIDATION (lifecycle + scoring, §5.3-5.5).
        val_box, val_grid = self._make_group("VALIDATION — lifecycle & scoring")
        self.spin_score = _dspin(0.0, 1.0, 0.01,
            tooltip="Composite score floor for SELECTED")
        self.spin_strikes = _ispin(1, 10, "Strikes before blacklist")
        self.spin_strikewin = _dspin(1.0, 300.0, 1.0, suffix=" s", decimals=1,
            tooltip="Strike memory window")
        self.spin_decodeto = _dspin(0.05, 5.0, 0.01, suffix=" s", decimals=3,
            tooltip="No-decode watchdog before the track is dropped")
        self.spin_hist = _ispin(2, 50, "Photometry history length")
        val_grid.addWidget(self._label("Score Min"), 0, 0)
        val_grid.addWidget(self.spin_score, 0, 1)
        val_grid.addWidget(self._label("Strikes → Blacklist"), 1, 0)
        val_grid.addWidget(self.spin_strikes, 1, 1)
        val_grid.addWidget(self._label("Strike Window"), 2, 0)
        val_grid.addWidget(self.spin_strikewin, 2, 1)
        val_grid.addWidget(self._label("Decode Timeout"), 3, 0)
        val_grid.addWidget(self.spin_decodeto, 3, 1)
        val_grid.addWidget(self._label("History N"), 4, 0)
        val_grid.addWidget(self.spin_hist, 4, 1)
        root.addWidget(val_box)

        # 3. TRACKING (association + loss, §7.1).
        trk_box, trk_grid = self._make_group("TRACKING — association & loss")
        self.spin_gate = _dspin(1.0, 200.0, 1.0, suffix=" px", decimals=1,
            tooltip="Max jump from last centroid to associate")
        self.spin_losses = _ispin(1, 50, "Consecutive misses before track loss")
        self.spin_nodet = _dspin(0.05, 2.0, 0.01, suffix=" s", decimals=3,
            tooltip="Time-based loss threshold")
        trk_grid.addWidget(self._label("Associate Gate"), 0, 0)
        trk_grid.addWidget(self.spin_gate, 0, 1)
        trk_grid.addWidget(self._label("Loss After Misses"), 1, 0)
        trk_grid.addWidget(self.spin_losses, 1, 1)
        trk_grid.addWidget(self._label("Max No-Detection Time"), 2, 0)
        trk_grid.addWidget(self.spin_nodet, 2, 1)
        root.addWidget(trk_box)

        # 4. MOTION MODEL (α-β filter, §7.3).
        mot_box, mot_grid = self._make_group("MOTION MODEL — α-β filter")
        self.spin_alpha = _dspin(0.0, 1.0, 0.01, tooltip="Position gain α")
        self.spin_beta = _dspin(0.0, 1.0, 0.01, tooltip="Velocity gain β")
        self.spin_growth = _dspin(0.0, 20.0, 0.1, suffix=" px", decimals=1,
            tooltip="Uncertainty growth per coasted frame")
        self.spin_cap = _dspin(1.0, 100.0, 1.0, suffix=" px", decimals=1,
            tooltip="Uncertainty cap (prediction search cap)")
        mot_grid.addWidget(self._label("Alpha"), 0, 0)
        mot_grid.addWidget(self.spin_alpha, 0, 1)
        mot_grid.addWidget(self._label("Beta"), 1, 0)
        mot_grid.addWidget(self.spin_beta, 1, 1)
        mot_grid.addWidget(self._label("Uncertainty Growth"), 2, 0)
        mot_grid.addWidget(self.spin_growth, 2, 1)
        mot_grid.addWidget(self._label("Uncertainty Cap"), 3, 0)
        mot_grid.addWidget(self.spin_cap, 3, 1)
        root.addWidget(mot_box)

        # 5. SCAN (schedule, §4).
        scn_box, scn_grid = self._make_group("SCAN — search schedule")
        self.spin_dwell = _ispin(1, 30, "Frames per cell for photometry")
        self.spin_decdwell = _ispin(1, 30, "Extended dwell on decoding candidate")
        self.combo_pattern = QComboBox()
        self.combo_pattern.addItems(["RASTER", "SPIRAL", "SECTOR"])
        self.combo_pattern.setToolTip("Systematic sweep order (§4.2)")
        scn_grid.addWidget(self._label("Dwell Frames"), 0, 0)
        scn_grid.addWidget(self.spin_dwell, 0, 1)
        scn_grid.addWidget(self._label("Decoding Dwell"), 1, 0)
        scn_grid.addWidget(self.spin_decdwell, 1, 1)
        scn_grid.addWidget(self._label("Pattern"), 2, 0)
        scn_grid.addWidget(self.combo_pattern, 2, 1)
        scn_grid.addWidget(
            self._hint("Scan start cell lives under Camera & PTZ → Starting Positions."),
            3, 0, 1, 2,
        )
        root.addWidget(scn_box)

        # 6. RE-ACQUISITION (escalation ladder, §8).
        rea_box, rea_grid = self._make_group("RE-ACQUISITION — escalation ladder")
        self.spin_initr = _dspin(10.0, 500.0, 5.0, suffix=" px", decimals=0,
            tooltip="Initial search radius around prediction")
        self.spin_stepr = _dspin(1.0, 200.0, 1.0, suffix=" px", decimals=0,
            tooltip="Radius growth per frame")
        self.spin_maxr = _dspin(50.0, 1500.0, 10.0, suffix=" px", decimals=0,
            tooltip="Radius cap before standby-pool escalation")
        self.spin_conftime = _dspin(0.1, 5.0, 0.01, suffix=" s", decimals=3,
            tooltip="Provisional-confirm watchdog (2 beacon periods)")
        self.spin_maxstandby = _ispin(1, 10, "Standby candidates tried before priority scan")
        rea_grid.addWidget(self._label("Initial Radius"), 0, 0)
        rea_grid.addWidget(self.spin_initr, 0, 1)
        rea_grid.addWidget(self._label("Radius Step"), 1, 0)
        rea_grid.addWidget(self.spin_stepr, 1, 1)
        rea_grid.addWidget(self._label("Max Radius"), 2, 0)
        rea_grid.addWidget(self.spin_maxr, 2, 1)
        rea_grid.addWidget(self._label("Confirm Timeout"), 3, 0)
        rea_grid.addWidget(self.spin_conftime, 3, 1)
        rea_grid.addWidget(self._label("Max Standby Attempts"), 4, 0)
        rea_grid.addWidget(self.spin_maxstandby, 4, 1)
        root.addWidget(rea_box)

        # 7. AUTONOMY SUPERVISOR + STANDBY POOL (§6, §9).
        sup_box, sup_grid = self._make_group("AUTONOMY — supervisor & standby")
        self.spin_maxreset = _ispin(1, 10, "Full resets allowed per window")
        self.spin_resetwin = _dspin(10.0, 3600.0, 10.0, suffix=" s", decimals=0,
            tooltip="Reset rate-limit window")
        self.spin_watchdog = _dspin(0.1, 5.0, 0.01, suffix=" s", decimals=3,
            tooltip="Decoding watchdog (2 beacon periods)")
        self.spin_recheck = _ispin(1, 300, "Frames between in-track signature re-checks")
        self.spin_sb_age = _dspin(1.0, 120.0, 1.0, suffix=" s", decimals=0,
            tooltip="Standby candidate retention")
        self.spin_sb_size = _ispin(1, 64, "Standby pool cap (best-by-score kept)")
        sup_grid.addWidget(self._label("Max Resets / Window"), 0, 0)
        sup_grid.addWidget(self.spin_maxreset, 0, 1)
        sup_grid.addWidget(self._label("Reset Window"), 1, 0)
        sup_grid.addWidget(self.spin_resetwin, 1, 1)
        sup_grid.addWidget(self._label("Decoding Watchdog"), 2, 0)
        sup_grid.addWidget(self.spin_watchdog, 2, 1)
        sup_grid.addWidget(self._label("In-Track Recheck"), 3, 0)
        sup_grid.addWidget(self.spin_recheck, 3, 1)
        sup_grid.addWidget(self._label("Standby Max Age"), 4, 0)
        sup_grid.addWidget(self.spin_sb_age, 4, 1)
        sup_grid.addWidget(self._label("Standby Max Size"), 5, 0)
        sup_grid.addWidget(self.spin_sb_size, 5, 1)
        root.addWidget(sup_box)
        root.addStretch(1)

        for w in self._watched_widgets():
            if isinstance(w, QComboBox):
                w.currentIndexChanged.connect(self._on_changed)
            else:
                try:
                    w.valueChanged.connect(self._on_changed)
                except AttributeError:
                    pass

    def _watched_widgets(self):
        return [
            self.spin_peak, self.spin_sigma, self.spin_r2, self.spin_snr,
            self.spin_isolation, self.spin_bg, self.spin_maxcand,
            self.spin_score, self.spin_strikes, self.spin_strikewin,
            self.spin_decodeto, self.spin_hist,
            self.spin_gate, self.spin_losses, self.spin_nodet,
            self.spin_alpha, self.spin_beta, self.spin_growth, self.spin_cap,
            self.spin_dwell, self.spin_decdwell, self.combo_pattern,
            self.spin_initr, self.spin_stepr, self.spin_maxr,
            self.spin_conftime, self.spin_maxstandby,
            self.spin_maxreset, self.spin_resetwin, self.spin_watchdog,
            self.spin_recheck, self.spin_sb_age, self.spin_sb_size,
        ]

    # -- config ------------------------------------------------------
    def collect_config(self) -> LocalTerminalConfig:
        from local_terminal.detector import DetectorConfig
        from local_terminal.motion import AlphaBetaConfig
        from local_terminal.reacquisition import ReacquisitionConfig
        from local_terminal.scan import ScanConfig
        from local_terminal.supervisor import SupervisorConfig
        from local_terminal.tracker import TrackerConfig
        from local_terminal.validator import ValidationConfig

        cfg = LocalTerminalConfig(
            detector=DetectorConfig(
                peak_min=float(self.spin_peak.value()),
                sigma_min_px=float(self.spin_sigma.value()),
                r2_min=float(self.spin_r2.value()),
                snr_min_db=float(self.spin_snr.value()),
                isolation_px=float(self.spin_isolation.value()),
                bg_annulus_px=int(self.spin_bg.value()),
                max_candidates=int(self.spin_maxcand.value()),
            ),
            tracker=TrackerConfig(
                associate_gate_px=float(self.spin_gate.value()),
                loss_after_misses=int(self.spin_losses.value()),
                max_no_detection_time_s=float(self.spin_nodet.value()),
            ),
            motion=AlphaBetaConfig(
                alpha=float(self.spin_alpha.value()),
                beta=float(self.spin_beta.value()),
                uncertainty_growth_px=float(self.spin_growth.value()),
                uncertainty_cap_px=float(self.spin_cap.value()),
            ),
            validation=ValidationConfig(
                score_min=float(self.spin_score.value()),
                strikes_to_blacklist=int(self.spin_strikes.value()),
                strike_window_s=float(self.spin_strikewin.value()),
                decode_timeout_s=float(self.spin_decodeto.value()),
                history_n=int(self.spin_hist.value()),
            ),
            scan=ScanConfig(
                default_dwell_frames=int(self.spin_dwell.value()),
                decoding_dwell_frames=int(self.spin_decdwell.value()),
                pattern=str(self.combo_pattern.currentText()),
            ),
            reacquisition=ReacquisitionConfig(
                initial_radius_px=float(self.spin_initr.value()),
                radius_step_px=float(self.spin_stepr.value()),
                max_radius_px=float(self.spin_maxr.value()),
                confirm_timeout_s=float(self.spin_conftime.value()),
                max_standby_attempts=int(self.spin_maxstandby.value()),
            ),
            supervisor=SupervisorConfig(
                max_resets_per_window=int(self.spin_maxreset.value()),
                reset_window_s=float(self.spin_resetwin.value()),
                decoding_watchdog_s=float(self.spin_watchdog.value()),
                in_track_recheck_interval=int(self.spin_recheck.value()),
            ),
            standby_max_age_s=float(self.spin_sb_age.value()),
            standby_max_size=int(self.spin_sb_size.value()),
        )
        return cfg.validate()

    def set_config(self, cfg: LocalTerminalConfig, emit: bool = False) -> None:
        cfg = cfg.validate()
        self._config = copy.deepcopy(cfg)
        self._updating = True
        try:
            for w in self._watched_widgets():
                w.blockSignals(True)
            d = cfg.detector
            self.spin_peak.setValue(float(d.peak_min))
            self.spin_sigma.setValue(float(d.sigma_min_px))
            self.spin_r2.setValue(float(d.r2_min))
            self.spin_snr.setValue(float(d.snr_min_db))
            self.spin_isolation.setValue(float(d.isolation_px))
            self.spin_bg.setValue(int(d.bg_annulus_px))
            self.spin_maxcand.setValue(int(d.max_candidates))
            v = cfg.validation
            self.spin_score.setValue(float(v.score_min))
            self.spin_strikes.setValue(int(v.strikes_to_blacklist))
            self.spin_strikewin.setValue(float(v.strike_window_s))
            self.spin_decodeto.setValue(float(v.decode_timeout_s))
            self.spin_hist.setValue(int(v.history_n))
            t = cfg.tracker
            self.spin_gate.setValue(float(t.associate_gate_px))
            self.spin_losses.setValue(int(t.loss_after_misses))
            self.spin_nodet.setValue(float(t.max_no_detection_time_s))
            m = cfg.motion
            self.spin_alpha.setValue(float(m.alpha))
            self.spin_beta.setValue(float(m.beta))
            self.spin_growth.setValue(float(m.uncertainty_growth_px))
            self.spin_cap.setValue(float(m.uncertainty_cap_px))
            s = cfg.scan
            self.spin_dwell.setValue(int(s.default_dwell_frames))
            self.spin_decdwell.setValue(int(s.decoding_dwell_frames))
            idx = self.combo_pattern.findText(str(s.pattern).upper())
            self.combo_pattern.setCurrentIndex(max(0, idx))
            r = cfg.reacquisition
            self.spin_initr.setValue(float(r.initial_radius_px))
            self.spin_stepr.setValue(float(r.radius_step_px))
            self.spin_maxr.setValue(float(r.max_radius_px))
            self.spin_conftime.setValue(float(r.confirm_timeout_s))
            self.spin_maxstandby.setValue(int(r.max_standby_attempts))
            sup = cfg.supervisor
            self.spin_maxreset.setValue(int(sup.max_resets_per_window))
            self.spin_resetwin.setValue(float(sup.reset_window_s))
            self.spin_watchdog.setValue(float(sup.decoding_watchdog_s))
            self.spin_recheck.setValue(int(sup.in_track_recheck_interval))
            self.spin_sb_age.setValue(float(cfg.standby_max_age_s))
            self.spin_sb_size.setValue(int(cfg.standby_max_size))
        finally:
            for w in self._watched_widgets():
                w.blockSignals(False)
            self._updating = False
        if emit:
            self._emit_config()

    def reset_to_defaults(self) -> None:
        self.set_config(make_default_local_terminal(), emit=True)

    # -- internals ---------------------------------------------------
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

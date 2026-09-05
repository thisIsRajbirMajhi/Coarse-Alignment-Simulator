# gui/panels/tuning_panel.py - Detection & Tracking tuning — all detector/tracker params
from PyQt5.QtCore import pyqtSignal
from PyQt5.QtWidgets import QDoubleSpinBox, QGridLayout, QGroupBox, QLabel, QSpinBox, QVBoxLayout

from detection.config import DetectorConfig
from detection.constants import DETECTOR_LIMITS
from gui.panels.base import BaseConfigPanel
from tracking.config import TrackerConfig
from tracking.constants import TRACKER_LIMITS


class TuningPanel(BaseConfigPanel):
    """
    Detection + Tracking tab — exposes all tuning params for coarse alignment.

    Groups:
      A Detection: brightness_threshold, min_area, max_beacons
      B Tracking: smoothing, miss_limit, acquire_hits, lost_grace_mult
    Signals:
      detectorChanged(DetectorConfig) | trackerChanged(TrackerConfig)
    """
    detectorChanged = pyqtSignal(object)
    trackerChanged = pyqtSignal(object)
    configChanged = pyqtSignal(object)  # legacy combined

    def __init__(self, detector: DetectorConfig | None = None, tracker: TrackerConfig | None = None, parent=None):
        super().__init__(parent)
        self._det = (detector or DetectorConfig()).validate()
        self._trk = (tracker or TrackerConfig()).validate()
        self._build_ui()
        self.set_configs(self._det, self._trk, emit=False)

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(10)

        # A — Detection
        det_box = QGroupBox("Detection — Thresholding & Contours")
        det_grid = QGridLayout(det_box)
        det_grid.setContentsMargins(12, 18, 12, 12)
        det_grid.setHorizontalSpacing(8)
        det_grid.setVerticalSpacing(8)
        det_grid.setColumnStretch(1, 1)
        det_grid.setColumnStretch(3, 1)

        det_grid.addWidget(self._label("Threshold"), 0, 0)
        self.thresh_spin = QSpinBox()
        lo, hi = DETECTOR_LIMITS["brightness_threshold"]
        self.thresh_spin.setRange(lo, hi)
        self.thresh_spin.setSuffix("")
        self.thresh_spin.setToolTip("Brightness T 0-255 — mask = (gray > T) ? 255 : 0. Higher = stricter, fewer false positives from stars/noise.")
        self.thresh_spin.setMinimumHeight(26)
        det_grid.addWidget(self.thresh_spin, 0, 1)

        det_grid.addWidget(self._label("Min Area"), 0, 2)
        self.min_area_spin = QSpinBox()
        lo, hi = DETECTOR_LIMITS["min_area"]
        self.min_area_spin.setRange(lo, hi)
        self.min_area_spin.setSuffix(" px²")
        self.min_area_spin.setToolTip("Min contour area px² — rejects single-pixel S&P noise.")
        self.min_area_spin.setMinimumHeight(26)
        det_grid.addWidget(self.min_area_spin, 0, 3)

        det_grid.addWidget(self._label("Max Beacons"), 1, 0)
        self.max_beacons_spin = QSpinBox()
        lo, hi = DETECTOR_LIMITS["max_beacons"]
        self.max_beacons_spin.setRange(lo, hi)
        self.max_beacons_spin.setToolTip("Cap detections per frame (sorted by confidence area*peak).")
        self.max_beacons_spin.setMinimumHeight(26)
        det_grid.addWidget(self.max_beacons_spin, 1, 1)

        det_hint = QLabel("Threshold 200 ≈ 78% brightness. Lower to 160 for fog/low-light, higher to 220 for noisy stars.")
        det_hint.setWordWrap(True)
        det_hint.setStyleSheet("color:#64748b; font-size:10px; font-style:italic;")
        det_grid.addWidget(det_hint, 2, 0, 1, 4)
        layout.addWidget(det_box)

        # B — Tracking
        trk_box = QGroupBox("Tracking — Smoothing & Lock State Machine")
        trk_grid = QGridLayout(trk_box)
        trk_grid.setContentsMargins(12, 18, 12, 12)
        trk_grid.setHorizontalSpacing(8)
        trk_grid.setVerticalSpacing(8)
        trk_grid.setColumnStretch(1, 1)
        trk_grid.setColumnStretch(3, 1)

        trk_grid.addWidget(self._label("Smoothing α"), 0, 0)
        self.smoothing_spin = QDoubleSpinBox()
        lo, hi = TRACKER_LIMITS["smoothing"]
        self.smoothing_spin.setRange(lo, hi)
        self.smoothing_spin.setSingleStep(0.05)
        self.smoothing_spin.setDecimals(2)
        self.smoothing_spin.setToolTip("Exponential α 0..0.95 — y=α·y_prev+(1-α)·x. 0=snap, 0.25 default, 0.6 heavy.")
        self.smoothing_spin.setMinimumHeight(26)
        trk_grid.addWidget(self.smoothing_spin, 0, 1)

        trk_grid.addWidget(self._label("Miss Limit"), 0, 2)
        self.miss_spin = QSpinBox()
        lo, hi = TRACKER_LIMITS["miss_limit"]
        self.miss_spin.setRange(int(lo), int(hi))
        self.miss_spin.setSuffix(" fr")
        self.miss_spin.setToolTip("Consecutive misses before ACQUIRED/TRACKING→LOST. Sr.18 <5% loss needs 5-8.")
        self.miss_spin.setMinimumHeight(26)
        trk_grid.addWidget(self.miss_spin, 0, 3)

        trk_grid.addWidget(self._label("Acquire Hits"), 1, 0)
        self.acquire_spin = QSpinBox()
        lo, hi = TRACKER_LIMITS["acquire_hits"]
        self.acquire_spin.setRange(int(lo), int(hi))
        self.acquire_spin.setSuffix(" hits")
        self.acquire_spin.setToolTip("Hits to confirm TRACKING from ACQUIRED. Spec 3.")
        self.acquire_spin.setMinimumHeight(26)
        trk_grid.addWidget(self.acquire_spin, 1, 1)

        trk_grid.addWidget(self._label("Lost Grace"), 1, 2)
        self.grace_spin = QDoubleSpinBox()
        lo, hi = TRACKER_LIMITS["lost_grace_mult"]
        self.grace_spin.setRange(lo, hi)
        self.grace_spin.setSingleStep(0.1)
        self.grace_spin.setDecimals(1)
        self.grace_spin.setSuffix(" ×")
        self.grace_spin.setToolTip("LOST→SEARCHING after miss_limit * grace. 2.0 = 10 misses if miss_limit 5.")
        self.grace_spin.setMinimumHeight(26)
        trk_grid.addWidget(self.grace_spin, 1, 3)

        trk_hint = QLabel("Tune: smoothing 0.25 for random, 0.45 for noisy fog. Miss 5 balances <5% loss vs false reacq.")
        trk_hint.setWordWrap(True)
        trk_hint.setStyleSheet("color:#64748b; font-size:10px; font-style:italic;")
        trk_grid.addWidget(trk_hint, 2, 0, 1, 4)
        layout.addWidget(trk_box)
        layout.addStretch()

        # Wire
        self.thresh_spin.valueChanged.connect(self._emit_detector)
        self.min_area_spin.valueChanged.connect(self._emit_detector)
        self.max_beacons_spin.valueChanged.connect(self._emit_detector)
        self.smoothing_spin.valueChanged.connect(self._emit_tracker)
        self.miss_spin.valueChanged.connect(self._emit_tracker)
        self.acquire_spin.valueChanged.connect(self._emit_tracker)
        self.grace_spin.valueChanged.connect(self._emit_tracker)

    def _emit_detector(self):
        try:
            cfg = self.collect_detector()
            self.detectorChanged.emit(cfg)
            self.configChanged.emit(cfg)
        except Exception: pass

    def _emit_tracker(self):
        try:
            cfg = self.collect_tracker()
            self.trackerChanged.emit(cfg)
            self.configChanged.emit(cfg)
        except Exception: pass

    def collect_detector(self) -> DetectorConfig:
        return DetectorConfig(
            brightness_threshold=int(self.thresh_spin.value()),
            min_area=int(self.min_area_spin.value()),
            max_beacons=int(self.max_beacons_spin.value()),
        ).validate()

    def collect_tracker(self) -> TrackerConfig:
        return TrackerConfig(
            smoothing=float(self.smoothing_spin.value()),
            miss_limit=int(self.miss_spin.value()),
            acquire_hits=int(self.acquire_spin.value()),
            lost_grace_mult=float(self.grace_spin.value()),
        ).validate()

    def set_configs(self, det: DetectorConfig, trk: TrackerConfig, emit: bool = False):
        det = det.validate(); trk = trk.validate()
        widgets = [self.thresh_spin, self.min_area_spin, self.max_beacons_spin, self.smoothing_spin, self.miss_spin, self.acquire_spin, self.grace_spin]
        for w in widgets: w.blockSignals(True)
        try:
            self.thresh_spin.setValue(int(det.brightness_threshold))
            self.min_area_spin.setValue(int(det.min_area))
            self.max_beacons_spin.setValue(int(det.max_beacons))
            self.smoothing_spin.setValue(float(trk.smoothing))
            self.miss_spin.setValue(int(trk.miss_limit))
            self.acquire_spin.setValue(int(trk.acquire_hits))
            self.grace_spin.setValue(float(trk.lost_grace_mult))
        finally:
            for w in widgets: w.blockSignals(False)
        if emit:
            self._emit_detector(); self._emit_tracker()

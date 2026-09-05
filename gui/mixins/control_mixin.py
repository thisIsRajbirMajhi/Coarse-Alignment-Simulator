# gui/mixins/control_mixin.py - Global / Control / Tuning / Disturbance handlers
# Extracted from gui/main_window.py controller handlers (200+ lines).

import math  # noqa
import numpy as np
from PyQt5.QtWidgets import QMessageBox  # noqa
from target.motion import MotionProfile  # noqa
from control.config import ControllerConfig  # noqa
from beacon_tracker.detection.detector import BeaconDetector  # noqa
from tracking.tracker import Tracker  # noqa


class ControlMixin:
    """Mixin: Motion, speed, threshold, tracker/detector tuning, control/disturbance sync."""

    def _on_motion_change(self, value: str):
        try:
            prof = MotionProfile(value)
            # Apply to primary always; if multiple beacons, optionally apply to all for uniform test
            # Keep varied beacons realistic: only primary follows combo, others keep their random profiles
            # Uncomment next two lines to force all:
            # for b in getattr(self, "beacons", []):
            #     b.profile = prof
            self.target.profile = prof
        except: pass

    def _on_speed_change(self, value: int):
        self._target_speed = int(value)
        if hasattr(self, "target"): self.target.speed = float(value)
        for b in getattr(self, "beacons", []):
            # keep relative speed ratios but scale primary exactly
            if b is getattr(self, "target", None):
                b.speed = float(value)
            else:
                # scale proportionally to keep diversity
                b.speed = float(np.clip(float(value) * (0.85 + 0.30*(b.beacon_id % 3)/2), 12, 180))

    def _on_thresh_change(self, value: int):
        self._det_thresh = int(value)
        if hasattr(self, "detector"): self.detector.brightness_threshold = int(value)

    def _on_tracker_smoothing_change(self, value: float):
        self._tracker_smoothing = float(value)
        if hasattr(self, "tracker"): self.tracker.smoothing = float(value)

    def _on_tracker_miss_change(self, value: int):
        self._tracker_miss_limit = int(value)
        if hasattr(self, "tracker"): self.tracker.miss_limit = int(value)

    def _on_detector_min_area_change(self, value: int):
        self._detector_min_area = int(value)
        if hasattr(self, "detector"): self.detector.min_area = int(value)

    def _on_detector_tuning_changed(self, cfg):
        try:
            cfg = cfg.validate() if hasattr(cfg, "validate") else cfg
            self._det_thresh = int(getattr(cfg, "brightness_threshold", 200))
            self._detector_min_area = int(getattr(cfg, "min_area", 2))
            if hasattr(self, "detector"):
                self.detector.brightness_threshold = int(cfg.brightness_threshold)
                self.detector.min_area = int(cfg.min_area)
                try: self.detector.max_beacons = int(cfg.max_beacons)
                except: pass
            # Keep beacon_manager thresh in sync
            try:
                if hasattr(self, "beacon_manager"):
                    self.beacon_manager.spin_thresh.blockSignals(True)
                    self.beacon_manager.spin_thresh.setValue(int(cfg.brightness_threshold))
                    self.beacon_manager.spin_thresh.blockSignals(False)
            except: pass
            self._mark_dirty("tuning")
            self._schedule_auto("tuning", lambda: self._clear_dirty("tuning"), 300)
        except Exception: pass

    def _on_tracker_tuning_changed(self, cfg):
        try:
            cfg = cfg.validate() if hasattr(cfg, "validate") else cfg
            self._tracker_smoothing = float(getattr(cfg, "smoothing", 0.25))
            self._tracker_miss_limit = int(getattr(cfg, "miss_limit", 5))
            if hasattr(self, "tracker"):
                # Apply without full rebuild for immediate response
                self.tracker.smoothing = float(cfg.smoothing)
                self.tracker.miss_limit = int(cfg.miss_limit)
                try:
                    self.tracker.acquire_hits = int(cfg.acquire_hits)
                    self.tracker.lost_grace_mult = float(cfg.lost_grace_mult)
                except: pass
            self._mark_dirty("tuning")
            self._schedule_auto("tuning", lambda: self._clear_dirty("tuning"), 300)
        except Exception: pass

    def _on_sim_speed_change(self, value: float):
        self._sim_speed = float(value)

    def _on_global_brightness_change(self, value: int):
        self._global_brightness = int(value)
        for b in getattr(self, "beacons", []):
            b.brightness = int(value)
            b.current_brightness = float(value)

    def _on_global_radius_change(self, value: int):
        self._global_radius = int(value)
        for b in getattr(self, "beacons", []):
            b.radius = int(value)

    def _apply_global_tuning(self):
        # Recreate tracker/detector with new params (live values already applied, this ensures fresh state)
        try:
            smoothing = float(self.tracker_smoothing_spin.value())
            miss = int(self.tracker_miss_spin.value())
            min_area = int(self.detector_min_area_spin.value())
            thresh = int(self.thresh_slider.value()) if hasattr(self, "thresh_slider") else int(self._det_thresh)
            self._tracker_smoothing = smoothing; self._tracker_miss_limit = miss
            self._detector_min_area = min_area
            self.tracker = Tracker(smoothing=smoothing, miss_limit=miss)
            self.detector = BeaconDetector(brightness_threshold=thresh, min_area=min_area)
            self.statusBar().showMessage(f"Global tuning applied — tracker smooth {smoothing:.2f} miss {miss} minArea {min_area}", 3000)
        except Exception as e:
            QMessageBox.warning(self, "Global Tuning", f"Failed: {e}")

    def _on_gain_change_spin(self, value: float):
        self._ctrl_gain = float(value)
        if hasattr(self, "controller"): self.controller.gain = float(value)
        iv = int(round(value*100))
        if self.gain_slider.value() != iv:
            self.gain_slider.blockSignals(True); self.gain_slider.setValue(iv); self.gain_slider.blockSignals(False)

    def _on_gain_change_slider(self, value: int):
        f = value/100.0
        if abs(self.gain_spin.value()-f) > 1e-9:
            self.gain_spin.blockSignals(True); self.gain_spin.setValue(f); self.gain_spin.blockSignals(False)
        self._ctrl_gain = f
        if hasattr(self, "controller"): self.controller.gain = f

    def _on_control_config_changed(self, cfg):
        """ handler — ControlPanel emitted validated ControllerConfig."""
        try:
            cfg = cfg.validate()
            self.controller_config = cfg
            # Apply to live controller without rebuild
            if hasattr(self, "controller"):
                self.controller.apply_config(cfg)
        except Exception:
            pass
        self._mark_dirty("control")
        self._schedule_auto("control", self._apply_control_hot, 80)

    def _apply_control_hot(self):
        """Apply controller config — , validates, syncs gain alias, snapss."""
        try:
            if hasattr(self, "control_panel"):
                cfg = self.control_panel.collect_config().validate()
                self.controller_config = cfg
            else:
                cfg = self.controller_config.validate()
            self.controller.apply_config(cfg)
            # Sync camera gain alias (bidirectional, but avoid loop)
            try:
                if hasattr(self, "camera_panel"):
                    self.camera_panel.gain_spin.blockSignals(True)
                    self.camera_panel.gain_spin.setValue(float(np.clip(cfg.kp, 0.02, 0.50)))
                    self.camera_panel.gain_slider.blockSignals(True)
                    self.camera_panel.gain_slider.setValue(int(round(float(cfg.kp)*100)))
                    self.camera_panel.gain_spin.blockSignals(False)
                    self.camera_panel.gain_slider.blockSignals(False)
            except: pass
            self._clear_dirty("control")
            self._snapshot_section("control")
            self.statusBar().showMessage(f"Control — {cfg.controller_type} Kp {cfg.kp:.3f} Ki {cfg.ki:.3f} Kd {cfg.kd:.3f} dead {cfg.dead_zone:.1f}px clamp {cfg.output_clamp:.0f}px rate {cfg.update_rate_hz:.0f}Hz", 2000)
        except Exception as e:
            QMessageBox.warning(self, "Control", f"Failed: {e}")

    def _sync_control_gain_to_camera(self, v: float) -> None:
        # Control Kp → Camera gain alias (no loop)
        try:
            if hasattr(self, "camera_panel"):
                self.camera_panel.gain_spin.blockSignals(True)
                self.camera_panel.gain_spin.setValue(float(np.clip(float(v), 0.02, 0.50)))
                self.camera_panel.gain_slider.blockSignals(True)
                self.camera_panel.gain_slider.setValue(int(round(float(v)*100)))
                self.camera_panel.gain_spin.blockSignals(False)
                self.camera_panel.gain_slider.blockSignals(False)
        except: pass

    def _sync_camera_gain_to_control(self, v: float) -> None:
        # Camera gain → Control Kp
        try:
            if hasattr(self, "control_panel"):
                self.control_panel.kp_spin.blockSignals(True)
                self.control_panel.kp_spin.setValue(float(v))
                self.control_panel.kp_spin.blockSignals(False)
                # Also sync gain alias
                self.control_panel.gain_spin.blockSignals(True)
                self.control_panel.gain_spin.setValue(float(np.clip(float(v), 0.02, 0.50)))
                self.control_panel.gain_spin.blockSignals(False)
                # Update controller directly for immediate response
                if hasattr(self, "controller"):
                    self.controller.config.kp = float(v)
        except: pass
        # Mark dirty for 
        self._mark_dirty("control")
        self._schedule_auto("control", self._apply_control_hot, 80)

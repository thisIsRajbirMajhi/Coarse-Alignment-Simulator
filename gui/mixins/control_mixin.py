# gui/mixins/control_mixin.py - Global / Control handlers (beacon_tracker removed)

import numpy as np
from PyQt5.QtWidgets import QMessageBox
from target.motion import MotionProfile


class ControlMixin:
    """Mixin: Motion, speed, control/disturbance sync (no beacon_tracker)."""

    def _on_motion_change(self, value: str):
        try:
            prof = MotionProfile(value)
            self.target.profile = prof
        except Exception: pass

    def _on_speed_change(self, value: int):
        self._target_speed = int(value)
        if hasattr(self, "target"): self.target.speed = float(value)
        for b in getattr(self, "beacons", []):
            if b is getattr(self, "target", None):
                b.speed = float(value)
            else:
                b.speed = float(np.clip(float(value) * (0.85 + 0.30*(b.beacon_id % 3)/2), 12, 180))

    def _apply_global_tuning(self):
        # No detector tuning (beacon_tracker removed) — only global beacon/cam params
        try:
            self.statusBar().showMessage("Global tuning applied", 2000)
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
        try:
            cfg = cfg.validate()
            self.controller_config = cfg
            if hasattr(self, "controller"):
                self.controller.apply_config(cfg)
        except Exception:
            pass
        self._mark_dirty("control")
        self._schedule_auto("control", self._apply_control_hot, 80)

    def _apply_control_hot(self):
        try:
            if hasattr(self, "control_panel"):
                cfg = self.control_panel.collect_config().validate()
                self.controller_config = cfg
            else:
                cfg = self.controller_config.validate()
            self.controller.apply_config(cfg)
            try:
                if hasattr(self, "camera_panel"):
                    self.camera_panel.gain_spin.blockSignals(True)
                    self.camera_panel.gain_spin.setValue(float(np.clip(cfg.kp, 0.02, 0.50)))
                    self.camera_panel.gain_slider.blockSignals(True)
                    self.camera_panel.gain_slider.setValue(int(round(float(cfg.kp)*100)))
                    self.camera_panel.gain_spin.blockSignals(False)
                    self.camera_panel.gain_slider.blockSignals(False)
            except Exception: pass
            self._clear_dirty("control")
            self._snapshot_section("control")
            self.statusBar().showMessage(f"Control — {cfg.controller_type} Kp {cfg.kp:.3f} Ki {cfg.ki:.3f} Kd {cfg.kd:.3f} dead {cfg.dead_zone:.1f}px clamp {cfg.output_clamp:.0f}px rate {cfg.update_rate_hz:.0f}Hz", 2000)
        except Exception as e:
            QMessageBox.warning(self, "Control", f"Failed: {e}")

    def _sync_control_gain_to_camera(self, v: float) -> None:
        try:
            if hasattr(self, "camera_panel"):
                self.camera_panel.gain_spin.blockSignals(True)
                self.camera_panel.gain_spin.setValue(float(np.clip(float(v), 0.02, 0.50)))
                self.camera_panel.gain_slider.blockSignals(True)
                self.camera_panel.gain_slider.setValue(int(round(float(v)*100)))
                self.camera_panel.gain_spin.blockSignals(False)
                self.camera_panel.gain_slider.blockSignals(False)
        except Exception: pass

    def _sync_camera_gain_to_control(self, v: float) -> None:
        try:
            if hasattr(self, "control_panel"):
                self.control_panel.kp_spin.blockSignals(True)
                self.control_panel.kp_spin.setValue(float(v))
                self.control_panel.kp_spin.blockSignals(False)
                self.control_panel.gain_spin.blockSignals(True)
                self.control_panel.gain_spin.setValue(float(np.clip(float(v), 0.02, 0.50)))
                self.control_panel.gain_spin.blockSignals(False)
                if hasattr(self, "controller"):
                    self.controller.config.kp = float(v)
        except Exception: pass
        self._mark_dirty("control")
        self._schedule_auto("control", self._apply_control_hot, 80)

# gui/mixins/beacon_mixin.py - Beacon/target handling
# Tracking removed: no tracker recreation on beacon change.

import time
import numpy as np
from target.motion import MotionProfile, create_beacons


class BeaconMixin:
    """Mixin: Beacon count/target logic, randomization, hot-apply."""

    def _update_beacon_count_label(self, v: int):
        try:
            tgt = int(getattr(self, "target_beacon_spin", self).value()) if hasattr(self, "target_beacon_spin") else int(getattr(self, "_target_beacon_id", 0))
            self.beacon_count_label.setText(f"{v} beacon{'s' if v!=1 else ''}, Target #{tgt}")
        except Exception:
            try: self.beacon_count_label.setText(f"{v} beacon{'s' if v!=1 else ''}")
            except Exception: pass

    def _on_beacon_count_changed(self, v: int):
        try:
            self.target_beacon_spin.setMaximum(max(0, v - 1))
            if self.target_beacon_spin.value() >= v:
                self.target_beacon_spin.setValue(v - 1)
            self._update_beacon_count_label(v)
        except Exception: pass

    def _on_target_beacon_change(self, idx: int):
        try:
            idx = int(np.clip(int(idx), 0, max(0, len(getattr(self, "beacons", [])) - 1)))
            self._target_beacon_id = idx
            try:
                self.beacon_config.target_index = int(idx)
                if hasattr(self, "beacon_manager"):
                    self.beacon_manager.spin_target_index.blockSignals(True)
                    self.beacon_manager.spin_target_index.setValue(int(idx))
                    self.beacon_manager.spin_target_index.blockSignals(False)
            except Exception:
                pass
            if hasattr(self, "beacons") and 0 <= idx < len(self.beacons):
                self.target = self.beacons[idx]
                self.statusBar().showMessage(f"Target -> Beacon #{idx}", 2500)
                try:
                    if hasattr(self, "beacon_manager"):
                        self.beacon_manager._update_status()
                except Exception: pass
        except Exception: pass

    def _on_multi_beacon_config_changed(self, cfg):
        try:
            cfg = cfg.validate() if hasattr(cfg, "validate") else cfg
            self.beacon_config = cfg
            self._beacon_count = int(cfg.beacon_count)
            self._target_beacon_id = int(cfg.target_index)
            self._mark_dirty("beacons")
            self._schedule_auto("beacons", self._apply_beacons_hot, 400)
            try:
                self._schedule_auto("beacons_highlight", lambda: self._on_target_beacon_change(int(cfg.target_index)), 80)
            except Exception: pass
        except Exception:
            try: self._schedule_auto("beacons", self._apply_beacons_hot, 400)
            except Exception: pass

    def _sync_beacon_to_global(self, cfg):
        try:
            cfg = cfg.validate() if hasattr(cfg, "validate") else cfg
            rev = {"linear": "linear", "curved": "curved", "figure_eight": "figure_eight", "spiral": "spiral", "sinusoidal": "sinusoidal", "zigzag": "zigzag", "random": "curved"}
            prof = rev.get(str(getattr(cfg, "profile", "curved")).lower(), "curved")
            if hasattr(self, "motion_combo"):
                self.motion_combo.blockSignals(True)
                idx = self.motion_combo.findText(prof)
                if idx >= 0:
                    self.motion_combo.setCurrentIndex(idx)
                else:
                    self.motion_combo.setCurrentText(prof)
                self.motion_combo.blockSignals(False)
            if hasattr(self, "speed_slider"):
                self.speed_slider.blockSignals(True)
                self.speed_slider.setValue(int(getattr(cfg, "speed", 60)))
                if hasattr(self.speed_slider, "_value_label"):
                    self.speed_slider._value_label.setText(str(int(getattr(cfg, "speed", 60))))
                self.speed_slider.blockSignals(False)
        except Exception: pass

    def _apply_beacons(self):
        if hasattr(self, "beacon_manager") and self.beacon_manager is not None:
            try:
                multi_cfg = self.beacon_manager.collect_multi_config().validate()
                self.beacon_config = multi_cfg
                was_running = getattr(self, "_running", False)
                if was_running: self._pause()
                profile = str(getattr(multi_cfg, "profile", "curved"))
                speed = float(getattr(multi_cfg, "speed", 60))
                shape = str(getattr(multi_cfg, "shape", "square"))
                size_w = int(getattr(multi_cfg, "size_w", 10))
                size_h = int(getattr(multi_cfg, "size_h", 10))
                blinking = bool(getattr(multi_cfg, "blinking", False))
                speed_random = bool(getattr(multi_cfg, "speed_random", False))
                tgt_x = float(getattr(multi_cfg, "x", 2500)) if multi_cfg.beacon_count == 1 else None
                tgt_y = float(getattr(multi_cfg, "y", 2500)) if multi_cfg.beacon_count == 1 else None
                scene_w, scene_h = self._scene_size
                seed = int(self.seed_spin.value()) + int(time.time()) % 1000 if hasattr(self, "seed_spin") else 42
                self.beacons = create_beacons(int(multi_cfg.beacon_count), (scene_w, scene_h), profile, speed,
                                               seed=seed, hitbox_radius=14, center_radius=2, shape=shape, size_w=size_w, size_h=size_h, blinking=blinking, x=tgt_x, y=tgt_y, speed_random=speed_random)
                tid = int(np.clip(int(multi_cfg.target_index), 0, max(0, len(self.beacons)-1)))
                self._target_beacon_id = tid; self._beacon_count = int(multi_cfg.beacon_count)
                self.target = self.beacons[tid] if self.beacons else self.beacons[0]
                self.statusBar().showMessage(f"Beacons: {self._beacon_count} Target #{tid} {shape} {size_w}x{size_h}", 3000)
                self._rebuild_per_beacon_panels()
                try: self._on_target_beacon_change(tid)
                except Exception: pass
                if was_running: self._start()
                return
            except Exception:
                pass
        try:
            self._beacon_count = int(self.beacon_count_spin.value())
        except Exception: return
        was_running = getattr(self, "_running", False)
        if was_running: self._pause()
        try: profile = MotionProfile(self.motion_combo.currentText())
        except Exception: profile = self.target.profile if hasattr(self, "target") else MotionProfile.CURVED
        speed = float(getattr(self, "_target_speed", 60))
        scene_w, scene_h = self._scene_size
        seed = int(self.seed_spin.value()) + int(time.time()) % 1000
        self.beacons = create_beacons(self._beacon_count, (scene_w, scene_h), profile, speed,
                                       seed=seed, hitbox_radius=self._hitbox_radius, center_radius=self._center_radius)
        try:
            tid = int(self.target_beacon_spin.value())
        except Exception:
            tid = int(getattr(self, "_target_beacon_id", 0))
        tid = int(np.clip(tid, 0, max(0, len(self.beacons)-1)))
        self._target_beacon_id = tid
        self.target = self.beacons[tid] if self.beacons else self.beacons[0]
        self.statusBar().showMessage(f"Beacons: {self._beacon_count}  Target #{tid}  hitbox {self._hitbox_radius}px  center {self._center_radius}px", 3000)
        self._rebuild_per_beacon_panels()
        try: self._on_target_beacon_change(tid)
        except Exception: pass
        if was_running: self._start()

    def _apply_beacons_hot(self):
        try:
            if hasattr(self, "beacon_manager") and self.beacon_manager is not None:
                multi_cfg = self.beacon_manager.collect_multi_config().validate()
                self.beacon_config = multi_cfg
                self._beacon_count = int(multi_cfg.beacon_count)
                tid = int(multi_cfg.target_index)
                profile = str(getattr(multi_cfg, "profile", "curved"))
                speed = float(getattr(multi_cfg, "speed", 60))
                shape = str(getattr(multi_cfg, "shape", "square"))
                size_w = int(getattr(multi_cfg, "size_w", 10))
                size_h = int(getattr(multi_cfg, "size_h", 10))
                blinking = bool(getattr(multi_cfg, "blinking", False))
                speed_random = bool(getattr(multi_cfg, "speed_random", False))
                tgt_x = float(getattr(multi_cfg, "x", 2500)) if multi_cfg.beacon_count == 1 else None
                tgt_y = float(getattr(multi_cfg, "y", 2500)) if multi_cfg.beacon_count == 1 else None
                scene_w, scene_h = self._scene_size
                seed = int(self.seed_spin.value()) + int(time.time()) % 1000 if hasattr(self, "seed_spin") else 42
                self.beacons = create_beacons(self._beacon_count, (scene_w, scene_h), profile, speed,
                                               seed=seed, hitbox_radius=14, center_radius=2, shape=shape, size_w=size_w, size_h=size_h, blinking=blinking, x=tgt_x, y=tgt_y, speed_random=speed_random)
                tid = int(np.clip(int(tid), 0, max(0, len(self.beacons)-1)))
                self._target_beacon_id = tid
                self.target = self.beacons[tid] if self.beacons else self.beacons[0]
                self._rebuild_per_beacon_panels()
                try: self._on_target_beacon_change(tid)
                except Exception: pass
                self.statusBar().showMessage(f"Beacons — {self._beacon_count} {shape} {size_w}x{size_h} Target #{tid}", 2000)
                try: self._snapshot_section("beacons"); self._clear_dirty("beacons")
                except Exception: pass
                return
        except Exception:
            pass
        try:
            self._beacon_count = int(self.beacon_count_spin.value())
        except Exception: return
        try: profile = MotionProfile(self.motion_combo.currentText())
        except Exception: profile = self.target.profile if hasattr(self, "target") else MotionProfile.CURVED
        speed = float(getattr(self, "_target_speed", 60))
        scene_w, scene_h = self._scene_size
        seed = int(self.seed_spin.value()) + int(time.time()) % 1000
        self.beacons = create_beacons(self._beacon_count, (scene_w, scene_h), profile, speed,
                                       seed=seed, hitbox_radius=self._hitbox_radius, center_radius=self._center_radius)
        try: tid = int(self.target_beacon_spin.value())
        except Exception: tid = int(getattr(self, "_target_beacon_id", 0))
        tid = int(np.clip(tid, 0, max(0, len(self.beacons)-1)))
        self._target_beacon_id = tid
        self.target = self.beacons[tid] if self.beacons else self.beacons[0]
        self._rebuild_per_beacon_panels()
        try: self._on_target_beacon_change(tid)
        except Exception: pass
        self.statusBar().showMessage(f"Beacons — {self._beacon_count} beacons Target #{tid} (auto)", 2000)
        try: self._snapshot_section("beacons"); self._clear_dirty("beacons")
        except Exception: pass

    def _rebuild_per_beacon_panels(self):
        try:
            if hasattr(self, "beacon_manager"):
                self.beacon_manager._update_status()
        except Exception: pass

    def _randomize_all_beacons(self):
        try:
            import random
            if hasattr(self, "beacon_manager"):
                bm = self.beacon_manager
                try:
                    bm.combo_shape.setCurrentIndex(random.randint(0, bm.combo_shape.count()-1))
                except Exception: pass
                try:
                    bm.spin_size_w.setValue(random.randint(5, 20))
                    bm.spin_size_h.setValue(random.randint(2, 20))
                except Exception: pass
                try:
                    bm.spin_x.setValue(random.randint(200, 4800))
                    bm.spin_y.setValue(random.randint(200, 4800))
                except Exception: pass
                try:
                    bm.combo_motion.setCurrentIndex(random.randint(0, bm.combo_motion.count()-1))
                except Exception: pass
                try:
                    bm.spin_speed.setValue(random.randint(20, 150))
                    bm.chk_random_speed.setChecked(random.choice([True, False]))
                except Exception: pass
                try:
                    bm.chk_blinking.setChecked(random.choice([True, False]))
                except Exception: pass
                self.statusBar().showMessage(f"Randomized parameters for {len(getattr(self,'beacons',[]))} beacons", 2500)
                return
            import random as _rnd
            for b in getattr(self, "beacons", []):
                try:
                    b.profile = _rnd.choice(list(MotionProfile))
                except Exception: pass
                try:
                    b.shape = _rnd.choice(["square", "circle"])
                    b.size_w = _rnd.randint(5, 20)
                    b.size_h = _rnd.randint(2, 20)
                    b.speed = float(_rnd.randint(20, 150))
                    b.blinking = _rnd.choice([True, False])
                    b.randomize_position(seed=int(_rnd.randint(0, 999999)))
                except Exception:
                    try:
                        b.x = float(_rnd.uniform(60, self._scene_size[0]-60))
                        b.y = float(_rnd.uniform(60, self._scene_size[1]-60))
                    except Exception: pass
            self.statusBar().showMessage(f"Randomized parameters for {len(self.beacons)} beacons", 2500)
        except Exception: pass

    def _randomize_beacon_motion(self):
        try:
            import random
            if hasattr(self, "beacon_manager"):
                bm = self.beacon_manager
                bm.combo_motion.setCurrentIndex(random.randint(0, bm.combo_motion.count()-1))
                self.statusBar().showMessage(f"Randomized motion for {len(getattr(self,'beacons',[]))} beacons", 2500)
                return
            import random as _rnd
            for b in getattr(self, "beacons", []):
                try:
                    b.profile = _rnd.choice(list(MotionProfile))
                    b.randomize_position(seed=int(_rnd.randint(0, 999999)))
                except Exception: pass
            self.statusBar().showMessage(f"Randomized motion for {len(self.beacons)} beacons", 2500)
        except Exception: pass

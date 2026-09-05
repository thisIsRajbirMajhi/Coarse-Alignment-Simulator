# gui/mixins/presets_mixin.py - Preset handling for Control Deck
# Extracted as part of control deck upgrade: Presets tab + quick bar.
# Provides _apply_preset (full-system one-click) and _randomize_all_presets.
# Single Responsibility: translate preset specs (gui/panels/presets_panel.PRESETS) into live configs.

from __future__ import annotations

from PyQt5.QtWidgets import QMessageBox


class PresetsMixin:
    """Mixin: Preset application — applies PRESETS dict to all panels + simulation."""

    def _apply_preset(self, name: str) -> None:  # type: ignore
        """Apply a named preset from gui/panels/presets_panel.PRESETS.

        Merges preset overrides onto current configs, pushes to panels (emit=False),
        then rebuilds simulation for beacon/camera/world changes. HOT for env/camera/control/disturbance.
        """
        try:
            from gui.panels.presets_panel import PRESETS
            spec = PRESETS.get(name)
            if spec is None:
                raise ValueError(f"Unknown preset {name!r}")
        except Exception as e:
            QMessageBox.warning(self, "Preset", f"Failed to load preset {name}: {e}")  # type: ignore
            return

        was_running = bool(getattr(self, "_running", False))
        if was_running:
            try:
                self._pause()  # type: ignore
            except Exception:
                pass

        # 1) Environment
        try:
            if "env" in spec and spec["env"]:
                from environment.config import EnvironmentConfig as _EC
                base = self.env_config.to_dict() if hasattr(self, "env_config") else {}
                merged = {**base, **spec["env"]}
                cfg = _EC.from_dict(merged).validate()
                if hasattr(self, "env_panel") and self.env_panel is not None:
                    self.env_panel.set_config(cfg, emit=False)
                self.env_config = cfg
                self._scene_size = (int(cfg.world_width), int(cfg.world_height))
        except Exception as e:
            print(f"Preset env failed: {e}")

        # 2) Camera (needs scene bounds after env)
        try:
            if "camera" in spec and spec["camera"]:
                from camera.config import CameraConfig as _CC
                base = self.camera_config.to_dict() if hasattr(self, "camera_config") else {}
                merged = {**base, **spec["camera"]}
                # Need scene bounds for validate
                bounds = getattr(self, "_scene_size", None)
                cfg = _CC.from_dict(merged).validate(bounds)
                if hasattr(self, "camera_panel") and self.camera_panel is not None:
                    self.camera_panel.set_config(cfg, emit=False)
                    try:
                        self.camera_panel.set_scene_bounds(bounds)  # type: ignore
                    except Exception:
                        pass
                self.camera_config = cfg
        except Exception as e:
            print(f"Preset camera failed: {e}")

        # 3) Control
        try:
            if "control" in spec and spec["control"]:
                from control.config import ControllerConfig as _CtrlC
                base = self.controller_config.to_dict() if hasattr(self, "controller_config") else {}
                merged = {**base, **spec["control"]}
                cfg = _CtrlC(**merged).validate()
                if hasattr(self, "control_panel") and self.control_panel is not None:
                    self.control_panel.set_config(cfg, emit=False)
                self.controller_config = cfg
                # Apply live
                try:
                    self.controller.apply_config(cfg)  # type: ignore
                except Exception:
                    pass
        except Exception as e:
            print(f"Preset control failed: {e}")

        # 4) Disturbance
        try:
            if "disturb" in spec and spec["disturb"]:
                from disturbance.config import DisturbanceConfig as _DC
                base = self.disturbance_config.to_dict() if hasattr(self, "disturbance_config") else {}
                merged = {**base, **spec["disturb"]}
                cfg = _DC.from_dict(merged).validate()
                if hasattr(self, "disturbances_panel") and self.disturbances_panel is not None:
                    self.disturbances_panel.set_config(cfg, emit=False)
                    try:
                        self.sliders = self.disturbances_panel.sliders  # type: ignore
                    except Exception:
                        pass
                self.disturbance_config = cfg
        except Exception as e:
            print(f"Preset disturbance failed: {e}")

        # 5) Beacons / Target
        try:
            if "beacon" in spec and spec["beacon"]:
                from target.config import MultiBeaconConfig as _MBC
                base = self.beacon_config.to_dict() if hasattr(self, "beacon_config") else {}
                merged = {**base, **spec["beacon"]}
                # Ensure beacon_count/target_index compatibility
                cfg = _MBC.from_dict(merged).validate()
                if hasattr(self, "beacon_manager") and self.beacon_manager is not None:
                    self.beacon_manager.set_config(cfg, emit=False)
                self.beacon_config = cfg
                self._beacon_count = int(cfg.beacon_count)
                self._target_beacon_id = int(cfg.target_index)
        except Exception as e:
            print(f"Preset beacon failed: {e}")

        # 6) Global tuning (sim speed, brightness, radius) — if preset had extras, handle
        try:
            if "global" in spec and spec["global"]:
                g = spec["global"]
                if "sim_speed" in g and hasattr(self, "global_panel") and hasattr(self.global_panel, "sim_speed_spin"):
                    self.global_panel.sim_speed_spin.blockSignals(True)
                    self.global_panel.sim_speed_spin.setValue(float(g["sim_speed"]))
                    self.global_panel.sim_speed_spin.blockSignals(False)
                    self._sim_speed = float(g["sim_speed"])  # type: ignore
                if "brightness" in g and hasattr(self, "global_panel") and hasattr(self.global_panel, "global_brightness_spin"):
                    self.global_panel.global_brightness_spin.blockSignals(True)
                    self.global_panel.global_brightness_spin.setValue(int(g["brightness"]))
                    self.global_panel.global_brightness_spin.blockSignals(False)
                if "radius" in g and hasattr(self, "global_panel") and hasattr(self.global_panel, "global_radius_spin"):
                    self.global_panel.global_radius_spin.blockSignals(True)
                    self.global_panel.global_radius_spin.setValue(int(g["radius"]))
                    self.global_panel.global_radius_spin.blockSignals(False)
        except Exception:
            pass

        # Rebuild simulation to realize world/camera/beacon changes
        try:
            self._build_simulation()  # type: ignore
            self._invalidate_minimap_cache()  # type: ignore
            self._rebuild_per_beacon_panels()  # type: ignore
            self._sync_per_beacon_xy_ranges()  # type: ignore
            # Refresh dirty snapshots
            for sec in ["global", "beacons", "camera", "control", "environment", "disturbances"]:
                try:
                    self._snapshot_section(sec)  # type: ignore
                    self._clear_dirty(sec)  # type: ignore
                except Exception:
                    pass
        except Exception as e:
            print(f"Preset rebuild failed: {e}")

        if was_running:
            try:
                self._start()  # type: ignore
            except Exception:
                pass

        try:
            self.statusBar().showMessage(f"Preset '{name}' applied — {spec.get('desc','')}", 3500)  # type: ignore
        except Exception:
            pass
        # Also reflect in control deck status if visible
        try:
            if hasattr(self, "control_deck_window") and self.control_deck_window is not None:
                self.control_deck_window.statusBar().showMessage(f"Preset {name} applied", 2500)
        except Exception:
            pass

    def _randomize_all_presets(self) -> None:  # type: ignore
        """Domain-randomize all configs (mixed difficulty) — for AI training / stress."""
        import numpy as np
        import random
        try:
            from environment.config import EnvironmentConfig as _EC
            from disturbance.config import DisturbanceConfig as _DC
            rng = np.random.default_rng(random.randint(0, 999999))
            # Environment mixed
            try:
                ec = _EC().randomize_for_training(rng, difficulty="mixed").validate()
                if hasattr(self, "env_panel"):
                    self.env_panel.set_config(ec, emit=False)
                self.env_config = ec
                self._scene_size = (int(ec.world_width), int(ec.world_height))
            except Exception:
                pass
            # Disturbance mixed
            try:
                dc = _DC().randomize_for_training(rng, difficulty="mixed").validate()
                if hasattr(self, "disturbances_panel"):
                    self.disturbances_panel.set_config(dc, emit=False)
                    self.sliders = self.disturbances_panel.sliders  # type: ignore
                self.disturbance_config = dc
            except Exception:
                pass
            # Beacons random
            try:
                if hasattr(self, "beacon_manager"):
                    self.beacon_manager.spin_beacon_count.blockSignals(True)
                    self.beacon_manager.spin_beacon_count.setValue(int(rng.integers(1, 6)))
                    self.beacon_manager.spin_beacon_count.blockSignals(False)
                    # Random shape/motion etc handled via randomize_all_beacons
                    self._randomize_all_beacons()  # type: ignore
            except Exception:
                pass
            # Camera random realism within limits
            try:
                from camera.config import CameraConfig as _CC
                # Keep current but randomize realism fields
                base = self.camera_config.to_dict()
                base["backlash_px"] = float(rng.uniform(0, 1.2))
                base["encoder_sigma_px"] = float(rng.uniform(0, 0.2))
                base["max_accel_deg"] = float(rng.integers(60, 220))
                cfg = _CC.from_dict(base).validate(self._scene_size)
                if hasattr(self, "camera_panel"):
                    self.camera_panel.set_config(cfg, emit=False)
                self.camera_config = cfg
            except Exception:
                pass
            # Rebuild
            self._build_simulation()  # type: ignore
            self._invalidate_minimap_cache()  # type: ignore
            for sec in ["environment", "disturbances", "beacons", "camera"]:
                try:
                    self._snapshot_section(sec)  # type: ignore
                    self._clear_dirty(sec)  # type: ignore
                except Exception:
                    pass
            self.statusBar().showMessage("Randomize All — domain randomization (mixed) applied", 3000)  # type: ignore
        except Exception as e:
            QMessageBox.warning(self, "Randomize", f"Failed: {e}")  # type: ignore

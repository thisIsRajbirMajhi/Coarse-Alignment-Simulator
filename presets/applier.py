"""
Module: presets.applier
Purpose: Apply a Preset to a live MainWindow — configures entire software (well-commented).
Public API: apply_preset
Notes: Stateless helper — reads preset dicts, builds validated configs, pushes to panels,
       triggers HOT applies, then auto-runs simulation. Keeps preset pure data, applier handles GUI wiring.

Steps per preset:
  1) Environment — EnvironmentConfig.from_dict → env_panel.set_config → _apply_scene_settings_hot
  2) Camera — CameraConfig.from_dict → camera_panel.set_config → _apply_camera_hot
  3) Beacons — MultiBeaconConfig.from_dict → beacon_manager.set_config → _apply_beacons_hot (+ _apply_beacon_configs_hot for per-beacon)
  4) Disturbances — set 4 sliders
  5) Controller — ControllerConfig.from_dict → control_panel.set_config → _apply_control_hot
  6) Overlay — OverlayConfig.from_dict → overlay_panel.set_config → _apply_overlay_hot
  7) Detector/Tracker — set thresholds via detector/tracker directly
  8) Reset disturbance state, tracker, perf, then _start()
"""

from __future__ import annotations

import time

# ============================================================
# SECTION: apply_preset — entire software
# ============================================================

def apply_preset(window, preset, auto_run: bool = True) -> None:
    """
    Apply preset to window and optionally auto-run.

    Args:
      window: MainWindow instance
      preset: Preset
      auto_run: if True, calls window._start() after configuring (and resets perf)
    """
    # Environment
    if preset.environment:
        try:
            from environment.config import EnvironmentConfig
            cfg = EnvironmentConfig.from_dict(dict(preset.environment)).validate()
            window.env_config = cfg
            if hasattr(window, "env_panel"):
                window.env_panel.set_config(cfg, emit=False)
        except Exception:
            pass

    # Camera
    if preset.camera:
        try:
            from camera.config import CameraConfig
            # Need scene bounds for validation
            sw, sh = getattr(window, "_scene_size", (1000, 1000))
            cfg = CameraConfig.from_dict(dict(preset.camera)).validate((sw, sh))
            window.camera_config = cfg
            if hasattr(window, "camera_panel"):
                window.camera_panel.set_config(cfg, emit=False)
        except Exception:
            pass

    # Beacons (Multi)
    if preset.beacons:
        try:
            from target.config import MultiBeaconConfig
            # Merge environment seed into beacons if not specified
            beacons_dict = dict(preset.beacons)
            # Ensure beacons have proper structure — if only top-level, let from_dict handle
            cfg = MultiBeaconConfig.from_dict(beacons_dict).validate()
            window.beacon_config = cfg
            if hasattr(window, "beacon_manager"):
                window.beacon_manager.set_config(cfg, emit=False)
                # Keep legacy mirror attrs
                window._beacon_count = int(cfg.beacon_count)
                window._target_beacon_id = int(cfg.target_index)
        except Exception:
            pass

    # Target profile/speed override (applies to beacons' profile/speed if beacons not fully specified)
    if preset.target:
        try:
            prof = preset.target.get("profile")
            speed = preset.target.get("speed")
            if prof or speed:
                # Update first beacon or all? For presets, update target beacon
                if hasattr(window, "beacon_manager"):
                    # Update via panel configs
                    for panel in window.beacon_manager.get_per_beacon_panels():
                        if prof:
                            idx = window.beacon_manager.spin_target_index.value()
                            if panel.beacon_id == idx:
                                panel.combo_profile.setCurrentText(str(prof))
                        if speed is not None:
                            # Only target gets exact speed, others proportional (handled in speed handler)
                            if panel.beacon_id == window.beacon_manager.spin_target_index.value():
                                panel.spin_speed.setValue(int(speed))
                # Also update global motion combo for legacy
                if prof and hasattr(window, "motion_combo"):
                    try:
                        window.motion_combo.setCurrentText(str(prof))
                    except: pass
        except: pass

    # Disturbances — 4 sliders
    if preset.disturbances:
        try:
            for key, val in dict(preset.disturbances).items():
                if key in getattr(window, "sliders", {}):
                    window.sliders[key].setValue(int(val))
                elif hasattr(window, "disturbances_panel") and key in window.disturbances_panel.sliders:
                    window.disturbances_panel.sliders[key].setValue(int(val))
        except: pass

    # Controller
    if preset.controller:
        try:
            from control.config import ControllerConfig
            cfg = ControllerConfig.from_dict(dict(preset.controller)).validate()
            window.controller_config = cfg
            if hasattr(window, "control_panel"):
                window.control_panel.set_config(cfg, emit=False)
            # Also apply to live controller if exists
            if hasattr(window, "controller"):
                try:
                    window.controller.apply_config(cfg)
                except: pass
        except: pass

    # Overlay
    if preset.overlay:
        try:
            from overlay.config import OverlayConfig
            cfg = OverlayConfig.from_dict(dict(preset.overlay)).validate()
            window.overlay_config = cfg
            if hasattr(window, "overlay_panel"):
                window.overlay_panel.set_config(cfg, emit=False)
        except: pass

    # Detector
    if preset.detector:
        try:
            thresh = preset.detector.get("brightness_threshold")
            if thresh is not None and hasattr(window, "detector"):
                window.detector.brightness_threshold = int(thresh)
                # Also sync GUI slider if exists (thresh_slider in global_panel)
                if hasattr(window, "global_panel") and hasattr(window.global_panel, "thresh_slider"):
                    window.global_panel.thresh_slider.blockSignals(True)
                    window.global_panel.thresh_slider.setValue(int(thresh))
                    window.global_panel.thresh_slider.blockSignals(False)
                if hasattr(window, "thresh_slider"):
                    window.thresh_slider.blockSignals(True)
                    window.thresh_slider.setValue(int(thresh))
                    window.thresh_slider.blockSignals(False)
        except: pass

    # Tracker
    if preset.tracker:
        try:
            from tracking.config import TrackerConfig
            cfg = TrackerConfig.from_dict(dict(preset.tracker)).validate()
            if hasattr(window, "tracker"):
                window.tracker.apply_config(cfg)
        except: pass

    # Force HOT applies (ensure scene/camera/beacons rebuilt with new configs)
    # Use small delay to let signals settle, then trigger rebuilds
    try:
        # Snapshot current to clear dirty
        for sec in ["environment", "camera", "beacons", "control", "overlay", "disturbances"]:
            try:
                window._snapshot_section(sec)
            except: pass
        # Trigger rebuilds via HOT handlers (debounced but we force immediate)
        # For immediate effect in preset, call the underlying apply directly
        # Environment+Camera via scene
        try:
            window._apply_scene_settings_hot()
        except: pass
        try:
            window._apply_camera_hot()
        except: pass
        # Beacons — need factory rebuild for count/profile changes
        try:
            # If beacon count/profile changed, do full factory
            window._apply_beacons_hot()
            # Then per-beacon overlay (brightness/radius etc.)
            window._apply_beacon_configs_hot()
        except: pass
        # Control/Overlay
        try:
            window._apply_control_hot()
        except: pass
        try:
            window._apply_overlay_hot()
        except: pass
        # Disturbances are live via sliders, no rebuild needed
        # Clear all dirty
        try:
            window._dirty_tabs.clear()
        except: pass
    except: pass

    # Reset performance and disturbance state for clean run
    try:
        from disturbance.state import reset_disturbance_state
        reset_disturbance_state()
        window._camera_drift_state.clear()
    except: pass
    try:
        window.perf = window.perf.__class__()
        window._hitbox_hits = 0; window._center_hits = 0; window._frames_with_detections = 0
        if hasattr(window, "tracker"):
            window.tracker.reset()
    except: pass

    # Auto-run
    if auto_run:
        try:
            # Small delay to let UI settle, then start
            window._start()
            window.statusBar().showMessage(f"Preset '{preset.name}' — {preset.goal}", 4000)
        except: pass

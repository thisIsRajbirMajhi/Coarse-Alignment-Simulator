# gui/mixins/stats_mixin.py - Dashboard stats update (logging removed, in-memory only)

import time
import math
from collections import deque
import numpy as np  # noqa


class StatsMixin:
    """Mixin: Push live pose + config + lightweight in-memory metrics into DashboardPanel."""

    def _ensure_stats(self):
        if not hasattr(self, "_stats_start"):
            self._stats_start = time.time()
            self._stats_frames = 0
            self._stats_proc = deque(maxlen=200)
            self._stats_errors = deque(maxlen=200)
            self._stats_lock_retention = deque(maxlen=200)
            self._stats_acq_time = None
            self._stats_first_lock = None
            self._stats_acquisitions = 0
            self._stats_lock_losses = 0
            self._stats_prev_lock = "searching"
            self._stats_detection = deque(maxlen=200)
            self._stats_last_tick = None
            self._stats_detect_hits = 0
            self._stats_center_hits = 0
            self._stats_search_frames = 0

    def _update_stats(self, tracking_error_px):
        self._ensure_stats()
        try:
            # Timing
            now = time.time()
            # _tick records timing for every frame; this method only refreshes the UI.

            # Lock / retention tracking (open-loop: always searching, unless estimate exists)
            lock = getattr(self, "_last_lock_state", "searching")
            is_tracking = (lock == "tracking")
            self._stats_lock_retention.append(1 if is_tracking else 0)
            if lock != self._stats_prev_lock:
                if lock == "tracking" and self._stats_prev_lock != "tracking":
                    self._stats_acquisitions += 1
                    if self._stats_first_lock is None:
                        self._stats_first_lock = now - self._stats_start
                if self._stats_prev_lock == "tracking" and lock != "tracking":
                    self._stats_lock_losses += 1
            self._stats_prev_lock = lock

            # Tracking error stats
            if tracking_error_px is not None:
                self._stats_errors.append(float(tracking_error_px))
            # Keep only recent 200 for p95 etc.
            # Detection hit this frame: real pipeline output (not hardcoded 0).
            try:
                dets = getattr(self, "_last_all_detections", []) or []
                est = getattr(self, "_last_estimate", None)
                has_det = 1 if (len(dets) > 0 or est is not None) else 0
            except Exception:
                has_det = 0
            self._stats_detection.append(has_det)
            try:
                if has_det:
                    self._stats_detect_hits += 1
                if lock == "searching":
                    self._stats_search_frames += 1
            except Exception:
                pass

            # Build summary dict expected by dashboard
            s = {}
            elapsed = max(1e-6, now - self._stats_start)
            s["simulation_duration_s"] = elapsed
            fps = self._stats_frames / elapsed if elapsed > 0 else 0
            # Smooth FPS with recent proc times as well
            s["fps"] = round(fps, 1)
            if self._stats_proc:
                arr = list(self._stats_proc)
                s["avg_processing_time_ms"] = float(sum(arr)/len(arr))
                s["min_processing_time_ms"] = float(min(arr))
                s["max_processing_time_ms"] = float(max(arr))
                # jitter as std
                mean = sum(arr)/len(arr)
                var = sum((x-mean)**2 for x in arr)/len(arr)
                s["jitter_ms"] = math.sqrt(var)
                # p95
                s["p95_processing_time_ms"] = float(sorted(arr)[int(len(arr)*0.95)] if len(arr)>5 else max(arr))
            else:
                s["avg_processing_time_ms"] = s["min_processing_time_ms"] = s["max_processing_time_ms"] = s["jitter_ms"] = s["p95_processing_time_ms"] = 0.0

            # Acquisition / re-acquisition from the real GT-isolated logger.
            # Falls back to live counters when logger has no records yet.
            try:
                logger = getattr(self, "_metrics_logger", None)
                recs = list(getattr(logger, "records", [])) if logger is not None else []
            except Exception:
                logger, recs = None, []
            try:
                hb = int(getattr(getattr(self, "target", None), "hitbox_radius", 14))
            except Exception:
                hb = 14
            try:
                cr = int(getattr(getattr(self, "target", None), "center_radius", 2))
            except Exception:
                cr = 2
            msum = None
            if logger is not None and recs:
                try:
                    msum = logger.summary(hitbox_radius=hb, center_radius=cr)
                except TypeError:
                    msum = logger.summary()
                except Exception:
                    msum = None
            if msum:
                s["acquisition_time_s"] = msum.get("acquisition_time_s")
                s["avg_reacquisition_time_s"] = msum.get("avg_reacquisition_time_s")
                s["min_reacquisition_time_s"] = msum.get("min_reacquisition_time_s")
                s["max_reacquisition_time_s"] = msum.get("max_reacquisition_time_s")
            else:
                s["acquisition_time_s"] = None
                s["avg_reacquisition_time_s"] = None
                s["min_reacquisition_time_s"] = None
                s["max_reacquisition_time_s"] = None
            s["acquisitions"] = self._stats_acquisitions
            s["lock_losses"] = self._stats_lock_losses
            # Multi-beacon identity (C): designated mission target, live locked
            # internal track, switches, hypothesis count.
            try:
                s["designated_target_id"] = int(getattr(self, "_target_beacon_id", 0))
            except Exception:
                s["designated_target_id"] = 0
            try:
                pipe = getattr(self, "_pipeline", None)
                s["locked_track_id"] = getattr(pipe, "multi", None).designated_internal_id if pipe is not None and getattr(pipe, "multi", None) is not None else getattr(self, "_last_locked_track_id", None)
                s["id_switches"] = int(getattr(pipe, "multi", None).id_switches) if pipe is not None and getattr(pipe, "multi", None) is not None else int(getattr(self, "_last_id_switches", 0) or 0)
                s["n_tracks"] = int(len(getattr(getattr(pipe, "multi", None), "tracks", []) or []))
            except Exception:
                s["locked_track_id"] = getattr(self, "_last_locked_track_id", None)
                s["id_switches"] = int(getattr(self, "_last_id_switches", 0) or 0)
                s["n_tracks"] = int(getattr(self, "_last_n_tracks", 0) or 0)
            try:
                if msum is not None and msum.get("id_switches") is not None:
                    s["id_switches"] = int(msum.get("id_switches"))
            except Exception:
                pass

            # Lock / retention - compute from recent window
            if self._stats_lock_retention:
                ret = sum(self._stats_lock_retention)/len(self._stats_lock_retention)*100
                s["lock_retention_rate_pct"] = round(ret,1)
                s["target_loss_pct"] = round(100-ret,1)
                # state percentages - simplified: searching vs tracking
                s["state_acquired_pct"] = 0.0
                s["state_lost_pct"] = round(100-ret,1) if ret<100 else 0.0
            else:
                s["lock_retention_rate_pct"] = 0.0
                s["target_loss_pct"] = 100.0
                s["state_acquired_pct"] = 0.0
                s["state_lost_pct"] = 0.0

            # Tracking errors
            if self._stats_errors:
                arr = list(self._stats_errors)
                s["avg_tracking_error_px"] = float(sum(arr)/len(arr))
                s["max_tracking_error_px"] = float(max(arr))
                s["min_tracking_error_px"] = float(min(arr))
                s["median_tracking_error_px"] = float(sorted(arr)[len(arr)//2])
                # rms
                s["rms_tracking_error_px"] = math.sqrt(sum(x*x for x in arr)/len(arr))
                s["p95_tracking_error_px"] = float(sorted(arr)[int(len(arr)*0.95)] if len(arr)>5 else max(arr))
                mean = s["avg_tracking_error_px"]
                s["std_tracking_error_px"] = math.sqrt(sum((x-mean)**2 for x in arr)/len(arr)) if len(arr)>1 else 0.0
            else:
                # No error data (open-loop with no estimate) — show 0 with green (not red) to avoid false failure
                s["avg_tracking_error_px"] = 0.0
                s["max_tracking_error_px"] = 0.0
                s["min_tracking_error_px"] = 0.0
                s["median_tracking_error_px"] = 0.0
                s["rms_tracking_error_px"] = 0.0
                s["p95_tracking_error_px"] = 0.0
                s["std_tracking_error_px"] = 0.0
            s["live_error_px"] = float(tracking_error_px) if tracking_error_px is not None else None

            # Detection / center-hit / searching from logger (GT-isolated).
            if msum:
                total = max(int(msum.get("frames", 0)), 1)
                s["detection_rate_pct"] = float(msum.get("detection_rate_pct", 0.0) or 0.0)
                s["detection_time_s"] = float(msum.get("detection_time_s", 0.0) or 0.0)
                s["detection_count"] = int(msum.get("detection_count", 0) or 0)
                s["center_hit_rate_pct"] = float(msum.get("center_hit_rate_pct", 0.0) or 0.0)
                s["center_hit_time_s"] = float(msum.get("center_hit_time_s", 0.0) or 0.0)
                s["center_hit_count"] = int(msum.get("center_hit_count", 0) or 0)
                s["searching_rate_pct"] = float(msum.get("searching_rate_pct", 0.0) or 0.0)
                s["searching_time_s"] = float(msum.get("searching_time_s", 0.0) or 0.0)
                s["frame_count"] = max(self._stats_frames, int(msum.get("frames", 0) or 0))
                # Prefer full-run retention/loss over the 200-frame window.
                try:
                    s["lock_retention_rate_pct"] = round(float(msum.get("lock_retention_pct", s.get("lock_retention_rate_pct", 0)) or 0), 1)
                    s["target_loss_pct"] = round(float(msum.get("target_loss_pct", s.get("target_loss_pct", 0)) or 0), 1)
                except Exception:
                    pass
            else:
                # No logger records yet: live fallback from pipeline outputs.
                total = max(self._stats_frames, 1)
                det_rate = 100.0 * sum(self._stats_detection) / max(len(self._stats_detection), 1) if self._stats_detection else 0.0
                s["detection_rate_pct"] = round(det_rate, 1)
                s["detection_count"] = int(self._stats_detect_hits)
                s["detection_time_s"] = round(self._stats_detect_hits / 30.0, 2)
                s["center_hit_rate_pct"] = 0.0
                s["center_hit_time_s"] = 0.0
                s["center_hit_count"] = 0
                s["searching_rate_pct"] = round(100.0 * self._stats_search_frames / total, 1)
                s["searching_time_s"] = round(self._stats_search_frames / 30.0, 2)
                s["frame_count"] = self._stats_frames

        except Exception:
            s = {}

        # Live pose and config (same as before, but without perf)
        try:
            pan = float(getattr(self.camera, "pan", 0) if hasattr(self, "camera") else 0)
            tilt = float(getattr(self.camera, "tilt", 0) if hasattr(self, "camera") else 0)
            s["live_pan"] = round(pan, 1)
            s["live_tilt"] = round(tilt, 1)
            s["live_fov"] = f"{self._fov_size[0]}×{self._fov_size[1]}"
            s["live_world"] = f"{self._scene_size[0]}×{self._scene_size[1]}"
            try:
                s["live_pixel_scale"] = float(getattr(getattr(self.camera, "config", {}), "pixel_scale_mrad", 0.035))
            except Exception:
                s["live_pixel_scale"] = float(getattr(self.camera_config, "pixel_scale_mrad", 0.035)) if hasattr(self, "camera_config") else 0.035
            # live_error already set above, but ensure
            if "live_error_px" not in s:
                s["live_error_px"] = float(tracking_error_px) if tracking_error_px is not None else None
            try:
                s["config_haze_pct"] = int(getattr(self.env_config, "haze_pct", 0)) if hasattr(self, "env_config") else 0
                s["config_star_count"] = int(getattr(self.env_config, "star_count", 0)) if hasattr(self, "env_config") else 0
                s["config_max_slew"] = float(getattr(self.camera_config, "max_slew_rate", 0)) if hasattr(self, "camera_config") else 0
                s["config_latency_ms"] = int(getattr(self.camera_config, "latency_ms", 0)) if hasattr(self, "camera_config") else 0
                s["config_beacon_count"] = f"{self._beacon_count} (target #{self._target_beacon_id})" if hasattr(self, "_beacon_count") else str(getattr(self.beacon_config, "beacon_count", 1)) if hasattr(self, "beacon_config") else "—"
                try:
                    prof = getattr(self.target, "profile", None)
                    prof_str = prof.value if hasattr(prof, "value") else str(prof) if prof else "—"
                    speed = getattr(self.target, "speed", 0)
                    s["config_beacon_profile"] = f"{prof_str} @ {float(speed):.0f} px/s"
                except Exception:
                    s["config_beacon_profile"] = "—"
                try:
                    if hasattr(self, "disturbance_config") and self.disturbance_config is not None:
                        dc = self.disturbance_config
                        parts = [f"T{int(getattr(dc,'turbulence',0))} V{int(getattr(dc,'vibration',0))} C{int(getattr(dc,'camera_motion',0))} N{int(getattr(dc,'noise',0))}"]
                        if bool(getattr(dc,'enable_salt_pepper',False) or getattr(dc,'enable_gaussian',False) or getattr(dc,'enable_poisson',False)):
                            en=[]
                            if getattr(dc,'enable_salt_pepper',False): en.append(f"S&P{getattr(dc,'salt_pepper_density',0)*100:.0f}%")
                            if getattr(dc,'enable_gaussian',False): en.append(f"Gσ{getattr(dc,'gaussian_sigma',0):.0f}")
                            if getattr(dc,'enable_poisson',False): en.append("Poisson")
                            parts.append("+".join(en) + f"/max{getattr(dc,'gaussian_sigma_max',20):.0f}")
                        if float(getattr(dc,'camera_jitter',0))>0:
                            parts.append(f"J±{float(getattr(dc,'camera_jitter',0)):.1f}px")
                        preset = str(getattr(dc,'atmospheric_preset','Clear'))
                        if preset!="Clear":
                            parts.append(f"Atmo{preset[:4]} C{int(getattr(dc,'atmospheric_contrast',0))} B{int(getattr(dc,'atmospheric_brightness',0))}")
                        if float(getattr(dc,'platform_speed',0))>0:
                            parts.append(f"Plat{str(getattr(dc,'platform_profile','Lin'))[:4]} {float(getattr(dc,'platform_speed',0)):.0f}px/f")
                        s["config_disturbances"] = " • ".join(parts)
                    else:
                        turb = self.sliders["Turbulence"].value() if hasattr(self, "sliders") and "Turbulence" in self.sliders else 0
                        vib = self.sliders["Vibration"].value() if hasattr(self, "sliders") and "Vibration" in self.sliders else 0
                        cam = self.sliders["Camera Motion"].value() if hasattr(self, "sliders") and "Camera Motion" in self.sliders else 0
                        noise = self.sliders["Noise"].value() if hasattr(self, "sliders") and "Noise" in self.sliders else 0
                        s["config_disturbances"] = f"T{turb} V{vib} C{cam} N{noise}"
                except Exception:
                    s["config_disturbances"] = "—"
                try:
                    ctrl_type = getattr(self.controller_config, "controller_type", "P") if hasattr(self, "controller_config") else "P"
                    kp = getattr(self.controller_config, "kp", 0) if hasattr(self, "controller_config") else 0
                    rate = getattr(self.controller_config, "update_rate_hz", 0) if hasattr(self, "controller_config") else 0
                    s["config_controller"] = f"{ctrl_type} Kp{kp:.2f} @ {rate:.0f}Hz"
                except Exception:
                    s["config_controller"] = "—"
            except Exception:
                pass
        except Exception:
            pass
        try:
            if hasattr(self, "dashboard_panel"):
                cam_scale = s.get("live_pixel_scale")
                if cam_scale is None:
                    try:
                        cam_scale = float(getattr(getattr(self, "camera", None).config, "pixel_scale_mrad", None))
                    except Exception: pass
                lock_val = getattr(self, "_last_lock_state", "searching")
                self.dashboard_panel.update_from_summary(s, lock_val, tracking_error_px, camera_scale_mrad=cam_scale)
                try:
                    if hasattr(self, "dashboard_window") and hasattr(self.dashboard_window, "update_live_status"):
                        self.dashboard_window.update_live_status(s)
                except Exception: pass
            else:
                for k in ["fps","simulation_duration_s","acquisition_time_s","avg_processing_time_ms","avg_tracking_error_px","max_tracking_error_px","tracking_error_pct","lock_retention_rate_pct","acquisitions","detection_rate_pct","detection_time_s","searching_rate_pct","searching_time_s","center_hit_rate_pct","center_hit_time_s"]:
                    if k in getattr(self, "stat_labels", {}):
                        self.stat_labels[k].setText(str(s.get(k, "-")))
                if "lock_status" in getattr(self, "stat_labels", {}):
                    self.stat_labels["lock_status"].setText(getattr(self, "_last_lock_state", "searching"))
        except Exception: pass

        try:
            for attr in ["_telemetry_strip", "_fov_footer", "_god_footer", "_hdr_mode_badge", "_hdr_fov_badge", "_hdr_world_badge", "footer_lock", "lock_dot", "footer_fps", "footer_info", "_fov_footer_info", "_god_footer_info"]:
                w = getattr(self, attr, None)
                if w is not None:
                    try:
                        w.hide()
                    except Exception: pass
            # NOTE: no per-tick statusBar spam here (was causing flicker + lag).
        except Exception: pass

    def _reset_stats(self):
        for attr in ["_stats_start","_stats_frames","_stats_proc","_stats_errors","_stats_lock_retention","_stats_acq_time","_stats_first_lock","_stats_acquisitions","_stats_lock_losses","_stats_prev_lock","_stats_detection","_stats_last_tick","_stats_detect_hits","_stats_center_hits","_stats_search_frames"]:
            try: delattr(self, attr)
            except Exception: pass

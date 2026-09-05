# gui/mixins/stats_mixin.py - Dashboard stats update
# Extracted from gui/main_window.py::_update_stats (103 lines).

import numpy as np  # noqa


class StatsMixin:
    """Mixin: Push perf summary + live pose + config snaps into DashboardPanel."""

    def _update_stats(self, tracking_error_px):
        # Dashboard-only: all metrics consolidated in DashboardPanel (single source)
        try:
            s = self.perf.summary()
        except Exception:
            return
        # Inject live system pose metrics (previously footer/header) into summary for dashboard
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
            s["live_error_px"] = float(tracking_error_px) if tracking_error_px is not None else None
            # Config snaps — entire system (for dashboard G, dashboard-only)
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
                self.dashboard_panel.update_from_summary(s, self.tracker.status.value, tracking_error_px, camera_scale_mrad=cam_scale)
                # Inform dashboard window status bar (intuitive live indicator)
                try:
                    if hasattr(self, "dashboard_window") and hasattr(self.dashboard_window, "update_live_status"):
                        self.dashboard_window.update_live_status(s)
                except Exception: pass
            else:
                # Fallback legacy direct label updates
                for k in ["fps","simulation_duration_s","acquisition_time_s","avg_processing_time_ms","avg_tracking_error_px","max_tracking_error_px","tracking_error_pct","lock_retention_rate_pct","acquisitions","detection_rate_pct","detection_time_s","searching_rate_pct","searching_time_s","center_hit_rate_pct","center_hit_time_s"]:
                    if k in getattr(self, "stat_labels", {}):
                        self.stat_labels[k].setText(str(s.get(k, "-")))
                if "lock_status" in getattr(self, "stat_labels", {}):
                    self.stat_labels["lock_status"].setText(self.tracker.status.value)
        except Exception: pass

        # Dashboard-only: external telemetry/header/footer metric displays hidden; dashboard is single source
        try:
            for attr in ["_telemetry_strip", "_fov_footer", "_god_footer", "_hdr_mode_badge", "_hdr_fov_badge", "_hdr_world_badge", "footer_lock", "lock_dot", "footer_fps", "footer_info", "_fov_footer_info", "_god_footer_info"]:
                w = getattr(self, attr, None)
                if w is not None:
                    try:
                        w.hide()
                    except Exception: pass
            # Status bar no longer shows metric values outside dashboard — points to dashboard (metrics dashboard-only)
            self.statusBar().showMessage("Metrics -> Dashboard only -- see Dashboard tab/window for live FPS, error, retention, reacq, etc. (Sr.16-20)", 2000)
        except Exception: pass

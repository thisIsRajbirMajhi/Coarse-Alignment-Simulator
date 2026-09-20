# camera/ptz.py - Virtual Pan-Tilt-Zoom (PTZ) Camera with realistic gimbal kinematics and FOV extraction.
from __future__ import annotations

import logging
import math
from typing import Any

import cv2
import numpy as np

from camera.config import CameraConfig
from camera.state import PTZState
from common.rng import get_rng

log = logging.getLogger(__name__)


class PTZCamera:
    """
    Virtual PTZ Camera for Coarse Alignment Simulator.
    
    Features:
    - 2-axis gimbal kinematics with rate and acceleration limits
    - Realistic mechanical dynamics: inertia, damping, backlash hysteresis
    - Optical encoder quantization and measurement noise
    - Exact FOV viewport extraction from world scene with boundary padding
    - Strict monochrome output (per user specifications)
    - Full telemetry reporting
    """

    def __init__(
        self,
        config: CameraConfig | None = None,
        world_size: tuple[int, int] = (2000, 2000),
        rng: np.random.Generator | None = None,
    ):
        self.config = (config or CameraConfig()).validate()
        self.world_size = (int(world_size[0]), int(world_size[1]))
        self.rng = get_rng(rng, 42)

        # Mechanical state (true angles and velocities)
        self.pan_deg: float = float(self.config.home_pan_deg)
        self.tilt_deg: float = float(self.config.home_tilt_deg)
        self.pan_vel_deg_s: float = 0.0
        self.tilt_vel_deg_s: float = 0.0
        self.pan_accel_deg_s2: float = 0.0
        self.tilt_accel_deg_s2: float = 0.0

        # Commanded targets
        self.target_pan_deg: float = self.pan_deg
        self.target_tilt_deg: float = self.tilt_deg

        # Backlash state (hysteresis tracking per axis)
        self._pan_backlash_slack: float = 0.0
        self._tilt_backlash_slack: float = 0.0

        # Pre-calculated encoder quantization step
        self._update_encoder_resolution()

        # Cached measured angles (quantization + sensor noise)
        self._measured_pan_deg: float = self.pan_deg
        self._measured_tilt_deg: float = self.tilt_deg
        self._compute_measured_angles()

        # Last extracted frame cache
        self._last_fov_frame: np.ndarray | None = None
        self._last_raw_mono: np.ndarray | None = None

    def _update_encoder_resolution(self) -> None:
        """Calculate encoder angular resolution based on bit count."""
        bits = int(self.config.encoder_bits)
        self._encoder_step_deg = 360.0 / (2 ** bits)

    def apply_config(self, config: CameraConfig) -> None:
        """Hot-reload configuration."""
        self.config = config.validate()
        self._update_encoder_resolution()
        # Clamp current position to new limits constrained by world boundaries
        p_min, p_max, t_min, t_max = self.get_effective_angular_limits()
        self.pan_deg = float(np.clip(self.pan_deg, p_min, p_max))
        self.tilt_deg = float(np.clip(self.tilt_deg, t_min, t_max))
        self._compute_measured_angles()

    def set_world_size(self, world_size: tuple[int, int]) -> None:
        """Update world bounds and re-clamp gimbal angles."""
        self.world_size = (int(world_size[0]), int(world_size[1]))
        p_min, p_max, t_min, t_max = self.get_effective_angular_limits()
        self.pan_deg = float(np.clip(self.pan_deg, p_min, p_max))
        self.tilt_deg = float(np.clip(self.tilt_deg, t_min, t_max))
        self._compute_measured_angles()

    def reset(self, pan_deg: float | None = None, tilt_deg: float | None = None) -> None:
        """Reset gimbal to home or specified angles, bounded by world borders."""
        raw_pan = float(self.config.home_pan_deg if pan_deg is None else pan_deg)
        raw_tilt = float(self.config.home_tilt_deg if tilt_deg is None else tilt_deg)
        p_min, p_max, t_min, t_max = self.get_effective_angular_limits()
        self.pan_deg = float(np.clip(raw_pan, p_min, p_max))
        self.tilt_deg = float(np.clip(raw_tilt, t_min, t_max))
        self.pan_vel_deg_s = 0.0
        self.tilt_vel_deg_s = 0.0
        self.pan_accel_deg_s2 = 0.0
        self.tilt_accel_deg_s2 = 0.0
        self.target_pan_deg = self.pan_deg
        self.target_tilt_deg = self.tilt_deg
        self._pan_backlash_slack = 0.0
        self._tilt_backlash_slack = 0.0
        self._last_fov_frame = None
        self._last_raw_mono = None
        self._compute_measured_angles()

    # -- Properties for GUI & Renderer compatibility ------------------
    @property
    def fov_width(self) -> int:
        return int(self.config.resolution_w)

    @property
    def fov_height(self) -> int:
        return int(self.config.resolution_h)

    def get_home(self) -> tuple[float, float]:
        """Return world coordinates (x, y) corresponding to home (0°, 0°)."""
        return (self.world_size[0] / 2.0, self.world_size[1] / 2.0)

    def get_pan_range(self) -> tuple[float, float]:
        return (float(self.config.pan_min_deg), float(self.config.pan_max_deg))

    def get_tilt_range(self) -> tuple[float, float]:
        return (float(self.config.tilt_min_deg), float(self.config.tilt_max_deg))

    def get_world_bounds_angular_limits(self) -> tuple[float, float, float, float]:
        """
        Calculate maximum pan/tilt angles such that the 640x480 FOV rectangle
        remains completely within the world scene boundaries [0, world_w] x [0, world_h].
        
        Returns: (pan_min, pan_max, tilt_min, tilt_max) in degrees.
        """
        half_w = self.config.resolution_w / 2.0
        half_h = self.config.resolution_h / 2.0
        max_pan = max(0.0, (self.world_size[0] / 2.0 - half_w) / max(1e-4, self.config.px_per_deg_h))
        max_tilt = max(0.0, (self.world_size[1] / 2.0 - half_h) / max(1e-4, self.config.px_per_deg_v))
        return (-max_pan, max_pan, -max_tilt, max_tilt)

    def get_effective_angular_limits(self) -> tuple[float, float, float, float]:
        """
        Return the effective (pan_min, pan_max, tilt_min, tilt_max) in degrees,
        taking into account both config limits and world boundaries.
        """
        w_p_min, w_p_max, w_t_min, w_t_max = self.get_world_bounds_angular_limits()
        p_min = max(self.config.pan_min_deg, w_p_min)
        p_max = min(self.config.pan_max_deg, w_p_max)
        t_min = max(self.config.tilt_min_deg, w_t_min)
        t_max = min(self.config.tilt_max_deg, w_t_max)
        if p_min > p_max:
            p_min, p_max = p_max, p_min
        if t_min > t_max:
            t_min, t_max = t_max, t_min
        return (p_min, p_max, t_min, t_max)

    def get_fov_center_world(self, use_measured: bool = False) -> tuple[float, float]:
        """
        Calculate current optical axis intersection with the 2D world plane (x, y).
        Home (0°, 0°) is at (world_w / 2, world_h / 2).
        Bounded so the 640x480 FOV rectangle never extends outside the world scene.

        Args:
            use_measured: use encoder-measured (quantized + noisy) angles
                instead of true angles (Plan Stage 2 measured-feedback mode).
        """
        home_x, home_y = self.get_home()
        if use_measured:
            meas_pan, meas_tilt = self.get_measured_angles()
        else:
            meas_pan, meas_tilt = self.pan_deg, self.tilt_deg
        cx = home_x + meas_pan * self.config.px_per_deg_h
        cy = home_y - meas_tilt * self.config.px_per_deg_v
        half_w = self.config.resolution_w / 2.0
        half_h = self.config.resolution_h / 2.0
        cx = float(np.clip(cx, half_w, max(half_w, self.world_size[0] - half_w)))
        cy = float(np.clip(cy, half_h, max(half_h, self.world_size[1] - half_h)))
        return (cx, cy)

    def get_fov_rect(self) -> tuple[float, float, float, float]:
        """
        Return the FOV bounding box in world coordinates: (x0, y0, x1, y1).
        Guaranteed to be completely within [0, 0, world_w, world_h].
        """
        cx, cy = self.get_fov_center_world()
        half_w = self.config.resolution_w / 2.0
        half_h = self.config.resolution_h / 2.0
        x0 = max(0.0, cx - half_w)
        y0 = max(0.0, cy - half_h)
        x1 = min(float(self.world_size[0]), cx + half_w)
        y1 = min(float(self.world_size[1]), cy + half_h)
        return (x0, y0, x1, y1)

    # -- Kinematics & Stepping ----------------------------------------
    def set_target_angles(self, pan_deg: float, tilt_deg: float) -> None:
        """Command target pointing angles, bounded by world borders."""
        w_p_min, w_p_max, w_t_min, w_t_max = self.get_world_bounds_angular_limits()
        p_min = max(self.config.pan_min_deg, w_p_min)
        p_max = min(self.config.pan_max_deg, w_p_max)
        t_min = max(self.config.tilt_min_deg, w_t_min)
        t_max = min(self.config.tilt_max_deg, w_t_max)
        self.target_pan_deg = float(np.clip(pan_deg, p_min, p_max))
        self.target_tilt_deg = float(np.clip(tilt_deg, t_min, t_max))

    def _apply_axis_kinematics(
        self,
        current_pos: float,
        current_vel: float,
        cmd_vel: float,
        max_speed: float,
        max_accel: float,
        pos_min: float,
        pos_max: float,
        backlash: float,
        current_slack: float,
        dt: float,
    ) -> tuple[float, float, float, float]:
        """
        Simulate single-axis motion with acceleration limit, velocity clamp,
        backlash hysteresis, and position end-stops.
        
        Returns: (new_pos, new_vel, accel, new_slack)
        """
        # Clamp commanded velocity to speed limit
        target_vel = float(np.clip(cmd_vel, -max_speed, max_speed))

        # Apply acceleration limit
        vel_diff = target_vel - current_vel
        max_delta_vel = max_accel * dt
        actual_delta_vel = float(np.clip(vel_diff, -max_delta_vel, max_delta_vel))
        new_vel = current_vel + actual_delta_vel
        accel = actual_delta_vel / max(1e-6, dt)

        # Damping & inertia lag filter (first-order equivalent of second-order mechanical system)
        # tau_mech ~ inertia / (damping_ratio * 2 * sqrt(inertia * k))
        tau_mech = max(0.005, self.config.inertia_kg_m2 / max(0.01, self.config.damping_ratio))
        alpha = dt / (tau_mech + dt)
        filtered_vel = current_vel + alpha * (new_vel - current_vel)

        # True mechanical acceleration achieved after inertia lag
        accel = (filtered_vel - current_vel) / max(1e-6, dt)

        # Raw displacement before backlash
        delta_pos = filtered_vel * dt

        # Backlash model
        effective_delta_pos = 0.0
        new_slack = current_slack

        if backlash > 1e-6:
            if delta_pos > 0:
                needed = backlash - new_slack
                if delta_pos >= needed:
                    effective_delta_pos = delta_pos - needed
                    new_slack = backlash
                else:
                    new_slack += delta_pos
                    effective_delta_pos = 0.0
            elif delta_pos < 0:
                needed = new_slack
                if abs(delta_pos) >= needed:
                    effective_delta_pos = delta_pos + needed
                    new_slack = 0.0
                else:
                    new_slack += delta_pos  # delta_pos is negative
                    effective_delta_pos = 0.0
        else:
            effective_delta_pos = delta_pos

        # Update position and apply hard travel stops
        raw_pos = current_pos + effective_delta_pos
        new_pos = float(np.clip(raw_pos, pos_min, pos_max))

        # If hard stop hit, kill velocity in direction of travel and update acceleration
        if (new_pos <= pos_min and filtered_vel < 0) or (new_pos >= pos_max and filtered_vel > 0):
            filtered_vel = 0.0
            accel = (filtered_vel - current_vel) / max(1e-6, dt)

        return new_pos, filtered_vel, accel, new_slack

    def update(
        self,
        dt: float,
        cmd_pan_vel: float | None = None,
        cmd_tilt_vel: float | None = None,
    ) -> PTZState:
        """
        Advance gimbal physics by time dt.
        If cmd_*_vel is provided, operates in velocity-control mode.
        Otherwise, moves toward target_pan_deg and target_tilt_deg via proportional rate.
        """
        dt_eff = float(np.clip(dt, 1e-4, 0.1))

        # Determine commanded velocities
        if cmd_pan_vel is not None:
            pan_cmd = float(cmd_pan_vel)
            self.target_pan_deg = self.pan_deg
        else:
            # Position-seeking velocity command
            pan_err = self.target_pan_deg - self.pan_deg
            pan_cmd = pan_err / max(dt_eff, 0.05)

        if cmd_tilt_vel is not None:
            tilt_cmd = float(cmd_tilt_vel)
            self.target_tilt_deg = self.tilt_deg
        else:
            tilt_err = self.target_tilt_deg - self.tilt_deg
            tilt_cmd = tilt_err / max(dt_eff, 0.05)

        # Effective travel limits constrained by world borders
        eff_pan_min, eff_pan_max, eff_tilt_min, eff_tilt_max = self.get_effective_angular_limits()

        # Update Pan Axis
        self.pan_deg, self.pan_vel_deg_s, self.pan_accel_deg_s2, self._pan_backlash_slack = (
            self._apply_axis_kinematics(
                current_pos=self.pan_deg,
                current_vel=self.pan_vel_deg_s,
                cmd_vel=pan_cmd,
                max_speed=self.config.max_pan_speed_deg_s,
                max_accel=self.config.max_pan_accel_deg_s2,
                pos_min=eff_pan_min,
                pos_max=eff_pan_max,
                backlash=self.config.backlash_deg,
                current_slack=self._pan_backlash_slack,
                dt=dt_eff,
            )
        )

        # Update Tilt Axis
        self.tilt_deg, self.tilt_vel_deg_s, self.tilt_accel_deg_s2, self._tilt_backlash_slack = (
            self._apply_axis_kinematics(
                current_pos=self.tilt_deg,
                current_vel=self.tilt_vel_deg_s,
                cmd_vel=tilt_cmd,
                max_speed=self.config.max_tilt_speed_deg_s,
                max_accel=self.config.max_tilt_accel_deg_s2,
                pos_min=eff_tilt_min,
                pos_max=eff_tilt_max,
                backlash=self.config.backlash_deg,
                current_slack=self._tilt_backlash_slack,
                dt=dt_eff,
            )
        )

        # Update simulated encoder measurement cache
        self._compute_measured_angles()

        return self.get_state()

    def _compute_measured_angles(self) -> tuple[float, float]:
        """
        Calculate and cache optical encoder measurements with quantization and noise.
        """
        q = max(1e-6, self._encoder_step_deg)
        quant_pan = round(self.pan_deg / q) * q
        quant_tilt = round(self.tilt_deg / q) * q

        noise_sigma = float(self.config.encoder_noise_deg)
        if noise_sigma > 1e-7:
            noise_pan = float(self.rng.normal(0.0, noise_sigma))
            noise_tilt = float(self.rng.normal(0.0, noise_sigma))
        else:
            noise_pan, noise_tilt = 0.0, 0.0

        self._measured_pan_deg = float(quant_pan + noise_pan)
        self._measured_tilt_deg = float(quant_tilt + noise_tilt)
        self._cached_pan_deg = self.pan_deg
        self._cached_tilt_deg = self.tilt_deg
        return (self._measured_pan_deg, self._measured_tilt_deg)

    def get_measured_angles(self) -> tuple[float, float]:
        """Return cached optical encoder measurements."""
        if (
            getattr(self, "_cached_pan_deg", None) != self.pan_deg
            or getattr(self, "_cached_tilt_deg", None) != self.tilt_deg
        ):
            self._compute_measured_angles()
        return (self._measured_pan_deg, self._measured_tilt_deg)

    def get_state(self) -> PTZState:
        """Capture complete runtime state."""
        meas_pan, meas_tilt = self.get_measured_angles()
        rect = self.get_fov_rect()
        settled = (
            abs(self.pan_vel_deg_s) < 0.05
            and abs(self.tilt_vel_deg_s) < 0.05
            and abs(self.target_pan_deg - self.pan_deg) < 0.05
            and abs(self.target_tilt_deg - self.tilt_deg) < 0.05
        )
        
        eff_pan_min, eff_pan_max, eff_tilt_min, eff_tilt_max = self.get_effective_angular_limits()
        in_limits = (
            eff_pan_min - 1e-4 <= self.pan_deg <= eff_pan_max + 1e-4
            and eff_tilt_min - 1e-4 <= self.tilt_deg <= eff_tilt_max + 1e-4
        )

        return PTZState(
            pan_deg=self.pan_deg,
            tilt_deg=self.tilt_deg,
            pan_vel_deg_s=self.pan_vel_deg_s,
            tilt_vel_deg_s=self.tilt_vel_deg_s,
            pan_accel_deg_s2=self.pan_accel_deg_s2,
            tilt_accel_deg_s2=self.tilt_accel_deg_s2,
            measured_pan_deg=meas_pan,
            measured_tilt_deg=meas_tilt,
            target_pan_deg=self.target_pan_deg,
            target_tilt_deg=self.target_tilt_deg,
            fov_rect=rect,
            in_limits=in_limits,
            settled=settled,
        )

    # -- FOV Viewport Extraction --------------------------------------
    def extract_fov(self, world_frame: np.ndarray) -> np.ndarray:
        """
        Extract 640x480 monochrome FOV viewport from the full world scene.
        Handles out-of-bounds FOV with black border padding.

        Returns:
            np.ndarray: 640x480 3-channel monochrome image (R=G=B) suitable
                        for display and downstream reticle overlay drawing.
        """
        # Get top-left corner in integer world coordinates
        x0, y0, _, _ = self.get_fov_rect()
        return self.extract_fov_at(world_frame, x0 + self.fov_width / 2.0, y0 + self.fov_height / 2.0)

    def extract_fov_at(self, world_frame: np.ndarray, cx: float, cy: float) -> np.ndarray:
        """
        Extract the FOV viewport centered at world pixels (cx, cy).

        Used by the simulation tick path to render the camera view at the
        disturbance-perturbed pose — mechanical jitter/vibration/platform
        drift shift where the camera actually looks without moving the true
        gimbal state (observation noise, not a physical move).

        Args:
            world_frame: full world scene (H×W×3 uint8).
            cx, cy: disturbed FOV center in world pixels (floats rounded
                to integer pixels, same as :meth:`extract_fov`).

        Returns:
            np.ndarray: resolution_h×resolution_w 3-channel monochrome image.
        """
        if world_frame is None:
            # Fallback black frame
            res_w, res_h = int(self.config.resolution_w), int(self.config.resolution_h)
            return np.zeros((res_h, res_w, 3), dtype=np.uint8)

        wh, ww = world_frame.shape[:2]
        res_w, res_h = int(self.config.resolution_w), int(self.config.resolution_h)

        ix0, iy0 = int(round(cx - res_w / 2.0)), int(round(cy - res_h / 2.0))
        ix1, iy1 = ix0 + res_w, iy0 + res_h

        # Compute intersection with world frame
        src_x0 = max(0, ix0)
        src_y0 = max(0, iy0)
        src_x1 = min(ww, ix1)
        src_y1 = min(wh, iy1)

        # Target placement inside 640x480 buffer
        dst_x0 = max(0, -ix0)
        dst_y0 = max(0, -iy0)
        dst_x1 = dst_x0 + max(0, src_x1 - src_x0)
        dst_y1 = dst_y0 + max(0, src_y1 - src_y0)

        # Allocate buffer (monochrome grayscale)
        raw_crop = np.zeros((res_h, res_w), dtype=np.uint8)

        if src_x1 > src_x0 and src_y1 > src_y0:
            world_crop = world_frame[src_y0:src_y1, src_x0:src_x1]
            # Ensure uint8
            if world_crop.dtype != np.uint8:
                world_crop = np.clip(world_crop, 0, 255).astype(np.uint8)
            # Handle channel shapes
            if world_crop.ndim == 3 and world_crop.shape[2] == 3:
                gray_crop = cv2.cvtColor(world_crop, cv2.COLOR_BGR2GRAY)
            elif world_crop.ndim == 3 and world_crop.shape[2] == 4:
                gray_crop = cv2.cvtColor(world_crop, cv2.COLOR_BGRA2GRAY)
            elif world_crop.ndim == 3 and world_crop.shape[2] == 1:
                gray_crop = world_crop.squeeze(-1)
            elif world_crop.ndim == 3:
                gray_crop = world_crop[:, :, 0]
            else:
                gray_crop = world_crop
            raw_crop[dst_y0:dst_y1, dst_x0:dst_x1] = gray_crop

        self._last_raw_mono = raw_crop

        # Convert to 3-channel grayscale (R=G=B) so overlays (crosshair, tracker ring) can be drawn in color
        fov_bgr = cv2.cvtColor(raw_crop, cv2.COLOR_GRAY2BGR)
        self._last_fov_frame = fov_bgr
        return fov_bgr

    @property
    def raw_monochrome(self) -> np.ndarray | None:
        """1-channel (480, 640) uint8 grayscale image."""
        return self._last_raw_mono

    def world_to_fov(self, world_x: float, world_y: float) -> tuple[float, float]:
        """Convert world coordinates to FOV image coordinates (0..640, 0..480)."""
        x0, y0, _, _ = self.get_fov_rect()
        return (world_x - x0, world_y - y0)

    def fov_to_world(self, fov_x: float, fov_y: float) -> tuple[float, float]:
        """Convert FOV image coordinates to world coordinates."""
        x0, y0, _, _ = self.get_fov_rect()
        return (fov_x + x0, fov_y + y0)

    def get_telemetry(self) -> dict[str, Any]:
        """Return telemetry dictionary."""
        st = self.get_state()
        return {
            "ptz": st.to_dict(),
            "optics": {
                "fov_deg_h": self.config.fov_deg_h,
                "fov_deg_v": self.config.fov_deg_v,
                "resolution": [self.config.resolution_w, self.config.resolution_h],
                "deg_per_px_h": self.config.deg_per_px_h,
                "deg_per_px_v": self.config.deg_per_px_v,
            }
        }

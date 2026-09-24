# io/simulation_source.py - Simulation-backed FrameSource adapter
from __future__ import annotations

from typing import Any, Optional

import numpy as np

from src.benchmark_io.frame_source import FramePacket, FrameSource, Point


class SimulationSource(FrameSource):
    """Wraps an existing SimulationSession or HeadlessSimulation as a FrameSource.

    Produces FramePacket at 30 fps (dt=1/30) by delegating to the simulation's
    ``step()``. Preserves ground_truth from remote terminal telemetry when
    available. PTZ and disturbance pipelines run normally (no bypass).

    Args:
        session: SimulationSession (gui/application/session.py) or HeadlessSimulation.
        fps: Target fps (default 30).
        world_size: Optional override; otherwise inferred from session.
    """

    def __init__(self, session: Any = None, fps: float = 30.0, world_size: tuple[int, int] | None = None, **kwargs):
        # Lazy / flexible construction: caller may pass configs to build a new session.
        if session is None:
            # Build default SimulationSession if none supplied
            from src.gui.application.session import SimulationSession
            session = SimulationSession(**kwargs)
            try:
                session.ensure_built()
            except Exception:
                pass
        self.session = session
        self.fps = float(fps) if fps else 30.0
        self._dt = 1.0 / self.fps if self.fps > 0 else 1.0 / 30.0
        self._frame_index = 0
        self._timestamp_s = 0.0
        self._world_size = world_size
        self._closed = False
        # Detect headless vs gui session by method signature
        self._is_headless = hasattr(session, "step") and "action" in getattr(session.step, "__code__", {}).co_varnames

    def _infer_world_size(self) -> tuple[int, int]:
        if self._world_size is not None:
            return self._world_size
        for attr in ("_scene_size", "world_size"):
            if hasattr(self.session, attr):
                try:
                    v = getattr(self.session, attr)
                    if isinstance(v, tuple) and len(v) == 2:
                        return (int(v[0]), int(v[1]))
                except Exception:
                    pass
        for cfg_attr in ("env_config",):
            try:
                cfg = getattr(self.session, cfg_attr, None)
                if cfg is not None:
                    return (int(cfg.world_width), int(cfg.world_height))
            except Exception:
                pass
        return (640, 480)

    def _extract_frame(self, step_result: Any) -> tuple[np.ndarray | None, np.ndarray | None, dict, Any]:
        """Normalise step() return into (frame, fov_frame, telemetry, raw)."""
        frame: np.ndarray | None = None
        fov: np.ndarray | None = None
        telemetry: dict = {}
        # HeadlessSimulation.step() -> (obs_dict, reward, terminated, truncated, info)
        if isinstance(step_result, tuple) and len(step_result) >= 1 and isinstance(step_result[0], dict):
            obs = step_result[0]
            frame = obs.get("frame")
            if frame is None:
                frame = obs.get("world_frame")
            if frame is None:
                frame = obs.get("image")
            fov = obs.get("fov_frame")
            if fov is None:
                fov = frame
            telemetry = obs
        # SimulationSession.step() -> FrameSnapshot
        elif hasattr(step_result, "world_frame") or hasattr(step_result, "fov_frame"):
            snap = step_result
            frame = getattr(snap, "world_frame", None)
            fv = getattr(snap, "fov_frame", None)
            fov = fv if fv is not None else frame
            telemetry = {
                "camera_telemetry": getattr(snap, "camera_telemetry", None),
                "pid_telemetry": getattr(snap, "pid_telemetry", None),
                "tracker_telemetry": getattr(snap, "tracker_telemetry", None),
                "terminals": getattr(snap, "terminals", None),
            }
        elif isinstance(step_result, dict):
            frame = step_result.get("frame")
            if frame is None:
                frame = step_result.get("world_frame")
            fov = step_result.get("fov_frame")
            if fov is None:
                fov = frame
            telemetry = step_result
        return frame, fov, telemetry, step_result

    def next(self) -> FramePacket | None:
        if self._closed:
            return None
        try:
            # Dispatch to correct step signature
            if self._is_headless:
                # headless expects optional action/dt kwargs
                result = self.session.step(dt=self._dt)
            else:
                # SimulationSession.step(dt)
                try:
                    result = self.session.step(self._dt)
                except TypeError:
                    result = self.session.step(dt=self._dt)
        except Exception:
            return None

        frame, fov, telemetry, _raw = self._extract_frame(result)
        if frame is None:
            return None
        if not isinstance(frame, np.ndarray):
            try:
                frame = np.asarray(frame, dtype=np.uint8)
            except Exception:
                return None
        if fov is None:
            fov = frame

        # Attempt to extract ground truth from telemetry
        gt: Optional[Point] = None
        try:
            terms = telemetry.get("terminals") if isinstance(telemetry, dict) else None
            if isinstance(terms, dict):
                # remote telemetry dict may contain terminal positions
                pass
            # Fallback: supervisor tracker telemetry may have target pos
            tracker = telemetry.get("tracker") if isinstance(telemetry, dict) else None
            if isinstance(tracker, dict) and "target_world" in tracker:
                tx, ty = tracker["target_world"]
                gt = Point(float(tx), float(ty))
        except Exception:
            gt = None

        ws = self._infer_world_size()
        # Ensure 3-channel uint8 for downstream
        if frame.ndim == 2:
            frame = np.stack([frame] * 3, axis=-1)
        if fov is not None and isinstance(fov, np.ndarray) and fov.ndim == 2:
            fov = np.stack([fov] * 3, axis=-1)

        pkt = FramePacket(
            image=frame,
            timestamp_s=float(self._timestamp_s),
            frame_index=int(self._frame_index),
            ground_truth=gt,
            fov_frame=fov if isinstance(fov, np.ndarray) else frame,
            world_size=ws,
            metadata=telemetry if isinstance(telemetry, dict) else {},
        )
        self._frame_index += 1
        self._timestamp_s += self._dt
        return pkt

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            if hasattr(self.session, "close"):
                self.session.close()
        except Exception:
            pass

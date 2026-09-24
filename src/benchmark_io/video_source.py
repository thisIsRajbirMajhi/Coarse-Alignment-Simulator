# io/video_source.py - Benchmark .mp4 VideoCapture adapter at 30 fps (PTZ bypass)
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import ClassVar
from pathlib import Path
from typing import Any, Optional

import cv2
import numpy as np

from src.common.config_base import BaseValidatedConfig
from src.benchmark_io.frame_source import FramePacket, FrameSource, Point

log = logging.getLogger(__name__)


@dataclass
class VideoSourceConfig(BaseValidatedConfig):
    """Config for VideoSource. Uses BaseValidatedConfig style."""
    target_width: int = 640
    target_height: int = 480
    fps: float = 30.0
    monochrome: bool = True
    loop: bool = False
    # PTZ bypass flag — when True, consumers must skip camera.update/disturbance
    ptz_bypass: bool = True

    LIMITS: ClassVar[dict] = {
        "target_width": (64, 4096),
        "target_height": (64, 4096),
        "fps": (1.0, 240.0),
    }
    DEFAULTS: ClassVar[dict] = {}


class VideoSource(FrameSource):
    """Reads .mp4 via cv2.VideoCapture at 30 fps, resizes to 640x480 monochrome.

    Preserves timestamps from container (CAP_PROP_POS_MSEC) when available,
    falls back to frame_index / fps. Sets ``ptz_bypass=True`` so callers can
    skip camera kinematics and disturbance injection.

    Produces same dict keys as SimulationSource: frame, fov_frame, world_size.

    Args:
        path: Path to .mp4 file.
        config: VideoSourceConfig (validated).
        ground_truth_csv: Optional CSV with per-frame ground truth (columns x,y).
        annotation_provider: Optional callable(frame_index) -> Point|None.
    """

    def __init__(
        self,
        path: str | Path,
        config: VideoSourceConfig | None = None,
        ground_truth_csv: str | Path | None = None,
        annotation_provider: Any | None = None,
    ):
        self.path = Path(path)
        self.config = (config or VideoSourceConfig()).validate()  # type: ignore[attr-defined]
        self.fps = float(self.config.fps) if float(self.config.fps) > 0 else 30.0
        self._dt = 1.0 / self.fps
        self.ptz_bypass: bool = bool(self.config.ptz_bypass)
        self.is_benchmark: bool = True  # alias for consumer checks
        self.world_size: tuple[int, int] = (int(self.config.target_width), int(self.config.target_height))
        self._cap: cv2.VideoCapture | None = None
        self._frame_index: int = 0
        self._closed: bool = False
        self._annotation_provider = annotation_provider
        self._gt_map: dict[int, Point] | None = None
        if ground_truth_csv is not None:
            self._gt_map = self._load_gt_csv(ground_truth_csv)
        self._open()

    def _load_gt_csv(self, csv_path: str | Path) -> dict[int, Point]:
        import csv
        gt: dict[int, Point] = {}
        try:
            with open(csv_path, newline="") as f:
                reader = csv.DictReader(f)
                for i, row in enumerate(reader):
                    try:
                        # Support headers x,y or ground_truth_x, ground_truth_y
                        x = row.get("x") or row.get("ground_truth_x") or row.get("gt_x") or row.get("px")
                        y = row.get("y") or row.get("ground_truth_y") or row.get("gt_y") or row.get("py")
                        if x is None or y is None:
                            # Fallback to first two numeric columns
                            vals = list(row.values())
                            x, y = vals[0], vals[1]
                        gt[i] = Point(float(x), float(y))
                    except Exception:
                        continue
        except Exception as e:
            log.debug("VideoSource GT CSV load skipped: %s", e)
        return gt

    def _open(self) -> None:
        if not self.path.exists():
            raise FileNotFoundError(f"VideoSource: file not found: {self.path}")
        cap = cv2.VideoCapture(str(self.path))
        if not cap.isOpened():
            raise IOError(f"VideoSource: failed to open {self.path}")
        # Hint fps; container fps may differ but we pace at config fps
        try:
            src_fps = float(cap.get(cv2.CAP_PROP_FPS) or 0)
            if src_fps > 0:
                log.debug("VideoSource %s container fps=%.2f -> pacing at %.2f", self.path, src_fps, self.fps)
        except Exception:
            pass
        self._cap = cap

    def _process_frame(self, raw: np.ndarray) -> np.ndarray:
        """Resize to target, monochrome-expand to 3ch if requested."""
        cfg = self.config
        img = raw
        # Resize to 640x480
        h, w = img.shape[:2]
        tw, th = int(cfg.target_width), int(cfg.target_height)
        if w != tw or h != th:
            try:
                img = cv2.resize(img, (tw, th), interpolation=cv2.INTER_AREA)
            except Exception as e:
                log.debug("VideoSource resize failed: %s", e)
        # Monochrome: convert to gray then back to 3ch so downstream always gets HxWx3
        if bool(cfg.monochrome):
            try:
                if img.ndim == 3 and img.shape[2] == 3:
                    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
                elif img.ndim == 3 and img.shape[2] == 4:
                    gray = cv2.cvtColor(img, cv2.COLOR_BGRA2GRAY)
                else:
                    gray = img if img.ndim == 2 else img[:, :, 0]
                img = cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)
            except Exception as e:
                log.debug("VideoSource monochrome convert skipped: %s", e)
        # Ensure uint8
        if img.dtype != np.uint8:
            img = np.clip(img, 0, 255).astype(np.uint8)
        # Ensure 3 channels
        if img.ndim == 2:
            img = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
        elif img.ndim == 3 and img.shape[2] == 1:
            img = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
        return img

    def next(self) -> FramePacket | None:
        if self._closed or self._cap is None:
            return None
        cap = self._cap
        try:
            ok, raw = cap.read()
        except Exception as e:
            log.debug("VideoSource read error: %s", e)
            return None
        if not ok or raw is None:
            # Loop if requested
            if bool(self.config.loop):
                try:
                    cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                    ok, raw = cap.read()
                    if not ok or raw is None:
                        return None
                    self._frame_index = 0
                except Exception:
                    return None
            else:
                return None

        # Preserve timestamp: prefer container pts (msec), fallback to index/fps
        timestamp_s: float
        try:
            msec = float(cap.get(cv2.CAP_PROP_POS_MSEC))
            # CAP_PROP_POS_MSEC is time of NEXT frame after read on some backends; use index fallback if 0
            if msec > 1e-6:
                # After read, msec corresponds to next frame; estimate current as msec - dt*1000
                # Safer to use frame_index based fallback if jump is irregular; we use msec as-is for monotonicity
                timestamp_s = msec / 1000.0
                # Ensure monotonic with index pacing (hybrid)
                expected = self._frame_index / self.fps
                # If container pts wildly off, prefer pacing
                if abs(timestamp_s - expected) > 1.0:
                    timestamp_s = expected
            else:
                timestamp_s = self._frame_index / self.fps
        except Exception:
            timestamp_s = self._frame_index / self.fps

        image = self._process_frame(raw)
        # fov_frame same as image in bypass mode (no cropping)
        fov_frame = image  # alias; copy not needed

        # Ground truth lookup
        gt: Optional[Point] = None
        try:
            if self._annotation_provider is not None:
                gt = self._annotation_provider(self._frame_index)
            elif self._gt_map is not None:
                gt = self._gt_map.get(self._frame_index)
        except Exception:
            gt = None

        pkt = FramePacket(
            image=image,
            timestamp_s=float(timestamp_s),
            frame_index=int(self._frame_index),
            ground_truth=gt,
            fov_frame=fov_frame,
            world_size=self.world_size,
            metadata={"ptz_bypass": True, "source": "video", "path": str(self.path)},
        )
        self._frame_index += 1
        return pkt

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            if self._cap is not None:
                self._cap.release()
        except Exception:
            pass
        self._cap = None

    # Backward-compat alias used by some callers
    def release(self) -> None:
        self.close()

    @property
    def frame_index(self) -> int:
        return self._frame_index

    def __len__(self) -> int:
        # Best-effort total frames
        if self._cap is None:
            return 0
        try:
            return int(self._cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        except Exception:
            return 0

# io/frame_source.py - Unified FrameSource interface (simulation & video)
from __future__ import annotations

import abc
from dataclasses import dataclass, field
from typing import Any, Optional

import numpy as np


@dataclass
class Point:
    """Ground-truth point in world coordinates (pixels or metres)."""
    x: float = 0.0
    y: float = 0.0

    def as_tuple(self) -> tuple[float, float]:
        return (float(self.x), float(self.y))


@dataclass
class FramePacket:
    """Unified frame container produced by any FrameSource at 30 fps.

    Attributes:
        image: HxWx3 uint8 frame (BGR/RGB); video source resized to 640x480 monochrome-expanded.
        timestamp_s: Presentation timestamp in seconds (monotonic, video preserves source pts).
        frame_index: Sequential index (0-based).
        ground_truth: Optional annotated target centre for benchmark scoring.
        fov_frame: Cropped FOV view (same as image when no PTZ, kept for dict compatibility).
        world_size: (width, height) of logical world / frame dimensions.
        metadata: Extra telemetry passthrough.
    """
    image: np.ndarray
    timestamp_s: float
    frame_index: int
    ground_truth: Optional[Point] = None
    fov_frame: Optional[np.ndarray] = None
    world_size: tuple[int, int] = (640, 480)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Produce canonical dict keys required by GUI/headless consumers.

        Guarantees keys: ``frame``, ``fov_frame``, ``world_size``.
        """
        fov = self.fov_frame if self.fov_frame is not None else self.image
        return {
            "frame": self.image,
            "fov_frame": fov,
            "world_size": self.world_size,
            "timestamp_s": self.timestamp_s,
            "frame_index": self.frame_index,
            "ground_truth": self.ground_truth,
            "metadata": self.metadata,
        }


class FrameSource(abc.ABC):
    """Abstract 30 fps frame source. Implementations: SimulationSource, VideoSource."""

    @abc.abstractmethod
    def next(self) -> FramePacket | None:
        """Return next FramePacket or None on EOS / error."""
        raise NotImplementedError

    @abc.abstractmethod
    def close(self) -> None:
        """Release underlying resources (idempotent)."""
        raise NotImplementedError

    # Context-manager support
    def __enter__(self) -> "FrameSource":
        return self

    def __exit__(self, *exc) -> None:
        try:
            self.close()
        except Exception:
            pass

    def __iter__(self):
        while True:
            pkt = self.next()
            if pkt is None:
                break
            yield pkt

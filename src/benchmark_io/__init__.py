# benchmark_io/__init__.py - FrameSource abstraction for simulation and benchmark video
from src.benchmark_io.frame_source import FramePacket, FrameSource, Point
from src.benchmark_io.simulation_source import SimulationSource
from src.benchmark_io.video_source import VideoSource, VideoSourceConfig

__all__ = [
    "FramePacket",
    "FrameSource",
    "Point",
    "SimulationSource",
    "VideoSource",
    "VideoSourceConfig",
]

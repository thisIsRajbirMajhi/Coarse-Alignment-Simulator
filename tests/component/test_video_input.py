# tests/component/test_video_input.py - Video benchmark adapter smoke tests
from __future__ import annotations

import pathlib
import tempfile

import cv2
import numpy as np
import pytest

from src.benchmark_io.frame_source import FramePacket, FrameSource, Point
from src.benchmark_io.video_source import VideoSource, VideoSourceConfig
from src.benchmark_io.simulation_source import SimulationSource


def _make_dummy_mp4(path: pathlib.Path, n_frames: int = 5, w: int = 800, h: int = 600, fps: float = 30.0):
    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    writer = cv2.VideoWriter(str(path), fourcc, fps, (w, h))
    assert writer.isOpened(), "VideoWriter open failed"
    for i in range(n_frames):
        img = np.zeros((h, w, 3), dtype=np.uint8)
        # moving white dot
        x = int((i / max(n_frames - 1, 1)) * (w - 20)) + 10
        y = h // 2
        cv2.circle(img, (x, y), 8, (255, 255, 255), -1)
        writer.write(img)
    writer.release()


def test_frame_packet_interface():
    pkt = FramePacket(image=np.zeros((480, 640, 3), dtype=np.uint8), timestamp_s=0.0, frame_index=0, ground_truth=Point(10, 20))
    d = pkt.to_dict()
    assert "frame" in d and "fov_frame" in d and "world_size" in d
    assert d["world_size"] == (640, 480)
    assert isinstance(d["ground_truth"], Point)
    assert issubclass(FrameSource, object)


def test_video_source_monochrome_resize_and_timestamps():
    with tempfile.TemporaryDirectory() as td:
        p = pathlib.Path(td) / "clip.mp4"
        _make_dummy_mp4(p, n_frames=6, w=800, h=600, fps=30.0)
        cfg = VideoSourceConfig(target_width=640, target_height=480, fps=30.0, monochrome=True, ptz_bypass=True).validate()
        vs = VideoSource(p, config=cfg)
        try:
            assert vs.ptz_bypass is True
            assert vs.is_benchmark is True
            packets = []
            for _ in range(6):
                pkt = vs.next()
                assert pkt is not None, "expected frame"
                # resize + monochrome -> 640x480x3
                assert pkt.image.shape == (480, 640, 3)
                # monochrome check: channels equal
                assert np.allclose(pkt.image[:, :, 0], pkt.image[:, :, 1])
                # timestamps monotonic
                assert pkt.timestamp_s >= 0
                # world_size key
                d = pkt.to_dict()
                assert d["frame"].shape == (480, 640, 3)
                assert d["world_size"] == (640, 480)
                packets.append(pkt)
            # fps pacing ~1/30
            if len(packets) >= 2:
                dt = packets[1].timestamp_s - packets[0].timestamp_s
                assert 0.01 < dt < 0.2
            # EOS returns None
            assert vs.next() is None
        finally:
            vs.close()


def test_simulation_source_same_interface():
    src = SimulationSource()
    try:
        pkt = src.next()
        assert pkt is not None
        d = pkt.to_dict()
        assert "frame" in d and "fov_frame" in d and "world_size" in d
        assert d["frame"].ndim == 3
    finally:
        src.close()


def test_session_benchmark_bypass_flag():
    from src.gui.application.session import SimulationSession, RunMode
    sess = SimulationSession(seed=0)
    assert sess.run_mode == RunMode.SIMULATION
    assert not sess.is_benchmark
    # no file: set_video_source should raise
    with pytest.raises((FileNotFoundError, IOError)):
        sess.set_video_source("nonexistent_xyz.mp4")
    # attach dummy video
    with tempfile.TemporaryDirectory() as td:
        p = pathlib.Path(td) / "clip.mp4"
        _make_dummy_mp4(p, n_frames=3)
        sess.set_video_source(p)
        assert sess.is_benchmark
        assert sess.run_mode == RunMode.BENCHMARK_VIDEO
        assert sess.video_source is not None
        # step should bypass PTZ (no exception)
        sess.ensure_built()
        snap = sess.step(dt=1/30)
        assert snap.fov_frame is not None
        assert snap.fov_frame.shape[1] == 640
        sess.clear_video_source()
        assert not sess.is_benchmark


def test_headless_benchmark_bypass():
    from src.simulation.headless import HeadlessSimulation
    sim = HeadlessSimulation(seed=0, max_steps=10)
    assert not sim.is_benchmark
    with tempfile.TemporaryDirectory() as td:
        p = pathlib.Path(td) / "clip.mp4"
        _make_dummy_mp4(p, n_frames=4)
        sim.set_video_source(p)
        assert sim.is_benchmark
        # step should consume video frame and skip camera.update/disturbance pose
        obs, _, _, _, _ = sim.step()
        assert "frame" in obs and "fov_frame" in obs and "world_size" in obs
        assert obs["fov_frame"].shape == (480, 640, 3)
        # monochrome property
        assert np.allclose(obs["fov_frame"][:, :, 0], obs["fov_frame"][:, :, 1])
        sim.clear_video_source()
        assert not sim.is_benchmark
    sim.close()

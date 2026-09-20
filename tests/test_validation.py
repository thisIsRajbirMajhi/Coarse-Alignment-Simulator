# tests/test_validation.py - Plan Stage 3: registry, comm receiver, validator lifecycle.
from __future__ import annotations

import numpy as np
import pytest

from common.protocol.beacon.frame import BeaconFrameParser
from local_terminal import (
    CommReceiver,
    CommSource,
    SignatureRegistry,
    TrackValidator,
    ValidationConfig,
    ber_from_snr_db,
)


def _parse_chips(chips):
    return BeaconFrameParser().parse([int(c) for c in chips])


def _rt001_registry():
    from remote_terminal import make_default_scenario
    return SignatureRegistry.from_scenario(make_default_scenario(1))


def _phot(snr_db=20.0, peak=140.0, centroid=(320.0, 240.0)):
    return {"snr_db": snr_db, "peak": peak, "centroid": centroid}


def test_registry_from_scenario():
    reg = _rt001_registry()
    assert reg.is_known("RT-001")
    assert not reg.is_known("RT-999")
    assert reg.wavelength_match_score("RT-001", 1550.0) == pytest.approx(1.0)
    assert reg.wavelength_match_score("RT-001", 1600.0) == pytest.approx(0.0)
    assert reg.wavelength_match_score("RT-001", 750.0) == -1.0  # out of band
    assert reg.wavelength_match_score("RT-999", 1550.0) == -1.0  # unknown


def test_ber_from_snr_db():
    assert ber_from_snr_db(32.0) == pytest.approx(0.0, abs=1e-9)
    assert ber_from_snr_db(6.0) == pytest.approx(0.0228, rel=0.05)
    assert ber_from_snr_db(20.0) < ber_from_snr_db(10.0)


def test_comm_receiver_parses_real_frame_offline():
    from remote_terminal.beacon_encoder import BeaconGenerator
    from common.protocol.beacon.navigation import NavigationState2D

    g = BeaconGenerator("RT-001", 1550.0)
    b = g.new_frame(NavigationState2D(timestamp_ms=0, position_x_m=1.0, position_y_m=2.0), 0.0)
    src = CommSource(position=(0.0, 0.0), emitting=True, power_w=0.5, chip_at=g.chip_at)
    rx = CommReceiver()
    simt = 0.0
    result = None
    for _ in range(12):
        simt += 1 / 30
        rx.update([src], (0.0, 0.0), simt, 1 / 30, 0.0, None)
        result = rx.try_parse()
        if result is not None:
            break
    assert result is not None and result.valid_crc
    assert result.payload.tid == "RT-001"
    assert result.payload.seq == 0
    assert float(result.payload.wl) == 1550.0
    assert rx.parsed_frames == 1


def test_comm_receiver_ber_flips_are_seeded_deterministic():
    from remote_terminal.beacon_encoder import BeaconGenerator
    from common.protocol.beacon.navigation import NavigationState2D

    def run(seed):
        g = BeaconGenerator("RT-001", 1550.0)
        g.new_frame(NavigationState2D(timestamp_ms=0, position_x_m=0.0, position_y_m=0.0), 0.0)
        src = CommSource(position=(0.0, 0.0), emitting=True, power_w=0.5, chip_at=g.chip_at)
        rx = CommReceiver()
        simt = 0.0
        for _ in range(12):
            simt += 1 / 30
            rx.update([src], (0.0, 0.0), simt, 1 / 30, 0.5, np.random.default_rng(seed))
        return list(rx.buffer)

    assert run(7) == run(7)
    assert run(7) != run(8)


def test_validator_happy_path_selects():
    from remote_terminal.beacon_encoder import BeaconGenerator
    from common.protocol.beacon.navigation import NavigationState2D

    g = BeaconGenerator("RT-001", 1550.0)
    val = TrackValidator(_rt001_registry())
    t = 0.0
    # Two consecutive frames: continuity (≥2 frames) then score → SELECTED.
    for seq in range(2):
        nav = NavigationState2D(timestamp_ms=int(t * 1000), position_x_m=5.0, position_y_m=6.0)
        b = g.new_frame(nav, t)
        res = _parse_chips(b.chips)
        assert res.valid_crc
        snap = val.ingest(res, _phot(), False, t + 0.34)
        t += 0.34
    assert snap.state == "SELECTED"
    assert snap.validated and snap.terminal_id == "RT-001"
    assert snap.score >= 0.60


def test_validator_stale_sequence_strikes_and_blacklists():
    from remote_terminal.beacon_encoder import BeaconGenerator
    from common.protocol.beacon.navigation import NavigationState2D

    g = BeaconGenerator("RT-001", 1550.0)
    val = TrackValidator(_rt001_registry())
    nav = NavigationState2D(timestamp_ms=0, position_x_m=0.0, position_y_m=0.0)
    b = g.new_frame(nav, 0.0)
    res = _parse_chips(b.chips)
    val.ingest(res, _phot(), False, 0.34)  # first frame recorded
    # Replay the SAME frame (stale sequence) three times → blacklist.
    for i in range(3):
        snap = val.ingest(res, _phot(), False, 0.7 + i * 0.34)
    assert snap.state == "REJECTED"
    assert snap.reject_reason in ("stale_sequence", "blacklisted")
    assert "RT-001" in val.blacklist
    assert snap.drop_track  # blacklisted tracks are abandoned


def test_validator_unknown_id_ignored_without_strike():
    from remote_terminal.beacon_encoder import BeaconGenerator
    from common.protocol.beacon.navigation import NavigationState2D

    g = BeaconGenerator("SPOOF-9", 1550.0)
    val = TrackValidator(_rt001_registry())
    nav = NavigationState2D(timestamp_ms=0, position_x_m=0.0, position_y_m=0.0)
    for i in range(2):
        b = g.new_frame(nav, i * 0.34)
        snap = val.ingest(_parse_chips(b.chips), _phot(), False, i * 0.34 + 0.34)
    assert snap.state == "REJECTED"
    assert snap.reject_reason == "unknown_id"
    assert snap.strikes == 0 and "SPOOF-9" not in val.blacklist
    assert snap.drop_track


def test_validator_low_score_strikes():
    from remote_terminal.beacon_encoder import BeaconGenerator
    from common.protocol.beacon.navigation import NavigationState2D

    g = BeaconGenerator("RT-001", 1550.0)
    val = TrackValidator(_rt001_registry())
    for i in range(2):
        nav = NavigationState2D(timestamp_ms=int(i * 340), position_x_m=0.0, position_y_m=0.0)
        b = g.new_frame(nav, i * 0.34)
        # Floor-level photometry: snr term 0, single-sample histories 0.5/0.5.
        snap = val.ingest(_parse_chips(b.chips), _phot(snr_db=6.0, peak=35.0), False,
                          i * 0.34 + 0.34)
    assert snap.state == "REJECTED"
    assert snap.reject_reason == "score_below_minimum"
    assert snap.strikes == 1


def test_validator_undecodable_abandons_track_without_blacklist():
    val = TrackValidator(_rt001_registry())
    snap = None
    for i in range(3):
        snap = val.ingest(None, None, True, i * 0.34)
    assert snap.state == "REJECTED"
    assert snap.reject_reason == "undecodable"
    assert snap.drop_track
    assert len(val.blacklist) == 0  # no TID known → nothing blacklisted


def test_headless_reaches_validated_selection():
    from disturbance.core.config import DisturbanceConfig
    from simulation.headless import HeadlessSimulation

    sim = HeadlessSimulation(seed=1, disturbance_config=DisturbanceConfig().validate())
    sim.reset(seed=1)
    final = None
    for _ in range(40):
        obs, _, _, _, _ = sim.step()
        final = (obs["tracker"].get("validation") or {})
        if final.get("validated"):
            break
    assert final.get("validated") is True
    assert final.get("terminal_id") == "RT-001"
    assert final.get("state") == "SELECTED"


def test_headless_validation_deterministic():
    from disturbance.core.config import DisturbanceConfig
    from simulation.headless import HeadlessSimulation

    def run():
        sim = HeadlessSimulation(seed=2, disturbance_config=DisturbanceConfig().validate())
        sim.reset(seed=2)
        out = []
        for _ in range(25):
            obs, _, _, _, _ = sim.step()
            out.append((obs["tracker"].get("validation") or {}))
        return out

    assert run() == run()


def test_beacon_off_never_validates():
    from disturbance.core.config import DisturbanceConfig
    from remote_terminal import make_default_scenario
    from simulation.headless import HeadlessSimulation

    scen = make_default_scenario(1)
    scen.terminals[0].power_enabled = False
    scen.validate()
    sim = HeadlessSimulation(seed=1, scenario_config=scen,
                             disturbance_config=DisturbanceConfig().validate())
    sim.reset(seed=1)
    for _ in range(15):
        obs, _, _, _, _ = sim.step()
    val = obs["tracker"].get("validation") or {}
    assert val.get("validated") is not True
    assert val.get("state") in ("IDLE", "DECODING")

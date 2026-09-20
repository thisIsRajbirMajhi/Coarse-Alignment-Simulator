# tests/test_remote_protocol.py - Navigation extension + sequence rules (RemoteTerminal.md §§72-73).
import struct

import pytest

from common.protocol.beacon import (
    CAP_NAVIGATION_STATE,
    NAV_EXTENSION_BYTES,
    BeaconFrame,
    BeaconFrameParser,
    BeaconPayload,
    PayloadDecoder,
    bytes_to_chips,
    decode_navigation_state,
    encode_navigation_state,
    frame_to_chips,
    NavigationState2D,
    sequence_is_newer,
)


def _nav_payload(seq=152, ts=12500, x=10342.5, y=-2410.75):
    nav = encode_navigation_state(NavigationState2D(ts, x, y))
    return BeaconPayload(tid="RT-001", token="RT-001", wl=1550, seq=seq,
                         capabilities=CAP_NAVIGATION_STATE, nav=nav)


def test_capability_bit_is_first_unused():
    assert CAP_NAVIGATION_STATE == 0x0001


def test_navigation_round_trip_within_float_tolerance():
    state = NavigationState2D(timestamp_ms=12500, position_x_m=10342.5, position_y_m=-2410.75)
    raw = encode_navigation_state(state)
    assert len(raw) == 12 == NAV_EXTENSION_BYTES
    assert raw == struct.pack(">Iff", 12500, 10342.5, -2410.75)  # big-endian IEEE-754
    back = decode_navigation_state(raw)
    assert back.timestamp_ms == 12500
    assert back.position_x_m == pytest.approx(10342.5)
    assert back.position_y_m == pytest.approx(-2410.75)


def test_encode_rejects_bad_input():
    with pytest.raises(TypeError):
        encode_navigation_state("nope")
    with pytest.raises(ValueError):
        encode_navigation_state(NavigationState2D(-1, 0.0, 0.0))
    with pytest.raises(ValueError):
        encode_navigation_state(NavigationState2D(2**32, 0.0, 0.0))
    with pytest.raises(ValueError):
        encode_navigation_state(NavigationState2D(0, float("inf"), 0.0))
    with pytest.raises(TypeError):
        decode_navigation_state("nope")
    with pytest.raises(ValueError):
        decode_navigation_state(b"\x00" * 11)
    with pytest.raises(ValueError):
        decode_navigation_state(b"\x00" * 13)


def test_extension_absent_on_legacy_payload():
    raw = BeaconPayload(tid="RT-001", token="ALPHA-7", wl=1550, seq=7).serialize()
    assert len(raw) == 21  # legacy size preserved
    decoded = PayloadDecoder.decode(raw)
    assert decoded.navigation_state is None
    assert decoded.sequence_number == 7


def test_extension_present_when_capability_set():
    decoded = PayloadDecoder.decode(_nav_payload().serialize())
    nav = decoded.navigation_state
    assert nav is not None
    assert (nav.timestamp_ms, nav.position_x_m, nav.position_y_m) == (
        12500, pytest.approx(10342.5), pytest.approx(-2410.75))
    assert decoded.sequence_number == 152
    assert decoded.capabilities & CAP_NAVIGATION_STATE


def test_malformed_extension_contained_as_absent():
    full = _nav_payload().serialize()
    truncated = full[:-3]  # capability bit set, nav cut short
    decoded = PayloadDecoder.decode(truncated)
    assert decoded.navigation_state is None  # no crash, treated as absent


def test_old_payload_compatibility():
    legacy = BeaconPayload(tid="RT-009", token="ECHO-9", wl=1064, seq=250,
                           network_id=3, capabilities=0).serialize()
    frame = BeaconFrame(payload=BeaconPayload.deserialize(legacy))
    result = BeaconFrameParser().parse(frame_to_chips(frame))
    assert result.valid_crc and result.reason == "OK"
    assert PayloadDecoder.decode(result.payload.serialize()).navigation_state is None


def test_crc_covers_extended_frame():
    wire = BeaconFrame(payload=_nav_payload()).to_bytes()
    tampered = bytearray(wire)
    tampered[-2] ^= 0xFF  # flip a navigation byte (last byte is CRC)
    parser = BeaconFrameParser()
    assert parser.parse(frame_to_chips(BeaconFrame(payload=_nav_payload()))).valid_crc
    bad = parser.parse(bytes_to_chips(bytes(tampered)))
    assert not bad.valid_crc and bad.reason == "CRC_MISMATCH"


def test_sequence_wrap_and_freshness():
    assert sequence_is_newer(0, 255)      # wrap: 255 -> 0 is newer
    assert sequence_is_newer(1, 255)
    assert sequence_is_newer(5, 4)
    assert not sequence_is_newer(3, 3)    # equal is never newer
    assert not sequence_is_newer(4, 5)
    assert not sequence_is_newer(255, 0)  # 0 -> 255 would be going backwards
    assert not sequence_is_newer(128, 0)  # half-ring ambiguity treated as stale
    # Parser uses modular freshness across the wrap.
    parser = BeaconFrameParser()
    mk = lambda s: frame_to_chips(BeaconFrame(payload=_nav_payload(seq=s)))
    assert parser.parse(mk(255), last_seq=254).is_new_frame is True
    assert parser.parse(mk(0), last_seq=255).is_new_frame is True
    assert parser.parse(mk(255), last_seq=255).is_new_frame is False
    assert parser.parse(mk(254), last_seq=255).is_new_frame is False


def test_last_known_location_temporal():
    # RemoteTerminal.md §73 exact scenario: t=10.0 at (1000, 500) a beacon
    # frame is created; at t=10.5 the terminal is at (1050, 500); decoding
    # the ORIGINAL frame must yield (1000, 500) @ t=10.0, not (1050, 500).
    from remote_terminal import BeaconGenerator
    gen = BeaconGenerator(terminal_id="RT-001", wavelength_nm=1550.0)
    first = gen.new_frame(NavigationState2D(10000, 1000.0, 500.0), 10.0)
    original_wire = first.frame_bytes
    gen.new_frame(NavigationState2D(10500, 1050.0, 500.0), 10.5)

    parsed = BeaconFrameParser().parse(frame_to_chips(
        BeaconFrame(payload=BeaconPayload.deserialize(original_wire[6:-1]))))
    assert parsed.valid_crc and parsed.reason == "OK"
    decoded = PayloadDecoder.decode(parsed.payload.serialize())
    nav = decoded.navigation_state
    assert nav is not None
    assert nav.timestamp_ms == 10000
    assert nav.position_x_m == pytest.approx(1000.0)
    assert nav.position_y_m == pytest.approx(500.0)

    # Same guarantee through the live manager: frozen sample vs live truth.
    from remote_terminal import RemoteTerminalManager, make_default_scenario
    mgr = RemoteTerminalManager(make_default_scenario(1), bounds=(2000, 2000), seed=1)
    mgr.update(0.5)
    live_pos = mgr.terminals[0].position_m.as_tuple()
    frozen_wire = mgr.terminals[0].generator.current.frame_bytes
    mgr.update(2.0)  # terminal moves on (constant velocity)
    assert mgr.terminals[0].position_m.as_tuple() != live_pos
    frozen = PayloadDecoder.decode(frozen_wire[6:-1])
    assert frozen.navigation_state.position_x_m == pytest.approx(live_pos[0], abs=0.5)
    assert frozen.navigation_state.position_y_m == pytest.approx(live_pos[1], abs=0.5)

# tests/test_photodiode_receiver.py - Tests for physical photodiode receiver SNR and BER.
import math
import pytest

from local_terminal.comm_receiver import (
    CommReceiver,
    CommSource,
    compute_photodiode_snr,
    ber_from_snr_db,
)


def test_compute_photodiode_snr_strong_signal():
    src = CommSource(
        position=(1000.0, 1000.0),
        emitting=True,
        power_w=0.5,
        wavelength_nm=1550.0,
        range_m=100.0,
        beam_diameter_m=0.5,
    )
    snr_db, ber, p_rx = compute_photodiode_snr([src], boresight=(1000.0, 1000.0))
    assert snr_db > 20.0
    assert ber < 1e-4
    assert p_rx > 0.0


def test_compute_photodiode_snr_faded_or_mispointed():
    src_strong = CommSource(
        position=(1000.0, 1000.0),
        emitting=True,
        power_w=0.5,
        wavelength_nm=1550.0,
        range_m=100.0,
        beam_diameter_m=0.5,
        pointing_error_deg=0.0,
    )
    src_mispointed = CommSource(
        position=(1000.0, 1000.0),
        emitting=True,
        power_w=0.5,
        wavelength_nm=1550.0,
        range_m=100.0,
        beam_diameter_m=0.5,
        pointing_error_deg=0.5,  # Large pointing error relative to beam waist
    )
    snr_good, ber_good, p_good = compute_photodiode_snr([src_strong], boresight=(1000.0, 1000.0))
    snr_faded, ber_faded, p_faded = compute_photodiode_snr([src_mispointed], boresight=(1000.0, 1000.0))

    assert p_good > p_faded
    assert snr_good > snr_faded
    assert ber_good <= ber_faded


def test_comm_receiver_physical_update():
    from remote_terminal.beacon_encoder import BeaconGenerator
    from common.protocol.beacon.navigation import NavigationState2D

    g = BeaconGenerator("RT-001", 1550.0)
    g.new_frame(NavigationState2D(timestamp_ms=0, position_x_m=0.0, position_y_m=0.0), 0.0)

    src = CommSource(
        position=(1000.0, 1000.0),
        emitting=True,
        power_w=0.5,
        chip_at=g.chip_at,
        wavelength_nm=1550.0,
        range_m=100.0,
        beam_diameter_m=0.5,
    )
    rx = CommReceiver()
    simt = 0.0
    for _ in range(15):
        simt += 1 / 30
        rx.update([src], (1000.0, 1000.0), simt, 1 / 30)

    assert rx.last_snr_pd_db > 20.0
    assert rx.last_ber < 1e-4
    assert rx.last_p_rx_w > 0.0
    res = rx.try_parse()
    assert res is not None and res.valid_crc

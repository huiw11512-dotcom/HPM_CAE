import numpy as np
import pytest

from hpm_platform.physics.power_amplifier import (
    digital_predistort,
    memoryless_pa,
    rapp_am_am,
)


def test_rapp_curve_is_monotone_and_bounded():
    drive = np.linspace(0.0, 20.0, 2000)
    output = rapp_am_am(drive, saturation_amplitude=1.0, smoothness=3.0)
    assert np.all(np.diff(output) >= -1e-12)
    assert output[-1] < 1.001
    assert output[0] == 0.0


def test_predistortion_round_trip_in_reachable_region():
    desired = np.array([0.2, 0.55, 0.82]) * np.exp(1j * np.array([0.1, -0.4, 1.1]))
    drive = digital_predistort(
        desired,
        saturation_amplitude=1.0,
        smoothness=3.0,
        maximum_phase_deg=12.0,
        drive_limit=1.2,
    )
    actual = memoryless_pa(
        drive,
        saturation_amplitude=1.0,
        smoothness=3.0,
        maximum_phase_deg=12.0,
    )
    assert np.allclose(actual, desired, atol=1e-8, rtol=1e-8)


def test_predistortion_respects_drive_limit():
    desired = np.array([10.0 + 0.0j])
    drive = digital_predistort(desired, drive_limit=1.1)
    assert np.max(np.abs(drive)) <= 1.1 + 1e-12


def test_invalid_pa_parameter_raises():
    with pytest.raises(ValueError):
        rapp_am_am(np.array([1.0]), saturation_amplitude=0.0)

"""Memoryless normalized power-amplifier models and digital predistortion.

The model is deliberately dimensionless.  It is intended to expose how
amplitude compression and AM/PM conversion distort an array field pattern; it
is not a device-specific power-amplifier model and contains no absolute output
power, voltage, thermal, or reliability parameters.
"""
from __future__ import annotations

import numpy as np


def rapp_am_am(
    input_amplitude: np.ndarray | float,
    *,
    saturation_amplitude: float = 1.0,
    smoothness: float = 3.0,
) -> np.ndarray:
    """Return the Rapp AM/AM output amplitude.

    Parameters
    ----------
    input_amplitude:
        Non-negative normalized drive magnitude.
    saturation_amplitude:
        Normalized soft-saturation scale.
    smoothness:
        Rapp smoothness exponent.  Larger values approach hard limiting.
    """
    amplitude = np.asarray(input_amplitude, dtype=float)
    if np.any(amplitude < 0):
        raise ValueError("input_amplitude must be non-negative")
    if saturation_amplitude <= 0 or smoothness <= 0:
        raise ValueError("saturation_amplitude and smoothness must be positive")
    ratio = amplitude / float(saturation_amplitude)
    return amplitude / (1.0 + ratio ** (2.0 * smoothness)) ** (1.0 / (2.0 * smoothness))


def am_pm_phase_rad(
    input_amplitude: np.ndarray | float,
    *,
    saturation_amplitude: float = 1.0,
    maximum_phase_deg: float = 12.0,
) -> np.ndarray:
    """Return a bounded, monotone normalized AM/PM phase shift in radians."""
    amplitude = np.asarray(input_amplitude, dtype=float)
    if np.any(amplitude < 0):
        raise ValueError("input_amplitude must be non-negative")
    if saturation_amplitude <= 0:
        raise ValueError("saturation_amplitude must be positive")
    ratio_sq = (amplitude / float(saturation_amplitude)) ** 2
    return np.deg2rad(float(maximum_phase_deg)) * ratio_sq / (1.0 + ratio_sq)


def memoryless_pa(
    drive: np.ndarray,
    *,
    saturation_amplitude: float = 1.0,
    smoothness: float = 3.0,
    maximum_phase_deg: float = 12.0,
) -> np.ndarray:
    """Apply the normalized memoryless PA model to complex element drives."""
    x = np.asarray(drive, dtype=complex)
    amplitude = np.abs(x)
    output_amplitude = rapp_am_am(
        amplitude,
        saturation_amplitude=saturation_amplitude,
        smoothness=smoothness,
    )
    phase = np.angle(x) + am_pm_phase_rad(
        amplitude,
        saturation_amplitude=saturation_amplitude,
        maximum_phase_deg=maximum_phase_deg,
    )
    return output_amplitude * np.exp(1j * phase)


def digital_predistort(
    desired_output: np.ndarray,
    *,
    saturation_amplitude: float = 1.0,
    smoothness: float = 3.0,
    maximum_phase_deg: float = 12.0,
    drive_limit: float = 1.2,
    bisection_iterations: int = 48,
) -> np.ndarray:
    """Invert the normalized PA element-wise using bounded bisection.

    Desired magnitudes that cannot be reached below ``drive_limit`` are clipped
    to the largest reachable output.  The phase is pre-rotated to compensate
    the AM/PM curve.
    """
    desired = np.asarray(desired_output, dtype=complex)
    if drive_limit <= 0 or bisection_iterations < 1:
        raise ValueError("drive_limit and bisection_iterations must be positive")

    desired_amplitude = np.abs(desired)
    upper = np.full(desired_amplitude.shape, float(drive_limit), dtype=float)
    lower = np.zeros_like(upper)
    reachable = rapp_am_am(
        upper,
        saturation_amplitude=saturation_amplitude,
        smoothness=smoothness,
    )
    target = np.minimum(desired_amplitude, reachable)

    for _ in range(int(bisection_iterations)):
        midpoint = 0.5 * (lower + upper)
        output = rapp_am_am(
            midpoint,
            saturation_amplitude=saturation_amplitude,
            smoothness=smoothness,
        )
        needs_more_drive = output < target
        lower = np.where(needs_more_drive, midpoint, lower)
        upper = np.where(needs_more_drive, upper, midpoint)

    drive_amplitude = 0.5 * (lower + upper)
    phase_correction = am_pm_phase_rad(
        drive_amplitude,
        saturation_amplitude=saturation_amplitude,
        maximum_phase_deg=maximum_phase_deg,
    )
    return drive_amplitude * np.exp(1j * (np.angle(desired) - phase_correction))

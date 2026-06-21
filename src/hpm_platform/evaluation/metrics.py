"""Metrics shared by the demo and future experiment runners."""
from __future__ import annotations

import numpy as np


def angular_error_deg(
    estimated: tuple[float, float],
    truth: tuple[float, float],
) -> float:
    """Great-circle angular separation between two (theta, phi) directions."""
    def vec(direction: tuple[float, float]) -> np.ndarray:
        theta, phi = np.deg2rad(direction)
        return np.array([np.sin(theta) * np.cos(phi), np.sin(theta) * np.sin(phi), np.cos(theta)])

    dot = np.clip(np.dot(vec(estimated), vec(truth)), -1.0, 1.0)
    return float(np.rad2deg(np.arccos(dot)))


def response_ratio_db(numerator: float, denominator: float) -> float:
    return float(20.0 * np.log10(max(numerator, 1e-15) / max(denominator, 1e-15)))


def focal_peak_error_lambda(
    intensity: np.ndarray,
    x_lambda: np.ndarray,
    z_lambda: np.ndarray,
    requested_focus_lambda: tuple[float, float],
) -> tuple[float, tuple[float, float]]:
    idx = np.unravel_index(np.nanargmax(intensity), intensity.shape)
    peak = (float(x_lambda[idx[1]]), float(z_lambda[idx[0]]))
    error = float(np.hypot(peak[0] - requested_focus_lambda[0], peak[1] - requested_focus_lambda[1]))
    return error, peak


def outside_region_fraction(
    values: np.ndarray,
    x_lambda: np.ndarray,
    z_lambda: np.ndarray,
    center_lambda: tuple[float, float],
    radius_lambda: float,
    threshold: float,
) -> float:
    xx, zz = np.meshgrid(x_lambda, z_lambda, indexing="xy")
    outside = (xx - center_lambda[0]) ** 2 + (zz - center_lambda[1]) ** 2 > radius_lambda**2
    if not np.any(outside):
        return 0.0
    return float(np.mean(np.asarray(values)[outside] >= threshold))

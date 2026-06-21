"""Normalized transmit-field shaping baselines."""
from __future__ import annotations

import numpy as np

from hpm_platform.physics.array_geometry import RectangularArray


def normalized_intensity(field: np.ndarray) -> np.ndarray:
    """Return |field|^2 normalized to its finite maximum."""
    intensity = np.abs(np.asarray(field)) ** 2
    maximum = np.nanmax(intensity)
    return intensity / maximum if maximum > 0 else intensity


def focus_on_xz_plane(
    array: RectangularArray,
    focus_point_m: np.ndarray,
    x_m: np.ndarray,
    z_m: np.ndarray,
) -> tuple[np.ndarray, np.ndarray]:
    """Phase-conjugate focus and normalized intensity on y=0 plane."""
    xx, zz = np.meshgrid(np.asarray(x_m, float), np.asarray(z_m, float), indexing="xy")
    points = np.column_stack((xx.ravel(), np.zeros(xx.size), zz.ravel()))
    weights = array.phase_conjugate_focus_weights(focus_point_m)
    coherence = array.near_field_coherence(weights, points).reshape(xx.shape)
    return coherence, weights

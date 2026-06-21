"""Forward and forward-backward spatial smoothing for rectangular arrays."""
from __future__ import annotations

from dataclasses import dataclass
import numpy as np

from hpm_platform.physics.array_geometry import RectangularArray


@dataclass(frozen=True)
class SpatialSmoothingResult:
    covariance: np.ndarray
    subarray: RectangularArray
    n_subarrays: int
    subarray_nx: int
    subarray_ny: int
    forward_backward: bool


def spatially_smoothed_covariance(
    x: np.ndarray,
    array: RectangularArray,
    subarray_nx: int,
    subarray_ny: int,
    *,
    forward_backward: bool = True,
    diagonal_loading: float = 0.0,
) -> SpatialSmoothingResult:
    """Average covariance matrices from all overlapping URA subarrays."""

    data = np.asarray(x, dtype=complex)
    if data.ndim != 2:
        raise ValueError("x must have shape (sensors, snapshots)")
    if data.shape[0] != array.n_elements:
        raise ValueError("x sensor count does not match array")
    if data.shape[1] < 2:
        raise ValueError("At least two snapshots are required")
    if not 1 <= subarray_nx <= array.nx or not 1 <= subarray_ny <= array.ny:
        raise ValueError("Subarray dimensions must lie within the parent array")
    if diagonal_loading < 0:
        raise ValueError("diagonal_loading must be non-negative")

    cube = data.reshape(array.nx, array.ny, data.shape[1])
    m_sub = subarray_nx * subarray_ny
    covariance = np.zeros((m_sub, m_sub), dtype=complex)
    n_subarrays = 0

    for ix in range(array.nx - subarray_nx + 1):
        for iy in range(array.ny - subarray_ny + 1):
            sub_snapshots = cube[
                ix : ix + subarray_nx,
                iy : iy + subarray_ny,
                :,
            ].reshape(m_sub, data.shape[1])
            covariance += (sub_snapshots @ np.conj(sub_snapshots.T)) / data.shape[1]
            n_subarrays += 1

    covariance /= n_subarrays
    if forward_backward:
        exchange = np.fliplr(np.eye(m_sub))
        covariance = 0.5 * (
            covariance + exchange @ np.conj(covariance) @ exchange
        )

    covariance = 0.5 * (covariance + np.conj(covariance.T))
    if diagonal_loading > 0:
        scale = max(float(np.trace(covariance).real / m_sub), np.finfo(float).tiny)
        covariance = covariance + diagonal_loading * scale * np.eye(m_sub)

    subarray = RectangularArray(
        nx=subarray_nx,
        ny=subarray_ny,
        frequency_hz=array.frequency_hz,
        dx_m=array.dx_m,
        dy_m=array.dy_m,
    )
    return SpatialSmoothingResult(
        covariance=covariance,
        subarray=subarray,
        n_subarrays=n_subarrays,
        subarray_nx=subarray_nx,
        subarray_ny=subarray_ny,
        forward_backward=forward_backward,
    )

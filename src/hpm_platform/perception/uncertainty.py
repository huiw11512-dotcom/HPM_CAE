"""Local 2-D DOA uncertainty extraction from a subspace spectrum."""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from hpm_platform.physics.array_geometry import RectangularArray


@dataclass(frozen=True)
class LocalDoaUncertainty:
    estimate_deg: tuple[float, float]
    posterior_mean_deg: tuple[float, float]
    covariance_deg2: np.ndarray
    theta_grid_deg: np.ndarray
    phi_grid_deg: np.ndarray
    posterior: np.ndarray
    principal_std_deg: np.ndarray
    principal_axes: np.ndarray


def _axis(center: float, radius: float, step: float, lower: float | None = None, upper: float | None = None) -> np.ndarray:
    start = center - radius
    stop = center + radius
    if lower is not None:
        start = max(start, lower)
    if upper is not None:
        stop = min(stop, upper)
    count = int(np.floor((stop - start) / step + 0.5))
    values = start + step * np.arange(count + 1)
    if values[-1] < stop - 1e-9:
        values = np.r_[values, stop]
    return values


def local_music_posterior_covariance(
    covariance: np.ndarray,
    array: RectangularArray,
    estimate_deg: tuple[float, float],
    n_sources: int,
    *,
    radius_deg: float = 3.0,
    grid_step_deg: float = 0.35,
    temperature: float = 0.55,
    std_floor_deg: float = 0.45,
    std_ceiling_deg: float = 8.0,
) -> LocalDoaUncertainty:
    """Approximate a local angular posterior and return its 2x2 covariance.

    The posterior is a tempered normalization of the MUSIC pseudospectrum in a
    small neighborhood around the continuous PAWR estimate.  A quantization
    floor prevents unrealistically tiny covariance from a finite numerical
    grid.  This is a numerical uncertainty proxy, not a hardware-calibrated
    confidence bound.
    """

    if radius_deg <= 0 or grid_step_deg <= 0 or temperature <= 0:
        raise ValueError("radius, grid step, and temperature must be positive")
    if std_floor_deg <= 0 or std_ceiling_deg < std_floor_deg:
        raise ValueError("invalid uncertainty standard-deviation bounds")
    r = np.asarray(covariance, dtype=complex)
    if r.shape != (array.n_elements, array.n_elements):
        raise ValueError("covariance shape does not match array")
    if not 1 <= int(n_sources) < array.n_elements:
        raise ValueError("n_sources must lie between 1 and M-1")

    r = 0.5 * (r + np.conj(r.T))
    eigenvalues, eigenvectors = np.linalg.eigh(r)
    order = np.argsort(eigenvalues)[::-1]
    signal_subspace = eigenvectors[:, order[: int(n_sources)]]

    theta0, phi0 = float(estimate_deg[0]), float(estimate_deg[1])
    theta = _axis(theta0, radius_deg, grid_step_deg, 0.1, 89.9)
    phi = _axis(phi0, radius_deg, grid_step_deg)
    tt, pp = np.meshgrid(theta, phi, indexing="ij")
    steering = array.steering_matrix(tt.ravel(), pp.ravel())
    norm_sq = np.sum(np.abs(steering) ** 2, axis=0)
    projection = np.conj(signal_subspace.T) @ steering
    denominator = np.maximum(
        norm_sq - np.sum(np.abs(projection) ** 2, axis=0),
        np.finfo(float).eps,
    )
    log_spectrum = -np.log(denominator)
    log_probability = (log_spectrum - np.max(log_spectrum)) / float(temperature)
    probability = np.exp(np.clip(log_probability, -80.0, 0.0))
    probability = probability / max(float(np.sum(probability)), np.finfo(float).tiny)

    coordinates = np.column_stack((tt.ravel(), pp.ravel()))
    mean = probability @ coordinates
    offsets = coordinates - mean[None, :]
    covariance_deg2 = (offsets.T * probability) @ offsets
    covariance_deg2 += np.eye(2) * (grid_step_deg**2 / 12.0)

    eigenvalues_cov, eigenvectors_cov = np.linalg.eigh(0.5 * (covariance_deg2 + covariance_deg2.T))
    eigenvalues_cov = np.clip(
        eigenvalues_cov,
        float(std_floor_deg) ** 2,
        float(std_ceiling_deg) ** 2,
    )
    covariance_deg2 = (eigenvectors_cov * eigenvalues_cov) @ eigenvectors_cov.T
    return LocalDoaUncertainty(
        estimate_deg=(theta0, phi0),
        posterior_mean_deg=(float(mean[0]), float(mean[1])),
        covariance_deg2=covariance_deg2,
        theta_grid_deg=theta,
        phi_grid_deg=phi,
        posterior=probability.reshape(tt.shape),
        principal_std_deg=np.sqrt(eigenvalues_cov),
        principal_axes=eigenvectors_cov,
    )

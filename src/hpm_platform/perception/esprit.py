"""Gridless two-dimensional ESPRIT baseline for uniform rectangular arrays."""
from __future__ import annotations

from dataclasses import dataclass
import numpy as np

from hpm_platform.physics.array_geometry import RectangularArray


@dataclass(frozen=True)
class EspritResult:
    estimates: list[tuple[float, float]]
    spatial_frequencies_x: np.ndarray
    spatial_frequencies_y: np.ndarray
    eigenvalues: np.ndarray
    valid: np.ndarray


def esprit_2d_from_covariance(
    covariance: np.ndarray,
    array: RectangularArray,
    n_sources: int,
) -> EspritResult:
    """Estimate paired 2-D directions using least-squares shift invariance.

    Pairing is obtained by diagonalizing the x-shift operator and expressing
    the y-shift operator in the same eigenbasis.  Invalid estimates outside the
    visible unit disk are retained in ``valid`` but excluded from ``estimates``.
    """

    value = np.asarray(covariance, dtype=complex)
    m = array.n_elements
    if value.shape != (m, m):
        raise ValueError("covariance shape does not match array")
    if not 1 <= n_sources < min(array.nx * (array.ny - 1), array.ny * (array.nx - 1)):
        raise ValueError("n_sources is incompatible with the array selections")

    value = 0.5 * (value + np.conj(value.T))
    eigenvalues, eigenvectors = np.linalg.eigh(value)
    order = np.argsort(eigenvalues)[::-1]
    eigenvalues = np.real(eigenvalues[order])
    signal = eigenvectors[:, order[:n_sources]].reshape(array.nx, array.ny, n_sources)

    x1 = signal[:-1, :, :].reshape((array.nx - 1) * array.ny, n_sources)
    x2 = signal[1:, :, :].reshape((array.nx - 1) * array.ny, n_sources)
    y1 = signal[:, :-1, :].reshape(array.nx * (array.ny - 1), n_sources)
    y2 = signal[:, 1:, :].reshape(array.nx * (array.ny - 1), n_sources)
    psi_x = np.linalg.pinv(x1) @ x2
    psi_y = np.linalg.pinv(y1) @ y2

    eig_x, transform = np.linalg.eig(psi_x)
    transform_inv = np.linalg.pinv(transform)
    paired_y_operator = transform_inv @ psi_y @ transform
    eig_y = np.diag(paired_y_operator)

    mu_x = np.angle(eig_x)
    mu_y = np.angle(eig_y)
    u = mu_x / (array.wave_number * float(array.dx_m))
    v = mu_y / (array.wave_number * float(array.dy_m))
    radius = np.sqrt(u**2 + v**2)
    valid = np.isfinite(radius) & (radius <= 1.0 + 1e-6)

    estimates: list[tuple[float, float]] = []
    for ux, vy, is_valid in zip(u, v, valid):
        if not bool(is_valid):
            continue
        theta = float(np.rad2deg(np.arcsin(np.clip(np.hypot(ux, vy), 0.0, 1.0))))
        phi = float(np.rad2deg(np.arctan2(vy, ux)))
        estimates.append((theta, phi))
    estimates.sort(key=lambda pair: (pair[0], pair[1]))
    return EspritResult(
        estimates=estimates,
        spatial_frequencies_x=mu_x,
        spatial_frequencies_y=mu_y,
        eigenvalues=eigenvalues,
        valid=valid,
    )

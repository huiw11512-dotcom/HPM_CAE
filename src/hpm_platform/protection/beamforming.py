"""Receive-side conventional, MVDR, and LCMV beamforming baselines."""
from __future__ import annotations

import numpy as np

from hpm_platform.physics.array_geometry import RectangularArray


def covariance_matrix(x: np.ndarray) -> np.ndarray:
    x = np.asarray(x, dtype=complex)
    return (x @ np.conj(x.T)) / x.shape[1]


def diagonal_load(r: np.ndarray, loading_factor: float) -> np.ndarray:
    if loading_factor < 0:
        raise ValueError("loading_factor must be nonnegative")
    m = r.shape[0]
    return r + loading_factor * np.trace(r).real / m * np.eye(m)


def mvdr_weights(
    r: np.ndarray,
    steering: np.ndarray,
    loading_factor: float = 0.0,
) -> np.ndarray:
    """Distortionless MVDR weights."""
    loaded = diagonal_load(np.asarray(r, complex), loading_factor)
    a = np.asarray(steering, complex).reshape(-1)
    solved = np.linalg.solve(loaded, a)
    denominator = np.vdot(a, solved)
    if np.abs(denominator) < np.finfo(float).eps:
        raise np.linalg.LinAlgError("Degenerate MVDR normalization")
    return solved / denominator


def lcmv_weights(
    r: np.ndarray,
    constraints: np.ndarray,
    responses: np.ndarray,
    loading_factor: float = 0.0,
) -> np.ndarray:
    """Linearly constrained minimum-variance weights.

    ``constraints`` has shape (M, K), with C^H w = f.
    """
    loaded = diagonal_load(np.asarray(r, complex), loading_factor)
    c = np.asarray(constraints, complex)
    f = np.asarray(responses, complex).reshape(-1)
    if c.ndim != 2 or c.shape[1] != f.size:
        raise ValueError("constraints must have shape (M, K) and responses shape (K,)")
    inv_c = np.linalg.solve(loaded, c)
    gram = np.conj(c.T) @ inv_c
    return inv_c @ np.linalg.solve(gram, f)


def output_sinr_db(
    weights: np.ndarray,
    array: RectangularArray,
    desired_direction: tuple[float, float],
    interferer_direction: tuple[float, float],
    desired_power: float,
    interferer_power: float,
    noise_power: float,
) -> float:
    """Analytic output SINR for one desired and one interfering source."""
    w = np.asarray(weights, complex).reshape(-1)
    a_s = array.steering_vector(*desired_direction)
    a_i = array.steering_vector(*interferer_direction)
    signal = desired_power * np.abs(np.vdot(w, a_s)) ** 2
    interference = interferer_power * np.abs(np.vdot(w, a_i)) ** 2
    noise = noise_power * np.vdot(w, w).real
    return float(10.0 * np.log10(signal / max(interference + noise, np.finfo(float).tiny)))

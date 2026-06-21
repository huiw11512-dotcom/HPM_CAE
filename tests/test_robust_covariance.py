import numpy as np

from hpm_platform.perception.music import MusicGridScanner
from hpm_platform.perception.robust_covariance import (
    adaptive_spatially_smoothed_covariance,
    bttb_projection,
    gaussian_angular_prior,
    pawr_estimate,
)
from hpm_platform.physics.array_geometry import RectangularArray
from hpm_platform.signal.multipath import CoherentEmitter, CoherentPath, simulate_coherent_multipath


def _lag_values(matrix: np.ndarray, nx: int, ny: int, lag: tuple[int, int]) -> list[complex]:
    values = []
    for ix in range(nx):
        for iy in range(ny):
            jx, jy = ix - lag[0], iy - lag[1]
            if 0 <= jx < nx and 0 <= jy < ny:
                p = ix * ny + iy
                q = jx * ny + jy
                values.append(matrix[p, q])
    return values


def test_bttb_projection_is_psd_hermitian_and_lag_stationary():
    rng = np.random.default_rng(2)
    data = rng.standard_normal((12, 40)) + 1j * rng.standard_normal((12, 40))
    covariance = data @ data.conj().T / data.shape[1]
    projected = bttb_projection(covariance, 3, 4)
    assert np.allclose(projected, projected.conj().T)
    assert np.min(np.linalg.eigvalsh(projected)) >= -1e-10
    for lag in [(0, 0), (1, 0), (0, 1), (1, -1)]:
        values = _lag_values(projected, 3, 4, lag)
        assert np.max(np.abs(np.asarray(values) - values[0])) < 1e-10


def test_adaptive_weights_sum_to_one_and_downweight_corner_fault():
    array = RectangularArray(8, 8, 1.0e10)
    rng = np.random.default_rng(3)
    x = (rng.standard_normal((64, 128)) + 1j * rng.standard_normal((64, 128))) / np.sqrt(2)
    x[0] *= 8.0
    result = adaptive_spatially_smoothed_covariance(
        x,
        array,
        6,
        6,
        health_window=5,
        weight_exponent=20.0,
    )
    assert np.isclose(np.sum(result.weights), 1.0)
    assert result.sensor_reliability.shape == (8, 8)
    assert result.sensor_reliability[0, 0] < 0.6
    weight_grid = result.weights.reshape(3, 3)
    assert weight_grid[0, 0] < np.max(weight_grid)


def test_gaussian_prior_has_expected_shape_and_peak():
    theta = np.arange(5.0, 51.0, 1.0)
    phi = np.arange(-25.0, 26.0, 1.0)
    prior = gaussian_angular_prior(theta, phi, [(20.0, -5.0)], sigma_deg=7.0, floor=0.1)
    assert prior.shape == (theta.size, phi.size)
    assert np.isclose(np.max(prior), 1.0)
    i, j = np.unravel_index(np.argmax(prior), prior.shape)
    assert theta[i] == 20.0
    assert phi[j] == -5.0
    assert np.min(prior) >= 0.1


def test_pawr_returns_finite_two_direction_estimates():
    array = RectangularArray(8, 8, 1.0e10)
    subarray = RectangularArray(6, 6, 1.0e10)
    scanner = MusicGridScanner(
        subarray,
        np.arange(5.0, 50.1, 1.0),
        np.arange(-25.0, 25.1, 1.0),
    )
    emitter = CoherentEmitter(
        reference_power_db=0.0,
        paths=(
            CoherentPath(18.4, -7.6, 0.0, 0.0),
            CoherentPath(35.7, 11.8, -3.0, 55.0),
        ),
    )
    x, _ = simulate_coherent_multipath(array, [emitter], 128, seed=99)
    result = pawr_estimate(
        x,
        array,
        scanner,
        2,
        6,
        6,
        [(20.0, -5.0), (33.0, 9.0)],
    )
    assert len(result.estimates) == 2
    assert np.all(np.isfinite(np.asarray(result.estimates)))
    assert np.min(np.linalg.eigvalsh(result.covariance)) >= -1e-9

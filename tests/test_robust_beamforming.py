from __future__ import annotations

import numpy as np

from hpm_platform.physics.array_geometry import RectangularArray
from hpm_platform.protection.beamforming import covariance_matrix, lcmv_weights
from hpm_platform.protection.robust_beamforming import (
    analytic_output_sinr_db,
    build_confidence_sector,
    confidence_region_hybrid_null_weights,
    derivative_lcmv_weights,
    derivative_null_basis,
    sector_energy_rank,
    soft_sector_mvdr_weights,
    white_noise_gain_db,
)


def _array() -> RectangularArray:
    return RectangularArray(8, 8, 10.0e9)


def test_confidence_sector_is_psd_and_trace_normalized() -> None:
    array = _array()
    sector = build_confidence_sector(array, (42.0, -8.0), (7.0, 7.0), grid_step_deg=1.0)
    eigenvalues = np.linalg.eigvalsh(sector.covariance)
    assert sector.n_grid_points > 50
    assert np.min(eigenvalues) > -1e-9
    assert np.isclose(np.trace(sector.covariance).real, array.n_elements, rtol=1e-10)
    assert np.all(np.diff(sector.cumulative_energy) >= -1e-12)
    assert np.isclose(sector.cumulative_energy[-1], 1.0)


def test_derivative_lcmv_enforces_local_null_subspace() -> None:
    array = _array()
    desired = array.steering_vector(15.0, 20.0)
    basis = derivative_null_basis(array, (42.0, -8.0), step_deg=0.1)
    covariance = np.eye(array.n_elements, dtype=complex)
    weights = derivative_lcmv_weights(
        covariance,
        desired,
        array,
        (42.0, -8.0),
        loading_factor=0.01,
    )
    assert np.isclose(np.vdot(weights, desired), 1.0, atol=1e-9)
    assert np.max(np.abs(np.conj(basis.T) @ weights)) < 1e-8


def test_hybrid_null_meets_constraints_and_wng_floor() -> None:
    array = _array()
    desired = array.steering_vector(15.0, 20.0)
    sector = build_confidence_sector(array, (42.0, -8.0), (7.0, 7.0), grid_step_deg=1.0)
    covariance = np.eye(array.n_elements, dtype=complex)
    result = confidence_region_hybrid_null_weights(
        covariance,
        desired,
        sector,
        loading_factor=0.01,
        energy_threshold=0.999,
        max_rank=10,
        white_noise_gain_floor_db=8.0,
    )
    assert 1 <= result.selected_rank <= 10
    assert result.energy_coverage >= 0.99
    assert result.white_noise_gain_db >= 8.0
    assert np.isclose(np.vdot(result.weights, desired), 1.0, atol=1e-8)
    residual = np.conj(result.null_basis.T) @ result.weights
    assert np.max(np.abs(residual)) < 1e-7


def test_energy_rank_increases_with_requested_coverage() -> None:
    sector = build_confidence_sector(_array(), (42.0, -8.0), (7.0, 7.0))
    low = sector_energy_rank(sector, 0.95)
    high = sector_energy_rank(sector, 0.9999)
    assert high >= low


def test_hybrid_wide_null_beats_point_constraint_after_direction_drift() -> None:
    array = _array()
    rng = np.random.default_rng(1234)
    desired_direction = (15.0, 20.0)
    center = (42.0, -8.0)
    drifted = (47.0, -4.0)
    desired = array.steering_vector(*desired_direction)
    interferer_center = array.steering_vector(*center)
    gains = 10.0 ** (rng.normal(0.0, 0.1, array.n_elements) / 20.0) * np.exp(
        1j * np.deg2rad(rng.normal(0.0, 2.0, array.n_elements))
    )

    def cn(shape: tuple[int, ...]) -> np.ndarray:
        return (rng.standard_normal(shape) + 1j * rng.standard_normal(shape)) / np.sqrt(2.0)

    n = 128
    x = (
        gains[:, None] * desired[:, None] * np.sqrt(10.0 ** (-5.0 / 10.0)) * cn((1, n))
        + gains[:, None]
        * interferer_center[:, None]
        * np.sqrt(10.0 ** (30.0 / 10.0))
        * cn((1, n))
        + cn((array.n_elements, n))
    )
    covariance = covariance_matrix(x)
    point = lcmv_weights(
        covariance,
        np.column_stack((desired, interferer_center)),
        np.array([1.0, 0.0]),
        loading_factor=0.03,
    )
    sector = build_confidence_sector(array, center, (7.0, 7.0), grid_step_deg=1.0)
    hybrid = confidence_region_hybrid_null_weights(
        covariance,
        desired,
        sector,
        loading_factor=0.03,
        energy_threshold=0.999,
        max_rank=10,
        soft_strength=0.5,
        white_noise_gain_floor_db=8.0,
    ).weights
    desired_true = gains * desired
    interferer_true = gains * array.steering_vector(*drifted)
    point_sinr = analytic_output_sinr_db(
        point,
        desired_true,
        interferer_true,
        desired_power=10.0 ** (-5.0 / 10.0),
        interferer_power=10.0 ** (30.0 / 10.0),
    )
    hybrid_sinr = analytic_output_sinr_db(
        hybrid,
        desired_true,
        interferer_true,
        desired_power=10.0 ** (-5.0 / 10.0),
        interferer_power=10.0 ** (30.0 / 10.0),
    )
    assert hybrid_sinr > point_sinr + 8.0
    assert white_noise_gain_db(hybrid) > 8.0


def test_soft_sector_mvdr_returns_finite_weights() -> None:
    array = _array()
    desired = array.steering_vector(15.0, 20.0)
    sector = build_confidence_sector(array, (42.0, -8.0), (7.0, 7.0))
    weights = soft_sector_mvdr_weights(
        np.eye(array.n_elements),
        desired,
        sector,
        sector_strength=0.5,
        loading_factor=0.03,
    )
    assert np.all(np.isfinite(weights))
    assert np.isclose(np.vdot(weights, desired), 1.0, atol=1e-8)

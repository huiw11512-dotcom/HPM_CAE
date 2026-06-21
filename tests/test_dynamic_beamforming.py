from __future__ import annotations

import numpy as np

from hpm_platform.physics.array_geometry import RectangularArray
from hpm_platform.protection.dynamic_beamforming import (
    analytic_output_sinr_multi_db,
    build_covariance_confidence_sector,
    fault_aware_covariance,
    multi_confidence_region_hybrid_null_weights,
    multi_point_lcmv_weights,
)


def _array() -> RectangularArray:
    return RectangularArray(8, 8, 10.0e9)


def test_covariance_sector_is_psd_and_rotated() -> None:
    array = _array()
    covariance = np.array([[4.0, 1.2], [1.2, 2.0]])
    sector = build_covariance_confidence_sector(array, (35.0, -8.0), covariance)
    assert sector.n_grid_points > 10
    assert np.min(np.linalg.eigvalsh(sector.covariance)) > -1e-9
    assert np.isclose(np.trace(sector.covariance).real, array.n_elements)


def test_fault_aware_covariance_penalizes_bad_channel() -> None:
    covariance = np.eye(4, dtype=complex)
    health = np.array([1.0, 0.1, 1.0, 1.0])
    result = fault_aware_covariance(covariance, health, penalty_strength=1.0)
    assert result[1, 1].real > result[0, 0].real
    assert np.allclose(result, result.conj().T)


def test_multi_hybrid_null_protects_two_drifted_interferers() -> None:
    array = _array()
    desired = array.steering_vector(15.0, 20.0)
    centers = [(34.0, -12.0), (48.0, 15.0)]
    actual = [(37.0, -9.0), (45.0, 12.0)]
    covariance = np.eye(array.n_elements, dtype=complex)
    for center, power in zip(centers, [1000.0, 500.0]):
        steering = array.steering_vector(*center)
        covariance += power * np.outer(steering, steering.conj())
    sectors = [
        build_covariance_confidence_sector(array, center, np.diag([2.5, 2.5]) ** 2)
        for center in centers
    ]
    point = multi_point_lcmv_weights(covariance, desired, array, centers, loading_factor=0.03)
    hybrid = multi_confidence_region_hybrid_null_weights(
        covariance,
        desired,
        sectors,
        loading_factor=0.03,
        max_rank_per_sector=6,
        max_total_rank=12,
        white_noise_gain_floor_db=5.0,
    )
    true_interferers = [array.steering_vector(*direction) for direction in actual]
    point_sinr = analytic_output_sinr_multi_db(
        point,
        desired,
        true_interferers,
        desired_power=1.0,
        interferer_powers=[1000.0, 500.0],
    )
    hybrid_sinr = analytic_output_sinr_multi_db(
        hybrid.weights,
        desired,
        true_interferers,
        desired_power=1.0,
        interferer_powers=[1000.0, 500.0],
    )
    assert hybrid.selected_rank >= 2
    assert hybrid_sinr > point_sinr + 4.0
    assert np.isclose(np.vdot(hybrid.weights, desired), 1.0, atol=1e-7)

from __future__ import annotations

import numpy as np

from hpm_platform.perception.uncertainty import local_music_posterior_covariance
from hpm_platform.physics.array_geometry import RectangularArray


def test_local_music_uncertainty_is_spd_and_near_peak() -> None:
    array = RectangularArray(6, 6, 10.0e9)
    a1 = array.steering_vector(25.4, -6.2)
    a2 = array.steering_vector(39.2, 10.5)
    covariance = 100.0 * np.outer(a1, a1.conj()) + 30.0 * np.outer(a2, a2.conj()) + np.eye(36)
    result = local_music_posterior_covariance(
        covariance,
        array,
        (25.4, -6.2),
        2,
        radius_deg=2.5,
        grid_step_deg=0.5,
    )
    assert result.posterior.shape == (result.theta_grid_deg.size, result.phi_grid_deg.size)
    assert np.isclose(np.sum(result.posterior), 1.0)
    assert np.min(np.linalg.eigvalsh(result.covariance_deg2)) > 0
    assert np.linalg.norm(np.asarray(result.posterior_mean_deg) - np.array([25.4, -6.2])) < 1.0

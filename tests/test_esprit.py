import numpy as np

from hpm_platform.perception.esprit import esprit_2d_from_covariance
from hpm_platform.physics.array_geometry import RectangularArray


def test_2d_esprit_recovers_two_uncorrelated_sources_in_low_noise_case():
    array = RectangularArray(6, 6, 1.0e10)
    truth = [(16.0, -9.0), (34.0, 13.0)]
    steering = np.column_stack([array.steering_vector(*direction) for direction in truth])
    covariance = steering @ np.diag([1.0, 0.7]) @ steering.conj().T + 1e-4 * np.eye(array.n_elements)
    result = esprit_2d_from_covariance(covariance, array, 2)
    assert len(result.estimates) == 2
    estimates = sorted(result.estimates)
    truths = sorted(truth)
    assert np.max(np.abs(np.asarray(estimates) - np.asarray(truths))) < 0.05

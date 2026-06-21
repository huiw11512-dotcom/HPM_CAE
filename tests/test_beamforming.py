import numpy as np

from hpm_platform.physics.array_geometry import RectangularArray
from hpm_platform.protection.beamforming import lcmv_weights


def test_lcmv_satisfies_linear_constraints():
    array = RectangularArray(4, 4, 10e9)
    a0 = array.steering_vector(10.0, 0.0)
    a1 = array.steering_vector(35.0, 0.0)
    c = np.column_stack((a0, a1))
    r = np.eye(array.n_elements)
    w = lcmv_weights(r, c, np.array([1.0, 0.0]))
    achieved = np.conj(c.T) @ w
    assert np.allclose(achieved, np.array([1.0, 0.0]), atol=1e-10)

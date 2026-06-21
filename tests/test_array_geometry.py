import numpy as np

from hpm_platform.physics.array_geometry import RectangularArray


def test_array_is_centered_and_has_correct_size():
    array = RectangularArray(8, 8, 10e9)
    assert array.positions_m.shape == (64, 3)
    assert np.allclose(array.positions_m.mean(axis=0), 0.0)


def test_conventional_weights_are_distortionless():
    array = RectangularArray(8, 8, 10e9)
    a = array.steering_vector(20.0, 10.0)
    w = array.conventional_receive_weights(20.0, 10.0)
    assert np.allclose(np.vdot(w, a), 1.0)


def test_phase_conjugate_weights_are_unit_norm():
    array = RectangularArray(8, 8, 10e9)
    focus = np.array([0.1, 0.0, 1.0])
    q = array.phase_conjugate_focus_weights(focus)
    assert np.allclose(np.linalg.norm(q), 1.0)

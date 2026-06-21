import numpy as np

from hpm_platform.perception.music import MusicGridScanner
from hpm_platform.physics.array_geometry import RectangularArray


def test_signal_subspace_complement_matches_noise_subspace_music():
    array = RectangularArray(4, 4, 10e9)
    rng = np.random.default_rng(123)
    x = (rng.standard_normal((array.n_elements, 80)) + 1j * rng.standard_normal((array.n_elements, 80))) / np.sqrt(2.0)
    covariance = x @ np.conj(x.T) / x.shape[1]
    theta = np.arange(5.0, 31.0, 2.0)
    phi = np.arange(-12.0, 13.0, 2.0)
    scanner = MusicGridScanner(array, theta, phi)
    fast = scanner.scan_covariance(covariance, 2).spectrum

    eigenvalues, eigenvectors = np.linalg.eigh(covariance)
    order = np.argsort(eigenvalues)[::-1]
    noise = eigenvectors[:, order][:, 2:]
    projection = np.conj(noise.T) @ scanner.steering_matrix
    denominator = np.sum(np.abs(projection) ** 2, axis=0)
    reference = 1.0 / np.maximum(denominator, np.finfo(float).eps)
    reference = reference.reshape(fast.shape)
    reference /= reference.max()
    assert np.allclose(fast, reference, rtol=1e-10, atol=1e-10)

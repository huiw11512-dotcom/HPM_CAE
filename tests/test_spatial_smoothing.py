import numpy as np

from hpm_platform.perception.music import MusicGridScanner
from hpm_platform.perception.spatial_smoothing import spatially_smoothed_covariance
from hpm_platform.physics.array_geometry import RectangularArray
from hpm_platform.signal.multipath import CoherentEmitter, CoherentPath, simulate_coherent_multipath


def test_spatial_smoothing_shape_and_hermitian_property():
    array = RectangularArray(8, 8, 10e9)
    emitter = CoherentEmitter(
        reference_power_db=10.0,
        paths=(CoherentPath(18.0, -8.0), CoherentPath(36.0, 12.0, -3.0, 55.0)),
    )
    x, _ = simulate_coherent_multipath(array, [emitter], 256, seed=11)
    result = spatially_smoothed_covariance(x, array, 6, 6, forward_backward=True)
    assert result.covariance.shape == (36, 36)
    assert result.n_subarrays == 9
    assert np.allclose(result.covariance, np.conj(result.covariance.T))


def test_fbss_music_resolves_two_coherent_paths_at_high_snr():
    array = RectangularArray(8, 8, 10e9)
    emitter = CoherentEmitter(
        reference_power_db=15.0,
        paths=(CoherentPath(18.0, -8.0), CoherentPath(36.0, 12.0, -3.0, 55.0)),
    )
    x, _ = simulate_coherent_multipath(array, [emitter], 512, seed=13)
    smooth = spatially_smoothed_covariance(x, array, 6, 6, forward_backward=True)
    scanner = MusicGridScanner(smooth.subarray, np.arange(8.0, 46.0, 1.0), np.arange(-18.0, 19.0, 1.0))
    result = scanner.scan_covariance(smooth.covariance, 2, n_peaks=2, min_separation_deg=5.0)
    estimates = [(peak[0], peak[1]) for peak in result.peaks]
    assert any(np.hypot(theta - 18.0, phi + 8.0) <= 1.5 for theta, phi in estimates)
    assert any(np.hypot(theta - 36.0, phi - 12.0) <= 1.5 for theta, phi in estimates)

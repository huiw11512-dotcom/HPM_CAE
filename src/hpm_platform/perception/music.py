"""Two-dimensional MUSIC estimators for uniform rectangular arrays."""
from __future__ import annotations

from dataclasses import dataclass
import numpy as np

from hpm_platform.physics.array_geometry import RectangularArray


@dataclass(frozen=True)
class MusicResult:
    spectrum: np.ndarray
    theta_grid_deg: np.ndarray
    phi_grid_deg: np.ndarray
    peaks: list[tuple[float, float, float]]
    eigenvalues: np.ndarray


def sample_covariance(x: np.ndarray) -> np.ndarray:
    x = np.asarray(x, dtype=complex)
    if x.ndim != 2:
        raise ValueError("x must have shape (sensors, snapshots)")
    if x.shape[1] < 2:
        raise ValueError("At least two snapshots are required")
    return (x @ np.conj(x.T)) / x.shape[1]


def _direction_vector(theta_deg: float, phi_deg: float) -> np.ndarray:
    theta = np.deg2rad(theta_deg)
    phi = np.deg2rad(phi_deg)
    return np.array(
        [np.sin(theta) * np.cos(phi), np.sin(theta) * np.sin(phi), np.cos(theta)]
    )


def _separation_deg(a: tuple[float, float], b: tuple[float, float]) -> float:
    dot = np.clip(np.dot(_direction_vector(*a), _direction_vector(*b)), -1.0, 1.0)
    return float(np.rad2deg(np.arccos(dot)))


def find_peaks_nms(
    spectrum: np.ndarray,
    theta_grid_deg: np.ndarray,
    phi_grid_deg: np.ndarray,
    n_peaks: int,
    min_separation_deg: float = 5.0,
) -> list[tuple[float, float, float]]:
    """Angular non-maximum suppression over a gridded spectrum."""

    if n_peaks < 1:
        raise ValueError("n_peaks must be positive")
    p = np.asarray(spectrum, float)
    theta = np.asarray(theta_grid_deg, float)
    phi = np.asarray(phi_grid_deg, float)
    if p.shape != (theta.size, phi.size):
        raise ValueError("spectrum shape must be (len(theta), len(phi))")

    order = np.argsort(p.ravel())[::-1]
    selected: list[tuple[float, float, float]] = []
    for flat_idx in order:
        i, j = np.unravel_index(flat_idx, p.shape)
        candidate = (float(theta[i]), float(phi[j]), float(p[i, j]))
        if all(
            _separation_deg((candidate[0], candidate[1]), (old[0], old[1]))
            >= min_separation_deg
            for old in selected
        ):
            selected.append(candidate)
            if len(selected) >= n_peaks:
                break
    return selected


class MusicGridScanner:
    """Precomputed 2-D MUSIC grid for repeated Monte Carlo trials."""

    def __init__(
        self,
        array: RectangularArray,
        theta_grid_deg: np.ndarray,
        phi_grid_deg: np.ndarray,
    ) -> None:
        self.array = array
        self.theta_grid_deg = np.asarray(theta_grid_deg, dtype=float).reshape(-1)
        self.phi_grid_deg = np.asarray(phi_grid_deg, dtype=float).reshape(-1)
        if self.theta_grid_deg.size < 2 or self.phi_grid_deg.size < 2:
            raise ValueError("Both MUSIC grid axes must have at least two points")
        tt, pp = np.meshgrid(
            self.theta_grid_deg, self.phi_grid_deg, indexing="ij"
        )
        self._shape = tt.shape
        self._steering = array.steering_matrix(tt.ravel(), pp.ravel())
        self._steering_norm_sq = np.sum(np.abs(self._steering) ** 2, axis=0)

    @property
    def steering_matrix(self) -> np.ndarray:
        return self._steering

    def scan_covariance(
        self,
        covariance: np.ndarray,
        n_sources: int,
        *,
        diagonal_loading: float = 1e-8,
        n_peaks: int | None = None,
        min_separation_deg: float = 5.0,
    ) -> MusicResult:
        r = np.asarray(covariance, dtype=complex)
        m = self.array.n_elements
        if r.shape != (m, m):
            raise ValueError("covariance shape does not match scanner array")
        if not 1 <= n_sources < m:
            raise ValueError("n_sources must be between 1 and M-1")
        if diagonal_loading < 0:
            raise ValueError("diagonal_loading must be non-negative")

        r = 0.5 * (r + np.conj(r.T))
        loading = diagonal_loading * max(
            float(np.trace(r).real / m), np.finfo(float).tiny
        )
        if loading > 0:
            r = r + loading * np.eye(m)

        eigenvalues, eigenvectors = np.linalg.eigh(r)
        order = np.argsort(eigenvalues)[::-1]
        eigenvalues = np.real(eigenvalues[order])
        eigenvectors = eigenvectors[:, order]
        # Use the signal-subspace complement identity
        # a^H E_n E_n^H a = ||a||^2 - ||E_s^H a||^2.  For the usual
        # small source count this is mathematically equivalent and much faster
        # in Monte Carlo scans than multiplying by the full noise subspace.
        signal_subspace = eigenvectors[:, :n_sources]
        projection = np.conj(signal_subspace.T) @ self._steering
        denominator = self._steering_norm_sq - np.sum(np.abs(projection) ** 2, axis=0)
        spectrum = 1.0 / np.maximum(denominator, np.finfo(float).eps)
        spectrum = spectrum.reshape(self._shape)
        spectrum /= max(float(np.max(spectrum)), np.finfo(float).tiny)
        peaks = find_peaks_nms(
            spectrum,
            self.theta_grid_deg,
            self.phi_grid_deg,
            n_peaks or n_sources,
            min_separation_deg=min_separation_deg,
        )
        return MusicResult(
            spectrum=spectrum,
            theta_grid_deg=self.theta_grid_deg,
            phi_grid_deg=self.phi_grid_deg,
            peaks=peaks,
            eigenvalues=eigenvalues,
        )

    def scan_snapshots(
        self,
        x: np.ndarray,
        n_sources: int,
        **kwargs: float | int,
    ) -> MusicResult:
        return self.scan_covariance(sample_covariance(x), n_sources, **kwargs)


def music_2d_from_covariance(
    covariance: np.ndarray,
    array: RectangularArray,
    n_sources: int,
    theta_grid_deg: np.ndarray,
    phi_grid_deg: np.ndarray,
    diagonal_loading: float = 1e-8,
    n_peaks: int | None = None,
    min_separation_deg: float = 5.0,
) -> MusicResult:
    scanner = MusicGridScanner(array, theta_grid_deg, phi_grid_deg)
    return scanner.scan_covariance(
        covariance,
        n_sources,
        diagonal_loading=diagonal_loading,
        n_peaks=n_peaks,
        min_separation_deg=min_separation_deg,
    )


def music_2d(
    x: np.ndarray,
    array: RectangularArray,
    n_sources: int,
    theta_grid_deg: np.ndarray,
    phi_grid_deg: np.ndarray,
    diagonal_loading: float = 1e-8,
    n_peaks: int | None = None,
    min_separation_deg: float = 5.0,
) -> MusicResult:
    scanner = MusicGridScanner(array, theta_grid_deg, phi_grid_deg)
    return scanner.scan_snapshots(
        x,
        n_sources,
        diagonal_loading=diagonal_loading,
        n_peaks=n_peaks,
        min_separation_deg=min_separation_deg,
    )

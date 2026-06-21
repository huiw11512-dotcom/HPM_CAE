"""Robust covariance tools for coherent-multipath DOA estimation.

The algorithms in this module operate on normalized narrowband array data.
They deliberately avoid absolute source-power or equipment-vulnerability
parameters.  The main research baseline, PAWR, combines three transparent
priors rather than hiding them inside a black-box optimizer:

1. sensor-health weights inferred from local power smoothness;
2. block-Toeplitz-with-Toeplitz-blocks (BTTB) stationarity of a URA;
3. a broad, uncertain angular prior used only for covariance reconstruction.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Sequence

import numpy as np
from scipy.ndimage import median_filter

from hpm_platform.perception.music import MusicGridScanner
from hpm_platform.physics.array_geometry import RectangularArray


@dataclass(frozen=True)
class AdaptiveSmoothingResult:
    covariance: np.ndarray
    subarray: RectangularArray
    n_subarrays: int
    weights: np.ndarray
    offsets: np.ndarray
    sensor_reliability: np.ndarray
    forward_backward: bool


@dataclass(frozen=True)
class ReconstructionResult:
    covariance: np.ndarray
    weighted_covariance: np.ndarray
    structured_covariance: np.ndarray
    reconstructed_covariance: np.ndarray
    prior_mask: np.ndarray
    coarse_spectrum: np.ndarray
    sensor_reliability: np.ndarray
    subarray_weights: np.ndarray
    structural_residual: float
    estimated_noise_power: float


def _hermitian(matrix: np.ndarray) -> np.ndarray:
    value = np.asarray(matrix, dtype=complex)
    return 0.5 * (value + np.conj(value.T))


def project_psd(matrix: np.ndarray, eigenvalue_floor: float = 0.0) -> np.ndarray:
    """Project a Hermitian matrix onto the PSD cone by eigenvalue clipping."""

    if eigenvalue_floor < 0:
        raise ValueError("eigenvalue_floor must be non-negative")
    value = _hermitian(matrix)
    eigenvalues, eigenvectors = np.linalg.eigh(value)
    scale = max(float(np.trace(value).real / value.shape[0]), np.finfo(float).tiny)
    clipped = np.maximum(np.real(eigenvalues), eigenvalue_floor * scale)
    return _hermitian((eigenvectors * clipped[None, :]) @ np.conj(eigenvectors.T))


def sensor_health_from_local_power(
    x: np.ndarray,
    array: RectangularArray,
    *,
    window: int = 3,
    tuning: float = 2.5,
    reliability_floor: float = 0.05,
) -> np.ndarray:
    """Estimate per-channel reliability from abrupt local power anomalies.

    Smooth coherent interference is retained: reliability is based on the
    residual from a local median surface, not deviation from one global power.
    """

    data = np.asarray(x, dtype=complex)
    if data.ndim != 2 or data.shape[0] != array.n_elements:
        raise ValueError("x must have shape (array.n_elements, snapshots)")
    if data.shape[1] < 2:
        raise ValueError("At least two snapshots are required")
    if window < 1 or window % 2 == 0:
        raise ValueError("window must be a positive odd integer")
    if tuning <= 0:
        raise ValueError("tuning must be positive")
    if not 0 < reliability_floor <= 1:
        raise ValueError("reliability_floor must lie in (0, 1]")

    power = np.mean(np.abs(data) ** 2, axis=1).reshape(array.nx, array.ny)
    log_power = 10.0 * np.log10(np.maximum(power, np.finfo(float).tiny))
    local = median_filter(log_power, size=window, mode="reflect")
    residual = np.abs(log_power - local)
    center = float(np.median(residual))
    mad = float(np.median(np.abs(residual - center)))
    scale = max(1.4826 * mad, 0.05)
    threshold = center + tuning * scale
    reliability = np.minimum(1.0, threshold / np.maximum(residual, threshold))
    reliability = np.clip(reliability, reliability_floor, 1.0)
    return reliability


def adaptive_spatially_smoothed_covariance(
    x: np.ndarray,
    array: RectangularArray,
    subarray_nx: int,
    subarray_ny: int,
    *,
    forward_backward: bool = True,
    health_window: int = 3,
    health_tuning: float = 2.5,
    reliability_floor: float = 0.05,
    weight_exponent: float = 3.0,
    weight_floor_fraction: float = 0.02,
) -> AdaptiveSmoothingResult:
    """Spatial smoothing with data-driven channel-health subarray weights."""

    data = np.asarray(x, dtype=complex)
    if data.ndim != 2 or data.shape[0] != array.n_elements:
        raise ValueError("x must have shape (array.n_elements, snapshots)")
    if data.shape[1] < 2:
        raise ValueError("At least two snapshots are required")
    if not 1 <= subarray_nx <= array.nx or not 1 <= subarray_ny <= array.ny:
        raise ValueError("Subarray dimensions must lie within the parent array")
    if weight_exponent <= 0:
        raise ValueError("weight_exponent must be positive")
    if not 0 <= weight_floor_fraction < 1:
        raise ValueError("weight_floor_fraction must lie in [0, 1)")

    reliability = sensor_health_from_local_power(
        data,
        array,
        window=health_window,
        tuning=health_tuning,
        reliability_floor=reliability_floor,
    )
    cube = data.reshape(array.nx, array.ny, data.shape[1])
    matrices: list[np.ndarray] = []
    raw_scores: list[float] = []
    offsets: list[tuple[int, int]] = []
    m_sub = subarray_nx * subarray_ny

    for ix in range(array.nx - subarray_nx + 1):
        for iy in range(array.ny - subarray_ny + 1):
            block = cube[ix : ix + subarray_nx, iy : iy + subarray_ny, :].reshape(
                m_sub, data.shape[1]
            )
            matrices.append((block @ np.conj(block.T)) / data.shape[1])
            health = reliability[ix : ix + subarray_nx, iy : iy + subarray_ny]
            # The geometric mean penalizes a subarray containing a few badly
            # corrupted channels without collapsing to a hard rejection.
            score = float(np.exp(np.mean(np.log(np.maximum(health, 1e-12)))))
            raw_scores.append(score**weight_exponent)
            offsets.append((ix, iy))

    scores = np.asarray(raw_scores, dtype=float)
    if np.all(scores <= 0):
        scores = np.ones_like(scores)
    scores /= np.sum(scores)
    uniform = np.full_like(scores, 1.0 / scores.size)
    weights = (1.0 - weight_floor_fraction) * scores + weight_floor_fraction * uniform
    weights /= np.sum(weights)

    covariance = np.zeros_like(matrices[0])
    for weight, matrix in zip(weights, matrices):
        covariance += float(weight) * matrix

    if forward_backward:
        exchange = np.fliplr(np.eye(m_sub))
        covariance = 0.5 * (covariance + exchange @ np.conj(covariance) @ exchange)
    covariance = _hermitian(covariance)

    subarray = RectangularArray(
        nx=subarray_nx,
        ny=subarray_ny,
        frequency_hz=array.frequency_hz,
        dx_m=array.dx_m,
        dy_m=array.dy_m,
    )
    return AdaptiveSmoothingResult(
        covariance=covariance,
        subarray=subarray,
        n_subarrays=len(matrices),
        weights=weights,
        offsets=np.asarray(offsets, dtype=int),
        sensor_reliability=reliability,
        forward_backward=forward_backward,
    )


def bttb_projection(
    covariance: np.ndarray,
    nx: int,
    ny: int,
    *,
    project_to_psd: bool = True,
    eigenvalue_floor: float = 1e-9,
) -> np.ndarray:
    """Project a URA covariance onto the 2-D BTTB structural set."""

    value = _hermitian(covariance)
    m = nx * ny
    if value.shape != (m, m):
        raise ValueError("covariance shape must equal (nx*ny, nx*ny)")

    sums: dict[tuple[int, int], complex] = {}
    counts: dict[tuple[int, int], int] = {}
    coordinates = [(ix, iy) for ix in range(nx) for iy in range(ny)]
    for p, (ix, iy) in enumerate(coordinates):
        for q, (jx, jy) in enumerate(coordinates):
            lag = (ix - jx, iy - jy)
            sums[lag] = sums.get(lag, 0.0j) + value[p, q]
            counts[lag] = counts.get(lag, 0) + 1

    lag_values = {lag: sums[lag] / counts[lag] for lag in sums}
    for lag in list(lag_values):
        opposite = (-lag[0], -lag[1])
        paired = 0.5 * (lag_values[lag] + np.conj(lag_values[opposite]))
        lag_values[lag] = paired
        lag_values[opposite] = np.conj(paired)

    structured = np.empty_like(value)
    for p, (ix, iy) in enumerate(coordinates):
        for q, (jx, jy) in enumerate(coordinates):
            structured[p, q] = lag_values[(ix - jx, iy - jy)]
    structured = _hermitian(structured)
    if project_to_psd:
        structured = project_psd(structured, eigenvalue_floor=eigenvalue_floor)
    return structured


def gaussian_angular_prior(
    theta_grid_deg: np.ndarray,
    phi_grid_deg: np.ndarray,
    centers_deg: Sequence[tuple[float, float]],
    *,
    sigma_deg: float | Sequence[float] = 8.0,
    floor: float = 0.08,
) -> np.ndarray:
    """Build a broad spherical Gaussian mixture prior over a 2-D scan grid."""

    theta = np.asarray(theta_grid_deg, dtype=float).reshape(-1)
    phi = np.asarray(phi_grid_deg, dtype=float).reshape(-1)
    if len(centers_deg) == 0:
        raise ValueError("At least one prior center is required")
    if not 0 <= floor < 1:
        raise ValueError("floor must lie in [0, 1)")
    if np.isscalar(sigma_deg):
        sigmas = [float(sigma_deg)] * len(centers_deg)
    else:
        sigmas = [float(value) for value in sigma_deg]
    if len(sigmas) != len(centers_deg) or any(value <= 0 for value in sigmas):
        raise ValueError("sigma_deg must contain one positive value per center")

    tt, pp = np.meshgrid(theta, phi, indexing="ij")
    directions = RectangularArray.direction_vector(tt, pp)
    mixture = np.zeros(tt.shape, dtype=float)
    for (theta0, phi0), sigma in zip(centers_deg, sigmas):
        center = RectangularArray.direction_vector(theta0, phi0).reshape(3)
        dot = np.clip(np.sum(directions * center, axis=-1), -1.0, 1.0)
        distance = np.rad2deg(np.arccos(dot))
        mixture = np.maximum(mixture, np.exp(-0.5 * (distance / sigma) ** 2))
    mixture /= max(float(np.max(mixture)), np.finfo(float).tiny)
    return floor + (1.0 - floor) * mixture


def prior_weighted_reconstruction(
    covariance: np.ndarray,
    scanner: MusicGridScanner,
    n_sources: int,
    prior_mask: np.ndarray,
    *,
    spectrum_exponent: float = 1.35,
    blend: float = 0.55,
    diagonal_loading: float = 1e-8,
) -> tuple[np.ndarray, np.ndarray, float]:
    """Reconstruct covariance by integrating a prior-weighted coarse spectrum."""

    if spectrum_exponent <= 0:
        raise ValueError("spectrum_exponent must be positive")
    if not 0 <= blend <= 1:
        raise ValueError("blend must lie in [0, 1]")
    prior = np.asarray(prior_mask, dtype=float)
    expected_shape = (scanner.theta_grid_deg.size, scanner.phi_grid_deg.size)
    if prior.shape != expected_shape:
        raise ValueError("prior_mask shape does not match scanner grid")
    if np.any(prior < 0):
        raise ValueError("prior_mask must be non-negative")

    base = _hermitian(covariance)
    coarse = scanner.scan_covariance(
        base,
        n_sources,
        diagonal_loading=diagonal_loading,
        n_peaks=n_sources,
    )
    spectrum = np.maximum(coarse.spectrum, 1e-12)
    weights = (spectrum**spectrum_exponent) * prior
    weights = weights.ravel()
    weights /= max(float(np.sum(weights)), np.finfo(float).tiny)

    steering = scanner.steering_matrix
    angular_covariance = (steering * weights[None, :]) @ np.conj(steering.T)
    angular_covariance = _hermitian(angular_covariance)

    eigenvalues = np.linalg.eigvalsh(base)
    eigenvalues = np.maximum(np.real(eigenvalues), 0.0)
    noise_power = float(np.median(eigenvalues[: max(1, base.shape[0] - n_sources)]))
    signal_trace = max(float(np.trace(base).real - base.shape[0] * noise_power), np.finfo(float).tiny)
    angular_trace = max(float(np.trace(angular_covariance).real), np.finfo(float).tiny)
    reconstructed = angular_covariance * (signal_trace / angular_trace)
    reconstructed += noise_power * np.eye(base.shape[0])
    reconstructed = project_psd(reconstructed, eigenvalue_floor=1e-10)
    fused = project_psd((1.0 - blend) * base + blend * reconstructed, eigenvalue_floor=1e-10)
    return fused, coarse.spectrum, noise_power


def pawr_covariance(
    x: np.ndarray,
    array: RectangularArray,
    scanner: MusicGridScanner,
    n_sources: int,
    subarray_nx: int,
    subarray_ny: int,
    prior_centers_deg: Sequence[tuple[float, float]],
    *,
    prior_sigma_deg: float | Sequence[float] = 8.0,
    prior_floor: float = 0.08,
    reconstruction_blend: float = 0.55,
    spectrum_exponent: float = 1.35,
    forward_backward: bool = True,
    health_window: int = 3,
    health_tuning: float = 2.5,
    reliability_floor: float = 0.05,
    weight_exponent: float = 3.0,
    weight_floor_fraction: float = 0.02,
) -> ReconstructionResult:
    """Full prior-assisted adaptive weighted reconstruction (PAWR)."""

    adaptive = adaptive_spatially_smoothed_covariance(
        x,
        array,
        subarray_nx,
        subarray_ny,
        forward_backward=forward_backward,
        health_window=health_window,
        health_tuning=health_tuning,
        reliability_floor=reliability_floor,
        weight_exponent=weight_exponent,
        weight_floor_fraction=weight_floor_fraction,
    )
    structured = bttb_projection(
        adaptive.covariance,
        subarray_nx,
        subarray_ny,
        project_to_psd=True,
    )
    residual = float(
        np.linalg.norm(adaptive.covariance - structured, ord="fro")
        / max(np.linalg.norm(adaptive.covariance, ord="fro"), np.finfo(float).tiny)
    )
    prior = gaussian_angular_prior(
        scanner.theta_grid_deg,
        scanner.phi_grid_deg,
        prior_centers_deg,
        sigma_deg=prior_sigma_deg,
        floor=prior_floor,
    )
    final, coarse_spectrum, noise_power = prior_weighted_reconstruction(
        structured,
        scanner,
        n_sources,
        prior,
        spectrum_exponent=spectrum_exponent,
        blend=reconstruction_blend,
    )
    return ReconstructionResult(
        covariance=final,
        weighted_covariance=adaptive.covariance,
        structured_covariance=structured,
        reconstructed_covariance=final,
        prior_mask=prior,
        coarse_spectrum=coarse_spectrum,
        sensor_reliability=adaptive.sensor_reliability,
        subarray_weights=adaptive.weights,
        structural_residual=residual,
        estimated_noise_power=noise_power,
    )

@dataclass(frozen=True)
class SubspaceFitResult:
    estimates: tuple[tuple[float, float], ...]
    initial_estimates: tuple[tuple[float, float], ...]
    objectives: np.ndarray
    coarse_spectrum: np.ndarray
    prior_components: np.ndarray
    noise_projector: np.ndarray


@dataclass(frozen=True)
class PawrEstimateResult:
    estimates: tuple[tuple[float, float], ...]
    initial_estimates: tuple[tuple[float, float], ...]
    covariance: np.ndarray
    analysis_covariance: np.ndarray
    weighted_covariance: np.ndarray
    structured_covariance: np.ndarray
    coarse_spectrum: np.ndarray
    prior_components: np.ndarray
    sensor_reliability: np.ndarray
    subarray_weights: np.ndarray
    structural_residual: float
    estimated_noise_power: float
    objectives: np.ndarray


def _angular_distance_deg(
    theta_deg: float,
    phi_deg: float,
    center: tuple[float, float],
) -> float:
    direction = RectangularArray.direction_vector(theta_deg, phi_deg).reshape(3)
    reference = RectangularArray.direction_vector(center[0], center[1]).reshape(3)
    return float(np.rad2deg(np.arccos(np.clip(np.dot(direction, reference), -1.0, 1.0))))


def prior_guided_subspace_fit(
    covariance: np.ndarray,
    scanner: MusicGridScanner,
    n_sources: int,
    prior_centers_deg: Sequence[tuple[float, float]],
    *,
    prior_sigma_deg: float | Sequence[float] = 8.0,
    prior_strength: float = 1e-3,
    selection_exponent: float = 0.35,
    search_radius_sigma: float = 2.2,
    min_separation_deg: float = 3.0,
) -> SubspaceFitResult:
    """Continuously refine MUSIC minima under broad component-wise priors.

    The prior labels broad direct/echo sectors; it does not provide exact DOAs.
    A weak quadratic regularizer resolves false-peak ambiguity while the MUSIC
    noise-projection term remains the dominant local objective.
    """

    from scipy.optimize import minimize

    base = _hermitian(covariance)
    m = base.shape[0]
    if base.shape != (m, m) or m != scanner.array.n_elements:
        raise ValueError("covariance shape does not match scanner array")
    if len(prior_centers_deg) != n_sources:
        raise ValueError("One broad prior center is required per source/path")
    if prior_strength < 0 or selection_exponent < 0 or search_radius_sigma <= 0:
        raise ValueError("Invalid subspace-fit hyperparameter")
    if np.isscalar(prior_sigma_deg):
        sigmas = [float(prior_sigma_deg)] * n_sources
    else:
        sigmas = [float(value) for value in prior_sigma_deg]
    if len(sigmas) != n_sources or any(value <= 0 for value in sigmas):
        raise ValueError("prior_sigma_deg must contain positive values")

    eigenvalues, eigenvectors = np.linalg.eigh(base)
    order = np.argsort(eigenvalues)[::-1]
    signal = eigenvectors[:, order[:n_sources]]
    noise_projector = _hermitian(np.eye(m) - signal @ np.conj(signal.T))
    coarse = scanner.scan_covariance(
        base,
        n_sources,
        n_peaks=max(n_sources, 2 * n_sources),
        min_separation_deg=min_separation_deg,
    )

    component_priors: list[np.ndarray] = []
    initial: list[tuple[float, float]] = []
    refined: list[tuple[float, float]] = []
    objectives: list[float] = []
    theta_min = float(scanner.theta_grid_deg.min())
    theta_max = float(scanner.theta_grid_deg.max())
    phi_min = float(scanner.phi_grid_deg.min())
    phi_max = float(scanner.phi_grid_deg.max())

    for center, sigma in zip(prior_centers_deg, sigmas):
        component = gaussian_angular_prior(
            scanner.theta_grid_deg,
            scanner.phi_grid_deg,
            [center],
            sigma_deg=sigma,
            floor=0.0,
        )
        component_priors.append(component)
        score = coarse.spectrum * np.maximum(component, 1e-12) ** selection_exponent
        i, j = np.unravel_index(int(np.argmax(score)), score.shape)
        x0 = np.array(
            [scanner.theta_grid_deg[i], scanner.phi_grid_deg[j]], dtype=float
        )
        initial.append((float(x0[0]), float(x0[1])))

        bounds = [
            (
                max(theta_min, float(center[0]) - search_radius_sigma * sigma),
                min(theta_max, float(center[0]) + search_radius_sigma * sigma),
            ),
            (
                max(phi_min, float(center[1]) - search_radius_sigma * sigma),
                min(phi_max, float(center[1]) + search_radius_sigma * sigma),
            ),
        ]

        def objective(value: np.ndarray) -> float:
            theta_value, phi_value = float(value[0]), float(value[1])
            steering = scanner.array.steering_vector(theta_value, phi_value)
            projection = float(
                np.real(np.vdot(steering, noise_projector @ steering))
                / max(float(np.vdot(steering, steering).real), np.finfo(float).tiny)
            )
            distance = _angular_distance_deg(theta_value, phi_value, center)
            return projection + prior_strength * (distance / sigma) ** 2

        optimum = minimize(
            objective,
            x0,
            method="L-BFGS-B",
            bounds=bounds,
            options={"maxiter": 120, "ftol": 1e-13, "gtol": 1e-9},
        )
        point = np.asarray(optimum.x if optimum.success else x0, dtype=float)
        refined.append((float(point[0]), float(point[1])))
        objectives.append(float(objective(point)))

    return SubspaceFitResult(
        estimates=tuple(refined),
        initial_estimates=tuple(initial),
        objectives=np.asarray(objectives, dtype=float),
        coarse_spectrum=coarse.spectrum,
        prior_components=np.asarray(component_priors, dtype=float),
        noise_projector=noise_projector,
    )


def reconstruct_covariance_from_directions(
    covariance: np.ndarray,
    array: RectangularArray,
    estimates: Sequence[tuple[float, float]],
    *,
    n_sources: int | None = None,
    eigenvalue_floor: float = 1e-10,
) -> tuple[np.ndarray, float]:
    """Fit a low-rank steering-manifold covariance plus white noise."""

    base = _hermitian(covariance)
    directions = list(estimates)
    k = len(directions) if n_sources is None else int(n_sources)
    if len(directions) != k or k < 1 or k >= array.n_elements:
        raise ValueError("Invalid direction count")
    steering = np.column_stack(
        [array.steering_vector(theta, phi) for theta, phi in directions]
    )
    eigenvalues = np.maximum(np.real(np.linalg.eigvalsh(base)), 0.0)
    noise_power = float(np.median(eigenvalues[: max(1, base.shape[0] - k)]))
    signal_part = project_psd(base - noise_power * np.eye(base.shape[0]), 0.0)
    steering_pinv = np.linalg.pinv(steering)
    source_covariance = steering_pinv @ signal_part @ np.conj(steering_pinv.T)
    source_covariance = project_psd(source_covariance, 0.0)
    reconstructed = steering @ source_covariance @ np.conj(steering.T)
    reconstructed += noise_power * np.eye(base.shape[0])
    reconstructed = project_psd(reconstructed, eigenvalue_floor=eigenvalue_floor)
    return reconstructed, noise_power


def pawr_estimate(
    x: np.ndarray,
    array: RectangularArray,
    scanner: MusicGridScanner,
    n_sources: int,
    subarray_nx: int,
    subarray_ny: int,
    prior_centers_deg: Sequence[tuple[float, float]],
    *,
    prior_sigma_deg: float | Sequence[float] = 8.0,
    prior_strength: float = 1e-3,
    selection_exponent: float = 1.0,
    search_radius_sigma: float = 1.2,
    structure_blend: float = 0.02,
    forward_backward: bool = True,
    health_window: int = 5,
    health_tuning: float = 2.5,
    reliability_floor: float = 0.05,
    weight_exponent: float = 20.0,
    weight_floor_fraction: float = 0.02,
) -> PawrEstimateResult:
    """PAWR estimator: health weighting, light BTTB regularization and WSF."""

    if not 0 <= structure_blend <= 1:
        raise ValueError("structure_blend must lie in [0, 1]")
    adaptive = adaptive_spatially_smoothed_covariance(
        x,
        array,
        subarray_nx,
        subarray_ny,
        forward_backward=forward_backward,
        health_window=health_window,
        health_tuning=health_tuning,
        reliability_floor=reliability_floor,
        weight_exponent=weight_exponent,
        weight_floor_fraction=weight_floor_fraction,
    )
    structured = bttb_projection(
        adaptive.covariance,
        subarray_nx,
        subarray_ny,
        project_to_psd=True,
    )
    residual = float(
        np.linalg.norm(adaptive.covariance - structured, ord="fro")
        / max(np.linalg.norm(adaptive.covariance, ord="fro"), np.finfo(float).tiny)
    )
    analysis_covariance = project_psd(
        (1.0 - structure_blend) * adaptive.covariance
        + structure_blend * structured,
        eigenvalue_floor=1e-10,
    )
    fit = prior_guided_subspace_fit(
        analysis_covariance,
        scanner,
        n_sources,
        prior_centers_deg,
        prior_sigma_deg=prior_sigma_deg,
        prior_strength=prior_strength,
        selection_exponent=selection_exponent,
        search_radius_sigma=search_radius_sigma,
    )
    reconstructed, noise_power = reconstruct_covariance_from_directions(
        adaptive.covariance,
        adaptive.subarray,
        fit.estimates,
        n_sources=n_sources,
    )
    return PawrEstimateResult(
        estimates=fit.estimates,
        initial_estimates=fit.initial_estimates,
        covariance=reconstructed,
        analysis_covariance=analysis_covariance,
        weighted_covariance=adaptive.covariance,
        structured_covariance=structured,
        coarse_spectrum=fit.coarse_spectrum,
        prior_components=fit.prior_components,
        sensor_reliability=adaptive.sensor_reliability,
        subarray_weights=adaptive.weights,
        structural_residual=residual,
        estimated_noise_power=noise_power,
        objectives=fit.objectives,
    )

def refine_music_peaks(
    covariance: np.ndarray,
    scanner: MusicGridScanner,
    n_sources: int,
    *,
    local_radius_deg: float = 2.0,
    min_separation_deg: float = 5.0,
) -> tuple[tuple[float, float], ...]:
    """Off-grid local refinement of unconstrained MUSIC NMS peaks."""

    from scipy.optimize import minimize

    if local_radius_deg <= 0:
        raise ValueError("local_radius_deg must be positive")
    base = _hermitian(covariance)
    m = scanner.array.n_elements
    if base.shape != (m, m):
        raise ValueError("covariance shape does not match scanner array")
    eigenvalues, eigenvectors = np.linalg.eigh(base)
    order = np.argsort(eigenvalues)[::-1]
    signal = eigenvectors[:, order[:n_sources]]
    noise_projector = _hermitian(np.eye(m) - signal @ np.conj(signal.T))
    coarse = scanner.scan_covariance(
        base,
        n_sources,
        n_peaks=n_sources,
        min_separation_deg=min_separation_deg,
    )
    refined: list[tuple[float, float]] = []
    for theta0, phi0, _ in coarse.peaks:
        bounds = [
            (
                max(float(scanner.theta_grid_deg.min()), theta0 - local_radius_deg),
                min(float(scanner.theta_grid_deg.max()), theta0 + local_radius_deg),
            ),
            (
                max(float(scanner.phi_grid_deg.min()), phi0 - local_radius_deg),
                min(float(scanner.phi_grid_deg.max()), phi0 + local_radius_deg),
            ),
        ]

        def objective(value: np.ndarray) -> float:
            steering = scanner.array.steering_vector(float(value[0]), float(value[1]))
            return float(
                np.real(np.vdot(steering, noise_projector @ steering))
                / max(float(np.vdot(steering, steering).real), np.finfo(float).tiny)
            )

        optimum = minimize(
            objective,
            np.array([theta0, phi0], dtype=float),
            method="L-BFGS-B",
            bounds=bounds,
            options={"maxiter": 100, "ftol": 1e-13, "gtol": 1e-9},
        )
        point = optimum.x if optimum.success else np.array([theta0, phi0])
        refined.append((float(point[0]), float(point[1])))
    return tuple(refined)

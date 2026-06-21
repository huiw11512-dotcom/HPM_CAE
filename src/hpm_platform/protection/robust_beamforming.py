"""Confidence-region robust receive beamforming utilities.

The routines in this module are deliberately normalized and defensive.  They
operate on array covariances, steering manifolds, and relative signal powers;
they do not contain an absolute source budget, device susceptibility data, or
any real-world damage model.

The main V0.4 method is ``confidence_region_hybrid_null_weights``.  It turns a
DOA confidence ellipse into a weighted steering-manifold subspace, imposes
hard null constraints on the energetic subspace modes, and uses the full
sector covariance as a soft residual penalty.  The number of hard modes is
selected by energy coverage and reduced when necessary to respect a white-
noise-gain floor.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

import numpy as np

from hpm_platform.physics.array_geometry import RectangularArray
from hpm_platform.protection.beamforming import lcmv_weights, mvdr_weights


@dataclass(frozen=True)
class ConfidenceSector:
    """Weighted angular confidence region and its manifold decomposition."""

    center_deg: tuple[float, float]
    half_width_deg: tuple[float, float]
    theta_deg: np.ndarray
    phi_deg: np.ndarray
    probability: np.ndarray
    steering: np.ndarray
    covariance: np.ndarray
    eigenvectors: np.ndarray
    singular_values: np.ndarray
    cumulative_energy: np.ndarray

    @property
    def n_grid_points(self) -> int:
        return int(self.theta_deg.size)


@dataclass(frozen=True)
class HybridNullResult:
    """Weights and diagnostics returned by the confidence-region method."""

    weights: np.ndarray
    selected_rank: int
    energy_coverage: float
    white_noise_gain_db: float
    constraint_condition: float
    soft_strength: float
    null_basis: np.ndarray


def _inclusive_axis(start: float, stop: float, step: float) -> np.ndarray:
    if step <= 0:
        raise ValueError("grid step must be positive")
    count = int(np.floor((stop - start) / step + 1e-12))
    values = start + step * np.arange(count + 1, dtype=float)
    if values.size == 0 or values[-1] < stop - 1e-10:
        values = np.append(values, stop)
    return values


def build_confidence_sector(
    array: RectangularArray,
    center_deg: tuple[float, float],
    half_width_deg: tuple[float, float],
    *,
    grid_step_deg: float = 1.0,
    sigma_deg: tuple[float, float] | None = None,
) -> ConfidenceSector:
    """Discretize an elliptical DOA confidence region.

    Parameters
    ----------
    array:
        Array manifold provider.
    center_deg:
        Estimated interferer direction ``(theta, phi)`` in degrees.
    half_width_deg:
        Ellipse semi-axes in coordinate degrees.
    grid_step_deg:
        Cartesian angular sampling step.
    sigma_deg:
        Standard deviations used for Gaussian quadrature weights.  By
        default each sigma is half of the corresponding semi-axis.

    Notes
    -----
    The sector covariance is normalized to have trace equal to the element
    count, so its scale is comparable across sector widths.
    """
    theta0, phi0 = (float(center_deg[0]), float(center_deg[1]))
    htheta, hphi = (float(half_width_deg[0]), float(half_width_deg[1]))
    if not (0.0 <= theta0 <= 90.0):
        raise ValueError("center theta must lie in the visible 0...90 degree hemisphere")
    if htheta <= 0 or hphi <= 0:
        raise ValueError("confidence half widths must be positive")
    if sigma_deg is None:
        sigma_theta, sigma_phi = htheta / 2.0, hphi / 2.0
    else:
        sigma_theta, sigma_phi = (float(sigma_deg[0]), float(sigma_deg[1]))
    if sigma_theta <= 0 or sigma_phi <= 0:
        raise ValueError("sector sigmas must be positive")

    theta_axis = _inclusive_axis(max(0.0, theta0 - htheta), min(90.0, theta0 + htheta), grid_step_deg)
    phi_axis = _inclusive_axis(phi0 - hphi, phi0 + hphi, grid_step_deg)
    theta_mesh, phi_mesh = np.meshgrid(theta_axis, phi_axis, indexing="ij")
    dtheta = (theta_mesh.ravel() - theta0) / htheta
    dphi = (phi_mesh.ravel() - phi0) / hphi
    mask = dtheta**2 + dphi**2 <= 1.0 + 1e-12
    theta = theta_mesh.ravel()[mask]
    phi = phi_mesh.ravel()[mask]
    if theta.size < 3:
        raise ValueError("confidence sector contains too few grid points")

    log_probability = -0.5 * (
        ((theta - theta0) / sigma_theta) ** 2 + ((phi - phi0) / sigma_phi) ** 2
    )
    probability = np.exp(log_probability - np.max(log_probability))
    probability = probability / np.sum(probability)

    steering = array.steering_matrix(theta, phi)
    weighted = steering * np.sqrt(probability)[None, :]
    eigenvectors, singular_values, _ = np.linalg.svd(weighted, full_matrices=False)
    energy = singular_values**2
    cumulative = np.cumsum(energy) / max(float(np.sum(energy)), np.finfo(float).tiny)
    covariance = weighted @ np.conj(weighted.T)
    covariance = 0.5 * (covariance + np.conj(covariance.T))
    trace = float(np.trace(covariance).real)
    if trace <= np.finfo(float).tiny:
        raise np.linalg.LinAlgError("degenerate confidence-sector covariance")
    covariance = covariance * (array.n_elements / trace)

    return ConfidenceSector(
        center_deg=(theta0, phi0),
        half_width_deg=(htheta, hphi),
        theta_deg=theta,
        phi_deg=phi,
        probability=probability,
        steering=steering,
        covariance=covariance,
        eigenvectors=eigenvectors,
        singular_values=singular_values,
        cumulative_energy=cumulative,
    )


def white_noise_gain_db(weights: np.ndarray) -> float:
    """White-noise gain for distortionless normalized receive weights."""
    w = np.asarray(weights, dtype=complex).reshape(-1)
    power = float(np.vdot(w, w).real)
    return float(-10.0 * np.log10(max(power, np.finfo(float).tiny)))


def relative_response_db(
    weights: np.ndarray,
    steering: np.ndarray,
    reference_steering: np.ndarray,
    *,
    floor_db: float = -180.0,
) -> np.ndarray:
    """Response relative to a reference direction, in dB."""
    w = np.asarray(weights, dtype=complex).reshape(-1)
    a = np.asarray(steering, dtype=complex)
    if a.ndim == 1:
        a = a[:, None]
    reference = np.asarray(reference_steering, dtype=complex).reshape(-1)
    denominator = max(float(np.abs(np.vdot(w, reference))), np.finfo(float).tiny)
    response = np.abs(np.conj(w) @ a) / denominator
    db = 20.0 * np.log10(np.maximum(response, 10.0 ** (floor_db / 20.0)))
    return np.asarray(db, dtype=float)


def derivative_null_basis(
    array: RectangularArray,
    center_deg: tuple[float, float],
    *,
    step_deg: float = 0.1,
) -> np.ndarray:
    """Orthonormal local manifold basis ``[a, da/dtheta, da/dphi]``."""
    if step_deg <= 0:
        raise ValueError("finite-difference step must be positive")
    theta, phi = (float(center_deg[0]), float(center_deg[1]))
    a0 = array.steering_vector(theta, phi)
    dtheta = (
        array.steering_vector(theta + step_deg, phi)
        - array.steering_vector(theta - step_deg, phi)
    ) / (2.0 * np.deg2rad(step_deg))
    dphi = (
        array.steering_vector(theta, phi + step_deg)
        - array.steering_vector(theta, phi - step_deg)
    ) / (2.0 * np.deg2rad(step_deg))
    basis = np.column_stack((a0, dtheta, dphi))
    q, r = np.linalg.qr(basis)
    diagonal = np.abs(np.diag(r))
    keep = diagonal > max(float(np.max(diagonal)), 1.0) * 1e-10
    return q[:, keep]


def derivative_lcmv_weights(
    covariance: np.ndarray,
    desired_steering: np.ndarray,
    array: RectangularArray,
    interferer_center_deg: tuple[float, float],
    *,
    loading_factor: float = 0.03,
    step_deg: float = 0.1,
) -> np.ndarray:
    """LCMV with zero response and zero first angular derivatives."""
    null_basis = derivative_null_basis(array, interferer_center_deg, step_deg=step_deg)
    constraints = np.column_stack((np.asarray(desired_steering, complex), null_basis))
    responses = np.r_[1.0, np.zeros(null_basis.shape[1])]
    return lcmv_weights(covariance, constraints, responses, loading_factor)


def soft_sector_mvdr_weights(
    covariance: np.ndarray,
    desired_steering: np.ndarray,
    sector: ConfidenceSector,
    *,
    sector_strength: float = 0.5,
    loading_factor: float = 0.03,
) -> np.ndarray:
    """MVDR with confidence-sector covariance as a soft angular penalty."""
    if sector_strength < 0:
        raise ValueError("sector_strength must be nonnegative")
    r = np.asarray(covariance, dtype=complex)
    scale = float(np.trace(r).real) / r.shape[0]
    effective = r + float(sector_strength) * scale * sector.covariance
    return mvdr_weights(effective, desired_steering, loading_factor)


def sector_energy_rank(
    sector: ConfidenceSector,
    energy_threshold: float,
    *,
    max_rank: int | None = None,
    margin_modes: int = 0,
) -> int:
    """Smallest manifold rank reaching the requested cumulative energy."""
    if not (0.0 < energy_threshold <= 1.0):
        raise ValueError("energy_threshold must lie in (0, 1]")
    if margin_modes < 0:
        raise ValueError("margin_modes must be nonnegative")
    rank = int(np.searchsorted(sector.cumulative_energy, energy_threshold) + 1 + margin_modes)
    rank = min(rank, sector.eigenvectors.shape[1])
    if max_rank is not None:
        if max_rank < 1:
            raise ValueError("max_rank must be positive")
        rank = min(rank, int(max_rank))
    return max(rank, 1)


def confidence_region_hybrid_null_weights(
    covariance: np.ndarray,
    desired_steering: np.ndarray,
    sector: ConfidenceSector,
    *,
    loading_factor: float = 0.03,
    energy_threshold: float = 0.999,
    max_rank: int = 12,
    margin_modes: int = 0,
    soft_strength: float = 0.5,
    white_noise_gain_floor_db: float = 8.0,
    condition_limit: float = 1.0e10,
) -> HybridNullResult:
    """Confidence-region eigennull LCMV with a soft residual-sector penalty.

    The initial hard-null rank is determined from weighted manifold energy.
    If the resulting LCMV violates the configured white-noise-gain or
    conditioning limit, the rank is reduced one mode at a time.  This makes
    the method degrade gracefully for very broad confidence regions or small
    arrays rather than returning an unstable high-norm solution.
    """
    if soft_strength < 0:
        raise ValueError("soft_strength must be nonnegative")
    r = np.asarray(covariance, dtype=complex)
    a_s = np.asarray(desired_steering, dtype=complex).reshape(-1)
    if r.shape != (a_s.size, a_s.size):
        raise ValueError("covariance and steering dimensions do not match")
    scale = float(np.trace(r).real) / r.shape[0]
    effective = r + float(soft_strength) * scale * sector.covariance
    initial_rank = sector_energy_rank(
        sector,
        energy_threshold,
        max_rank=max_rank,
        margin_modes=margin_modes,
    )

    last_error: Exception | None = None
    for rank in range(initial_rank, 0, -1):
        null_basis = sector.eigenvectors[:, :rank]
        constraints = np.column_stack((a_s, null_basis))
        responses = np.r_[1.0, np.zeros(rank)]
        try:
            weights = lcmv_weights(effective, constraints, responses, loading_factor)
            loaded = effective + loading_factor * np.trace(effective).real / r.shape[0] * np.eye(r.shape[0])
            inv_c = np.linalg.solve(loaded, constraints)
            gram = np.conj(constraints.T) @ inv_c
            condition = float(np.linalg.cond(gram))
            wng = white_noise_gain_db(weights)
        except np.linalg.LinAlgError as exc:
            last_error = exc
            continue
        if np.isfinite(condition) and condition <= condition_limit and wng >= white_noise_gain_floor_db:
            return HybridNullResult(
                weights=weights,
                selected_rank=rank,
                energy_coverage=float(sector.cumulative_energy[rank - 1]),
                white_noise_gain_db=wng,
                constraint_condition=condition,
                soft_strength=float(soft_strength),
                null_basis=null_basis,
            )

    if last_error is not None:
        raise np.linalg.LinAlgError("no stable confidence-region null solution") from last_error
    raise np.linalg.LinAlgError(
        "no confidence-region rank satisfies the white-noise-gain and conditioning limits"
    )


def sampled_sector_lcmv_weights(
    covariance: np.ndarray,
    desired_steering: np.ndarray,
    sector: ConfidenceSector,
    *,
    n_constraints: int = 9,
    loading_factor: float = 0.03,
) -> np.ndarray:
    """Dense sampled-sector LCMV baseline used in diagnostic ablations."""
    if n_constraints < 1:
        raise ValueError("n_constraints must be positive")
    indices = np.linspace(0, sector.n_grid_points - 1, n_constraints, dtype=int)
    constraints = np.column_stack(
        (np.asarray(desired_steering, complex), sector.steering[:, indices])
    )
    responses = np.r_[1.0, np.zeros(indices.size)]
    return lcmv_weights(covariance, constraints, responses, loading_factor)


def analytic_output_sinr_db(
    weights: np.ndarray,
    desired_steering_true: np.ndarray,
    interferer_steering_true: np.ndarray,
    *,
    desired_power: float,
    interferer_power: float,
    noise_power: float = 1.0,
) -> float:
    """Analytic narrowband output SINR for independent sources and white noise."""
    if desired_power < 0 or interferer_power < 0 or noise_power <= 0:
        raise ValueError("source powers must be nonnegative and noise power positive")
    w = np.asarray(weights, dtype=complex).reshape(-1)
    signal = float(desired_power) * np.abs(np.vdot(w, desired_steering_true)) ** 2
    interference = float(interferer_power) * np.abs(np.vdot(w, interferer_steering_true)) ** 2
    noise = float(noise_power) * float(np.vdot(w, w).real)
    return float(10.0 * np.log10(max(signal, np.finfo(float).tiny) / max(interference + noise, np.finfo(float).tiny)))


def constraint_residuals(
    weights: np.ndarray,
    constraints: np.ndarray,
    responses: Iterable[complex],
) -> np.ndarray:
    """Return ``C^H w - f`` for tests and diagnostics."""
    w = np.asarray(weights, dtype=complex).reshape(-1)
    c = np.asarray(constraints, dtype=complex)
    f = np.asarray(tuple(responses), dtype=complex).reshape(-1)
    return np.conj(c.T) @ w - f

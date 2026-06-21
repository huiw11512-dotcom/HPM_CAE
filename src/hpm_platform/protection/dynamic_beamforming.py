"""Dynamic multi-interferer receive-protection primitives.

All source powers are normalized to the white-noise variance.  The functions
here design receive weights only; they do not contain absolute source power,
range, equipment thresholds, or damage models.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

import numpy as np

from hpm_platform.physics.array_geometry import RectangularArray
from hpm_platform.protection.beamforming import lcmv_weights
from hpm_platform.protection.robust_beamforming import (
    ConfidenceSector,
    sector_energy_rank,
    white_noise_gain_db,
)


@dataclass(frozen=True)
class MultiHybridNullResult:
    weights: np.ndarray
    selected_rank: int
    requested_rank: int
    per_sector_requested_ranks: tuple[int, ...]
    white_noise_gain_db: float
    constraint_condition: float
    null_basis: np.ndarray
    mode: str


def _hermitian(matrix: np.ndarray) -> np.ndarray:
    value = np.asarray(matrix, dtype=complex)
    return 0.5 * (value + np.conj(value.T))


def fault_aware_covariance(
    covariance: np.ndarray,
    sensor_reliability: np.ndarray,
    *,
    penalty_strength: float = 0.8,
    reliability_floor: float = 0.05,
) -> np.ndarray:
    """Penalize weights on channels flagged as unreliable by perception."""
    if penalty_strength < 0:
        raise ValueError("penalty_strength must be nonnegative")
    if not 0 < reliability_floor <= 1:
        raise ValueError("reliability_floor must lie in (0, 1]")
    r = _hermitian(covariance)
    health = np.asarray(sensor_reliability, dtype=float).reshape(-1)
    if r.shape != (health.size, health.size):
        raise ValueError("sensor reliability size does not match covariance")
    health = np.clip(health, reliability_floor, 1.0)
    penalty = (1.0 - health) / health
    if np.max(penalty) > 0:
        penalty = penalty / np.max(penalty)
    scale = max(float(np.trace(r).real / r.shape[0]), np.finfo(float).tiny)
    result = r + float(penalty_strength) * scale * np.diag(penalty)
    return _hermitian(result)


def build_covariance_confidence_sector(
    array: RectangularArray,
    center_deg: tuple[float, float],
    covariance_deg2: np.ndarray,
    *,
    confidence_radius: float = 2.45,
    grid_step_deg: float = 0.75,
    min_half_width_deg: float = 1.5,
    max_half_width_deg: float = 12.0,
) -> ConfidenceSector:
    """Build a rotated Gaussian confidence sector from a 2-D DOA covariance."""
    if confidence_radius <= 0 or grid_step_deg <= 0:
        raise ValueError("confidence_radius and grid_step_deg must be positive")
    if min_half_width_deg <= 0 or max_half_width_deg < min_half_width_deg:
        raise ValueError("invalid half-width bounds")
    center = np.asarray(center_deg, dtype=float).reshape(2)
    covariance = np.asarray(covariance_deg2, dtype=float)
    if covariance.shape != (2, 2):
        raise ValueError("covariance_deg2 must have shape (2, 2)")
    covariance = 0.5 * (covariance + covariance.T)
    eigenvalues, eigenvectors = np.linalg.eigh(covariance)
    eigenvalues = np.maximum(eigenvalues, (min_half_width_deg / confidence_radius) ** 2)
    covariance = (eigenvectors * eigenvalues) @ eigenvectors.T
    inverse = np.linalg.inv(covariance)

    bounding_half_width = confidence_radius * np.sqrt(np.diag(covariance))
    bounding_half_width = np.clip(
        bounding_half_width,
        min_half_width_deg,
        max_half_width_deg,
    )
    theta_min = max(0.1, center[0] - bounding_half_width[0])
    theta_max = min(89.9, center[0] + bounding_half_width[0])
    phi_min = center[1] - bounding_half_width[1]
    phi_max = center[1] + bounding_half_width[1]
    theta = np.arange(theta_min, theta_max + 0.5 * grid_step_deg, grid_step_deg)
    phi = np.arange(phi_min, phi_max + 0.5 * grid_step_deg, grid_step_deg)
    tt, pp = np.meshgrid(theta, phi, indexing="ij")
    offsets = np.column_stack((tt.ravel() - center[0], pp.ravel() - center[1]))
    mahalanobis_sq = np.einsum("ni,ij,nj->n", offsets, inverse, offsets)
    mask = mahalanobis_sq <= confidence_radius**2 + 1e-12
    if int(np.sum(mask)) < 3:
        # Coarse-grid fallback: keep nearest points.
        mask[np.argsort(mahalanobis_sq)[:3]] = True
    selected_theta = tt.ravel()[mask]
    selected_phi = pp.ravel()[mask]
    selected_distance = mahalanobis_sq[mask]
    probability = np.exp(-0.5 * selected_distance)
    probability = probability / max(float(np.sum(probability)), np.finfo(float).tiny)

    steering = array.steering_matrix(selected_theta, selected_phi)
    weighted = steering * np.sqrt(probability)[None, :]
    eigenvectors_sector, singular_values, _ = np.linalg.svd(weighted, full_matrices=False)
    energy = singular_values**2
    cumulative = np.cumsum(energy) / max(float(np.sum(energy)), np.finfo(float).tiny)
    sector_covariance = weighted @ np.conj(weighted.T)
    sector_covariance = _hermitian(sector_covariance)
    trace = max(float(np.trace(sector_covariance).real), np.finfo(float).tiny)
    sector_covariance *= array.n_elements / trace
    return ConfidenceSector(
        center_deg=(float(center[0]), float(center[1])),
        half_width_deg=(float(bounding_half_width[0]), float(bounding_half_width[1])),
        theta_deg=selected_theta,
        phi_deg=selected_phi,
        probability=probability,
        steering=steering,
        covariance=sector_covariance,
        eigenvectors=eigenvectors_sector,
        singular_values=singular_values,
        cumulative_energy=cumulative,
    )


def multi_point_lcmv_weights(
    covariance: np.ndarray,
    desired_steering: np.ndarray,
    array: RectangularArray,
    interferer_centers_deg: Sequence[tuple[float, float]],
    *,
    loading_factor: float = 0.03,
) -> np.ndarray:
    """LCMV with one point null per interferer."""
    if len(interferer_centers_deg) < 1:
        raise ValueError("at least one interferer center is required")
    columns = [np.asarray(desired_steering, dtype=complex).reshape(-1)]
    columns.extend(array.steering_vector(*center) for center in interferer_centers_deg)
    constraints = np.column_stack(columns)
    responses = np.r_[1.0, np.zeros(len(interferer_centers_deg))]
    return lcmv_weights(covariance, constraints, responses, loading_factor)


def _round_robin_basis(sectors: Sequence[ConfidenceSector], ranks: Sequence[int]) -> np.ndarray:
    columns: list[np.ndarray] = []
    maximum = max(ranks, default=0)
    for mode in range(maximum):
        for sector, rank in zip(sectors, ranks):
            if mode < rank:
                columns.append(sector.eigenvectors[:, mode])
    if not columns:
        raise ValueError("at least one sector mode is required")
    raw = np.column_stack(columns)
    q, r = np.linalg.qr(raw)
    diagonal = np.abs(np.diag(r))
    threshold = max(float(np.max(diagonal)), 1.0) * 1e-10
    return q[:, diagonal > threshold]


def multi_confidence_region_hybrid_null_weights(
    covariance: np.ndarray,
    desired_steering: np.ndarray,
    sectors: Sequence[ConfidenceSector],
    *,
    loading_factor: float = 0.03,
    energy_threshold: float = 0.995,
    max_rank_per_sector: int = 7,
    max_total_rank: int = 14,
    soft_strength: float = 0.45,
    white_noise_gain_floor_db: float = 6.0,
    condition_limit: float = 1e10,
) -> MultiHybridNullResult:
    """Joint hard/soft nulling for multiple covariance-shaped sectors."""
    if len(sectors) < 1:
        raise ValueError("at least one confidence sector is required")
    if max_rank_per_sector < 1 or max_total_rank < 1:
        raise ValueError("rank limits must be positive")
    if soft_strength < 0:
        raise ValueError("soft_strength must be nonnegative")
    r = _hermitian(covariance)
    desired = np.asarray(desired_steering, dtype=complex).reshape(-1)
    if r.shape != (desired.size, desired.size):
        raise ValueError("covariance and desired steering dimensions do not match")

    scale = max(float(np.trace(r).real / r.shape[0]), np.finfo(float).tiny)
    soft_covariance = sum((sector.covariance for sector in sectors), start=np.zeros_like(r))
    effective = r + float(soft_strength) * scale * soft_covariance / len(sectors)

    requested_ranks = tuple(
        sector_energy_rank(
            sector,
            energy_threshold,
            max_rank=max_rank_per_sector,
        )
        for sector in sectors
    )
    basis = _round_robin_basis(sectors, requested_ranks)
    requested_total = min(int(basis.shape[1]), int(max_total_rank))
    basis = basis[:, :requested_total]

    last_error: Exception | None = None
    minimum_rank = min(len(sectors), requested_total)
    for rank in range(requested_total, minimum_rank - 1, -1):
        null_basis = basis[:, :rank]
        constraints = np.column_stack((desired, null_basis))
        responses = np.r_[1.0, np.zeros(rank)]
        try:
            weights = lcmv_weights(effective, constraints, responses, loading_factor)
            loaded = effective + loading_factor * scale * np.eye(r.shape[0])
            inv_constraints = np.linalg.solve(loaded, constraints)
            gram = np.conj(constraints.T) @ inv_constraints
            condition = float(np.linalg.cond(gram))
            wng = white_noise_gain_db(weights)
        except np.linalg.LinAlgError as exc:
            last_error = exc
            continue
        if np.isfinite(condition) and condition <= condition_limit and wng >= white_noise_gain_floor_db:
            return MultiHybridNullResult(
                weights=np.asarray(weights, complex),
                selected_rank=rank,
                requested_rank=requested_total,
                per_sector_requested_ranks=requested_ranks,
                white_noise_gain_db=wng,
                constraint_condition=condition,
                null_basis=null_basis,
                mode="hard+soft",
            )

    # Stable soft-only fallback preserves the desired response and avoids
    # returning an unusable high-norm hard-null solution.
    try:
        loaded = effective + loading_factor * scale * np.eye(r.shape[0])
        solved = np.linalg.solve(loaded, desired)
        denominator = np.vdot(desired, solved)
        if np.abs(denominator) < np.finfo(float).eps:
            raise np.linalg.LinAlgError("degenerate soft-only normalization")
        weights = solved / denominator
    except np.linalg.LinAlgError as exc:
        if last_error is not None:
            raise np.linalg.LinAlgError("no stable multi-sector solution") from last_error
        raise exc
    return MultiHybridNullResult(
        weights=np.asarray(weights, complex),
        selected_rank=0,
        requested_rank=requested_total,
        per_sector_requested_ranks=requested_ranks,
        white_noise_gain_db=white_noise_gain_db(weights),
        constraint_condition=float("nan"),
        null_basis=np.empty((desired.size, 0), dtype=complex),
        mode="soft-only",
    )


def analytic_output_sinr_multi_db(
    weights: np.ndarray,
    desired_steering_true: np.ndarray,
    interferer_steering_true: Sequence[np.ndarray],
    *,
    desired_power: float,
    interferer_powers: Sequence[float],
    noise_power: float = 1.0,
) -> float:
    """Analytic output SINR for independent multiple interferers."""
    if desired_power < 0 or noise_power <= 0:
        raise ValueError("desired power must be nonnegative and noise power positive")
    if len(interferer_steering_true) != len(interferer_powers):
        raise ValueError("one power is required per interferer")
    w = np.asarray(weights, dtype=complex).reshape(-1)
    signal = float(desired_power) * np.abs(np.vdot(w, desired_steering_true)) ** 2
    interference = 0.0
    for steering, power in zip(interferer_steering_true, interferer_powers):
        if power < 0:
            raise ValueError("interferer powers must be nonnegative")
        interference += float(power) * np.abs(np.vdot(w, np.asarray(steering, complex))) ** 2
    noise = float(noise_power) * float(np.vdot(w, w).real)
    ratio = max(float(signal), np.finfo(float).tiny) / max(
        float(interference + noise), np.finfo(float).tiny
    )
    return float(10.0 * np.log10(ratio))


def worst_interferer_response_db(
    weights: np.ndarray,
    desired_steering_reference: np.ndarray,
    interferer_steering_true: Sequence[np.ndarray],
    *,
    floor_db: float = -180.0,
) -> float:
    """Largest actual interferer response relative to desired response."""
    w = np.asarray(weights, dtype=complex).reshape(-1)
    denominator = max(
        float(np.abs(np.vdot(w, np.asarray(desired_steering_reference, complex)))),
        np.finfo(float).tiny,
    )
    values = [
        float(np.abs(np.vdot(w, np.asarray(steering, complex))) / denominator)
        for steering in interferer_steering_true
    ]
    maximum = max(values, default=0.0)
    return float(20.0 * np.log10(max(maximum, 10.0 ** (floor_db / 20.0))))

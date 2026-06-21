"""Normalized near-field region shaping and scenario-robust optimization.

The functions operate on a scalar Green-function approximation and normalized
complex element excitations.  They are intended for reproducible algorithm
research, not for absolute field-strength, link-budget, or device-effect
prediction.
"""
from __future__ import annotations

from dataclasses import dataclass
import time
from typing import Sequence

import numpy as np

from hpm_platform.physics.array_geometry import RectangularArray


@dataclass(frozen=True)
class RegionMasks:
    target: np.ndarray
    guard: np.ndarray
    outside: np.ndarray
    normalized_radius: np.ndarray


@dataclass(frozen=True)
class ShapingResult:
    weights: np.ndarray
    objective_history: np.ndarray
    runtime_ms: float


@dataclass(frozen=True)
class LinearScenarioSet:
    target_matrices: tuple[np.ndarray, ...]
    outside_matrices: tuple[np.ndarray, ...]
    gain_vectors: tuple[np.ndarray, ...]
    shifts_m: tuple[np.ndarray, ...]


def scalar_green_matrix(
    array: RectangularArray,
    points_m: np.ndarray,
    *,
    reference_scale: float = 1.0,
    element_gains: np.ndarray | None = None,
    chunk_size: int = 4096,
) -> np.ndarray:
    """Return scalar Green-function coefficients with shape (P, M)."""
    points = np.asarray(points_m, dtype=float).reshape(-1, 3)
    if reference_scale <= 0 or chunk_size < 1:
        raise ValueError("reference_scale and chunk_size must be positive")
    gains = np.ones(array.n_elements, dtype=complex)
    if element_gains is not None:
        gains = np.asarray(element_gains, dtype=complex).reshape(-1)
        if gains.size != array.n_elements:
            raise ValueError("element_gains size does not match the array")

    output = np.empty((points.shape[0], array.n_elements), dtype=complex)
    positions = array.positions_m
    for start in range(0, points.shape[0], int(chunk_size)):
        stop = min(start + int(chunk_size), points.shape[0])
        delta = points[start:stop, None, :] - positions[None, :, :]
        ranges = np.linalg.norm(delta, axis=2)
        ranges = np.maximum(ranges, array.wavelength_m * 1e-8)
        output[start:stop] = (
            np.exp(-1j * array.wave_number * ranges) / ranges / float(reference_scale)
        ) * gains[None, :]
    return output


def unit_rms_point_focus_weights(
    array: RectangularArray,
    focus_point_m: np.ndarray,
    *,
    rms_amplitude: float = 1.0,
) -> np.ndarray:
    """Return phase-conjugate point-focus weights with specified element RMS."""
    if rms_amplitude < 0:
        raise ValueError("rms_amplitude must be non-negative")
    focus = np.asarray(focus_point_m, dtype=float).reshape(3)
    ranges = np.linalg.norm(focus[None, :] - array.positions_m, axis=1)
    if np.any(ranges <= 0):
        raise ValueError("focus cannot coincide with an array element")
    return float(rms_amplitude) * np.exp(1j * array.wave_number * ranges)


def point_focus_reference_scale(array: RectangularArray, focus_point_m: np.ndarray) -> float:
    """Field magnitude at the focus for unit-RMS phase-conjugate weights."""
    focus = np.asarray(focus_point_m, dtype=float).reshape(1, 3)
    weights = unit_rms_point_focus_weights(array, focus.ravel(), rms_amplitude=1.0)
    matrix = scalar_green_matrix(array, focus, reference_scale=1.0)
    value = float(np.abs(matrix @ weights).item())
    if not np.isfinite(value) or value <= 0:
        raise RuntimeError("invalid reference field scale")
    return value


def rotated_ellipse_masks(
    x_m: np.ndarray,
    y_m: np.ndarray,
    *,
    center_m: tuple[float, float],
    semi_axes_m: tuple[float, float],
    rotation_deg: float = 0.0,
    guard_scale: float = 1.45,
) -> RegionMasks:
    """Build target, transition guard, and outside masks for a rotated ellipse."""
    xx, yy = np.broadcast_arrays(np.asarray(x_m, float), np.asarray(y_m, float))
    major, minor = map(float, semi_axes_m)
    if major <= 0 or minor <= 0 or guard_scale <= 1.0:
        raise ValueError("semi-axes must be positive and guard_scale must exceed one")
    angle = np.deg2rad(float(rotation_deg))
    dx = xx - float(center_m[0])
    dy = yy - float(center_m[1])
    x_rot = np.cos(angle) * dx + np.sin(angle) * dy
    y_rot = -np.sin(angle) * dx + np.cos(angle) * dy
    radius = np.sqrt((x_rot / major) ** 2 + (y_rot / minor) ** 2)
    return RegionMasks(
        target=radius <= 1.0,
        guard=(radius > 1.0) & (radius < float(guard_scale)),
        outside=radius >= float(guard_scale),
        normalized_radius=radius,
    )


def project_excitation(
    weights: np.ndarray,
    *,
    rms_limit: float,
    peak_limit: float,
) -> np.ndarray:
    """Project complex weights onto element-peak and total-RMS limits."""
    if rms_limit <= 0 or peak_limit <= 0:
        raise ValueError("rms_limit and peak_limit must be positive")
    projected = np.asarray(weights, dtype=complex).reshape(-1).copy()
    magnitude = np.abs(projected)
    too_large = magnitude > float(peak_limit)
    if np.any(too_large):
        projected[too_large] *= float(peak_limit) / magnitude[too_large]
    rms = float(np.sqrt(np.mean(np.abs(projected) ** 2)))
    if rms > float(rms_limit):
        projected *= float(rms_limit) / rms
    return projected


def scale_to_target_amplitude(
    weights: np.ndarray,
    target_matrix: np.ndarray,
    *,
    target_amplitude: float,
    rms_limit: float,
    peak_limit: float,
) -> np.ndarray:
    """Apply the least-squares positive scalar that best matches target magnitude."""
    if target_amplitude <= 0:
        raise ValueError("target_amplitude must be positive")
    w = np.asarray(weights, dtype=complex).reshape(-1)
    matrix = np.asarray(target_matrix, dtype=complex)
    amplitudes = np.abs(matrix @ w)
    denominator = float(np.sum(amplitudes**2))
    if denominator <= np.finfo(float).tiny:
        return project_excitation(w, rms_limit=rms_limit, peak_limit=peak_limit)
    scalar = float(target_amplitude) * float(np.sum(amplitudes)) / denominator
    return project_excitation(
        max(scalar, 0.0) * w,
        rms_limit=rms_limit,
        peak_limit=peak_limit,
    )


def region_least_squares_weights(
    target_matrix: np.ndarray,
    outside_matrix: np.ndarray,
    phase_template_weights: np.ndarray,
    *,
    target_amplitude: float,
    outside_penalty: float,
    ridge: float,
    rms_limit: float,
    peak_limit: float,
) -> np.ndarray:
    """Closed-form complex region-LS baseline with a point-focus phase template."""
    target = np.asarray(target_matrix, dtype=complex)
    outside = np.asarray(outside_matrix, dtype=complex)
    template = np.asarray(phase_template_weights, dtype=complex).reshape(-1)
    if target.shape[1] != outside.shape[1] or target.shape[1] != template.size:
        raise ValueError("matrix and weight dimensions are inconsistent")
    if target_amplitude <= 0 or outside_penalty < 0 or ridge < 0:
        raise ValueError("invalid optimization parameter")

    phase = np.angle(target @ template)
    desired = float(target_amplitude) * np.exp(1j * phase)
    hessian = target.conj().T @ target
    hessian += float(outside_penalty) * (outside.conj().T @ outside)
    hessian += float(ridge) * np.eye(target.shape[1])
    rhs = target.conj().T @ desired
    weights = np.linalg.solve(hessian, rhs)
    weights = project_excitation(weights, rms_limit=rms_limit, peak_limit=peak_limit)
    return scale_to_target_amplitude(
        weights,
        target,
        target_amplitude=target_amplitude,
        rms_limit=rms_limit,
        peak_limit=peak_limit,
    )


def magnitude_objective_gradient(
    weights: np.ndarray,
    target_matrices: Sequence[np.ndarray],
    outside_matrices: Sequence[np.ndarray],
    *,
    target_amplitude: float,
    outside_hinge_amplitude: float,
    outside_penalty: float,
    power_regularization: float = 5e-4,
) -> tuple[float, np.ndarray]:
    """Return scenario-averaged magnitude loss and a Wirtinger descent gradient."""
    if not target_matrices or not outside_matrices:
        raise ValueError("at least one target and outside scenario is required")
    if len(target_matrices) != len(outside_matrices):
        raise ValueError("target and outside scenario counts must match")
    if target_amplitude <= 0 or outside_hinge_amplitude < 0 or outside_penalty < 0:
        raise ValueError("invalid magnitude objective parameter")

    w = np.asarray(weights, dtype=complex).reshape(-1)
    gradient = np.zeros_like(w)
    objective = 0.0
    scale_sq = float(target_amplitude) ** 2
    n_scenarios = len(target_matrices)

    for target in target_matrices:
        matrix = np.asarray(target, dtype=complex)
        field = matrix @ w
        amplitude = np.abs(field)
        error = amplitude - float(target_amplitude)
        objective += float(np.mean(error**2) / scale_sq) / n_scenarios
        direction = field / np.maximum(amplitude, 1e-12)
        gradient += (
            matrix.conj().T @ ((error / scale_sq) * direction)
        ) / (matrix.shape[0] * n_scenarios)

    for outside in outside_matrices:
        matrix = np.asarray(outside, dtype=complex)
        field = matrix @ w
        amplitude = np.abs(field)
        excess = np.maximum(amplitude - float(outside_hinge_amplitude), 0.0)
        objective += (
            float(outside_penalty) * float(np.mean(excess**2) / scale_sq) / n_scenarios
        )
        direction = field / np.maximum(amplitude, 1e-12)
        gradient += (
            float(outside_penalty)
            * (matrix.conj().T @ ((excess / scale_sq) * direction))
            / (matrix.shape[0] * n_scenarios)
        )

    objective += float(power_regularization) * float(np.mean(np.abs(w) ** 2))
    gradient += float(power_regularization) * w / w.size
    return objective, gradient


def projected_adam_magnitude_shaping(
    initial_weights: np.ndarray,
    target_matrices: Sequence[np.ndarray],
    outside_matrices: Sequence[np.ndarray],
    *,
    target_amplitude: float,
    outside_hinge_amplitude: float,
    outside_penalty: float,
    rms_limit: float,
    peak_limit: float,
    iterations: int = 600,
    learning_rate: float = 0.025,
    beta1: float = 0.9,
    beta2: float = 0.999,
    epsilon: float = 1e-8,
    power_regularization: float = 5e-4,
) -> ShapingResult:
    """Projected complex Adam optimizer for normalized magnitude shaping."""
    if iterations < 1 or learning_rate <= 0:
        raise ValueError("iterations and learning_rate must be positive")
    start = time.perf_counter()
    weights = project_excitation(
        initial_weights,
        rms_limit=rms_limit,
        peak_limit=peak_limit,
    )
    first_moment = np.zeros_like(weights)
    second_moment = np.zeros(weights.shape, dtype=float)
    history = np.empty(int(iterations), dtype=float)
    best_objective = np.inf
    best_weights = weights.copy()

    for iteration in range(1, int(iterations) + 1):
        objective, gradient = magnitude_objective_gradient(
            weights,
            target_matrices,
            outside_matrices,
            target_amplitude=target_amplitude,
            outside_hinge_amplitude=outside_hinge_amplitude,
            outside_penalty=outside_penalty,
            power_regularization=power_regularization,
        )
        first_moment = beta1 * first_moment + (1.0 - beta1) * gradient
        second_moment = beta2 * second_moment + (1.0 - beta2) * np.abs(gradient) ** 2
        corrected_first = first_moment / (1.0 - beta1**iteration)
        corrected_second = second_moment / (1.0 - beta2**iteration)
        weights = weights - float(learning_rate) * corrected_first / (
            np.sqrt(corrected_second) + float(epsilon)
        )
        weights = project_excitation(
            weights,
            rms_limit=rms_limit,
            peak_limit=peak_limit,
        )
        history[iteration - 1] = objective
        if objective < best_objective:
            best_objective = objective
            best_weights = weights.copy()

    return ShapingResult(
        weights=best_weights,
        objective_history=history,
        runtime_ms=1000.0 * (time.perf_counter() - start),
    )


def sample_linear_scenarios(
    array: RectangularArray,
    target_points_m: np.ndarray,
    outside_points_m: np.ndarray,
    *,
    reference_scale: float,
    n_scenarios: int,
    gain_std_fraction: float,
    phase_std_deg: float,
    registration_jitter_std_lambda: float,
    seed: int,
    include_nominal: bool = True,
) -> LinearScenarioSet:
    """Generate multiplicative channel and plane-registration scenarios."""
    if n_scenarios < 1:
        raise ValueError("n_scenarios must be positive")
    if gain_std_fraction < 0 or phase_std_deg < 0 or registration_jitter_std_lambda < 0:
        raise ValueError("uncertainty standard deviations must be non-negative")
    rng = np.random.default_rng(int(seed))
    target_points = np.asarray(target_points_m, dtype=float).reshape(-1, 3)
    outside_points = np.asarray(outside_points_m, dtype=float).reshape(-1, 3)
    target_matrices: list[np.ndarray] = []
    outside_matrices: list[np.ndarray] = []
    gain_vectors: list[np.ndarray] = []
    shifts: list[np.ndarray] = []

    for index in range(int(n_scenarios)):
        if include_nominal and index == 0:
            gains = np.ones(array.n_elements, dtype=complex)
            shift = np.zeros(3, dtype=float)
        else:
            amplitudes = np.clip(
                1.0 + rng.normal(0.0, float(gain_std_fraction), array.n_elements),
                0.2,
                None,
            )
            phases = np.deg2rad(rng.normal(0.0, float(phase_std_deg), array.n_elements))
            gains = amplitudes * np.exp(1j * phases)
            shift = np.array(
                [
                    rng.normal(0.0, float(registration_jitter_std_lambda) * array.wavelength_m),
                    rng.normal(0.0, float(registration_jitter_std_lambda) * array.wavelength_m),
                    0.0,
                ],
                dtype=float,
            )
        target_matrices.append(
            scalar_green_matrix(
                array,
                target_points + shift,
                reference_scale=reference_scale,
                element_gains=gains,
            )
        )
        outside_matrices.append(
            scalar_green_matrix(
                array,
                outside_points + shift,
                reference_scale=reference_scale,
                element_gains=gains,
            )
        )
        gain_vectors.append(gains)
        shifts.append(shift)

    return LinearScenarioSet(
        target_matrices=tuple(target_matrices),
        outside_matrices=tuple(outside_matrices),
        gain_vectors=tuple(gain_vectors),
        shifts_m=tuple(shifts),
    )

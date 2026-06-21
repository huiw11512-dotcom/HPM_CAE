"""Object-aware constrained near-field shaping for HPM-CAE V1.2.

All quantities are wavelength-scaled and normalized.  The optimizer balances
multiple target-region setpoints, explicit protected-zone exposure caps, and a
general outside-region hinge penalty.  It is a numerical research layer, not a
full-wave or absolute-power solver.
"""
from __future__ import annotations

from dataclasses import dataclass
import time
from typing import Sequence

import numpy as np

from hpm_platform.field_control.region_shaping import project_excitation, scalar_green_matrix
from hpm_platform.physics.array_geometry import RectangularArray


@dataclass(frozen=True)
class GroupedScenarioSet:
    """Scenario matrices grouped by target/protected object.

    Outer tuples index uncertainty scenarios.  Inner tuples index scene
    objects.  The same gain/phase vector and registration shift are used for
    every object within one scenario.
    """

    target_matrices: tuple[tuple[np.ndarray, ...], ...]
    outside_matrices: tuple[np.ndarray, ...]
    protected_matrices: tuple[tuple[np.ndarray, ...], ...]
    gain_vectors: tuple[np.ndarray, ...]
    shifts_m: tuple[np.ndarray, ...]


@dataclass(frozen=True)
class MultiObjectiveShapingResult:
    weights: np.ndarray
    objective_history: np.ndarray
    component_history: np.ndarray
    component_labels: tuple[str, ...]
    runtime_ms: float

    @property
    def final_components(self) -> dict[str, float]:
        if self.component_history.size == 0:
            return {label: float("nan") for label in self.component_labels}
        return {
            label: float(value)
            for label, value in zip(self.component_labels, self.component_history[-1], strict=True)
        }


def sample_grouped_scenarios(
    array: RectangularArray,
    target_point_groups_m: Sequence[np.ndarray],
    outside_points_m: np.ndarray,
    protected_point_groups_m: Sequence[np.ndarray],
    *,
    reference_scale: float,
    n_scenarios: int,
    gain_std_fraction: float,
    phase_std_deg: float,
    registration_jitter_std_lambda: float,
    seed: int,
    include_nominal: bool = True,
) -> GroupedScenarioSet:
    """Generate consistent linear scenarios for every scene object."""
    if int(n_scenarios) < 1:
        raise ValueError("n_scenarios must be positive")
    if gain_std_fraction < 0 or phase_std_deg < 0 or registration_jitter_std_lambda < 0:
        raise ValueError("uncertainty standard deviations must be non-negative")
    target_groups = tuple(np.asarray(points, float).reshape(-1, 3) for points in target_point_groups_m)
    protected_groups = tuple(np.asarray(points, float).reshape(-1, 3) for points in protected_point_groups_m)
    outside_points = np.asarray(outside_points_m, float).reshape(-1, 3)
    if not target_groups or any(points.shape[0] == 0 for points in target_groups):
        raise ValueError("every target group must contain at least one point")
    if outside_points.shape[0] == 0:
        raise ValueError("outside_points_m cannot be empty")
    if any(points.shape[0] == 0 for points in protected_groups):
        raise ValueError("protected groups cannot be empty")

    rng = np.random.default_rng(int(seed))
    target_scenarios: list[tuple[np.ndarray, ...]] = []
    outside_scenarios: list[np.ndarray] = []
    protected_scenarios: list[tuple[np.ndarray, ...]] = []
    gains_all: list[np.ndarray] = []
    shifts_all: list[np.ndarray] = []

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
        target_scenarios.append(
            tuple(
                scalar_green_matrix(
                    array,
                    points + shift,
                    reference_scale=reference_scale,
                    element_gains=gains,
                )
                for points in target_groups
            )
        )
        outside_scenarios.append(
            scalar_green_matrix(
                array,
                outside_points + shift,
                reference_scale=reference_scale,
                element_gains=gains,
            )
        )
        protected_scenarios.append(
            tuple(
                scalar_green_matrix(
                    array,
                    points + shift,
                    reference_scale=reference_scale,
                    element_gains=gains,
                )
                for points in protected_groups
            )
        )
        gains_all.append(gains)
        shifts_all.append(shift)

    return GroupedScenarioSet(
        target_matrices=tuple(target_scenarios),
        outside_matrices=tuple(outside_scenarios),
        protected_matrices=tuple(protected_scenarios),
        gain_vectors=tuple(gains_all),
        shifts_m=tuple(shifts_all),
    )


def _validate_problem(
    initial_weights: np.ndarray,
    target_scenarios: Sequence[Sequence[np.ndarray]],
    desired_groups: Sequence[np.ndarray],
    target_priorities: np.ndarray,
    outside_scenarios: Sequence[np.ndarray],
    protected_scenarios: Sequence[Sequence[np.ndarray]],
    protected_limits: np.ndarray,
    protected_priorities: np.ndarray,
) -> tuple[int, int, int, int]:
    weights = np.asarray(initial_weights, complex).reshape(-1)
    if weights.size == 0:
        raise ValueError("initial_weights cannot be empty")
    n_scenarios = len(target_scenarios)
    if n_scenarios == 0 or len(outside_scenarios) != n_scenarios or len(protected_scenarios) != n_scenarios:
        raise ValueError("target, outside, and protected scenario counts must match and be nonzero")
    n_targets = len(desired_groups)
    n_protected = len(protected_limits)
    if n_targets == 0 or target_priorities.size != n_targets:
        raise ValueError("target desired vectors and priorities are inconsistent")
    if protected_priorities.size != n_protected:
        raise ValueError("protected limits and priorities are inconsistent")
    for scenario_index in range(n_scenarios):
        if len(target_scenarios[scenario_index]) != n_targets:
            raise ValueError("each target scenario must contain every target object")
        if len(protected_scenarios[scenario_index]) != n_protected:
            raise ValueError("each protected scenario must contain every protected object")
        if np.asarray(outside_scenarios[scenario_index]).shape[1] != weights.size:
            raise ValueError("outside matrix width does not match weights")
        for group_index, matrix in enumerate(target_scenarios[scenario_index]):
            array = np.asarray(matrix)
            if array.ndim != 2 or array.shape[1] != weights.size:
                raise ValueError("target matrix width does not match weights")
            if array.shape[0] != np.asarray(desired_groups[group_index]).size:
                raise ValueError("target matrix rows do not match desired group")
        for matrix in protected_scenarios[scenario_index]:
            array = np.asarray(matrix)
            if array.ndim != 2 or array.shape[1] != weights.size:
                raise ValueError("protected matrix width does not match weights")
    if np.any(np.asarray(target_priorities, float) <= 0) or np.any(np.asarray(protected_priorities, float) <= 0):
        raise ValueError("object priorities must be positive")
    if np.any(np.asarray(protected_limits, float) <= 0):
        raise ValueError("protected limits must be positive")
    return weights.size, n_scenarios, n_targets, n_protected


def _magnitude_error_loss_gradient(
    matrix: np.ndarray,
    weights: np.ndarray,
    desired: np.ndarray,
) -> tuple[float, np.ndarray]:
    field = np.asarray(matrix, complex) @ weights
    amplitude = np.abs(field)
    target = np.asarray(desired, float).reshape(-1)
    denominator = np.maximum(target, 1e-12)
    normalized_error = (amplitude - target) / denominator
    direction = field / np.maximum(amplitude, 1e-12)
    loss = float(np.mean(normalized_error**2))
    gradient = np.asarray(matrix, complex).conj().T @ (
        (normalized_error / denominator) * direction
    ) / max(matrix.shape[0], 1)
    return loss, gradient


def _hinge_loss_gradient(
    matrix: np.ndarray,
    weights: np.ndarray,
    *,
    limit: float,
    reference_scale: float,
    tail_penalty: float,
    tail_fraction: float,
) -> tuple[float, np.ndarray]:
    field = np.asarray(matrix, complex) @ weights
    amplitude = np.abs(field)
    excess = np.maximum(amplitude - float(limit), 0.0)
    direction = field / np.maximum(amplitude, 1e-12)
    scale_sq = max(float(reference_scale) ** 2, 1e-12)
    base_loss = float(np.mean(excess**2) / scale_sq)
    base_gradient = np.asarray(matrix, complex).conj().T @ (
        (excess / scale_sq) * direction
    ) / max(matrix.shape[0], 1)
    if tail_penalty <= 0 or not np.any(excess > 0):
        return base_loss, base_gradient
    count = max(1, int(np.ceil(float(tail_fraction) * excess.size)))
    indices = np.argpartition(excess, -count)[-count:]
    tail_excess = excess[indices]
    tail_direction = direction[indices]
    tail_matrix = np.asarray(matrix, complex)[indices]
    tail_loss = float(np.mean(tail_excess**2) / scale_sq)
    tail_gradient = tail_matrix.conj().T @ (
        (tail_excess / scale_sq) * tail_direction
    ) / count
    return base_loss + float(tail_penalty) * tail_loss, base_gradient + float(tail_penalty) * tail_gradient


def projected_adam_multi_object(
    initial_weights: np.ndarray,
    target_scenarios: Sequence[Sequence[np.ndarray]],
    desired_groups: Sequence[np.ndarray],
    target_priorities: Sequence[float],
    outside_scenarios: Sequence[np.ndarray],
    protected_scenarios: Sequence[Sequence[np.ndarray]],
    protected_limits: Sequence[float],
    protected_priorities: Sequence[float],
    *,
    outside_hinge_amplitude: float,
    outside_penalty: float,
    protected_penalty: float,
    fairness_penalty: float,
    tail_penalty: float,
    tail_fraction: float,
    reference_amplitude: float,
    rms_limit: float,
    peak_limit: float,
    iterations: int,
    learning_rate: float,
    power_regularization: float = 5e-4,
    fairness_temperature: float = 8.0,
    gradient_clip: float = 8.0,
) -> MultiObjectiveShapingResult:
    """Solve a robust object-aware magnitude-shaping problem.

    The target term is a priority-weighted normalized error.  A smooth-max
    fairness term discourages sacrificing a small or low-area target.  General
    outside samples and each protected zone use separate hinge limits with a
    tail term so isolated peaks cannot hide inside a mean-square objective.
    """
    target_priorities_array = np.asarray(target_priorities, float).reshape(-1)
    protected_priorities_array = np.asarray(protected_priorities, float).reshape(-1)
    protected_limits_array = np.asarray(protected_limits, float).reshape(-1)
    desired = tuple(np.asarray(item, float).reshape(-1) for item in desired_groups)
    _, n_scenarios, n_targets, n_protected = _validate_problem(
        initial_weights,
        target_scenarios,
        desired,
        target_priorities_array,
        outside_scenarios,
        protected_scenarios,
        protected_limits_array,
        protected_priorities_array,
    )
    if iterations < 1 or learning_rate <= 0 or reference_amplitude <= 0:
        raise ValueError("iterations, learning_rate, and reference_amplitude must be positive")
    if min(outside_hinge_amplitude, outside_penalty, protected_penalty, fairness_penalty, tail_penalty) < 0:
        raise ValueError("penalties and hinge amplitudes must be non-negative")
    if not 0.01 <= float(tail_fraction) <= 0.5:
        raise ValueError("tail_fraction must be in [0.01, 0.5]")

    target_weights = target_priorities_array / np.sum(target_priorities_array)
    protected_weights = (
        protected_priorities_array / np.sum(protected_priorities_array)
        if n_protected
        else np.empty(0, dtype=float)
    )
    weights = project_excitation(np.asarray(initial_weights, complex), rms_limit=rms_limit, peak_limit=peak_limit)
    first = np.zeros_like(weights)
    second = np.zeros(weights.shape, dtype=float)
    labels = ("target", "fairness", "outside", "protected", "power", "total")
    history = np.empty(int(iterations), dtype=float)
    components = np.empty((int(iterations), len(labels)), dtype=float)
    best_weights = weights.copy()
    best_objective = float("inf")
    started = time.perf_counter()

    for iteration in range(1, int(iterations) + 1):
        gradient = np.zeros_like(weights)
        target_component = 0.0
        fairness_component = 0.0
        outside_component = 0.0
        protected_component = 0.0

        for scenario_index in range(n_scenarios):
            group_losses: list[float] = []
            group_gradients: list[np.ndarray] = []
            for group_index in range(n_targets):
                loss, grad = _magnitude_error_loss_gradient(
                    target_scenarios[scenario_index][group_index],
                    weights,
                    desired[group_index],
                )
                group_losses.append(loss)
                group_gradients.append(grad)
            loss_array = np.asarray(group_losses, float)
            target_loss = float(np.dot(target_weights, loss_array))
            target_grad = np.sum(
                np.asarray([weight * grad for weight, grad in zip(target_weights, group_gradients, strict=True)]),
                axis=0,
            )
            target_component += target_loss / n_scenarios
            gradient += target_grad / n_scenarios

            if n_targets > 1 and fairness_penalty > 0:
                beta = float(fairness_temperature)
                maximum = float(np.max(loss_array))
                exp_terms = np.exp(beta * (loss_array - maximum))
                softmax = exp_terms / np.sum(exp_terms)
                smooth_max = maximum + np.log(np.sum(exp_terms)) / beta - np.log(n_targets) / beta
                fairness_component += float(fairness_penalty) * smooth_max / n_scenarios
                fairness_grad = np.sum(
                    np.asarray([weight * grad for weight, grad in zip(softmax, group_gradients, strict=True)]),
                    axis=0,
                )
                gradient += float(fairness_penalty) * fairness_grad / n_scenarios

            outside_loss, outside_grad = _hinge_loss_gradient(
                outside_scenarios[scenario_index],
                weights,
                limit=float(outside_hinge_amplitude),
                reference_scale=float(reference_amplitude),
                tail_penalty=float(tail_penalty),
                tail_fraction=float(tail_fraction),
            )
            outside_component += float(outside_penalty) * outside_loss / n_scenarios
            gradient += float(outside_penalty) * outside_grad / n_scenarios

            if n_protected:
                for zone_index in range(n_protected):
                    zone_loss, zone_grad = _hinge_loss_gradient(
                        protected_scenarios[scenario_index][zone_index],
                        weights,
                        limit=float(protected_limits_array[zone_index]),
                        reference_scale=float(reference_amplitude),
                        tail_penalty=float(tail_penalty),
                        tail_fraction=float(tail_fraction),
                    )
                    coefficient = float(protected_penalty) * float(protected_weights[zone_index])
                    protected_component += coefficient * zone_loss / n_scenarios
                    gradient += coefficient * zone_grad / n_scenarios

        power_component = float(power_regularization) * float(np.mean(np.abs(weights) ** 2))
        gradient += float(power_regularization) * weights / weights.size
        total = target_component + fairness_component + outside_component + protected_component + power_component

        norm = float(np.linalg.norm(gradient))
        if gradient_clip > 0 and norm > float(gradient_clip):
            gradient *= float(gradient_clip) / norm
        first = 0.9 * first + 0.1 * gradient
        second = 0.999 * second + 0.001 * np.abs(gradient) ** 2
        corrected_first = first / (1.0 - 0.9**iteration)
        corrected_second = second / (1.0 - 0.999**iteration)
        weights = weights - float(learning_rate) * corrected_first / (np.sqrt(corrected_second) + 1e-8)
        weights = project_excitation(weights, rms_limit=rms_limit, peak_limit=peak_limit)

        history[iteration - 1] = total
        components[iteration - 1] = (
            target_component,
            fairness_component,
            outside_component,
            protected_component,
            power_component,
            total,
        )
        if total < best_objective:
            best_objective = total
            best_weights = weights.copy()

    return MultiObjectiveShapingResult(
        weights=best_weights,
        objective_history=history,
        component_history=components,
        component_labels=labels,
        runtime_ms=1000.0 * (time.perf_counter() - started),
    )

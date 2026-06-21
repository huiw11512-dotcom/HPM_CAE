"""HPM-CAE V1.3 插件式传播后端快速求解桥。

The solver combines wavelength-scaled scalar Green-function propagation with
normalized complex array excitations.  V1.2 adds object-aware target fairness,
protected-zone exposure caps, tail-sensitive penalties, and per-object
constraint diagnostics.  It remains an algorithm CAE, not a full-wave or
absolute-power electromagnetic solver.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import json
import time
from typing import Callable, Sequence

import numpy as np
import pandas as pd
from threadpoolctl import threadpool_limits

from hpm_platform.evaluation.field_metrics import FieldControlMetrics
from hpm_platform.field_control.multiobjective import projected_adam_multi_object
from hpm_platform.field_control.region_shaping import (
    project_excitation,
    rotated_ellipse_masks,
)
from hpm_platform.physics.field_backends import (
    get_field_backend,
    sample_backend_scenarios,
    sample_grouped_backend_scenarios,
)
from hpm_platform.physics.power_amplifier import digital_predistort, memoryless_pa
from hpm_platform.ui.project_model import CAEProject

LogCallback = Callable[[str], None] | None


@dataclass(frozen=True)
class CAESolveResult:
    project: CAEProject
    x_lambda: np.ndarray
    y_lambda: np.ndarray
    field: np.ndarray
    target_mask: np.ndarray
    guard_mask: np.ndarray
    outside_mask: np.ndarray
    protected_mask: np.ndarray
    target_component_masks: tuple[np.ndarray, ...]
    protected_component_masks: tuple[np.ndarray, ...]
    desired_map: np.ndarray
    desired_weights: np.ndarray
    drive_weights: np.ndarray
    actual_weights: np.ndarray
    u: np.ndarray
    v: np.ndarray
    far_field: np.ndarray
    objective_history: np.ndarray
    objective_component_history: np.ndarray
    objective_component_labels: tuple[str, ...]
    object_metrics: pd.DataFrame
    metrics: dict[str, float | int | bool | str]
    log_lines: tuple[str, ...]

    @property
    def amplitude(self) -> np.ndarray:
        return np.abs(self.field)

    @property
    def field_db(self) -> np.ndarray:
        reference = max(float(self.project.solver.target_amplitude), 1e-12)
        return 20.0 * np.log10(np.maximum(self.amplitude / reference, 1e-6))

    def object_metrics_frame(self) -> pd.DataFrame:
        return self.object_metrics.copy()

    def metrics_frame(self) -> pd.DataFrame:
        labels = {
            "propagation_backend_name": "传播后端",
            "target_rmse_percent": "目标区总体 RMSE",
            "worst_target_rmse_percent": "最差目标 RMSE",
            "target_coverage_percent": "目标区容差覆盖率",
            "minimum_target_coverage_percent": "最低目标覆盖率",
            "target_fairness_gap_percent": "目标间 RMSE 差",
            "target_cv_percent": "目标区变异系数",
            "peak_outside_db": "区外峰值 / 目标参考",
            "outside_peak_limit_db": "区外峰值上限",
            "outside_peak_violation_db": "区外峰值超限",
            "p95_outside_db": "区外 P95 / 目标参考",
            "protected_p95_db": "保护区总体 P95 / 目标参考",
            "maximum_protected_violation_db": "最坏保护区超限",
            "sampled_plane_efficiency_percent": "采样平面能量占比",
            "constraint_success_rate_percent": "对象约束通过率",
            "control_success": "联合控制判据",
            "solver_runtime_ms": "求解耗时",
            "n_elements": "阵元数",
            "wavelength_mm": "波长",
        }
        units = {
            "propagation_backend_name": "",
            "target_rmse_percent": "%",
            "worst_target_rmse_percent": "%",
            "target_coverage_percent": "%",
            "minimum_target_coverage_percent": "%",
            "target_fairness_gap_percent": "百分点",
            "target_cv_percent": "%",
            "peak_outside_db": "dB",
            "outside_peak_limit_db": "dB",
            "outside_peak_violation_db": "dB",
            "p95_outside_db": "dB",
            "protected_p95_db": "dB",
            "maximum_protected_violation_db": "dB",
            "sampled_plane_efficiency_percent": "%",
            "constraint_success_rate_percent": "%",
            "control_success": "",
            "solver_runtime_ms": "ms",
            "n_elements": "",
            "wavelength_mm": "mm",
        }
        rows = []
        for key, label in labels.items():
            value = self.metrics.get(key, "—")
            if isinstance(value, float):
                shown: object = round(value, 4) if np.isfinite(value) else "—"
            else:
                shown = value
            rows.append({"指标": label, "数值": shown, "单位": units[key]})
        return pd.DataFrame(rows)


def _log(lines: list[str], callback: LogCallback, message: str) -> None:
    lines.append(message)
    if callback is not None:
        callback(message)


def _select_points(mask: np.ndarray, points: np.ndarray, count: int, rng: np.random.Generator) -> np.ndarray:
    candidates = np.flatnonzero(np.asarray(mask, dtype=bool).ravel())
    if candidates.size == 0:
        raise ValueError("requested region has no grid samples")
    if candidates.size <= int(count):
        selected = candidates
    else:
        selected = np.sort(rng.choice(candidates, size=int(count), replace=False))
    return points[selected]


def _select_group_indices(
    masks: Sequence[np.ndarray],
    total_count: int,
    rng: np.random.Generator,
    *,
    priorities: Sequence[float] | None = None,
    minimum_per_group: int = 12,
) -> tuple[np.ndarray, ...]:
    """Allocate samples across objects so small regions cannot disappear."""
    if not masks:
        return ()
    candidates = [np.flatnonzero(np.asarray(mask, bool).ravel()) for mask in masks]
    if any(item.size == 0 for item in candidates):
        raise ValueError("every enabled object must contain at least one grid sample")
    count = max(int(total_count), len(masks))
    priority = np.ones(len(masks), dtype=float) if priorities is None else np.asarray(priorities, float)
    area_weight = np.sqrt(np.asarray([item.size for item in candidates], float))
    allocation_weight = area_weight * np.sqrt(priority / max(float(np.mean(priority)), 1e-12))
    raw = count * allocation_weight / np.sum(allocation_weight)
    allocations = np.maximum(np.floor(raw).astype(int), int(minimum_per_group))
    allocations = np.minimum(allocations, np.asarray([item.size for item in candidates], int))
    while allocations.sum() > count and np.any(allocations > minimum_per_group):
        index = int(np.argmax(allocations - raw))
        allocations[index] -= 1
    while allocations.sum() < count:
        capacity = np.asarray([item.size for item in candidates], int) - allocations
        if np.max(capacity) <= 0:
            break
        score = raw - allocations
        score[capacity <= 0] = -np.inf
        allocations[int(np.argmax(score))] += 1
    output = []
    for pool, take in zip(candidates, allocations, strict=True):
        selected = pool if take >= pool.size else np.sort(rng.choice(pool, size=int(take), replace=False))
        output.append(np.asarray(selected, int))
    return tuple(output)


def _make_masks(project: CAEProject, xx_lambda: np.ndarray, yy_lambda: np.ndarray):
    """Build union masks, per-object masks, and the target setpoint map."""
    shape = np.broadcast(xx_lambda, yy_lambda).shape
    target = np.zeros(shape, dtype=bool)
    guard = np.zeros(shape, dtype=bool)
    desired = np.zeros(shape, dtype=float)
    target_components: list[np.ndarray] = []
    for item in project.targets:
        region = rotated_ellipse_masks(
            xx_lambda,
            yy_lambda,
            center_m=(item.center_x_lambda, item.center_y_lambda),
            semi_axes_m=(item.semi_major_lambda, item.semi_minor_lambda),
            rotation_deg=item.rotation_deg,
            guard_scale=item.guard_scale,
        )
        component = np.asarray(region.target, dtype=bool)
        target |= component
        guard |= region.guard
        desired[component] = np.maximum(
            desired[component],
            float(project.solver.target_amplitude) * float(item.amplitude_scale),
        )
        target_components.append(component)

    protected = np.zeros(shape, dtype=bool)
    protected_components: list[np.ndarray] = []
    for zone in project.protected_zones:
        dx = xx_lambda - zone.center_x_lambda
        dy = yy_lambda - zone.center_y_lambda
        component = (dx**2 + dy**2 <= zone.radius_lambda**2) & ~target
        protected |= component
        protected_components.append(component)

    guard &= ~(target | protected)
    outside = ~(target | guard | protected)
    return (
        target,
        guard,
        outside,
        protected,
        desired,
        tuple(target_components),
        tuple(protected_components),
    )


def _scale_to_vector_target(
    weights: np.ndarray,
    matrix: np.ndarray,
    desired_amplitudes: np.ndarray,
    *,
    rms_limit: float,
    peak_limit: float,
) -> np.ndarray:
    w = np.asarray(weights, complex).reshape(-1)
    observed = np.abs(np.asarray(matrix, complex) @ w)
    desired = np.asarray(desired_amplitudes, float).reshape(-1)
    denominator = float(np.dot(observed, observed))
    if denominator <= np.finfo(float).tiny:
        return project_excitation(w, rms_limit=rms_limit, peak_limit=peak_limit)
    scalar = max(float(np.dot(observed, desired)) / denominator, 0.0)
    return project_excitation(scalar * w, rms_limit=rms_limit, peak_limit=peak_limit)


def _weighted_region_ls(
    target_matrices: Sequence[np.ndarray],
    desired_groups: Sequence[np.ndarray],
    target_priorities: Sequence[float],
    outside_matrix: np.ndarray,
    protected_matrices: Sequence[np.ndarray],
    protected_priorities: Sequence[float],
    template: np.ndarray,
    *,
    outside_penalty: float,
    protected_penalty: float,
    ridge: float,
    rms_limit: float,
    peak_limit: float,
) -> np.ndarray:
    """Object-balanced complex LS initializer with explicit protected samples."""
    matrices: list[np.ndarray] = []
    vectors: list[np.ndarray] = []
    for matrix, desired, priority in zip(target_matrices, desired_groups, target_priorities, strict=True):
        a = np.asarray(matrix, complex)
        phase = np.angle(a @ np.asarray(template, complex).reshape(-1))
        scale = np.sqrt(float(priority) / max(a.shape[0], 1))
        matrices.append(scale * a)
        vectors.append(scale * np.asarray(desired, float) * np.exp(1j * phase))
    outside = np.asarray(outside_matrix, complex)
    if outside.size and outside_penalty > 0:
        scale = np.sqrt(float(outside_penalty) / max(outside.shape[0], 1))
        matrices.append(scale * outside)
        vectors.append(np.zeros(outside.shape[0], dtype=complex))
    if protected_matrices and protected_penalty > 0:
        total_priority = max(float(np.sum(protected_priorities)), 1e-12)
        for matrix, priority in zip(protected_matrices, protected_priorities, strict=True):
            a = np.asarray(matrix, complex)
            scale = np.sqrt(float(protected_penalty) * float(priority) / total_priority / max(a.shape[0], 1))
            matrices.append(scale * a)
            vectors.append(np.zeros(a.shape[0], dtype=complex))
    design = np.vstack(matrices)
    response = np.concatenate(vectors)
    hessian = design.conj().T @ design + float(ridge) * np.eye(design.shape[1])
    weights = np.linalg.solve(hessian, design.conj().T @ response)
    weights = project_excitation(weights, rms_limit=rms_limit, peak_limit=peak_limit)
    combined_target = np.vstack(tuple(np.asarray(item, complex) for item in target_matrices))
    combined_desired = np.concatenate(tuple(np.asarray(item, float) for item in desired_groups))
    return _scale_to_vector_target(
        weights,
        combined_target,
        combined_desired,
        rms_limit=rms_limit,
        peak_limit=peak_limit,
    )


def _projected_adam_variable(
    initial: np.ndarray,
    target_matrices: tuple[np.ndarray, ...],
    outside_matrices: tuple[np.ndarray, ...],
    desired_amplitudes: np.ndarray,
    *,
    outside_hinge_amplitude: float,
    outside_penalty: float,
    rms_limit: float,
    peak_limit: float,
    iterations: int,
    learning_rate: float,
) -> tuple[np.ndarray, np.ndarray]:
    """Legacy union-region projected Adam retained as a paper baseline."""
    weights = project_excitation(initial, rms_limit=rms_limit, peak_limit=peak_limit)
    first = np.zeros_like(weights)
    second = np.zeros(weights.shape, dtype=float)
    history = np.empty(int(iterations), dtype=float)
    best = weights.copy()
    best_objective = np.inf
    desired = np.asarray(desired_amplitudes, float).reshape(-1)
    scale_sq = max(float(np.mean(desired**2)), 1e-12)
    n_scenarios = len(target_matrices)
    for iteration in range(1, int(iterations) + 1):
        gradient = np.zeros_like(weights)
        objective = 0.0
        for target_matrix, outside_matrix in zip(target_matrices, outside_matrices, strict=True):
            target_field = target_matrix @ weights
            target_amp = np.abs(target_field)
            error = target_amp - desired
            direction = target_field / np.maximum(target_amp, 1e-12)
            objective += float(np.mean(error**2) / scale_sq) / n_scenarios
            gradient += target_matrix.conj().T @ ((error / scale_sq) * direction) / (target_matrix.shape[0] * n_scenarios)
            outside_field = outside_matrix @ weights
            outside_amp = np.abs(outside_field)
            excess = np.maximum(outside_amp - float(outside_hinge_amplitude), 0.0)
            outside_direction = outside_field / np.maximum(outside_amp, 1e-12)
            objective += float(outside_penalty) * float(np.mean(excess**2) / scale_sq) / n_scenarios
            gradient += float(outside_penalty) * outside_matrix.conj().T @ ((excess / scale_sq) * outside_direction) / (outside_matrix.shape[0] * n_scenarios)
        objective += 5e-4 * float(np.mean(np.abs(weights) ** 2))
        gradient += 5e-4 * weights / weights.size
        first = 0.9 * first + 0.1 * gradient
        second = 0.999 * second + 0.001 * np.abs(gradient) ** 2
        corrected_first = first / (1.0 - 0.9**iteration)
        corrected_second = second / (1.0 - 0.999**iteration)
        weights = weights - float(learning_rate) * corrected_first / (np.sqrt(corrected_second) + 1e-8)
        weights = project_excitation(weights, rms_limit=rms_limit, peak_limit=peak_limit)
        history[iteration - 1] = objective
        if objective < best_objective:
            best_objective = objective
            best = weights.copy()
    return best, history


def _evaluate_variable_field(
    field: np.ndarray,
    target_mask: np.ndarray,
    outside_mask: np.ndarray,
    desired_map: np.ndarray,
    *,
    reference_amplitude: float,
    outside_peak_limit_db: float,
) -> FieldControlMetrics:
    values = np.abs(np.asarray(field, complex))
    desired = np.asarray(desired_map, float)[target_mask]
    target_values = values[target_mask]
    outside_values = values[outside_mask]
    normalized = target_values / np.maximum(desired, 1e-12)
    rmse = float(np.sqrt(np.mean((normalized - 1.0) ** 2)))
    coverage = float(np.mean(np.abs(normalized - 1.0) <= 0.10))
    cv = float(np.std(normalized) / max(float(np.mean(normalized)), 1e-12))
    peak_db = float(20.0 * np.log10(max(float(np.max(outside_values)) / reference_amplitude, 1e-12)))
    p95_db = float(20.0 * np.log10(max(float(np.quantile(outside_values, 0.95)) / reference_amplitude, 1e-12)))
    total_energy = float(np.sum(values**2))
    efficiency = float(np.sum(target_values**2) / max(total_energy, np.finfo(float).tiny))
    return FieldControlMetrics(
        target_mean=float(np.mean(target_values)),
        target_rmse_fraction=rmse,
        target_cv_fraction=cv,
        target_coverage=coverage,
        peak_outside_db=peak_db,
        p95_outside_db=p95_db,
        outside_area_above_minus6db=float(np.mean(outside_values > 10.0 ** (-6.0 / 20.0) * reference_amplitude)),
        outside_area_above_minus10db=float(np.mean(outside_values > 10.0 ** (-10.0 / 20.0) * reference_amplitude)),
        sampled_plane_efficiency=efficiency,
        control_success=bool(rmse <= 0.12 and coverage >= 0.60 and peak_db <= float(outside_peak_limit_db)),
    )


def _object_metrics(
    project: CAEProject,
    field: np.ndarray,
    target_components: Sequence[np.ndarray],
    protected_components: Sequence[np.ndarray],
) -> pd.DataFrame:
    amplitude = np.abs(np.asarray(field, complex))
    reference = float(project.solver.target_amplitude)
    rows: list[dict[str, object]] = []
    for item, mask in zip(project.targets, target_components, strict=True):
        values = amplitude[np.asarray(mask, bool)]
        desired = reference * float(item.amplitude_scale)
        normalized = values / max(desired, 1e-12)
        rmse = 100.0 * float(np.sqrt(np.mean((normalized - 1.0) ** 2)))
        coverage = 100.0 * float(np.mean(np.abs(normalized - 1.0) <= float(item.tolerance_percent) / 100.0))
        p95_deviation = 100.0 * float(np.quantile(np.abs(normalized - 1.0), 0.95))
        success = bool(rmse <= 1.25 * float(item.tolerance_percent) and coverage >= 55.0)
        rows.append(
            {
                "object_type": "target",
                "object_id": item.object_id,
                "name": item.name,
                "priority": float(item.priority),
                "setpoint_or_cap": desired,
                "mean_amplitude": float(np.mean(values)),
                "rmse_percent": rmse,
                "coverage_percent": coverage,
                "p95_deviation_percent": p95_deviation,
                "p95_db": float(20.0 * np.log10(max(float(np.quantile(values, 0.95)) / reference, 1e-12))),
                "peak_db": float(20.0 * np.log10(max(float(np.max(values)) / reference, 1e-12))),
                "limit_db": float("nan"),
                "violation_db": float("nan"),
                "success": success,
            }
        )
    for item, mask in zip(project.protected_zones, protected_components, strict=True):
        values = amplitude[np.asarray(mask, bool)]
        if values.size == 0:
            continue
        cap = reference * float(item.max_amplitude_scale)
        p95_db = float(20.0 * np.log10(max(float(np.quantile(values, 0.95)) / reference, 1e-12)))
        peak_db = float(20.0 * np.log10(max(float(np.max(values)) / reference, 1e-12)))
        limit_db = float(20.0 * np.log10(float(item.max_amplitude_scale)))
        violation = p95_db - limit_db
        rows.append(
            {
                "object_type": "protected",
                "object_id": item.object_id,
                "name": item.name,
                "priority": float(item.priority),
                "setpoint_or_cap": cap,
                "mean_amplitude": float(np.mean(values)),
                "rmse_percent": float("nan"),
                "coverage_percent": 100.0 * float(np.mean(values <= cap)),
                "p95_deviation_percent": float("nan"),
                "p95_db": p95_db,
                "peak_db": peak_db,
                "limit_db": limit_db,
                "violation_db": violation,
                "success": bool(violation <= 0.75),
            }
        )
    return pd.DataFrame(rows)


def _apply_pa(project: CAEProject, desired: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    spec = project.solver
    if not spec.pa_enabled:
        return desired.copy(), desired.copy()
    if spec.dpd_enabled:
        drive = digital_predistort(
            desired,
            saturation_amplitude=spec.pa_saturation_amplitude,
            smoothness=spec.pa_smoothness,
            maximum_phase_deg=spec.pa_maximum_phase_deg,
            drive_limit=spec.peak_limit,
        )
    else:
        drive = desired.copy()
    actual = memoryless_pa(
        drive,
        saturation_amplitude=spec.pa_saturation_amplitude,
        smoothness=spec.pa_smoothness,
        maximum_phase_deg=spec.pa_maximum_phase_deg,
    )
    return drive, actual


def _solve_project_impl(project: CAEProject, log_callback: LogCallback = None) -> CAESolveResult:
    project.validate_geometry()
    started = time.perf_counter()
    log_lines: list[str] = []
    _log(log_lines, log_callback, f"[1/8] 项目校验完成：{project.meta.name}")

    array = project.array.build_array()
    backend = get_field_backend(project.propagation.backend)
    backend_summary = backend.summary(project)
    wavelength = array.wavelength_m
    n = int(project.plane.samples)
    x_lambda = np.linspace(-project.plane.span_x_lambda / 2, project.plane.span_x_lambda / 2, n)
    y_lambda = np.linspace(-project.plane.span_y_lambda / 2, project.plane.span_y_lambda / 2, n)
    xx_lambda, yy_lambda = np.meshgrid(x_lambda, y_lambda, indexing="xy")
    points_m = np.column_stack(
        (
            xx_lambda.ravel() * wavelength,
            yy_lambda.ravel() * wavelength,
            np.full(xx_lambda.size, project.plane.z_lambda * wavelength),
        )
    )
    (
        target_mask,
        guard_mask,
        outside_mask,
        protected_mask,
        desired_map,
        target_components,
        protected_components,
    ) = _make_masks(project, xx_lambda, yy_lambda)
    _log(
        log_lines,
        log_callback,
        f"[2/8] 建立 {array.nx}×{array.ny} 阵列与 {n}×{n} 观察面；传播后端={backend.display_name}；λ={1e3*wavelength:.3f} mm",
    )

    rng = np.random.default_rng(int(project.meta.seed))
    target_indices = _select_group_indices(
        target_components,
        project.solver.target_samples,
        rng,
        priorities=[item.priority for item in project.targets],
    )
    target_points_groups = tuple(points_m[index] for index in target_indices)
    desired_groups = tuple(desired_map.ravel()[index] for index in target_indices)

    protected_budget = min(max(project.solver.outside_samples // 3, 24 * len(protected_components)), int(np.sum(protected_mask))) if protected_components else 0
    protected_indices = _select_group_indices(
        protected_components,
        protected_budget,
        rng,
        priorities=[item.priority for item in project.protected_zones],
        minimum_per_group=8,
    ) if protected_components else ()
    protected_points_groups = tuple(points_m[index] for index in protected_indices)
    general_count = max(int(project.solver.outside_samples) - int(sum(len(index) for index in protected_indices)), 32)
    outside_points = _select_points(outside_mask, points_m, general_count, rng)

    primary_focus_m = wavelength * np.array(
        [project.target.center_x_lambda, project.target.center_y_lambda, project.plane.z_lambda],
        dtype=float,
    )
    reference_scale = backend.reference_scale(array, primary_focus_m, project=project)
    templates = []
    for item in project.targets:
        item_focus = wavelength * np.array([item.center_x_lambda, item.center_y_lambda, project.plane.z_lambda], dtype=float)
        templates.append(
            float(item.amplitude_scale)
            * np.sqrt(float(item.priority))
            * backend.focus_weights(array, item_focus, project=project, rms_amplitude=1.0)
        )
    template = project_excitation(np.sum(templates, axis=0), rms_limit=project.solver.rms_limit, peak_limit=project.solver.peak_limit)

    nominal_target_groups = tuple(
        backend.matrix(array, points, project=project, reference_scale=reference_scale)
        for points in target_points_groups
    )
    nominal_outside = backend.matrix(
        array, outside_points, project=project, reference_scale=reference_scale
    )
    nominal_protected_groups = tuple(
        backend.matrix(array, points, project=project, reference_scale=reference_scale)
        for points in protected_points_groups
    )
    target_matrix = np.vstack(nominal_target_groups)
    target_setpoints = np.concatenate(desired_groups)
    combined_outside_points = np.vstack((outside_points, *protected_points_groups)) if protected_points_groups else outside_points
    combined_outside_matrix = backend.matrix(
        array, combined_outside_points, project=project, reference_scale=reference_scale
    )
    _log(
        log_lines,
        log_callback,
        f"[3/8] 分层抽样：{len(project.targets)}个目标/{target_matrix.shape[0]}点 · 区外{outside_points.shape[0]}点 · {len(project.protected_zones)}个保护区/{sum(len(x) for x in protected_indices)}点",
    )

    initial = _weighted_region_ls(
        nominal_target_groups,
        desired_groups,
        [item.priority for item in project.targets],
        nominal_outside,
        nominal_protected_groups,
        [item.priority for item in project.protected_zones],
        template,
        outside_penalty=project.solver.outside_penalty,
        protected_penalty=project.solver.protected_penalty,
        ridge=project.solver.ridge,
        rms_limit=project.solver.rms_limit,
        peak_limit=project.solver.peak_limit,
    )

    method = project.solver.method
    objective_history = np.empty(0, dtype=float)
    objective_component_history = np.empty((0, 0), dtype=float)
    objective_component_labels: tuple[str, ...] = ()
    if method == "Point-Focus":
        desired_weights = template
        _log(log_lines, log_callback, "[4/8] 求解器：多焦点相位共轭基线")
    elif method == "Region-LS":
        desired_weights = initial
        _log(log_lines, log_callback, "[4/8] 求解器：对象平衡闭式区域最小二乘")
    elif method in {"Nominal-PGMS", "Robust-PGMS"}:
        if method == "Nominal-PGMS":
            target_scenarios = (target_matrix,)
            outside_scenarios = (combined_outside_matrix,)
            _log(log_lines, log_callback, "[4/8] 求解器：名义联合区域 PGMS 基线")
        else:
            scenario_set = sample_backend_scenarios(
                backend,
                array,
                np.vstack(target_points_groups),
                combined_outside_points,
                project=project,
                reference_scale=reference_scale,
                n_scenarios=project.solver.uncertainty_scenarios,
                gain_std_fraction=project.solver.gain_std_percent / 100.0,
                phase_std_deg=project.solver.phase_std_deg,
                registration_jitter_std_lambda=project.solver.registration_jitter_lambda,
                seed=project.meta.seed + 17,
                include_nominal=True,
            )
            target_scenarios = scenario_set.target_matrices
            outside_scenarios = scenario_set.outside_matrices
            _log(log_lines, log_callback, f"[4/8] 求解器：{len(target_scenarios)}场景鲁棒联合区域 PGMS 基线")
        desired_weights, objective_history = _projected_adam_variable(
            initial,
            tuple(target_scenarios),
            tuple(outside_scenarios),
            target_setpoints,
            outside_hinge_amplitude=project.solver.outside_hinge_amplitude,
            outside_penalty=project.solver.outside_penalty,
            rms_limit=project.solver.rms_limit,
            peak_limit=project.solver.peak_limit,
            iterations=project.solver.iterations,
            learning_rate=project.solver.learning_rate,
        )
    else:
        grouped = sample_grouped_backend_scenarios(
            backend,
            array,
            target_points_groups,
            outside_points,
            protected_points_groups,
            project=project,
            reference_scale=reference_scale,
            n_scenarios=project.solver.uncertainty_scenarios,
            gain_std_fraction=project.solver.gain_std_percent / 100.0,
            phase_std_deg=project.solver.phase_std_deg,
            registration_jitter_std_lambda=project.solver.registration_jitter_lambda,
            seed=project.meta.seed + 23,
            include_nominal=True,
        )
        shaped = projected_adam_multi_object(
            initial,
            grouped.target_matrices,
            desired_groups,
            [item.priority for item in project.targets],
            grouped.outside_matrices,
            grouped.protected_matrices,
            [project.solver.target_amplitude * item.max_amplitude_scale for item in project.protected_zones],
            [item.priority for item in project.protected_zones],
            outside_hinge_amplitude=project.solver.outside_hinge_amplitude,
            outside_penalty=project.solver.outside_penalty,
            protected_penalty=project.solver.protected_penalty,
            fairness_penalty=project.solver.fairness_penalty,
            tail_penalty=project.solver.tail_penalty,
            tail_fraction=project.solver.tail_fraction,
            reference_amplitude=project.solver.target_amplitude,
            rms_limit=project.solver.rms_limit,
            peak_limit=project.solver.peak_limit,
            iterations=project.solver.iterations,
            learning_rate=project.solver.learning_rate,
        )
        desired_weights = shaped.weights
        objective_history = shaped.objective_history
        objective_component_history = shaped.component_history
        objective_component_labels = shaped.component_labels
        _log(
            log_lines,
            log_callback,
            f"[4/8] 求解器：Constrained-MO-PGMS · {len(grouped.target_matrices)}场景 · 公平项/保护区尾部约束",
        )

    drive, actual = _apply_pa(project, desired_weights)
    pa_text = "关闭" if not project.solver.pa_enabled else ("启用+DPD" if project.solver.dpd_enabled else "启用，无DPD")
    _log(log_lines, log_callback, f"[5/8] 归一化功放链：{pa_text}")

    full_matrix = backend.matrix(
        array, points_m, project=project, reference_scale=reference_scale
    )
    field = (full_matrix @ actual).reshape(xx_lambda.shape)
    field_metrics = _evaluate_variable_field(
        field,
        target_mask,
        outside_mask,
        desired_map,
        reference_amplitude=project.solver.target_amplitude,
        outside_peak_limit_db=project.solver.outside_peak_limit_db,
    )
    object_metrics = _object_metrics(project, field, target_components, protected_components)
    _log(log_lines, log_callback, "[6/8] 完成复场与对象级约束诊断")

    target_rows = object_metrics[object_metrics["object_type"] == "target"]
    protected_rows = object_metrics[object_metrics["object_type"] == "protected"]
    worst_target_rmse = float(target_rows["rmse_percent"].max())
    minimum_target_coverage = float(target_rows["coverage_percent"].min())
    fairness_gap = float(target_rows["rmse_percent"].max() - target_rows["rmse_percent"].min())
    if protected_rows.empty:
        protected_p95_db = float("nan")
        maximum_protected_violation = float("nan")
    else:
        protected_values = np.abs(field[protected_mask])
        protected_p95_db = float(20.0 * np.log10(max(float(np.quantile(protected_values, 0.95)) / project.solver.target_amplitude, 1e-12)))
        maximum_protected_violation = float(protected_rows["violation_db"].max())
    constraint_success_rate = 100.0 * float(object_metrics["success"].mean()) if not object_metrics.empty else 0.0
    target_ok = bool(target_rows["success"].all())
    protected_ok = bool(protected_rows["success"].all()) if not protected_rows.empty else True
    control_success = bool(target_ok and protected_ok and field_metrics.peak_outside_db <= project.solver.outside_peak_limit_db)

    u = np.linspace(-1.0, 1.0, 91)
    v = np.linspace(-1.0, 1.0, 91)
    uu, vv = np.meshgrid(u, v, indexing="xy")
    far_field = array.transmit_response_uv(actual, uu, vv)
    _log(log_lines, log_callback, "[7/8] 完成方向图与归一化工程判据")

    runtime_ms = 1000.0 * (time.perf_counter() - started)
    metrics: dict[str, float | int | bool | str] = {
        "project_name": project.meta.name,
        "method": method,
        "propagation_backend": backend.backend_id,
        "propagation_backend_name": backend.display_name,
        "active_reflectors": int(backend_summary.active_reflectors),
        "active_apertures": int(backend_summary.active_apertures),
        "active_cavities": int(backend_summary.active_cavities),
        "n_elements": int(array.n_elements),
        "target_count": int(len(project.targets)),
        "protected_zone_count": int(len(project.protected_zones)),
        "wavelength_mm": float(1e3 * wavelength),
        "target_rmse_percent": float(100.0 * field_metrics.target_rmse_fraction),
        "worst_target_rmse_percent": worst_target_rmse,
        "target_coverage_percent": float(100.0 * field_metrics.target_coverage),
        "minimum_target_coverage_percent": minimum_target_coverage,
        "target_fairness_gap_percent": fairness_gap,
        "target_cv_percent": float(100.0 * field_metrics.target_cv_fraction),
        "peak_outside_db": float(field_metrics.peak_outside_db),
        "outside_peak_limit_db": float(project.solver.outside_peak_limit_db),
        "outside_peak_violation_db": float(field_metrics.peak_outside_db - project.solver.outside_peak_limit_db),
        "p95_outside_db": float(field_metrics.p95_outside_db),
        "protected_p95_db": protected_p95_db,
        "maximum_protected_violation_db": maximum_protected_violation,
        "sampled_plane_efficiency_percent": float(100.0 * field_metrics.sampled_plane_efficiency),
        "constraint_success_rate_percent": constraint_success_rate,
        "control_success": control_success,
        "solver_runtime_ms": float(runtime_ms),
        "pa_enabled": bool(project.solver.pa_enabled),
        "dpd_enabled": bool(project.solver.dpd_enabled),
        "model_scope": project.model_scope,
    }
    _log(
        log_lines,
        log_callback,
        f"[8/8] 完成：后端={backend.display_name} · 总体RMSE={metrics['target_rmse_percent']:.2f}% · 最差目标={worst_target_rmse:.2f}% · 保护区最坏超限={maximum_protected_violation:.2f} dB · {runtime_ms:.1f} ms",
    )

    return CAESolveResult(
        project=project,
        x_lambda=x_lambda,
        y_lambda=y_lambda,
        field=field,
        target_mask=target_mask,
        guard_mask=guard_mask,
        outside_mask=outside_mask,
        protected_mask=protected_mask,
        target_component_masks=tuple(target_components),
        protected_component_masks=tuple(protected_components),
        desired_map=desired_map,
        desired_weights=desired_weights,
        drive_weights=drive,
        actual_weights=actual,
        u=u,
        v=v,
        far_field=far_field,
        objective_history=objective_history,
        objective_component_history=objective_component_history,
        objective_component_labels=objective_component_labels,
        object_metrics=object_metrics,
        metrics=metrics,
        log_lines=tuple(log_lines),
    )


def solve_project(project: CAEProject, log_callback: LogCallback = None) -> CAESolveResult:
    """Solve one project with a single BLAS thread for responsive UI work."""
    with threadpool_limits(limits=1):
        return _solve_project_impl(project, log_callback=log_callback)


def save_numeric_result(result: CAESolveResult, output_dir: str | Path) -> Path:
    """Persist project, metrics, object constraints, weights, and field arrays."""
    destination = Path(output_dir)
    destination.mkdir(parents=True, exist_ok=True)
    result.project.save_yaml(destination / "project.yaml")
    (destination / "metrics.json").write_text(json.dumps(result.metrics, indent=2, ensure_ascii=False), encoding="utf-8")
    result.metrics_frame().to_csv(destination / "metrics.csv", index=False, encoding="utf-8-sig")
    result.object_metrics_frame().to_csv(destination / "object_metrics.csv", index=False, encoding="utf-8-sig")
    weights = pd.DataFrame(
        {
            "element": np.arange(result.actual_weights.size),
            "desired_amplitude": np.abs(result.desired_weights),
            "desired_phase_deg": np.rad2deg(np.angle(result.desired_weights)),
            "drive_amplitude": np.abs(result.drive_weights),
            "drive_phase_deg": np.rad2deg(np.angle(result.drive_weights)),
            "actual_amplitude": np.abs(result.actual_weights),
            "actual_phase_deg": np.rad2deg(np.angle(result.actual_weights)),
        }
    )
    weights.to_csv(destination / "element_weights.csv", index=False, encoding="utf-8-sig")
    np.savez_compressed(
        destination / "field_solution.npz",
        x_lambda=result.x_lambda,
        y_lambda=result.y_lambda,
        field=result.field,
        target_mask=result.target_mask,
        guard_mask=result.guard_mask,
        outside_mask=result.outside_mask,
        protected_mask=result.protected_mask,
        target_component_masks=np.asarray(result.target_component_masks, dtype=bool),
        protected_component_masks=np.asarray(result.protected_component_masks, dtype=bool),
        desired_map=result.desired_map,
        desired_weights=result.desired_weights,
        drive_weights=result.drive_weights,
        actual_weights=result.actual_weights,
        u=result.u,
        v=result.v,
        far_field=result.far_field,
        objective_history=result.objective_history,
        objective_component_history=result.objective_component_history,
        objective_component_labels=np.asarray(result.objective_component_labels, dtype=str),
    )
    (destination / "solver.log").write_text("\n".join(result.log_lines) + "\n", encoding="utf-8")
    return destination

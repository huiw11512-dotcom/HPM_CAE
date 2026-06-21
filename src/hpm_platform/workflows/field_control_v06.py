"""V0.6 normalized near-field region-control workflow.

This workflow studies spatial magnitude shaping on a normalized observation
plane.  It includes scenario-based gain/phase/registration uncertainty and a
memoryless Rapp PA with bounded digital predistortion.  It deliberately omits
absolute source power, range budgets, device susceptibility, and damage
inference.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence
import argparse
import base64
import csv
import hashlib
import json
import math
import platform
import shutil
import sys
import time

import matplotlib
import numpy as np
import scipy
from scipy.stats import wilcoxon
from threadpoolctl import threadpool_limits
import yaml

from hpm_platform.evaluation.doa_statistics import mean_confidence_interval, wilson_interval
from hpm_platform.evaluation.field_metrics import FieldControlMetrics, evaluate_field_control
from hpm_platform.field_control.region_shaping import (
    RegionMasks,
    ShapingResult,
    point_focus_reference_scale,
    projected_adam_magnitude_shaping,
    region_least_squares_weights,
    rotated_ellipse_masks,
    sample_linear_scenarios,
    scalar_green_matrix,
    scale_to_target_amplitude,
    unit_rms_point_focus_weights,
)
from hpm_platform.physics.array_geometry import C0, RectangularArray
from hpm_platform.physics.power_amplifier import digital_predistort, memoryless_pa, rapp_am_am
from hpm_platform.visualization.field_control_v06 import (
    plot_ablation,
    plot_cdf,
    plot_convergence,
    plot_cross_section,
    plot_element_quantity,
    plot_field_map,
    plot_mechanism,
    plot_metric_curve,
    plot_pa_transfer,
    plot_pareto,
    plot_region_geometry,
    plot_runtime,
    plot_target_amplitude_cdf,
)


METHOD_POINT = "Point-Focus"
METHOD_LS = "Region-LS"
METHOD_NOMINAL = "Nominal-PGMS"
METHOD_PROPOSED = "SR-PGMS-DPD"
METHOD_ORDER = [METHOD_POINT, METHOD_LS, METHOD_NOMINAL, METHOD_PROPOSED]
ABLATION_NO_DPD = "SR-PGMS, no DPD"
ABLATION_ORDER = [METHOD_POINT, METHOD_LS, METHOD_NOMINAL, ABLATION_NO_DPD, METHOD_PROPOSED]


@dataclass(frozen=True)
class PlaneGrid:
    x_m: np.ndarray
    y_m: np.ndarray
    xx_m: np.ndarray
    yy_m: np.ndarray
    points_m: np.ndarray
    masks: RegionMasks


@dataclass(frozen=True)
class MethodDesign:
    weights: np.ndarray
    use_predistortion: bool
    runtime_ms: float
    objective_history: np.ndarray


@dataclass(frozen=True)
class TrainingData:
    target_points_m: np.ndarray
    outside_points_m: np.ndarray
    target_matrix: np.ndarray
    outside_matrix: np.ndarray


def _array_from_config(config: dict[str, Any]) -> RectangularArray:
    cfg = config["array"]
    frequency = float(cfg["frequency_hz"])
    spacing = float(cfg["spacing_lambda"]) * C0 / frequency
    return RectangularArray(
        nx=int(cfg["nx"]),
        ny=int(cfg["ny"]),
        frequency_hz=frequency,
        dx_m=spacing,
        dy_m=spacing,
    )


def _plane_grid(array: RectangularArray, config: dict[str, Any], n_points: int) -> PlaneGrid:
    plane = config["control_plane"]
    region = config["region"]
    wavelength = array.wavelength_m
    x = np.linspace(float(plane["x_min_lambda"]), float(plane["x_max_lambda"]), int(n_points)) * wavelength
    y = np.linspace(float(plane["y_min_lambda"]), float(plane["y_max_lambda"]), int(n_points)) * wavelength
    xx, yy = np.meshgrid(x, y, indexing="xy")
    points = np.column_stack(
        (
            xx.ravel(),
            yy.ravel(),
            np.full(xx.size, float(plane["z_lambda"]) * wavelength),
        )
    )
    masks = rotated_ellipse_masks(
        xx,
        yy,
        center_m=(float(region["center_lambda"][0]) * wavelength, float(region["center_lambda"][1]) * wavelength),
        semi_axes_m=(
            float(region["semi_axes_lambda"][0]) * wavelength,
            float(region["semi_axes_lambda"][1]) * wavelength,
        ),
        rotation_deg=float(region["rotation_deg"]),
        guard_scale=float(region["guard_scale"]),
    )
    return PlaneGrid(x_m=x, y_m=y, xx_m=xx, yy_m=yy, points_m=points, masks=masks)


def _focus_point(array: RectangularArray, config: dict[str, Any]) -> np.ndarray:
    region = config["region"]
    plane = config["control_plane"]
    return array.wavelength_m * np.array(
        [
            float(region["center_lambda"][0]),
            float(region["center_lambda"][1]),
            float(plane["z_lambda"]),
        ]
    )


def _training_data(
    array: RectangularArray,
    config: dict[str, Any],
    grid: PlaneGrid,
    reference_scale: float,
) -> TrainingData:
    rng = np.random.default_rng(int(config["training"]["sample_seed"]))
    target_indices = np.flatnonzero(grid.masks.target.ravel())
    outside_indices = np.flatnonzero(grid.masks.outside.ravel())
    n_outside = min(int(config["training"]["outside_samples"]), outside_indices.size)
    selected_outside = rng.choice(outside_indices, size=n_outside, replace=False)
    target_points = grid.points_m[target_indices]
    outside_points = grid.points_m[selected_outside]
    return TrainingData(
        target_points_m=target_points,
        outside_points_m=outside_points,
        target_matrix=scalar_green_matrix(array, target_points, reference_scale=reference_scale),
        outside_matrix=scalar_green_matrix(array, outside_points, reference_scale=reference_scale),
    )


def _design_methods(
    array: RectangularArray,
    config: dict[str, Any],
    training: TrainingData,
    reference_scale: float,
) -> tuple[dict[str, MethodDesign], Any]:
    region = config["region"]
    limits = config["excitation_limits"]
    optimizer = config["optimizer"]
    target_amplitude = float(region["target_amplitude"])
    rms_limit = float(limits["rms_limit"])
    peak_limit = float(limits["peak_limit"])

    start = time.perf_counter()
    point = unit_rms_point_focus_weights(array, _focus_point(array, config), rms_amplitude=1.0)
    point = scale_to_target_amplitude(
        point,
        training.target_matrix,
        target_amplitude=target_amplitude,
        rms_limit=rms_limit,
        peak_limit=peak_limit,
    )
    point_runtime = 1000.0 * (time.perf_counter() - start)

    start = time.perf_counter()
    ls = region_least_squares_weights(
        training.target_matrix,
        training.outside_matrix,
        point,
        target_amplitude=target_amplitude,
        outside_penalty=float(config["region_ls"]["outside_penalty"]),
        ridge=float(config["region_ls"]["ridge"]),
        rms_limit=rms_limit,
        peak_limit=peak_limit,
    )
    ls_runtime = 1000.0 * (time.perf_counter() - start)

    nominal = projected_adam_magnitude_shaping(
        ls,
        [training.target_matrix],
        [training.outside_matrix],
        target_amplitude=target_amplitude,
        outside_hinge_amplitude=float(optimizer["outside_hinge_amplitude"]),
        outside_penalty=float(optimizer["nominal_outside_penalty"]),
        rms_limit=rms_limit,
        peak_limit=peak_limit,
        iterations=int(optimizer["iterations"]),
        learning_rate=float(optimizer["learning_rate"]),
        power_regularization=float(optimizer["power_regularization"]),
    )

    scenarios = sample_linear_scenarios(
        array,
        training.target_points_m,
        training.outside_points_m,
        reference_scale=reference_scale,
        n_scenarios=int(optimizer["design_scenarios"]),
        gain_std_fraction=float(optimizer["design_gain_std_fraction"]),
        phase_std_deg=float(optimizer["design_phase_std_deg"]),
        registration_jitter_std_lambda=float(optimizer["design_registration_jitter_std_lambda"]),
        seed=int(config["platform"]["seed"]),
        include_nominal=True,
    )
    proposed = projected_adam_magnitude_shaping(
        ls,
        scenarios.target_matrices,
        scenarios.outside_matrices,
        target_amplitude=target_amplitude,
        outside_hinge_amplitude=float(optimizer["outside_hinge_amplitude"]),
        outside_penalty=float(optimizer["proposed_outside_penalty"]),
        rms_limit=rms_limit,
        peak_limit=peak_limit,
        iterations=int(optimizer["iterations"]),
        learning_rate=float(optimizer["learning_rate"]),
        power_regularization=float(optimizer["power_regularization"]),
    )

    pa = config["power_amplifier"]
    start = time.perf_counter()
    _ = digital_predistort(
        proposed.weights,
        saturation_amplitude=float(pa["saturation_amplitude"]),
        smoothness=float(pa["smoothness"]),
        maximum_phase_deg=float(pa["maximum_phase_deg"]),
        drive_limit=float(pa["predistorter_drive_limit"]),
    )
    dpd_runtime = 1000.0 * (time.perf_counter() - start)

    designs = {
        METHOD_POINT: MethodDesign(point, False, point_runtime, np.empty(0)),
        METHOD_LS: MethodDesign(ls, False, ls_runtime, np.empty(0)),
        METHOD_NOMINAL: MethodDesign(nominal.weights, False, nominal.runtime_ms, nominal.objective_history),
        METHOD_PROPOSED: MethodDesign(
            proposed.weights,
            True,
            proposed.runtime_ms + dpd_runtime,
            proposed.objective_history,
        ),
    }
    return designs, scenarios


def _draw_uncertainty(
    array: RectangularArray,
    rng: np.random.Generator,
    *,
    gain_std_fraction: float,
    phase_std_deg: float,
    registration_jitter_std_lambda: float,
) -> tuple[np.ndarray, np.ndarray]:
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
        ]
    )
    return gains, shift


def _actual_output(
    design: MethodDesign,
    config: dict[str, Any],
    *,
    saturation_amplitude: float | None = None,
) -> tuple[np.ndarray, np.ndarray]:
    pa = config["power_amplifier"]
    saturation = float(pa["saturation_amplitude"]) if saturation_amplitude is None else float(saturation_amplitude)
    if design.use_predistortion:
        drive = digital_predistort(
            design.weights,
            saturation_amplitude=saturation,
            smoothness=float(pa["smoothness"]),
            maximum_phase_deg=float(pa["maximum_phase_deg"]),
            drive_limit=float(pa["predistorter_drive_limit"]),
        )
    else:
        drive = design.weights
    output = memoryless_pa(
        drive,
        saturation_amplitude=saturation,
        smoothness=float(pa["smoothness"]),
        maximum_phase_deg=float(pa["maximum_phase_deg"]),
    )
    return np.asarray(drive, complex), np.asarray(output, complex)


def _metrics(
    field_vector: np.ndarray,
    grid: PlaneGrid,
    config: dict[str, Any],
) -> FieldControlMetrics:
    region = config["region"]
    criterion = config["success_criterion"]
    field_map = np.asarray(field_vector, complex).reshape(grid.xx_m.shape)
    return evaluate_field_control(
        field_map,
        grid.masks.target,
        grid.masks.outside,
        target_amplitude=float(region["target_amplitude"]),
        tolerance_fraction=float(region["tolerance_fraction"]),
        success_rmse_fraction=float(criterion["target_rmse_fraction"]),
        success_min_coverage=float(criterion["minimum_target_coverage"]),
        success_max_peak_outside_db=float(criterion["maximum_peak_outside_db"]),
    )


def _representative_case(
    array: RectangularArray,
    config: dict[str, Any],
    grid: PlaneGrid,
    reference_scale: float,
    designs: Mapping[str, MethodDesign],
    output_dir: Path,
) -> tuple[dict[str, dict[str, Any]], dict[str, np.ndarray], dict[str, np.ndarray], np.ndarray, np.ndarray]:
    uncertainty = config["representative_uncertainty"]
    rng = np.random.default_rng(int(uncertainty["seed"]))
    gains, shift = _draw_uncertainty(
        array,
        rng,
        gain_std_fraction=float(uncertainty["gain_std_fraction"]),
        phase_std_deg=float(uncertainty["phase_std_deg"]),
        registration_jitter_std_lambda=float(uncertainty["registration_jitter_std_lambda"]),
    )
    matrix = scalar_green_matrix(
        array,
        grid.points_m + shift,
        reference_scale=reference_scale,
        element_gains=gains,
    )

    fields: dict[str, np.ndarray] = {}
    drives: dict[str, np.ndarray] = {}
    metrics: dict[str, dict[str, Any]] = {}
    target_values: dict[str, np.ndarray] = {}
    for method in METHOD_ORDER:
        drive, output = _actual_output(designs[method], config)
        field = (matrix @ output).reshape(grid.xx_m.shape)
        result = _metrics(field.ravel(), grid, config)
        fields[method] = field
        drives[method] = drive
        target_values[method] = np.abs(field)[grid.masks.target]
        metrics[method] = {
            **result.to_dict(),
            "drive_rms": float(np.sqrt(np.mean(np.abs(drive) ** 2))),
            "drive_peak": float(np.max(np.abs(drive))),
            "weight_design_runtime_ms": float(designs[method].runtime_ms),
        }

    wavelength = array.wavelength_m
    x_lambda = grid.xx_m / wavelength
    y_lambda = grid.yy_m / wavelength
    plot_region_geometry(
        x_lambda,
        y_lambda,
        grid.masks.target,
        grid.masks.guard,
        array.positions_m[:, 0] / wavelength,
        array.positions_m[:, 1] / wavelength,
        plane_z_lambda=float(config["control_plane"]["z_lambda"]),
        output=output_dir / "01_region_geometry.png",
    )
    figure_names = {
        METHOD_POINT: "02_point_focus_map.png",
        METHOD_LS: "03_region_ls_map.png",
        METHOD_NOMINAL: "04_nominal_pgms_map.png",
        METHOD_PROPOSED: "05_sr_pgms_dpd_map.png",
    }
    for method in METHOD_ORDER:
        plot_field_map(
            x_lambda,
            y_lambda,
            np.abs(fields[method]),
            grid.masks.target,
            grid.masks.guard,
            target_amplitude=float(config["region"]["target_amplitude"]),
            title=f"{method}: representative impaired control-plane magnitude",
            output=output_dir / figure_names[method],
        )
    plot_target_amplitude_cdf(
        target_values,
        target_amplitude=float(config["region"]["target_amplitude"]),
        tolerance_fraction=float(config["region"]["tolerance_fraction"]),
        output=output_dir / "06_target_amplitude_cdf.png",
    )

    center_y = float(config["region"]["center_lambda"][1]) * wavelength
    row = int(np.argmin(np.abs(grid.y_m - center_y)))
    major = float(config["region"]["semi_axes_lambda"][0])
    minor = float(config["region"]["semi_axes_lambda"][1])
    angle = np.deg2rad(float(config["region"]["rotation_deg"]))
    x_half = math.sqrt((major * math.cos(angle)) ** 2 + (minor * math.sin(angle)) ** 2)
    center_x_lambda = float(config["region"]["center_lambda"][0])
    plot_cross_section(
        grid.x_m / wavelength,
        {method: np.abs(fields[method][row]) for method in METHOD_ORDER},
        target_amplitude=float(config["region"]["target_amplitude"]),
        target_interval_lambda=(center_x_lambda - x_half, center_x_lambda + x_half),
        output=output_dir / "07_control_plane_cross_section.png",
    )
    plot_convergence(
        {
            METHOD_NOMINAL: designs[METHOD_NOMINAL].objective_history,
            METHOD_PROPOSED: designs[METHOD_PROPOSED].objective_history,
        },
        output_dir / "08_optimizer_convergence.png",
    )
    return metrics, fields, drives, gains, shift


def _trial_parameters(config: dict[str, Any], sweep: str, value: float) -> dict[str, float]:
    base = config["representative_uncertainty"]
    parameters = {
        "gain_std_fraction": float(base["gain_std_fraction"]),
        "phase_std_deg": float(base["phase_std_deg"]),
        "registration_jitter_std_lambda": float(base["registration_jitter_std_lambda"]),
        "saturation_amplitude": float(config["power_amplifier"]["saturation_amplitude"]),
    }
    mapping = {
        "phase_error_std_deg": "phase_std_deg",
        "gain_error_std_fraction": "gain_std_fraction",
        "registration_jitter_std_lambda": "registration_jitter_std_lambda",
        "pa_saturation_amplitude": "saturation_amplitude",
    }
    parameters[mapping[sweep]] = float(value)
    return parameters


def _run_sweeps(
    array: RectangularArray,
    config: dict[str, Any],
    grid: PlaneGrid,
    reference_scale: float,
    designs: Mapping[str, MethodDesign],
    mark: Any,
) -> list[dict[str, Any]]:
    mc = config["monte_carlo"]
    records: list[dict[str, Any]] = []
    sweeps = mc["sweeps"]
    for sweep_index, (sweep, values) in enumerate(sweeps.items()):
        for value_index, value in enumerate(values):
            parameters = _trial_parameters(config, sweep, float(value))
            output_vectors: dict[str, np.ndarray] = {}
            drive_vectors: dict[str, np.ndarray] = {}
            for method in METHOD_ORDER:
                drive, output = _actual_output(
                    designs[method],
                    config,
                    saturation_amplitude=parameters["saturation_amplitude"],
                )
                output_vectors[method] = output
                drive_vectors[method] = drive
            stacked = np.column_stack([output_vectors[method] for method in METHOD_ORDER])

            for trial in range(int(mc["trials_per_point"])):
                seed = int(mc["base_seed"]) + 100000 * sweep_index + 1000 * value_index + trial
                rng = np.random.default_rng(seed)
                gains, shift = _draw_uncertainty(
                    array,
                    rng,
                    gain_std_fraction=parameters["gain_std_fraction"],
                    phase_std_deg=parameters["phase_std_deg"],
                    registration_jitter_std_lambda=parameters["registration_jitter_std_lambda"],
                )
                matrix = scalar_green_matrix(
                    array,
                    grid.points_m + shift,
                    reference_scale=reference_scale,
                    element_gains=gains,
                )
                fields = matrix @ stacked
                for method_index, method in enumerate(METHOD_ORDER):
                    result = _metrics(fields[:, method_index], grid, config)
                    drive = drive_vectors[method]
                    records.append(
                        {
                            "sweep": sweep,
                            "x_value": float(value),
                            "trial": trial,
                            "method": method,
                            **result.to_dict(),
                            "drive_rms": float(np.sqrt(np.mean(np.abs(drive) ** 2))),
                            "drive_peak": float(np.max(np.abs(drive))),
                        }
                    )
        mark(f"sweep_done:{sweep}")
    return records


def _run_ablation(
    array: RectangularArray,
    config: dict[str, Any],
    grid: PlaneGrid,
    reference_scale: float,
    designs: Mapping[str, MethodDesign],
    mark: Any,
) -> list[dict[str, Any]]:
    mc = config["monte_carlo"]
    uncertainty = config["representative_uncertainty"]
    no_dpd = MethodDesign(
        weights=designs[METHOD_PROPOSED].weights,
        use_predistortion=False,
        runtime_ms=designs[METHOD_PROPOSED].runtime_ms,
        objective_history=designs[METHOD_PROPOSED].objective_history,
    )
    ablation_designs = {
        METHOD_POINT: designs[METHOD_POINT],
        METHOD_LS: designs[METHOD_LS],
        METHOD_NOMINAL: designs[METHOD_NOMINAL],
        ABLATION_NO_DPD: no_dpd,
        METHOD_PROPOSED: designs[METHOD_PROPOSED],
    }
    outputs: dict[str, np.ndarray] = {}
    drives: dict[str, np.ndarray] = {}
    for method in ABLATION_ORDER:
        drive, output = _actual_output(ablation_designs[method], config)
        outputs[method] = output
        drives[method] = drive
    stacked = np.column_stack([outputs[method] for method in ABLATION_ORDER])

    records: list[dict[str, Any]] = []
    for trial in range(int(mc["ablation_trials"])):
        rng = np.random.default_rng(int(mc["base_seed"]) + 900000 + trial)
        gains, shift = _draw_uncertainty(
            array,
            rng,
            gain_std_fraction=float(uncertainty["gain_std_fraction"]),
            phase_std_deg=float(uncertainty["phase_std_deg"]),
            registration_jitter_std_lambda=float(uncertainty["registration_jitter_std_lambda"]),
        )
        matrix = scalar_green_matrix(
            array,
            grid.points_m + shift,
            reference_scale=reference_scale,
            element_gains=gains,
        )
        fields = matrix @ stacked
        for method_index, method in enumerate(ABLATION_ORDER):
            result = _metrics(fields[:, method_index], grid, config)
            drive = drives[method]
            records.append(
                {
                    "sweep": "key_condition",
                    "x_value": 0.0,
                    "trial": trial,
                    "method": method,
                    **result.to_dict(),
                    "drive_rms": float(np.sqrt(np.mean(np.abs(drive) ** 2))),
                    "drive_peak": float(np.max(np.abs(drive))),
                }
            )
    mark("ablation_done")
    return records


def _summarize(records: Sequence[dict[str, Any]], confidence: float) -> list[dict[str, Any]]:
    groups: dict[tuple[str, float, str], list[dict[str, Any]]] = {}
    for row in records:
        key = (str(row["sweep"]), float(row["x_value"]), str(row["method"]))
        groups.setdefault(key, []).append(row)

    summary: list[dict[str, Any]] = []
    metric_keys = [
        "target_rmse_fraction",
        "target_cv_fraction",
        "target_coverage",
        "peak_outside_db",
        "p95_outside_db",
        "outside_area_above_minus6db",
        "outside_area_above_minus10db",
        "sampled_plane_efficiency",
        "drive_rms",
        "drive_peak",
    ]
    for (sweep, x_value, method), rows in sorted(groups.items()):
        output: dict[str, Any] = {
            "sweep": sweep,
            "x_value": x_value,
            "method": method,
            "n_trials": len(rows),
        }
        for key in metric_keys:
            values = np.asarray([float(row[key]) for row in rows])
            mean, low, high = mean_confidence_interval(values, confidence)
            output[f"mean_{key}"] = mean
            output[f"{key}_ci_low"] = low
            output[f"{key}_ci_high"] = high
        success_count = sum(bool(row["control_success"]) for row in rows)
        rate, low, high = wilson_interval(success_count, len(rows), confidence)
        output.update(
            {
                "success_count": success_count,
                "success_rate": rate,
                "success_ci_low": low,
                "success_ci_high": high,
            }
        )
        summary.append(output)
    return summary


def _paired_statistics(records: Sequence[dict[str, Any]]) -> dict[str, Any]:
    by_method: dict[str, list[dict[str, Any]]] = {
        method: sorted((row for row in records if row["method"] == method), key=lambda row: int(row["trial"]))
        for method in METHOD_ORDER
    }
    proposed = np.asarray([float(row["target_rmse_fraction"]) for row in by_method[METHOD_PROPOSED]])
    result: dict[str, Any] = {}
    for baseline in [METHOD_POINT, METHOD_LS, METHOD_NOMINAL]:
        values = np.asarray([float(row["target_rmse_fraction"]) for row in by_method[baseline]])
        improvement = values - proposed
        try:
            test = wilcoxon(improvement, alternative="greater", zero_method="wilcox")
            p_value = float(test.pvalue)
        except ValueError:
            p_value = 1.0
        baseline_success = np.mean([bool(row["control_success"]) for row in by_method[baseline]])
        proposed_success = np.mean([bool(row["control_success"]) for row in by_method[METHOD_PROPOSED]])
        result[baseline] = {
            "mean_rmse_reduction_percentage_points": 100.0 * float(np.mean(improvement)),
            "median_rmse_reduction_percentage_points": 100.0 * float(np.median(improvement)),
            "wilcoxon_one_sided_p": p_value,
            "success_rate_improvement_percentage_points": 100.0 * float(proposed_success - baseline_success),
        }
    return result


def _pareto_study(
    array: RectangularArray,
    config: dict[str, Any],
    training: TrainingData,
    reference_scale: float,
    scenarios: Any,
    representative_grid: PlaneGrid,
    representative_gains: np.ndarray,
    representative_shift: np.ndarray,
    initial_weights: np.ndarray,
) -> list[dict[str, Any]]:
    optimizer = config["optimizer"]
    limits = config["excitation_limits"]
    pa = config["power_amplifier"]
    matrix = scalar_green_matrix(
        array,
        representative_grid.points_m + representative_shift,
        reference_scale=reference_scale,
        element_gains=representative_gains,
    )
    rows: list[dict[str, Any]] = []
    for penalty in config["pareto"]["outside_penalties"]:
        result = projected_adam_magnitude_shaping(
            initial_weights,
            scenarios.target_matrices,
            scenarios.outside_matrices,
            target_amplitude=float(config["region"]["target_amplitude"]),
            outside_hinge_amplitude=float(optimizer["outside_hinge_amplitude"]),
            outside_penalty=float(penalty),
            rms_limit=float(limits["rms_limit"]),
            peak_limit=float(limits["peak_limit"]),
            iterations=int(config["pareto"]["iterations"]),
            learning_rate=float(optimizer["learning_rate"]),
            power_regularization=float(optimizer["power_regularization"]),
        )
        drive = digital_predistort(
            result.weights,
            saturation_amplitude=float(pa["saturation_amplitude"]),
            smoothness=float(pa["smoothness"]),
            maximum_phase_deg=float(pa["maximum_phase_deg"]),
            drive_limit=float(pa["predistorter_drive_limit"]),
        )
        output = memoryless_pa(
            drive,
            saturation_amplitude=float(pa["saturation_amplitude"]),
            smoothness=float(pa["smoothness"]),
            maximum_phase_deg=float(pa["maximum_phase_deg"]),
        )
        metrics = _metrics(matrix @ output, representative_grid, config)
        rows.append(
            {
                "outside_penalty": float(penalty),
                **metrics.to_dict(),
                "runtime_ms": float(result.runtime_ms),
            }
        )
    return rows


def _write_dict_csv(path: Path, rows: Sequence[dict[str, Any]]) -> None:
    rows = list(rows)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    keys: list[str] = []
    for row in rows:
        for key in row:
            if key not in keys:
                keys.append(key)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=keys)
        writer.writeheader()
        writer.writerows(rows)


def _environment() -> dict[str, str]:
    return {
        "python": sys.version.split()[0],
        "numpy": np.__version__,
        "scipy": scipy.__version__,
        "matplotlib": matplotlib.__version__,
        "platform": platform.platform(),
    }


def _json_default(value: Any) -> Any:
    if isinstance(value, (np.floating, np.integer)):
        return value.item()
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, (np.bool_,)):
        return bool(value)
    raise TypeError(f"Cannot serialize {type(value)!r}")


def _flatten(prefix: str, value: Any, output: list[tuple[str, str]]) -> None:
    if isinstance(value, dict):
        for key, nested in value.items():
            _flatten(f"{prefix}.{key}" if prefix else str(key), nested, output)
    elif isinstance(value, (list, tuple)):
        output.append((prefix, json.dumps(value, ensure_ascii=False, default=_json_default)))
    elif isinstance(value, float):
        output.append((prefix, f"{value:.6g}"))
    else:
        output.append((prefix, str(value)))


def _figure_manifest() -> list[tuple[str, str]]:
    return [
        ("V0.6机理图", "00_sr_pgms_mechanism.png"),
        ("控制平面区域定义", "01_region_geometry.png"),
        ("点聚焦基线场图", "02_point_focus_map.png"),
        ("区域最小二乘场图", "03_region_ls_map.png"),
        ("名义投影梯度场图", "04_nominal_pgms_map.png"),
        ("场景鲁棒赋形与DPD场图", "05_sr_pgms_dpd_map.png"),
        ("目标区幅值CDF", "06_target_amplitude_cdf.png"),
        ("控制平面横截面", "07_control_plane_cross_section.png"),
        ("优化收敛曲线", "08_optimizer_convergence.png"),
        ("目标RMSE—相位误差", "09_rmse_vs_phase_error.png"),
        ("成功率—相位误差", "10_success_vs_phase_error.png"),
        ("目标RMSE—增益误差", "11_rmse_vs_gain_error.png"),
        ("目标RMSE—配准抖动", "12_rmse_vs_registration_jitter.png"),
        ("成功率—配准抖动", "13_success_vs_registration_jitter.png"),
        ("成功率—PA饱和尺度", "14_success_vs_pa_saturation.png"),
        ("关键工况RMSE经验CDF", "15_rmse_cdf_key_condition.png"),
        ("Rapp AM/AM曲线", "16_pa_transfer.png"),
        ("所提方法DPD驱动幅度", "17_proposed_drive_amplitude.png"),
        ("所提方法DPD驱动相位", "18_proposed_drive_phase.png"),
        ("均匀性—旁区折中", "19_pareto_tradeoff.png"),
        ("组件消融", "20_ablation.png"),
        ("权值设计耗时", "21_runtime.png"),
    ]


def _write_html_report(output_dir: Path, metrics: dict[str, Any]) -> None:
    flattened: list[tuple[str, str]] = []
    _flatten("", metrics, flattened)
    rows = "\n".join(f"<tr><td>{key}</td><td>{value}</td></tr>" for key, value in flattened)
    cards: list[str] = []
    standalone: list[str] = []
    for title, filename in _figure_manifest():
        cards.append(f'<section><h2>{title}</h2><img src="{filename}" alt="{title}"></section>')
        payload = base64.b64encode((output_dir / filename).read_bytes()).decode("ascii")
        standalone.append(f'<section><h2>{title}</h2><img src="data:image/png;base64,{payload}" alt="{title}"></section>')
    card_html = "\n".join(cards)
    standalone_html = "\n".join(standalone)
    html = f"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><title>HPM Digital Twin v0.6 场调控报告</title>
<style>
body{{font-family:Arial,"Microsoft YaHei",sans-serif;max-width:1180px;margin:34px auto;padding:0 20px;line-height:1.65}}
h1{{margin-bottom:6px}} .note{{padding:14px;border:1px solid #999;border-radius:8px;background:#fafafa}}
img{{max-width:100%;border:1px solid #bbb;border-radius:8px}} section{{margin:34px 0}}
table{{border-collapse:collapse;width:100%;font-size:13px}} td{{border:1px solid #aaa;padding:7px;word-break:break-word}}
code{{background:#eee;padding:2px 5px;border-radius:4px}}
</style></head><body>
<h1>HPM Digital Twin v0.6 — 不确定条件下的归一化近场区域精准调控</h1>
<p class="note"><strong>模型边界：</strong>本报告只比较标量Green函数下的归一化空间幅值控制、阵元增益/相位误差、平面配准抖动和无记忆PA非线性。所谓“控制成功”仅由配置中的归一化RMSE、覆盖率和旁区峰值联合门限定义，不对应真实设备效应、射程、绝对场强或毁伤概率。快速配置每点样本数有限，定稿复算入口为 <code>configs/field_control_v06_paper.yaml</code>。</p>
<h2>关键指标</h2><table>{rows}</table>{card_html}
</body></html>"""
    (output_dir / "field_control_v06_report.html").write_text(html, encoding="utf-8")
    (output_dir / "field_control_v06_report_standalone.html").write_text(
        html.replace(card_html, standalone_html), encoding="utf-8"
    )


def _write_paper_tables(
    output_dir: Path,
    key_summary: Sequence[dict[str, Any]],
    runtime_rows: Sequence[dict[str, Any]],
    pareto_rows: Sequence[dict[str, Any]],
) -> None:
    key_rows = [next(row for row in key_summary if row["method"] == method) for method in METHOD_ORDER]
    _write_dict_csv(output_dir / "paper_table_key_results.csv", key_rows)
    _write_dict_csv(output_dir / "paper_table_runtime.csv", runtime_rows)
    _write_dict_csv(output_dir / "paper_table_pareto.csv", pareto_rows)
    lines = [
        r"\begin{tabular}{lrrrrr}",
        r"\hline",
        r"Method & RMSE (\%) & Coverage (\%) & Peak outside (dB) & Success (\%) & Runtime (ms) \\",
        r"\hline",
    ]
    runtime_map = {row["method"]: float(row["runtime_ms"]) for row in runtime_rows}
    for row in key_rows:
        lines.append(
            f"{row['method']} & {100.0 * float(row['mean_target_rmse_fraction']):.2f} & "
            f"{100.0 * float(row['mean_target_coverage']):.1f} & "
            f"{float(row['mean_peak_outside_db']):.2f} & "
            f"{100.0 * float(row['success_rate']):.1f} & "
            f"{runtime_map[row['method']]:.2f} \\\\"
        )
    lines.extend([r"\hline", r"\end{tabular}"])
    (output_dir / "paper_table_key_results.tex").write_text("\n".join(lines), encoding="utf-8")


def _write_key_findings(output_dir: Path, metrics: dict[str, Any]) -> None:
    key = metrics["key_condition"]
    proposed = key[METHOD_PROPOSED]
    point = key[METHOD_POINT]
    ls = key[METHOD_LS]
    nominal = key[METHOD_NOMINAL]
    paired = metrics["paired_statistics"]
    text = f"""# V0.6 Key Findings

快速配置采用8×8阵列、z=8λ控制平面、旋转椭圆目标区，以及归一化阵元幅相误差、平面配准抖动和Rapp PA非线性。关键工况使用 {metrics['ablation_trials']} 次配对Monte Carlo。

## 关键工况

- Point-Focus：目标区RMSE {100.0 * float(point['mean_target_rmse_fraction']):.2f}%，覆盖率 {100.0 * float(point['mean_target_coverage']):.1f}%，旁区峰值 {float(point['mean_peak_outside_db']):.2f} dB，联合成功率 {100.0 * float(point['success_rate']):.1f}%。
- Region-LS：目标区RMSE {100.0 * float(ls['mean_target_rmse_fraction']):.2f}%，覆盖率 {100.0 * float(ls['mean_target_coverage']):.1f}%，旁区峰值 {float(ls['mean_peak_outside_db']):.2f} dB，联合成功率 {100.0 * float(ls['success_rate']):.1f}%。
- Nominal-PGMS：目标区RMSE {100.0 * float(nominal['mean_target_rmse_fraction']):.2f}%，覆盖率 {100.0 * float(nominal['mean_target_coverage']):.1f}%，旁区峰值 {float(nominal['mean_peak_outside_db']):.2f} dB，联合成功率 {100.0 * float(nominal['success_rate']):.1f}%。
- SR-PGMS-DPD：目标区RMSE {100.0 * float(proposed['mean_target_rmse_fraction']):.2f}%，95% CI [{100.0 * float(proposed['target_rmse_fraction_ci_low']):.2f}, {100.0 * float(proposed['target_rmse_fraction_ci_high']):.2f}]%，覆盖率 {100.0 * float(proposed['mean_target_coverage']):.1f}%，旁区峰值 {float(proposed['mean_peak_outside_db']):.2f} dB，联合成功率 {100.0 * float(proposed['success_rate']):.1f}%。

相对Point-Focus，所提方法平均RMSE降低 {float(paired[METHOD_POINT]['mean_rmse_reduction_percentage_points']):.2f} 个百分点，配对单侧Wilcoxon检验 p={float(paired[METHOD_POINT]['wilcoxon_one_sided_p']):.3g}；相对Region-LS降低 {float(paired[METHOD_LS]['mean_rmse_reduction_percentage_points']):.2f} 个百分点；相对Nominal-PGMS降低 {float(paired[METHOD_NOMINAL]['mean_rmse_reduction_percentage_points']):.2f} 个百分点。

## 需要保留的折中

SR-PGMS-DPD的优势是把目标均匀性、旁区峰值和非线性补偿同时维持在联合门限内；它并不在每个单项上都占优。点聚焦的采样平面能量效率通常更高，名义PGMS在部分工况下可得到更低旁区统计量，但两者在不确定性或PA压缩下更容易牺牲目标区覆盖率。该折中已通过Pareto图和组件消融完整保留。

这些结论只针对归一化数值模型，不对应真实设备效应、绝对场强、射程或毁伤概率。
"""
    (output_dir / "KEY_FINDINGS.md").write_text(text, encoding="utf-8")


def _write_checksums(output_dir: Path, filenames: Sequence[str]) -> None:
    lines: list[str] = []
    for filename in filenames:
        path = output_dir / filename
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        lines.append(f"{digest}  {filename}")
    (output_dir / "CHECKSUMS.sha256").write_text("\n".join(lines) + "\n", encoding="utf-8")


def run(config_path: str | Path, output_dir: str | Path) -> dict[str, Any]:
    start_time = time.perf_counter()
    config_path = Path(config_path)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    progress_path = output_dir / "progress.log"
    progress_path.write_text("start\n", encoding="utf-8")

    def mark(message: str) -> None:
        with progress_path.open("a", encoding="utf-8") as handle:
            handle.write(message + "\n")

    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    array = _array_from_config(config)
    representative_grid = _plane_grid(array, config, int(config["control_plane"]["representative_grid_points"]))
    mc_grid = _plane_grid(array, config, int(config["control_plane"]["monte_carlo_grid_points"]))
    reference_scale = point_focus_reference_scale(array, _focus_point(array, config))
    training = _training_data(array, config, representative_grid, reference_scale)
    mark("config_and_geometry_loaded")

    plot_mechanism(
        output_dir / "00_sr_pgms_mechanism.png",
        output_dir / "00_sr_pgms_mechanism.svg",
    )

    with threadpool_limits(limits=1):
        designs, scenarios = _design_methods(array, config, training, reference_scale)
        mark("weights_designed")
        representative_metrics, representative_fields, representative_drives, representative_gains, representative_shift = _representative_case(
            array,
            config,
            representative_grid,
            reference_scale,
            designs,
            output_dir,
        )
        mark("representative_case_done")
        sweep_records = _run_sweeps(array, config, mc_grid, reference_scale, designs, mark)
        sweep_summary = _summarize(sweep_records, float(config["monte_carlo"]["confidence"]))
        ablation_records = _run_ablation(array, config, mc_grid, reference_scale, designs, mark)
        ablation_summary = _summarize(ablation_records, float(config["monte_carlo"]["confidence"]))
        paired = _paired_statistics(ablation_records)
        pareto_rows = _pareto_study(
            array,
            config,
            training,
            reference_scale,
            scenarios,
            representative_grid,
            representative_gains,
            representative_shift,
            designs[METHOD_LS].weights,
        )
        mark("pareto_done")

    _write_dict_csv(output_dir / "monte_carlo_trials.csv", sweep_records)
    _write_dict_csv(output_dir / "monte_carlo_summary.csv", sweep_summary)
    _write_dict_csv(output_dir / "ablation_trials.csv", ablation_records)
    _write_dict_csv(output_dir / "ablation_summary.csv", ablation_summary)
    _write_dict_csv(output_dir / "pareto_summary.csv", pareto_rows)

    phase_rows = [row for row in sweep_summary if row["sweep"] == "phase_error_std_deg"]
    gain_rows = [row for row in sweep_summary if row["sweep"] == "gain_error_std_fraction"]
    jitter_rows = [row for row in sweep_summary if row["sweep"] == "registration_jitter_std_lambda"]
    pa_rows = [row for row in sweep_summary if row["sweep"] == "pa_saturation_amplitude"]
    plot_metric_curve(
        phase_rows,
        mean_key="mean_target_rmse_fraction",
        low_key="target_rmse_fraction_ci_low",
        high_key="target_rmse_fraction_ci_high",
        xlabel="Element phase-error standard deviation (deg)",
        ylabel="Mean target-zone RMSE fraction",
        title="Target-zone accuracy under element phase uncertainty (95% CI)",
        methods=METHOD_ORDER,
        output=output_dir / "09_rmse_vs_phase_error.png",
    )
    plot_metric_curve(
        phase_rows,
        mean_key="success_rate",
        low_key="success_ci_low",
        high_key="success_ci_high",
        xlabel="Element phase-error standard deviation (deg)",
        ylabel="Normalized control-success probability",
        title="Joint control success under phase uncertainty",
        methods=METHOD_ORDER,
        output=output_dir / "10_success_vs_phase_error.png",
        y_limits=(0.0, 1.05),
    )
    plot_metric_curve(
        gain_rows,
        mean_key="mean_target_rmse_fraction",
        low_key="target_rmse_fraction_ci_low",
        high_key="target_rmse_fraction_ci_high",
        xlabel="Element gain-error standard deviation (fraction)",
        ylabel="Mean target-zone RMSE fraction",
        title="Target-zone accuracy under element gain uncertainty (95% CI)",
        methods=METHOD_ORDER,
        output=output_dir / "11_rmse_vs_gain_error.png",
    )
    plot_metric_curve(
        jitter_rows,
        mean_key="mean_target_rmse_fraction",
        low_key="target_rmse_fraction_ci_low",
        high_key="target_rmse_fraction_ci_high",
        xlabel="Plane-registration jitter standard deviation / wavelength",
        ylabel="Mean target-zone RMSE fraction",
        title="Target-zone accuracy under registration jitter (95% CI)",
        methods=METHOD_ORDER,
        output=output_dir / "12_rmse_vs_registration_jitter.png",
    )
    plot_metric_curve(
        jitter_rows,
        mean_key="success_rate",
        low_key="success_ci_low",
        high_key="success_ci_high",
        xlabel="Plane-registration jitter standard deviation / wavelength",
        ylabel="Normalized control-success probability",
        title="Joint control success under registration jitter",
        methods=METHOD_ORDER,
        output=output_dir / "13_success_vs_registration_jitter.png",
        y_limits=(0.0, 1.05),
    )
    plot_metric_curve(
        pa_rows,
        mean_key="success_rate",
        low_key="success_ci_low",
        high_key="success_ci_high",
        xlabel="Normalized PA saturation amplitude",
        ylabel="Normalized control-success probability",
        title="Effect of memoryless PA compression and bounded predistortion",
        methods=METHOD_ORDER,
        output=output_dir / "14_success_vs_pa_saturation.png",
        y_limits=(0.0, 1.05),
    )
    plot_cdf(
        ablation_records,
        value_key="target_rmse_fraction",
        xlabel="Target-zone RMSE fraction",
        title="Key-condition target-zone error distribution",
        methods=ABLATION_ORDER,
        output=output_dir / "15_rmse_cdf_key_condition.png",
    )

    drive_axis = np.linspace(0.0, 1.5, 300)
    pa = config["power_amplifier"]
    plot_pa_transfer(
        drive_axis,
        {
            f"a_sat={value:g}": rapp_am_am(
                drive_axis,
                saturation_amplitude=float(value),
                smoothness=float(pa["smoothness"]),
            )
            for value in config["monte_carlo"]["sweeps"]["pa_saturation_amplitude"]
        },
        output=output_dir / "16_pa_transfer.png",
    )
    proposed_drive = representative_drives[METHOD_PROPOSED]
    plot_element_quantity(
        np.abs(proposed_drive),
        nx=array.nx,
        ny=array.ny,
        title="SR-PGMS-DPD normalized drive magnitude",
        label="Drive magnitude",
        output=output_dir / "17_proposed_drive_amplitude.png",
    )
    plot_element_quantity(
        np.rad2deg(np.angle(proposed_drive)),
        nx=array.nx,
        ny=array.ny,
        title="SR-PGMS-DPD normalized drive phase",
        label="Phase (deg)",
        output=output_dir / "18_proposed_drive_phase.png",
    )
    plot_pareto(
        pareto_rows,
        selected_penalty=float(config["optimizer"]["proposed_outside_penalty"]),
        output=output_dir / "19_pareto_tradeoff.png",
    )
    ablation_ordered = [
        next(row for row in ablation_summary if row["method"] == method)
        for method in ABLATION_ORDER
    ]
    plot_ablation(ablation_ordered, output_dir / "20_ablation.png")
    runtime_rows = [
        {"method": method, "runtime_ms": float(designs[method].runtime_ms)} for method in METHOD_ORDER
    ]
    plot_runtime(runtime_rows, output_dir / "21_runtime.png")

    key_condition = {
        method: next(row for row in ablation_summary if row["method"] == method)
        for method in METHOD_ORDER
    }
    metrics: dict[str, Any] = {
        "version": "0.6.0",
        "model_scope": "normalized scalar near-field magnitude control; no absolute source or device-effect inference",
        "array_elements": array.n_elements,
        "control_plane_z_lambda": float(config["control_plane"]["z_lambda"]),
        "target_region": config["region"],
        "representative_metrics": representative_metrics,
        "key_condition": key_condition,
        "paired_statistics": paired,
        "monte_carlo_trials_per_sweep_point": int(config["monte_carlo"]["trials_per_point"]),
        "ablation_trials": int(config["monte_carlo"]["ablation_trials"]),
        "runtime_seconds": float(time.perf_counter() - start_time),
        "environment": _environment(),
    }
    (output_dir / "results_summary.json").write_text(
        json.dumps(metrics, ensure_ascii=False, indent=2, default=_json_default), encoding="utf-8"
    )
    (output_dir / "environment.json").write_text(
        json.dumps(_environment(), ensure_ascii=False, indent=2), encoding="utf-8"
    )
    shutil.copyfile(config_path, output_dir / "config_snapshot.yaml")

    np.savez_compressed(
        output_dir / "representative_case.npz",
        x_lambda=representative_grid.x_m / array.wavelength_m,
        y_lambda=representative_grid.y_m / array.wavelength_m,
        target_mask=representative_grid.masks.target,
        guard_mask=representative_grid.masks.guard,
        outside_mask=representative_grid.masks.outside,
        representative_gain_vector=representative_gains,
        representative_shift_lambda=representative_shift / array.wavelength_m,
        **{f"field_{method.replace('-', '_').replace(' ', '_')}": representative_fields[method] for method in METHOD_ORDER},
        **{f"weights_{method.replace('-', '_').replace(' ', '_')}": designs[method].weights for method in METHOD_ORDER},
    )
    _write_paper_tables(output_dir, ablation_summary, runtime_rows, pareto_rows)
    _write_key_findings(output_dir, metrics)
    _write_html_report(output_dir, metrics)

    manifest_rows = [
        {"title": title, "filename": filename} for title, filename in _figure_manifest()
    ]
    _write_dict_csv(output_dir / "figure_manifest.csv", manifest_rows)
    (output_dir / "README.md").write_text(
        "# V0.6 outputs\n\n"
        "Open `field_control_v06_report_standalone.html` for the self-contained report.\n\n"
        "All fields and success criteria are normalized algorithmic quantities; no absolute effect or damage inference is included.\n",
        encoding="utf-8",
    )
    checksum_files = [
        "results_summary.json",
        "monte_carlo_summary.csv",
        "ablation_summary.csv",
        "pareto_summary.csv",
        "paper_table_key_results.csv",
        "representative_case.npz",
        "field_control_v06_report_standalone.html",
    ]
    _write_checksums(output_dir, checksum_files)
    mark("complete")
    return metrics


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default="configs/field_control_v06.yaml")
    parser.add_argument("--output", default="outputs_v06_field_control")
    args = parser.parse_args()
    metrics = run(args.config, args.output)
    print(json.dumps(metrics["key_condition"], ensure_ascii=False, indent=2, default=_json_default))


if __name__ == "__main__":
    main()

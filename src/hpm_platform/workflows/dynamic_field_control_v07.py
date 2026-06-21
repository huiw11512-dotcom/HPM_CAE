"""V0.7 dynamic normalized transmit-region control workflow.

The workflow closes the loop from delayed center measurements to timestamped
prediction, covariance-aware region control, normalized field-quality feedback,
and spatial evaluation on a moving target zone.  All quantities are normalized;
no source-power, range, device-threshold, or damage inference is performed.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence
import argparse
import base64
import csv
import hashlib
import json
import math
import os
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

from hpm_platform.evaluation.doa_statistics import mean_confidence_interval
from hpm_platform.evaluation.field_metrics import evaluate_field_control
from hpm_platform.field_control.dynamic_region_control import (
    PlanarKalmanTracker,
    covariance_sigma_centers,
    robust_dynamic_region_ls,
    sample_outside_points_lambda,
    update_feedback_scale,
)
from hpm_platform.field_control.region_shaping import (
    point_focus_reference_scale,
    rotated_ellipse_masks,
    scalar_green_matrix,
)
from hpm_platform.physics.array_geometry import C0, RectangularArray
from hpm_platform.physics.power_amplifier import digital_predistort, memoryless_pa


METHOD_STATIC = "Static-RLS"
METHOD_DELAYED = "Delayed-RLS"
METHOD_PREDICTIVE = "Predictive-RLS"
METHOD_COVARIANCE = "Covariance-RLS"
METHOD_PROPOSED = "PCF-RLS"
METHOD_ORDER = [METHOD_STATIC, METHOD_DELAYED, METHOD_PREDICTIVE, METHOD_COVARIANCE, METHOD_PROPOSED]


@dataclass(frozen=True)
class MethodSpec:
    name: str
    center_mode: str
    use_covariance: bool = False
    use_hardware_ensemble: bool = False
    use_feedback: bool = False
    use_dpd: bool = False


@dataclass(frozen=True)
class PlaneGrid:
    x_lambda: np.ndarray
    y_lambda: np.ndarray
    xx_lambda: np.ndarray
    yy_lambda: np.ndarray
    points_lambda: np.ndarray
    points_m: np.ndarray


@dataclass
class MethodState:
    weights: np.ndarray | None = None
    command_center_lambda: np.ndarray | None = None
    design_covariance_lambda2: np.ndarray | None = None
    feedback_scale: float = 1.0
    runtime_ms: float = 0.0
    condition_number: float = math.nan
    n_center_scenarios: int = 0
    n_hardware_scenarios: int = 0


@dataclass(frozen=True)
class TrialOutput:
    records: list[dict[str, Any]]
    trajectory_lambda: np.ndarray
    measurements: list[dict[str, Any]]
    predictions: list[dict[str, Any]]
    snapshots: dict[str, np.ndarray]
    snapshot_metadata: dict[str, dict[str, Any]]
    actual_gains: np.ndarray


def main_method_specs() -> tuple[MethodSpec, ...]:
    return (
        MethodSpec(METHOD_STATIC, "static"),
        MethodSpec(METHOD_DELAYED, "delayed"),
        MethodSpec(METHOD_PREDICTIVE, "predictive"),
        MethodSpec(METHOD_COVARIANCE, "predictive", use_covariance=True),
        MethodSpec(
            METHOD_PROPOSED,
            "predictive",
            use_covariance=True,
            use_hardware_ensemble=True,
            use_feedback=True,
            use_dpd=True,
        ),
    )


def ablation_specs() -> tuple[MethodSpec, ...]:
    return (
        MethodSpec(METHOD_PROPOSED, "predictive", True, True, True, True),
        MethodSpec("PCF-RLS: no prediction", "delayed", True, True, True, True),
        MethodSpec("PCF-RLS: no covariance", "predictive", False, True, True, True),
        MethodSpec("PCF-RLS: no hardware ensemble", "predictive", True, False, True, True),
        MethodSpec("PCF-RLS: no feedback", "predictive", True, True, False, True),
        MethodSpec("PCF-RLS: no DPD", "predictive", True, True, True, False),
    )


def _load_config(path: str | Path) -> dict[str, Any]:
    config_path = Path(path)
    with config_path.open("r", encoding="utf-8") as handle:
        config = yaml.safe_load(handle)
    if not isinstance(config, dict):
        raise ValueError("configuration root must be a mapping")
    if "_base" in config:
        base_path = config_path.parent / str(config.pop("_base"))
        with base_path.open("r", encoding="utf-8") as handle:
            base = yaml.safe_load(handle)
        config = _deep_merge(base, config)
    return config


def _deep_merge(base: Mapping[str, Any], update: Mapping[str, Any]) -> dict[str, Any]:
    output: dict[str, Any] = dict(base)
    for key, value in update.items():
        if isinstance(value, Mapping) and isinstance(output.get(key), Mapping):
            output[key] = _deep_merge(output[key], value)
        else:
            output[key] = value
    return output


def _array_from_config(config: Mapping[str, Any]) -> RectangularArray:
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


def _plane_grid(array: RectangularArray, config: Mapping[str, Any], n_points: int) -> PlaneGrid:
    plane = config["control_plane"]
    x = np.linspace(float(plane["x_min_lambda"]), float(plane["x_max_lambda"]), int(n_points))
    y = np.linspace(float(plane["y_min_lambda"]), float(plane["y_max_lambda"]), int(n_points))
    xx, yy = np.meshgrid(x, y, indexing="xy")
    points_lambda = np.column_stack(
        (xx.ravel(), yy.ravel(), np.full(xx.size, float(plane["z_lambda"])))
    )
    return PlaneGrid(
        x_lambda=x,
        y_lambda=y,
        xx_lambda=xx,
        yy_lambda=yy,
        points_lambda=points_lambda,
        points_m=points_lambda * array.wavelength_m,
    )


def _trajectory(
    config: Mapping[str, Any],
    *,
    n_frames: int,
    maneuver_scale: float,
    rng: np.random.Generator,
    include_process_jitter: bool,
) -> np.ndarray:
    cfg = config["trajectory"]
    t = np.arange(int(n_frames), dtype=float)
    start = np.asarray(cfg["start_lambda"], dtype=float)
    velocity = np.asarray(cfg["velocity_lambda_per_frame"], dtype=float)
    amplitude = float(maneuver_scale) * np.asarray(cfg["sinusoid_amplitude_lambda"], dtype=float)
    period = np.asarray(cfg["sinusoid_period_frames"], dtype=float)
    phase = np.array([0.15, -0.35])
    oscillation = amplitude[None, :] * np.sin(2.0 * np.pi * t[:, None] / period[None, :] + phase)
    turn = np.zeros((n_frames, 2), dtype=float)
    turn[:, 1] = (
        float(maneuver_scale)
        * float(cfg["turn_amplitude_lambda"])
        * np.tanh((t - float(cfg["turn_frame"])) / 2.8)
    )
    path = start[None, :] + t[:, None] * velocity[None, :] + oscillation + turn
    if include_process_jitter:
        jitter_std = float(cfg["process_jitter_std_lambda"])
        jitter = np.zeros_like(path)
        for index in range(1, n_frames):
            jitter[index] = 0.82 * jitter[index - 1] + rng.normal(0.0, jitter_std, 2)
        path = path + jitter
    plane = config["control_plane"]
    region = config["moving_region"]
    margin = float(max(region["semi_axes_lambda"])) * 1.25
    path[:, 0] = np.clip(path[:, 0], float(plane["x_min_lambda"]) + margin, float(plane["x_max_lambda"]) - margin)
    path[:, 1] = np.clip(path[:, 1], float(plane["y_min_lambda"]) + margin, float(plane["y_max_lambda"]) - margin)
    return path


def _draw_actual_gains(
    array: RectangularArray,
    rng: np.random.Generator,
    *,
    gain_std_fraction: float,
    phase_std_deg: float,
) -> np.ndarray:
    amplitude = np.clip(1.0 + rng.normal(0.0, float(gain_std_fraction), array.n_elements), 0.2, None)
    phase = np.deg2rad(rng.normal(0.0, float(phase_std_deg), array.n_elements))
    return amplitude * np.exp(1j * phase)


def _design_gain_scenarios(
    array: RectangularArray,
    config: Mapping[str, Any],
    rng: np.random.Generator,
) -> tuple[np.ndarray, ...]:
    cfg = config["controller"]
    count = max(int(cfg["robust_hardware_scenarios"]), 1)
    output = [np.ones(array.n_elements, dtype=complex)]
    for _ in range(1, count):
        output.append(
            _draw_actual_gains(
                array,
                rng,
                gain_std_fraction=float(cfg["design_gain_std_fraction"]),
                phase_std_deg=float(cfg["design_phase_std_deg"]),
            )
        )
    return tuple(output)


def _reference_scale(array: RectangularArray, config: Mapping[str, Any]) -> float:
    z = float(config["control_plane"]["z_lambda"])
    point = array.wavelength_m * np.array([0.0, 0.0, z])
    return point_focus_reference_scale(array, point)


def _region_masks(grid: PlaneGrid, config: Mapping[str, Any], center_lambda: np.ndarray):
    region = config["moving_region"]
    return rotated_ellipse_masks(
        grid.xx_lambda,
        grid.yy_lambda,
        center_m=(float(center_lambda[0]), float(center_lambda[1])),
        semi_axes_m=(float(region["semi_axes_lambda"][0]), float(region["semi_axes_lambda"][1])),
        rotation_deg=float(region["rotation_deg"]),
        guard_scale=float(region["guard_scale"]),
    )


def _feedback_update(
    state: MethodState,
    observed_mean: float,
    config: Mapping[str, Any],
) -> None:
    controller = config["controller"]
    region = config["moving_region"]
    state.feedback_scale = update_feedback_scale(
        state.feedback_scale,
        observed_mean,
        target_amplitude=float(region["target_amplitude"]),
        proportional_gain=float(controller["feedback_proportional_gain"]),
        smoothing=float(controller["feedback_smoothing"]),
        minimum_scale=float(controller["feedback_minimum_scale"]),
        maximum_scale=float(controller["feedback_maximum_scale"]),
    )


def _command_center(
    spec: MethodSpec,
    *,
    initial_center: np.ndarray,
    latest_measurement: np.ndarray,
    predicted_center: np.ndarray,
) -> np.ndarray:
    if spec.center_mode == "static":
        return initial_center.copy()
    if spec.center_mode == "delayed":
        return latest_measurement.copy()
    if spec.center_mode == "predictive":
        return predicted_center.copy()
    raise ValueError(f"unknown center mode: {spec.center_mode}")


def _design_method(
    array: RectangularArray,
    config: Mapping[str, Any],
    spec: MethodSpec,
    state: MethodState,
    *,
    command_center: np.ndarray,
    prediction_covariance: np.ndarray,
    reference_scale: float,
    design_gains: tuple[np.ndarray, ...],
    seed: int,
) -> None:
    controller = config["controller"]
    plane = config["control_plane"]
    region = config["moving_region"]
    limits = config["excitation_limits"]
    covariance = np.asarray(prediction_covariance, dtype=float)
    if spec.use_covariance:
        centers = covariance_sigma_centers(
            command_center,
            covariance,
            sigma_scale=float(controller["covariance_sigma_scale"]),
            maximum_offset_lambda=float(controller["covariance_max_offset_lambda"]),
            include_diagonals=bool(controller["covariance_diagonal_points"]),
        )
        buffer = float(controller["envelope_sigma_scale"]) * np.sqrt(np.maximum(np.diag(covariance), 0.0))
    else:
        centers = command_center[None, :]
        buffer = np.zeros(2, dtype=float)
    base_axes = np.asarray(region["semi_axes_lambda"], dtype=float)
    envelope_axes = base_axes + np.minimum(buffer, float(controller["covariance_max_offset_lambda"]))
    outside = sample_outside_points_lambda(
        [float(plane["x_min_lambda"]), float(plane["x_max_lambda"])],
        [float(plane["y_min_lambda"]), float(plane["y_max_lambda"])],
        z_lambda=float(plane["z_lambda"]),
        center_lambda=command_center,
        semi_axes_lambda=envelope_axes,
        rotation_deg=float(region["rotation_deg"]),
        guard_scale=float(region["guard_scale"]),
        n_points=int(controller["outside_samples"]),
        seed=int(seed),
    )
    gains = design_gains if spec.use_hardware_ensemble else (np.ones(array.n_elements, dtype=complex),)
    target_amplitude = float(region["target_amplitude"]) * (state.feedback_scale if spec.use_feedback else 1.0)
    result = robust_dynamic_region_ls(
        array,
        centers,
        semi_axes_lambda=base_axes,
        rotation_deg=float(region["rotation_deg"]),
        z_lambda=float(plane["z_lambda"]),
        outside_points_lambda=outside,
        reference_scale=reference_scale,
        target_amplitude=target_amplitude,
        outside_penalty=float(
            controller.get("proposed_outside_penalty", controller["outside_penalty"])
            if spec.use_hardware_ensemble
            else controller["outside_penalty"]
        ),
        ridge=float(controller["ridge"]),
        rms_limit=float(limits["rms_limit"]),
        peak_limit=float(limits["peak_limit"]),
        hardware_gain_scenarios=gains,
        radial_samples=int(controller["target_radial_samples"]),
        angular_samples=int(controller["target_angular_samples"]),
        alternating_iterations=int(controller.get("alternating_iterations", 3)),
    )
    state.weights = result.weights
    state.command_center_lambda = command_center.copy()
    state.design_covariance_lambda2 = covariance.copy()
    state.runtime_ms = float(result.runtime_ms)
    state.condition_number = float(result.condition_number)
    state.n_center_scenarios = int(result.n_center_scenarios)
    state.n_hardware_scenarios = int(result.n_hardware_scenarios)


def _pa_output(weights: np.ndarray, spec: MethodSpec, config: Mapping[str, Any]) -> tuple[np.ndarray, np.ndarray]:
    pa = config["power_amplifier"]
    if spec.use_dpd:
        drive = digital_predistort(
            weights,
            saturation_amplitude=float(pa["saturation_amplitude"]),
            smoothness=float(pa["smoothness"]),
            maximum_phase_deg=float(pa["maximum_phase_deg"]),
            drive_limit=float(pa["predistorter_drive_limit"]),
        )
    else:
        drive = np.asarray(weights, dtype=complex)
    output = memoryless_pa(
        drive,
        saturation_amplitude=float(pa["saturation_amplitude"]),
        smoothness=float(pa["smoothness"]),
        maximum_phase_deg=float(pa["maximum_phase_deg"]),
    )
    return np.asarray(drive, complex), np.asarray(output, complex)


def _simulate_trial(
    config: Mapping[str, Any],
    *,
    seed: int,
    n_frames: int,
    grid_points: int,
    maneuver_scale: float,
    processing_delay_frames: int,
    measurement_noise_std_lambda: float,
    phase_error_std_deg: float,
    specs: Sequence[MethodSpec],
    store_snapshots: bool = False,
    store_all_fields: bool = False,
    include_process_jitter: bool = True,
) -> TrialOutput:
    if processing_delay_frames < 0 or measurement_noise_std_lambda < 0 or phase_error_std_deg < 0:
        raise ValueError("delay and uncertainty parameters must be non-negative")
    array = _array_from_config(config)
    grid = _plane_grid(array, config, grid_points)
    reference = _reference_scale(array, config)
    seed_sequence = np.random.SeedSequence(int(seed))
    children = seed_sequence.spawn(7)
    rng_path = np.random.default_rng(children[0])
    rng_measurement = np.random.default_rng(children[1])
    rng_hardware = np.random.default_rng(children[2])
    rng_design = np.random.default_rng(children[3])
    rng_feedback = np.random.default_rng(children[4])
    rng_misc = np.random.default_rng(children[5])

    trajectory = _trajectory(
        config,
        n_frames=n_frames + int(config["sensing"]["actuation_latency_frames"]) + 1,
        maneuver_scale=maneuver_scale,
        rng=rng_path,
        include_process_jitter=include_process_jitter,
    )
    sensing = config["sensing"]
    actual_cfg = config["actual_impairments"]
    actual_gains = _draw_actual_gains(
        array,
        rng_hardware,
        gain_std_fraction=float(actual_cfg["gain_std_fraction"]),
        phase_std_deg=float(phase_error_std_deg),
    )
    actual_matrix = scalar_green_matrix(
        array,
        grid.points_m,
        reference_scale=reference,
        element_gains=actual_gains,
    )
    design_gains = _design_gain_scenarios(array, config, rng_design)

    initial_prior = trajectory[0] + rng_measurement.normal(0.0, float(sensing["initial_prior_std_lambda"]), 2)
    tracker = PlanarKalmanTracker(
        initial_prior,
        initial_position_std_lambda=float(sensing["tracker_initial_position_std_lambda"]),
        initial_velocity_std_lambda_per_frame=float(sensing["tracker_initial_velocity_std_lambda_per_frame"]),
        process_acceleration_std_lambda_per_frame2=float(
            sensing["tracker_process_acceleration_std_lambda_per_frame2"]
        ),
        initial_time=0.0,
    )
    latest_measurement = initial_prior.copy()
    measurement_covariance = np.eye(2) * max(float(measurement_noise_std_lambda), 1e-4) ** 2
    arrivals: dict[int, list[tuple[int, np.ndarray]]] = {}
    measurement_log: list[dict[str, Any]] = []
    interval = int(sensing["measurement_interval_frames"])
    for acquisition in range(0, int(n_frames), interval):
        measurement = trajectory[acquisition] + rng_measurement.normal(
            0.0, float(measurement_noise_std_lambda), 2
        )
        arrival = acquisition + int(processing_delay_frames)
        arrivals.setdefault(arrival, []).append((acquisition, measurement))
        measurement_log.append(
            {
                "acquisition_frame": int(acquisition),
                "arrival_frame": int(arrival),
                "x_lambda": float(measurement[0]),
                "y_lambda": float(measurement[1]),
            }
        )

    states = {spec.name: MethodState() for spec in specs}
    feedback_history = {spec.name: [] for spec in specs}
    records: list[dict[str, Any]] = []
    prediction_log: list[dict[str, Any]] = []
    snapshots: dict[str, np.ndarray] = {}
    snapshot_metadata: dict[str, dict[str, Any]] = {}
    representative_cfg = config.get("representative", {})
    snapshot_frames = {int(value) for value in representative_cfg.get("snapshot_frames", [])}
    update_interval = int(config["controller"]["update_interval_frames"])
    actuation_latency = int(sensing["actuation_latency_frames"])
    feedback_delay = int(sensing["feedback_delay_frames"])

    for frame in range(int(n_frames)):
        for acquisition, measurement in arrivals.get(frame, []):
            tracker.update(
                measurement,
                measurement_covariance,
                measurement_time=float(acquisition),
                gate_mahalanobis_sq=float(sensing["gate_mahalanobis_sq"]),
            )
            latest_measurement = measurement.copy()
        prediction = tracker.predict(float(frame + actuation_latency))
        prediction_log.append(
            {
                "frame": int(frame),
                "actuation_frame": int(frame + actuation_latency),
                "mean_x_lambda": float(prediction.mean_lambda[0]),
                "mean_y_lambda": float(prediction.mean_lambda[1]),
                "cov_xx_lambda2": float(prediction.covariance_lambda2[0, 0]),
                "cov_xy_lambda2": float(prediction.covariance_lambda2[0, 1]),
                "cov_yy_lambda2": float(prediction.covariance_lambda2[1, 1]),
            }
        )
        evaluation_frame = min(frame + actuation_latency, trajectory.shape[0] - 1)
        true_center = trajectory[evaluation_frame]
        masks = _region_masks(grid, config, true_center)

        for method_index, spec in enumerate(specs):
            state = states[spec.name]
            if spec.use_feedback and frame - feedback_delay >= 0:
                observed = feedback_history[spec.name][frame - feedback_delay]
                noise = rng_feedback.normal(
                    0.0,
                    float(config["controller"]["feedback_measurement_noise_fraction"]),
                )
                _feedback_update(state, max(float(observed) * (1.0 + noise), 1e-6), config)

            command_center = _command_center(
                spec,
                initial_center=initial_prior,
                latest_measurement=latest_measurement,
                predicted_center=prediction.mean_lambda,
            )
            if spec.center_mode == "delayed" and spec.use_covariance:
                design_covariance = measurement_covariance + np.eye(2) * (
                    float(config["sensing"]["tracker_process_acceleration_std_lambda_per_frame2"])
                    * max(processing_delay_frames + actuation_latency, 1)
                ) ** 2
            else:
                design_covariance = prediction.covariance_lambda2
            needs_update = state.weights is None or frame % update_interval == 0
            if needs_update:
                _design_method(
                    array,
                    config,
                    spec,
                    state,
                    command_center=command_center,
                    prediction_covariance=design_covariance,
                    reference_scale=reference,
                    design_gains=design_gains,
                    seed=int(seed + 10007 * (frame + 1) + 101 * (method_index + 1)),
                )
                runtime_ms = state.runtime_ms
            else:
                runtime_ms = 0.0
            assert state.weights is not None and state.command_center_lambda is not None
            drive, pa_output = _pa_output(state.weights, spec, config)
            field = (actual_matrix @ pa_output).reshape(grid.xx_lambda.shape)
            region = config["moving_region"]
            criterion = config["success_criterion"]
            metrics = evaluate_field_control(
                field,
                masks.target,
                masks.outside,
                target_amplitude=float(region["target_amplitude"]),
                tolerance_fraction=float(region["tolerance_fraction"]),
                success_rmse_fraction=float(criterion["target_rmse_fraction"]),
                success_min_coverage=float(criterion["minimum_target_coverage"]),
                success_max_peak_outside_db=float(criterion["maximum_peak_outside_db"]),
            )
            feedback_history[spec.name].append(float(metrics.target_mean))
            dynamic_success = bool(
                metrics.target_rmse_fraction <= float(criterion["target_rmse_fraction"])
                and metrics.target_coverage >= float(criterion["minimum_target_coverage"])
                and metrics.p95_outside_db <= float(
                    criterion.get("maximum_p95_outside_db", criterion["maximum_peak_outside_db"])
                )
            )
            command_error = float(np.linalg.norm(state.command_center_lambda - true_center))
            record = {
                "method": spec.name,
                "frame": int(frame),
                "actuation_frame": int(evaluation_frame),
                "true_x_lambda": float(true_center[0]),
                "true_y_lambda": float(true_center[1]),
                "command_x_lambda": float(state.command_center_lambda[0]),
                "command_y_lambda": float(state.command_center_lambda[1]),
                "command_center_error_lambda": command_error,
                "prediction_std_x_lambda": float(np.sqrt(max(prediction.covariance_lambda2[0, 0], 0.0))),
                "prediction_std_y_lambda": float(np.sqrt(max(prediction.covariance_lambda2[1, 1], 0.0))),
                "target_rmse_fraction": float(metrics.target_rmse_fraction),
                "target_coverage": float(metrics.target_coverage),
                "target_mean": float(metrics.target_mean),
                "target_cv_fraction": float(metrics.target_cv_fraction),
                "peak_outside_db": float(metrics.peak_outside_db),
                "p95_outside_db": float(metrics.p95_outside_db),
                "sampled_plane_efficiency": float(metrics.sampled_plane_efficiency),
                "control_success": dynamic_success,
                "feedback_scale": float(state.feedback_scale),
                "design_runtime_ms": float(runtime_ms),
                "condition_number": float(state.condition_number),
                "n_center_scenarios": int(state.n_center_scenarios),
                "n_hardware_scenarios": int(state.n_hardware_scenarios),
                "drive_rms": float(np.sqrt(np.mean(np.abs(drive) ** 2))),
                "drive_peak": float(np.max(np.abs(drive))),
            }
            records.append(record)
            if store_snapshots and (store_all_fields or frame in snapshot_frames or spec.name == METHOD_PROPOSED):
                key = f"{spec.name}__frame_{frame:03d}"
                snapshots[key] = np.asarray(field, complex)
                snapshot_metadata[key] = {
                    "method": spec.name,
                    "frame": int(frame),
                    "actuation_frame": int(evaluation_frame),
                    "true_center_lambda": true_center.tolist(),
                    "command_center_lambda": state.command_center_lambda.tolist(),
                    "target_rmse_fraction": float(metrics.target_rmse_fraction),
                    "target_coverage": float(metrics.target_coverage),
                    "peak_outside_db": float(metrics.peak_outside_db),
                }

    return TrialOutput(
        records=records,
        trajectory_lambda=trajectory,
        measurements=measurement_log,
        predictions=prediction_log,
        snapshots=snapshots,
        snapshot_metadata=snapshot_metadata,
        actual_gains=actual_gains,
    )


def _trial_summary(records: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    methods = list(dict.fromkeys(str(row["method"]) for row in records))
    output: list[dict[str, Any]] = []
    for method in methods:
        selected = [row for row in records if row["method"] == method]
        updates = [float(row["design_runtime_ms"]) for row in selected if float(row["design_runtime_ms"]) > 0]
        output.append(
            {
                "method": method,
                "mean_target_rmse_fraction": float(np.mean([row["target_rmse_fraction"] for row in selected])),
                "mean_target_coverage": float(np.mean([row["target_coverage"] for row in selected])),
                "mean_peak_outside_db": float(np.mean([row["peak_outside_db"] for row in selected])),
                "mean_target_mean": float(np.mean([row["target_mean"] for row in selected])),
                "mean_command_center_error_lambda": float(
                    np.mean([row["command_center_error_lambda"] for row in selected])
                ),
                "control_success_rate": float(np.mean([row["control_success"] for row in selected])),
                "median_update_runtime_ms": float(np.median(updates)) if updates else 0.0,
                "p95_update_runtime_ms": float(np.quantile(updates, 0.95)) if updates else 0.0,
                "mean_drive_rms": float(np.mean([row["drive_rms"] for row in selected])),
            }
        )
    return output


def _sweep_overrides(
    config: Mapping[str, Any], sweep: str, value: float
) -> tuple[int, float, float, float]:
    delay = int(config["sensing"]["processing_delay_frames"])
    noise = float(config["sensing"]["measurement_noise_std_lambda"])
    maneuver = float(config["trajectory"]["representative_maneuver_scale"])
    phase = float(config["actual_impairments"]["phase_std_deg"])
    if sweep == "processing_delay_frames":
        delay = int(value)
    elif sweep == "measurement_noise_std_lambda":
        noise = float(value)
    elif sweep == "maneuver_scale":
        maneuver = float(value)
    elif sweep == "phase_error_std_deg":
        phase = float(value)
    else:
        raise ValueError(f"unknown sweep: {sweep}")
    return delay, noise, maneuver, phase


def _run_sweeps(config: Mapping[str, Any], *, progress_path: Path) -> list[dict[str, Any]]:
    mc = config["monte_carlo"]
    records: list[dict[str, Any]] = []
    base_seed = int(mc["base_seed"])
    counter = 0
    for sweep, values in mc["sweeps"].items():
        for x_index, value in enumerate(values):
            delay, noise, maneuver, phase = _sweep_overrides(config, str(sweep), float(value))
            for trial in range(int(mc["trials_per_point"])):
                counter += 1
                seed = base_seed + 100000 * (list(mc["sweeps"].keys()).index(sweep) + 1) + 1000 * x_index + trial
                output = _simulate_trial(
                    config,
                    seed=seed,
                    n_frames=int(mc["frames"]),
                    grid_points=int(config["control_plane"]["monte_carlo_grid_points"]),
                    maneuver_scale=maneuver,
                    processing_delay_frames=delay,
                    measurement_noise_std_lambda=noise,
                    phase_error_std_deg=phase,
                    specs=main_method_specs(),
                    store_snapshots=False,
                    include_process_jitter=True,
                )
                for summary in _trial_summary(output.records):
                    records.append(
                        {
                            "sweep": str(sweep),
                            "x_value": float(value),
                            "trial": int(trial),
                            "seed": int(seed),
                            **summary,
                        }
                    )
                with progress_path.open("a", encoding="utf-8") as handle:
                    handle.write(f"sweep={sweep}, value={value}, trial={trial}, seed={seed}\n")
    return records


def _run_ablation(config: Mapping[str, Any], *, progress_path: Path) -> list[dict[str, Any]]:
    mc = config["monte_carlo"]
    output_rows: list[dict[str, Any]] = []
    for trial in range(int(mc["ablation_trials"])):
        seed = int(mc["base_seed"]) + 900000 + trial
        output = _simulate_trial(
            config,
            seed=seed,
            n_frames=int(mc["frames"]),
            grid_points=int(config["control_plane"]["monte_carlo_grid_points"]),
            maneuver_scale=float(config["trajectory"]["representative_maneuver_scale"]),
            processing_delay_frames=int(config["sensing"]["processing_delay_frames"]),
            measurement_noise_std_lambda=float(config["sensing"]["measurement_noise_std_lambda"]),
            phase_error_std_deg=float(config["actual_impairments"]["phase_std_deg"]),
            specs=ablation_specs(),
            store_snapshots=False,
            include_process_jitter=True,
        )
        for summary in _trial_summary(output.records):
            output_rows.append({"trial": int(trial), "seed": int(seed), **summary})
        with progress_path.open("a", encoding="utf-8") as handle:
            handle.write(f"ablation trial={trial}, seed={seed}\n")
    return output_rows


def _summarize_sweeps(rows: Sequence[dict[str, Any]], confidence: float) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    keys = sorted({(str(row["sweep"]), float(row["x_value"]), str(row["method"])) for row in rows})
    for sweep, x_value, method in keys:
        selected = [row for row in rows if row["sweep"] == sweep and float(row["x_value"]) == x_value and row["method"] == method]
        entry: dict[str, Any] = {
            "sweep": sweep,
            "x_value": x_value,
            "method": method,
            "n_trials": len(selected),
        }
        for key in (
            "mean_target_rmse_fraction",
            "mean_target_coverage",
            "mean_peak_outside_db",
            "mean_command_center_error_lambda",
            "control_success_rate",
            "median_update_runtime_ms",
        ):
            values = np.asarray([float(row[key]) for row in selected], dtype=float)
            mean, low, high = mean_confidence_interval(values, confidence)
            entry[f"{key}_mean"] = mean
            entry[f"{key}_ci_low"] = low
            entry[f"{key}_ci_high"] = high
        output.append(entry)
    return output


def _summarize_ablation(rows: Sequence[dict[str, Any]], confidence: float) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for method in dict.fromkeys(str(row["method"]) for row in rows):
        selected = [row for row in rows if row["method"] == method]
        entry: dict[str, Any] = {"method": method, "n_trials": len(selected)}
        for key in ("mean_target_rmse_fraction", "mean_target_coverage", "control_success_rate"):
            mean, low, high = mean_confidence_interval([float(row[key]) for row in selected], confidence)
            entry[f"{key}_mean"] = mean
            entry[f"{key}_ci_low"] = low
            entry[f"{key}_ci_high"] = high
        output.append(entry)
    return output


def _paired_statistics(sweep_rows: Sequence[dict[str, Any]], config: Mapping[str, Any]) -> dict[str, Any]:
    key_sweep = "processing_delay_frames"
    key_value = float(config["sensing"]["processing_delay_frames"])
    selected = [row for row in sweep_rows if row["sweep"] == key_sweep and float(row["x_value"]) == key_value]
    by_method_trial = {(str(row["method"]), int(row["trial"])): float(row["mean_target_rmse_fraction"]) for row in selected}
    trials = sorted({int(row["trial"]) for row in selected if row["method"] == METHOD_PROPOSED})
    result: dict[str, Any] = {"sweep": key_sweep, "x_value": key_value, "comparisons": {}}
    proposed = np.asarray([by_method_trial[(METHOD_PROPOSED, trial)] for trial in trials], dtype=float)
    for baseline in METHOD_ORDER[:-1]:
        baseline_values = np.asarray([by_method_trial[(baseline, trial)] for trial in trials], dtype=float)
        difference = baseline_values - proposed
        if difference.size < 2 or np.allclose(difference, 0.0):
            p_value = 1.0
        else:
            p_value = float(wilcoxon(proposed, baseline_values, alternative="less").pvalue)
        result["comparisons"][baseline] = {
            "mean_rmse_reduction_percentage_points": float(100.0 * np.mean(difference)),
            "relative_rmse_reduction_percent": float(
                100.0 * np.mean(difference) / max(float(np.mean(baseline_values)), 1e-12)
            ),
            "wilcoxon_one_sided_p": p_value,
            "n_pairs": int(difference.size),
        }
    return result


def _write_csv(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = list(rows)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    fieldnames: list[str] = []
    for row in rows:
        for key in row:
            if key not in fieldnames:
                fieldnames.append(key)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _json_default(value: Any) -> Any:
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, (np.floating, np.integer, np.bool_)):
        return value.item()
    if isinstance(value, complex):
        return {"real": value.real, "imag": value.imag}
    if isinstance(value, Path):
        return str(value)
    raise TypeError(f"cannot serialize {type(value)!r}")


def _environment() -> dict[str, str]:
    return {
        "python": sys.version.split()[0],
        "numpy": np.__version__,
        "scipy": scipy.__version__,
        "matplotlib": matplotlib.__version__,
        "platform": platform.platform(),
    }


def _write_npz(path: Path, trial: TrialOutput, grid: PlaneGrid) -> None:
    arrays: dict[str, np.ndarray] = {
        "trajectory_lambda": trial.trajectory_lambda,
        "x_lambda": grid.x_lambda,
        "y_lambda": grid.y_lambda,
        "actual_gains": trial.actual_gains,
    }
    for key, value in trial.snapshots.items():
        safe = key.replace("-", "_").replace(":", "_").replace(" ", "_")
        arrays[f"field__{safe}"] = value
    np.savez_compressed(path, **arrays)


def _write_paper_table(path_csv: Path, path_tex: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    _write_csv(path_csv, rows)
    lines = [
        r"\begin{tabular}{lrrrr}",
        r"\toprule",
        r"Method & Mean RMSE (\%) & Coverage (\%) & Success (\%) & Median update (ms) \\",
        r"\midrule",
    ]
    for row in rows:
        lines.append(
            f"{row['method']} & {100*float(row['mean_target_rmse_fraction']):.2f} & "
            f"{100*float(row['mean_target_coverage']):.1f} & {100*float(row['control_success_rate']):.1f} & "
            f"{float(row['median_update_runtime_ms']):.2f} " + r" \\"
        )
    lines.extend([r"\bottomrule", r"\end{tabular}"])
    path_tex.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _checksum_files(output_dir: Path, names: Sequence[str]) -> None:
    lines: list[str] = []
    for name in names:
        path = output_dir / name
        if path.exists() and path.is_file():
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            lines.append(f"{digest}  {name}")
    (output_dir / "CHECKSUMS.sha256").write_text("\n".join(lines) + "\n", encoding="utf-8")


def run(config_path: str | Path, output_dir: str | Path) -> dict[str, Any]:
    """Run V0.7 representative, sweep, ablation, visualization, and reporting."""
    config = _load_config(config_path)
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    progress = output / "progress.log"
    progress.write_text("V0.7 dynamic field-control run started\n", encoding="utf-8")
    start = time.perf_counter()

    with threadpool_limits(limits=1):
        representative = _simulate_trial(
            config,
            seed=int(config["representative"]["seed"]),
            n_frames=int(config["trajectory"]["frames"]),
            grid_points=int(config["control_plane"]["representative_grid_points"]),
            maneuver_scale=float(config["trajectory"]["representative_maneuver_scale"]),
            processing_delay_frames=int(config["sensing"]["processing_delay_frames"]),
            measurement_noise_std_lambda=float(config["sensing"]["measurement_noise_std_lambda"]),
            phase_error_std_deg=float(config["actual_impairments"]["phase_std_deg"]),
            specs=main_method_specs(),
            store_snapshots=True,
            include_process_jitter=False,
        )
        representative_summary = _trial_summary(representative.records)
        with progress.open("a", encoding="utf-8") as handle:
            handle.write("representative complete\n")
        sweep_rows = _run_sweeps(config, progress_path=progress)
        ablation_rows = _run_ablation(config, progress_path=progress)
    sweep_summary = _summarize_sweeps(sweep_rows, float(config["monte_carlo"]["confidence"]))
    ablation_summary = _summarize_ablation(ablation_rows, float(config["monte_carlo"]["confidence"]))
    paired = _paired_statistics(sweep_rows, config)

    array = _array_from_config(config)
    rep_grid = _plane_grid(array, config, int(config["control_plane"]["representative_grid_points"]))
    _write_csv(output / "representative_frame_records.csv", representative.records)
    _write_csv(output / "representative_summary.csv", representative_summary)
    _write_csv(output / "measurement_log.csv", representative.measurements)
    _write_csv(output / "prediction_log.csv", representative.predictions)
    _write_csv(output / "monte_carlo_trials.csv", sweep_rows)
    _write_csv(output / "monte_carlo_summary.csv", sweep_summary)
    _write_csv(output / "ablation_trials.csv", ablation_rows)
    _write_csv(output / "ablation_summary.csv", ablation_summary)
    _write_npz(output / "representative_case.npz", representative, rep_grid)
    _write_paper_table(
        output / "paper_table_key_results.csv",
        output / "paper_table_key_results.tex",
        representative_summary,
    )
    with (output / "config_snapshot.yaml").open("w", encoding="utf-8") as handle:
        yaml.safe_dump(config, handle, sort_keys=False, allow_unicode=True)
    (output / "environment.json").write_text(
        json.dumps(_environment(), indent=2, ensure_ascii=False), encoding="utf-8"
    )
    metrics: dict[str, Any] = {
        "platform_version": str(config["platform"]["version"]),
        "normalized_scope": True,
        "representative_summary": representative_summary,
        "paired_statistics": paired,
        "snapshot_metadata": representative.snapshot_metadata,
        "monte_carlo_points": len(sweep_rows),
        "ablation_points": len(ablation_rows),
        "run_time_seconds": float(time.perf_counter() - start),
    }
    (output / "results_summary.json").write_text(
        json.dumps(metrics, indent=2, ensure_ascii=False, default=_json_default), encoding="utf-8"
    )

    from hpm_platform.visualization.dynamic_field_control_v07 import generate_all_figures, write_reports

    figure_manifest = generate_all_figures(
        output_dir=output,
        config=config,
        representative=representative,
        representative_summary=representative_summary,
        sweep_summary=sweep_summary,
        sweep_rows=sweep_rows,
        ablation_summary=ablation_summary,
        grid=rep_grid,
    )
    _write_csv(output / "figure_manifest.csv", figure_manifest)
    write_reports(
        output_dir=output,
        config=config,
        metrics=metrics,
        representative_summary=representative_summary,
        sweep_summary=sweep_summary,
        ablation_summary=ablation_summary,
        figure_manifest=figure_manifest,
    )
    _checksum_files(
        output,
        [
            "results_summary.json",
            "representative_frame_records.csv",
            "monte_carlo_summary.csv",
            "ablation_summary.csv",
            "representative_case.npz",
            "dynamic_field_control_v07_report_standalone.html",
        ],
    )
    with progress.open("a", encoding="utf-8") as handle:
        handle.write(f"complete, runtime_seconds={time.perf_counter() - start:.3f}\n")
    return metrics


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default="configs/dynamic_field_control_v07.yaml")
    parser.add_argument("--output", default="outputs_v07_dynamic_field_control")
    args = parser.parse_args()
    run(args.config, args.output)


if __name__ == "__main__":
    main()

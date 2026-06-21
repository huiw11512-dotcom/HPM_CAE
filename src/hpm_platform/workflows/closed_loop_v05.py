"""V0.5 dynamic perception--protection closed-loop workflow.

The workflow couples the V0.3 PAWR front-end to a timestamp-aware Kalman
tracker and the V0.4 confidence-region receive-protection model.  Two moving
interferers, processing latency, sparse channel faults, and stale covariance
updates are simulated with normalized narrowband data.  No absolute source
power, range, equipment threshold, or damage inference is included.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Sequence
import argparse
import base64
import csv
import hashlib
import json
import math
import platform
import sys
import time

import matplotlib
import numpy as np
import scipy
from scipy.optimize import linear_sum_assignment
from scipy.stats import wilcoxon
from threadpoolctl import threadpool_limits
import yaml

from hpm_platform.evaluation.doa_statistics import mean_confidence_interval
from hpm_platform.evaluation.metrics import angular_error_deg
from hpm_platform.perception.music import MusicGridScanner
from hpm_platform.perception.robust_covariance import pawr_estimate, refine_music_peaks
from hpm_platform.perception.tracking import MultiTargetKalmanTracker, TrackPrediction
from hpm_platform.perception.uncertainty import local_music_posterior_covariance
from hpm_platform.physics.array_geometry import C0, RectangularArray
from hpm_platform.protection.beamforming import covariance_matrix
from hpm_platform.protection.dynamic_beamforming import (
    MultiHybridNullResult,
    analytic_output_sinr_multi_db,
    build_covariance_confidence_sector,
    fault_aware_covariance,
    multi_confidence_region_hybrid_null_weights,
    multi_point_lcmv_weights,
    worst_interferer_response_db,
)
from hpm_platform.protection.robust_beamforming import white_noise_gain_db
from hpm_platform.visualization.closed_loop_v05 import (
    plot_ablation,
    plot_confidence_width_rank,
    plot_health_maps,
    plot_mechanism,
    plot_metric_sweep,
    plot_response_map,
    plot_runtime,
    plot_sensor_health_timeline,
    plot_timeline,
    plot_tracking,
    plot_tracking_error,
    plot_trajectory,
)


METHOD_STATIC = "Static-Point"
METHOD_DELAYED = "Delayed-Point"
METHOD_PREDICTIVE = "Predictive-Point"
METHOD_FIXED = "Delayed-FixedCR"
METHOD_PROPOSED = "PCP-HybridNull"
METHOD_ORDER = [
    METHOD_STATIC,
    METHOD_DELAYED,
    METHOD_PREDICTIVE,
    METHOD_FIXED,
    METHOD_PROPOSED,
]

ABLATION_PRED_POINT = "Prediction only"
ABLATION_PRED_FIXED = "Prediction + fixed sector"
ABLATION_COV_DELAYED = "DOA covariance, no prediction"
ABLATION_NO_HEALTH = "PCP without health penalty"
ABLATION_FULL = "Full PCP-HybridNull"
ABLATION_ORDER = [
    ABLATION_PRED_POINT,
    ABLATION_PRED_FIXED,
    ABLATION_COV_DELAYED,
    ABLATION_NO_HEALTH,
    ABLATION_FULL,
]


@dataclass(frozen=True)
class MeasurementPacket:
    acquisition_frame: int
    ready_frame: int
    estimates_deg: tuple[tuple[float, float], ...]
    covariance_deg2: tuple[np.ndarray, ...]
    sample_covariance: np.ndarray
    sensor_reliability: np.ndarray
    runtime_ms: float
    measurement_errors_deg: tuple[float, ...]
    health_tail_mean: float
    fault_mask: np.ndarray


@dataclass
class SequenceResult:
    frame_records: list[dict[str, Any]]
    packet_records: list[dict[str, Any]]
    method_summary: list[dict[str, Any]]
    diagnostics: dict[str, Any]


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


def _scanner_from_config(
    array: RectangularArray,
    config: dict[str, Any],
) -> tuple[RectangularArray, MusicGridScanner]:
    smoothing = config["perception"]["spatial_smoothing"]
    subarray = RectangularArray(
        int(smoothing["subarray_nx"]),
        int(smoothing["subarray_ny"]),
        array.frequency_hz,
        dx_m=array.dx_m,
        dy_m=array.dy_m,
    )
    scan = config["perception"]["scan"]
    theta = np.arange(
        float(scan["theta_min_deg"]),
        float(scan["theta_max_deg"]) + 0.5 * float(scan["theta_step_deg"]),
        float(scan["theta_step_deg"]),
    )
    phi = np.arange(
        float(scan["phi_min_deg"]),
        float(scan["phi_max_deg"]) + 0.5 * float(scan["phi_step_deg"]),
        float(scan["phi_step_deg"]),
    )
    return subarray, MusicGridScanner(subarray, theta, phi)


def _initial_centers(config: dict[str, Any]) -> tuple[tuple[float, float], ...]:
    return tuple(
        (float(value[0]), float(value[1]))
        for value in config["perception"]["initial_prior_centers_deg"]
    )


def _tracker(config: dict[str, Any]) -> MultiTargetKalmanTracker:
    cfg = config["perception"]["tracker"]
    return MultiTargetKalmanTracker(
        _initial_centers(config),
        initial_position_std_deg=float(cfg["initial_position_std_deg"]),
        initial_velocity_std_deg_per_frame=float(cfg["initial_velocity_std_deg_per_frame"]),
        process_acceleration_std_deg_per_frame2=float(
            cfg["process_acceleration_std_deg_per_frame2"]
        ),
        initial_time=0.0,
    )


def _trajectory(
    config: dict[str, Any],
    n_frames: int,
    speed_scale: float,
) -> np.ndarray:
    """Return true interferer directions with shape (frames, K, 2)."""
    if n_frames < 1 or speed_scale <= 0:
        raise ValueError("n_frames and speed_scale must be positive")
    output = np.empty((n_frames, len(config["scenario"]["interferers"]), 2), dtype=float)
    for frame in range(n_frames):
        tau = float(frame) * float(speed_scale)
        for index, source in enumerate(config["scenario"]["interferers"]):
            theta = (
                float(source["theta_start_deg"])
                + float(source["theta_rate_deg_per_frame"]) * tau
                + float(source["theta_sinusoid_amplitude_deg"])
                * math.sin(
                    float(source["theta_sinusoid_frequency_rad_per_frame"]) * tau
                    + float(source["theta_phase_rad"])
                )
            )
            phi = (
                float(source["phi_start_deg"])
                + float(source["phi_rate_deg_per_frame"]) * tau
                + float(source["phi_sinusoid_amplitude_deg"])
                * math.sin(
                    float(source["phi_sinusoid_frequency_rad_per_frame"]) * tau
                    + float(source["phi_phase_rad"])
                )
            )
            output[frame, index] = (np.clip(theta, 0.1, 89.9), phi)
    return output


def _complex_normal(rng: np.random.Generator, shape: tuple[int, ...]) -> np.ndarray:
    return (rng.standard_normal(shape) + 1j * rng.standard_normal(shape)) / np.sqrt(2.0)


def _fault_count_for_frame(
    frame: int,
    n_frames: int,
    final_fault_count: int,
    config: dict[str, Any],
) -> int:
    if final_fault_count <= 0:
        return 0
    observation = config["observation"]
    first_onset = int(round(float(observation["first_fault_onset_fraction"]) * (n_frames - 1)))
    second_onset = int(round(float(observation["second_fault_onset_fraction"]) * (n_frames - 1)))
    first_group = int(math.ceil(final_fault_count / 2.0))
    if frame < first_onset:
        return 0
    if frame < second_onset:
        return first_group
    return final_fault_count


def _draw_trial_hardware(
    array: RectangularArray,
    config: dict[str, Any],
    rng: np.random.Generator,
    final_fault_count: int,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    observation = config["observation"]
    base_gains = 10.0 ** (
        rng.normal(0.0, float(observation["sensor_gain_std_db"]), array.n_elements) / 20.0
    ) * np.exp(
        1j
        * np.deg2rad(
            rng.normal(0.0, float(observation["sensor_phase_std_deg"]), array.n_elements)
        )
    )
    candidates = np.asarray(observation["fault_candidate_indices"], dtype=int)
    if final_fault_count > candidates.size:
        raise ValueError("fault count exceeds configured candidate channels")
    if final_fault_count:
        fault_indices = rng.choice(candidates, size=final_fault_count, replace=False)
    else:
        fault_indices = np.empty(0, dtype=int)
    fault_phases = np.exp(
        1j
        * np.deg2rad(
            rng.normal(0.0, float(observation["fault_phase_std_deg"]), final_fault_count)
        )
    )
    return base_gains, np.asarray(fault_indices, dtype=int), fault_phases


def _simulate_frame(
    array: RectangularArray,
    config: dict[str, Any],
    directions_deg: np.ndarray,
    *,
    frame_seed: int,
    base_gains: np.ndarray,
    fault_indices: np.ndarray,
    fault_phases: np.ndarray,
    active_fault_count: int,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    rng = np.random.default_rng(int(frame_seed))
    observation = config["observation"]
    scenario = config["scenario"]
    snapshots = int(observation["snapshots"])
    noise_power = float(observation["noise_power"])
    gains = np.asarray(base_gains, complex).copy()
    fault_mask = np.zeros(array.n_elements, dtype=bool)
    if active_fault_count:
        active = fault_indices[:active_fault_count]
        fault_mask[active] = True
        gains[active] *= 10.0 ** (float(observation["fault_gain_db"]) / 20.0)
        gains[active] *= fault_phases[:active_fault_count]

    desired = scenario["desired"]
    desired_power = 10.0 ** (float(desired["snr_db"]) / 10.0)
    desired_steering = array.steering_vector(
        float(desired["theta_deg"]), float(desired["phi_deg"])
    )
    x = (
        gains[:, None]
        * desired_steering[:, None]
        * np.sqrt(desired_power)
        * _complex_normal(rng, (1, snapshots))
    )
    for direction, source in zip(directions_deg, scenario["interferers"]):
        power = 10.0 ** (float(source["inr_db"]) / 10.0)
        x += (
            gains[:, None]
            * array.steering_vector(float(direction[0]), float(direction[1]))[:, None]
            * np.sqrt(power)
            * _complex_normal(rng, (1, snapshots))
        )
    x += np.sqrt(noise_power) * _complex_normal(rng, (array.n_elements, snapshots))
    if active_fault_count:
        active = fault_indices[:active_fault_count]
        extra_power = 10.0 ** (float(observation["fault_extra_noise_db"]) / 10.0)
        x[active] += np.sqrt(extra_power) * _complex_normal(
            rng, (active_fault_count, snapshots)
        )
    return x, gains, fault_mask


def _associate_to_priors(
    estimates: Sequence[tuple[float, float]],
    priors: Sequence[tuple[float, float]],
) -> tuple[tuple[float, float], ...]:
    estimates = tuple((float(a), float(b)) for a, b in estimates)
    priors = tuple((float(a), float(b)) for a, b in priors)
    if len(estimates) != len(priors):
        raise ValueError("estimate and prior counts must match")
    cost = np.empty((len(priors), len(estimates)), dtype=float)
    for i, prior in enumerate(priors):
        for j, estimate in enumerate(estimates):
            cost[i, j] = angular_error_deg(estimate, prior)
    rows, columns = linear_sum_assignment(cost)
    ordered: list[tuple[float, float] | None] = [None] * len(priors)
    for row, column in zip(rows, columns):
        ordered[row] = estimates[column]
    return tuple(value for value in ordered if value is not None)


def _estimate_packet(
    x: np.ndarray,
    array: RectangularArray,
    subarray: RectangularArray,
    scanner: MusicGridScanner,
    config: dict[str, Any],
    priors: Sequence[tuple[float, float]],
    true_directions: Sequence[tuple[float, float]],
    *,
    acquisition_frame: int,
    ready_frame: int,
    fault_mask: np.ndarray,
) -> MeasurementPacket:
    perception = config["perception"]
    smoothing = perception["spatial_smoothing"]
    pawr = perception["pawr"]
    scan = perception["scan"]
    uncertainty = perception["uncertainty"]
    start = time.perf_counter()
    result = pawr_estimate(
        x,
        array,
        scanner,
        len(priors),
        int(smoothing["subarray_nx"]),
        int(smoothing["subarray_ny"]),
        priors,
        prior_sigma_deg=float(pawr["prior_sigma_deg"]),
        prior_strength=float(pawr["prior_strength"]),
        selection_exponent=float(pawr["selection_exponent"]),
        search_radius_sigma=float(pawr["search_radius_sigma"]),
        structure_blend=float(pawr["structure_blend"]),
        forward_backward=bool(pawr["forward_backward"]),
        health_window=int(pawr["health_window"]),
        health_tuning=float(pawr["health_tuning"]),
        reliability_floor=float(pawr["reliability_floor"]),
        weight_exponent=float(pawr["weight_exponent"]),
        weight_floor_fraction=float(pawr["weight_floor_fraction"]),
    )
    # For independent moving emitters, use the PAWR health-weighted analysis
    # covariance but select unconstrained MUSIC peaks before track association.
    raw_estimates = refine_music_peaks(
        result.analysis_covariance,
        scanner,
        len(priors),
        local_radius_deg=float(scan["local_refinement_radius_deg"]),
        min_separation_deg=float(scan["min_peak_separation_deg"]),
    )
    estimates = _associate_to_priors(raw_estimates, priors)

    health = np.asarray(result.sensor_reliability, dtype=float).reshape(-1)
    tail_count = max(
        1,
        int(math.ceil(float(uncertainty["health_tail_fraction"]) * health.size)),
    )
    health_tail_mean = float(np.mean(np.sort(health)[:tail_count]))
    inflation = 1.0 + float(uncertainty["health_covariance_inflation"]) * (
        1.0 - health_tail_mean
    )
    covariances: list[np.ndarray] = []
    for estimate in estimates:
        local = local_music_posterior_covariance(
            result.analysis_covariance,
            subarray,
            estimate,
            len(priors),
            radius_deg=float(uncertainty["local_radius_deg"]),
            grid_step_deg=float(uncertainty["local_grid_step_deg"]),
            temperature=float(uncertainty["temperature"]),
            std_floor_deg=float(uncertainty["std_floor_deg"]),
            std_ceiling_deg=float(uncertainty["std_ceiling_deg"]),
        )
        covariances.append(local.covariance_deg2 * inflation)
    runtime_ms = 1000.0 * (time.perf_counter() - start)
    errors = tuple(
        angular_error_deg(estimate, truth)
        for estimate, truth in zip(estimates, true_directions)
    )
    return MeasurementPacket(
        acquisition_frame=int(acquisition_frame),
        ready_frame=int(ready_frame),
        estimates_deg=tuple(estimates),
        covariance_deg2=tuple(covariances),
        sample_covariance=covariance_matrix(x),
        sensor_reliability=health,
        runtime_ms=float(runtime_ms),
        measurement_errors_deg=errors,
        health_tail_mean=health_tail_mean,
        fault_mask=np.asarray(fault_mask, bool).copy(),
    )


def _desired_direction(config: dict[str, Any]) -> tuple[float, float]:
    desired = config["scenario"]["desired"]
    return float(desired["theta_deg"]), float(desired["phi_deg"])


def _source_powers(config: dict[str, Any]) -> tuple[float, tuple[float, ...], float]:
    desired_power = 10.0 ** (float(config["scenario"]["desired"]["snr_db"]) / 10.0)
    interferer_powers = tuple(
        10.0 ** (float(source["inr_db"]) / 10.0)
        for source in config["scenario"]["interferers"]
    )
    return desired_power, interferer_powers, float(config["observation"]["noise_power"])


def _fixed_sectors(
    array: RectangularArray,
    config: dict[str, Any],
    centers: Sequence[tuple[float, float]],
) -> list[Any]:
    protection = config["protection"]
    variance = float(protection["fixed_sector_std_deg"]) ** 2
    return [
        build_covariance_confidence_sector(
            array,
            center,
            np.eye(2) * variance,
            confidence_radius=float(protection["confidence_radius"]),
            grid_step_deg=float(protection["confidence_grid_step_deg"]),
            min_half_width_deg=float(protection["fixed_min_half_width_deg"]),
            max_half_width_deg=float(protection["max_half_width_deg"]),
        )
        for center in centers
    ]


def _prediction_sectors(
    array: RectangularArray,
    config: dict[str, Any],
    predictions: Sequence[TrackPrediction],
) -> list[Any]:
    protection = config["protection"]
    return [
        build_covariance_confidence_sector(
            array,
            prediction.mean_deg,
            prediction.covariance_deg2,
            confidence_radius=float(protection["confidence_radius"]),
            grid_step_deg=float(protection["confidence_grid_step_deg"]),
            min_half_width_deg=float(protection["min_half_width_deg"]),
            max_half_width_deg=float(protection["max_half_width_deg"]),
        )
        for prediction in predictions
    ]


def _measurement_covariance_sectors(
    array: RectangularArray,
    config: dict[str, Any],
    packet: MeasurementPacket,
) -> list[Any]:
    protection = config["protection"]
    return [
        build_covariance_confidence_sector(
            array,
            center,
            covariance,
            confidence_radius=float(protection["confidence_radius"]),
            grid_step_deg=float(protection["confidence_grid_step_deg"]),
            min_half_width_deg=float(protection["min_half_width_deg"]),
            max_half_width_deg=float(protection["max_half_width_deg"]),
        )
        for center, covariance in zip(packet.estimates_deg, packet.covariance_deg2)
    ]


def _hybrid(
    covariance: np.ndarray,
    desired_steering: np.ndarray,
    sectors: Sequence[Any],
    config: dict[str, Any],
) -> MultiHybridNullResult:
    protection = config["protection"]
    return multi_confidence_region_hybrid_null_weights(
        covariance,
        desired_steering,
        sectors,
        loading_factor=float(protection["diagonal_loading"]),
        energy_threshold=float(protection["energy_threshold"]),
        max_rank_per_sector=int(protection["max_rank_per_sector"]),
        max_total_rank=int(protection["max_total_rank"]),
        soft_strength=float(protection["soft_strength"]),
        white_noise_gain_floor_db=float(protection["white_noise_gain_floor_db"]),
        condition_limit=float(protection["condition_limit"]),
    )


def _safe_timed_design(
    builder: Callable[[], tuple[np.ndarray, dict[str, Any]]],
    fallback: np.ndarray,
) -> tuple[np.ndarray, float, dict[str, Any]]:
    start = time.perf_counter()
    try:
        weights, metadata = builder()
        weights = np.asarray(weights, complex)
        if not np.all(np.isfinite(weights)):
            raise np.linalg.LinAlgError("non-finite beamformer weights")
        status = "ok"
    except (np.linalg.LinAlgError, ValueError, FloatingPointError) as exc:
        weights = np.asarray(fallback, complex)
        metadata = {"fallback_reason": str(exc)}
        status = "fallback"
    runtime_ms = 1000.0 * (time.perf_counter() - start)
    metadata = dict(metadata)
    metadata["status"] = status
    return weights, runtime_ms, metadata


def _method_summary(
    frame_records: Sequence[dict[str, Any]],
    threshold_db: float,
) -> list[dict[str, Any]]:
    summary: list[dict[str, Any]] = []
    for method in METHOD_ORDER:
        rows = [row for row in frame_records if row["method"] == method]
        if not rows:
            continue
        sinr = np.asarray([float(row["output_sinr_db"]) for row in rows])
        response = np.asarray([float(row["worst_interferer_response_db"]) for row in rows])
        runtime = np.asarray([float(row["design_runtime_ms"]) for row in rows])
        wng = np.asarray([float(row["white_noise_gain_db"]) for row in rows])
        summary.append(
            {
                "method": method,
                "mean_output_sinr_db": float(np.mean(sinr)),
                "median_output_sinr_db": float(np.median(sinr)),
                "p05_output_sinr_db": float(np.quantile(sinr, 0.05)),
                "minimum_output_sinr_db": float(np.min(sinr)),
                "protection_availability": float(np.mean(sinr >= threshold_db)),
                "mean_worst_response_db": float(np.mean(response)),
                "p90_worst_response_db": float(np.quantile(response, 0.90)),
                "median_design_runtime_ms": float(np.median(runtime)),
                "median_white_noise_gain_db": float(np.median(wng)),
            }
        )
    return summary


def _run_sequence(
    array: RectangularArray,
    subarray: RectangularArray,
    scanner: MusicGridScanner,
    config: dict[str, Any],
    *,
    seed: int,
    n_frames: int,
    update_interval: int,
    latency: int,
    final_fault_count: int,
    speed_scale: float,
    diagnostics: bool = False,
    include_ablation: bool = False,
) -> SequenceResult:
    if n_frames < 2 or update_interval < 1 or latency < 0 or final_fault_count < 0:
        raise ValueError("invalid sequence configuration")
    rng = np.random.default_rng(int(seed))
    trajectories = _trajectory(config, n_frames, speed_scale)
    base_gains, fault_indices, fault_phases = _draw_trial_hardware(
        array, config, rng, final_fault_count
    )
    perception_tracker = _tracker(config)
    protection_tracker = _tracker(config)
    packets: list[MeasurementPacket] = []
    latest_packet: MeasurementPacket | None = None
    static_weights: np.ndarray | None = None
    previous_weights: dict[str, np.ndarray] = {}
    frame_records: list[dict[str, Any]] = []
    packet_records: list[dict[str, Any]] = []
    threshold_db = float(config["protection"]["protection_sinr_threshold_db"])
    desired_direction = _desired_direction(config)
    desired_nominal = array.steering_vector(*desired_direction)
    desired_power, interferer_powers, noise_power = _source_powers(config)
    loading = float(config["protection"]["diagonal_loading"])
    tracker_gate = float(config["perception"]["tracker"]["gate_mahalanobis_sq"])

    diag: dict[str, Any] = {
        "trajectories_deg": trajectories,
        "packet_frames": [],
        "packet_ready_frames": [],
        "packet_estimates_deg": [],
        "packet_covariance_deg2": [],
        "packet_health": [],
        "packet_fault_masks": [],
        "predicted_centers_deg": [],
        "predicted_covariance_deg2": [],
        "tracking_error_deg": [],
        "sector_half_width_deg": [],
        "selected_rank": [],
        "weights": {method: [] for method in METHOD_ORDER},
        "gains": [],
        "fault_masks": [],
        "actual_interferer_response_db": {method: [] for method in METHOD_ORDER},
    }

    # Warm numerical kernels before timing the first acquisition.
    np.linalg.eigh(np.eye(subarray.n_elements))

    for frame in range(n_frames):
        active_fault_count = _fault_count_for_frame(
            frame, n_frames, final_fault_count, config
        )
        frame_seed = int(rng.integers(0, np.iinfo(np.int32).max))
        x, gains, fault_mask = _simulate_frame(
            array,
            config,
            trajectories[frame],
            frame_seed=frame_seed,
            base_gains=base_gains,
            fault_indices=fault_indices,
            fault_phases=fault_phases,
            active_fault_count=active_fault_count,
        )
        current_covariance = covariance_matrix(x)

        if frame % update_interval == 0:
            priors = tuple(pred.mean_deg for pred in perception_tracker.predict(frame))
            ready_frame = frame if frame == 0 else frame + latency
            packet = _estimate_packet(
                x,
                array,
                subarray,
                scanner,
                config,
                priors,
                tuple(tuple(value) for value in trajectories[frame]),
                acquisition_frame=frame,
                ready_frame=ready_frame,
                fault_mask=fault_mask,
            )
            perception_tracker.update(
                packet.estimates_deg,
                packet.covariance_deg2,
                measurement_time=float(frame),
                gate_mahalanobis_sq=tracker_gate,
            )
            packets.append(packet)
            packet_records.append(
                {
                    "acquisition_frame": frame,
                    "ready_frame": ready_frame,
                    "latency_frames": ready_frame - frame,
                    "mean_measurement_error_deg": float(
                        np.mean(packet.measurement_errors_deg)
                    ),
                    "max_measurement_error_deg": float(
                        np.max(packet.measurement_errors_deg)
                    ),
                    "runtime_ms": packet.runtime_ms,
                    "health_tail_mean": packet.health_tail_mean,
                    "active_fault_count": int(np.sum(packet.fault_mask)),
                    "fault_detection_recall": float(
                        np.mean(packet.sensor_reliability[packet.fault_mask] < 0.5)
                    )
                    if np.any(packet.fault_mask)
                    else math.nan,
                    "healthy_false_alarm_rate": float(
                        np.mean(packet.sensor_reliability[~packet.fault_mask] < 0.5)
                    ),
                }
            )

        arrived = [packet for packet in packets if packet.ready_frame == frame]
        for packet in arrived:
            latest_packet = packet
            protection_tracker.update(
                packet.estimates_deg,
                packet.covariance_deg2,
                measurement_time=float(packet.acquisition_frame),
                gate_mahalanobis_sq=tracker_gate,
            )

        if latest_packet is None:
            # This only applies to malformed custom schedules because frame 0
            # is deliberately delivered immediately.
            latest_covariance = current_covariance
            latest_centers = _initial_centers(config)
            latest_health = np.ones(array.n_elements)
        else:
            latest_covariance = latest_packet.sample_covariance
            latest_centers = latest_packet.estimates_deg
            latest_health = latest_packet.sensor_reliability

        if static_weights is None:
            static_weights = multi_point_lcmv_weights(
                latest_covariance,
                desired_nominal,
                array,
                latest_centers,
                loading_factor=loading,
            )

        predictions = protection_tracker.predict(float(frame))
        predicted_centers = tuple(pred.mean_deg for pred in predictions)
        fixed_sectors = _fixed_sectors(array, config, latest_centers)
        predictive_sectors = _prediction_sectors(array, config, predictions)
        health_covariance = fault_aware_covariance(
            latest_covariance,
            latest_health,
            penalty_strength=float(config["protection"]["fault_penalty_strength"]),
        )

        conventional_fallback = desired_nominal / np.vdot(desired_nominal, desired_nominal)
        designs: dict[str, tuple[np.ndarray, float, dict[str, Any]]] = {}
        designs[METHOD_STATIC] = (
            static_weights,
            0.0,
            {"status": "held", "selected_rank": 0},
        )
        designs[METHOD_DELAYED] = _safe_timed_design(
            lambda: (
                multi_point_lcmv_weights(
                    latest_covariance,
                    desired_nominal,
                    array,
                    latest_centers,
                    loading_factor=loading,
                ),
                {"selected_rank": 0},
            ),
            previous_weights.get(METHOD_DELAYED, conventional_fallback),
        )
        designs[METHOD_PREDICTIVE] = _safe_timed_design(
            lambda: (
                multi_point_lcmv_weights(
                    latest_covariance,
                    desired_nominal,
                    array,
                    predicted_centers,
                    loading_factor=loading,
                ),
                {"selected_rank": 0},
            ),
            previous_weights.get(METHOD_PREDICTIVE, conventional_fallback),
        )
        designs[METHOD_FIXED] = _safe_timed_design(
            lambda: (
                (result := _hybrid(
                    latest_covariance, desired_nominal, fixed_sectors, config
                )).weights,
                {
                    "selected_rank": result.selected_rank,
                    "requested_rank": result.requested_rank,
                    "mode": result.mode,
                },
            ),
            previous_weights.get(METHOD_FIXED, conventional_fallback),
        )
        designs[METHOD_PROPOSED] = _safe_timed_design(
            lambda: (
                (result := _hybrid(
                    health_covariance, desired_nominal, predictive_sectors, config
                )).weights,
                {
                    "selected_rank": result.selected_rank,
                    "requested_rank": result.requested_rank,
                    "mode": result.mode,
                    "constraint_condition": result.constraint_condition,
                },
            ),
            previous_weights.get(METHOD_PROPOSED, conventional_fallback),
        )
        previous_weights.update({method: value[0] for method, value in designs.items()})

        actual_desired = gains * desired_nominal
        actual_interferers = [
            gains * array.steering_vector(float(direction[0]), float(direction[1]))
            for direction in trajectories[frame]
        ]
        tracking_errors = np.asarray(
            [
                angular_error_deg(prediction.mean_deg, tuple(truth))
                for prediction, truth in zip(predictions, trajectories[frame])
            ],
            dtype=float,
        )
        sector_width = float(
            np.mean(
                [
                    math.sqrt(float(sector.half_width_deg[0] * sector.half_width_deg[1]))
                    for sector in predictive_sectors
                ]
            )
        )

        for method in METHOD_ORDER:
            weights, design_runtime_ms, metadata = designs[method]
            output_sinr = analytic_output_sinr_multi_db(
                weights,
                actual_desired,
                actual_interferers,
                desired_power=desired_power,
                interferer_powers=interferer_powers,
                noise_power=noise_power,
            )
            response = worst_interferer_response_db(
                weights,
                actual_desired,
                actual_interferers,
            )
            frame_records.append(
                {
                    "frame": frame,
                    "method": method,
                    "output_sinr_db": output_sinr,
                    "protected": int(output_sinr >= threshold_db),
                    "worst_interferer_response_db": response,
                    "white_noise_gain_db": white_noise_gain_db(weights),
                    "design_runtime_ms": design_runtime_ms,
                    "selected_rank": int(metadata.get("selected_rank", 0)),
                    "status": str(metadata.get("status", "ok")),
                    "active_fault_count": active_fault_count,
                    "latest_measurement_age_frames": int(
                        frame - latest_packet.acquisition_frame
                    )
                    if latest_packet is not None
                    else frame,
                    "mean_tracking_error_deg": float(np.mean(tracking_errors)),
                    "max_tracking_error_deg": float(np.max(tracking_errors)),
                    "mean_sector_half_width_deg": sector_width,
                }
            )
            if diagnostics:
                diag["weights"][method].append(np.asarray(weights, complex))
                diag["actual_interferer_response_db"][method].append(response)

        if include_ablation and latest_packet is not None:
            ablation_designs: dict[str, tuple[np.ndarray, float, dict[str, Any]]] = {
                ABLATION_PRED_POINT: designs[METHOD_PREDICTIVE],
                ABLATION_PRED_FIXED: _safe_timed_design(
                    lambda: (
                        (result := _hybrid(
                            latest_covariance,
                            desired_nominal,
                            _fixed_sectors(array, config, predicted_centers),
                            config,
                        )).weights,
                        {"selected_rank": result.selected_rank},
                    ),
                    designs[METHOD_PREDICTIVE][0],
                ),
                ABLATION_COV_DELAYED: _safe_timed_design(
                    lambda: (
                        (result := _hybrid(
                            latest_covariance,
                            desired_nominal,
                            _measurement_covariance_sectors(
                                array, config, latest_packet
                            ),
                            config,
                        )).weights,
                        {"selected_rank": result.selected_rank},
                    ),
                    designs[METHOD_FIXED][0],
                ),
                ABLATION_NO_HEALTH: _safe_timed_design(
                    lambda: (
                        (result := _hybrid(
                            latest_covariance,
                            desired_nominal,
                            predictive_sectors,
                            config,
                        )).weights,
                        {"selected_rank": result.selected_rank},
                    ),
                    designs[METHOD_PROPOSED][0],
                ),
                ABLATION_FULL: designs[METHOD_PROPOSED],
            }
            for label, (weights, design_runtime_ms, metadata) in ablation_designs.items():
                output_sinr = analytic_output_sinr_multi_db(
                    weights,
                    actual_desired,
                    actual_interferers,
                    desired_power=desired_power,
                    interferer_powers=interferer_powers,
                    noise_power=noise_power,
                )
                frame_records.append(
                    {
                        "frame": frame,
                        "method": f"ABLATION::{label}",
                        "output_sinr_db": output_sinr,
                        "protected": int(output_sinr >= threshold_db),
                        "worst_interferer_response_db": worst_interferer_response_db(
                            weights, actual_desired, actual_interferers
                        ),
                        "white_noise_gain_db": white_noise_gain_db(weights),
                        "design_runtime_ms": design_runtime_ms,
                        "selected_rank": int(metadata.get("selected_rank", 0)),
                        "status": str(metadata.get("status", "ok")),
                        "active_fault_count": active_fault_count,
                        "latest_measurement_age_frames": int(
                            frame - latest_packet.acquisition_frame
                        ),
                        "mean_tracking_error_deg": float(np.mean(tracking_errors)),
                        "max_tracking_error_deg": float(np.max(tracking_errors)),
                        "mean_sector_half_width_deg": sector_width,
                    }
                )

        if diagnostics:
            diag["predicted_centers_deg"].append(
                np.asarray([prediction.mean_deg for prediction in predictions], dtype=float)
            )
            diag["predicted_covariance_deg2"].append(
                np.asarray([prediction.covariance_deg2 for prediction in predictions])
            )
            diag["tracking_error_deg"].append(tracking_errors)
            diag["sector_half_width_deg"].append(
                np.asarray([sector.half_width_deg for sector in predictive_sectors])
            )
            diag["selected_rank"].append(
                int(designs[METHOD_PROPOSED][2].get("selected_rank", 0))
            )
            diag["gains"].append(gains)
            diag["fault_masks"].append(fault_mask)

    if diagnostics:
        for packet in packets:
            diag["packet_frames"].append(packet.acquisition_frame)
            diag["packet_ready_frames"].append(packet.ready_frame)
            diag["packet_estimates_deg"].append(np.asarray(packet.estimates_deg))
            diag["packet_covariance_deg2"].append(np.asarray(packet.covariance_deg2))
            diag["packet_health"].append(packet.sensor_reliability)
            diag["packet_fault_masks"].append(packet.fault_mask)
        for key in [
            "packet_frames",
            "packet_ready_frames",
            "packet_estimates_deg",
            "packet_covariance_deg2",
            "packet_health",
            "packet_fault_masks",
            "predicted_centers_deg",
            "predicted_covariance_deg2",
            "tracking_error_deg",
            "sector_half_width_deg",
            "selected_rank",
            "gains",
            "fault_masks",
        ]:
            diag[key] = np.asarray(diag[key])
        for method in METHOD_ORDER:
            diag["weights"][method] = np.asarray(diag["weights"][method])
            diag["actual_interferer_response_db"][method] = np.asarray(
                diag["actual_interferer_response_db"][method]
            )

    return SequenceResult(
        frame_records=frame_records,
        packet_records=packet_records,
        method_summary=_method_summary(frame_records, threshold_db),
        diagnostics=diag,
    )


def _aggregate_sequence(
    result: SequenceResult,
    *,
    sweep: str,
    x_value: float,
    trial: int,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    packet_error = np.asarray(
        [float(row["mean_measurement_error_deg"]) for row in result.packet_records],
        dtype=float,
    )
    perception_runtime = np.asarray(
        [float(row["runtime_ms"]) for row in result.packet_records], dtype=float
    )
    fault_recall = np.asarray(
        [float(row["fault_detection_recall"]) for row in result.packet_records],
        dtype=float,
    )
    for row in result.method_summary:
        item = dict(row)
        item.update(
            {
                "sweep": sweep,
                "x_value": float(x_value),
                "trial": int(trial),
                "mean_measurement_error_deg": float(np.mean(packet_error))
                if packet_error.size
                else math.nan,
                "median_perception_runtime_ms": float(np.median(perception_runtime))
                if perception_runtime.size
                else math.nan,
                "fault_detection_recall": float(np.nanmean(fault_recall))
                if np.any(np.isfinite(fault_recall))
                else math.nan,
            }
        )
        rows.append(item)
    return rows


def _summarize_sweep(
    records: Sequence[dict[str, Any]],
    confidence: float,
) -> list[dict[str, Any]]:
    groups = sorted(
        {
            (str(row["sweep"]), float(row["x_value"]), str(row["method"]))
            for row in records
        }
    )
    output: list[dict[str, Any]] = []
    metrics = [
        "mean_output_sinr_db",
        "p05_output_sinr_db",
        "protection_availability",
        "mean_worst_response_db",
        "median_design_runtime_ms",
        "mean_measurement_error_deg",
        "median_perception_runtime_ms",
        "fault_detection_recall",
    ]
    for sweep, x_value, method in groups:
        subset = [
            row
            for row in records
            if row["sweep"] == sweep
            and float(row["x_value"]) == x_value
            and row["method"] == method
        ]
        summary: dict[str, Any] = {
            "sweep": sweep,
            "x_value": x_value,
            "method": method,
            "n_trials": len(subset),
        }
        for metric in metrics:
            values = np.asarray([float(row[metric]) for row in subset], dtype=float)
            mean, low, high = mean_confidence_interval(values, confidence)
            summary[f"{metric}_mean"] = mean
            summary[f"{metric}_ci_low"] = low
            summary[f"{metric}_ci_high"] = high
        output.append(summary)
    return output


def _run_standard_sweeps(
    array: RectangularArray,
    subarray: RectangularArray,
    scanner: MusicGridScanner,
    config: dict[str, Any],
    progress: Callable[[str], None],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    mc = config["monte_carlo"]
    trials = int(mc["trials"])
    frames = int(mc["frames"])
    base_seed = int(config["seed"]) + 50_000
    records: list[dict[str, Any]] = []
    specifications = [
        (
            "latency",
            list(mc["latency_sweep_frames"]),
            lambda value: {
                "update_interval": int(mc["base_update_interval_frames"]),
                "latency": int(value),
                "fault_count": int(mc["base_fault_count"]),
                "speed_scale": float(mc["base_speed_scale"]),
            },
        ),
        (
            "update_interval",
            list(mc["update_interval_sweep_frames"]),
            lambda value: {
                "update_interval": int(value),
                "latency": int(mc["base_latency_frames"]),
                "fault_count": int(mc["base_fault_count"]),
                "speed_scale": float(mc["base_speed_scale"]),
            },
        ),
        (
            "fault_count",
            list(mc["fault_count_sweep"]),
            lambda value: {
                "update_interval": int(mc["base_update_interval_frames"]),
                "latency": int(mc["base_latency_frames"]),
                "fault_count": int(value),
                "speed_scale": float(mc["base_speed_scale"]),
            },
        ),
        (
            "speed_scale",
            list(mc["speed_scale_sweep"]),
            lambda value: {
                "update_interval": int(mc["base_update_interval_frames"]),
                "latency": int(mc["base_latency_frames"]),
                "fault_count": int(mc["base_fault_count"]),
                "speed_scale": float(value),
            },
        ),
    ]
    run_index = 0
    total = sum(len(values) * trials for _, values, _ in specifications)
    for sweep_index, (sweep, values, builder) in enumerate(specifications):
        for value_index, value in enumerate(values):
            for trial in range(trials):
                run_index += 1
                parameters = builder(value)
                seed = (
                    base_seed
                    + sweep_index * 1_000_000
                    + value_index * 10_000
                    + trial * 101
                )
                sequence = _run_sequence(
                    array,
                    subarray,
                    scanner,
                    config,
                    seed=seed,
                    n_frames=frames,
                    update_interval=parameters["update_interval"],
                    latency=parameters["latency"],
                    final_fault_count=parameters["fault_count"],
                    speed_scale=parameters["speed_scale"],
                )
                records.extend(
                    _aggregate_sequence(
                        sequence,
                        sweep=sweep,
                        x_value=float(value),
                        trial=trial,
                    )
                )
                if run_index == 1 or run_index % max(1, total // 12) == 0:
                    progress(f"Monte Carlo {run_index}/{total}: {sweep}={value}")
    summary = _summarize_sweep(records, float(mc["confidence"]))
    return records, summary


def _run_ablation(
    array: RectangularArray,
    subarray: RectangularArray,
    scanner: MusicGridScanner,
    config: dict[str, Any],
    progress: Callable[[str], None],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    mc = config["monte_carlo"]
    trials = int(mc["ablation_trials"])
    records: list[dict[str, Any]] = []
    for trial in range(trials):
        sequence = _run_sequence(
            array,
            subarray,
            scanner,
            config,
            seed=int(config["seed"]) + 9_000_000 + trial * 313,
            n_frames=int(mc["frames"]),
            update_interval=int(mc["base_update_interval_frames"]),
            latency=int(mc["base_latency_frames"]),
            final_fault_count=int(mc["base_fault_count"]),
            speed_scale=float(mc["base_speed_scale"]),
            include_ablation=True,
        )
        for label in ABLATION_ORDER:
            rows = [
                row
                for row in sequence.frame_records
                if row["method"] == f"ABLATION::{label}"
            ]
            sinr = np.asarray([float(row["output_sinr_db"]) for row in rows])
            records.append(
                {
                    "trial": trial,
                    "method": label,
                    "mean_output_sinr_db": float(np.mean(sinr)),
                    "p05_output_sinr_db": float(np.quantile(sinr, 0.05)),
                    "protection_availability": float(
                        np.mean(
                            sinr
                            >= float(
                                config["protection"][
                                    "protection_sinr_threshold_db"
                                ]
                            )
                        )
                    ),
                }
            )
        if trial == 0 or (trial + 1) % max(1, trials // 4) == 0:
            progress(f"Ablation {trial + 1}/{trials}")
    summary: list[dict[str, Any]] = []
    for label in ABLATION_ORDER:
        subset = [row for row in records if row["method"] == label]
        values = np.asarray([float(row["mean_output_sinr_db"]) for row in subset])
        mean, low, high = mean_confidence_interval(
            values, float(mc["confidence"])
        )
        availability = np.asarray(
            [float(row["protection_availability"]) for row in subset]
        )
        availability_mean, availability_low, availability_high = mean_confidence_interval(
            availability, float(mc["confidence"])
        )
        summary.append(
            {
                "method": label,
                "mean_output_sinr_db": mean,
                "sinr_ci_low_db": low,
                "sinr_ci_high_db": high,
                "protection_availability": availability_mean,
                "availability_ci_low": availability_low,
                "availability_ci_high": availability_high,
                "n_trials": len(subset),
            }
        )
    return records, summary


def _write_csv(path: Path, rows: Sequence[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    fields: list[str] = []
    for row in rows:
        for key in row:
            if key not in fields:
                fields.append(key)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def _json_ready(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _json_ready(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_ready(item) for item in value]
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, (np.floating, np.integer)):
        return value.item()
    if isinstance(value, complex):
        return {"real": value.real, "imag": value.imag}
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def _select_summary(
    summary: Sequence[dict[str, Any]],
    sweep: str,
    x_value: float,
    method: str,
) -> dict[str, Any]:
    for row in summary:
        if (
            row["sweep"] == sweep
            and float(row["x_value"]) == float(x_value)
            and row["method"] == method
        ):
            return row
    raise KeyError((sweep, x_value, method))


def _paired_statistics(
    records: Sequence[dict[str, Any]],
    *,
    latency_value: float,
) -> dict[str, Any]:
    subset = [
        row
        for row in records
        if row["sweep"] == "latency" and float(row["x_value"]) == latency_value
    ]
    proposed = {
        int(row["trial"]): float(row["mean_output_sinr_db"])
        for row in subset
        if row["method"] == METHOD_PROPOSED
    }
    output: dict[str, Any] = {}
    for baseline in [METHOD_DELAYED, METHOD_PREDICTIVE, METHOD_FIXED]:
        baseline_values = {
            int(row["trial"]): float(row["mean_output_sinr_db"])
            for row in subset
            if row["method"] == baseline
        }
        trials = sorted(set(proposed).intersection(baseline_values))
        differences = np.asarray(
            [proposed[trial] - baseline_values[trial] for trial in trials]
        )
        if differences.size and np.any(np.abs(differences) > 1e-12):
            statistic, p_value = wilcoxon(
                differences,
                alternative="greater",
                zero_method="wilcox",
            )
        else:
            statistic, p_value = math.nan, math.nan
        output[baseline] = {
            "n": int(differences.size),
            "mean_gain_db": float(np.mean(differences))
            if differences.size
            else math.nan,
            "median_gain_db": float(np.median(differences))
            if differences.size
            else math.nan,
            "wilcoxon_statistic": float(statistic),
            "one_sided_p_value": float(p_value),
        }
    return output


def _response_map(
    array: RectangularArray,
    weights: np.ndarray,
    gains: np.ndarray,
    config: dict[str, Any],
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    response = config["response_map"]
    theta = np.arange(
        float(response["theta_min_deg"]),
        float(response["theta_max_deg"]) + 0.5 * float(response["theta_step_deg"]),
        float(response["theta_step_deg"]),
    )
    phi = np.arange(
        float(response["phi_min_deg"]),
        float(response["phi_max_deg"]) + 0.5 * float(response["phi_step_deg"]),
        float(response["phi_step_deg"]),
    )
    tt, pp = np.meshgrid(theta, phi, indexing="ij")
    steering = np.asarray(gains, complex)[:, None] * array.steering_matrix(
        tt.ravel(), pp.ravel()
    )
    desired = np.asarray(gains, complex) * array.steering_vector(*_desired_direction(config))
    denominator = max(float(np.abs(np.vdot(weights, desired))), np.finfo(float).tiny)
    magnitude = np.abs(np.conj(np.asarray(weights, complex)) @ steering) / denominator
    floor_db = float(response["floor_db"])
    response_db = 20.0 * np.log10(
        np.maximum(magnitude, 10.0 ** (floor_db / 20.0))
    ).reshape(tt.shape)
    return theta, phi, response_db


def _critical_frame(result: SequenceResult, config: dict[str, Any]) -> int:
    proposed = {
        int(row["frame"]): float(row["output_sinr_db"])
        for row in result.frame_records
        if row["method"] == METHOD_PROPOSED
    }
    delayed = {
        int(row["frame"]): float(row["output_sinr_db"])
        for row in result.frame_records
        if row["method"] == METHOD_DELAYED
    }
    n_frames = len(proposed)
    onset = int(
        round(
            float(config["observation"]["first_fault_onset_fraction"])
            * (n_frames - 1)
        )
    )
    candidates = [frame for frame in proposed if frame >= onset and frame in delayed]
    if not candidates:
        candidates = sorted(proposed)
    return max(candidates, key=lambda frame: proposed[frame] - delayed[frame])


def _image_to_data_uri(path: Path) -> str:
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:image/png;base64,{encoded}"


def _format_number(value: Any, digits: int = 3) -> str:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return str(value)
    if not math.isfinite(numeric):
        return "—"
    return f"{numeric:.{digits}f}"


def _html_report(
    output_dir: Path,
    metrics: dict[str, Any],
    figures: Sequence[tuple[str, str]],
    *,
    standalone: bool,
) -> str:
    representative = metrics["representative"]["method_summary"]
    stressed = metrics["stressed_latency_results"]
    rows_rep = "".join(
        "<tr>"
        f"<td>{row['method']}</td>"
        f"<td>{_format_number(row['mean_output_sinr_db'], 2)}</td>"
        f"<td>{_format_number(100.0 * row['protection_availability'], 1)}%</td>"
        f"<td>{_format_number(row['mean_worst_response_db'], 2)}</td>"
        f"<td>{_format_number(row['median_design_runtime_ms'], 3)}</td>"
        "</tr>"
        for row in representative
    )
    rows_stressed = "".join(
        "<tr>"
        f"<td>{row['method']}</td>"
        f"<td>{_format_number(row['mean_output_sinr_db_mean'], 2)}</td>"
        f"<td>[{_format_number(row['mean_output_sinr_db_ci_low'], 2)}, {_format_number(row['mean_output_sinr_db_ci_high'], 2)}]</td>"
        f"<td>{_format_number(100.0 * row['protection_availability_mean'], 1)}%</td>"
        "</tr>"
        for row in stressed
    )
    image_blocks = []
    for filename, caption in figures:
        source = _image_to_data_uri(output_dir / filename) if standalone else filename
        image_blocks.append(
            f"<figure><img src=\"{source}\" alt=\"{caption}\"><figcaption>{caption}</figcaption></figure>"
        )
    findings = metrics["key_findings"]
    findings_html = "".join(f"<li>{value}</li>" for value in findings)
    return f"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8">
<title>HPM Digital Twin V0.5 Closed-Loop Report</title>
<style>
body{{font-family:Arial,'Noto Sans CJK SC',sans-serif;max-width:1180px;margin:28px auto;padding:0 22px;line-height:1.62;color:#202124}}
h1,h2{{line-height:1.25}} .note{{background:#f3f6fa;border-left:4px solid #5f6b7a;padding:12px 16px}}
table{{border-collapse:collapse;width:100%;margin:14px 0 24px}}th,td{{border:1px solid #c8ccd0;padding:8px;text-align:center}}th{{background:#f0f2f5}}
figure{{margin:26px 0}}img{{max-width:100%;height:auto;border:1px solid #e1e4e8}}figcaption{{text-align:center;font-size:0.93em;color:#555;margin-top:8px}}
code{{background:#f3f4f6;padding:2px 5px}} .grid{{display:grid;grid-template-columns:1fr 1fr;gap:16px}} @media(max-width:850px){{.grid{{grid-template-columns:1fr}}}}
</style></head><body>
<h1>HPM微波系统与效应数字化平台 V0.5</h1>
<p><strong>主题：</strong>感知协方差传播、多干扰动态跟踪与接收端鲁棒防护闭环</p>
<div class="note">全部功率相对白噪声方差归一化。本报告仅研究防御性接收信号处理，不包含真实高功率源预算、射程、设备阈值或毁伤推断。</div>
<h2>关键发现</h2><ul>{findings_html}</ul>
<h2>代表性动态序列</h2>
<table><thead><tr><th>方法</th><th>平均输出SINR / dB</th><th>防护可用率</th><th>平均最坏干扰响应 / dB</th><th>中位权值更新时间 / ms</th></tr></thead><tbody>{rows_rep}</tbody></table>
<h2>{metrics['stressed_latency_frames']}帧处理滞后 Monte Carlo</h2>
<table><thead><tr><th>方法</th><th>平均输出SINR / dB</th><th>95% CI</th><th>防护可用率</th></tr></thead><tbody>{rows_stressed}</tbody></table>
<h2>图形结果</h2>{''.join(image_blocks)}
<h2>复现实验</h2><pre>python -m pip install -r requirements.txt
python run_closed_loop_v05.py</pre>
<p>完整逐帧数据见 <code>representative_frame_records.csv</code>，Monte Carlo数据见 <code>monte_carlo_trials.csv</code>，配置快照见 <code>config_snapshot.yaml</code>。</p>
</body></html>"""


def _write_paper_tables(
    output_dir: Path,
    stressed_rows: Sequence[dict[str, Any]],
    ablation_summary: Sequence[dict[str, Any]],
    representative: Sequence[dict[str, Any]],
) -> None:
    _write_csv(output_dir / "paper_table_latency_results.csv", stressed_rows)
    _write_csv(output_dir / "paper_table_ablation.csv", ablation_summary)
    _write_csv(output_dir / "paper_table_runtime.csv", representative)
    lines = [
        r"\begin{tabular}{lccc}",
        r"\hline",
        r"Method & Mean SINR (dB) & 95\% CI & Availability (\%) \\",
        r"\hline",
    ]
    for row in stressed_rows:
        lines.append(
            f"{row['method']} & {float(row['mean_output_sinr_db_mean']):.2f} & "
            f"[{float(row['mean_output_sinr_db_ci_low']):.2f}, {float(row['mean_output_sinr_db_ci_high']):.2f}] & "
            f"{100.0 * float(row['protection_availability_mean']):.1f} \\\\"
        )
    lines.extend([r"\hline", r"\end{tabular}"])
    (output_dir / "paper_table_latency_results.tex").write_text(
        "\n".join(lines), encoding="utf-8"
    )


def _write_checksums(output_dir: Path, filenames: Sequence[str]) -> None:
    lines: list[str] = []
    for filename in filenames:
        path = output_dir / filename
        if path.exists():
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            lines.append(f"{digest}  {filename}")
    (output_dir / "CHECKSUMS.sha256").write_text("\n".join(lines) + "\n", encoding="utf-8")


def run(config_path: str | Path, output_dir: str | Path) -> dict[str, Any]:
    config_path = Path(config_path)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    progress_path = output_dir / "progress.log"

    def progress(message: str) -> None:
        stamp = time.strftime("%Y-%m-%d %H:%M:%S")
        line = f"[{stamp}] {message}"
        print(line, flush=True)
        with progress_path.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")

    if progress_path.exists():
        progress_path.unlink()
    start_total = time.perf_counter()
    array = _array_from_config(config)
    subarray, scanner = _scanner_from_config(array, config)
    scenario = config["scenario"]
    perception = config["perception"]
    observation = config["observation"]

    with threadpool_limits(limits=1):
        progress("Running representative dynamic closed-loop sequence")
        representative = _run_sequence(
            array,
            subarray,
            scanner,
            config,
            seed=int(config["seed"]),
            n_frames=int(scenario["frames"]),
            update_interval=int(perception["update_interval_frames"]),
            latency=int(perception["processing_latency_frames"]),
            final_fault_count=int(observation["representative_fault_count"]),
            speed_scale=float(scenario["speed_scale"]),
            diagnostics=True,
        )
        progress("Running dynamic Monte Carlo sweeps")
        mc_records, mc_summary = _run_standard_sweeps(
            array, subarray, scanner, config, progress
        )
        progress("Running component ablation")
        ablation_records, ablation_summary = _run_ablation(
            array, subarray, scanner, config, progress
        )

    _write_csv(output_dir / "representative_frame_records.csv", representative.frame_records)
    _write_csv(output_dir / "representative_packet_records.csv", representative.packet_records)
    _write_csv(output_dir / "monte_carlo_trials.csv", mc_records)
    _write_csv(output_dir / "monte_carlo_summary.csv", mc_summary)
    _write_csv(output_dir / "ablation_trials.csv", ablation_records)
    _write_csv(output_dir / "ablation_summary.csv", ablation_summary)

    diagnostics = representative.diagnostics
    critical_frame = _critical_frame(representative, config)
    delayed_weights = diagnostics["weights"][METHOD_DELAYED][critical_frame]
    proposed_weights = diagnostics["weights"][METHOD_PROPOSED][critical_frame]
    gains = diagnostics["gains"][critical_frame]
    theta, phi, delayed_map = _response_map(array, delayed_weights, gains, config)
    _, _, proposed_map = _response_map(array, proposed_weights, gains, config)
    predicted = diagnostics["predicted_centers_deg"][critical_frame]
    actual = diagnostics["trajectories_deg"][critical_frame]

    npz_payload: dict[str, Any] = {
        "trajectories_deg": diagnostics["trajectories_deg"],
        "packet_frames": diagnostics["packet_frames"],
        "packet_ready_frames": diagnostics["packet_ready_frames"],
        "packet_estimates_deg": diagnostics["packet_estimates_deg"],
        "packet_covariance_deg2": diagnostics["packet_covariance_deg2"],
        "packet_health": diagnostics["packet_health"],
        "packet_fault_masks": diagnostics["packet_fault_masks"],
        "predicted_centers_deg": diagnostics["predicted_centers_deg"],
        "predicted_covariance_deg2": diagnostics["predicted_covariance_deg2"],
        "tracking_error_deg": diagnostics["tracking_error_deg"],
        "sector_half_width_deg": diagnostics["sector_half_width_deg"],
        "selected_rank": diagnostics["selected_rank"],
        "critical_frame": np.asarray(critical_frame),
        "response_theta_deg": theta,
        "response_phi_deg": phi,
        "delayed_point_response_db": delayed_map,
        "pcp_response_db": proposed_map,
    }
    for method in METHOD_ORDER:
        key = method.lower().replace("-", "_")
        npz_payload[f"weights_{key}"] = diagnostics["weights"][method]
    np.savez_compressed(output_dir / "representative_case.npz", **npz_payload)

    progress("Rendering mechanism and result figures")
    plot_mechanism(
        output_dir / "00_pcp_closed_loop_mechanism.png",
        output_dir / "00_pcp_closed_loop_mechanism.svg",
    )
    plot_trajectory(diagnostics, output_dir / "01_dynamic_trajectories.png")
    plot_timeline(
        diagnostics["packet_frames"],
        diagnostics["packet_ready_frames"],
        diagnostics["fault_masks"],
        output_dir / "02_latency_fault_timeline.png",
    )
    plot_tracking(
        representative.frame_records,
        float(config["protection"]["protection_sinr_threshold_db"]),
        METHOD_ORDER,
        output_dir / "03_output_sinr_timeline.png",
    )
    plot_tracking_error(
        diagnostics,
        representative.packet_records,
        output_dir / "04_tracking_error.png",
    )
    plot_confidence_width_rank(
        diagnostics, output_dir / "05_confidence_width_rank.png"
    )
    plot_sensor_health_timeline(
        diagnostics, output_dir / "06_sensor_health_timeline.png"
    )
    plot_health_maps(
        diagnostics,
        (array.nx, array.ny),
        output_dir / "07_sensor_health_maps.png",
    )
    plot_response_map(
        theta,
        phi,
        delayed_map,
        desired_deg=_desired_direction(config),
        interferers_deg=actual,
        predicted_deg=predicted,
        title=f"Delayed point nulls at critical frame {critical_frame}",
        output=output_dir / "08_delayed_point_response_map.png",
    )
    plot_response_map(
        theta,
        phi,
        proposed_map,
        desired_deg=_desired_direction(config),
        interferers_deg=actual,
        predicted_deg=predicted,
        title=f"PCP-HybridNull covariance-shaped sectors at frame {critical_frame}",
        output=output_dir / "09_pcp_response_map.png",
    )

    plot_specs = [
        ("latency", "mean_output_sinr_db", "Processing latency (frames)", "Mean output SINR (dB)", "Latency robustness of the dynamic protection loop", "10_sinr_vs_latency.png", None),
        ("latency", "protection_availability", "Processing latency (frames)", "Protection availability", "Availability versus sensing-to-actuation latency", "11_availability_vs_latency.png", (0.0, 1.05)),
        ("update_interval", "mean_output_sinr_db", "Perception update interval (frames)", "Mean output SINR (dB)", "Update-rate sensitivity", "12_sinr_vs_update_interval.png", None),
        ("update_interval", "protection_availability", "Perception update interval (frames)", "Protection availability", "Availability versus update interval", "13_availability_vs_update_interval.png", (0.0, 1.05)),
        ("fault_count", "mean_output_sinr_db", "Final failed-channel count", "Mean output SINR (dB)", "Graceful degradation under sparse channel faults", "14_sinr_vs_fault_count.png", None),
        ("fault_count", "protection_availability", "Final failed-channel count", "Protection availability", "Protection availability under channel faults", "15_availability_vs_fault_count.png", (0.0, 1.05)),
        ("speed_scale", "mean_output_sinr_db", "Trajectory speed scale", "Mean output SINR (dB)", "Tracking-speed sensitivity", "16_sinr_vs_speed.png", None),
        ("latency", "p05_output_sinr_db", "Processing latency (frames)", "5th-percentile output SINR (dB)", "Tail-risk behavior under latency", "17_p05_sinr_vs_latency.png", None),
    ]
    for sweep, metric, xlabel, ylabel, title, filename, limits in plot_specs:
        plot_metric_sweep(
            mc_summary,
            sweep=sweep,
            mean_key=f"{metric}_mean",
            low_key=f"{metric}_ci_low",
            high_key=f"{metric}_ci_high",
            xlabel=xlabel,
            ylabel=ylabel,
            title=title,
            method_order=METHOD_ORDER,
            output=output_dir / filename,
            y_limits=limits,
        )
    plot_ablation(ablation_summary, output_dir / "18_ablation.png")
    plot_runtime(
        representative.method_summary,
        representative.packet_records,
        output_dir / "19_runtime.png",
    )

    latency_values = [float(value) for value in config["monte_carlo"]["latency_sweep_frames"]]
    stressed_latency = 4.0 if 4.0 in latency_values else max(latency_values)
    stressed_rows = [
        _select_summary(mc_summary, "latency", stressed_latency, method)
        for method in METHOD_ORDER
    ]
    paired = _paired_statistics(mc_records, latency_value=stressed_latency)
    proposed_rep = next(
        row for row in representative.method_summary if row["method"] == METHOD_PROPOSED
    )
    fixed_rep = next(
        row for row in representative.method_summary if row["method"] == METHOD_FIXED
    )
    delayed_rep = next(
        row for row in representative.method_summary if row["method"] == METHOD_DELAYED
    )
    packet_error = np.asarray(
        [float(row["mean_measurement_error_deg"]) for row in representative.packet_records]
    )
    packet_runtime = np.asarray(
        [float(row["runtime_ms"]) for row in representative.packet_records]
    )
    fault_recall = np.asarray(
        [float(row["fault_detection_recall"]) for row in representative.packet_records]
    )
    false_alarm = np.asarray(
        [float(row["healthy_false_alarm_rate"]) for row in representative.packet_records]
    )
    key_findings = [
        f"代表性双干扰动态序列中，PCP-HybridNull平均输出SINR为{proposed_rep['mean_output_sinr_db']:.2f} dB，较Delayed-Point提高{proposed_rep['mean_output_sinr_db'] - delayed_rep['mean_output_sinr_db']:.2f} dB。",
        f"PCP-HybridNull防护可用率为{100.0 * proposed_rep['protection_availability']:.1f}%，固定扇区基线为{100.0 * fixed_rep['protection_availability']:.1f}%。",
        f"PAWR更新点平均测向误差为{np.mean(packet_error):.3f}°，中位感知与协方差提取耗时为{np.median(packet_runtime):.2f} ms。",
        f"关键帧{critical_frame}处，协方差传播自动扩大零陷扇区并选择秩{int(diagnostics['selected_rank'][critical_frame])}，用于覆盖测量滞后与轨迹漂移。",
        f"{int(stressed_latency)}帧滞后下，相对Delayed-FixedCR的配对平均增益为{paired[METHOD_FIXED]['mean_gain_db']:.2f} dB，单侧Wilcoxon p={paired[METHOD_FIXED]['one_sided_p_value']:.3g}。",
        "失效边界仍然存在：当轨迹速度或更新间隔继续增大、预测置信域触及上限时，所有方法都会下降；报告未将快速配置结果包装成硬件抗毁结论。",
    ]
    metrics: dict[str, Any] = {
        "platform_version": "0.5.0",
        "total_runtime_s": float(time.perf_counter() - start_total),
        "representative": {
            "method_summary": representative.method_summary,
            "mean_measurement_error_deg": float(np.mean(packet_error)),
            "median_perception_runtime_ms": float(np.median(packet_runtime)),
            "mean_fault_detection_recall": float(np.nanmean(fault_recall))
            if np.any(np.isfinite(fault_recall))
            else math.nan,
            "mean_healthy_false_alarm_rate": float(np.mean(false_alarm)),
            "critical_frame": critical_frame,
        },
        "stressed_latency_frames": stressed_latency,
        "stressed_latency_results": stressed_rows,
        "paired_statistics": paired,
        "ablation_summary": ablation_summary,
        "key_findings": key_findings,
        "test_protocol": {
            "monte_carlo_trials_per_point": int(config["monte_carlo"]["trials"]),
            "monte_carlo_frames": int(config["monte_carlo"]["frames"]),
            "ablation_trials": int(config["monte_carlo"]["ablation_trials"]),
            "normalized_power_only": True,
        },
    }
    (output_dir / "results_summary.json").write_text(
        json.dumps(_json_ready(metrics), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    (output_dir / "config_snapshot.yaml").write_text(
        yaml.safe_dump(config, sort_keys=False, allow_unicode=True), encoding="utf-8"
    )
    environment = {
        "python": sys.version,
        "platform": platform.platform(),
        "numpy": np.__version__,
        "scipy": scipy.__version__,
        "matplotlib": matplotlib.__version__,
    }
    (output_dir / "environment.json").write_text(
        json.dumps(environment, indent=2), encoding="utf-8"
    )

    figure_manifest = [
        ("00_pcp_closed_loop_mechanism.png", "V0.5感知协方差传播与动态防护闭环机理图"),
        ("01_dynamic_trajectories.png", "双干扰真实轨迹、PAWR测量及延迟补偿预测"),
        ("02_latency_fault_timeline.png", "采集—权值生效时延与阵元失效时间线"),
        ("03_output_sinr_timeline.png", "代表性序列输出SINR逐帧对比"),
        ("04_tracking_error.png", "测量误差与预测跟踪误差"),
        ("05_confidence_width_rank.png", "置信域宽度与零陷子空间秩自适应变化"),
        ("06_sensor_health_timeline.png", "PAWR通道健康度时序热图"),
        ("07_sensor_health_maps.png", "阵列平面故障定位可视化"),
        ("08_delayed_point_response_map.png", "关键帧延迟点零陷二维响应"),
        ("09_pcp_response_map.png", "关键帧PCP-HybridNull二维响应"),
        ("10_sinr_vs_latency.png", "平均SINR随处理滞后变化"),
        ("11_availability_vs_latency.png", "防护可用率随处理滞后变化"),
        ("12_sinr_vs_update_interval.png", "平均SINR随感知更新间隔变化"),
        ("13_availability_vs_update_interval.png", "防护可用率随更新间隔变化"),
        ("14_sinr_vs_fault_count.png", "平均SINR随失效通道数变化"),
        ("15_availability_vs_fault_count.png", "防护可用率随失效通道数变化"),
        ("16_sinr_vs_speed.png", "平均SINR随轨迹速度变化"),
        ("17_p05_sinr_vs_latency.png", "滞后条件下5%分位SINR"),
        ("18_ablation.png", "PCP-HybridNull组件消融"),
        ("19_runtime.png", "感知与权值更新时间"),
    ]
    _write_csv(
        output_dir / "figure_manifest.csv",
        [{"filename": name, "caption": caption} for name, caption in figure_manifest],
    )
    report = _html_report(output_dir, metrics, figure_manifest, standalone=False)
    standalone = _html_report(output_dir, metrics, figure_manifest, standalone=True)
    (output_dir / "closed_loop_v05_report.html").write_text(report, encoding="utf-8")
    (output_dir / "closed_loop_v05_report_standalone.html").write_text(
        standalone, encoding="utf-8"
    )
    _write_paper_tables(
        output_dir, stressed_rows, ablation_summary, representative.method_summary
    )
    (output_dir / "KEY_FINDINGS.md").write_text(
        "# V0.5 Key Findings\n\n" + "\n".join(f"- {value}" for value in key_findings) + "\n",
        encoding="utf-8",
    )
    (output_dir / "README.md").write_text(
        "# V0.5 outputs\n\n"
        "Open `closed_loop_v05_report_standalone.html` for the self-contained report.\n\n"
        "All powers are normalized to white-noise variance. These outputs describe defensive receive processing only.\n",
        encoding="utf-8",
    )
    checksum_files = [
        "results_summary.json",
        "representative_case.npz",
        "monte_carlo_trials.csv",
        "monte_carlo_summary.csv",
        "ablation_summary.csv",
        "closed_loop_v05_report_standalone.html",
    ]
    _write_checksums(output_dir, checksum_files)
    progress(f"V0.5 complete in {metrics['total_runtime_s']:.1f} s")
    return metrics


def cli(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--config",
        default="configs/closed_loop_v05.yaml",
        help="YAML configuration path",
    )
    parser.add_argument(
        "--output",
        default="outputs_v05_closed_loop",
        help="Output directory",
    )
    args = parser.parse_args(argv)
    run(args.config, args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(cli())

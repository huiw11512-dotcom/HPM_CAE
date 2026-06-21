"""V0.4 receive-side robust wide-null protection workflow.

This workflow links a direction estimate and its confidence region to
normalized receive beamforming.  A strong interferer is observed at the
estimated direction during weight training and then drifts before evaluation,
which exposes the fragility of point-null designs.  All powers are relative to
white-noise variance; no absolute high-power source, range, device threshold,
or damage inference is included.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
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
from scipy.stats import wilcoxon
from threadpoolctl import threadpool_limits
import yaml

from hpm_platform.evaluation.doa_statistics import mean_confidence_interval, wilson_interval
from hpm_platform.physics.array_geometry import C0, RectangularArray
from hpm_platform.protection.beamforming import covariance_matrix, lcmv_weights, mvdr_weights
from hpm_platform.protection.robust_beamforming import (
    ConfidenceSector,
    HybridNullResult,
    analytic_output_sinr_db,
    build_confidence_sector,
    confidence_region_hybrid_null_weights,
    derivative_lcmv_weights,
    relative_response_db,
    sampled_sector_lcmv_weights,
    sector_energy_rank,
    soft_sector_mvdr_weights,
    white_noise_gain_db,
)
from hpm_platform.visualization.protection_v04 import (
    plot_ablation,
    plot_angular_cut,
    plot_cdf,
    plot_mechanism,
    plot_metric_curve,
    plot_rank_tradeoff,
    plot_response_map,
    plot_runtime,
    plot_sector_energy,
)


METHOD_CONVENTIONAL = "Conventional"
METHOD_MVDR = "DL-MVDR"
METHOD_POINT = "Point-LCMV"
METHOD_DERIVATIVE = "Derivative-LCMV"
METHOD_SOFT = "Sector-MVDR"
METHOD_PROPOSED = "CR-HybridNull"
METHOD_ORDER = [
    METHOD_CONVENTIONAL,
    METHOD_MVDR,
    METHOD_POINT,
    METHOD_DERIVATIVE,
    METHOD_SOFT,
    METHOD_PROPOSED,
]
PAPER_METHOD_ORDER = [METHOD_MVDR, METHOD_POINT, METHOD_DERIVATIVE, METHOD_SOFT, METHOD_PROPOSED]

ABLATION_POINT = "Point constraint"
ABLATION_DERIVATIVE = "First-order derivatives"
ABLATION_SOFT = "Soft sector penalty"
ABLATION_HARD = "Hard sector eigennull"
ABLATION_FULL = "Full CR-HybridNull"
ABLATION_DENSE = "Dense sampled sector"
ABLATION_ORDER = [
    ABLATION_POINT,
    ABLATION_DERIVATIVE,
    ABLATION_SOFT,
    ABLATION_HARD,
    ABLATION_FULL,
    ABLATION_DENSE,
]


@dataclass(frozen=True)
class TrialSetup:
    sensor_gains: np.ndarray
    covariance: np.ndarray
    actual_interferer_deg: tuple[float, float]
    drift_angle_rad: float


@dataclass(frozen=True)
class WeightDesign:
    weights: np.ndarray
    runtime_ms: float
    selected_rank: int = 0
    energy_coverage: float = 0.0
    constraint_condition: float = math.nan


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


def _directions(config: dict[str, Any]) -> tuple[tuple[float, float], tuple[float, float]]:
    desired = config["scenario"]["desired"]
    interferer = config["scenario"]["interferer"]
    return (
        (float(desired["theta_deg"]), float(desired["phi_deg"])),
        (float(interferer["estimate_theta_deg"]), float(interferer["estimate_phi_deg"])),
    )


def _complex_normal(rng: np.random.Generator, shape: tuple[int, ...]) -> np.ndarray:
    return (rng.standard_normal(shape) + 1j * rng.standard_normal(shape)) / np.sqrt(2.0)


def _draw_sensor_gains(
    rng: np.random.Generator,
    n_elements: int,
    gain_std_db: float,
    phase_std_deg: float,
) -> np.ndarray:
    gain_db = rng.normal(0.0, float(gain_std_db), n_elements)
    phase_deg = rng.normal(0.0, float(phase_std_deg), n_elements)
    return 10.0 ** (gain_db / 20.0) * np.exp(1j * np.deg2rad(phase_deg))


def _drifted_direction(
    center_deg: tuple[float, float],
    magnitude_deg: float,
    angle_rad: float,
) -> tuple[float, float]:
    theta = float(center_deg[0]) + float(magnitude_deg) * math.cos(float(angle_rad))
    phi = float(center_deg[1]) + float(magnitude_deg) * math.sin(float(angle_rad))
    return float(np.clip(theta, 0.1, 89.9)), phi


def _simulate_trial_setup(
    array: RectangularArray,
    config: dict[str, Any],
    *,
    seed: int,
    snapshots: int,
    phase_std_deg: float,
    inr_db: float,
    drift_deg: float,
) -> TrialSetup:
    if snapshots < 2:
        raise ValueError("snapshots must be at least two")
    rng = np.random.default_rng(int(seed))
    drift_angle = float(rng.uniform(0.0, 2.0 * np.pi))
    desired_deg, center_deg = _directions(config)
    observation = config["observation"]
    sensor_gains = _draw_sensor_gains(
        rng,
        array.n_elements,
        float(observation["sensor_gain_std_db"]),
        float(phase_std_deg),
    )
    a_s = sensor_gains * array.steering_vector(*desired_deg)
    a_i = sensor_gains * array.steering_vector(*center_deg)
    desired_power = 10.0 ** (float(config["scenario"]["desired"]["snr_db"]) / 10.0)
    interferer_power = 10.0 ** (float(inr_db) / 10.0)
    noise_power = float(observation["noise_power"])
    x = (
        a_s[:, None] * np.sqrt(desired_power) * _complex_normal(rng, (1, snapshots))
        + a_i[:, None] * np.sqrt(interferer_power) * _complex_normal(rng, (1, snapshots))
        + np.sqrt(noise_power) * _complex_normal(rng, (array.n_elements, snapshots))
    )
    return TrialSetup(
        sensor_gains=sensor_gains,
        covariance=covariance_matrix(x),
        actual_interferer_deg=_drifted_direction(center_deg, float(drift_deg), drift_angle),
        drift_angle_rad=drift_angle,
    )


def _sector_from_config(
    array: RectangularArray,
    config: dict[str, Any],
    *,
    half_width_deg: float | None = None,
) -> ConfidenceSector:
    _, center = _directions(config)
    cfg = config["confidence_region"]
    if half_width_deg is None:
        half_theta = float(cfg["half_width_theta_deg"])
        half_phi = float(cfg["half_width_phi_deg"])
        sigma_theta = float(cfg["sigma_theta_deg"])
        sigma_phi = float(cfg["sigma_phi_deg"])
    else:
        half_theta = half_phi = float(half_width_deg)
        sigma_theta = sigma_phi = max(float(half_width_deg) / 2.0, 0.25)
    return build_confidence_sector(
        array,
        center,
        (half_theta, half_phi),
        grid_step_deg=float(cfg["grid_step_deg"]),
        sigma_deg=(sigma_theta, sigma_phi),
    )


def _timed(builder: Callable[[], np.ndarray]) -> WeightDesign:
    start = time.perf_counter()
    weights = builder()
    return WeightDesign(weights=np.asarray(weights, complex), runtime_ms=1000.0 * (time.perf_counter() - start))


def _design_methods(
    array: RectangularArray,
    config: dict[str, Any],
    covariance: np.ndarray,
    sector: ConfidenceSector,
) -> dict[str, WeightDesign]:
    desired_deg, center_deg = _directions(config)
    a_s = array.steering_vector(*desired_deg)
    a_i = array.steering_vector(*center_deg)
    cfg = config["beamforming"]
    loading = float(cfg["diagonal_loading"])

    designs: dict[str, WeightDesign] = {}
    start = time.perf_counter()
    conventional = a_s / np.vdot(a_s, a_s)
    designs[METHOD_CONVENTIONAL] = WeightDesign(
        conventional,
        1000.0 * (time.perf_counter() - start),
    )
    designs[METHOD_MVDR] = _timed(lambda: mvdr_weights(covariance, a_s, loading))
    designs[METHOD_POINT] = _timed(
        lambda: lcmv_weights(
            covariance,
            np.column_stack((a_s, a_i)),
            np.array([1.0, 0.0]),
            loading,
        )
    )
    designs[METHOD_DERIVATIVE] = _timed(
        lambda: derivative_lcmv_weights(
            covariance,
            a_s,
            array,
            center_deg,
            loading_factor=loading,
            step_deg=float(cfg["derivative_step_deg"]),
        )
    )
    designs[METHOD_SOFT] = _timed(
        lambda: soft_sector_mvdr_weights(
            covariance,
            a_s,
            sector,
            sector_strength=float(cfg["soft_sector_strength"]),
            loading_factor=loading,
        )
    )

    start = time.perf_counter()
    proposed = confidence_region_hybrid_null_weights(
        covariance,
        a_s,
        sector,
        loading_factor=loading,
        energy_threshold=float(cfg["energy_threshold"]),
        max_rank=int(cfg["max_eigennull_rank"]),
        margin_modes=int(cfg["margin_modes"]),
        soft_strength=float(cfg["soft_sector_strength"]),
        white_noise_gain_floor_db=float(cfg["white_noise_gain_floor_db"]),
        condition_limit=float(cfg["condition_limit"]),
    )
    designs[METHOD_PROPOSED] = WeightDesign(
        proposed.weights,
        1000.0 * (time.perf_counter() - start),
        selected_rank=proposed.selected_rank,
        energy_coverage=proposed.energy_coverage,
        constraint_condition=proposed.constraint_condition,
    )
    return designs


def _evaluate_design(
    array: RectangularArray,
    config: dict[str, Any],
    setup: TrialSetup,
    sector: ConfidenceSector,
    method: str,
    design: WeightDesign,
    *,
    inr_db: float,
    success_threshold_db: float,
) -> dict[str, Any]:
    desired_deg, _ = _directions(config)
    weights = design.weights
    a_s_true = setup.sensor_gains * array.steering_vector(*desired_deg)
    a_i_true = setup.sensor_gains * array.steering_vector(*setup.actual_interferer_deg)
    desired_power = 10.0 ** (float(config["scenario"]["desired"]["snr_db"]) / 10.0)
    interferer_power = 10.0 ** (float(inr_db) / 10.0)
    noise_power = float(config["observation"]["noise_power"])
    output_sinr = analytic_output_sinr_db(
        weights,
        a_s_true,
        a_i_true,
        desired_power=desired_power,
        interferer_power=interferer_power,
        noise_power=noise_power,
    )
    actual_null = float(relative_response_db(weights, a_i_true, a_s_true)[0])
    true_sector_steering = setup.sensor_gains[:, None] * sector.steering
    sector_response = relative_response_db(weights, true_sector_steering, a_s_true)
    desired_gain = float(20.0 * np.log10(max(np.abs(np.vdot(weights, a_s_true)), 1e-15)))
    return {
        "method": method,
        "output_sinr_db": output_sinr,
        "actual_null_db": actual_null,
        "sector_worst_response_db": float(np.max(sector_response)),
        "sector_median_response_db": float(np.median(sector_response)),
        "desired_gain_db": desired_gain,
        "white_noise_gain_db": white_noise_gain_db(weights),
        "runtime_ms": float(design.runtime_ms),
        "selected_rank": int(design.selected_rank),
        "energy_coverage": float(design.energy_coverage),
        "constraint_condition": (float(design.constraint_condition) if np.isfinite(design.constraint_condition) else None),
        "protected": int(output_sinr >= float(success_threshold_db)),
        "actual_theta_deg": float(setup.actual_interferer_deg[0]),
        "actual_phi_deg": float(setup.actual_interferer_deg[1]),
    }


def _run_one(
    array: RectangularArray,
    config: dict[str, Any],
    sector: ConfidenceSector,
    *,
    seed: int,
    snapshots: int,
    phase_std_deg: float,
    inr_db: float,
    drift_deg: float,
    success_threshold_db: float,
) -> list[dict[str, Any]]:
    setup = _simulate_trial_setup(
        array,
        config,
        seed=seed,
        snapshots=snapshots,
        phase_std_deg=phase_std_deg,
        inr_db=inr_db,
        drift_deg=drift_deg,
    )
    designs = _design_methods(array, config, setup.covariance, sector)
    return [
        _evaluate_design(
            array,
            config,
            setup,
            sector,
            method,
            designs[method],
            inr_db=inr_db,
            success_threshold_db=success_threshold_db,
        )
        for method in METHOD_ORDER
    ]


def _run_sweeps(
    array: RectangularArray,
    config: dict[str, Any],
    default_sector: ConfidenceSector,
    mark: Callable[[str], None],
) -> list[dict[str, Any]]:
    mc = config["monte_carlo"]
    trials = int(mc["trials"])
    threshold = float(mc["protection_sinr_threshold_db"])
    base_seed = int(config["seed"]) + 100_000_000
    records: list[dict[str, Any]] = []

    specifications: list[tuple[str, list[float], Callable[[float], tuple[int, float, float, float, float | None]]]] = [
        (
            "drift_deg",
            [float(v) for v in mc["drift_sweep_deg"]],
            lambda value: (
                int(mc["snapshots_for_drift_sweep"]),
                float(mc["phase_std_for_drift_sweep_deg"]),
                float(mc["inr_for_drift_sweep_db"]),
                float(value),
                None,
            ),
        ),
        (
            "snapshots",
            [float(v) for v in mc["snapshot_sweep"]],
            lambda value: (
                int(value),
                float(mc["phase_std_for_snapshot_sweep_deg"]),
                float(mc["inr_for_snapshot_sweep_db"]),
                float(mc["drift_for_snapshot_sweep_deg"]),
                None,
            ),
        ),
        (
            "phase_error_std_deg",
            [float(v) for v in mc["phase_error_sweep_deg"]],
            lambda value: (
                int(mc["snapshots_for_phase_sweep"]),
                float(value),
                float(mc["inr_for_phase_sweep_db"]),
                float(mc["drift_for_phase_sweep_deg"]),
                None,
            ),
        ),
        (
            "uncertainty_half_width_deg",
            [float(v) for v in mc["uncertainty_half_width_sweep_deg"]],
            lambda value: (
                int(mc["snapshots_for_uncertainty_sweep"]),
                float(mc["phase_std_for_uncertainty_sweep_deg"]),
                float(mc["inr_for_uncertainty_sweep_db"]),
                float(mc["drift_for_uncertainty_sweep_deg"]),
                float(value),
            ),
        ),
        (
            "inr_db",
            [float(v) for v in mc["inr_sweep_db"]],
            lambda value: (
                int(mc["snapshots_for_inr_sweep"]),
                float(mc["phase_std_for_inr_sweep_deg"]),
                float(value),
                float(mc["drift_for_inr_sweep_deg"]),
                None,
            ),
        ),
    ]

    sector_cache: dict[float, ConfidenceSector] = {}
    for sweep_index, (sweep, values, builder) in enumerate(specifications):
        for value in values:
            snapshots, phase_std, inr_db, drift_deg, half_width = builder(value)
            if half_width is None:
                sector = default_sector
            else:
                sector = sector_cache.setdefault(
                    float(half_width),
                    _sector_from_config(array, config, half_width_deg=float(half_width)),
                )
            for trial in range(trials):
                seed = base_seed + sweep_index * 10_000_000 + trial
                rows = _run_one(
                    array,
                    config,
                    sector,
                    seed=seed,
                    snapshots=snapshots,
                    phase_std_deg=phase_std,
                    inr_db=inr_db,
                    drift_deg=drift_deg,
                    success_threshold_db=threshold,
                )
                for row in rows:
                    row.update(
                        {
                            "sweep": sweep,
                            "x_value": float(value),
                            "trial": int(trial),
                            "snapshots": int(snapshots),
                            "phase_error_std_deg": float(phase_std),
                            "inr_db": float(inr_db),
                            "drift_deg": float(drift_deg),
                            "sector_half_width_deg": float(
                                sector.half_width_deg[0]
                            ),
                        }
                    )
                    records.append(row)
            mark(f"sweep_{sweep}_{value:g}_done")
    return records


def _summarize(records: Sequence[dict[str, Any]], confidence: float) -> list[dict[str, Any]]:
    keys = sorted({(str(row["sweep"]), float(row["x_value"]), str(row["method"])) for row in records})
    output: list[dict[str, Any]] = []
    for sweep, x_value, method in keys:
        group = [
            row
            for row in records
            if row["sweep"] == sweep
            and np.isclose(float(row["x_value"]), x_value)
            and row["method"] == method
        ]
        sinr = np.asarray([float(row["output_sinr_db"]) for row in group])
        actual_null = np.asarray([float(row["actual_null_db"]) for row in group])
        sector_worst = np.asarray([float(row["sector_worst_response_db"]) for row in group])
        wng = np.asarray([float(row["white_noise_gain_db"]) for row in group])
        gain = np.asarray([float(row["desired_gain_db"]) for row in group])
        runtime = np.asarray([float(row["runtime_ms"]) for row in group])
        ranks = np.asarray([float(row["selected_rank"]) for row in group])
        mean_sinr, sinr_low, sinr_high = mean_confidence_interval(sinr, confidence)
        mean_null, null_low, null_high = mean_confidence_interval(actual_null, confidence)
        mean_sector, sector_low, sector_high = mean_confidence_interval(sector_worst, confidence)
        protected = int(sum(int(row["protected"]) for row in group))
        rate, rate_low, rate_high = wilson_interval(protected, len(group), confidence)
        output.append(
            {
                "sweep": sweep,
                "x_value": float(x_value),
                "method": method,
                "n_trials": len(group),
                "mean_output_sinr_db": float(mean_sinr),
                "sinr_ci_low_db": float(sinr_low),
                "sinr_ci_high_db": float(sinr_high),
                "median_output_sinr_db": float(np.median(sinr)),
                "p10_output_sinr_db": float(np.quantile(sinr, 0.10)),
                "mean_actual_null_db": float(mean_null),
                "actual_null_ci_low_db": float(null_low),
                "actual_null_ci_high_db": float(null_high),
                "mean_sector_worst_response_db": float(mean_sector),
                "sector_worst_ci_low_db": float(sector_low),
                "sector_worst_ci_high_db": float(sector_high),
                "mean_white_noise_gain_db": float(np.mean(wng)),
                "mean_desired_gain_db": float(np.mean(gain)),
                "protection_rate": float(rate),
                "protection_ci_low": float(rate_low),
                "protection_ci_high": float(rate_high),
                "median_runtime_ms": float(np.median(runtime)),
                "p95_runtime_ms": float(np.quantile(runtime, 0.95)),
                "mean_selected_rank": float(np.mean(ranks)),
            }
        )
    return output


def _select_summary(
    summary: Sequence[dict[str, Any]],
    sweep: str,
    x_value: float,
    method: str,
) -> dict[str, Any]:
    return next(
        row
        for row in summary
        if row["sweep"] == sweep
        and np.isclose(float(row["x_value"]), float(x_value))
        and row["method"] == method
    )


def _write_dict_csv(path: Path, rows: Sequence[dict[str, Any]]) -> None:
    if not rows:
        raise ValueError(f"cannot write empty CSV: {path}")
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def _representative_case(
    array: RectangularArray,
    config: dict[str, Any],
    sector: ConfidenceSector,
    output_dir: Path,
) -> tuple[dict[str, Any], dict[str, WeightDesign], TrialSetup]:
    rep = config["scenario"]["representative_drift"]
    desired_deg, center_deg = _directions(config)
    delta_theta = float(rep["delta_theta_deg"])
    delta_phi = float(rep["delta_phi_deg"])
    drift = float(np.hypot(delta_theta, delta_phi))
    angle = float(np.arctan2(delta_phi, delta_theta))

    seed = int(config["seed"]) + 4_000_000
    # Reproduce the standard trial but force the representative drift vector.
    setup_random = _simulate_trial_setup(
        array,
        config,
        seed=seed,
        snapshots=int(config["observation"]["snapshots"]),
        phase_std_deg=float(config["observation"]["sensor_phase_std_deg"]),
        inr_db=float(config["scenario"]["interferer"]["inr_db"]),
        drift_deg=drift,
    )
    setup = TrialSetup(
        sensor_gains=setup_random.sensor_gains,
        covariance=setup_random.covariance,
        actual_interferer_deg=(center_deg[0] + delta_theta, center_deg[1] + delta_phi),
        drift_angle_rad=angle,
    )
    designs = _design_methods(array, config, setup.covariance, sector)
    threshold = float(config["monte_carlo"]["protection_sinr_threshold_db"])
    metrics: dict[str, Any] = {}
    for method in METHOD_ORDER:
        metrics[method] = _evaluate_design(
            array,
            config,
            setup,
            sector,
            method,
            designs[method],
            inr_db=float(config["scenario"]["interferer"]["inr_db"]),
            success_threshold_db=threshold,
        )

    map_cfg = config["response_map"]
    theta = np.arange(
        float(map_cfg["theta_min_deg"]),
        float(map_cfg["theta_max_deg"]) + 0.5 * float(map_cfg["theta_step_deg"]),
        float(map_cfg["theta_step_deg"]),
    )
    phi = np.arange(
        float(map_cfg["phi_min_deg"]),
        float(map_cfg["phi_max_deg"]) + 0.5 * float(map_cfg["phi_step_deg"]),
        float(map_cfg["phi_step_deg"]),
    )
    tt, pp = np.meshgrid(theta, phi, indexing="ij")
    steering_true = setup.sensor_gains[:, None] * array.steering_matrix(tt.ravel(), pp.ravel())
    desired_true = setup.sensor_gains * array.steering_vector(*desired_deg)
    maps: dict[str, np.ndarray] = {}
    for method in [METHOD_POINT, METHOD_PROPOSED]:
        response = relative_response_db(
            designs[method].weights,
            steering_true,
            desired_true,
            floor_db=float(map_cfg["floor_db"]),
        ).reshape(tt.shape)
        maps[method] = np.maximum(response, float(map_cfg["floor_db"]))
    plot_response_map(
        theta,
        phi,
        maps[METHOD_POINT],
        desired_deg=desired_deg,
        interferer_center_deg=center_deg,
        actual_interferer_deg=setup.actual_interferer_deg,
        half_width_deg=sector.half_width_deg,
        title="Point-LCMV: deep nominal null but weak drift tolerance",
        output=output_dir / "01_point_lcmv_map.png",
    )
    plot_response_map(
        theta,
        phi,
        maps[METHOD_PROPOSED],
        desired_deg=desired_deg,
        interferer_center_deg=center_deg,
        actual_interferer_deg=setup.actual_interferer_deg,
        half_width_deg=sector.half_width_deg,
        title="CR-HybridNull: confidence-region broad null",
        output=output_dir / "02_cr_hybridnull_map.png",
    )

    signed = np.linspace(-10.0, 12.0, 241)
    unit_delta = np.array([delta_theta, delta_phi], dtype=float) / max(drift, 1e-12)
    cut_theta = center_deg[0] + signed * unit_delta[0]
    cut_phi = center_deg[1] + signed * unit_delta[1]
    cut_steering = setup.sensor_gains[:, None] * array.steering_matrix(cut_theta, cut_phi)
    cut_responses = {
        method: np.maximum(
            relative_response_db(designs[method].weights, cut_steering, desired_true),
            -90.0,
        )
        for method in [METHOD_MVDR, METHOD_POINT, METHOD_DERIVATIVE, METHOD_SOFT, METHOD_PROPOSED]
    }
    plot_angular_cut(
        signed,
        cut_responses,
        actual_offset_deg=drift,
        title="Receive null along the estimated-to-actual drift trajectory",
        output=output_dir / "03_drift_cut.png",
    )
    selected_rank = designs[METHOD_PROPOSED].selected_rank
    plot_sector_energy(
        sector.singular_values,
        sector.cumulative_energy,
        selected_rank,
        output_dir / "04_sector_eigen_energy.png",
    )

    rank_values = list(range(1, min(14, sector.eigenvectors.shape[1]) + 1))
    worst_response: list[float] = []
    a_s_nominal = array.steering_vector(*desired_deg)
    beam_cfg = config["beamforming"]
    scale = float(np.trace(setup.covariance).real) / array.n_elements
    effective = setup.covariance + float(beam_cfg["soft_sector_strength"]) * scale * sector.covariance
    for rank in rank_values:
        constraints = np.column_stack((a_s_nominal, sector.eigenvectors[:, :rank]))
        try:
            weights = lcmv_weights(
                effective,
                constraints,
                np.r_[1.0, np.zeros(rank)],
                float(beam_cfg["diagonal_loading"]),
            )
            response = relative_response_db(weights, sector.steering, a_s_nominal)
            worst_response.append(float(np.max(response)))
        except np.linalg.LinAlgError:
            worst_response.append(float("nan"))
    plot_rank_tradeoff(
        rank_values,
        worst_response,
        selected_rank=selected_rank,
        output=output_dir / "05_rank_tradeoff.png",
    )

    np.savez_compressed(
        output_dir / "representative_case.npz",
        sensor_gains=setup.sensor_gains,
        covariance=setup.covariance,
        desired_direction_deg=np.asarray(desired_deg),
        estimated_interferer_deg=np.asarray(center_deg),
        actual_interferer_deg=np.asarray(setup.actual_interferer_deg),
        sector_theta_deg=sector.theta_deg,
        sector_phi_deg=sector.phi_deg,
        sector_probability=sector.probability,
        sector_covariance=sector.covariance,
        sector_singular_values=sector.singular_values,
        point_weights=designs[METHOD_POINT].weights,
        proposed_weights=designs[METHOD_PROPOSED].weights,
        theta_grid_deg=theta,
        phi_grid_deg=phi,
        point_response_db=maps[METHOD_POINT],
        proposed_response_db=maps[METHOD_PROPOSED],
        cut_offset_deg=signed,
        **{f"cut_{method.replace('-', '_').replace(' ', '_').lower()}": values for method, values in cut_responses.items()},
    )
    return metrics, designs, setup


def _run_ablation(
    array: RectangularArray,
    config: dict[str, Any],
    sector: ConfidenceSector,
    mark: Callable[[str], None],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    mc = config["monte_carlo"]
    trials = int(mc["ablation_trials"])
    threshold = float(mc["protection_sinr_threshold_db"])
    desired_deg, center_deg = _directions(config)
    a_s = array.steering_vector(*desired_deg)
    a_i = array.steering_vector(*center_deg)
    beam_cfg = config["beamforming"]
    loading = float(beam_cfg["diagonal_loading"])
    initial_rank = sector_energy_rank(
        sector,
        float(beam_cfg["energy_threshold"]),
        max_rank=int(beam_cfg["max_eigennull_rank"]),
        margin_modes=int(beam_cfg["margin_modes"]),
    )
    records: list[dict[str, Any]] = []
    base_seed = int(config["seed"]) + 300_000_000

    for trial in range(trials):
        setup = _simulate_trial_setup(
            array,
            config,
            seed=base_seed + trial,
            snapshots=int(mc["ablation_snapshots"]),
            phase_std_deg=float(mc["ablation_phase_std_deg"]),
            inr_db=float(mc["ablation_inr_db"]),
            drift_deg=float(mc["ablation_drift_deg"]),
        )
        r = setup.covariance
        scale = float(np.trace(r).real) / array.n_elements
        methods: dict[str, WeightDesign] = {}
        methods[ABLATION_POINT] = _timed(
            lambda: lcmv_weights(r, np.column_stack((a_s, a_i)), np.array([1.0, 0.0]), loading)
        )
        methods[ABLATION_DERIVATIVE] = _timed(
            lambda: derivative_lcmv_weights(
                r,
                a_s,
                array,
                center_deg,
                loading_factor=loading,
                step_deg=float(beam_cfg["derivative_step_deg"]),
            )
        )
        methods[ABLATION_SOFT] = _timed(
            lambda: soft_sector_mvdr_weights(
                r,
                a_s,
                sector,
                sector_strength=float(beam_cfg["soft_sector_strength"]),
                loading_factor=loading,
            )
        )
        start = time.perf_counter()
        hard = confidence_region_hybrid_null_weights(
            r,
            a_s,
            sector,
            loading_factor=loading,
            energy_threshold=float(beam_cfg["energy_threshold"]),
            max_rank=int(beam_cfg["max_eigennull_rank"]),
            margin_modes=int(beam_cfg["margin_modes"]),
            soft_strength=0.0,
            white_noise_gain_floor_db=float(beam_cfg["white_noise_gain_floor_db"]),
            condition_limit=float(beam_cfg["condition_limit"]),
        )
        methods[ABLATION_HARD] = WeightDesign(
            hard.weights,
            1000.0 * (time.perf_counter() - start),
            hard.selected_rank,
            hard.energy_coverage,
            hard.constraint_condition,
        )
        start = time.perf_counter()
        full = confidence_region_hybrid_null_weights(
            r,
            a_s,
            sector,
            loading_factor=loading,
            energy_threshold=float(beam_cfg["energy_threshold"]),
            max_rank=int(beam_cfg["max_eigennull_rank"]),
            margin_modes=int(beam_cfg["margin_modes"]),
            soft_strength=float(beam_cfg["soft_sector_strength"]),
            white_noise_gain_floor_db=float(beam_cfg["white_noise_gain_floor_db"]),
            condition_limit=float(beam_cfg["condition_limit"]),
        )
        methods[ABLATION_FULL] = WeightDesign(
            full.weights,
            1000.0 * (time.perf_counter() - start),
            full.selected_rank,
            full.energy_coverage,
            full.constraint_condition,
        )
        methods[ABLATION_DENSE] = _timed(
            lambda: sampled_sector_lcmv_weights(
                r,
                a_s,
                sector,
                n_constraints=min(13, sector.n_grid_points),
                loading_factor=loading,
            )
        )

        for method in ABLATION_ORDER:
            row = _evaluate_design(
                array,
                config,
                setup,
                sector,
                method,
                methods[method],
                inr_db=float(mc["ablation_inr_db"]),
                success_threshold_db=threshold,
            )
            row.update({"sweep": "ablation", "x_value": 0.0, "trial": trial})
            records.append(row)
    summary = _summarize(records, float(mc["confidence"]))
    mark("ablation_done")
    return records, summary


def _flatten(prefix: str, value: Any, output: list[tuple[str, str]]) -> None:
    if isinstance(value, dict):
        for key, nested in value.items():
            _flatten(f"{prefix}.{key}" if prefix else str(key), nested, output)
    elif isinstance(value, (list, tuple)):
        output.append((prefix, json.dumps(value, ensure_ascii=False)))
    elif isinstance(value, float):
        output.append((prefix, f"{value:.6g}"))
    else:
        output.append((prefix, str(value)))


def _write_html_report(output_dir: Path, metrics: dict[str, Any]) -> None:
    flattened: list[tuple[str, str]] = []
    _flatten("", metrics, flattened)
    rows = "\n".join(f"<tr><td>{key}</td><td>{value}</td></tr>" for key, value in flattened)
    images = [
        ("置信域宽零陷机理", "00_cr_hybridnull_mechanism.png"),
        ("点零陷二维响应", "01_point_lcmv_map.png"),
        ("置信域宽零陷二维响应", "02_cr_hybridnull_map.png"),
        ("干扰漂移路径方向切面", "03_drift_cut.png"),
        ("置信域流形能量谱", "04_sector_eigen_energy.png"),
        ("角域子空间秩与最坏响应", "05_rank_tradeoff.png"),
        ("输出SINR—方向漂移", "06_sinr_vs_drift.png"),
        ("防护成功率—方向漂移", "07_protection_rate_vs_drift.png"),
        ("实际干扰响应—方向漂移", "08_null_vs_drift.png"),
        ("输出SINR—快拍数", "09_sinr_vs_snapshots.png"),
        ("输出SINR—阵列相位失配", "10_sinr_vs_phase_error.png"),
        ("输出SINR—置信域宽度", "11_sinr_vs_uncertainty_width.png"),
        ("自适应零陷秩—置信域宽度", "12_rank_vs_uncertainty_width.png"),
        ("输出SINR—输入干扰强度", "13_sinr_vs_inr.png"),
        ("关键工况SINR经验CDF", "14_sinr_cdf_drift6.png"),
        ("组件消融", "15_ablation.png"),
        ("权值更新时间", "16_runtime.png"),
    ]
    cards: list[str] = []
    standalone: list[str] = []
    for title, filename in images:
        cards.append(f'<section><h2>{title}</h2><img src="{filename}" alt="{title}"></section>')
        payload = base64.b64encode((output_dir / filename).read_bytes()).decode("ascii")
        standalone.append(
            f'<section><h2>{title}</h2><img src="data:image/png;base64,{payload}" alt="{title}"></section>'
        )
    card_html = "\n".join(cards)
    standalone_html = "\n".join(standalone)
    html = f"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><title>HPM Digital Twin v0.4 接收防护报告</title>
<style>
body{{font-family:Arial,"Microsoft YaHei",sans-serif;max-width:1180px;margin:34px auto;padding:0 20px;line-height:1.65}}
h1{{margin-bottom:6px}} .note{{padding:14px;border:1px solid #999;border-radius:8px;background:#fafafa}}
img{{max-width:100%;border:1px solid #bbb;border-radius:8px}} section{{margin:34px 0}}
table{{border-collapse:collapse;width:100%;font-size:13px}} td{{border:1px solid #aaa;padding:7px;word-break:break-word}}
code{{background:#eee;padding:2px 5px;border-radius:4px}}
</style></head><body>
<h1>HPM Digital Twin v0.4 — DOA不确定条件下的接收端鲁棒宽零陷防护</h1>
<p class="note"><strong>模型边界：</strong>本报告只研究归一化窄带阵列接收、方向漂移、有限快拍和通道幅相失配。训练期干扰位于感知中心，评估期干扰在置信域附近漂移。所有功率均相对白噪声方差归一化；不包含真实高功率源预算、设备易损阈值或毁伤效能外推。快速配置每点试验次数有限，论文定稿应运行 <code>configs/protection_v04_paper.yaml</code>。</p>
<h2>关键指标</h2><table>{rows}</table>{card_html}
</body></html>"""
    (output_dir / "protection_v04_report.html").write_text(html, encoding="utf-8")
    (output_dir / "protection_v04_report_standalone.html").write_text(
        html.replace(card_html, standalone_html),
        encoding="utf-8",
    )


def _write_paper_tables(
    output_dir: Path,
    summary: Sequence[dict[str, Any]],
    ablation_summary: Sequence[dict[str, Any]],
    runtime_rows: Sequence[dict[str, Any]],
) -> None:
    key_rows = [_select_summary(summary, "drift_deg", 6.0, method) for method in PAPER_METHOD_ORDER]
    _write_dict_csv(output_dir / "paper_table_key_results.csv", key_rows)
    _write_dict_csv(output_dir / "paper_table_ablation.csv", ablation_summary)
    _write_dict_csv(output_dir / "paper_table_runtime.csv", runtime_rows)
    lines = [
        r"\begin{tabular}{lrrrrr}",
        r"\hline",
        r"Method & Output SINR (dB) & 95\% CI & Actual response (dB) & Success & Runtime (ms) \\",
        r"\hline",
    ]
    for row in key_rows:
        lines.append(
            f"{row['method']} & {float(row['mean_output_sinr_db']):.2f} & "
            f"[{float(row['sinr_ci_low_db']):.2f}, {float(row['sinr_ci_high_db']):.2f}] & "
            f"{float(row['mean_actual_null_db']):.2f} & "
            f"{100.0 * float(row['protection_rate']):.1f}\\% & "
            f"{float(row['median_runtime_ms']):.3f} \\\\"
        )
    lines.extend([r"\hline", r"\end{tabular}"])
    (output_dir / "paper_table_key_results.tex").write_text("\n".join(lines), encoding="utf-8")


def _paired_statistics(records: Sequence[dict[str, Any]]) -> dict[str, Any]:
    key = [
        row
        for row in records
        if row["sweep"] == "drift_deg" and np.isclose(float(row["x_value"]), 6.0)
    ]
    by_method: dict[str, list[dict[str, Any]]] = {
        method: sorted((row for row in key if row["method"] == method), key=lambda row: int(row["trial"]))
        for method in METHOD_ORDER
    }
    proposed = np.asarray([float(row["output_sinr_db"]) for row in by_method[METHOD_PROPOSED]])
    output: dict[str, Any] = {}
    for baseline in [METHOD_POINT, METHOD_DERIVATIVE, METHOD_SOFT]:
        values = np.asarray([float(row["output_sinr_db"]) for row in by_method[baseline]])
        differences = proposed - values
        try:
            test = wilcoxon(differences, alternative="greater", zero_method="wilcox")
            p_value = float(test.pvalue)
        except ValueError:
            p_value = 1.0
        output[baseline] = {
            "mean_improvement_db": float(np.mean(differences)),
            "median_improvement_db": float(np.median(differences)),
            "wilcoxon_one_sided_p": p_value,
        }
    return output


def _write_key_findings(output_dir: Path, metrics: dict[str, Any]) -> None:
    key = metrics["key_condition_drift_6deg"]
    proposed = key[METHOD_PROPOSED]
    point = key[METHOD_POINT]
    derivative = key[METHOD_DERIVATIVE]
    soft = key[METHOD_SOFT]
    paired = metrics["paired_statistics_drift_6deg"]
    text = f"""# V0.4 Key Findings

快速配置采用8×8阵列、归一化目标SNR -5 dB、训练期干扰INR 30 dB，并在权值更新后引入随机方向漂移。每个标准扫参点运行 {metrics['monte_carlo_trials']} 次配对试验。

## 6°方向漂移关键工况

- Point-LCMV：平均输出SINR {float(point['mean_output_sinr_db']):.2f} dB，防护成功率 {100.0 * float(point['protection_rate']):.1f}% 。
- Derivative-LCMV：平均输出SINR {float(derivative['mean_output_sinr_db']):.2f} dB，防护成功率 {100.0 * float(derivative['protection_rate']):.1f}% 。
- Sector-MVDR：平均输出SINR {float(soft['mean_output_sinr_db']):.2f} dB，防护成功率 {100.0 * float(soft['protection_rate']):.1f}% 。
- CR-HybridNull：平均输出SINR {float(proposed['mean_output_sinr_db']):.2f} dB，95% CI [{float(proposed['sinr_ci_low_db']):.2f}, {float(proposed['sinr_ci_high_db']):.2f}] dB，防护成功率 {100.0 * float(proposed['protection_rate']):.1f}% 。

CR-HybridNull相对Point-LCMV的平均提升为 {float(paired[METHOD_POINT]['mean_improvement_db']):.2f} dB，配对单侧Wilcoxon检验 p={float(paired[METHOD_POINT]['wilcoxon_one_sided_p']):.3g}；相对Derivative-LCMV提升 {float(paired[METHOD_DERIVATIVE]['mean_improvement_db']):.2f} dB；相对Sector-MVDR提升 {float(paired[METHOD_SOFT]['mean_improvement_db']):.2f} dB。

## 解释边界

这些结果证明的是：把感知不确定区间显式映射为接收阵列的角域子空间约束，可提高权值在更新滞后和方向漂移下的稳定性。结果不等价于真实设备防护等级，也不包含绝对场强、器件阈值或毁伤推断。
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
    sector = _sector_from_config(array, config)
    mark("config_loaded")

    plot_mechanism(
        output_dir / "00_cr_hybridnull_mechanism.png",
        output_dir / "00_cr_hybridnull_mechanism.svg",
    )
    representative_metrics, representative_designs, representative_setup = _representative_case(
        array,
        config,
        sector,
        output_dir,
    )
    mark("representative_case_done")

    records = _run_sweeps(array, config, sector, mark)
    summary = _summarize(records, float(config["monte_carlo"]["confidence"]))
    _write_dict_csv(output_dir / "monte_carlo_trials.csv", records)
    _write_dict_csv(output_dir / "monte_carlo_summary.csv", summary)
    mark("monte_carlo_done")

    ablation_records, ablation_summary = _run_ablation(array, config, sector, mark)
    _write_dict_csv(output_dir / "ablation_trials.csv", ablation_records)
    _write_dict_csv(output_dir / "ablation_summary.csv", ablation_summary)

    drift_summary = [row for row in summary if row["sweep"] == "drift_deg"]
    snapshot_summary = [row for row in summary if row["sweep"] == "snapshots"]
    phase_summary = [row for row in summary if row["sweep"] == "phase_error_std_deg"]
    width_summary = [row for row in summary if row["sweep"] == "uncertainty_half_width_deg"]
    inr_summary = [row for row in summary if row["sweep"] == "inr_db"]
    threshold = float(config["monte_carlo"]["protection_sinr_threshold_db"])

    plot_metric_curve(
        drift_summary,
        mean_key="mean_output_sinr_db",
        low_key="sinr_ci_low_db",
        high_key="sinr_ci_high_db",
        xlabel="Direction drift magnitude (deg)",
        ylabel="Mean output SINR (dB)",
        title="Protection under post-update interferer direction drift (95% CI)",
        output=output_dir / "06_sinr_vs_drift.png",
        method_order=METHOD_ORDER,
    )
    plot_metric_curve(
        drift_summary,
        mean_key="protection_rate",
        low_key="protection_ci_low",
        high_key="protection_ci_high",
        xlabel="Direction drift magnitude (deg)",
        ylabel="Protection success probability",
        title=f"Protection probability (output SINR >= {threshold:g} dB)",
        output=output_dir / "07_protection_rate_vs_drift.png",
        method_order=METHOD_ORDER,
        y_limits=(0.0, 1.05),
    )
    plot_metric_curve(
        drift_summary,
        mean_key="mean_actual_null_db",
        low_key="actual_null_ci_low_db",
        high_key="actual_null_ci_high_db",
        xlabel="Direction drift magnitude (deg)",
        ylabel="Response at actual interferer direction (dB)",
        title="Null retention after direction drift (95% CI; lower is better)",
        output=output_dir / "08_null_vs_drift.png",
        method_order=METHOD_ORDER,
    )
    plot_metric_curve(
        snapshot_summary,
        mean_key="mean_output_sinr_db",
        low_key="sinr_ci_low_db",
        high_key="sinr_ci_high_db",
        xlabel="Training snapshots",
        ylabel="Mean output SINR (dB)",
        title="Finite-snapshot receive protection at 6-degree drift (95% CI)",
        output=output_dir / "09_sinr_vs_snapshots.png",
        method_order=METHOD_ORDER,
    )
    plot_metric_curve(
        phase_summary,
        mean_key="mean_output_sinr_db",
        low_key="sinr_ci_low_db",
        high_key="sinr_ci_high_db",
        xlabel="Sensor phase-error standard deviation (deg)",
        ylabel="Mean output SINR (dB)",
        title="Robustness to uncalibrated channel phase errors (95% CI)",
        output=output_dir / "10_sinr_vs_phase_error.png",
        method_order=METHOD_ORDER,
    )
    plot_metric_curve(
        width_summary,
        mean_key="mean_output_sinr_db",
        low_key="sinr_ci_low_db",
        high_key="sinr_ci_high_db",
        xlabel="Confidence-region half width (deg)",
        ylabel="Mean output SINR (dB)",
        title="Coverage-versus-degrees-of-freedom tradeoff at 6-degree drift",
        output=output_dir / "11_sinr_vs_uncertainty_width.png",
        method_order=METHOD_ORDER,
    )
    plot_metric_curve(
        [row for row in width_summary if row["method"] == METHOD_PROPOSED],
        mean_key="mean_selected_rank",
        low_key=None,
        high_key=None,
        xlabel="Confidence-region half width (deg)",
        ylabel="Mean selected hard-null rank",
        title="Adaptive angular-subspace rank",
        output=output_dir / "12_rank_vs_uncertainty_width.png",
        method_order=[METHOD_PROPOSED],
    )
    plot_metric_curve(
        inr_summary,
        mean_key="mean_output_sinr_db",
        low_key="sinr_ci_low_db",
        high_key="sinr_ci_high_db",
        xlabel="Training and evaluation INR (dB)",
        ylabel="Mean output SINR (dB)",
        title="Protection versus normalized interference strength at 6-degree drift",
        output=output_dir / "13_sinr_vs_inr.png",
        method_order=METHOD_ORDER,
    )
    cdf_records = [
        row
        for row in records
        if row["sweep"] == "drift_deg" and np.isclose(float(row["x_value"]), 6.0)
    ]
    plot_cdf(
        cdf_records,
        value_key="output_sinr_db",
        xlabel="Output SINR (dB)",
        title="Output-SINR distribution at 6-degree direction drift",
        method_order=METHOD_ORDER,
        output=output_dir / "14_sinr_cdf_drift6.png",
    )
    ordered_ablation = sorted(
        ablation_summary,
        key=lambda row: ABLATION_ORDER.index(str(row["method"])),
    )
    plot_ablation(ordered_ablation, output=output_dir / "15_ablation.png")

    runtime_rows: list[dict[str, Any]] = []
    for method in METHOD_ORDER:
        values = np.asarray(
            [
                float(row["runtime_ms"])
                for row in records
                if row["sweep"] == "drift_deg" and row["method"] == method
            ]
        )
        runtime_rows.append(
            {
                "method": method,
                "median_runtime_ms": float(np.median(values)),
                "mean_runtime_ms": float(np.mean(values)),
                "p95_runtime_ms": float(np.quantile(values, 0.95)),
            }
        )
    plot_runtime(runtime_rows, output_dir / "16_runtime.png")
    mark("figures_done")

    paired = _paired_statistics(records)
    key_rows = {
        method: _select_summary(summary, "drift_deg", 6.0, method) for method in METHOD_ORDER
    }
    proposed_width_rows = [row for row in width_summary if row["method"] == METHOD_PROPOSED]
    best_width = max(proposed_width_rows, key=lambda row: float(row["mean_output_sinr_db"]))
    metrics: dict[str, Any] = {
        "version": "0.4.0",
        "model_scope": "normalized defensive receive beamforming",
        "array": {
            "shape": [array.nx, array.ny],
            "elements": array.n_elements,
            "frequency_hz": array.frequency_hz,
            "spacing_lambda": float(array.dx_m / array.wavelength_m),
        },
        "scenario": config["scenario"],
        "confidence_region": {
            "center_deg": list(sector.center_deg),
            "half_width_deg": list(sector.half_width_deg),
            "grid_points": sector.n_grid_points,
            "nominal_energy_rank": sector_energy_rank(
                sector,
                float(config["beamforming"]["energy_threshold"]),
                max_rank=int(config["beamforming"]["max_eigennull_rank"]),
                margin_modes=int(config["beamforming"]["margin_modes"]),
            ),
        },
        "representative_case": representative_metrics,
        "key_condition_drift_6deg": key_rows,
        "paired_statistics_drift_6deg": paired,
        "best_tested_uncertainty_half_width_deg": float(best_width["x_value"]),
        "best_tested_uncertainty_mean_sinr_db": float(best_width["mean_output_sinr_db"]),
        "monte_carlo_trials": int(config["monte_carlo"]["trials"]),
        "ablation_trials": int(config["monte_carlo"]["ablation_trials"]),
        "runtime_total_s": float(time.perf_counter() - start_time),
        "environment": {
            "python": sys.version.split()[0],
            "platform": platform.platform(),
            "numpy": np.__version__,
            "scipy": scipy.__version__,
            "matplotlib": matplotlib.__version__,
        },
    }
    (output_dir / "results_summary.json").write_text(
        json.dumps(metrics, indent=2, ensure_ascii=False, allow_nan=False),
        encoding="utf-8",
    )
    (output_dir / "config_snapshot.yaml").write_text(
        yaml.safe_dump(config, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )
    (output_dir / "environment.json").write_text(
        json.dumps(metrics["environment"], indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    _write_paper_tables(output_dir, summary, ordered_ablation, runtime_rows)

    figure_rows = [
        {"figure": index, "title": title, "filename": filename}
        for index, (title, filename) in enumerate(
            [
                ("Mechanism", "00_cr_hybridnull_mechanism.png"),
                ("Point response map", "01_point_lcmv_map.png"),
                ("Proposed response map", "02_cr_hybridnull_map.png"),
                ("Drift cut", "03_drift_cut.png"),
                ("Sector eigenspectrum", "04_sector_eigen_energy.png"),
                ("Rank tradeoff", "05_rank_tradeoff.png"),
                ("SINR versus drift", "06_sinr_vs_drift.png"),
                ("Protection probability", "07_protection_rate_vs_drift.png"),
                ("Actual null versus drift", "08_null_vs_drift.png"),
                ("SINR versus snapshots", "09_sinr_vs_snapshots.png"),
                ("SINR versus phase error", "10_sinr_vs_phase_error.png"),
                ("SINR versus confidence width", "11_sinr_vs_uncertainty_width.png"),
                ("Selected rank versus confidence width", "12_rank_vs_uncertainty_width.png"),
                ("SINR versus INR", "13_sinr_vs_inr.png"),
                ("SINR CDF", "14_sinr_cdf_drift6.png"),
                ("Ablation", "15_ablation.png"),
                ("Runtime", "16_runtime.png"),
            ]
        )
    ]
    _write_dict_csv(output_dir / "figure_manifest.csv", figure_rows)
    _write_html_report(output_dir, metrics)
    _write_key_findings(output_dir, metrics)
    readme = f"""# V0.4 receive-protection outputs

- Standalone report: `protection_v04_report_standalone.html`
- Key findings: `KEY_FINDINGS.md`
- Raw paired trials: `monte_carlo_trials.csv`
- Aggregated confidence intervals: `monte_carlo_summary.csv`
- Representative arrays and responses: `representative_case.npz`
- Paper tables: `paper_table_key_results.csv/.tex`

Fast configuration: {int(config['monte_carlo']['trials'])} trials per standard point.  Use the paper configuration for final statistical claims.
"""
    (output_dir / "README.md").write_text(readme, encoding="utf-8")
    checksum_files = [
        "results_summary.json",
        "monte_carlo_trials.csv",
        "monte_carlo_summary.csv",
        "ablation_trials.csv",
        "representative_case.npz",
        "protection_v04_report_standalone.html",
    ]
    _write_checksums(output_dir, checksum_files)
    mark("complete")
    return metrics


def cli(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default="configs/protection_v04.yaml")
    parser.add_argument("--output", default="outputs_v04_protection")
    args = parser.parse_args(argv)
    with threadpool_limits(limits=1, user_api="blas"):
        metrics = run(args.config, args.output)
    key = metrics["key_condition_drift_6deg"]
    print(json.dumps({METHOD_POINT: key[METHOD_POINT], METHOD_PROPOSED: key[METHOD_PROPOSED]}, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(cli())

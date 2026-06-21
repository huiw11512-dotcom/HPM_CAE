"""V0.3 robust coherent-multipath perception workflow.

The workflow remains a normalized array-processing study.  It contains no
absolute high-power source budget, device susceptibility threshold, or damage
prediction.  PAWR-MUSIC combines transparent data-reliability weighting,
light URA covariance regularization, broad path-sector priors, continuous
subspace fitting, and low-rank covariance reconstruction.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Sequence
import base64
import csv
import json
import platform
import sys
import time

import matplotlib
import numpy as np
import scipy
import yaml

from hpm_platform.evaluation.doa_statistics import (
    match_directions,
    mean_confidence_interval,
    wilson_interval,
)
from hpm_platform.perception.esprit import esprit_2d_from_covariance
from hpm_platform.perception.music import MusicGridScanner, sample_covariance
from hpm_platform.perception.robust_covariance import (
    adaptive_spatially_smoothed_covariance,
    bttb_projection,
    pawr_estimate,
    refine_music_peaks,
)
from hpm_platform.perception.spatial_smoothing import spatially_smoothed_covariance
from hpm_platform.physics.array_geometry import C0, RectangularArray
from hpm_platform.signal.multipath import (
    CoherentEmitter,
    CoherentPath,
    draw_sensor_gain_phase_errors,
    simulate_coherent_multipath,
)
from hpm_platform.visualization.perception_v02 import plot_music_spectrum
from hpm_platform.visualization.perception_v03 import (
    plot_ablation,
    plot_eigenspectrum_comparison,
    plot_error_cdf,
    plot_metric_curve,
    plot_pawr_mechanism,
    plot_prior_map,
    plot_runtime,
    plot_sensor_reliability,
    plot_subarray_weights,
)


METHOD_FBSS = "FBSS-MUSIC"
METHOD_BTTB = "BTTB-FBSS-MUSIC"
METHOD_ESPRIT = "FBSS-ESPRIT"
METHOD_PAWR = "PAWR-MUSIC"
METHOD_ORDER = [METHOD_FBSS, METHOD_BTTB, METHOD_ESPRIT, METHOD_PAWR]

ABLATION_FBSS = "Uniform FBSS"
ABLATION_WEIGHTED = "Health-weighted FBSS"
ABLATION_OFFGRID = "Weighted + off-grid fit"
ABLATION_FULL = "Full PAWR"


@dataclass(frozen=True)
class SimulatedTrial:
    snapshots: np.ndarray
    fault_indices: tuple[int, ...]
    sensor_gains: np.ndarray


@dataclass(frozen=True)
class MethodEstimate:
    estimates: tuple[tuple[float, float], ...]
    runtime_ms: float
    covariance: np.ndarray
    spectrum: np.ndarray | None = None
    valid: bool = True
    details: Any = None


def _array_from_config(config: dict[str, Any]) -> RectangularArray:
    cfg = config["array"]
    frequency = float(cfg["frequency_hz"])
    wavelength = C0 / frequency
    spacing = float(cfg["spacing_lambda"]) * wavelength
    return RectangularArray(
        nx=int(cfg["nx"]),
        ny=int(cfg["ny"]),
        frequency_hz=frequency,
        dx_m=spacing,
        dy_m=spacing,
    )


def _truths_from_config(config: dict[str, Any]) -> tuple[tuple[float, float], ...]:
    direct = config["scenario"]["direct_path"]
    echo = config["scenario"]["coherent_echo"]
    return (
        (float(direct["theta_deg"]), float(direct["phi_deg"])),
        (float(echo["theta_deg"]), float(echo["phi_deg"])),
    )


def _emitter_from_config(config: dict[str, Any], snr_db: float) -> CoherentEmitter:
    direct = config["scenario"]["direct_path"]
    echo = config["scenario"]["coherent_echo"]
    return CoherentEmitter(
        reference_power_db=float(snr_db),
        paths=(
            CoherentPath(
                theta_deg=float(direct["theta_deg"]),
                phi_deg=float(direct["phi_deg"]),
                relative_power_db=float(direct["relative_power_db"]),
                phase_deg=float(direct["phase_deg"]),
                label="direct",
            ),
            CoherentPath(
                theta_deg=float(echo["theta_deg"]),
                phi_deg=float(echo["phi_deg"]),
                relative_power_db=float(echo["relative_power_db"]),
                phase_deg=float(echo["phase_deg"]),
                label="coherent_echo",
            ),
        ),
        label="source_1",
    )


def _scan_grids(config: dict[str, Any]) -> tuple[np.ndarray, np.ndarray]:
    cfg = config["scan"]
    theta = np.arange(
        float(cfg["theta_min_deg"]),
        float(cfg["theta_max_deg"]) + 0.5 * float(cfg["theta_step_deg"]),
        float(cfg["theta_step_deg"]),
    )
    phi = np.arange(
        float(cfg["phi_min_deg"]),
        float(cfg["phi_max_deg"]) + 0.5 * float(cfg["phi_step_deg"]),
        float(cfg["phi_step_deg"]),
    )
    return theta, phi


def _prior_centers(config: dict[str, Any], bias_deg: float = 0.0) -> tuple[tuple[float, float], ...]:
    centers = config["pawr"]["prior_centers_deg"]
    mc = config.get("monte_carlo", {})
    theta_scale = float(mc.get("prior_bias_theta_scale", 1.0))
    phi_scale = float(mc.get("prior_bias_phi_scale", 0.5))
    return tuple(
        (
            float(center[0]) + float(bias_deg) * theta_scale,
            float(center[1]) + float(bias_deg) * phi_scale,
        )
        for center in centers
    )


def _simulate_trial(
    array: RectangularArray,
    config: dict[str, Any],
    *,
    snr_db: float,
    snapshots: int,
    fault_count: int,
    seed: int,
) -> SimulatedTrial:
    if fault_count < 0:
        raise ValueError("fault_count must be non-negative")
    rng = np.random.default_rng(int(seed))
    mismatch = config["channel_mismatch"]
    gains = draw_sensor_gain_phase_errors(
        array.n_elements,
        rng,
        gain_std_db=float(mismatch["sensor_gain_std_db"]),
        phase_std_deg=float(mismatch["sensor_phase_std_deg"]),
    )
    candidates = np.asarray(mismatch["fault_candidate_indices"], dtype=int)
    if fault_count > candidates.size:
        raise ValueError("fault_count exceeds configured candidate channels")
    faults = tuple(int(value) for value in rng.choice(candidates, size=fault_count, replace=False))
    if faults:
        fault_gain_db = rng.normal(
            float(mismatch["fault_gain_mean_db"]),
            float(mismatch["fault_gain_std_db"]),
            len(faults),
        )
        fault_phase_deg = rng.normal(
            float(mismatch["fault_phase_mean_deg"]),
            float(mismatch["fault_phase_std_deg"]),
            len(faults),
        )
        gains[list(faults)] *= 10.0 ** (fault_gain_db / 20.0) * np.exp(
            1j * np.deg2rad(fault_phase_deg)
        )

    signal_seed = int(rng.integers(0, np.iinfo(np.int32).max))
    x, _ = simulate_coherent_multipath(
        array,
        [_emitter_from_config(config, float(snr_db))],
        n_snapshots=int(snapshots),
        noise_power=1.0,
        seed=signal_seed,
        sensor_gains=gains,
    )
    if faults:
        extra_power = 10.0 ** (float(mismatch["fault_extra_noise_db"]) / 10.0)
        noise = (
            rng.standard_normal((len(faults), snapshots))
            + 1j * rng.standard_normal((len(faults), snapshots))
        ) / np.sqrt(2.0)
        x[list(faults), :] += np.sqrt(extra_power) * noise
    return SimulatedTrial(x, faults, gains)


def _pawr_kwargs(config: dict[str, Any]) -> dict[str, Any]:
    cfg = config["pawr"]
    return {
        "prior_sigma_deg": float(cfg["prior_sigma_deg"]),
        "prior_strength": float(cfg["prior_strength"]),
        "selection_exponent": float(cfg["selection_exponent"]),
        "search_radius_sigma": float(cfg["search_radius_sigma"]),
        "structure_blend": float(cfg["structure_blend"]),
        "forward_backward": bool(config["spatial_smoothing"]["forward_backward"]),
        "health_window": int(cfg["health_window"]),
        "health_tuning": float(cfg["health_tuning"]),
        "reliability_floor": float(cfg["reliability_floor"]),
        "weight_exponent": float(cfg["weight_exponent"]),
        "weight_floor_fraction": float(cfg["weight_floor_fraction"]),
    }


def _estimate_all(
    x: np.ndarray,
    array: RectangularArray,
    subarray: RectangularArray,
    scanner: MusicGridScanner,
    config: dict[str, Any],
    *,
    prior_centers_deg: Sequence[tuple[float, float]],
) -> dict[str, MethodEstimate]:
    smooth_cfg = config["spatial_smoothing"]
    scan_cfg = config["scan"]
    scan_kwargs = {
        "diagonal_loading": float(smooth_cfg["diagonal_loading"]),
        "n_peaks": 2,
        "min_separation_deg": float(scan_cfg["min_peak_separation_deg"]),
    }

    t0 = time.perf_counter()
    smooth = spatially_smoothed_covariance(
        x,
        array,
        int(smooth_cfg["subarray_nx"]),
        int(smooth_cfg["subarray_ny"]),
        forward_backward=bool(smooth_cfg["forward_backward"]),
        diagonal_loading=0.0,
    )
    smooth_ms = 1000.0 * (time.perf_counter() - t0)

    t0 = time.perf_counter()
    fbss_result = scanner.scan_covariance(smooth.covariance, 2, **scan_kwargs)
    fbss_ms = smooth_ms + 1000.0 * (time.perf_counter() - t0)

    t0 = time.perf_counter()
    structured = bttb_projection(
        smooth.covariance,
        subarray.nx,
        subarray.ny,
        project_to_psd=True,
    )
    bttb_result = scanner.scan_covariance(structured, 2, **scan_kwargs)
    bttb_ms = smooth_ms + 1000.0 * (time.perf_counter() - t0)

    t0 = time.perf_counter()
    esprit_result = esprit_2d_from_covariance(smooth.covariance, subarray, 2)
    esprit_ms = smooth_ms + 1000.0 * (time.perf_counter() - t0)
    esprit_valid = len(esprit_result.estimates) >= 2

    t0 = time.perf_counter()
    pawr_result = pawr_estimate(
        x,
        array,
        scanner,
        2,
        int(smooth_cfg["subarray_nx"]),
        int(smooth_cfg["subarray_ny"]),
        prior_centers_deg,
        **_pawr_kwargs(config),
    )
    pawr_ms = 1000.0 * (time.perf_counter() - t0)
    pawr_spectrum = scanner.scan_covariance(
        pawr_result.covariance,
        2,
        **scan_kwargs,
    ).spectrum

    return {
        METHOD_FBSS: MethodEstimate(
            tuple((float(p[0]), float(p[1])) for p in fbss_result.peaks),
            fbss_ms,
            smooth.covariance,
            fbss_result.spectrum,
            True,
            smooth,
        ),
        METHOD_BTTB: MethodEstimate(
            tuple((float(p[0]), float(p[1])) for p in bttb_result.peaks),
            bttb_ms,
            structured,
            bttb_result.spectrum,
            True,
            None,
        ),
        METHOD_ESPRIT: MethodEstimate(
            tuple(esprit_result.estimates),
            esprit_ms,
            smooth.covariance,
            None,
            esprit_valid,
            esprit_result,
        ),
        METHOD_PAWR: MethodEstimate(
            tuple(pawr_result.estimates),
            pawr_ms,
            pawr_result.covariance,
            pawr_spectrum,
            True,
            pawr_result,
        ),
    }


def _record(
    *,
    sweep: str,
    x_value: float,
    method: str,
    trial: int,
    estimate: MethodEstimate,
    truths: Sequence[tuple[float, float]],
    tolerance_deg: float,
    failure_penalty_deg: float,
) -> dict[str, Any]:
    valid = bool(estimate.valid and len(estimate.estimates) >= len(truths))
    if valid:
        matched = match_directions(estimate.estimates, truths)
        ordered = matched.ordered_estimates
        errors = matched.errors_deg
        rmse = matched.rmse_deg
        maximum = matched.max_error_deg
    else:
        ordered = tuple((float("nan"), float("nan")) for _ in truths)
        errors = tuple(float(failure_penalty_deg) for _ in truths)
        rmse = float(failure_penalty_deg)
        maximum = float(failure_penalty_deg)
    return {
        "sweep": sweep,
        "x_value": float(x_value),
        "method": method,
        "trial": int(trial),
        "rmse_deg": float(rmse),
        "max_error_deg": float(maximum),
        "resolved": int(valid and maximum <= tolerance_deg),
        "valid": int(valid),
        "runtime_ms": float(estimate.runtime_ms),
        "direct_error_deg": float(errors[0]),
        "echo_error_deg": float(errors[1]),
        "direct_est_theta_deg": float(ordered[0][0]),
        "direct_est_phi_deg": float(ordered[0][1]),
        "echo_est_theta_deg": float(ordered[1][0]),
        "echo_est_phi_deg": float(ordered[1][1]),
    }


def _summarize_records(
    records: list[dict[str, Any]], confidence: float
) -> list[dict[str, Any]]:
    keys = sorted(
        {
            (str(row["sweep"]), float(row["x_value"]), str(row["method"]))
            for row in records
        }
    )
    output: list[dict[str, Any]] = []
    for sweep, x_value, method in keys:
        group = [
            row
            for row in records
            if row["sweep"] == sweep
            and np.isclose(float(row["x_value"]), x_value)
            and row["method"] == method
        ]
        rmse = np.asarray([float(row["rmse_deg"]) for row in group])
        maximum = np.asarray([float(row["max_error_deg"]) for row in group])
        runtimes = np.asarray([float(row["runtime_ms"]) for row in group])
        resolved = int(sum(int(row["resolved"]) for row in group))
        valid = int(sum(int(row["valid"]) for row in group))
        mean, low, high = mean_confidence_interval(rmse, confidence)
        rate, rate_low, rate_high = wilson_interval(resolved, len(group), confidence)
        valid_rate, valid_low, valid_high = wilson_interval(valid, len(group), confidence)
        output.append(
            {
                "sweep": sweep,
                "x_value": float(x_value),
                "method": method,
                "n_trials": len(group),
                "mean_rmse_deg": float(mean),
                "rmse_ci_low_deg": float(max(0.0, low)),
                "rmse_ci_high_deg": float(high),
                "median_rmse_deg": float(np.median(rmse)),
                "mean_max_error_deg": float(np.mean(maximum)),
                "resolution_rate": float(rate),
                "resolution_ci_low": float(rate_low),
                "resolution_ci_high": float(rate_high),
                "valid_rate": float(valid_rate),
                "valid_ci_low": float(valid_low),
                "valid_ci_high": float(valid_high),
                "median_runtime_ms": float(np.median(runtimes)),
                "mean_runtime_ms": float(np.mean(runtimes)),
            }
        )
    return output


def _select_summary(
    summary: list[dict[str, Any]], sweep: str, x_value: float, method: str
) -> dict[str, Any]:
    return next(
        row
        for row in summary
        if row["sweep"] == sweep
        and np.isclose(float(row["x_value"]), float(x_value))
        and row["method"] == method
    )


def _write_dict_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        raise ValueError("Cannot write empty CSV")
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def _run_standard_sweeps(
    *,
    array: RectangularArray,
    subarray: RectangularArray,
    scanner: MusicGridScanner,
    config: dict[str, Any],
    truths: Sequence[tuple[float, float]],
    mark,
) -> list[dict[str, Any]]:
    mc = config["monte_carlo"]
    trials = int(mc["trials"])
    tolerance = float(mc["resolution_tolerance_deg"])
    penalty = float(mc["failure_penalty_deg"])
    base_seed = int(config["seed"])
    records: list[dict[str, Any]] = []

    specifications = [
        (
            "snr_db",
            [float(v) for v in mc["snr_sweep_db"]],
            lambda value: (
                float(value),
                int(mc["snapshots_for_snr_sweep"]),
                int(mc["faults_for_snr_sweep"]),
            ),
        ),
        (
            "fault_count",
            [float(v) for v in mc["fault_count_sweep"]],
            lambda value: (
                float(mc["snr_db_for_fault_sweep"]),
                int(mc["snapshots_for_fault_sweep"]),
                int(value),
            ),
        ),
        (
            "snapshots",
            [float(v) for v in mc["snapshot_sweep"]],
            lambda value: (
                float(mc["snr_db_for_snapshot_sweep"]),
                int(value),
                int(mc["faults_for_snapshot_sweep"]),
            ),
        ),
    ]

    for sweep_index, (sweep, values, builder) in enumerate(specifications, start=1):
        for value_index, value in enumerate(values):
            snr_db, snapshots, fault_count = builder(value)
            for trial in range(trials):
                seed = base_seed + sweep_index * 10_000_000 + value_index * 10_000 + trial
                simulated = _simulate_trial(
                    array,
                    config,
                    snr_db=snr_db,
                    snapshots=snapshots,
                    fault_count=fault_count,
                    seed=seed,
                )
                estimates = _estimate_all(
                    simulated.snapshots,
                    array,
                    subarray,
                    scanner,
                    config,
                    prior_centers_deg=_prior_centers(config),
                )
                for method in METHOD_ORDER:
                    records.append(
                        _record(
                            sweep=sweep,
                            x_value=value,
                            method=method,
                            trial=trial,
                            estimate=estimates[method],
                            truths=truths,
                            tolerance_deg=tolerance,
                            failure_penalty_deg=penalty,
                        )
                    )
            mark(f"sweep_{sweep}_{value:g}_done")
    return records


def _run_prior_bias_sweep(
    *,
    array: RectangularArray,
    subarray: RectangularArray,
    scanner: MusicGridScanner,
    config: dict[str, Any],
    truths: Sequence[tuple[float, float]],
    mark,
) -> list[dict[str, Any]]:
    mc = config["monte_carlo"]
    trials = int(mc["trials"])
    tolerance = float(mc["resolution_tolerance_deg"])
    penalty = float(mc["failure_penalty_deg"])
    values = [float(v) for v in mc["prior_bias_sweep_deg"]]
    base_seed = int(config["seed"]) + 40_000_000
    output: list[dict[str, Any]] = []

    # Use identical data for all bias levels in each trial.  This isolates the
    # prior-misspecification effect and avoids conflating it with noise draws.
    for trial in range(trials):
        simulated = _simulate_trial(
            array,
            config,
            snr_db=float(mc["snr_db_for_prior_bias_sweep"]),
            snapshots=int(mc["snapshots_for_prior_bias_sweep"]),
            fault_count=int(mc["faults_for_prior_bias_sweep"]),
            seed=base_seed + trial,
        )
        baseline = _estimate_all(
            simulated.snapshots,
            array,
            subarray,
            scanner,
            config,
            prior_centers_deg=_prior_centers(config),
        )
        for value in values:
            for method in [METHOD_FBSS, METHOD_BTTB, METHOD_ESPRIT]:
                output.append(
                    _record(
                        sweep="prior_bias_deg",
                        x_value=value,
                        method=method,
                        trial=trial,
                        estimate=baseline[method],
                        truths=truths,
                        tolerance_deg=tolerance,
                        failure_penalty_deg=penalty,
                    )
                )
            t0 = time.perf_counter()
            pawr_result = pawr_estimate(
                simulated.snapshots,
                array,
                scanner,
                2,
                int(config["spatial_smoothing"]["subarray_nx"]),
                int(config["spatial_smoothing"]["subarray_ny"]),
                _prior_centers(config, value),
                **_pawr_kwargs(config),
            )
            estimate = MethodEstimate(
                estimates=tuple(pawr_result.estimates),
                runtime_ms=1000.0 * (time.perf_counter() - t0),
                covariance=pawr_result.covariance,
                valid=True,
                details=pawr_result,
            )
            output.append(
                _record(
                    sweep="prior_bias_deg",
                    x_value=value,
                    method=METHOD_PAWR,
                    trial=trial,
                    estimate=estimate,
                    truths=truths,
                    tolerance_deg=tolerance,
                    failure_penalty_deg=penalty,
                )
            )
        mark(f"prior_bias_trial_{trial + 1}_done")
    return output


def _run_ablation(
    *,
    array: RectangularArray,
    scanner: MusicGridScanner,
    config: dict[str, Any],
    truths: Sequence[tuple[float, float]],
    mark,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    mc = config["monte_carlo"]
    trials = int(mc["trials"])
    tolerance = float(mc["resolution_tolerance_deg"])
    penalty = float(mc["failure_penalty_deg"])
    smooth_cfg = config["spatial_smoothing"]
    pawr_cfg = config["pawr"]
    scan_kwargs = {
        "diagonal_loading": float(smooth_cfg["diagonal_loading"]),
        "n_peaks": 2,
        "min_separation_deg": float(config["scan"]["min_peak_separation_deg"]),
    }
    records: list[dict[str, Any]] = []
    base_seed = int(config["seed"]) + 50_000_000

    for trial in range(trials):
        simulated = _simulate_trial(
            array,
            config,
            snr_db=float(mc["ablation_snr_db"]),
            snapshots=int(mc["ablation_snapshots"]),
            fault_count=int(mc["ablation_fault_count"]),
            seed=base_seed + trial,
        )
        x = simulated.snapshots

        t0 = time.perf_counter()
        uniform = spatially_smoothed_covariance(
            x,
            array,
            int(smooth_cfg["subarray_nx"]),
            int(smooth_cfg["subarray_ny"]),
            forward_backward=bool(smooth_cfg["forward_backward"]),
        )
        uniform_scan = scanner.scan_covariance(uniform.covariance, 2, **scan_kwargs)
        uniform_est = MethodEstimate(
            tuple((float(p[0]), float(p[1])) for p in uniform_scan.peaks),
            1000.0 * (time.perf_counter() - t0),
            uniform.covariance,
        )

        t0 = time.perf_counter()
        adaptive = adaptive_spatially_smoothed_covariance(
            x,
            array,
            int(smooth_cfg["subarray_nx"]),
            int(smooth_cfg["subarray_ny"]),
            forward_backward=bool(smooth_cfg["forward_backward"]),
            health_window=int(pawr_cfg["health_window"]),
            health_tuning=float(pawr_cfg["health_tuning"]),
            reliability_floor=float(pawr_cfg["reliability_floor"]),
            weight_exponent=float(pawr_cfg["weight_exponent"]),
            weight_floor_fraction=float(pawr_cfg["weight_floor_fraction"]),
        )
        adaptive_scan = scanner.scan_covariance(adaptive.covariance, 2, **scan_kwargs)
        adaptive_ms = 1000.0 * (time.perf_counter() - t0)
        adaptive_est = MethodEstimate(
            tuple((float(p[0]), float(p[1])) for p in adaptive_scan.peaks),
            adaptive_ms,
            adaptive.covariance,
        )

        t0 = time.perf_counter()
        offgrid = refine_music_peaks(
            adaptive.covariance,
            scanner,
            2,
            local_radius_deg=2.0,
            min_separation_deg=float(config["scan"]["min_peak_separation_deg"]),
        )
        offgrid_est = MethodEstimate(
            offgrid,
            adaptive_ms + 1000.0 * (time.perf_counter() - t0),
            adaptive.covariance,
        )

        t0 = time.perf_counter()
        full = pawr_estimate(
            x,
            array,
            scanner,
            2,
            int(smooth_cfg["subarray_nx"]),
            int(smooth_cfg["subarray_ny"]),
            _prior_centers(config),
            **_pawr_kwargs(config),
        )
        full_est = MethodEstimate(
            tuple(full.estimates),
            1000.0 * (time.perf_counter() - t0),
            full.covariance,
        )

        for method, estimate in [
            (ABLATION_FBSS, uniform_est),
            (ABLATION_WEIGHTED, adaptive_est),
            (ABLATION_OFFGRID, offgrid_est),
            (ABLATION_FULL, full_est),
        ]:
            records.append(
                _record(
                    sweep="ablation",
                    x_value=0.0,
                    method=method,
                    trial=trial,
                    estimate=estimate,
                    truths=truths,
                    tolerance_deg=tolerance,
                    failure_penalty_deg=penalty,
                )
            )
    summary = _summarize_records(records, float(mc["confidence"]))
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
    rows = "\n".join(f"<tr><td>{k}</td><td>{v}</td></tr>" for k, v in flattened)
    images = [
        ("PAWR 机理与数据流", "00_pawr_mechanism.png"),
        ("代表场景：传统 MUSIC", "01_standard_music_spectrum.png"),
        ("代表场景：FBSS-MUSIC", "02_fbss_music_spectrum.png"),
        ("代表场景：BTTB-FBSS-MUSIC", "03_bttb_music_spectrum.png"),
        ("代表场景：PAWR 重构谱", "04_pawr_music_spectrum.png"),
        ("通道健康度", "05_sensor_reliability.png"),
        ("自适应子阵权重", "06_subarray_weights.png"),
        ("宽松先验与连续估计", "07_prior_map.png"),
        ("协方差特征值结构", "08_eigenspectrum.png"),
        ("SNR 扫描 RMSE", "09_rmse_vs_snr.png"),
        ("SNR 扫描工作区间放大", "09b_rmse_vs_snr_zoom.png"),
        ("SNR 扫描分辨概率", "10_resolution_vs_snr.png"),
        ("局部异常通道数量扫描", "11_rmse_vs_fault_count.png"),
        ("快拍数扫描", "12_rmse_vs_snapshots.png"),
        ("先验偏差鲁棒性", "13_rmse_vs_prior_bias.png"),
        ("关键工况误差 CDF", "14_error_cdf.png"),
        ("PAWR 消融实验", "15_ablation.png"),
        ("算法运行时间", "16_runtime.png"),
    ]
    cards = []
    standalone = []
    for title, filename in images:
        cards.append(f'<section><h2>{title}</h2><img src="{filename}" alt="{title}"></section>')
        payload = base64.b64encode((output_dir / filename).read_bytes()).decode("ascii")
        standalone.append(
            f'<section><h2>{title}</h2><img src="data:image/png;base64,{payload}" alt="{title}"></section>'
        )
    body_cards = "\n".join(cards)
    standalone_cards = "\n".join(standalone)
    html = f"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><title>HPM Digital Twin v0.3 感知报告</title>
<style>
body{{font-family:Arial,"Microsoft YaHei",sans-serif;max-width:1160px;margin:34px auto;padding:0 20px;line-height:1.65}}
h1{{margin-bottom:6px}} .note{{padding:14px;border:1px solid #999;border-radius:8px;background:#fafafa}}
img{{max-width:100%;border:1px solid #bbb;border-radius:8px}} section{{margin:34px 0}}
table{{border-collapse:collapse;width:100%;font-size:13px}} td{{border:1px solid #aaa;padding:7px;word-break:break-word}}
code{{background:#eee;padding:2px 5px;border-radius:4px}}
</style></head><body>
<h1>HPM Digital Twin v0.3 — 鲁棒相干多径感知</h1>
<p class="note"><strong>模型边界：</strong>本报告只研究归一化窄带阵列观测、相干多径、阵列失配与局部接收通道异常。所有信号功率均相对噪声归一化；不包含真实高功率源预算、设备易损阈值或毁伤效能推断。快速配置使用有限 Monte Carlo 次数，定稿应运行 <code>configs/perception_v03_paper.yaml</code>。</p>
<h2>关键指标</h2><table>{rows}</table>{body_cards}
</body></html>"""
    (output_dir / "perception_v03_report.html").write_text(html, encoding="utf-8")
    (output_dir / "perception_v03_report_standalone.html").write_text(
        html.replace(body_cards, standalone_cards), encoding="utf-8"
    )


def _write_paper_tables(
    output_dir: Path,
    summary: list[dict[str, Any]],
    ablation_summary: list[dict[str, Any]],
    runtime_rows: list[dict[str, Any]],
) -> None:
    selected: list[dict[str, Any]] = []
    for method in METHOD_ORDER:
        row = _select_summary(summary, "snr_db", -8.0, method)
        selected.append(
            {
                "method": method,
                "mean_rmse_deg": row["mean_rmse_deg"],
                "rmse_ci_low_deg": row["rmse_ci_low_deg"],
                "rmse_ci_high_deg": row["rmse_ci_high_deg"],
                "resolution_rate": row["resolution_rate"],
                "median_runtime_ms": row["median_runtime_ms"],
            }
        )
    _write_dict_csv(output_dir / "paper_table_key_results.csv", selected)
    _write_dict_csv(output_dir / "paper_table_ablation.csv", ablation_summary)
    _write_dict_csv(output_dir / "paper_table_runtime.csv", runtime_rows)

    lines = [
        r"\begin{tabular}{lrrrr}",
        r"\hline",
        r"Method & RMSE ($^\circ$) & 95\% CI & Resolution & Runtime (ms) \\",
        r"\hline",
    ]
    for row in selected:
        lines.append(
            f"{row['method']} & {float(row['mean_rmse_deg']):.3f} & "
            f"[{float(row['rmse_ci_low_deg']):.3f}, {float(row['rmse_ci_high_deg']):.3f}] & "
            f"{100.0 * float(row['resolution_rate']):.1f}\\% & {float(row['median_runtime_ms']):.2f} \\\\" 
        )
    lines.extend([r"\hline", r"\end{tabular}"])
    (output_dir / "paper_table_key_results.tex").write_text("\n".join(lines), encoding="utf-8")


def run(config_path: str | Path, output_dir: str | Path) -> dict[str, Any]:
    start = time.perf_counter()
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
    truths = _truths_from_config(config)
    theta_grid, phi_grid = _scan_grids(config)
    smooth_cfg = config["spatial_smoothing"]
    subarray = RectangularArray(
        nx=int(smooth_cfg["subarray_nx"]),
        ny=int(smooth_cfg["subarray_ny"]),
        frequency_hz=array.frequency_hz,
        dx_m=array.dx_m,
        dy_m=array.dy_m,
    )
    scanner = MusicGridScanner(subarray, theta_grid, phi_grid)
    standard_scanner = MusicGridScanner(array, theta_grid, phi_grid)
    mark("configuration_ready")

    plot_pawr_mechanism(
        output_dir / "00_pawr_mechanism.png",
        output_dir / "00_pawr_mechanism.svg",
    )
    mark("mechanism_done")

    rep_cfg = config["representative_case"]
    representative = _simulate_trial(
        array,
        config,
        snr_db=float(rep_cfg["snr_db"]),
        snapshots=int(rep_cfg["snapshots"]),
        fault_count=int(rep_cfg["fault_count"]),
        seed=int(config["seed"]),
    )
    estimates = _estimate_all(
        representative.snapshots,
        array,
        subarray,
        scanner,
        config,
        prior_centers_deg=_prior_centers(config),
    )
    standard = standard_scanner.scan_covariance(
        sample_covariance(representative.snapshots),
        2,
        diagonal_loading=float(smooth_cfg["diagonal_loading"]),
        n_peaks=2,
        min_separation_deg=float(config["scan"]["min_peak_separation_deg"]),
    )
    standard_estimates = tuple((float(p[0]), float(p[1])) for p in standard.peaks)

    representative_metrics: dict[str, Any] = {}
    for method, estimate in [("Standard MUSIC", MethodEstimate(standard_estimates, 0.0, sample_covariance(representative.snapshots), standard.spectrum))] + [
        (method, estimates[method]) for method in METHOD_ORDER
    ]:
        if len(estimate.estimates) >= 2:
            matched = match_directions(estimate.estimates, truths)
            representative_metrics[method] = {
                "rmse_deg": matched.rmse_deg,
                "max_error_deg": matched.max_error_deg,
                "ordered_estimates_deg": [list(value) for value in matched.ordered_estimates],
                "runtime_ms": estimate.runtime_ms,
            }
        else:
            representative_metrics[method] = {
                "rmse_deg": float(config["monte_carlo"]["failure_penalty_deg"]),
                "max_error_deg": float(config["monte_carlo"]["failure_penalty_deg"]),
                "ordered_estimates_deg": [],
                "runtime_ms": estimate.runtime_ms,
            }

    plot_music_spectrum(
        theta_grid,
        phi_grid,
        standard.spectrum,
        list(truths),
        list(standard_estimates),
        "Standard MUSIC",
        output_dir / "01_standard_music_spectrum.png",
    )
    plot_music_spectrum(
        theta_grid,
        phi_grid,
        estimates[METHOD_FBSS].spectrum,
        list(truths),
        list(estimates[METHOD_FBSS].estimates),
        METHOD_FBSS,
        output_dir / "02_fbss_music_spectrum.png",
    )
    plot_music_spectrum(
        theta_grid,
        phi_grid,
        estimates[METHOD_BTTB].spectrum,
        list(truths),
        list(estimates[METHOD_BTTB].estimates),
        METHOD_BTTB,
        output_dir / "03_bttb_music_spectrum.png",
    )
    plot_music_spectrum(
        theta_grid,
        phi_grid,
        estimates[METHOD_PAWR].spectrum,
        list(truths),
        list(estimates[METHOD_PAWR].estimates),
        METHOD_PAWR,
        output_dir / "04_pawr_music_spectrum.png",
    )
    pawr_details = estimates[METHOD_PAWR].details
    plot_sensor_reliability(
        pawr_details.sensor_reliability,
        representative.fault_indices,
        output_dir / "05_sensor_reliability.png",
    )
    plot_subarray_weights(
        pawr_details.subarray_weights,
        array.nx,
        array.ny,
        subarray.nx,
        subarray.ny,
        output_dir / "06_subarray_weights.png",
    )
    plot_prior_map(
        theta_grid,
        phi_grid,
        pawr_details.prior_components,
        _prior_centers(config),
        truths,
        estimates[METHOD_PAWR].estimates,
        output_dir / "07_prior_map.png",
    )
    plot_eigenspectrum_comparison(
        [
            (estimates[METHOD_FBSS].covariance, METHOD_FBSS),
            (estimates[METHOD_BTTB].covariance, METHOD_BTTB),
            (pawr_details.weighted_covariance, "Health-weighted FBSS"),
            (estimates[METHOD_PAWR].covariance, "PAWR reconstruction"),
        ],
        output_dir / "08_eigenspectrum.png",
    )
    np.savez_compressed(
        output_dir / "representative_case.npz",
        snapshots=representative.snapshots,
        fault_indices=np.asarray(representative.fault_indices, dtype=int),
        theta_grid_deg=theta_grid,
        phi_grid_deg=phi_grid,
        standard_spectrum=standard.spectrum,
        fbss_spectrum=estimates[METHOD_FBSS].spectrum,
        bttb_spectrum=estimates[METHOD_BTTB].spectrum,
        pawr_spectrum=estimates[METHOD_PAWR].spectrum,
        sensor_reliability=pawr_details.sensor_reliability,
        subarray_weights=pawr_details.subarray_weights,
        prior_components=pawr_details.prior_components,
        fbss_covariance=estimates[METHOD_FBSS].covariance,
        bttb_covariance=estimates[METHOD_BTTB].covariance,
        pawr_covariance=estimates[METHOD_PAWR].covariance,
    )
    mark("representative_case_done")

    records = _run_standard_sweeps(
        array=array,
        subarray=subarray,
        scanner=scanner,
        config=config,
        truths=truths,
        mark=mark,
    )
    records.extend(
        _run_prior_bias_sweep(
            array=array,
            subarray=subarray,
            scanner=scanner,
            config=config,
            truths=truths,
            mark=mark,
        )
    )
    summary = _summarize_records(records, float(config["monte_carlo"]["confidence"]))
    _write_dict_csv(output_dir / "monte_carlo_trials.csv", records)
    _write_dict_csv(output_dir / "monte_carlo_summary.csv", summary)
    mark("monte_carlo_done")

    ablation_records, ablation_summary = _run_ablation(
        array=array,
        scanner=scanner,
        config=config,
        truths=truths,
        mark=mark,
    )
    _write_dict_csv(output_dir / "ablation_trials.csv", ablation_records)
    _write_dict_csv(output_dir / "ablation_summary.csv", ablation_summary)

    snr_summary = [row for row in summary if row["sweep"] == "snr_db"]
    fault_summary = [row for row in summary if row["sweep"] == "fault_count"]
    snapshot_summary = [row for row in summary if row["sweep"] == "snapshots"]
    prior_summary = [row for row in summary if row["sweep"] == "prior_bias_deg"]
    tolerance = float(config["monte_carlo"]["resolution_tolerance_deg"])

    plot_metric_curve(
        snr_summary,
        x_key="x_value",
        mean_key="mean_rmse_deg",
        low_key="rmse_ci_low_deg",
        high_key="rmse_ci_high_deg",
        xlabel="Reference-path SNR (dB)",
        ylabel="Mean matched-path RMSE (deg)",
        title="Coherent multipath with two corrupted channels (95% CI)",
        output=output_dir / "09_rmse_vs_snr.png",
        method_order=METHOD_ORDER,
    )
    plot_metric_curve(
        [row for row in snr_summary if float(row["x_value"]) >= -10.0],
        x_key="x_value",
        mean_key="mean_rmse_deg",
        low_key="rmse_ci_low_deg",
        high_key="rmse_ci_high_deg",
        xlabel="Reference-path SNR (dB)",
        ylabel="Mean matched-path RMSE (deg)",
        title="Operational SNR range enlarged view (95% CI)",
        output=output_dir / "09b_rmse_vs_snr_zoom.png",
        y_limits=(0.0, 3.5),
        method_order=METHOD_ORDER,
    )
    plot_metric_curve(
        snr_summary,
        x_key="x_value",
        mean_key="resolution_rate",
        low_key="resolution_ci_low",
        high_key="resolution_ci_high",
        xlabel="Reference-path SNR (dB)",
        ylabel="Two-path resolution probability",
        title=f"Resolution probability (maximum error <= {tolerance:g} deg)",
        output=output_dir / "10_resolution_vs_snr.png",
        y_limits=(0.0, 1.05),
        method_order=METHOD_ORDER,
    )
    plot_metric_curve(
        fault_summary,
        x_key="x_value",
        mean_key="mean_rmse_deg",
        low_key="rmse_ci_low_deg",
        high_key="rmse_ci_high_deg",
        xlabel="Number of locally corrupted channels",
        ylabel="Mean matched-path RMSE (deg)",
        title="Robustness to localized receive-channel corruption (95% CI)",
        output=output_dir / "11_rmse_vs_fault_count.png",
        method_order=METHOD_ORDER,
    )
    plot_metric_curve(
        snapshot_summary,
        x_key="x_value",
        mean_key="mean_rmse_deg",
        low_key="rmse_ci_low_deg",
        high_key="rmse_ci_high_deg",
        xlabel="Number of snapshots",
        ylabel="Mean matched-path RMSE (deg)",
        title="Finite-snapshot behavior with coherent paths (95% CI)",
        output=output_dir / "12_rmse_vs_snapshots.png",
        method_order=METHOD_ORDER,
    )
    plot_metric_curve(
        prior_summary,
        x_key="x_value",
        mean_key="mean_rmse_deg",
        low_key="rmse_ci_low_deg",
        high_key="rmse_ci_high_deg",
        xlabel="Additional prior-center bias (deg)",
        ylabel="Mean matched-path RMSE (deg)",
        title="Sensitivity to misspecified coupling-path prior (95% CI)",
        output=output_dir / "13_rmse_vs_prior_bias.png",
        method_order=METHOD_ORDER,
    )
    cdf_records = [
        row
        for row in records
        if row["sweep"] == "snr_db" and np.isclose(float(row["x_value"]), -8.0)
    ]
    plot_error_cdf(
        cdf_records,
        output_dir / "14_error_cdf.png",
        "Error distribution at -8 dB with two corrupted channels",
        METHOD_ORDER,
    )
    ablation_order = [ABLATION_FBSS, ABLATION_WEIGHTED, ABLATION_OFFGRID, ABLATION_FULL]
    ablation_rows = sorted(
        ablation_summary,
        key=lambda row: ablation_order.index(str(row["method"])),
    )
    plot_ablation(ablation_rows, output_dir / "15_ablation.png")

    runtime_rows = []
    for method in METHOD_ORDER:
        values = np.asarray(
            [
                float(row["runtime_ms"])
                for row in records
                if row["sweep"] == "snr_db" and row["method"] == method
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

    key_snr = -8.0
    key_rows = {method: _select_summary(summary, "snr_db", key_snr, method) for method in METHOD_ORDER}
    key_records = {
        method: sorted(
            (
                row
                for row in records
                if row["sweep"] == "snr_db"
                and np.isclose(float(row["x_value"]), key_snr)
                and row["method"] == method
            ),
            key=lambda row: int(row["trial"]),
        )
        for method in METHOD_ORDER
    }
    pawr_values = np.asarray([float(row["rmse_deg"]) for row in key_records[METHOD_PAWR]])
    paired_tests: dict[str, Any] = {}
    for comparator in [METHOD_FBSS, METHOD_ESPRIT]:
        comparator_values = np.asarray(
            [float(row["rmse_deg"]) for row in key_records[comparator]]
        )
        try:
            test = scipy.stats.wilcoxon(
                pawr_values,
                comparator_values,
                alternative="less",
                zero_method="wilcox",
            )
            p_value = float(test.pvalue)
        except ValueError:
            p_value = 1.0
        paired_tests[comparator] = {
            "median_paired_reduction_deg": float(np.median(comparator_values - pawr_values)),
            "wilcoxon_one_sided_p_value": p_value,
        }

    prior_breakpoint = None
    for value in sorted(float(v) for v in config["monte_carlo"]["prior_bias_sweep_deg"]):
        row = _select_summary(summary, "prior_bias_deg", value, METHOD_PAWR)
        if float(row["resolution_rate"]) < 0.8:
            prior_breakpoint = value
            break

    runtime = time.perf_counter() - start
    metrics: dict[str, Any] = {
        "version": "0.3.0",
        "method": "PAWR-MUSIC (Prior-Assisted Adaptive Weighted Reconstruction)",
        "truth_directions_deg": {
            "direct": list(truths[0]),
            "coherent_echo": list(truths[1]),
        },
        "nominal_prior_centers_deg": [list(value) for value in _prior_centers(config)],
        "representative_case": {
            "snr_db": float(rep_cfg["snr_db"]),
            "snapshots": int(rep_cfg["snapshots"]),
            "fault_indices": list(representative.fault_indices),
            "methods": representative_metrics,
            "pawr_structural_residual": float(pawr_details.structural_residual),
        },
        "monte_carlo": {
            "trials_per_point": int(config["monte_carlo"]["trials"]),
            "confidence": float(config["monte_carlo"]["confidence"]),
            "resolution_tolerance_deg": tolerance,
            "at_minus8_db_two_faults": {
                method: {
                    "mean_rmse_deg": float(key_rows[method]["mean_rmse_deg"]),
                    "rmse_ci_deg": [
                        float(key_rows[method]["rmse_ci_low_deg"]),
                        float(key_rows[method]["rmse_ci_high_deg"]),
                    ],
                    "resolution_rate": float(key_rows[method]["resolution_rate"]),
                    "median_runtime_ms": float(key_rows[method]["median_runtime_ms"]),
                }
                for method in METHOD_ORDER
            },
            "paired_tests_pawr_lower_error": paired_tests,
            "first_prior_bias_deg_with_resolution_below_0_8": prior_breakpoint,
        },
        "runtime_seconds": float(runtime),
        "scope": "Normalized coherent-multipath receive-array processing only; no absolute source power, susceptibility threshold, or damage inference.",
    }
    (output_dir / "results_summary.json").write_text(
        json.dumps(metrics, indent=2, ensure_ascii=False), encoding="utf-8"
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
        "seed": int(config["seed"]),
    }
    (output_dir / "environment.json").write_text(
        json.dumps(environment, indent=2), encoding="utf-8"
    )
    _write_paper_tables(output_dir, summary, ablation_rows, runtime_rows)

    figure_manifest = [
        {"figure": f"Fig. {index}", "file": filename, "purpose": title}
        for index, (title, filename) in enumerate(
            [
                ("PAWR mechanism", "00_pawr_mechanism.png"),
                ("Standard MUSIC representative spectrum", "01_standard_music_spectrum.png"),
                ("FBSS representative spectrum", "02_fbss_music_spectrum.png"),
                ("BTTB representative spectrum", "03_bttb_music_spectrum.png"),
                ("PAWR reconstructed spectrum", "04_pawr_music_spectrum.png"),
                ("Sensor reliability", "05_sensor_reliability.png"),
                ("Subarray weights", "06_subarray_weights.png"),
                ("Broad prior", "07_prior_map.png"),
                ("Eigenspectrum", "08_eigenspectrum.png"),
                ("RMSE versus SNR", "09_rmse_vs_snr.png"),
                ("RMSE versus SNR zoom", "09b_rmse_vs_snr_zoom.png"),
                ("Resolution versus SNR", "10_resolution_vs_snr.png"),
                ("RMSE versus fault count", "11_rmse_vs_fault_count.png"),
                ("RMSE versus snapshots", "12_rmse_vs_snapshots.png"),
                ("RMSE versus prior bias", "13_rmse_vs_prior_bias.png"),
                ("Error CDF", "14_error_cdf.png"),
                ("Ablation", "15_ablation.png"),
                ("Runtime", "16_runtime.png"),
            ],
            start=1,
        )
    ]
    _write_dict_csv(output_dir / "figure_manifest.csv", figure_manifest)
    _write_html_report(output_dir, metrics)
    mark("report_done")
    return metrics

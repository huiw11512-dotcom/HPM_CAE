"""V0.8 normalized effect-evaluation digital twin.

The workflow consumes V0.7 dynamic field maps and produces target-attached
cumulative-response maps, world-fixed risk maps, uncertainty intervals, mission
metrics, and an abstract effect-aware exposure-allocation comparison.  No
absolute source power, physical range, calibrated component threshold, or
real-world damage inference is performed.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence
import argparse
import csv
import hashlib
import json
import math
import os
import platform
import sys
import time

import matplotlib
import numpy as np
import scipy
from scipy.ndimage import map_coordinates
from scipy.stats import wilcoxon
from threadpoolctl import threadpool_limits
import yaml

from hpm_platform.evaluation.doa_statistics import mean_confidence_interval
from hpm_platform.evaluation.effect_digital_twin import (
    EffectMapMetrics,
    EffectTier,
    choose_effect_aware_duty,
    dose_increment,
    evaluate_moving_effect_state,
    lognormal_response_probability,
    probability_interval,
    update_leaky_dose,
)
from hpm_platform.field_control.region_shaping import rotated_ellipse_masks
from hpm_platform.workflows.dynamic_field_control_v07 import (
    METHOD_ORDER,
    METHOD_PROPOSED,
    PlaneGrid,
    TrialOutput,
    _array_from_config,
    _load_config,
    _plane_grid,
    _region_masks,
    _simulate_trial,
    main_method_specs,
)

POLICY_ALWAYS = "PCF-RLS / always-on"
POLICY_STOP = "PCF-RLS / target-stop"
POLICY_EFFECT_AWARE = "PCF-RLS / EA-Duty"
POLICY_ORDER = [POLICY_ALWAYS, POLICY_STOP, POLICY_EFFECT_AWARE]


@dataclass(frozen=True)
class TargetLocalGrid:
    x_lambda: np.ndarray
    y_lambda: np.ndarray
    xx_lambda: np.ndarray
    yy_lambda: np.ndarray
    target_mask: np.ndarray


@dataclass(frozen=True)
class PreparedExposure:
    world_intensity: dict[str, np.ndarray]
    target_intensity: dict[str, np.ndarray]
    true_centers_lambda: np.ndarray
    off_target_masks: np.ndarray


@dataclass(frozen=True)
class EffectRunOutput:
    trial: TrialOutput
    grid: PlaneGrid
    local_grid: TargetLocalGrid
    protected_mask: np.ndarray
    exposure: PreparedExposure
    method_records: list[dict[str, Any]]
    method_summary: list[dict[str, Any]]
    policy_records: list[dict[str, Any]]
    policy_summary: list[dict[str, Any]]
    sweep_rows: list[dict[str, Any]]
    sweep_summary: list[dict[str, Any]]
    final_maps: dict[str, np.ndarray]
    policy_final_maps: dict[str, np.ndarray]
    snapshot_maps: dict[str, np.ndarray]
    policy_snapshot_maps: dict[str, np.ndarray]
    uncertainty_maps: dict[str, np.ndarray]
    paired_statistics: dict[str, Any]


def _tiers(config: Mapping[str, Any]) -> tuple[EffectTier, ...]:
    output = []
    for row in config["effect_twin"]["tiers"]:
        output.append(
            EffectTier(
                name=str(row["name"]),
                threshold_median=float(row["threshold_median"]),
                threshold_log_sigma=float(row["threshold_log_sigma"]),
                probability_goal=float(row["probability_goal"]),
                coverage_probability=float(row["coverage_probability"]),
            )
        )
    if not output:
        raise ValueError("at least one effect tier is required")
    return tuple(output)


def _primary_tier(config: Mapping[str, Any], tiers: Sequence[EffectTier]) -> EffectTier:
    name = str(config["effect_twin"]["primary_tier"])
    matches = [tier for tier in tiers if tier.name == name]
    if len(matches) != 1:
        raise ValueError(f"primary tier {name!r} is not uniquely defined")
    return matches[0]


def _target_local_grid(config: Mapping[str, Any]) -> TargetLocalGrid:
    effect = config["effect_twin"]
    region = config["moving_region"]
    n = int(effect["target_local_grid_points"])
    scale = float(effect["target_local_extent_scale"])
    axes = np.asarray(region["semi_axes_lambda"], dtype=float)
    x = np.linspace(-scale * axes[0], scale * axes[0], n)
    y = np.linspace(-scale * axes[1], scale * axes[1], n)
    xx, yy = np.meshgrid(x, y, indexing="xy")
    mask = (xx / axes[0]) ** 2 + (yy / axes[1]) ** 2 <= 1.0
    return TargetLocalGrid(x, y, xx, yy, mask)


def _protected_mask(grid: PlaneGrid, config: Mapping[str, Any]) -> np.ndarray:
    cfg = config["protected_zone"]
    masks = rotated_ellipse_masks(
        grid.xx_lambda,
        grid.yy_lambda,
        center_m=tuple(float(v) for v in cfg["center_lambda"]),
        semi_axes_m=tuple(float(v) for v in cfg["semi_axes_lambda"]),
        rotation_deg=float(cfg["rotation_deg"]),
        guard_scale=float(cfg["guard_scale"]),
    )
    return masks.target


def _snapshot_field(trial: TrialOutput, method: str, frame: int) -> np.ndarray:
    key = f"{method}__frame_{int(frame):03d}"
    try:
        return np.asarray(trial.snapshots[key], dtype=complex)
    except KeyError as exc:
        raise KeyError(f"missing stored field {key}; V0.8 requires store_all_fields=True") from exc


def _sample_target_attached(
    field: np.ndarray,
    grid: PlaneGrid,
    local: TargetLocalGrid,
    center_lambda: np.ndarray,
    rotation_deg: float,
) -> np.ndarray:
    angle = np.deg2rad(float(rotation_deg))
    dx = np.cos(angle) * local.xx_lambda - np.sin(angle) * local.yy_lambda
    dy = np.sin(angle) * local.xx_lambda + np.cos(angle) * local.yy_lambda
    world_x = float(center_lambda[0]) + dx
    world_y = float(center_lambda[1]) + dy
    column = (world_x - float(grid.x_lambda[0])) / float(grid.x_lambda[1] - grid.x_lambda[0])
    row = (world_y - float(grid.y_lambda[0])) / float(grid.y_lambda[1] - grid.y_lambda[0])
    amplitude = map_coordinates(
        np.abs(np.asarray(field)),
        [row.ravel(), column.ravel()],
        order=1,
        mode="constant",
        cval=0.0,
    )
    return amplitude.reshape(local.xx_lambda.shape)


def _prepare_exposure(
    trial: TrialOutput,
    grid: PlaneGrid,
    local: TargetLocalGrid,
    config: Mapping[str, Any],
) -> PreparedExposure:
    n_frames = int(config["trajectory"]["frames"])
    actuation = int(config["sensing"]["actuation_latency_frames"])
    reference = float(config["effect_twin"]["reference_amplitude"])
    exponent = float(config["effect_twin"]["amplitude_exponent"])
    true_centers = trial.trajectory_lambda[actuation : actuation + n_frames]
    world_intensity: dict[str, np.ndarray] = {}
    target_intensity: dict[str, np.ndarray] = {}
    off_masks = []
    for frame, center in enumerate(true_centers):
        off_masks.append(_region_masks(grid, config, center).outside)
    for method in METHOD_ORDER:
        world_series = []
        target_series = []
        for frame, center in enumerate(true_centers):
            field = _snapshot_field(trial, method, frame)
            world_series.append(
                dose_increment(
                    field,
                    reference_amplitude=reference,
                    pulse_weight=1.0,
                    amplitude_exponent=exponent,
                )
            )
            local_amplitude = _sample_target_attached(
                field,
                grid,
                local,
                center,
                float(config["moving_region"]["rotation_deg"]),
            )
            target_series.append(
                dose_increment(
                    local_amplitude,
                    reference_amplitude=reference,
                    pulse_weight=1.0,
                    amplitude_exponent=exponent,
                )
            )
        world_intensity[method] = np.asarray(world_series, dtype=float)
        target_intensity[method] = np.asarray(target_series, dtype=float)
    return PreparedExposure(
        world_intensity=world_intensity,
        target_intensity=target_intensity,
        true_centers_lambda=np.asarray(true_centers, dtype=float),
        off_target_masks=np.asarray(off_masks, dtype=bool),
    )


def _metric_kwargs(config: Mapping[str, Any], tier: EffectTier) -> dict[str, float]:
    success = config["effect_success"]
    return {
        "coverage_probability": float(tier.coverage_probability),
        "high_risk_probability": float(success["high_risk_probability"]),
        "target_goal_probability": float(tier.probability_goal),
        "minimum_target_coverage": float(success["minimum_target_coverage"]),
        "maximum_protected_p95_probability": float(success["maximum_protected_p95_probability"]),
        "maximum_off_target_high_risk_fraction": float(success["maximum_off_target_high_risk_fraction"]),
    }


def _metrics_record(
    metrics: EffectMapMetrics,
    *,
    label_key: str,
    label: str,
    tier: EffectTier,
    frame: int,
    duty: float,
    cumulative_duty: float,
) -> dict[str, Any]:
    return {
        label_key: label,
        "tier": tier.name,
        "frame": int(frame),
        "duty_factor": float(duty),
        "cumulative_duty": float(cumulative_duty),
        **asdict(metrics),
    }


def _evaluate_methods(
    exposure: PreparedExposure,
    local: TargetLocalGrid,
    protected: np.ndarray,
    tiers: Sequence[EffectTier],
    config: Mapping[str, Any],
) -> tuple[list[dict[str, Any]], dict[str, np.ndarray], dict[str, np.ndarray], dict[str, np.ndarray]]:
    effect = config["effect_twin"]
    pulse_weight = float(effect["pulse_weight"])
    retention = float(effect["retention"])
    coupling_sigma = float(effect["coupling_log_sigma"])
    snapshot_frames = {int(v) for v in config["representative_effect"]["snapshot_frames"]}
    records: list[dict[str, Any]] = []
    final_maps: dict[str, np.ndarray] = {}
    snapshots: dict[str, np.ndarray] = {}
    uncertainty: dict[str, np.ndarray] = {}
    primary = _primary_tier(config, tiers)
    for method in METHOD_ORDER:
        target_dose = np.zeros_like(exposure.target_intensity[method][0])
        world_dose = np.zeros_like(exposure.world_intensity[method][0])
        for frame in range(exposure.target_intensity[method].shape[0]):
            target_dose = update_leaky_dose(
                target_dose,
                pulse_weight * exposure.target_intensity[method][frame],
                retention=retention,
            )
            world_dose = update_leaky_dose(
                world_dose,
                pulse_weight * exposure.world_intensity[method][frame],
                retention=retention,
            )
            for tier in tiers:
                p_target = lognormal_response_probability(target_dose, tier, coupling_log_sigma=coupling_sigma)
                p_world = lognormal_response_probability(world_dose, tier, coupling_log_sigma=coupling_sigma)
                metrics = evaluate_moving_effect_state(
                    p_target,
                    p_world,
                    target_mask=local.target_mask,
                    protected_mask=protected,
                    off_target_mask=exposure.off_target_masks[frame],
                    **_metric_kwargs(config, tier),
                )
                records.append(
                    _metrics_record(
                        metrics,
                        label_key="method",
                        label=method,
                        tier=tier,
                        frame=frame,
                        duty=1.0,
                        cumulative_duty=float(frame + 1),
                    )
                )
                if frame in snapshot_frames and tier.name == primary.name:
                    snapshots[f"target_probability__{method}__frame_{frame:03d}"] = p_target.copy()
                    snapshots[f"world_probability__{method}__frame_{frame:03d}"] = p_world.copy()
        for tier in tiers:
            p_target = lognormal_response_probability(target_dose, tier, coupling_log_sigma=coupling_sigma)
            p_world = lognormal_response_probability(world_dose, tier, coupling_log_sigma=coupling_sigma)
            final_maps[f"target_dose__{method}"] = target_dose.copy()
            final_maps[f"world_dose__{method}"] = world_dose.copy()
            final_maps[f"target_probability__{method}__{tier.name}"] = p_target
            final_maps[f"world_probability__{method}__{tier.name}"] = p_world
        if method == METHOD_PROPOSED:
            central_t, low_t, high_t = probability_interval(
                target_dose,
                primary,
                coupling_log_sigma=coupling_sigma,
                epistemic_threshold_log_sigma=float(effect["epistemic_threshold_log_sigma"]),
                confidence=float(effect["confidence"]),
            )
            central_w, low_w, high_w = probability_interval(
                world_dose,
                primary,
                coupling_log_sigma=coupling_sigma,
                epistemic_threshold_log_sigma=float(effect["epistemic_threshold_log_sigma"]),
                confidence=float(effect["confidence"]),
            )
            uncertainty.update(
                {
                    "target_central": central_t,
                    "target_lower": low_t,
                    "target_upper": high_t,
                    "target_width": high_t - low_t,
                    "world_central": central_w,
                    "world_lower": low_w,
                    "world_upper": high_w,
                    "world_width": high_w - low_w,
                }
            )
    return records, final_maps, snapshots, uncertainty


def _evaluate_policies(
    exposure: PreparedExposure,
    local: TargetLocalGrid,
    protected: np.ndarray,
    tiers: Sequence[EffectTier],
    config: Mapping[str, Any],
) -> tuple[list[dict[str, Any]], dict[str, np.ndarray], dict[str, np.ndarray]]:
    effect = config["effect_twin"]
    policy_cfg = config["effect_policy"]
    primary = _primary_tier(config, tiers)
    pulse_weight = float(effect["pulse_weight"])
    retention = float(effect["retention"])
    coupling_sigma = float(effect["coupling_log_sigma"])
    snapshot_frames = {int(v) for v in config["representative_effect"]["snapshot_frames"]}
    world_intensity = exposure.world_intensity[METHOD_PROPOSED]
    target_intensity = exposure.target_intensity[METHOD_PROPOSED]
    records: list[dict[str, Any]] = []
    final_maps: dict[str, np.ndarray] = {}
    snapshots: dict[str, np.ndarray] = {}
    for policy in POLICY_ORDER:
        target_dose = np.zeros_like(target_intensity[0])
        world_dose = np.zeros_like(world_intensity[0])
        cumulative_duty = 0.0
        previous_duty = 1.0
        for frame in range(target_intensity.shape[0]):
            target_full = pulse_weight * target_intensity[frame]
            world_full = pulse_weight * world_intensity[frame]
            if policy == POLICY_ALWAYS:
                duty = 1.0
            elif policy == POLICY_STOP:
                p_before = lognormal_response_probability(target_dose, primary, coupling_log_sigma=coupling_sigma)
                current_mean = float(np.mean(p_before[local.target_mask]))
                hysteresis = float(policy_cfg["stop_hysteresis"])
                if previous_duty > 0.0 and current_mean >= primary.probability_goal + hysteresis:
                    duty = 0.0
                elif previous_duty == 0.0 and current_mean < primary.probability_goal - hysteresis:
                    duty = 1.0
                else:
                    duty = previous_duty
            else:
                decision = choose_effect_aware_duty(
                    previous_target_dose=target_dose,
                    target_full_increment=target_full,
                    target_mask=local.target_mask,
                    previous_world_dose=world_dose,
                    world_full_increment=world_full,
                    protected_mask=protected,
                    off_target_mask=exposure.off_target_masks[frame],
                    tier=primary,
                    candidate_duties=policy_cfg["candidate_duties"],
                    retention=retention,
                    coupling_log_sigma=coupling_sigma,
                    coverage_probability=primary.coverage_probability,
                    high_risk_probability=float(config["effect_success"]["high_risk_probability"]),
                    target_goal_probability=primary.probability_goal,
                    target_upper_probability=float(policy_cfg["target_upper_probability"]),
                    protected_probability_limit=float(config["effect_success"]["maximum_protected_p95_probability"]),
                    off_target_high_risk_limit=float(config["effect_success"]["maximum_off_target_high_risk_fraction"]),
                    weights=policy_cfg["objective_weights"],
                    previous_duty=previous_duty,
                    prediction_horizon=int(policy_cfg["prediction_horizon_frames"]),
                )
                duty = float(decision.duty_factor)
            target_dose = update_leaky_dose(target_dose, duty * target_full, retention=retention)
            world_dose = update_leaky_dose(world_dose, duty * world_full, retention=retention)
            cumulative_duty += duty
            previous_duty = duty
            p_target = lognormal_response_probability(target_dose, primary, coupling_log_sigma=coupling_sigma)
            p_world = lognormal_response_probability(world_dose, primary, coupling_log_sigma=coupling_sigma)
            metrics = evaluate_moving_effect_state(
                p_target,
                p_world,
                target_mask=local.target_mask,
                protected_mask=protected,
                off_target_mask=exposure.off_target_masks[frame],
                **_metric_kwargs(config, primary),
            )
            records.append(
                _metrics_record(
                    metrics,
                    label_key="policy",
                    label=policy,
                    tier=primary,
                    frame=frame,
                    duty=duty,
                    cumulative_duty=cumulative_duty,
                )
            )
            if frame in snapshot_frames or policy == POLICY_EFFECT_AWARE:
                snapshots[f"target_probability__{policy}__frame_{frame:03d}"] = p_target.copy()
                snapshots[f"world_probability__{policy}__frame_{frame:03d}"] = p_world.copy()
        final_maps[f"target_dose__{policy}"] = target_dose
        final_maps[f"world_dose__{policy}"] = world_dose
        final_maps[f"target_probability__{policy}"] = lognormal_response_probability(
            target_dose, primary, coupling_log_sigma=coupling_sigma
        )
        final_maps[f"world_probability__{policy}"] = lognormal_response_probability(
            world_dose, primary, coupling_log_sigma=coupling_sigma
        )
    return records, final_maps, snapshots


def _summarize_records(
    records: Sequence[Mapping[str, Any]],
    *,
    label_key: str,
    order: Sequence[str],
) -> list[dict[str, Any]]:
    tiers = list(dict.fromkeys(str(row["tier"]) for row in records))
    output: list[dict[str, Any]] = []
    for label in order:
        for tier in tiers:
            selected = sorted(
                (row for row in records if row[label_key] == label and row["tier"] == tier),
                key=lambda row: int(row["frame"]),
            )
            if not selected:
                continue
            first_goal = next(
                (
                    int(row["frame"])
                    for row in selected
                    if float(row["target_mean_probability"]) >= 0.5
                ),
                -1,
            )
            target_mean = float(np.mean([row["target_mean_probability"] for row in selected]))
            protected_p95 = float(np.mean([row["protected_p95_probability"] for row in selected]))
            outside_high = float(np.mean([row["off_target_high_risk_fraction"] for row in selected]))
            output.append(
                {
                    label_key: label,
                    "tier": tier,
                    "mean_target_probability": target_mean,
                    "final_target_probability": float(selected[-1]["target_mean_probability"]),
                    "mean_target_coverage": float(np.mean([row["target_coverage"] for row in selected])),
                    "mean_protected_p95_probability": protected_p95,
                    "peak_protected_probability": float(max(row["protected_peak_probability"] for row in selected)),
                    "mean_off_target_high_risk_fraction": outside_high,
                    "mean_effect_selectivity": float(np.mean([row["effect_selectivity"] for row in selected])),
                    "mean_response_efficiency": float(np.mean([row["response_efficiency"] for row in selected])),
                    "mission_success_rate": float(np.mean([row["mission_success"] for row in selected])),
                    "first_frame_above_0p5": int(first_goal),
                    "cumulative_duty": float(selected[-1]["cumulative_duty"]),
                    "risk_adjusted_utility": float(target_mean - 0.75 * protected_p95 - 0.35 * outside_high),
                }
            )
    return output


def _evaluate_trial_parameters(
    exposure: PreparedExposure,
    local: TargetLocalGrid,
    protected: np.ndarray,
    tier: EffectTier,
    config: Mapping[str, Any],
    *,
    pulse_weight: float,
    retention: float,
    coupling_log_sigma: float,
    threshold_median_scale: float,
) -> list[dict[str, Any]]:
    output = []
    for method in METHOD_ORDER:
        td = np.zeros_like(exposure.target_intensity[method][0])
        wd = np.zeros_like(exposure.world_intensity[method][0])
        frame_metrics = []
        for frame in range(exposure.target_intensity[method].shape[0]):
            td = update_leaky_dose(td, pulse_weight * exposure.target_intensity[method][frame], retention=retention)
            wd = update_leaky_dose(wd, pulse_weight * exposure.world_intensity[method][frame], retention=retention)
            pt = lognormal_response_probability(td, tier, coupling_log_sigma=coupling_log_sigma, threshold_median_scale=threshold_median_scale)
            pw = lognormal_response_probability(wd, tier, coupling_log_sigma=coupling_log_sigma, threshold_median_scale=threshold_median_scale)
            frame_metrics.append(
                evaluate_moving_effect_state(
                    pt,
                    pw,
                    target_mask=local.target_mask,
                    protected_mask=protected,
                    off_target_mask=exposure.off_target_masks[frame],
                    **_metric_kwargs(config, tier),
                )
            )
        first_goal = next((i for i, m in enumerate(frame_metrics) if m.target_mean_probability >= tier.probability_goal), -1)
        output.append(
            {
                "method": method,
                "mean_target_probability": float(np.mean([m.target_mean_probability for m in frame_metrics])),
                "final_target_probability": float(frame_metrics[-1].target_mean_probability),
                "mean_target_coverage": float(np.mean([m.target_coverage for m in frame_metrics])),
                "mean_protected_p95_probability": float(np.mean([m.protected_p95_probability for m in frame_metrics])),
                "mean_off_target_high_risk_fraction": float(np.mean([m.off_target_high_risk_fraction for m in frame_metrics])),
                "mission_success_rate": float(np.mean([m.mission_success for m in frame_metrics])),
                "time_to_goal_frame": int(first_goal),
            }
        )
    return output


def _run_effect_sweeps(
    exposure: PreparedExposure,
    local: TargetLocalGrid,
    protected: np.ndarray,
    tier: EffectTier,
    config: Mapping[str, Any],
    progress: Path,
) -> list[dict[str, Any]]:
    effect = config["effect_twin"]
    mc = config["monte_carlo_effect"]
    rows: list[dict[str, Any]] = []
    sweep_names = list(mc["sweeps"].keys())
    for sweep_index, sweep in enumerate(sweep_names):
        for value_index, value in enumerate(mc["sweeps"][sweep]):
            for trial in range(int(mc["trials_per_point"])):
                seed = int(mc["base_seed"]) + 100000 * (sweep_index + 1) + 1000 * value_index + trial
                rng = np.random.default_rng(seed)
                threshold_scale = math.exp(rng.normal(0.0, float(mc["threshold_epistemic_draw_log_sigma"])))
                retention = float(np.clip(float(effect["retention"]) + rng.normal(0.0, float(mc["retention_draw_std"])), 0.0, 0.995))
                coupling_sigma = float(effect["coupling_log_sigma"])
                pulse_weight = float(effect["pulse_weight"]) * math.exp(rng.normal(0.0, float(mc["pulse_weight_draw_log_sigma"])))
                if sweep == "threshold_median_scale":
                    threshold_scale *= float(value)
                elif sweep == "retention":
                    retention = float(value)
                elif sweep == "coupling_log_sigma":
                    coupling_sigma = float(value)
                elif sweep == "pulse_weight":
                    pulse_weight = float(value)
                else:
                    raise ValueError(f"unknown effect sweep {sweep}")
                summaries = _evaluate_trial_parameters(
                    exposure,
                    local,
                    protected,
                    tier,
                    config,
                    pulse_weight=pulse_weight,
                    retention=retention,
                    coupling_log_sigma=coupling_sigma,
                    threshold_median_scale=threshold_scale,
                )
                for summary in summaries:
                    rows.append(
                        {
                            "sweep": sweep,
                            "x_value": float(value),
                            "trial": int(trial),
                            "seed": int(seed),
                            "threshold_median_scale_realized": float(threshold_scale),
                            "retention_realized": float(retention),
                            "coupling_log_sigma_realized": float(coupling_sigma),
                            "pulse_weight_realized": float(pulse_weight),
                            **summary,
                        }
                    )
                with progress.open("a", encoding="utf-8") as handle:
                    handle.write(f"effect sweep={sweep}, value={value}, trial={trial}, seed={seed}\n")
    return rows


def _summarize_sweeps(rows: Sequence[Mapping[str, Any]], confidence: float) -> list[dict[str, Any]]:
    output = []
    keys = sorted({(str(row["sweep"]), float(row["x_value"]), str(row["method"])) for row in rows})
    for sweep, x_value, method in keys:
        selected = [row for row in rows if row["sweep"] == sweep and float(row["x_value"]) == x_value and row["method"] == method]
        entry: dict[str, Any] = {"sweep": sweep, "x_value": x_value, "method": method, "n_trials": len(selected)}
        for key in (
            "mean_target_probability",
            "final_target_probability",
            "mean_target_coverage",
            "mean_protected_p95_probability",
            "mean_off_target_high_risk_fraction",
            "mission_success_rate",
        ):
            mean, low, high = mean_confidence_interval([float(row[key]) for row in selected], confidence)
            entry[f"{key}_mean"] = mean
            entry[f"{key}_ci_low"] = low
            entry[f"{key}_ci_high"] = high
        output.append(entry)
    return output


def _paired_statistics(sweep_rows: Sequence[Mapping[str, Any]], config: Mapping[str, Any]) -> dict[str, Any]:
    sweep = "threshold_median_scale"
    value = min(config["monte_carlo_effect"]["sweeps"][sweep], key=lambda v: abs(float(v) - 1.0))
    selected = [row for row in sweep_rows if row["sweep"] == sweep and float(row["x_value"]) == float(value)]
    lookup = {(str(row["method"]), int(row["trial"])): float(row["mean_target_probability"]) for row in selected}
    trials = sorted({int(row["trial"]) for row in selected if row["method"] == METHOD_PROPOSED})
    proposed = np.asarray([lookup[(METHOD_PROPOSED, t)] for t in trials])
    result: dict[str, Any] = {"sweep": sweep, "x_value": float(value), "comparisons": {}}
    for baseline in METHOD_ORDER[:-1]:
        base = np.asarray([lookup[(baseline, t)] for t in trials])
        difference = proposed - base
        if difference.size < 2 or np.allclose(difference, 0.0):
            p_value = 1.0
        else:
            p_value = float(wilcoxon(proposed, base, alternative="greater").pvalue)
        result["comparisons"][baseline] = {
            "mean_target_probability_gain": float(np.mean(difference)),
            "wilcoxon_one_sided_p": p_value,
            "n_pairs": int(difference.size),
        }
    return result


def _write_csv(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    rows = list(rows)
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


def _json_default(value: Any) -> Any:
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, (np.floating, np.integer, np.bool_)):
        return value.item()
    if isinstance(value, complex):
        return {"real": value.real, "imag": value.imag}
    if isinstance(value, Path):
        return str(value)
    raise TypeError(type(value).__name__)


def _write_npz(path: Path, result: EffectRunOutput) -> None:
    arrays: dict[str, np.ndarray] = {
        "x_lambda": result.grid.x_lambda,
        "y_lambda": result.grid.y_lambda,
        "target_local_x_lambda": result.local_grid.x_lambda,
        "target_local_y_lambda": result.local_grid.y_lambda,
        "target_local_mask": result.local_grid.target_mask,
        "protected_mask": result.protected_mask,
        "true_centers_lambda": result.exposure.true_centers_lambda,
    }
    for mapping in (result.final_maps, result.policy_final_maps, result.snapshot_maps, result.policy_snapshot_maps, result.uncertainty_maps):
        for key, value in mapping.items():
            safe = key.replace(" ", "_").replace("/", "_").replace(":", "_").replace("-", "_")
            arrays[safe] = np.asarray(value)
    np.savez_compressed(path, **arrays)


def _write_paper_table(path_csv: Path, path_tex: Path, rows: Sequence[Mapping[str, Any]], label_key: str) -> None:
    _write_csv(path_csv, rows)
    lines = [r"\begin{tabular}{lrrrrr}", r"\toprule", r"Method & Target $\bar{P}$ & Coverage & Protected $P_{95}$ & Success & Duty \\", r"\midrule"]
    for row in rows:
        lines.append(
            f"{row[label_key]} & {float(row['mean_target_probability']):.3f} & {100*float(row['mean_target_coverage']):.1f}\\% & "
            f"{float(row['mean_protected_p95_probability']):.3f} & {100*float(row['mission_success_rate']):.1f}\\% & "
            f"{float(row['cumulative_duty']):.2f} " + r"\\"
        )
    lines.extend([r"\bottomrule", r"\end{tabular}"])
    path_tex.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _checksums(output: Path, names: Sequence[str]) -> None:
    lines = []
    for name in names:
        path = output / name
        if path.is_file():
            lines.append(f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {name}")
    (output / "CHECKSUMS.sha256").write_text("\n".join(lines) + "\n", encoding="utf-8")


def _environment() -> dict[str, str]:
    return {
        "python": sys.version.split()[0],
        "numpy": np.__version__,
        "scipy": scipy.__version__,
        "matplotlib": matplotlib.__version__,
        "platform": platform.platform(),
    }


def run(config_path: str | Path, output_dir: str | Path) -> dict[str, Any]:
    config = _load_config(config_path)
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    progress = output / "progress.log"
    progress.write_text("V0.8 normalized effect-twin run started\n", encoding="utf-8")
    start = time.perf_counter()
    tiers = _tiers(config)
    primary = _primary_tier(config, tiers)
    array = _array_from_config(config)
    grid = _plane_grid(array, config, int(config["control_plane"]["representative_grid_points"]))
    local = _target_local_grid(config)
    protected = _protected_mask(grid, config)

    with threadpool_limits(limits=1):
        trial = _simulate_trial(
            config,
            seed=int(config["representative_effect"]["seed"]),
            n_frames=int(config["trajectory"]["frames"]),
            grid_points=int(config["control_plane"]["representative_grid_points"]),
            maneuver_scale=float(config["trajectory"]["representative_maneuver_scale"]),
            processing_delay_frames=int(config["sensing"]["processing_delay_frames"]),
            measurement_noise_std_lambda=float(config["sensing"]["measurement_noise_std_lambda"]),
            phase_error_std_deg=float(config["actual_impairments"]["phase_std_deg"]),
            specs=main_method_specs(),
            store_snapshots=True,
            store_all_fields=True,
            include_process_jitter=False,
        )
        with progress.open("a", encoding="utf-8") as handle:
            handle.write("dynamic field replay complete\n")
        exposure = _prepare_exposure(trial, grid, local, config)
        method_records, final_maps, snapshot_maps, uncertainty_maps = _evaluate_methods(
            exposure, local, protected, tiers, config
        )
        policy_records, policy_final_maps, policy_snapshot_maps = _evaluate_policies(
            exposure, local, protected, tiers, config
        )
        sweep_rows = _run_effect_sweeps(exposure, local, protected, primary, config, progress)

    method_summary = _summarize_records(method_records, label_key="method", order=METHOD_ORDER)
    policy_summary = _summarize_records(policy_records, label_key="policy", order=POLICY_ORDER)
    sweep_summary = _summarize_sweeps(sweep_rows, float(config["monte_carlo_effect"]["confidence"]))
    paired = _paired_statistics(sweep_rows, config)
    result = EffectRunOutput(
        trial=trial,
        grid=grid,
        local_grid=local,
        protected_mask=protected,
        exposure=exposure,
        method_records=method_records,
        method_summary=method_summary,
        policy_records=policy_records,
        policy_summary=policy_summary,
        sweep_rows=sweep_rows,
        sweep_summary=sweep_summary,
        final_maps=final_maps,
        policy_final_maps=policy_final_maps,
        snapshot_maps=snapshot_maps,
        policy_snapshot_maps=policy_snapshot_maps,
        uncertainty_maps=uncertainty_maps,
        paired_statistics=paired,
    )

    _write_csv(output / "effect_frame_records.csv", method_records)
    _write_csv(output / "effect_method_summary.csv", method_summary)
    _write_csv(output / "effect_policy_frame_records.csv", policy_records)
    _write_csv(output / "effect_policy_summary.csv", policy_summary)
    _write_csv(output / "effect_sweep_trials.csv", sweep_rows)
    _write_csv(output / "effect_sweep_summary.csv", sweep_summary)
    primary_methods = [row for row in method_summary if row["tier"] == primary.name]
    _write_paper_table(output / "paper_table_key_results.csv", output / "paper_table_key_results.tex", primary_methods, "method")
    _write_paper_table(output / "paper_table_policy_results.csv", output / "paper_table_policy_results.tex", policy_summary, "policy")
    _write_npz(output / "representative_effect_case.npz", result)
    with (output / "config_snapshot.yaml").open("w", encoding="utf-8") as handle:
        yaml.safe_dump(config, handle, sort_keys=False, allow_unicode=True)
    (output / "environment.json").write_text(json.dumps(_environment(), indent=2), encoding="utf-8")

    metrics: dict[str, Any] = {
        "platform_version": str(config["platform"]["version"]),
        "normalized_scope": True,
        "primary_tier": primary.name,
        "method_summary": method_summary,
        "policy_summary": policy_summary,
        "paired_statistics": paired,
        "n_effect_sweep_rows": len(sweep_rows),
        "run_time_seconds_before_figures": float(time.perf_counter() - start),
    }
    (output / "results_summary.json").write_text(
        json.dumps(metrics, indent=2, ensure_ascii=False, default=_json_default), encoding="utf-8"
    )

    from hpm_platform.visualization.effect_twin_v08 import generate_all_figures, write_reports

    manifest = generate_all_figures(output, config, result)
    _write_csv(output / "figure_manifest.csv", manifest)
    write_reports(output, config, result, metrics, manifest)
    metrics["run_time_seconds"] = float(time.perf_counter() - start)
    (output / "results_summary.json").write_text(
        json.dumps(metrics, indent=2, ensure_ascii=False, default=_json_default), encoding="utf-8"
    )
    _checksums(
        output,
        [
            "results_summary.json",
            "effect_method_summary.csv",
            "effect_policy_summary.csv",
            "effect_sweep_summary.csv",
            "representative_effect_case.npz",
            "effect_twin_v08_report_standalone.html",
        ],
    )
    with progress.open("a", encoding="utf-8") as handle:
        handle.write(f"complete, runtime_seconds={time.perf_counter()-start:.3f}\n")
    return metrics


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default="configs/effect_twin_v08.yaml")
    parser.add_argument("--output", default="outputs_v08_effect_twin")
    args = parser.parse_args()
    run(args.config, args.output)


if __name__ == "__main__":
    main()

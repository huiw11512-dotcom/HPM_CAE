"""Normalized effect digital-twin primitives for V0.8.

All quantities are dimensionless. The code supports uncertainty propagation
and algorithm comparison without mapping results to a source power, range,
component, or calibrated physical damage threshold.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Sequence
import math

import numpy as np
from scipy.ndimage import gaussian_filter
from scipy.stats import norm

_EPS = 1e-15


@dataclass(frozen=True)
class EffectTier:
    """Dimensionless lognormal response-threshold tier."""

    name: str
    threshold_median: float
    threshold_log_sigma: float
    probability_goal: float = 0.70
    coverage_probability: float = 0.60

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("tier name must be non-empty")
        if self.threshold_median <= 0.0:
            raise ValueError("threshold_median must be positive")
        if self.threshold_log_sigma <= 0.0:
            raise ValueError("threshold_log_sigma must be positive")
        if not 0.0 <= self.probability_goal <= 1.0:
            raise ValueError("probability_goal must be in [0, 1]")
        if not 0.0 <= self.coverage_probability <= 1.0:
            raise ValueError("coverage_probability must be in [0, 1]")


@dataclass(frozen=True)
class EffectMapMetrics:
    target_mean_probability: float
    target_p10_probability: float
    target_coverage: float
    target_entropy: float
    protected_mean_probability: float
    protected_p95_probability: float
    protected_peak_probability: float
    off_target_mean_probability: float
    off_target_high_risk_fraction: float
    effect_selectivity: float
    response_efficiency: float
    mission_success: bool


@dataclass(frozen=True)
class DutyDecision:
    duty_factor: float
    objective: float
    predicted_target_mean_probability: float
    predicted_target_coverage: float
    predicted_protected_p95_probability: float
    predicted_off_target_high_risk_fraction: float


def normalized_intensity(
    field: np.ndarray,
    *,
    reference_amplitude: float,
    amplitude_exponent: float = 2.0,
) -> np.ndarray:
    if reference_amplitude <= 0.0:
        raise ValueError("reference_amplitude must be positive")
    if amplitude_exponent <= 0.0:
        raise ValueError("amplitude_exponent must be positive")
    amplitude = np.abs(np.asarray(field))
    return np.power(amplitude / float(reference_amplitude), float(amplitude_exponent))


def dose_increment(
    field: np.ndarray,
    *,
    reference_amplitude: float,
    pulse_weight: float,
    amplitude_exponent: float = 2.0,
    duty_factor: float = 1.0,
    coupling_map: np.ndarray | None = None,
) -> np.ndarray:
    if pulse_weight < 0.0:
        raise ValueError("pulse_weight must be non-negative")
    if not 0.0 <= duty_factor <= 1.0:
        raise ValueError("duty_factor must be in [0, 1]")
    increment = float(pulse_weight) * float(duty_factor) * normalized_intensity(
        field,
        reference_amplitude=reference_amplitude,
        amplitude_exponent=amplitude_exponent,
    )
    if coupling_map is not None:
        coupling = np.asarray(coupling_map, dtype=float)
        if coupling.shape != increment.shape:
            raise ValueError("coupling_map must match field shape")
        if np.any(coupling < 0.0):
            raise ValueError("coupling_map must be non-negative")
        increment = increment * coupling
    return np.asarray(increment, dtype=float)


def update_leaky_dose(
    previous_dose: np.ndarray | None,
    increment: np.ndarray,
    *,
    retention: float,
) -> np.ndarray:
    if not 0.0 <= retention <= 1.0:
        raise ValueError("retention must be in [0, 1]")
    inc = np.maximum(np.asarray(increment, dtype=float), 0.0)
    if previous_dose is None:
        previous = np.zeros_like(inc)
    else:
        previous = np.asarray(previous_dose, dtype=float)
        if previous.shape != inc.shape:
            raise ValueError("previous_dose and increment must match")
        if np.any(previous < 0.0):
            raise ValueError("previous_dose must be non-negative")
    return float(retention) * previous + inc


def lognormal_response_probability(
    cumulative_dose: np.ndarray,
    tier: EffectTier,
    *,
    coupling_log_sigma: float = 0.0,
    threshold_median_scale: float = 1.0,
) -> np.ndarray:
    if coupling_log_sigma < 0.0:
        raise ValueError("coupling_log_sigma must be non-negative")
    if threshold_median_scale <= 0.0:
        raise ValueError("threshold_median_scale must be positive")
    dose = np.maximum(np.asarray(cumulative_dose, dtype=float), 0.0)
    sigma = math.sqrt(tier.threshold_log_sigma**2 + float(coupling_log_sigma) ** 2)
    median = tier.threshold_median * float(threshold_median_scale)
    z = (np.log(np.maximum(dose, _EPS)) - math.log(median)) / max(sigma, _EPS)
    probability = norm.cdf(z)
    probability = np.where(dose <= 0.0, 0.0, probability)
    return np.clip(probability, 0.0, 1.0)


def probability_interval(
    cumulative_dose: np.ndarray,
    tier: EffectTier,
    *,
    coupling_log_sigma: float,
    epistemic_threshold_log_sigma: float,
    confidence: float = 0.95,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    if epistemic_threshold_log_sigma < 0.0:
        raise ValueError("epistemic_threshold_log_sigma must be non-negative")
    if not 0.0 < confidence < 1.0:
        raise ValueError("confidence must be in (0, 1)")
    central = lognormal_response_probability(cumulative_dose, tier, coupling_log_sigma=coupling_log_sigma)
    q = float(norm.ppf(0.5 + confidence / 2.0))
    lower = lognormal_response_probability(
        cumulative_dose,
        tier,
        coupling_log_sigma=coupling_log_sigma,
        threshold_median_scale=math.exp(q * epistemic_threshold_log_sigma),
    )
    upper = lognormal_response_probability(
        cumulative_dose,
        tier,
        coupling_log_sigma=coupling_log_sigma,
        threshold_median_scale=math.exp(-q * epistemic_threshold_log_sigma),
    )
    return central, lower, upper


def binary_entropy(probability: np.ndarray) -> np.ndarray:
    p = np.clip(np.asarray(probability, dtype=float), _EPS, 1.0 - _EPS)
    h = -(p * np.log2(p) + (1.0 - p) * np.log2(1.0 - p))
    return np.where((probability <= 0.0) | (probability >= 1.0), 0.0, h)


def _mask_values(array: np.ndarray, mask: np.ndarray, name: str) -> np.ndarray:
    values = np.asarray(array, dtype=float)
    mask_array = np.asarray(mask, dtype=bool)
    if values.shape != mask_array.shape:
        raise ValueError(f"{name} mask must match map shape")
    selected = values[mask_array]
    if selected.size == 0:
        raise ValueError(f"{name} mask must contain a sample")
    return selected


def evaluate_effect_map(
    probability: np.ndarray,
    *,
    target_mask: np.ndarray,
    protected_mask: np.ndarray,
    off_target_mask: np.ndarray,
    coverage_probability: float,
    high_risk_probability: float,
    target_goal_probability: float,
    minimum_target_coverage: float,
    maximum_protected_p95_probability: float,
    maximum_off_target_high_risk_fraction: float,
) -> EffectMapMetrics:
    p = np.clip(np.asarray(probability, dtype=float), 0.0, 1.0)
    return _metrics_from_values(
        _mask_values(p, target_mask, "target"),
        _mask_values(p, protected_mask, "protected"),
        _mask_values(p, off_target_mask, "off_target"),
        float(np.sum(p)),
        coverage_probability=coverage_probability,
        high_risk_probability=high_risk_probability,
        target_goal_probability=target_goal_probability,
        minimum_target_coverage=minimum_target_coverage,
        maximum_protected_p95_probability=maximum_protected_p95_probability,
        maximum_off_target_high_risk_fraction=maximum_off_target_high_risk_fraction,
    )


def evaluate_moving_effect_state(
    target_probability: np.ndarray,
    world_probability: np.ndarray,
    *,
    target_mask: np.ndarray,
    protected_mask: np.ndarray,
    off_target_mask: np.ndarray,
    coverage_probability: float,
    high_risk_probability: float,
    target_goal_probability: float,
    minimum_target_coverage: float,
    maximum_protected_p95_probability: float,
    maximum_off_target_high_risk_fraction: float,
) -> EffectMapMetrics:
    target_values = _mask_values(np.asarray(target_probability, float), target_mask, "target")
    world = np.clip(np.asarray(world_probability, float), 0.0, 1.0)
    protected_values = _mask_values(world, protected_mask, "protected")
    outside_values = _mask_values(world, off_target_mask, "off_target")
    return _metrics_from_values(
        target_values,
        protected_values,
        outside_values,
        float(np.sum(world)) + float(np.sum(target_values)),
        coverage_probability=coverage_probability,
        high_risk_probability=high_risk_probability,
        target_goal_probability=target_goal_probability,
        minimum_target_coverage=minimum_target_coverage,
        maximum_protected_p95_probability=maximum_protected_p95_probability,
        maximum_off_target_high_risk_fraction=maximum_off_target_high_risk_fraction,
    )


def _metrics_from_values(
    target: np.ndarray,
    protected: np.ndarray,
    outside: np.ndarray,
    total_probability: float,
    *,
    coverage_probability: float,
    high_risk_probability: float,
    target_goal_probability: float,
    minimum_target_coverage: float,
    maximum_protected_p95_probability: float,
    maximum_off_target_high_risk_fraction: float,
) -> EffectMapMetrics:
    target_mean = float(np.mean(target))
    target_p10 = float(np.quantile(target, 0.10))
    target_coverage = float(np.mean(target >= float(coverage_probability)))
    target_entropy = float(np.mean(binary_entropy(target)))
    protected_mean = float(np.mean(protected))
    protected_p95 = float(np.quantile(protected, 0.95))
    protected_peak = float(np.max(protected))
    outside_mean = float(np.mean(outside))
    outside_high = float(np.mean(outside >= float(high_risk_probability)))
    response_efficiency = float(np.sum(target) / max(total_probability, _EPS))
    selectivity = float(target_mean - max(protected_p95, outside_mean))
    success = bool(
        target_mean >= float(target_goal_probability)
        and target_coverage >= float(minimum_target_coverage)
        and protected_p95 <= float(maximum_protected_p95_probability)
        and outside_high <= float(maximum_off_target_high_risk_fraction)
    )
    return EffectMapMetrics(
        target_mean, target_p10, target_coverage, target_entropy,
        protected_mean, protected_p95, protected_peak,
        outside_mean, outside_high, selectivity, response_efficiency, success,
    )


def correlated_lognormal_map(
    shape: Sequence[int],
    *,
    log_sigma: float,
    correlation_pixels: float,
    rng: np.random.Generator,
) -> np.ndarray:
    if log_sigma < 0.0 or correlation_pixels < 0.0:
        raise ValueError("uncertainty parameters must be non-negative")
    shape_tuple = tuple(int(v) for v in shape)
    if any(v <= 0 for v in shape_tuple):
        raise ValueError("shape dimensions must be positive")
    if log_sigma == 0.0:
        return np.ones(shape_tuple)
    field = rng.normal(size=shape_tuple)
    if correlation_pixels > 0.0:
        field = gaussian_filter(field, sigma=float(correlation_pixels), mode="reflect")
    field = (field - float(np.mean(field))) / max(float(np.std(field)), _EPS)
    return np.exp(float(log_sigma) * field)


def choose_effect_aware_duty(
    *,
    previous_target_dose: np.ndarray,
    target_full_increment: np.ndarray,
    target_mask: np.ndarray,
    previous_world_dose: np.ndarray,
    world_full_increment: np.ndarray,
    protected_mask: np.ndarray,
    off_target_mask: np.ndarray,
    tier: EffectTier,
    candidate_duties: Iterable[float],
    retention: float,
    coupling_log_sigma: float,
    coverage_probability: float,
    high_risk_probability: float,
    target_goal_probability: float,
    target_upper_probability: float,
    protected_probability_limit: float,
    off_target_high_risk_limit: float,
    weights: Sequence[float],
    previous_duty: float = 1.0,
    prediction_horizon: int = 1,
) -> DutyDecision:
    duties = sorted({float(v) for v in candidate_duties})
    if not duties or duties[0] < 0.0 or duties[-1] > 1.0:
        raise ValueError("candidate_duties must be within [0, 1]")
    if len(weights) != 6 or any(float(v) < 0.0 for v in weights):
        raise ValueError("weights must contain six non-negative values")
    if int(prediction_horizon) < 1:
        raise ValueError("prediction_horizon must be at least one")
    sw, ow, pw, rw, ew, cw = map(float, weights)
    best: DutyDecision | None = None
    for duty in duties:
        target_dose = np.asarray(previous_target_dose, dtype=float).copy()
        world_dose = np.asarray(previous_world_dose, dtype=float).copy()
        for _ in range(int(prediction_horizon)):
            target_dose = update_leaky_dose(target_dose, duty * target_full_increment, retention=retention)
            world_dose = update_leaky_dose(world_dose, duty * world_full_increment, retention=retention)
        p_target = lognormal_response_probability(target_dose, tier, coupling_log_sigma=coupling_log_sigma)
        p_world = lognormal_response_probability(world_dose, tier, coupling_log_sigma=coupling_log_sigma)
        t = _mask_values(p_target, target_mask, "target")
        pz = _mask_values(p_world, protected_mask, "protected")
        out = _mask_values(p_world, off_target_mask, "off_target")
        tm = float(np.mean(t))
        tc = float(np.mean(t >= coverage_probability))
        pp95 = float(np.quantile(pz, 0.95))
        oh = float(np.mean(out >= high_risk_probability))
        objective = (
            sw * max(target_goal_probability - tm, 0.0) ** 2
            + ow * max(tm - target_upper_probability, 0.0) ** 2
            + pw * max(pp95 - protected_probability_limit, 0.0) ** 2
            + rw * max(oh - off_target_high_risk_limit, 0.0) ** 2
            + ew * duty
            + cw * (duty - float(previous_duty)) ** 2
        )
        decision = DutyDecision(duty, float(objective), tm, tc, pp95, oh)
        if best is None or decision.objective < best.objective - 1e-12 or (
            abs(decision.objective - best.objective) <= 1e-12 and duty < best.duty_factor
        ):
            best = decision
    assert best is not None
    return best

"""Direction-of-arrival matching and uncertainty summaries."""
from __future__ import annotations

from dataclasses import dataclass
import math
import numpy as np
from scipy.optimize import linear_sum_assignment
from scipy.stats import t

from hpm_platform.evaluation.metrics import angular_error_deg


@dataclass(frozen=True)
class DirectionMatch:
    ordered_estimates: tuple[tuple[float, float], ...]
    errors_deg: tuple[float, ...]

    @property
    def rmse_deg(self) -> float:
        return float(np.sqrt(np.mean(np.square(self.errors_deg))))

    @property
    def max_error_deg(self) -> float:
        return float(np.max(self.errors_deg))


def match_directions(
    estimates: list[tuple[float, float]] | tuple[tuple[float, float], ...],
    truths: list[tuple[float, float]] | tuple[tuple[float, float], ...],
) -> DirectionMatch:
    """Assign estimated directions to truths using minimum great-circle error."""

    estimates = tuple((float(a), float(b)) for a, b in estimates)
    truths = tuple((float(a), float(b)) for a, b in truths)
    if len(truths) == 0:
        raise ValueError("At least one truth direction is required")
    if len(estimates) < len(truths):
        raise ValueError("Number of estimates must be at least number of truths")

    cost = np.empty((len(truths), len(estimates)), dtype=float)
    for i, truth in enumerate(truths):
        for j, estimate in enumerate(estimates):
            cost[i, j] = angular_error_deg(estimate, truth)
    truth_indices, estimate_indices = linear_sum_assignment(cost)

    ordered: list[tuple[float, float] | None] = [None] * len(truths)
    errors = np.empty(len(truths), dtype=float)
    for truth_index, estimate_index in zip(truth_indices, estimate_indices):
        ordered[truth_index] = estimates[estimate_index]
        errors[truth_index] = cost[truth_index, estimate_index]
    return DirectionMatch(
        ordered_estimates=tuple(value for value in ordered if value is not None),
        errors_deg=tuple(float(value) for value in errors),
    )


def mean_confidence_interval(
    values: np.ndarray | list[float], confidence: float = 0.95
) -> tuple[float, float, float]:
    """Return sample mean and Student-t confidence interval."""

    data = np.asarray(values, dtype=float)
    data = data[np.isfinite(data)]
    if data.size == 0:
        return math.nan, math.nan, math.nan
    mean = float(np.mean(data))
    if data.size == 1:
        return mean, mean, mean
    sem = float(np.std(data, ddof=1) / np.sqrt(data.size))
    half = float(t.ppf(0.5 + confidence / 2.0, data.size - 1) * sem)
    return mean, mean - half, mean + half


def wilson_interval(
    successes: int, total: int, confidence: float = 0.95
) -> tuple[float, float, float]:
    """Return a binomial proportion and Wilson score interval."""

    if total < 1 or not 0 <= successes <= total:
        raise ValueError("Require 0 <= successes <= total and total >= 1")
    # 1.959963984540054 for the default 95%; use scipy's t-independent normal
    # quantile through a compact approximation for arbitrary confidence.
    from scipy.stats import norm

    z = float(norm.ppf(0.5 + confidence / 2.0))
    p = successes / total
    denominator = 1.0 + z**2 / total
    center = (p + z**2 / (2.0 * total)) / denominator
    half = z * np.sqrt(p * (1.0 - p) / total + z**2 / (4.0 * total**2)) / denominator
    return float(p), float(max(0.0, center - half)), float(min(1.0, center + half))

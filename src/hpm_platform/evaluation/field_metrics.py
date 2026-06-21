"""Metrics for normalized near-field region-control experiments."""
from __future__ import annotations

from dataclasses import asdict, dataclass
import numpy as np


@dataclass(frozen=True)
class FieldControlMetrics:
    target_mean: float
    target_rmse_fraction: float
    target_cv_fraction: float
    target_coverage: float
    peak_outside_db: float
    p95_outside_db: float
    outside_area_above_minus6db: float
    outside_area_above_minus10db: float
    sampled_plane_efficiency: float
    control_success: bool

    def to_dict(self) -> dict[str, float | bool]:
        return asdict(self)


def evaluate_field_control(
    field: np.ndarray,
    target_mask: np.ndarray,
    outside_mask: np.ndarray,
    *,
    target_amplitude: float,
    tolerance_fraction: float = 0.10,
    success_rmse_fraction: float = 0.12,
    success_min_coverage: float = 0.60,
    success_max_peak_outside_db: float = -2.0,
) -> FieldControlMetrics:
    """Evaluate a complex field map using normalized algorithmic criteria."""
    values = np.abs(np.asarray(field, dtype=complex))
    target = np.asarray(target_mask, dtype=bool)
    outside = np.asarray(outside_mask, dtype=bool)
    if values.shape != target.shape or values.shape != outside.shape:
        raise ValueError("field and masks must have identical shapes")
    if not np.any(target) or not np.any(outside):
        raise ValueError("target_mask and outside_mask must both contain samples")
    if target_amplitude <= 0 or tolerance_fraction < 0:
        raise ValueError("target_amplitude must be positive and tolerance non-negative")

    target_values = values[target]
    outside_values = values[outside]
    target_mean = float(np.mean(target_values))
    rmse = float(np.sqrt(np.mean((target_values - target_amplitude) ** 2)) / target_amplitude)
    cv = float(np.std(target_values) / max(target_mean, np.finfo(float).tiny))
    coverage = float(
        np.mean(np.abs(target_values - target_amplitude) <= tolerance_fraction * target_amplitude)
    )
    peak_db = float(20.0 * np.log10(max(float(np.max(outside_values)) / target_amplitude, 1e-12)))
    p95_db = float(
        20.0 * np.log10(max(float(np.quantile(outside_values, 0.95)) / target_amplitude, 1e-12))
    )
    area_minus6 = float(np.mean(outside_values > 10.0 ** (-6.0 / 20.0) * target_amplitude))
    area_minus10 = float(np.mean(outside_values > 10.0 ** (-10.0 / 20.0) * target_amplitude))
    total_energy = float(np.sum(values**2))
    efficiency = float(np.sum(target_values**2) / max(total_energy, np.finfo(float).tiny))
    success = bool(
        rmse <= success_rmse_fraction
        and coverage >= success_min_coverage
        and peak_db <= success_max_peak_outside_db
    )
    return FieldControlMetrics(
        target_mean=target_mean,
        target_rmse_fraction=rmse,
        target_cv_fraction=cv,
        target_coverage=coverage,
        peak_outside_db=peak_db,
        p95_outside_db=p95_db,
        outside_area_above_minus6db=area_minus6,
        outside_area_above_minus10db=area_minus10,
        sampled_plane_efficiency=efficiency,
        control_success=success,
    )

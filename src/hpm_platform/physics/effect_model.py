"""Dimensionless probabilistic response model.

This module is intentionally *not* a calibrated device-damage model. It maps a
normalized field-derived stress index into a response probability under a
lognormal threshold distribution. It is suitable for sensitivity analysis,
algorithm comparison, uncertainty propagation, and paper figures without
claiming a real hardware threshold.
"""
from __future__ import annotations

from dataclasses import dataclass
import numpy as np
from scipy.stats import lognorm


@dataclass(frozen=True)
class NormalizedEffectModel:
    threshold_median: float = 0.55
    threshold_log_sigma: float = 0.22
    pulse_width_exponent: float = 0.5
    pulse_count_exponent: float = 0.25

    def __post_init__(self) -> None:
        if self.threshold_median <= 0:
            raise ValueError("threshold_median must be positive")
        if self.threshold_log_sigma <= 0:
            raise ValueError("threshold_log_sigma must be positive")

    def stress_index(
        self,
        normalized_intensity: np.ndarray,
        pulse_width_norm: float = 1.0,
        pulse_count: int = 1,
    ) -> np.ndarray:
        if pulse_width_norm <= 0 or pulse_count < 1:
            raise ValueError("pulse_width_norm must be positive and pulse_count >= 1")
        intensity = np.maximum(np.asarray(normalized_intensity, float), 0.0)
        return (
            intensity
            * pulse_width_norm ** self.pulse_width_exponent
            * pulse_count ** self.pulse_count_exponent
        )

    def probability(
        self,
        normalized_intensity: np.ndarray,
        pulse_width_norm: float = 1.0,
        pulse_count: int = 1,
    ) -> np.ndarray:
        stress = self.stress_index(normalized_intensity, pulse_width_norm, pulse_count)
        return lognorm.cdf(
            stress,
            s=self.threshold_log_sigma,
            scale=self.threshold_median,
        )

    def median_margin_db(
        self,
        normalized_intensity: np.ndarray,
        pulse_width_norm: float = 1.0,
        pulse_count: int = 1,
    ) -> np.ndarray:
        stress = self.stress_index(normalized_intensity, pulse_width_norm, pulse_count)
        return 10.0 * np.log10(np.maximum(stress, 1e-15) / self.threshold_median)

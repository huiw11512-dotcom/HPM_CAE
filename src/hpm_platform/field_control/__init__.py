"""Normalized near-field focusing, region shaping, and dynamic control."""

from .dynamic_region_control import (
    DynamicDesignResult,
    PlanarKalmanTracker,
    PlanarPrediction,
    PlanarUpdate,
    covariance_sigma_centers,
    ellipse_sample_points_lambda,
    robust_dynamic_region_ls,
    sample_outside_points_lambda,
    update_feedback_scale,
)

__all__ = [
    "DynamicDesignResult",
    "PlanarKalmanTracker",
    "PlanarPrediction",
    "PlanarUpdate",
    "covariance_sigma_centers",
    "ellipse_sample_points_lambda",
    "robust_dynamic_region_ls",
    "sample_outside_points_lambda",
    "update_feedback_scale",
]

from .multiobjective import (
    GroupedScenarioSet,
    MultiObjectiveShapingResult,
    projected_adam_multi_object,
    sample_grouped_scenarios,
)

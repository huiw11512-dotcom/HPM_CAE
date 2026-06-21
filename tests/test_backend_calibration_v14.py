from pathlib import Path

import numpy as np
import pytest

from hpm_platform.ui.project_model import CAEProject
from hpm_platform.validation.backend_calibration import (
    calibrate_backend_scales,
    generate_reference_samples,
)

ROOT = Path(__file__).resolve().parents[1]


def test_hybrid_scale_calibration_recovers_noise_free_truth():
    project = CAEProject.load_yaml(ROOT / "configs" / "cae_project_v14.yaml")
    truth = (0.86, 0.72, 0.93)
    samples = generate_reference_samples(
        project,
        reference_backend="hybrid_scene",
        reference_scales=truth,
        samples_per_axis=9,
        noise_std_fraction=0.0,
    )
    result = calibrate_backend_scales(
        project,
        samples,
        candidate_backend="hybrid_scene",
        initial_scales=(0.50, 0.40, 0.40),
        maximum_evaluations=40,
    )
    assert result.success
    assert result.fitted_scales == pytest.approx(truth, abs=2e-6)
    assert result.relative_rmse_after_percent < 1e-5
    assert result.r2_after > 0.999999
    assert result.improvement_percent > 99.9
    assert np.all(np.isfinite(result.fitted_field))


def test_calibration_summary_is_chinese():
    project = CAEProject.load_yaml(ROOT / "configs" / "cae_project_v14.yaml")
    result = calibrate_backend_scales(
        project,
        reference_backend="hybrid_scene",
        candidate_backend="hybrid_scene",
        reference_scales=(0.8, 0.6, 0.8),
        initial_scales=(0.6, 0.4, 0.5),
        samples_per_axis=9,
        maximum_evaluations=30,
    )
    summary = result.summary_dict()
    assert "标定前相对RMSE/%" in summary
    assert "直达尺度标定值" in summary

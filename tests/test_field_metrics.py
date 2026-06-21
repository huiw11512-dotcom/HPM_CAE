import numpy as np
import pytest

from hpm_platform.evaluation.field_metrics import evaluate_field_control


def test_perfect_normalized_field_passes_joint_criterion():
    field = np.zeros((5, 5), dtype=complex)
    target = np.zeros((5, 5), dtype=bool)
    target[2, 2] = True
    outside = ~target
    field[target] = 0.5
    result = evaluate_field_control(field, target, outside, target_amplitude=0.5)
    assert result.target_rmse_fraction == 0.0
    assert result.target_coverage == 1.0
    assert result.control_success


def test_large_outside_peak_fails_joint_criterion():
    field = np.zeros((5, 5), dtype=complex)
    target = np.zeros((5, 5), dtype=bool)
    target[1:4, 1:4] = True
    outside = ~target
    field[target] = 0.5
    field[0, 0] = 0.6
    result = evaluate_field_control(field, target, outside, target_amplitude=0.5)
    assert result.peak_outside_db > 0.0
    assert not result.control_success


def test_metric_shape_mismatch_raises():
    with pytest.raises(ValueError):
        evaluate_field_control(
            np.zeros((3, 3), dtype=complex),
            np.zeros((2, 2), dtype=bool),
            np.ones((3, 3), dtype=bool),
            target_amplitude=1.0,
        )

import numpy as np

from hpm_platform.field_control.dynamic_region_control import (
    PlanarKalmanTracker,
    covariance_sigma_centers,
    ellipse_sample_points_lambda,
    robust_dynamic_region_ls,
    sample_outside_points_lambda,
    update_feedback_scale,
)
from hpm_platform.field_control.region_shaping import point_focus_reference_scale
from hpm_platform.physics.array_geometry import C0, RectangularArray


def _array() -> RectangularArray:
    frequency = 10.0e9
    spacing = 0.5 * C0 / frequency
    return RectangularArray(4, 4, frequency, spacing, spacing)


def test_tracker_assimilates_delayed_measurement_and_predicts_forward() -> None:
    tracker = PlanarKalmanTracker([0.0, 0.0], process_acceleration_std_lambda_per_frame2=0.01)
    tracker.update([0.5, -0.2], np.eye(2) * 0.01, measurement_time=2.0)
    tracker.update([0.9, -0.2], np.eye(2) * 0.01, measurement_time=4.0)
    prediction = tracker.predict(6.0)
    assert prediction.mean_lambda[0] > 0.9
    assert prediction.covariance_lambda2.shape == (2, 2)
    assert np.all(np.linalg.eigvalsh(prediction.covariance_lambda2) > 0)


def test_covariance_sigma_centers_are_symmetric_about_mean() -> None:
    mean = np.array([1.2, -0.4])
    centers = covariance_sigma_centers(mean, np.diag([0.25, 0.04]), sigma_scale=2.0)
    assert centers.shape == (5, 2)
    assert np.allclose(centers[0], mean)
    assert np.allclose(np.mean(centers[1:], axis=0), mean)


def test_ellipse_samples_remain_inside_rotated_region() -> None:
    center = np.array([0.6, -0.3])
    axes = np.array([1.1, 0.5])
    rotation = 27.0
    points = ellipse_sample_points_lambda(
        center,
        axes,
        rotation_deg=rotation,
        z_lambda=8.0,
        radial_samples=5,
        angular_samples=10,
    )
    angle = np.deg2rad(rotation)
    delta = points[:, :2] - center
    xr = np.cos(angle) * delta[:, 0] + np.sin(angle) * delta[:, 1]
    yr = -np.sin(angle) * delta[:, 0] + np.cos(angle) * delta[:, 1]
    radius = np.sqrt((xr / axes[0]) ** 2 + (yr / axes[1]) ** 2)
    assert np.max(radius) <= 1.0 + 1e-12
    assert np.allclose(points[:, 2], 8.0)


def test_dynamic_region_ls_returns_bounded_finite_weights() -> None:
    array = _array()
    focus = array.wavelength_m * np.array([0.0, 0.0, 6.0])
    reference = point_focus_reference_scale(array, focus)
    outside = sample_outside_points_lambda(
        [-3.0, 3.0],
        [-3.0, 3.0],
        z_lambda=6.0,
        center_lambda=[0.0, 0.0],
        semi_axes_lambda=[0.8, 0.5],
        rotation_deg=15.0,
        guard_scale=1.5,
        n_points=80,
        seed=1,
    )
    result = robust_dynamic_region_ls(
        array,
        np.array([[0.0, 0.0], [0.2, 0.0], [-0.2, 0.0]]),
        semi_axes_lambda=[0.8, 0.5],
        rotation_deg=15.0,
        z_lambda=6.0,
        outside_points_lambda=outside,
        reference_scale=reference,
        target_amplitude=0.45,
        outside_penalty=0.05,
        ridge=1e-3,
        rms_limit=0.8,
        peak_limit=1.0,
        radial_samples=3,
        angular_samples=8,
    )
    assert result.weights.shape == (array.n_elements,)
    assert np.all(np.isfinite(result.weights))
    assert np.max(np.abs(result.weights)) <= 1.0 + 1e-9
    assert np.sqrt(np.mean(np.abs(result.weights) ** 2)) <= 0.8 + 1e-9
    assert result.runtime_ms >= 0.0


def test_feedback_scale_is_directional_and_bounded() -> None:
    low = update_feedback_scale(1.0, 0.35, target_amplitude=0.5)
    high = update_feedback_scale(1.0, 0.70, target_amplitude=0.5)
    assert low > 1.0
    assert high < 1.0
    clipped = update_feedback_scale(1.28, 0.01, target_amplitude=0.5)
    assert clipped <= 1.28

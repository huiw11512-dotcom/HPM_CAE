import numpy as np

from hpm_platform.field_control.region_shaping import (
    magnitude_objective_gradient,
    point_focus_reference_scale,
    project_excitation,
    projected_adam_magnitude_shaping,
    rotated_ellipse_masks,
    sample_linear_scenarios,
    scalar_green_matrix,
    unit_rms_point_focus_weights,
)
from hpm_platform.physics.array_geometry import RectangularArray


def _array() -> RectangularArray:
    return RectangularArray(4, 4, 10e9)


def test_rotated_ellipse_masks_are_disjoint_and_complete():
    x = np.linspace(-2.0, 2.0, 41)
    y = np.linspace(-2.0, 2.0, 41)
    xx, yy = np.meshgrid(x, y, indexing="xy")
    masks = rotated_ellipse_masks(
        xx,
        yy,
        center_m=(0.2, -0.1),
        semi_axes_m=(0.8, 0.45),
        rotation_deg=30.0,
        guard_scale=1.4,
    )
    assert not np.any(masks.target & masks.guard)
    assert not np.any(masks.target & masks.outside)
    assert not np.any(masks.guard & masks.outside)
    assert np.all(masks.target | masks.guard | masks.outside)


def test_point_focus_reference_normalizes_unit_rms_focus_to_one():
    array = _array()
    focus = np.array([0.2, -0.1, 8.0]) * array.wavelength_m
    reference = point_focus_reference_scale(array, focus)
    matrix = scalar_green_matrix(array, focus[None, :], reference_scale=reference)
    weights = unit_rms_point_focus_weights(array, focus, rms_amplitude=1.0)
    assert np.isclose(np.abs(matrix @ weights).item(), 1.0, atol=1e-12)


def test_excitation_projection_obeys_rms_and_peak_limits():
    values = np.array([3 + 4j, 2 - 1j, -5j, 0.1 + 0.2j])
    projected = project_excitation(values, rms_limit=0.8, peak_limit=1.0)
    assert np.max(np.abs(projected)) <= 1.0 + 1e-12
    assert np.sqrt(np.mean(np.abs(projected) ** 2)) <= 0.8 + 1e-12


def test_magnitude_gradient_produces_descent_direction():
    rng = np.random.default_rng(3)
    target = rng.normal(size=(8, 5)) + 1j * rng.normal(size=(8, 5))
    outside = rng.normal(size=(11, 5)) + 1j * rng.normal(size=(11, 5))
    weights = rng.normal(size=5) + 1j * rng.normal(size=5)
    objective, gradient = magnitude_objective_gradient(
        weights,
        [target],
        [outside],
        target_amplitude=0.6,
        outside_hinge_amplitude=0.2,
        outside_penalty=0.8,
    )
    step = weights - 1e-4 * gradient
    objective_after, _ = magnitude_objective_gradient(
        step,
        [target],
        [outside],
        target_amplitude=0.6,
        outside_hinge_amplitude=0.2,
        outside_penalty=0.8,
    )
    assert objective_after < objective


def test_projected_optimizer_reduces_training_objective():
    rng = np.random.default_rng(4)
    target = rng.normal(size=(20, 6)) + 1j * rng.normal(size=(20, 6))
    outside = 0.4 * (rng.normal(size=(30, 6)) + 1j * rng.normal(size=(30, 6)))
    initial = np.ones(6, dtype=complex) * 0.2
    result = projected_adam_magnitude_shaping(
        initial,
        [target],
        [outside],
        target_amplitude=0.7,
        outside_hinge_amplitude=0.2,
        outside_penalty=0.5,
        rms_limit=0.8,
        peak_limit=1.0,
        iterations=80,
        learning_rate=0.02,
    )
    assert np.min(result.objective_history) < result.objective_history[0]
    assert np.max(np.abs(result.weights)) <= 1.0 + 1e-12


def test_scenario_generator_returns_expected_shapes():
    array = _array()
    wavelength = array.wavelength_m
    target_points = np.array([[0.0, 0.0, 6.0], [0.2, 0.1, 6.0]]) * wavelength
    outside_points = np.array([[1.0, 1.0, 6.0], [-1.0, 1.0, 6.0], [1.0, -1.0, 6.0]]) * wavelength
    reference = point_focus_reference_scale(array, np.array([0.0, 0.0, 6.0]) * wavelength)
    scenarios = sample_linear_scenarios(
        array,
        target_points,
        outside_points,
        reference_scale=reference,
        n_scenarios=3,
        gain_std_fraction=0.03,
        phase_std_deg=4.0,
        registration_jitter_std_lambda=0.1,
        seed=5,
    )
    assert len(scenarios.target_matrices) == 3
    assert scenarios.target_matrices[0].shape == (2, array.n_elements)
    assert scenarios.outside_matrices[0].shape == (3, array.n_elements)
    assert np.allclose(scenarios.gain_vectors[0], 1.0)

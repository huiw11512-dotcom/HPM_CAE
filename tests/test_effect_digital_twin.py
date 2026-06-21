import numpy as np

from hpm_platform.evaluation.effect_digital_twin import (
    EffectTier, choose_effect_aware_duty, correlated_lognormal_map,
    dose_increment, evaluate_effect_map, probability_interval, update_leaky_dose,
)


def test_probability_monotonic_and_interval_ordered():
    tier = EffectTier("tier", 0.8, 0.25)
    dose = np.linspace(0.0, 2.0, 101)
    p, low, high = probability_interval(dose, tier, coupling_log_sigma=0.2, epistemic_threshold_log_sigma=0.15)
    assert np.all(np.diff(p) >= -1e-12)
    assert np.all(low <= p + 1e-12) and np.all(p <= high + 1e-12)
    assert p[0] == 0.0


def test_leaky_dose_recurrence():
    dose = None
    for _ in range(3):
        dose = update_leaky_dose(dose, np.array([1.0]), retention=0.5)
    assert np.allclose(dose, [1.75])


def test_effect_metrics_separate_regions():
    p = np.zeros((4, 4)); p[:2, :2] = 0.9
    target = np.zeros_like(p, bool); target[:2, :2] = True
    protected = np.zeros_like(p, bool); protected[2:, 2:] = True
    metrics = evaluate_effect_map(
        p, target_mask=target, protected_mask=protected, off_target_mask=~target,
        coverage_probability=0.6, high_risk_probability=0.2,
        target_goal_probability=0.7, minimum_target_coverage=0.8,
        maximum_protected_p95_probability=0.1, maximum_off_target_high_risk_fraction=0.1,
    )
    assert metrics.target_mean_probability > 0.85
    assert metrics.protected_peak_probability == 0.0
    assert metrics.mission_success


def test_correlated_map_positive_and_reproducible():
    a = correlated_lognormal_map((20, 20), log_sigma=0.3, correlation_pixels=2.0, rng=np.random.default_rng(7))
    b = correlated_lognormal_map((20, 20), log_sigma=0.3, correlation_pixels=2.0, rng=np.random.default_rng(7))
    assert np.all(a > 0.0) and np.allclose(a, b)


def test_effect_aware_duty_can_stop_after_goal():
    tier = EffectTier("tier", 0.5, 0.2)
    previous_target = np.full((5, 5), 2.0)
    previous_world = np.zeros((5, 5))
    increment = np.ones((5, 5))
    target = np.ones((5, 5), bool)
    protected = np.zeros((5, 5), bool); protected[0, 0] = True
    outside = np.ones((5, 5), bool); outside[2, 2] = False
    d = choose_effect_aware_duty(
        previous_target_dose=previous_target, target_full_increment=increment, target_mask=target,
        previous_world_dose=previous_world, world_full_increment=increment,
        protected_mask=protected, off_target_mask=outside, tier=tier,
        candidate_duties=[0.0, 0.5, 1.0], retention=1.0, coupling_log_sigma=0.0,
        coverage_probability=0.6, high_risk_probability=0.2,
        target_goal_probability=0.7, target_upper_probability=0.9,
        protected_probability_limit=0.1, off_target_high_risk_limit=0.1,
        weights=[20.0, 5.0, 10.0, 10.0, 0.5, 0.0], previous_duty=0.0,
    )
    assert d.duty_factor == 0.0


def test_dose_increment_linear_in_duty():
    f = np.ones((3, 3), complex)
    full = dose_increment(f, reference_amplitude=1.0, pulse_weight=0.2, duty_factor=1.0)
    half = dose_increment(f, reference_amplitude=1.0, pulse_weight=0.2, duty_factor=0.5)
    assert np.allclose(half, 0.5 * full)

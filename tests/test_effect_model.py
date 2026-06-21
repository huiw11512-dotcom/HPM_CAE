import numpy as np

from hpm_platform.physics.effect_model import NormalizedEffectModel


def test_probability_is_bounded_and_monotonic():
    model = NormalizedEffectModel()
    intensity = np.linspace(0.0, 1.0, 101)
    probability = model.probability(intensity)
    assert np.all((probability >= 0.0) & (probability <= 1.0))
    assert np.all(np.diff(probability) >= 0.0)

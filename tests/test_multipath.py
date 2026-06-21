import numpy as np

from hpm_platform.physics.array_geometry import RectangularArray
from hpm_platform.signal.multipath import (
    CoherentEmitter,
    CoherentPath,
    simulate_coherent_multipath,
)


def test_paths_of_one_emitter_are_fully_coherent_without_noise_component():
    array = RectangularArray(4, 4, 10e9)
    emitter = CoherentEmitter(
        reference_power_db=20.0,
        paths=(
            CoherentPath(12.0, -5.0, label="direct"),
            CoherentPath(32.0, 9.0, relative_power_db=-3.0, phase_deg=40.0, label="echo"),
        ),
    )
    _, components = simulate_coherent_multipath(array, [emitter], 128, seed=7)
    first = components["emitter:direct"]
    second = components["emitter:echo"]
    # Each path matrix has rank one, and both share the same temporal row space.
    assert np.linalg.matrix_rank(first, tol=1e-9) == 1
    assert np.linalg.matrix_rank(second, tol=1e-9) == 1
    normalized_first = first[0] / np.linalg.norm(first[0])
    normalized_second = second[0] / np.linalg.norm(second[0])
    assert np.isclose(abs(np.vdot(normalized_first, normalized_second)), 1.0)

from __future__ import annotations

import copy

import numpy as np

from hpmdt.application.factories import (
    city_dynamic_project,
    make_moving_aircraft,
    static_multi_receiver_project,
)
from hpmdt.solvers.free_space import run_free_space


def test_static_solver_runs_multi_receiver():
    project = static_multi_receiver_project()
    result = run_free_space(project, project.missions[0])
    assert result.summary.frame_count == 1
    assert result.summary.emitter_count == 1
    assert result.summary.receiver_count == 3
    assert result.plane_field.shape[0] == 1
    assert 0 <= result.plane_field.min() <= result.plane_field.max() <= 1.0 + 1e-12


def test_dynamic_solver_runs_two_arrays_three_moving_objects():
    project = city_dynamic_project()
    project.missions[0].time_grid.frame_count = 3
    probe = next(item for item in project.scene.entities if item.has_component("probe"))
    probe.component("probe").resolution = [10, 8, 1]
    result = run_free_space(project, project.missions[0])
    assert result.summary.emitter_count == 2
    assert result.summary.moving_entity_count == 3
    assert result.summary.receiver_count == 4
    assert result.plane_field.shape == (3, 8, 10)
    assert all(values.shape == (3,) for values in result.receiver_amplitudes.values())


def test_solver_accepts_twenty_motion_entities_without_fixed_ids():
    project = city_dynamic_project()
    project.scene.entities = [
        item for item in project.scene.entities if not item.has_role("trackable")
    ]
    for index in range(20):
        project.scene.entities.append(
            make_moving_aircraft(
                f"对象{index}",
                [(0, (-20 + index, 0, 10)), (1, (20 - index, 5, 12))],
            )
        )
    project.missions[0].time_grid.stop_s = 1
    project.missions[0].time_grid.frame_count = 2
    probe = next(item for item in project.scene.entities if item.has_component("probe"))
    probe.component("probe").resolution = [6, 5, 1]
    result = run_free_space(project, project.missions[0])
    assert result.summary.moving_entity_count == 20
    assert result.summary.receiver_count == 21


def test_result_is_reproducible_for_same_project():
    project_a = static_multi_receiver_project()
    project_b = copy.deepcopy(project_a)
    result_a = run_free_space(project_a, project_a.missions[0])
    result_b = run_free_space(project_b, project_b.missions[0])
    np.testing.assert_allclose(result_a.plane_field, result_b.plane_field)
    for key_a, key_b in zip(result_a.receiver_amplitudes, result_b.receiver_amplitudes):
        np.testing.assert_allclose(result_a.receiver_amplitudes[key_a], result_b.receiver_amplitudes[key_b])

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import numpy as np

from hpm_platform.ui.experiment_manager import (
    ExperimentDatabase,
    SweepSpec,
    run_sweep,
    set_project_parameter,
)
from hpm_platform.ui.project_model import CAEProject, default_project
from hpm_platform.ui.scene_editor import scene_editor_value
from hpm_platform.ui.task_graph import GRAPH, default_selection, make_task_graph_figure
from hpm_platform.ui.timeline import make_timeline_animation, run_timeline


def test_v09_project_payload_migrates_to_v10():
    project = default_project()
    payload = project.to_dict()
    payload["schema_version"] = "0.9"
    payload.pop("motion")
    payload.pop("workflow")
    migrated = CAEProject.from_dict(payload)
    assert migrated.schema_version == "1.4"
    assert migrated.motion.enabled is True
    assert "field_control" in migrated.workflow.enabled_nodes


def test_scene_editor_payload_contains_motion_and_geometry():
    payload = scene_editor_value(default_project())
    assert '"target_x"' in payload
    assert '"motion_path"' in payload
    assert len(payload) > 300


def test_task_graph_closure_adds_dependencies_and_is_acyclic():
    closure = GRAPH.closure(["effect_proxy"])
    assert closure[-1] == "effect_proxy"
    assert "scene" in closure
    assert "field_control" in closure
    assert "perception" in closure
    assert "protection" in closure
    plan = GRAPH.compile_plan(["effect_proxy"])
    assert len(plan) == len(closure)
    assert len(make_task_graph_figure(default_selection()).data) > 10


def test_three_frame_timeline_is_finite_and_animated():
    project = default_project()
    project = replace(
        project,
        motion=replace(project.motion, frames=3, preview_samples=31, observation_delay_frames=1),
    )
    result = run_timeline(project)
    assert result.fields.shape == (3, 31, 31)
    assert np.isfinite(result.fields).all()
    assert result.metrics["target_rmse_percent"].mean() < 20.0
    assert len(make_timeline_animation(result).frames) == 3


def test_sweep_persists_runs_to_sqlite(tmp_path: Path):
    database = ExperimentDatabase(tmp_path / "experiments.sqlite3")
    project = default_project()
    spec = SweepSpec(
        parameter="solver.phase_std_deg",
        start=0.0,
        stop=2.0,
        points=2,
        replicates=1,
        metric="target_rmse_percent",
        fast_mode=True,
    )
    result = run_sweep(project, spec, database)
    assert len(result.records) == 2
    assert (result.records["status"] == "completed").all()
    assert len(database.history()) == 1
    assert len(database.runs(result.experiment_id)) == 2


def test_nested_parameter_replacement_preserves_other_sections():
    project = default_project()
    updated = set_project_parameter(project, "solver.target_amplitude", 0.55)
    assert updated.solver.target_amplitude == 0.55
    assert updated.array == project.array

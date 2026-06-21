from dataclasses import replace
from pathlib import Path

import numpy as np

from hpm_platform.ui.app_v12 import build_app
from hpm_platform.ui.exporter import export_result_bundle
from hpm_platform.ui.pareto import export_pareto_bundle, run_pareto_study
from hpm_platform.ui.project_model import CAEProject
from hpm_platform.ui.quick_solver import solve_project

ROOT = Path(__file__).resolve().parents[1]


def fast_multi_project() -> CAEProject:
    project = CAEProject.load_yaml(ROOT / "configs" / "cae_project_v12.yaml")
    return replace(
        project,
        plane=replace(project.plane, samples=41),
        solver=replace(
            project.solver,
            iterations=70,
            target_samples=110,
            outside_samples=220,
            uncertainty_scenarios=2,
            pareto_points=3,
        ),
    )


def test_v11_payload_migrates_to_v12_defaults():
    project = fast_multi_project()
    payload = project.to_dict()
    payload["schema_version"] = "1.1"
    payload["solver"].pop("outside_peak_limit_db")
    payload["solver"].pop("protected_penalty")
    payload["solver"].pop("fairness_penalty")
    payload["solver"].pop("tail_penalty")
    payload["solver"].pop("tail_fraction")
    payload["solver"].pop("pareto_points")
    for item in [payload["target"], *payload["additional_targets"]]:
        item.pop("priority")
        item.pop("tolerance_percent")
    for item in [payload["protected_zone"], *payload["additional_protected_zones"]]:
        item.pop("max_amplitude_scale")
    migrated = CAEProject.from_dict(payload)
    assert migrated.schema_version == "1.4"
    assert migrated.solver.protected_penalty > 0
    assert all(target.priority > 0 for target in migrated.targets)
    assert all(zone.max_amplitude_scale > 0 for zone in migrated.protected_zones)


def test_constrained_multi_object_solver_emits_object_metrics_and_histories():
    result = solve_project(fast_multi_project())
    assert result.metrics["target_count"] == 2
    assert result.metrics["protected_zone_count"] == 2
    assert set(result.object_metrics["object_type"]) == {"target", "protected"}
    assert result.objective_component_history.ndim == 2
    assert len(result.objective_component_labels) == result.objective_component_history.shape[1]
    assert np.isfinite(result.metrics["worst_target_rmse_percent"])
    assert np.isfinite(result.metrics["maximum_protected_violation_db"])


def test_static_export_contains_object_level_artifacts(tmp_path: Path):
    result = solve_project(fast_multi_project())
    folder, report, archive = export_result_bundle(result, tmp_path, run_name="v12-static")
    assert report.exists() and archive.exists()
    assert (folder / "object_metrics.csv").exists()
    assert (folder / "interactive_figures" / "07_constraint_margin.html").exists()
    assert (folder / "interactive_figures" / "08_object_metrics.html").exists()


def test_pareto_study_marks_front_and_recommendation(tmp_path: Path):
    study = run_pareto_study(fast_multi_project(), multipliers=[0.3, 1.0, 3.0], fast_mode=True)
    assert len(study.records) == 3
    assert study.records["pareto"].any()
    assert int(study.records["recommended"].sum()) == 1
    folder, report, archive = export_pareto_bundle(study, tmp_path, run_name="v12-pareto")
    assert report.exists() and archive.exists()
    assert (folder / "pareto_records.csv").exists()


def test_v12_app_builds_with_dual_target_demo():
    app = build_app()
    assert app is not None

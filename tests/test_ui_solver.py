from dataclasses import replace
from pathlib import Path
import zipfile

import numpy as np

from hpm_platform.ui.exporter import export_result_bundle
from hpm_platform.ui.project_model import default_project
from hpm_platform.ui.quick_solver import solve_project


def test_default_interactive_solver_returns_expected_artifacts():
    project = default_project()
    result = solve_project(project)
    n = project.plane.samples
    assert result.field.shape == (n, n)
    assert result.far_field.shape == (91, 91)
    assert result.actual_weights.size == project.array.nx * project.array.ny
    assert np.isfinite(result.amplitude).all()
    assert result.metrics["target_rmse_percent"] < 15.0
    assert result.metrics["target_coverage_percent"] > 50.0
    assert result.metrics["control_success"] is True


def test_solver_is_deterministic_for_same_project():
    project = default_project()
    first = solve_project(project)
    second = solve_project(project)
    assert np.allclose(first.actual_weights, second.actual_weights)
    assert np.allclose(first.field, second.field)
    # Runtime is intentionally excluded from deterministic equality.
    assert first.metrics["target_rmse_percent"] == second.metrics["target_rmse_percent"]


def test_point_focus_fast_path_has_no_objective_history():
    project = default_project()
    project = replace(
        project,
        solver=replace(
            project.solver,
            method="Point-Focus",
            pa_enabled=False,
            dpd_enabled=False,
            uncertainty_scenarios=1,
        ),
    )
    result = solve_project(project)
    assert result.objective_history.size == 0
    assert result.metrics["method"] == "Point-Focus"


def test_protected_zone_is_present_and_evaluated():
    result = solve_project(default_project())
    assert np.any(result.protected_mask)
    assert np.isfinite(result.metrics["protected_p95_db"])


def test_result_bundle_contains_reproducibility_artifacts(tmp_path):
    result = solve_project(default_project())
    run_dir, report, archive = export_result_bundle(result, tmp_path, run_name="unit_case")
    assert report.exists()
    assert archive.exists()
    assert (run_dir / "project.yaml").exists()
    assert (run_dir / "metrics.json").exists()
    assert (run_dir / "field_solution.npz").exists()
    assert (run_dir / "result_manifest.json").exists()
    with zipfile.ZipFile(archive) as handle:
        names = set(handle.namelist())
    assert "HPM_CAE_report.html" in names
    assert "project.yaml" in names

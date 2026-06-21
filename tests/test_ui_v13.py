from dataclasses import replace
from pathlib import Path

import numpy as np

from hpm_platform.physics.field_backends import available_field_backends, get_field_backend
from hpm_platform.ui.app_v13 import build_app
from hpm_platform.ui.backend_explorer import export_backend_comparison, run_backend_comparison
from hpm_platform.ui.environment_manager import apply_environment_frames, project_to_environment_frames
from hpm_platform.ui.project_model import CAEProject
from hpm_platform.ui.quick_solver import solve_project

ROOT = Path(__file__).resolve().parents[1]


def fast_environment_project() -> CAEProject:
    project = CAEProject.load_yaml(ROOT / "configs" / "cae_project_v13.yaml")
    return replace(
        project,
        plane=replace(project.plane, samples=41),
        solver=replace(
            project.solver,
            iterations=45,
            target_samples=90,
            outside_samples=180,
            uncertainty_scenarios=2,
        ),
    )


def test_v13_project_contains_plugin_environment():
    project = fast_environment_project()
    assert project.schema_version == "1.4"
    assert project.propagation.backend == "hybrid_scene"
    assert len(project.active_reflectors) == 1
    assert len(project.active_apertures) == 1
    assert len(project.active_cavities) == 1


def test_registered_backends_return_finite_matrices():
    project = fast_environment_project()
    array = project.array.build_array()
    points = array.wavelength_m * np.array([[0.2, -0.3, project.plane.z_lambda], [1.0, 0.4, project.plane.z_lambda]])
    identifiers = {item.backend_id for item in available_field_backends()}
    assert identifiers == {"free_space_green", "image_ray", "aperture_cavity_rom", "hybrid_scene"}
    for backend_id in sorted(identifiers):
        backend = get_field_backend(backend_id)
        matrix = backend.matrix(array, points, project=project, reference_scale=1.0)
        assert matrix.shape == (2, array.n_elements)
        assert np.all(np.isfinite(matrix))


def test_environment_tables_roundtrip():
    project = fast_environment_project()
    frames = project_to_environment_frames(project)
    restored = apply_environment_frames(project, *frames)
    assert restored.materials == project.materials
    assert restored.reflecting_planes == project.reflecting_planes
    assert restored.apertures == project.apertures
    assert restored.cavities == project.cavities


def test_hybrid_solver_reports_backend_metrics():
    result = solve_project(fast_environment_project())
    assert result.metrics["propagation_backend"] == "hybrid_scene"
    assert result.metrics["active_reflectors"] == 1
    assert np.isfinite(result.metrics["target_rmse_percent"])
    assert np.all(np.isfinite(result.field))


def test_backend_comparison_and_export(tmp_path: Path):
    comparison = run_backend_comparison(
        fast_environment_project(),
        backend_ids=("free_space_green", "hybrid_scene"),
        fast_mode=True,
    )
    assert len(comparison.records) == 2
    assert set(comparison.records["后端标识"]) == {"free_space_green", "hybrid_scene"}
    folder, report, archive = export_backend_comparison(comparison, tmp_path)
    assert folder.exists() and report.exists() and archive.exists()
    assert (folder / "传播后端对比.csv").exists()


def test_v13_app_uses_native_open_source_template():
    app = build_app()
    assert app is not None

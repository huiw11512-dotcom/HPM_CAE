from dataclasses import replace

import pytest

from hpm_platform.ui.project_model import (
    CAEProject,
    ObservationPlaneSpec,
    SolverSpec,
    default_project,
)


def test_default_project_is_valid_and_normalized():
    project = default_project()
    project.validate_geometry()
    assert project.schema_version == "1.4"
    assert "归一化" in project.model_scope
    assert project.array.build_array().n_elements == 64


def test_project_yaml_roundtrip(tmp_path):
    original = default_project()
    path = original.save_yaml(tmp_path / "case.hpmcae.yaml")
    loaded = CAEProject.load_yaml(path)
    assert loaded == original
    assert loaded.slug.startswith("HPM_")


def test_even_plane_grid_is_rejected():
    with pytest.raises(ValueError, match="odd"):
        ObservationPlaneSpec(samples=80)


def test_target_must_fit_in_plane():
    project = default_project()
    with pytest.raises(ValueError, match="target"):
        replace(project, target=replace(project.target, center_x_lambda=3.4))


def test_dpd_requires_pa():
    with pytest.raises(ValueError, match="DPD"):
        SolverSpec(pa_enabled=False, dpd_enabled=True)


def test_array_spacing_is_converted_from_lambda():
    project = default_project()
    array = project.array.build_array()
    assert array.dx_m == pytest.approx(project.array.spacing_x_lambda * array.wavelength_m)
    assert array.dy_m == pytest.approx(project.array.spacing_y_lambda * array.wavelength_m)

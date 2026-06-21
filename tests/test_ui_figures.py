from hpm_platform.ui.figures import (
    make_convergence_figure,
    make_far_field_figure,
    make_field_figure,
    make_scene_figure,
    make_weights_figure,
    write_standalone_report,
)
from hpm_platform.ui.project_model import default_project
from hpm_platform.ui.quick_solver import solve_project


def test_plotly_figures_are_populated():
    project = default_project()
    result = solve_project(project)
    assert len(make_scene_figure(project).data) >= 4
    assert len(make_field_figure(result).data) >= 3
    assert len(make_far_field_figure(result).data) >= 2
    assert len(make_weights_figure(result).data) == 2
    assert len(make_convergence_figure(result).data) == 1


def test_standalone_report_embeds_model_boundary(tmp_path):
    project = default_project()
    result = solve_project(project)
    path = write_standalone_report(
        result,
        [("场景", make_scene_figure(project)), ("场分布", make_field_figure(result))],
        tmp_path / "report.html",
    )
    text = path.read_text(encoding="utf-8")
    assert "归一化数值研究模式" in text
    assert "绝对功率仅作为实测标定元数据" in text
    assert "plotly" in text.lower()

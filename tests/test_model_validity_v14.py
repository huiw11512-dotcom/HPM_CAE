from dataclasses import replace
from pathlib import Path

from hpm_platform.ui.project_model import CAEProject
from hpm_platform.validation.model_validity import assess_model_validity

ROOT = Path(__file__).resolve().parents[1]


def v14_project() -> CAEProject:
    return CAEProject.load_yaml(ROOT / "configs" / "cae_project_v14.yaml")


def test_hybrid_validity_report_is_chinese_and_bounded():
    report = assess_model_validity(v14_project(), "hybrid_scene")
    assert 0.0 <= report.score <= 100.0
    assert report.backend_name == "混合场景后端"
    assert len(report.checks) >= 8
    assert "归一化" in report.summary
    assert {item.status for item in report.checks} <= {"适用", "提示", "谨慎", "越界"}


def test_image_ray_without_reflector_reports_boundary_violation():
    project = v14_project()
    project = replace(
        project,
        reflecting_planes=tuple(replace(item, enabled=False) for item in project.reflecting_planes),
    )
    report = assess_model_validity(project, "image_ray")
    assert any(item.status == "越界" for item in report.checks)
    assert report.worst_status == "越界"

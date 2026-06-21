from pathlib import Path

from fastapi.testclient import TestClient

from hpm_platform.validation.analytic_cases import (
    run_array_factor_case,
    run_backend_consistency_case,
    run_green_function_case,
    run_mvdr_lcmv_case,
    run_scan_beam_case,
)
from hpm_platform.validation.uncertainty import run_monte_carlo_uncertainty
from hpm_platform.validation.vv_runner import run_vv
from hpm_platform.ui.app_v20a import create_app

ROOT = Path(__file__).resolve().parents[1]


def test_array_factor_analytic_error_is_below_threshold():
    result = run_array_factor_case(grid_points=121)
    assert result.passed
    assert result.metrics["归一化幅度RMSE"] < 1e-3


def test_scan_beam_peak_is_close_to_target():
    result = run_scan_beam_case(grid_points=181)
    assert result.passed
    assert result.metrics["峰值偏差"] < 0.03


def test_green_function_amplitude_and_phase_errors_are_normal():
    result = run_green_function_case(samples=48)
    assert result.passed
    assert result.metrics["幅度最大误差"] < 1e-6


def test_mvdr_lcmv_constraint_residual_is_low():
    result = run_mvdr_lcmv_case()
    assert result.passed
    assert result.metrics["LCMV约束残差"] < 1e-6


def test_backend_degradation_error_is_low():
    result = run_backend_consistency_case(ROOT / "configs" / "cae_project_v14.yaml")
    assert result.passed
    assert result.metrics["最大退化相对误差"] < 1e-6


def test_vv_runner_generates_report_and_machine_outputs(tmp_path):
    result = run_vv(
        mode="fast",
        project_path=ROOT / "configs" / "cae_project_v14.yaml",
        output_dir=tmp_path,
    )
    assert result["summary"]["总测试数"] == 6
    assert result["summary"]["失败数"] == 0
    assert result["score"]["可信度评分"] > 85
    assert result["external_data_vv"]["可纳入正式可信度评分"] is False
    assert result["external_data_vv"]["正式评分策略"]["是否改写正式评分"] is False
    assert Path(result["outputs"]["html"]).exists()
    assert Path(result["outputs"]["json"]).exists()
    assert Path(result["outputs"]["csv"]).exists()
    assert Path(result["outputs"]["latex"]).exists()


def test_v20a_chinese_ui_returns_http_200(tmp_path):
    with TestClient(create_app(ROOT / "configs" / "cae_project_v14.yaml", tmp_path)) as client:
        response = client.get("/")
    assert response.status_code == 200
    assert "HPM-DT CAE 场景工作台" in response.text
    assert '<section class="页面" data-page-section="场景编辑"' in response.text
    assert '<section class="页面 d-none" data-page-section="验证中心"' in response.text
    assert 'data-testid="scene-first-core"' in response.text
    assert "可信度验证" in response.text
    assert "运行快速V&amp;V" in response.text


def test_fixed_random_seed_is_reproducible():
    a = run_monte_carlo_uncertainty(n_samples=12, seed=1234, grid_points=61)
    b = run_monte_carlo_uncertainty(n_samples=12, seed=1234, grid_points=61)
    assert a.summary["固定随机种子可复现"] is True
    assert b.summary["固定随机种子可复现"] is True
    assert a.records == b.records

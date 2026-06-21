from pathlib import Path

from fastapi.testclient import TestClient

from hpm_platform.ui.app_v14 import create_app

ROOT = Path(__file__).resolve().parents[1]


def client() -> TestClient:
    return TestClient(create_app(ROOT / "configs" / "cae_project_v14.yaml"))


def test_v14_bootstrap_template_is_local_and_chinese():
    with client() as test_client:
        response = test_client.get("/")
    assert response.status_code == 200
    text = response.text
    assert "HPM 数字化电磁算法 CAE" in text
    assert "模型适用性" in text
    assert "参数标定" in text
    assert "Bootstrap 5 官方 Dashboard" in text
    assert "/static/vendor/bootstrap.min.css" in text


def test_v14_health_and_validity_api():
    with client() as test_client:
        health = test_client.get("/api/health")
        validity = test_client.post("/api/validity", json={"backend": "hybrid_scene"})
    assert health.status_code == 200
    assert health.json()["平台版本"] == "1.4.0"
    assert validity.status_code == 200
    assert validity.json()["报告"]["传播后端"] == "混合场景后端"


def test_v14_calibration_api_recovers_reference_scales():
    payload = {
        "reference_backend": "hybrid_scene",
        "candidate_backend": "hybrid_scene",
        "reference_scales": [0.86, 0.72, 0.93],
        "initial_scales": [0.50, 0.40, 0.40],
        "samples_per_axis": 9,
        "noise_percent": 0.0,
    }
    with client() as test_client:
        response = test_client.post("/api/calibrate", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["成功"] is True
    assert data["摘要"]["标定后相对RMSE/%"] < 1e-4


def test_v14_illustrations_are_packaged():
    image_root = ROOT / "src" / "hpm_platform" / "ui" / "static_v14" / "img"
    for stem in (
        "01_全链路数字孪生架构图",
        "02_混合传播后端机理图",
        "03_传播后端参数标定闭环图",
    ):
        assert (image_root / f"{stem}.png").stat().st_size > 50_000
        assert (image_root / f"{stem}.svg").stat().st_size > 5_000

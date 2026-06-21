from pathlib import Path

from fastapi.testclient import TestClient

from hpm_platform.readiness import load_readiness_config
from hpm_platform.ui.app_v20a import create_app


ROOT = Path(__file__).resolve().parents[1]


def test_platform_readiness_config_lives_under_configs():
    config = load_readiness_config(ROOT / "configs" / "platform_readiness.yaml")

    assert config["version"] == "NorthStar-readiness-v1"
    assert config["thresholds"]["vv_a_score"] == 85
    assert "使用准备度" not in config
    assert "use_readiness" in config["summary_weights"]
    assert config["caps"]["publication_readiness_if_p0"] == 68
    assert "真实作用距离" in config["safety_boundary"]["no_output_items"]


def test_platform_readiness_api_generates_report_artifacts_and_blockers(tmp_path):
    with TestClient(create_app(ROOT / "configs" / "cae_project_v14.yaml", tmp_path)) as client:
        response = client.get("/api/platform/readiness")

    assert response.status_code == 200
    payload = response.json()

    assert payload["版本"] == "NorthStar-readiness-v1"
    assert payload["使用准备度/%"] > 60
    assert payload["发文准备度/%"] > 50
    assert payload["平台成熟度/%"] > 60
    assert payload["配置"].endswith("configs\\platform_readiness.yaml") or payload["配置"].endswith("configs/platform_readiness.yaml")
    assert {"可信度验证", "三维CAE工作台", "真实数据接入", "论文生产"} <= {item["维度"] for item in payload["维度"]}
    assert any(item["步骤"] == "正式数据纳入评分" and item["通过"] is False for item in payload["主链路"])
    assert any("真实源链" in item["阻断项"] or "相位参考" in item["阻断项"] for item in payload["关键阻断项"])
    assert "真实作用距离" in payload["安全边界"]["不输出项"]
    assert Path(payload["产物"]["json"]).exists()
    assert Path(payload["产物"]["csv"]).exists()


def test_platform_readiness_frontend_and_manifest_register_entrypoints():
    html = (ROOT / "src" / "hpm_platform" / "ui" / "templates_v20a" / "index.html").read_text(encoding="utf-8")
    js = (ROOT / "src" / "hpm_platform" / "ui" / "static_v20a" / "js" / "v20a.js").read_text(encoding="utf-8")
    manifest = (ROOT / "PROJECT_MANIFEST.json").read_text(encoding="utf-8")

    assert 'data-testid="nav-platform-readiness"' in html
    assert 'data-testid="platform-readiness-dimensions"' in html
    assert 'data-testid="platform-readiness-workflow"' in html
    assert "/api/platform/readiness" in js
    assert "渲染平台成熟度" in js
    assert "platform_readiness.yaml" in manifest
    assert "external_data_evidence.yaml" in manifest


def test_required_project_management_files_exist_and_state_safety_scope():
    required = [
        "VISION.md",
        "ROADMAP.md",
        "ARCHITECTURE.md",
        "CHANGELOG.md",
        "PROJECT_AUDIT.md",
        "STATUS.md",
    ]
    for name in required:
        assert (ROOT / name).exists(), name

    status = (ROOT / "STATUS.md").read_text(encoding="utf-8")
    audit = (ROOT / "PROJECT_AUDIT.md").read_text(encoding="utf-8")
    assert "当前版本" in status
    assert "技术债务" in status
    assert "架构风险" in status
    assert "真实作用距离" in audit
    assert "configs/platform_readiness.yaml" in audit

from pathlib import Path
import json

from fastapi.testclient import TestClient

from hpm_platform.ui.app_v20a import create_app
from hpm_platform.validation.vv_runner import run_vv


ROOT = Path(__file__).resolve().parents[1]


def read_text(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_agents_file_declares_hpm_dt_as_codex_north_star():
    text = read_text("AGENTS.md")
    assert "你的最终任务不是开发一个 Python 项目" in text
    assert "HPM-DT（High-Power Microwave Digital Twin）" in text
    assert "高功率微波数字孪生 CAE 平台" in text
    assert "V2.0A 是可信度层的阶段成果，不是平台最高目标" in text


def test_readme_starts_from_platform_goal_not_v20a_task():
    text = read_text("README.md")
    first_line = text.splitlines()[0]
    assert "HPM-DT" in first_line
    assert "V2.0A" not in first_line
    assert "V2.0A 只是当前阶段里程碑" in text
    assert "docs/HPM_DT_NORTH_STAR.md" in text
    assert "AGENTS.md" in text


def test_manifest_links_north_star_roadmap_and_agent_guidance():
    manifest = json.loads(read_text("PROJECT_MANIFEST.json"))
    assert manifest["项目"] == "HPM-DT 高功率微波数字孪生 CAE 平台"
    assert "持续演进" in manifest["最高层目标"]
    assert manifest["North Star"] == "docs/HPM_DT_NORTH_STAR.md"
    assert manifest["长期路线图"] == "docs/HPM_DT_ROADMAP.md"
    assert manifest["Codex协作说明"] == "AGENTS.md"
    assert len(manifest["长期架构"]) == 8


def test_roadmap_preserves_next_stage_targets():
    roadmap = read_text("docs/HPM_DT_ROADMAP.md")
    for item in ("V2.0B", "V2.0C", "V2.0D", "V3.0", "V4.0"):
        assert item in roadmap
    assert "Three.js" in roadmap
    assert "Plugin Marketplace" in roadmap
    assert "Paper Factory" in roadmap
    assert "Touchstone" in roadmap
    assert "实验室公共平台" in roadmap


def test_v20a_ui_and_api_expose_platform_north_star(tmp_path):
    with TestClient(create_app(ROOT / "configs" / "cae_project_v14.yaml", tmp_path)) as client:
        page = client.get("/")
        north_star = client.get("/api/platform/north-star")
    assert page.status_code == 200
    assert "HPM-DT V2.0A 可信度验证中心" in page.text
    assert "HPM-DT North Star" in page.text
    assert "平台愿景" in page.text
    assert north_star.status_code == 200
    payload = north_star.json()
    assert payload["平台名称"] == "HPM-DT"
    assert "不是算法仓库" in payload["平台定位"]
    assert len(payload["八层架构"]) == 8
    assert len(payload["层级状态"]) == 8
    assert payload["层级状态"][5]["层级"] == "可信度层"
    assert payload["层级状态"][5]["当前状态"] == "V2.0A 已完成"
    assert len(payload["里程碑状态"]) == 6
    assert payload["里程碑状态"][0]["状态"] == "已完成"


def test_vv_machine_result_contains_platform_context(tmp_path):
    result = run_vv(
        mode="fast",
        project_path=ROOT / "configs" / "cae_project_v14.yaml",
        output_dir=tmp_path,
    )
    result_path = Path(result["outputs"]["json"])
    payload = json.loads(result_path.read_text(encoding="utf-8"))
    assert payload["平台"]["平台名称"] == "HPM-DT"
    assert "持续演进 HPM-DT" in payload["平台"]["最高层目标"]
    assert "V2.0B 真正三维 CAE 编辑器" in payload["平台"]["阶段路线"]
    assert payload["平台"]["层级状态"][6]["层级"] == "CAE平台层"
    assert payload["平台"]["里程碑状态"][2]["阶段"] == "V2.0C"

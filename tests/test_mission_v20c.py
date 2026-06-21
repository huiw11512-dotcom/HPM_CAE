from pathlib import Path
import json

from fastapi.testclient import TestClient

from hpm_platform.ui.app_v20a import create_app
from hpm_platform.ui.mission_sim import MISSION_SIM_VERSION, MissionSimulationService


ROOT = Path(__file__).resolve().parents[1]


def test_v20c_mission_service_runs_normalized_timeline_and_archives(tmp_path):
    service = MissionSimulationService(ROOT / "configs" / "cae_project_v14.yaml", tmp_path)
    catalog = service.catalog()

    assert catalog["版本"] == MISSION_SIM_VERSION
    assert catalog["默认模板"] == "MST-TRACK-001"
    assert len(catalog["模板"]) >= 3
    assert "真实作用距离" in catalog["安全边界"]["不输出项"]

    payload = service.run_mission("MST-TRACK-001", frames=3, label="pytest任务")

    assert payload["成功"] is True
    assert payload["版本"] == MISSION_SIM_VERSION
    assert payload["mission_id"] == "MIS-0001"
    assert payload["模板"]["id"] == "MST-TRACK-001"
    assert payload["任务"]["帧数"] == 3
    assert payload["任务"]["控制器"] == "Predictive-PGMS"
    assert 0 <= payload["指标"]["任务成功代理/%"] <= 100
    assert 0 <= payload["指标"]["归一化风险代理"] <= 1
    assert len(payload["时间线"]) == 3
    assert all("归一化风险代理" in frame for frame in payload["时间线"])
    assert any(item["项目"] == "归一化安全边界" and item["通过"] for item in payload["验收清单"])
    assert "器件阈值" in payload["安全边界"]["不输出项"]
    assert Path(payload["产物"]["report_html"]).exists()
    assert Path(payload["产物"]["archive_zip"]).exists()
    assert Path(payload["产物"]["mission_json"]).exists()

    serialized = json.dumps(payload, ensure_ascii=False)
    for forbidden in ("damage_probability", "effect_distance", "device_threshold", "作用距离_m", "threshold_v_per_m"):
        assert forbidden not in serialized

    status = service.status()
    assert status["任务数量"] == 1
    assert Path(status["索引"]["json"]).exists()
    assert Path(status["索引"]["csv"]).exists()
    assert service.get_mission("MIS-0001")["mission_id"] == "MIS-0001"


def test_v20c_mission_api_exposes_templates_status_run_and_result(tmp_path):
    with TestClient(create_app(ROOT / "configs" / "cae_project_v14.yaml", tmp_path)) as client:
        templates = client.get("/api/mission/templates")
        run = client.post("/api/mission/run", json={"template_id": "MST-TRACK-001", "frames": 3})
        status = client.get("/api/mission/status")
        result = client.get(f"/api/mission/results/{run.json()['mission_id']}")

    assert templates.status_code == 200
    assert templates.json()["版本"] == MISSION_SIM_VERSION
    assert any(item["id"] == "MST-TRACK-001" for item in templates.json()["模板"])
    assert run.status_code == 200
    assert run.json()["任务"]["帧数"] == 3
    assert run.json()["指标"]["任务成功代理/%"] >= 0
    assert status.status_code == 200
    assert status.json()["任务数量"] == 1
    assert result.status_code == 200
    assert result.json()["mission_id"] == run.json()["mission_id"]


def test_v20c_mission_frontend_assets_register_scene_first_task_panel():
    html = (ROOT / "src" / "hpm_platform" / "ui" / "templates_v20a" / "index.html").read_text(encoding="utf-8")
    js = (ROOT / "src" / "hpm_platform" / "ui" / "static_v20a" / "js" / "v20a.js").read_text(encoding="utf-8")
    manifest = (ROOT / "PROJECT_MANIFEST.json").read_text(encoding="utf-8")

    assert 'data-testid="mission-first-panel"' in html
    assert 'data-testid="mission-template-catalog"' in html
    assert 'data-testid="mission-run"' in html
    assert 'data-testid="mission-timeline"' in html
    assert "/api/mission/templates" in js
    assert "/api/mission/run" in js
    assert "运行任务级仿真" in js
    assert "mission_v20c" in manifest

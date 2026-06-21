from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from hpm_platform.plugins import PluginMarketplaceService, PluginRegistry
from hpm_platform.ui.app_v20a import create_app


ROOT = Path(__file__).resolve().parents[1]
PLUGIN_DIR = ROOT / "plugins" / "builtin"


def test_v20c_registry_loads_builtin_plugin_manifests():
    registry = PluginRegistry((PLUGIN_DIR,))
    plugins = registry.list()
    ids = {plugin.plugin_id for plugin in plugins}
    categories = set(registry.categories())

    assert ids == {
        "hpm.data_import.evidence_chain",
        "hpm.publication.paper_template_pack",
        "hpm.propagation.hybrid_scene",
        "hpm.perception.music_esprit_benchmark",
        "hpm.publication.vv_report_pack",
    }
    assert {"propagation_backend", "perception_algorithm", "data_import_adapter", "report_template"} <= categories
    for plugin in plugins:
        assert plugin.version == "2.0.0"
        assert plugin.entry_point.kind == "builtin_hook"
        assert plugin.parameters_schema["type"] == "object"
        assert plugin.safety["execution"] == "builtin_hook_only"
        assert plugin.acceptance_tests


def test_v20c_marketplace_runs_allowlisted_plugins_and_enforces_enable_state(tmp_path):
    service = PluginMarketplaceService((PLUGIN_DIR,), output_dir=tmp_path)
    catalog = service.catalog()
    acceptance = service.acceptance_summary()

    assert catalog["版本"] == "V2.0C-preview"
    assert catalog["插件总数"] == 5
    assert acceptance["通过"] is True
    assert any(item["项目"] == "数据导入插件可注册" and item["通过"] for item in acceptance["验收清单"])

    propagation = service.run_plugin("hpm.propagation.hybrid_scene")
    assert propagation["成功"] is True
    assert propagation["结果"]["后端"]["后端标识"] == "hybrid_scene"

    perception = service.run_plugin("hpm.perception.music_esprit_benchmark", {"algorithm": "esprit"})
    assert "ESPRIT" in perception["结果"]["能力"]

    report = service.run_plugin("hpm.publication.vv_report_pack", {"format": "latex"})
    assert report["参数"]["format"] == "latex"
    assert report["结果"]["目标产物"].endswith("v20A_论文表格.tex")

    paper_templates = service.run_plugin("hpm.publication.paper_template_pack", {"format": "paper_template"})
    assert paper_templates["成功"] is True
    assert paper_templates["结果"]["论文模板数量"] >= 2
    assert {item["类型"] for item in paper_templates["结果"]["论文模板"]} >= {"journal_article", "thesis_chapter"}

    data_import = service.run_plugin("hpm.data_import.evidence_chain", {"report_type": "evidence_chain"})
    assert data_import["成功"] is True
    assert data_import["结果"]["样例数"] == 7
    assert data_import["结果"]["证据链"]["生成"] is True
    assert data_import["结果"]["证据链"]["真实源链与相位参考已接入"] is False

    disabled = service.set_enabled("hpm.propagation.hybrid_scene", False)
    assert disabled["已启用"] is False
    with pytest.raises(ValueError, match="disabled"):
        service.run_plugin("hpm.propagation.hybrid_scene")


def test_v20c_api_exposes_plugin_marketplace(tmp_path):
    with TestClient(create_app(ROOT / "configs" / "cae_project_v14.yaml", tmp_path)) as client:
        catalog = client.get("/api/plugins/catalog")
        acceptance = client.get("/api/plugins/acceptance")
        detail = client.get("/api/plugins/hpm.propagation.hybrid_scene")
        run = client.post(
            "/api/plugins/hpm.propagation.hybrid_scene/run",
            json={"parameters": {"backend_id": "free_space_green"}},
        )
        data_import_run = client.post(
            "/api/plugins/hpm.data_import.evidence_chain/run",
            json={"parameters": {"report_type": "full"}},
        )
        disabled = client.post("/api/plugins/hpm.propagation.hybrid_scene/enable", json={"enabled": False})
        rejected = client.post("/api/plugins/hpm.propagation.hybrid_scene/run", json={"parameters": {}})

    assert catalog.status_code == 200
    assert catalog.json()["插件总数"] == 5
    assert acceptance.status_code == 200
    assert acceptance.json()["通过"] is True
    assert detail.status_code == 200
    assert detail.json()["参数Schema"]["type"] == "object"
    assert run.status_code == 200
    assert run.json()["结果"]["后端"]["后端标识"] == "free_space_green"
    assert data_import_run.status_code == 200
    assert data_import_run.json()["结果"]["证据链"]["生成"] is True
    assert disabled.status_code == 200
    assert disabled.json()["已启用"] is False
    assert rejected.status_code == 400


def test_v20c_frontend_assets_register_plugin_marketplace_page():
    html = (ROOT / "src" / "hpm_platform" / "ui" / "templates_v20a" / "index.html").read_text(encoding="utf-8")
    js = (ROOT / "src" / "hpm_platform" / "ui" / "static_v20a" / "js" / "v20a.js").read_text(encoding="utf-8")

    assert 'data-page="插件市场"' in html
    assert 'data-testid="nav-plugin-marketplace"' in html
    assert 'data-testid="plugin-catalog"' in html
    assert 'data-testid="plugin-acceptance"' in html
    assert "/api/plugins/catalog" in js
    assert "/api/plugins/acceptance" in js
    assert "/api/plugins/${encodeURIComponent(pluginId)}/run" in js

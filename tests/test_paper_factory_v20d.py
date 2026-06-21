from pathlib import Path
import json
import zipfile

from fastapi.testclient import TestClient

from hpm_platform.publication import PaperFactoryService, generate_paper_factory_bundle
from hpm_platform.ui.app_v20a import create_app
from hpm_platform.validation.vv_runner import run_vv


ROOT = Path(__file__).resolve().parents[1]


def test_v20d_paper_factory_generates_reproducible_bundle(tmp_path):
    run_vv(mode="fast", project_path=ROOT / "configs" / "cae_project_v14.yaml", output_dir=tmp_path)

    bundle = generate_paper_factory_bundle(tmp_path)
    manifest = json.loads(bundle.manifest.read_text(encoding="utf-8"))
    draft = bundle.draft_markdown.read_text(encoding="utf-8")
    latex = bundle.ieee_latex.read_text(encoding="utf-8")

    assert manifest["版本"] == "V2.0D-preview"
    assert manifest["通过"] is True
    assert manifest["图表数量"] >= 3
    assert manifest["表格数量"] >= 3
    assert "摘要" in draft
    assert "安全边界" in draft
    assert "\\documentclass[conference]{IEEEtran}" in latex
    assert bundle.archive.exists()

    with zipfile.ZipFile(bundle.archive) as zf:
        names = set(zf.namelist())
    assert "HPM_DT_V20D_论文草稿.md" in names
    assert "HPM_DT_V20D_IEEE骨架.tex" in names
    assert "paper_factory_manifest.json" in names
    assert any(name.startswith("figures/") for name in names)
    assert any(name.startswith("tables/") for name in names)


def test_v20d_service_status_reflects_generation(tmp_path):
    service = PaperFactoryService(tmp_path)
    assert service.status()["状态"] == "尚未生成"

    run_vv(mode="fast", project_path=ROOT / "configs" / "cae_project_v14.yaml", output_dir=tmp_path)
    generated = service.generate()
    status = service.status()

    assert generated["通过"] is True
    assert status["状态"] == "已生成"
    assert Path(status["产物"]["论文包ZIP"]).exists()


def test_v20d_api_generates_and_downloads_paper_bundle(tmp_path):
    with TestClient(create_app(ROOT / "configs" / "cae_project_v14.yaml", tmp_path)) as client:
        status_before = client.get("/api/paper-factory/status")
        generated = client.post("/api/paper-factory/generate", json={"refresh_vv": True})
        status_after = client.get("/api/paper-factory/status")
        download = client.get("/download/paper-factory.zip")

    assert status_before.status_code == 200
    assert status_before.json()["通过"] is False
    assert generated.status_code == 200
    assert generated.json()["通过"] is True
    assert "论文草稿" in generated.json()["产物"]
    assert status_after.json()["状态"] == "已生成"
    assert download.status_code == 200
    assert download.content[:2] == b"PK"


def test_v20d_frontend_assets_register_paper_factory_controls():
    html = (ROOT / "src" / "hpm_platform" / "ui" / "templates_v20a" / "index.html").read_text(encoding="utf-8")
    js = (ROOT / "src" / "hpm_platform" / "ui" / "static_v20a" / "js" / "v20a.js").read_text(encoding="utf-8")

    assert 'data-testid="paper-factory-generate"' in html
    assert 'data-testid="paper-factory-status"' in html
    assert 'data-testid="paper-factory-output"' in html
    assert "/api/paper-factory/status" in js
    assert "/api/paper-factory/generate" in js
    assert "/download/paper-factory.zip" in js

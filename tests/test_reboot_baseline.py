from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def read(name: str) -> str:
    return (ROOT / name).read_text(encoding="utf-8")


def test_reboot_documents_define_studio_direction():
    assert "HPM-DT Studio" in read("PRODUCT_VISION.md")
    assert "物理对象优先" in read("PRODUCT_PRINCIPLES.md")
    assert "Entity Component" in read("DOMAIN_MODEL.md")
    assert "TargetRegion" in read("SCENE_MODEL.md")
    assert "StaticFieldSurvey" in read("MISSION_MODEL.md")
    assert "*.hpmdt" in read("PROJECT_FORMAT.md")
    assert "SolverBackend" in read("SOLVER_API.md")
    assert "React" in read("UI_UX_SPEC.md")


def test_reboot_branch_does_not_keep_legacy_worktree_payloads():
    assert not (ROOT / "src" / "hpm_platform").exists()
    assert not (ROOT / "legacy").exists()
    assert not any(ROOT.glob("outputs*"))
    assert not (ROOT / "PROJECT_MANIFEST.json").exists()


def test_reboot_status_records_next_commit():
    status = read("REBOOT_STATUS.md")
    assert "reboot/studio-core" in status
    assert "Commit 3" in status
    assert "hpmdt project format" in status or "ZIP 工程格式" in status
    assert "core: introduce entity component scene domain" in status

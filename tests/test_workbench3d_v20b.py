from pathlib import Path
import sqlite3
import time

import pytest
from fastapi.testclient import TestClient

from hpm_platform.data_import import (
    DataImportService,
    generate_calibration_bridge_report,
    generate_external_data_vv_audit,
    generate_model_comparison_report,
)
from hpm_platform.ui.app_v20a import create_app
from hpm_platform.ui.project_model import default_project
from hpm_platform.ui.workbench3d import (
    Workbench3DService,
    apply_workbench3d_material_update,
    apply_workbench3d_update,
    build_material_proxy_audit,
    build_workbench3d_scene,
)

ROOT = Path(__file__).resolve().parents[1]


def test_workbench3d_scene_projects_v14_objects_into_threejs_payload():
    scene = build_workbench3d_scene(default_project())
    object_types = {item["类型"] for item in scene["对象"]}
    assert scene["版本"] == "V2.0B-preview"
    assert scene["引擎"].startswith("Three.js")
    assert scene["校验"]["通过"] is True
    assert scene["工程"]["单位"] == "lambda"
    assert {"array", "observation_plane", "target_region", "protected_zone", "far_field_source"} <= object_types
    assert scene["scene_hash"]
    target = next(item for item in scene["对象"] if item["id"] == "TGT-001")
    assert target["可编辑字段"] == sorted(target["可编辑字段"])
    material = next(item for item in scene["材料库"] if item["id"] == "MAT-金属代理")
    assert "reflection_magnitude" in material["可编辑字段"]
    assert "REF-001" in material["引用对象"]


def test_workbench3d_scene_includes_environment_objects_from_v14_project():
    project = default_project()
    scene = build_workbench3d_scene(project)
    ids = {item["id"] for item in scene["对象"]}
    assert {"REF-001", "APT-001", "CAV-001"} <= ids
    assert scene["统计"]["对象总数"] >= 8
    assert any(group["名称"] == "环境对象" for group in scene["对象树"])


def test_workbench3d_update_is_validated_by_project_geometry():
    project = default_project()
    updated = apply_workbench3d_update(project, "TGT-001", {"center_x_lambda": 0.4})
    assert updated.target.center_x_lambda == pytest.approx(0.4)
    transformed = apply_workbench3d_update(
        updated,
        "TGT-001",
        {"semi_major_lambda": 1.2, "semi_minor_lambda": 0.7, "rotation_deg": 30.0},
    )
    assert transformed.target.semi_major_lambda == pytest.approx(1.2)
    assert transformed.target.semi_minor_lambda == pytest.approx(0.7)
    assert transformed.target.rotation_deg == pytest.approx(30.0)
    with pytest.raises(ValueError, match="target"):
        apply_workbench3d_update(project, "TGT-001", {"center_x_lambda": 99.0})


def test_workbench3d_material_update_is_validated_by_project_model():
    project = default_project()
    updated = apply_workbench3d_material_update(project, "MAT-金属代理", {"reflection_magnitude": 0.61})
    material = next(item for item in updated.materials if item.material_id == "MAT-金属代理")
    assert material.reflection_magnitude == pytest.approx(0.61)
    audit = build_material_proxy_audit(updated)
    assert audit["通过"] is True
    assert audit["材料数量"] >= 1
    assert any(item["材料ID"] == "MAT-金属代理" and item["通过"] for item in audit["材料"])
    with pytest.raises(ValueError, match="reflection_magnitude"):
        apply_workbench3d_material_update(project, "MAT-金属代理", {"reflection_magnitude": 1.2})


def test_workbench3d_service_supports_undo_redo_and_snapshots(tmp_path):
    service = Workbench3DService(None, tmp_path)
    initial = service.scene()
    assert initial["历史"]["可撤销"] is False
    snapshot = service.capture_snapshot("基线")
    assert snapshot["快照"]["id"] == "SNP-0001"
    assert snapshot["快照"]["scene_hash"] == initial["scene_hash"]
    assert Path(snapshot["快照"]["工程路径"]).exists()
    assert Path(snapshot["快照"]["场景路径"]).exists()
    assert (tmp_path / "workbench3d_snapshots" / "index.json").exists()
    assert (tmp_path / "workbench3d_snapshots" / "index.csv").exists()

    moved = service.update_object("TGT-001", {"center_x_lambda": 0.35})
    moved_target = next(item for item in moved["对象"] if item["id"] == "TGT-001")
    assert moved_target["属性"]["center_x_lambda"] == pytest.approx(0.35)
    assert moved["历史"]["可撤销"] is True

    undone = service.undo()
    undone_target = next(item for item in undone["对象"] if item["id"] == "TGT-001")
    assert undone_target["属性"]["center_x_lambda"] == pytest.approx(initial["对象"][2]["属性"]["center_x_lambda"])
    assert undone["历史"]["可重做"] is True

    redone = service.redo()
    redone_target = next(item for item in redone["对象"] if item["id"] == "TGT-001")
    assert redone_target["属性"]["center_x_lambda"] == pytest.approx(0.35)

    snapshot2 = service.capture_snapshot("移动后")
    assert snapshot2["快照"]["id"] == "SNP-0002"
    diff = service.diff_snapshots("SNP-0001", "SNP-0002")
    assert diff["scene_hash_changed"] is True
    assert diff["摘要"]["对象差异数"] >= 1
    assert diff["摘要"]["字段变更数"] >= 1
    target_diff = next(item for item in diff["对象差异"] if item["id"] == "TGT-001")
    assert any(change["字段"].endswith("center_x_lambda") for change in target_diff["变更"])

    restored = service.restore_snapshot("SNP-0001")
    restored_target = next(item for item in restored["对象"] if item["id"] == "TGT-001")
    assert restored_target["属性"]["center_x_lambda"] == pytest.approx(initial["对象"][2]["属性"]["center_x_lambda"])

    restored_service = Workbench3DService(None, tmp_path)
    snapshot_archive = restored_service.list_snapshots()
    assert snapshot_archive["快照"][0]["id"] == "SNP-0001"
    assert snapshot_archive["快照"][1]["id"] == "SNP-0002"
    assert Path(snapshot_archive["索引"]["json"]).exists()
    restored_diff = restored_service.diff_snapshots("SNP-0001", "SNP-0002")
    assert restored_diff["摘要"]["字段变更数"] >= 1
    restored_again = restored_service.restore_snapshot("SNP-0001")
    restored_again_target = next(item for item in restored_again["对象"] if item["id"] == "TGT-001")
    assert restored_again_target["属性"]["center_x_lambda"] == pytest.approx(initial["对象"][2]["属性"]["center_x_lambda"])


def test_workbench3d_service_runs_quick_solver_from_current_scene():
    service = Workbench3DService(None)
    scene = service.scene()
    result = service.solve_preview()
    assert result["成功"] is True
    assert result["result_id"] == "SOL-0001"
    assert result["阶段"] == "V2.0B 三维工作台求解联动预览"
    assert result["scene_hash"] == scene["scene_hash"]
    assert result["求解器"]["平面采样"] <= 51
    assert result["摘要"]["target_rmse_percent"] is not None
    assert result["摘要"]["solver_runtime_ms"] > 0
    assert result["对象指标"]
    target_metric = next(item for item in result["对象指标"] if item["object_id"] == "TGT-001")
    protected_metric = next(item for item in result["对象指标"] if item["object_id"] == "PRT-001")
    assert target_metric["rmse_percent"] is not None
    assert protected_metric["violation_db"] is not None
    layer = result["结果图层"]
    assert layer["类型"] == "observation_field_db"
    assert layer["单位"] == "dB"
    assert layer["samples"] <= 51
    assert layer["field_hash"]
    assert len(layer["values_db"]) == layer["samples"]
    assert len(layer["values_db"][0]) == layer["samples"]
    assert layer["统计"]["最大值"] >= layer["统计"]["最小值"]
    assert "峰值坐标" in layer["统计"]
    assert len(layer["剖面"]["x_cut_db"]) == layer["samples"]
    assert len(layer["剖面"]["y_cut_db"]) == layer["samples"]
    assert layer["剖面"]["x_cut_y_lambda"] is not None
    assert layer["剖面"]["y_cut_x_lambda"] is not None
    assert result["适用性"]["适用性得分"] >= 0
    assert result["适用性"]["检查项"]
    assert all("状态" in item for item in result["适用性"]["检查项"])
    archive = service.list_results()
    assert archive["结果"][0]["id"] == result["result_id"]
    assert service.get_result(result["result_id"])["结果图层"]["field_hash"] == layer["field_hash"]
    assert "适用性得分" in result["适用性"]
    assert any(item["项目"] == "安全边界" for item in result["验收清单"])


def test_workbench3d_service_tracks_solve_jobs(tmp_path):
    service = Workbench3DService(None, tmp_path)
    job_response = service.submit_solve_job("队列验收")
    job = job_response["任务"]
    assert job["id"] == "JOB-0001"
    assert job["状态"] == "已完成"
    assert job["result_id"] == job_response["结果"]["result_id"]
    assert job_response["结果"]["求解任务"]["id"] == "JOB-0001"
    assert Path(job["任务路径"]).exists()
    assert (tmp_path / "workbench3d_solve_jobs" / "index.json").exists()
    assert (tmp_path / "workbench3d_solve_jobs" / "index.csv").exists()

    jobs = service.list_solve_jobs()
    assert jobs["任务"][0]["id"] == "JOB-0001"
    assert jobs["审计"]["通过"] is True
    assert service.get_solve_job("JOB-0001")["结果"]["result_id"] == job["result_id"]

    retry_response = service.retry_solve_job("JOB-0001")
    retry_job = retry_response["任务"]
    assert retry_response["操作"]["通过"] is True
    assert retry_response["操作"]["来源任务"] == "JOB-0001"
    assert retry_response["操作"]["新任务"] == "JOB-0002"
    assert retry_job["id"] == "JOB-0002"
    assert retry_job["重试来源"] == "JOB-0001"
    assert retry_response["结果"]["求解任务"]["重试来源"] == "JOB-0001"
    original_after_retry = service.get_solve_job("JOB-0001")["任务"]
    assert any(item["动作"] == "重试" and item["新任务"] == "JOB-0002" for item in original_after_retry["操作日志"])

    cancel_response = service.cancel_solve_job("JOB-0001")
    assert cancel_response["操作"]["通过"] is False
    assert cancel_response["任务"]["状态"] == "已完成"
    assert any(item["动作"] == "取消" and item["通过"] is False for item in cancel_response["任务"]["操作日志"])

    background_response = service.submit_background_solve_job("后台检查点", start_paused=True)
    assert background_response["任务"]["id"] == "JOB-0003"
    assert background_response["任务"]["状态"] == "已暂停"
    assert background_response["结果"] is None
    resumed = service.resume_solve_job("JOB-0003")
    assert resumed["操作"]["通过"] is True
    for _ in range(30):
        resumed_detail = service.get_solve_job("JOB-0003")["任务"]
        if resumed_detail["状态"] == "已完成":
            break
        time.sleep(0.05)
    assert service.get_solve_job("JOB-0003")["任务"]["状态"] == "已完成"
    assert service.get_solve_job("JOB-0003")["结果"]["result_id"] == service.get_solve_job("JOB-0003")["任务"]["result_id"]

    paused_cancel = service.submit_background_solve_job("后台取消", start_paused=True)
    assert paused_cancel["任务"]["id"] == "JOB-0004"
    cancelled_background = service.cancel_solve_job("JOB-0004")
    assert cancelled_background["操作"]["通过"] is True
    assert cancelled_background["任务"]["状态"] == "已取消"

    solve_job_audit = service.audit_solve_jobs()
    assert solve_job_audit["审计"]["通过"] is True
    assert solve_job_audit["审计"]["任务总数"] == 4
    assert solve_job_audit["审计"]["状态计数"]["已完成"] == 3
    assert solve_job_audit["审计"]["状态计数"]["已取消"] == 1
    assert Path(solve_job_audit["索引"]["audit_json"]).exists()
    assert Path(solve_job_audit["索引"]["audit_csv"]).exists()

    snapshot = service.capture_snapshot("资产快照")
    assets = service.list_assets()
    asset_types = {item["类型"] for item in assets["资产"]}
    assert {"求解任务", "求解结果", "工程快照", "材料代理审计"} <= asset_types
    assert Path(assets["索引"]["json"]).exists()
    assert Path(assets["索引"]["csv"]).exists()
    assert Path(assets["索引"]["sqlite"]).exists()
    assert Path(assets["索引"]["audit_json"]).exists()
    assert Path(assets["索引"]["audit_csv"]).exists()
    assert Path(assets["索引"]["database_audit_json"]).exists()
    assert Path(assets["索引"]["database_audit_csv"]).exists()
    assert Path(assets["索引"]["naming_audit_json"]).exists()
    assert Path(assets["索引"]["naming_audit_csv"]).exists()
    assert Path(assets["索引"]["lineage_json"]).exists()
    assert Path(assets["索引"]["lineage_csv"]).exists()
    assert Path(assets["索引"]["material_proxy_audit_json"]).exists()
    assert Path(assets["索引"]["material_proxy_audit_csv"]).exists()
    assert assets["数据库审计"]["通过"] is True
    assert assets["命名审计"]["通过"] is True
    assert assets["材料代理审计"]["通过"] is True
    assert assets["材料代理审计"]["材料数量"] >= 1
    assert assets["命名审计"]["统计"]["任务数"] == 4
    background_done = service.get_solve_job("JOB-0003")["任务"]
    assert Path(background_done["任务路径"]).name == f"JOB-0003_{background_done['scene_hash']}_{background_done['result_id']}.json"
    assert not list((tmp_path / "workbench3d_solve_jobs").glob("JOB-0003_*_no_result.json"))
    assert service.get_asset("JOB-0001")["资产"]["类型"] == "求解任务"
    assert service.get_asset(job["result_id"])["资产"]["类型"] == "求解结果"
    assert service.get_asset(snapshot["快照"]["id"])["资产"]["类型"] == "工程快照"
    assert service.get_asset("MAT-AUDIT-001")["资产"]["类型"] == "材料代理审计"
    job_assets = service.list_assets(asset_type="求解任务", query="JOB-0001", limit=1)
    assert job_assets["筛选"]["匹配资产"] == 1
    assert job_assets["筛选"]["返回资产"] == 1
    assert job_assets["资产"][0]["资产id"] == "JOB-0001"
    audit = service.audit_assets(asset_type="求解任务")
    assert audit["审计"]["通过"] is True
    assert audit["审计"]["匹配资产"] == 4
    assert audit["审计"]["摘要"]["类型计数"]["求解任务"] == 4
    with sqlite3.connect(assets["索引"]["sqlite"]) as connection:
        row_count = connection.execute("SELECT COUNT(*) FROM workbench3d_assets").fetchone()[0]
        job_row_count = connection.execute("SELECT COUNT(*) FROM workbench3d_solve_jobs").fetchone()[0]
        event_count = connection.execute("SELECT COUNT(*) FROM workbench3d_solve_job_events").fetchone()[0]
        result_row_count = connection.execute("SELECT COUNT(*) FROM workbench3d_results").fetchone()[0]
        snapshot_row_count = connection.execute("SELECT COUNT(*) FROM workbench3d_snapshots").fetchone()[0]
        manifest_count = connection.execute("SELECT COUNT(*) FROM workbench3d_database_manifest").fetchone()[0]
        event_actions = {row[0] for row in connection.execute("SELECT action FROM workbench3d_solve_job_events").fetchall()}
    assert row_count == len(assets["资产"])
    assert job_row_count == 4
    assert event_count >= 11
    assert result_row_count == len(service.list_results()["结果"])
    assert snapshot_row_count == 1
    assert manifest_count >= 6
    assert {"暂停", "恢复", "启动", "完成", "取消"} <= event_actions
    database_audit = service.audit_asset_database()
    assert database_audit["数据库审计"]["通过"] is True
    assert database_audit["数据库审计"]["行数"]["workbench3d_assets"] == len(assets["资产"])
    assert database_audit["数据库审计"]["行数"]["workbench3d_solve_jobs"] == 4
    assert database_audit["数据库审计"]["行数"]["workbench3d_solve_job_events"] == event_count
    assert database_audit["数据库审计"]["行数"]["workbench3d_results"] == len(service.list_results()["结果"])
    assert database_audit["数据库审计"]["行数"]["workbench3d_snapshots"] == 1
    assert any(item["action"] == "取消" for item in database_audit["任务事件"])
    database_records = service.asset_database_records(table="workbench3d_results", limit=2)
    assert database_records["行数"]["workbench3d_results"] == len(service.list_results()["结果"])
    assert database_records["结构"]["workbench3d_results"][0]["列"] == "result_id"
    assert len(database_records["记录"]["workbench3d_results"]) <= 2
    lineage = service.asset_lineage()
    assert lineage["通过"] is True
    assert lineage["摘要"]["任务数"] == 4
    assert lineage["摘要"]["结果数"] == len(service.list_results()["结果"])
    assert lineage["摘要"]["任务结果边"] >= 3
    assert Path(lineage["索引"]["lineage_json"]).exists()
    assert Path(lineage["索引"]["lineage_csv"]).exists()
    assert any(edge["关系"] == "生成结果" and edge["source"] == "JOB-0001" and edge["target"] == job["result_id"] for edge in lineage["边"])
    assert any(edge["关系"] == "重试派生" and edge["source"] == "JOB-0001" and edge["target"] == "JOB-0002" for edge in lineage["边"])
    reproducibility = service.asset_reproducibility()
    assert reproducibility["通过"] is True
    assert reproducibility["摘要"]["结果数"] == len(service.list_results()["结果"])
    assert reproducibility["摘要"]["可复查结果数"] == len(service.list_results()["结果"])
    assert Path(reproducibility["索引"]["reproducibility_audit_json"]).exists()
    assert Path(reproducibility["索引"]["reproducibility_audit_csv"]).exists()
    calibration = service.absolute_calibration()
    assert calibration["通过"] is True
    assert calibration["阵列"]["阵元数"] == 64
    assert len(calibration["阵元功率"]) == 64
    assert calibration["校准结果"]["校准系数_v_per_m_per_normalized_unit"] is not None
    assert "真实作用距离" in calibration["不输出项"]
    assert Path(calibration["索引"]["absolute_calibration_json"]).exists()
    assert Path(calibration["索引"]["absolute_calibration_points_csv"]).exists()
    assert Path(calibration["索引"]["absolute_element_powers_csv"]).exists()
    data_import = DataImportService(tmp_path)
    generate_calibration_bridge_report(ROOT / "configs" / "cae_project_v14.yaml", tmp_path, data_import)
    generate_model_comparison_report(ROOT / "configs" / "cae_project_v14.yaml", tmp_path, data_import)
    generate_external_data_vv_audit(ROOT / "configs" / "cae_project_v14.yaml", tmp_path, data_import)
    imported_calibration = service.imported_calibration_bridge()
    assert imported_calibration["通过"] is True
    assert imported_calibration["摘要"]["样本数"] == 5
    assert imported_calibration["摘要"]["可纳入正式可信度评分"] is False
    assert "真实作用距离" in imported_calibration["不输出项"]
    assert Path(imported_calibration["索引"]["imported_calibration_bridge_json"]).exists()
    assert Path(imported_calibration["索引"]["imported_calibration_bridge_csv"]).exists()
    updated_calibration = service.update_absolute_calibration(
        {
            "element_powers_w": [1.25] * 64,
            "calibration_points": [
                {"point_id": "LAB-001", "distance_m": 0.8, "normalized_model_amplitude": 1.0, "measured_field_v_per_m": 3.0, "uncertainty_percent": 5.0},
                {"point_id": "LAB-002", "distance_m": 1.2, "normalized_model_amplitude": 0.7, "measured_field_v_per_m": 2.1, "uncertainty_percent": 6.0},
            ],
        }
    )
    assert updated_calibration["通过"] is True
    assert updated_calibration["功率元数据"]["总输入功率_w"] == pytest.approx(80.0)
    assert updated_calibration["校准结果"]["实测距离覆盖区间_m"]["最大"] == pytest.approx(1.2)
    with pytest.raises(ValueError):
        service.update_absolute_calibration({"element_powers_w": [1.0] * 64, "device_threshold": 12.0})
    naming_audit = service.audit_asset_naming()
    assert naming_audit["命名审计"]["通过"] is True
    assert naming_audit["命名审计"]["命名规则"]["编号规则"]["求解任务"].startswith("JOB-0001")
    assert naming_audit["命名审计"]["统计"]["路径检查数"] >= 8

    restored = Workbench3DService(None, tmp_path)
    assert restored.list_solve_jobs()["任务"][0]["id"] == "JOB-0001"
    assert restored.get_solve_job("JOB-0001")["任务"]["状态"] == "已完成"
    assert any(item["动作"] == "取消" for item in restored.get_solve_job("JOB-0001")["任务"]["操作日志"])
    assert restored.get_solve_job("JOB-0002")["任务"]["重试来源"] == "JOB-0001"
    assert restored.get_solve_job("JOB-0003")["任务"]["状态"] == "已完成"
    assert restored.get_solve_job("JOB-0004")["任务"]["状态"] == "已取消"
    assert restored.get_asset("JOB-0001")["资产"]["类型"] == "求解任务"
    assert restored.get_asset("IMP-CAL-001")["资产"]["类型"] == "导入标定桥接"


def test_v20a_api_exposes_workbench3d_scene_and_rejects_invalid_update(tmp_path):
    with TestClient(create_app(ROOT / "configs" / "cae_project_v14.yaml", tmp_path)) as client:
        scene = client.get("/api/workbench3d/scene")
        assert scene.status_code == 200
        payload = scene.json()
        assert payload["版本"] == "V2.0B-preview"
        assert payload["统计"]["目标区"] == 2

        moved = client.post("/api/workbench3d/objects/TGT-001", json={"properties": {"center_x_lambda": 0.45}})
        assert moved.status_code == 200
        moved_target = next(item for item in moved.json()["对象"] if item["id"] == "TGT-001")
        assert moved_target["属性"]["center_x_lambda"] == pytest.approx(0.45)

        transformed = client.post(
            "/api/workbench3d/objects/TGT-001",
            json={"properties": {"semi_major_lambda": 1.18, "semi_minor_lambda": 0.62, "rotation_deg": 35.0}},
        )
        assert transformed.status_code == 200
        transformed_target = next(item for item in transformed.json()["对象"] if item["id"] == "TGT-001")
        assert transformed_target["属性"]["semi_major_lambda"] == pytest.approx(1.18)
        assert transformed_target["属性"]["semi_minor_lambda"] == pytest.approx(0.62)
        assert transformed_target["属性"]["rotation_deg"] == pytest.approx(35.0)

        invalid = client.post("/api/workbench3d/objects/TGT-001", json={"properties": {"center_x_lambda": 99.0}})
        assert invalid.status_code == 400
        assert "target" in invalid.json()["detail"]

        material_update = client.post(
            "/api/workbench3d/materials/MAT-金属代理",
            json={"properties": {"reflection_magnitude": 0.66, "roughness_proxy": 0.11}},
        )
        assert material_update.status_code == 200
        material = next(item for item in material_update.json()["材料库"] if item["id"] == "MAT-金属代理")
        assert material["属性"]["reflection_magnitude"] == pytest.approx(0.66)
        assert material_update.json()["历史"]["可撤销"] is True

        invalid_material = client.post(
            "/api/workbench3d/materials/MAT-金属代理",
            json={"properties": {"reflection_magnitude": 1.5}},
        )
        assert invalid_material.status_code == 400
        assert "reflection_magnitude" in invalid_material.json()["detail"]

        history = client.get("/api/workbench3d/history")
        assert history.status_code == 200
        assert history.json()["可撤销"] is True

        undo_material = client.post("/api/workbench3d/undo")
        assert undo_material.status_code == 200
        undo_material_target = next(item for item in undo_material.json()["对象"] if item["id"] == "TGT-001")
        undo_material_record = next(item for item in undo_material.json()["材料库"] if item["id"] == "MAT-金属代理")
        assert undo_material_target["属性"]["center_x_lambda"] == pytest.approx(0.45)
        assert undo_material_target["属性"]["rotation_deg"] == pytest.approx(35.0)
        assert undo_material_record["属性"]["reflection_magnitude"] == pytest.approx(0.82)

        undo_target = client.post("/api/workbench3d/undo")
        assert undo_target.status_code == 200
        undo_target_record = next(item for item in undo_target.json()["对象"] if item["id"] == "TGT-001")
        assert undo_target_record["属性"]["center_x_lambda"] == pytest.approx(0.45)
        assert undo_target_record["属性"]["rotation_deg"] == pytest.approx(25.0)

        redo_target = client.post("/api/workbench3d/redo")
        assert redo_target.status_code == 200
        redo_target_record = next(item for item in redo_target.json()["对象"] if item["id"] == "TGT-001")
        assert redo_target_record["属性"]["center_x_lambda"] == pytest.approx(0.45)
        assert redo_target_record["属性"]["rotation_deg"] == pytest.approx(35.0)

        redo = client.post("/api/workbench3d/redo")
        assert redo.status_code == 200
        redo_material = next(item for item in redo.json()["材料库"] if item["id"] == "MAT-金属代理")
        assert redo_material["属性"]["reflection_magnitude"] == pytest.approx(0.66)

        solve = client.post("/api/workbench3d/solve")
        assert solve.status_code == 200
        assert solve.json()["成功"] is True
        assert solve.json()["阶段"] == "V2.0B 三维工作台求解联动预览"
        assert solve.json()["摘要"]["target_rmse_percent"] is not None
        assert solve.json()["对象指标"]
        assert any(item["object_id"] == "TGT-001" for item in solve.json()["对象指标"])
        result_id = solve.json()["result_id"]
        assert solve.json()["结果图层"]["field_hash"]
        assert solve.json()["结果图层"]["统计"]["平均值"] is not None
        assert Path(solve.json()["结果档案"]["保存路径"]).exists()
        assert (tmp_path / "workbench3d_results" / "index.json").exists()
        assert (tmp_path / "workbench3d_results" / "index.csv").exists()

        results = client.get("/api/workbench3d/results")
        assert results.status_code == 200
        assert results.json()["结果"][0]["id"] == result_id
        assert Path(results.json()["索引"]["json"]).exists()
        assert Path(results.json()["索引"]["csv"]).exists()

        result_detail = client.get(f"/api/workbench3d/results/{result_id}")
        assert result_detail.status_code == 200
        assert result_detail.json()["result_id"] == result_id
        assert result_detail.json()["结果图层"]["field_hash"] == solve.json()["结果图层"]["field_hash"]

        restored_archive = Workbench3DService(ROOT / "configs" / "cae_project_v14.yaml", tmp_path)
        restored_results = restored_archive.list_results()
        assert restored_results["结果"][0]["id"] == result_id
        assert restored_archive.get_result(result_id)["scene_hash"] == solve.json()["scene_hash"]

        job = client.post("/api/workbench3d/solve-jobs", json={"label": "API队列验收"})
        assert job.status_code == 200
        job_payload = job.json()
        assert job_payload["任务"]["id"] == "JOB-0001"
        assert job_payload["任务"]["状态"] == "已完成"
        assert job_payload["任务"]["result_id"] == job_payload["结果"]["result_id"]
        assert Path(job_payload["任务"]["任务路径"]).exists()

        jobs = client.get("/api/workbench3d/solve-jobs")
        assert jobs.status_code == 200
        assert jobs.json()["任务"][0]["id"] == "JOB-0001"
        assert Path(jobs.json()["索引"]["json"]).exists()
        assert Path(jobs.json()["索引"]["csv"]).exists()

        job_detail = client.get("/api/workbench3d/solve-jobs/JOB-0001")
        assert job_detail.status_code == 200
        assert job_detail.json()["任务"]["状态"] == "已完成"
        assert job_detail.json()["结果"]["result_id"] == job_payload["结果"]["result_id"]

        retry_job = client.post("/api/workbench3d/solve-jobs/JOB-0001/retry")
        assert retry_job.status_code == 200
        retry_payload = retry_job.json()
        assert retry_payload["操作"]["通过"] is True
        assert retry_payload["操作"]["新任务"] == "JOB-0002"
        assert retry_payload["任务"]["重试来源"] == "JOB-0001"
        assert retry_payload["结果"]["求解任务"]["重试来源"] == "JOB-0001"

        cancel_job = client.post("/api/workbench3d/solve-jobs/JOB-0001/cancel")
        assert cancel_job.status_code == 200
        assert cancel_job.json()["操作"]["通过"] is False
        assert cancel_job.json()["任务"]["状态"] == "已完成"

        job_audit = client.get("/api/workbench3d/solve-jobs/audit")
        assert job_audit.status_code == 200
        assert job_audit.json()["审计"]["通过"] is True
        assert job_audit.json()["审计"]["任务总数"] == 2
        assert Path(job_audit.json()["索引"]["audit_json"]).exists()
        assert Path(job_audit.json()["索引"]["audit_csv"]).exists()

        background_job = client.post(
            "/api/workbench3d/solve-jobs",
            json={"label": "API后台检查点", "background": True, "start_paused": True},
        )
        assert background_job.status_code == 200
        assert background_job.json()["任务"]["id"] == "JOB-0003"
        assert background_job.json()["任务"]["状态"] == "已暂停"

        resume_job = client.post("/api/workbench3d/solve-jobs/JOB-0003/resume")
        assert resume_job.status_code == 200
        assert resume_job.json()["操作"]["通过"] is True
        for _ in range(30):
            resumed_detail = client.get("/api/workbench3d/solve-jobs/JOB-0003")
            assert resumed_detail.status_code == 200
            if resumed_detail.json()["任务"]["状态"] == "已完成":
                break
            time.sleep(0.05)
        resumed_detail = client.get("/api/workbench3d/solve-jobs/JOB-0003")
        assert resumed_detail.json()["任务"]["状态"] == "已完成"
        assert resumed_detail.json()["结果"]["result_id"] == resumed_detail.json()["任务"]["result_id"]

        paused_job = client.post(
            "/api/workbench3d/solve-jobs",
            json={"label": "API后台取消", "background": True, "start_paused": True},
        )
        assert paused_job.status_code == 200
        assert paused_job.json()["任务"]["id"] == "JOB-0004"
        pause_again = client.post("/api/workbench3d/solve-jobs/JOB-0004/pause")
        assert pause_again.status_code == 200
        assert pause_again.json()["操作"]["通过"] is True
        cancel_background = client.post("/api/workbench3d/solve-jobs/JOB-0004/cancel")
        assert cancel_background.status_code == 200
        assert cancel_background.json()["操作"]["通过"] is True
        assert cancel_background.json()["任务"]["状态"] == "已取消"

        snapshot = client.post("/api/workbench3d/snapshots", json={"label": "API快照"})
        assert snapshot.status_code == 200
        snapshot_id = snapshot.json()["快照"]["id"]
        assert snapshot.json()["快照"]["scene_hash"] == redo.json()["scene_hash"]
        assert Path(snapshot.json()["快照"]["工程路径"]).exists()
        assert Path(snapshot.json()["快照"]["场景路径"]).exists()

        assets = client.get("/api/workbench3d/assets")
        assert assets.status_code == 200
        asset_payload = assets.json()
        asset_types = {item["类型"] for item in asset_payload["资产"]}
        assert {"求解任务", "求解结果", "工程快照", "材料代理审计"} <= asset_types
        assert Path(asset_payload["索引"]["json"]).exists()
        assert Path(asset_payload["索引"]["csv"]).exists()
        assert Path(asset_payload["索引"]["sqlite"]).exists()
        assert Path(asset_payload["索引"]["audit_json"]).exists()
        assert Path(asset_payload["索引"]["audit_csv"]).exists()
        assert Path(asset_payload["索引"]["database_audit_json"]).exists()
        assert Path(asset_payload["索引"]["database_audit_csv"]).exists()
        assert Path(asset_payload["索引"]["naming_audit_json"]).exists()
        assert Path(asset_payload["索引"]["naming_audit_csv"]).exists()
        assert Path(asset_payload["索引"]["lineage_json"]).exists()
        assert Path(asset_payload["索引"]["lineage_csv"]).exists()
        assert Path(asset_payload["索引"]["reproducibility_audit_json"]).exists()
        assert Path(asset_payload["索引"]["reproducibility_audit_csv"]).exists()
        assert Path(asset_payload["索引"]["absolute_calibration_json"]).exists()
        assert Path(asset_payload["索引"]["absolute_calibration_points_csv"]).exists()
        assert Path(asset_payload["索引"]["absolute_element_powers_csv"]).exists()
        assert Path(asset_payload["索引"]["imported_calibration_bridge_json"]).exists()
        assert Path(asset_payload["索引"]["imported_calibration_bridge_csv"]).exists()
        assert Path(asset_payload["索引"]["material_proxy_audit_json"]).exists()
        assert Path(asset_payload["索引"]["material_proxy_audit_csv"]).exists()
        assert asset_payload["审计"]["通过"] is True
        assert asset_payload["数据库审计"]["通过"] is True
        assert {"workbench3d_solve_jobs", "workbench3d_results", "workbench3d_snapshots"} <= set(asset_payload["数据库审计"]["表"])
        assert asset_payload["命名审计"]["通过"] is True
        assert asset_payload["复现审计"]["通过"] is True
        assert asset_payload["绝对量纲标定"]["通过"] is True
        assert asset_payload["导入数据标定桥接"]["通过"] is True
        assert asset_payload["材料代理审计"]["通过"] is True
        assert any(item["资产id"] == "IMP-CAL-001" and item["类型"] == "导入标定桥接" for item in asset_payload["资产"])
        assert any(item["资产id"] == "MAT-AUDIT-001" and item["类型"] == "材料代理审计" for item in asset_payload["资产"])

        material_audit = client.get("/api/workbench3d/materials/audit")
        assert material_audit.status_code == 200
        assert material_audit.json()["材料代理审计"]["通过"] is True
        assert material_audit.json()["材料代理审计"]["材料数量"] >= 1

        filtered_assets = client.get("/api/workbench3d/assets", params={"asset_type": "求解任务", "q": "JOB-0001", "limit": 1})
        assert filtered_assets.status_code == 200
        assert filtered_assets.json()["筛选"]["匹配资产"] == 1
        assert filtered_assets.json()["资产"][0]["资产id"] == "JOB-0001"

        asset_audit = client.get("/api/workbench3d/assets/audit", params={"asset_type": "求解任务"})
        assert asset_audit.status_code == 200
        assert asset_audit.json()["审计"]["通过"] is True
        assert asset_audit.json()["审计"]["匹配资产"] == 4

        asset_database = client.get("/api/workbench3d/assets/database")
        assert asset_database.status_code == 200
        assert asset_database.json()["数据库审计"]["通过"] is True
        assert asset_database.json()["数据库审计"]["行数"]["workbench3d_assets"] == len(asset_payload["资产"])
        assert asset_database.json()["数据库审计"]["行数"]["workbench3d_solve_jobs"] == 4
        assert asset_database.json()["数据库审计"]["行数"]["workbench3d_solve_job_events"] >= 11
        assert asset_database.json()["数据库审计"]["行数"]["workbench3d_results"] >= 4
        assert asset_database.json()["数据库审计"]["行数"]["workbench3d_snapshots"] == 1
        assert any(item["action"] == "重试" for item in asset_database.json()["任务事件"])
        assert any(item["action"] == "恢复" for item in asset_database.json()["任务事件"])
        assert any(item["action"] == "完成" for item in asset_database.json()["任务事件"])

        database_records = client.get("/api/workbench3d/assets/database/records", params={"table": "workbench3d_snapshots", "limit": 1})
        assert database_records.status_code == 200
        assert database_records.json()["表"] == ["workbench3d_snapshots"]
        assert database_records.json()["行数"]["workbench3d_snapshots"] == 1
        assert database_records.json()["结构"]["workbench3d_snapshots"][0]["列"] == "snapshot_id"
        assert len(database_records.json()["记录"]["workbench3d_snapshots"]) == 1
        invalid_records = client.get("/api/workbench3d/assets/database/records", params={"table": "unknown"})
        assert invalid_records.status_code == 400

        asset_lineage = client.get("/api/workbench3d/assets/lineage")
        assert asset_lineage.status_code == 200
        assert asset_lineage.json()["通过"] is True
        assert asset_lineage.json()["摘要"]["任务数"] == 4
        assert asset_lineage.json()["摘要"]["任务结果边"] >= 3
        assert any(edge["关系"] == "生成结果" and edge["source"] == "JOB-0001" and edge["target"] == job_payload["任务"]["result_id"] for edge in asset_lineage.json()["边"])
        assert any(edge["关系"] == "重试派生" and edge["source"] == "JOB-0001" and edge["target"] == "JOB-0002" for edge in asset_lineage.json()["边"])

        asset_reproducibility = client.get("/api/workbench3d/assets/reproducibility")
        assert asset_reproducibility.status_code == 200
        assert asset_reproducibility.json()["通过"] is True
        assert asset_reproducibility.json()["摘要"]["结果数"] >= 4
        assert Path(asset_reproducibility.json()["索引"]["reproducibility_audit_json"]).exists()

        imported_calibration = client.get("/api/workbench3d/assets/imported-calibration")
        assert imported_calibration.status_code == 200
        assert imported_calibration.json()["通过"] is True
        assert imported_calibration.json()["摘要"]["样本数"] == 5
        assert imported_calibration.json()["摘要"]["可纳入正式可信度评分"] is False
        assert Path(imported_calibration.json()["索引"]["imported_calibration_bridge_json"]).exists()

        absolute_calibration = client.get("/api/workbench3d/absolute-calibration")
        assert absolute_calibration.status_code == 200
        assert absolute_calibration.json()["通过"] is True
        assert absolute_calibration.json()["阵列"]["阵元数"] == 64
        assert "真实作用距离" in absolute_calibration.json()["不输出项"]
        posted_calibration = client.post(
            "/api/workbench3d/absolute-calibration",
            json={
                "element_powers_w": [1.5] * 64,
                "calibration_points": [
                    {"point_id": "API-001", "distance_m": 1.0, "normalized_model_amplitude": 1.0, "measured_field_v_per_m": 4.0, "uncertainty_percent": 5.0},
                    {"point_id": "API-002", "distance_m": 1.8, "normalized_model_amplitude": 0.5, "measured_field_v_per_m": 2.0, "uncertainty_percent": 7.0},
                ],
            },
        )
        assert posted_calibration.status_code == 200
        assert posted_calibration.json()["功率元数据"]["总输入功率_w"] == pytest.approx(96.0)
        assert posted_calibration.json()["校准结果"]["实测距离覆盖区间_m"]["最大"] == pytest.approx(1.8)
        forbidden_calibration = client.post(
            "/api/workbench3d/absolute-calibration",
            json={"element_powers_w": [1.0] * 64, "device_threshold": 10.0},
        )
        assert forbidden_calibration.status_code == 400
        assert "阈值" in forbidden_calibration.json()["detail"]

        asset_naming = client.get("/api/workbench3d/assets/naming")
        assert asset_naming.status_code == 200
        assert asset_naming.json()["命名审计"]["通过"] is True
        assert asset_naming.json()["命名审计"]["统计"]["任务数"] == 4
        assert Path(asset_naming.json()["索引"]["naming_audit_json"]).exists()
        assert not list((tmp_path / "workbench3d_solve_jobs").glob("JOB-0003_*_no_result.json"))

        job_asset = client.get("/api/workbench3d/assets/JOB-0001")
        assert job_asset.status_code == 200
        assert job_asset.json()["资产"]["类型"] == "求解任务"
        assert job_asset.json()["详情"]["任务"]["状态"] == "已完成"
        assert any(item["动作"] == "取消" for item in job_asset.json()["详情"]["任务"]["操作日志"])

        result_asset = client.get(f"/api/workbench3d/assets/{result_id}")
        assert result_asset.status_code == 200
        assert result_asset.json()["资产"]["类型"] == "求解结果"
        assert result_asset.json()["详情"]["result_id"] == result_id

        snapshot_asset = client.get(f"/api/workbench3d/assets/{snapshot_id}")
        assert snapshot_asset.status_code == 200
        assert snapshot_asset.json()["资产"]["类型"] == "工程快照"
        assert snapshot_asset.json()["详情"]["id"] == snapshot_id

        shifted = client.post("/api/workbench3d/objects/TGT-001", json={"properties": {"center_x_lambda": 0.55}})
        assert shifted.status_code == 200
        snapshot_next = client.post("/api/workbench3d/snapshots", json={"label": "API快照-移动后"})
        assert snapshot_next.status_code == 200
        snapshot_next_id = snapshot_next.json()["快照"]["id"]
        assert snapshot_next_id == "SNP-0002"

        diff = client.get(f"/api/workbench3d/snapshots/{snapshot_id}/diff/{snapshot_next_id}")
        assert diff.status_code == 200
        assert diff.json()["scene_hash_changed"] is True
        assert diff.json()["摘要"]["字段变更数"] >= 1
        target_diff = next(item for item in diff.json()["对象差异"] if item["id"] == "TGT-001")
        assert any(change["字段"].endswith("center_x_lambda") for change in target_diff["变更"])

        snapshots = client.get("/api/workbench3d/snapshots")
        assert snapshots.status_code == 200
        assert snapshots.json()["快照"][0]["id"] == snapshot_id
        assert Path(snapshots.json()["索引"]["json"]).exists()
        assert Path(snapshots.json()["索引"]["csv"]).exists()

        restored = client.post(f"/api/workbench3d/snapshots/{snapshot_id}/restore")
        assert restored.status_code == 200
        restored_target = next(item for item in restored.json()["对象"] if item["id"] == "TGT-001")
        assert restored_target["属性"]["center_x_lambda"] == pytest.approx(0.45)

        restored_snapshot_archive = Workbench3DService(ROOT / "configs" / "cae_project_v14.yaml", tmp_path)
        assert restored_snapshot_archive.list_snapshots()["快照"][0]["id"] == snapshot_id


def test_v20b_frontend_assets_are_local_and_registered():
    with TestClient(create_app(ROOT / "configs" / "cae_project_v14.yaml")) as client:
        response = client.get("/")
    assert response.status_code == 200
    html = response.text
    assert "V2.0B 三维 CAE 编辑器" in html
    assert "workbench3d.js" in html
    assert "workbench3d-move-mode" in html
    assert "workbench3d-undo" in html
    assert "workbench3d-capture-snapshot" in html
    assert "workbench3d-run-solve" in html
    assert "workbench3d-solve-jobs" in html
    assert "workbench3d-asset-ledger" in html
    assert "绝对量纲标定" in html
    assert "workbench3d-solve-panel" in html
    assert "workbench3d-result-archive" in html
    assert "workbench3d-snapshot-archive" in html
    assert "workbench3d-material-editor" in html
    assert "three.module.min.js" not in html
    assert (ROOT / "src" / "hpm_platform" / "ui" / "static_v20a" / "vendor" / "three.module.min.js").stat().st_size > 500_000
    assert "Three.js" in (ROOT / "THIRD_PARTY_NOTICES.md").read_text(encoding="utf-8")
    assert (ROOT / "licenses" / "THREE_LICENSE.txt").stat().st_size > 500
    js = (ROOT / "src" / "hpm_platform" / "ui" / "static_v20a" / "js" / "workbench3d.js").read_text(encoding="utf-8")
    assert "/api/workbench3d/solve" in js
    assert "/api/workbench3d/solve-jobs" in js
    assert "/api/workbench3d/solve-jobs/audit" in js
    assert "/retry" in js
    assert "/cancel" in js
    assert "/pause" in js
    assert "/resume" in js
    assert "background: true" in js
    assert "start_paused: true" in js
    assert "/api/workbench3d/assets" in js
    assert "/api/workbench3d/assets/audit" in js
    assert "/api/workbench3d/assets/database" in js
    assert "/api/workbench3d/assets/database/records" in js
    assert "/api/workbench3d/assets/lineage" in js
    assert "/api/workbench3d/assets/reproducibility" in js
    assert "/api/workbench3d/assets/imported-calibration" in js
    assert "/api/workbench3d/assets/naming" in js
    assert "/api/workbench3d/absolute-calibration" in js
    assert "/api/workbench3d/materials/audit" in js
    assert "workbench3d-result-layer" in js
    assert "data-job-action" in js
    assert 'data-job-action="retry"' in js
    assert 'data-job-action="cancel"' in js
    assert 'data-job-action="pause"' in js
    assert 'data-job-action="resume"' in js
    assert 'data-job-action="background"' in js
    assert "workbench3d-solve-job-audit" in js
    assert "solveJobAudit" in js
    assert "data-asset-action" in js
    assert 'data-asset-action="database"' in js
    assert 'data-asset-action="records"' in js
    assert 'data-asset-action="lineage"' in js
    assert 'data-asset-action="reproducibility"' in js
    assert 'data-asset-action="calibration"' in js
    assert 'data-asset-action="imported-calibration"' in js
    assert 'data-asset-action="materials"' in js
    assert 'data-asset-action="naming"' in js
    assert "data-asset-filter" in js
    assert "assetDatabaseAudit" in js
    assert "assetDatabaseRecords" in js
    assert "assetLineage" in js
    assert "workbench3d-asset-lineage" in js
    assert "assetReproducibilityAudit" in js
    assert "assetAbsoluteCalibration" in js
    assert "workbench3d-absolute-calibration" in js
    assert "workbench3d-imported-calibration" in js
    assert "workbench3d-imported-calibration-mini" in js
    assert "workbench3d-asset-reproducibility" in js
    assert "workbench3d-asset-calibration" in js
    assert "workbench3d-database-records" in js
    assert "assetNamingAudit" in js
    assert "assetMaterialAudit" in js
    assert "workbench3d-asset-filters" in js
    assert "workbench3d-transform-controls" in js
    assert "data-transform-action" in js
    assert "transformPatch" in js
    assert "workbench3d-result-diagnostics" in js
    assert "workbench3d-profile-inspector" in js
    assert "data-profile-axis" in js
    assert "profileAxis" in js
    assert "workbench3d-validity-diagnostics" in js
    assert "data-validity-status" in js
    assert "workbench3d-object-metrics" in js
    assert "addMetricBadge" in js
    assert "/api/workbench3d/results" in js
    assert "/api/workbench3d/snapshots" in js
    assert "data-snapshot-action" in js
    assert "workbench3d-snapshot-diff" in js
    assert "结果图层" in js
    css = (ROOT / "src" / "hpm_platform" / "ui" / "static_v20a" / "css" / "v20a.css").read_text(encoding="utf-8")
    assert "workbench3d-result-colorbar" in css
    assert "workbench3d-profile-chart" in css
    assert "workbench3d-validity-checks" in css
    assert "workbench3d-solve-job-list" in css
    assert "workbench3d-solve-job-audit" in css
    assert "workbench3d-absolute-calibration" in css
    assert "workbench3d-imported-calibration" in css
    assert "workbench3d-imported-calibration-mini" in css
    assert "workbench3d-calibration-form" in css
    assert "workbench3d-solve-job-empty" in css
    assert "workbench3d-solve-job.cancelled" in css
    assert "workbench3d-solve-job.paused" in css
    assert "workbench3d-asset-record" in css
    assert "workbench3d-asset-toolbar" in css
    assert "workbench3d-asset-summary" in css
    assert "workbench3d-transform-controls" in css
    assert "workbench3d-transform-buttons" in css
    assert "workbench3d-object-metrics" in css
    assert "workbench3d-result-record" in css
    assert "workbench3d-snapshot-archive" in css

"""HPM-DT CAE 场景工作台。"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from starlette.templating import Jinja2Templates

from hpm_platform.ui.v20a_service import V20AValidationService

PACKAGE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = PACKAGE_DIR.parents[2]
STATIC_V14_DIR = PACKAGE_DIR / "static_v14"
STATIC_V20A_DIR = PACKAGE_DIR / "static_v20a"
TEMPLATE_DIR = PACKAGE_DIR / "templates_v20a"
DEFAULT_PROJECT = PROJECT_ROOT / "configs" / "cae_project_v14.yaml"
DEFAULT_OUTPUT = PROJECT_ROOT / "outputs_v20a_vv"


class RunVVRequest(BaseModel):
    mode: str = "fast"


class SceneObjectPatchRequest(BaseModel):
    properties: dict[str, Any]
    save: bool = False


class SceneSnapshotRequest(BaseModel):
    label: str | None = None


class SolveJobRequest(BaseModel):
    label: str | None = None
    background: bool = False
    start_paused: bool = False


class PluginEnableRequest(BaseModel):
    enabled: bool = True


class PluginRunRequest(BaseModel):
    parameters: dict[str, Any] = Field(default_factory=dict)


class PaperFactoryRequest(BaseModel):
    title: str | None = None
    refresh_vv: bool = False


class DataImportPathRequest(BaseModel):
    path: str


class MissionRunRequest(BaseModel):
    template_id: str = "MST-TRACK-001"
    frames: int | None = None
    controller: str | None = None
    label: str | None = None


def create_app(
    project_path: str | Path | None = None,
    output_dir: str | Path | None = None,
) -> FastAPI:
    service = V20AValidationService(project_path or DEFAULT_PROJECT, output_dir or DEFAULT_OUTPUT)
    download_dir = Path(output_dir or DEFAULT_OUTPUT)
    app = FastAPI(
        title="HPM-DT 高功率微波数字孪生 CAE 平台",
        description="全中文、本地离线、面向 HPM-DT 长期平台目标的 Scene First CAE 场景工作台",
        version="2.0A",
        docs_url="/接口文档",
        redoc_url=None,
    )
    app.state.service = service
    app.mount("/static", StaticFiles(directory=STATIC_V14_DIR), name="static")
    app.mount("/static_v20a", StaticFiles(directory=STATIC_V20A_DIR), name="static_v20a")
    templates = Jinja2Templates(directory=TEMPLATE_DIR)
    templates.env.policies["json.dumps_kwargs"] = {"ensure_ascii": False}

    @app.get("/", response_class=HTMLResponse)
    async def index(request: Request):
        return templates.TemplateResponse(
            request=request,
            name="index.html",
            context={
                "version": "V2.0A",
                "platform": service.north_star_payload(),
            },
        )

    @app.get("/api/health")
    async def health() -> dict[str, Any]:
        return {"状态": "正常", "平台版本": "2.0A", "平台": "HPM-DT", "页面": "CAE场景工作台"}

    @app.get("/api/platform/north-star")
    async def north_star() -> dict[str, Any]:
        return service.north_star_payload()

    @app.get("/api/platform/readiness")
    async def platform_readiness() -> dict[str, Any]:
        try:
            return service.platform_readiness()
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"生成平台成熟度与发文准备度报告失败：{exc}") from exc

    @app.get("/api/platform/mission-control")
    async def platform_mission_control() -> dict[str, Any]:
        try:
            return service.mission_control()
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"生成主控台状态失败：{exc}") from exc

    @app.get("/api/mission/templates")
    async def mission_templates() -> dict[str, Any]:
        return service.mission_sim.catalog()

    @app.get("/api/mission/status")
    async def mission_status() -> dict[str, Any]:
        return service.mission_sim.status()

    @app.post("/api/mission/run")
    async def mission_run(payload: MissionRunRequest) -> dict[str, Any]:
        try:
            return service.mission_sim.run_mission(
                payload.template_id,
                frames=payload.frames,
                controller=payload.controller,
                label=payload.label,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"运行任务级仿真失败：{exc}") from exc

    @app.get("/api/mission/results/{mission_id}")
    async def mission_result(mission_id: str) -> dict[str, Any]:
        try:
            return service.mission_sim.get_mission(mission_id)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.get("/api/plugins/catalog")
    async def plugin_catalog() -> dict[str, Any]:
        return service.plugins.catalog()

    @app.get("/api/plugins/acceptance")
    async def plugin_acceptance() -> dict[str, Any]:
        return service.plugins.acceptance_summary()

    @app.get("/api/plugins/{plugin_id}")
    async def plugin_detail(plugin_id: str) -> dict[str, Any]:
        try:
            return service.plugins.plugin_detail(plugin_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.post("/api/plugins/{plugin_id}/enable")
    async def plugin_enable(plugin_id: str, payload: PluginEnableRequest) -> dict[str, Any]:
        try:
            return service.plugins.set_enabled(plugin_id, payload.enabled)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.post("/api/plugins/{plugin_id}/run")
    async def plugin_run(plugin_id: str, payload: PluginRunRequest) -> dict[str, Any]:
        try:
            return service.plugins.run_plugin(plugin_id, payload.parameters)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/api/paper-factory/status")
    async def paper_factory_status() -> dict[str, Any]:
        return service.paper_factory.status()

    @app.post("/api/paper-factory/generate")
    async def paper_factory_generate(payload: PaperFactoryRequest) -> dict[str, Any]:
        try:
            if payload.refresh_vv or service.paper_factory.status().get("状态") == "尚未生成":
                service.run("fast")
            return service.paper_factory.generate(title=payload.title)
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"生成论文草稿包失败：{exc}") from exc

    @app.get("/api/data-import/catalog")
    async def data_import_catalog() -> dict[str, Any]:
        return service.data_import.catalog()

    @app.get("/api/data-import/acceptance")
    async def data_import_acceptance() -> dict[str, Any]:
        return service.data_import.acceptance_summary()

    @app.get("/api/data-import/calibration-readiness")
    async def data_import_calibration_readiness() -> dict[str, Any]:
        return service.data_import.calibration_readiness()

    @app.get("/api/data-import/calibration-bridge")
    async def data_import_calibration_bridge() -> dict[str, Any]:
        try:
            return service.data_import_calibration_bridge()
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"生成数据导入标定桥接预览失败：{exc}") from exc

    @app.get("/api/data-import/model-comparison")
    async def data_import_model_comparison() -> dict[str, Any]:
        try:
            return service.data_import_model_comparison()
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"生成数据导入模型误差对比预览失败：{exc}") from exc

    @app.get("/api/data-import/evidence-chain")
    async def data_import_evidence_chain() -> dict[str, Any]:
        try:
            return service.data_import_evidence_chain()
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"生成外部数据证据链审计失败：{exc}") from exc

    @app.post("/api/data-import/evidence-package")
    async def data_import_evidence_package(payload: DataImportPathRequest) -> dict[str, Any]:
        try:
            return service.data_import_evidence_package(payload.path)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"审计外部数据正式证据包失败：{exc}") from exc

    @app.get("/api/data-import/evidence-package/template")
    async def data_import_evidence_package_template() -> dict[str, Any]:
        try:
            return service.data_import_evidence_package_template()
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"生成外部数据正式证据包模板失败：{exc}") from exc

    @app.post("/api/data-import/evidence-package/vv-candidate")
    async def data_import_evidence_package_vv_candidate(payload: DataImportPathRequest) -> dict[str, Any]:
        try:
            return service.data_import_evidence_package_vv_candidate(payload.path)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"生成外部数据证据包 V&V 候选评分失败：{exc}") from exc

    @app.get("/api/data-import/vv-audit")
    async def data_import_vv_audit() -> dict[str, Any]:
        try:
            return service.data_import_vv_audit()
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"生成外部数据V&V审计失败：{exc}") from exc

    @app.get("/api/data-import/samples/{sample_id}")
    async def data_import_sample(sample_id: str) -> dict[str, Any]:
        try:
            return service.data_import.inspect_sample(sample_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"解析数据样例失败：{exc}") from exc

    @app.post("/api/data-import/inspect")
    async def data_import_inspect(payload: DataImportPathRequest) -> dict[str, Any]:
        try:
            return service.data_import.inspect_path(payload.path)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"解析外部数据失败：{exc}") from exc

    @app.get("/api/workbench3d/scene")
    async def workbench3d_scene() -> dict[str, Any]:
        try:
            service.ensure_workbench_imported_calibration_bridge()
            return service.workbench3d.scene()
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"读取三维场景失败：{exc}") from exc

    @app.post("/api/workbench3d/objects/{object_id}")
    async def update_workbench3d_object(object_id: str, payload: SceneObjectPatchRequest) -> dict[str, Any]:
        try:
            return service.workbench3d.update_object(object_id, payload.properties, save=payload.save)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"更新三维对象失败：{exc}") from exc

    @app.post("/api/workbench3d/materials/{material_id}")
    async def update_workbench3d_material(material_id: str, payload: SceneObjectPatchRequest) -> dict[str, Any]:
        try:
            return service.workbench3d.update_material(material_id, payload.properties, save=payload.save)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"更新材料代理失败：{exc}") from exc

    @app.get("/api/workbench3d/materials/audit")
    async def audit_workbench3d_materials() -> dict[str, Any]:
        try:
            return service.workbench3d.audit_materials()
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"生成材料代理审计失败：{exc}") from exc

    @app.post("/api/workbench3d/solve")
    async def solve_workbench3d_scene() -> dict[str, Any]:
        try:
            return service.workbench3d.solve_preview()
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"三维工作台求解失败：{exc}") from exc

    @app.get("/api/workbench3d/absolute-calibration")
    async def get_workbench3d_absolute_calibration() -> dict[str, Any]:
        return service.workbench3d.absolute_calibration()

    @app.post("/api/workbench3d/absolute-calibration")
    async def update_workbench3d_absolute_calibration(payload: dict[str, Any]) -> dict[str, Any]:
        try:
            return service.workbench3d.update_absolute_calibration(payload)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/workbench3d/solve-jobs")
    async def submit_workbench3d_solve_job(payload: SolveJobRequest) -> dict[str, Any]:
        try:
            if payload.background:
                return service.workbench3d.submit_background_solve_job(payload.label, start_paused=payload.start_paused)
            return service.workbench3d.submit_solve_job(payload.label)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"三维求解任务失败：{exc}") from exc

    @app.get("/api/workbench3d/solve-jobs")
    async def list_workbench3d_solve_jobs() -> dict[str, Any]:
        return service.workbench3d.list_solve_jobs()

    @app.get("/api/workbench3d/solve-jobs/audit")
    async def audit_workbench3d_solve_jobs() -> dict[str, Any]:
        return service.workbench3d.audit_solve_jobs()

    @app.post("/api/workbench3d/solve-jobs/{job_id}/cancel")
    async def cancel_workbench3d_solve_job(job_id: str) -> dict[str, Any]:
        try:
            return service.workbench3d.cancel_solve_job(job_id)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"取消三维求解任务失败：{exc}") from exc

    @app.post("/api/workbench3d/solve-jobs/{job_id}/pause")
    async def pause_workbench3d_solve_job(job_id: str) -> dict[str, Any]:
        try:
            return service.workbench3d.pause_solve_job(job_id)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"暂停三维求解任务失败：{exc}") from exc

    @app.post("/api/workbench3d/solve-jobs/{job_id}/resume")
    async def resume_workbench3d_solve_job(job_id: str) -> dict[str, Any]:
        try:
            return service.workbench3d.resume_solve_job(job_id)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"恢复三维求解任务失败：{exc}") from exc

    @app.post("/api/workbench3d/solve-jobs/{job_id}/retry")
    async def retry_workbench3d_solve_job(job_id: str) -> dict[str, Any]:
        try:
            return service.workbench3d.retry_solve_job(job_id)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"重试三维求解任务失败：{exc}") from exc

    @app.get("/api/workbench3d/solve-jobs/{job_id}")
    async def get_workbench3d_solve_job(job_id: str) -> dict[str, Any]:
        try:
            return service.workbench3d.get_solve_job(job_id)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"读取三维求解任务失败：{exc}") from exc

    @app.get("/api/workbench3d/assets")
    async def list_workbench3d_assets(
        asset_type: str | None = None,
        q: str | None = None,
        limit: int | None = None,
    ) -> dict[str, Any]:
        return service.workbench3d.list_assets(asset_type=asset_type, query=q, limit=limit)

    @app.get("/api/workbench3d/assets/audit")
    async def audit_workbench3d_assets(asset_type: str | None = None, q: str | None = None) -> dict[str, Any]:
        return service.workbench3d.audit_assets(asset_type=asset_type, query=q)

    @app.get("/api/workbench3d/assets/database")
    async def audit_workbench3d_asset_database() -> dict[str, Any]:
        return service.workbench3d.audit_asset_database()

    @app.get("/api/workbench3d/assets/database/records")
    async def browse_workbench3d_asset_database_records(
        table: str | None = None,
        limit: int | None = 50,
    ) -> dict[str, Any]:
        try:
            return service.workbench3d.asset_database_records(table=table, limit=limit)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/api/workbench3d/assets/naming")
    async def audit_workbench3d_asset_naming() -> dict[str, Any]:
        return service.workbench3d.audit_asset_naming()

    @app.get("/api/workbench3d/assets/lineage")
    async def trace_workbench3d_asset_lineage() -> dict[str, Any]:
        return service.workbench3d.asset_lineage()

    @app.get("/api/workbench3d/assets/reproducibility")
    async def audit_workbench3d_asset_reproducibility() -> dict[str, Any]:
        return service.workbench3d.asset_reproducibility()

    @app.get("/api/workbench3d/assets/imported-calibration")
    async def workbench3d_imported_calibration_bridge() -> dict[str, Any]:
        return service.ensure_workbench_imported_calibration_bridge()

    @app.get("/api/workbench3d/assets/{asset_id}")
    async def get_workbench3d_asset(asset_id: str) -> dict[str, Any]:
        try:
            return service.workbench3d.get_asset(asset_id)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"读取三维工程资产失败：{exc}") from exc

    @app.get("/api/workbench3d/results")
    async def list_workbench3d_results() -> dict[str, Any]:
        return service.workbench3d.list_results()

    @app.get("/api/workbench3d/results/{result_id}")
    async def get_workbench3d_result(result_id: str) -> dict[str, Any]:
        try:
            return service.workbench3d.get_result(result_id)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"读取三维求解结果失败：{exc}") from exc

    @app.post("/api/workbench3d/reset")
    async def reset_workbench3d_scene() -> dict[str, Any]:
        try:
            return service.workbench3d.reset()
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"重置三维场景失败：{exc}") from exc

    @app.get("/api/workbench3d/history")
    async def workbench3d_history() -> dict[str, Any]:
        return service.workbench3d.history()

    @app.post("/api/workbench3d/undo")
    async def undo_workbench3d_scene() -> dict[str, Any]:
        try:
            return service.workbench3d.undo()
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"撤销三维编辑失败：{exc}") from exc

    @app.post("/api/workbench3d/redo")
    async def redo_workbench3d_scene() -> dict[str, Any]:
        try:
            return service.workbench3d.redo()
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"重做三维编辑失败：{exc}") from exc

    @app.get("/api/workbench3d/snapshots")
    async def list_workbench3d_snapshots() -> dict[str, Any]:
        return service.workbench3d.list_snapshots()

    @app.post("/api/workbench3d/snapshots")
    async def capture_workbench3d_snapshot(payload: SceneSnapshotRequest) -> dict[str, Any]:
        try:
            return service.workbench3d.capture_snapshot(payload.label)
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"创建三维工程快照失败：{exc}") from exc

    @app.post("/api/workbench3d/snapshots/{snapshot_id}/restore")
    async def restore_workbench3d_snapshot(snapshot_id: str) -> dict[str, Any]:
        try:
            return service.workbench3d.restore_snapshot(snapshot_id)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"恢复三维工程快照失败：{exc}") from exc

    @app.get("/api/workbench3d/snapshots/{left_id}/diff/{right_id}")
    async def diff_workbench3d_snapshots(left_id: str, right_id: str) -> dict[str, Any]:
        try:
            return service.workbench3d.diff_snapshots(left_id, right_id)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"对比三维工程快照失败：{exc}") from exc

    @app.get("/api/vv/overview")
    async def overview() -> dict[str, Any]:
        try:
            return service.overview()
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"读取V&V总览失败：{exc}") from exc

    @app.post("/api/vv/run")
    async def run_vv_api(payload: RunVVRequest) -> dict[str, Any]:
        try:
            return service.run(payload.mode)
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"运行V&V失败：{exc}") from exc

    @app.get("/download/vv-results.zip")
    async def download_results_zip() -> FileResponse:
        path = download_dir / "v20A_VV结果包.zip"
        if not path.exists():
            service.run("fast")
        return FileResponse(path, filename="v20A_VV结果包.zip")

    @app.get("/download/vv-report.html")
    async def download_report() -> FileResponse:
        path = download_dir / "v20A_可信度验证报告.html"
        if not path.exists():
            service.run("fast")
        return FileResponse(path, filename="v20A_可信度验证报告.html")

    @app.get("/download/vv-latex.tex")
    async def download_latex() -> FileResponse:
        path = download_dir / "v20A_论文表格.tex"
        if not path.exists():
            service.run("fast")
        return FileResponse(path, filename="v20A_论文表格.tex")

    @app.get("/download/paper-factory.zip")
    async def download_paper_factory() -> FileResponse:
        path = service.paper_factory.archive_path()
        if not path.exists():
            service.run("fast")
            service.paper_factory.generate()
        return FileResponse(path, filename="HPM_DT_V20D_paper_factory_bundle.zip")

    return app


app = create_app()

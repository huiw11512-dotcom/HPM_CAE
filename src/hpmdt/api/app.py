"""HPM-DT Studio FastAPI 入口。"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import Body, FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from hpmdt.application import Workspace
from hpmdt.solvers.free_space import SimulationResult

PACKAGE_ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = PACKAGE_ROOT.parents[1]
STATIC_DIR = PACKAGE_ROOT / "frontend" / "static"
TEMPLATE_DIR = PACKAGE_ROOT / "frontend" / "templates"
WORKSPACE_DIR = PROJECT_ROOT / "workspaces"

workspace = Workspace(WORKSPACE_DIR)

app = FastAPI(
    title="HPM-DT Studio",
    version="0.1.0-alpha",
    description="面向系统级电磁场景与任务仿真的全中文研究工作台",
)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
templates = Jinja2Templates(directory=TEMPLATE_DIR)


@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={"app_version": app.version},
    )


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok", "version": app.version}


@app.get("/api/bootstrap")
def bootstrap() -> dict[str, Any]:
    return workspace.bootstrap()


@app.post("/api/examples/{example_id}/load")
def load_example(example_id: str) -> dict[str, Any]:
    try:
        workspace.load_example(example_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="示例工程不存在") from exc
    return workspace.bootstrap()


@app.post("/api/entities")
def add_entity(payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
    kind = str(payload.get("kind", ""))
    try:
        entity = workspace.add_entity(kind)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return entity.model_dump()


@app.patch("/api/entities/{entity_id}")
def update_entity(entity_id: str, payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
    try:
        entity = workspace.update_entity(entity_id, payload)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="实体不存在") from exc
    return entity.model_dump()


@app.delete("/api/entities/{entity_id}")
def delete_entity(entity_id: str) -> dict[str, bool]:
    workspace.delete_entity(entity_id)
    return {"deleted": True}


@app.post("/api/missions/default")
def add_default_mission() -> dict[str, Any]:
    return workspace.add_default_mission().model_dump()


@app.post("/api/missions/{mission_id}/run")
def run_mission(mission_id: str) -> dict[str, Any]:
    try:
        result = workspace.run(mission_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="任务不存在") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return result.to_jsonable()


@app.get("/api/results/{result_id}")
def get_result(result_id: str) -> dict[str, Any]:
    result = workspace.results.get(result_id)
    if result is None:
        raise HTTPException(status_code=404, detail="结果不存在")
    if isinstance(result, SimulationResult):
        return result.to_jsonable()
    return result


@app.post("/api/project/new")
def new_project() -> dict[str, Any]:
    workspace.load_example("empty")
    return workspace.bootstrap()


@app.post("/api/project/open")
async def open_project(file: UploadFile = File(...)) -> dict[str, Any]:
    filename = Path(file.filename or "project.hpmdt").name
    if not filename.lower().endswith(".hpmdt"):
        raise HTTPException(status_code=400, detail="请选择 .hpmdt 工程文件")
    destination = WORKSPACE_DIR / filename
    destination.write_bytes(await file.read())
    try:
        workspace.load_path(destination)
    except Exception as exc:
        destination.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail=f"工程文件无法打开：{exc}") from exc
    return workspace.bootstrap()


@app.post("/api/project/save")
def save_project(payload: dict[str, Any] | None = Body(default=None)) -> dict[str, str]:
    filename = None if payload is None else payload.get("filename")
    path = workspace.save(filename)
    return {"filename": path.name, "download_url": f"/api/project/download/{path.name}"}


@app.get("/api/project/download/{filename}")
def download_project(filename: str):
    safe_name = Path(filename).name
    path = WORKSPACE_DIR / safe_name
    if not path.exists():
        raise HTTPException(status_code=404, detail="工程文件不存在")
    return FileResponse(path, filename=path.name, media_type="application/zip")

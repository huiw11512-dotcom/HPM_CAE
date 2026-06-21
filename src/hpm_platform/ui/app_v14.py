"""HPM 数字化电磁算法 CAE V1.4 全中文 Bootstrap 工作台。"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from jinja2 import Environment
from pydantic import BaseModel, Field
from starlette.templating import Jinja2Templates

from hpm_platform.physics.field_backends import backend_choices
from hpm_platform.ui.v14_service import V14WorkbenchService

PACKAGE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = PACKAGE_DIR.parents[2]
STATIC_DIR = PACKAGE_DIR / "static_v14"
TEMPLATE_DIR = PACKAGE_DIR / "templates_v14"
DEFAULT_PROJECT = PROJECT_ROOT / "configs" / "cae_project_v14.yaml"

SOLVER_CHOICES = [
    ("多焦点相位共轭", "Point-Focus"),
    ("对象平衡区域最小二乘", "Region-LS"),
    ("名义区域梯度赋形", "Nominal-PGMS"),
    ("场景鲁棒区域赋形", "Robust-PGMS"),
    ("多对象约束赋形", "Constrained-MO-PGMS"),
]


class SolveRequest(BaseModel):
    backend: str = "hybrid_scene"
    solver_method: str = "Constrained-MO-PGMS"
    direct_scale: float = Field(0.8, ge=0.0, le=5.0)
    reflection_scale: float = Field(0.6, ge=0.0, le=5.0)
    cavity_scale: float = Field(0.8, ge=0.0, le=5.0)
    fast: bool = True


class ValidityRequest(BaseModel):
    backend: str = "hybrid_scene"


class CompareRequest(BaseModel):
    backends: list[str] | None = None


class CalibrationRequest(BaseModel):
    reference_backend: str = "hybrid_scene"
    candidate_backend: str = "hybrid_scene"
    reference_scales: tuple[float, float, float] = (0.86, 0.72, 0.93)
    initial_scales: tuple[float, float, float] = (0.50, 0.40, 0.40)
    samples_per_axis: int = Field(21, ge=9, le=81)
    noise_percent: float = Field(0.25, ge=0.0, le=10.0)


def create_app(project_path: str | Path | None = None) -> FastAPI:
    project_file = Path(project_path) if project_path else DEFAULT_PROJECT
    service = V14WorkbenchService(project_file)
    app = FastAPI(
        title="HPM 数字化电磁算法 CAE V1.4",
        description="全中文、本地离线、归一化阵列算法与降阶传播模型工作台",
        version="1.4.0",
        docs_url="/接口文档",
        redoc_url=None,
    )
    app.state.service = service
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
    templates = Jinja2Templates(directory=TEMPLATE_DIR)
    templates.env.policies["json.dumps_kwargs"] = {"ensure_ascii": False}

    @app.get("/", response_class=HTMLResponse)
    async def index(request: Request):
        project = service.project
        return templates.TemplateResponse(
            request=request,
            name="index.html",
            context={
                "backend_choices": backend_choices(),
                "solver_choices": SOLVER_CHOICES,
                "current_backend": project.propagation.backend,
                "current_solver": project.solver.method,
                "direct_scale": project.propagation.direct_path_scale,
                "reflection_scale": project.propagation.reflection_scale,
                "cavity_scale": project.propagation.cavity_scale,
                "illustrations": [
                    {"title": "全链路数字孪生架构", "png": "img/01_全链路数字孪生架构图.png", "svg": "img/01_全链路数字孪生架构图.svg"},
                    {"title": "混合传播后端机理", "png": "img/02_混合传播后端机理图.png", "svg": "img/02_混合传播后端机理图.svg"},
                    {"title": "传播后端参数标定闭环", "png": "img/03_传播后端参数标定闭环图.png", "svg": "img/03_传播后端参数标定闭环图.svg"},
                ],
            },
        )

    @app.get("/api/health")
    async def health() -> dict[str, Any]:
        return {"状态": "正常", "平台版本": "1.4.0", "工程": service.project.meta.name}

    @app.get("/api/overview")
    async def overview() -> dict[str, Any]:
        try:
            return service.overview_payload()
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"总览计算失败：{exc}") from exc

    @app.post("/api/solve")
    async def solve(payload: SolveRequest) -> dict[str, Any]:
        try:
            return service.solve_payload(**payload.model_dump())
        except Exception as exc:
            raise HTTPException(status_code=400, detail=f"静态求解失败：{exc}") from exc

    @app.post("/api/validity")
    async def validity(payload: ValidityRequest) -> dict[str, Any]:
        try:
            return service.validity_payload(payload.backend)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=f"适用性诊断失败：{exc}") from exc

    @app.post("/api/compare")
    async def compare(payload: CompareRequest) -> dict[str, Any]:
        try:
            return service.compare_payload(payload.backends)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=f"传播后端对比失败：{exc}") from exc

    @app.post("/api/calibrate")
    async def calibrate(payload: CalibrationRequest) -> dict[str, Any]:
        try:
            data = payload.model_dump()
            data["reference_scales"] = tuple(data["reference_scales"])
            data["initial_scales"] = tuple(data["initial_scales"])
            return service.calibration_payload(**data)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=f"参数标定失败：{exc}") from exc

    return app


app = create_app()

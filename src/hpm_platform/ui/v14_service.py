"""V1.4 Bootstrap 工作台的业务服务层。"""
from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import json
import threading
import time
from typing import Any

import numpy as np
import pandas as pd
import plotly.graph_objects as go

from hpm_platform.physics.field_backends import backend_choices, get_field_backend
from hpm_platform.ui.backend_explorer import (
    BackendComparisonResult,
    make_backend_gallery,
    make_backend_metrics_figure,
    run_backend_comparison,
)
from hpm_platform.ui.figures import (
    make_constraint_margin_figure,
    make_field_figure,
    make_object_metrics_figure,
    make_scene_figure,
    make_weights_figure,
)
from hpm_platform.ui.project_model import CAEProject
from hpm_platform.ui.quick_solver import CAESolveResult, solve_project
from hpm_platform.validation.backend_calibration import (
    CalibrationResult,
    calibrate_backend_scales,
    generate_reference_samples,
)
from hpm_platform.validation.model_validity import ValidityReport, assess_model_validity
from hpm_platform.validation.visualization import (
    make_calibration_field_figure,
    make_calibration_overview,
    make_validity_figure,
)


def _figure_payload(figure: go.Figure) -> dict[str, Any]:
    return json.loads(figure.to_json())


def _finite(value: Any, digits: int = 4) -> Any:
    if isinstance(value, (np.floating, float)):
        return round(float(value), digits) if np.isfinite(value) else None
    if isinstance(value, (np.integer, int)):
        return int(value)
    if isinstance(value, np.bool_):
        return bool(value)
    return value


def _frame_records(frame: pd.DataFrame) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for row in frame.to_dict(orient="records"):
        output.append({str(key): _finite(value) for key, value in row.items()})
    return output

SOLVER_LABELS = {
    "Point-Focus": "多焦点相位共轭",
    "Region-LS": "对象平衡区域最小二乘",
    "Nominal-PGMS": "名义区域梯度赋形",
    "Robust-PGMS": "场景鲁棒区域赋形",
    "Constrained-MO-PGMS": "多对象约束赋形",
}

OBJECT_COLUMN_LABELS = {
    "object_type": "对象类型",
    "object_id": "对象标识",
    "name": "名称",
    "priority": "优先级",
    "setpoint_or_cap": "设定值或上限",
    "mean_amplitude": "平均幅度",
    "rmse_percent": "RMSE/%",
    "coverage_percent": "覆盖率/%",
    "p95_deviation_percent": "P95偏差/%",
    "p95_db": "P95/dB",
    "peak_db": "峰值/dB",
    "limit_db": "上限/dB",
    "violation_db": "超限量/dB",
    "success": "通过",
}


def _localized_object_records(frame: pd.DataFrame) -> list[dict[str, Any]]:
    data = frame.rename(columns=OBJECT_COLUMN_LABELS).copy()
    if "对象类型" in data.columns:
        data["对象类型"] = data["对象类型"].map({"target": "目标区", "protected": "保护区"}).fillna(data["对象类型"])
    return _frame_records(data)


def _localized_field_figure(result: CAESolveResult) -> go.Figure:
    figure = make_field_figure(result)
    method = str(result.project.solver.method)
    label = SOLVER_LABELS.get(method, method)
    if figure.layout.title and figure.layout.title.text:
        figure.update_layout(title_text=str(figure.layout.title.text).replace(method, label))
    return figure


class V14WorkbenchService:
    """Thread-safe in-process service used by the local FastAPI UI."""

    def __init__(self, project_path: str | Path):
        self.project_path = Path(project_path)
        self.project = CAEProject.load_yaml(self.project_path)
        self._lock = threading.RLock()
        self._result: CAESolveResult | None = None
        self._comparison: BackendComparisonResult | None = None
        self._calibration: CalibrationResult | None = None
        self._validity: ValidityReport | None = None
        self.logs: list[str] = []

    def _append_log(self, message: str) -> None:
        stamp = time.strftime("%H:%M:%S")
        self.logs.append(f"[{stamp}] {message}")
        self.logs = self.logs[-200:]

    @staticmethod
    def _quick_project(project: CAEProject) -> CAEProject:
        samples = min(int(project.plane.samples), 61)
        if samples % 2 == 0:
            samples -= 1
        return replace(
            project,
            plane=replace(project.plane, samples=max(samples, 31)),
            solver=replace(
                project.solver,
                iterations=min(int(project.solver.iterations), 110),
                target_samples=min(int(project.solver.target_samples), 180),
                outside_samples=min(int(project.solver.outside_samples), 420),
                uncertainty_scenarios=min(int(project.solver.uncertainty_scenarios), 3),
            ),
        )

    def _update_project(
        self,
        *,
        backend: str | None = None,
        solver_method: str | None = None,
        direct_scale: float | None = None,
        reflection_scale: float | None = None,
        cavity_scale: float | None = None,
    ) -> CAEProject:
        project = self.project
        propagation = project.propagation
        if backend is not None or any(item is not None for item in (direct_scale, reflection_scale, cavity_scale)):
            propagation = replace(
                propagation,
                backend=str(backend or propagation.backend),
                direct_path_scale=float(direct_scale if direct_scale is not None else propagation.direct_path_scale),
                reflection_scale=float(reflection_scale if reflection_scale is not None else propagation.reflection_scale),
                cavity_scale=float(cavity_scale if cavity_scale is not None else propagation.cavity_scale),
            )
        solver = project.solver if solver_method is None else replace(project.solver, method=str(solver_method))
        return replace(project, propagation=propagation, solver=solver)

    def solve(
        self,
        *,
        backend: str | None = None,
        solver_method: str | None = None,
        direct_scale: float | None = None,
        reflection_scale: float | None = None,
        cavity_scale: float | None = None,
        fast: bool = True,
    ) -> CAESolveResult:
        with self._lock:
            candidate = self._update_project(
                backend=backend,
                solver_method=solver_method,
                direct_scale=direct_scale,
                reflection_scale=reflection_scale,
                cavity_scale=cavity_scale,
            )
            if fast:
                candidate = self._quick_project(candidate)
            self._append_log(
                f"开始静态求解：后端={get_field_backend(candidate.propagation.backend).display_name}，求解器={candidate.solver.method}"
            )
            result = solve_project(candidate)
            self.project = replace(
                self.project,
                propagation=candidate.propagation,
                solver=replace(self.project.solver, method=candidate.solver.method),
            )
            self._result = result
            self._validity = assess_model_validity(self.project, self.project.propagation.backend)
            self._append_log(
                f"静态求解完成：RMSE={result.metrics['target_rmse_percent']:.2f}%，最低覆盖率={result.metrics['minimum_target_coverage_percent']:.2f}%"
            )
            return result

    def ensure_result(self) -> CAESolveResult:
        with self._lock:
            if self._result is None:
                return self.solve(fast=True)
            return self._result

    def validity(self, backend: str | None = None) -> ValidityReport:
        with self._lock:
            report = assess_model_validity(self.project, backend or self.project.propagation.backend)
            self._validity = report
            self._append_log(
                f"完成模型适用性诊断：{report.backend_name}，得分={report.score:.1f}"
            )
            return report

    def compare(self, backends: list[str] | None = None) -> BackendComparisonResult:
        with self._lock:
            ids = backends or [value for _, value in backend_choices()]
            self._append_log(f"开始传播后端对比：{len(ids)} 个后端")
            comparison = run_backend_comparison(self._quick_project(self.project), ids, fast_mode=True)
            self._comparison = comparison
            self._append_log("传播后端对比完成")
            return comparison

    def calibrate(
        self,
        *,
        reference_backend: str = "hybrid_scene",
        candidate_backend: str = "hybrid_scene",
        reference_scales: tuple[float, float, float] = (0.86, 0.72, 0.93),
        initial_scales: tuple[float, float, float] = (0.50, 0.40, 0.40),
        samples_per_axis: int = 21,
        noise_percent: float = 0.25,
    ) -> CalibrationResult:
        with self._lock:
            self._append_log(
                f"开始参数标定：参考={get_field_backend(reference_backend).display_name}，待标定={get_field_backend(candidate_backend).display_name}"
            )
            samples = generate_reference_samples(
                self.project,
                reference_backend=reference_backend,
                reference_scales=reference_scales,
                samples_per_axis=int(samples_per_axis),
                noise_std_fraction=float(noise_percent) / 100.0,
                seed=self.project.meta.seed + 140,
            )
            result = calibrate_backend_scales(
                self.project,
                samples,
                candidate_backend=candidate_backend,
                initial_scales=initial_scales,
                maximum_evaluations=60,
            )
            self._calibration = result
            self._append_log(
                f"参数标定完成：相对RMSE {result.relative_rmse_before_percent:.2f}% → {result.relative_rmse_after_percent:.3f}%"
            )
            return result

    def overview_payload(self) -> dict[str, Any]:
        result = self.ensure_result()
        validity = self._validity or self.validity(result.project.propagation.backend)
        metrics = result.metrics
        cards = [
            {
                "标签": "目标区总体 RMSE",
                "数值": f"{float(metrics['target_rmse_percent']):.2f}%",
                "说明": "越低越好",
                "状态": "良好" if float(metrics["target_rmse_percent"]) <= 10 else "关注",
            },
            {
                "标签": "最低目标覆盖率",
                "数值": f"{float(metrics['minimum_target_coverage_percent']):.1f}%",
                "说明": "落入对象容差带的采样比例",
                "状态": "良好" if float(metrics["minimum_target_coverage_percent"]) >= 60 else "关注",
            },
            {
                "标签": "区外峰值",
                "数值": f"{float(metrics['peak_outside_db']):.2f} dB",
                "说明": f"限制 {float(metrics['outside_peak_limit_db']):.2f} dB",
                "状态": "通过" if float(metrics["outside_peak_violation_db"]) <= 0 else "超限",
            },
            {
                "标签": "模型适用性",
                "数值": f"{validity.score:.1f} 分",
                "说明": validity.level,
                "状态": "良好" if validity.score >= 90 else "关注",
            },
        ]
        return {
            "平台版本": "1.4.0",
            "工程名称": self.project.meta.name,
            "模型边界": self.project.model_scope,
            "当前后端": get_field_backend(result.project.propagation.backend).display_name,
            "当前求解器": result.project.solver.method,
            "联合判据": bool(metrics["control_success"]),
            "卡片": cards,
            "对象指标": _localized_object_records(result.object_metrics_frame()),
            "适用性摘要": validity.as_dict(),
            "图形": {
                "场景": _figure_payload(make_scene_figure(result.project)),
                "场分布": _figure_payload(_localized_field_figure(result)),
                "对象指标": _figure_payload(make_object_metrics_figure(result)),
                "约束裕量": _figure_payload(make_constraint_margin_figure(result)),
                "阵元权值": _figure_payload(make_weights_figure(result)),
            },
            "运行日志": list(self.logs[-40:]),
        }

    def solve_payload(self, **kwargs: Any) -> dict[str, Any]:
        result = self.solve(**kwargs)
        validity = self._validity or self.validity(result.project.propagation.backend)
        return {
            "成功": True,
            "提示": "静态求解完成",
            "指标": {str(k): _finite(v) for k, v in result.metrics.items()},
            "对象指标": _localized_object_records(result.object_metrics_frame()),
            "适用性得分": round(validity.score, 2),
            "图形": {
                "场景": _figure_payload(make_scene_figure(result.project)),
                "场分布": _figure_payload(_localized_field_figure(result)),
                "对象指标": _figure_payload(make_object_metrics_figure(result)),
                "约束裕量": _figure_payload(make_constraint_margin_figure(result)),
                "阵元权值": _figure_payload(make_weights_figure(result)),
            },
            "运行日志": list(self.logs[-40:]),
        }

    def validity_payload(self, backend: str | None = None) -> dict[str, Any]:
        report = self.validity(backend)
        return {
            "成功": True,
            "报告": report.as_dict(),
            "图形": _figure_payload(make_validity_figure(report)),
            "运行日志": list(self.logs[-40:]),
        }

    def compare_payload(self, backends: list[str] | None = None) -> dict[str, Any]:
        comparison = self.compare(backends)
        return {
            "成功": True,
            "记录": _frame_records(comparison.records),
            "图形": {
                "场图对比": _figure_payload(make_backend_gallery(comparison)),
                "指标对比": _figure_payload(make_backend_metrics_figure(comparison)),
            },
            "运行日志": list(self.logs[-40:]),
        }

    def calibration_payload(self, **kwargs: Any) -> dict[str, Any]:
        result = self.calibrate(**kwargs)
        return {
            "成功": bool(result.success),
            "摘要": result.summary_dict(),
            "图形": {
                "标定总览": _figure_payload(make_calibration_overview(result)),
                "空间复核": _figure_payload(make_calibration_field_figure(result)),
            },
            "运行日志": list(self.logs[-40:]),
        }

"""Configuration-driven live workflow executor for HPM-CAE V1.2."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from html import escape
from pathlib import Path
import json
import shutil
import time
from typing import Callable, Iterable

import numpy as np
import pandas as pd

from hpm_platform.ui.figures import make_field_figure, make_metric_cards_html, make_scene_figure
from hpm_platform.ui.live_chain import LivePerceptionResult, LiveProtectionResult, run_live_perception, run_live_protection
from hpm_platform.ui.live_figures import (
    make_live_metric_cards,
    make_perception_comparison,
    make_perception_diagnostics,
    make_perception_spectrum,
    make_protection_comparison,
    make_protection_map,
)
from hpm_platform.ui.object_manager import object_tree_html
from hpm_platform.ui.project_model import CAEProject
from hpm_platform.ui.quick_solver import CAESolveResult, solve_project
from hpm_platform.ui.task_graph import GRAPH

LogCallback = Callable[[str], None] | None


@dataclass(frozen=True)
class WorkflowExecutionResult:
    project: CAEProject
    selected_nodes: tuple[str, ...]
    statuses: dict[str, str]
    perception: LivePerceptionResult | None
    protection: LiveProtectionResult | None
    field_control: CAESolveResult | None
    effect_metrics: dict[str, float | bool]
    log_lines: tuple[str, ...]
    output_folder: Path | None = None
    report_path: Path | None = None
    archive_path: Path | None = None

    def task_frame(self) -> pd.DataFrame:
        frame = GRAPH.compile_plan(self.selected_nodes)
        mapping = {GRAPH.by_id[node_id].label: self.statuses.get(node_id, "idle") for node_id in GRAPH.by_id}
        frame["状态"] = frame["任务"].map(mapping).fillna(frame["状态"])
        return frame


def _effect_proxy(
    perception: LivePerceptionResult | None,
    protection: LiveProtectionResult | None,
    field: CAESolveResult | None,
) -> dict[str, float | bool]:
    if perception is None or protection is None or field is None:
        return {}
    pm = perception.metrics; rm = protection.metrics; fm = field.metrics
    sensing_quality = float(np.exp(-float(pm["rmse_deg"]) / 2.0))
    sinr_margin = float(np.clip((float(rm["output_sinr_db"]) - 0.0) / 12.0, 0.0, 1.0))
    null_margin = float(np.clip((-float(rm["worst_true_response_db"]) - 25.0) / 20.0, 0.0, 1.0))
    receive_quality = float(np.sqrt(sinr_margin * null_margin))
    field_uniformity = float(np.clip(1.0 - float(fm["target_rmse_percent"]) / 20.0, 0.0, 1.0))
    field_coverage = float(np.clip(float(fm["target_coverage_percent"]) / 80.0, 0.0, 1.0))
    field_quality = float(np.sqrt(field_uniformity * field_coverage))
    protected_margin = float(np.clip((-float(fm["protected_p95_db"]) - 8.0) / 12.0, 0.0, 1.0))
    mission_score = float((sensing_quality * receive_quality * field_quality * max(protected_margin, 1e-6)) ** 0.25)
    available = bool(
        pm["resolved_within_2deg"]
        and rm["protection_success"]
        and fm["control_success"]
        and mission_score >= 0.62
    )
    return {
        "sensing_quality": sensing_quality,
        "receive_protection_quality": receive_quality,
        "field_control_quality": field_quality,
        "protected_margin_score": protected_margin,
        "normalized_mission_score": mission_score,
        "full_chain_available": available,
    }


def execute_workflow(
    project: CAEProject,
    selected: Iterable[str] | None = None,
    *,
    log_callback: LogCallback = None,
    export_root: str | Path | None = None,
) -> WorkflowExecutionResult:
    ordered = GRAPH.closure(selected or project.workflow.enabled_nodes)
    statuses = {node_id: "queued" for node_id in ordered}
    lines: list[str] = []
    perception: LivePerceptionResult | None = None
    protection: LiveProtectionResult | None = None
    field: CAESolveResult | None = None
    effects: dict[str, float | bool] = {}

    def emit(message: str) -> None:
        stamp = datetime.now(timezone.utc).strftime("%H:%M:%S")
        line = f"[{stamp}] {message}"
        lines.append(line)
        if log_callback is not None:
            log_callback(line)

    emit("workflow compiled: " + " → ".join(GRAPH.by_id[item].label for item in ordered))
    try:
        for node_id in ordered:
            statuses[node_id] = "running"
            t0 = time.perf_counter()
            if node_id == "scene":
                project.validate_geometry()
                emit(f"scene validated: {len(project.targets)} target(s), {len(project.protected_zones)} protected zone(s), {len(project.active_interferers)} emitter(s)")
            elif node_id == "signal":
                # Signal generation is executed inside the perception node so
                # one deterministic snapshot matrix is shared by all estimators.
                emit("signal node armed: coherent paths, mismatch and local faults")
            elif node_id == "perception":
                perception = run_live_perception(project)
                emit(f"perception: RMSE={float(perception.metrics['rmse_deg']):.3f}°, resolved={perception.metrics['resolved_within_2deg']}")
            elif node_id == "protection":
                protection = run_live_protection(project, perception)
                emit(f"protection: SINR={float(protection.metrics['output_sinr_db']):.2f} dB, worst={float(protection.metrics['worst_true_response_db']):.2f} dB")
            elif node_id == "field_control":
                field = solve_project(project)
                emit(f"field control: RMSE={float(field.metrics['target_rmse_percent']):.2f}%, coverage={float(field.metrics['target_coverage_percent']):.1f}%")
            elif node_id == "dynamic_timeline":
                # The dedicated timeline tab executes the multi-frame solver;
                # the workflow node records that the configured controller is available.
                emit(f"timeline controller ready: {project.motion.controller} ({project.motion.frames} frames)")
            elif node_id == "effect_proxy":
                effects = _effect_proxy(perception, protection, field)
                if not effects:
                    raise RuntimeError("effect proxy requires perception, protection and field-control outputs")
                emit(f"normalized full-chain score={float(effects['normalized_mission_score']):.3f}, available={effects['full_chain_available']}")
            elif node_id == "batch_sweep":
                emit("persistent queue node ready; cases are submitted from the queue tab")
            elif node_id == "report":
                emit("report node will archive all upstream artifacts after execution")
            statuses[node_id] = "completed"
            emit(f"{GRAPH.by_id[node_id].label} completed in {1000.0*(time.perf_counter()-t0):.1f} ms")
    except Exception as exc:
        statuses[node_id] = "failed"
        emit(f"FAILED at {GRAPH.by_id[node_id].label}: {type(exc).__name__}: {exc}")
        raise

    result = WorkflowExecutionResult(project, ordered, statuses, perception, protection, field, effects, tuple(lines))
    if export_root is not None and "report" in ordered:
        folder, report, archive = export_workflow(result, export_root)
        result = WorkflowExecutionResult(project, ordered, statuses, perception, protection, field, effects, tuple(lines), folder, report, archive)
    return result


def _table(frame: pd.DataFrame) -> str:
    return frame.to_html(index=False, border=0, classes="data-table", float_format=lambda value: f"{value:.4g}")


def export_workflow(result: WorkflowExecutionResult, root: str | Path) -> tuple[Path, Path, Path]:
    root_path = Path(root); root_path.mkdir(parents=True, exist_ok=True)
    run_id = datetime.now(timezone.utc).strftime("RUN-%Y%m%d-%H%M%S-") + result.project.slug[:20]
    folder = root_path / run_id
    suffix = 1
    while folder.exists():
        suffix += 1; folder = root_path / f"{run_id}-{suffix}"
    folder.mkdir(parents=True)
    result.project.save_yaml(folder / "project.yaml")
    (folder / "workflow_log.txt").write_text("\n".join(result.log_lines), encoding="utf-8")
    result.task_frame().to_csv(folder / "task_status.csv", index=False)
    payload = {"effect_proxy": result.effect_metrics}
    if result.perception is not None:
        payload["perception"] = result.perception.metrics
        result.perception.estimates_frame().to_csv(folder / "perception_estimates.csv", index=False)
        result.perception.comparison_frame().to_csv(folder / "perception_comparison.csv", index=False)
        np.savez_compressed(folder / "perception_arrays.npz", spectrum=result.perception.spectrum, covariance=result.perception.covariance, reliability=result.perception.sensor_reliability)
    if result.protection is not None:
        payload["protection"] = result.protection.metrics
        result.protection.comparison_frame().to_csv(folder / "protection_comparison.csv", index=False)
        np.savez_compressed(folder / "protection_arrays.npz", weights=result.protection.weights, response_db=result.protection.response_db, covariance=result.protection.covariance)
    if result.field_control is not None:
        payload["field_control"] = result.field_control.metrics
        np.savez_compressed(folder / "field_control_arrays.npz", x_lambda=result.field_control.x_lambda, y_lambda=result.field_control.y_lambda, field=result.field_control.field, desired_weights=result.field_control.desired_weights, drive_weights=result.field_control.drive_weights, actual_weights=result.field_control.actual_weights)
    (folder / "metrics.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    figures = [("场景与对象", make_scene_figure(result.project))]
    if result.perception is not None:
        figures += [("二维空间谱", make_perception_spectrum(result.perception)), ("感知诊断", make_perception_diagnostics(result.perception)), ("感知对比", make_perception_comparison(result.perception))]
    if result.protection is not None:
        figures += [("接收响应", make_protection_map(result.protection)), ("防护对比", make_protection_comparison(result.protection))]
    if result.field_control is not None:
        figures += [("空间场分布", make_field_figure(result.field_control))]
    plots = []
    for index, (title, figure) in enumerate(figures):
        plots.append(f"<section><h2>{escape(title)}</h2>" + figure.to_html(full_html=False, include_plotlyjs="inline" if index == 0 else False, config={"displaylogo": False, "responsive": True}) + "</section>")
    metrics_html = make_live_metric_cards(result.perception, result.protection)
    if result.field_control is not None:
        metrics_html += make_metric_cards_html(result.field_control)
    effect_table = _table(pd.DataFrame([result.effect_metrics])) if result.effect_metrics else "<p>未运行。</p>"
    report = folder / "HPM_CAE_V12_full_chain_report.html"
    report.write_text(
        "<!doctype html><html lang='zh-CN'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'><title>HPM-CAE V1.2 Full Chain</title><style>"
        "body{margin:0;background:#07101d;color:#e7eef9;font-family:Inter,Segoe UI,Microsoft YaHei,sans-serif}main{max-width:1500px;margin:auto;padding:28px 4vw}header{padding:18px 0;border-bottom:1px solid #26354d}h1{margin:0}p,small{color:#91a2bb}section{background:#0d1828;border:1px solid #26354d;border-radius:13px;padding:16px;margin:16px 0}.metric-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:8px}.metric-card{background:#091422;border:1px solid #26354d;border-radius:9px;padding:10px}.metric-card span,.metric-card small{display:block;color:#91a2bb}.metric-card strong{font-size:20px;display:block;margin:5px 0}.metric-card.ok{border-color:#4ee0a5}.metric-card.warn{border-color:#ffc857}.object-row{display:grid;grid-template-columns:20px 25px minmax(160px,1fr) 90px 2fr;gap:6px;padding:5px}.object-group{margin-top:9px;color:#35d8ff}.object-row code{color:#ab8cff}.object-row small{color:#91a2bb}.data-table{width:100%;border-collapse:collapse}.data-table th,.data-table td{padding:8px;border-bottom:1px solid #26354d;text-align:left}.scope{border-left:4px solid #ffc857;padding:10px;background:#091422}</style></head><body><main>"
        f"<header><h1>HPM-CAE V1.2 · 实时全链路报告</h1><p>{escape(result.project.meta.name)} · {datetime.now(timezone.utc).isoformat()}</p></header>"
        f"<section><h2>对象树</h2>{object_tree_html(result.project)}</section>"
        f"<section><h2>关键指标</h2>{metrics_html}</section>"
        f"<section><h2>归一化任务评价</h2>{effect_table}</section>"
        + "".join(plots)
        + f"<section><h2>任务状态</h2>{_table(result.task_frame())}</section>"
        + "<section class='scope'><b>模型边界</b><p>本报告仅包含波长尺度几何、归一化复场、相对接收响应和无量纲算法代理指标；不表示绝对源功率、具体设备阈值、实际毁伤概率或现实作用距离。</p></section>"
        + "</main></body></html>", encoding="utf-8"
    )
    archive = Path(shutil.make_archive(str(folder), "zip", root_dir=folder))
    return folder, report, archive

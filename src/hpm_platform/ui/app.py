"""HPM-CAE V1.0 local visual workbench.

The browser UI is defined from Python with Gradio and Plotly.  A custom HTML
canvas provides true drag editing while every persisted object and numerical
operation remains controlled by the Python project model.
"""
from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Any, Sequence
import traceback

import gradio as gr
import pandas as pd

from hpm_platform.ui.experiment_manager import (
    ExperimentDatabase,
    METRIC_LABELS,
    SWEEP_PARAMETERS,
    SweepSpec,
    export_sweep,
    make_sweep_figure,
    run_sweep,
)
from hpm_platform.ui.exporter import export_project_file, export_result_bundle
from hpm_platform.ui.figures import (
    make_convergence_figure,
    make_cut_figure,
    make_empty_result_figure,
    make_far_field_figure,
    make_field_figure,
    make_metric_cards_html,
    make_scene_figure,
    make_weights_figure,
)
from hpm_platform.ui.project_model import (
    ArraySpec,
    CAEProject,
    MotionSpec,
    ObservationPlaneSpec,
    ProjectMeta,
    ProtectedZoneSpec,
    SolverSpec,
    TargetRegionSpec,
    WorkflowSpec,
    default_project,
)
from hpm_platform.ui.quick_solver import CAESolveResult, solve_project
from hpm_platform.ui.scene_editor import EDITOR_CSS, EDITOR_HTML, EDITOR_JS, scene_editor_value
from hpm_platform.ui.task_graph import GRAPH, default_selection, make_task_graph_figure, node_choices
from hpm_platform.ui.timeline import (
    TimelineResult,
    export_timeline,
    make_timeline_animation,
    make_timeline_metrics_figure,
    make_trajectory_figure,
    run_timeline,
)

PROJECT_ROOT = Path(__file__).resolve().parents[3]
UI_ROOT = PROJECT_ROOT / "outputs_v10_ui"
UI_OUTPUT_ROOT = UI_ROOT / "runs"
UI_PROJECT_ROOT = UI_ROOT / "projects"
TIMELINE_ROOT = UI_ROOT / "timelines"
SWEEP_ROOT = UI_ROOT / "sweeps"
DATABASE_PATH = UI_ROOT / "experiments.sqlite3"
DATABASE = ExperimentDatabase(DATABASE_PATH)

PARAMETER_KEYS = [
    "project_name", "seed", "frequency_ghz", "nx", "ny", "spacing_x_lambda", "spacing_y_lambda",
    "z_lambda", "span_x_lambda", "span_y_lambda", "samples",
    "target_center_x", "target_center_y", "target_major", "target_minor", "target_rotation", "guard_scale",
    "protected_enabled", "protected_center_x", "protected_center_y", "protected_radius",
    "method", "target_amplitude", "outside_penalty", "outside_hinge", "iterations", "learning_rate",
    "uncertainty_scenarios", "gain_std_percent", "phase_std_deg", "registration_jitter",
    "pa_enabled", "dpd_enabled", "pa_saturation", "pa_smoothness", "pa_phase_deg",
    "motion_enabled", "motion_frames", "motion_dt", "motion_vx", "motion_vy", "motion_ax", "motion_ay",
    "motion_maneuver_amplitude", "motion_maneuver_period", "motion_delay", "motion_controller", "motion_samples",
]

CSS = r"""
:root{--cae-bg:#07101d;--cae-panel:#0d1828;--cae-panel2:#111f33;--cae-line:#26354d;--cae-text:#e7eef9;--cae-muted:#91a2bb;--cae-cyan:#35d8ff;--cae-amber:#ffc857;--cae-green:#4ee0a5;--cae-red:#ff6b7a;--cae-purple:#ab8cff}
.gradio-container{max-width:none!important;background:var(--cae-bg)!important;color:var(--cae-text)!important;font-family:Inter,'Segoe UI','Microsoft YaHei',sans-serif!important}footer{display:none!important}.contain{max-width:none!important}
#cae-topbar{background:linear-gradient(115deg,#0e2138,#07101d 72%);border-bottom:1px solid var(--cae-line);padding:14px 20px;margin:-16px -16px 12px!important}.cae-topbar-inner{display:flex;align-items:center;justify-content:space-between;gap:18px}.cae-brand{display:flex;align-items:center;gap:12px}.cae-logo{width:40px;height:40px;border-radius:11px;background:linear-gradient(145deg,var(--cae-cyan),#4276ff);box-shadow:0 0 24px rgba(53,216,255,.23);display:flex;align-items:center;justify-content:center;font-weight:900;color:#03111b}.cae-title{font-size:19px;font-weight:780}.cae-sub{font-size:12px;color:var(--cae-muted);margin-top:2px}.cae-badges{display:flex;gap:8px;flex-wrap:wrap}.cae-badge{font-size:10px;padding:5px 9px;border-radius:999px;border:1px solid rgba(53,216,255,.32);background:rgba(53,216,255,.08);color:var(--cae-cyan)}
#workbench-row{gap:10px!important;align-items:stretch!important}.cae-sidebar{background:var(--cae-panel)!important;border:1px solid var(--cae-line)!important;border-radius:10px!important;padding:9px!important;box-shadow:0 14px 36px rgba(0,0,0,.18)}#viewport-panel{background:var(--cae-panel)!important;border:1px solid var(--cae-line)!important;border-radius:10px!important;padding:8px!important;box-shadow:0 14px 36px rgba(0,0,0,.18)}
.cae-section-title{font-size:11px;text-transform:uppercase;letter-spacing:1.4px;color:var(--cae-muted);margin:2px 0 8px}.tree{font-size:13px;line-height:1.85;color:var(--cae-text);padding:4px 5px 8px}.tree .node{display:flex;align-items:center;gap:7px;padding:2px 5px;border-radius:5px}.tree .node.active{background:rgba(53,216,255,.09);color:var(--cae-cyan)}.tree .indent{padding-left:20px}.tree .dot{width:7px;height:7px;border-radius:50%;background:var(--cae-green);box-shadow:0 0 8px rgba(78,224,165,.55)}.tree .dot.adapter{background:var(--cae-amber);box-shadow:none}
.cae-sidebar label,.cae-sidebar span{font-size:12px!important}.cae-sidebar input,.cae-sidebar textarea,.cae-sidebar select{background:#091422!important;color:var(--cae-text)!important;border-color:var(--cae-line)!important}button.primary{background:linear-gradient(135deg,#147fab,#2b65db)!important;border:none!important;color:white!important;box-shadow:0 6px 18px rgba(35,116,215,.26)!important}button.secondary{background:var(--cae-panel2)!important;color:var(--cae-text)!important;border-color:var(--cae-line)!important}#run-button{font-weight:750!important;min-height:44px!important}
.cae-status{border:1px solid var(--cae-line);border-left:4px solid var(--cae-cyan);background:#091422;border-radius:8px;padding:10px 12px;font-size:12px;line-height:1.55}.cae-status.ok{border-left-color:var(--cae-green)}.cae-status.warn{border-left-color:var(--cae-amber)}.cae-status.error{border-left-color:var(--cae-red)}.cae-status strong{display:block;font-size:13px;margin-bottom:2px}.metric-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:7px}.metric-card{background:#091422;border:1px solid var(--cae-line);border-radius:8px;padding:9px;min-width:0}.metric-card span{display:block;color:var(--cae-muted);font-size:10px!important}.metric-card strong{display:block;font-size:17px;margin:4px 0;color:var(--cae-text);white-space:nowrap}.metric-card small{display:block;color:var(--cae-muted);font-size:9px}.metric-card.status.ok{border-color:rgba(78,224,165,.45)}.metric-card.status.ok strong{color:var(--cae-green)}.metric-card.status.warn{border-color:rgba(255,200,87,.45)}.metric-card.status.warn strong{color:var(--cae-amber)}
#viewport-tabs .tab-nav{background:#091422!important;border:1px solid var(--cae-line)!important;border-radius:8px!important;padding:4px!important}#viewport-tabs button{font-size:11px!important}.plot-container{border-radius:8px;overflow:hidden}#task-console{background:var(--cae-panel)!important;border:1px solid var(--cae-line)!important;border-radius:10px!important;margin-top:9px!important}.pipeline{display:flex;align-items:stretch;gap:7px;overflow-x:auto;padding:8px 2px}.stage{min-width:135px;flex:1;background:#091422;border:1px solid var(--cae-line);border-radius:9px;padding:10px}.stage b{display:block;font-size:12px}.stage span{display:block;color:var(--cae-muted);font-size:9px;margin-top:4px}.stage.ready{border-top:3px solid var(--cae-green)}.stage.ui{border-top:3px solid var(--cae-cyan)}.arrow{display:flex;align-items:center;color:var(--cae-muted);font-size:18px}.scope-note{font-size:11px;color:var(--cae-muted);line-height:1.6;border:1px dashed var(--cae-line);border-radius:8px;padding:9px;margin-top:8px}.tab-note{color:var(--cae-muted);font-size:12px;line-height:1.65;background:#091422;border:1px solid var(--cae-line);border-radius:8px;padding:10px;margin-bottom:8px}.toolbar-row{background:#091422;border:1px solid var(--cae-line);border-radius:8px;padding:8px!important;margin-bottom:8px!important}
@media(max-width:1220px){#workbench-row{flex-direction:column!important}.cae-sidebar{min-width:100%!important}.metric-grid{grid-template-columns:repeat(3,minmax(0,1fr))}}
"""

HEADER_HTML = """
<div class="cae-topbar-inner"><div class="cae-brand"><div class="cae-logo">H</div><div><div class="cae-title">HPM-CAE Workbench <span style="color:#35d8ff">V1.0</span></div><div class="cae-sub">Drag geometry · dynamic timeline · task graph · experiment database</div></div></div><div class="cae-badges"><span class="cae-badge">LOCAL PYTHON</span><span class="cae-badge">DRAG EDITOR</span><span class="cae-badge">SQLITE EXPERIMENTS</span><span class="cae-badge">NORMALIZED MODE</span></div></div>
"""

PIPELINE_HTML = """
<div class="pipeline"><div class="stage ready"><b>① 感知</b><span>V0.3适配器</span></div><div class="arrow">›</div><div class="stage ready"><b>② 接收防护</b><span>V0.5适配器</span></div><div class="arrow">›</div><div class="stage ready"><b>③ 空间控场</b><span>静态 + 动态求解</span></div><div class="arrow">›</div><div class="stage ready"><b>④ 效应评价</b><span>归一化代理层</span></div><div class="arrow">›</div><div class="stage ui"><b>⑤ CAE工作台</b><span>建模 / 队列 / 报告</span></div></div>
"""


def _status(title: str, detail: str, kind: str = "ok") -> str:
    return f'<div class="cae-status {kind}"><strong>{title}</strong>{detail}</div>'


def _tree(project: CAEProject) -> str:
    return f"""<div class="cae-section-title">Project Navigator</div><div class="tree"><div class="node active">▾ 📁 {project.meta.name}</div><div class="indent"><div class="node"><span class="dot"></span> 阵列 · {project.array.nx}×{project.array.ny}</div><div class="node"><span class="dot"></span> 观察面 · {project.plane.samples}² @ {project.plane.z_lambda:g}λ</div><div class="node"><span class="dot"></span> 目标区 · ({project.target.center_x_lambda:.2f}, {project.target.center_y_lambda:.2f})λ</div><div class="node"><span class="dot"></span> 保护区 · {'启用' if project.protected_zone.enabled else '关闭'}</div><div class="node"><span class="dot"></span> 静态求解 · {project.solver.method}</div><div class="node"><span class="dot"></span> 动态任务 · {project.motion.controller} / {project.motion.frames}帧</div><div class="node"><span class="dot adapter"></span> 感知/防护 · 结果适配器</div></div></div>"""


def _project_from_values(values: Sequence[Any]) -> CAEProject:
    if len(values) != len(PARAMETER_KEYS):
        raise ValueError(f"expected {len(PARAMETER_KEYS)} parameters, got {len(values)}")
    p = dict(zip(PARAMETER_KEYS, values, strict=True))
    return CAEProject(
        meta=ProjectMeta(name=str(p["project_name"]), seed=int(p["seed"])),
        array=ArraySpec(nx=int(p["nx"]), ny=int(p["ny"]), frequency_ghz=float(p["frequency_ghz"]), spacing_x_lambda=float(p["spacing_x_lambda"]), spacing_y_lambda=float(p["spacing_y_lambda"])),
        plane=ObservationPlaneSpec(z_lambda=float(p["z_lambda"]), span_x_lambda=float(p["span_x_lambda"]), span_y_lambda=float(p["span_y_lambda"]), samples=int(p["samples"])),
        target=TargetRegionSpec(center_x_lambda=float(p["target_center_x"]), center_y_lambda=float(p["target_center_y"]), semi_major_lambda=float(p["target_major"]), semi_minor_lambda=float(p["target_minor"]), rotation_deg=float(p["target_rotation"]), guard_scale=float(p["guard_scale"])),
        protected_zone=ProtectedZoneSpec(enabled=bool(p["protected_enabled"]), center_x_lambda=float(p["protected_center_x"]), center_y_lambda=float(p["protected_center_y"]), radius_lambda=float(p["protected_radius"])),
        solver=SolverSpec(method=str(p["method"]), target_amplitude=float(p["target_amplitude"]), outside_penalty=float(p["outside_penalty"]), outside_hinge_amplitude=float(p["outside_hinge"]), iterations=int(p["iterations"]), learning_rate=float(p["learning_rate"]), uncertainty_scenarios=int(p["uncertainty_scenarios"]), gain_std_percent=float(p["gain_std_percent"]), phase_std_deg=float(p["phase_std_deg"]), registration_jitter_lambda=float(p["registration_jitter"]), pa_enabled=bool(p["pa_enabled"]), dpd_enabled=bool(p["dpd_enabled"]), pa_saturation_amplitude=float(p["pa_saturation"]), pa_smoothness=float(p["pa_smoothness"]), pa_maximum_phase_deg=float(p["pa_phase_deg"])),
        motion=MotionSpec(enabled=bool(p["motion_enabled"]), frames=int(p["motion_frames"]), dt_frames=float(p["motion_dt"]), velocity_x_lambda_per_frame=float(p["motion_vx"]), velocity_y_lambda_per_frame=float(p["motion_vy"]), acceleration_x_lambda_per_frame2=float(p["motion_ax"]), acceleration_y_lambda_per_frame2=float(p["motion_ay"]), maneuver_amplitude_lambda=float(p["motion_maneuver_amplitude"]), maneuver_period_frames=float(p["motion_maneuver_period"]), observation_delay_frames=int(p["motion_delay"]), controller=str(p["motion_controller"]), preview_samples=int(p["motion_samples"])),
        workflow=WorkflowSpec(),
    )


def _project_values(project: CAEProject) -> list[Any]:
    return [
        project.meta.name, project.meta.seed, project.array.frequency_ghz, project.array.nx, project.array.ny, project.array.spacing_x_lambda, project.array.spacing_y_lambda,
        project.plane.z_lambda, project.plane.span_x_lambda, project.plane.span_y_lambda, project.plane.samples,
        project.target.center_x_lambda, project.target.center_y_lambda, project.target.semi_major_lambda, project.target.semi_minor_lambda, project.target.rotation_deg, project.target.guard_scale,
        project.protected_zone.enabled, project.protected_zone.center_x_lambda, project.protected_zone.center_y_lambda, project.protected_zone.radius_lambda,
        project.solver.method, project.solver.target_amplitude, project.solver.outside_penalty, project.solver.outside_hinge_amplitude, project.solver.iterations, project.solver.learning_rate,
        project.solver.uncertainty_scenarios, project.solver.gain_std_percent, project.solver.phase_std_deg, project.solver.registration_jitter_lambda,
        project.solver.pa_enabled, project.solver.dpd_enabled, project.solver.pa_saturation_amplitude, project.solver.pa_smoothness, project.solver.pa_maximum_phase_deg,
        project.motion.enabled, project.motion.frames, project.motion.dt_frames, project.motion.velocity_x_lambda_per_frame, project.motion.velocity_y_lambda_per_frame,
        project.motion.acceleration_x_lambda_per_frame2, project.motion.acceleration_y_lambda_per_frame2, project.motion.maneuver_amplitude_lambda,
        project.motion.maneuver_period_frames, project.motion.observation_delay_frames, project.motion.controller, project.motion.preview_samples,
    ]


def _preset_project(name: str) -> CAEProject:
    project = default_project()
    if name == "快速预览 · 单点聚焦":
        return replace(project, meta=replace(project.meta, name="Quick Point Focus"), plane=replace(project.plane, samples=61), solver=replace(project.solver, method="Point-Focus", iterations=40, uncertainty_scenarios=1, pa_enabled=False, dpd_enabled=False), motion=replace(project.motion, enabled=False))
    if name == "动态机动 · 预测赋形":
        return replace(project, meta=replace(project.meta, name="Dynamic Maneuver Study"), motion=replace(project.motion, enabled=True, frames=24, velocity_x_lambda_per_frame=0.045, velocity_y_lambda_per_frame=0.012, maneuver_amplitude_lambda=0.28, observation_delay_frames=3, controller="Predictive-PGMS"))
    if name == "保护区优先 · 鲁棒赋形":
        return replace(project, meta=replace(project.meta, name="Protected-Zone Priority"), protected_zone=replace(project.protected_zone, radius_lambda=0.90), solver=replace(project.solver, outside_penalty=1.9, outside_hinge_amplitude=0.12, uncertainty_scenarios=7, iterations=460))
    if name == "非理想功放 · 无DPD":
        return replace(project, meta=replace(project.meta, name="PA Distortion Inspection"), solver=replace(project.solver, method="Nominal-PGMS", pa_enabled=True, dpd_enabled=False, pa_saturation_amplitude=0.82, pa_maximum_phase_deg=16.0))
    return project


def _preview_callback(*values: Any):
    try:
        project = _project_from_values(values)
        aperture_x = (project.array.nx - 1) * project.array.spacing_x_lambda
        aperture_y = (project.array.ny - 1) * project.array.spacing_y_lambda
        detail = f"几何有效：{project.array.nx*project.array.ny}阵元，孔径 {aperture_x:.2f}λ×{aperture_y:.2f}λ，动态轨迹 {project.motion.frames} 帧。"
        return make_scene_figure(project), scene_editor_value(project), project.to_dict(), _tree(project), _status("场景已同步", detail)
    except Exception as exc:
        return make_empty_result_figure("场景参数错误", str(exc)), scene_editor_value(default_project()), {"error": str(exc)}, _tree(default_project()), _status("参数校验失败", str(exc), "error")


def _save_callback(*values: Any):
    try:
        project = _project_from_values(values)
        path = export_project_file(project, UI_PROJECT_ROOT)
        return str(path), project.to_dict(), _status("项目已保存", f"{path.name} 可完整恢复静态、动态和任务图参数。")
    except Exception as exc:
        return None, {"error": str(exc)}, _status("保存失败", str(exc), "error")


def _solve_callback(*values: Any):
    try:
        project = _project_from_values(values)
        result = solve_project(project)
        run_dir, report, archive = export_result_bundle(result, UI_OUTPUT_ROOT)
        detail = f"{project.solver.method} 完成；RMSE {result.metrics['target_rmse_percent']:.2f}%，覆盖率 {result.metrics['target_coverage_percent']:.1f}%，{result.metrics['solver_runtime_ms']:.1f} ms。"
        return result, make_scene_figure(project), make_field_figure(result), make_cut_figure(result), make_far_field_figure(result), make_weights_figure(result), make_convergence_figure(result), result.metrics_frame(), make_metric_cards_html(result), "\n".join(result.log_lines)+f"\n[export] {archive.name}\n", project.to_dict(), _tree(project), str(run_dir/"project.yaml"), str(report), str(archive), _status("静态求解完成", detail, "ok" if result.metrics["control_success"] else "warn"), make_task_graph_figure(project.workflow.enabled_nodes, statuses={"scene":"completed","field_control":"completed","report":"completed"})
    except Exception as exc:
        error = "".join(traceback.format_exception_only(type(exc), exc)).strip(); empty = make_empty_result_figure("求解失败", error)
        return None, empty, empty, empty, empty, empty, empty, pd.DataFrame([{"指标":"错误","数值":error,"单位":""}]), "", traceback.format_exc(), {"error":error}, _tree(default_project()), None, None, None, _status("求解失败", error, "error"), make_task_graph_figure()


def _load_callback(path: str | None):
    if not path:
        raise gr.Error("请先选择 .yaml 项目文件")
    try:
        project = CAEProject.load_yaml(path)
        return (*_project_values(project), make_scene_figure(project), scene_editor_value(project), project.to_dict(), _tree(project), _status("项目已载入", Path(path).name))
    except Exception as exc:
        raise gr.Error(f"项目载入失败：{exc}")


def _preset_callback(name: str):
    project = _preset_project(name)
    return (*_project_values(project), make_scene_figure(project), scene_editor_value(project), project.to_dict(), _tree(project), _status("预设已应用", name))


def _editor_event_callback(evt: gr.EventData):
    def get(name: str, default: float = 0.0) -> float:
        return float(getattr(evt, name, default))
    return get("target_x"), get("target_y"), get("target_major", 1.0), get("target_minor", 0.6), get("target_rotation"), get("protected_x"), get("protected_y"), get("protected_radius", 0.7), _status("拖拽参数已写回", "目标区与保护区坐标已同步到Python项目模型。")


def _timeline_callback(*values: Any):
    try:
        project = _project_from_values(values)
        if not project.motion.enabled:
            raise ValueError("请先启用动态时间轴")
        result = run_timeline(project)
        report, archive = export_timeline(result, TIMELINE_ROOT)
        summary = pd.DataFrame([{"指标":k, "数值":v} for k,v in result.summary().items()])
        detail = f"{result.n_frames}帧完成；平均RMSE {result.summary()['mean_target_rmse_percent']:.2f}%，动态可用率 {result.summary()['availability_percent']:.1f}%。"
        return result, make_timeline_animation(result), make_timeline_metrics_figure(result), make_trajectory_figure(result), result.metrics, summary, "\n".join(result.log_lines), str(report), str(archive), _status("动态时间轴完成", detail, "ok"), make_task_graph_figure(project.workflow.enabled_nodes, statuses={"scene":"completed","field_control":"completed","dynamic_timeline":"completed","effect_proxy":"completed","report":"completed"})
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"; empty = make_empty_result_figure("动态任务失败", error)
        return None, empty, empty, empty, pd.DataFrame([{"error":error}]), pd.DataFrame([{"指标":"错误","数值":error}]), traceback.format_exc(), None, None, _status("动态任务失败", error, "error"), make_task_graph_figure()


def _sweep_callback(*args: Any):
    values = args[:len(PARAMETER_KEYS)]; sweep_values = args[len(PARAMETER_KEYS):]
    parameter, start, stop, points, replicates, metric, fast_mode = sweep_values
    try:
        project = _project_from_values(values)
        spec = SweepSpec(parameter=str(parameter), start=float(start), stop=float(stop), points=int(points), replicates=int(replicates), metric=str(metric), fast_mode=bool(fast_mode))
        result = run_sweep(project, spec, DATABASE)
        report, archive = export_sweep(result, SWEEP_ROOT)
        best = result.best_record(); detail = f"{len(result.records)}个任务完成；最佳 {METRIC_LABELS[spec.metric]}={float(best[spec.metric]):.4g} @ {float(best['parameter_value']):.4g}。"
        return result, make_sweep_figure(result), result.summary, result.records, "\n".join(result.log_lines), str(report), str(archive), DATABASE.history(), _status("批量试验完成", detail, "ok"), make_task_graph_figure(project.workflow.enabled_nodes, statuses={"scene":"completed","field_control":"completed","batch_sweep":"completed","report":"completed"})
    except Exception as exc:
        error=f"{type(exc).__name__}: {exc}"; empty=make_empty_result_figure("扫参失败",error)
        return None, empty, pd.DataFrame([{"error":error}]), pd.DataFrame([{"error":error}]), traceback.format_exc(), None, None, DATABASE.history(), _status("扫参失败",error,"error"), make_task_graph_figure()


def _compile_graph(selected: list[str] | None):
    try:
        selected = selected or []
        plan = GRAPH.compile_plan(selected)
        closure = GRAPH.closure(selected)
        adapters = sum(GRAPH.by_id[item].implementation == "adapter" for item in closure)
        return make_task_graph_figure(selected), plan, _status("任务图已编译", f"共 {len(closure)} 个节点，含 {adapters} 个既有结果适配器。")
    except Exception as exc:
        return make_task_graph_figure(), pd.DataFrame([{"错误":str(exc)}]), _status("任务图错误",str(exc),"error")


def _library_items(version: str) -> tuple[str, list[tuple[str,str]], str | None]:
    library = {
        "V0.3 感知识别": ("PAWR-MUSIC、FBSS、ESPRIT与失配敏感性。","outputs_v03_perception",["00_pawr_mechanism.png","04_pawr_music_spectrum.png","09b_rmse_vs_snr_zoom.png","15_ablation.png"],"perception_v03_report_standalone.html"),
        "V0.4 接收防护": ("DOA不确定条件下的宽零陷防护。","outputs_v04_protection",["00_cr_hybridnull_mechanism.png","02_cr_hybridnull_map.png","06_sinr_vs_drift.png","12_ablation_sinr.png"],"protection_v04_report_standalone.html"),
        "V0.7 动态控场": ("预测—协方差—反馈移动目标区赋形。","outputs_v07_dynamic_field_control",["00_pcf_rls_mechanism.png","05_pcf_rls_field_map.png","12_rmse_time_series.png","27_pcf_rls_dynamic_field.gif"],"dynamic_field_control_v07_report_standalone.html"),
        "V0.8 效应数字孪生": ("双参考系累积、概率代理与风险调整分配。","outputs_v08_effect_twin",["00_effect_twin_mechanism.png","06_pcf_rls_probability_map.png","20_strategy_risk_utility.png","29_ea_duty_dynamic_probability.gif"],"effect_twin_v08_report_standalone.html"),
    }
    description, folder, names, report_name = library[version]; root=PROJECT_ROOT/folder
    items=[(str(root/name),name) for name in names if (root/name).exists()]; report=root/report_name
    return f"### {version}\n\n{description}", items, str(report) if report.exists() else None


def build_app() -> gr.Blocks:
    initial_project=default_project(); initial_result=solve_project(initial_project)
    initial_scene=make_scene_figure(initial_project); initial_field=make_field_figure(initial_result); initial_cut=make_cut_figure(initial_result); initial_far=make_far_field_figure(initial_result); initial_weights=make_weights_figure(initial_result); initial_convergence=make_convergence_figure(initial_result)
    empty_timeline=make_empty_result_figure("动态时间轴","设置运动参数后点击“运行动态时间轴”")
    empty_sweep=make_empty_result_figure("批量试验","选择变量范围后提交本地任务队列")
    sample_root=UI_ROOT/"sample_project"; sample_project_file=sample_root/"project.yaml"; sample_report=sample_root/"HPM_CAE_report.html"; sample_archive=UI_ROOT/"sample_project.zip"

    with gr.Blocks(title="HPM-CAE Workbench V1.0",fill_width=True,fill_height=True) as demo:
        result_state=gr.State(initial_result); timeline_state=gr.State(None); sweep_state=gr.State(None)
        gr.HTML(HEADER_HTML,elem_id="cae-topbar"); gr.HTML(PIPELINE_HTML)
        with gr.Row(elem_id="workbench-row"):
            with gr.Column(scale=23,min_width=285,elem_classes="cae-sidebar"):
                project_tree=gr.HTML(_tree(initial_project))
                with gr.Accordion("项目",open=True):
                    project_name=gr.Textbox(value=initial_project.meta.name,label="项目名称"); seed=gr.Number(value=initial_project.meta.seed,label="随机种子",precision=0)
                    preset=gr.Dropdown(choices=["论文基线 · 鲁棒区域赋形","快速预览 · 单点聚焦","动态机动 · 预测赋形","保护区优先 · 鲁棒赋形","非理想功放 · 无DPD"],value="论文基线 · 鲁棒区域赋形",label="场景预设"); apply_preset=gr.Button("应用预设",variant="secondary",size="sm")
                    load_file=gr.File(label="载入项目 YAML",file_types=[".yaml",".yml"],type="filepath"); load_button=gr.Button("读取项目",variant="secondary",size="sm")
                with gr.Accordion("阵列几何",open=True):
                    frequency=gr.Number(value=initial_project.array.frequency_ghz,label="频率 / GHz",minimum=.1,maximum=100,step=.1)
                    with gr.Row(): nx=gr.Slider(2,20,value=initial_project.array.nx,step=1,label="Nx"); ny=gr.Slider(2,20,value=initial_project.array.ny,step=1,label="Ny")
                    with gr.Row(): spacing_x=gr.Slider(.2,1.2,value=initial_project.array.spacing_x_lambda,step=.05,label="dx / λ"); spacing_y=gr.Slider(.2,1.2,value=initial_project.array.spacing_y_lambda,step=.05,label="dy / λ")
                with gr.Accordion("观察面与目标区",open=False):
                    z_lambda=gr.Slider(2,30,value=initial_project.plane.z_lambda,step=.5,label="z / λ")
                    with gr.Row(): span_x=gr.Slider(4,20,value=initial_project.plane.span_x_lambda,step=.5,label="x跨度 / λ"); span_y=gr.Slider(4,20,value=initial_project.plane.span_y_lambda,step=.5,label="y跨度 / λ")
                    samples=gr.Dropdown(choices=[41,51,61,81,101,121,151,181],value=initial_project.plane.samples,label="网格点数")
                    with gr.Row(): target_x=gr.Number(value=initial_project.target.center_x_lambda,label="目标 x / λ",step=.05); target_y=gr.Number(value=initial_project.target.center_y_lambda,label="目标 y / λ",step=.05)
                    with gr.Row(): target_major=gr.Number(value=initial_project.target.semi_major_lambda,label="长半轴 / λ",step=.05); target_minor=gr.Number(value=initial_project.target.semi_minor_lambda,label="短半轴 / λ",step=.05)
                    target_rotation=gr.Slider(-180,180,value=initial_project.target.rotation_deg,step=1,label="旋转 / °"); guard_scale=gr.Slider(1.05,2.5,value=initial_project.target.guard_scale,step=.05,label="过渡区尺度")
                with gr.Accordion("保护区",open=False):
                    protected_enabled=gr.Checkbox(value=initial_project.protected_zone.enabled,label="启用保护区")
                    with gr.Row(): protected_x=gr.Number(value=initial_project.protected_zone.center_x_lambda,label="x / λ",step=.05); protected_y=gr.Number(value=initial_project.protected_zone.center_y_lambda,label="y / λ",step=.05)
                    protected_radius=gr.Number(value=initial_project.protected_zone.radius_lambda,label="半径 / λ",minimum=.1,step=.05)
                with gr.Accordion("静态求解器",open=False):
                    method=gr.Dropdown(choices=list(SolverSpec.METHODS),value=initial_project.solver.method,label="算法"); target_amplitude=gr.Slider(.1,1,value=initial_project.solver.target_amplitude,step=.01,label="目标归一化幅度"); outside_penalty=gr.Slider(0,3,value=initial_project.solver.outside_penalty,step=.05,label="区外惩罚"); outside_hinge=gr.Slider(.02,.8,value=initial_project.solver.outside_hinge_amplitude,step=.01,label="区外铰链幅度"); iterations=gr.Slider(20,1000,value=initial_project.solver.iterations,step=20,label="迭代次数"); learning_rate=gr.Number(value=initial_project.solver.learning_rate,label="学习率",minimum=.001,maximum=.2,step=.005)
                with gr.Accordion("不确定性与功放",open=False):
                    uncertainty_scenarios=gr.Slider(1,16,value=initial_project.solver.uncertainty_scenarios,step=1,label="鲁棒场景数"); gain_std=gr.Slider(0,15,value=initial_project.solver.gain_std_percent,step=.5,label="增益误差 σ / %"); phase_std=gr.Slider(0,25,value=initial_project.solver.phase_std_deg,step=.5,label="相位误差 σ / °"); registration_jitter=gr.Slider(0,.4,value=initial_project.solver.registration_jitter_lambda,step=.01,label="配准抖动 σ / λ"); pa_enabled=gr.Checkbox(value=initial_project.solver.pa_enabled,label="启用归一化功放"); dpd_enabled=gr.Checkbox(value=initial_project.solver.dpd_enabled,label="启用DPD"); pa_saturation=gr.Slider(.5,1.5,value=initial_project.solver.pa_saturation_amplitude,step=.05,label="饱和幅度"); pa_smoothness=gr.Slider(1,8,value=initial_project.solver.pa_smoothness,step=.5,label="Rapp平滑度"); pa_phase=gr.Slider(0,30,value=initial_project.solver.pa_maximum_phase_deg,step=1,label="最大AM/PM / °")
                with gr.Accordion("动态时间轴",open=False):
                    motion_enabled=gr.Checkbox(value=initial_project.motion.enabled,label="启用动态任务"); motion_frames=gr.Slider(3,50,value=initial_project.motion.frames,step=1,label="帧数"); motion_dt=gr.Number(value=initial_project.motion.dt_frames,label="帧间隔",minimum=.1,step=.1)
                    with gr.Row(): motion_vx=gr.Number(value=initial_project.motion.velocity_x_lambda_per_frame,label="vx / λ·帧⁻¹",step=.005); motion_vy=gr.Number(value=initial_project.motion.velocity_y_lambda_per_frame,label="vy / λ·帧⁻¹",step=.005)
                    with gr.Row(): motion_ax=gr.Number(value=initial_project.motion.acceleration_x_lambda_per_frame2,label="ax",step=.002); motion_ay=gr.Number(value=initial_project.motion.acceleration_y_lambda_per_frame2,label="ay",step=.002)
                    motion_maneuver_amplitude=gr.Slider(0,.6,value=initial_project.motion.maneuver_amplitude_lambda,step=.02,label="横向机动幅度 / λ"); motion_maneuver_period=gr.Slider(4,40,value=initial_project.motion.maneuver_period_frames,step=1,label="机动周期 / 帧"); motion_delay=gr.Slider(0,10,value=initial_project.motion.observation_delay_frames,step=1,label="观测延迟 / 帧"); motion_controller=gr.Dropdown(choices=list(MotionSpec.CONTROLLERS),value=initial_project.motion.controller,label="动态控制器"); motion_samples=gr.Dropdown(choices=[31,41,51,61,71,81,91,101],value=initial_project.motion.preview_samples,label="动态网格")

            with gr.Column(scale=56,min_width=700,elem_id="viewport-panel"):
                with gr.Tabs(elem_id="viewport-tabs"):
                    with gr.Tab("拖拽建模"):
                        gr.HTML('<div class="tab-note">拖拽黄色目标中心、长短轴柄和紫色旋转柄；绿色控制保护区。松手后参数会写回Python对象并重新校验。</div>')
                        scene_editor=gr.HTML(value=scene_editor_value(initial_project),html_template=EDITOR_HTML,css_template=EDITOR_CSS,js_on_load=EDITOR_JS,apply_default_css=False,min_height=620)
                    with gr.Tab("三维场景"): scene_plot=gr.Plot(initial_scene,show_label=False)
                    with gr.Tab("静态场"):
                        with gr.Tabs():
                            with gr.Tab("场分布"): field_plot=gr.Plot(initial_field,show_label=False)
                            with gr.Tab("目标截线"): cut_plot=gr.Plot(initial_cut,show_label=False)
                            with gr.Tab("远场方向图"): far_plot=gr.Plot(initial_far,show_label=False)
                            with gr.Tab("阵元激励"): weights_plot=gr.Plot(initial_weights,show_label=False)
                            with gr.Tab("收敛"): convergence_plot=gr.Plot(initial_convergence,show_label=False)
                    with gr.Tab("动态时间轴"):
                        gr.HTML('<div class="tab-note">逐帧重新赋形；黄色是真实移动目标区，蓝色虚线是延迟观测后的赋形中心。播放控件和帧滑条都在图内。</div>')
                        timeline_run=gr.Button("▶ 运行动态时间轴",variant="primary")
                        timeline_animation=gr.Plot(empty_timeline,show_label=False)
                        with gr.Row(): timeline_metrics_plot=gr.Plot(empty_timeline,show_label=False); trajectory_plot=gr.Plot(empty_timeline,show_label=False)
                        timeline_summary=gr.Dataframe(pd.DataFrame(columns=["指标","数值"]),label="动态摘要",interactive=False,show_row_numbers=False)
                        with gr.Accordion("逐帧数据",open=False): timeline_table=gr.Dataframe(pd.DataFrame(),interactive=False,show_row_numbers=False,max_height=380)
                        timeline_log=gr.Code(value="尚未运行动态任务",language="shell",lines=8,max_lines=20,interactive=False,show_line_numbers=False)
                        with gr.Row(): timeline_report=gr.DownloadButton("下载动态报告 HTML",value=None); timeline_archive=gr.DownloadButton("下载动态结果 ZIP",value=None,variant="primary")
                    with gr.Tab("批量试验"):
                        gr.HTML('<div class="tab-note">本地任务队列将每个试验写入SQLite。快速模式会自动降低网格和迭代量，但保留重复试验与随机种子。</div>')
                        with gr.Row(elem_classes="toolbar-row"):
                            sweep_parameter=gr.Dropdown(choices=[(label,key) for key,label in SWEEP_PARAMETERS.items()],value="solver.phase_std_deg",label="扫参变量",scale=2); sweep_start=gr.Number(value=0,label="起点"); sweep_stop=gr.Number(value=12,label="终点"); sweep_points=gr.Slider(2,15,value=5,step=1,label="点数"); sweep_replicates=gr.Slider(1,8,value=2,step=1,label="重复")
                        with gr.Row(): sweep_metric=gr.Dropdown(choices=[(label,key) for key,label in METRIC_LABELS.items()],value="target_rmse_percent",label="观察指标"); sweep_fast=gr.Checkbox(value=True,label="快速模式"); sweep_run=gr.Button("提交批量任务",variant="primary")
                        sweep_plot=gr.Plot(empty_sweep,show_label=False); sweep_summary=gr.Dataframe(pd.DataFrame(),label="统计摘要",interactive=False,show_row_numbers=False); 
                        with gr.Accordion("全部运行记录",open=False): sweep_records=gr.Dataframe(pd.DataFrame(),interactive=False,show_row_numbers=False,max_height=380)
                        sweep_log=gr.Code(value="任务队列空闲",language="shell",lines=8,max_lines=20,interactive=False,show_line_numbers=False)
                        with gr.Row(): sweep_report=gr.DownloadButton("下载扫参报告 HTML",value=None); sweep_archive=gr.DownloadButton("下载扫参 ZIP",value=None,variant="primary"); db_download=gr.DownloadButton("下载实验数据库",value=str(DATABASE_PATH))
                        history_refresh=gr.Button("刷新实验历史",variant="secondary",size="sm"); history_table=gr.Dataframe(DATABASE.history(),label="SQLite历史",interactive=False,show_row_numbers=False,max_height=320)
                    with gr.Tab("任务图"):
                        gr.HTML('<div class="tab-note">选择任意下游节点后，依赖会自动补全。黄色节点是既有算法结果适配器，不伪装成当前UI中的实时重算模块。</div>')
                        task_selection=gr.CheckboxGroup(choices=node_choices(),value=default_selection(),label="任务节点"); compile_button=gr.Button("编译执行计划",variant="primary"); task_graph_plot=gr.Plot(make_task_graph_figure(),show_label=False); task_plan=gr.Dataframe(GRAPH.compile_plan(default_selection()),interactive=False,show_row_numbers=False)
                    with gr.Tab("结果库"):
                        library_choice=gr.Dropdown(choices=["V0.3 感知识别","V0.4 接收防护","V0.7 动态控场","V0.8 效应数字孪生"],value="V0.8 效应数字孪生",label="结果集"); initial_lib=_library_items("V0.8 效应数字孪生"); library_description=gr.Markdown(initial_lib[0]); library_gallery=gr.Gallery(initial_lib[1],columns=2,height=520,label="代表结果",object_fit="contain"); library_report=gr.File(value=initial_lib[2],label="完整报告",interactive=False)
                with gr.Accordion("任务监视器 / Solver Log",open=True,elem_id="task-console"):
                    solver_log=gr.Code(value="\n".join(initial_result.log_lines),language="shell",lines=8,max_lines=18,interactive=False,show_line_numbers=False,label="")

            with gr.Column(scale=21,min_width=285,elem_classes="cae-sidebar"):
                gr.HTML('<div class="cae-section-title">Static Solver</div>'); run_button=gr.Button("▶ 运行静态求解",variant="primary",elem_id="run-button")
                with gr.Row(): preview_button=gr.Button("同步场景",variant="secondary",size="sm"); save_button=gr.Button("保存项目",variant="secondary",size="sm")
                status_html=gr.HTML(_status("V1.0示例工程已载入",f"{initial_project.solver.method}：目标RMSE {initial_result.metrics['target_rmse_percent']:.2f}%。")); metric_cards=gr.HTML(make_metric_cards_html(initial_result)); metrics_table=gr.Dataframe(initial_result.metrics_frame(),label="关键指标",interactive=False,show_row_numbers=False,max_height=335,wrap=True)
                with gr.Accordion("项目快照",open=False): config_json=gr.JSON(initial_project.to_dict(),label="",open=False,show_indices=False,max_height=360)
                gr.HTML('<div class="cae-section-title" style="margin-top:10px">Artifacts</div>'); project_download=gr.DownloadButton("下载项目 YAML",value=str(sample_project_file) if sample_project_file.exists() else None,size="sm"); report_download=gr.DownloadButton("下载静态报告 HTML",value=str(sample_report) if sample_report.exists() else None,size="sm"); bundle_download=gr.DownloadButton("下载静态结果 ZIP",value=str(sample_archive) if sample_archive.exists() else None,variant="primary",size="sm"); gr.HTML('<div class="scope-note"><b>模型边界</b><br>只处理波长尺度几何、归一化复场和无量纲效应代理；不提供真实源功率、具体器件毁伤阈值或现实作用距离推断。</div>')

        components=[project_name,seed,frequency,nx,ny,spacing_x,spacing_y,z_lambda,span_x,span_y,samples,target_x,target_y,target_major,target_minor,target_rotation,guard_scale,protected_enabled,protected_x,protected_y,protected_radius,method,target_amplitude,outside_penalty,outside_hinge,iterations,learning_rate,uncertainty_scenarios,gain_std,phase_std,registration_jitter,pa_enabled,dpd_enabled,pa_saturation,pa_smoothness,pa_phase,motion_enabled,motion_frames,motion_dt,motion_vx,motion_vy,motion_ax,motion_ay,motion_maneuver_amplitude,motion_maneuver_period,motion_delay,motion_controller,motion_samples]
        assert len(components)==len(PARAMETER_KEYS)
        preview_button.click(_preview_callback,inputs=components,outputs=[scene_plot,scene_editor,config_json,project_tree,status_html],show_progress="minimal")
        save_button.click(_save_callback,inputs=components,outputs=[project_download,config_json,status_html],show_progress="minimal")
        run_button.click(_solve_callback,inputs=components,outputs=[result_state,scene_plot,field_plot,cut_plot,far_plot,weights_plot,convergence_plot,metrics_table,metric_cards,solver_log,config_json,project_tree,project_download,report_download,bundle_download,status_html,task_graph_plot],show_progress="full",concurrency_limit=1)
        load_button.click(_load_callback,inputs=[load_file],outputs=[*components,scene_plot,scene_editor,config_json,project_tree,status_html],show_progress="minimal")
        apply_preset.click(_preset_callback,inputs=[preset],outputs=[*components,scene_plot,scene_editor,config_json,project_tree,status_html],show_progress="minimal")
        drag_event=scene_editor.input(_editor_event_callback,inputs=None,outputs=[target_x,target_y,target_major,target_minor,target_rotation,protected_x,protected_y,protected_radius,status_html],show_progress="hidden")
        drag_event.then(_preview_callback,inputs=components,outputs=[scene_plot,scene_editor,config_json,project_tree,status_html],show_progress="hidden")
        timeline_run.click(_timeline_callback,inputs=components,outputs=[timeline_state,timeline_animation,timeline_metrics_plot,trajectory_plot,timeline_table,timeline_summary,timeline_log,timeline_report,timeline_archive,status_html,task_graph_plot],show_progress="full",concurrency_limit=1)
        sweep_run.click(_sweep_callback,inputs=[*components,sweep_parameter,sweep_start,sweep_stop,sweep_points,sweep_replicates,sweep_metric,sweep_fast],outputs=[sweep_state,sweep_plot,sweep_summary,sweep_records,sweep_log,sweep_report,sweep_archive,history_table,status_html,task_graph_plot],show_progress="full",concurrency_limit=1)
        history_refresh.click(lambda:DATABASE.history(),outputs=[history_table],show_progress="minimal")
        compile_button.click(_compile_graph,inputs=[task_selection],outputs=[task_graph_plot,task_plan,status_html],show_progress="minimal")
        library_choice.change(_library_items,inputs=[library_choice],outputs=[library_description,library_gallery,library_report],show_progress="minimal")
        pa_enabled.change(lambda enabled:gr.update(value=bool(enabled),interactive=bool(enabled)),inputs=[pa_enabled],outputs=[dpd_enabled],show_progress="hidden")
    return demo


def launch(**kwargs: Any) -> None:
    app=build_app(); launch_kwargs={"server_name":"127.0.0.1","server_port":7860,"share":False,"inbrowser":True,"show_error":True,"allowed_paths":[str(PROJECT_ROOT)],"theme":gr.themes.Base(primary_hue="cyan",secondary_hue="blue",neutral_hue="slate"),"css":CSS}; launch_kwargs.update(kwargs); app.queue(default_concurrency_limit=1).launch(**launch_kwargs)

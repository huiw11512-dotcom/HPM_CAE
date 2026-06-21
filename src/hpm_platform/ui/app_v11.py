"""HPM-CAE V1.1 visual workbench.

The V1.1 UI turns perception and receive protection into live executable
nodes, adds a persisted multi-object scene, and exposes a checkpointed local
parallel queue.  All numerical quantities remain normalized research proxies.
"""
from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Any, Sequence
import traceback

import gradio as gr
import pandas as pd

from hpm_platform.ui.app import CSS as V10_CSS
from hpm_platform.ui.experiment_manager import METRIC_LABELS, SWEEP_PARAMETERS, SweepSpec
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
from hpm_platform.ui.job_queue import PersistentJobQueue
from hpm_platform.ui.live_chain import run_live_perception, run_live_protection
from hpm_platform.ui.live_figures import (
    make_live_metric_cards,
    make_perception_comparison,
    make_perception_diagnostics,
    make_perception_spectrum,
    make_protection_comparison,
    make_protection_map,
)
from hpm_platform.ui.object_manager import (
    INTERFERER_COLUMNS,
    TARGET_COLUMNS,
    ZONE_COLUMNS,
    add_interferer_row,
    add_target_row,
    add_zone_row,
    apply_object_frames,
    object_tree_html,
    project_to_object_frames,
)
from hpm_platform.ui.project_model import (
    CAEProject,
    PerceptionSpec,
    ProtectionSpec,
    default_project,
)
from hpm_platform.ui.quick_solver import solve_project
from hpm_platform.ui.scene_editor import EDITOR_CSS, EDITOR_HTML, EDITOR_JS, scene_editor_value
from hpm_platform.ui.task_graph import GRAPH, default_selection, make_task_graph_figure, node_choices
from hpm_platform.ui.timeline import export_timeline, make_timeline_animation, make_timeline_metrics_figure, make_trajectory_figure, run_timeline
from hpm_platform.ui.workflow_executor import execute_workflow

PROJECT_ROOT = Path(__file__).resolve().parents[3]
OUTPUT_ROOT = PROJECT_ROOT / "outputs_v11_ui"
RUN_ROOT = OUTPUT_ROOT / "runs"
PROJECT_DIR = OUTPUT_ROOT / "projects"
TIMELINE_ROOT = OUTPUT_ROOT / "timelines"
WORKFLOW_ROOT = OUTPUT_ROOT / "workflows"
QUEUE_DB = OUTPUT_ROOT / "job_queue.sqlite3"
QUEUE = PersistentJobQueue(QUEUE_DB)

UI_KEYS = (
    "project_name", "seed", "frequency_ghz", "nx", "ny", "spacing_x_lambda", "spacing_y_lambda",
    "z_lambda", "span_x_lambda", "span_y_lambda", "samples",
    "solver_method", "iterations", "target_amplitude", "outside_penalty", "outside_hinge",
    "uncertainty_scenarios", "gain_std_percent", "phase_std_deg", "registration_jitter", "pa_enabled", "dpd_enabled",
    "perception_method", "snr_db", "snapshots", "fault_count", "prior_sigma_deg", "prior_strength",
    "protection_method", "desired_theta_deg", "desired_phi_deg", "interferer_power_db", "sector_scale", "soft_strength",
    "parallel_workers",
)

EXTRA_CSS = r"""
.object-tree{font-size:11px;line-height:1.45}.object-root{font-weight:760;color:#e7eef9;padding:6px}.object-group{color:#35d8ff;margin-top:7px;padding:4px 6px;border-top:1px solid #26354d}.object-group em{float:right;color:#91a2bb;font-style:normal}.object-row{display:grid;grid-template-columns:12px 18px minmax(100px,1fr) 70px;gap:5px;padding:4px 7px;align-items:center}.object-row small{grid-column:3/5;color:#91a2bb}.object-row code{font-size:9px;color:#ab8cff}.object-row.off{opacity:.52}
.v11-scope{border-left:4px solid #ffc857;background:#091422;border-radius:8px;padding:10px;color:#91a2bb;font-size:11px;line-height:1.6}.v11-live-banner{display:flex;gap:7px;flex-wrap:wrap}.v11-live-banner span{border:1px solid rgba(78,224,165,.35);background:rgba(78,224,165,.07);color:#4ee0a5;border-radius:999px;padding:5px 9px;font-size:10px}.queue-controls button{min-width:100px}.gradio-container table{font-size:11px!important}
"""
CSS = V10_CSS + EDITOR_CSS + EXTRA_CSS

HEADER = """
<div class="cae-topbar-inner"><div class="cae-brand"><div class="cae-logo">H</div><div><div class="cae-title">HPM-CAE Workbench <span style="color:#35d8ff">V1.1</span></div><div class="cae-sub">Live sensing · robust receive protection · multi-object field control · resumable local queue</div></div></div><div class="cae-badges"><span class="cae-badge">ALL PYTHON</span><span class="cae-badge">LIVE FULL CHAIN</span><span class="cae-badge">MULTI-OBJECT</span><span class="cae-badge">NORMALIZED MODE</span></div></div>
"""

PIPELINE = """
<div class="pipeline"><div class="stage ready"><b>① 信号/感知</b><span>相干多径 · PAWR实时计算</span></div><div class="arrow">›</div><div class="stage ready"><b>② 接收防护</b><span>DOA置信域 · 鲁棒宽零陷</span></div><div class="arrow">›</div><div class="stage ready"><b>③ 多目标控场</b><span>PGMS · PA · DPD</span></div><div class="arrow">›</div><div class="stage ready"><b>④ 代理评价</b><span>归一化任务评分</span></div><div class="arrow">›</div><div class="stage ui"><b>⑤ CAE管理</b><span>对象树 · 队列 · 报告</span></div></div>
"""


def _status(title: str, detail: str, kind: str = "ok") -> str:
    return f'<div class="cae-status {kind}"><strong>{title}</strong>{detail}</div>'


def _project_from_ui(state: dict, values: Sequence[Any], targets: Any, zones: Any, interferers: Any) -> CAEProject:
    if len(values) != len(UI_KEYS):
        raise ValueError(f"expected {len(UI_KEYS)} UI values, got {len(values)}")
    v = dict(zip(UI_KEYS, values, strict=True))
    base = CAEProject.from_dict(state)
    perception = replace(
        base.perception,
        method=str(v["perception_method"]), snr_db=float(v["snr_db"]), snapshots=int(v["snapshots"]),
        fault_count=int(v["fault_count"]), prior_sigma_deg=float(v["prior_sigma_deg"]), prior_strength=float(v["prior_strength"]),
    )
    protection = replace(
        base.protection,
        method=str(v["protection_method"]), desired_theta_deg=float(v["desired_theta_deg"]), desired_phi_deg=float(v["desired_phi_deg"]),
        interferer_power_db=float(v["interferer_power_db"]), sector_scale=float(v["sector_scale"]), soft_strength=float(v["soft_strength"]),
    )
    project = replace(
        base,
        meta=replace(base.meta, name=str(v["project_name"]), seed=int(v["seed"])),
        array=replace(base.array, nx=int(v["nx"]), ny=int(v["ny"]), frequency_ghz=float(v["frequency_ghz"]), spacing_x_lambda=float(v["spacing_x_lambda"]), spacing_y_lambda=float(v["spacing_y_lambda"])),
        plane=replace(base.plane, z_lambda=float(v["z_lambda"]), span_x_lambda=float(v["span_x_lambda"]), span_y_lambda=float(v["span_y_lambda"]), samples=int(v["samples"])),
        perception=perception,
        protection=protection,
        solver=replace(
            base.solver, method=str(v["solver_method"]), iterations=int(v["iterations"]), target_amplitude=float(v["target_amplitude"]),
            outside_penalty=float(v["outside_penalty"]), outside_hinge_amplitude=float(v["outside_hinge"]),
            uncertainty_scenarios=int(v["uncertainty_scenarios"]), gain_std_percent=float(v["gain_std_percent"]),
            phase_std_deg=float(v["phase_std_deg"]), registration_jitter_lambda=float(v["registration_jitter"]),
            pa_enabled=bool(v["pa_enabled"]), dpd_enabled=bool(v["dpd_enabled"] and v["pa_enabled"]),
        ),
        workflow=replace(base.workflow, parallel_workers=int(v["parallel_workers"])),
    )
    return apply_object_frames(project, targets, zones, interferers)


def _ui_values(project: CAEProject) -> list[Any]:
    return [
        project.meta.name, project.meta.seed, project.array.frequency_ghz, project.array.nx, project.array.ny, project.array.spacing_x_lambda, project.array.spacing_y_lambda,
        project.plane.z_lambda, project.plane.span_x_lambda, project.plane.span_y_lambda, project.plane.samples,
        project.solver.method, project.solver.iterations, project.solver.target_amplitude, project.solver.outside_penalty, project.solver.outside_hinge_amplitude,
        project.solver.uncertainty_scenarios, project.solver.gain_std_percent, project.solver.phase_std_deg, project.solver.registration_jitter_lambda, project.solver.pa_enabled, project.solver.dpd_enabled,
        project.perception.method, project.perception.snr_db, project.perception.snapshots, project.perception.fault_count, project.perception.prior_sigma_deg, project.perception.prior_strength,
        project.protection.method, project.protection.desired_theta_deg, project.protection.desired_phi_deg, project.protection.interferer_power_db, project.protection.sector_scale, project.protection.soft_strength,
        project.workflow.parallel_workers,
    ]


def _sync_callback(state: dict, *args: Any):
    try:
        values = args[:len(UI_KEYS)]; targets, zones, interferers = args[len(UI_KEYS):]
        project = _project_from_ui(state, values, targets, zones, interferers)
        detail = f"{project.array.nx*project.array.ny}阵元 · {len(project.targets)}目标 · {len(project.protected_zones)}保护区 · {len(project.active_interferers)}辐射源"
        return project.to_dict(), object_tree_html(project), make_scene_figure(project), scene_editor_value(project), _status("场景已同步", detail)
    except Exception as exc:
        return state, object_tree_html(CAEProject.from_dict(state)), make_empty_result_figure("场景参数错误", str(exc)), scene_editor_value(CAEProject.from_dict(state)), _status("参数校验失败", str(exc), "error")


def _drag_callback(targets: Any, zones: Any, evt: gr.EventData):
    target_frame = pd.DataFrame(targets, columns=TARGET_COLUMNS).copy()
    zone_frame = pd.DataFrame(zones, columns=ZONE_COLUMNS).copy()
    def get(name: str, default: float) -> float:
        return float(getattr(evt, name, default))
    if not target_frame.empty:
        target_frame.loc[0, ["center_x_lambda", "center_y_lambda", "semi_major_lambda", "semi_minor_lambda", "rotation_deg"]] = [
            get("target_x", .8), get("target_y", -.6), get("target_major", 1.1), get("target_minor", .65), get("target_rotation", 25),
        ]
    if not zone_frame.empty:
        zone_frame.loc[0, ["center_x_lambda", "center_y_lambda", "radius_lambda"]] = [get("protected_x", -2.5), get("protected_y", 2.1), get("protected_radius", .7)]
    return target_frame, zone_frame, _status("拖拽已写回对象树", "主目标区与主保护区几何参数已同步。")


def _static_callback(state: dict, *args: Any):
    try:
        values = args[:len(UI_KEYS)]; targets, zones, interferers = args[len(UI_KEYS):]
        project = _project_from_ui(state, values, targets, zones, interferers)
        result = solve_project(project)
        run_dir, report, archive = export_result_bundle(result, RUN_ROOT)
        detail = f"RMSE {result.metrics['target_rmse_percent']:.2f}% · 覆盖率 {result.metrics['target_coverage_percent']:.1f}% · {result.metrics['solver_runtime_ms']:.1f} ms"
        return project.to_dict(), result, make_scene_figure(project), make_field_figure(result), make_cut_figure(result), make_far_field_figure(result), make_weights_figure(result), make_convergence_figure(result), result.metrics_frame(), make_metric_cards_html(result), "\n".join(result.log_lines), str(report), str(archive), object_tree_html(project), _status("多目标静态求解完成", detail, "ok" if result.metrics["control_success"] else "warn")
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"; empty = make_empty_result_figure("求解失败", error)
        return state, None, empty, empty, empty, empty, empty, empty, pd.DataFrame([{"指标":"错误","数值":error}]), "", traceback.format_exc(), None, None, object_tree_html(CAEProject.from_dict(state)), _status("求解失败", error, "error")


def _live_callback(state: dict, *args: Any):
    try:
        values = args[:len(UI_KEYS)]; targets, zones, interferers = args[len(UI_KEYS):]
        project = _project_from_ui(state, values, targets, zones, interferers)
        perception = run_live_perception(project)
        protection = run_live_protection(project, perception)
        detail = f"DOA RMSE {perception.metrics['rmse_deg']:.3f}° · 输出SINR {protection.metrics['output_sinr_db']:.2f} dB · 最坏响应 {protection.metrics['worst_true_response_db']:.2f} dB"
        log = "\n".join((*perception.log_lines, *protection.log_lines))
        return project.to_dict(), perception, protection, make_perception_spectrum(perception), make_perception_diagnostics(perception), make_perception_comparison(perception), perception.estimates_frame(), perception.comparison_frame(), make_protection_map(protection), make_protection_comparison(protection), protection.comparison_frame(), make_live_metric_cards(perception, protection), log, _status("实时感知—防护链路完成", detail, "ok" if protection.metrics["protection_success"] else "warn")
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"; empty = make_empty_result_figure("实时链路失败", error)
        return state, None, None, empty, empty, empty, pd.DataFrame([{"error":error}]), pd.DataFrame(), empty, empty, pd.DataFrame(), "", traceback.format_exc(), _status("实时链路失败", error, "error")


def _workflow_callback(state: dict, selected: list[str] | None, *args: Any):
    try:
        values = args[:len(UI_KEYS)]; targets, zones, interferers = args[len(UI_KEYS):]
        project = _project_from_ui(state, values, targets, zones, interferers)
        result = execute_workflow(project, selected or default_selection(), export_root=WORKFLOW_ROOT)
        effect = pd.DataFrame([result.effect_metrics])
        return project.to_dict(), result, make_task_graph_figure(result.selected_nodes, statuses=result.statuses), result.task_frame(), effect, "\n".join(result.log_lines), str(result.report_path), str(result.archive_path), _status("一键全链路完成", f"归一化任务评分 {float(result.effect_metrics.get('normalized_mission_score',0)):.3f} · 可用={result.effect_metrics.get('full_chain_available',False)}")
    except Exception as exc:
        error=f"{type(exc).__name__}: {exc}"
        return state, None, make_task_graph_figure(selected or default_selection()), pd.DataFrame([{"error":error}]), pd.DataFrame(), traceback.format_exc(), None, None, _status("全链路执行失败", error, "error")


def _timeline_callback(state: dict, *args: Any):
    try:
        values=args[:len(UI_KEYS)]; targets,zones,interferers=args[len(UI_KEYS):]
        project=_project_from_ui(state,values,targets,zones,interferers)
        result=run_timeline(project); report,archive=export_timeline(result,TIMELINE_ROOT)
        summary=pd.DataFrame([{"指标":k,"数值":v} for k,v in result.summary().items()])
        return result,make_timeline_animation(result),make_timeline_metrics_figure(result),make_trajectory_figure(result),summary,result.metrics,"\n".join(result.log_lines),str(report),str(archive),_status("动态时间轴完成",f"{result.n_frames}帧 · 平均RMSE {result.summary()['mean_target_rmse_percent']:.2f}%")
    except Exception as exc:
        error=f"{type(exc).__name__}: {exc}"; empty=make_empty_result_figure("动态任务失败",error)
        return None,empty,empty,empty,pd.DataFrame([{"错误":error}]),pd.DataFrame(),traceback.format_exc(),None,None,_status("动态任务失败",error,"error")


def _save_callback(state: dict, *args: Any):
    values=args[:len(UI_KEYS)]; targets,zones,interferers=args[len(UI_KEYS):]
    try:
        project=_project_from_ui(state,values,targets,zones,interferers); path=export_project_file(project,PROJECT_DIR)
        return project.to_dict(),str(path),_status("项目已保存",path.name)
    except Exception as exc:
        return state,None,_status("保存失败",str(exc),"error")


def _load_callback(path: Any):
    if not path:
        raise gr.Error("请选择项目 YAML")
    try:
        filename=getattr(path,"name",path); project=CAEProject.load_yaml(filename); t,z,i=project_to_object_frames(project)
        return (*_ui_values(project),t,z,i,project.to_dict(),object_tree_html(project),make_scene_figure(project),scene_editor_value(project),_status("项目已载入",Path(filename).name))
    except Exception as exc:
        raise gr.Error(f"项目载入失败：{exc}")


def _queue_submit_callback(state: dict, parameter: str, start: float, stop: float, points: int, replicates: int, metric: str, fast_mode: bool, auto_start: bool, *args: Any):
    try:
        values=args[:len(UI_KEYS)]; targets,zones,interferers=args[len(UI_KEYS):]
        project=_project_from_ui(state,values,targets,zones,interferers)
        spec=SweepSpec(parameter=parameter,start=float(start),stop=float(stop),points=int(points),replicates=int(replicates),metric=metric,fast_mode=bool(fast_mode))
        job_id=QUEUE.submit_sweep(project,spec,workers=project.workflow.parallel_workers)
        if auto_start: QUEUE.start(job_id)
        return job_id,QUEUE.jobs(),QUEUE.items(job_id),_status("任务已提交",f"{job_id} · {points*replicates}算例 · {project.workflow.parallel_workers} workers")
    except Exception as exc:
        return "",QUEUE.jobs(),pd.DataFrame(),_status("提交失败",str(exc),"error")


def _queue_action(job_id: str, action: str, workers: int):
    try:
        if not job_id: raise ValueError("请先提交或输入任务ID")
        if action=="pause": QUEUE.pause(job_id)
        elif action=="resume": QUEUE.resume(job_id,workers=int(workers))
        elif action=="cancel": QUEUE.cancel(job_id)
        elif action=="run": QUEUE.start(job_id)
        row=QUEUE.job(job_id)
        return QUEUE.jobs(),QUEUE.items(job_id),_status(f"任务 {row['status']}",row.get("message") or job_id)
    except Exception as exc:
        return QUEUE.jobs(),pd.DataFrame(),_status("队列操作失败",str(exc),"error")


def _queue_refresh(job_id: str):
    try:
        items=QUEUE.items(job_id) if job_id else pd.DataFrame(); detail=QUEUE.job(job_id) if job_id else {"status":"idle","message":"尚未选择任务"}
        return QUEUE.jobs(),items,_status(f"任务 {detail['status']}",detail.get("message") or "")
    except Exception as exc:
        return QUEUE.jobs(),pd.DataFrame(),_status("刷新失败",str(exc),"error")


def _add_second_target(frame: Any): return add_target_row(frame)
def _add_second_zone(frame: Any): return add_zone_row(frame)
def _add_second_interferer(frame: Any): return add_interferer_row(frame)
def _drop_last(frame: Any, columns: list[str]):
    data=pd.DataFrame(frame,columns=columns).copy()
    return data.iloc[:-1].reset_index(drop=True) if len(data)>1 else data


def build_app() -> gr.Blocks:
    initial=default_project(); target_frame,zone_frame,interferer_frame=project_to_object_frames(initial)
    empty=make_empty_result_figure("尚未运行","从左侧同步场景，然后运行对应求解节点。")
    ui_values=_ui_values(initial)
    with gr.Blocks(title="HPM-CAE V1.1") as demo:
        project_state=gr.State(initial.to_dict()); static_state=gr.State(); perception_state=gr.State(); protection_state=gr.State(); workflow_state=gr.State(); timeline_state=gr.State(); job_state=gr.State("")
        gr.HTML(HEADER,elem_id="cae-topbar"); gr.HTML(PIPELINE)
        with gr.Row(elem_id="workbench-row"):
            with gr.Column(scale=21,min_width=300,elem_classes="cae-sidebar"):
                object_tree=gr.HTML(object_tree_html(initial))
                with gr.Accordion("工程 / 阵列",open=True):
                    project_name=gr.Textbox(value=initial.meta.name,label="工程名称"); seed=gr.Number(value=initial.meta.seed,precision=0,label="随机种子")
                    with gr.Row(): frequency=gr.Number(value=initial.array.frequency_ghz,label="频率/GHz"); nx=gr.Slider(6,16,value=initial.array.nx,step=1,label="Nx"); ny=gr.Slider(6,16,value=initial.array.ny,step=1,label="Ny")
                    with gr.Row(): spacing_x=gr.Number(value=initial.array.spacing_x_lambda,label="dx/λ"); spacing_y=gr.Number(value=initial.array.spacing_y_lambda,label="dy/λ")
                with gr.Accordion("观察面",open=False):
                    z_lambda=gr.Number(value=initial.plane.z_lambda,label="z/λ"); span_x=gr.Number(value=initial.plane.span_x_lambda,label="跨度x/λ"); span_y=gr.Number(value=initial.plane.span_y_lambda,label="跨度y/λ"); samples=gr.Slider(31,121,value=initial.plane.samples,step=2,label="网格点数")
                with gr.Accordion("空间控场",open=False):
                    solver_method=gr.Dropdown(choices=list(initial.solver.METHODS),value=initial.solver.method,label="求解器"); iterations=gr.Slider(20,800,value=initial.solver.iterations,step=10,label="迭代"); target_amplitude=gr.Number(value=initial.solver.target_amplitude,label="目标归一化幅度"); outside_penalty=gr.Number(value=initial.solver.outside_penalty,label="区外惩罚"); outside_hinge=gr.Number(value=initial.solver.outside_hinge_amplitude,label="区外铰链幅度")
                    uncertainty_scenarios=gr.Slider(1,15,value=initial.solver.uncertainty_scenarios,step=1,label="鲁棒场景数"); gain_std=gr.Number(value=initial.solver.gain_std_percent,label="增益误差σ/%"); phase_std=gr.Number(value=initial.solver.phase_std_deg,label="相位误差σ/°"); registration_jitter=gr.Number(value=initial.solver.registration_jitter_lambda,label="配准抖动σ/λ"); pa_enabled=gr.Checkbox(value=initial.solver.pa_enabled,label="功放模型"); dpd_enabled=gr.Checkbox(value=initial.solver.dpd_enabled,label="DPD")
                with gr.Accordion("实时感知",open=False):
                    perception_method=gr.Dropdown(choices=list(PerceptionSpec.METHODS),value=initial.perception.method,label="测向方法"); snr_db=gr.Number(value=initial.perception.snr_db,label="归一化SNR/dB"); snapshots=gr.Slider(32,512,value=initial.perception.snapshots,step=16,label="快拍"); fault_count=gr.Slider(0,8,value=initial.perception.fault_count,step=1,label="坏通道数"); prior_sigma=gr.Number(value=initial.perception.prior_sigma_deg,label="先验σ/°"); prior_strength=gr.Number(value=initial.perception.prior_strength,label="先验强度")
                with gr.Accordion("接收防护",open=False):
                    protection_method=gr.Dropdown(choices=list(ProtectionSpec.METHODS),value=initial.protection.method,label="波束形成"); desired_theta=gr.Number(value=initial.protection.desired_theta_deg,label="期望θ/°"); desired_phi=gr.Number(value=initial.protection.desired_phi_deg,label="期望φ/°"); interferer_power=gr.Number(value=initial.protection.interferer_power_db,label="相对干扰功率/dB"); sector_scale=gr.Number(value=initial.protection.sector_scale,label="置信扇区尺度"); soft_strength=gr.Number(value=initial.protection.soft_strength,label="软加载强度")
                parallel_workers=gr.Slider(1,8,value=initial.workflow.parallel_workers,step=1,label="并行 workers")
                sync_button=gr.Button("同步场景",variant="secondary"); status_html=gr.HTML(_status("V1.1工程就绪","实时节点和多对象模型已加载。"))
                gr.HTML('<div class="v11-scope"><b>模型边界</b><br>仅处理波长尺度几何、归一化复场、相对阵列响应与无量纲代理评价；不输出绝对源功率、具体器件阈值、现实毁伤概率或作用距离。</div>')
            with gr.Column(scale=58,min_width=680,elem_id="viewport-panel"):
                with gr.Tabs(elem_id="viewport-tabs"):
                    with gr.Tab("场景 / 对象"):
                        with gr.Tabs():
                            with gr.Tab("拖拽编辑"): scene_editor=gr.HTML(value=scene_editor_value(initial),html_template=EDITOR_HTML,css_template=EDITOR_CSS,js_on_load=EDITOR_JS,apply_default_css=False,min_height=620)
                            with gr.Tab("三维几何"): scene_plot=gr.Plot(make_scene_figure(initial),show_label=False)
                            with gr.Tab("对象表"):
                                with gr.Accordion("目标区",open=True):
                                    target_table=gr.Dataframe(target_frame,headers=TARGET_COLUMNS,interactive=True,show_row_numbers=False); 
                                    with gr.Row(): add_target=gr.Button("＋目标",size="sm"); drop_target=gr.Button("－末行",size="sm")
                                with gr.Accordion("保护区",open=False):
                                    zone_table=gr.Dataframe(zone_frame,headers=ZONE_COLUMNS,interactive=True,show_row_numbers=False)
                                    with gr.Row(): add_zone=gr.Button("＋保护区",size="sm"); drop_zone=gr.Button("－末行",size="sm")
                                with gr.Accordion("相干辐射源",open=False):
                                    interferer_table=gr.Dataframe(interferer_frame,headers=INTERFERER_COLUMNS,interactive=True,show_row_numbers=False)
                                    with gr.Row(): add_interferer=gr.Button("＋辐射源",size="sm"); drop_interferer=gr.Button("－末行",size="sm")
                    with gr.Tab("静态控场"):
                        static_run=gr.Button("▶ 运行多目标静态求解",variant="primary")
                        static_cards=gr.HTML(''); field_plot=gr.Plot(empty,show_label=False)
                        with gr.Tabs():
                            with gr.Tab("截线"): cut_plot=gr.Plot(empty,show_label=False)
                            with gr.Tab("远场"): far_plot=gr.Plot(empty,show_label=False)
                            with gr.Tab("激励"): weights_plot=gr.Plot(empty,show_label=False)
                            with gr.Tab("收敛"): convergence_plot=gr.Plot(empty,show_label=False)
                        static_metrics=gr.Dataframe(pd.DataFrame(),interactive=False,show_row_numbers=False); static_log=gr.Code(value="",language="shell",lines=9,max_lines=24,interactive=False,show_line_numbers=False)
                        with gr.Row(): static_report=gr.DownloadButton("下载静态报告",value=None); static_archive=gr.DownloadButton("下载静态结果ZIP",value=None,variant="primary")
                    with gr.Tab("实时感知 / 防护"):
                        gr.HTML('<div class="v11-live-banner"><span>实时信号生成</span><span>PAWR / FBSS / ESPRIT</span><span>DOA不确定度</span><span>鲁棒宽零陷</span></div>')
                        live_run=gr.Button("▶ 运行实时感知—防护链路",variant="primary"); live_cards=gr.HTML('')
                        with gr.Tabs():
                            with gr.Tab("二维空间谱"): perception_spectrum=gr.Plot(empty,show_label=False)
                            with gr.Tab("秩 / 坏通道"): perception_diag=gr.Plot(empty,show_label=False)
                            with gr.Tab("测向对比"): perception_compare=gr.Plot(empty,show_label=False)
                            with gr.Tab("接收响应"): protection_map=gr.Plot(empty,show_label=False)
                            with gr.Tab("防护对比"): protection_compare=gr.Plot(empty,show_label=False)
                        with gr.Row(): perception_estimates=gr.Dataframe(pd.DataFrame(),label="路径估计",interactive=False,show_row_numbers=False); perception_methods=gr.Dataframe(pd.DataFrame(),label="测向基线",interactive=False,show_row_numbers=False)
                        protection_methods=gr.Dataframe(pd.DataFrame(),label="防护基线",interactive=False,show_row_numbers=False); live_log=gr.Code(value="",language="shell",lines=10,max_lines=26,interactive=False,show_line_numbers=False)
                    with gr.Tab("全链路任务图"):
                        task_selection=gr.CheckboxGroup(choices=node_choices(),value=default_selection(),label="任务节点"); workflow_run=gr.Button("▶ 一键执行所选全链路",variant="primary")
                        task_graph=gr.Plot(make_task_graph_figure(),show_label=False); task_plan=gr.Dataframe(GRAPH.compile_plan(default_selection()),interactive=False,show_row_numbers=False); effect_table=gr.Dataframe(pd.DataFrame(),label="归一化任务评价",interactive=False,show_row_numbers=False); workflow_log=gr.Code(value="",language="shell",lines=10,max_lines=28,interactive=False,show_line_numbers=False)
                        with gr.Row(): workflow_report=gr.DownloadButton("下载全链路报告",value=None); workflow_archive=gr.DownloadButton("下载全链路ZIP",value=None,variant="primary")
                    with gr.Tab("动态时间轴"):
                        timeline_run=gr.Button("▶ 运行动态时间轴",variant="primary"); timeline_animation=gr.Plot(empty,show_label=False)
                        with gr.Row(): timeline_metrics_plot=gr.Plot(empty,show_label=False); trajectory_plot=gr.Plot(empty,show_label=False)
                        timeline_summary=gr.Dataframe(pd.DataFrame(),interactive=False,show_row_numbers=False); timeline_records=gr.Dataframe(pd.DataFrame(),interactive=False,show_row_numbers=False); timeline_log=gr.Code(value="",language="shell",lines=8,max_lines=20,interactive=False,show_line_numbers=False)
                        with gr.Row(): timeline_report=gr.DownloadButton("下载动态报告",value=None); timeline_archive=gr.DownloadButton("下载动态ZIP",value=None)
                    with gr.Tab("并行任务队列"):
                        gr.HTML('<div class="tab-note">任务在本机执行并逐算例写入SQLite。暂停会让当前正在运行的算例完成，然后停止派发新算例；恢复后从未完成检查点继续。</div>')
                        with gr.Row(): queue_parameter=gr.Dropdown(choices=[(v,k) for k,v in SWEEP_PARAMETERS.items()],value="solver.phase_std_deg",label="扫参变量"); queue_start=gr.Number(value=0,label="起点"); queue_stop=gr.Number(value=12,label="终点"); queue_points=gr.Slider(2,15,value=5,step=1,label="点数"); queue_replicates=gr.Slider(1,8,value=2,step=1,label="重复")
                        with gr.Row(): queue_metric=gr.Dropdown(choices=[(v,k) for k,v in METRIC_LABELS.items()],value="target_rmse_percent",label="指标"); queue_fast=gr.Checkbox(value=True,label="快速模式"); queue_auto=gr.Checkbox(value=True,label="提交后立即运行"); queue_submit=gr.Button("提交任务",variant="primary")
                        job_id=gr.Textbox(value="",label="当前任务ID")
                        with gr.Row(elem_classes="queue-controls"): queue_run=gr.Button("运行"); queue_pause=gr.Button("暂停"); queue_resume=gr.Button("恢复"); queue_cancel=gr.Button("取消"); queue_refresh=gr.Button("刷新")
                        queue_status=gr.HTML(_status("队列空闲","尚未提交任务。")); jobs_table=gr.Dataframe(QUEUE.jobs(),label="任务列表",interactive=False,show_row_numbers=False); items_table=gr.Dataframe(pd.DataFrame(),label="当前任务检查点",interactive=False,show_row_numbers=False,max_height=380); queue_db=gr.DownloadButton("下载队列数据库",value=str(QUEUE_DB))
                    with gr.Tab("项目文件"):
                        load_file=gr.File(label="载入YAML",file_types=[".yaml",".yml"],type="filepath"); load_button=gr.Button("载入项目",variant="secondary"); save_button=gr.Button("保存当前项目",variant="primary"); project_download=gr.DownloadButton("下载项目YAML",value=None); config_json=gr.JSON(initial.to_dict(),label="项目快照",open=False)
                with gr.Accordion("Workbench Log",open=False): global_note=gr.Markdown("V1.1 live chain ready.")

        components=[project_name,seed,frequency,nx,ny,spacing_x,spacing_y,z_lambda,span_x,span_y,samples,solver_method,iterations,target_amplitude,outside_penalty,outside_hinge,uncertainty_scenarios,gain_std,phase_std,registration_jitter,pa_enabled,dpd_enabled,perception_method,snr_db,snapshots,fault_count,prior_sigma,prior_strength,protection_method,desired_theta,desired_phi,interferer_power,sector_scale,soft_strength,parallel_workers]
        assert len(components)==len(UI_KEYS)
        common_inputs=[project_state,*components,target_table,zone_table,interferer_table]
        sync_outputs=[project_state,object_tree,scene_plot,scene_editor,status_html]
        sync_button.click(_sync_callback,inputs=common_inputs,outputs=sync_outputs,show_progress="minimal")
        static_run.click(_static_callback,inputs=common_inputs,outputs=[project_state,static_state,scene_plot,field_plot,cut_plot,far_plot,weights_plot,convergence_plot,static_metrics,static_cards,static_log,static_report,static_archive,object_tree,status_html],show_progress="full",concurrency_limit=1)
        live_run.click(_live_callback,inputs=common_inputs,outputs=[project_state,perception_state,protection_state,perception_spectrum,perception_diag,perception_compare,perception_estimates,perception_methods,protection_map,protection_compare,protection_methods,live_cards,live_log,status_html],show_progress="full",concurrency_limit=1)
        workflow_run.click(_workflow_callback,inputs=[project_state,task_selection,*components,target_table,zone_table,interferer_table],outputs=[project_state,workflow_state,task_graph,task_plan,effect_table,workflow_log,workflow_report,workflow_archive,status_html],show_progress="full",concurrency_limit=1)
        timeline_run.click(_timeline_callback,inputs=common_inputs,outputs=[timeline_state,timeline_animation,timeline_metrics_plot,trajectory_plot,timeline_summary,timeline_records,timeline_log,timeline_report,timeline_archive,status_html],show_progress="full",concurrency_limit=1)
        save_button.click(_save_callback,inputs=common_inputs,outputs=[project_state,project_download,status_html],show_progress="minimal")
        load_button.click(_load_callback,inputs=[load_file],outputs=[*components,target_table,zone_table,interferer_table,project_state,object_tree,scene_plot,scene_editor,status_html],show_progress="minimal")
        scene_editor.input(_drag_callback,inputs=[target_table,zone_table],outputs=[target_table,zone_table,status_html],show_progress="hidden").then(_sync_callback,inputs=common_inputs,outputs=sync_outputs,show_progress="hidden")
        add_target.click(_add_second_target,inputs=[target_table],outputs=[target_table]).then(_sync_callback,inputs=common_inputs,outputs=sync_outputs,show_progress="hidden")
        drop_target.click(lambda frame:_drop_last(frame,TARGET_COLUMNS),inputs=[target_table],outputs=[target_table]).then(_sync_callback,inputs=common_inputs,outputs=sync_outputs,show_progress="hidden")
        add_zone.click(_add_second_zone,inputs=[zone_table],outputs=[zone_table]).then(_sync_callback,inputs=common_inputs,outputs=sync_outputs,show_progress="hidden")
        drop_zone.click(lambda frame:_drop_last(frame,ZONE_COLUMNS),inputs=[zone_table],outputs=[zone_table]).then(_sync_callback,inputs=common_inputs,outputs=sync_outputs,show_progress="hidden")
        add_interferer.click(_add_second_interferer,inputs=[interferer_table],outputs=[interferer_table]).then(_sync_callback,inputs=common_inputs,outputs=sync_outputs,show_progress="hidden")
        drop_interferer.click(lambda frame:_drop_last(frame,INTERFERER_COLUMNS),inputs=[interferer_table],outputs=[interferer_table]).then(_sync_callback,inputs=common_inputs,outputs=sync_outputs,show_progress="hidden")
        queue_submit.click(_queue_submit_callback,inputs=[project_state,queue_parameter,queue_start,queue_stop,queue_points,queue_replicates,queue_metric,queue_fast,queue_auto,*components,target_table,zone_table,interferer_table],outputs=[job_id,jobs_table,items_table,queue_status],show_progress="minimal")
        queue_run.click(lambda jid,w:_queue_action(jid,"run",w),inputs=[job_id,parallel_workers],outputs=[jobs_table,items_table,queue_status],show_progress="minimal")
        queue_pause.click(lambda jid,w:_queue_action(jid,"pause",w),inputs=[job_id,parallel_workers],outputs=[jobs_table,items_table,queue_status],show_progress="minimal")
        queue_resume.click(lambda jid,w:_queue_action(jid,"resume",w),inputs=[job_id,parallel_workers],outputs=[jobs_table,items_table,queue_status],show_progress="minimal")
        queue_cancel.click(lambda jid,w:_queue_action(jid,"cancel",w),inputs=[job_id,parallel_workers],outputs=[jobs_table,items_table,queue_status],show_progress="minimal")
        queue_refresh.click(_queue_refresh,inputs=[job_id],outputs=[jobs_table,items_table,queue_status],show_progress="minimal")
        pa_enabled.change(lambda enabled:gr.update(value=bool(enabled),interactive=bool(enabled)),inputs=[pa_enabled],outputs=[dpd_enabled],show_progress="hidden")
    return demo


def launch(**kwargs: Any) -> None:
    app=build_app()
    options={"server_name":"127.0.0.1","server_port":7860,"share":False,"inbrowser":True,"show_error":True,"allowed_paths":[str(PROJECT_ROOT)],"theme":gr.themes.Base(primary_hue="cyan",secondary_hue="blue",neutral_hue="slate"),"css":CSS}
    options.update(kwargs)
    app.queue(default_concurrency_limit=4).launch(**options)

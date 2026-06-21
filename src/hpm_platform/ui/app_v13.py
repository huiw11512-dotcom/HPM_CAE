"""HPM 数字化电磁算法 CAE V1.3 全中文可视化工作台。

界面基于开源 Gradio Ocean 主题和原生布局组件，不再使用自绘管理后台外观。
所有计算均为波长尺度、归一化标量场与无量纲代理量。
"""
from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Any, Sequence
import traceback

import gradio as gr
import pandas as pd

from hpm_platform.physics.field_backends import backend_choices, get_field_backend
from hpm_platform.ui.backend_explorer import (
    export_backend_comparison,
    make_backend_gallery,
    make_backend_metrics_figure,
    make_propagation_mechanism_figure,
    run_backend_comparison,
)
from hpm_platform.ui.environment_manager import (
    APERTURE_HEADERS,
    CAVITY_HEADERS,
    MATERIAL_HEADERS,
    REFLECTOR_HEADERS,
    add_aperture_row,
    add_cavity_row,
    add_material_row,
    add_reflector_row,
    apply_environment_frames,
    environment_summary_markdown,
    project_to_environment_frames,
)
from hpm_platform.ui.experiment_manager import METRIC_LABELS, SWEEP_PARAMETERS, SweepSpec
from hpm_platform.ui.exporter import export_project_file, export_result_bundle
from hpm_platform.ui.figures import (
    make_convergence_figure,
    make_constraint_margin_figure,
    make_cut_figure,
    make_empty_result_figure,
    make_far_field_figure,
    make_field_figure,
    make_metric_cards_html,
    make_object_metrics_figure,
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
    project_to_object_frames,
)
from hpm_platform.ui.pareto import (
    export_pareto_bundle,
    make_pareto_field_gallery,
    make_pareto_figure,
    make_tradeoff_figure,
    run_pareto_study,
)
from hpm_platform.ui.project_model import (
    CAEProject,
    PerceptionSpec,
    ProtectionSpec,
    default_project,
)
from hpm_platform.ui.quick_solver import solve_project
from hpm_platform.ui.task_graph import GRAPH, default_selection, make_task_graph_figure, node_choices
from hpm_platform.ui.timeline import (
    export_timeline,
    make_timeline_animation,
    make_timeline_metrics_figure,
    make_trajectory_figure,
    run_timeline,
)
from hpm_platform.ui.workflow_executor import execute_workflow

PROJECT_ROOT = Path(__file__).resolve().parents[3]
OUTPUT_ROOT = PROJECT_ROOT / "outputs_v13_ui"
RUN_ROOT = OUTPUT_ROOT / "静态求解"
BACKEND_ROOT = OUTPUT_ROOT / "传播后端对比"
PROJECT_DIR = OUTPUT_ROOT / "工程文件"
TIMELINE_ROOT = OUTPUT_ROOT / "动态时间轴"
WORKFLOW_ROOT = OUTPUT_ROOT / "全链路"
PARETO_ROOT = OUTPUT_ROOT / "帕累托分析"
QUEUE_DB = OUTPUT_ROOT / "任务队列.sqlite3"
QUEUE = PersistentJobQueue(QUEUE_DB)

TARGET_HEADERS = [
    "对象标识", "对象名称", "启用", "中心x/λ", "中心y/λ", "长半轴/λ", "短半轴/λ",
    "旋转角/°", "过渡区倍率", "幅度倍率", "优先级", "容差/%",
]
ZONE_HEADERS = ["对象标识", "对象名称", "启用", "中心x/λ", "中心y/λ", "半径/λ", "优先级", "幅度上限倍率"]
INTERFERER_HEADERS = [
    "对象标识", "对象名称", "启用", "直达θ/°", "直达φ/°", "相对功率/dB", "启用相干回波",
    "回波θ/°", "回波φ/°", "回波相对功率/dB", "回波相位/°", "先验θ/°", "先验φ/°",
    "θ不确定度/°", "φ不确定度/°",
]

SOLVER_CHOICES = [
    ("多焦点相位共轭", "Point-Focus"),
    ("对象平衡区域最小二乘", "Region-LS"),
    ("名义区域梯度赋形", "Nominal-PGMS"),
    ("场景鲁棒区域赋形", "Robust-PGMS"),
    ("多对象约束赋形", "Constrained-MO-PGMS"),
]
PROTECTION_CHOICES = [
    ("对角加载 MVDR", "DL-MVDR"),
    ("点零陷 LCMV", "Point-LCMV"),
    ("扇区鲁棒 MVDR", "Sector-MVDR"),
    ("置信域混合宽零陷", "CR-HybridNull"),
]

UI_KEYS = (
    "project_name", "seed", "frequency_ghz", "nx", "ny", "spacing_x_lambda", "spacing_y_lambda",
    "z_lambda", "span_x_lambda", "span_y_lambda", "samples",
    "propagation_backend", "direct_path_scale", "reflection_scale", "cavity_scale", "maximum_modes",
    "solver_method", "iterations", "target_amplitude", "outside_peak_limit_db", "uncertainty_scenarios",
    "gain_std_percent", "phase_std_deg", "registration_jitter_lambda", "pa_enabled", "dpd_enabled",
    "perception_method", "snr_db", "snapshots", "fault_count", "prior_sigma_deg", "prior_strength",
    "protection_method", "desired_theta_deg", "desired_phi_deg", "interferer_power_db", "sector_scale", "soft_strength",
    "parallel_workers",
)


def _status(title: str, detail: str, kind: str = "ok") -> str:
    icon = {"ok": "✅", "warn": "⚠️", "error": "❌", "info": "ℹ️"}.get(kind, "ℹ️")
    return f"### {icon} {title}\n{detail}"


def _internal_frame(frame: Any, columns: list[str]) -> pd.DataFrame:
    data = frame.copy() if isinstance(frame, pd.DataFrame) else pd.DataFrame(frame)
    if len(data.columns) != len(columns):
        data = pd.DataFrame(frame, columns=columns)
    else:
        data.columns = columns
    return data


def _display_frame(frame: pd.DataFrame, headers: list[str]) -> pd.DataFrame:
    data = frame.copy()
    data.columns = headers
    return data


def _object_frames(project: CAEProject) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    targets, zones, interferers = project_to_object_frames(project)
    return (
        _display_frame(targets, TARGET_HEADERS),
        _display_frame(zones, ZONE_HEADERS),
        _display_frame(interferers, INTERFERER_HEADERS),
    )


def _project_from_ui(state: dict, values: Sequence[Any], frames: Sequence[Any]) -> CAEProject:
    if len(values) != len(UI_KEYS):
        raise ValueError(f"界面参数数量不一致：期望 {len(UI_KEYS)}，实际 {len(values)}")
    if len(frames) != 7:
        raise ValueError("场景表格数量不一致")
    v = dict(zip(UI_KEYS, values, strict=True))
    targets, zones, interferers, materials, reflectors, apertures, cavities = frames
    base = CAEProject.from_dict(state)
    project = replace(
        base,
        meta=replace(base.meta, name=str(v["project_name"]), seed=int(v["seed"])),
        array=replace(
            base.array,
            nx=int(v["nx"]), ny=int(v["ny"]), frequency_ghz=float(v["frequency_ghz"]),
            spacing_x_lambda=float(v["spacing_x_lambda"]), spacing_y_lambda=float(v["spacing_y_lambda"]),
        ),
        plane=replace(
            base.plane,
            z_lambda=float(v["z_lambda"]), span_x_lambda=float(v["span_x_lambda"]),
            span_y_lambda=float(v["span_y_lambda"]), samples=int(v["samples"]),
        ),
        propagation=replace(
            base.propagation,
            backend=str(v["propagation_backend"]),
            direct_path_scale=float(v["direct_path_scale"]),
            reflection_scale=float(v["reflection_scale"]),
            cavity_scale=float(v["cavity_scale"]),
            maximum_modes=int(v["maximum_modes"]),
        ),
        solver=replace(
            base.solver,
            method=str(v["solver_method"]), iterations=int(v["iterations"]),
            target_amplitude=float(v["target_amplitude"]), outside_peak_limit_db=float(v["outside_peak_limit_db"]),
            uncertainty_scenarios=int(v["uncertainty_scenarios"]), gain_std_percent=float(v["gain_std_percent"]),
            phase_std_deg=float(v["phase_std_deg"]), registration_jitter_lambda=float(v["registration_jitter_lambda"]),
            pa_enabled=bool(v["pa_enabled"]), dpd_enabled=bool(v["dpd_enabled"] and v["pa_enabled"]),
        ),
        perception=replace(
            base.perception,
            method=str(v["perception_method"]), snr_db=float(v["snr_db"]), snapshots=int(v["snapshots"]),
            fault_count=int(v["fault_count"]), prior_sigma_deg=float(v["prior_sigma_deg"]),
            prior_strength=float(v["prior_strength"]),
        ),
        protection=replace(
            base.protection,
            method=str(v["protection_method"]), desired_theta_deg=float(v["desired_theta_deg"]),
            desired_phi_deg=float(v["desired_phi_deg"]), interferer_power_db=float(v["interferer_power_db"]),
            sector_scale=float(v["sector_scale"]), soft_strength=float(v["soft_strength"]),
        ),
        workflow=replace(base.workflow, parallel_workers=int(v["parallel_workers"])),
    )
    project = apply_object_frames(
        project,
        _internal_frame(targets, TARGET_COLUMNS),
        _internal_frame(zones, ZONE_COLUMNS),
        _internal_frame(interferers, INTERFERER_COLUMNS),
    )
    project = apply_environment_frames(project, materials, reflectors, apertures, cavities)
    return project


def _ui_values(project: CAEProject) -> list[Any]:
    return [
        project.meta.name, project.meta.seed, project.array.frequency_ghz, project.array.nx, project.array.ny,
        project.array.spacing_x_lambda, project.array.spacing_y_lambda,
        project.plane.z_lambda, project.plane.span_x_lambda, project.plane.span_y_lambda, project.plane.samples,
        project.propagation.backend, project.propagation.direct_path_scale, project.propagation.reflection_scale,
        project.propagation.cavity_scale, project.propagation.maximum_modes,
        project.solver.method, project.solver.iterations, project.solver.target_amplitude,
        project.solver.outside_peak_limit_db, project.solver.uncertainty_scenarios,
        project.solver.gain_std_percent, project.solver.phase_std_deg, project.solver.registration_jitter_lambda,
        project.solver.pa_enabled, project.solver.dpd_enabled,
        project.perception.method, project.perception.snr_db, project.perception.snapshots,
        project.perception.fault_count, project.perception.prior_sigma_deg, project.perception.prior_strength,
        project.protection.method, project.protection.desired_theta_deg, project.protection.desired_phi_deg,
        project.protection.interferer_power_db, project.protection.sector_scale, project.protection.soft_strength,
        project.workflow.parallel_workers,
    ]


def _backend_summary_frame(project: CAEProject) -> pd.DataFrame:
    return pd.DataFrame([get_field_backend(project.propagation.backend).summary(project).to_dict()])


_中文列名 = {
    "object_type": "对象类型", "object_id": "对象标识", "name": "对象名称",
    "priority": "优先级", "setpoint_or_cap": "设定值或上限", "mean_amplitude": "平均幅度",
    "rmse_percent": "RMSE/%", "coverage_percent": "覆盖率/%",
    "p95_deviation_percent": "P95偏差/%", "p95_db": "P95/dB", "peak_db": "峰值/dB",
    "limit_db": "限值/dB", "violation_db": "超限量/dB", "success": "是否通过",
    "controller": "控制器", "frames": "帧数", "frame": "帧序号",
    "mean_tracking_error_lambda": "平均跟踪误差/λ", "mean_target_rmse_percent": "平均目标区RMSE/%",
    "mean_target_coverage_percent": "平均目标覆盖率/%", "mean_protected_p95_db": "平均保护区P95/dB",
    "mean_response_proxy": "平均响应代理", "availability_percent": "可用率/%",
    "median_frame_runtime_ms": "单帧耗时中位数/ms", "true_x_lambda": "真实x/λ",
    "true_y_lambda": "真实y/λ", "design_x_lambda": "设计x/λ", "design_y_lambda": "设计y/λ",
    "tracking_error_lambda": "跟踪误差/λ", "target_rmse_percent": "目标区RMSE/%",
    "target_coverage_percent": "目标覆盖率/%", "peak_outside_db": "区外峰值/dB",
    "protected_p95_db": "保护区P95/dB", "target_response_proxy": "目标响应代理",
    "control_success": "控制判据", "runtime_ms": "耗时/ms",
    "index": "序号", "risk_multiplier": "风险倍率",
    "worst_target_rmse_percent": "最差目标RMSE/%",
    "minimum_target_coverage_percent": "最低目标覆盖率/%",
    "target_fairness_gap_percent": "目标公平性差值/百分点",
    "outside_limit_db": "区外限值/dB", "outside_violation_db": "区外超限量/dB",
    "maximum_protected_violation_db": "最坏保护区超限/dB", "risk_violation_db": "风险超限/dB",
    "sampled_plane_efficiency_percent": "采样平面能量占比/%", "pareto": "帕累托点",
    "recommended": "推荐点", "sensing_quality": "感知质量",
    "receive_protection_quality": "接收防护质量", "field_control_quality": "控场质量",
    "protected_margin_score": "保护区裕量评分", "normalized_mission_score": "归一化任务评分",
    "full_chain_available": "全链路可用", "job_id": "任务标识", "created_utc": "创建时间/UTC",
    "updated_utc": "更新时间/UTC", "project_name": "工程名称", "status": "状态",
    "requested_workers": "工作进程数", "total": "总算例数", "completed": "已完成",
    "failed": "失败", "pending": "待运行", "running": "运行中", "message": "消息",
    "item_id": "算例标识", "item_index": "算例序号", "parameter_value": "参数值",
    "replicate": "重复序号", "seed": "随机种子", "started_utc": "开始时间/UTC",
    "finished_utc": "结束时间/UTC", "error_text": "错误信息", "worker_name": "工作进程",
}

_中文状态 = {
    "target": "目标区", "protected": "保护区", "completed": "已完成",
    "completed_with_errors": "完成但有错误", "running": "运行中", "pending": "待运行",
    "queued": "已排队", "paused": "已暂停", "pause_requested": "正在暂停",
    "failed": "失败", "cancelled": "已取消", "true": "是", "false": "否",
}


def _中文化表格(frame: pd.DataFrame | None) -> pd.DataFrame:
    """仅在界面层翻译列名与状态；原始导出仍保留稳定机器字段。"""
    if frame is None:
        return pd.DataFrame()
    output = frame.copy().rename(columns=_中文列名)
    for column in output.columns:
        if output[column].dtype == object or str(output[column].dtype) == "bool":
            output[column] = output[column].map(
                lambda value: _中文状态.get(str(value).lower(), value) if value is not None else value
            )
    return output


def _中文状态文字(value: object) -> str:
    return str(_中文状态.get(str(value).lower(), value))


def _sync_callback(state: dict, *args: Any):
    try:
        values = args[:len(UI_KEYS)]
        frames = args[len(UI_KEYS):]
        project = _project_from_ui(state, values, frames)
        detail = (
            f"{project.array.nx * project.array.ny} 阵元 · {len(project.targets)} 个目标区 · "
            f"{len(project.protected_zones)} 个保护区 · {len(project.active_reflectors)} 个反射面 · "
            f"{len(project.active_apertures)} 个孔缝 · {len(project.active_cavities)} 个腔体"
        )
        return (
            project.to_dict(), make_scene_figure(project), environment_summary_markdown(project),
            _backend_summary_frame(project), project.to_dict(), _status("场景已同步", detail),
        )
    except Exception as exc:
        project = CAEProject.from_dict(state)
        return (
            state, make_empty_result_figure("场景参数错误", str(exc)), environment_summary_markdown(project),
            _backend_summary_frame(project), state, _status("参数校验失败", str(exc), "error"),
        )


def _static_callback(state: dict, *args: Any):
    try:
        project = _project_from_ui(state, args[:len(UI_KEYS)], args[len(UI_KEYS):])
        result = solve_project(project)
        _, report, archive = export_result_bundle(result, RUN_ROOT)
        detail = (
            f"传播后端：{result.metrics['propagation_backend_name']}；目标区 RMSE {result.metrics['target_rmse_percent']:.2f}%；"
            f"区外峰值 {result.metrics['peak_outside_db']:.2f} dB。"
        )
        return (
            project.to_dict(), result, make_metric_cards_html(result), make_field_figure(result),
            make_constraint_margin_figure(result), make_object_metrics_figure(result), make_cut_figure(result),
            make_far_field_figure(result), make_weights_figure(result), make_convergence_figure(result),
            result.metrics_frame(), _中文化表格(result.object_metrics_frame()), "\n".join(result.log_lines),
            str(report), str(archive), _status("静态控场求解完成", detail, "ok" if result.metrics["control_success"] else "warn"),
        )
    except Exception as exc:
        empty = make_empty_result_figure("求解失败", str(exc))
        return (
            state, None, "", empty, empty, empty, empty, empty, empty, empty,
            pd.DataFrame([{"错误": str(exc)}]), pd.DataFrame(), traceback.format_exc(), None, None,
            _status("静态求解失败", str(exc), "error"),
        )


def _backend_callback(state: dict, fast_mode: bool, selected: list[str] | None, *args: Any):
    try:
        project = _project_from_ui(state, args[:len(UI_KEYS)], args[len(UI_KEYS):])
        comparison = run_backend_comparison(project, selected or list(project.propagation.comparison_backends), fast_mode=bool(fast_mode))
        _, report, archive = export_backend_comparison(comparison, BACKEND_ROOT)
        best = comparison.records.sort_values("目标区RMSE/%").iloc[0]
        detail = f"完成 {len(comparison.results)} 个后端；当前快速配置下 RMSE 最低为 {best['传播后端']}（{best['目标区RMSE/%']:.2f}%）。"
        return (
            project.to_dict(), comparison, make_backend_gallery(comparison), make_backend_metrics_figure(comparison),
            make_propagation_mechanism_figure(project), comparison.records, "\n".join(comparison.log_lines),
            str(report), str(archive), _status("传播后端对比完成", detail),
        )
    except Exception as exc:
        empty = make_empty_result_figure("传播后端对比失败", str(exc))
        return state, None, empty, empty, empty, pd.DataFrame([{"错误": str(exc)}]), traceback.format_exc(), None, None, _status("传播后端对比失败", str(exc), "error")


def _live_callback(state: dict, *args: Any):
    try:
        project = _project_from_ui(state, args[:len(UI_KEYS)], args[len(UI_KEYS):])
        perception = run_live_perception(project)
        protection = run_live_protection(project, perception)
        detail = (
            f"测向 RMSE {perception.metrics['rmse_deg']:.3f}°；输出 SINR {protection.metrics['output_sinr_db']:.2f} dB；"
            f"最坏真实干扰响应 {protection.metrics['worst_true_response_db']:.2f} dB。"
        )
        return (
            project.to_dict(), perception, protection, make_live_metric_cards(perception, protection),
            make_perception_spectrum(perception), make_perception_diagnostics(perception), make_perception_comparison(perception),
            perception.estimates_frame(), perception.comparison_frame(), make_protection_map(protection),
            make_protection_comparison(protection), protection.comparison_frame(),
            "\n".join((*perception.log_lines, *protection.log_lines)),
            _status("感知—接收防护链路完成", detail, "ok" if protection.metrics["protection_success"] else "warn"),
        )
    except Exception as exc:
        empty = make_empty_result_figure("感知—防护链路失败", str(exc))
        return state, None, None, "", empty, empty, empty, pd.DataFrame([{"错误": str(exc)}]), pd.DataFrame(), empty, empty, pd.DataFrame(), traceback.format_exc(), _status("感知—防护链路失败", str(exc), "error")


def _workflow_callback(state: dict, selected: list[str] | None, *args: Any):
    try:
        project = _project_from_ui(state, args[:len(UI_KEYS)], args[len(UI_KEYS):])
        result = execute_workflow(project, selected or default_selection(), export_root=WORKFLOW_ROOT)
        effect = pd.DataFrame([result.effect_metrics])
        return (
            project.to_dict(), result, make_task_graph_figure(result.selected_nodes, statuses=result.statuses),
            _中文化表格(result.task_frame()), _中文化表格(effect), "\n".join(result.log_lines), str(result.report_path), str(result.archive_path),
            _status("一键全链路执行完成", f"归一化任务评分 {float(result.effect_metrics.get('normalized_mission_score', 0.0)):.3f}。"),
        )
    except Exception as exc:
        return state, None, make_task_graph_figure(selected or default_selection()), pd.DataFrame([{"错误": str(exc)}]), pd.DataFrame(), traceback.format_exc(), None, None, _status("全链路执行失败", str(exc), "error")


def _timeline_callback(state: dict, *args: Any):
    try:
        project = _project_from_ui(state, args[:len(UI_KEYS)], args[len(UI_KEYS):])
        result = run_timeline(project)
        report, archive = export_timeline(result, TIMELINE_ROOT)
        summary = pd.DataFrame([{"指标": key, "数值": value} for key, value in result.summary().items()])
        return (
            result, make_timeline_animation(result), make_timeline_metrics_figure(result), make_trajectory_figure(result),
            _中文化表格(summary), _中文化表格(result.metrics), "\n".join(result.log_lines), str(report), str(archive),
            _status("动态时间轴完成", f"{result.n_frames} 帧；平均目标区 RMSE {result.summary()['mean_target_rmse_percent']:.2f}%。"),
        )
    except Exception as exc:
        empty = make_empty_result_figure("动态时间轴失败", str(exc))
        return None, empty, empty, empty, pd.DataFrame([{"错误": str(exc)}]), pd.DataFrame(), traceback.format_exc(), None, None, _status("动态时间轴失败", str(exc), "error")


def _pareto_callback(state: dict, fast_mode: bool, *args: Any):
    try:
        project = _project_from_ui(state, args[:len(UI_KEYS)], args[len(UI_KEYS):])
        study = run_pareto_study(project, fast_mode=bool(fast_mode))
        _, report, archive = export_pareto_bundle(study, PARETO_ROOT)
        record = study.recommended_record
        detail = (
            f"推荐风险倍率 {float(record['risk_multiplier']):.3g}；最差目标 RMSE "
            f"{float(record['worst_target_rmse_percent']):.2f}%。"
        )
        return (
            study, make_pareto_figure(study), make_tradeoff_figure(study), make_pareto_field_gallery(study),
            _中文化表格(study.records), "\n".join(study.log_lines), str(report), str(archive), _status("帕累托扫描完成", detail),
        )
    except Exception as exc:
        empty = make_empty_result_figure("帕累托扫描失败", str(exc))
        return None, empty, empty, empty, pd.DataFrame([{"错误": str(exc)}]), traceback.format_exc(), None, None, _status("帕累托扫描失败", str(exc), "error")


def _save_callback(state: dict, *args: Any):
    try:
        project = _project_from_ui(state, args[:len(UI_KEYS)], args[len(UI_KEYS):])
        path = export_project_file(project, PROJECT_DIR)
        return project.to_dict(), str(path), _status("工程已保存", path.name)
    except Exception as exc:
        return state, None, _status("工程保存失败", str(exc), "error")


def _load_callback(path: Any):
    if not path:
        raise gr.Error("请选择工程 YAML 文件")
    filename = getattr(path, "name", path)
    try:
        project = CAEProject.load_yaml(filename)
        targets, zones, interferers = _object_frames(project)
        materials, reflectors, apertures, cavities = project_to_environment_frames(project)
        return (
            *_ui_values(project), targets, zones, interferers, materials, reflectors, apertures, cavities,
            project.to_dict(), make_scene_figure(project), environment_summary_markdown(project),
            _backend_summary_frame(project), project.to_dict(), _status("工程已载入", Path(filename).name),
        )
    except Exception as exc:
        raise gr.Error(f"工程载入失败：{exc}") from exc


def _queue_submit_callback(
    state: dict, parameter: str, start: float, stop: float, points: int, replicates: int,
    metric: str, fast_mode: bool, auto_start: bool, *args: Any,
):
    try:
        project = _project_from_ui(state, args[:len(UI_KEYS)], args[len(UI_KEYS):])
        spec = SweepSpec(
            parameter=parameter, start=float(start), stop=float(stop), points=int(points),
            replicates=int(replicates), metric=metric, fast_mode=bool(fast_mode),
        )
        job_id = QUEUE.submit_sweep(project, spec, workers=project.workflow.parallel_workers)
        if auto_start:
            QUEUE.start(job_id)
        return job_id, _中文化表格(QUEUE.jobs()), _中文化表格(QUEUE.items(job_id)), _status("批量任务已提交", f"任务 {job_id}；共 {points * replicates} 个算例。")
    except Exception as exc:
        return "", _中文化表格(QUEUE.jobs()), pd.DataFrame(), _status("任务提交失败", str(exc), "error")


def _queue_action(job_id: str, action: str, workers: int):
    try:
        if not job_id:
            raise ValueError("请先提交或输入任务标识")
        if action == "pause":
            QUEUE.pause(job_id)
        elif action == "resume":
            QUEUE.resume(job_id, workers=int(workers))
        elif action == "cancel":
            QUEUE.cancel(job_id)
        elif action == "run":
            QUEUE.start(job_id)
        row = QUEUE.job(job_id)
        return _中文化表格(QUEUE.jobs()), _中文化表格(QUEUE.items(job_id)), _status(f"任务状态：{_中文状态文字(row['status'])}", row.get("message") or job_id)
    except Exception as exc:
        return _中文化表格(QUEUE.jobs()), pd.DataFrame(), _status("队列操作失败", str(exc), "error")


def _queue_refresh(job_id: str):
    try:
        items = QUEUE.items(job_id) if job_id else pd.DataFrame()
        detail = QUEUE.job(job_id) if job_id else {"status": "空闲", "message": "尚未选择任务"}
        return _中文化表格(QUEUE.jobs()), _中文化表格(items), _status(f"任务状态：{_中文状态文字(detail['status'])}", detail.get("message") or "")
    except Exception as exc:
        return _中文化表格(QUEUE.jobs()), pd.DataFrame(), _status("队列刷新失败", str(exc), "error")


def _drop_last(frame: Any, headers: list[str]) -> pd.DataFrame:
    data = frame.copy() if isinstance(frame, pd.DataFrame) else pd.DataFrame(frame, columns=headers)
    if len(data) > 1:
        data = data.iloc[:-1].reset_index(drop=True)
    return data


def _add_object(frame: Any, kind: str) -> pd.DataFrame:
    mapping = {
        "target": (TARGET_COLUMNS, TARGET_HEADERS, add_target_row),
        "zone": (ZONE_COLUMNS, ZONE_HEADERS, add_zone_row),
        "interferer": (INTERFERER_COLUMNS, INTERFERER_HEADERS, add_interferer_row),
    }
    columns, headers, function = mapping[kind]
    internal = _internal_frame(frame, columns)
    return _display_frame(function(internal), headers)


def _initial_project() -> CAEProject:
    path = PROJECT_ROOT / "configs" / "cae_project_v13.yaml"
    try:
        return CAEProject.load_yaml(path) if path.exists() else default_project()
    except Exception:
        return default_project()


def build_app() -> gr.Blocks:
    initial = _initial_project()
    target_frame, zone_frame, interferer_frame = _object_frames(initial)
    material_frame, reflector_frame, aperture_frame, cavity_frame = project_to_environment_frames(initial)
    empty = make_empty_result_figure("尚未运行", "请先同步场景，再运行相应求解任务。")

    with gr.Blocks(title="HPM 数字化电磁算法 CAE V1.3") as demo:
        project_state = gr.State(initial.to_dict())
        static_state = gr.State()
        backend_state = gr.State()
        perception_state = gr.State()
        protection_state = gr.State()
        workflow_state = gr.State()
        timeline_state = gr.State()
        pareto_state = gr.State()

        gr.Navbar(
            value=[
                ("平台说明", "#平台说明"),
                ("传播后端", "#传播后端"),
                ("数值边界", "#数值边界"),
            ],
            main_page_name="HPM 数字化电磁算法 CAE V1.3",
        )
        gr.Markdown(
            "# HPM 数字化电磁算法 CAE V1.3\n"
            "**全中文工作台 · 插件式场求解后端 · 多对象约束控场 · 实时感知防护 · 批量实验管理**\n\n"
            "> 本平台采用开源 Gradio Ocean 界面模板与原生组件。计算结果仅用于归一化算法研究。",
            elem_id="平台说明",
        )

        with gr.Sidebar(label="工程参数与求解设置", open=True, width=380):
            with gr.Accordion("工程信息", open=True):
                project_name = gr.Textbox(value=initial.meta.name, label="工程名称")
                seed = gr.Number(value=initial.meta.seed, precision=0, label="随机种子")
            with gr.Accordion("阵列与观察面", open=True):
                frequency = gr.Number(value=initial.array.frequency_ghz, label="工作频率/GHz")
                with gr.Row():
                    nx = gr.Slider(2, 32, value=initial.array.nx, step=1, label="x方向阵元数")
                    ny = gr.Slider(2, 32, value=initial.array.ny, step=1, label="y方向阵元数")
                with gr.Row():
                    spacing_x = gr.Number(value=initial.array.spacing_x_lambda, label="x间距/λ")
                    spacing_y = gr.Number(value=initial.array.spacing_y_lambda, label="y间距/λ")
                z_lambda = gr.Number(value=initial.plane.z_lambda, label="观察面距离/λ")
                with gr.Row():
                    span_x = gr.Number(value=initial.plane.span_x_lambda, label="观察面x跨度/λ")
                    span_y = gr.Number(value=initial.plane.span_y_lambda, label="观察面y跨度/λ")
                samples = gr.Slider(31, 181, value=initial.plane.samples, step=2, label="单轴网格点数")
            with gr.Accordion("传播后端", open=True):
                propagation_backend = gr.Dropdown(choices=list(backend_choices()), value=initial.propagation.backend, label="场求解后端")
                with gr.Row():
                    direct_path_scale = gr.Number(value=initial.propagation.direct_path_scale, label="直达分量系数")
                    reflection_scale = gr.Number(value=initial.propagation.reflection_scale, label="反射分量系数")
                with gr.Row():
                    cavity_scale = gr.Number(value=initial.propagation.cavity_scale, label="腔体分量系数")
                    maximum_modes = gr.Slider(1, 32, value=initial.propagation.maximum_modes, step=1, label="最大降阶模态数")
            with gr.Accordion("空间控场求解器", open=False):
                solver_method = gr.Dropdown(choices=SOLVER_CHOICES, value=initial.solver.method, label="求解方法")
                iterations = gr.Slider(20, 1500, value=initial.solver.iterations, step=20, label="优化迭代次数")
                target_amplitude = gr.Number(value=initial.solver.target_amplitude, label="目标归一化幅度")
                outside_peak_limit = gr.Number(value=initial.solver.outside_peak_limit_db, label="区外峰值上限/dB")
                uncertainty_scenarios = gr.Slider(1, 32, value=initial.solver.uncertainty_scenarios, step=1, label="鲁棒场景数")
                with gr.Row():
                    gain_std = gr.Number(value=initial.solver.gain_std_percent, label="增益误差标准差/%")
                    phase_std = gr.Number(value=initial.solver.phase_std_deg, label="相位误差标准差/°")
                registration_jitter = gr.Number(value=initial.solver.registration_jitter_lambda, label="配准抖动标准差/λ")
                with gr.Row():
                    pa_enabled = gr.Checkbox(value=initial.solver.pa_enabled, label="启用归一化功放")
                    dpd_enabled = gr.Checkbox(value=initial.solver.dpd_enabled, label="启用数字预失真")
            with gr.Accordion("感知与接收防护", open=False):
                perception_method = gr.Dropdown(choices=list(PerceptionSpec.METHODS), value=initial.perception.method, label="测向方法")
                with gr.Row():
                    snr_db = gr.Number(value=initial.perception.snr_db, label="归一化信噪比/dB")
                    snapshots = gr.Slider(16, 1024, value=initial.perception.snapshots, step=16, label="快拍数")
                with gr.Row():
                    fault_count = gr.Slider(0, 16, value=initial.perception.fault_count, step=1, label="异常通道数")
                    prior_sigma = gr.Number(value=initial.perception.prior_sigma_deg, label="先验标准差/°")
                prior_strength = gr.Number(value=initial.perception.prior_strength, label="先验强度")
                protection_method = gr.Dropdown(choices=PROTECTION_CHOICES, value=initial.protection.method, label="接收防护方法")
                with gr.Row():
                    desired_theta = gr.Number(value=initial.protection.desired_theta_deg, label="期望方向θ/°")
                    desired_phi = gr.Number(value=initial.protection.desired_phi_deg, label="期望方向φ/°")
                interferer_power = gr.Number(value=initial.protection.interferer_power_db, label="相对干扰功率/dB")
                with gr.Row():
                    sector_scale = gr.Number(value=initial.protection.sector_scale, label="置信扇区尺度")
                    soft_strength = gr.Number(value=initial.protection.soft_strength, label="软加载强度")
            parallel_workers = gr.Slider(1, 8, value=initial.workflow.parallel_workers, step=1, label="并行工作进程数")
            sync_button = gr.Button("同步并校验场景", variant="primary")
            status_markdown = gr.Markdown(_status("工程已就绪", "请选择传播后端并编辑场景对象。"))

        with gr.Tabs():
            with gr.Tab("场景建模"):
                with gr.Row():
                    scene_plot = gr.Plot(make_scene_figure(initial), label="三维场景")
                    with gr.Column(scale=1):
                        environment_summary = gr.Markdown(environment_summary_markdown(initial))
                        backend_summary = gr.Dataframe(_backend_summary_frame(initial), label="当前传播后端摘要", interactive=False, show_row_numbers=False)
                        gr.Markdown(
                            "### 数值边界\n"
                            "仅处理波长尺度几何、归一化标量复场、相对阵列响应和无量纲评价。"
                            "不输出绝对源功率、具体器件阈值、现实毁伤概率或作用距离。",
                            elem_id="数值边界",
                        )
                with gr.Tabs():
                    with gr.Tab("目标区"):
                        target_table = gr.Dataframe(target_frame, headers=TARGET_HEADERS, label="目标区对象", interactive=True, show_row_numbers=True, wrap=True)
                        with gr.Row():
                            add_target = gr.Button("新增目标区")
                            drop_target = gr.Button("删除末行")
                    with gr.Tab("保护区"):
                        zone_table = gr.Dataframe(zone_frame, headers=ZONE_HEADERS, label="保护区对象", interactive=True, show_row_numbers=True, wrap=True)
                        with gr.Row():
                            add_zone = gr.Button("新增保护区")
                            drop_zone = gr.Button("删除末行")
                    with gr.Tab("辐射源"):
                        interferer_table = gr.Dataframe(interferer_frame, headers=INTERFERER_HEADERS, label="辐射源对象", interactive=True, show_row_numbers=True, wrap=True)
                        with gr.Row():
                            add_interferer = gr.Button("新增辐射源")
                            drop_interferer = gr.Button("删除末行")
                    with gr.Tab("材料库"):
                        material_table = gr.Dataframe(material_frame, headers=MATERIAL_HEADERS, label="材料代理库", interactive=True, show_row_numbers=True, wrap=True)
                        add_material = gr.Button("新增材料")
                    with gr.Tab("反射面"):
                        reflector_table = gr.Dataframe(reflector_frame, headers=REFLECTOR_HEADERS, label="镜像反射平面", interactive=True, show_row_numbers=True, wrap=True)
                        with gr.Row():
                            add_reflector = gr.Button("新增反射面")
                            drop_reflector = gr.Button("删除末行")
                    with gr.Tab("孔缝"):
                        aperture_table = gr.Dataframe(aperture_frame, headers=APERTURE_HEADERS, label="等效孔缝", interactive=True, show_row_numbers=True, wrap=True)
                        with gr.Row():
                            add_aperture = gr.Button("新增孔缝")
                            drop_aperture = gr.Button("删除末行")
                    with gr.Tab("腔体"):
                        cavity_table = gr.Dataframe(cavity_frame, headers=CAVITY_HEADERS, label="降阶腔体", interactive=True, show_row_numbers=True, wrap=True)
                        with gr.Row():
                            add_cavity = gr.Button("新增腔体")
                            drop_cavity = gr.Button("删除末行")

            with gr.Tab("传播后端", elem_id="传播后端"):
                gr.Markdown("## 插件式传播模型对比\n在同一工程、同一阵列与同一优化约束下，对比不同传播矩阵后端。")
                with gr.Row():
                    backend_selection = gr.CheckboxGroup(choices=list(backend_choices()), value=list(initial.propagation.comparison_backends), label="参与对比的传播后端")
                    backend_fast = gr.Checkbox(value=True, label="快速工程验收模式")
                    backend_run = gr.Button("运行传播后端对比", variant="primary")
                mechanism_plot = gr.Plot(make_propagation_mechanism_figure(initial), label="传播机理交互预览")
                backend_gallery = gr.Plot(empty, label="场分布对比")
                backend_metrics_plot = gr.Plot(empty, label="性能概览")
                backend_records = gr.Dataframe(pd.DataFrame(), label="传播后端指标", interactive=False, show_row_numbers=False)
                backend_log = gr.Code(value="", language="shell", label="传播后端运行日志", lines=8, max_lines=30, interactive=False, show_line_numbers=False)
                with gr.Row():
                    backend_report = gr.DownloadButton("下载传播后端对比报告", value=None)
                    backend_archive = gr.DownloadButton("下载传播后端对比数据包", value=None, variant="primary")

            with gr.Tab("静态控场"):
                static_run = gr.Button("运行静态多对象控场", variant="primary")
                static_cards = gr.HTML("")
                with gr.Tabs():
                    with gr.Tab("场分布"):
                        field_plot = gr.Plot(empty, label="观察面场分布")
                    with gr.Tab("约束裕量"):
                        constraint_plot = gr.Plot(empty, label="约束裕量图")
                    with gr.Tab("对象级指标"):
                        object_metric_plot = gr.Plot(empty, label="对象级指标图")
                    with gr.Tab("目标截线"):
                        cut_plot = gr.Plot(empty, label="目标截线图")
                    with gr.Tab("远场方向图"):
                        far_plot = gr.Plot(empty, label="远场方向图")
                    with gr.Tab("阵元激励"):
                        weights_plot = gr.Plot(empty, label="阵元激励图")
                    with gr.Tab("收敛历史"):
                        convergence_plot = gr.Plot(empty, label="收敛历史图")
                with gr.Row():
                    static_metrics = gr.Dataframe(pd.DataFrame(), label="总体指标", interactive=False, show_row_numbers=False)
                    object_metrics_table = gr.Dataframe(pd.DataFrame(), label="对象约束", interactive=False, show_row_numbers=False)
                static_log = gr.Code(value="", language="shell", label="求解日志", lines=9, max_lines=30, interactive=False, show_line_numbers=False)
                with gr.Row():
                    static_report = gr.DownloadButton("下载静态求解报告", value=None)
                    static_archive = gr.DownloadButton("下载完整静态求解数据包", value=None, variant="primary")

            with gr.Tab("感知与接收防护"):
                live_run = gr.Button("运行实时感知—接收防护链路", variant="primary")
                live_cards = gr.HTML("")
                with gr.Tabs():
                    with gr.Tab("二维空间谱"):
                        perception_spectrum = gr.Plot(empty, label="二维空间谱")
                    with gr.Tab("感知诊断"):
                        perception_diag = gr.Plot(empty, label="感知诊断图")
                    with gr.Tab("测向基线对比"):
                        perception_compare = gr.Plot(empty, label="测向基线对比图")
                    with gr.Tab("接收响应图"):
                        protection_map = gr.Plot(empty, label="接收响应图")
                    with gr.Tab("防护方法对比"):
                        protection_compare = gr.Plot(empty, label="防护方法对比图")
                with gr.Row():
                    perception_estimates = gr.Dataframe(pd.DataFrame(), label="路径估计", interactive=False, show_row_numbers=False)
                    perception_methods = gr.Dataframe(pd.DataFrame(), label="测向方法对比", interactive=False, show_row_numbers=False)
                protection_methods = gr.Dataframe(pd.DataFrame(), label="接收防护方法对比", interactive=False, show_row_numbers=False)
                live_log = gr.Code(value="", language="shell", label="感知与防护日志", lines=10, max_lines=32, interactive=False, show_line_numbers=False)

            with gr.Tab("全链路任务"):
                task_selection = gr.CheckboxGroup(choices=node_choices(), value=default_selection(), label="选择任务节点")
                workflow_run = gr.Button("一键执行所选全链路", variant="primary")
                task_graph = gr.Plot(make_task_graph_figure(), label="任务依赖图")
                task_plan = gr.Dataframe(GRAPH.compile_plan(default_selection()), label="执行计划", interactive=False, show_row_numbers=False)
                effect_table = gr.Dataframe(pd.DataFrame(), label="归一化任务评价", interactive=False, show_row_numbers=False)
                workflow_log = gr.Code(value="", language="shell", label="全链路日志", lines=10, max_lines=32, interactive=False, show_line_numbers=False)
                with gr.Row():
                    workflow_report = gr.DownloadButton("下载全链路报告", value=None)
                    workflow_archive = gr.DownloadButton("下载全链路数据包", value=None, variant="primary")

            with gr.Tab("动态与帕累托"):
                with gr.Tabs():
                    with gr.Tab("动态时间轴"):
                        timeline_run = gr.Button("运行动态时间轴", variant="primary")
                        timeline_animation = gr.Plot(empty, label="动态时间轴场分布")
                        with gr.Row():
                            timeline_metrics_plot = gr.Plot(empty, label="动态指标曲线")
                            trajectory_plot = gr.Plot(empty, label="目标轨迹图")
                        timeline_summary = gr.Dataframe(pd.DataFrame(), label="动态摘要", interactive=False, show_row_numbers=False)
                        timeline_records = gr.Dataframe(pd.DataFrame(), label="逐帧指标", interactive=False, show_row_numbers=False)
                        timeline_log = gr.Code(value="", language="shell", label="动态求解日志", lines=8, max_lines=30, interactive=False, show_line_numbers=False)
                        with gr.Row():
                            timeline_report = gr.DownloadButton("下载动态报告", value=None)
                            timeline_archive = gr.DownloadButton("下载动态数据包", value=None)
                    with gr.Tab("帕累托设计空间"):
                        with gr.Row():
                            pareto_fast = gr.Checkbox(value=True, label="快速模式")
                            pareto_run = gr.Button("运行帕累托扫描", variant="primary")
                        pareto_plot = gr.Plot(empty, label="帕累托前沿")
                        tradeoff_plot = gr.Plot(empty, label="约束折中图")
                        pareto_gallery = gr.Plot(empty, label="推荐解场分布")
                        pareto_records = gr.Dataframe(pd.DataFrame(), label="帕累托记录", interactive=False, show_row_numbers=False)
                        pareto_log = gr.Code(value="", language="shell", label="帕累托日志", lines=8, max_lines=30, interactive=False, show_line_numbers=False)
                        with gr.Row():
                            pareto_report = gr.DownloadButton("下载帕累托报告", value=None)
                            pareto_archive = gr.DownloadButton("下载帕累托数据包", value=None)

            with gr.Tab("批量任务队列"):
                gr.Markdown("任务逐算例写入本地 SQLite。暂停后不再派发新算例，恢复时从未完成检查点继续。")
                with gr.Row():
                    queue_parameter = gr.Dropdown(choices=[(value, key) for key, value in SWEEP_PARAMETERS.items()], value="solver.phase_std_deg", label="扫描变量")
                    queue_start = gr.Number(value=0, label="起点")
                    queue_stop = gr.Number(value=12, label="终点")
                    queue_points = gr.Slider(2, 15, value=5, step=1, label="参数点数")
                    queue_replicates = gr.Slider(1, 8, value=2, step=1, label="重复次数")
                with gr.Row():
                    queue_metric = gr.Dropdown(choices=[(value, key) for key, value in METRIC_LABELS.items()], value="target_rmse_percent", label="统计指标")
                    queue_fast = gr.Checkbox(value=True, label="快速模式")
                    queue_auto = gr.Checkbox(value=True, label="提交后立即运行")
                    queue_submit = gr.Button("提交批量任务", variant="primary")
                job_id = gr.Textbox(value="", label="当前任务标识")
                with gr.Row():
                    queue_run = gr.Button("运行")
                    queue_pause = gr.Button("暂停")
                    queue_resume = gr.Button("恢复")
                    queue_cancel = gr.Button("取消")
                    queue_refresh = gr.Button("刷新")
                queue_status = gr.Markdown(_status("队列空闲", "尚未提交任务。"))
                jobs_table = gr.Dataframe(QUEUE.jobs(), label="任务列表", interactive=False, show_row_numbers=False)
                items_table = gr.Dataframe(pd.DataFrame(), label="当前任务检查点", interactive=False, show_row_numbers=False, max_height=420)
                queue_db = gr.DownloadButton("下载任务队列数据库", value=str(QUEUE_DB))

            with gr.Tab("工程文件"):
                load_file = gr.File(label="选择工程 YAML", file_types=[".yaml", ".yml"], type="filepath")
                with gr.Row():
                    load_button = gr.Button("载入工程")
                    save_button = gr.Button("保存当前工程", variant="primary")
                project_download = gr.DownloadButton("下载工程 YAML", value=None)
                config_json = gr.JSON(initial.to_dict(), label="工程配置快照", open=False)

        ui_components = [
            project_name, seed, frequency, nx, ny, spacing_x, spacing_y,
            z_lambda, span_x, span_y, samples,
            propagation_backend, direct_path_scale, reflection_scale, cavity_scale, maximum_modes,
            solver_method, iterations, target_amplitude, outside_peak_limit, uncertainty_scenarios,
            gain_std, phase_std, registration_jitter, pa_enabled, dpd_enabled,
            perception_method, snr_db, snapshots, fault_count, prior_sigma, prior_strength,
            protection_method, desired_theta, desired_phi, interferer_power, sector_scale, soft_strength,
            parallel_workers,
        ]
        assert len(ui_components) == len(UI_KEYS)
        scene_frames = [target_table, zone_table, interferer_table, material_table, reflector_table, aperture_table, cavity_table]
        common_inputs = [project_state, *ui_components, *scene_frames]

        sync_button.click(
            _sync_callback,
            inputs=common_inputs,
            outputs=[project_state, scene_plot, environment_summary, backend_summary, config_json, status_markdown],
            show_progress="minimal",
        )
        static_run.click(
            _static_callback,
            inputs=common_inputs,
            outputs=[
                project_state, static_state, static_cards, field_plot, constraint_plot, object_metric_plot,
                cut_plot, far_plot, weights_plot, convergence_plot, static_metrics, object_metrics_table,
                static_log, static_report, static_archive, status_markdown,
            ],
            show_progress="full", concurrency_limit=1,
        )
        backend_run.click(
            _backend_callback,
            inputs=[project_state, backend_fast, backend_selection, *ui_components, *scene_frames],
            outputs=[
                project_state, backend_state, backend_gallery, backend_metrics_plot, mechanism_plot,
                backend_records, backend_log, backend_report, backend_archive, status_markdown,
            ],
            show_progress="full", concurrency_limit=1,
        )
        live_run.click(
            _live_callback,
            inputs=common_inputs,
            outputs=[
                project_state, perception_state, protection_state, live_cards, perception_spectrum,
                perception_diag, perception_compare, perception_estimates, perception_methods,
                protection_map, protection_compare, protection_methods, live_log, status_markdown,
            ],
            show_progress="full", concurrency_limit=1,
        )
        workflow_run.click(
            _workflow_callback,
            inputs=[project_state, task_selection, *ui_components, *scene_frames],
            outputs=[
                project_state, workflow_state, task_graph, task_plan, effect_table, workflow_log,
                workflow_report, workflow_archive, status_markdown,
            ],
            show_progress="full", concurrency_limit=1,
        )
        timeline_run.click(
            _timeline_callback,
            inputs=common_inputs,
            outputs=[
                timeline_state, timeline_animation, timeline_metrics_plot, trajectory_plot, timeline_summary,
                timeline_records, timeline_log, timeline_report, timeline_archive, status_markdown,
            ],
            show_progress="full", concurrency_limit=1,
        )
        pareto_run.click(
            _pareto_callback,
            inputs=[project_state, pareto_fast, *ui_components, *scene_frames],
            outputs=[pareto_state, pareto_plot, tradeoff_plot, pareto_gallery, pareto_records, pareto_log, pareto_report, pareto_archive, status_markdown],
            show_progress="full", concurrency_limit=1,
        )
        save_button.click(
            _save_callback,
            inputs=common_inputs,
            outputs=[project_state, project_download, status_markdown],
            show_progress="minimal",
        )
        load_button.click(
            _load_callback,
            inputs=[load_file],
            outputs=[
                *ui_components, *scene_frames, project_state, scene_plot, environment_summary,
                backend_summary, config_json, status_markdown,
            ],
            show_progress="minimal",
        )

        add_target.click(lambda frame: _add_object(frame, "target"), inputs=[target_table], outputs=[target_table])
        drop_target.click(lambda frame: _drop_last(frame, TARGET_HEADERS), inputs=[target_table], outputs=[target_table])
        add_zone.click(lambda frame: _add_object(frame, "zone"), inputs=[zone_table], outputs=[zone_table])
        drop_zone.click(lambda frame: _drop_last(frame, ZONE_HEADERS), inputs=[zone_table], outputs=[zone_table])
        add_interferer.click(lambda frame: _add_object(frame, "interferer"), inputs=[interferer_table], outputs=[interferer_table])
        drop_interferer.click(lambda frame: _drop_last(frame, INTERFERER_HEADERS), inputs=[interferer_table], outputs=[interferer_table])
        add_material.click(add_material_row, inputs=[material_table], outputs=[material_table])
        add_reflector.click(add_reflector_row, inputs=[reflector_table], outputs=[reflector_table])
        drop_reflector.click(lambda frame: _drop_last(frame, REFLECTOR_HEADERS), inputs=[reflector_table], outputs=[reflector_table])
        add_aperture.click(add_aperture_row, inputs=[aperture_table], outputs=[aperture_table])
        drop_aperture.click(lambda frame: _drop_last(frame, APERTURE_HEADERS), inputs=[aperture_table], outputs=[aperture_table])
        add_cavity.click(add_cavity_row, inputs=[cavity_table], outputs=[cavity_table])
        drop_cavity.click(lambda frame: _drop_last(frame, CAVITY_HEADERS), inputs=[cavity_table], outputs=[cavity_table])

        queue_submit.click(
            _queue_submit_callback,
            inputs=[
                project_state, queue_parameter, queue_start, queue_stop, queue_points, queue_replicates,
                queue_metric, queue_fast, queue_auto, *ui_components, *scene_frames,
            ],
            outputs=[job_id, jobs_table, items_table, queue_status],
            show_progress="minimal",
        )
        queue_run.click(lambda jid, workers: _queue_action(jid, "run", workers), inputs=[job_id, parallel_workers], outputs=[jobs_table, items_table, queue_status])
        queue_pause.click(lambda jid, workers: _queue_action(jid, "pause", workers), inputs=[job_id, parallel_workers], outputs=[jobs_table, items_table, queue_status])
        queue_resume.click(lambda jid, workers: _queue_action(jid, "resume", workers), inputs=[job_id, parallel_workers], outputs=[jobs_table, items_table, queue_status])
        queue_cancel.click(lambda jid, workers: _queue_action(jid, "cancel", workers), inputs=[job_id, parallel_workers], outputs=[jobs_table, items_table, queue_status])
        queue_refresh.click(_queue_refresh, inputs=[job_id], outputs=[jobs_table, items_table, queue_status])
        pa_enabled.change(lambda enabled: gr.update(value=bool(enabled), interactive=bool(enabled)), inputs=[pa_enabled], outputs=[dpd_enabled], show_progress="hidden")

    return demo


def launch(**kwargs: Any) -> None:
    app = build_app()
    options = {
        "server_name": "127.0.0.1",
        "server_port": 7860,
        "share": False,
        "inbrowser": True,
        "show_error": True,
        "allowed_paths": [str(PROJECT_ROOT)],
        "footer_links": [],
        "theme": gr.themes.Ocean(
            font=("Microsoft YaHei", "PingFang SC", "Noto Sans CJK SC", "system-ui", "sans-serif"),
            font_mono=("Cascadia Code", "Consolas", "monospace"),
        ),
    }
    options.update(kwargs)
    app.queue(default_concurrency_limit=4).launch(**options)

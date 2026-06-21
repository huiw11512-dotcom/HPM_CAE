"""Gradio-based local CAE workbench for HPM Digital Twin V0.9.

Launch with ``python run_ui_v09.py``.  The browser UI is defined entirely from
Python and runs locally; no cloud service or external model is required.
"""
from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Any, Sequence
import traceback

import gradio as gr
import pandas as pd

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
    ObservationPlaneSpec,
    ProjectMeta,
    ProtectedZoneSpec,
    SolverSpec,
    TargetRegionSpec,
    default_project,
)
from hpm_platform.ui.quick_solver import CAESolveResult, solve_project

PROJECT_ROOT = Path(__file__).resolve().parents[3]
UI_OUTPUT_ROOT = PROJECT_ROOT / "outputs_v09_ui" / "runs"
UI_PROJECT_ROOT = PROJECT_ROOT / "outputs_v09_ui" / "projects"

PARAMETER_KEYS = [
    "project_name",
    "seed",
    "frequency_ghz",
    "nx",
    "ny",
    "spacing_x_lambda",
    "spacing_y_lambda",
    "z_lambda",
    "span_x_lambda",
    "span_y_lambda",
    "samples",
    "target_center_x",
    "target_center_y",
    "target_major",
    "target_minor",
    "target_rotation",
    "guard_scale",
    "protected_enabled",
    "protected_center_x",
    "protected_center_y",
    "protected_radius",
    "method",
    "target_amplitude",
    "outside_penalty",
    "outside_hinge",
    "iterations",
    "learning_rate",
    "uncertainty_scenarios",
    "gain_std_percent",
    "phase_std_deg",
    "registration_jitter",
    "pa_enabled",
    "dpd_enabled",
    "pa_saturation",
    "pa_smoothness",
    "pa_phase_deg",
]

CSS = r"""
:root{--cae-bg:#07101d;--cae-panel:#0d1828;--cae-panel2:#111f33;--cae-line:#26354d;--cae-text:#e7eef9;--cae-muted:#91a2bb;--cae-cyan:#35d8ff;--cae-amber:#ffc857;--cae-green:#4ee0a5;--cae-red:#ff6b7a}
.gradio-container{max-width:none!important;background:var(--cae-bg)!important;color:var(--cae-text)!important;font-family:Inter,'Segoe UI','Microsoft YaHei',sans-serif!important}
footer{display:none!important}.contain{max-width:none!important}.app.svelte-182fdeq{padding:0!important}
#cae-topbar{background:linear-gradient(115deg,#0e2138,#07101d 72%);border-bottom:1px solid var(--cae-line);padding:14px 20px;margin:-16px -16px 12px!important}
.cae-topbar-inner{display:flex;align-items:center;justify-content:space-between;gap:18px}.cae-brand{display:flex;align-items:center;gap:12px}.cae-logo{width:38px;height:38px;border-radius:10px;background:linear-gradient(145deg,var(--cae-cyan),#4276ff);box-shadow:0 0 24px rgba(53,216,255,.23);display:flex;align-items:center;justify-content:center;font-weight:900;color:#03111b}.cae-title{font-size:18px;font-weight:750;letter-spacing:.2px}.cae-sub{font-size:12px;color:var(--cae-muted);margin-top:2px}.cae-badges{display:flex;gap:8px;flex-wrap:wrap}.cae-badge{font-size:11px;padding:5px 9px;border-radius:999px;border:1px solid rgba(53,216,255,.32);background:rgba(53,216,255,.08);color:var(--cae-cyan)}
#workbench-row{gap:10px!important;align-items:stretch!important}.cae-sidebar{background:var(--cae-panel)!important;border:1px solid var(--cae-line)!important;border-radius:10px!important;padding:9px!important;box-shadow:0 14px 36px rgba(0,0,0,.18)}#viewport-panel{background:var(--cae-panel)!important;border:1px solid var(--cae-line)!important;border-radius:10px!important;padding:8px!important;box-shadow:0 14px 36px rgba(0,0,0,.18)}
.cae-section-title{font-size:11px;text-transform:uppercase;letter-spacing:1.4px;color:var(--cae-muted);margin:2px 0 8px}.tree{font-size:13px;line-height:1.85;color:var(--cae-text);padding:4px 5px 8px}.tree .node{display:flex;align-items:center;gap:7px;padding:2px 5px;border-radius:5px}.tree .node.active{background:rgba(53,216,255,.09);color:var(--cae-cyan)}.tree .indent{padding-left:20px}.tree .dot{width:7px;height:7px;border-radius:50%;background:var(--cae-green);box-shadow:0 0 8px rgba(78,224,165,.55)}.tree .dot.pending{background:var(--cae-amber);box-shadow:none}
.cae-sidebar .gr-group,.cae-sidebar .gr-box,.cae-sidebar .block{border-color:var(--cae-line)!important}.cae-sidebar label,.cae-sidebar span{font-size:12px!important}.cae-sidebar input,.cae-sidebar textarea,.cae-sidebar select{background:#091422!important;color:var(--cae-text)!important;border-color:var(--cae-line)!important}
button.primary{background:linear-gradient(135deg,#147fab,#2b65db)!important;border:none!important;color:white!important;box-shadow:0 6px 18px rgba(35,116,215,.26)!important}button.secondary{background:var(--cae-panel2)!important;color:var(--cae-text)!important;border-color:var(--cae-line)!important}
#run-button{font-weight:750!important;letter-spacing:.2px!important;min-height:44px!important}.cae-status{border:1px solid var(--cae-line);border-left:4px solid var(--cae-cyan);background:#091422;border-radius:8px;padding:10px 12px;font-size:12px;line-height:1.55}.cae-status.ok{border-left-color:var(--cae-green)}.cae-status.warn{border-left-color:var(--cae-amber)}.cae-status.error{border-left-color:var(--cae-red)}.cae-status strong{display:block;font-size:13px;margin-bottom:2px}
.metric-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:7px}.metric-card{background:#091422;border:1px solid var(--cae-line);border-radius:8px;padding:9px;min-width:0}.metric-card span{display:block;color:var(--cae-muted);font-size:10px!important}.metric-card strong{display:block;font-size:17px;margin:4px 0;color:var(--cae-text);white-space:nowrap}.metric-card small{display:block;color:var(--cae-muted);font-size:9px}.metric-card.status.ok{border-color:rgba(78,224,165,.45)}.metric-card.status.ok strong{color:var(--cae-green)}.metric-card.status.warn{border-color:rgba(255,200,87,.45)}.metric-card.status.warn strong{color:var(--cae-amber)}
#viewport-tabs .tab-nav{background:#091422!important;border:1px solid var(--cae-line)!important;border-radius:8px!important;padding:4px!important}#viewport-tabs button{font-size:12px!important}.plot-container{border-radius:8px;overflow:hidden}
#task-console{background:var(--cae-panel)!important;border:1px solid var(--cae-line)!important;border-radius:10px!important;margin-top:9px!important}.pipeline{display:flex;align-items:stretch;gap:7px;overflow-x:auto;padding:8px 2px}.stage{min-width:150px;flex:1;background:#091422;border:1px solid var(--cae-line);border-radius:9px;padding:11px}.stage b{display:block;font-size:13px}.stage span{display:block;color:var(--cae-muted);font-size:10px;margin-top:4px}.stage.ready{border-top:3px solid var(--cae-green)}.stage.ui{border-top:3px solid var(--cae-cyan)}.arrow{display:flex;align-items:center;color:var(--cae-muted);font-size:18px}
.scope-note{font-size:11px;color:var(--cae-muted);line-height:1.6;border:1px dashed var(--cae-line);border-radius:8px;padding:9px;margin-top:8px}.library-note{color:var(--cae-muted);font-size:12px;line-height:1.7}
@media(max-width:1180px){#workbench-row{flex-direction:column!important}.cae-sidebar{min-width:100%!important}.metric-grid{grid-template-columns:repeat(3,minmax(0,1fr))}}
"""

HEADER_HTML = """
<div class="cae-topbar-inner">
  <div class="cae-brand"><div class="cae-logo">H</div><div><div class="cae-title">HPM-CAE Workbench <span style="color:#35d8ff">V0.9</span></div><div class="cae-sub">Phased-array digital-twin · local visual research environment</div></div></div>
  <div class="cae-badges"><span class="cae-badge">LOCAL PYTHON</span><span class="cae-badge">NORMALIZED MODE</span><span class="cae-badge">64 ELEMENTS READY</span></div>
</div>
"""

PIPELINE_HTML = """
<div class="pipeline">
 <div class="stage ready"><b>① 感知</b><span>PAWR / FBSS / ESPRIT</span></div><div class="arrow">›</div>
 <div class="stage ready"><b>② 接收防护</b><span>预测宽零陷 / 多干扰</span></div><div class="arrow">›</div>
 <div class="stage ready"><b>③ 动态控场</b><span>PCF-RLS / 鲁棒区域赋形</span></div><div class="arrow">›</div>
 <div class="stage ready"><b>④ 效应评价</b><span>双参考系 / 概率代理</span></div><div class="arrow">›</div>
 <div class="stage ui"><b>⑤ CAE工作台</b><span>建模 / 求解 / 可视化 / 导出</span></div>
</div>
"""


def _status(title: str, detail: str, kind: str = "ok") -> str:
    return f'<div class="cae-status {kind}"><strong>{title}</strong>{detail}</div>'


def _tree(project: CAEProject) -> str:
    return f"""
<div class="cae-section-title">Project Navigator</div>
<div class="tree">
 <div class="node active">▾ 📁 {project.meta.name}</div>
 <div class="indent">
   <div class="node"><span class="dot"></span> 阵列几何 · {project.array.nx}×{project.array.ny}</div>
   <div class="node"><span class="dot"></span> 观察面 · z={project.plane.z_lambda:g}λ</div>
   <div class="node"><span class="dot"></span> 目标区域 · 旋转椭圆</div>
   <div class="node"><span class="dot"></span> 保护区域 · {'启用' if project.protected_zone.enabled else '关闭'}</div>
   <div class="node"><span class="dot"></span> 求解器 · {project.solver.method}</div>
   <div class="node"><span class="dot pending"></span> 动态任务 · 下一阶段</div>
 </div>
</div>"""


def _project_from_values(values: Sequence[Any]) -> CAEProject:
    if len(values) != len(PARAMETER_KEYS):
        raise ValueError(f"expected {len(PARAMETER_KEYS)} parameters, got {len(values)}")
    p = dict(zip(PARAMETER_KEYS, values, strict=True))
    return CAEProject(
        meta=ProjectMeta(name=str(p["project_name"]), seed=int(p["seed"])),
        array=ArraySpec(
            nx=int(p["nx"]),
            ny=int(p["ny"]),
            frequency_ghz=float(p["frequency_ghz"]),
            spacing_x_lambda=float(p["spacing_x_lambda"]),
            spacing_y_lambda=float(p["spacing_y_lambda"]),
        ),
        plane=ObservationPlaneSpec(
            z_lambda=float(p["z_lambda"]),
            span_x_lambda=float(p["span_x_lambda"]),
            span_y_lambda=float(p["span_y_lambda"]),
            samples=int(p["samples"]),
        ),
        target=TargetRegionSpec(
            center_x_lambda=float(p["target_center_x"]),
            center_y_lambda=float(p["target_center_y"]),
            semi_major_lambda=float(p["target_major"]),
            semi_minor_lambda=float(p["target_minor"]),
            rotation_deg=float(p["target_rotation"]),
            guard_scale=float(p["guard_scale"]),
        ),
        protected_zone=ProtectedZoneSpec(
            enabled=bool(p["protected_enabled"]),
            center_x_lambda=float(p["protected_center_x"]),
            center_y_lambda=float(p["protected_center_y"]),
            radius_lambda=float(p["protected_radius"]),
        ),
        solver=SolverSpec(
            method=str(p["method"]),
            target_amplitude=float(p["target_amplitude"]),
            outside_penalty=float(p["outside_penalty"]),
            outside_hinge_amplitude=float(p["outside_hinge"]),
            iterations=int(p["iterations"]),
            learning_rate=float(p["learning_rate"]),
            uncertainty_scenarios=int(p["uncertainty_scenarios"]),
            gain_std_percent=float(p["gain_std_percent"]),
            phase_std_deg=float(p["phase_std_deg"]),
            registration_jitter_lambda=float(p["registration_jitter"]),
            pa_enabled=bool(p["pa_enabled"]),
            dpd_enabled=bool(p["dpd_enabled"]),
            pa_saturation_amplitude=float(p["pa_saturation"]),
            pa_smoothness=float(p["pa_smoothness"]),
            pa_maximum_phase_deg=float(p["pa_phase_deg"]),
        ),
    )


def _project_values(project: CAEProject) -> list[Any]:
    return [
        project.meta.name,
        project.meta.seed,
        project.array.frequency_ghz,
        project.array.nx,
        project.array.ny,
        project.array.spacing_x_lambda,
        project.array.spacing_y_lambda,
        project.plane.z_lambda,
        project.plane.span_x_lambda,
        project.plane.span_y_lambda,
        project.plane.samples,
        project.target.center_x_lambda,
        project.target.center_y_lambda,
        project.target.semi_major_lambda,
        project.target.semi_minor_lambda,
        project.target.rotation_deg,
        project.target.guard_scale,
        project.protected_zone.enabled,
        project.protected_zone.center_x_lambda,
        project.protected_zone.center_y_lambda,
        project.protected_zone.radius_lambda,
        project.solver.method,
        project.solver.target_amplitude,
        project.solver.outside_penalty,
        project.solver.outside_hinge_amplitude,
        project.solver.iterations,
        project.solver.learning_rate,
        project.solver.uncertainty_scenarios,
        project.solver.gain_std_percent,
        project.solver.phase_std_deg,
        project.solver.registration_jitter_lambda,
        project.solver.pa_enabled,
        project.solver.dpd_enabled,
        project.solver.pa_saturation_amplitude,
        project.solver.pa_smoothness,
        project.solver.pa_maximum_phase_deg,
    ]


def _preset_project(name: str) -> CAEProject:
    project = default_project()
    if name == "快速预览 · 单点聚焦":
        return replace(
            project,
            meta=replace(project.meta, name="Quick Point Focus"),
            plane=replace(project.plane, samples=61),
            solver=replace(
                project.solver,
                method="Point-Focus",
                iterations=40,
                uncertainty_scenarios=1,
                pa_enabled=False,
                dpd_enabled=False,
            ),
        )
    if name == "保护区优先 · 鲁棒赋形":
        return replace(
            project,
            meta=replace(project.meta, name="Protected-Zone Priority"),
            protected_zone=replace(project.protected_zone, radius_lambda=0.90),
            solver=replace(
                project.solver,
                outside_penalty=1.9,
                outside_hinge_amplitude=0.12,
                uncertainty_scenarios=7,
                iterations=460,
            ),
        )
    if name == "非理想功放 · 无DPD":
        return replace(
            project,
            meta=replace(project.meta, name="PA Distortion Inspection"),
            solver=replace(
                project.solver,
                method="Nominal-PGMS",
                pa_enabled=True,
                dpd_enabled=False,
                pa_saturation_amplitude=0.82,
                pa_maximum_phase_deg=16.0,
            ),
        )
    return project


def _preview_callback(*values: Any):
    try:
        project = _project_from_values(values)
        array = project.array.build_array()
        aperture_x = (project.array.nx - 1) * project.array.spacing_x_lambda
        aperture_y = (project.array.ny - 1) * project.array.spacing_y_lambda
        detail = (
            f"几何有效：{array.n_elements}阵元，孔径 {aperture_x:.2f}λ × {aperture_y:.2f}λ，"
            f"观察面 {project.plane.samples}×{project.plane.samples}。"
        )
        return make_scene_figure(project), project.to_dict(), _tree(project), _status("场景预览已更新", detail)
    except Exception as exc:
        return (
            make_empty_result_figure("场景参数错误", str(exc)),
            {"error": str(exc)},
            _tree(default_project()),
            _status("参数校验失败", str(exc), "error"),
        )


def _save_callback(*values: Any):
    try:
        project = _project_from_values(values)
        path = export_project_file(project, UI_PROJECT_ROOT)
        return str(path), project.to_dict(), _status("项目已保存", f"{path.name} 可用于后续复现。")
    except Exception as exc:
        return None, {"error": str(exc)}, _status("保存失败", str(exc), "error")


def _solve_callback(*values: Any):
    try:
        project = _project_from_values(values)
        result = solve_project(project)
        run_dir, report, archive = export_result_bundle(result, UI_OUTPUT_ROOT)
        project_path = run_dir / "project.yaml"
        detail = (
            f"{project.solver.method} 完成；目标RMSE {result.metrics['target_rmse_percent']:.2f}%，"
            f"覆盖率 {result.metrics['target_coverage_percent']:.1f}%，"
            f"求解 {result.metrics['solver_runtime_ms']:.1f} ms。"
        )
        return (
            result,
            make_scene_figure(project),
            make_field_figure(result),
            make_cut_figure(result),
            make_far_field_figure(result),
            make_weights_figure(result),
            make_convergence_figure(result),
            result.metrics_frame(),
            make_metric_cards_html(result),
            "\n".join(result.log_lines) + f"\n[export] {archive.name}\n",
            project.to_dict(),
            _tree(project),
            str(project_path),
            str(report),
            str(archive),
            _status("求解完成", detail, "ok" if result.metrics["control_success"] else "warn"),
        )
    except Exception as exc:
        error = "".join(traceback.format_exception_only(type(exc), exc)).strip()
        empty = make_empty_result_figure("求解失败", error)
        return (
            None,
            empty,
            empty,
            empty,
            empty,
            empty,
            empty,
            pd.DataFrame([{"指标": "错误", "数值": error, "单位": ""}]),
            "",
            traceback.format_exc(),
            {"error": error},
            _tree(default_project()),
            None,
            None,
            None,
            _status("求解失败", error, "error"),
        )


def _load_callback(path: str | None):
    try:
        if not path:
            raise ValueError("请先选择 .yaml 项目文件")
        project = CAEProject.load_yaml(path)
        return (*_project_values(project), make_scene_figure(project), project.to_dict(), _tree(project), _status("项目已载入", Path(path).name))
    except Exception as exc:
        raise gr.Error(f"项目载入失败：{exc}")


def _preset_callback(name: str):
    project = _preset_project(name)
    return (*_project_values(project), make_scene_figure(project), project.to_dict(), _tree(project), _status("预设已应用", name))


def _library_items(version: str) -> tuple[str, list[tuple[str, str]], str | None]:
    library = {
        "V0.3 感知识别": (
            "PAWR-MUSIC、FBSS、ESPRIT与模型失配敏感性。",
            "outputs_v03_perception",
            ["00_pawr_mechanism.png", "04_pawr_music_spectrum.png", "09b_rmse_vs_snr_zoom.png", "15_ablation.png"],
            "perception_v03_report_standalone.html",
        ),
        "V0.4 接收防护": (
            "DOA不确定条件下的宽零陷接收防护。",
            "outputs_v04_protection",
            ["00_cr_hybridnull_mechanism.png", "02_cr_hybridnull_map.png", "06_sinr_vs_drift.png", "12_ablation_sinr.png"],
            "protection_v04_report_standalone.html",
        ),
        "V0.7 动态控场": (
            "预测—协方差—反馈移动目标区赋形。",
            "outputs_v07_dynamic_field_control",
            ["00_pcf_rls_mechanism.png", "05_pcf_rls_field_map.png", "12_rmse_time_series.png", "27_pcf_rls_dynamic_field.gif"],
            "dynamic_field_control_v07_report_standalone.html",
        ),
        "V0.8 效应数字孪生": (
            "双参考系累积、概率代理与风险调整资源分配。",
            "outputs_v08_effect_twin",
            ["00_effect_twin_mechanism.png", "06_pcf_rls_probability_map.png", "20_strategy_risk_utility.png", "29_ea_duty_dynamic_probability.gif"],
            "effect_twin_v08_report_standalone.html",
        ),
    }
    description, folder, names, report_name = library[version]
    root = PROJECT_ROOT / folder
    items: list[tuple[str, str]] = []
    for name in names:
        path = root / name
        if path.exists():
            items.append((str(path), name))
    report = root / report_name
    return f"### {version}\n\n{description}", items, str(report) if report.exists() else None


def build_app() -> gr.Blocks:
    initial_project = default_project()
    initial_result = solve_project(initial_project)
    initial_scene = make_scene_figure(initial_project)
    initial_field = make_field_figure(initial_result)
    initial_cut = make_cut_figure(initial_result)
    initial_far = make_far_field_figure(initial_result)
    initial_weights = make_weights_figure(initial_result)
    initial_convergence = make_convergence_figure(initial_result)

    sample_root = PROJECT_ROOT / "outputs_v09_ui" / "sample_project"
    sample_project_file = sample_root / "project.yaml"
    sample_report = sample_root / "HPM_CAE_report.html"
    sample_archive = PROJECT_ROOT / "outputs_v09_ui" / "sample_project.zip"

    with gr.Blocks(
        title="HPM-CAE Workbench V0.9",
        fill_width=True,
        fill_height=True,
    ) as demo:
        result_state = gr.State(initial_result)
        gr.HTML(HEADER_HTML, elem_id="cae-topbar")
        gr.HTML(PIPELINE_HTML)

        with gr.Row(elem_id="workbench-row"):
            with gr.Column(scale=23, min_width=285, elem_classes="cae-sidebar"):
                project_tree = gr.HTML(_tree(initial_project))
                with gr.Accordion("项目", open=True):
                    project_name = gr.Textbox(value=initial_project.meta.name, label="项目名称")
                    seed = gr.Number(value=initial_project.meta.seed, label="随机种子", precision=0)
                    preset = gr.Dropdown(
                        choices=[
                            "论文基线 · 鲁棒区域赋形",
                            "快速预览 · 单点聚焦",
                            "保护区优先 · 鲁棒赋形",
                            "非理想功放 · 无DPD",
                        ],
                        value="论文基线 · 鲁棒区域赋形",
                        label="场景预设",
                    )
                    apply_preset = gr.Button("应用预设", variant="secondary", size="sm")
                    load_file = gr.File(label="载入项目 YAML", file_types=[".yaml", ".yml"], type="filepath")
                    load_button = gr.Button("读取项目", variant="secondary", size="sm")

                with gr.Accordion("阵列几何", open=True):
                    frequency = gr.Number(value=initial_project.array.frequency_ghz, label="频率 / GHz", minimum=0.1, maximum=100.0, step=0.1)
                    with gr.Row():
                        nx = gr.Slider(2, 20, value=initial_project.array.nx, step=1, label="Nx")
                        ny = gr.Slider(2, 20, value=initial_project.array.ny, step=1, label="Ny")
                    with gr.Row():
                        spacing_x = gr.Slider(0.2, 1.2, value=initial_project.array.spacing_x_lambda, step=0.05, label="dx / λ")
                        spacing_y = gr.Slider(0.2, 1.2, value=initial_project.array.spacing_y_lambda, step=0.05, label="dy / λ")

                with gr.Accordion("观察面", open=False):
                    z_lambda = gr.Slider(2.0, 30.0, value=initial_project.plane.z_lambda, step=0.5, label="z / λ")
                    with gr.Row():
                        span_x = gr.Slider(4.0, 20.0, value=initial_project.plane.span_x_lambda, step=0.5, label="x跨度 / λ")
                        span_y = gr.Slider(4.0, 20.0, value=initial_project.plane.span_y_lambda, step=0.5, label="y跨度 / λ")
                    samples = gr.Dropdown(choices=[41, 61, 81, 101, 121, 151, 181], value=initial_project.plane.samples, label="网格点数")

                with gr.Accordion("目标区域", open=False):
                    with gr.Row():
                        target_x = gr.Number(value=initial_project.target.center_x_lambda, label="中心 x / λ", step=0.1)
                        target_y = gr.Number(value=initial_project.target.center_y_lambda, label="中心 y / λ", step=0.1)
                    with gr.Row():
                        target_major = gr.Number(value=initial_project.target.semi_major_lambda, label="长半轴 / λ", minimum=0.1, step=0.05)
                        target_minor = gr.Number(value=initial_project.target.semi_minor_lambda, label="短半轴 / λ", minimum=0.1, step=0.05)
                    target_rotation = gr.Slider(-90, 90, value=initial_project.target.rotation_deg, step=1, label="旋转角 / °")
                    guard_scale = gr.Slider(1.05, 2.5, value=initial_project.target.guard_scale, step=0.05, label="过渡区倍率")

                with gr.Accordion("保护区域", open=False):
                    protected_enabled = gr.Checkbox(value=initial_project.protected_zone.enabled, label="启用保护区")
                    with gr.Row():
                        protected_x = gr.Number(value=initial_project.protected_zone.center_x_lambda, label="中心 x / λ", step=0.1)
                        protected_y = gr.Number(value=initial_project.protected_zone.center_y_lambda, label="中心 y / λ", step=0.1)
                    protected_radius = gr.Number(value=initial_project.protected_zone.radius_lambda, label="半径 / λ", minimum=0.1, step=0.05)

                with gr.Accordion("求解器与约束", open=False):
                    method = gr.Dropdown(choices=list(SolverSpec.METHODS), value=initial_project.solver.method, label="算法")
                    target_amplitude = gr.Slider(0.1, 1.0, value=initial_project.solver.target_amplitude, step=0.01, label="目标归一化幅度")
                    outside_penalty = gr.Slider(0.0, 3.0, value=initial_project.solver.outside_penalty, step=0.05, label="区外惩罚")
                    outside_hinge = gr.Slider(0.02, 0.8, value=initial_project.solver.outside_hinge_amplitude, step=0.01, label="区外铰链幅度")
                    iterations = gr.Slider(20, 1000, value=initial_project.solver.iterations, step=20, label="迭代次数")
                    learning_rate = gr.Number(value=initial_project.solver.learning_rate, label="学习率", minimum=0.001, maximum=0.2, step=0.005)

                with gr.Accordion("不确定性与功放", open=False):
                    uncertainty_scenarios = gr.Slider(1, 16, value=initial_project.solver.uncertainty_scenarios, step=1, label="鲁棒场景数")
                    gain_std = gr.Slider(0, 15, value=initial_project.solver.gain_std_percent, step=0.5, label="增益误差 σ / %")
                    phase_std = gr.Slider(0, 25, value=initial_project.solver.phase_std_deg, step=0.5, label="相位误差 σ / °")
                    registration_jitter = gr.Slider(0, 0.4, value=initial_project.solver.registration_jitter_lambda, step=0.01, label="配准抖动 σ / λ")
                    pa_enabled = gr.Checkbox(value=initial_project.solver.pa_enabled, label="启用归一化功放模型")
                    dpd_enabled = gr.Checkbox(value=initial_project.solver.dpd_enabled, label="启用DPD")
                    pa_saturation = gr.Slider(0.5, 1.5, value=initial_project.solver.pa_saturation_amplitude, step=0.05, label="饱和幅度")
                    pa_smoothness = gr.Slider(1.0, 8.0, value=initial_project.solver.pa_smoothness, step=0.5, label="Rapp平滑度")
                    pa_phase = gr.Slider(0, 30, value=initial_project.solver.pa_maximum_phase_deg, step=1, label="最大AM/PM / °")

            with gr.Column(scale=54, min_width=650, elem_id="viewport-panel"):
                with gr.Tabs(elem_id="viewport-tabs"):
                    with gr.Tab("三维场景"):
                        scene_plot = gr.Plot(initial_scene, show_label=False)
                    with gr.Tab("场分布"):
                        field_plot = gr.Plot(initial_field, show_label=False)
                    with gr.Tab("目标截线"):
                        cut_plot = gr.Plot(initial_cut, show_label=False)
                    with gr.Tab("远场方向图"):
                        far_plot = gr.Plot(initial_far, show_label=False)
                    with gr.Tab("阵元激励"):
                        weights_plot = gr.Plot(initial_weights, show_label=False)
                    with gr.Tab("收敛"):
                        convergence_plot = gr.Plot(initial_convergence, show_label=False)
                    with gr.Tab("工作流库"):
                        gr.Markdown("### 历史算法结果库\nV0.3—V0.8的代表图与完整自包含报告在同一个工作台中浏览。")
                        library_choice = gr.Dropdown(
                            choices=["V0.3 感知识别", "V0.4 接收防护", "V0.7 动态控场", "V0.8 效应数字孪生"],
                            value="V0.8 效应数字孪生",
                            label="结果集",
                        )
                        initial_lib = _library_items("V0.8 效应数字孪生")
                        library_description = gr.Markdown(initial_lib[0])
                        library_gallery = gr.Gallery(initial_lib[1], columns=2, height=500, label="代表结果", object_fit="contain")
                        library_report = gr.File(value=initial_lib[2], label="完整报告", interactive=False)

                with gr.Accordion("任务监视器 / Solver Log", open=True, elem_id="task-console"):
                    solver_log = gr.Code(
                        value="\n".join(initial_result.log_lines),
                        language="shell",
                        lines=9,
                        max_lines=18,
                        label="",
                        interactive=False,
                        show_line_numbers=False,
                    )

            with gr.Column(scale=23, min_width=290, elem_classes="cae-sidebar"):
                gr.HTML('<div class="cae-section-title">Solver Control</div>')
                run_button = gr.Button("▶ 运行求解", variant="primary", elem_id="run-button")
                with gr.Row():
                    preview_button = gr.Button("刷新场景", variant="secondary", size="sm")
                    save_button = gr.Button("保存项目", variant="secondary", size="sm")
                status_html = gr.HTML(
                    _status(
                        "示例工程已载入",
                        f"{initial_project.solver.method}：目标RMSE {initial_result.metrics['target_rmse_percent']:.2f}%。",
                        "ok",
                    )
                )
                metric_cards = gr.HTML(make_metric_cards_html(initial_result))
                metrics_table = gr.Dataframe(
                    initial_result.metrics_frame(),
                    label="关键指标",
                    interactive=False,
                    show_row_numbers=False,
                    max_height=340,
                    wrap=True,
                )
                with gr.Accordion("项目快照", open=False):
                    config_json = gr.JSON(initial_project.to_dict(), label="", open=False, show_indices=False, max_height=360)
                gr.HTML('<div class="cae-section-title" style="margin-top:10px">Artifacts</div>')
                project_download = gr.DownloadButton(
                    "下载项目 YAML",
                    value=str(sample_project_file) if sample_project_file.exists() else None,
                    size="sm",
                )
                report_download = gr.DownloadButton(
                    "下载交互报告 HTML",
                    value=str(sample_report) if sample_report.exists() else None,
                    size="sm",
                )
                bundle_download = gr.DownloadButton(
                    "下载完整结果 ZIP",
                    value=str(sample_archive) if sample_archive.exists() else None,
                    variant="primary",
                    size="sm",
                )
                gr.HTML(
                    '<div class="scope-note"><b>模型边界</b><br>工作台只处理波长尺度几何、归一化复场和统计代理量；不提供真实源功率、器件毁伤阈值或现实作用距离推断。</div>'
                )

        components = [
            project_name,
            seed,
            frequency,
            nx,
            ny,
            spacing_x,
            spacing_y,
            z_lambda,
            span_x,
            span_y,
            samples,
            target_x,
            target_y,
            target_major,
            target_minor,
            target_rotation,
            guard_scale,
            protected_enabled,
            protected_x,
            protected_y,
            protected_radius,
            method,
            target_amplitude,
            outside_penalty,
            outside_hinge,
            iterations,
            learning_rate,
            uncertainty_scenarios,
            gain_std,
            phase_std,
            registration_jitter,
            pa_enabled,
            dpd_enabled,
            pa_saturation,
            pa_smoothness,
            pa_phase,
        ]
        assert len(components) == len(PARAMETER_KEYS)

        preview_button.click(
            _preview_callback,
            inputs=components,
            outputs=[scene_plot, config_json, project_tree, status_html],
            show_progress="minimal",
        )
        save_button.click(
            _save_callback,
            inputs=components,
            outputs=[project_download, config_json, status_html],
            show_progress="minimal",
        )
        run_button.click(
            _solve_callback,
            inputs=components,
            outputs=[
                result_state,
                scene_plot,
                field_plot,
                cut_plot,
                far_plot,
                weights_plot,
                convergence_plot,
                metrics_table,
                metric_cards,
                solver_log,
                config_json,
                project_tree,
                project_download,
                report_download,
                bundle_download,
                status_html,
            ],
            show_progress="full",
            concurrency_limit=1,
        )
        load_button.click(
            _load_callback,
            inputs=[load_file],
            outputs=[*components, scene_plot, config_json, project_tree, status_html],
            show_progress="minimal",
        )
        apply_preset.click(
            _preset_callback,
            inputs=[preset],
            outputs=[*components, scene_plot, config_json, project_tree, status_html],
            show_progress="minimal",
        )
        library_choice.change(
            _library_items,
            inputs=[library_choice],
            outputs=[library_description, library_gallery, library_report],
            show_progress="minimal",
        )
        pa_enabled.change(
            lambda enabled: gr.update(value=bool(enabled), interactive=bool(enabled)),
            inputs=[pa_enabled],
            outputs=[dpd_enabled],
            show_progress="hidden",
        )

    return demo


def launch(**kwargs: Any) -> None:
    app = build_app()
    launch_kwargs = {
        "server_name": "127.0.0.1",
        "server_port": 7860,
        "share": False,
        "inbrowser": True,
        "show_error": True,
        "allowed_paths": [str(PROJECT_ROOT)],
        "theme": gr.themes.Base(
            primary_hue="cyan",
            secondary_hue="blue",
            neutral_hue="slate",
        ),
        "css": CSS,
    }
    launch_kwargs.update(kwargs)
    app.queue(default_concurrency_limit=1).launch(**launch_kwargs)

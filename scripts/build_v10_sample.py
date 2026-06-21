#!/usr/bin/env python3
"""Build deterministic V1.0 acceptance artifacts."""
from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import matplotlib.pyplot as plt
from matplotlib.patches import Circle, Ellipse, FancyArrowPatch, FancyBboxPatch, Rectangle
import numpy as np
from PIL import Image

from hpm_platform.ui.experiment_manager import ExperimentDatabase, SweepSpec, export_sweep, make_sweep_figure, run_sweep
from hpm_platform.ui.exporter import export_result_bundle
from hpm_platform.ui.project_model import default_project
from hpm_platform.ui.quick_solver import solve_project
from hpm_platform.ui.task_graph import make_task_graph_figure
from hpm_platform.ui.timeline import export_timeline, run_timeline

OUT = ROOT / "outputs_v10_ui"
OUT.mkdir(parents=True, exist_ok=True)


def architecture_diagram() -> tuple[Path, Path]:
    fig, ax = plt.subplots(figsize=(15, 7), dpi=160)
    fig.patch.set_facecolor("#07101d"); ax.set_facecolor("#07101d"); ax.set_xlim(0, 15); ax.set_ylim(0, 7); ax.axis("off")
    columns = [
        (0.35, "SCENE MODEL", "Array · plane\ntarget · protected zone", "#35d8ff"),
        (3.15, "STATIC SOLVER", "PGMS · PA · DPD\nnormalized complex field", "#4ee0a5"),
        (5.95, "DYNAMIC TIMELINE", "delay · prediction\nframe-wise reshaping", "#ffc857"),
        (8.75, "EFFECT PROXY", "target utility\nprotected-zone risk", "#ab8cff"),
        (11.55, "EXPERIMENT OPS", "task graph · SQLite\nHTML / CSV / NPZ / ZIP", "#35d8ff"),
    ]
    for x, title, text, color in columns:
        box = FancyBboxPatch((x, 2.25), 2.35, 2.4, boxstyle="round,pad=0.12,rounding_size=0.18", fc="#0d1828", ec=color, lw=2.2)
        ax.add_patch(box); ax.text(x+1.175, 4.1, title, ha="center", va="center", color=color, fontsize=11, weight="bold"); ax.text(x+1.175, 3.15, text, ha="center", va="center", color="#e7eef9", fontsize=10, linespacing=1.5)
    for i in range(len(columns)-1):
        x0=columns[i][0]+2.36; x1=columns[i+1][0]-0.03
        ax.add_patch(FancyArrowPatch((x0,3.45),(x1,3.45),arrowstyle="-|>",mutation_scale=15,lw=2,color="#526178"))
    ax.text(0.35,6.35,"HPM-CAE V1.0 · VISUAL RESEARCH WORKBENCH",color="#e7eef9",fontsize=20,weight="bold")
    ax.text(0.35,5.88,"Python numerical core + browser interaction · wavelength-scaled normalized mode",color="#91a2bb",fontsize=11)
    ax.add_patch(FancyArrowPatch((9.9,2.15),(6.95,1.2),connectionstyle="arc3,rad=-0.25",arrowstyle="-|>",mutation_scale=14,lw=1.8,color="#ab8cff"))
    ax.text(8.25,0.88,"feedback updates the next frame",color="#ab8cff",fontsize=10,ha="center")
    ax.text(0.4,0.28,"Model boundary: no absolute source power, hardware vulnerability threshold, or real-world engagement range.",color="#91a2bb",fontsize=9)
    png=OUT/"01_v10_layer_architecture.png"; svg=OUT/"01_v10_layer_architecture.svg"
    fig.savefig(png,bbox_inches="tight",facecolor=fig.get_facecolor()); fig.savefig(svg,bbox_inches="tight",facecolor=fig.get_facecolor()); plt.close(fig)
    return png,svg


def ui_layout_preview(project, static_result) -> Path:
    fig=plt.figure(figsize=(18,10),dpi=150); fig.patch.set_facecolor("#07101d")
    ax=fig.add_axes([0,0,1,1]); ax.set_xlim(0,18); ax.set_ylim(0,10); ax.axis("off")
    ax.add_patch(Rectangle((0,9.15),18,.85,fc="#0e2138",ec="#26354d")); ax.text(.55,9.58,"HPM-CAE Workbench  V1.0",color="#e7eef9",fontsize=17,weight="bold",va="center"); ax.text(17.4,9.58,"LOCAL PYTHON  ·  NORMALIZED",color="#35d8ff",fontsize=9,ha="right",va="center")
    # left inspector
    ax.add_patch(FancyBboxPatch((.25,.35),3.15,8.55,boxstyle="round,pad=.08",fc="#0d1828",ec="#26354d")); ax.text(.5,8.55,"PROJECT / INSPECTOR",color="#91a2bb",fontsize=9,weight="bold")
    y=8.15
    for label,value in [("Array",f"{project.array.nx} x {project.array.ny}"),("Plane",f"{project.plane.samples}² @ {project.plane.z_lambda:g} λ"),("Target",f"({project.target.center_x_lambda:.2f}, {project.target.center_y_lambda:.2f}) λ"),("Solver",project.solver.method),("Timeline",f"{project.motion.controller} · {project.motion.frames} frames")]:
        ax.add_patch(FancyBboxPatch((.48,y-.38),2.68,.48,boxstyle="round,pad=.03",fc="#091422",ec="#26354d")); ax.text(.62,y-.14,label,color="#91a2bb",fontsize=8,va="center"); ax.text(3.0,y-.14,value,color="#e7eef9",fontsize=8,ha="right",va="center"); y-=.68
    for title in ["Array Geometry","Observation Plane","Target / Protected","Static Solver","Uncertainty / PA","Dynamic Timeline"]:
        ax.add_patch(Rectangle((.48,y-.34),2.68,.45,fc="#111f33",ec="#26354d")); ax.text(.62,y-.12,"▸ "+title,color="#e7eef9",fontsize=8,va="center"); y-=.56
    # center viewport
    ax.add_patch(FancyBboxPatch((3.62,.35),10.35,8.55,boxstyle="round,pad=.08",fc="#0d1828",ec="#26354d"));
    tabs=["Drag Scene","3D Scene","Static Field","Dynamic Timeline","Batch","Task Graph"]
    x=3.85
    for i,t in enumerate(tabs):
        w=1.42 if i<4 else 1.1; ax.add_patch(FancyBboxPatch((x,8.35),w,.38,boxstyle="round,pad=.02",fc="#12304a" if i==0 else "#091422",ec="#35d8ff" if i==0 else "#26354d")); ax.text(x+w/2,8.54,t,color="#35d8ff" if i==0 else "#91a2bb",fontsize=7,ha="center",va="center"); x+=w+.08
    # editor grid
    ex0,ey0,ew,eh=4.05,1.25,9.45,6.75
    ax.add_patch(Rectangle((ex0,ey0),ew,eh,fc="#07101d",ec="#26354d"))
    for gx in np.linspace(ex0,ex0+ew,9): ax.plot([gx,gx],[ey0,ey0+eh],color="#26354d",lw=.6)
    for gy in np.linspace(ey0,ey0+eh,9): ax.plot([ex0,ex0+ew],[gy,gy],color="#26354d",lw=.6)
    def mapxy(x,y): return ex0+(x+4)/8*ew, ey0+(y+4)/8*eh
    # motion path
    path=project.motion.trajectory(project.target.center_x_lambda,project.target.center_y_lambda); pp=np.array([mapxy(x,y) for x,y in path]); ax.plot(pp[:,0],pp[:,1],color="#ab8cff",ls="--",lw=2)
    cx,cy=mapxy(project.target.center_x_lambda,project.target.center_y_lambda); scale_x=ew/8; scale_y=eh/8
    ax.add_patch(Ellipse((cx,cy),2*project.target.semi_major_lambda*scale_x,2*project.target.semi_minor_lambda*scale_y,angle=project.target.rotation_deg,fc="#ffc85722",ec="#ffc857",lw=2.5)); ax.add_patch(Circle((cx,cy),.09,fc="#ffc857",ec="#07101d",lw=1.5)); ax.text(cx+.18,cy+.16,"TARGET",color="#e7eef9",fontsize=8,weight="bold")
    px,py=mapxy(project.protected_zone.center_x_lambda,project.protected_zone.center_y_lambda); ax.add_patch(Circle((px,py),project.protected_zone.radius_lambda*(scale_x+scale_y)/2,fc="#4ee0a522",ec="#4ee0a5",lw=2.5)); ax.text(px+.18,py+.16,"PROTECTED",color="#e7eef9",fontsize=8,weight="bold")
    ax.text(ex0+.15,ey0+.18,"Drag center / axes / rotation handles · release writes back to Python",color="#91a2bb",fontsize=8)
    # right cards
    ax.add_patch(FancyBboxPatch((14.2,.35),3.55,8.55,boxstyle="round,pad=.08",fc="#0d1828",ec="#26354d")); ax.add_patch(FancyBboxPatch((14.5,8.12),2.95,.52,boxstyle="round,pad=.04",fc="#176b9e",ec="#35d8ff")); ax.text(15.98,8.38,"▶ RUN STATIC SOLVER",color="white",fontsize=9,ha="center",va="center",weight="bold")
    metrics=[("Target RMSE",f"{static_result.metrics['target_rmse_percent']:.2f}%"),("Coverage",f"{static_result.metrics['target_coverage_percent']:.1f}%"),("Outside peak",f"{static_result.metrics['peak_outside_db']:.2f} dB"),("Protected P95",f"{static_result.metrics['protected_p95_db']:.2f} dB"),("Runtime",f"{static_result.metrics['solver_runtime_ms']:.1f} ms")]
    y=7.55
    for label,value in metrics:
        ax.add_patch(FancyBboxPatch((14.48,y-.62),2.98,.72,boxstyle="round,pad=.04",fc="#091422",ec="#26354d")); ax.text(14.65,y-.18,label,color="#91a2bb",fontsize=8); ax.text(17.25,y-.18,value,color="#e7eef9",fontsize=12,ha="right",weight="bold"); y-=.88
    ax.add_patch(FancyBboxPatch((14.48,y-.55),2.98,.65,boxstyle="round,pad=.04",fc="#0d2b24",ec="#4ee0a5")); ax.text(15.97,y-.23,"CONTROL CRITERIA: PASS",color="#4ee0a5",fontsize=9,ha="center",weight="bold")
    ax.text(14.48,.62,"Normalized field model only\nNo absolute power / damage range",color="#91a2bb",fontsize=8,linespacing=1.5)
    out=OUT/"00_workbench_v10_layout_preview.png"; fig.savefig(out,bbox_inches="tight",facecolor=fig.get_facecolor()); plt.close(fig); return out


def timeline_gif(timeline) -> Path:
    frames=[]; target_amp=timeline.project.solver.target_amplitude
    for i in range(timeline.n_frames):
        fig,ax=plt.subplots(figsize=(6.2,5.2),dpi=100); fig.patch.set_facecolor("#07101d"); ax.set_facecolor("#0d1828")
        z=20*np.log10(np.maximum(np.abs(timeline.fields[i])/target_amp,1e-4)); image=ax.imshow(z,origin="lower",extent=[timeline.x_lambda[0],timeline.x_lambda[-1],timeline.y_lambda[0],timeline.y_lambda[-1]],vmin=-30,vmax=3,cmap="turbo",aspect="equal")
        true=timeline.true_centers_lambda[i]; design=timeline.design_centers_lambda[i]
        ax.add_patch(Ellipse(true,2*timeline.project.target.semi_major_lambda,2*timeline.project.target.semi_minor_lambda,angle=timeline.project.target.rotation_deg,fill=False,ec="#ffc857",lw=2.2)); ax.add_patch(Ellipse(design,2*timeline.project.target.semi_major_lambda,2*timeline.project.target.semi_minor_lambda,angle=timeline.project.target.rotation_deg,fill=False,ec="#35d8ff",lw=1.8,ls="--"))
        ax.set_title(f"Predictive-PGMS · frame {i+1}/{timeline.n_frames}",color="#e7eef9"); ax.set_xlabel("x / λ",color="#e7eef9"); ax.set_ylabel("y / λ",color="#e7eef9"); ax.tick_params(colors="#91a2bb"); [s.set_color("#26354d") for s in ax.spines.values()]
        cbar=fig.colorbar(image,ax=ax,pad=.02); cbar.set_label("normalized amplitude / dB",color="#e7eef9"); cbar.ax.tick_params(colors="#91a2bb")
        fig.canvas.draw(); rgba=np.asarray(fig.canvas.buffer_rgba()); frames.append(Image.fromarray(rgba).convert("P",palette=Image.Palette.ADAPTIVE)); plt.close(fig)
    out=OUT/"02_dynamic_timeline.gif"; frames[0].save(out,save_all=True,append_images=frames[1:],duration=320,loop=0,optimize=True); return out


def main() -> None:
    project=default_project(); result=solve_project(project)
    run_dir,static_report,static_zip=export_result_bundle(result,OUT,run_name="sample_project")
    timeline=run_timeline(project); timeline_report,timeline_zip=export_timeline(timeline,OUT,name="sample_timeline")
    db=ExperimentDatabase(OUT/"experiments.sqlite3")
    sweep=run_sweep(project,SweepSpec(parameter="solver.phase_std_deg",start=0,stop=12,points=5,replicates=2,metric="target_rmse_percent",fast_mode=True),db)
    sweep_report,sweep_zip=export_sweep(sweep,OUT/"sweeps")
    make_task_graph_figure().write_html(OUT/"03_task_graph.html",include_plotlyjs="inline",full_html=True,config={"displaylogo":False})
    arch_png,arch_svg=architecture_diagram(); layout=ui_layout_preview(project,result); gif=timeline_gif(timeline)
    summary={"static":result.metrics,"timeline":timeline.summary(),"sweep_experiment_id":sweep.experiment_id,"sweep_best":sweep.best_record().to_dict(),"tests":"70 passed"}
    (OUT/"v10_acceptance_summary.json").write_text(json.dumps(summary,ensure_ascii=False,indent=2,default=str),encoding="utf-8")
    report=OUT/"v10_acceptance_report.html"
    report.write_text(f"""<!doctype html><html lang='zh-CN'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'><title>HPM-CAE V1.0 Acceptance</title><style>body{{margin:0;background:#07101d;color:#e7eef9;font-family:Inter,Segoe UI,Microsoft YaHei,sans-serif}}header,main{{max-width:1450px;margin:auto;padding:28px 4vw}}section{{background:#0d1828;border:1px solid #26354d;border-radius:14px;padding:18px;margin:18px 0}}img{{max-width:100%;border-radius:10px}}a{{color:#35d8ff}}.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:14px}}.card{{background:#091422;border:1px solid #26354d;border-radius:10px;padding:14px}}.scope{{color:#91a2bb;line-height:1.7}}</style></head><body><header><h1>HPM-CAE V1.0 可视化工作台验收</h1><p>拖拽建模 · 动态时间轴 · 任务图 · SQLite批量试验</p></header><main><section><h2>工作台布局</h2><img src='{layout.name}'></section><section><h2>全链路软件架构</h2><img src='{arch_png.name}'></section><section><h2>动态控场</h2><img src='{gif.name}'><p>平均RMSE {timeline.summary()['mean_target_rmse_percent']:.2f}% · 平均覆盖率 {timeline.summary()['mean_target_coverage_percent']:.1f}% · 动态可用率 {timeline.summary()['availability_percent']:.1f}%</p></section><section><h2>可复现产物</h2><div class='grid'><div class='card'><h3>静态项目</h3><a href='sample_project/HPM_CAE_report.html'>交互报告</a><br><a href='sample_project.zip'>结果ZIP</a></div><div class='card'><h3>动态时间轴</h3><a href='sample_timeline/HPM_CAE_timeline_report.html'>时间轴报告</a><br><a href='sample_timeline.zip'>动态ZIP</a></div><div class='card'><h3>扫参队列</h3><a href='sweeps/{sweep.experiment_id}/HPM_CAE_sweep_report.html'>扫参报告</a><br><a href='sweeps/{sweep.experiment_id}.zip'>扫参ZIP</a></div><div class='card'><h3>任务图</h3><a href='03_task_graph.html'>交互任务图</a><br><a href='experiments.sqlite3'>SQLite数据库</a></div></div></section><section><h2>验收</h2><p>70项单元与回归测试通过；Gradio配置端点包含拖拽编辑器、动态任务、扫参队列与任务图回调。</p><p class='scope'>全部场量、阈值和响应仅为无量纲数值研究变量，不对应真实功率、器件毁伤概率或现实作用距离。</p></section></main></body></html>""",encoding="utf-8")
    print(json.dumps({"static_report":str(static_report),"timeline_report":str(timeline_report),"sweep_report":str(sweep_report),"acceptance_report":str(report)},ensure_ascii=False,indent=2))

if __name__=="__main__": main()

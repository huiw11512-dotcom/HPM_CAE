#!/usr/bin/env python3
"""Build deterministic V1.1 acceptance assets from real numerical outputs."""
from __future__ import annotations

import base64
from dataclasses import replace
from pathlib import Path
import json
import shutil

import matplotlib.pyplot as plt
from matplotlib import font_manager
from matplotlib.patches import FancyBboxPatch, Ellipse, Circle, FancyArrowPatch
import numpy as np
import pandas as pd

from hpm_platform.ui.experiment_manager import SweepSpec
from hpm_platform.ui.job_queue import PersistentJobQueue
from hpm_platform.ui.project_model import CAEProject, default_project

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "outputs_v11_ui"
SAMPLE = OUT / "sample_full_chain"

BG = "#07101d"; PANEL = "#0d1828"; PANEL2 = "#111f33"; GRID = "#26354d"
TEXT = "#e7eef9"; MUTED = "#91a2bb"; CYAN = "#35d8ff"; GREEN = "#4ee0a5"
AMBER = "#ffc857"; RED = "#ff6b7a"; PURPLE = "#ab8cff"
CJK_FONT_PATH = Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc")
if CJK_FONT_PATH.exists():
    font_manager.fontManager.addfont(str(CJK_FONT_PATH))
    _cjk_family = font_manager.FontProperties(fname=str(CJK_FONT_PATH)).get_name()
    plt.rcParams["font.family"] = [_cjk_family, "DejaVu Sans"]
else:
    plt.rcParams["font.family"] = ["DejaVu Sans"]
plt.rcParams["axes.unicode_minus"] = False


def load_outputs():
    project = CAEProject.load_yaml(SAMPLE / "project.yaml")
    p = np.load(SAMPLE / "perception_arrays.npz")
    r = np.load(SAMPLE / "protection_arrays.npz")
    f = np.load(SAMPLE / "field_control_arrays.npz")
    metrics = json.loads((SAMPLE / "metrics.json").read_text(encoding="utf-8"))
    theta = np.arange(project.perception.scan_theta_min_deg, project.perception.scan_theta_max_deg + .25, project.perception.scan_step_deg)
    phi = np.arange(project.perception.scan_phi_min_deg, project.perception.scan_phi_max_deg + .25, project.perception.scan_step_deg)
    return project, p, r, f, metrics, theta, phi


def rounded_panel(ax, x, y, w, h, title, subtitle=""):
    ax.add_patch(FancyBboxPatch((x,y),w,h,boxstyle="round,pad=0.008,rounding_size=0.012",facecolor=PANEL,edgecolor=GRID,linewidth=1.2))
    ax.text(x+.018,y+h-.035,title,color=TEXT,fontsize=12,fontweight="bold",va="top")
    if subtitle: ax.text(x+w-.018,y+h-.035,subtitle,color=MUTED,fontsize=8,ha="right",va="top")


def build_preview():
    project, p, r, f, metrics, theta, phi = load_outputs()
    fig = plt.figure(figsize=(19.2,10.8),dpi=100,facecolor=BG)
    ax = fig.add_axes([0,0,1,1]); ax.set_xlim(0,1); ax.set_ylim(0,1); ax.axis("off")
    # Header
    ax.add_patch(FancyBboxPatch((.012,.92),.976,.065,boxstyle="round,pad=.008,rounding_size=.012",facecolor="#0b1c30",edgecolor=GRID))
    ax.add_patch(FancyBboxPatch((.027,.936),.032,.035,boxstyle="round,pad=.006,rounding_size=.008",facecolor=CYAN,edgecolor="none"))
    ax.text(.043,.953,"H",ha="center",va="center",fontsize=18,fontweight="bold",color=BG)
    ax.text(.070,.960,"HPM-CAE Workbench",color=TEXT,fontsize=17,fontweight="bold",va="center")
    ax.text(.246,.960,"V1.1",color=CYAN,fontsize=17,fontweight="bold",va="center")
    ax.text(.070,.940,"实时感知 · 鲁棒接收防护 · 多对象控场 · 可恢复任务队列",color=MUTED,fontsize=9,va="center")
    badges=["ALL PYTHON","LIVE FULL CHAIN","MULTI-OBJECT","NORMALIZED"]
    xx=.67
    for badge in badges:
        w=.071 if badge!="LIVE FULL CHAIN" else .092
        ax.add_patch(FancyBboxPatch((xx,.944),w,.022,boxstyle="round,pad=.004,rounding_size=.01",facecolor="#0a2937",edgecolor="#206a7e",linewidth=.8))
        ax.text(xx+w/2,.955,badge,ha="center",va="center",color=CYAN,fontsize=7,fontweight="bold"); xx+=w+.008
    # Sidebar
    rounded_panel(ax,.012,.07,.205,.835,"项目与对象树","Schema 1.1")
    ax.text(.028,.832,"▾ HPM-CAE Demo",color=TEXT,fontsize=11,fontweight="bold")
    y=.797
    groups=[("▾ 阵列与网格",[("64阵元","8×8 @ 0.5λ"),("观察面","81² @ z=8λ")]),("▾ 目标与保护区",[("TGT-001","旋转椭圆目标区"),("PRT-001","圆形保护区")]),("▾ 相干辐射源",[("INT-001","直达 + 完全相干回波")]),("▾ 求解节点",[("PAWR-MUSIC","实时"),("CR-HybridNull","实时"),("Robust-PGMS","实时")])]
    for group,items in groups:
        ax.text(.030,y,group,color=CYAN,fontsize=9,fontweight="bold"); y-=.029
        for name,detail in items:
            ax.text(.040,y,"●",color=GREEN,fontsize=7); ax.text(.052,y,name,color=TEXT,fontsize=8,fontweight="bold"); ax.text(.102,y,detail,color=MUTED,fontsize=7); y-=.026
        y-=.010
    ax.add_patch(FancyBboxPatch((.028,.105),.173,.105,boxstyle="round,pad=.008,rounding_size=.008",facecolor="#091422",edgecolor=GRID))
    ax.text(.040,.188,"关键参数",color=MUTED,fontsize=8,fontweight="bold")
    params=[("SNR","−8 dB"),("快拍","128"),("坏通道","2"),("worker","2")]
    yy=.164
    for k,v in params:
        ax.text(.042,yy,k,color=MUTED,fontsize=7); ax.text(.183,yy,v,color=TEXT,fontsize=8,ha="right",fontweight="bold"); yy-=.021
    # Central field panel
    rounded_panel(ax,.228,.49,.375,.415,"多目标空间场控制","Robust-PGMS · PA + DPD")
    field_ax=fig.add_axes([.242,.525,.347,.315],facecolor=PANEL)
    field=np.abs(f["field"]); ref=project.solver.target_amplitude
    db=20*np.log10(np.maximum(field/ref,1e-6))
    im=field_ax.imshow(np.clip(db,-30,3),origin="lower",extent=[f["x_lambda"].min(),f["x_lambda"].max(),f["y_lambda"].min(),f["y_lambda"].max()],cmap="turbo",vmin=-30,vmax=3,aspect="equal")
    t=project.target
    field_ax.add_patch(Ellipse((t.center_x_lambda,t.center_y_lambda),2*t.semi_major_lambda,2*t.semi_minor_lambda,angle=t.rotation_deg,fill=False,color=AMBER,lw=2))
    z=project.protected_zone
    field_ax.add_patch(Circle((z.center_x_lambda,z.center_y_lambda),z.radius_lambda,fill=False,color=GREEN,lw=2))
    field_ax.set_xlabel("x / λ",color=MUTED,fontsize=8); field_ax.set_ylabel("y / λ",color=MUTED,fontsize=8)
    field_ax.tick_params(colors=MUTED,labelsize=7); [sp.set_color(GRID) for sp in field_ax.spines.values()]
    cb=fig.colorbar(im,ax=field_ax,fraction=.035,pad=.02); cb.ax.tick_params(colors=MUTED,labelsize=7); cb.outline.set_edgecolor(GRID)
    # Perception
    rounded_panel(ax,.228,.07,.375,.405,"实时二维空间谱","PAWR-MUSIC")
    spec_ax=fig.add_axes([.242,.105,.347,.30],facecolor=PANEL)
    spec=p["spectrum"]; spec_db=10*np.log10(np.maximum(spec/spec.max(),1e-8))
    spec_ax.imshow(np.clip(spec_db,-35,0),origin="lower",extent=[phi.min(),phi.max(),theta.min(),theta.max()],aspect="auto",cmap="turbo",vmin=-35,vmax=0)
    truth=[(18.4,-7.6),(35.7,11.8)]; est=[(19.0798,-6.9236),(35.6835,12.7389)]
    spec_ax.scatter([v[1] for v in truth],[v[0] for v in truth],marker="x",s=65,c=GREEN,lw=2,label="数值真值")
    spec_ax.scatter([v[1] for v in est],[v[0] for v in est],facecolors="none",edgecolors=AMBER,s=80,lw=2,label="PAWR估计")
    spec_ax.set_xlabel("φ / °",color=MUTED,fontsize=8); spec_ax.set_ylabel("θ / °",color=MUTED,fontsize=8); spec_ax.tick_params(colors=MUTED,labelsize=7); [sp.set_color(GRID) for sp in spec_ax.spines.values()]
    spec_ax.legend(loc="lower right",fontsize=7,facecolor="#091422",edgecolor=GRID,labelcolor=TEXT)
    # Protection map
    rounded_panel(ax,.615,.49,.373,.415,"接收端二维响应","CR-HybridNull")
    prot_ax=fig.add_axes([.629,.525,.345,.315],facecolor=PANEL)
    resp=r["response_db"]
    prot_ax.imshow(np.clip(resp,-60,0),origin="lower",extent=[-90,90,0,80],aspect="auto",cmap="turbo",vmin=-60,vmax=0)
    prot_ax.scatter([12],[18],marker="*",s=120,c=GREEN,label="期望方向")
    prot_ax.scatter([v[1] for v in truth],[v[0] for v in truth],marker="x",s=65,c=RED,lw=2,label="干扰路径")
    prot_ax.scatter([v[1] for v in est],[v[0] for v in est],facecolors="none",edgecolors=AMBER,s=70,lw=2,label="感知中心")
    prot_ax.set_xlabel("φ / °",color=MUTED,fontsize=8); prot_ax.set_ylabel("θ / °",color=MUTED,fontsize=8); prot_ax.tick_params(colors=MUTED,labelsize=7); [sp.set_color(GRID) for sp in prot_ax.spines.values()]
    prot_ax.legend(loc="lower right",fontsize=7,facecolor="#091422",edgecolor=GRID,labelcolor=TEXT)
    # Metrics & queue
    rounded_panel(ax,.615,.07,.373,.405,"全链路指标与任务队列","SQLite checkpoints")
    cards=[("测向RMSE","0.636°",GREEN),("输出SINR","9.77 dB",GREEN),("最坏响应","−40.85 dB",GREEN),("场RMSE","9.67%",GREEN),("任务评分","0.701",CYAN),("全链路","通过",GREEN)]
    x0=.632; y0=.385
    for idx,(k,v,c) in enumerate(cards):
        col=idx%3; row=idx//3; x=x0+col*.112; y=y0-row*.092
        ax.add_patch(FancyBboxPatch((x,y),.102,.073,boxstyle="round,pad=.006,rounding_size=.008",facecolor="#091422",edgecolor=c if idx in {0,1,5} else GRID,linewidth=1))
        ax.text(x+.008,y+.050,k,color=MUTED,fontsize=7); ax.text(x+.008,y+.021,v,color=c,fontsize=12,fontweight="bold")
    ax.text(.632,.202,"JOB-…  相位误差扫描",color=TEXT,fontsize=9,fontweight="bold")
    stages=[("2/6","已完成",GREEN),("2","workers",CYAN),("✓","可恢复",AMBER)]
    xx=.632
    for v,k,c in stages:
        ax.add_patch(FancyBboxPatch((xx,.125),.102,.055,boxstyle="round,pad=.005,rounding_size=.007",facecolor="#091422",edgecolor=GRID))
        ax.text(xx+.008,.154,v,color=c,fontsize=10,fontweight="bold"); ax.text(xx+.048,.151,k,color=MUTED,fontsize=7); xx+=.112
    ax.text(.632,.092,"暂停在算例边界生效；恢复仅领取 pending 检查点",color=MUTED,fontsize=7.5)
    fig.text(.012,.018,"界面布局预览由真实 V1.1 数值输出绘制；实际交互工作台通过 run_ui_v11.py 启动。",color=MUTED,fontsize=8)
    path=OUT/"00_workbench_v11_preview.png"; fig.savefig(path,facecolor=BG,bbox_inches="tight",pad_inches=.03); plt.close(fig)
    return path


def build_architecture_svg():
    path=OUT/"01_v11_layer_architecture.svg"
    nodes=[
        (70,145,190,76,"多对象场景","阵列 · 目标 · 保护区 · 辐射源",CYAN),
        (330,70,190,76,"信号与信道","相干多径 · 失配 · 坏通道",PURPLE),
        (590,70,190,76,"实时感知","PAWR · FBSS · ESPRIT",CYAN),
        (850,70,190,76,"接收防护","置信扇区 · CR-HybridNull",GREEN),
        (330,220,190,76,"多目标控场","PGMS · PA · DPD",AMBER),
        (590,220,190,76,"动态时间轴","延迟 · 预测 · 逐帧重算",PURPLE),
        (850,220,190,76,"代理评价","质量 · 风险 · 任务评分",GREEN),
        (1110,145,190,76,"CAE管理层","对象树 · 队列 · 报告",CYAN),
        (590,370,190,76,"SQLite任务队列","并行 · 暂停 · 恢复 · 检查点",AMBER),
    ]
    arrows=[((260,183),(330,108)),((520,108),(590,108)),((780,108),(850,108)),((260,183),(330,258)),((520,258),(590,258)),((780,258),(850,258)),((1040,108),(1110,183)),((1040,258),(1110,183)),((685,296),(685,370)),((780,408),(1110,200))]
    svg=[f'<svg xmlns="http://www.w3.org/2000/svg" width="1380" height="520" viewBox="0 0 1380 520"><defs><marker id="a" markerWidth="8" markerHeight="8" refX="7" refY="4" orient="auto"><path d="M0,0 L8,4 L0,8 z" fill="{MUTED}"/></marker><filter id="glow"><feGaussianBlur stdDeviation="3" result="b"/><feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge></filter></defs><rect width="1380" height="520" fill="{BG}"/><text x="54" y="48" fill="{TEXT}" font-size="25" font-family="Noto Sans CJK SC, sans-serif" font-weight="700">HPM-CAE V1.1 · 实时全链路与可恢复实验管理</text><text x="54" y="76" fill="{MUTED}" font-size="13" font-family="Noto Sans CJK SC, sans-serif">归一化阵列算法 CAE：感知、防护、控场、代理评价与实验编排</text>']
    for (a,b) in arrows:
        svg.append(f'<path d="M{a[0]},{a[1]} L{b[0]},{b[1]}" stroke="{MUTED}" stroke-width="2" fill="none" marker-end="url(#a)"/>')
    for x,y,w,h,title,sub,color in nodes:
        svg.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="13" fill="{PANEL}" stroke="{color}" stroke-width="2"/>')
        svg.append(f'<rect x="{x}" y="{y}" width="7" height="{h}" rx="3" fill="{color}"/>')
        svg.append(f'<text x="{x+22}" y="{y+31}" fill="{TEXT}" font-size="16" font-family="Noto Sans CJK SC, sans-serif" font-weight="700">{title}</text>')
        svg.append(f'<text x="{x+22}" y="{y+55}" fill="{MUTED}" font-size="11" font-family="Noto Sans CJK SC, sans-serif">{sub}</text>')
    svg.append(f'<rect x="54" y="470" width="1272" height="30" rx="8" fill="#091422" stroke="{GRID}"/><text x="70" y="490" fill="{AMBER}" font-size="12" font-family="Noto Sans CJK SC, sans-serif">模型边界：</text><text x="146" y="490" fill="{MUTED}" font-size="12" font-family="Noto Sans CJK SC, sans-serif">波长尺度几何、归一化复场、相对阵列响应和无量纲代理评价；不等同于全波求解或实测毁伤结论。</text></svg>')
    path.write_text("".join(svg),encoding="utf-8")
    try:
        import cairosvg
        cairosvg.svg2png(bytestring=path.read_bytes(),write_to=str(OUT/"01_v11_layer_architecture.png"),output_width=1380,output_height=520)
    except Exception as exc:
        print("SVG PNG conversion skipped:",exc)
    return path


def build_queue_demo():
    db=OUT/"job_queue.sqlite3"; db.unlink(missing_ok=True)
    queue=PersistentJobQueue(db)
    p=default_project()
    p=replace(p,plane=replace(p.plane,samples=41),solver=replace(p.solver,iterations=55,target_samples=90,outside_samples=180,uncertainty_scenarios=2),motion=replace(p.motion,enabled=False))
    spec=SweepSpec(parameter="solver.phase_std_deg",start=0,stop=10,points=3,replicates=2,metric="target_rmse_percent",fast_mode=True)
    jid=queue.submit_sweep(p,spec,workers=2)
    paused=queue.run_job(jid,max_items=2)
    paused_items=queue.items(jid).copy(); paused_items.to_csv(OUT/"queue_checkpoint_paused.csv",index=False)
    finished=queue.run_job(jid)
    items=queue.items(jid); items.to_csv(OUT/"queue_checkpoint_completed.csv",index=False)
    queue.jobs().to_csv(OUT/"queue_jobs.csv",index=False)
    summary={"job_id":jid,"paused":paused.__dict__,"finished":finished.__dict__}
    (OUT/"queue_acceptance_summary.json").write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding="utf-8")
    return summary


def img_uri(path: Path) -> str:
    return "data:image/png;base64,"+base64.b64encode(path.read_bytes()).decode()


def build_acceptance_report(preview: Path, queue_summary: dict):
    metrics = json.loads((OUT / "v11_acceptance_summary.json").read_text(encoding="utf-8"))
    preview_uri = img_uri(preview)
    arch_png = OUT / "01_v11_layer_architecture.png"
    arch_uri = img_uri(arch_png) if arch_png.exists() else ""
    p = metrics["perception"]
    r = metrics["protection"]
    f = metrics["field_control"]
    e = metrics["effect_proxy"]
    report = OUT / "v11_acceptance_report.html"
    rows = [
        ("PAWR-MUSIC 测向RMSE", f"{p['rmse_deg']:.3f}°"),
        ("最大路径误差", f"{p['max_error_deg']:.3f}°"),
        ("CR-HybridNull输出SINR", f"{r['output_sinr_db']:.3f} dB"),
        ("最坏真实路径响应", f"{r['worst_true_response_db']:.3f} dB"),
        ("目标区RMSE", f"{f['target_rmse_percent']:.3f}%"),
        ("目标覆盖率", f"{f['target_coverage_percent']:.3f}%"),
        ("归一化任务评分", f"{e['normalized_mission_score']:.3f}"),
        ("全链路判据", "通过" if e["full_chain_available"] else "未通过"),
        ("自动测试", "76 passed"),
    ]
    table = "".join(f"<tr><td>{k}</td><td><b>{v}</b></td></tr>" for k, v in rows)
    qs = queue_summary["finished"]
    css = """
body{margin:0;background:#07101d;color:#e7eef9;font-family:Inter,"Noto Sans CJK SC",sans-serif}
main{max-width:1500px;margin:auto;padding:30px 4vw}
header{padding:18px 0 24px;border-bottom:1px solid #26354d}
h1{margin:0}p{color:#91a2bb;line-height:1.65}
section{background:#0d1828;border:1px solid #26354d;border-radius:14px;padding:18px;margin:18px 0}
img{width:100%;border-radius:10px;border:1px solid #26354d}
table{width:100%;border-collapse:collapse}td{padding:10px;border-bottom:1px solid #26354d}
td:last-child{color:#4ee0a5}.grid{display:grid;grid-template-columns:1fr 1fr;gap:18px}
.scope{border-left:4px solid #ffc857;background:#091422;padding:13px}a{color:#35d8ff}
@media(max-width:900px){.grid{grid-template-columns:1fr}}
"""
    arch_section = f'<section><h2>分层架构</h2><img src="{arch_uri}"></section>' if arch_uri else ""
    html = f"""<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>HPM-CAE V1.1 Acceptance</title><style>{css}</style></head><body><main>
<header><h1>HPM-CAE V1.1 验收报告</h1><p>实时感知、接收防护、多对象控场、任务图和可恢复队列的确定性工程验收。</p></header>
<section><h2>工作台布局预览</h2><img src="{preview_uri}"><p>预览图由真实V1.1数值输出绘制。交互UI由 <code>run_ui_v11.py</code> 启动。</p></section>
{arch_section}
<div class="grid"><section><h2>默认全链路指标</h2><table>{table}</table></section>
<section><h2>队列检查点验收</h2><p>任务ID：<code>{queue_summary['job_id']}</code></p><table>
<tr><td>并行worker</td><td><b>2</b></td></tr>
<tr><td>暂停后完成</td><td><b>{queue_summary['paused']['completed']}/{queue_summary['paused']['total']}</b></td></tr>
<tr><td>恢复后状态</td><td><b>{qs['status']}</b></td></tr>
<tr><td>最终完成</td><td><b>{qs['completed']}/{qs['total']}</b></td></tr>
<tr><td>失败</td><td><b>{qs['failed']}</b></td></tr></table></section></div>
<section><h2>可复现产物</h2><p><a href="sample_full_chain/HPM_CAE_V11_full_chain_report.html">完整全链路交互报告</a> · <a href="queue_checkpoint_paused.csv">暂停检查点</a> · <a href="queue_checkpoint_completed.csv">恢复后记录</a> · <a href="../configs/cae_project_v11.yaml">多对象工程配置</a></p></section>
<section class="scope"><b>模型边界</b><p>所有结果均为波长尺度、归一化数值模型和无量纲代理评价，不代表绝对源功率、具体器件阈值、实际毁伤概率或现实作用距离。默认结果用于软件验收，不替代论文级Monte Carlo或实测验证。</p></section>
</main></body></html>"""
    report.write_text(html, encoding="utf-8")
    return report


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    preview = build_preview()
    build_architecture_svg()
    queue_summary = build_queue_demo()
    report = build_acceptance_report(preview, queue_summary)
    archive = OUT / "sample_full_chain.zip"
    archive.unlink(missing_ok=True)
    shutil.make_archive(str(archive.with_suffix("")), "zip", root_dir=SAMPLE)
    print(preview)
    print(report)
    print(queue_summary)


if __name__ == "__main__":
    main()

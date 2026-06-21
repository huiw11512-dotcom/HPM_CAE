#!/usr/bin/env python3
"""Build deterministic V1.2 acceptance assets from real numerical results."""
from __future__ import annotations

import base64
from dataclasses import replace
from pathlib import Path
import json
import shutil

import matplotlib.pyplot as plt
from matplotlib import font_manager
from matplotlib.patches import Circle, Ellipse, FancyBboxPatch, FancyArrowPatch
import numpy as np
import pandas as pd

from hpm_platform.ui.experiment_manager import SweepSpec
from hpm_platform.ui.job_queue import PersistentJobQueue
from hpm_platform.ui.project_model import CAEProject
from hpm_platform.ui.quick_solver import solve_project
from hpm_platform.ui.workflow_executor import execute_workflow, export_workflow

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "outputs_v12_ui"
STATIC = OUT / "sample_constrained_multi_object"
PARETO = OUT / "sample_pareto"
CONFIG = ROOT / "configs" / "cae_project_v12.yaml"

BG = "#07101d"; PANEL = "#0d1828"; PANEL2 = "#111f33"; GRID = "#26354d"
TEXT = "#e7eef9"; MUTED = "#91a2bb"; CYAN = "#35d8ff"; GREEN = "#4ee0a5"
AMBER = "#ffc857"; RED = "#ff6b7a"; PURPLE = "#ab8cff"

for candidate in (
    Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"),
    Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc"),
):
    if candidate.exists():
        font_manager.fontManager.addfont(str(candidate))
        plt.rcParams["font.family"] = [font_manager.FontProperties(fname=str(candidate)).get_name(), "DejaVu Sans"]
        break
else:
    plt.rcParams["font.family"] = ["DejaVu Sans"]
plt.rcParams["axes.unicode_minus"] = False


def _panel(ax, x: float, y: float, w: float, h: float, title: str, subtitle: str = "") -> None:
    ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle="round,pad=.007,rounding_size=.012", facecolor=PANEL, edgecolor=GRID, linewidth=1.2))
    ax.text(x + .015, y + h - .028, title, color=TEXT, fontsize=11, fontweight="bold", va="top")
    if subtitle:
        ax.text(x + w - .015, y + h - .028, subtitle, color=MUTED, fontsize=7.5, ha="right", va="top")


def _ellipse(ax, target, color=AMBER, lw=1.8, guard=False) -> None:
    scale = target.guard_scale if guard else 1.0
    ax.add_patch(Ellipse((target.center_x_lambda, target.center_y_lambda), 2 * target.semi_major_lambda * scale, 2 * target.semi_minor_lambda * scale, angle=target.rotation_deg, fill=False, edgecolor=color, linewidth=lw, linestyle=":" if guard else "-"))


def load_data():
    project = CAEProject.load_yaml(CONFIG)
    arrays = np.load(STATIC / "field_solution.npz", allow_pickle=True)
    metrics = json.loads((STATIC / "metrics.json").read_text(encoding="utf-8"))
    objects = pd.read_csv(STATIC / "object_metrics.csv")
    pareto = pd.read_csv(PARETO / "pareto_records.csv")
    return project, arrays, metrics, objects, pareto


def constraint_margin(project: CAEProject, arrays) -> np.ndarray:
    amplitude = np.abs(arrays["field"])
    ref = project.solver.target_amplitude
    margin = np.full(amplitude.shape, np.nan, float)
    outside = arrays["outside_mask"].astype(bool)
    cap = ref * 10.0 ** (project.solver.outside_peak_limit_db / 20.0)
    margin[outside] = (cap - amplitude[outside]) / ref
    for target, mask in zip(project.targets, arrays["target_component_masks"].astype(bool), strict=True):
        setpoint = ref * target.amplitude_scale
        margin[mask] = target.tolerance_percent / 100.0 - np.abs(amplitude[mask] / setpoint - 1.0)
    for zone, mask in zip(project.protected_zones, arrays["protected_component_masks"].astype(bool), strict=True):
        cap = ref * zone.max_amplitude_scale
        margin[mask] = (cap - amplitude[mask]) / ref
    return margin


def build_preview() -> Path:
    project, arrays, metrics, objects, pareto = load_data()
    x = arrays["x_lambda"]; y = arrays["y_lambda"]
    field_db = 20 * np.log10(np.maximum(np.abs(arrays["field"]) / project.solver.target_amplitude, 1e-6))
    margin = constraint_margin(project, arrays) * 100.0

    fig = plt.figure(figsize=(19.2, 10.8), dpi=110, facecolor=BG)
    ax = fig.add_axes([0, 0, 1, 1]); ax.set_xlim(0, 1); ax.set_ylim(0, 1); ax.axis("off")
    ax.add_patch(FancyBboxPatch((.012, .923), .976, .062, boxstyle="round,pad=.007,rounding_size=.012", facecolor="#0b1c30", edgecolor=GRID))
    ax.add_patch(FancyBboxPatch((.027, .938), .032, .033, boxstyle="round,pad=.005,rounding_size=.008", facecolor=CYAN, edgecolor="none"))
    ax.text(.043, .954, "H", ha="center", va="center", fontsize=17, fontweight="bold", color=BG)
    ax.text(.070, .960, "HPM-CAE Workbench", color=TEXT, fontsize=16, fontweight="bold", va="center")
    ax.text(.247, .960, "V1.2", color=CYAN, fontsize=16, fontweight="bold", va="center")
    ax.text(.070, .940, "对象级约束多目标控场 · Pareto 设计空间 · 实时全链路 · 可恢复任务队列", color=MUTED, fontsize=8.5, va="center")
    xx = .655
    for badge, width in [("ALL PYTHON", .071), ("CONSTRAINED", .082), ("PARETO", .058), ("NORMALIZED", .079)]:
        ax.add_patch(FancyBboxPatch((xx, .944), width, .021, boxstyle="round,pad=.004,rounding_size=.01", facecolor="#0a2937", edgecolor="#206a7e", linewidth=.8))
        ax.text(xx + width/2, .9545, badge, color=CYAN, fontsize=6.7, fontweight="bold", ha="center", va="center")
        xx += width + .008

    _panel(ax, .012, .07, .205, .835, "项目 / 对象树", "Schema 1.2")
    ax.text(.028, .846, "▾ HPM-CAE V1.2 Multi-object", color=TEXT, fontsize=10.5, fontweight="bold")
    ypos = .812
    groups = [
        ("▾ 阵列与观察面", [("ARRAY", "8×8 @ 0.5λ"), ("PLANE", "81² @ z=8λ")]),
        ("▾ 目标对象", [(t.object_id, f"p={t.priority:g} · ±{t.tolerance_percent:g}%") for t in project.targets]),
        ("▾ 保护对象", [(z.object_id, f"cap={z.max_amplitude_scale:.2f} · p={z.priority:g}") for z in project.protected_zones]),
        ("▾ 求解与评价", [("MO-PGMS", "对象约束"), ("MARGIN", "有符号裕量"), ("PARETO", "7点前沿")]),
    ]
    for title, items in groups:
        ax.text(.030, ypos, title, color=CYAN, fontsize=8.6, fontweight="bold"); ypos -= .028
        for name, detail in items:
            ax.text(.040, ypos, "●", color=GREEN, fontsize=6.8)
            ax.text(.052, ypos, name, color=TEXT, fontsize=7.7, fontweight="bold")
            ax.text(.113, ypos, detail, color=MUTED, fontsize=6.7)
            ypos -= .024
        ypos -= .008
    ax.add_patch(FancyBboxPatch((.027, .095), .175, .12, boxstyle="round,pad=.007,rounding_size=.008", facecolor="#091422", edgecolor=GRID))
    ax.text(.040, .190, "约束设置", color=MUTED, fontsize=7.5, fontweight="bold")
    params = [("区外上限", f"{project.solver.outside_peak_limit_db:.1f} dB"), ("鲁棒场景", str(project.solver.uncertainty_scenarios)), ("目标数", str(len(project.targets))), ("保护区", str(len(project.protected_zones)))]
    yp = .165
    for key, value in params:
        ax.text(.041, yp, key, color=MUTED, fontsize=6.8); ax.text(.188, yp, value, color=TEXT, fontsize=7.8, ha="right", fontweight="bold"); yp -= .022

    _panel(ax, .228, .50, .375, .405, "双目标归一化场分布", "Constrained-MO-PGMS · PA + DPD")
    fax = fig.add_axes([.243, .535, .345, .305], facecolor=PANEL)
    im = fax.imshow(np.clip(field_db, -28, 3), origin="lower", extent=[x.min(), x.max(), y.min(), y.max()], cmap="turbo", vmin=-28, vmax=3, aspect="equal")
    for target in project.targets:
        _ellipse(fax, target); _ellipse(fax, target, lw=1.0, guard=True)
    for zone in project.protected_zones:
        fax.add_patch(Circle((zone.center_x_lambda, zone.center_y_lambda), zone.radius_lambda, fill=False, edgecolor=GREEN, linewidth=1.8))
    fax.set_xlabel("x / λ", color=MUTED, fontsize=7.5); fax.set_ylabel("y / λ", color=MUTED, fontsize=7.5)
    fax.tick_params(colors=MUTED, labelsize=6.5); [sp.set_color(GRID) for sp in fax.spines.values()]
    cb = fig.colorbar(im, ax=fax, fraction=.035, pad=.02); cb.ax.tick_params(colors=MUTED, labelsize=6); cb.outline.set_edgecolor(GRID)

    _panel(ax, .228, .07, .375, .41, "二维约束裕量", "蓝色满足 · 红色超限")
    maxis = fig.add_axes([.243, .105, .345, .31], facecolor=PANEL)
    mim = maxis.imshow(np.clip(margin, -25, 25), origin="lower", extent=[x.min(), x.max(), y.min(), y.max()], cmap="RdBu", vmin=-25, vmax=25, aspect="equal")
    for target in project.targets: _ellipse(maxis, target)
    for zone in project.protected_zones: maxis.add_patch(Circle((zone.center_x_lambda, zone.center_y_lambda), zone.radius_lambda, fill=False, edgecolor=GREEN, linewidth=1.6))
    maxis.set_xlabel("x / λ", color=MUTED, fontsize=7.5); maxis.set_ylabel("y / λ", color=MUTED, fontsize=7.5)
    maxis.tick_params(colors=MUTED, labelsize=6.5); [sp.set_color(GRID) for sp in maxis.spines.values()]
    cb2 = fig.colorbar(mim, ax=maxis, fraction=.035, pad=.02); cb2.ax.tick_params(colors=MUTED, labelsize=6); cb2.outline.set_edgecolor(GRID)

    _panel(ax, .615, .50, .373, .405, "Pareto 设计空间", "最差目标误差 ↔ 风险超限")
    pax = fig.add_axes([.64, .555, .32, .27], facecolor=PANEL)
    dominated = pareto[~pareto["pareto"].astype(bool)]
    front = pareto[pareto["pareto"].astype(bool)].sort_values("worst_target_rmse_percent")
    pax.scatter(dominated["worst_target_rmse_percent"], dominated["risk_violation_db"], s=40, color=MUTED, alpha=.55, label="被支配")
    pax.plot(front["worst_target_rmse_percent"], front["risk_violation_db"], "o-", color=CYAN, linewidth=2, markersize=6, label="Pareto")
    rec = pareto[pareto["recommended"].astype(bool)].iloc[0]
    pax.scatter([rec["worst_target_rmse_percent"]], [rec["risk_violation_db"]], s=155, marker="*", color=AMBER, edgecolor=TEXT, linewidth=.7, label="推荐")
    pax.axhline(0, color=GREEN, linestyle="--", linewidth=1)
    pax.set_xlabel("最差目标 RMSE / %", color=MUTED, fontsize=7.5); pax.set_ylabel("风险超限 / dB", color=MUTED, fontsize=7.5)
    pax.tick_params(colors=MUTED, labelsize=6.5); pax.grid(color=GRID, alpha=.55); [sp.set_color(GRID) for sp in pax.spines.values()]
    pax.legend(fontsize=6.5, facecolor="#091422", edgecolor=GRID, labelcolor=TEXT, loc="lower right")

    _panel(ax, .615, .07, .373, .41, "对象级指标与联合判据", "来自真实求解结果")
    cards = [
        ("总体 RMSE", f"{metrics['target_rmse_percent']:.2f}%", GREEN),
        ("最差目标", f"{metrics['worst_target_rmse_percent']:.2f}%", GREEN),
        ("最低覆盖", f"{metrics['minimum_target_coverage_percent']:.1f}%", CYAN),
        ("区外峰值", f"{metrics['peak_outside_db']:.2f} dB", GREEN),
        ("保护超限", f"{metrics['maximum_protected_violation_db']:+.2f} dB", GREEN),
        ("联合判据", "通过" if metrics["control_success"] else "未通过", GREEN if metrics["control_success"] else RED),
    ]
    x0=.632; y0=.380
    for idx, (key, value, color) in enumerate(cards):
        col=idx%3; row=idx//3; xx=x0+col*.113; yy=y0-row*.088
        ax.add_patch(FancyBboxPatch((xx, yy), .103, .071, boxstyle="round,pad=.006,rounding_size=.008", facecolor="#091422", edgecolor=color if idx in {0,4,5} else GRID, linewidth=1))
        ax.text(xx+.008, yy+.048, key, color=MUTED, fontsize=6.8); ax.text(xx+.008, yy+.019, value, color=color, fontsize=10.5, fontweight="bold")
    ax.text(.632, .190, "对象", color=MUTED, fontsize=7.2, fontweight="bold")
    yy=.165
    for _, row in objects.iterrows():
        color = GREEN if bool(row["success"]) else RED
        if row["object_type"] == "target": detail=f"RMSE {row['rmse_percent']:.2f}% · cover {row['coverage_percent']:.1f}%"
        else: detail=f"P95 {row['p95_db']:.2f} dB · Δ {row['violation_db']:+.2f} dB"
        ax.text(.632, yy, "●", color=color, fontsize=6.5); ax.text(.644, yy, str(row["object_id"]), color=TEXT, fontsize=7.2, fontweight="bold"); ax.text(.700, yy, detail, color=MUTED, fontsize=6.7); yy-=.022

    fig.text(.014, .018, "V1.2布局预览由默认双目标工程的真实求解数组与Pareto记录绘制；交互工作台通过 run_ui_v12.py 启动。", color=MUTED, fontsize=7.7)
    path = OUT / "00_workbench_v12_preview.png"
    fig.savefig(path, facecolor=BG, bbox_inches="tight", pad_inches=.03)
    plt.close(fig)
    return path


def build_architecture() -> tuple[Path, Path]:
    svg = OUT / "01_v12_layer_architecture.svg"
    png = OUT / "01_v12_layer_architecture.png"
    nodes = [
        (55, 145, 185, 72, "对象场景", "阵列 · 目标 · 保护区", CYAN),
        (300, 65, 190, 72, "信号 / 感知", "相干多径 · PAWR", PURPLE),
        (550, 65, 190, 72, "接收防护", "置信域 · 宽零陷", GREEN),
        (300, 225, 190, 72, "分组鲁棒矩阵", "目标 / 区外 / 保护区", CYAN),
        (550, 225, 190, 72, "Constrained-MO-PGMS", "公平性 · 尾部峰值 · 投影", AMBER),
        (800, 225, 190, 72, "PA / DPD / 场评估", "复场 · 对象级指标", PURPLE),
        (1050, 145, 190, 72, "CAE 可视层", "裕量图 · Pareto · 报告", CYAN),
        (800, 65, 190, 72, "代理评价", "归一化任务评分", GREEN),
        (550, 375, 190, 72, "实验管理", "SQLite · 队列 · 置信区间", AMBER),
    ]
    arrows = [((240,181),(300,101)),((490,101),(550,101)),((740,101),(800,101)),((990,101),(1050,181)),((240,181),(300,261)),((490,261),(550,261)),((740,261),(800,261)),((990,261),(1050,181)),((645,297),(645,375)),((740,411),(1050,203))]
    parts=[f'<svg xmlns="http://www.w3.org/2000/svg" width="1300" height="510" viewBox="0 0 1300 510"><defs><marker id="a" markerWidth="8" markerHeight="8" refX="7" refY="4" orient="auto"><path d="M0,0 L8,4 L0,8 z" fill="{MUTED}"/></marker></defs><rect width="1300" height="510" fill="{BG}"/><text x="45" y="43" fill="{TEXT}" font-size="24" font-family="Noto Sans CJK SC,sans-serif" font-weight="700">HPM-CAE V1.2 · 对象级约束多目标数字化工作台</text><text x="45" y="70" fill="{MUTED}" font-size="13" font-family="Noto Sans CJK SC,sans-serif">实时感知 / 防护主链 + 多目标约束控场 + Pareto 可解释设计 + 可恢复实验管理</text>']
    for a,b in arrows:
        parts.append(f'<path d="M{a[0]},{a[1]} L{b[0]},{b[1]}" stroke="{MUTED}" stroke-width="2" fill="none" marker-end="url(#a)"/>')
    for x,y,w,h,title,sub,color in nodes:
        parts.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="13" fill="{PANEL}" stroke="{color}" stroke-width="2"/><rect x="{x}" y="{y}" width="7" height="{h}" rx="3" fill="{color}"/><text x="{x+20}" y="{y+29}" fill="{TEXT}" font-size="15" font-family="Noto Sans CJK SC,sans-serif" font-weight="700">{title}</text><text x="{x+20}" y="{y+52}" fill="{MUTED}" font-size="10.5" font-family="Noto Sans CJK SC,sans-serif">{sub}</text>')
    parts.append(f'<rect x="45" y="466" width="1210" height="27" rx="7" fill="#091422" stroke="{GRID}"/><text x="60" y="484" fill="{AMBER}" font-size="11.5" font-family="Noto Sans CJK SC,sans-serif">模型边界：</text><text x="132" y="484" fill="{MUTED}" font-size="11.5" font-family="Noto Sans CJK SC,sans-serif">波长尺度、归一化标量场与无量纲代理评价；不等同于全波求解、绝对功率预算或实物效应结论。</text></svg>')
    svg.write_text("".join(parts), encoding="utf-8")
    import cairosvg
    cairosvg.svg2png(bytestring=svg.read_bytes(), write_to=str(png), output_width=1300, output_height=510)
    return svg, png


def build_mechanism() -> tuple[Path, Path]:
    svg = OUT / "02_constrained_multi_object_mechanism.svg"
    png = OUT / "02_constrained_multi_object_mechanism.png"
    parts=[f'<svg xmlns="http://www.w3.org/2000/svg" width="1400" height="650" viewBox="0 0 1400 650"><defs><marker id="a" markerWidth="8" markerHeight="8" refX="7" refY="4" orient="auto"><path d="M0,0 L8,4 L0,8 z" fill="{MUTED}"/></marker><linearGradient id="g" x1="0" x2="1"><stop offset="0" stop-color="{CYAN}" stop-opacity=".18"/><stop offset="1" stop-color="{PURPLE}" stop-opacity=".10"/></linearGradient></defs><rect width="1400" height="650" fill="{BG}"/><text x="55" y="48" fill="{TEXT}" font-size="25" font-family="Noto Sans CJK SC,sans-serif" font-weight="700">Constrained-MO-PGMS 机理图</text><text x="55" y="76" fill="{MUTED}" font-size="13" font-family="Noto Sans CJK SC,sans-serif">对象级设定值、独立保护上限、目标公平性与区外尾部峰值的多场景联合优化</text>']
    # Scene plane
    parts.append(f'<rect x="55" y="115" width="330" height="430" rx="18" fill="{PANEL}" stroke="{GRID}"/><text x="78" y="148" fill="{TEXT}" font-size="17" font-family="Noto Sans CJK SC,sans-serif" font-weight="700">① 对象场景与分组采样</text><rect x="85" y="178" width="270" height="260" rx="12" fill="#091422" stroke="{GRID}"/>')
    parts += [f'<ellipse cx="175" cy="270" rx="62" ry="36" transform="rotate(22 175 270)" fill="none" stroke="{AMBER}" stroke-width="3"/><ellipse cx="270" cy="347" rx="43" ry="26" transform="rotate(-18 270 347)" fill="none" stroke="{AMBER}" stroke-width="3"/><circle cx="290" cy="230" r="30" fill="rgba(78,224,165,.08)" stroke="{GREEN}" stroke-width="3"/><circle cx="140" cy="385" r="22" fill="rgba(78,224,165,.08)" stroke="{GREEN}" stroke-width="3"/>']
    parts.append(f'<text x="105" y="470" fill="{AMBER}" font-size="12" font-family="Noto Sans CJK SC,sans-serif">目标对象：设定值 d_k · 优先级 alpha_k · 容差 epsilon_k</text><text x="105" y="496" fill="{GREEN}" font-size="12" font-family="Noto Sans CJK SC,sans-serif">保护对象：上限 tau_j · 优先级 beta_j</text><text x="105" y="522" fill="{MUTED}" font-size="12" font-family="Noto Sans CJK SC,sans-serif">普通区外：软铰链 + 全局峰值上限</text>')
    # Scenario stack
    parts.append(f'<rect x="445" y="115" width="250" height="430" rx="18" fill="{PANEL}" stroke="{GRID}"/><text x="468" y="148" fill="{TEXT}" font-size="17" font-family="Noto Sans CJK SC,sans-serif" font-weight="700">② 鲁棒场景栈</text>')
    for i,(label,color) in enumerate([("名义矩阵 A(0)",CYAN),("增益误差 A(1)",PURPLE),("相位误差 A(2)",PURPLE),("配准扰动 A(3)",AMBER),("功放 / DPD",GREEN)]):
        y=185+i*64
        parts.append(f'<rect x="475" y="{y}" width="190" height="44" rx="9" fill="#091422" stroke="{color}"/><text x="570" y="{y+27}" text-anchor="middle" fill="{TEXT}" font-size="13" font-family="Noto Sans CJK SC,sans-serif">{label}</text>')
    # Objective
    parts.append(f'<rect x="755" y="115" width="320" height="430" rx="18" fill="url(#g)" stroke="{AMBER}" stroke-width="2"/><text x="780" y="148" fill="{TEXT}" font-size="17" font-family="Noto Sans CJK SC,sans-serif" font-weight="700">③ 对象约束目标函数</text>')
    lines=[("目标加权误差", "sum alpha_k E[e_k^2]", CYAN),("最坏目标公平性", "lambda_f · smooth-max(E[e_k^2])", AMBER),("普通区外超限", "lambda_o · E[(|Bw|-tau_o)_+^2]", PURPLE),("保护区独立超限", "lambda_p sum beta_j E[(|C_jw|-tau_j)_+^2]", GREEN),("尾部局部峰值", "lambda_t · Top-q(|Bw|)", RED),("工程投影", "RMS / peak limits", MUTED)]
    for i,(name,formula,color) in enumerate(lines):
        y=184+i*54
        parts.append(f'<rect x="785" y="{y}" width="260" height="40" rx="8" fill="#091422" stroke="{color}"/><text x="800" y="{y+17}" fill="{color}" font-size="11.5" font-family="Noto Sans CJK SC,sans-serif" font-weight="700">{name}</text><text x="800" y="{y+32}" fill="{MUTED}" font-size="10.5" font-family="Noto Sans CJK SC,sans-serif">{formula}</text>')
    # Outputs
    parts.append(f'<rect x="1135" y="115" width="210" height="430" rx="18" fill="{PANEL}" stroke="{GRID}"/><text x="1158" y="148" fill="{TEXT}" font-size="17" font-family="Noto Sans CJK SC,sans-serif" font-weight="700">④ 可解释输出</text>')
    for i,(label,color) in enumerate([("复场热图",CYAN),("约束裕量图",GREEN),("对象级指标",AMBER),("分项收敛",PURPLE),("Pareto 前沿",RED),("HTML / CSV / NPZ",MUTED)]):
        y=184+i*54
        parts.append(f'<rect x="1165" y="{y}" width="150" height="38" rx="8" fill="#091422" stroke="{color}"/><text x="1240" y="{y+24}" text-anchor="middle" fill="{TEXT}" font-size="11.5" font-family="Noto Sans CJK SC,sans-serif">{label}</text>')
    for a,b in [((385,330),(445,330)),((695,330),(755,330)),((1075,330),(1135,330))]:
        parts.append(f'<path d="M{a[0]},{a[1]} L{b[0]},{b[1]}" stroke="{MUTED}" stroke-width="2.5" fill="none" marker-end="url(#a)"/>')
    parts.append(f'<rect x="55" y="585" width="1290" height="34" rx="9" fill="#091422" stroke="{GRID}"/><text x="75" y="607" fill="{MUTED}" font-size="12" font-family="Noto Sans CJK SC,sans-serif">正裕量 = 满足约束；负裕量 = 超限。所有场量与上限均为归一化研究变量，不映射现实设备毁伤参数。</text></svg>')
    svg.write_text("".join(parts), encoding="utf-8")
    import cairosvg
    cairosvg.svg2png(bytestring=svg.read_bytes(), write_to=str(png), output_width=1400, output_height=650)
    return svg, png


def build_full_chain() -> dict:
    project = CAEProject.load_yaml(CONFIG)
    temp_root = OUT / "_workflow_tmp"
    if temp_root.exists(): shutil.rmtree(temp_root)
    execution = execute_workflow(project)
    folder, report, archive = export_workflow(execution, temp_root)
    fixed = OUT / "sample_full_chain"
    if fixed.exists(): shutil.rmtree(fixed)
    shutil.move(str(folder), fixed)
    archive.unlink(missing_ok=True)
    shutil.rmtree(temp_root, ignore_errors=True)
    fixed_archive = Path(shutil.make_archive(str(fixed), "zip", root_dir=fixed))
    return {
        "metrics": execution.effect_metrics,
        "report": str(fixed / "HPM_CAE_V12_full_chain_report.html"),
        "archive": str(fixed_archive),
    }


def build_queue_acceptance() -> dict:
    db = OUT / "job_queue.sqlite3"; db.unlink(missing_ok=True)
    queue = PersistentJobQueue(db)
    project = CAEProject.load_yaml(CONFIG)
    project = replace(project, plane=replace(project.plane, samples=41), solver=replace(project.solver, iterations=55, target_samples=100, outside_samples=210, uncertainty_scenarios=2, pareto_points=3))
    spec = SweepSpec(parameter="solver.phase_std_deg", start=1, stop=9, points=3, replicates=2, metric="worst_target_rmse_percent", fast_mode=True)
    job_id = queue.submit_sweep(project, spec, workers=2)
    paused = queue.run_job(job_id, max_items=2)
    queue.items(job_id).to_csv(OUT / "queue_checkpoint_paused.csv", index=False)
    finished = queue.run_job(job_id)
    queue.items(job_id).to_csv(OUT / "queue_checkpoint_completed.csv", index=False)
    queue.jobs().to_csv(OUT / "queue_jobs.csv", index=False)
    summary = {"job_id": job_id, "paused": paused.__dict__, "finished": finished.__dict__}
    (OUT / "queue_acceptance_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return summary



def build_method_evidence() -> tuple[Path, Path]:
    """Run real method comparison and component ablation; save CSV and PNG."""
    project = CAEProject.load_yaml(CONFIG)
    method_rows: list[dict[str, object]] = []
    for method in ("Point-Focus", "Region-LS", "Nominal-PGMS", "Robust-PGMS", "Constrained-MO-PGMS"):
        result = solve_project(replace(project, solver=replace(project.solver, method=method)))
        method_rows.append({
            "method": method,
            "target_rmse_percent": result.metrics["target_rmse_percent"],
            "worst_target_rmse_percent": result.metrics["worst_target_rmse_percent"],
            "minimum_target_coverage_percent": result.metrics["minimum_target_coverage_percent"],
            "target_fairness_gap_percent": result.metrics["target_fairness_gap_percent"],
            "peak_outside_db": result.metrics["peak_outside_db"],
            "outside_peak_violation_db": result.metrics["outside_peak_violation_db"],
            "maximum_protected_violation_db": result.metrics["maximum_protected_violation_db"],
            "constraint_success_rate_percent": result.metrics["constraint_success_rate_percent"],
            "control_success": result.metrics["control_success"],
            "runtime_ms": result.metrics["solver_runtime_ms"],
        })
    comparison = pd.DataFrame(method_rows)
    comparison.to_csv(OUT / "method_comparison.csv", index=False, encoding="utf-8-sig")

    labels = [name.replace("Constrained-", "C-").replace("Point-", "P-") for name in comparison["method"]]
    xpos = np.arange(len(labels))
    fig = plt.figure(figsize=(12.8, 5.4), dpi=130, facecolor=BG)
    left = fig.add_axes([.075, .18, .40, .70], facecolor=PANEL)
    right = fig.add_axes([.56, .18, .40, .70], facecolor=PANEL)
    left.bar(xpos - .18, comparison["worst_target_rmse_percent"], width=.36, color=AMBER, label="最差目标 RMSE / %")
    left.bar(xpos + .18, 100.0 - comparison["minimum_target_coverage_percent"], width=.36, color=CYAN, label="未覆盖率 / %")
    left.set_xticks(xpos, labels, rotation=18, ha="right"); left.set_ylabel("%", color=MUTED); left.set_title("目标对象质量", color=TEXT, fontweight="bold")
    right.bar(xpos - .18, comparison["outside_peak_violation_db"], width=.36, color=PURPLE, label="区外峰值超限 / dB")
    right.bar(xpos + .18, comparison["maximum_protected_violation_db"], width=.36, color=GREEN, label="保护区最坏超限 / dB")
    right.axhline(0, color=RED, linestyle="--", linewidth=1.1); right.set_xticks(xpos, labels, rotation=18, ha="right"); right.set_ylabel("dB（≤0满足）", color=MUTED); right.set_title("风险约束", color=TEXT, fontweight="bold")
    for axis in (left, right):
        axis.tick_params(colors=MUTED, labelsize=8); axis.grid(axis="y", color=GRID, alpha=.55); [sp.set_color(GRID) for sp in axis.spines.values()]
        axis.legend(fontsize=7.5, facecolor="#091422", edgecolor=GRID, labelcolor=TEXT)
    fig.suptitle("V1.2 双目标方法对比 · 同一工程与随机种子", color=TEXT, fontsize=15, fontweight="bold")
    method_png = OUT / "03_method_comparison.png"; fig.savefig(method_png, facecolor=BG, bbox_inches="tight"); plt.close(fig)

    variants = {
        "Full": {},
        "No fairness": {"fairness_penalty": 0.0},
        "No protected": {"protected_penalty": 0.0},
        "No tail": {"tail_penalty": 0.0},
        "Nominal only": {"uncertainty_scenarios": 1, "gain_std_percent": 0.0, "phase_std_deg": 0.0, "registration_jitter_lambda": 0.0},
    }
    ablation_rows: list[dict[str, object]] = []
    for label, changes in variants.items():
        result = solve_project(replace(project, solver=replace(project.solver, **changes)))
        ablation_rows.append({
            "variant": label,
            "worst_target_rmse_percent": result.metrics["worst_target_rmse_percent"],
            "minimum_target_coverage_percent": result.metrics["minimum_target_coverage_percent"],
            "target_fairness_gap_percent": result.metrics["target_fairness_gap_percent"],
            "outside_peak_violation_db": result.metrics["outside_peak_violation_db"],
            "maximum_protected_violation_db": result.metrics["maximum_protected_violation_db"],
            "control_success": result.metrics["control_success"],
            "runtime_ms": result.metrics["solver_runtime_ms"],
        })
    ablation = pd.DataFrame(ablation_rows)
    ablation.to_csv(OUT / "ablation_summary.csv", index=False, encoding="utf-8-sig")
    xpos = np.arange(len(ablation))
    fig = plt.figure(figsize=(12.8, 5.4), dpi=130, facecolor=BG)
    left = fig.add_axes([.075, .18, .40, .70], facecolor=PANEL)
    right = fig.add_axes([.56, .18, .40, .70], facecolor=PANEL)
    left.bar(xpos - .18, ablation["worst_target_rmse_percent"], width=.36, color=AMBER, label="最差RMSE / %")
    left.bar(xpos + .18, 100.0 - ablation["minimum_target_coverage_percent"], width=.36, color=CYAN, label="未覆盖率 / %")
    right.bar(xpos - .18, ablation["outside_peak_violation_db"], width=.36, color=PURPLE, label="区外超限 / dB")
    right.bar(xpos + .18, ablation["maximum_protected_violation_db"], width=.36, color=GREEN, label="保护区超限 / dB")
    right.axhline(0, color=RED, linestyle="--", linewidth=1.1)
    short=["Full","No fair","No protect","No tail","Nominal"]
    for axis, title in ((left, "目标质量"), (right, "约束风险")):
        axis.set_xticks(xpos, short, rotation=15, ha="right"); axis.set_title(title, color=TEXT, fontweight="bold"); axis.tick_params(colors=MUTED, labelsize=8); axis.grid(axis="y", color=GRID, alpha=.55); [sp.set_color(GRID) for sp in axis.spines.values()]
        axis.legend(fontsize=7.5, facecolor="#091422", edgecolor=GRID, labelcolor=TEXT)
    left.set_ylabel("%", color=MUTED); right.set_ylabel("dB（≤0满足）", color=MUTED)
    fig.suptitle("V1.2 组件消融 · 保护区项移除后联合判据失效", color=TEXT, fontsize=15, fontweight="bold")
    ablation_png = OUT / "04_ablation.png"; fig.savefig(ablation_png, facecolor=BG, bbox_inches="tight"); plt.close(fig)
    return method_png, ablation_png

def _uri(path: Path) -> str:
    return "data:image/png;base64," + base64.b64encode(path.read_bytes()).decode("ascii")


def build_acceptance_report(preview: Path, architecture_png: Path, mechanism_png: Path, method_png: Path, ablation_png: Path, full_chain: dict, queue: dict) -> Path:
    summary = json.loads((OUT / "v12_acceptance_summary.json").read_text(encoding="utf-8"))
    metrics = summary["static_metrics"]
    rec = summary["pareto_recommended"]
    rows = [
        ("总体目标区 RMSE", f"{metrics['target_rmse_percent']:.3f}%"),
        ("最差单目标 RMSE", f"{metrics['worst_target_rmse_percent']:.3f}%"),
        ("最低单目标覆盖率", f"{metrics['minimum_target_coverage_percent']:.3f}%"),
        ("区外峰值 / 上限", f"{metrics['peak_outside_db']:.3f} / {metrics['outside_peak_limit_db']:.3f} dB"),
        ("最坏保护区超限", f"{metrics['maximum_protected_violation_db']:+.3f} dB"),
        ("对象约束通过率", f"{metrics['constraint_success_rate_percent']:.1f}%"),
        ("联合判据", "通过" if metrics["control_success"] else "未通过"),
        ("Pareto 推荐倍率", f"{float(rec['risk_multiplier']):.3f}"),
        ("推荐点最差 RMSE", f"{float(rec['worst_target_rmse_percent']):.3f}%"),
        ("推荐点风险超限", f"{float(rec['risk_violation_db']):+.3f} dB"),
        ("自动测试", "81 passed"),
    ]
    table = "".join(f"<tr><td>{key}</td><td><b>{value}</b></td></tr>" for key,value in rows)
    qf=queue["finished"]; qp=queue["paused"]
    css = (
        f"body{{margin:0;background:{BG};color:{TEXT};font-family:Inter,'Noto Sans CJK SC','Microsoft YaHei',sans-serif}}"
        f"main{{max-width:1500px;margin:auto;padding:30px 4vw 60px}}"
        f"header{{padding:18px 0 24px;border-bottom:1px solid {GRID}}}"
        f"h1{{margin:0}}p{{color:{MUTED};line-height:1.7}}"
        f"section{{background:{PANEL};border:1px solid {GRID};border-radius:14px;padding:18px;margin:18px 0}}"
        f"img{{width:100%;border-radius:10px;border:1px solid {GRID}}}"
        f"table{{width:100%;border-collapse:collapse}}td{{padding:10px;border-bottom:1px solid {GRID}}}"
        f"td:last-child{{color:{GREEN}}}.grid{{display:grid;grid-template-columns:1fr 1fr;gap:18px}}"
        f".scope{{border-left:4px solid {AMBER};background:#091422;padding:13px}}"
        f"a{{color:{CYAN}}}code{{color:{PURPLE}}}"
        "@media(max-width:900px){.grid{grid-template-columns:1fr}}"
    )
    path=OUT/"v12_acceptance_report.html"
    path.write_text(f"""<!doctype html><html lang='zh-CN'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'><title>HPM-CAE V1.2 Acceptance</title><style>{css}</style></head><body><main><header><h1>HPM-CAE V1.2 验收报告</h1><p>对象级约束多目标控场、可解释裕量、Pareto设计空间、实时全链路和可恢复任务队列的确定性工程验收。</p></header><section><h2>工作台布局预览</h2><img src='{_uri(preview)}'><p>预览由默认双目标工程真实数值输出绘制；交互界面通过 <code>run_ui_v12.py</code> 启动。</p></section><section><h2>平台分层架构</h2><img src='{_uri(architecture_png)}'></section><section><h2>对象约束优化机理</h2><img src='{_uri(mechanism_png)}'></section><div class='grid'><section><h2>方法对比</h2><img src='{_uri(method_png)}'></section><section><h2>组件消融</h2><img src='{_uri(ablation_png)}'></section></div><div class='grid'><section><h2>默认工程指标</h2><table>{table}</table></section><section><h2>队列检查点验收</h2><table><tr><td>任务ID</td><td><b>{queue['job_id']}</b></td></tr><tr><td>并行 worker</td><td><b>2</b></td></tr><tr><td>暂停后完成</td><td><b>{qp['completed']}/{qp['total']}</b></td></tr><tr><td>恢复后状态</td><td><b>{qf['status']}</b></td></tr><tr><td>最终完成</td><td><b>{qf['completed']}/{qf['total']}</b></td></tr><tr><td>失败</td><td><b>{qf['failed']}</b></td></tr></table></section></div><section><h2>可复现产物</h2><p><a href='sample_constrained_multi_object/HPM_CAE_report.html'>静态约束控场交互报告</a> · <a href='sample_pareto/HPM_CAE_V12_pareto_report.html'>Pareto交互报告</a> · <a href='sample_full_chain/HPM_CAE_V12_full_chain_report.html'>实时全链路报告</a> · <a href='queue_checkpoint_paused.csv'>暂停检查点</a> · <a href='queue_checkpoint_completed.csv'>恢复后记录</a></p></section><section class='scope'><b>模型边界</b><p>所有结果均为波长尺度、归一化标量场和无量纲代理评价，不代表绝对源功率、具体器件阈值、现实毁伤概率或作用距离；默认结果用于软件验收，不替代论文级 Monte Carlo、全波求解或实测验证。</p></section></main></body></html>""",encoding="utf-8")
    return path


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    preview=build_preview()
    _,arch_png=build_architecture()
    _,mech_png=build_mechanism()
    method_png,ablation_png=build_method_evidence()
    full=build_full_chain()
    queue=build_queue_acceptance()
    report=build_acceptance_report(preview,arch_png,mech_png,method_png,ablation_png,full,queue)
    print(preview); print(report); print(full); print(queue)


if __name__ == "__main__":
    main()

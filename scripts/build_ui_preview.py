#!/usr/bin/env python3
"""Build a static PNG preview of the V0.9 CAE workbench."""
from __future__ import annotations

import sys
from pathlib import Path

import matplotlib.pyplot as plt
from matplotlib import font_manager
from matplotlib.patches import FancyBboxPatch, Rectangle, Circle, Ellipse
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from hpm_platform.ui.project_model import default_project
from hpm_platform.ui.quick_solver import solve_project

BG = "#07101d"
PANEL = "#0d1828"
PANEL2 = "#091422"
LINE = "#26354d"
TEXT = "#e7eef9"
MUTED = "#91a2bb"
CYAN = "#35d8ff"
GREEN = "#4ee0a5"
AMBER = "#ffc857"
BLUE = "#2b65db"

_font_path = Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc")
if _font_path.exists():
    font_manager.fontManager.addfont(str(_font_path))
    _font_name = font_manager.FontProperties(fname=str(_font_path)).get_name()
    plt.rcParams["font.family"] = [_font_name, "DejaVu Sans"]
else:
    plt.rcParams["font.family"] = ["DejaVu Sans"]
plt.rcParams["axes.unicode_minus"] = False


def rounded(ax, xy, width, height, radius=0.012, face=PANEL, edge=LINE, lw=1.0):
    patch = FancyBboxPatch(
        xy,
        width,
        height,
        boxstyle=f"round,pad=0.004,rounding_size={radius}",
        transform=ax.transAxes,
        facecolor=face,
        edgecolor=edge,
        linewidth=lw,
    )
    ax.add_patch(patch)
    return patch


def label(ax, x, y, text, size=10, color=TEXT, weight="normal", ha="left", va="center"):
    ax.text(x, y, text, transform=ax.transAxes, fontsize=size, color=color, fontweight=weight, ha=ha, va=va)


def main() -> None:
    project = default_project()
    result = solve_project(project)
    fig = plt.figure(figsize=(16, 10), dpi=120, facecolor=BG)
    canvas = fig.add_axes([0, 0, 1, 1])
    canvas.set_axis_off()

    # Header
    canvas.add_patch(Rectangle((0, 0.936), 1, 0.064, transform=canvas.transAxes, facecolor="#0b1b2e", edgecolor="none"))
    rounded(canvas, (0.014, 0.949), 0.027, 0.038, radius=0.008, face=CYAN, edge=CYAN)
    label(canvas, 0.0275, 0.968, "H", size=13, color="#03111b", weight="bold", ha="center")
    label(canvas, 0.048, 0.973, "HPM-CAE Workbench", size=16, weight="bold")
    label(canvas, 0.194, 0.973, "V0.9", size=16, color=CYAN, weight="bold")
    label(canvas, 0.048, 0.952, "Phased-array digital-twin · local visual research environment", size=8, color=MUTED)
    badges = ["LOCAL PYTHON", "NORMALIZED MODE", "64 ELEMENTS READY"]
    xpos = 0.785
    for badge in badges:
        width = 0.062 if badge != "64 ELEMENTS READY" else 0.09
        rounded(canvas, (xpos, 0.958), width, 0.022, radius=0.01, face="#071827", edge="#176381")
        label(canvas, xpos + width / 2, 0.969, badge, size=6.5, color=CYAN, ha="center")
        xpos += width + 0.008

    # Pipeline
    stage_y, stage_h = 0.866, 0.052
    stages = [
        ("① 感知", "PAWR / FBSS / ESPRIT"),
        ("② 接收防护", "预测宽零陷 / 多干扰"),
        ("③ 动态控场", "PCF-RLS / 鲁棒赋形"),
        ("④ 效应评价", "双参考系 / 概率代理"),
        ("⑤ CAE工作台", "建模 / 求解 / 可视化 / 导出"),
    ]
    left = 0.015
    gap = 0.018
    sw = (0.97 - 4 * gap) / 5
    for i, (title, subtitle) in enumerate(stages):
        x = left + i * (sw + gap)
        rounded(canvas, (x, stage_y), sw, stage_h, radius=0.008, face=PANEL, edge=LINE)
        canvas.add_patch(Rectangle((x, stage_y + stage_h - 0.003), sw, 0.003, transform=canvas.transAxes, facecolor=CYAN if i == 4 else GREEN, edgecolor="none"))
        label(canvas, x + 0.009, stage_y + 0.033, title, size=9.5, weight="bold")
        label(canvas, x + 0.009, stage_y + 0.015, subtitle, size=6.3, color=MUTED)
        if i < 4:
            label(canvas, x + sw + gap / 2, stage_y + 0.026, "›", size=16, color=MUTED, ha="center")

    # Main panels
    left_x, left_w = 0.012, 0.145
    center_x, center_w = 0.164, 0.626
    right_x, right_w = 0.797, 0.191
    bottom, height = 0.018, 0.829
    rounded(canvas, (left_x, bottom), left_w, height, face=PANEL)
    rounded(canvas, (center_x, bottom), center_w, height, face=PANEL)
    rounded(canvas, (right_x, bottom), right_w, height, face=PANEL)

    # Left project tree
    label(canvas, left_x + 0.009, 0.829, "PROJECT NAVIGATOR", size=7.5, color=MUTED)
    rounded(canvas, (left_x + 0.007, 0.795), left_w - 0.014, 0.026, radius=0.004, face="#10304a", edge="#10304a")
    label(canvas, left_x + 0.014, 0.808, "▾  📁  HPM-CAE Demo", size=8.3, color=CYAN)
    nodes = ["阵列几何 · 8×8", "观察面 · z=8λ", "目标区域 · 旋转椭圆", "保护区域 · 启用", "求解器 · Robust-PGMS"]
    y = 0.778
    for node in nodes:
        canvas.add_patch(Circle((left_x + 0.02, y), 0.002, transform=canvas.transAxes, facecolor=GREEN, edgecolor="none"))
        label(canvas, left_x + 0.028, y, node, size=7.2)
        y -= 0.027
    canvas.plot([left_x + 0.008, left_x + left_w - 0.008], [0.635, 0.635], transform=canvas.transAxes, color=LINE, lw=0.8)

    groups = [
        ("阵列几何", [("频率", "10.0 GHz"), ("阵列规模", "8 × 8"), ("阵元间距", "0.5 λ")]),
        ("目标区域", [("中心", "(0.8, -0.6) λ"), ("半轴", "1.1 × 0.65 λ"), ("旋转", "25°")]),
        ("求解器", [("算法", "Robust-PGMS"), ("场景数", "5"), ("PA / DPD", "ON / ON")]),
    ]
    gy = 0.615
    for title, rows in groups:
        gh = 0.108
        rounded(canvas, (left_x + 0.007, gy - gh), left_w - 0.014, gh, radius=0.006, face=PANEL2, edge=LINE)
        label(canvas, left_x + 0.014, gy - 0.016, title, size=7.5, weight="bold")
        ry = gy - 0.044
        for k, v in rows:
            label(canvas, left_x + 0.014, ry, k, size=6.4, color=MUTED)
            label(canvas, left_x + left_w - 0.014, ry, v, size=6.5, weight="bold", ha="right")
            ry -= 0.025
        gy -= gh + 0.014

    # Center tabs
    canvas.add_patch(Rectangle((center_x + 0.004, 0.805), center_w - 0.008, 0.035, transform=canvas.transAxes, facecolor=PANEL2, edgecolor="none"))
    tabs = ["三维场景", "场分布", "目标截线", "远场方向图", "阵元激励", "收敛"]
    tx = center_x + 0.012
    for i, tab in enumerate(tabs):
        if i == 1:
            rounded(canvas, (tx - 0.003, 0.81), 0.053, 0.024, radius=0.004, face="#123653", edge="#123653")
        label(canvas, tx + 0.023, 0.822, tab, size=6.5, color=CYAN if i == 1 else MUTED, ha="center")
        tx += 0.064

    # Actual field heat map
    heat_ax = fig.add_axes([center_x + 0.035, 0.325, center_w - 0.075, 0.455], facecolor=PANEL2)
    field_db = np.clip(result.field_db, -30, 3)
    im = heat_ax.imshow(
        field_db,
        extent=[result.x_lambda[0], result.x_lambda[-1], result.y_lambda[0], result.y_lambda[-1]],
        origin="lower",
        cmap="turbo",
        vmin=-30,
        vmax=3,
        interpolation="bilinear",
        aspect="equal",
    )
    heat_ax.add_patch(Ellipse((project.target.center_x_lambda, project.target.center_y_lambda), 2 * project.target.semi_major_lambda, 2 * project.target.semi_minor_lambda, angle=project.target.rotation_deg, fill=False, lw=2.0, edgecolor=AMBER))
    heat_ax.add_patch(Ellipse((project.target.center_x_lambda, project.target.center_y_lambda), 2 * project.target.semi_major_lambda * project.target.guard_scale, 2 * project.target.semi_minor_lambda * project.target.guard_scale, angle=project.target.rotation_deg, fill=False, lw=1.0, ls="--", edgecolor=AMBER, alpha=0.75))
    heat_ax.add_patch(Circle((project.protected_zone.center_x_lambda, project.protected_zone.center_y_lambda), project.protected_zone.radius_lambda, fill=False, lw=2.0, edgecolor=GREEN))
    heat_ax.set_title("观察面归一化场分布 · Robust-PGMS", fontsize=10, color=TEXT, pad=10)
    heat_ax.set_xlabel("x / λ", color=TEXT, fontsize=8)
    heat_ax.set_ylabel("y / λ", color=TEXT, fontsize=8)
    heat_ax.tick_params(colors=MUTED, labelsize=7)
    for spine in heat_ax.spines.values():
        spine.set_color(LINE)
    heat_ax.grid(color="#ffffff", alpha=0.08, lw=0.5)
    cax = fig.add_axes([center_x + center_w - 0.035, 0.37, 0.009, 0.36])
    cb = fig.colorbar(im, cax=cax)
    cb.set_label("幅度 / dB", color=TEXT, fontsize=7)
    cb.ax.tick_params(colors=MUTED, labelsize=6)
    cb.outline.set_edgecolor(LINE)

    # Cut monitor
    cut_ax = fig.add_axes([center_x + 0.035, 0.065, center_w - 0.075, 0.205], facecolor=PANEL2)
    yi = int(np.argmin(np.abs(result.y_lambda - project.target.center_y_lambda)))
    amp = np.abs(result.field[yi])
    cut_ax.plot(result.x_lambda, amp, color=CYAN, lw=2)
    cut_ax.axhspan(0.9 * project.solver.target_amplitude, 1.1 * project.solver.target_amplitude, color=AMBER, alpha=0.15)
    cut_ax.axhline(project.solver.target_amplitude, color=AMBER, lw=1.2, ls="--")
    cut_ax.set_title("目标中心横向截线与 ±10% 控制带", fontsize=8.5, color=TEXT, pad=7)
    cut_ax.set_xlabel("x / λ", color=TEXT, fontsize=7)
    cut_ax.set_ylabel("归一化幅度", color=TEXT, fontsize=7)
    cut_ax.tick_params(colors=MUTED, labelsize=6)
    cut_ax.grid(color="#ffffff", alpha=0.08, lw=0.5)
    for spine in cut_ax.spines.values():
        spine.set_color(LINE)

    # Right controls and metrics
    label(canvas, right_x + 0.009, 0.829, "SOLVER CONTROL", size=7.5, color=MUTED)
    rounded(canvas, (right_x + 0.008, 0.778), right_w - 0.016, 0.038, radius=0.006, face=BLUE, edge=BLUE)
    label(canvas, right_x + right_w / 2, 0.797, "▶  运行求解", size=9.2, weight="bold", ha="center")
    rounded(canvas, (right_x + 0.008, 0.714), right_w - 0.016, 0.052, radius=0.006, face=PANEL2, edge=LINE)
    canvas.add_patch(Rectangle((right_x + 0.008, 0.714), 0.003, 0.052, transform=canvas.transAxes, facecolor=GREEN, edgecolor="none"))
    label(canvas, right_x + 0.017, 0.749, "示例工程已求解", size=7.3, weight="bold")
    label(canvas, right_x + 0.017, 0.728, "Robust-PGMS完成；联合归一化判据通过。", size=6.1, color=MUTED)

    metrics = [
        ("目标区 RMSE", f"{result.metrics['target_rmse_percent']:.2f}%", "越低越好"),
        ("±10%覆盖率", f"{result.metrics['target_coverage_percent']:.1f}%", "越高越好"),
        ("区外峰值", f"{result.metrics['peak_outside_db']:.2f} dB", "相对目标参考"),
        ("保护区 P95", f"{result.metrics['protected_p95_db']:.2f} dB", "相对目标参考"),
        ("求解耗时", f"{result.metrics['solver_runtime_ms']:.0f} ms", "当前机器"),
        ("联合判据", "通过", "归一化算法判据"),
    ]
    mx0 = right_x + 0.008
    my0 = 0.635
    mw = (right_w - 0.023) / 2
    mh = 0.073
    for i, (name, value, note) in enumerate(metrics):
        col, row = i % 2, i // 2
        x = mx0 + col * (mw + 0.007)
        y = my0 - row * (mh + 0.009)
        rounded(canvas, (x, y), mw, mh, radius=0.006, face=PANEL2, edge=LINE)
        label(canvas, x + 0.008, y + 0.055, name, size=5.9, color=MUTED)
        label(canvas, x + 0.008, y + 0.033, value, size=10.5, color=GREEN if i == 5 else TEXT, weight="bold")
        label(canvas, x + 0.008, y + 0.012, note, size=5.2, color=MUTED)

    label(canvas, right_x + 0.009, 0.365, "ARTIFACTS", size=7.5, color=MUTED)
    for j, text in enumerate(["下载项目 YAML", "下载交互报告 HTML", "下载完整结果 ZIP"]):
        y = 0.322 - j * 0.048
        rounded(canvas, (right_x + 0.008, y), right_w - 0.016, 0.036, radius=0.005, face=PANEL2, edge=BLUE if j == 2 else LINE)
        label(canvas, right_x + right_w / 2, y + 0.018, text, size=6.7, ha="center")
    rounded(canvas, (right_x + 0.008, 0.064), right_w - 0.016, 0.105, radius=0.006, face=PANEL2, edge=LINE)
    label(canvas, right_x + 0.017, 0.151, "模型边界", size=6.7, weight="bold")
    scope = "只处理波长尺度几何、归一化复场和统计代理量；\n不输出真实源功率、器件毁伤阈值或现实作用距离。"
    label(canvas, right_x + 0.017, 0.116, scope, size=5.8, color=MUTED, va="top")

    out = ROOT / "outputs_v09_ui" / "00_workbench_preview.png"
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, facecolor=BG, bbox_inches="tight", pad_inches=0)
    plt.close(fig)
    print(out)


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Generate PNG and SVG layer-architecture diagrams for HPM-CAE V0.9."""
from pathlib import Path

import matplotlib.pyplot as plt
from matplotlib import font_manager
from matplotlib.patches import FancyBboxPatch, Rectangle, FancyArrowPatch

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "outputs_v09_ui"
OUT.mkdir(parents=True, exist_ok=True)

font_path = Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc")
if font_path.exists():
    font_manager.fontManager.addfont(str(font_path))
    family = font_manager.FontProperties(fname=str(font_path)).get_name()
else:
    family = "DejaVu Sans"
plt.rcParams["font.family"] = [family, "DejaVu Sans"]
plt.rcParams["svg.fonttype"] = "path"

BG = "#07101d"
PANEL = "#0d1828"
LINE = "#26354d"
TEXT = "#e7eef9"
MUTED = "#91a2bb"
CYAN = "#35d8ff"
GREEN = "#4ee0a5"
AMBER = "#ffc857"
PURPLE = "#ab8cff"

fig = plt.figure(figsize=(16, 9), dpi=120, facecolor=BG)
ax = fig.add_axes([0, 0, 1, 1])
ax.set_xlim(0, 1)
ax.set_ylim(0, 1)
ax.axis("off")


def box(x, y, w, h, color, title, items, item_widths=None):
    ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0.004,rounding_size=0.018", facecolor=PANEL, edgecolor=LINE, linewidth=1.5))
    ax.add_patch(FancyBboxPatch((x, y), 0.009, h, boxstyle="round,pad=0,rounding_size=0.006", facecolor=color, edgecolor=color))
    ax.text(x + 0.025, y + h - 0.035, title, color=TEXT, fontsize=16, fontweight="bold", va="center")
    if item_widths is None:
        item_widths = [1 / len(items)] * len(items)
    total_gap = 0.016 * (len(items) - 1)
    available = w - 0.05 - total_gap
    cursor = x + 0.025
    for (item_title, item_sub), frac in zip(items, item_widths):
        iw = available * frac
        iy, ih = y + 0.028, h - 0.09
        ax.add_patch(FancyBboxPatch((cursor, iy), iw, ih, boxstyle="round,pad=0.003,rounding_size=0.012", facecolor="#10253c", edgecolor=color, linewidth=1.0))
        ax.text(cursor + iw / 2, iy + ih * 0.62, item_title, color=TEXT, fontsize=11.5, ha="center", va="center", fontweight="bold")
        if item_sub:
            ax.text(cursor + iw / 2, iy + ih * 0.30, item_sub, color=MUTED, fontsize=8.5, ha="center", va="center")
        cursor += iw + 0.016


ax.text(0.045, 0.94, "HPM-CAE V0.9 可视化平台分层架构", color=TEXT, fontsize=25, fontweight="bold")
ax.text(0.045, 0.905, "配置驱动 · 本地 Python · 归一化研究模式 · 可复现结果工件", color=MUTED, fontsize=12)
ax.add_patch(FancyBboxPatch((0.78, 0.917), 0.17, 0.045, boxstyle="round,pad=0.002,rounding_size=0.022", facecolor="#0b2638", edgecolor=CYAN, linewidth=1.0))
ax.text(0.865, 0.9395, "NORMALIZED RESEARCH MODE", color=CYAN, fontsize=10, ha="center", va="center")

box(
    0.045, 0.665, 0.91, 0.17, CYAN,
    "① 表现层 / CAE Workbench",
    [
        ("项目树与参数检查器", "Project / Inspector"),
        ("三维场景与二维场视图", "Plotly viewport"),
        ("求解监视与指标面板", "Solver / Metrics"),
        ("历史结果与方案对比", "Result library"),
        ("YAML / HTML / ZIP", "一键导出"),
    ],
)
box(
    0.045, 0.445, 0.91, 0.17, GREEN,
    "② 项目与任务层 / Project & Orchestration",
    [
        ("dataclass 项目模型", "参数与几何校验"),
        ("场景预设 / 保存载入", "YAML lifecycle"),
        ("同步交互求解", "日志与状态回传"),
        ("结果清单 / SHA-256", "可复现归档"),
    ],
)
box(
    0.045, 0.225, 0.91, 0.17, AMBER,
    "③ 算法求解层 / Solver Bridge",
    [
        ("Point-Focus", "相位共轭基线"),
        ("Region-LS", "闭式区域拟合"),
        ("Nominal-PGMS", "名义幅度优化"),
        ("Robust-PGMS", "多场景鲁棒设计"),
        ("PA + DPD", "幅相 / 配准非理想"),
    ],
)
box(
    0.045, 0.045, 0.91, 0.13, PURPLE,
    "④ 物理与数据底座",
    [
        ("阵列几何", "URA"),
        ("标量 Green 矩阵", "近场叠加"),
        ("目标 / 保护区掩膜", "区域约束"),
        ("归一化场指标", "RMSE / P95"),
        ("V0.3—V0.8 算法库", "感知—防护—控场—评估"),
    ],
)

for y0, y1 in [(0.665, 0.615), (0.445, 0.395), (0.225, 0.175)]:
    ax.add_patch(FancyArrowPatch((0.5, y0), (0.5, y1), arrowstyle="-|>", mutation_scale=18, linewidth=1.8, color=MUTED))

png = OUT / "01_cae_layer_architecture.png"
svg = OUT / "01_cae_layer_architecture.svg"
fig.savefig(png, facecolor=BG, bbox_inches="tight", pad_inches=0)
fig.savefig(svg, facecolor=BG, bbox_inches="tight", pad_inches=0)
plt.close(fig)
print(svg)

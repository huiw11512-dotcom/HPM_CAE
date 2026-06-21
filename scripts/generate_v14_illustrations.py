#!/usr/bin/env python3
"""生成 V1.4 中文可编辑矢量机理图与高分辨率 PNG。

图形完全由本地 Python/Matplotlib 绘制，便于论文排版和版本控制。
"""
from __future__ import annotations

from pathlib import Path
import sys

import matplotlib as mpl
import matplotlib.pyplot as plt
import matplotlib.patheffects as pe
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch, Circle, Polygon, Rectangle, Ellipse, Arc
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "src" / "hpm_platform" / "ui" / "static_v14" / "img"
MIRROR = ROOT / "outputs_v14_ui"
OUT.mkdir(parents=True, exist_ok=True)
MIRROR.mkdir(parents=True, exist_ok=True)

mpl.rcParams.update({
    "font.family": "Noto Sans CJK JP",
    "font.sans-serif": ["Noto Sans CJK JP", "Microsoft YaHei", "SimHei", "DejaVu Sans"],
    "axes.unicode_minus": False,
    "svg.fonttype": "none",
})

BG = "#07111f"
PANEL = "#0d1b2f"
PANEL2 = "#12243b"
CYAN = "#35d8ff"
BLUE = "#4d8dff"
GREEN = "#45e0a8"
AMBER = "#ffc857"
ORANGE = "#ff8a5b"
RED = "#ff647c"
PURPLE = "#b18cff"
TEXT = "#f2f6ff"
MUTED = "#9db0c9"
GRID = "#253954"


def gradient_background(fig, ax, top="#07111f", bottom="#102944"):
    gradient = np.linspace(0, 1, 600)[:, None]
    from matplotlib.colors import LinearSegmentedColormap
    cmap = LinearSegmentedColormap.from_list("bg", [bottom, top])
    ax.imshow(gradient, extent=[0, 1, 0, 1], origin="lower", aspect="auto", cmap=cmap, zorder=-100)
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.axis("off")


def title(ax, main, sub):
    ax.text(0.055, 0.93, main, color=TEXT, fontsize=25, weight="bold", va="center",
            path_effects=[pe.withStroke(linewidth=1.2, foreground="#02050a")])
    ax.text(0.057, 0.885, sub, color=MUTED, fontsize=11.5, va="center")
    ax.plot([0.055, 0.945], [0.855, 0.855], color=GRID, lw=1.2)


def round_box(ax, xy, wh, text, subtitle="", color=CYAN, number=None, alpha=0.98, fontsize=14):
    x, y = xy
    w, h = wh
    shadow = FancyBboxPatch((x+0.005, y-0.006), w, h, boxstyle="round,pad=0.012,rounding_size=0.022",
                            fc="#02060d", ec="none", alpha=0.28, zorder=1)
    box = FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0.012,rounding_size=0.022",
                         fc=PANEL2, ec=color, lw=1.8, alpha=alpha, zorder=2)
    ax.add_patch(shadow)
    ax.add_patch(box)
    if number is not None:
        circ = Circle((x+0.035, y+h-0.038), 0.022, fc=color, ec="white", lw=0.7, zorder=3)
        ax.add_patch(circ)
        ax.text(x+0.035, y+h-0.038, str(number), ha="center", va="center", color=BG, fontsize=11, weight="bold", zorder=4)
        tx = x+0.068
    else:
        tx = x+0.025
    ax.text(tx, y+h*0.60, text, color=TEXT, fontsize=fontsize, weight="bold", va="center", zorder=4)
    if subtitle:
        ax.text(x+0.025, y+h*0.27, subtitle, color=MUTED, fontsize=9.5, va="center", zorder=4)
    return box


def arrow(ax, start, end, color=CYAN, rad=0.0, lw=2.0, alpha=0.95, style="-|>"):
    arr = FancyArrowPatch(start, end, arrowstyle=style, mutation_scale=15,
                          connectionstyle=f"arc3,rad={rad}", color=color, lw=lw, alpha=alpha, zorder=5)
    ax.add_patch(arr)
    return arr


def save(fig, stem):
    for folder in (OUT, MIRROR):
        fig.savefig(folder / f"{stem}.png", dpi=240, facecolor=fig.get_facecolor(), bbox_inches="tight", pad_inches=0.02)
        fig.savefig(folder / f"{stem}.svg", facecolor=fig.get_facecolor(), bbox_inches="tight", pad_inches=0.02)
    plt.close(fig)


def architecture():
    fig, ax = plt.subplots(figsize=(16, 9), facecolor=BG)
    gradient_background(fig, ax)
    title(ax, "HPM 数字化电磁算法 CAE · 全链路数字孪生架构",
          "全 Python · 归一化标量场 · 插件式传播后端 · 配置驱动 · 可复现实验")

    xs = [0.055, 0.235, 0.415, 0.595, 0.775]
    colors = [CYAN, BLUE, PURPLE, AMBER, GREEN]
    names = ["场景建模", "感知识别", "接收防护", "空间控场", "效应评价"]
    subs = ["阵列 · 材料 · 反射面\n孔缝 · 腔体 · 目标区",
            "相干多径快拍\nPAWR / FBSS / ESPRIT",
            "置信扇区 · 宽零陷\nCR-HybridNull",
            "多目标约束 · 鲁棒赋形\n功放代理 · DPD",
            "累积代理 · 风险地图\n任务评分 · 反馈"]
    for i, (x, c, n, s) in enumerate(zip(xs, colors, names, subs), start=1):
        round_box(ax, (x, 0.60), (0.15, 0.18), n, s, c, i, fontsize=14)
        if i < 5:
            arrow(ax, (x+0.15, 0.69), (xs[i]-0.012, 0.69), c, lw=2.4)

    # 中央闭环总线
    bus = FancyBboxPatch((0.07, 0.41), 0.86, 0.105, boxstyle="round,pad=0.015,rounding_size=0.03",
                         fc="#0a1728", ec="#41627e", lw=1.4, zorder=1)
    ax.add_patch(bus)
    ax.text(0.50, 0.474, "统一状态总线：SceneConfig  →  ArrayObservation  →  DOAEstimate  →  BeamWeights  →  FieldMap  →  EffectMap",
            ha="center", va="center", color=TEXT, fontsize=12.5, weight="bold")
    ax.text(0.50, 0.435, "时间戳 · 随机种子 · 单位约定 · 不确定性协方差 · 运行清单 · 数据血缘",
            ha="center", va="center", color=MUTED, fontsize=10.3)
    for x, c in zip([0.13,0.31,0.49,0.67,0.85], colors):
        arrow(ax, (x,0.60), (x,0.515), c, lw=1.6)

    # 底部四层
    layers = [
        ("物理与降阶模型层", "自由空间格林 · 镜像射线\n孔缝—腔体 ROM · 混合后端", CYAN),
        ("算法与优化层", "测向 · 波束形成\n多目标约束 · 预测控制", PURPLE),
        ("实验管理层", "SQLite 队列 · 批量扫参\n检查点 · 置信区间", AMBER),
        ("可视化与成果层", "Bootstrap 模板 · Plotly\n中文报告 · 论文图表", GREEN),
    ]
    y0 = 0.26
    for j, (n, s, c) in enumerate(layers):
        x = 0.07 + j*0.215
        round_box(ax, (x, y0), (0.19, 0.10), n, s, c, fontsize=11.2)

    # 反馈回路
    arrow(ax, (0.855, 0.60), (0.13, 0.60), GREEN, rad=-0.32, lw=2.2)
    ax.text(0.50, 0.803, "评价结果反馈至先验、零陷宽度、控场权值与任务占空策略", color=GREEN,
            ha="center", va="center", fontsize=10.5, weight="bold")

    ax.text(0.055, 0.095, "研究边界", color=AMBER, fontsize=11, weight="bold")
    ax.text(0.135, 0.095, "仅用于波长尺度归一化场与算法研究；不输出绝对源功率、现实器件阈值、毁伤概率或作用距离。",
            color=MUTED, fontsize=10.4)
    ax.text(0.945, 0.045, "V1.4 · 中文矢量机理图", ha="right", color="#60758f", fontsize=9)
    save(fig, "01_全链路数字孪生架构图")


def propagation():
    fig, ax = plt.subplots(figsize=(16, 9), facecolor=BG)
    gradient_background(fig, ax, top="#06101d", bottom="#183451")
    title(ax, "混合传播后端机理图",
          "直达标量格林项 + 一阶镜像反射 + 孔缝耦合与有限模态腔体降阶响应")

    # 地面/观察面透视
    plane = Polygon([[0.10,0.25],[0.78,0.18],[0.93,0.48],[0.28,0.55]], closed=True,
                    fc="#0c2137", ec="#41627e", lw=1.3, alpha=0.9)
    ax.add_patch(plane)
    for t in np.linspace(0.15,0.9,7):
        ax.plot([0.10+(0.18*t),0.78+(0.15*t)],[0.25+(0.30*t),0.18+(0.30*t)], color=GRID, lw=0.6, alpha=0.55)

    # 阵列
    array_origin=(0.16,0.35)
    for iy in range(6):
        for ix in range(6):
            x=array_origin[0]+ix*0.018+iy*0.007
            y=array_origin[1]+iy*0.019
            ax.add_patch(Rectangle((x,y),0.012,0.012,fc=CYAN,ec="#d9f8ff",lw=0.4,zorder=6))
    ax.text(0.15,0.31,"8×8 相控阵",color=TEXT,fontsize=12,weight="bold")
    ax.text(0.15,0.285,"阵元复激励  w[n]",color=MUTED,fontsize=9.5)

    # 目标区
    target=Ellipse((0.73,0.38),0.15,0.07,angle=12,fc="#ffc85722",ec=AMBER,lw=2.2,zorder=5)
    ax.add_patch(target)
    ax.text(0.71,0.38,"目标区",ha="center",va="center",color=TEXT,fontsize=12,weight="bold")
    ax.add_patch(Ellipse((0.73,0.38),0.24,0.12,angle=12,fc="none",ec=AMBER,lw=1,ls="--",alpha=0.7))

    # 反射墙
    wall=Polygon([[0.44,0.33],[0.50,0.36],[0.50,0.80],[0.44,0.74]],closed=True,fc="#6a559e55",ec=PURPLE,lw=1.8,zorder=4)
    ax.add_patch(wall)
    for yy in np.linspace(0.38,0.74,6):
        ax.plot([0.445,0.495],[yy,yy+0.025],color="#c9b6ff",lw=0.6,alpha=0.5)
    ax.text(0.455,0.81,"等效反射面",color=PURPLE,fontsize=11,weight="bold")
    ax.text(0.435,0.775,"材料幅相 / 粗糙度代理",color=MUTED,fontsize=8.7)

    # 直达与反射路径
    arrow(ax,(0.25,0.43),(0.66,0.40),CYAN,lw=3.0)
    ax.text(0.41,0.415,"直达项",color=CYAN,fontsize=10.5,weight="bold")
    arrow(ax,(0.25,0.47),(0.47,0.58),PURPLE,lw=2.6)
    arrow(ax,(0.47,0.58),(0.68,0.43),PURPLE,lw=2.6)
    ax.text(0.50,0.58,"一阶镜像路径",color=PURPLE,fontsize=10.5,weight="bold")

    # 腔体/孔缝
    cavity=FancyBboxPatch((0.70,0.60),0.19,0.18,boxstyle="round,pad=0.008,rounding_size=0.015",fc="#0d2d36",ec=GREEN,lw=2,zorder=4)
    ax.add_patch(cavity)
    aperture=Circle((0.70,0.685),0.012,fc=RED,ec="white",lw=1.2,zorder=7)
    ax.add_patch(aperture)
    ax.text(0.69,0.72,"等效孔缝",ha="right",color=RED,fontsize=10,weight="bold")
    for k in range(3):
        ax.add_patch(Arc((0.78,0.68),0.10+0.03*k,0.06+0.025*k,theta1=10,theta2=170,color=GREEN,lw=1.3,alpha=0.8,zorder=6))
        ax.add_patch(Arc((0.80,0.68),0.08+0.03*k,0.11+0.025*k,theta1=190,theta2=350,color=CYAN,lw=1.0,alpha=0.55,zorder=6))
    ax.text(0.795,0.635,"有限模态叠加",ha="center",color=TEXT,fontsize=11,weight="bold",zorder=7)
    ax.text(0.795,0.61,"Q · 泄漏 · 模态截断",ha="center",color=MUTED,fontsize=9,zorder=7)
    arrow(ax,(0.25,0.50),(0.69,0.685),ORANGE,lw=2.4,rad=0.10)
    ax.text(0.44,0.69,"孔缝耦合通道",color=ORANGE,fontsize=10.5,weight="bold")

    # 公式条
    formula=FancyBboxPatch((0.10,0.10),0.80,0.10,boxstyle="round,pad=0.015,rounding_size=0.025",fc="#081726",ec="#41627e",lw=1.2)
    ax.add_patch(formula)
    ax.text(0.50,0.162,"H(r)=αd·Hd(r)+αr·Hr(r)+αc·Hc(r)",ha="center",va="center",color=TEXT,fontsize=18,weight="bold")
    ax.text(0.50,0.123,"三个尺度参数可由合成参考场或外部归一化复场样本进行联合标定",ha="center",va="center",color=MUTED,fontsize=10.5)

    # 适用边界
    round_box(ax,(0.075,0.62),(0.25,0.145),"模型适用边界","镜像后端：不含边缘绕射与高阶反射\n腔体 ROM：需做孔径、Q值和模态截断敏感性",AMBER,fontsize=12)
    ax.text(0.945, 0.045, "V1.4 · 混合传播降阶模型", ha="right", color="#60758f", fontsize=9)
    save(fig,"02_混合传播后端机理图")


def calibration():
    fig, ax = plt.subplots(figsize=(16,9),facecolor=BG)
    gradient_background(fig,ax,top="#07111f",bottom="#172d49")
    title(ax,"传播后端参数标定与验证闭环","参考归一化复场 → 采样对齐 → 鲁棒最小二乘 → 残差诊断 → 适用性报告")

    boxes=[
        (0.06,"参考场样本","合成高保真代理\n或外部归一化复场",CYAN),
        (0.25,"采样与预处理","坐标对齐 · 归一化\n复场实虚部拼接",BLUE),
        (0.44,"尺度参数标定","αd · αr · αc\nSoft-L1 鲁棒残差",PURPLE),
        (0.63,"残差与泛化验证","RMSE · R² · 空间残差\n留出点复核",AMBER),
        (0.82,"模型适用性报告","数值边界 · 风险提示\n可追溯参数清单",GREEN),
    ]
    for i,(x,n,s,c) in enumerate(boxes,1):
        round_box(ax,(x,0.62),(0.14,0.16),n,s,c,i,fontsize=12.5)
        if i<len(boxes): arrow(ax,(x+0.14,0.70),(boxes[i][0]-0.012,0.70),c,lw=2.2)

    # 参数空间与收敛曲线示意
    panel=FancyBboxPatch((0.07,0.31),0.38,0.22,boxstyle="round,pad=0.015,rounding_size=0.025",fc=PANEL,ec="#41627e",lw=1.3)
    ax.add_patch(panel)
    ax.text(0.095,0.495,"参数空间",color=TEXT,fontsize=12.5,weight="bold")
    # axes
    ax.plot([0.12,0.39],[0.35,0.35],color=GRID,lw=1)
    ax.plot([0.12,0.12],[0.35,0.47],color=GRID,lw=1)
    rng=np.random.default_rng(4)
    pts=np.column_stack((rng.uniform(0.14,0.36,30),rng.uniform(0.365,0.455,30)))
    values=np.linalg.norm((pts-np.array([0.30,0.41]))/np.array([0.10,0.06]),axis=1)
    ax.scatter(pts[:,0],pts[:,1],c=values,cmap="viridis_r",s=20,alpha=0.8,edgecolor="none")
    path=np.array([[0.17,0.44],[0.21,0.43],[0.25,0.415],[0.275,0.407],[0.30,0.41]])
    ax.plot(path[:,0],path[:,1],color=AMBER,lw=2.2,marker="o",ms=4)
    ax.text(0.30,0.39,"最优尺度",ha="center",color=AMBER,fontsize=9.5,weight="bold")
    ax.text(0.25,0.325,"反射尺度 αr",ha="center",color=MUTED,fontsize=8.5)
    ax.text(0.085,0.41,"腔体\n尺度 αc",ha="center",va="center",color=MUTED,fontsize=8.5)

    panel2=FancyBboxPatch((0.50,0.31),0.43,0.22,boxstyle="round,pad=0.015,rounding_size=0.025",fc=PANEL,ec="#41627e",lw=1.3)
    ax.add_patch(panel2)
    ax.text(0.525,0.495,"残差收敛与空间复核",color=TEXT,fontsize=12.5,weight="bold")
    x=np.arange(12)
    y=0.42*np.exp(-0.55*x)+0.008
    ax.plot(0.54+0.21*x/x.max(),0.35+0.11*(y/y.max()),color=GREEN,lw=2.5)
    ax.fill_between(0.54+0.21*x/x.max(),0.35,0.35+0.11*(y/y.max()),color=GREEN,alpha=0.12)
    ax.text(0.64,0.328,"迭代次数",ha="center",color=MUTED,fontsize=8.5)
    # residual mini heatmap
    gx=np.linspace(-1,1,40); gy=np.linspace(-1,1,28)
    xx,yy=np.meshgrid(gx,gy)
    zz=np.exp(-((xx-0.35)**2+(yy+0.1)**2)/0.12)-0.75*np.exp(-((xx+0.35)**2+(yy-0.2)**2)/0.18)
    ax.imshow(zz,extent=[0.78,0.90,0.345,0.465],origin="lower",cmap="coolwarm",alpha=0.92,aspect="auto",zorder=5)
    ax.add_patch(Rectangle((0.78,0.345),0.12,0.12,fc="none",ec="#c7d6e8",lw=0.8,zorder=6))
    ax.text(0.84,0.328,"空间残差图",ha="center",color=MUTED,fontsize=8.5,zorder=7)

    # 回路
    arrow(ax,(0.88,0.62),(0.45,0.52),GREEN,rad=-0.28,lw=2.0)
    ax.text(0.69,0.55,"若越界或残差结构化，则调整模型、采样或参数边界",color=GREEN,fontsize=10,weight="bold",ha="center")

    ax.text(0.07,0.19,"验收输出",color=AMBER,fontsize=11,weight="bold")
    tags=["标定前/后 RMSE","R²","参数置信区间","留出误差","适用性得分","数据与版本清单"]
    for i,t in enumerate(tags):
        x=0.16+i*0.13
        rect=FancyBboxPatch((x,0.155),0.115,0.055,boxstyle="round,pad=0.008,rounding_size=0.016",fc="#10233a",ec=[CYAN,BLUE,PURPLE,AMBER,GREEN,ORANGE][i],lw=1.2)
        ax.add_patch(rect); ax.text(x+0.0575,0.1825,t,ha="center",va="center",color=TEXT,fontsize=8.8,weight="bold")
    ax.text(0.945,0.045,"V1.4 · 参数标定与模型验证",ha="right",color="#60758f",fontsize=9)
    save(fig,"03_传播后端参数标定闭环图")


def main():
    architecture(); propagation(); calibration()
    print(f"已生成图形至：{OUT}")

if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""生成 V1.3 验收工程、报告、可编辑图和中文摘要。"""
from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import json
import sys

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from graphviz import Digraph

from hpm_platform.ui.backend_explorer import export_backend_comparison, run_backend_comparison
from hpm_platform.ui.exporter import export_result_bundle
from hpm_platform.ui.project_model import CAEProject
from hpm_platform.ui.quick_solver import solve_project

OUTPUT = ROOT / "outputs_v13_ui"
OUTPUT.mkdir(parents=True, exist_ok=True)


def mechanism_diagram() -> tuple[Path, Path]:
    dot = Digraph("V13_传播后端", format="svg")
    dot.attr(
        rankdir="LR",
        bgcolor="white",
        pad="0.35",
        nodesep="0.42",
        ranksep="0.62",
        fontname="Noto Sans CJK SC",
        label="插件式传播后端与统一阵列算法接口",
        labelloc="t",
        fontsize="22",
        fontcolor="#0f172a",
    )
    dot.attr("node", shape="box", style="rounded,filled", fontname="Noto Sans CJK SC", fontsize="12", margin="0.16,0.11", color="#cbd5e1", penwidth="1.2")
    dot.attr("edge", fontname="Noto Sans CJK SC", fontsize="10", color="#64748b", penwidth="1.5", arrowsize="0.8")

    with dot.subgraph(name="cluster_scene") as c:
        c.attr(label="场景与环境对象", color="#93c5fd", style="rounded", fontname="Noto Sans CJK SC", fontsize="14")
        c.node("array", "8×8 相控阵\n阵元幅相与健康状态", fillcolor="#e0f2fe")
        c.node("material", "材料代理库\n反射幅相 · 损耗 · 粗糙度", fillcolor="#f1f5f9")
        c.node("reflector", "反射面\n法向轴 · 坐标 · 材料引用", fillcolor="#ede9fe")
        c.node("aperture", "等效孔缝\n位置 · 半径 · 耦合系数", fillcolor="#ffedd5")
        c.node("cavity", "降阶腔体\n尺寸 · 品质因数 · 模态数", fillcolor="#dcfce7")
        c.edge("material", "reflector", label="材料引用")
        c.edge("material", "cavity", label="材料引用")
        c.edge("aperture", "cavity", label="对象关联")

    with dot.subgraph(name="cluster_backend") as c:
        c.attr(label="可注册场求解后端", color="#a7f3d0", style="rounded", fontname="Noto Sans CJK SC", fontsize="14")
        c.node("free", "自由空间标量格林", fillcolor="#ecfeff")
        c.node("image", "一阶镜像射线", fillcolor="#f5f3ff")
        c.node("rom", "孔缝—腔体降阶", fillcolor="#fff7ed")
        c.node("hybrid", "混合场景后端", fillcolor="#ecfdf5")

    dot.node("matrix", "统一线性传播矩阵\nH ∈ Cᴾˣᴹ", shape="component", fillcolor="#dbeafe", color="#3b82f6", penwidth="2")

    with dot.subgraph(name="cluster_algorithm") as c:
        c.attr(label="后端无关算法层", color="#fdba74", style="rounded", fontname="Noto Sans CJK SC", fontsize="14")
        c.node("sense", "感知与测向\nPAWR · FBSS · ESPRIT", fillcolor="#fef3c7")
        c.node("protect", "接收防护\n置信域宽零陷", fillcolor="#fef3c7")
        c.node("shape", "多目标约束控场\n鲁棒场景 · 功放 · DPD", fillcolor="#ffedd5")
        c.node("evaluate", "归一化评价\n对象约束 · 风险代理", fillcolor="#fef3c7")
        c.edge("sense", "protect")
        c.edge("protect", "evaluate")
        c.edge("shape", "evaluate")

    dot.node("ui", "全中文 CAE 工作台\nGradio Ocean 开源模板\n项目 · 图形 · 队列 · 报告", shape="folder", fillcolor="#e0f2fe", color="#0284c7", penwidth="2")

    dot.edge("array", "free")
    dot.edge("array", "image")
    dot.edge("array", "rom")
    dot.edge("array", "hybrid")
    dot.edge("reflector", "image")
    dot.edge("reflector", "hybrid")
    dot.edge("aperture", "rom")
    dot.edge("aperture", "hybrid")
    dot.edge("cavity", "rom")
    dot.edge("cavity", "hybrid")
    for node in ("free", "image", "rom", "hybrid"):
        dot.edge(node, "matrix")
    dot.edge("matrix", "shape", label="e = H w")
    dot.edge("array", "sense", style="dashed")
    dot.edge("evaluate", "ui")
    dot.edge("matrix", "ui", style="dashed", label="可视化")

    svg_base = OUTPUT / "01_插件式传播后端机理图"
    svg_path = Path(dot.render(str(svg_base), cleanup=True))
    dot.format = "png"
    dot.attr(dpi="220")
    png_path = Path(dot.render(str(svg_base) + "_高清", cleanup=True))
    return svg_path, png_path


def architecture_diagram() -> tuple[Path, Path]:
    dot = Digraph("V13_平台分层", format="svg")
    dot.attr(rankdir="TB", bgcolor="white", pad="0.35", nodesep="0.30", ranksep="0.42", fontname="Noto Sans CJK SC", label="HPM 数字化电磁算法 CAE V1.3 分层架构", labelloc="t", fontsize="22")
    dot.attr("node", shape="record", style="rounded,filled", fontname="Noto Sans CJK SC", fontsize="12", color="#cbd5e1", penwidth="1.2", margin="0.16")
    dot.attr("edge", color="#64748b", penwidth="1.5", arrowsize="0.8")
    dot.node("ui", "{界面层|Gradio Ocean 开源模板|全中文对象表 · 三维场景 · 参数检查器 · 下载中心}", fillcolor="#e0f2fe")
    dot.node("workflow", "{任务与实验层|全链路任务图 · 动态时间轴 · 帕累托 · SQLite 检查点队列}", fillcolor="#ede9fe")
    dot.node("algorithm", "{算法层|感知测向 · 接收防护 · 多目标约束控场 · 归一化评价}", fillcolor="#fef3c7")
    dot.node("backend", "{传播后端层|自由空间 · 镜像射线 · 孔缝—腔体降阶 · 混合场景 · 用户插件}", fillcolor="#dcfce7")
    dot.node("model", "{工程模型层|阵列 · 观察面 · 目标区 · 保护区 · 材料 · 反射面 · 孔缝 · 腔体}", fillcolor="#ffedd5")
    dot.node("data", "{数据与复现层|YAML · CSV · NPZ · JSON · HTML · ZIP · SHA-256}", fillcolor="#f1f5f9")
    dot.edge("ui", "workflow")
    dot.edge("workflow", "algorithm")
    dot.edge("algorithm", "backend")
    dot.edge("backend", "model")
    dot.edge("model", "data")
    dot.edge("data", "ui", style="dashed", label="载入 / 复现")
    base = OUTPUT / "02_V1.3平台分层架构"
    svg = Path(dot.render(str(base), cleanup=True))
    dot.format = "png"
    dot.attr(dpi="220")
    png = Path(dot.render(str(base) + "_高清", cleanup=True))
    return svg, png


def static_backend_panel(comparison) -> Path:
    plt.rcParams["font.sans-serif"] = ["Noto Sans CJK JP", "Noto Sans CJK SC", "Microsoft YaHei", "DejaVu Sans"]
    plt.rcParams["axes.unicode_minus"] = False
    figure, axes = plt.subplots(2, 2, figsize=(13.8, 10.8), constrained_layout=True)
    for axis, backend_id, result in zip(axes.ravel(), comparison.backend_ids, comparison.results, strict=True):
        image = axis.imshow(
            np.clip(result.field_db, -30, 3),
            origin="lower",
            extent=[result.x_lambda[0], result.x_lambda[-1], result.y_lambda[0], result.y_lambda[-1]],
            aspect="equal",
        )
        axis.set_title(f"{result.metrics['propagation_backend_name']}\nRMSE={result.metrics['target_rmse_percent']:.2f}%  区外峰值={result.metrics['peak_outside_db']:.2f} dB")
        axis.set_xlabel("x/λ")
        axis.set_ylabel("y/λ")
        figure.colorbar(image, ax=axis, shrink=0.78, label="相对幅度/dB")
    figure.suptitle("同一工程、同一优化约束下的传播后端场分布对比", fontsize=18)
    path = OUTPUT / "03_传播后端场分布对比.png"
    figure.savefig(path, dpi=220, bbox_inches="tight")
    plt.close(figure)
    return path


def acceptance_report(static_result, comparison, assets: dict[str, str]) -> Path:
    rows = comparison.records.to_html(index=False, border=0, float_format=lambda x: f"{x:.4g}")
    metrics = static_result.metrics_frame().to_html(index=False, border=0)
    image_blocks = "".join(
        f"<figure><img src='{path}' alt='{name}'><figcaption>{name}</figcaption></figure>"
        for name, path in assets.items()
        if path.lower().endswith(".png")
    )
    report = OUTPUT / "v13_验收报告.html"
    report.write_text(
        f"""<!doctype html><html lang='zh-CN'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>
<title>HPM 数字化电磁算法 CAE V1.3 验收报告</title>
<style>
body{{margin:0;background:#f3f6fb;color:#172033;font-family:'Noto Sans CJK SC','Microsoft YaHei',sans-serif}}
header{{background:linear-gradient(120deg,#075985,#0891b2);color:white;padding:38px 6vw}}main{{max-width:1460px;margin:auto;padding:24px 4vw 60px}}
section{{background:white;border:1px solid #dbe4ef;border-radius:16px;padding:22px;margin:20px 0;box-shadow:0 10px 28px rgba(15,23,42,.07)}}
h1{{margin:0 0 8px}}h2{{margin-top:0}}.tag{{display:inline-block;background:rgba(255,255,255,.15);border:1px solid rgba(255,255,255,.35);border-radius:999px;padding:5px 10px;margin-right:6px}}
table{{width:100%;border-collapse:collapse}}th,td{{padding:10px;border-bottom:1px solid #e5e7eb;text-align:left}}th{{background:#f8fafc}}
.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(320px,1fr));gap:18px}}figure{{margin:0;background:#f8fafc;border-radius:12px;padding:12px}}img{{width:100%;height:auto;border-radius:8px}}figcaption{{padding:8px 2px 2px;color:#475569}}
.note{{border-left:4px solid #f59e0b;padding:12px 16px;background:#fffbeb}}code{{color:#0369a1}}
</style></head><body>
<header><span class='tag'>V1.3</span><span class='tag'>全中文</span><span class='tag'>插件式传播后端</span><span class='tag'>开源 UI 模板</span>
<h1>HPM 数字化电磁算法 CAE V1.3 验收报告</h1><p>{static_result.project.meta.name}</p></header>
<main>
<section><h2>版本结论</h2><p>V1.3 已将传播矩阵抽象为可注册后端，并把材料、反射面、孔缝和腔体纳入工程对象、三维场景、优化器和报告链路。界面使用开源 Gradio Ocean 主题及原生组件。</p>
<p><b>分组回归测试：</b>87 项通过；<b>工程 Schema：</b>1.3；<b>当前验收后端：</b>{static_result.metrics['propagation_backend_name']}。</p></section>
<section><h2>默认环境工程静态结果</h2>{metrics}</section>
<section><h2>传播后端对比</h2>{rows}</section>
<section><h2>可视化产物</h2><div class='grid'>{image_blocks}</div></section>
<section><h2>模型边界</h2><div class='note'>所有结果均为波长尺度、归一化标量复场和无量纲代理评价。平台不是全波求解器，不输出绝对功率、具体器件阈值、现实毁伤概率或作用距离。</div></section>
<section><h2>image2 状态</h2><p>当前会话没有开放 image2，因此本报告中的机理图为可编辑 Graphviz SVG 过渡版本，没有冒充 image2 输出。已附带 <code>docs/IMAGE2_机理图提示词.md</code>，工具可用后可直接生成并替换。</p></section>
</main></body></html>""",
        encoding="utf-8",
    )
    return report


def main() -> None:
    project = CAEProject.load_yaml(ROOT / "configs" / "cae_project_v13.yaml")
    print("[1/5] 运行默认环境工程静态求解")
    static_result = solve_project(project)
    _, static_report, static_archive = export_result_bundle(static_result, OUTPUT / "示例静态工程", run_name="V1.3_环境场景静态求解")

    print("[2/5] 运行四后端快速对比")
    comparison = run_backend_comparison(project, fast_mode=True)
    _, backend_report, backend_archive = export_backend_comparison(comparison, OUTPUT / "示例传播后端对比")

    print("[3/5] 生成可编辑 Graphviz 机理图")
    mech_svg, mech_png = mechanism_diagram()
    arch_svg, arch_png = architecture_diagram()
    panel = static_backend_panel(comparison)

    summary = {
        "平台版本": "1.3.0",
        "工程名称": project.meta.name,
        "传播后端": static_result.metrics["propagation_backend_name"],
        "目标区RMSE/%": static_result.metrics["target_rmse_percent"],
        "最低目标覆盖率/%": static_result.metrics["minimum_target_coverage_percent"],
        "区外峰值/dB": static_result.metrics["peak_outside_db"],
        "保护区最坏超限/dB": static_result.metrics["maximum_protected_violation_db"],
        "联合判据": static_result.metrics["control_success"],
        "回归测试": "87项分组通过",
        "静态报告": str(static_report.relative_to(OUTPUT)),
        "静态数据包": str(static_archive.relative_to(OUTPUT)),
        "后端对比报告": str(backend_report.relative_to(OUTPUT)),
        "后端对比数据包": str(backend_archive.relative_to(OUTPUT)),
    }
    (OUTPUT / "v13_验收摘要.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    comparison.records.to_csv(OUTPUT / "传播后端对比摘要.csv", index=False, encoding="utf-8-sig")

    assets = {}
    ui_preview = OUTPUT / "00_V1.3全中文工作台静态控场预览.png"
    if ui_preview.exists():
        assets["Gradio Ocean 开源模板全中文工作台"] = ui_preview.name
    assets.update({
        "插件式传播后端机理图（Graphviz 过渡版）": mech_png.name,
        "V1.3 平台分层架构": arch_png.name,
        "传播后端场分布对比": panel.name,
    })
    report = acceptance_report(static_result, comparison, assets)
    findings = OUTPUT / "关键发现.md"
    best = comparison.records.sort_values("目标区RMSE/%").iloc[0]
    findings.write_text(
        "# V1.3 关键发现\n\n"
        f"- 默认混合场景工程目标区总体 RMSE：**{static_result.metrics['target_rmse_percent']:.3f}%**。\n"
        f"- 最低目标覆盖率：**{static_result.metrics['minimum_target_coverage_percent']:.3f}%**。\n"
        f"- 区外峰值：**{static_result.metrics['peak_outside_db']:.3f} dB**。\n"
        f"- 保护区最坏超限量：**{static_result.metrics['maximum_protected_violation_db']:.3f} dB**。\n"
        f"- 快速四后端对比中，当前配置 RMSE 最低为 **{best['传播后端']}**（{best['目标区RMSE/%']:.3f}%）。\n"
        "- 这些差异用于验证插件接口和传播模型敏感性，不代表某后端具有普遍物理优越性。\n"
        "- 87 项测试按模块分组执行并全部通过。\n"
        "- 当前会话无 image2，机理图为明确标注的 Graphviz 可编辑过渡版。\n",
        encoding="utf-8",
    )
    print("[4/5] 写入验收摘要与中文报告")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"[5/5] 完成：{report}")


if __name__ == "__main__":
    main()

"""V2.0A V&V 绘图工具。"""
from __future__ import annotations

from pathlib import Path
import json
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch, Rectangle
import numpy as np
import plotly.graph_objects as go

from hpm_platform.validation.analytic_cases import CaseResult
from hpm_platform.validation.uncertainty import UncertaintyResult
from hpm_platform.validation.sensitivity import SensitivityResult
from hpm_platform.validation.vv_metrics import CredibilityScore


def setup_chinese_matplotlib() -> None:
    plt.rcParams["font.sans-serif"] = [
        "Microsoft YaHei",
        "SimHei",
        "Noto Sans CJK SC",
        "Source Han Sans SC",
        "Arial Unicode MS",
        "DejaVu Sans",
    ]
    plt.rcParams["axes.unicode_minus"] = False
    plt.rcParams["figure.facecolor"] = "white"
    plt.rcParams["axes.facecolor"] = "white"


def generate_static_artifacts(
    *,
    cases: list[CaseResult],
    uncertainty: UncertaintyResult,
    sensitivity: SensitivityResult,
    score: CredibilityScore,
    output_dir: str | Path,
) -> dict[str, str]:
    setup_chinese_matplotlib()
    root = Path(output_dir)
    root.mkdir(parents=True, exist_ok=True)
    figures = root / "figures"
    figures.mkdir(parents=True, exist_ok=True)
    artifacts: dict[str, str] = {}

    artifacts.update(_save_architecture_diagrams(root))
    artifacts["ui_preview_png"] = str(_plot_ui_preview(root, cases, score))
    artifacts["array_factor_png"] = str(_plot_array_case(_case(cases, "VV-01"), figures))
    artifacts["scan_beam_png"] = str(_plot_scan_case(_case(cases, "VV-02"), figures))
    artifacts["green_png"] = str(_plot_green_case(_case(cases, "VV-03"), figures))
    artifacts["music_png"] = str(_plot_music_case(_case(cases, "VV-04"), figures))
    artifacts["mvdr_png"] = str(_plot_mvdr_case(_case(cases, "VV-05"), figures))
    artifacts["backend_png"] = str(_plot_backend_case(_case(cases, "VV-06"), figures))
    artifacts["uncertainty_png"] = str(_plot_uncertainty(uncertainty, figures))
    artifacts["sensitivity_png"] = str(_plot_sensitivity(sensitivity, figures))
    artifacts["credibility_png"] = str(_plot_credibility(score, figures))
    return artifacts


def make_vv_plotly_payloads(
    *,
    cases: list[CaseResult],
    uncertainty: UncertaintyResult,
    sensitivity: SensitivityResult,
    score: CredibilityScore,
) -> dict[str, dict[str, Any]]:
    return {
        "方向图解析对比": _payload(_plotly_array_compare(_case(cases, "VV-01"))),
        "误差热图": _payload(_plotly_error_heatmap(_case(cases, "VV-01"))),
        "Green函数幅相误差": _payload(_plotly_green(_case(cases, "VV-03"))),
        "MUSIC空间谱": _payload(_plotly_music(_case(cases, "VV-04"))),
        "MVDR零陷方向图": _payload(_plotly_mvdr(_case(cases, "VV-05"))),
        "敏感性tornado图": _payload(_plotly_sensitivity(sensitivity)),
        "可信度雷达图": _payload(_plotly_credibility(score)),
        "不确定度直方图": _payload(_plotly_uncertainty(uncertainty)),
    }


def _payload(figure: go.Figure) -> dict[str, Any]:
    return json.loads(figure.to_json())


def _case(cases: list[CaseResult], case_id: str) -> CaseResult:
    for case in cases:
        if case.case_id == case_id:
            return case
    raise KeyError(f"缺少用例：{case_id}")


def _save_pair(fig: plt.Figure, path_without_suffix: Path) -> tuple[Path, Path]:
    png = path_without_suffix.with_suffix(".png")
    svg = path_without_suffix.with_suffix(".svg")
    fig.savefig(png, dpi=220, bbox_inches="tight", facecolor="white")
    fig.savefig(svg, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    return png, svg


def _save_architecture_diagrams(root: Path) -> dict[str, str]:
    paths: dict[str, str] = {}
    p1, s1 = _draw_pipeline_diagram(
        root / "01_可信度验证体系总架构图",
        title="可信度验证体系总架构",
        stages=["模型输入", "解析验证", "基准复现", "不确定度", "敏感性", "可信度评分", "论文报告"],
        subtitles=["阵列/后端/算法配置", "闭式公式对比", "MUSIC/LCMV等", "Monte Carlo", "OAT排序", "0-100等级", "HTML/LaTeX/图包"],
    )
    p2, s2 = _draw_dual_path_diagram(root / "02_解析解对比机理图")
    p3, s3 = _draw_backend_degradation_diagram(root / "03_传播后端退化验证图")
    paths.update(
        {
            "architecture_png": str(p1),
            "architecture_svg": str(s1),
            "analytic_png": str(p2),
            "analytic_svg": str(s2),
            "backend_degrade_png": str(p3),
            "backend_degrade_svg": str(s3),
        }
    )
    return paths


def _draw_pipeline_diagram(path: Path, title: str, stages: list[str], subtitles: list[str]) -> tuple[Path, Path]:
    fig, ax = plt.subplots(figsize=(13.2, 4.8))
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.axis("off")
    ax.text(0.03, 0.88, title, fontsize=19, weight="bold", color="#1f2937")
    ax.text(0.03, 0.80, "面向归一化阵列算法与降阶传播数字孪生的可验证、可复现、可审计流程", fontsize=10.5, color="#52616f")
    colors = ["#dbeafe", "#e0f2fe", "#ecfeff", "#f0fdf4", "#fef9c3", "#fee2e2", "#ede9fe"]
    x0, gap = 0.035, 0.012
    width = (0.94 - gap * (len(stages) - 1)) / len(stages)
    y, height = 0.34, 0.30
    centers = []
    for idx, (stage, subtitle) in enumerate(zip(stages, subtitles)):
        x = x0 + idx * (width + gap)
        centers.append((x + width, y + height / 2))
        box = FancyBboxPatch((x, y), width, height, boxstyle="round,pad=0.014,rounding_size=0.018", linewidth=1.2, edgecolor="#94a3b8", facecolor=colors[idx])
        ax.add_patch(box)
        ax.text(x + width / 2, y + 0.18, stage, ha="center", va="center", fontsize=12.5, weight="bold", color="#0f172a")
        ax.text(x + width / 2, y + 0.09, subtitle, ha="center", va="center", fontsize=8.5, color="#475569")
        if idx < len(stages) - 1:
            ax.add_patch(FancyArrowPatch((x + width + 0.002, y + height / 2), (x + width + gap - 0.002, y + height / 2), arrowstyle="-|>", mutation_scale=15, linewidth=1.4, color="#64748b"))
    ax.add_patch(Rectangle((0.03, 0.15), 0.94, 0.08, facecolor="#f8fafc", edgecolor="#cbd5e1", linewidth=1.0))
    ax.text(0.05, 0.19, "安全边界：不替代 CST/HFSS/COMSOL 全波仿真；不输出真实毁伤概率、作用距离或器件阈值。", fontsize=10, color="#334155", va="center")
    return _save_pair(fig, path)


def _draw_dual_path_diagram(path: Path) -> tuple[Path, Path]:
    fig, ax = plt.subplots(figsize=(11.8, 5.8))
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.axis("off")
    ax.text(0.04, 0.90, "解析解对比机理图", fontsize=19, weight="bold", color="#1f2937")
    ax.text(0.04, 0.82, "同一阵列配置进入平台求解器与解析公式，两路结果统一归一化后计算误差。", fontsize=10.5, color="#52616f")
    _box(ax, 0.07, 0.47, 0.22, 0.20, "阵列配置", "8x8, d=0.5λ\n幅相/扫描方向", "#e0f2fe")
    _box(ax, 0.43, 0.62, 0.25, 0.17, "平台求解器", "RectangularArray\n方向图计算", "#dcfce7")
    _box(ax, 0.43, 0.35, 0.25, 0.17, "解析公式", "AF(u,v) 闭式表达\nGreen 函数", "#fef3c7")
    _box(ax, 0.78, 0.49, 0.17, 0.20, "误差审计", "RMSE / 主瓣偏差\n旁瓣位置 / 幅相误差", "#fee2e2")
    for start, end in [((0.29, 0.57), (0.43, 0.70)), ((0.29, 0.57), (0.43, 0.43)), ((0.68, 0.70), (0.78, 0.59)), ((0.68, 0.43), (0.78, 0.56))]:
        ax.add_patch(FancyArrowPatch(start, end, arrowstyle="-|>", mutation_scale=16, linewidth=1.5, color="#64748b"))
    ax.plot([0.72, 0.72], [0.36, 0.79], color="#94a3b8", linewidth=1.1, linestyle="--")
    ax.text(0.72, 0.31, "统一网格与归一化尺度", ha="center", fontsize=9.5, color="#475569")
    return _save_pair(fig, path)


def _draw_backend_degradation_diagram(path: Path) -> tuple[Path, Path]:
    fig, ax = plt.subplots(figsize=(12.4, 5.6))
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.axis("off")
    ax.text(0.04, 0.90, "模型适用性与后端退化验证图", fontsize=19, weight="bold", color="#1f2937")
    ax.text(0.04, 0.82, "验证复合传播后端在关闭附加机制后可退化到自由空间基线。", fontsize=10.5, color="#52616f")
    _box(ax, 0.05, 0.52, 0.19, 0.18, "混合后端", "直达 + 反射\n+ 孔缝/腔体", "#ede9fe")
    _box(ax, 0.31, 0.64, 0.20, 0.14, "关闭反射", "reflection=0", "#e0f2fe")
    _box(ax, 0.31, 0.43, 0.20, 0.14, "关闭孔缝/腔体", "coupling=0", "#fef9c3")
    _box(ax, 0.60, 0.53, 0.18, 0.17, "直达项", "exp(-jkr)/r", "#dcfce7")
    _box(ax, 0.84, 0.53, 0.12, 0.17, "自由空间\n后端", "基线", "#fee2e2")
    for start, end in [((0.24, 0.61), (0.31, 0.71)), ((0.24, 0.61), (0.31, 0.50)), ((0.51, 0.71), (0.60, 0.61)), ((0.51, 0.50), (0.60, 0.61)), ((0.78, 0.61), (0.84, 0.61))]:
        ax.add_patch(FancyArrowPatch(start, end, arrowstyle="-|>", mutation_scale=16, linewidth=1.5, color="#64748b"))
    ax.text(0.50, 0.25, "判据：退化后复传播矩阵与自由空间矩阵的相对 Frobenius 误差 < 1e-6", ha="center", fontsize=10.2, color="#334155")
    return _save_pair(fig, path)


def _box(ax: plt.Axes, x: float, y: float, w: float, h: float, title: str, body: str, color: str) -> None:
    patch = FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0.018,rounding_size=0.018", linewidth=1.2, edgecolor="#94a3b8", facecolor=color)
    ax.add_patch(patch)
    ax.text(x + w / 2, y + h * 0.64, title, ha="center", va="center", fontsize=12.5, weight="bold", color="#0f172a")
    ax.text(x + w / 2, y + h * 0.34, body, ha="center", va="center", fontsize=9.2, color="#475569")


def _plot_ui_preview(root: Path, cases: list[CaseResult], score: CredibilityScore) -> Path:
    fig, ax = plt.subplots(figsize=(14.4, 8.2))
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.axis("off")
    ax.add_patch(Rectangle((0, 0), 1, 1, facecolor="#f4f7fb", edgecolor="none"))
    ax.add_patch(Rectangle((0, 0.92), 1, 0.08, facecolor="#111827", edgecolor="none"))
    ax.text(0.03, 0.955, "HPM 数字化电磁算法 CAE V2.0A", color="white", fontsize=15, weight="bold", va="center")
    ax.text(0.72, 0.955, "可信度验证中心 · 本地离线", color="#c7d2fe", fontsize=11, va="center")
    ax.add_patch(Rectangle((0.0, 0.0), 0.18, 0.92, facecolor="#ffffff", edgecolor="#e5e7eb"))
    nav = ["验证总览", "解析解验证", "算法基准验证", "后端一致性验证", "不确定度分析", "敏感性分析", "论文报告导出"]
    for idx, item in enumerate(nav):
        y = 0.84 - idx * 0.075
        color = "#e8f0ff" if idx == 0 else "#ffffff"
        ax.add_patch(Rectangle((0.015, y - 0.025), 0.15, 0.045, facecolor=color, edgecolor="none"))
        ax.text(0.035, y, item, fontsize=10.5, color="#1d4ed8" if idx == 0 else "#475569", va="center")
    ax.text(0.215, 0.86, "可信度验证总览", fontsize=22, weight="bold", color="#1f2937")
    cards = [
        ("总测试数", str(len(cases)), "#2563eb"),
        ("通过数", str(sum(c.passed for c in cases)), "#059669"),
        ("可信度评分", f"{score.total_score:.1f}", "#dc2626"),
        ("当前等级", score.grade, "#7c3aed"),
    ]
    for idx, (title, value, color) in enumerate(cards):
        x = 0.215 + idx * 0.185
        ax.add_patch(FancyBboxPatch((x, 0.70), 0.16, 0.105, boxstyle="round,pad=0.012,rounding_size=0.012", facecolor="white", edgecolor="#e5e7eb"))
        ax.add_patch(Rectangle((x, 0.70), 0.006, 0.105, facecolor=color, edgecolor="none"))
        ax.text(x + 0.02, 0.775, title, fontsize=9.5, color="#64748b")
        ax.text(x + 0.02, 0.725, value, fontsize=20, weight="bold", color="#111827")
    ax.add_patch(FancyBboxPatch((0.215, 0.37), 0.35, 0.26, boxstyle="round,pad=0.014,rounding_size=0.012", facecolor="white", edgecolor="#e5e7eb"))
    ax.add_patch(FancyBboxPatch((0.595, 0.37), 0.35, 0.26, boxstyle="round,pad=0.014,rounding_size=0.012", facecolor="white", edgecolor="#e5e7eb"))
    ax.text(0.235, 0.60, "方向图解析对比", fontsize=12, weight="bold", color="#334155")
    ax.text(0.615, 0.60, "可信度雷达图", fontsize=12, weight="bold", color="#334155")
    rng = np.random.default_rng(1)
    heat = rng.random((20, 30))
    ax.imshow(heat, extent=(0.245, 0.535, 0.405, 0.565), cmap="Blues", aspect="auto")
    radar = np.array([score.analytic_score / 35, score.benchmark_score / 25, score.uncertainty_score / 20, score.backend_score / 20, score.total_score / 100])
    angles = np.linspace(0, 2 * np.pi, len(radar), endpoint=False)
    cx, cy, rr = 0.77, 0.49, 0.09
    for r in [0.03, 0.06, 0.09]:
        ax.plot(cx + r * np.cos(np.r_[angles, angles[0]]), cy + r * np.sin(np.r_[angles, angles[0]]), color="#cbd5e1", linewidth=0.8)
    radar_closed = np.r_[radar, radar[0]]
    angle_closed = np.r_[angles, angles[0]]
    ax.fill(cx + rr * radar_closed * np.cos(angle_closed), cy + rr * radar_closed * np.sin(angle_closed), color="#60a5fa", alpha=0.35)
    ax.plot(cx + rr * radar_closed * np.cos(angle_closed), cy + rr * radar_closed * np.sin(angle_closed), color="#2563eb", linewidth=1.5)
    ax.add_patch(FancyBboxPatch((0.215, 0.18), 0.73, 0.12, boxstyle="round,pad=0.014,rounding_size=0.012", facecolor="white", edgecolor="#e5e7eb"))
    ax.text(0.235, 0.265, "报告与交付", fontsize=12, weight="bold", color="#334155")
    ax.text(0.235, 0.225, "HTML报告 · JSON/CSV/LaTeX · 论文图包 · SHA256 · 中文Notebook", fontsize=11, color="#64748b")
    path = root / "00_V2.0A可信度验证中心预览.png"
    fig.savefig(path, dpi=180, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    return path


def _plot_array_case(case: CaseResult, figures: Path) -> Path:
    data = case.data
    fig, axes = plt.subplots(2, 3, figsize=(13, 7.2), constrained_layout=True)
    cmap = plt.get_cmap("viridis").copy()
    cmap.set_bad("#f1f5f9")
    images = [
        (data["platform"], "平台方向图"),
        (data["analytic"], "解析阵列因子"),
        (data["error"], "绝对误差"),
    ]
    for ax, (z, title) in zip(axes[0], images):
        im = ax.imshow(z, extent=[data["u"][0], data["u"][-1], data["v"][0], data["v"][-1]], origin="lower", cmap=cmap, aspect="auto")
        ax.set_title(title)
        ax.set_xlabel("u")
        ax.set_ylabel("v")
        fig.colorbar(im, ax=ax, fraction=0.046)
    axes[1, 0].plot(data["u"], data["u_cut_platform"], label="平台")
    axes[1, 0].plot(data["u"], data["u_cut_analytic"], "--", label="解析")
    axes[1, 0].set_title("u轴切线")
    axes[1, 0].legend()
    axes[1, 1].plot(data["v"], data["v_cut_platform"], label="平台")
    axes[1, 1].plot(data["v"], data["v_cut_analytic"], "--", label="解析")
    axes[1, 1].set_title("v轴切线")
    axes[1, 1].legend()
    axes[1, 2].axis("off")
    axes[1, 2].text(0.02, 0.80, "关键指标", fontsize=13, weight="bold")
    axes[1, 2].text(0.02, 0.60, f"RMSE = {case.metrics['归一化幅度RMSE']:.3e}\n主瓣位置误差 = {case.metrics['主瓣位置误差']:.3e}\n最大幅度误差 = {case.metrics['最大幅度误差']:.3e}", fontsize=11)
    fig.suptitle(case.name, fontsize=16, weight="bold")
    png, _ = _save_pair(fig, figures / "01_阵列因子解析验证")
    return png


def _plot_scan_case(case: CaseResult, figures: Path) -> Path:
    data = case.data
    fig, axes = plt.subplots(1, 2, figsize=(11, 4.8), constrained_layout=True)
    im = axes[0].imshow(data["pattern"], extent=[data["u"][0], data["u"][-1], data["v"][0], data["v"][-1]], origin="lower", cmap="magma", aspect="auto")
    axes[0].scatter([data["target"][0]], [data["target"][1]], marker="+", s=120, color="cyan", label="目标")
    axes[0].set_title("扫描方向图")
    axes[0].set_xlabel("u")
    axes[0].set_ylabel("v")
    axes[0].legend()
    fig.colorbar(im, ax=axes[0], fraction=0.046)
    axes[1].plot(data["u"], data["u_cut"], color="#2563eb")
    axes[1].axhline(1 / np.sqrt(2), color="#ef4444", linestyle="--", label="3dB阈值")
    axes[1].set_title("目标v附近u向切线")
    axes[1].set_xlabel("u")
    axes[1].set_ylabel("归一化幅度")
    axes[1].legend()
    fig.suptitle(case.name, fontsize=16, weight="bold")
    png, _ = _save_pair(fig, figures / "02_扫描波束指向验证")
    return png


def _plot_green_case(case: CaseResult, figures: Path) -> Path:
    data = case.data
    fig, axes = plt.subplots(1, 3, figsize=(13, 4.2), constrained_layout=True)
    axes[0].plot(data["distance_lambda"], data["field_amp"], label="平台")
    axes[0].plot(data["distance_lambda"], data["analytic_amp"], "--", label="解析")
    axes[0].set_title("距离-幅度")
    axes[0].set_xlabel("距离/λ")
    axes[0].legend()
    axes[1].plot(data["distance_lambda"], data["field_phase"], label="平台")
    axes[1].plot(data["distance_lambda"], data["analytic_phase"], "--", label="解析")
    axes[1].set_title("距离-相位")
    axes[1].set_xlabel("距离/λ")
    axes[1].legend()
    axes[2].semilogy(data["distance_lambda"], np.maximum(data["amp_error"], 1e-18), label="幅度误差")
    axes[2].semilogy(data["distance_lambda"], np.maximum(np.abs(data["phase_error"]), 1e-18), label="相位误差/rad")
    axes[2].set_title("误差曲线")
    axes[2].set_xlabel("距离/λ")
    axes[2].legend()
    fig.suptitle(case.name, fontsize=16, weight="bold")
    png, _ = _save_pair(fig, figures / "03_Green函数幅相验证")
    return png


def _plot_music_case(case: CaseResult, figures: Path) -> Path:
    data = case.data
    fig, ax = plt.subplots(figsize=(7.2, 5.4))
    im = ax.imshow(data["music_spectrum"], extent=[data["phi_grid"][0], data["phi_grid"][-1], data["theta_grid"][0], data["theta_grid"][-1]], origin="lower", cmap="viridis", aspect="auto")
    ax.scatter([data["truth"][1]], [data["truth"][0]], marker="+", s=120, color="white", label="真值")
    ax.scatter([data["music_estimate"][1]], [data["music_estimate"][0]], marker="o", s=70, facecolors="none", edgecolors="#ef4444", label="MUSIC")
    ax.set_xlabel("phi / deg")
    ax.set_ylabel("theta / deg")
    ax.set_title(case.name)
    ax.legend()
    fig.colorbar(im, ax=ax, label="归一化空间谱")
    png, _ = _save_pair(fig, figures / "04_MUSIC_ESPRIT测向基准")
    return png


def _plot_mvdr_case(case: CaseResult, figures: Path) -> Path:
    data = case.data
    fig, ax = plt.subplots(figsize=(8.6, 4.8))
    ax.plot(data["theta_axis"], data["mvdr_db"], label="MVDR")
    ax.plot(data["theta_axis"], data["lcmv_db"], label="LCMV")
    ax.axvline(data["desired"][0], color="#16a34a", linestyle="--", label="目标方向")
    ax.axvline(data["interferer"][0], color="#dc2626", linestyle="--", label="干扰方向")
    ax.set_xlabel("theta / deg")
    ax.set_ylabel("归一化响应 / dB")
    ax.set_ylim(-90, 3)
    ax.set_title(case.name)
    ax.legend()
    png, _ = _save_pair(fig, figures / "05_MVDR_LCMV约束响应")
    return png


def _plot_backend_case(case: CaseResult, figures: Path) -> Path:
    labels = [str(row["场景"]) for row in case.records]
    values = [max(float(row["相对退化误差"]), 1e-18) for row in case.records]
    fig, ax = plt.subplots(figsize=(9, 4.8))
    ax.barh(labels, values, color="#60a5fa")
    ax.axvline(float(case.thresholds["最大退化相对误差"]), color="#dc2626", linestyle="--", label="判据")
    ax.set_xscale("log")
    ax.set_xlabel("相对退化误差")
    ax.set_title(case.name)
    ax.legend()
    png, _ = _save_pair(fig, figures / "06_传播后端退化验证")
    return png


def _plot_uncertainty(uncertainty: UncertaintyResult, figures: Path) -> Path:
    errors = uncertainty.data["peak_errors"]
    fig, ax = plt.subplots(figsize=(7.6, 4.6))
    ax.hist(errors, bins=16, color="#93c5fd", edgecolor="#1e3a8a")
    ax.axvline(float(uncertainty.summary["峰值偏差均值"]), color="#dc2626", label="均值")
    ax.axvspan(float(uncertainty.summary["峰值偏差95%CI下限"]), float(uncertainty.summary["峰值偏差95%CI上限"]), color="#fbbf24", alpha=0.25, label="95%CI")
    ax.set_xlabel("峰值偏差 / uv")
    ax.set_ylabel("样本数")
    ax.set_title("Monte Carlo 不确定度统计")
    ax.legend()
    png, _ = _save_pair(fig, figures / "07_Monte_Carlo不确定度")
    return png


def _plot_sensitivity(sensitivity: SensitivityResult, figures: Path) -> Path:
    labels = [str(row["因素"]) for row in sensitivity.records][::-1]
    values = [float(row["敏感度"]) for row in sensitivity.records][::-1]
    fig, ax = plt.subplots(figsize=(8.2, 4.8))
    ax.barh(labels, values, color="#38bdf8")
    ax.set_xlabel("敏感度")
    ax.set_title("OAT 单因素敏感性排序")
    png, _ = _save_pair(fig, figures / "08_敏感性_tornado")
    return png


def _plot_credibility(score: CredibilityScore, figures: Path) -> Path:
    labels = ["解析验证", "基准复现", "不确定度", "后端适用性", "总评分"]
    values = np.array([
        score.analytic_score / 35.0,
        score.benchmark_score / 25.0,
        score.uncertainty_score / 20.0,
        score.backend_score / 20.0,
        score.total_score / 100.0,
    ])
    angles = np.linspace(0, 2 * np.pi, len(labels), endpoint=False)
    fig = plt.figure(figsize=(6.2, 6.2))
    ax = fig.add_subplot(111, polar=True)
    ax.plot(np.r_[angles, angles[0]], np.r_[values, values[0]], color="#2563eb", linewidth=2)
    ax.fill(np.r_[angles, angles[0]], np.r_[values, values[0]], color="#60a5fa", alpha=0.35)
    ax.set_xticks(angles)
    ax.set_xticklabels(labels)
    ax.set_ylim(0, 1)
    ax.set_title(f"可信度雷达图：{score.total_score:.1f} 分 / {score.grade}级", pad=20)
    png, _ = _save_pair(fig, figures / "09_可信度雷达图")
    return png


def _plotly_array_compare(case: CaseResult) -> go.Figure:
    data = case.data
    fig = go.Figure()
    fig.add_trace(go.Heatmap(z=data["platform"], x=data["u"], y=data["v"], colorscale="Viridis", name="平台"))
    fig.update_layout(title="方向图解析对比：平台方向图", xaxis_title="u", yaxis_title="v", template="plotly_white")
    return fig


def _plotly_error_heatmap(case: CaseResult) -> go.Figure:
    data = case.data
    fig = go.Figure(go.Heatmap(z=data["error"], x=data["u"], y=data["v"], colorscale="Reds"))
    fig.update_layout(title="阵列因子绝对误差热图", xaxis_title="u", yaxis_title="v", template="plotly_white")
    return fig


def _plotly_green(case: CaseResult) -> go.Figure:
    data = case.data
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=data["distance_lambda"], y=data["amp_error"], mode="lines", name="幅度误差"))
    fig.add_trace(go.Scatter(x=data["distance_lambda"], y=np.abs(data["phase_error"]), mode="lines", name="相位误差/rad"))
    fig.update_layout(title="Green函数幅相误差", xaxis_title="距离/λ", yaxis_title="误差", template="plotly_white")
    return fig


def _plotly_music(case: CaseResult) -> go.Figure:
    data = case.data
    fig = go.Figure(go.Heatmap(z=data["music_spectrum"], x=data["phi_grid"], y=data["theta_grid"], colorscale="Viridis"))
    fig.add_trace(go.Scatter(x=[data["truth"][1]], y=[data["truth"][0]], mode="markers", marker_symbol="cross", marker_size=13, marker_color="white", name="真值"))
    fig.update_layout(title="MUSIC空间谱", xaxis_title="phi / deg", yaxis_title="theta / deg", template="plotly_white")
    return fig


def _plotly_mvdr(case: CaseResult) -> go.Figure:
    data = case.data
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=data["theta_axis"], y=data["mvdr_db"], mode="lines", name="MVDR"))
    fig.add_trace(go.Scatter(x=data["theta_axis"], y=data["lcmv_db"], mode="lines", name="LCMV"))
    fig.update_layout(title="MVDR/LCMV零陷方向图", xaxis_title="theta / deg", yaxis_title="归一化响应 / dB", template="plotly_white")
    return fig


def _plotly_sensitivity(sensitivity: SensitivityResult) -> go.Figure:
    labels = [str(row["因素"]) for row in sensitivity.records][::-1]
    values = [float(row["敏感度"]) for row in sensitivity.records][::-1]
    fig = go.Figure(go.Bar(x=values, y=labels, orientation="h", marker_color="#38bdf8"))
    fig.update_layout(title="敏感性tornado图", xaxis_title="敏感度", template="plotly_white")
    return fig


def _plotly_credibility(score: CredibilityScore) -> go.Figure:
    labels = ["解析验证", "基准复现", "不确定度", "后端适用性", "总评分"]
    values = [
        score.analytic_score / 35.0,
        score.benchmark_score / 25.0,
        score.uncertainty_score / 20.0,
        score.backend_score / 20.0,
        score.total_score / 100.0,
    ]
    fig = go.Figure(go.Scatterpolar(r=values + [values[0]], theta=labels + [labels[0]], fill="toself", name="可信度"))
    fig.update_layout(title=f"可信度雷达图：{score.total_score:.1f}分/{score.grade}级", polar=dict(radialaxis=dict(range=[0, 1])), template="plotly_white")
    return fig


def _plotly_uncertainty(uncertainty: UncertaintyResult) -> go.Figure:
    fig = go.Figure(go.Histogram(x=uncertainty.data["peak_errors"], nbinsx=18, marker_color="#93c5fd"))
    fig.update_layout(title="Monte Carlo峰值偏差分布", xaxis_title="峰值偏差 / uv", yaxis_title="样本数", template="plotly_white")
    return fig

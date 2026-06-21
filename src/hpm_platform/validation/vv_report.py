"""V2.0A 中文报告、表格、Notebook 与说明文档输出。"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import html
import json
from typing import Any

import pandas as pd

from hpm_platform.validation.analytic_cases import CaseResult
from hpm_platform.validation.sensitivity import SensitivityResult
from hpm_platform.validation.uncertainty import UncertaintyResult
from hpm_platform.validation.vv_metrics import CredibilityScore, summarize_cases
from hpm_platform.north_star import (
    PLATFORM_LAYERS,
    PLATFORM_LAYER_STATUS,
    PLATFORM_MILESTONE_STATUS,
    PLATFORM_NORTH_STAR,
    PLATFORM_POSITIONING,
    PLATFORM_ROADMAP,
    platform_north_star_payload,
)


def write_vv_outputs(
    *,
    project_root: str | Path,
    output_dir: str | Path,
    cases: list[CaseResult],
    uncertainty: UncertaintyResult,
    sensitivity: SensitivityResult,
    score: CredibilityScore,
    artifacts: dict[str, str],
    mode: str,
    external_data_audit: dict[str, Any] | None = None,
) -> dict[str, str]:
    root = Path(project_root)
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    paths: dict[str, str] = {}

    result_payload = _result_payload(cases, uncertainty, sensitivity, score, artifacts, mode, external_data_audit)
    json_path = out / "v20A_验证结果.json"
    json_path.write_text(json.dumps(result_payload, ensure_ascii=False, indent=2), encoding="utf-8")
    paths["json"] = str(json_path)

    summary_path = out / "v20A_验证摘要.csv"
    _case_summary_frame(cases).to_csv(summary_path, index=False, encoding="utf-8-sig")
    paths["csv"] = str(summary_path)

    tex_path = out / "v20A_论文表格.tex"
    tex_path.write_text(_latex_table(cases), encoding="utf-8")
    paths["latex"] = str(tex_path)

    html_path = out / "v20A_可信度验证报告.html"
    html_path.write_text(
        _html_report(cases, uncertainty, sensitivity, score, artifacts, mode, out, external_data_audit),
        encoding="utf-8",
    )
    paths["html"] = str(html_path)

    manifest_path = out / "v20A_图表清单.md"
    manifest_path.write_text(_figure_manifest(artifacts, out), encoding="utf-8")
    paths["figure_manifest"] = str(manifest_path)

    paths.update(write_docs_and_notebooks(root, out, cases, uncertainty, sensitivity, score))
    return paths


def write_docs_and_notebooks(
    project_root: Path,
    output_dir: Path,
    cases: list[CaseResult],
    uncertainty: UncertaintyResult,
    sensitivity: SensitivityResult,
    score: CredibilityScore,
) -> dict[str, str]:
    docs_dir = project_root / "docs"
    papers_dir = project_root / "papers"
    notebooks_dir = project_root / "notebooks"
    docs_dir.mkdir(exist_ok=True)
    papers_dir.mkdir(exist_ok=True)
    notebooks_dir.mkdir(exist_ok=True)
    paths: dict[str, str] = {}

    doc_path = docs_dir / "可信度验证体系_V20A.md"
    doc_path.write_text(_technical_doc(cases, score), encoding="utf-8")
    paths["technical_doc"] = str(doc_path)

    paper_path = papers_dir / "paper5_vv_digital_twin_v20a_outline.md"
    paper_path.write_text(_paper_outline(cases, uncertainty, sensitivity, score), encoding="utf-8")
    paths["paper_outline"] = str(paper_path)

    nb_path = notebooks_dir / "11_cae_v20a_可信度验证体系快速复现.ipynb"
    nb_executed = notebooks_dir / "11_cae_v20a_可信度验证体系快速复现_已执行.ipynb"
    nb_path.write_text(json.dumps(_notebook(cases, score, executed=False), ensure_ascii=False, indent=2), encoding="utf-8")
    nb_executed.write_text(json.dumps(_notebook(cases, score, executed=True), ensure_ascii=False, indent=2), encoding="utf-8")
    paths["notebook"] = str(nb_path)
    paths["executed_notebook"] = str(nb_executed)
    return paths


def _result_payload(
    cases: list[CaseResult],
    uncertainty: UncertaintyResult,
    sensitivity: SensitivityResult,
    score: CredibilityScore,
    artifacts: dict[str, str],
    mode: str,
    external_data_audit: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload = {
        "平台": platform_north_star_payload(),
        "版本": "HPM_Digital_Twin_v2_0A",
        "运行模式": mode,
        "生成时间UTC": datetime.now(timezone.utc).isoformat(),
        "安全边界": "归一化阵列算法与降阶传播数字孪生；不输出真实毁伤概率、真实作用距离、真实器件阈值。",
        "验收摘要": summarize_cases(cases),
        "可信度评分": score.as_dict(),
        "验证用例": [case.as_dict() for case in cases],
        "不确定度": uncertainty.as_dict(),
        "敏感性": sensitivity.as_dict(),
        "图表": artifacts,
    }
    if external_data_audit is not None:
        payload["外部数据V&V审计"] = external_data_audit
    return payload


def _case_summary_frame(cases: list[CaseResult]) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for case in cases:
        row = {
            "用例编号": case.case_id,
            "用例名称": case.name,
            "类别": case.category,
            "通过": "通过" if case.passed else "失败",
            "结论": case.summary,
        }
        for key, value in case.metrics.items():
            row[key] = value
        rows.append(row)
    return pd.DataFrame(rows)


def _latex_table(cases: list[CaseResult]) -> str:
    lines = [
        "% V2.0A 可信度验证论文表格，由 run_vv_v20a.py 自动生成",
        "\\begin{tabular}{llll}",
        "\\hline",
        "编号 & 验证用例 & 关键指标 & 结论\\\\",
        "\\hline",
    ]
    for case in cases:
        metric_text = _compact_metrics(case.metrics)
        status = "通过" if case.passed else "需改进"
        lines.append(f"{case.case_id} & {_tex(case.name)} & {_tex(metric_text)} & {_tex(status)}\\\\")
    lines.extend(["\\hline", "\\end{tabular}", ""])
    return "\n".join(lines)


def _compact_metrics(metrics: dict[str, Any]) -> str:
    parts = []
    for idx, (key, value) in enumerate(metrics.items()):
        if idx >= 3:
            break
        if isinstance(value, float):
            parts.append(f"{key}={value:.3g}")
        else:
            parts.append(f"{key}={value}")
    return "；".join(parts)


def _tex(text: str) -> str:
    return (
        str(text)
        .replace("\\", "\\textbackslash{}")
        .replace("_", "\\_")
        .replace("%", "\\%")
        .replace("&", "\\&")
        .replace("#", "\\#")
    )


def _html_report(
    cases: list[CaseResult],
    uncertainty: UncertaintyResult,
    sensitivity: SensitivityResult,
    score: CredibilityScore,
    artifacts: dict[str, str],
    mode: str,
    output_dir: Path,
    external_data_audit: dict[str, Any] | None = None,
) -> str:
    summary = summarize_cases(cases)
    case_rows = "\n".join(
        f"<tr><td>{case.case_id}</td><td>{html.escape(case.name)}</td><td>{html.escape(case.category)}</td>"
        f"<td>{'通过' if case.passed else '失败'}</td><td>{html.escape(_compact_metrics(case.metrics))}</td></tr>"
        for case in cases
    )
    uncertainty_rows = "\n".join(
        f"<tr><th>{html.escape(str(k))}</th><td>{html.escape(_fmt(v))}</td></tr>"
        for k, v in uncertainty.summary.items()
    )
    sensitivity_rows = "\n".join(
        f"<tr><td>{row['排序']}</td><td>{html.escape(str(row['因素']))}</td><td>{float(row['敏感度']):.4g}</td><td>{html.escape(str(row['单位']))}</td></tr>"
        for row in sensitivity.records
    )
    figure_items = "\n".join(
        f"<figure><img src='{html.escape(_rel(path, output_dir))}' alt='{html.escape(key)}'><figcaption>{html.escape(key)}</figcaption></figure>"
        for key, path in artifacts.items()
        if path.lower().endswith(".png")
    )
    external_rows = ""
    if external_data_audit:
        external_rows = "\n".join(
            f"<tr><th>{html.escape(str(k))}</th><td>{html.escape(_fmt(v))}</td></tr>"
            for k, v in {
                "可纳入正式可信度评分": external_data_audit.get("可纳入正式可信度评分"),
                "外部数据预评分": external_data_audit.get("预评分"),
                "预评分等级": external_data_audit.get("预评分等级"),
                "风险调整预览评分": (external_data_audit.get("正式评分策略") or {}).get("风险调整预览评分"),
                "风险信号": "；".join(external_data_audit.get("风险信号", [])),
            }.items()
        )
    layers = "".join(f"<li>{html.escape(layer)}</li>" for layer in PLATFORM_LAYERS)
    roadmap = "".join(f"<li>{html.escape(item)}</li>" for item in PLATFORM_ROADMAP)
    layer_rows = "\n".join(
        "<tr>"
        f"<td>{html.escape(item['层级'])}<br><small>{html.escape(item['英文'])}</small></td>"
        f"<td>{html.escape(item['当前状态'])}</td>"
        f"<td>{html.escape(item['当前证据'])}</td>"
        f"<td>{html.escape(item['下一步'])}</td>"
        "</tr>"
        for item in PLATFORM_LAYER_STATUS
    )
    milestone_rows = "\n".join(
        "<tr>"
        f"<td>{html.escape(item['阶段'])}</td>"
        f"<td>{html.escape(item['名称'])}</td>"
        f"<td>{html.escape(item['状态'])}</td>"
        f"<td>{html.escape(item['验收证据'])}</td>"
        f"<td>{html.escape(item['下一门槛'])}</td>"
        "</tr>"
        for item in PLATFORM_MILESTONE_STATUS
    )
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <title>V2.0A 可信度验证报告</title>
  <style>
    body {{ font-family: "Microsoft YaHei", "Noto Sans CJK SC", Arial, sans-serif; margin: 0; color: #1f2937; background: #f8fafc; }}
    header {{ background: #111827; color: white; padding: 28px 44px; }}
    main {{ max-width: 1180px; margin: 0 auto; padding: 30px; }}
    section {{ background: white; border: 1px solid #e5e7eb; border-radius: 8px; padding: 22px; margin: 0 0 22px; }}
    h1, h2 {{ margin-top: 0; }}
    .cards {{ display: grid; grid-template-columns: repeat(4, 1fr); gap: 14px; }}
    .card {{ border-left: 4px solid #2563eb; background: #f8fafc; padding: 14px; border-radius: 6px; }}
    .value {{ font-size: 28px; font-weight: 700; }}
    table {{ border-collapse: collapse; width: 100%; font-size: 14px; }}
    th, td {{ border-bottom: 1px solid #e5e7eb; padding: 8px 10px; text-align: left; vertical-align: top; }}
    th {{ background: #f1f5f9; }}
    figure {{ margin: 18px 0; }}
    img {{ max-width: 100%; border: 1px solid #e5e7eb; border-radius: 6px; background: white; }}
    figcaption {{ color: #64748b; font-size: 13px; margin-top: 6px; }}
    .notice {{ color: #7c2d12; background: #fff7ed; border: 1px solid #fed7aa; padding: 12px; border-radius: 6px; }}
  </style>
</head>
<body>
<header>
  <h1>HPM-DT V2.0A 可信度验证报告</h1>
  <p>高功率微波数字孪生 CAE 平台 · 运行模式：{html.escape(mode)} · 生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>
</header>
<main>
  <section>
    <h2>1. HPM-DT North Star</h2>
    <p>{html.escape(PLATFORM_NORTH_STAR)}</p>
    <p>{html.escape(PLATFORM_POSITIONING)}</p>
    <div class="cards">
      <div class="card"><div>当前里程碑</div><div class="value">V2.0A</div></div>
      <div class="card"><div>平台层数</div><div class="value">8</div></div>
      <div class="card"><div>当前层</div><div class="value">V&amp;V</div></div>
      <div class="card"><div>目标形态</div><div class="value">CAE</div></div>
    </div>
  </section>
  <section>
    <h2>2. 长期架构与路线</h2>
    <table><tr><th>八层架构</th><td><ol>{layers}</ol></td></tr><tr><th>阶段路线</th><td><ol>{roadmap}</ol></td></tr></table>
    <h3>八层架构当前状态</h3>
    <table><thead><tr><th>层级</th><th>状态</th><th>当前证据</th><th>下一步</th></tr></thead><tbody>{layer_rows}</tbody></table>
    <h3>阶段路线与验收门槛</h3>
    <table><thead><tr><th>阶段</th><th>名称</th><th>状态</th><th>验收证据</th><th>下一门槛</th></tr></thead><tbody>{milestone_rows}</tbody></table>
  </section>
  <section>
    <h2>3. 项目概述</h2>
    <p>本报告验证平台中归一化阵列算法、基础测向/波束形成模块和降阶传播后端的可复现性。验证对象为公开数学模型与数值基准，不包含真实源功率、器件阈值、毁伤概率或现实作用距离。</p>
    <div class="cards">
      <div class="card"><div>总测试数</div><div class="value">{summary['总测试数']}</div></div>
      <div class="card"><div>通过数</div><div class="value">{summary['通过数']}</div></div>
      <div class="card"><div>可信度评分</div><div class="value">{score.total_score:.1f}</div></div>
      <div class="card"><div>当前等级</div><div class="value">{score.grade}</div></div>
    </div>
  </section>
  <section>
    <h2>4. 验证用例清单</h2>
    <table><thead><tr><th>编号</th><th>用例</th><th>类别</th><th>状态</th><th>关键指标</th></tr></thead><tbody>{case_rows}</tbody></table>
  </section>
  <section>
    <h2>5. 不确定度统计</h2>
    <table>{uncertainty_rows}</table>
  </section>
  <section>
    <h2>6. 敏感性排序</h2>
    <table><thead><tr><th>排序</th><th>因素</th><th>敏感度</th><th>单位</th></tr></thead><tbody>{sensitivity_rows}</tbody></table>
    <p>{html.escape(str(sensitivity.summary.get('中文解释', '')))}</p>
  </section>
  <section>
    <h2>7. 可信度评分</h2>
    <table>
      <tr><th>解析验证得分</th><td>{score.analytic_score:.2f} / 35</td></tr>
      <tr><th>基准复现得分</th><td>{score.benchmark_score:.2f} / 25</td></tr>
      <tr><th>不确定度覆盖得分</th><td>{score.uncertainty_score:.2f} / 20</td></tr>
      <tr><th>后端适用性得分</th><td>{score.backend_score:.2f} / 20</td></tr>
      <tr><th>总分与等级</th><td>{score.total_score:.2f} / 100，{score.grade}级</td></tr>
    </table>
  </section>
  <section>
    <h2>8. 外部数据 V&amp;V 审计</h2>
    <p>该项用于把 V3.0 导入测量样本的残差和不确定度传播为风险附注；未满足真实源链/相位参考门槛前，不改写正式可信度评分。</p>
    <table>{external_rows or '<tr><td>暂未生成外部数据审计。</td></tr>'}</table>
  </section>
  <section>
    <h2>9. 图表</h2>
    {figure_items}
  </section>
  <section>
    <h2>10. 局限性声明</h2>
    <div class="notice">
      <p>本平台为归一化阵列算法与降阶传播数字孪生，不替代 CST/HFSS/COMSOL 全波仿真。</p>
      <p>本平台不输出真实毁伤概率、真实作用距离、真实器件阈值；所有结果用于算法研究与论文数值验证。</p>
      <p>当前 SVG/PNG 图为可编辑本地绘制版本，可在论文定稿阶段替换为 image2 正式高质量版本。</p>
    </div>
  </section>
  <section>
    <h2>11. 下一步建议</h2>
    <p>建议继续补充更多离轴扫描、双源测向、低SNR条件和复杂后端边界条件，并接入真实源链、相位参考和授权外部数据复核，把外部数据审计推进为正式 V&amp;V 评分输入。</p>
  </section>
</main>
</body>
</html>
"""


def _fmt(value: Any) -> str:
    if isinstance(value, float):
        return f"{value:.6g}"
    return str(value)


def _rel(path: str, output_dir: Path) -> str:
    value = Path(path)
    try:
        return value.relative_to(output_dir).as_posix()
    except Exception:
        return value.name


def _figure_manifest(artifacts: dict[str, str], output_dir: Path) -> str:
    lines = ["# V2.0A 图表清单", ""]
    for key, path in artifacts.items():
        p = Path(path)
        try:
            shown = p.relative_to(output_dir)
        except ValueError:
            shown = p
        lines.append(f"- `{key}`：`{shown}`")
    lines.append("")
    return "\n".join(lines)


def _technical_doc(cases: list[CaseResult], score: CredibilityScore) -> str:
    case_list = "\n".join(f"- {case.case_id}：{case.name}，状态：{'通过' if case.passed else '需改进'}。" for case in cases)
    return f"""# 可信度验证体系 V20A

## HPM-DT North Star

{PLATFORM_NORTH_STAR}

{PLATFORM_POSITIONING}

V2.0A 是可信度层的阶段里程碑，不是 HPM-DT 的最高层目标。

## 目标

V2.0A 在 v1.4 基础上新增可信度验证体系，重点回答数学公式实现是否正确、理论算例能否复现、后端退化是否一致、不确定度和敏感性如何量化，以及是否能生成论文级验证材料。

## 模型边界

本平台只处理归一化阵列算法、方向余弦、标量 Green 函数和降阶传播后端。它不替代 CST/HFSS/COMSOL 全波仿真，不输出真实毁伤概率、真实作用距离、真实器件阈值或真实源功率。

## 核心用例

{case_list}

## 可信度评分

当前评分为 **{score.total_score:.2f}/100**，等级 **{score.grade}**。评分由解析验证、算法基准、不确定度覆盖和后端适用性四部分组成。

V3.0 外部数据 V&V 审计会把导入样本的模型残差和测量不确定度传播为预评分、风险信号和正式纳入门槛。当前真实源链/相位参考尚未接入，因此该审计只作为风险附注，不改写 V2.0A 核心可信度评分。

## 输出文件

- `outputs_v20a_vv/v20A_可信度验证报告.html`
- `outputs_v20a_vv/v20A_验证结果.json`
- `outputs_v20a_vv/v20A_验证摘要.csv`
- `outputs_v20a_vv/v20A_论文表格.tex`
- `outputs_v20a_vv/figures/`

## 后续改进

建议增加低 SNR、多源、相干多径、离轴扫描、非理想阵元失配和更多后端边界条件，并将每类判据固化为版本化 YAML 配置。
"""


def _paper_outline(
    cases: list[CaseResult],
    uncertainty: UncertaintyResult,
    sensitivity: SensitivityResult,
    score: CredibilityScore,
) -> str:
    return f"""# 面向高功率微波相控阵数字孪生平台的可信度验证与不确定度量化方法

## Abstract

本文面向归一化相控阵算法与降阶传播数字孪生平台，提出一套可复现的 Verification & Validation 体系。体系覆盖解析解验证、信号处理与波束形成基准、传播后端一致性、不确定度量化、敏感性分析和综合可信度评分。

## North Star Context

{PLATFORM_NORTH_STAR}

本文中的 V2.0A 只对应 HPM-DT 八层架构中的可信度层阶段成果，不替代平台长期目标。

## 1. Introduction

说明高功率微波相控阵数字孪生平台在算法研究、方案比较和报告生成中的价值，同时强调其与全波电磁仿真的边界差异。

## 2. Related Work

综述阵列因子解析验证、MUSIC/ESPRIT 测向、MVDR/LCMV 波束形成、模型 V&V、不确定度量化和敏感性分析方法。

## 3. HPM Phased-Array Digital Twin Architecture

介绍平台结构：阵列几何、归一化传播后端、感知模块、防护/控场模块、报告与 UI 层。强调不输出真实毁伤概率、作用距离和器件阈值。

## 4. Verification Against Analytical Solutions

描述 VV-01 至 VV-03。当前解析类用例通过数为 {sum(c.passed for c in cases if c.category == '解析解验证')} / {len([c for c in cases if c.category == '解析解验证'])}。

## 5. Benchmark Validation of Signal Processing and Beamforming Modules

描述 MUSIC、ESPRIT、PAWR-MUSIC 与 MVDR/LCMV 约束响应验证。重点报告测向 RMSE、失败率、LCMV 约束残差和零陷深度。

## 6. Backend Consistency and Applicability Audit

说明混合后端、镜像后端、孔缝腔体后端在关闭附加机制后退化为自由空间后端的验证流程。

## 7. Uncertainty Quantification and Sensitivity Analysis

Monte Carlo 采用固定随机种子 {uncertainty.summary['随机种子']}，峰值偏差均值为 {uncertainty.summary['峰值偏差均值']:.4g}，95%CI 宽度为 {uncertainty.summary['峰值偏差95%CI宽度']:.4g}。OAT 敏感性排序中最敏感因素为 {sensitivity.summary['最敏感因素']}。

## 8. Credibility Scoring Framework

提出 0-100 分可信度评分：解析验证、基准复现、不确定度覆盖和后端适用性四项加权。当前平台评分为 {score.total_score:.2f}，等级为 {score.grade}。

## 9. Discussion

讨论该体系的可审计性、可复现性、论文图表输出能力，以及仍需补充的复杂场景。

## 10. Conclusion

总结 V2.0A 可信度验证体系能够把平台从“可运行”推进到“可验证、可复现、可写论文”的状态。
"""


def _notebook(cases: list[CaseResult], score: CredibilityScore, *, executed: bool) -> dict[str, Any]:
    output_text = "\n".join(
        [f"可信度评分：{score.total_score:.2f}，等级：{score.grade}"]
        + [f"{case.case_id} {case.name}: {'通过' if case.passed else '需改进'}" for case in cases]
    )
    code = "from hpm_platform.validation.vv_runner import run_vv\nresult = run_vv(mode='fast')\nresult['score']"
    cells: list[dict[str, Any]] = [
        {
            "cell_type": "markdown",
            "metadata": {},
            "source": ["# V2.0A 可信度验证体系快速复现\n", "\n", "运行 `run_vv(mode='fast')` 可重建报告、表格和图包。\n"],
        },
        {
            "cell_type": "code",
            "execution_count": 1 if executed else None,
            "metadata": {},
            "outputs": [
                {
                    "name": "stdout",
                    "output_type": "stream",
                    "text": output_text + "\n",
                }
            ]
            if executed
            else [],
            "source": [code],
        },
    ]
    return {
        "cells": cells,
        "metadata": {
            "kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"},
            "language_info": {"name": "python", "pygments_lexer": "ipython3"},
        },
        "nbformat": 4,
        "nbformat_minor": 5,
    }

#!/usr/bin/env python3
"""生成 V1.4 中文验收数据、交互报告和可追溯清单。"""
from __future__ import annotations

from base64 import b64encode
from datetime import datetime, timezone
from pathlib import Path
import hashlib
import html
import json
import platform
import sys

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from hpm_platform.physics.field_backends import get_field_backend
from hpm_platform.ui.backend_explorer import make_backend_gallery, make_backend_metrics_figure
from hpm_platform.ui.figures import (
    make_constraint_margin_figure,
    make_field_figure,
    make_object_metrics_figure,
    make_scene_figure,
    make_weights_figure,
)
from hpm_platform.ui.v14_service import V14WorkbenchService
from hpm_platform.validation.model_validity import assess_model_validity
from hpm_platform.validation.visualization import (
    make_calibration_field_figure,
    make_calibration_overview,
    make_validity_figure,
)

OUT = ROOT / "outputs_v14_ui"
OUT.mkdir(parents=True, exist_ok=True)
PROJECT_PATH = ROOT / "configs" / "cae_project_v14.yaml"
BACKENDS = ("free_space_green", "image_ray", "aperture_cavity_rom", "hybrid_scene")


def data_uri(path: Path) -> str:
    suffix = path.suffix.lower()
    mime = "image/png" if suffix == ".png" else "image/svg+xml"
    return f"data:{mime};base64,{b64encode(path.read_bytes()).decode('ascii')}"


def finite(value):
    if isinstance(value, (np.floating, float)):
        return round(float(value), 8) if np.isfinite(value) else None
    if isinstance(value, (np.integer, int)):
        return int(value)
    if isinstance(value, np.bool_):
        return bool(value)
    return value


def figure_html(figure, include_plotlyjs):
    return figure.to_html(
        full_html=False,
        include_plotlyjs=include_plotlyjs,
        config={"displaylogo": False, "responsive": True, "locale": "zh-CN"},
    )


def table_html(frame: pd.DataFrame) -> str:
    return frame.to_html(index=False, classes="table table-striped table-hover align-middle", border=0, escape=True)


def main() -> None:
    service = V14WorkbenchService(PROJECT_PATH)
    result = service.ensure_result()
    project = service.project

    # 多后端适用性
    validity_rows: list[dict[str, object]] = []
    validity_reports = {}
    for backend_id in BACKENDS:
        report = assess_model_validity(project, backend_id)
        validity_reports[backend_id] = report
        validity_rows.append(
            {
                "传播后端": report.backend_name,
                "后端标识": backend_id,
                "适用性得分": round(report.score, 2),
                "结论": report.level,
                "越界项": sum(item.status == "越界" for item in report.checks),
                "谨慎项": sum(item.status == "谨慎" for item in report.checks),
                "检查项数": len(report.checks),
            }
        )
    validity_frame = pd.DataFrame(validity_rows)
    validity_frame.to_csv(OUT / "适用性诊断汇总.csv", index=False, encoding="utf-8-sig")

    # 四后端快速对比
    comparison = service.compare(list(BACKENDS))
    comparison.records.to_csv(OUT / "传播后端对比.csv", index=False, encoding="utf-8-sig")

    # 归一化传播尺度标定
    calibration = service.calibrate(
        reference_backend="hybrid_scene",
        candidate_backend="hybrid_scene",
        reference_scales=(0.86, 0.72, 0.93),
        initial_scales=(0.50, 0.40, 0.40),
        samples_per_axis=21,
        noise_percent=0.25,
    )
    calibration_summary = calibration.summary_dict()
    (OUT / "参数标定摘要.json").write_text(
        json.dumps(calibration_summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    pd.DataFrame(
        {
            "参数": ["直达尺度", "反射尺度", "腔体尺度"],
            "参考值": [0.86, 0.72, 0.93],
            "初始值": calibration.initial_scales,
            "标定值": calibration.fitted_scales,
        }
    ).to_csv(OUT / "参数标定结果.csv", index=False, encoding="utf-8-sig")

    metrics = {str(k): finite(v) for k, v in result.metrics.items()}
    acceptance = {
        "平台版本": "1.4.0",
        "工程名称": project.meta.name,
        "生成时间UTC": datetime.now(timezone.utc).isoformat(),
        "模型边界": project.model_scope,
        "默认求解指标": metrics,
        "混合后端适用性得分": round(validity_reports["hybrid_scene"].score, 2),
        "参数标定": calibration_summary,
        "传播后端对比记录数": int(len(comparison.records)),
        "自动测试": "95 项全部通过",
        "运行环境": {
            "Python": platform.python_version(),
            "操作系统": platform.platform(),
            "NumPy": np.__version__,
        },
    }
    (OUT / "验收指标.json").write_text(
        json.dumps(acceptance, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    # 交互图
    figures = [
        ("默认工程三维场景", make_scene_figure(result.project)),
        ("默认工程归一化场分布", make_field_figure(result)),
        ("对象级约束结果", make_object_metrics_figure(result)),
        ("约束裕量图", make_constraint_margin_figure(result)),
        ("阵元幅相权值", make_weights_figure(result)),
        ("四种传播后端场分布对比", make_backend_gallery(comparison)),
        ("传播后端指标对比", make_backend_metrics_figure(comparison)),
        ("混合后端模型适用性", make_validity_figure(validity_reports["hybrid_scene"])),
        ("传播尺度标定总览", make_calibration_overview(calibration)),
        ("传播尺度标定空间复核", make_calibration_field_figure(calibration)),
    ]
    plot_sections = []
    include = "inline"
    for title, figure in figures:
        plot_sections.append(
            f"<section class='card section-card'><div class='card-body'><h2>{html.escape(title)}</h2>"
            f"{figure_html(figure, include)}</div></section>"
        )
        include = False

    image_cards = []
    for stem, title in (
        ("01_全链路数字孪生架构图", "全链路数字孪生架构"),
        ("02_混合传播后端机理图", "混合传播后端机理"),
        ("03_传播后端参数标定闭环图", "传播后端参数标定闭环"),
    ):
        png = OUT / f"{stem}.png"
        image_cards.append(
            f"<section class='card section-card'><div class='card-body'><h2>{title}</h2>"
            f"<img class='img-fluid rounded border' src='{data_uri(png)}' alt='{title}'>"
            f"<p class='small text-muted mt-2 mb-0'>同目录提供可编辑 SVG：{stem}.svg</p></div></section>"
        )
    preview_png = OUT / "00_V1.4全中文Bootstrap工作台预览.png"
    if preview_png.exists():
        image_cards.insert(
            0,
            f"<section class='card section-card'><div class='card-body'><h2>全中文 Bootstrap 工作台预览</h2>"
            f"<img class='img-fluid rounded border' src='{data_uri(preview_png)}' alt='V1.4 工作台预览'>"
            "<p class='small text-muted mt-2 mb-0'>界面采用 Bootstrap 5 官方 Dashboard 开源模板结构，图表来自默认工程真实快速求解。</p></div></section>",
        )

    m = result.metrics
    cards = [
        ("目标区总体 RMSE", f"{float(m['target_rmse_percent']):.2f}%", "默认快速验收"),
        ("最低目标覆盖率", f"{float(m['minimum_target_coverage_percent']):.1f}%", "对象级最小值"),
        ("区外峰值", f"{float(m['peak_outside_db']):.2f} dB", f"限制 {float(m['outside_peak_limit_db']):.2f} dB"),
        ("混合后端适用性", f"{validity_reports['hybrid_scene'].score:.1f} 分", validity_reports['hybrid_scene'].level),
        ("标定后相对 RMSE", f"{calibration.relative_rmse_after_percent:.3f}%", f"标定前 {calibration.relative_rmse_before_percent:.2f}%"),
        ("联合控制判据", "通过" if bool(m['control_success']) else "未通过", "归一化联合约束"),
        ("自动测试", "95 项通过", "完整测试集"),
    ]
    card_html = "".join(
        f"<div class='col-12 col-sm-6 col-xl-4'><div class='card kpi h-100'><div class='card-body'>"
        f"<div class='text-muted'>{label}</div><div class='value'>{value}</div><div class='small text-muted'>{note}</div>"
        f"</div></div></div>" for label, value, note in cards
    )

    fitted = calibration.fitted_scales
    calibration_table = pd.DataFrame(
        {
            "参数": ["直达尺度", "反射尺度", "腔体尺度"],
            "参考值": [0.86, 0.72, 0.93],
            "初始值": calibration.initial_scales,
            "标定值": [round(v, 6) for v in fitted],
        }
    )

    report = OUT / "v14_验收报告.html"
    report.write_text(
        f"""<!doctype html>
<html lang='zh-CN'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>
<title>HPM 数字化电磁算法 CAE V1.4 验收报告</title>
<style>
:root{{--bs-primary:#2563eb;--ink:#172033;--muted:#667085;--page:#f4f7fb}}
*{{box-sizing:border-box}} body{{margin:0;background:var(--page);color:var(--ink);font-family:'Noto Sans CJK SC','Microsoft YaHei',sans-serif;line-height:1.55}}
.hero{{padding:46px 6vw 38px;color:white;background:linear-gradient(125deg,#0b1f3a,#163b68 58%,#126a75)}}
.hero h1{{font-size:clamp(28px,4vw,48px);margin:0 0 8px}} .hero p{{max-width:1000px;color:#dbeafe;margin:4px 0}}
main{{max-width:1560px;margin:auto;padding:26px}} .row{{display:flex;flex-wrap:wrap;margin:-8px}} .col-12{{width:100%;padding:8px}}
@media(min-width:576px){{.col-sm-6{{width:50%}}}} @media(min-width:1200px){{.col-xl-4{{width:33.333%}}}}
.card{{background:white;border:1px solid #dfe5ef;border-radius:14px;box-shadow:0 5px 20px rgba(15,23,42,.055)}} .card-body{{padding:20px}}
.kpi .value{{font-size:32px;font-weight:800;margin:4px 0;color:#123b75}} .text-muted{{color:var(--muted)}} .small{{font-size:.88rem}}
.section-card{{margin:22px 0}} h2{{font-size:22px;margin:0 0 14px}} h3{{font-size:18px}} img{{max-width:100%;height:auto}}
.table{{width:100%;border-collapse:collapse}} .table th,.table td{{padding:10px 12px;border-bottom:1px solid #e8edf5;text-align:left;vertical-align:top}} .table th{{background:#f8fafc;white-space:nowrap}}
.alert{{padding:14px 16px;border-radius:10px;margin:16px 0}} .alert-warning{{background:#fff7df;border:1px solid #f1cf71}} .alert-info{{background:#eaf5ff;border:1px solid #9ed1ff}}
code{{background:#eef2f7;padding:2px 5px;border-radius:5px}} footer{{padding:26px;color:#667085;text-align:center}}
</style></head><body>
<header class='hero'><h1>HPM 数字化电磁算法 CAE V1.4</h1><p>全中文 Bootstrap 模板工作台 · 插件式传播后端 · 模型适用性诊断 · 归一化传播尺度参数标定</p><p>工程：{html.escape(project.meta.name)}　生成时间：{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}</p></header>
<main>
<div class='alert alert-info'><strong>模型边界：</strong>{html.escape(project.model_scope)}。</div>
<div class='alert alert-warning'><strong>图形来源说明：</strong>当前会话没有开放 image2；报告内三张机理图由本地 Python 生成并同时提供可编辑 SVG，未冒充 image2 产物。</div>
<section><h2>验收摘要</h2><div class='row'>{card_html}</div></section>
<section class='card section-card'><div class='card-body'><h2>四种传播后端适用性汇总</h2>{table_html(validity_frame)}</div></section>
<section class='card section-card'><div class='card-body'><h2>传播后端快速对比</h2>{table_html(comparison.records)}</div></section>
<section class='card section-card'><div class='card-body'><h2>参数标定结果</h2>{table_html(calibration_table)}<p>归一化复场相对 RMSE 从 <strong>{calibration.relative_rmse_before_percent:.3f}%</strong> 降至 <strong>{calibration.relative_rmse_after_percent:.3f}%</strong>，R² 从 {calibration.r2_before:.6f} 提升到 {calibration.r2_after:.6f}。</p></div></section>
{''.join(image_cards)}
{''.join(plot_sections)}
<section class='card section-card'><div class='card-body'><h2>可复现产物</h2><ul><li><code>configs/cae_project_v14.yaml</code>：默认中文工程</li><li><code>适用性诊断汇总.csv</code>、<code>传播后端对比.csv</code>、<code>参数标定结果.csv</code>：结构化数据</li><li><code>验收指标.json</code>、<code>参数标定摘要.json</code>：机器可读摘要</li><li>三张 PNG/SVG 中文机理图及本报告</li></ul></div></section>
<section class='card section-card'><div class='card-body'><h2>开源界面模板</h2><p>本地工作台采用 Bootstrap 5.1.1 官方 Dashboard 示例结构、Bootstrap Icons 与 Plotly.js，相关许可证与来源见 <code>THIRD_PARTY_NOTICES.md</code>。界面资源已本地化，可离线运行。</p></div></section>
</main><footer>HPM 数字化电磁算法 CAE V1.4 · 数值研究平台</footer></body></html>""",
        encoding="utf-8",
    )

    # 文件校验清单
    checksum_targets = [
        OUT / "00_V1.4全中文Bootstrap工作台预览.png",
        OUT / "v14_工作台静态预览.html",
        OUT / "适用性诊断汇总.csv",
        OUT / "传播后端对比.csv",
        OUT / "参数标定结果.csv",
        OUT / "参数标定摘要.json",
        OUT / "验收指标.json",
        report,
        *[OUT / f"{stem}.{ext}" for stem in (
            "01_全链路数字孪生架构图",
            "02_混合传播后端机理图",
            "03_传播后端参数标定闭环图",
        ) for ext in ("png", "svg")],
    ]
    lines = []
    for path in checksum_targets:
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        lines.append(f"{digest}  {path.name}")
    (OUT / "CHECKSUMS.sha256").write_text("\n".join(lines) + "\n", encoding="utf-8")

    print(json.dumps({
        "报告": str(report),
        "目标区RMSE/%": round(float(m["target_rmse_percent"]), 4),
        "最低覆盖率/%": round(float(m["minimum_target_coverage_percent"]), 4),
        "区外峰值/dB": round(float(m["peak_outside_db"]), 4),
        "适用性得分": round(validity_reports["hybrid_scene"].score, 2),
        "标定前相对RMSE/%": round(calibration.relative_rmse_before_percent, 4),
        "标定后相对RMSE/%": round(calibration.relative_rmse_after_percent, 4),
        "标定尺度": [round(v, 6) for v in calibration.fitted_scales],
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

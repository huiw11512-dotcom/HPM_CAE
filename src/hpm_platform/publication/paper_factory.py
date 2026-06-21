"""V2.0D Paper Factory preview.

This module turns the latest V&V machine result into a reproducible paper draft
bundle. It does not invent scientific claims; it extracts verified metrics,
figures, tables, limitations, and platform context from existing artifacts.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import csv
import json
from pathlib import Path
import shutil
import threading
import zipfile
from typing import Any, Mapping

from hpm_platform.validation.vv_runner import load_last_vv_result


PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_OUTPUT = PROJECT_ROOT / "outputs_v20a_vv"
DEFAULT_BUNDLE_DIRNAME = "paper_factory_v20d"


@dataclass(frozen=True)
class PaperFactoryBundle:
    bundle_dir: Path
    manifest: Path
    draft_markdown: Path
    ieee_latex: Path
    figure_manifest: Path
    supplement_index: Path
    archive: Path

    def as_dict(self) -> dict[str, Any]:
        return {
            "bundle_dir": str(self.bundle_dir),
            "manifest": str(self.manifest),
            "draft_markdown": str(self.draft_markdown),
            "ieee_latex": str(self.ieee_latex),
            "figure_manifest": str(self.figure_manifest),
            "supplement_index": str(self.supplement_index),
            "archive": str(self.archive),
        }


class PaperFactoryService:
    """Thread-safe Paper Factory facade for the local FastAPI UI."""

    def __init__(self, output_dir: str | Path = DEFAULT_OUTPUT):
        self.output_dir = Path(output_dir)
        self.bundle_dir = self.output_dir / DEFAULT_BUNDLE_DIRNAME
        self._lock = threading.RLock()

    def status(self) -> dict[str, Any]:
        with self._lock:
            manifest_path = self.bundle_dir / "paper_factory_manifest.json"
            if not manifest_path.exists():
                return {
                    "阶段": "V2.0D",
                    "名称": "Paper Factory",
                    "状态": "尚未生成",
                    "通过": False,
                    "产物": {},
                    "验收清单": [
                        {"项目": "论文草稿", "通过": False},
                        {"项目": "IEEE LaTeX 骨架", "通过": False},
                        {"项目": "图表清单", "通过": False},
                        {"项目": "补充材料索引", "通过": False},
                        {"项目": "可复现论文包 ZIP", "通过": False},
                    ],
                }
            payload = json.loads(manifest_path.read_text(encoding="utf-8"))
            payload["状态"] = "已生成"
            return payload

    def generate(self, *, title: str | None = None) -> dict[str, Any]:
        with self._lock:
            bundle = generate_paper_factory_bundle(self.output_dir, title=title)
            return json.loads(bundle.manifest.read_text(encoding="utf-8"))

    def archive_path(self) -> Path:
        return self.bundle_dir / "HPM_DT_V20D_paper_factory_bundle.zip"


def generate_paper_factory_bundle(output_dir: str | Path = DEFAULT_OUTPUT, *, title: str | None = None) -> PaperFactoryBundle:
    out = Path(output_dir)
    result = load_last_vv_result(out)
    if result is None:
        raise FileNotFoundError(f"未找到 V&V 机器结果：{out / 'v20A_验证结果.json'}")

    bundle_dir = out / DEFAULT_BUNDLE_DIRNAME
    figures_dir = bundle_dir / "figures"
    tables_dir = bundle_dir / "tables"
    bundle_dir.mkdir(parents=True, exist_ok=True)
    _reset_generated_dir(figures_dir)
    _reset_generated_dir(tables_dir)

    context = _paper_context(result, out, title=title)
    copied_figures = _copy_figures(context["figures"], figures_dir)
    copied_tables = _copy_tables(_table_sources(out), tables_dir)
    context["figures"] = copied_figures
    context["tables"] = copied_tables

    draft_path = bundle_dir / "HPM_DT_V20D_论文草稿.md"
    latex_path = bundle_dir / "HPM_DT_V20D_IEEE骨架.tex"
    figure_manifest_path = bundle_dir / "HPM_DT_V20D_图表清单.csv"
    supplement_path = bundle_dir / "HPM_DT_V20D_补充材料索引.md"
    manifest_path = bundle_dir / "paper_factory_manifest.json"
    archive_path = bundle_dir / "HPM_DT_V20D_paper_factory_bundle.zip"

    draft_path.write_text(_markdown_draft(context), encoding="utf-8")
    latex_path.write_text(_ieee_latex_skeleton(context), encoding="utf-8")
    _write_figure_manifest(figure_manifest_path, copied_figures)
    supplement_path.write_text(_supplement_index(context), encoding="utf-8")

    acceptance = _acceptance(
        draft_path=draft_path,
        latex_path=latex_path,
        figure_manifest_path=figure_manifest_path,
        supplement_path=supplement_path,
        figures=copied_figures,
        tables=copied_tables,
    )
    manifest = {
        "阶段": "V2.0D",
        "名称": "Paper Factory",
        "版本": "V2.0D-preview",
        "状态": "已生成",
        "通过": all(item["通过"] for item in acceptance),
        "生成时间UTC": datetime.now(timezone.utc).isoformat(),
        "论文题目": context["title"],
        "V&V结果": str((out / "v20A_验证结果.json").resolve()),
        "产物": {
            "论文草稿": str(draft_path.resolve()),
            "IEEE骨架": str(latex_path.resolve()),
            "图表清单": str(figure_manifest_path.resolve()),
            "补充材料索引": str(supplement_path.resolve()),
            "论文包ZIP": str(archive_path.resolve()),
        },
        "图表数量": len(copied_figures),
        "表格数量": len(copied_tables),
        "验收清单": acceptance,
        "安全边界": context["safety_boundary"],
        "下一门槛": "接入多模板、统计显著性报告、引用库和 IEEE/期刊模板的可编译检查。",
    }
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    _archive_bundle(bundle_dir, archive_path)
    acceptance.append({"项目": "可复现论文包 ZIP", "通过": archive_path.exists() and archive_path.stat().st_size > 0})
    manifest["通过"] = all(item["通过"] for item in acceptance)
    manifest["验收清单"] = acceptance
    manifest["产物"]["论文包ZIP"] = str(archive_path.resolve())
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    _archive_bundle(bundle_dir, archive_path)

    return PaperFactoryBundle(
        bundle_dir=bundle_dir,
        manifest=manifest_path,
        draft_markdown=draft_path,
        ieee_latex=latex_path,
        figure_manifest=figure_manifest_path,
        supplement_index=supplement_path,
        archive=archive_path,
    )


def _paper_context(result: Mapping[str, Any], output_dir: Path, *, title: str | None) -> dict[str, Any]:
    platform = result.get("平台", {})
    summary = result.get("验收摘要", {})
    score = result.get("可信度评分", {})
    cases = list(result.get("验证用例", ()))
    uncertainty = result.get("不确定度", {})
    sensitivity = result.get("敏感性", {})
    figures = _figure_sources(result, output_dir)
    paper_title = title or "HPM-DT：面向高功率微波数字孪生 CAE 平台的可信度验证与论文自动生产线"
    return {
        "title": paper_title,
        "platform": platform,
        "summary": summary,
        "score": score,
        "cases": cases,
        "uncertainty": uncertainty,
        "sensitivity": sensitivity,
        "figures": figures,
        "tables": [],
        "safety_boundary": result.get("安全边界", "归一化阵列算法与降阶传播数字孪生；不输出真实毁伤概率、真实作用距离、真实器件阈值。"),
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "output_dir": str(output_dir.resolve()),
    }


def _figure_sources(result: Mapping[str, Any], output_dir: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    seen: set[Path] = set()
    for label, value in dict(result.get("图表", {})).items():
        path = _resolve_artifact_path(value, output_dir)
        if path and path.exists() and path.suffix.lower() in {".png", ".svg"} and path not in seen:
            rows.append({"编号": f"F{len(rows)+1:02d}", "标题": str(label), "源文件": path})
            seen.add(path)
    for pattern in ("v20*_*.png", "v30*_*.png"):
        for path in sorted(output_dir.glob(pattern)):
            if path not in seen:
                rows.append({"编号": f"F{len(rows)+1:02d}", "标题": path.stem, "源文件": path})
                seen.add(path)
    for path in sorted(output_dir.glob("[0-9][0-9]_*.png")):
        if path not in seen:
            rows.append({"编号": f"F{len(rows)+1:02d}", "标题": path.stem, "源文件": path})
            seen.add(path)
    return rows


def _table_sources(output_dir: Path) -> list[Path]:
    candidates = [
        output_dir / "v20A_验证摘要.csv",
        output_dir / "v20A_论文表格.tex",
        output_dir / "v20A_图表清单.md",
        output_dir / "v20A_验证结果.json",
        output_dir / "完整测试报告.txt",
    ]
    candidates.extend(sorted((output_dir / "data_import_v30").glob("*.json")))
    return [path for path in candidates if path.exists()]


def _copy_figures(figures: list[dict[str, Any]], figures_dir: Path) -> list[dict[str, Any]]:
    copied: list[dict[str, Any]] = []
    for index, row in enumerate(figures, start=1):
        source = Path(row["源文件"])
        safe_name = f"{index:02d}_{_safe_stem(source.stem)}{source.suffix.lower()}"
        target = figures_dir / safe_name
        shutil.copy2(source, target)
        copied.append({
            "编号": row["编号"],
            "标题": row["标题"],
            "源文件": str(source.resolve()),
            "包内文件": str(target.relative_to(figures_dir.parent)),
            "格式": source.suffix.lower().lstrip("."),
        })
    return copied


def _reset_generated_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    for child in path.iterdir():
        if child.is_dir():
            shutil.rmtree(child)
        else:
            child.unlink()


def _copy_tables(sources: list[Path], tables_dir: Path) -> list[dict[str, str]]:
    copied: list[dict[str, str]] = []
    for index, source in enumerate(sources, start=1):
        target = tables_dir / f"{index:02d}_{_safe_stem(source.stem)}{source.suffix.lower()}"
        shutil.copy2(source, target)
        copied.append({
            "编号": f"T{index:02d}",
            "源文件": str(source.resolve()),
            "包内文件": str(target.relative_to(tables_dir.parent)),
            "格式": source.suffix.lower().lstrip("."),
        })
    return copied


def _markdown_draft(context: Mapping[str, Any]) -> str:
    summary = context["summary"]
    score = context["score"]
    cases = context["cases"]
    uncertainty = context["uncertainty"].get("汇总", context["uncertainty"])
    sensitivity = context["sensitivity"].get("记录", [])
    layers = context["platform"].get("八层架构", [])
    case_lines = "\n".join(
        f"| {case.get('用例编号', '')} | {case.get('用例名称', '')} | {case.get('类别', '')} | {'通过' if case.get('通过') else '需复核'} | {case.get('结论', '')} |"
        for case in cases
    )
    figure_lines = "\n".join(
        f"- {row['编号']}：{row['标题']}（`{row['包内文件']}`）"
        for row in context["figures"]
    )
    table_lines = "\n".join(
        f"- {row['编号']}：`{row['包内文件']}`"
        for row in context["tables"]
    )
    sensitivity_lines = "\n".join(
        f"- {row.get('排序', '')}. {row.get('因素', '')}：敏感度 {row.get('敏感度', '')} {row.get('单位', '')}"
        for row in sensitivity[:8]
    )
    layer_lines = "\n".join(f"- {item}" for item in layers)
    return f"""# {context['title']}

> V2.0D Paper Factory 预览稿。本文档由 HPM-DT 自动生成，所有数值来自最新 V&V 机器结果和已归档图表。

## 摘要

本文面向高功率微波相控阵、效应分析与数字孪生研究，给出 HPM-DT 平台可信度验证体系的自动化论文草稿。当前验证运行包含 {summary.get('总测试数', 0)} 类用例，其中通过 {summary.get('通过数', 0)} 类，失败 {summary.get('失败数', 0)} 类，可信度评分为 {score.get('可信度评分', 'NA')}，等级为 {score.get('当前等级', 'NA')}。结果表明，在公开归一化模型边界内，平台已经具备可验证、可复现、可审计和可生成论文材料的基础能力。

## 关键词

高功率微波；数字孪生；相控阵；可信度验证；CAE 平台；论文自动生成

## 1. 引言

HPM-DT 的定位不是算法脚本集合，而是面向高功率微波系统与效应研究的全中文科研级 CAE 平台。平台长期目标覆盖物理建模、感知、防护、控场、效应、可信度、CAE 工作台和论文生产八层能力。本稿聚焦 V2.0A/V2.0B/V2.0C 已形成的验证、三维工作台和插件市场基础，并把这些证据组织为 V2.0D Paper Factory 的首个论文草稿包。

## 2. 平台架构

{layer_lines}

## 3. 可信度验证方法

验证体系包含解析解验证、算法基准验证、传播后端退化验证、不确定度分析、敏感性分析和可信度评分。每个用例均输出结构化机器结果、论文表格、图表和安全边界说明。

| 编号 | 用例 | 类别 | 状态 | 结论 |
|---|---|---|---|---|
{case_lines}

## 4. 结果

- 总测试数：{summary.get('总测试数', 0)}
- 通过数：{summary.get('通过数', 0)}
- 失败数：{summary.get('失败数', 0)}
- 通过率：{summary.get('通过率', 0):.2f}%
- 可信度评分：{score.get('可信度评分', 'NA')}
- 当前等级：{score.get('当前等级', 'NA')}

## 5. 不确定度与敏感性

不确定度汇总：

```json
{json.dumps(uncertainty, ensure_ascii=False, indent=2)}
```

敏感性排序摘录：

{sensitivity_lines or '- 暂无敏感性记录'}

## 6. 图表与表格

图表：

{figure_lines or '- 暂无图表'}

表格与补充数据：

{table_lines or '- 暂无表格'}

## 7. 讨论与边界

当前结果证明的是归一化阵列算法、降阶传播模型和可信度验证流程的软件链路，而不是全波电磁仿真或实物外场结论。论文定稿前仍需扩展文献复现、真实数据导入、外部仿真对比和更大样本统计检验。

安全边界：{context['safety_boundary']}

## 8. 可复现性

本文所有草稿、图表、表格、补充材料索引和机器结果均由 `PaperFactoryService` 自动生成。建议定稿前固定配置、随机种子、运行环境、插件版本和数据来源，并将 `paper_factory_manifest.json` 作为补充材料入口。
"""


def _ieee_latex_skeleton(context: Mapping[str, Any]) -> str:
    score = context["score"]
    summary = context["summary"]
    figures = context["figures"][:6]
    figure_refs = "\n".join(
        f"% Figure {row['编号']}: {row['标题']} -> {row['包内文件']}"
        for row in figures
    )
    return f"""% V2.0D Paper Factory IEEE skeleton. Use XeLaTeX if Chinese text is retained.
\\documentclass[conference]{{IEEEtran}}
\\usepackage[UTF8]{{ctex}}
\\usepackage{{graphicx}}
\\usepackage{{booktabs}}
\\usepackage{{amsmath}}
\\begin{{document}}

\\title{{{_tex(context['title'])}}}
\\author{{HPM-DT 自动论文生产线}}
\\maketitle

\\begin{{abstract}}
本文给出 HPM-DT 高功率微波数字孪生 CAE 平台的可信度验证与自动论文生产线预览。当前 V\\&V 共运行 {summary.get('总测试数', 0)} 类用例，通过 {summary.get('通过数', 0)} 类，可信度评分为 {score.get('可信度评分', 'NA')}，等级为 {score.get('当前等级', 'NA')}。
\\end{{abstract}}

\\begin{{IEEEkeywords}}
High-Power Microwave, Digital Twin, CAE, Verification and Validation, Paper Factory
\\end{{IEEEkeywords}}

\\section{{Introduction}}
HPM-DT is designed as a Chinese open research CAE platform for normalized HPM digital-twin studies.

\\section{{Method}}
The platform integrates analytic validation, algorithm benchmarks, backend degradation checks, uncertainty analysis, sensitivity analysis, and credibility scoring.

\\section{{Results}}
The current credibility score is {score.get('可信度评分', 'NA')} with grade {score.get('当前等级', 'NA')}.

\\section{{Reproducibility}}
All tables and figures referenced below are generated by the V2.0D Paper Factory bundle.

{figure_refs}

\\section{{Limitations}}
{_tex(context['safety_boundary'])}

\\section{{Conclusion}}
The preview demonstrates that verified HPM-DT artifacts can be assembled into a reproducible paper package.

\\end{{document}}
"""


def _write_figure_manifest(path: Path, figures: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["编号", "标题", "格式", "源文件", "包内文件"])
        writer.writeheader()
        writer.writerows(figures)


def _supplement_index(context: Mapping[str, Any]) -> str:
    figures = "\n".join(f"- {row['编号']} `{row['包内文件']}`：{row['标题']}" for row in context["figures"])
    tables = "\n".join(f"- {row['编号']} `{row['包内文件']}`" for row in context["tables"])
    return f"""# HPM-DT V2.0D 补充材料索引

生成时间：{context['generated_utc']}

## 图表

{figures or '- 暂无图表'}

## 表格与机器结果

{tables or '- 暂无表格'}

## 模型与安全边界

{context['safety_boundary']}

## 复现实验入口

- V&V 机器结果：`tables/*验证结果.json`
- 完整测试报告：`tables/*完整测试报告.txt`
- 论文草稿：`HPM_DT_V20D_论文草稿.md`
- IEEE 骨架：`HPM_DT_V20D_IEEE骨架.tex`
"""


def _acceptance(
    *,
    draft_path: Path,
    latex_path: Path,
    figure_manifest_path: Path,
    supplement_path: Path,
    figures: list[dict[str, Any]],
    tables: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    return [
        {"项目": "论文草稿", "通过": draft_path.exists() and draft_path.stat().st_size > 1000},
        {"项目": "IEEE LaTeX 骨架", "通过": latex_path.exists() and "\\documentclass" in latex_path.read_text(encoding="utf-8")},
        {"项目": "图表清单", "通过": figure_manifest_path.exists() and len(figures) >= 3},
        {"项目": "补充材料索引", "通过": supplement_path.exists() and len(tables) >= 3},
        {"项目": "安全边界声明", "通过": "安全边界" in draft_path.read_text(encoding="utf-8")},
    ]


def _archive_bundle(bundle_dir: Path, archive_path: Path) -> None:
    with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for path in bundle_dir.rglob("*"):
            if path.is_dir() or path == archive_path:
                continue
            zf.write(path, path.relative_to(bundle_dir))


def _resolve_artifact_path(value: Any, output_dir: Path) -> Path | None:
    if not isinstance(value, str) or not value:
        return None
    path = Path(value)
    if not path.is_absolute():
        path = output_dir / path
    return path.resolve()


def _safe_stem(stem: str) -> str:
    cleaned = "".join(ch if ch.isalnum() or ch in {"-", "_"} else "_" for ch in stem)
    return cleaned[:80] or "artifact"


def _tex(text: Any) -> str:
    return (
        str(text)
        .replace("\\", "\\textbackslash{}")
        .replace("_", "\\_")
        .replace("%", "\\%")
        .replace("&", "\\&")
        .replace("#", "\\#")
    )

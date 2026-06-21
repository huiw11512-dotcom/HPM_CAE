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
import subprocess
import threading
import zipfile
from typing import Any, Mapping

import yaml

from hpm_platform.plugins import PluginRegistry
from hpm_platform.validation.vv_runner import load_last_vv_result


PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_OUTPUT = PROJECT_ROOT / "outputs_v20a_vv"
DEFAULT_BUNDLE_DIRNAME = "paper_factory_v20d"
DEFAULT_CONFIG = PROJECT_ROOT / "configs" / "paper_factory_v20d.yaml"


@dataclass(frozen=True)
class PaperFactoryBundle:
    bundle_dir: Path
    manifest: Path
    draft_markdown: Path
    ieee_latex: Path
    templates_dir: Path
    bibliography: Path
    reproduction_registry: Path
    statistics_audit: Path
    template_audit: Path
    latex_compile_audit: Path
    figure_manifest: Path
    supplement_index: Path
    archive: Path

    def as_dict(self) -> dict[str, Any]:
        return {
            "bundle_dir": str(self.bundle_dir),
            "manifest": str(self.manifest),
            "draft_markdown": str(self.draft_markdown),
            "ieee_latex": str(self.ieee_latex),
            "templates_dir": str(self.templates_dir),
            "bibliography": str(self.bibliography),
            "reproduction_registry": str(self.reproduction_registry),
            "statistics_audit": str(self.statistics_audit),
            "template_audit": str(self.template_audit),
            "latex_compile_audit": str(self.latex_compile_audit),
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
                        {"项目": "引用库", "通过": False},
                        {"项目": "文献复现注册表", "通过": False},
                        {"项目": "统计审计", "通过": False},
                        {"项目": "多模板导出", "通过": False},
                        {"项目": "模板审计", "通过": False},
                        {"项目": "LaTeX 编译审计", "通过": False},
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
    config = load_paper_factory_config()

    bundle_dir = out / DEFAULT_BUNDLE_DIRNAME
    figures_dir = bundle_dir / "figures"
    tables_dir = bundle_dir / "tables"
    templates_dir = bundle_dir / "templates"
    bundle_dir.mkdir(parents=True, exist_ok=True)
    _reset_generated_dir(figures_dir)
    _reset_generated_dir(tables_dir)
    _reset_generated_dir(templates_dir)

    context = _paper_context(result, out, title=title, config=config)
    copied_figures = _copy_figures(context["figures"], figures_dir)
    copied_tables = _copy_tables(_table_sources(out), tables_dir)
    context["figures"] = copied_figures
    context["tables"] = copied_tables

    draft_path = bundle_dir / "HPM_DT_V20D_论文草稿.md"
    latex_path = bundle_dir / "HPM_DT_V20D_IEEE骨架.tex"
    bibliography_path = bundle_dir / "HPM_DT_V20D_引用库.bib"
    reproduction_path = bundle_dir / "HPM_DT_V20D_文献复现注册表.csv"
    statistics_path = bundle_dir / "HPM_DT_V20D_统计审计.json"
    statistics_csv_path = bundle_dir / "HPM_DT_V20D_统计审计.csv"
    template_audit_path = bundle_dir / "HPM_DT_V20D_模板审计.json"
    template_audit_csv_path = bundle_dir / "HPM_DT_V20D_模板审计.csv"
    latex_audit_path = bundle_dir / "HPM_DT_V20D_LaTeX编译审计.json"
    latex_log_path = bundle_dir / "HPM_DT_V20D_LaTeX编译审计.log"
    figure_manifest_path = bundle_dir / "HPM_DT_V20D_图表清单.csv"
    supplement_path = bundle_dir / "HPM_DT_V20D_补充材料索引.md"
    manifest_path = bundle_dir / "paper_factory_manifest.json"
    archive_path = bundle_dir / "HPM_DT_V20D_paper_factory_bundle.zip"

    bibliography_path.write_text(_bibtex_library(config), encoding="utf-8")
    _write_reproduction_registry(reproduction_path, _reproduction_registry_rows(config, context, out))
    statistics_audit = _statistics_audit(context, config)
    statistics_path.write_text(json.dumps(statistics_audit, ensure_ascii=False, indent=2), encoding="utf-8")
    _write_statistics_csv(statistics_csv_path, statistics_audit)
    draft_path.write_text(_markdown_draft(context), encoding="utf-8")
    latex_path.write_text(_ieee_latex_skeleton(context), encoding="utf-8")
    template_rows = _write_latex_templates(templates_dir, context, config)
    template_audit = _template_audit(template_rows, config)
    template_audit_path.write_text(json.dumps(template_audit, ensure_ascii=False, indent=2), encoding="utf-8")
    _write_template_audit_csv(template_audit_csv_path, template_audit)
    latex_audit = _latex_compile_audit(latex_path, config)
    latex_audit_path.write_text(json.dumps(latex_audit, ensure_ascii=False, indent=2), encoding="utf-8")
    latex_log_path.write_text(str(latex_audit.get("日志", "")), encoding="utf-8")
    _write_figure_manifest(figure_manifest_path, copied_figures)
    supplement_path.write_text(_supplement_index(context), encoding="utf-8")

    acceptance = _acceptance(
        draft_path=draft_path,
        latex_path=latex_path,
        bibliography_path=bibliography_path,
        reproduction_path=reproduction_path,
        statistics_audit=statistics_audit,
        template_audit=template_audit,
        latex_audit=latex_audit,
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
            "引用库": str(bibliography_path.resolve()),
            "文献复现注册表": str(reproduction_path.resolve()),
            "统计审计JSON": str(statistics_path.resolve()),
            "统计审计CSV": str(statistics_csv_path.resolve()),
            "模板目录": str(templates_dir.resolve()),
            "模板审计JSON": str(template_audit_path.resolve()),
            "模板审计CSV": str(template_audit_csv_path.resolve()),
            "LaTeX编译审计": str(latex_audit_path.resolve()),
            "LaTeX编译日志": str(latex_log_path.resolve()),
            "图表清单": str(figure_manifest_path.resolve()),
            "补充材料索引": str(supplement_path.resolve()),
            "论文包ZIP": str(archive_path.resolve()),
        },
        "图表数量": len(copied_figures),
        "表格数量": len(copied_tables),
        "引用数量": len(config.get("references", ()) or ()),
        "复现条目数": len(_reproduction_registry_rows(config, context, out)),
        "模板数量": len(template_rows),
        "模板清单": template_rows,
        "统计审计": statistics_audit,
        "模板审计": template_audit,
        "LaTeX编译审计": {key: value for key, value in latex_audit.items() if key != "日志"},
        "验收清单": acceptance,
        "安全边界": context["safety_boundary"],
        "配置": str(config.get("__path__", DEFAULT_CONFIG)),
        "下一门槛": "接入外部文献 DOI、真实数据论文证据链、本机 PDF 编译归档和论文模板插件协议。",
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
        templates_dir=templates_dir,
        bibliography=bibliography_path,
        reproduction_registry=reproduction_path,
        statistics_audit=statistics_path,
        template_audit=template_audit_path,
        latex_compile_audit=latex_audit_path,
        figure_manifest=figure_manifest_path,
        supplement_index=supplement_path,
        archive=archive_path,
    )


def load_paper_factory_config(config_path: str | Path | None = None) -> dict[str, Any]:
    """Load Paper Factory publication settings from configs/."""

    path = Path(config_path or DEFAULT_CONFIG)
    with path.open("r", encoding="utf-8") as handle:
        payload = yaml.safe_load(handle) or {}
    if not isinstance(payload, dict):
        raise ValueError(f"Paper Factory 配置必须是 YAML 映射：{path}")
    payload["__path__"] = str(path.resolve())
    return payload


def _paper_context(result: Mapping[str, Any], output_dir: Path, *, title: str | None, config: Mapping[str, Any]) -> dict[str, Any]:
    platform = result.get("平台", {})
    summary = result.get("验收摘要", {})
    score = result.get("可信度评分", {})
    cases = list(result.get("验证用例", ()))
    uncertainty = result.get("不确定度", {})
    sensitivity = result.get("敏感性", {})
    figures = _figure_sources(result, output_dir)
    paper_title = title or str(config.get("default_title") or "HPM-DT：面向高功率微波数字孪生 CAE 平台的可信度验证与论文自动生产线")
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
        "config": config,
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


def _bibtex_library(config: Mapping[str, Any]) -> str:
    entries = []
    for item in config.get("references", ()) or ():
        if not isinstance(item, Mapping):
            continue
        key = _safe_bib_key(item.get("key"))
        entry_type = _safe_bib_key(item.get("type") or "misc")
        fields = []
        for field in ("author", "title", "year", "howpublished", "note"):
            value = item.get(field)
            if value:
                fields.append(f"  {field} = {{{_bibtex_value(value)}}}")
        if key and fields:
            entries.append(f"@{entry_type}{{{key},\n" + ",\n".join(fields) + "\n}")
    return "\n\n".join(entries) + "\n"


def _reproduction_registry_rows(config: Mapping[str, Any], context: Mapping[str, Any], output_dir: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for item in config.get("reproduction_registry", ()) or ():
        if not isinstance(item, Mapping):
            continue
        evidence_path = _resolve_evidence_path(item.get("evidence"), output_dir)
        rows.append(
            {
                "编号": item.get("id", f"REP-PF-{len(rows)+1:03d}"),
                "类型": item.get("type", "platform_evidence"),
                "主题": item.get("topic", ""),
                "引用键": item.get("reference_key", ""),
                "证据": str(evidence_path.resolve()) if evidence_path else "",
                "证据存在": bool(evidence_path and evidence_path.exists()),
                "状态": item.get("status", "planned"),
                "阻断项": item.get("blocker", ""),
            }
        )
    vv_result = output_dir / "v20A_验证结果.json"
    for index, case in enumerate(context.get("cases", ()) or (), start=1):
        if not isinstance(case, Mapping):
            continue
        rows.append(
            {
                "编号": f"REP-VV-{index:03d}",
                "类型": "automated_vv_case",
                "主题": case.get("用例名称", ""),
                "引用键": "hpm_dt_vv_report",
                "证据": str(vv_result.resolve()),
                "证据存在": vv_result.exists(),
                "状态": "已自动验证" if case.get("通过") else "需复核",
                "阻断项": "" if case.get("通过") else case.get("结论", "V&V 用例未通过"),
            }
        )
    return rows


def _write_reproduction_registry(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["编号", "类型", "主题", "引用键", "证据", "证据存在", "状态", "阻断项"])
        writer.writeheader()
        writer.writerows(rows)


def _statistics_audit(context: Mapping[str, Any], config: Mapping[str, Any]) -> dict[str, Any]:
    stats_cfg = _as_mapping(config.get("statistics"))
    summary = _as_mapping(context.get("summary"))
    uncertainty = _as_mapping(context.get("uncertainty"))
    sensitivity = _as_mapping(context.get("sensitivity"))
    sensitivity_rows = list(sensitivity.get("记录", ()) or ())
    uncertainty_summary = _as_mapping(uncertainty.get("汇总") or uncertainty)
    checks = [
        _audit_check("V&V用例数达标", _number(summary.get("总测试数")) >= _number(stats_cfg.get("min_vv_cases", 6)), f"{summary.get('总测试数', 0)} 个"),
        _audit_check("V&V全部通过", _number(summary.get("失败数")) == 0, f"失败 {summary.get('失败数', 0)} 个"),
        _audit_check("图表数量达标", len(context.get("figures", ()) or ()) >= _number(stats_cfg.get("min_figures", 3)), f"{len(context.get('figures', ()) or ())} 张"),
        _audit_check("表格数量达标", len(context.get("tables", ()) or ()) >= _number(stats_cfg.get("min_tables", 3)), f"{len(context.get('tables', ()) or ())} 个"),
        _audit_check("不确定度统计存在", bool(uncertainty_summary) or not stats_cfg.get("require_uncertainty", True), "Monte Carlo 汇总可读"),
        _audit_check("敏感性排序存在", bool(sensitivity_rows) or not stats_cfg.get("require_sensitivity", True), f"{len(sensitivity_rows)} 条"),
    ]
    return {
        "版本": config.get("version", "V2.0D-paper-factory-v1"),
        "统计审计通过": all(item["通过"] for item in checks),
        "统计显著性状态": "软件 V&V 统计审计已生成；外部实验显著性仍需真实授权数据和实验设计。",
        "关键指标": {
            "总测试数": summary.get("总测试数", 0),
            "通过率/%": summary.get("通过率", 0),
            "可信度评分": _as_mapping(context.get("score")).get("可信度评分", "NA"),
            "图表数量": len(context.get("figures", ()) or ()),
            "表格数量": len(context.get("tables", ()) or ()),
            "敏感性记录数": len(sensitivity_rows),
        },
        "检查项": checks,
        "安全边界": _as_mapping(config.get("safety_boundary")).get("description", context.get("safety_boundary", "")),
    }


def _write_statistics_csv(path: Path, audit: Mapping[str, Any]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["项目", "通过", "证据"])
        writer.writeheader()
        writer.writerows(audit.get("检查项", ()) or ())


def _latex_compile_audit(latex_path: Path, config: Mapping[str, Any]) -> dict[str, Any]:
    latex_cfg = _as_mapping(config.get("latex"))
    text = latex_path.read_text(encoding="utf-8")
    structural_checks = [
        _audit_check("documentclass存在", "\\documentclass" in text, "LaTeX 文档类可读"),
        _audit_check("正文环境闭合", "\\begin{document}" in text and "\\end{document}" in text, "document 环境完整"),
        _audit_check("标题存在", "\\title{" in text, "标题字段可读"),
        _audit_check("引用库绑定", "\\bibliography{" in text or not latex_cfg.get("require_bibliography", True), "BibTeX 入口可读"),
    ]
    preferred = [str(item) for item in latex_cfg.get("preferred_compilers", ()) or ()]
    available = [item for item in preferred if shutil.which(item.split()[0])]
    compile_result: dict[str, Any] = {
        "实际编译执行": False,
        "实际编译通过": None,
        "编译器": available[0] if available else "",
        "返回码": None,
    }
    log_text = "未发现本机 LaTeX 编译器；已完成结构审计。\n"
    if available:
        compiler = available[0]
        command = _latex_compile_command(compiler, latex_path.name)
        try:
            completed = subprocess.run(
                command,
                cwd=latex_path.parent,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                timeout=int(_number(latex_cfg.get("compile_timeout_s", 25))),
                check=False,
            )
            compile_result.update(
                {
                    "实际编译执行": True,
                    "实际编译通过": completed.returncode == 0,
                    "返回码": completed.returncode,
                }
            )
            log_text = completed.stdout[-12000:] if completed.stdout else ""
        except (OSError, subprocess.TimeoutExpired) as exc:
            compile_result.update({"实际编译执行": True, "实际编译通过": False, "返回码": -1})
            log_text = str(exc)
    structural_passed = all(item["通过"] for item in structural_checks)
    require_compiler = bool(latex_cfg.get("require_compiler_for_preview", False))
    actual_passed = compile_result["实际编译通过"] is True
    return {
        "通过": structural_passed and (actual_passed or not require_compiler),
        "结构审计通过": structural_passed,
        "本机编译器": available,
        **compile_result,
        "检查项": structural_checks,
        "说明": "预览阶段默认以结构审计为验收门槛；若本机存在 LaTeX 编译器，会记录实际编译结果。",
        "日志": log_text,
    }


def _latex_compile_command(compiler: str, tex_name: str) -> list[str]:
    name = compiler.split()[0]
    if name == "latexmk":
        return [name, "-pdf", "-interaction=nonstopmode", tex_name]
    return [name, "-interaction=nonstopmode", tex_name]


def _template_definitions(config: Mapping[str, Any]) -> list[dict[str, Any]]:
    template_cfg = _as_mapping(config.get("templates"))
    entries = template_cfg.get("entries", ()) or ()
    templates: list[dict[str, Any]] = []
    for item in entries:
        if not isinstance(item, Mapping):
            continue
        template = {
            "id": _safe_bib_key(item.get("id") or f"template_{len(templates)+1}"),
            "name": str(item.get("name") or f"论文模板{len(templates)+1}"),
            "kind": str(item.get("kind") or "journal_article"),
            "filename": str(item.get("filename") or f"HPM_DT_V20D_模板{len(templates)+1}.tex"),
            "documentclass": str(item.get("documentclass") or "\\documentclass[UTF8]{ctexart}"),
            "audience": str(item.get("audience") or "科研论文草稿"),
            "required_sections": [str(section) for section in item.get("required_sections", ()) or ()],
        }
        templates.append(template)
    templates.extend(_plugin_template_definitions(config))
    if not templates:
        templates = _default_template_definitions()
    deduped: dict[str, dict[str, Any]] = {}
    for template in templates:
        deduped.setdefault(str(template["id"]), template)
    return list(deduped.values())


def _plugin_template_definitions(config: Mapping[str, Any]) -> list[dict[str, Any]]:
    plugin_cfg = _as_mapping(_as_mapping(config.get("templates")).get("plugin_templates"))
    if not bool(plugin_cfg.get("enabled", True)):
        return []
    plugin_dirs = tuple(_resolve_project_path(item) for item in plugin_cfg.get("plugin_dirs", ()) or ())
    registry = PluginRegistry(plugin_dirs or None)
    requested_ids = {str(item) for item in plugin_cfg.get("plugin_ids", ()) or ()}
    templates: list[dict[str, Any]] = []
    for plugin in registry.list():
        if plugin.category != "report_template":
            continue
        if requested_ids and plugin.plugin_id not in requested_ids:
            continue
        for item in plugin.settings.get("paper_templates", ()) or ():
            if not isinstance(item, Mapping):
                continue
            template = {
                "id": _safe_bib_key(item.get("id") or f"{plugin.plugin_id}_template_{len(templates)+1}"),
                "name": str(item.get("name") or f"{plugin.name} 模板{len(templates)+1}"),
                "kind": str(item.get("kind") or "journal_article"),
                "filename": str(item.get("filename") or f"{_safe_bib_key(plugin.plugin_id)}_{len(templates)+1}.tex"),
                "documentclass": str(item.get("documentclass") or "\\documentclass[UTF8]{ctexart}"),
                "audience": str(item.get("audience") or plugin.summary or "科研论文草稿"),
                "required_sections": [str(section) for section in item.get("required_sections", ()) or ()],
                "source_plugin": plugin.plugin_id,
            }
            templates.append(template)
    return templates


def _default_template_definitions() -> list[dict[str, Any]]:
    return [
        {
            "id": "ieee_conference",
            "name": "IEEE会议论文模板",
            "kind": "ieee_conference",
            "filename": "HPM_DT_V20D_IEEE会议论文模板.tex",
            "documentclass": "\\documentclass[conference]{IEEEtran}",
            "audience": "IEEE conference or workshop paper",
            "required_sections": ["Introduction", "Method", "Results", "Reproducibility", "Limitations", "Conclusion"],
        },
        {
            "id": "journal_article",
            "name": "期刊论文模板",
            "kind": "journal_article",
            "filename": "HPM_DT_V20D_期刊论文模板.tex",
            "documentclass": "\\documentclass[UTF8]{ctexart}",
            "audience": "中文期刊或扩展版技术论文",
            "required_sections": ["引言", "方法", "结果", "讨论", "可复现性", "结论"],
        },
        {
            "id": "thesis_chapter",
            "name": "学位论文章节模板",
            "kind": "thesis_chapter",
            "filename": "HPM_DT_V20D_学位论文章节模板.tex",
            "documentclass": "\\documentclass[UTF8]{ctexrep}",
            "audience": "学位论文方法与实验章节",
            "required_sections": ["平台架构", "验证方法", "实验结果", "统计审计", "本章小结"],
        },
    ]


def _write_latex_templates(templates_dir: Path, context: Mapping[str, Any], config: Mapping[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for template in _template_definitions(config):
        filename = _safe_template_filename(template.get("filename"), f"{template['id']}.tex")
        path = templates_dir / filename
        path.write_text(_latex_template_document(context, template), encoding="utf-8")
        rows.append(
            {
                "模板ID": template["id"],
                "模板名称": template["name"],
                "类型": template["kind"],
                "来源插件": template.get("source_plugin", ""),
                "面向场景": template["audience"],
                "文件": str(path.resolve()),
                "包内文件": str(path.relative_to(templates_dir.parent)),
                "要求章节": "；".join(template.get("required_sections", ())),
            }
        )
    return rows


def _latex_template_document(context: Mapping[str, Any], template: Mapping[str, Any]) -> str:
    if template.get("kind") == "ieee_conference":
        return _ieee_latex_skeleton(context)
    return _chinese_latex_template(context, template)


def _chinese_latex_template(context: Mapping[str, Any], template: Mapping[str, Any]) -> str:
    score = _as_mapping(context.get("score"))
    summary = _as_mapping(context.get("summary"))
    kind = str(template.get("kind", "journal_article"))
    heading = "chapter" if kind == "thesis_chapter" else "section"
    subheading = "section" if kind == "thesis_chapter" else "subsection"
    documentclass = str(template.get("documentclass") or "\\documentclass[UTF8]{ctexart}")
    required_sections = list(template.get("required_sections", ()) or ())
    section_blocks = []
    for section in required_sections:
        section_blocks.append(f"\\{heading}{{{_tex(section)}}}\n{_template_section_text(section, context, subheading)}")
    sections = "\n\n".join(section_blocks)
    return f"""% V2.0D Paper Factory {template.get('name', '论文模板')}。预览稿以结构可审计为主。
{documentclass}
\\usepackage{{graphicx}}
\\usepackage{{booktabs}}
\\usepackage{{amsmath}}
\\usepackage{{hyperref}}
\\begin{{document}}

\\title{{{_tex(context['title'])}}}
\\author{{HPM-DT 自动论文生产线}}
\\date{{{_tex(context['generated_utc'])}}}
\\maketitle

\\begin{{abstract}}
本文档是面向{_tex(template.get('audience', '科研论文草稿'))}的 V2.0D Paper Factory 模板。当前 V\\&V 共运行 {summary.get('总测试数', 0)} 类用例，通过 {summary.get('通过数', 0)} 类，可信度评分为 {score.get('可信度评分', 'NA')}，等级为 {score.get('当前等级', 'NA')}。
\\end{{abstract}}

{sections}

\\bibliographystyle{{IEEEtran}}
\\bibliography{{HPM_DT_V20D_引用库}}

\\end{{document}}
"""


def _template_section_text(section: str, context: Mapping[str, Any], subheading: str) -> str:
    summary = _as_mapping(context.get("summary"))
    score = _as_mapping(context.get("score"))
    if section in {"引言", "平台架构"}:
        return "HPM-DT 面向归一化高功率微波数字孪生研究，强调软件链路可验证、证据可追溯和论文材料可复现。"
    if section in {"方法", "验证方法"}:
        return "平台复用 V2.0A 解析验证、算法基准、后端一致性、不确定度和敏感性分析结果，不为论文临时修改核心求解器。"
    if section in {"结果", "实验结果"}:
        return f"当前自动验收总数为 {summary.get('总测试数', 0)}，通过 {summary.get('通过数', 0)}，可信度评分为 {score.get('可信度评分', 'NA')}。"
    if section in {"统计审计"}:
        return "统计审计覆盖 V&V 用例数、图表数量、表格数量、不确定度汇总和敏感性排序；真实实验显著性仍需授权数据闭环。"
    if section in {"讨论"}:
        return f"本模板仅组织归一化科研结果。安全边界：{_tex(context.get('safety_boundary', ''))}"
    if section in {"可复现性"}:
        return f"\\{subheading}{{材料清单}}\n论文草稿、模板、引用库、复现注册表、统计审计、图表清单和补充材料均由 Paper Factory 自动生成。"
    if section in {"结论", "本章小结"}:
        return "多模板导出证明发文材料生产已经从单一草稿进入模板矩阵阶段；正式投稿前仍需外部 DOI、授权数据证据链和 PDF 编译归档。"
    return "本节由 Paper Factory 生成占位结构，等待用户补充面向具体期刊或学位论文格式的人工论述。"


def _template_audit(template_rows: list[dict[str, Any]], config: Mapping[str, Any]) -> dict[str, Any]:
    template_cfg = _as_mapping(config.get("templates"))
    min_templates = int(_number(template_cfg.get("min_templates", 3)))
    audited: list[dict[str, Any]] = []
    for row in template_rows:
        path = Path(str(row.get("文件", "")))
        text = path.read_text(encoding="utf-8") if path.exists() else ""
        section_checks = [
            _audit_check(f"章节存在:{section}", f"{{{section}}}" in text, row.get("包内文件", ""))
            for section in str(row.get("要求章节", "")).split("；")
            if section
        ]
        structural_checks = [
            _audit_check("文件存在", path.exists(), row.get("文件", "")),
            _audit_check("documentclass存在", "\\documentclass" in text, row.get("包内文件", "")),
            _audit_check("正文环境闭合", "\\begin{document}" in text and "\\end{document}" in text, row.get("包内文件", "")),
            _audit_check("引用库绑定", "\\bibliography{" in text or not _as_mapping(config.get("latex")).get("require_bibliography", True), row.get("包内文件", "")),
            *section_checks,
        ]
        passed = all(item["通过"] for item in structural_checks)
        audited.append(
            {
                **row,
                "通过": passed,
                "结构审计通过": passed,
                "检查项": structural_checks,
            }
        )
    count_check = _audit_check("模板数量达标", len(audited) >= min_templates, f"{len(audited)}/{min_templates}")
    all_check = _audit_check("模板结构全部通过", all(item["通过"] for item in audited), "逐模板章节、正文和引用入口审计")
    return {
        "版本": config.get("version", "V2.0D-paper-factory-v1"),
        "模板数量": len(audited),
        "要求模板数量": min_templates,
        "模板审计通过": count_check["通过"] and all_check["通过"],
        "检查项": [count_check, all_check],
        "模板": audited,
        "说明": "预览阶段完成多模板结构审计；实际 PDF 编译归档仍取决于本机 LaTeX 工具链和目标期刊模板。",
    }


def _write_template_audit_csv(path: Path, audit: Mapping[str, Any]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["模板ID", "模板名称", "类型", "来源插件", "面向场景", "通过", "结构审计通过", "包内文件", "文件"])
        writer.writeheader()
        for row in audit.get("模板", ()) or ():
            writer.writerow({key: row.get(key, "") for key in writer.fieldnames})


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

## 7. 引用、复现注册与统计审计

Paper Factory 同步生成 `HPM_DT_V20D_引用库.bib`、`HPM_DT_V20D_文献复现注册表.csv`、`HPM_DT_V20D_统计审计.json` 和 `HPM_DT_V20D_LaTeX编译审计.json`。其中引用库当前以平台自产证据和待绑定外部 DOI 的复现入口为主，不把预览数据伪装成已完成的外部文献复现。

## 8. 讨论与边界

当前结果证明的是归一化阵列算法、降阶传播模型和可信度验证流程的软件链路，而不是全波电磁仿真或实物外场结论。论文定稿前仍需扩展文献复现、真实数据导入、外部仿真对比和更大样本统计检验。

安全边界：{context['safety_boundary']}

## 9. 可复现性

本文所有草稿、图表、表格、补充材料索引和机器结果均由 `PaperFactoryService` 自动生成。建议定稿前固定配置、随机种子、运行环境、插件版本和数据来源，并将 `paper_factory_manifest.json` 作为补充材料入口。
"""


def _ieee_latex_skeleton(context: Mapping[str, Any]) -> str:
    score = context["score"]
    summary = context["summary"]
    figures = context["figures"][:6]
    ref_keys = [
        _safe_bib_key(item.get("key"))
        for item in context.get("config", {}).get("references", ()) or ()
        if isinstance(item, Mapping) and item.get("key")
    ]
    citation = "\\cite{" + ",".join(ref_keys[:3]) + "}" if ref_keys else ""
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
HPM-DT is designed as a Chinese open research CAE platform for normalized HPM digital-twin studies {citation}.

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

\\bibliographystyle{{IEEEtran}}
\\bibliography{{HPM_DT_V20D_引用库}}

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
- 多模板目录：`templates/`
- 引用库：`HPM_DT_V20D_引用库.bib`
- 文献复现注册表：`HPM_DT_V20D_文献复现注册表.csv`
- 统计审计：`HPM_DT_V20D_统计审计.json`
- 模板审计：`HPM_DT_V20D_模板审计.json`
- LaTeX 编译审计：`HPM_DT_V20D_LaTeX编译审计.json`
"""


def _acceptance(
    *,
    draft_path: Path,
    latex_path: Path,
    bibliography_path: Path,
    reproduction_path: Path,
    statistics_audit: Mapping[str, Any],
    template_audit: Mapping[str, Any],
    latex_audit: Mapping[str, Any],
    figure_manifest_path: Path,
    supplement_path: Path,
    figures: list[dict[str, Any]],
    tables: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    return [
        {"项目": "论文草稿", "通过": draft_path.exists() and draft_path.stat().st_size > 1000},
        {"项目": "IEEE LaTeX 骨架", "通过": latex_path.exists() and "\\documentclass" in latex_path.read_text(encoding="utf-8")},
        {"项目": "引用库", "通过": bibliography_path.exists() and "@misc" in bibliography_path.read_text(encoding="utf-8")},
        {"项目": "文献复现注册表", "通过": reproduction_path.exists() and reproduction_path.stat().st_size > 100},
        {"项目": "统计审计", "通过": bool(statistics_audit.get("统计审计通过"))},
        {"项目": "多模板导出", "通过": int(_number(template_audit.get("模板数量"))) >= int(_number(template_audit.get("要求模板数量", 3)))},
        {"项目": "模板审计", "通过": bool(template_audit.get("模板审计通过"))},
        {"项目": "LaTeX 编译审计", "通过": bool(latex_audit.get("通过"))},
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


def _resolve_evidence_path(value: Any, output_dir: Path) -> Path | None:
    if not isinstance(value, str) or not value:
        return None
    path = Path(value)
    if path.is_absolute():
        return path
    parts = path.parts
    if parts and parts[0] == DEFAULT_OUTPUT.name:
        return output_dir.joinpath(*parts[1:])
    candidate = PROJECT_ROOT / path
    if candidate.exists():
        return candidate
    return output_dir / path


def _audit_check(name: str, passed: bool, evidence: Any) -> dict[str, Any]:
    return {"项目": name, "通过": bool(passed), "证据": str(evidence)}


def _as_mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _number(value: Any) -> float:
    try:
        if value is None or value == "":
            return 0.0
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _safe_bib_key(value: Any) -> str:
    text = str(value or "ref").strip()
    cleaned = "".join(ch if ch.isalnum() or ch in {"-", "_", ":"} else "_" for ch in text)
    return cleaned or "ref"


def _bibtex_value(value: Any) -> str:
    return str(value).replace("\\", "\\textbackslash{}").replace("{", "\\{").replace("}", "\\}")


def _safe_template_filename(value: Any, fallback: str) -> str:
    text = str(value or fallback).strip() or fallback
    name = Path(text).name
    if not name.lower().endswith(".tex"):
        name = f"{name}.tex"
    stem = _safe_stem(Path(name).stem)
    return f"{stem}.tex"


def _resolve_project_path(value: Any) -> Path:
    path = Path(str(value))
    return path if path.is_absolute() else PROJECT_ROOT / path


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

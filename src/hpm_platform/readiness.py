"""North Star platform readiness audit.

This module turns the current V&V, Workbench, data import, plugin, and
publication evidence into a compact machine-readable progress report. The
scores are software/research workflow maturity indicators only; they do not
turn normalized proxy fields into real device thresholds, effect ranges, or
damage probabilities.
"""
from __future__ import annotations

from datetime import datetime, timezone
import csv
import json
from pathlib import Path
from typing import Any, Mapping

import yaml


READINESS_VERSION = "NorthStar-readiness-v1"
PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_READINESS_CONFIG = PROJECT_ROOT / "configs" / "platform_readiness.yaml"

NO_OUTPUT_ITEMS = [
    "真实作用距离",
    "器件阈值",
    "真实毁伤概率",
    "作战效能结论",
]


def load_readiness_config(config_path: str | Path | None = None) -> dict[str, Any]:
    """Load the readiness scoring config from configs/."""

    path = Path(config_path or DEFAULT_READINESS_CONFIG)
    with path.open("r", encoding="utf-8") as handle:
        payload = yaml.safe_load(handle) or {}
    if not isinstance(payload, dict):
        raise ValueError(f"平台成熟度配置必须是 YAML 映射：{path}")
    payload["__path__"] = str(path.resolve())
    return payload


def build_platform_readiness_report(
    *,
    output_dir: str | Path,
    north_star: Mapping[str, Any],
    vv: Mapping[str, Any],
    workbench: Mapping[str, Any],
    data_import: Mapping[str, Any],
    plugins: Mapping[str, Any],
    paper_factory: Mapping[str, Any],
    readiness_config: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build and persist a current platform readiness report."""

    out = Path(output_dir)
    config = dict(readiness_config or load_readiness_config())
    report_dir = out / "platform_readiness"
    json_path = report_dir / "platform_readiness_report.json"
    csv_path = report_dir / "platform_readiness_dimensions.csv"

    dimensions = [
        _vv_dimension(vv, config),
        _workbench_dimension(workbench, config),
        _data_import_dimension(data_import, config),
        _plugin_dimension(plugins, config),
        _paper_dimension(paper_factory, config),
        _engineering_dimension(workbench, paper_factory, out, config),
        _safety_dimension(vv, data_import, workbench, paper_factory, config),
    ]
    use_readiness = _weighted_dimension_score(dimensions, config, "use_readiness")
    publication_readiness = _weighted_dimension_score(dimensions, config, "publication_readiness")
    platform_maturity = _weighted_dimension_score(dimensions, config, "platform_maturity")
    layer_maturity = _layer_maturity(north_star, dimensions, config)
    workflow = _workflow_status(vv, workbench, data_import, paper_factory)
    blockers = _blockers(dimensions, data_import, paper_factory)
    capped_scores = _apply_score_caps(
        {
            "使用准备度/%": use_readiness,
            "发文准备度/%": publication_readiness,
            "平台成熟度/%": platform_maturity,
        },
        blockers,
        config,
    )
    use_readiness = capped_scores["使用准备度/%"]
    publication_readiness = capped_scores["发文准备度/%"]
    platform_maturity = capped_scores["平台成熟度/%"]

    payload: dict[str, Any] = {
        "版本": str(config.get("version", READINESS_VERSION)),
        "更新时间UTC": datetime.now(timezone.utc).isoformat(),
        "平台": north_star.get("平台名称", "HPM-DT"),
        "最高层目标": north_star.get("最高层目标", ""),
        "结论": _conclusion(use_readiness, publication_readiness, blockers),
        "使用准备度/%": use_readiness,
        "发文准备度/%": publication_readiness,
        "平台成熟度/%": platform_maturity,
        "维度": dimensions,
        "八层成熟度": layer_maturity,
        "主链路": workflow,
        "关键阻断项": blockers,
        "下一步建议": _next_actions(blockers, use_readiness, publication_readiness, config),
        "安全边界": {
            "说明": _mapping(config.get("safety_boundary")).get("description", "本报告只评估软件链路、科研证据链和论文材料成熟度。"),
            "不输出项": list(_mapping(config.get("safety_boundary")).get("no_output_items", NO_OUTPUT_ITEMS)),
        },
        "配置": config.get("__path__", str(DEFAULT_READINESS_CONFIG)),
        "产物": {
            "json": str(json_path.resolve()),
            "csv": str(csv_path.resolve()),
        },
    }
    report_dir.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    _write_dimension_csv(csv_path, dimensions)
    return payload


def _vv_dimension(vv: Mapping[str, Any], config: Mapping[str, Any]) -> dict[str, Any]:
    summary = _mapping(vv.get("摘要"))
    score = _mapping(vv.get("评分"))
    raw_score = _number(score.get("可信度评分"))
    pass_rate = _number(summary.get("通过率"))
    failures = int(_number(summary.get("失败数")))
    cases = int(_number(summary.get("总测试数")))
    checks = [
        _check("V&V用例存在", cases >= _threshold(config, "min_vv_cases", 6), f"{cases} 个自动验证用例"),
        _check("V&V全部通过", failures == 0, f"失败数 {failures}"),
        _check("可信度评分达到A级门槛", raw_score >= _threshold(config, "vv_a_score", 85), f"评分 {raw_score:.2f}"),
        _check("不确定度与敏感性可读", bool(vv.get("不确定度")) and bool(vv.get("敏感性")), "已返回统计摘要"),
    ]
    return _dimension(
        "可信度验证",
        _weighted_checks(
            checks,
            _check_weights(config, "可信度验证", checks),
            base_score=0.75 * raw_score + 0.25 * pass_rate,
            base_score_weight=_dimension_base_score_weight(config, "可信度验证", 0.45),
        ),
        checks,
        "解析验证、算法基准、后端一致性、不确定度、敏感性和可信度评分。",
        f"可信度 {raw_score:.2f}，通过率 {pass_rate:.1f}%。",
        config,
    )


def _workbench_dimension(workbench: Mapping[str, Any], config: Mapping[str, Any]) -> dict[str, Any]:
    scene = _mapping(workbench.get("scene"))
    assets = _mapping(workbench.get("assets"))
    imported = _mapping(workbench.get("imported_calibration"))
    material_audit = _mapping(workbench.get("material_audit") or assets.get("材料代理审计"))
    records = list(assets.get("资产", ()) or ())
    asset_types = {str(item.get("类型", "")) for item in records if isinstance(item, Mapping)}
    checks = [
        _check("三维场景可读", bool(scene.get("objects") or scene.get("对象")), "Workbench scene API 已返回"),
        _check("材料代理审计通过", bool(material_audit.get("通过")) and "材料代理审计" in asset_types, "MAT-AUDIT-001 已进入资产台账并通过字段/引用/边界审计"),
        _check("资产台账通过", bool(_mapping(assets.get("审计")).get("通过")), "资产 JSON/CSV/SQLite 索引可审计"),
        _check("数据库审计通过", bool(_mapping(assets.get("数据库审计")).get("通过")), "SQLite 表结构和行数可读"),
        _check("复现审计通过", bool(_mapping(assets.get("复现审计")).get("通过")), "结果/哈希/JOB/SOL 可复查"),
        _check("命名审计通过", bool(_mapping(assets.get("命名审计")).get("通过")), "JOB/SOL/SNP 编号规则可审计"),
        _check("绝对量纲标定可读", bool(_mapping(assets.get("绝对量纲标定")).get("通过")), "阵元功率元数据和实测点残差可读"),
        _check("导入标定桥接入账", bool(imported.get("通过")) and any(item.get("资产id") == "IMP-CAL-001" for item in records if isinstance(item, Mapping)), "IMP-CAL-001 已进入资产台账"),
        _check("求解结果资产存在", "求解结果" in asset_types, "至少有一条 SOL 结果档案"),
    ]
    return _dimension(
        "三维CAE工作台",
        _weighted_checks(checks, _check_weights(config, "三维CAE工作台", checks)),
        checks,
        "三维工程、求解、资产台账、数据库、快照和标定桥接。",
        f"资产 {len(records)} 条；类型 {len(asset_types)} 类。",
        config,
    )


def _data_import_dimension(data_import: Mapping[str, Any], config: Mapping[str, Any]) -> dict[str, Any]:
    catalog = _mapping(data_import.get("catalog"))
    readiness = _mapping(data_import.get("readiness"))
    bridge = _mapping(data_import.get("bridge"))
    comparison = _mapping(data_import.get("model_comparison"))
    evidence = _mapping(data_import.get("evidence_chain"))
    audit = _mapping(data_import.get("vv_audit"))
    formats = set(str(item) for item in catalog.get("支持格式", ()) or ())
    checks = [
        _check("多格式导入目录通过", bool(_mapping(catalog.get("验收")).get("通过")), f"格式 {len(formats)} 类"),
        _check("标定准备度通过", bool(readiness.get("通过")), f"准备度 {readiness.get('总体得分', '—')}"),
        _check("CalibrationSamples桥接通过", bool(bridge.get("通过")), f"样本 {bridge.get('样本数', 0)} 个"),
        _check("模型误差对比通过", bool(comparison.get("通过")), f"样本 {comparison.get('样本数', 0)} 个"),
        _check("证据链审计可执行", bool(evidence.get("输出文件")), evidence.get("输出文件", "未生成")),
        _check(
            "真实源链与相位参考证据通过",
            bool(evidence.get("真实源链与相位参考已接入")),
            "授权、源链、相位参考和校准证书均需通过",
            severity="P0",
        ),
        _check("外部数据V&V审计存在", int(_number(audit.get("样本数"))) > 0, f"样本 {audit.get('样本数', 0)} 个"),
        _check(
            "可纳入正式可信度评分",
            bool(audit.get("可纳入正式可信度评分")),
            "真实源链/相位参考满足后才能通过",
            severity="P0",
        ),
    ]
    return _dimension(
        "真实数据接入",
        _weighted_checks(checks, _check_weights(config, "真实数据接入", checks)),
        checks,
        "CST/HFSS/测量批次/CSV/Touchstone/NPZ/HDF5 的元数据、单位、坐标和不确定度链路。",
        f"支持格式 {', '.join(sorted(formats)) or '—'}。",
        config,
    )


def _plugin_dimension(plugins: Mapping[str, Any], config: Mapping[str, Any]) -> dict[str, Any]:
    acceptance = _mapping(plugins.get("acceptance"))
    catalog = _mapping(plugins.get("catalog"))
    checks = [
        _check("插件验收通过", bool(acceptance.get("通过")), f"启用 {acceptance.get('启用插件数', 0)} 个"),
        _check("至少三类插件", int(_number(acceptance.get("类别总数"))) >= _threshold(config, "min_plugin_categories", 3), f"{acceptance.get('类别总数', 0)} 类"),
        _check("目录可读", int(_number(catalog.get("插件总数"))) >= _threshold(config, "min_plugins", 3), f"{catalog.get('插件总数', 0)} 个插件"),
        _check("白名单钩子存在", bool(acceptance.get("白名单钩子")), "插件不导入任意 Python 模块"),
    ]
    return _dimension(
        "插件生态",
        _weighted_checks(checks, _check_weights(config, "插件生态", checks)),
        checks,
        "Plugin Marketplace、manifest、参数 Schema、启停和白名单运行。",
        f"插件 {catalog.get('插件总数', 0)} 个，类别 {catalog.get('类别总数', 0)} 类。",
        config,
    )


def _paper_dimension(paper: Mapping[str, Any], config: Mapping[str, Any]) -> dict[str, Any]:
    artifacts = _mapping(paper.get("产物"))
    artifact_paths = [Path(str(value)) for value in artifacts.values() if value]
    existing = sum(1 for path in artifact_paths if path.exists())
    statistics_audit = _mapping(paper.get("统计审计"))
    template_audit = _mapping(paper.get("模板审计"))
    latex_audit = _mapping(paper.get("LaTeX编译审计"))
    checks = [
        _check("Paper Factory已生成", bool(paper.get("通过")), paper.get("状态", "未知")),
        _check("核心论文产物存在", existing >= _threshold(config, "min_paper_artifacts", 5), f"{existing}/{len(artifact_paths)} 个产物存在"),
        _check("图表数量达标", int(_number(paper.get("图表数量"))) >= _threshold(config, "min_paper_figures", 3), f"{paper.get('图表数量', 0)} 张图"),
        _check("表格数量达标", int(_number(paper.get("表格数量"))) >= _threshold(config, "min_paper_tables", 3), f"{paper.get('表格数量', 0)} 张表"),
        _check("引用库存在", Path(str(artifacts.get("引用库", ""))).exists(), artifacts.get("引用库", "未生成")),
        _check("文献复现注册表存在", Path(str(artifacts.get("文献复现注册表", ""))).exists(), artifacts.get("文献复现注册表", "未生成")),
        _check("统计审计通过", bool(statistics_audit.get("统计审计通过")), statistics_audit.get("统计显著性状态", "未生成")),
        _check("多模板导出达标", int(_number(template_audit.get("模板数量"))) >= int(_number(template_audit.get("要求模板数量", 3))), f"{template_audit.get('模板数量', 0)}/{template_audit.get('要求模板数量', 3)} 个模板"),
        _check("模板审计通过", bool(template_audit.get("模板审计通过")), template_audit.get("说明", "未生成")),
        _check("LaTeX编译审计通过", bool(latex_audit.get("结构审计通过")), latex_audit.get("说明", "未生成")),
        _check("论文安全边界写入", bool(paper.get("安全边界")), "草稿包保留模型边界"),
    ]
    return _dimension(
        "论文生产",
        _weighted_checks(checks, _check_weights(config, "论文生产", checks)),
        checks,
        "Markdown 草稿、IEEE LaTeX 骨架、多模板矩阵、BibTeX 引用库、复现注册表、统计审计、模板审计、LaTeX 审计、图表清单、补充材料和可复现论文包。",
        f"状态 {paper.get('状态', '未知')}。",
        config,
    )


def _engineering_dimension(workbench: Mapping[str, Any], paper: Mapping[str, Any], output_dir: Path, config: Mapping[str, Any]) -> dict[str, Any]:
    assets = _mapping(workbench.get("assets"))
    index = _mapping(assets.get("索引"))
    test_report = output_dir / "完整测试报告.txt"
    checks = [
        _check("资产索引JSON存在", Path(str(index.get("json", ""))).exists(), str(index.get("json", ""))),
        _check("资产数据库存在", Path(str(index.get("sqlite", ""))).exists(), str(index.get("sqlite", ""))),
        _check("谱系审计存在", Path(str(index.get("lineage_json", ""))).exists(), str(index.get("lineage_json", ""))),
        _check("论文包ZIP存在", Path(str(_mapping(paper.get("产物")).get("论文包ZIP", ""))).exists(), str(_mapping(paper.get("产物")).get("论文包ZIP", ""))),
        _check("全量测试报告存在", test_report.exists() and "passed" in _safe_read_text(test_report).lower(), str(test_report)),
    ]
    return _dimension(
        "工程化与复现",
        _weighted_checks(checks, _check_weights(config, "工程化与复现", checks)),
        checks,
        "可复查资产、SQLite 索引、谱系、论文包和测试报告。",
        "用于支撑软件著作权、课题平台和论文补充材料。",
        config,
    )


def _safety_dimension(
    vv: Mapping[str, Any],
    data_import: Mapping[str, Any],
    workbench: Mapping[str, Any],
    paper: Mapping[str, Any],
    config: Mapping[str, Any],
) -> dict[str, Any]:
    text = json.dumps([vv, data_import, workbench, paper], ensure_ascii=False)
    checks = [
        _check("明确不输出真实作用距离", "真实作用距离" in text, "边界说明已出现"),
        _check("明确不输出器件阈值", "器件阈值" in text, "边界说明已出现"),
        _check("明确不输出真实毁伤概率", "毁伤概率" in text, "边界说明已出现"),
        _check("外部数据未改写正式评分", "是否改写正式评分" in text and "false" in text.lower(), "预评分保持附注"),
    ]
    return _dimension(
        "研究安全边界",
        _weighted_checks(checks, _check_weights(config, "研究安全边界", checks)),
        checks,
        "确保平台输出保持科研级归一化代理、残差、不确定度和证据链。",
        "不生成现实作用距离、器件阈值、真实毁伤概率或作战效能结论。",
        config,
    )


def _workflow_status(
    vv: Mapping[str, Any],
    workbench: Mapping[str, Any],
    data_import: Mapping[str, Any],
    paper: Mapping[str, Any],
) -> list[dict[str, Any]]:
    scene = _mapping(workbench.get("scene"))
    assets = _mapping(workbench.get("assets"))
    material_audit = _mapping(workbench.get("material_audit") or assets.get("材料代理审计"))
    bridge = _mapping(data_import.get("bridge"))
    audit = _mapping(data_import.get("vv_audit"))
    asset_types = {str(item.get("类型", "")) for item in assets.get("资产", ()) if isinstance(item, Mapping)}
    steps = [
        ("新建/加载工程", bool(scene), "默认工程可由 Workbench scene API 加载"),
        ("拖拽阵列/目标", bool(scene), "已有三维视口、对象树、移动模式和后端几何校验；尺寸/旋转 Gizmo 仍是后续门槛"),
        ("设置材料", bool(material_audit.get("通过")) and "材料代理审计" in asset_types, "材料代理审计 MAT-AUDIT-001 已入账，字段白名单、参数范围和安全边界可复查"),
        ("运行求解", "求解结果" in asset_types, "SOL 结果档案进入资产台账"),
        ("自动验证", _number(_mapping(vv.get("摘要")).get("失败数")) == 0, "V&V 用例、评分、不确定度和敏感性可读"),
        ("接入真实数据", bool(bridge.get("通过")), "Measurement Campaign 可桥接为 CalibrationSamples"),
        ("正式数据纳入评分", bool(audit.get("可纳入正式可信度评分")), "当前仍待真实源链/相位参考"),
        ("自动生成图表", int(_number(paper.get("图表数量"))) >= 3, "Paper Factory 图表清单可生成"),
        ("自动生成论文", bool(paper.get("通过")), "Markdown/多模板LaTeX/BibTeX/复现注册/统计审计/ZIP 可生成"),
    ]
    return [
        {
            "步骤": name,
            "状态": "已接通" if passed else "待补齐",
            "通过": bool(passed),
            "证据": evidence,
        }
        for name, passed, evidence in steps
    ]


def _layer_maturity(north_star: Mapping[str, Any], dimensions: list[dict[str, Any]], config: Mapping[str, Any]) -> list[dict[str, Any]]:
    score_by_name = {item["维度"]: float(item["得分"]) for item in dimensions}
    physics_data = score_by_name["真实数据接入"]
    workbench_score = score_by_name["三维CAE工作台"]
    vv_score = score_by_name["可信度验证"]
    layer_floor = _mapping(config.get("layer_floor_scores"))
    rows = []
    layer_scores = {
        "物理建模层": _round(0.45 * physics_data + 0.35 * workbench_score + 20),
        "感知层": _number(layer_floor.get("感知层", 55.0)),
        "防护层": _number(layer_floor.get("防护层", 58.0)),
        "控场层": _number(layer_floor.get("控场层", 62.0)),
        "效应层": _number(layer_floor.get("效应层", 45.0)),
        "可信度层": vv_score,
        "CAE平台层": workbench_score,
        "论文生产层": score_by_name["论文生产"],
    }
    for layer in north_star.get("层级状态", ()) or ():
        if not isinstance(layer, Mapping):
            continue
        name = str(layer.get("层级", ""))
        score = layer_scores.get(name, 40.0)
        rows.append(
            {
                "层级": name,
                "英文": layer.get("英文", ""),
                "得分": _round(score),
                "状态": _score_status(score, config),
                "当前证据": layer.get("当前证据", ""),
                "下一步": layer.get("下一步", ""),
            }
        )
    return rows


def _blockers(dimensions: list[dict[str, Any]], data_import: Mapping[str, Any], paper_factory: Mapping[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for dimension in dimensions:
        for check in dimension["检查项"]:
            if not check["通过"] and check.get("严重度") in {"P0", "P1"}:
                rows.append(
                    {
                        "优先级": check["严重度"],
                        "维度": dimension["维度"],
                        "阻断项": check["项目"],
                        "证据": check["证据"],
                    }
                )
    audit = _mapping(data_import.get("vv_audit"))
    for item in audit.get("风险信号", ()) or ():
        rows.append(
            {
                "优先级": "P0" if "真实源链" in str(item) or "相位参考" in str(item) else "P1",
                "维度": "真实数据接入",
                "阻断项": str(item),
                "证据": "外部数据 V&V 审计",
            }
        )
    paper_artifacts = _mapping(_mapping(paper_factory).get("产物"))
    missing_paper_items = [
        label
        for label in ("引用库", "文献复现注册表", "统计审计JSON", "模板审计JSON", "LaTeX编译审计")
        if not Path(str(paper_artifacts.get(label, ""))).exists()
    ]
    if missing_paper_items:
        rows.append(
            {
                "优先级": "P1",
                "维度": "论文生产",
                "阻断项": "缺少 " + "、".join(missing_paper_items),
                "证据": "Paper Factory 产物审计",
            }
        )
    rows.append(
        {
            "优先级": "P1",
            "维度": "三维CAE工作台",
            "阻断项": "完整尺寸/旋转 Gizmo、多用户调度器和正式工程数据库仍未完成",
            "证据": "Workbench 文档门槛",
        }
    )
    dedup: dict[tuple[str, str, str], dict[str, Any]] = {}
    for row in rows:
        dedup[(row["优先级"], row["维度"], row["阻断项"])] = row
    return sorted(dedup.values(), key=lambda item: (item["优先级"], item["维度"], item["阻断项"]))


def _next_actions(blockers: list[dict[str, Any]], use_readiness: float, publication_readiness: float, config: Mapping[str, Any] | None = None) -> list[str]:
    cfg = _mapping(config or {})
    actions = [str(item) for item in cfg.get("next_actions", ())] or [
        "优先把 V3.0 Measurement Campaign 的真实源链、相位参考、仪器校准证书和授权数据血缘接入外部数据 V&V。",
        "把 Paper Factory 的外部 DOI、正式复现实验编号、真实授权数据证据链、目标期刊模板插件和 PDF 归档补齐。",
        "继续补齐三维 Workbench 的尺寸/旋转 Gizmo、正式工程数据库和任务调度器。",
    ]
    if use_readiness >= 70:
        actions.append("可以作为本地演示和预实验平台继续迭代，但正式课题/发文材料应绑定可复查外部数据。")
    if publication_readiness < 70 or any(item["优先级"] == "P0" for item in blockers):
        actions.append("正式投稿前不要把代理残差或归一化场强写成现实作用距离、器件阈值或毁伤结论。")
    return actions


def _conclusion(use_readiness: float, publication_readiness: float, blockers: list[dict[str, Any]]) -> str:
    has_p0 = any(item["优先级"] == "P0" for item in blockers)
    if use_readiness >= 75 and publication_readiness >= 70 and not has_p0:
        return "可进入论文初稿和外部评审准备。"
    if use_readiness >= 65 and publication_readiness >= 55:
        return "可本地演示和预实验复现；正式发文仍需补真实数据闭环与论文级审计。"
    return "核心链路仍在预览阶段；优先补齐真实数据、三维交互和论文审计。"


def _dimension(name: str, score: float, checks: list[dict[str, Any]], scope: str, evidence: str, config: Mapping[str, Any] | None = None) -> dict[str, Any]:
    blockers = [item["项目"] for item in checks if not item["通过"]]
    return {
        "维度": name,
        "得分": _round(score),
        "状态": _score_status(score, config),
        "范围": scope,
        "证据摘要": evidence,
        "检查项": checks,
        "阻断项": blockers,
    }


def _check(name: str, passed: bool, evidence: Any, *, severity: str = "P2") -> dict[str, Any]:
    return {
        "项目": name,
        "通过": bool(passed),
        "证据": str(evidence),
        "严重度": severity,
    }


def _weighted_checks(
    checks: list[dict[str, Any]],
    weights: list[float],
    *,
    base_score: float | None = None,
    base_score_weight: float = 0.45,
) -> float:
    if len(checks) != len(weights):
        raise ValueError("checks and weights must have the same length")
    gate_score = sum((100.0 if item["通过"] else 0.0) * weight for item, weight in zip(checks, weights))
    if base_score is None:
        return _clamp(gate_score)
    base_weight = _clamp(base_score_weight) / 100.0 if base_score_weight > 1 else max(0.0, min(1.0, base_score_weight))
    return _clamp((1.0 - base_weight) * gate_score + base_weight * base_score)


def _weighted_average(items: list[tuple[float, float]]) -> float:
    total_weight = sum(weight for _, weight in items)
    if total_weight <= 0:
        return 0.0
    return _round(sum(score * weight for score, weight in items) / total_weight)


def _weighted_dimension_score(dimensions: list[dict[str, Any]], config: Mapping[str, Any], key: str) -> float:
    weights = _mapping(_mapping(config.get("summary_weights")).get(key))
    by_name = {str(item["维度"]): float(item["得分"]) for item in dimensions}
    return _weighted_average([(by_name.get(str(name), 0.0), _number(weight)) for name, weight in weights.items()])


def _apply_score_caps(scores: dict[str, float], blockers: list[dict[str, Any]], config: Mapping[str, Any]) -> dict[str, float]:
    capped = dict(scores)
    if any(item.get("优先级") == "P0" for item in blockers):
        caps = _mapping(config.get("caps"))
        if "publication_readiness_if_p0" in caps:
            capped["发文准备度/%"] = min(capped["发文准备度/%"], _number(caps["publication_readiness_if_p0"]))
        if "platform_maturity_if_p0" in caps:
            capped["平台成熟度/%"] = min(capped["平台成熟度/%"], _number(caps["platform_maturity_if_p0"]))
    return {key: _round(value) for key, value in capped.items()}


def _check_weights(config: Mapping[str, Any], dimension_name: str, checks: list[dict[str, Any]]) -> list[float]:
    gates = _mapping(_mapping(_mapping(config.get("dimension_weights")).get(dimension_name)).get("gates"))
    weights = [_number(gates.get(item["项目"])) for item in checks]
    total = sum(weights)
    if total <= 0:
        return [1.0 / len(checks)] * len(checks)
    return [weight / total for weight in weights]


def _dimension_base_score_weight(config: Mapping[str, Any], dimension_name: str, default: float) -> float:
    return _number(_mapping(_mapping(config.get("dimension_weights")).get(dimension_name)).get("base_score", default))


def _threshold(config: Mapping[str, Any], key: str, default: float) -> float:
    return _number(_mapping(config.get("thresholds")).get(key, default))


def _score_status(score: float, config: Mapping[str, Any] | None = None) -> str:
    cfg = _mapping(config or {})
    if score >= _threshold(cfg, "accept", 85):
        return "可验收"
    if score >= _threshold(cfg, "demo", 70):
        return "可演示"
    if score >= _threshold(cfg, "preview", 55):
        return "预览可用"
    return "待补齐"


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _number(value: Any) -> float:
    try:
        if value is None or value == "":
            return 0.0
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _clamp(value: float) -> float:
    return max(0.0, min(100.0, float(value)))


def _round(value: float) -> float:
    return round(_clamp(value), 2)


def _safe_read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return ""


def _write_dimension_csv(path: Path, dimensions: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=["维度", "得分", "状态", "证据摘要", "阻断项"],
        )
        writer.writeheader()
        for item in dimensions:
            writer.writerow(
                {
                    "维度": item["维度"],
                    "得分": item["得分"],
                    "状态": item["状态"],
                    "证据摘要": item["证据摘要"],
                    "阻断项": "；".join(item["阻断项"]),
                }
            )

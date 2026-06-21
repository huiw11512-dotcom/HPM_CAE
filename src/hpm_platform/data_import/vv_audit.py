"""External-data V&V audit preview for V3.0 data import.

The audit propagates imported measurement uncertainty and model residuals into
a separate credibility preview.  It deliberately does not overwrite the V2.0A
core credibility score until real source-chain and phase-reference evidence is
available.
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any

import numpy as np

from hpm_platform.data_import.evidence_chain import (
    evidence_source_chain_ready,
    generate_evidence_chain_report,
)
from hpm_platform.data_import.importers import DataImportService, DEFAULT_OUTPUT
from hpm_platform.data_import.model_comparison import generate_model_comparison_report
from hpm_platform.validation.vv_metrics import bounded_score, grade_from_score


EXTERNAL_VV_OUTPUT_NAME = "external_data_vv_audit.json"
MIN_AUDIT_SAMPLES = 3
TARGET_2SIGMA_COVERAGE_PERCENT = 95.0
TARGET_RELATIVE_RMSE_PERCENT = 10.0


def generate_external_data_vv_audit(
    project_path: str | Path,
    output_dir: str | Path = DEFAULT_OUTPUT,
    service: DataImportService | None = None,
    *,
    base_credibility_score: float | None = None,
    maximum_evaluations: int = 24,
) -> dict[str, Any]:
    """Generate an auditable external-data V&V preview report."""
    output_root = Path(output_dir)
    report_path = output_root / "data_import_v30" / EXTERNAL_VV_OUTPUT_NAME
    report_path.parent.mkdir(parents=True, exist_ok=True)
    data_import = service or DataImportService(output_root)
    blockers: list[str] = []
    comparison: dict[str, Any] = {}
    evidence: dict[str, Any] = {}

    try:
        evidence = generate_evidence_chain_report(output_root)
        comparison = generate_model_comparison_report(
            project_path,
            output_root,
            data_import,
            maximum_evaluations=maximum_evaluations,
        )
        audit = build_external_data_vv_audit(
            comparison,
            evidence_report=evidence,
            base_credibility_score=base_credibility_score,
            output_file=report_path,
        )
    except Exception as exc:  # pragma: no cover - defensive report shape.
        blockers.append(str(exc))
        audit = _blocked_audit(
            blockers=blockers,
            comparison=comparison,
            evidence_report=evidence,
            base_credibility_score=base_credibility_score,
            output_file=report_path,
        )

    report_path.write_text(json.dumps(audit, ensure_ascii=False, indent=2), encoding="utf-8")
    return audit


def build_external_data_vv_audit(
    comparison: dict[str, Any],
    *,
    evidence_report: dict[str, Any] | None = None,
    base_credibility_score: float | None = None,
    output_file: str | Path | None = None,
) -> dict[str, Any]:
    """Build the external-data V&V audit from a model-comparison report."""
    sample_count = int(comparison.get("样本数") or 0)
    passed_comparison = bool(comparison.get("通过"))
    residual = comparison.get("误差对比") if isinstance(comparison.get("误差对比"), dict) else {}
    coverage = comparison.get("不确定度覆盖率") if isinstance(comparison.get("不确定度覆盖率"), dict) else {}
    source_chain_ready = evidence_source_chain_ready(evidence_report) or _gate_passed(comparison, "真实源链与相位参考已接入")

    relative_rmse = _float_or_none(residual.get("标定后相对RMSE/%"))
    two_sigma_coverage = _float_or_none(coverage.get("2sigma覆盖率/%"))
    median_normalized = _float_or_none(coverage.get("中位归一化残差"))

    execution_score = 15.0 if passed_comparison and sample_count >= MIN_AUDIT_SAMPLES else 0.0
    source_chain_score = 20.0 if source_chain_ready else 0.0
    sample_score = 15.0 * min(sample_count / 10.0, 1.0)
    residual_score = 25.0 * (
        bounded_score(relative_rmse, TARGET_RELATIVE_RMSE_PERCENT)
        if relative_rmse is not None
        else 0.0
    )
    coverage_score = 25.0 * (
        min(max(two_sigma_coverage, 0.0), TARGET_2SIGMA_COVERAGE_PERCENT) / TARGET_2SIGMA_COVERAGE_PERCENT
        if two_sigma_coverage is not None
        else 0.0
    )
    preview_score = round(float(execution_score + source_chain_score + sample_score + residual_score + coverage_score), 2)
    formal_eligible = bool(
        passed_comparison
        and source_chain_ready
        and sample_count >= MIN_AUDIT_SAMPLES
        and relative_rmse is not None
        and relative_rmse <= TARGET_RELATIVE_RMSE_PERCENT
        and two_sigma_coverage is not None
        and two_sigma_coverage >= TARGET_2SIGMA_COVERAGE_PERCENT
    )
    risk_adjusted = _risk_adjusted_score(base_credibility_score, preview_score, formal_eligible)
    gates = _audit_gates(
        passed_comparison=passed_comparison,
        sample_count=sample_count,
        source_chain_ready=source_chain_ready,
        relative_rmse=relative_rmse,
        two_sigma_coverage=two_sigma_coverage,
    )
    audit = {
        "版本": "V3.0-preview",
        "名称": "外部数据 V&V 可信度审计",
        "通过": bool(formal_eligible),
        "可纳入正式可信度评分": bool(formal_eligible),
        "样例ID": comparison.get("样例ID"),
        "样本数": sample_count,
        "预评分": preview_score,
        "预评分等级": grade_from_score(preview_score),
        "分项得分": {
            "报告执行": round(execution_score, 2),
            "样本规模": round(sample_score, 2),
            "残差质量": round(residual_score, 2),
            "不确定度覆盖": round(coverage_score, 2),
            "真实源链与相位参考": round(source_chain_score, 2),
        },
        "关键指标": {
            "标定后相对RMSE/%": relative_rmse,
            "2sigma覆盖率/%": two_sigma_coverage,
            "中位归一化残差": median_normalized,
            "标定后P95残差": _float_or_none(residual.get("标定后P95残差")),
        },
        "正式评分策略": {
            "当前V2.0A核心评分": _float_or_none(base_credibility_score),
            "风险调整预览评分": risk_adjusted,
            "是否改写正式评分": bool(formal_eligible),
            "说明": (
                "真实源链、相位参考、残差阈值和不确定度覆盖均满足门槛后，"
                "外部数据审计才允许进入正式可信度评分。当前不满足时仅作为风险附注。"
            ),
        },
        "风险信号": _risk_signals(
            sample_count=sample_count,
            source_chain_ready=source_chain_ready,
            relative_rmse=relative_rmse,
            two_sigma_coverage=two_sigma_coverage,
            median_normalized=median_normalized,
            comparison=comparison,
            evidence_report=evidence_report,
        ),
        "门槛": gates,
        "证据链审计": _evidence_summary(evidence_report),
        "输入报告": comparison.get("输出文件"),
        "输出文件": str(Path(output_file).resolve()) if output_file else None,
        "安全边界": (
            "外部数据 V&V 审计只传播归一化测量样本的残差和不确定度风险；"
            "未接入真实源链、相位参考和授权外部数据复核前，不输出真实效应结论，"
            "也不改写 V2.0A 核心可信度评分。"
        ),
        "生成时间UTC": datetime.now(timezone.utc).isoformat(),
    }
    return audit


def _blocked_audit(
    *,
    blockers: list[str],
    comparison: dict[str, Any],
    evidence_report: dict[str, Any],
    base_credibility_score: float | None,
    output_file: Path,
) -> dict[str, Any]:
    return {
        "版本": "V3.0-preview",
        "名称": "外部数据 V&V 可信度审计",
        "通过": False,
        "可纳入正式可信度评分": False,
        "样例ID": comparison.get("样例ID"),
        "样本数": int(comparison.get("样本数") or 0),
        "预评分": 0.0,
        "预评分等级": "D",
        "分项得分": {},
        "关键指标": {},
        "正式评分策略": {
            "当前V2.0A核心评分": _float_or_none(base_credibility_score),
            "风险调整预览评分": _float_or_none(base_credibility_score),
            "是否改写正式评分": False,
            "说明": "外部数据审计未能完成，保留 V2.0A 核心评分并记录阻断项。",
        },
        "风险信号": [f"外部数据审计阻断：{item}" for item in blockers],
        "门槛": [{"项目": "外部数据 V&V 审计可执行", "通过": False}],
        "证据链审计": _evidence_summary(evidence_report),
        "输入报告": comparison.get("输出文件"),
        "输出文件": str(output_file.resolve()),
        "阻断项": blockers,
        "安全边界": "外部数据审计阻断时不进入正式可信度评分。",
        "生成时间UTC": datetime.now(timezone.utc).isoformat(),
    }


def _audit_gates(
    *,
    passed_comparison: bool,
    sample_count: int,
    source_chain_ready: bool,
    relative_rmse: float | None,
    two_sigma_coverage: float | None,
) -> list[dict[str, Any]]:
    return [
        {"项目": "模型误差对比报告可执行", "通过": bool(passed_comparison)},
        {"项目": f"样本数不少于{MIN_AUDIT_SAMPLES}", "通过": sample_count >= MIN_AUDIT_SAMPLES},
        {
            "项目": f"标定后相对RMSE不超过{TARGET_RELATIVE_RMSE_PERCENT:g}%",
            "通过": bool(relative_rmse is not None and relative_rmse <= TARGET_RELATIVE_RMSE_PERCENT),
        },
        {
            "项目": f"2sigma覆盖率不低于{TARGET_2SIGMA_COVERAGE_PERCENT:g}%",
            "通过": bool(two_sigma_coverage is not None and two_sigma_coverage >= TARGET_2SIGMA_COVERAGE_PERCENT),
        },
        {"项目": "真实源链与相位参考已接入", "通过": bool(source_chain_ready)},
        {"项目": "当前结果仅作为预览风险附注", "通过": True},
    ]


def _risk_signals(
    *,
    sample_count: int,
    source_chain_ready: bool,
    relative_rmse: float | None,
    two_sigma_coverage: float | None,
    median_normalized: float | None,
    comparison: dict[str, Any],
    evidence_report: dict[str, Any] | None = None,
) -> list[str]:
    signals: list[str] = []
    if not source_chain_ready:
        if evidence_report:
            failed = [
                str(item.get("项目"))
                for item in evidence_report.get("阻断项", ())
                if isinstance(item, dict) and item.get("严重度") == "P0"
            ]
            detail = "；".join(failed) if failed else "证据链未通过"
            signals.append(f"真实源链与相位参考未接入：{detail}。")
        else:
            signals.append("真实源链与相位参考未接入，不能作为实测闭环标定结论。")
    if sample_count < 10:
        signals.append(f"样本数为 {sample_count}，只能支撑接口级预览，统计外推能力不足。")
    if relative_rmse is None:
        signals.append("缺少标定后相对RMSE，无法评价模型残差质量。")
    elif relative_rmse > TARGET_RELATIVE_RMSE_PERCENT:
        signals.append(
            f"标定后相对RMSE为 {relative_rmse:.2f}%，高于 {TARGET_RELATIVE_RMSE_PERCENT:g}% 预览门槛。"
        )
    if two_sigma_coverage is None:
        signals.append("缺少 2sigma 覆盖率，测量不确定度尚未形成可量化评分输入。")
    elif two_sigma_coverage < TARGET_2SIGMA_COVERAGE_PERCENT:
        signals.append(
            f"2sigma 覆盖率为 {two_sigma_coverage:.2f}%，低于 {TARGET_2SIGMA_COVERAGE_PERCENT:g}% 门槛。"
        )
    if median_normalized is not None and median_normalized > 2.0:
        signals.append(f"中位归一化残差为 {median_normalized:.2f}，显示代理模型与导入样本不匹配。")
    if "代理激励" in str(comparison.get("安全边界", "")):
        signals.append("当前误差对比使用代理激励，不能解释为硬件源功率或效应标定。")
    return signals or ["未发现外部数据审计风险信号。"]


def _evidence_summary(evidence_report: dict[str, Any] | None) -> dict[str, Any]:
    if not evidence_report:
        return {"通过": False, "说明": "未生成外部数据证据链审计。"}
    return {
        "版本": evidence_report.get("版本"),
        "通过": bool(evidence_report.get("通过")),
        "真实源链与相位参考已接入": bool(evidence_report.get("真实源链与相位参考已接入")),
        "可纳入正式可信度评分证据": bool(evidence_report.get("可纳入正式可信度评分证据")),
        "阻断项": [
            item.get("项目")
            for item in evidence_report.get("阻断项", ())
            if isinstance(item, dict)
        ],
        "输出文件": evidence_report.get("输出文件"),
    }


def _risk_adjusted_score(
    base_score: float | None,
    preview_score: float,
    formal_eligible: bool,
) -> float | None:
    base = _float_or_none(base_score)
    if base is None:
        return None
    if not formal_eligible:
        return round(base, 2)
    return round(float(np.clip(0.85 * base + 0.15 * preview_score, 0.0, 100.0)), 2)


def _gate_passed(report: dict[str, Any], name: str) -> bool:
    for item in report.get("门槛", []):
        if isinstance(item, dict) and item.get("项目") == name:
            return bool(item.get("通过"))
    return False


def _float_or_none(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if np.isfinite(number) else None

"""V2.0A 可信度评分与通用指标工具。"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np

from hpm_platform.validation.analytic_cases import CaseResult


@dataclass(frozen=True)
class CredibilityScore:
    analytic_score: float
    benchmark_score: float
    uncertainty_score: float
    backend_score: float
    total_score: float
    grade: str
    explanation: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "解析验证得分": round(self.analytic_score, 2),
            "基准复现得分": round(self.benchmark_score, 2),
            "不确定度覆盖得分": round(self.uncertainty_score, 2),
            "后端适用性得分": round(self.backend_score, 2),
            "可信度评分": round(self.total_score, 2),
            "当前等级": self.grade,
            "解释": self.explanation,
        }


def bounded_score(value: float, threshold: float, *, lower_is_better: bool = True) -> float:
    """把单个指标映射到 0..1，阈值处给 0.7 分。"""

    if not np.isfinite(value) or not np.isfinite(threshold) or threshold <= 0:
        return 0.0
    ratio = value / threshold if lower_is_better else threshold / max(value, np.finfo(float).tiny)
    if lower_is_better:
        if ratio <= 0.1:
            return 1.0
        if ratio <= 1.0:
            return float(1.0 - (ratio - 0.1) * (0.3 / 0.9))
        return float(max(0.0, 0.7 * np.exp(-(ratio - 1.0))))
    if ratio >= 10.0:
        return 1.0
    if ratio >= 1.0:
        return float(0.7 + 0.3 * (ratio - 1.0) / 9.0)
    return float(max(0.0, 0.7 * ratio))


def grade_from_score(score: float) -> str:
    if score >= 90.0:
        return "A"
    if score >= 80.0:
        return "B"
    if score >= 70.0:
        return "C"
    return "D"


def compute_credibility_score(
    cases: list[CaseResult],
    uncertainty_summary: dict[str, Any],
    sensitivity_summary: dict[str, Any] | None = None,
) -> CredibilityScore:
    analytic_cases = [case for case in cases if case.category == "解析解验证"]
    benchmark_cases = [case for case in cases if case.category == "算法基准验证"]
    backend_cases = [case for case in cases if case.category == "后端一致性验证"]

    analytic_score = 35.0 * _case_group_score(analytic_cases)
    benchmark_score = 25.0 * _case_group_score(benchmark_cases)
    backend_score = 20.0 * _case_group_score(backend_cases)

    ci_width = float(uncertainty_summary.get("峰值偏差95%CI宽度", 1.0))
    reproducible = bool(uncertainty_summary.get("固定随机种子可复现", False))
    ci_component = bounded_score(ci_width, 0.025)
    seed_component = 1.0 if reproducible else 0.0
    sensitivity_component = 1.0 if sensitivity_summary and sensitivity_summary.get("排序可用", False) else 0.8
    uncertainty_score = 20.0 * (0.55 * ci_component + 0.25 * seed_component + 0.20 * sensitivity_component)

    total = analytic_score + benchmark_score + uncertainty_score + backend_score
    grade = grade_from_score(total)
    explanation = (
        "评分由解析验证、算法基准、不确定度覆盖和后端适用性四部分组成；"
        "当前结果仅代表归一化公开数值模型的可信度。"
    )
    return CredibilityScore(
        analytic_score=analytic_score,
        benchmark_score=benchmark_score,
        uncertainty_score=uncertainty_score,
        backend_score=backend_score,
        total_score=total,
        grade=grade,
        explanation=explanation,
    )


def _case_group_score(cases: list[CaseResult]) -> float:
    if not cases:
        return 0.0
    values: list[float] = []
    for case in cases:
        if not case.passed:
            values.append(0.45)
            continue
        local_scores: list[float] = []
        for metric_name, threshold in case.thresholds.items():
            if metric_name in case.metrics and isinstance(threshold, (int, float)):
                local_scores.append(bounded_score(float(case.metrics[metric_name]), float(threshold)))
        values.append(float(np.mean(local_scores)) if local_scores else 1.0)
    return float(np.mean(values))


def summarize_cases(cases: list[CaseResult]) -> dict[str, Any]:
    total = len(cases)
    passed = sum(1 for case in cases if case.passed)
    return {
        "总测试数": total,
        "通过数": passed,
        "失败数": total - passed,
        "通过率": 100.0 * passed / max(total, 1),
    }

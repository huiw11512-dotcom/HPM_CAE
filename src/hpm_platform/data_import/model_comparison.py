"""Preview model-vs-imported-data error comparison for V3.0 data import.

This layer turns the imported Measurement Campaign bridge into an auditable
error table with uncertainty coverage.  It still uses proxy excitation and
therefore remains a V&V preview, not a real measurement calibration claim.
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any

import numpy as np

from hpm_platform.data_import.calibration_bridge import (
    BRIDGE_SAFETY_BOUNDARY,
    DEFAULT_MEASUREMENT_SAMPLE_ID,
    ImportedCalibrationPayload,
    build_imported_calibration_samples,
)
from hpm_platform.data_import.importers import DataImportService, DEFAULT_OUTPUT
from hpm_platform.ui.project_model import CAEProject
from hpm_platform.validation.backend_calibration import calibrate_backend_scales


MODEL_COMPARISON_OUTPUT_NAME = "model_comparison_report.json"
MODEL_COMPARISON_SAFETY_BOUNDARY = (
    f"{BRIDGE_SAFETY_BOUNDARY} 模型误差对比使用代理激励和归一化复场残差，"
    "只用于 V3.0 数据闭环接口审计；不代表真实实验误差、真实硬件标定或效应结论。"
)


def generate_model_comparison_report(
    project_path: str | Path,
    output_dir: str | Path = DEFAULT_OUTPUT,
    service: DataImportService | None = None,
    *,
    sample_id: str = DEFAULT_MEASUREMENT_SAMPLE_ID,
    maximum_evaluations: int = 24,
) -> dict[str, Any]:
    """Generate a preview error-comparison report for imported field samples."""
    output_root = Path(output_dir)
    report_path = output_root / "data_import_v30" / MODEL_COMPARISON_OUTPUT_NAME
    report_path.parent.mkdir(parents=True, exist_ok=True)
    data_import = service or DataImportService(output_root)
    blockers: list[str] = []
    payload: ImportedCalibrationPayload | None = None
    summary: dict[str, Any] = {}
    coverage: dict[str, Any] = {}
    point_rows: list[dict[str, Any]] = []

    try:
        project = CAEProject.load_yaml(project_path)
        samples, payload = build_imported_calibration_samples(
            project,
            data_import,
            sample_id=sample_id,
        )
        result = calibrate_backend_scales(
            project,
            samples=samples,
            candidate_backend=project.propagation.backend,
            initial_scales=(0.55, 0.35, 0.35),
            maximum_evaluations=int(maximum_evaluations),
        )
        sigma = _combined_uncertainty_sigma(payload)
        after_residual = np.abs(result.fitted_field - result.reference_field)
        before_residual = np.abs(result.initial_field - result.reference_field)
        summary = _summary_dict(before_residual, after_residual, result)
        coverage = _coverage_dict(after_residual, sigma)
        point_rows = _point_rows(payload, result.reference_field, result.fitted_field, after_residual, sigma)
    except Exception as exc:  # pragma: no cover - report shape handles failures.
        blockers.append(str(exc))

    executable = payload is not None and bool(summary) and not blockers
    report = {
        "版本": "V3.0-preview",
        "名称": "导入数据模型误差对比预览",
        "通过": bool(executable),
        "样例ID": sample_id,
        "样本数": int(payload.points_lambda.shape[0]) if payload else 0,
        "比较对象": "Measurement Campaign 归一化复场 vs 当前工程代理激励降阶传播模型",
        "误差对比": summary,
        "不确定度覆盖率": coverage,
        "逐点残差": point_rows,
        "门槛": _gates(payload, executable, coverage),
        "阻断项": blockers,
        "安全边界": MODEL_COMPARISON_SAFETY_BOUNDARY,
        "输出文件": str(report_path.resolve()),
        "生成时间UTC": datetime.now(timezone.utc).isoformat(),
    }
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def _combined_uncertainty_sigma(payload: ImportedCalibrationPayload) -> np.ndarray | None:
    field = np.asarray(payload.reference_field, complex).reshape(-1)
    amplitude = payload.amplitude_sigma_norm
    phase = payload.phase_sigma_deg
    if amplitude is None and phase is None:
        return None
    amp = (
        np.asarray(amplitude, float).reshape(-1)
        if amplitude is not None
        else np.zeros(field.size, dtype=float)
    )
    phase_rad = (
        np.deg2rad(np.asarray(phase, float).reshape(-1))
        if phase is not None
        else np.zeros(field.size, dtype=float)
    )
    if amp.size != field.size or phase_rad.size != field.size:
        return None
    sigma = np.sqrt(np.maximum(amp, 0.0) ** 2 + (np.abs(field) * np.maximum(phase_rad, 0.0)) ** 2)
    return np.maximum(sigma, 1e-12)


def _summary_dict(before: np.ndarray, after: np.ndarray, result: Any) -> dict[str, Any]:
    return {
        "待比较后端": result.candidate_backend,
        "求解成功": bool(result.success),
        "迭代次数": int(result.iterations),
        "标定前RMSE": round(float(result.rmse_before), 8),
        "标定后RMSE": round(float(result.rmse_after), 8),
        "标定前相对RMSE/%": round(float(result.relative_rmse_before_percent), 4),
        "标定后相对RMSE/%": round(float(result.relative_rmse_after_percent), 4),
        "RMSE改善/%": round(float(result.improvement_percent), 4),
        "标定前MAE": round(float(np.mean(before)), 8),
        "标定后MAE": round(float(np.mean(after)), 8),
        "标定后P95残差": round(float(np.percentile(after, 95)), 8),
        "标定后最大残差": round(float(np.max(after)), 8),
        "拟合尺度": [round(float(item), 6) for item in result.fitted_scales],
    }


def _coverage_dict(residual: np.ndarray, sigma: np.ndarray | None) -> dict[str, Any]:
    if sigma is None:
        return {
            "不确定度可用": False,
            "1sigma覆盖率/%": None,
            "2sigma覆盖率/%": None,
            "中位归一化残差": None,
            "说明": "导入样本缺少可量化的不确定度字段。",
        }
    normalized = residual / sigma
    return {
        "不确定度可用": True,
        "1sigma覆盖率/%": round(100.0 * float(np.mean(normalized <= 1.0)), 2),
        "2sigma覆盖率/%": round(100.0 * float(np.mean(normalized <= 2.0)), 2),
        "中位归一化残差": round(float(np.median(normalized)), 4),
        "最大归一化残差": round(float(np.max(normalized)), 4),
        "说明": "覆盖率基于导入样本的幅度/相位 1-sigma 字段和代理模型残差。",
    }


def _point_rows(
    payload: ImportedCalibrationPayload,
    reference: np.ndarray,
    fitted: np.ndarray,
    residual: np.ndarray,
    sigma: np.ndarray | None,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    normalized = residual / sigma if sigma is not None else np.full(residual.size, np.nan)
    for index, (point, ref, fit, err) in enumerate(
        zip(payload.points_lambda, reference, fitted, residual, strict=False),
        start=1,
    ):
        item = {
            "序号": index,
            "x_lambda": round(float(point[0]), 6),
            "y_lambda": round(float(point[1]), 6),
            "z_lambda": round(float(point[2]), 6),
            "参考幅值": round(float(abs(ref)), 6),
            "模型幅值": round(float(abs(fit)), 6),
            "复场残差": round(float(err), 8),
        }
        if sigma is not None:
            item["合成sigma"] = round(float(sigma[index - 1]), 8)
            item["归一化残差"] = round(float(normalized[index - 1]), 4)
            item["2sigma内"] = bool(normalized[index - 1] <= 2.0)
        rows.append(item)
    return rows


def _gates(
    payload: ImportedCalibrationPayload | None,
    executable: bool,
    coverage: dict[str, Any],
) -> list[dict[str, Any]]:
    return [
        {"项目": "导入复场样本可比较", "通过": bool(payload is not None and payload.reference_field.size > 0)},
        {"项目": "坐标已规范化为 lambda", "通过": bool(payload is not None and payload.points_lambda.shape[1] == 3)},
        {"项目": "测量不确定度可用于覆盖率审计", "通过": bool(coverage.get("不确定度可用"))},
        {"项目": "代理模型误差对比已执行", "通过": bool(executable)},
        {"项目": "真实源链与相位参考已接入", "通过": False},
    ]

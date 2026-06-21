"""Bridge imported V3.0 measurement samples into V&V calibration previews.

The bridge proves data-shape compatibility with ``CalibrationSamples``.  It
uses proxy excitation from the current normalized CAE project and must not be
read as a real source-power, hardware-threshold, range, or effect calibration.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import io
import json
from pathlib import Path
import zipfile
from typing import Any

import numpy as np
import pandas as pd

from hpm_platform.data_import.importers import (
    DataImportService,
    DEFAULT_OUTPUT,
    MEASUREMENT_INFO_FILES,
    SAFETY_BOUNDARY,
)
from hpm_platform.ui.project_model import CAEProject
from hpm_platform.validation.backend_calibration import (
    CalibrationSamples,
    calibrate_backend_scales,
    generate_reference_samples,
)


DEFAULT_MEASUREMENT_SAMPLE_ID = "V30-MEASUREMENT-CAMPAIGN"
BRIDGE_OUTPUT_NAME = "calibration_bridge_report.json"
BRIDGE_SAFETY_BOUNDARY = (
    f"{SAFETY_BOUNDARY} 标定桥接仅验证导入归一化复场样本可进入 "
    "CalibrationSamples，并使用当前工程生成的代理激励做 smoke preview；"
    "不推断真实源功率、器件阈值、现实作用距离或真实毁伤概率。"
)


@dataclass(frozen=True)
class ImportedCalibrationPayload:
    sample_id: str
    source_path: Path
    metadata: dict[str, Any]
    csv_name: str
    points_lambda: np.ndarray
    reference_field: np.ndarray
    coordinate_unit: str
    reference_frequency_ghz: float | None
    uncertainty_columns: tuple[str, ...]
    amplitude_sigma_norm: np.ndarray | None = None
    phase_sigma_deg: np.ndarray | None = None


def build_imported_calibration_samples(
    project: CAEProject,
    service: DataImportService,
    *,
    sample_id: str = DEFAULT_MEASUREMENT_SAMPLE_ID,
) -> tuple[CalibrationSamples, ImportedCalibrationPayload]:
    """Load a normalized Measurement Campaign sample into CalibrationSamples."""
    payload = _load_measurement_payload(service, sample_id=sample_id)
    proxy = generate_reference_samples(
        project,
        reference_backend=project.propagation.backend,
        samples_per_axis=9,
        noise_std_fraction=0.0,
    )
    samples = CalibrationSamples(
        points_lambda=payload.points_lambda,
        reference_field=payload.reference_field,
        excitation=proxy.excitation,
        reference_backend="imported_measurement_preview",
        reference_scales=(
            float(project.propagation.direct_path_scale),
            float(project.propagation.reflection_scale),
            float(project.propagation.cavity_scale),
        ),
    )
    return samples, payload


def generate_calibration_bridge_report(
    project_path: str | Path,
    output_dir: str | Path = DEFAULT_OUTPUT,
    service: DataImportService | None = None,
    *,
    sample_id: str = DEFAULT_MEASUREMENT_SAMPLE_ID,
    maximum_evaluations: int = 24,
) -> dict[str, Any]:
    """Generate a preview report proving imported samples can reach calibration."""
    output_root = Path(output_dir)
    report_path = output_root / "data_import_v30" / BRIDGE_OUTPUT_NAME
    report_path.parent.mkdir(parents=True, exist_ok=True)
    data_import = service or DataImportService(output_root)
    blockers: list[str] = []
    calibration_preview: dict[str, Any] = {"执行": False}
    samples_compatible = False
    imported: ImportedCalibrationPayload | None = None

    try:
        project = CAEProject.load_yaml(project_path)
        samples, imported = build_imported_calibration_samples(
            project,
            data_import,
            sample_id=sample_id,
        )
        samples_compatible = True
        result = calibrate_backend_scales(
            project,
            samples=samples,
            candidate_backend=project.propagation.backend,
            initial_scales=(0.55, 0.35, 0.35),
            maximum_evaluations=int(maximum_evaluations),
        )
        calibration_preview = {
            "执行": True,
            "用途": "代理激励 smoke preview，不是真实测量标定结论",
            "待标定后端": result.candidate_backend,
            "求解成功": bool(result.success),
            "迭代次数": int(result.iterations),
            "初始尺度": [round(float(item), 6) for item in result.initial_scales],
            "拟合尺度": [round(float(item), 6) for item in result.fitted_scales],
            "标定前RMSE": round(float(result.rmse_before), 8),
            "标定后RMSE": round(float(result.rmse_after), 8),
            "标定前相对RMSE/%": round(float(result.relative_rmse_before_percent), 4),
            "标定后相对RMSE/%": round(float(result.relative_rmse_after_percent), 4),
            "RMSE改善/%": round(float(result.improvement_percent), 4),
            "求解信息": result.message,
        }
    except Exception as exc:  # pragma: no cover - exercised through report shape.
        blockers.append(str(exc))

    passed = samples_compatible and bool(calibration_preview.get("执行")) and not blockers
    report = {
        "版本": "V3.0-preview",
        "名称": "导入数据 V&V 标定桥接预览",
        "通过": bool(passed),
        "样例ID": sample_id,
        "导入源文件": str(imported.source_path) if imported else None,
        "CSV条目": imported.csv_name if imported else None,
        "样本数": int(imported.points_lambda.shape[0]) if imported else 0,
        "坐标来源单位": imported.coordinate_unit if imported else None,
        "目标坐标": "lambda",
        "参考频率GHz": imported.reference_frequency_ghz if imported else None,
        "CalibrationSamples兼容": bool(samples_compatible),
        "代理激励": "使用当前 CAEProject 传播后端生成 focus_weights 代理激励，仅用于接口 smoke preview。",
        "不确定度字段": list(imported.uncertainty_columns) if imported else [],
        "规范化预览": _preview(imported) if imported else [],
        "标定预览": calibration_preview,
        "阻断项": blockers,
        "安全边界": BRIDGE_SAFETY_BOUNDARY,
        "输出文件": str(report_path.resolve()),
        "生成时间UTC": datetime.now(timezone.utc).isoformat(),
    }
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def _load_measurement_payload(
    service: DataImportService,
    *,
    sample_id: str,
) -> ImportedCalibrationPayload:
    dataset = service.inspect_sample(sample_id)
    source = Path(str(dataset["源文件"]))
    metadata, csv_name, frame = _read_measurement_campaign(source)
    points_lambda, unit, reference_frequency = _points_lambda(frame, metadata)
    reference_field = _reference_field(frame)
    amplitude_sigma = _optional_uncertainty_array(
        frame,
        "amplitude_sigma_norm",
        metadata,
        "amplitude_sigma_norm",
        reference_field.size,
    )
    phase_sigma = _optional_uncertainty_array(
        frame,
        "phase_sigma_deg",
        metadata,
        "phase_sigma_deg",
        reference_field.size,
    )
    uncertainty = tuple(
        str(col)
        for col in frame.columns
        if "sigma" in str(col).lower() or "uncertainty" in str(col).lower()
    )
    if points_lambda.shape[0] != reference_field.size:
        raise ValueError("导入坐标数量与复场样本数量不一致")
    if points_lambda.shape[0] < 3:
        raise ValueError("标定桥接至少需要 3 个归一化复场样本")
    return ImportedCalibrationPayload(
        sample_id=sample_id,
        source_path=source,
        metadata=metadata,
        csv_name=csv_name,
        points_lambda=points_lambda,
        reference_field=reference_field,
        coordinate_unit=unit,
        reference_frequency_ghz=reference_frequency,
        uncertainty_columns=uncertainty,
        amplitude_sigma_norm=amplitude_sigma,
        phase_sigma_deg=phase_sigma,
    )


def _read_measurement_campaign(source: Path) -> tuple[dict[str, Any], str, pd.DataFrame]:
    if source.is_dir():
        return _read_measurement_directory(source)
    if source.suffix.lower() == ".zip" and zipfile.is_zipfile(source):
        return _read_measurement_zip(source)
    raise ValueError(f"测量批次必须是目录或 zip：{source}")


def _read_measurement_directory(source: Path) -> tuple[dict[str, Any], str, pd.DataFrame]:
    metadata_path = next((source / name for name in MEASUREMENT_INFO_FILES if (source / name).exists()), None)
    if metadata_path is None:
        raise ValueError("测量批次缺少 MEASUREMENT_CAMPAIGN.json")
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    csv_path = _preferred_csv_path(source, metadata)
    if csv_path is None:
        raise ValueError("测量批次缺少可桥接的近场 CSV")
    return metadata, str(csv_path.relative_to(source).as_posix()), pd.read_csv(csv_path)


def _read_measurement_zip(source: Path) -> tuple[dict[str, Any], str, pd.DataFrame]:
    with zipfile.ZipFile(source) as archive:
        names = [item.filename for item in archive.infolist() if not item.is_dir()]
        metadata_name = next(
            (name for name in names if Path(name).name in MEASUREMENT_INFO_FILES),
            None,
        )
        if metadata_name is None:
            raise ValueError("测量批次缺少 MEASUREMENT_CAMPAIGN.json")
        metadata = json.loads(archive.read(metadata_name).decode("utf-8"))
        csv_name = _preferred_csv_name(names, metadata)
        if csv_name is None:
            raise ValueError("测量批次缺少可桥接的近场 CSV")
        frame = pd.read_csv(io.StringIO(archive.read(csv_name).decode("utf-8")))
        return metadata, csv_name, frame


def _preferred_csv_path(source: Path, metadata: dict[str, Any]) -> Path | None:
    for candidate in _metadata_files(metadata):
        path = source / candidate
        if path.exists() and path.suffix.lower() == ".csv":
            return path
    csv_files = list(source.rglob("*.csv"))
    preferred = [path for path in csv_files if _looks_like_field_scan(path.as_posix())]
    return (preferred or csv_files or [None])[0]


def _preferred_csv_name(names: list[str], metadata: dict[str, Any]) -> str | None:
    available = {name.replace("\\", "/"): name for name in names}
    for candidate in _metadata_files(metadata):
        normalized = str(candidate).replace("\\", "/")
        if normalized in available and normalized.lower().endswith(".csv"):
            return available[normalized]
    csv_names = [name for name in names if name.lower().endswith(".csv")]
    preferred = [name for name in csv_names if _looks_like_field_scan(name)]
    return (preferred or csv_names or [None])[0]


def _metadata_files(metadata: dict[str, Any]) -> list[str]:
    files: list[str] = []
    for batch in metadata.get("batches", []):
        if isinstance(batch, dict) and batch.get("file"):
            files.append(str(batch["file"]))
    for item in metadata.get("exports", []):
        if isinstance(item, dict) and item.get("path"):
            files.append(str(item["path"]))
    return files


def _looks_like_field_scan(name: str) -> bool:
    lowered = name.lower()
    return any(token in lowered for token in ("near_field", "nearfield", "field", "scan"))


def _points_lambda(frame: pd.DataFrame, metadata: dict[str, Any]) -> tuple[np.ndarray, str, float | None]:
    columns = {str(col).lower(): str(col) for col in frame.columns}
    reference_frequency = _reference_frequency_ghz(metadata)
    for unit in ("lambda", "mm", "cm", "m"):
        keys = [f"x_{unit}", f"y_{unit}", f"z_{unit}"]
        if all(key in columns for key in keys):
            points = frame[[columns[key] for key in keys]].astype(float).to_numpy()
            if unit == "lambda":
                return points, unit, reference_frequency
            if reference_frequency is None:
                raise ValueError(f"{unit} 坐标缺少 reference_frequency_ghz，无法转换为 lambda")
            wavelength = {
                "mm": 299.792458 / reference_frequency,
                "cm": 29.9792458 / reference_frequency,
                "m": 0.299792458 / reference_frequency,
            }[unit]
            return points / wavelength, unit, reference_frequency
    raise ValueError("未找到 x/y/z 坐标列")


def _reference_field(frame: pd.DataFrame) -> np.ndarray:
    columns = {str(col).lower(): str(col) for col in frame.columns}
    for lowered, real_col in columns.items():
        if lowered.endswith("_real_norm") or lowered.endswith("_real"):
            prefix = lowered.rsplit("_real", 1)[0]
            imag_col = columns.get(f"{prefix}_imag_norm") or columns.get(f"{prefix}_imag")
            if imag_col:
                real = frame[real_col].astype(float).to_numpy()
                imag = frame[imag_col].astype(float).to_numpy()
                field = real + 1j * imag
                if not np.all(np.isfinite(field)):
                    raise ValueError("复场样本包含非有限值")
                return field
    raise ValueError("未找到可配对的归一化复场实部/虚部列")


def _optional_uncertainty_array(
    frame: pd.DataFrame,
    column_name: str,
    metadata: dict[str, Any],
    metadata_name: str,
    size: int,
) -> np.ndarray | None:
    columns = {str(col).lower(): str(col) for col in frame.columns}
    source = columns.get(column_name.lower())
    if source is not None:
        values = frame[source].astype(float).to_numpy()
        if values.size == size and np.all(np.isfinite(values)):
            return values
    uncertainty = metadata.get("uncertainty_model")
    if isinstance(uncertainty, dict):
        try:
            value = float(uncertainty.get(metadata_name))
        except (TypeError, ValueError):
            value = float("nan")
        if np.isfinite(value) and value >= 0:
            return np.full(size, value, dtype=float)
    return None


def _reference_frequency_ghz(metadata: dict[str, Any]) -> float | None:
    for key in (
        "reference_frequency_ghz",
        "frequency_ghz",
        "center_frequency_ghz",
        "carrier_frequency_ghz",
    ):
        try:
            value = float(metadata.get(key))
        except (TypeError, ValueError):
            continue
        if value > 0:
            return value
    return None


def _preview(payload: ImportedCalibrationPayload) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for point, field in zip(payload.points_lambda[:5], payload.reference_field[:5], strict=False):
        rows.append(
            {
                "x_lambda": round(float(point[0]), 6),
                "y_lambda": round(float(point[1]), 6),
                "z_lambda": round(float(point[2]), 6),
                "E_real_norm": round(float(np.real(field)), 6),
                "E_imag_norm": round(float(np.imag(field)), 6),
                "E_abs_norm": round(float(abs(field)), 6),
            }
        )
    return rows

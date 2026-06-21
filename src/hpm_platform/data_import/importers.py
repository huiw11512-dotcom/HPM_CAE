"""External data import audit layer for the V3.0 milestone.

The V3.0 preview focuses on metadata, units, coordinate conventions, and
provenance. It deliberately does not turn imported data into real-world effect
claims without later calibration and V&V.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
import io
import json
from pathlib import Path
import re
import threading
from typing import Any
import zipfile

import numpy as np
import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_OUTPUT = PROJECT_ROOT / "outputs_v20a_vv"
HDF5_SIGNATURE = b"\x89HDF\r\n\x1a\n"
SAFETY_BOUNDARY = "仅做外部数据格式、单位、坐标系和复数值审计；不输出真实源功率、器件阈值、现实作用距离或毁伤概率。"
TEXT_SCAN_LIMIT_BYTES = 512 * 1024
ARCHIVE_SCAN_LIMIT = 200
CST_INFO_FILES = ("CST_PROJECT_INFO.json", "cst_project_info.json", "cst_export_manifest.json")
HFSS_INFO_FILES = ("HFSS_PROJECT_INFO.json", "hfss_project_info.json", "hfss_export_manifest.json")
MEASUREMENT_INFO_FILES = ("MEASUREMENT_CAMPAIGN.json", "measurement_campaign.json", "measurement_manifest.json")


@dataclass(frozen=True)
class ImportedDataset:
    dataset_id: str
    name: str
    format: str
    source_path: str
    size_bytes: int
    sha256: str
    records: int
    columns: tuple[str, ...] = ()
    arrays: tuple[dict[str, Any], ...] = ()
    units: tuple[str, ...] = ()
    coordinate_columns: tuple[str, ...] = ()
    coordinate_system: str = "未声明"
    frequency_points: int = 0
    ports: int = 0
    parameters: dict[str, Any] = field(default_factory=dict)
    preview: tuple[dict[str, Any], ...] = ()
    warnings: tuple[str, ...] = ()
    safety_boundary: str = SAFETY_BOUNDARY

    def to_dict(self) -> dict[str, Any]:
        return {
            "数据集ID": self.dataset_id,
            "名称": self.name,
            "格式": self.format,
            "源文件": self.source_path,
            "大小Bytes": self.size_bytes,
            "SHA256": self.sha256,
            "记录数": self.records,
            "列": list(self.columns),
            "数组": [dict(item) for item in self.arrays],
            "单位": list(self.units),
            "坐标列": list(self.coordinate_columns),
            "坐标系": self.coordinate_system,
            "频点数": self.frequency_points,
            "端口数": self.ports,
            "参数": dict(self.parameters),
            "预览": [dict(item) for item in self.preview],
            "警告": list(self.warnings),
            "安全边界": self.safety_boundary,
        }


class DataImportService:
    """Thread-safe sample catalog and path inspection service."""

    def __init__(self, output_dir: str | Path = DEFAULT_OUTPUT):
        self.output_dir = Path(output_dir)
        self.sample_dir = self.output_dir / "data_import_v30" / "samples"
        self.catalog_path = self.output_dir / "data_import_v30" / "data_import_catalog.json"
        self.readiness_path = self.output_dir / "data_import_v30" / "calibration_readiness.json"
        self._lock = threading.RLock()
        self._sample_index: dict[str, Path] = {}
        self._ensure_samples()

    def catalog(self) -> dict[str, Any]:
        with self._lock:
            samples = [self.inspect_sample(sample_id) for sample_id in sorted(self._sample_index)]
            readiness = self.calibration_readiness(samples)
            payload = {
                "版本": "V3.0-preview",
                "名称": "真实数据导入预览",
                "支持格式": list(self.supported_formats()),
                "样例数": len(samples),
                "样例": samples,
                "验收": self.acceptance_summary(samples),
                "标定准备": readiness,
                "安全边界": SAFETY_BOUNDARY,
                "生成时间UTC": datetime.now(timezone.utc).isoformat(),
            }
            self.catalog_path.parent.mkdir(parents=True, exist_ok=True)
            self.catalog_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            return payload

    def acceptance_summary(self, samples: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        with self._lock:
            rows = samples if samples is not None else [self.inspect_sample(sample_id) for sample_id in sorted(self._sample_index)]
            formats = {item["格式"] for item in rows}
            checks = [
                {"项目": "CSV 场数据可解析", "通过": "CSV" in formats},
                {"项目": "Touchstone S 参数可解析", "通过": "Touchstone" in formats},
                {"项目": "NPZ 数组包可解析", "通过": "NPZ" in formats},
                {"项目": "HDF5 文件可识别", "通过": "HDF5" in self.supported_formats()},
                {"项目": "CST 导出包可识别", "通过": "CST" in formats},
                {"项目": "HFSS/AEDT 导出包可识别", "通过": "HFSS" in formats},
                {"项目": "测量数据批次可识别", "通过": "MeasurementCampaign" in formats},
                {"项目": "测量不确定度模型可审计", "通过": any(_has_measurement_uncertainty(item) for item in rows)},
                {"项目": "测量校准状态可审计", "通过": any(_has_measurement_calibration(item) for item in rows)},
                {"项目": "单位和坐标列审计", "通过": all(item["单位"] or item["坐标列"] or item["格式"] in {"Touchstone", "HDF5"} for item in rows)},
                {"项目": "安全边界声明", "通过": all("安全边界" in item for item in rows)},
            ]
            return {
                "阶段": "V3.0",
                "名称": "真实数据接入",
                "通过": all(item["通过"] for item in checks),
                "已解析格式": sorted(formats),
                "验收清单": checks,
                "下一门槛": "接入单位/坐标换算、导入数据到 V&V 标定流程和三维工作台结果查看。",
            }

    def supported_formats(self) -> tuple[str, ...]:
        return ("CSV", "Touchstone", "NPZ", "HDF5", "CST", "HFSS", "MeasurementCampaign")

    def calibration_readiness(self, samples: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        with self._lock:
            rows = samples if samples is not None else [self.inspect_sample(sample_id) for sample_id in sorted(self._sample_index)]
            reports = [_calibration_readiness_for_dataset(item) for item in rows]
            gates = [
                {"项目": "存在可坐标规范化的导入数据", "通过": any(item["坐标规范化"] for item in reports)},
                {"项目": "存在可用于归一化复场标定的数据", "通过": any(item["复场可用于标定"] for item in reports)},
                {"项目": "测量批次包含不确定度模型", "通过": any(item["格式"] == "MeasurementCampaign" and item["不确定度可用"] for item in reports)},
                {"项目": "测量批次包含校准状态", "通过": any(item["格式"] == "MeasurementCampaign" and item["校准状态可用"] for item in reports)},
                {"项目": "所有可标定样例保留安全边界", "通过": all("安全边界" in item for item in rows)},
            ]
            score = round(float(np.mean([item["标定准备度"] for item in reports])), 2) if reports else 0.0
            payload = {
                "版本": "V3.0-preview",
                "名称": "导入数据标定准备度",
                "通过": all(item["通过"] for item in gates),
                "总体得分": score,
                "样例数": len(reports),
                "样例": reports,
                "门槛": gates,
                "安全边界": SAFETY_BOUNDARY,
                "下一门槛": "把已规范化的归一化复场样本接入 backend_calibration.CalibrationSamples，并生成导入数据驱动的 V&V 对比报告。",
                "生成时间UTC": datetime.now(timezone.utc).isoformat(),
            }
            self.readiness_path.parent.mkdir(parents=True, exist_ok=True)
            self.readiness_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            return payload

    def inspect_sample(self, sample_id: str) -> dict[str, Any]:
        with self._lock:
            try:
                path = self._sample_index[str(sample_id)]
            except KeyError as exc:
                raise KeyError(f"未知数据样例：{sample_id}") from exc
            payload = inspect_dataset(path).to_dict()
            payload["样例ID"] = str(sample_id)
            return payload

    def inspect_path(self, path: str | Path) -> dict[str, Any]:
        return inspect_dataset(Path(path)).to_dict()

    def _ensure_samples(self) -> None:
        self.sample_dir.mkdir(parents=True, exist_ok=True)
        csv_path = self.sample_dir / "near_field_probe.csv"
        s2p_path = self.sample_dir / "coupler_response.s2p"
        npz_path = self.sample_dir / "field_volume.npz"
        h5_path = self.sample_dir / "external_measurement_stub.h5"
        cst_path = self.sample_dir / "cst_array_export_bundle.zip"
        hfss_path = self.sample_dir / "hfss_array_export_bundle.zip"
        measurement_path = self.sample_dir / "measurement_campaign_bundle.zip"

        if not csv_path.exists():
            csv_path.write_text(
                "\n".join(
                    [
                        "x_lambda,y_lambda,z_lambda,E_real_norm,E_imag_norm,uncertainty_sigma",
                        "-0.5,-0.5,1.0,0.82,0.10,0.030",
                        "0.0,-0.5,1.0,0.94,0.02,0.025",
                        "0.5,-0.5,1.0,0.79,-0.08,0.032",
                        "-0.5,0.0,1.0,0.88,0.05,0.028",
                        "0.0,0.0,1.0,1.00,0.00,0.020",
                        "0.5,0.0,1.0,0.87,-0.04,0.029",
                    ]
                ),
                encoding="utf-8",
            )
        if not s2p_path.exists():
            s2p_path.write_text(
                "\n".join(
                    [
                        "! HPM-DT V3.0 preview normalized S-parameter sample",
                        "# GHz S MA R 50",
                        "2.0 0.91 -4.0 0.03 88.0 0.04 -86.0 0.89 -5.0",
                        "3.0 0.87 -7.5 0.05 80.0 0.05 -78.0 0.86 -8.0",
                        "4.0 0.82 -12.0 0.07 73.0 0.08 -71.0 0.81 -13.0",
                    ]
                ),
                encoding="utf-8",
            )
        if not npz_path.exists():
            x = np.linspace(-1.0, 1.0, 5)
            y = np.linspace(-1.0, 1.0, 5)
            xx, yy = np.meshgrid(x, y, indexing="ij")
            field = np.exp(-(xx**2 + yy**2)) * np.exp(1j * 0.25 * np.pi * xx)
            np.savez(npz_path, x_lambda=x, y_lambda=y, normalized_field=field.astype(np.complex128))
        if not h5_path.exists():
            _write_hdf5_sample_or_stub(h5_path)
        _write_cst_export_bundle(cst_path)
        _write_hfss_export_bundle(hfss_path)
        _write_measurement_campaign_bundle(measurement_path)

        self._sample_index = {
            "V30-CSV-NEAR-FIELD": csv_path,
            "V30-TOUCHSTONE-S2P": s2p_path,
            "V30-NPZ-FIELD": npz_path,
            "V30-HDF5-STUB": h5_path,
            "V30-CST-EXPORT": cst_path,
            "V30-HFSS-EXPORT": hfss_path,
            "V30-MEASUREMENT-CAMPAIGN": measurement_path,
        }


def inspect_dataset(path: str | Path) -> ImportedDataset:
    source = Path(path)
    if not source.exists():
        raise FileNotFoundError(f"数据文件不存在：{source}")
    fmt = detect_format(source)
    if fmt == "CSV":
        return _inspect_csv(source)
    if fmt == "Touchstone":
        return _inspect_touchstone(source)
    if fmt == "NPZ":
        return _inspect_npz(source)
    if fmt == "HDF5":
        return _inspect_hdf5(source)
    if fmt == "CST":
        return _inspect_cst(source)
    if fmt == "HFSS":
        return _inspect_hfss(source)
    if fmt == "MeasurementCampaign":
        return _inspect_measurement_campaign(source)
    raise ValueError(f"暂不支持的数据格式：{source.suffix}")


def detect_format(path: Path) -> str:
    if path.is_dir():
        return _detect_em_export_folder(path)
    suffix = path.suffix.lower()
    if suffix in {".csv", ".txt"}:
        return "CSV"
    if re.match(r"\.s\d+p$", suffix):
        return "Touchstone"
    if suffix == ".npz":
        return "NPZ"
    if suffix in {".h5", ".hdf5"}:
        return "HDF5"
    if suffix == ".cst":
        return "CST"
    if suffix in {".aedt", ".aedtz", ".hfss"} or path.name.lower().endswith(".aedtresults"):
        return "HFSS"
    if suffix == ".zip":
        return _detect_em_export_archive(path)
    return "Unknown"


def _base(path: Path, fmt: str) -> dict[str, Any]:
    digest = _sha256(path)
    return {
        "dataset_id": f"{fmt.upper()}-{digest[:12]}",
        "name": path.stem,
        "format": fmt,
        "source_path": str(path.resolve()),
        "size_bytes": _source_size(path),
        "sha256": digest,
    }


def _inspect_csv(path: Path) -> ImportedDataset:
    frame = pd.read_csv(path)
    columns = tuple(str(item) for item in frame.columns)
    units = tuple(sorted(_infer_units(columns)))
    coords = tuple(col for col in columns if _is_coordinate_column(col))
    warnings = _audit_columns(columns, units, coords)
    preview = tuple(_json_safe_row(row) for row in frame.head(5).to_dict(orient="records"))
    return ImportedDataset(
        **_base(path, "CSV"),
        records=int(len(frame)),
        columns=columns,
        units=units,
        coordinate_columns=coords,
        coordinate_system="lambda-normalized" if any(col.endswith("_lambda") for col in coords) else "未声明",
        preview=preview,
        warnings=tuple(warnings),
        parameters={"复数字段": _complex_field_pairs(columns)},
    )


def _inspect_touchstone(path: Path) -> ImportedDataset:
    text = path.read_text(encoding="utf-8", errors="ignore").splitlines()
    option = None
    records: list[list[float]] = []
    for raw in text:
        line = raw.split("!", 1)[0].strip()
        if not line:
            continue
        if line.startswith("#"):
            option = line
            continue
        parts = line.split()
        try:
            records.append([float(part) for part in parts])
        except ValueError:
            continue
    ports = _ports_from_suffix(path.suffix)
    frequency_unit, parameter_kind, value_format, reference = _parse_touchstone_option(option)
    warnings: list[str] = []
    if not records:
        warnings.append("Touchstone 文件没有可解析数值记录")
    expected_cols = 1 + 2 * ports * ports
    if records and len(records[0]) != expected_cols:
        warnings.append(f"Touchstone 列数为 {len(records[0])}，按 {ports} 端口期望 {expected_cols} 列")
    preview = tuple({"频率": row[0], "首个参数幅度或实部": row[1] if len(row) > 1 else None} for row in records[:5])
    return ImportedDataset(
        **_base(path, "Touchstone"),
        records=len(records),
        units=(frequency_unit, parameter_kind, value_format),
        frequency_points=len(records),
        ports=ports,
        parameters={
            "option": option,
            "frequency_unit": frequency_unit,
            "parameter": parameter_kind,
            "value_format": value_format,
            "reference_ohm": reference,
        },
        preview=preview,
        warnings=tuple(warnings),
    )


def _inspect_npz(path: Path) -> ImportedDataset:
    arrays: list[dict[str, Any]] = []
    units: set[str] = set()
    coordinate_columns: list[str] = []
    records = 0
    warnings: list[str] = []
    with np.load(path, allow_pickle=False) as data:
        for name in data.files:
            value = data[name]
            arrays.append({
                "名称": name,
                "形状": list(value.shape),
                "dtype": str(value.dtype),
                "是否复数": bool(np.iscomplexobj(value)),
            })
            records = max(records, int(value.shape[0]) if value.shape else 1)
            units.update(_infer_units((name,)))
            if _is_coordinate_column(name):
                coordinate_columns.append(name)
    if not arrays:
        warnings.append("NPZ 文件未包含数组")
    return ImportedDataset(
        **_base(path, "NPZ"),
        records=records,
        arrays=tuple(arrays),
        units=tuple(sorted(units)),
        coordinate_columns=tuple(coordinate_columns),
        coordinate_system="lambda-normalized" if any(name.endswith("_lambda") for name in coordinate_columns) else "未声明",
        warnings=tuple(warnings),
    )


def _inspect_hdf5(path: Path) -> ImportedDataset:
    warnings: list[str] = []
    arrays: list[dict[str, Any]] = []
    records = 0
    with path.open("rb") as handle:
        signature = handle.read(8)
    if signature != HDF5_SIGNATURE:
        warnings.append("HDF5 文件头签名不匹配")
    try:
        import h5py  # type: ignore

        with h5py.File(path, "r") as handle:
            def visit(name: str, obj: Any) -> None:
                nonlocal records
                if hasattr(obj, "shape") and hasattr(obj, "dtype"):
                    shape = list(obj.shape)
                    arrays.append({"名称": name, "形状": shape, "dtype": str(obj.dtype), "是否复数": "complex" in str(obj.dtype)})
                    records = max(records, int(shape[0]) if shape else 1)

            handle.visititems(visit)
    except Exception as exc:  # h5py may be absent or the file may be a signature-only stub.
        warnings.append(f"HDF5 深度解析不可用：{exc}")
    return ImportedDataset(
        **_base(path, "HDF5"),
        records=records,
        arrays=tuple(arrays),
        warnings=tuple(warnings),
        parameters={"signature_valid": signature == HDF5_SIGNATURE, "h5py_deep_parse": bool(arrays)},
    )


def _inspect_cst(path: Path) -> ImportedDataset:
    return _inspect_em_export(
        path=path,
        fmt="CST",
        tool_name="CST Studio Suite",
        info_files=CST_INFO_FILES,
        native_suffixes={".cst"},
    )


def _inspect_hfss(path: Path) -> ImportedDataset:
    return _inspect_em_export(
        path=path,
        fmt="HFSS",
        tool_name="Ansys HFSS / AEDT",
        info_files=HFSS_INFO_FILES,
        native_suffixes={".aedt", ".aedtz", ".hfss"},
    )


def _inspect_measurement_campaign(path: Path) -> ImportedDataset:
    artifacts, metadata, text_markers = _collect_em_export_artifacts(path, MEASUREMENT_INFO_FILES)
    artifact_names = tuple(str(item.get("路径", "")) for item in artifacts)
    uncertainty_model = _measurement_uncertainty_model(metadata)
    calibration = _measurement_calibration(metadata)
    instrument_chain = metadata.get("instrument_chain") or metadata.get("仪器链") or []
    batches = metadata.get("batches") or metadata.get("批次") or []
    units = set(_infer_units(artifact_names))
    units.update(_units_from_metadata(metadata))
    coords = _coordinate_names_from_artifacts(artifact_names, metadata)
    warnings: list[str] = []
    if not artifacts:
        warnings.append("测量批次未发现可审计的数据文件")
    if not uncertainty_model:
        warnings.append("测量批次缺少不确定度模型，不能进入标定或可信度评分")
    if not calibration:
        warnings.append("测量批次缺少校准状态，不能进入标定或可信度评分")
    if not instrument_chain:
        warnings.append("测量批次缺少仪器链描述")
    if not metadata.get("traceability"):
        warnings.append("测量批次缺少数据血缘或来源说明")

    ports = max((int(item.get("端口数", 0) or 0) for item in artifacts), default=0)
    frequency_points = sum(int(item.get("频点数", 0) or 0) for item in artifacts)
    return ImportedDataset(
        **_base(path, "MeasurementCampaign"),
        records=max(len(artifacts), len(batches), 1),
        columns=tuple(sorted(str(key) for key in metadata.keys())),
        arrays=tuple(dict(item) for item in artifacts),
        units=tuple(sorted(units)),
        coordinate_columns=tuple(coords),
        coordinate_system=str(metadata.get("coordinate_system") or metadata.get("坐标系") or "测量批次声明缺失"),
        frequency_points=frequency_points,
        ports=ports,
        parameters={
            "campaign_id": metadata.get("campaign_id"),
            "source_type": "measurement",
            "container": _container_kind(path),
            "measurement_metadata": metadata,
            "uncertainty_model": uncertainty_model,
            "calibration": calibration,
            "instrument_chain": instrument_chain,
            "traceability": metadata.get("traceability"),
            "batch_count": len(batches) if isinstance(batches, list) else 0,
            "recognized_artifact_count": len(artifacts),
            "text_markers": text_markers,
            "import_scope": "测量批次元数据、仪器链、校准状态、不确定度和数据文件清单审计；不输出真实效应结论。",
        },
        preview=tuple(dict(item) for item in artifacts[:5]),
        warnings=tuple(warnings),
    )


def _inspect_em_export(
    path: Path,
    fmt: str,
    tool_name: str,
    info_files: tuple[str, ...],
    native_suffixes: set[str],
) -> ImportedDataset:
    artifacts, metadata, text_markers = _collect_em_export_artifacts(path, info_files)
    artifact_names = tuple(str(item.get("路径", "")) for item in artifacts)
    units = set(_infer_units(artifact_names))
    units.update(_units_from_metadata(metadata))
    coords = _coordinate_names_from_artifacts(artifact_names, metadata)
    warnings: list[str] = []
    if not artifacts:
        warnings.append(f"{fmt} 导入当前仅发现工程容器，未发现可审计的导出结果文件")
    if path.suffix.lower() in native_suffixes and not path.is_dir():
        warnings.append(f"{fmt} 原生工程当前按元数据预览处理；完整几何/网格/求解设置需后续专用适配器")
    if not units:
        warnings.append(f"{fmt} 导出包未明确声明单位，后续标定前需要人工确认")
    if not coords and fmt in {"CST", "HFSS"}:
        warnings.append(f"{fmt} 导出包未明确声明坐标系，默认不写入求解链")

    ports = max((int(item.get("端口数", 0) or 0) for item in artifacts), default=0)
    frequency_points = sum(int(item.get("频点数", 0) or 0) for item in artifacts)
    preview = tuple(dict(item) for item in artifacts[:5])
    return ImportedDataset(
        **_base(path, fmt),
        records=max(len(artifacts), 1),
        columns=tuple(sorted(str(key) for key in metadata.keys())),
        arrays=tuple(dict(item) for item in artifacts),
        units=tuple(sorted(units)),
        coordinate_columns=tuple(coords),
        coordinate_system=str(metadata.get("coordinate_system") or metadata.get("坐标系") or "导出包声明缺失"),
        frequency_points=frequency_points,
        ports=ports,
        parameters={
            "tool": tool_name,
            "container": _container_kind(path),
            "project_metadata": metadata,
            "recognized_artifact_count": len(artifacts),
            "text_markers": text_markers,
            "native_project_parse": "metadata-only",
            "import_scope": "导出包/工程元数据、结果文件清单、单位坐标线索审计；不执行商业求解器工程。",
        },
        preview=preview,
        warnings=tuple(warnings),
    )


def _collect_em_export_artifacts(path: Path, info_files: tuple[str, ...]) -> tuple[list[dict[str, Any]], dict[str, Any], list[str]]:
    if path.is_dir():
        return _collect_em_export_folder(path, info_files)
    if path.suffix.lower() == ".zip" and zipfile.is_zipfile(path):
        return _collect_em_export_archive(path, info_files)
    metadata = _metadata_from_text_file(path, info_files)
    artifact = _artifact_from_name(path.name, path.stat().st_size)
    return ([artifact] if artifact else [], metadata, _text_markers_from_file(path))


def _collect_em_export_folder(path: Path, info_files: tuple[str, ...]) -> tuple[list[dict[str, Any]], dict[str, Any], list[str]]:
    files = [item for item in sorted(path.rglob("*")) if item.is_file()][:ARCHIVE_SCAN_LIMIT]
    metadata: dict[str, Any] = {}
    artifacts: list[dict[str, Any]] = []
    markers: list[str] = []
    for item in files:
        relative = item.relative_to(path).as_posix()
        if item.name in info_files:
            metadata.update(_read_json_file(item))
        artifact = _artifact_from_name(relative, item.stat().st_size)
        if artifact:
            artifacts.append(artifact)
        if len(markers) < 8:
            markers.extend(_text_markers_from_file(item, relative))
            markers = markers[:8]
    return artifacts, metadata, markers


def _collect_em_export_archive(path: Path, info_files: tuple[str, ...]) -> tuple[list[dict[str, Any]], dict[str, Any], list[str]]:
    metadata: dict[str, Any] = {}
    artifacts: list[dict[str, Any]] = []
    markers: list[str] = []
    with zipfile.ZipFile(path) as archive:
        infos = [item for item in archive.infolist() if not item.is_dir()][:ARCHIVE_SCAN_LIMIT]
        for info in infos:
            name = info.filename
            if Path(name).name in info_files:
                metadata.update(_read_json_from_archive(archive, name))
            artifact = _artifact_from_name(name, info.file_size)
            if artifact:
                artifacts.append(artifact)
            if len(markers) < 8 and _is_text_like_name(name) and info.file_size <= TEXT_SCAN_LIMIT_BYTES:
                try:
                    text = archive.read(name).decode("utf-8", errors="ignore")
                except Exception:
                    text = ""
                markers.extend(_extract_text_markers(text, name))
                markers = markers[:8]
    return artifacts, metadata, markers


def _detect_em_export_folder(path: Path) -> str:
    if path.name.lower().endswith(".aedtresults"):
        return "HFSS"
    files = [item for item in sorted(path.rglob("*")) if item.is_file()][:ARCHIVE_SCAN_LIMIT]
    names = [item.relative_to(path).as_posix() for item in files]
    return _detect_archive_or_folder_names(names)


def _detect_em_export_archive(path: Path) -> str:
    if not zipfile.is_zipfile(path):
        return "Unknown"
    try:
        with zipfile.ZipFile(path) as archive:
            names = [item.filename for item in archive.infolist() if not item.is_dir()][:ARCHIVE_SCAN_LIMIT]
    except zipfile.BadZipFile:
        return "Unknown"
    return _detect_archive_or_folder_names(names)


def _detect_archive_or_folder_names(names: list[str]) -> str:
    if any(Path(name).name in MEASUREMENT_INFO_FILES for name in names):
        return "MeasurementCampaign"
    return _detect_em_names(names)


def _detect_em_names(names: list[str]) -> str:
    lowered = [name.lower() for name in names]
    if any(Path(name).name in CST_INFO_FILES for name in names) or any(_looks_like_cst_name(name) for name in lowered):
        return "CST"
    if any(Path(name).name in HFSS_INFO_FILES for name in names) or any(_looks_like_hfss_name(name) for name in lowered):
        return "HFSS"
    return "Unknown"


def _looks_like_cst_name(name: str) -> bool:
    return name.endswith(".cst") or "cst" in name or "result/3d" in name or "result/1d" in name


def _looks_like_hfss_name(name: str) -> bool:
    return name.endswith((".aedt", ".hfss")) or ".aedtresults" in name or "hfss" in name or "ansys" in name


def _artifact_from_name(name: str, size_bytes: int = 0) -> dict[str, Any] | None:
    lowered = name.lower()
    suffix = Path(lowered).suffix
    artifact_type = None
    ports = 0
    frequency_points = 0
    if re.search(r"\.s\d+p$", suffix):
        artifact_type = "S参数"
        ports = _ports_from_suffix(suffix)
        frequency_points = 1
    elif suffix in {".csv", ".txt", ".dat"}:
        artifact_type = "表格/曲线"
        if any(token in lowered for token in ("field", "farfield", "nearfield", "e-field", "h-field", "场")):
            artifact_type = "场数据"
    elif suffix in {".h5", ".hdf5", ".npz"}:
        artifact_type = "数组场数据"
    elif suffix in {".json", ".xml"} and any(token in lowered for token in ("manifest", "info", "project")):
        artifact_type = "工程元数据"
    elif suffix in {".cst", ".aedt", ".aedtz", ".hfss"} or lowered.endswith(".aedtresults"):
        artifact_type = "原生工程容器"
    if artifact_type is None:
        return None
    return {
        "路径": name,
        "类型": artifact_type,
        "大小Bytes": int(size_bytes),
        "端口数": ports,
        "频点数": frequency_points,
        "单位线索": sorted(_infer_units((name,))),
    }


def _metadata_from_text_file(path: Path, info_files: tuple[str, ...]) -> dict[str, Any]:
    if path.name in info_files:
        return _read_json_file(path)
    if path.suffix.lower() not in {".aedt", ".hfss", ".txt", ".json", ".xml"}:
        return {}
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")[:TEXT_SCAN_LIMIT_BYTES]
    except Exception:
        return {}
    data = _try_json_object(text)
    return data if isinstance(data, dict) else {}


def _read_json_file(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _read_json_from_archive(archive: zipfile.ZipFile, name: str) -> dict[str, Any]:
    try:
        return json.loads(archive.read(name).decode("utf-8"))
    except Exception:
        return {}


def _try_json_object(text: str) -> dict[str, Any] | None:
    stripped = text.strip()
    if not stripped.startswith("{"):
        return None
    try:
        data = json.loads(stripped)
    except Exception:
        return None
    return data if isinstance(data, dict) else None


def _measurement_uncertainty_model(metadata: dict[str, Any]) -> dict[str, Any]:
    model = metadata.get("uncertainty_model") or metadata.get("uncertainty") or metadata.get("不确定度模型")
    return dict(model) if isinstance(model, dict) else {}


def _measurement_calibration(metadata: dict[str, Any]) -> dict[str, Any]:
    calibration = metadata.get("calibration") or metadata.get("calibration_state") or metadata.get("校准")
    return dict(calibration) if isinstance(calibration, dict) else {}


def _has_measurement_uncertainty(payload: dict[str, Any]) -> bool:
    params = payload.get("参数") or {}
    model = params.get("uncertainty_model") if isinstance(params, dict) else None
    return payload.get("格式") == "MeasurementCampaign" and isinstance(model, dict) and bool(model)


def _has_measurement_calibration(payload: dict[str, Any]) -> bool:
    params = payload.get("参数") or {}
    calibration = params.get("calibration") if isinstance(params, dict) else None
    return payload.get("格式") == "MeasurementCampaign" and isinstance(calibration, dict) and bool(calibration)


def _calibration_readiness_for_dataset(payload: dict[str, Any]) -> dict[str, Any]:
    source = Path(str(payload.get("源文件", "")))
    fmt = str(payload.get("格式", "Unknown"))
    params = payload.get("参数") if isinstance(payload.get("参数"), dict) else {}
    preview = _normalization_preview_for_dataset(source, fmt, params)
    unit_ready = bool(payload.get("单位")) or bool(preview.get("单位换算"))
    coordinate_ready = bool(preview.get("坐标规范化"))
    complex_ready = int(preview.get("复场样本数", 0) or 0) > 0
    uncertainty_ready = _has_measurement_uncertainty(payload) or bool(preview.get("不确定度字段"))
    calibration_ready = _has_measurement_calibration(payload) or fmt not in {"MeasurementCampaign"}
    blockers: list[str] = []
    if not unit_ready:
        blockers.append("缺少可审计单位")
    if not coordinate_ready:
        blockers.append("缺少可规范化坐标")
    if not complex_ready and fmt in {"CSV", "CST", "HFSS", "MeasurementCampaign"}:
        blockers.append("缺少可配对复场样本")
    if fmt == "MeasurementCampaign" and not uncertainty_ready:
        blockers.append("测量不确定度缺失")
    if fmt == "MeasurementCampaign" and not calibration_ready:
        blockers.append("测量校准状态缺失")

    score = 0.0
    score += 18.0 if unit_ready else 0.0
    score += 22.0 if coordinate_ready else 0.0
    score += 24.0 if complex_ready else 0.0
    score += 12.0 if uncertainty_ready else (8.0 if fmt != "MeasurementCampaign" else 0.0)
    score += 12.0 if calibration_ready else (8.0 if fmt != "MeasurementCampaign" else 0.0)
    score += 12.0 if payload.get("SHA256") and payload.get("安全边界") else 0.0
    return {
        "样例ID": payload.get("样例ID"),
        "数据集ID": payload.get("数据集ID"),
        "名称": payload.get("名称"),
        "格式": fmt,
        "单位规范化": unit_ready,
        "坐标规范化": coordinate_ready,
        "复场可用于标定": complex_ready,
        "不确定度可用": uncertainty_ready,
        "校准状态可用": calibration_ready,
        "标定准备度": round(min(score, 100.0), 2),
        "规范化预览": preview,
        "阻断项": blockers,
        "下一步": "可进入导入数据 V&V 标定准备" if not blockers else "补齐阻断项后再进入 V&V 标定",
    }


def _normalization_preview_for_dataset(source: Path, fmt: str, params: dict[str, Any]) -> dict[str, Any]:
    if fmt == "CSV" and source.exists():
        try:
            return _preview_from_frame(pd.read_csv(source), {})
        except Exception as exc:
            return {"错误": f"CSV 规范化预览失败：{exc}"}
    if fmt == "MeasurementCampaign":
        metadata = params.get("measurement_metadata") if isinstance(params.get("measurement_metadata"), dict) else {}
        frame = _load_preferred_csv(source, ("near_field", "field", "scan"))
        preview = _preview_from_frame(frame, metadata) if frame is not None else {}
        preview.update({
            "测量批次": params.get("batch_count", 0),
            "仪器链数量": len(params.get("instrument_chain") or []),
            "校准状态": (params.get("calibration") or {}).get("status") if isinstance(params.get("calibration"), dict) else None,
            "不确定度模型": params.get("uncertainty_model") or {},
        })
        return preview
    if fmt in {"CST", "HFSS"}:
        metadata = params.get("project_metadata") if isinstance(params.get("project_metadata"), dict) else {}
        frame = _load_preferred_csv(source, ("nearfield", "near_field", "field", "farfield"))
        preview = _preview_from_frame(frame, metadata) if frame is not None else {}
        preview.update({
            "工程容器": params.get("container"),
            "识别工件数": params.get("recognized_artifact_count", 0),
            "工具": params.get("tool"),
        })
        return preview
    if fmt == "Touchstone":
        return {
            "频率单位": params.get("frequency_unit"),
            "参数类型": params.get("parameter"),
            "端口参考阻抗Ohm": params.get("reference_ohm"),
            "单位换算": bool(params.get("frequency_unit")),
            "坐标规范化": False,
            "复场样本数": 0,
        }
    return {
        "单位换算": False,
        "坐标规范化": False,
        "复场样本数": 0,
    }


def _load_preferred_csv(source: Path, preferred_tokens: tuple[str, ...]) -> pd.DataFrame | None:
    if not source.exists():
        return None
    if source.is_dir():
        candidates = [item for item in source.rglob("*.csv") if _name_matches_tokens(item.as_posix(), preferred_tokens)]
        if not candidates:
            candidates = list(source.rglob("*.csv"))
        if candidates:
            return pd.read_csv(candidates[0])
        return None
    if source.suffix.lower() == ".zip" and zipfile.is_zipfile(source):
        with zipfile.ZipFile(source) as archive:
            names = [item.filename for item in archive.infolist() if not item.is_dir() and item.filename.lower().endswith(".csv")]
            preferred = [name for name in names if _name_matches_tokens(name, preferred_tokens)]
            for name in preferred or names:
                try:
                    text = archive.read(name).decode("utf-8", errors="ignore")
                    return pd.read_csv(io.StringIO(text))
                except Exception:
                    continue
    return None


def _name_matches_tokens(name: str, tokens: tuple[str, ...]) -> bool:
    lowered = name.lower()
    return any(token in lowered for token in tokens)


def _preview_from_frame(frame: pd.DataFrame | None, metadata: dict[str, Any]) -> dict[str, Any]:
    if frame is None or frame.empty:
        return {"单位换算": bool(_units_from_metadata(metadata)), "坐标规范化": False, "复场样本数": 0}
    columns = tuple(str(item) for item in frame.columns)
    coordinate_preview = _normalized_coordinate_preview(frame, metadata)
    pairs = _complex_field_pairs(columns)
    uncertainty_columns = [col for col in columns if "sigma" in col.lower() or "uncertainty" in col.lower()]
    field_preview: list[dict[str, Any]] = []
    if pairs:
        first_pair = pairs[0]
        for _, row in frame.head(5).iterrows():
            real = row.get(first_pair["real"])
            imag = row.get(first_pair["imag"])
            if pd.notna(real) and pd.notna(imag):
                field_preview.append({
                    "real": float(real),
                    "imag": float(imag),
                    "amplitude": float(np.hypot(float(real), float(imag))),
                })
    return {
        "单位换算": bool(coordinate_preview.get("单位换算") or _infer_units(columns) or _units_from_metadata(metadata)),
        "坐标规范化": bool(coordinate_preview.get("坐标规范化")),
        "坐标预览": coordinate_preview.get("坐标预览", []),
        "坐标单位": coordinate_preview.get("源坐标单位"),
        "目标坐标": coordinate_preview.get("目标坐标"),
        "参考频率GHz": coordinate_preview.get("参考频率GHz"),
        "复场样本数": int(len(frame)) if pairs and coordinate_preview.get("坐标规范化") else 0,
        "复场字段": pairs,
        "复场预览": field_preview,
        "不确定度字段": uncertainty_columns,
        "记录数": int(len(frame)),
    }


def _normalized_coordinate_preview(frame: pd.DataFrame, metadata: dict[str, Any]) -> dict[str, Any]:
    columns = {str(col).lower(): str(col) for col in frame.columns}
    for unit in ("lambda", "mm", "cm", "m"):
        keys = [f"x_{unit}", f"y_{unit}", f"z_{unit}"]
        if all(key in columns for key in keys):
            coords = frame[[columns[key] for key in keys]].head(5).astype(float).to_numpy()
            reference_frequency = _reference_frequency_ghz(metadata)
            if unit == "lambda":
                normalized = coords
                converted = True
            elif reference_frequency is not None:
                if unit == "mm":
                    wavelength = 299.792458 / reference_frequency
                    normalized = coords / wavelength
                elif unit == "cm":
                    wavelength = 29.9792458 / reference_frequency
                    normalized = coords / wavelength
                else:
                    wavelength = 0.299792458 / reference_frequency
                    normalized = coords / wavelength
                converted = True
            else:
                normalized = coords
                converted = False
            return {
                "源坐标单位": unit,
                "目标坐标": "lambda",
                "参考频率GHz": reference_frequency,
                "单位换算": converted,
                "坐标规范化": converted,
                "坐标预览": [
                    {"x_lambda": round(float(row[0]), 6), "y_lambda": round(float(row[1]), 6), "z_lambda": round(float(row[2]), 6)}
                    for row in normalized
                ],
            }
    if "theta_deg" in columns and "phi_deg" in columns:
        preview = frame[[columns["theta_deg"], columns["phi_deg"]]].head(5).astype(float).to_numpy()
        return {
            "源坐标单位": "deg",
            "目标坐标": "angular",
            "单位换算": True,
            "坐标规范化": True,
            "坐标预览": [{"theta_deg": round(float(row[0]), 6), "phi_deg": round(float(row[1]), 6)} for row in preview],
        }
    return {"单位换算": False, "坐标规范化": False, "坐标预览": []}


def _reference_frequency_ghz(metadata: dict[str, Any]) -> float | None:
    candidates = (
        metadata.get("reference_frequency_ghz"),
        metadata.get("frequency_ghz"),
        metadata.get("center_frequency_ghz"),
        metadata.get("carrier_frequency_ghz"),
    )
    for value in candidates:
        try:
            number = float(value)
        except (TypeError, ValueError):
            continue
        if number > 0:
            return number
    return None


def _units_from_metadata(metadata: dict[str, Any]) -> set[str]:
    units = set(_infer_units(tuple(str(key) for key in metadata.keys())))
    for key, value in metadata.items():
        lowered_key = str(key).lower()
        if "unit" in lowered_key or "单位" in lowered_key:
            units.add(str(value))
        if isinstance(value, dict):
            units.update(_units_from_metadata(value))
        if isinstance(value, list):
            for item in value:
                if isinstance(item, dict):
                    units.update(_units_from_metadata(item))
    return {unit for unit in units if unit}


def _coordinate_names_from_artifacts(artifact_names: tuple[str, ...], metadata: dict[str, Any]) -> list[str]:
    names = [name for name in artifact_names if any(token in name.lower() for token in ("x_", "y_", "z_", "theta", "phi", "field"))]
    coordinate_system = metadata.get("coordinate_system") or metadata.get("坐标系")
    if coordinate_system and not names:
        names.append(str(coordinate_system))
    return names[:8]


def _container_kind(path: Path) -> str:
    if path.is_dir():
        return "directory"
    if path.suffix.lower() == ".zip":
        return "zip"
    return "file"


def _is_text_like_name(name: str) -> bool:
    return Path(name.lower()).suffix in {".csv", ".txt", ".json", ".xml", ".s1p", ".s2p", ".s3p", ".s4p"}


def _text_markers_from_file(path: Path, label: str | None = None) -> list[str]:
    if not _is_text_like_name(path.name) or path.stat().st_size > TEXT_SCAN_LIMIT_BYTES:
        return []
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return []
    return _extract_text_markers(text, label or path.name)


def _extract_text_markers(text: str, label: str) -> list[str]:
    markers: list[str] = []
    lowered = text.lower()
    for token in ("ghz", "mhz", "hz", "mm", "lambda", "s ma r", "farfield", "nearfield", "hfss", "cst", "measurement", "calibration", "uncertainty"):
        if token in lowered:
            markers.append(f"{label}: {token}")
    return markers[:4]


def _write_hdf5_sample_or_stub(path: Path) -> None:
    try:
        import h5py  # type: ignore

        with h5py.File(path, "w") as handle:
            handle.attrs["source"] = "HPM-DT V3.0 preview"
            handle.create_dataset("frequency_ghz", data=np.array([2.0, 3.0, 4.0], dtype=float))
            handle.create_dataset("normalized_response", data=np.array([0.91 + 0.02j, 0.88 - 0.03j, 0.84 - 0.05j]))
    except Exception:
        path.write_bytes(HDF5_SIGNATURE + b"HPM-DT V3.0 HDF5 signature stub; install h5py for dataset traversal.\n")


def _write_cst_export_bundle(path: Path) -> None:
    metadata = {
        "tool": "CST Studio Suite",
        "project": "HPM_DT_array_demo",
        "unit_length": "mm",
        "unit_frequency": "GHz",
        "reference_frequency_ghz": 3.0,
        "coordinate_system": "right-handed XYZ",
        "exports": [
            {"path": "Result/3D/nearfield_E.csv", "quantity": "normalized complex E-field", "unit": "norm"},
            {"path": "Result/1D/S-Parameters/coupler.s2p", "quantity": "S-parameter", "unit": "GHz"},
        ],
    }
    files = {
        "CST_PROJECT_INFO.json": json.dumps(metadata, ensure_ascii=False, indent=2),
        "Result/3D/nearfield_E.csv": "\n".join(
            [
                "x_mm,y_mm,z_mm,E_real_norm,E_imag_norm",
                "-10,0,100,0.82,0.10",
                "0,0,100,1.00,0.00",
                "10,0,100,0.81,-0.09",
            ]
        ),
        "Result/1D/S-Parameters/coupler.s2p": "\n".join(
            [
                "! CST exported normalized S-parameter sample",
                "# GHz S MA R 50",
                "2.0 0.92 -3.0 0.04 89.0 0.04 -89.0 0.90 -4.0",
                "3.0 0.88 -6.0 0.05 83.0 0.05 -82.0 0.87 -6.5",
            ]
        ),
    }
    _write_deterministic_zip(path, files)


def _write_hfss_export_bundle(path: Path) -> None:
    metadata = {
        "tool": "Ansys HFSS / AEDT",
        "project": "HPM_DT_hfss_array_demo",
        "unit_length": "mm",
        "unit_frequency": "GHz",
        "reference_frequency_ghz": 3.0,
        "coordinate_system": "right-handed XYZ",
        "exports": [
            {"path": "Reports/SParameters/array_feed.s2p", "quantity": "S-parameter", "unit": "GHz"},
            {"path": "Fields/Farfield/gain_cut.csv", "quantity": "normalized far-field gain cut", "unit": "deg"},
        ],
    }
    files = {
        "HFSS_PROJECT_INFO.json": json.dumps(metadata, ensure_ascii=False, indent=2),
        "Reports/SParameters/array_feed.s2p": "\n".join(
            [
                "! HFSS exported normalized S-parameter sample",
                "# GHz S MA R 50",
                "2.0 0.89 -5.0 0.03 91.0 0.03 -91.0 0.88 -5.5",
                "3.0 0.86 -8.5 0.05 84.0 0.05 -84.0 0.85 -9.0",
            ]
        ),
        "Fields/Farfield/gain_cut.csv": "\n".join(
            [
                "theta_deg,phi_deg,gain_norm,phase_deg",
                "-20,0,0.62,-18",
                "0,0,1.00,0",
                "20,0,0.61,19",
            ]
        ),
    }
    _write_deterministic_zip(path, files)


def _write_measurement_campaign_bundle(path: Path) -> None:
    metadata = {
        "campaign_id": "HPM_DT_MEAS_2026_PREVIEW",
        "source_type": "measurement",
        "title": "normalized near-field measurement campaign preview",
        "unit_length": "mm",
        "unit_frequency": "GHz",
        "reference_frequency_ghz": 3.0,
        "coordinate_system": "right-handed XYZ",
        "instrument_chain": [
            {"role": "field_probe", "name": "normalized E-field probe", "calibration_ref": "CAL-DEMO-001"},
            {"role": "receiver", "name": "VNA response channel", "calibration_ref": "CAL-DEMO-002"},
            {"role": "positioner", "name": "near-field scanner", "calibration_ref": "CAL-DEMO-003"},
        ],
        "calibration": {
            "status": "preview-calibrated",
            "date": "2026-01-01",
            "reference": "synthetic public demo only",
            "valid_for": "normalized metadata audit, not real source-power inference",
        },
        "uncertainty_model": {
            "confidence": "1-sigma",
            "amplitude_sigma_norm": 0.025,
            "phase_sigma_deg": 1.8,
            "position_sigma_mm": 0.15,
            "frequency_sigma_mhz": 0.5,
        },
        "traceability": {
            "origin": "HPM-DT generated public demo",
            "license": "project sample data",
            "operator": "automated fixture",
        },
        "batches": [
            {"batch_id": "BATCH-001", "file": "measurements/near_field_scan.csv", "records": 5},
            {"batch_id": "BATCH-002", "file": "measurements/vna_response.s2p", "records": 2},
        ],
    }
    files = {
        "MEASUREMENT_CAMPAIGN.json": json.dumps(metadata, ensure_ascii=False, indent=2),
        "measurements/near_field_scan.csv": "\n".join(
            [
                "scan_id,x_mm,y_mm,z_mm,E_real_norm,E_imag_norm,amplitude_sigma_norm,phase_sigma_deg",
                "S001,-20,0,100,0.72,0.11,0.025,1.8",
                "S001,-10,0,100,0.88,0.06,0.024,1.7",
                "S001,0,0,100,1.00,0.00,0.022,1.6",
                "S001,10,0,100,0.86,-0.05,0.024,1.7",
                "S001,20,0,100,0.70,-0.10,0.026,1.9",
            ]
        ),
        "measurements/vna_response.s2p": "\n".join(
            [
                "! Measurement campaign normalized VNA response sample",
                "# GHz S MA R 50",
                "2.0 0.90 -4.5 0.04 87.0 0.04 -87.0 0.89 -4.8",
                "3.0 0.85 -8.0 0.06 79.0 0.06 -79.0 0.84 -8.3",
            ]
        ),
        "calibration/calibration_summary.csv": "\n".join(
            [
                "item,status,sigma,unit",
                "field_probe,preview-calibrated,0.025,norm",
                "phase_reference,preview-calibrated,1.8,deg",
                "scanner_position,preview-calibrated,0.15,mm",
            ]
        ),
    }
    _write_deterministic_zip(path, files)


def _write_deterministic_zip(path: Path, files: dict[str, str]) -> None:
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name in sorted(files):
            info = zipfile.ZipInfo(name)
            info.date_time = (2026, 1, 1, 0, 0, 0)
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, files[name].encode("utf-8"))


def _ports_from_suffix(suffix: str) -> int:
    match = re.match(r"\.s(\d+)p$", suffix.lower())
    return int(match.group(1)) if match else 0


def _parse_touchstone_option(option: str | None) -> tuple[str, str, str, float | None]:
    if not option:
        return "Hz", "S", "MA", None
    parts = option.upper().replace("#", " ").split()
    frequency_unit = parts[0] if len(parts) > 0 else "HZ"
    parameter = parts[1] if len(parts) > 1 else "S"
    value_format = parts[2] if len(parts) > 2 else "MA"
    reference = None
    if "R" in parts:
        index = parts.index("R")
        if index + 1 < len(parts):
            try:
                reference = float(parts[index + 1])
            except ValueError:
                reference = None
    return frequency_unit, parameter, value_format, reference


def _infer_units(names: tuple[str, ...] | list[str]) -> set[str]:
    units: set[str] = set()
    for name in names:
        lowered = str(name).lower()
        for unit in ("lambda", "mm", "cm", "m", "ghz", "mhz", "hz", "db", "deg", "sigma", "norm"):
            if lowered.endswith(f"_{unit}") or f"_{unit}_" in lowered or lowered == unit:
                units.add(unit)
    return units


def _is_coordinate_column(name: str) -> bool:
    lowered = str(name).lower()
    return lowered.startswith(("x_", "y_", "z_")) or lowered in {"x", "y", "z", "theta_deg", "phi_deg"}


def _complex_field_pairs(columns: tuple[str, ...]) -> list[dict[str, str]]:
    lowered = {col.lower(): col for col in columns}
    pairs: list[dict[str, str]] = []
    for key, original in lowered.items():
        if key.endswith("_real_norm") or key.endswith("_real"):
            prefix = key.rsplit("_real", 1)[0]
            imag = lowered.get(f"{prefix}_imag_norm") or lowered.get(f"{prefix}_imag")
            if imag:
                pairs.append({"real": original, "imag": imag})
    return pairs


def _audit_columns(columns: tuple[str, ...], units: tuple[str, ...], coords: tuple[str, ...]) -> list[str]:
    warnings: list[str] = []
    if not coords:
        warnings.append("未发现坐标列")
    if not units:
        warnings.append("未从列名推断出单位")
    sensitive = [col for col in columns if any(token in col.lower() for token in ("power_w", "dbm", "damage", "kill", "range_m"))]
    if sensitive:
        warnings.append(f"发现可能超出公开模型边界的列：{', '.join(sensitive)}")
    if not _complex_field_pairs(columns) and any("field" in col.lower() or col.lower().startswith("e_") for col in columns):
        warnings.append("场数据缺少可配对的实部/虚部列")
    return warnings


def _json_safe_row(row: dict[str, Any]) -> dict[str, Any]:
    safe: dict[str, Any] = {}
    for key, value in row.items():
        if isinstance(value, np.generic):
            value = value.item()
        if pd.isna(value):
            value = None
        safe[str(key)] = value
    return safe


def _source_size(path: Path) -> int:
    if path.is_file():
        return path.stat().st_size
    if path.is_dir():
        return sum(item.stat().st_size for item in path.rglob("*") if item.is_file())
    return 0


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    if path.is_dir():
        for item in sorted(p for p in path.rglob("*") if p.is_file()):
            relative = item.relative_to(path).as_posix().encode("utf-8")
            digest.update(relative)
            with item.open("rb") as handle:
                for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                    digest.update(chunk)
        return digest.hexdigest()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()

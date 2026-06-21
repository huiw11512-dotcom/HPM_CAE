"""External measurement evidence-chain audit for V3.0 data import.

The evidence chain records provenance, authorization, source-chain,
phase-reference, calibration, and uncertainty metadata. It is deliberately a
research V&V gate, not a real effect or device-threshold model.
"""
from __future__ import annotations

from datetime import datetime, timezone
import csv
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping
import zipfile

import yaml

from hpm_platform.data_import.importers import DEFAULT_OUTPUT, SAFETY_BOUNDARY


PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_EVIDENCE_CONFIG = PROJECT_ROOT / "configs" / "external_data_evidence.yaml"
EVIDENCE_OUTPUT_NAME = "evidence_chain_report.json"
EVIDENCE_CSV_NAME = "evidence_chain_checks.csv"
EVIDENCE_PACKAGE_OUTPUT_NAME = "evidence_package_audit.json"
EVIDENCE_PACKAGE_CSV_NAME = "evidence_package_checks.csv"


def load_evidence_chain_config(config_path: str | Path | None = None) -> dict[str, Any]:
    path = Path(config_path or DEFAULT_EVIDENCE_CONFIG)
    with path.open("r", encoding="utf-8") as handle:
        payload = yaml.safe_load(handle) or {}
    if not isinstance(payload, dict):
        raise ValueError(f"外部数据证据链配置必须是 YAML 映射：{path}")
    payload["__path__"] = str(path.resolve())
    return payload


def generate_evidence_chain_report(
    output_dir: str | Path = DEFAULT_OUTPUT,
    *,
    config_path: str | Path | None = None,
) -> dict[str, Any]:
    config = load_evidence_chain_config(config_path)
    output_root = Path(output_dir)
    report_dir = output_root / "data_import_v30"
    report_path = report_dir / EVIDENCE_OUTPUT_NAME
    csv_path = report_dir / EVIDENCE_CSV_NAME
    report_dir.mkdir(parents=True, exist_ok=True)

    report = build_evidence_chain_report(config, output_file=report_path, csv_file=csv_path)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    _write_checks_csv(csv_path, report["验收清单"])
    return report


def inspect_evidence_package(
    package_path: str | Path,
    output_dir: str | Path = DEFAULT_OUTPUT,
    *,
    config_path: str | Path | None = None,
) -> dict[str, Any]:
    """Inspect a user-supplied external evidence package.

    The package may be a ZIP file or a directory. It must contain an evidence
    manifest plus raw data files whose SHA256 hashes are declared in the
    manifest. This only audits provenance and reproducibility metadata; it does
    not turn the platform into a real-effect, range, or device-threshold model.
    """

    base_config = load_evidence_chain_config(config_path)
    rules = _mapping(base_config.get("evidence_package"))
    manifest_names = _manifest_names(rules)
    forbidden_tokens = _forbidden_package_tokens(rules)
    min_files = int(_number(rules.get("min_files"), 2))
    max_files = int(_number(rules.get("max_files"), 500))
    max_bytes = int(_number(rules.get("max_bytes"), 50_000_000))

    package = Path(package_path)
    package_type, manifest_name, manifest_text, package_files = _read_evidence_package(
        package,
        manifest_names,
        max_files=max_files,
        max_bytes=max_bytes,
    )
    manifest = _parse_evidence_manifest(manifest_text, manifest_name)
    manifest["__path__"] = f"{package.resolve()}::{manifest_name}"
    chain_report = build_evidence_chain_report(manifest)

    data_files = [item for item in package_files if item.get("角色") != "manifest"]
    package_hashes = {str(item.get("SHA256", "")).lower() for item in data_files}
    declared_hashes = _declared_raw_hashes(manifest)
    matched_hashes = sorted(item for item in declared_hashes if item in package_hashes)
    missing_hashes = sorted(item for item in declared_hashes if item not in package_hashes)
    forbidden_hits = _scan_forbidden_tokens(manifest, forbidden_tokens)

    checks = [
        _check("证据包路径存在", package.exists(), str(package.resolve()), "P0"),
        _check("证据包格式可读取", package_type in {"zip", "directory"}, package_type, "P0"),
        _check("证据包manifest存在", bool(manifest_name), manifest_name or "未找到", "P0"),
        _check("证据包文件数量达标", len(package_files) >= min_files, f"file_count={len(package_files)}, min={min_files}", "P1"),
        _check("manifest可解析为映射", isinstance(manifest, Mapping), manifest_name, "P0"),
        _check(
            "包内原始数据哈希匹配",
            bool(declared_hashes) and not missing_hashes,
            f"declared={len(declared_hashes)}, matched={len(matched_hashes)}, missing={len(missing_hashes)}",
            "P0",
        ),
        _check(
            "安全字段扫描通过",
            not forbidden_hits,
            "; ".join(forbidden_hits[:6]) if forbidden_hits else "未发现真实作用距离/器件阈值/毁伤概率字段",
            "P0",
        ),
        _check(
            "证据链正式门槛通过",
            bool(chain_report.get("可纳入正式可信度评分证据")),
            f"阻断项={len(chain_report.get('阻断项', ()))}, dataset={chain_report.get('数据集ID')}",
            "P0",
        ),
    ]
    passed = all(item["通过"] for item in checks)

    output_root = Path(output_dir)
    report_dir = output_root / "data_import_v30"
    report_dir.mkdir(parents=True, exist_ok=True)
    report_path = report_dir / EVIDENCE_PACKAGE_OUTPUT_NAME
    csv_path = report_dir / EVIDENCE_PACKAGE_CSV_NAME

    report = {
        "版本": "V3.0-evidence-package-audit-v1",
        "名称": "外部数据正式证据包审计",
        "包路径": str(package.resolve()),
        "包类型": package_type,
        "manifest": manifest_name,
        "数据集ID": str(manifest.get("dataset_id", "未声明")),
        "通过": bool(passed),
        "可作为正式证据配置候选": bool(passed),
        "可直接改写可信度评分": False,
        "正式评分说明": "该审计只确认授权、源链、相位参考、校准和原始数据哈希闭环；是否进入正式评分仍需外部V&V残差、覆盖率和人工复核共同通过。",
        "验收清单": checks,
        "阻断项": [item for item in checks if not item["通过"]],
        "证据链审计": chain_report,
        "包内文件数量": len(package_files),
        "包内数据文件数量": len(data_files),
        "声明原始数据哈希": declared_hashes,
        "匹配原始数据哈希": matched_hashes,
        "缺失原始数据哈希": missing_hashes,
        "安全字段命中": forbidden_hits,
        "包内文件": package_files,
        "输出文件": str(report_path.resolve()),
        "CSV": str(csv_path.resolve()),
        "安全边界": SAFETY_BOUNDARY,
        "生成时间UTC": datetime.now(timezone.utc).isoformat(),
    }
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    _write_checks_csv(csv_path, checks)
    return report


def build_evidence_chain_report(
    config: Mapping[str, Any],
    *,
    output_file: str | Path | None = None,
    csv_file: str | Path | None = None,
) -> dict[str, Any]:
    evidence = _mapping(config.get("evidence"))
    thresholds = _mapping(config.get("thresholds"))
    authorization = _mapping(evidence.get("authorization"))
    source_chain = _mapping(evidence.get("source_chain"))
    phase_reference = _mapping(evidence.get("phase_reference"))
    calibration = _mapping(evidence.get("calibration"))
    uncertainty_model = _mapping(evidence.get("uncertainty_model"))
    raw_lineage = _mapping(evidence.get("raw_data_lineage"))

    max_phase_uncertainty = _number(thresholds.get("max_phase_reference_uncertainty_deg"), 5.0)
    min_raw_hashes = int(_number(thresholds.get("min_raw_data_hashes"), 1))
    phase_uncertainty = _number_or_none(phase_reference.get("reference_uncertainty_deg"))
    raw_hashes = [str(item).strip() for item in raw_lineage.get("raw_data_hashes", ()) if str(item).strip()]

    checks = [
        _check(
            "研究授权声明有效",
            bool(authorization.get("approved_for_research")) and str(authorization.get("approval_id", "")).strip() not in {"", "DEMO-ONLY"},
            f"approval_id={authorization.get('approval_id', '未声明')}",
            "P0",
        ),
        _check(
            "真实源链可追溯",
            str(source_chain.get("status", "")).lower() == "verified" and bool(str(source_chain.get("source_chain_hash", "")).strip()),
            f"status={source_chain.get('status', '未声明')}",
            "P0",
        ),
        _check(
            "相位参考已锁定",
            bool(phase_reference.get("locked_reference")) and str(phase_reference.get("status", "")).lower() == "verified",
            f"status={phase_reference.get('status', '未声明')}",
            "P0",
        ),
        _check(
            "相位参考不确定度达标",
            phase_uncertainty is not None and phase_uncertainty <= max_phase_uncertainty,
            f"reference_uncertainty_deg={phase_uncertainty}",
            "P0",
        ),
        _check(
            "校准证书可复查",
            bool(calibration.get("valid_for_dataset")) and bool(str(calibration.get("certificate_sha256", "")).strip()),
            f"certificate_id={calibration.get('certificate_id', '未声明')}",
            "P0",
        ),
        _check(
            "测量不确定度模型已声明",
            bool(uncertainty_model.get("amplitude_sigma_declared")) and bool(uncertainty_model.get("phase_sigma_declared")),
            f"status={uncertainty_model.get('status', '未声明')}",
            "P1",
        ),
        _check(
            "原始数据哈希可追溯",
            len(raw_hashes) >= min_raw_hashes and bool(raw_lineage.get("immutable_archive")),
            f"hash_count={len(raw_hashes)}",
            "P1",
        ),
        _check("安全边界已声明", bool(config.get("safety_boundary")), "不输出真实作用距离/器件阈值/毁伤概率", "P1"),
    ]
    source_chain_ready = all(item["通过"] for item in checks if item["严重度"] == "P0")
    formal_ready = source_chain_ready and all(item["通过"] for item in checks)
    return {
        "版本": str(config.get("version", "V3.0-evidence-chain-v1")),
        "名称": "外部数据证据链与相位参考审计",
        "数据集ID": str(config.get("dataset_id", "V30-MEASUREMENT-CAMPAIGN")),
        "通过": bool(formal_ready),
        "真实源链与相位参考已接入": bool(source_chain_ready),
        "可纳入正式可信度评分证据": bool(formal_ready),
        "验收清单": checks,
        "阻断项": [item for item in checks if not item["通过"]],
        "证据摘要": {
            "授权": _summary_value(authorization, "approval_id"),
            "源链状态": source_chain.get("status"),
            "相位参考状态": phase_reference.get("status"),
            "相位参考不确定度deg": phase_uncertainty,
            "校准证书": calibration.get("certificate_id"),
            "原始数据哈希数": len(raw_hashes),
        },
        "配置": str(config.get("__path__", DEFAULT_EVIDENCE_CONFIG)),
        "输出文件": str(Path(output_file).resolve()) if output_file else None,
        "CSV": str(Path(csv_file).resolve()) if csv_file else None,
        "安全边界": str(config.get("safety_boundary") or SAFETY_BOUNDARY),
        "生成时间UTC": datetime.now(timezone.utc).isoformat(),
    }


def evidence_source_chain_ready(report: Mapping[str, Any] | None) -> bool:
    return bool(report and report.get("真实源链与相位参考已接入"))


def _manifest_names(rules: Mapping[str, Any]) -> list[str]:
    configured = rules.get("manifest_names")
    if isinstance(configured, (list, tuple)):
        names = [str(item).strip() for item in configured if str(item).strip()]
    else:
        names = []
    defaults = [
        "external_data_evidence.yaml",
        "external_data_evidence.yml",
        "external_data_evidence.json",
        "EXTERNAL_DATA_EVIDENCE.yaml",
    ]
    return list(dict.fromkeys(names + defaults))


def _forbidden_package_tokens(rules: Mapping[str, Any]) -> list[str]:
    configured = rules.get("forbidden_fields")
    tokens = [str(item).strip() for item in configured if str(item).strip()] if isinstance(configured, (list, tuple)) else []
    defaults = [
        "real_effect_distance",
        "effect_distance",
        "action_distance",
        "device_threshold",
        "damage_probability",
        "kill_probability",
        "作用距离",
        "器件阈值",
        "毁伤概率",
        "作战效能",
    ]
    return list(dict.fromkeys(tokens + defaults))


def _read_evidence_package(
    package: Path,
    manifest_names: list[str],
    *,
    max_files: int,
    max_bytes: int,
) -> tuple[str, str, str, list[dict[str, Any]]]:
    if not package.exists():
        raise FileNotFoundError(f"证据包路径不存在：{package}")
    if package.is_dir():
        return _read_evidence_directory(package, manifest_names, max_files=max_files, max_bytes=max_bytes)
    if zipfile.is_zipfile(package):
        return _read_evidence_zip(package, manifest_names, max_files=max_files, max_bytes=max_bytes)
    raise ValueError(f"证据包必须是 ZIP 文件或目录：{package}")


def _read_evidence_directory(
    package: Path,
    manifest_names: list[str],
    *,
    max_files: int,
    max_bytes: int,
) -> tuple[str, str, str, list[dict[str, Any]]]:
    files = sorted(item for item in package.rglob("*") if item.is_file())
    if len(files) > max_files:
        raise ValueError(f"证据包文件数超过上限：{len(files)} > {max_files}")

    records: list[dict[str, Any]] = []
    manifest_name = ""
    manifest_text = ""
    total_bytes = 0
    for file_path in files:
        payload = file_path.read_bytes()
        total_bytes += len(payload)
        if total_bytes > max_bytes:
            raise ValueError(f"证据包总大小超过上限：{total_bytes} > {max_bytes}")
        rel_path = file_path.relative_to(package).as_posix()
        is_manifest = _is_manifest_name(rel_path, manifest_names)
        if is_manifest and not manifest_text:
            manifest_name = rel_path
            manifest_text = payload.decode("utf-8")
        records.append(_package_file_record(rel_path, payload, is_manifest))
    if not manifest_text:
        raise ValueError(f"证据包缺少 manifest：{', '.join(manifest_names)}")
    return "directory", manifest_name, manifest_text, records


def _read_evidence_zip(
    package: Path,
    manifest_names: list[str],
    *,
    max_files: int,
    max_bytes: int,
) -> tuple[str, str, str, list[dict[str, Any]]]:
    with zipfile.ZipFile(package) as archive:
        infos = sorted((item for item in archive.infolist() if not item.is_dir()), key=lambda item: item.filename)
        if len(infos) > max_files:
            raise ValueError(f"证据包文件数超过上限：{len(infos)} > {max_files}")

        records: list[dict[str, Any]] = []
        manifest_name = ""
        manifest_text = ""
        total_bytes = 0
        for info in infos:
            rel_path = info.filename.replace("\\", "/").lstrip("/")
            payload = archive.read(info)
            total_bytes += len(payload)
            if total_bytes > max_bytes:
                raise ValueError(f"证据包总大小超过上限：{total_bytes} > {max_bytes}")
            is_manifest = _is_manifest_name(rel_path, manifest_names)
            if is_manifest and not manifest_text:
                manifest_name = rel_path
                manifest_text = payload.decode("utf-8")
            records.append(_package_file_record(rel_path, payload, is_manifest))
    if not manifest_text:
        raise ValueError(f"证据包缺少 manifest：{', '.join(manifest_names)}")
    return "zip", manifest_name, manifest_text, records


def _package_file_record(rel_path: str, payload: bytes, is_manifest: bool) -> dict[str, Any]:
    return {
        "路径": rel_path,
        "角色": "manifest" if is_manifest else "data",
        "大小bytes": len(payload),
        "SHA256": hashlib.sha256(payload).hexdigest(),
    }


def _is_manifest_name(rel_path: str, manifest_names: list[str]) -> bool:
    normalized = rel_path.replace("\\", "/").lower()
    basename = normalized.rsplit("/", 1)[-1]
    for name in manifest_names:
        candidate = name.replace("\\", "/").lower()
        if normalized == candidate or basename == candidate.rsplit("/", 1)[-1]:
            return True
    return False


def _parse_evidence_manifest(manifest_text: str, manifest_name: str) -> dict[str, Any]:
    if manifest_name.lower().endswith(".json"):
        payload = json.loads(manifest_text)
    else:
        payload = yaml.safe_load(manifest_text) or {}
    if not isinstance(payload, dict):
        raise ValueError(f"证据包 manifest 必须是映射：{manifest_name}")
    return payload


def _declared_raw_hashes(manifest: Mapping[str, Any]) -> list[str]:
    evidence = _mapping(manifest.get("evidence"))
    raw_lineage = _mapping(evidence.get("raw_data_lineage"))
    hashes = raw_lineage.get("raw_data_hashes", ())
    if not isinstance(hashes, (list, tuple, set)):
        return []
    return [str(item).strip().lower() for item in hashes if str(item).strip()]


def _scan_forbidden_tokens(value: Any, tokens: list[str], path: str = "$") -> list[str]:
    hits: list[str] = []
    if isinstance(value, Mapping):
        for key, child in value.items():
            key_text = str(key)
            child_path = f"{path}.{key_text}"
            for token in tokens:
                if token and token.lower() in key_text.lower():
                    hits.append(f"{child_path} 命中 {token}")
            if key_text in {"safety_boundary", "usage_scope", "traceability_note", "coverage_statement"} and isinstance(child, str):
                continue
            hits.extend(_scan_forbidden_tokens(child, tokens, child_path))
    elif isinstance(value, (list, tuple, set)):
        for index, child in enumerate(value):
            hits.extend(_scan_forbidden_tokens(child, tokens, f"{path}[{index}]"))
    elif isinstance(value, str):
        lower_value = value.lower()
        for token in tokens:
            if token and token.lower() in lower_value:
                hits.append(f"{path} 值命中 {token}")
    return hits


def _check(name: str, passed: bool, evidence: Any, severity: str) -> dict[str, Any]:
    return {"项目": name, "通过": bool(passed), "证据": str(evidence), "严重度": severity}


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _number(value: Any, default: float) -> float:
    try:
        if value is None or value == "":
            return float(default)
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def _number_or_none(value: Any) -> float | None:
    try:
        if value is None or value == "":
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _summary_value(payload: Mapping[str, Any], key: str) -> str:
    value = str(payload.get(key, "")).strip()
    return value or "未声明"


def _write_checks_csv(path: Path, checks: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["项目", "通过", "证据", "严重度"], extrasaction="ignore")
        writer.writeheader()
        writer.writerows(checks)

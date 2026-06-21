"""External measurement evidence-chain audit for V3.0 data import.

The evidence chain records provenance, authorization, source-chain,
phase-reference, calibration, and uncertainty metadata. It is deliberately a
research V&V gate, not a real effect or device-threshold model.
"""
from __future__ import annotations

from datetime import datetime, timezone
import csv
import json
from pathlib import Path
from typing import Any, Mapping

import yaml

from hpm_platform.data_import.importers import DEFAULT_OUTPUT, SAFETY_BOUNDARY


PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_EVIDENCE_CONFIG = PROJECT_ROOT / "configs" / "external_data_evidence.yaml"
EVIDENCE_OUTPUT_NAME = "evidence_chain_report.json"
EVIDENCE_CSV_NAME = "evidence_chain_checks.csv"


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

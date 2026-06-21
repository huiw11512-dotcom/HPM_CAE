"""V2.0B Three.js 三维 CAE 工作台场景服务。

该模块把现有 :class:`CAEProject` 投影为前端可渲染的三维场景 JSON，并提供
受控对象属性更新。工程模型仍然是唯一可信来源，所有更新都会重新走
``CAEProject`` 的几何与安全边界校验。
"""
from __future__ import annotations

import csv
from dataclasses import replace
from pathlib import Path
import hashlib
import json
import re
import sqlite3
import threading
import time
from typing import Any, Iterable, Mapping

import numpy as np

from hpm_platform.physics.array_geometry import RectangularArray
from hpm_platform.ui.project_model import (
    ApertureSpec,
    CAEProject,
    CavitySpec,
    MaterialSpec,
    ProtectedZoneSpec,
    ReflectingPlaneSpec,
    TargetRegionSpec,
    default_project,
)
from hpm_platform.ui.quick_solver import solve_project
from hpm_platform.validation.model_validity import assess_model_validity

WORKBENCH3D_VERSION = "V2.0B-preview"
_JOB_ID_RE = re.compile(r"^JOB-\d{4}$")
_SOL_ID_RE = re.compile(r"^SOL-\d{4}$")
_SNP_ID_RE = re.compile(r"^SNP-\d{4}$")
_HASH16_RE = re.compile(r"^[0-9a-f]{16}$")
_ABSOLUTE_CALIBRATION_VERSION = "V2.0B-absolute-calibration"
_IMPORTED_CALIBRATION_VERSION = "V3.0-imported-calibration-to-workbench"
_ABSOLUTE_CALIBRATION_FORBIDDEN_KEYS = (
    "threshold",
    "damage",
    "kill",
    "effect_distance",
    "maximum_effect",
    "max_range",
    "max_distance",
    "阈值",
    "毁伤",
    "损伤",
    "失效",
    "作用距离",
    "效应距离",
    "最大距离",
)

TARGET_FIELDS = {
    "enabled",
    "center_x_lambda",
    "center_y_lambda",
    "semi_major_lambda",
    "semi_minor_lambda",
    "rotation_deg",
    "guard_scale",
    "amplitude_scale",
    "priority",
    "tolerance_percent",
}
PROTECTED_FIELDS = {
    "enabled",
    "center_x_lambda",
    "center_y_lambda",
    "radius_lambda",
    "priority",
    "max_amplitude_scale",
}
REFLECTOR_FIELDS = {"enabled", "axis", "coordinate_lambda", "material_id"}
CAVITY_FIELDS = {
    "enabled",
    "center_x_lambda",
    "center_y_lambda",
    "center_z_lambda",
    "size_x_lambda",
    "size_y_lambda",
    "size_z_lambda",
    "quality_factor",
    "leakage_scale",
    "modes_x",
    "modes_y",
    "modes_z",
    "material_id",
}
APERTURE_FIELDS = {
    "enabled",
    "center_x_lambda",
    "center_y_lambda",
    "center_z_lambda",
    "radius_lambda",
    "coupling_scale",
    "cavity_id",
}
MATERIAL_FIELDS = {
    "name",
    "relative_permittivity",
    "loss_tangent",
    "reflection_magnitude",
    "reflection_phase_deg",
    "roughness_proxy",
}


def _num(value: float, digits: int = 6) -> float:
    return round(float(value), digits)


def _vec(values: Iterable[float]) -> list[float]:
    return [_num(value) for value in values]


def _finite(value: Any, digits: int = 4) -> Any:
    if isinstance(value, (np.floating, float)):
        return round(float(value), digits) if np.isfinite(float(value)) else None
    if isinstance(value, (np.integer, int)):
        return int(value)
    if isinstance(value, np.bool_):
        return bool(value)
    return value


def _scene_hash(payload: Mapping[str, Any]) -> str:
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()[:16]


def _reject_absolute_calibration_forbidden_keys(payload: Any, path: str = "") -> None:
    if isinstance(payload, Mapping):
        for key, value in payload.items():
            key_text = str(key)
            key_lower = key_text.lower()
            if any(token in key_lower or token in key_text for token in _ABSOLUTE_CALIBRATION_FORBIDDEN_KEYS):
                location = f"{path}.{key_text}" if path else key_text
                raise ValueError(
                    f"绝对量纲标定接口不接受真实器件阈值、损伤/失效条件或作用距离反推字段：{location}"
                )
            _reject_absolute_calibration_forbidden_keys(value, f"{path}.{key_text}" if path else key_text)
    elif isinstance(payload, list):
        for index, value in enumerate(payload):
            _reject_absolute_calibration_forbidden_keys(value, f"{path}[{index}]")


def _finite_float(value: Any, name: str) -> float:
    try:
        output = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} 必须是有限数值") from exc
    if not np.isfinite(output):
        raise ValueError(f"{name} 必须是有限数值")
    return output


def _number_list(value: Any, name: str) -> list[float]:
    if isinstance(value, str):
        tokens = [item for item in re.split(r"[\s,;，；]+", value.strip()) if item]
        return [_finite_float(item, name) for item in tokens]
    if isinstance(value, Iterable) and not isinstance(value, (bytes, bytearray, Mapping)):
        return [_finite_float(item, name) for item in value]
    raise ValueError(f"{name} 必须是数值列表或分隔文本")


def _element_id(row: int, col: int) -> str:
    return f"E{row + 1:02d}-{col + 1:02d}"


def _default_absolute_calibration(project: CAEProject) -> dict[str, Any]:
    nx = int(project.array.nx)
    ny = int(project.array.ny)
    powers = [
        {"element_id": _element_id(row, col), "row": row + 1, "col": col + 1, "power_w": 1.0}
        for row in range(ny)
        for col in range(nx)
    ]
    return {
        "版本": _ABSOLUTE_CALIBRATION_VERSION,
        "模式": "实测点绝对量纲标定",
        "阵元功率": powers,
        "实测标定点": [
            {
                "point_id": "CAL-001",
                "label": "近场实测点A",
                "distance_m": 1.0,
                "normalized_model_amplitude": 1.0,
                "measured_field_v_per_m": 2.0,
                "uncertainty_percent": 8.0,
            },
            {
                "point_id": "CAL-002",
                "label": "近场实测点B",
                "distance_m": 1.5,
                "normalized_model_amplitude": 0.72,
                "measured_field_v_per_m": 1.46,
                "uncertainty_percent": 8.0,
            },
            {
                "point_id": "CAL-003",
                "label": "近场实测点C",
                "distance_m": 2.0,
                "normalized_model_amplitude": 0.55,
                "measured_field_v_per_m": 1.08,
                "uncertainty_percent": 10.0,
            },
        ],
        "说明": "阵元功率和距离只作为实验记录与实测标定元数据；核心快速求解器仍使用归一化场，不做作用距离或器件阈值反推。",
    }


def _normalize_element_powers(project: CAEProject, value: Any) -> list[dict[str, Any]]:
    nx = int(project.array.nx)
    ny = int(project.array.ny)
    expected = nx * ny
    if value is None:
        return list(_default_absolute_calibration(project)["阵元功率"])
    if isinstance(value, Mapping):
        for key in ("阵元功率", "element_powers_w", "element_powers", "powers_w"):
            if key in value:
                value = value[key]
                break
    if isinstance(value, str) or (
        isinstance(value, Iterable) and not isinstance(value, (bytes, bytearray, Mapping))
    ):
        raw_items = list(value) if not isinstance(value, str) else value
        if isinstance(raw_items, str):
            numbers = _number_list(raw_items, "element_powers_w")
            raw_items = numbers
        if raw_items and all(not isinstance(item, Mapping) for item in raw_items):
            numbers = [_finite_float(item, "element_powers_w") for item in raw_items]
            if len(numbers) == 1:
                numbers = numbers * expected
            if len(numbers) != expected:
                raise ValueError(f"阵元功率数量必须为 {expected} 个，当前为 {len(numbers)} 个")
            records = []
            for index, power in enumerate(numbers):
                if power < 0:
                    raise ValueError("阵元功率必须为非负数")
                row = index // nx
                col = index % nx
                records.append({"element_id": _element_id(row, col), "row": row + 1, "col": col + 1, "power_w": _num(power, 9)})
            return records
        if raw_items and all(isinstance(item, Mapping) for item in raw_items):
            if len(raw_items) != expected:
                raise ValueError(f"阵元功率记录数量必须为 {expected} 个，当前为 {len(raw_items)} 个")
            records = []
            for index, item in enumerate(raw_items):
                row = int(item.get("row") or (index // nx + 1))
                col = int(item.get("col") or (index % nx + 1))
                if not 1 <= row <= ny or not 1 <= col <= nx:
                    raise ValueError("阵元功率 row/col 超出当前阵列范围")
                power = _finite_float(item.get("power_w", item.get("功率W", item.get("power", 0.0))), "power_w")
                if power < 0:
                    raise ValueError("阵元功率必须为非负数")
                records.append(
                    {
                        "element_id": str(item.get("element_id") or item.get("阵元id") or _element_id(row - 1, col - 1)),
                        "row": row,
                        "col": col,
                        "power_w": _num(power, 9),
                    }
                )
            return records
    raise ValueError("阵元功率必须为数值列表、记录列表或分隔文本")


def _normalize_calibration_points(value: Any) -> list[dict[str, Any]]:
    if value is None:
        return list(_default_absolute_calibration(default_project())["实测标定点"])
    if isinstance(value, Mapping):
        for key in ("实测标定点", "calibration_points", "measurement_points", "points"):
            if key in value:
                value = value[key]
                break
    if not isinstance(value, list):
        raise ValueError("实测标定点必须是列表")
    points: list[dict[str, Any]] = []
    for index, item in enumerate(value[:48]):
        if not isinstance(item, Mapping):
            raise ValueError("实测标定点必须是对象列表")
        distance = _finite_float(item.get("distance_m", item.get("距离m", 0.0)), "distance_m")
        normalized = _finite_float(
            item.get("normalized_model_amplitude", item.get("归一化模型幅值", item.get("model", 0.0))),
            "normalized_model_amplitude",
        )
        measured = _finite_float(
            item.get("measured_field_v_per_m", item.get("实测场强Vpm", item.get("measured", 0.0))),
            "measured_field_v_per_m",
        )
        uncertainty = _finite_float(item.get("uncertainty_percent", item.get("不确定度百分比", 10.0)), "uncertainty_percent")
        if distance <= 0:
            raise ValueError("实测标定点 distance_m 必须为正数")
        if normalized < 0 or measured < 0:
            raise ValueError("归一化模型幅值和实测场强必须为非负数")
        if not 0 <= uncertainty <= 500:
            raise ValueError("uncertainty_percent 必须位于 [0, 500]")
        points.append(
            {
                "point_id": str(item.get("point_id") or item.get("id") or f"CAL-{index + 1:03d}"),
                "label": str(item.get("label") or item.get("标签") or f"实测点{index + 1}"),
                "distance_m": _num(distance, 6),
                "normalized_model_amplitude": _num(normalized, 9),
                "measured_field_v_per_m": _num(measured, 9),
                "uncertainty_percent": _num(uncertainty, 6),
            }
        )
    if not points:
        raise ValueError("至少需要 1 个实测标定点")
    return points


def _normalize_absolute_calibration(project: CAEProject, payload: Mapping[str, Any] | None) -> dict[str, Any]:
    payload = dict(payload or {})
    _reject_absolute_calibration_forbidden_keys(payload)
    powers_source = payload.get("阵元功率") if "阵元功率" in payload else payload.get("element_powers_w")
    if powers_source is None:
        powers_source = payload.get("element_powers") if "element_powers" in payload else payload.get("powers_w")
    points_source = payload.get("实测标定点") if "实测标定点" in payload else payload.get("calibration_points")
    if points_source is None:
        points_source = payload.get("measurement_points") if "measurement_points" in payload else payload.get("points")
    return {
        "版本": _ABSOLUTE_CALIBRATION_VERSION,
        "模式": "实测点绝对量纲标定",
        "阵元功率": _normalize_element_powers(project, powers_source),
        "实测标定点": _normalize_calibration_points(points_source),
        "说明": "阵元功率和距离只作为实验记录与实测标定元数据；核心快速求解器仍使用归一化场，不做作用距离或器件阈值反推。",
    }


def _absolute_calibration_analysis(
    project: CAEProject,
    calibration: Mapping[str, Any],
    *,
    revision: int,
    paths: Mapping[str, str | None] | None = None,
) -> dict[str, Any]:
    powers = [dict(item) for item in calibration.get("阵元功率", []) if isinstance(item, Mapping)]
    points = [dict(item) for item in calibration.get("实测标定点", []) if isinstance(item, Mapping)]
    power_values = np.asarray([float(item.get("power_w", 0.0)) for item in powers], dtype=float)
    nonzero = power_values[power_values > 0]
    total_power = float(np.sum(power_values)) if power_values.size else 0.0
    mean_power = float(np.mean(power_values)) if power_values.size else 0.0
    power_std = float(np.std(power_values)) if power_values.size else 0.0
    imbalance_db = None
    if nonzero.size >= 2 and float(np.min(nonzero)) > 0:
        imbalance_db = float(10.0 * np.log10(float(np.max(nonzero)) / float(np.min(nonzero))))

    x = np.asarray([float(item.get("normalized_model_amplitude", 0.0)) for item in points], dtype=float)
    y = np.asarray([float(item.get("measured_field_v_per_m", 0.0)) for item in points], dtype=float)
    uncertainty_percent = np.asarray([float(item.get("uncertainty_percent", 0.0)) for item in points], dtype=float)
    sigma = np.maximum(y * uncertainty_percent / 100.0, 1e-12)
    valid = np.isfinite(x) & np.isfinite(y) & np.isfinite(sigma) & (x > 0) & (y >= 0)
    scale = None
    predicted = np.full_like(y, np.nan, dtype=float)
    residual = np.full_like(y, np.nan, dtype=float)
    if np.any(valid):
        weights = 1.0 / np.square(sigma[valid])
        denominator = float(np.sum(weights * np.square(x[valid])))
        if denominator > np.finfo(float).tiny:
            scale = float(np.sum(weights * x[valid] * y[valid]) / denominator)
            predicted = scale * x
            residual = y - predicted
    residual_valid = valid & np.isfinite(residual)
    rmse = float(np.sqrt(np.mean(np.square(residual[residual_valid])))) if np.any(residual_valid) else None
    mean_measured = float(np.mean(y[valid])) if np.any(valid) else None
    relative_rmse = float(100.0 * rmse / max(mean_measured or 0.0, 1e-12)) if rmse is not None else None
    coverage_2sigma = (
        float(100.0 * np.mean(np.abs(residual[residual_valid]) <= 2.0 * sigma[residual_valid]))
        if np.any(residual_valid)
        else None
    )
    distances = np.asarray([float(item.get("distance_m", 0.0)) for item in points], dtype=float)
    valid_distances = distances[np.isfinite(distances) & (distances > 0)]
    point_rows: list[dict[str, Any]] = []
    for index, item in enumerate(points):
        estimate = predicted[index] if index < predicted.size else np.nan
        error = residual[index] if index < residual.size else np.nan
        measured = float(item.get("measured_field_v_per_m", 0.0))
        rel_error = 100.0 * error / max(measured, 1e-12) if np.isfinite(error) else None
        point_rows.append(
            {
                **item,
                "calibrated_estimate_v_per_m": _finite(estimate, 6) if np.isfinite(estimate) else None,
                "residual_v_per_m": _finite(error, 6) if np.isfinite(error) else None,
                "relative_error_percent": _finite(rel_error, 4) if rel_error is not None and np.isfinite(rel_error) else None,
                "uncertainty_v_per_m": _finite(sigma[index], 6) if index < sigma.size and np.isfinite(sigma[index]) else None,
                "within_2sigma": bool(abs(error) <= 2.0 * sigma[index]) if index < sigma.size and np.isfinite(error) else None,
            }
        )

    expected_elements = int(project.array.nx) * int(project.array.ny)
    checks = [
        {
            "项目": "阵元功率数量匹配",
            "通过": len(powers) == expected_elements,
            "说明": f"当前 {len(powers)} 个，阵列需要 {expected_elements} 个。",
        },
        {
            "项目": "阵元功率为有限非负数",
            "通过": bool(power_values.size == expected_elements and np.all(np.isfinite(power_values)) and np.all(power_values >= 0)),
            "说明": f"总输入功率元数据 {total_power:.6g} W，仅用于标定记录。",
        },
        {
            "项目": "实测标定点可拟合",
            "通过": bool(np.count_nonzero(valid) >= 2 and scale is not None),
            "说明": f"有效点 {int(np.count_nonzero(valid))} 个；拟合系数 {scale:.6g} V/m per normalized unit。" if scale is not None else f"有效点 {int(np.count_nonzero(valid))} 个。",
        },
        {
            "项目": "残差可审计",
            "通过": rmse is not None,
            "说明": f"RMSE {rmse:.6g} V/m，相对 RMSE {relative_rmse:.3g}%。" if rmse is not None and relative_rmse is not None else "暂无可审计残差。",
        },
        {
            "项目": "未输出作用距离或器件阈值",
            "通过": True,
            "说明": "仅返回实测点覆盖区间、校准系数、残差和不确定度；不做阈值到距离的反推。",
        },
    ]
    return {
        "版本": _ABSOLUTE_CALIBRATION_VERSION,
        "更新时间": time.strftime("%Y-%m-%d %H:%M:%S"),
        "修订": int(revision),
        "结论": "通过" if all(bool(item["通过"]) for item in checks) else "关注",
        "通过": all(bool(item["通过"]) for item in checks),
        "阵列": {
            "nx": int(project.array.nx),
            "ny": int(project.array.ny),
            "阵元数": expected_elements,
            "frequency_ghz": _num(project.array.frequency_ghz, 6),
        },
        "功率元数据": {
            "总输入功率_w": _num(total_power, 9),
            "平均阵元功率_w": _num(mean_power, 9),
            "阵元功率标准差_w": _num(power_std, 9),
            "启用阵元数": int(nonzero.size),
            "阵元功率不均衡_db": _num(imbalance_db, 6) if imbalance_db is not None else None,
            "用途": "实验记录与量纲标定元数据，不参与作用距离或器件阈值计算。",
        },
        "校准结果": {
            "校准系数_v_per_m_per_normalized_unit": _num(scale, 9) if scale is not None else None,
            "残差RMSE_v_per_m": _num(rmse, 9) if rmse is not None else None,
            "相对RMSE_percent": _num(relative_rmse, 6) if relative_rmse is not None else None,
            "2sigma覆盖率_percent": _num(coverage_2sigma, 6) if coverage_2sigma is not None else None,
            "实测距离覆盖区间_m": {
                "最小": _num(float(np.min(valid_distances)), 6) if valid_distances.size else None,
                "最大": _num(float(np.max(valid_distances)), 6) if valid_distances.size else None,
                "说明": "仅表示已有实测标定点的距离范围，不是作用距离、射程或阈值距离。",
            },
            "外推": "禁止外推为真实作用距离或器件阈值。",
        },
        "阵元功率": powers,
        "实测标定点": point_rows,
        "验收清单": checks,
        "索引": dict(paths or {}),
        "不输出项": ["真实作用距离", "器件失效阈值", "损伤/毁伤概率", "阈值到距离反推"],
        "安全边界": "绝对量纲标定只把用户输入的阵元功率元数据与实测标定点绑定到归一化模型，输出校准系数、残差、不确定度和实测覆盖区间；不输出真实作用距离、器件阈值、损伤概率或可操作效应范围。",
    }


def _load_json_report(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return dict(payload) if isinstance(payload, Mapping) else {}


def _basename(value: Any) -> str | None:
    if not value:
        return None
    return Path(str(value)).name


def _imported_calibration_payload(
    output_dir: Path | None,
    *,
    paths: Mapping[str, str | None] | None = None,
) -> dict[str, Any]:
    data_dir = output_dir / "data_import_v30" if output_dir is not None else None
    bridge_path = data_dir / "calibration_bridge_report.json" if data_dir is not None else None
    comparison_path = data_dir / "model_comparison_report.json" if data_dir is not None else None
    audit_path = data_dir / "external_data_vv_audit.json" if data_dir is not None else None

    bridge = _load_json_report(bridge_path) if bridge_path is not None else {}
    comparison = _load_json_report(comparison_path) if comparison_path is not None else {}
    audit = _load_json_report(audit_path) if audit_path is not None else {}

    residual = comparison.get("误差对比") if isinstance(comparison.get("误差对比"), Mapping) else {}
    coverage = comparison.get("不确定度覆盖率") if isinstance(comparison.get("不确定度覆盖率"), Mapping) else {}
    formal_strategy = audit.get("正式评分策略") if isinstance(audit.get("正式评分策略"), Mapping) else {}
    formal_ready = bool(audit.get("可纳入正式可信度评分"))
    bridge_ready = bool(bridge.get("通过")) and bool(bridge.get("CalibrationSamples兼容"))
    comparison_ready = bool(comparison.get("通过")) and bool(residual)
    coverage_ready = bool(coverage.get("不确定度可用"))
    blockers = [
        *([str(item) for item in bridge.get("阻断项", [])] if isinstance(bridge.get("阻断项"), list) else []),
        *([str(item) for item in comparison.get("阻断项", [])] if isinstance(comparison.get("阻断项"), list) else []),
    ]

    checks = [
        {
            "项目": "导入样本进入标定接口",
            "通过": bridge_ready,
            "说明": f"样本 {bridge.get('样本数', 0)} 个，CalibrationSamples兼容={bool(bridge.get('CalibrationSamples兼容'))}",
        },
        {
            "项目": "模型误差对比可复查",
            "通过": comparison_ready,
            "说明": f"标定后相对RMSE {residual.get('标定后相对RMSE/%', '--')}%，代理模型求解成功={residual.get('求解成功', '--')}",
        },
        {
            "项目": "测量不确定度覆盖率可审计",
            "通过": coverage_ready,
            "说明": f"2sigma覆盖率 {coverage.get('2sigma覆盖率/%', '--')}%，中位归一化残差 {coverage.get('中位归一化残差', '--')}",
        },
        {
            "项目": "真实源链与相位参考正式门槛",
            "通过": formal_ready,
            "说明": "未满足时只作为外部数据风险附注，不改写 V2.0A 正式可信度评分。",
        },
        {
            "项目": "未输出作用距离或器件阈值",
            "通过": True,
            "说明": "桥接层只保留导入源、坐标归一化、残差和不确定度证据。",
        },
    ]
    passed = bridge_ready and comparison_ready and not blockers
    source_path = bridge.get("导入源文件")
    return {
        "版本": _IMPORTED_CALIBRATION_VERSION,
        "更新时间": time.strftime("%Y-%m-%d %H:%M:%S"),
        "结论": "桥接可复查" if passed else "关注",
        "通过": bool(passed),
        "样例ID": bridge.get("样例ID") or comparison.get("样例ID") or audit.get("样例ID"),
        "摘要": {
            "导入源文件": source_path,
            "导入源名称": _basename(source_path),
            "CSV条目": bridge.get("CSV条目"),
            "样本数": bridge.get("样本数") or comparison.get("样本数") or audit.get("样本数") or 0,
            "坐标来源单位": bridge.get("坐标来源单位"),
            "目标坐标": bridge.get("目标坐标"),
            "参考频率GHz": bridge.get("参考频率GHz"),
            "标定后相对RMSE/%": residual.get("标定后相对RMSE/%"),
            "2sigma覆盖率/%": coverage.get("2sigma覆盖率/%"),
            "预评分": audit.get("预评分"),
            "预评分等级": audit.get("预评分等级"),
            "可纳入正式可信度评分": formal_ready,
            "是否改写正式评分": bool(formal_strategy.get("是否改写正式评分")),
        },
        "桥接报告": {
            "路径": str(bridge_path) if bridge_path is not None else None,
            "通过": bool(bridge.get("通过")),
            "CalibrationSamples兼容": bool(bridge.get("CalibrationSamples兼容")),
            "代理激励": bridge.get("代理激励"),
            "规范化预览": bridge.get("规范化预览", [])[:5] if isinstance(bridge.get("规范化预览"), list) else [],
        },
        "模型误差对比": {
            "路径": str(comparison_path) if comparison_path is not None else None,
            "通过": bool(comparison.get("通过")),
            "误差对比": dict(residual),
            "不确定度覆盖率": dict(coverage),
            "逐点残差": comparison.get("逐点残差", [])[:12] if isinstance(comparison.get("逐点残差"), list) else [],
            "门槛": comparison.get("门槛", []) if isinstance(comparison.get("门槛"), list) else [],
        },
        "外部数据V&V审计": {
            "路径": str(audit_path) if audit_path is not None else None,
            "通过": bool(audit.get("通过")),
            "可纳入正式可信度评分": formal_ready,
            "正式评分策略": dict(formal_strategy),
            "风险信号": audit.get("风险信号", []) if isinstance(audit.get("风险信号"), list) else [],
            "门槛": audit.get("门槛", []) if isinstance(audit.get("门槛"), list) else [],
        },
        "验收清单": checks,
        "阻断项": blockers,
        "索引": dict(paths or {}),
        "不输出项": ["真实作用距离", "器件阈值", "毁伤/失效概率", "阈值到距离反推"],
        "安全边界": "导入数据标定桥接只把外部测量/仿真样本、坐标归一化、代理模型残差和不确定度证据接入三维工作台资产台账；不把导入数据解释为真实源功率、器件阈值、现实作用距离或毁伤概率。",
    }


def _flatten_payload(value: Any, prefix: str = "") -> dict[str, Any]:
    if isinstance(value, Mapping):
        flattened: dict[str, Any] = {}
        for key, item in value.items():
            next_prefix = f"{prefix}.{key}" if prefix else str(key)
            flattened.update(_flatten_payload(item, next_prefix))
        return flattened
    if isinstance(value, list):
        flattened = {}
        for index, item in enumerate(value):
            next_prefix = f"{prefix}[{index}]"
            flattened.update(_flatten_payload(item, next_prefix))
        return flattened
    return {prefix: value}


def _diff_flattened(left: Mapping[str, Any], right: Mapping[str, Any]) -> list[dict[str, Any]]:
    changes: list[dict[str, Any]] = []
    keys = sorted(set(left) | set(right))
    for key in keys:
        left_value = left.get(key)
        right_value = right.get(key)
        if left_value != right_value:
            changes.append({"字段": key, "左": left_value, "右": right_value})
    return changes


def _object_record(
    *,
    object_id: str,
    name: str,
    object_type: str,
    layer: str,
    enabled: bool,
    geometry: Mapping[str, Any],
    properties: Mapping[str, Any],
    editable_fields: Iterable[str] = (),
    material_id: str | None = None,
) -> dict[str, Any]:
    return {
        "id": object_id,
        "名称": name,
        "类型": object_type,
        "层级": layer,
        "启用": bool(enabled),
        "材料": material_id,
        "几何": dict(geometry),
        "属性": dict(properties),
        "可编辑字段": sorted(editable_fields),
    }


def _material_records(project: CAEProject) -> list[dict[str, Any]]:
    usage: dict[str, list[str]] = {item.material_id: [] for item in project.materials}
    for reflector in project.reflecting_planes:
        usage.setdefault(reflector.material_id, []).append(reflector.object_id)
    for cavity in project.cavities:
        usage.setdefault(cavity.material_id, []).append(cavity.object_id)
    records: list[dict[str, Any]] = []
    for material in project.materials:
        records.append(
            {
                "id": material.material_id,
                "材料ID": material.material_id,
                "名称": material.name,
                "类型": "normalized_material_proxy",
                "引用对象": usage.get(material.material_id, []),
                "属性": {
                    "name": material.name,
                    "relative_permittivity": _num(material.relative_permittivity),
                    "loss_tangent": _num(material.loss_tangent),
                    "reflection_magnitude": _num(material.reflection_magnitude),
                    "reflection_phase_deg": _num(material.reflection_phase_deg),
                    "roughness_proxy": _num(material.roughness_proxy),
                },
                "可编辑字段": sorted(MATERIAL_FIELDS),
                "安全边界": "归一化材料代理，仅用于降阶反射/腔体模型，不等价于全波材料库或真实器件阈值。",
            }
        )
    return records


def _target_record(target: TargetRegionSpec, z_lambda: float) -> dict[str, Any]:
    return _object_record(
        object_id=target.object_id,
        name=target.name,
        object_type="target_region",
        layer="控场层",
        enabled=target.enabled,
        geometry={
            "kind": "elliptic_region",
            "center": _vec((target.center_x_lambda, target.center_y_lambda, z_lambda)),
            "semi_axes": _vec((target.semi_major_lambda, target.semi_minor_lambda)),
            "rotation_deg": _num(target.rotation_deg),
            "guard_scale": _num(target.guard_scale),
        },
        properties={
            "center_x_lambda": _num(target.center_x_lambda),
            "center_y_lambda": _num(target.center_y_lambda),
            "semi_major_lambda": _num(target.semi_major_lambda),
            "semi_minor_lambda": _num(target.semi_minor_lambda),
            "rotation_deg": _num(target.rotation_deg),
            "guard_scale": _num(target.guard_scale),
            "amplitude_scale": _num(target.amplitude_scale),
            "priority": _num(target.priority),
            "tolerance_percent": _num(target.tolerance_percent),
            "enabled": bool(target.enabled),
        },
        editable_fields=TARGET_FIELDS,
    )


def _protected_record(zone: ProtectedZoneSpec, z_lambda: float) -> dict[str, Any]:
    return _object_record(
        object_id=zone.object_id,
        name=zone.name,
        object_type="protected_zone",
        layer="防护层",
        enabled=zone.enabled,
        geometry={
            "kind": "circular_region",
            "center": _vec((zone.center_x_lambda, zone.center_y_lambda, z_lambda)),
            "radius": _num(zone.radius_lambda),
        },
        properties={
            "center_x_lambda": _num(zone.center_x_lambda),
            "center_y_lambda": _num(zone.center_y_lambda),
            "radius_lambda": _num(zone.radius_lambda),
            "priority": _num(zone.priority),
            "max_amplitude_scale": _num(zone.max_amplitude_scale),
            "enabled": bool(zone.enabled),
        },
        editable_fields=PROTECTED_FIELDS,
    )


def _reflector_record(reflector: ReflectingPlaneSpec, project: CAEProject) -> dict[str, Any]:
    span_x = project.plane.span_x_lambda
    span_y = project.plane.span_y_lambda
    z = project.plane.z_lambda
    return _object_record(
        object_id=reflector.object_id,
        name=reflector.name,
        object_type="reflecting_plane",
        layer="物理建模层",
        enabled=reflector.enabled,
        material_id=reflector.material_id,
        geometry={
            "kind": "axis_plane",
            "axis": reflector.axis,
            "coordinate_lambda": _num(reflector.coordinate_lambda),
            "span": _vec((span_x, span_y, z)),
        },
        properties={
            "axis": reflector.axis,
            "coordinate_lambda": _num(reflector.coordinate_lambda),
            "material_id": reflector.material_id,
            "enabled": bool(reflector.enabled),
        },
        editable_fields=REFLECTOR_FIELDS,
    )


def _cavity_record(cavity: CavitySpec) -> dict[str, Any]:
    return _object_record(
        object_id=cavity.object_id,
        name=cavity.name,
        object_type="cavity_rom",
        layer="物理建模层",
        enabled=cavity.enabled,
        material_id=cavity.material_id,
        geometry={
            "kind": "box",
            "center": _vec((cavity.center_x_lambda, cavity.center_y_lambda, cavity.center_z_lambda)),
            "size": _vec((cavity.size_x_lambda, cavity.size_y_lambda, cavity.size_z_lambda)),
        },
        properties={
            "center_x_lambda": _num(cavity.center_x_lambda),
            "center_y_lambda": _num(cavity.center_y_lambda),
            "center_z_lambda": _num(cavity.center_z_lambda),
            "size_x_lambda": _num(cavity.size_x_lambda),
            "size_y_lambda": _num(cavity.size_y_lambda),
            "size_z_lambda": _num(cavity.size_z_lambda),
            "quality_factor": _num(cavity.quality_factor),
            "leakage_scale": _num(cavity.leakage_scale),
            "modes_x": int(cavity.modes_x),
            "modes_y": int(cavity.modes_y),
            "modes_z": int(cavity.modes_z),
            "material_id": cavity.material_id,
            "enabled": bool(cavity.enabled),
        },
        editable_fields=CAVITY_FIELDS,
    )


def _aperture_record(aperture: ApertureSpec) -> dict[str, Any]:
    return _object_record(
        object_id=aperture.object_id,
        name=aperture.name,
        object_type="aperture",
        layer="物理建模层",
        enabled=aperture.enabled,
        geometry={
            "kind": "aperture_disc",
            "center": _vec((aperture.center_x_lambda, aperture.center_y_lambda, aperture.center_z_lambda)),
            "radius": _num(aperture.radius_lambda),
        },
        properties={
            "center_x_lambda": _num(aperture.center_x_lambda),
            "center_y_lambda": _num(aperture.center_y_lambda),
            "center_z_lambda": _num(aperture.center_z_lambda),
            "radius_lambda": _num(aperture.radius_lambda),
            "coupling_scale": _num(aperture.coupling_scale),
            "cavity_id": aperture.cavity_id,
            "enabled": bool(aperture.enabled),
        },
        editable_fields=APERTURE_FIELDS,
    )


def _interferer_record(source: Any, plane_z_lambda: float) -> dict[str, Any]:
    direction = RectangularArray.direction_vector(source.theta_deg, source.phi_deg).reshape(3)
    length = max(float(plane_z_lambda) * 1.2, 4.0)
    geometry = {
        "kind": "far_field_direction",
        "origin": _vec((0.0, 0.0, 0.0)),
        "direction": _vec(direction),
        "length": _num(length),
        "theta_deg": _num(source.theta_deg),
        "phi_deg": _num(source.phi_deg),
    }
    if source.echo_enabled:
        echo_direction = RectangularArray.direction_vector(source.echo_theta_deg, source.echo_phi_deg).reshape(3)
        geometry["echo_direction"] = _vec(echo_direction)
        geometry["echo_theta_deg"] = _num(source.echo_theta_deg)
        geometry["echo_phi_deg"] = _num(source.echo_phi_deg)
    return _object_record(
        object_id=source.object_id,
        name=source.name,
        object_type="far_field_source",
        layer="感知层",
        enabled=source.enabled,
        geometry=geometry,
        properties={
            "theta_deg": _num(source.theta_deg),
            "phi_deg": _num(source.phi_deg),
            "relative_power_db": _num(source.relative_power_db),
            "echo_enabled": bool(source.echo_enabled),
            "echo_theta_deg": _num(source.echo_theta_deg),
            "echo_phi_deg": _num(source.echo_phi_deg),
            "echo_relative_power_db": _num(source.echo_relative_power_db),
            "enabled": bool(source.enabled),
        },
    )


def build_workbench3d_scene(
    project: CAEProject,
    revision: int = 1,
    history: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Return a deterministic V2.0B scene payload for the current CAE project."""
    span_x = float(project.plane.span_x_lambda)
    span_y = float(project.plane.span_y_lambda)
    plane_z = float(project.plane.z_lambda)
    array_extent_x = (int(project.array.nx) - 1) * float(project.array.spacing_x_lambda)
    array_extent_y = (int(project.array.ny) - 1) * float(project.array.spacing_y_lambda)
    objects: list[dict[str, Any]] = [
        _object_record(
            object_id="ARR-001",
            name="矩形相控阵",
            object_type="array",
            layer="物理建模层",
            enabled=True,
            geometry={
                "kind": "rectangular_array",
                "center": _vec((0.0, 0.0, 0.0)),
                "nx": int(project.array.nx),
                "ny": int(project.array.ny),
                "spacing": _vec((project.array.spacing_x_lambda, project.array.spacing_y_lambda)),
                "size": _vec((array_extent_x, array_extent_y, 0.08)),
            },
            properties={
                "nx": int(project.array.nx),
                "ny": int(project.array.ny),
                "frequency_ghz": _num(project.array.frequency_ghz),
                "spacing_x_lambda": _num(project.array.spacing_x_lambda),
                "spacing_y_lambda": _num(project.array.spacing_y_lambda),
            },
        ),
        _object_record(
            object_id="OBS-001",
            name="观察面",
            object_type="observation_plane",
            layer="CAE平台层",
            enabled=True,
            geometry={
                "kind": "observation_plane",
                "center": _vec((0.0, 0.0, plane_z)),
                "size": _vec((span_x, span_y, 0.0)),
                "samples": int(project.plane.samples),
            },
            properties={
                "z_lambda": _num(project.plane.z_lambda),
                "span_x_lambda": _num(project.plane.span_x_lambda),
                "span_y_lambda": _num(project.plane.span_y_lambda),
                "samples": int(project.plane.samples),
            },
        ),
    ]
    objects.extend(_target_record(item, plane_z) for item in (project.target, *project.additional_targets))
    objects.extend(_protected_record(item, plane_z) for item in (project.protected_zone, *project.additional_protected_zones))
    objects.extend(_reflector_record(item, project) for item in project.reflecting_planes)
    objects.extend(_cavity_record(item) for item in project.cavities)
    objects.extend(_aperture_record(item) for item in project.apertures)
    objects.extend(_interferer_record(item, plane_z) for item in project.interferers)

    enabled_objects = [item for item in objects if item["启用"]]
    groups = [
        {"名称": "阵列与观察面", "对象": ["ARR-001", "OBS-001"]},
        {"名称": "目标区", "对象": [item.object_id for item in (project.target, *project.additional_targets)]},
        {"名称": "保护区", "对象": [item.object_id for item in (project.protected_zone, *project.additional_protected_zones)]},
        {"名称": "环境对象", "对象": [*(item.object_id for item in project.reflecting_planes), *(item.object_id for item in project.cavities), *(item.object_id for item in project.apertures)]},
        {"名称": "远场源", "对象": [item.object_id for item in project.interferers]},
    ]
    validation = {
        "通过": True,
        "检查": [
            "工程对象 ID 唯一",
            "目标区和保护区位于观察面范围内",
            "材料、腔体和孔缝引用关系有效",
            "核心求解使用归一化波长尺度；绝对功率只作为实测标定元数据",
        ],
        "边界": project.model_scope,
    }
    payload = {
        "版本": WORKBENCH3D_VERSION,
        "引擎": "Three.js 0.166.1",
        "阶段": "V2.0B 三维 CAE 编辑器原型",
        "修订": int(revision),
        "工程": {
            "名称": project.meta.name,
            "schema_version": project.schema_version,
            "传播后端": project.propagation.backend,
            "单位": "lambda",
            "坐标系": "右手系；阵列位于 x-y 平面 z=0；+z 为阵列法向和观察方向",
        },
        "材料库": _material_records(project),
        "视图": {
            "bounds": {
                "x": _vec((-span_x / 2.0, span_x / 2.0)),
                "y": _vec((-span_y / 2.0, span_y / 2.0)),
                "z": _vec((0.0, max(plane_z + 1.5, 4.0))),
            },
            "grid_step_lambda": 0.5 if max(span_x, span_y) <= 10.0 else 1.0,
        },
        "对象": objects,
        "对象树": groups,
        "统计": {
            "对象总数": len(objects),
            "启用对象数": len(enabled_objects),
            "目标区": len(project.targets),
            "保护区": len(project.protected_zones),
            "环境对象": len(project.active_reflectors) + len(project.active_cavities) + len(project.active_apertures),
            "远场源": len(project.active_interferers),
        },
        "校验": validation,
        "历史": dict(history or {}),
    }
    payload["scene_hash"] = _scene_hash(
        {key: value for key, value in payload.items() if key not in {"scene_hash", "历史", "修订"}}
    )
    return payload


def _quick_solve_project(project: CAEProject) -> CAEProject:
    samples = min(int(project.plane.samples), 51)
    if samples % 2 == 0:
        samples -= 1
    return replace(
        project,
        plane=replace(project.plane, samples=max(samples, 31)),
        solver=replace(
            project.solver,
            iterations=min(int(project.solver.iterations), 80),
            target_samples=min(int(project.solver.target_samples), 160),
            outside_samples=min(int(project.solver.outside_samples), 360),
            uncertainty_scenarios=min(int(project.solver.uncertainty_scenarios), 3),
        ),
    )


def _result_layer_payload(result: Any) -> dict[str, Any]:
    db_min = -30.0
    db_max = 4.0
    field_db = np.clip(result.field_db, db_min, db_max)
    values = [[_num(value, 3) for value in row] for row in field_db.tolist()]
    center_x_index = int(np.argmin(np.abs(result.x_lambda)))
    center_y_index = int(np.argmin(np.abs(result.y_lambda)))
    peak_y_index, peak_x_index = (int(value) for value in np.unravel_index(np.argmax(field_db), field_db.shape))
    payload = {
        "类型": "observation_field_db",
        "名称": "观察面归一化场强",
        "单位": "dB",
        "色标": {"最小值": db_min, "最大值": db_max},
        "samples": int(field_db.shape[0]),
        "x_lambda": [_num(value, 4) for value in result.x_lambda.tolist()],
        "y_lambda": [_num(value, 4) for value in result.y_lambda.tolist()],
        "z_lambda": _num(result.project.plane.z_lambda, 4),
        "bounds": {
            "x": _vec((float(result.x_lambda[0]), float(result.x_lambda[-1]))),
            "y": _vec((float(result.y_lambda[0]), float(result.y_lambda[-1]))),
        },
        "values_db": values,
        "统计": {
            "最小值": _num(float(np.min(field_db)), 3),
            "最大值": _num(float(np.max(field_db)), 3),
            "平均值": _num(float(np.mean(field_db)), 3),
            "峰值坐标": {
                "x_lambda": _num(float(result.x_lambda[peak_x_index]), 4),
                "y_lambda": _num(float(result.y_lambda[peak_y_index]), 4),
            },
        },
        "剖面": {
            "x_cut_y_lambda": _num(float(result.y_lambda[center_y_index]), 4),
            "y_cut_x_lambda": _num(float(result.x_lambda[center_x_index]), 4),
            "x_cut_db": values[center_y_index],
            "y_cut_db": [row[center_x_index] for row in values],
        },
        "安全边界": "归一化场强 dB 图层，仅用于算法与模型适用性分析，不代表绝对功率、器件阈值或现实作用距离。",
    }
    payload["field_hash"] = _scene_hash(
        {
            "类型": payload["类型"],
            "单位": payload["单位"],
            "色标": payload["色标"],
            "x_lambda": payload["x_lambda"],
            "y_lambda": payload["y_lambda"],
            "values_db": payload["values_db"],
        }
    )
    return payload


def _workbench_solve_payload(project: CAEProject, *, revision: int, history: Mapping[str, Any]) -> dict[str, Any]:
    scene = build_workbench3d_scene(project, revision, history)
    quick_project = _quick_solve_project(project)
    result = solve_project(quick_project)
    validity = assess_model_validity(project, project.propagation.backend)
    metrics = {str(key): _finite(value) for key, value in result.metrics.items()}
    object_rows = []
    for row in result.object_metrics_frame().to_dict(orient="records"):
        object_rows.append({str(key): _finite(value) for key, value in row.items()})
    summary_keys = (
        "target_rmse_percent",
        "minimum_target_coverage_percent",
        "peak_outside_db",
        "outside_peak_violation_db",
        "maximum_protected_violation_db",
        "constraint_success_rate_percent",
        "solver_runtime_ms",
        "control_success",
    )
    summary = {key: metrics.get(key) for key in summary_keys}
    checks = []
    if bool(metrics.get("control_success")):
        checks.append({"项目": "联合控场判据", "状态": "通过", "说明": "目标区、保护区和区外峰值满足当前归一化约束。"})
    else:
        checks.append({"项目": "联合控场判据", "状态": "关注", "说明": "至少一个目标区、保护区或区外峰值约束需要复核。"})
    checks.append(
        {
            "项目": "模型适用性",
            "状态": "通过" if validity.score >= 78 else "关注",
            "说明": f"{validity.level}；得分 {validity.score:.1f}",
        }
    )
    checks.append(
        {
            "项目": "安全边界",
            "状态": "提示",
            "说明": "结果为波长尺度归一化代理求解，不输出绝对功率、真实器件阈值、毁伤概率或作用距离。",
        }
    )
    return {
        "成功": True,
        "阶段": "V2.0B 三维工作台求解联动预览",
        "scene_hash": scene["scene_hash"],
        "修订": int(revision),
        "工程": scene["工程"],
        "求解器": {
            "方法": result.project.solver.method,
            "传播后端": metrics.get("propagation_backend_name"),
            "平面采样": int(result.project.plane.samples),
            "目标采样": int(result.project.solver.target_samples),
            "区外采样": int(result.project.solver.outside_samples),
            "不确定场景": int(result.project.solver.uncertainty_scenarios),
        },
        "摘要": summary,
        "指标": metrics,
        "对象指标": object_rows,
        "结果图层": _result_layer_payload(result),
        "适用性": validity.as_dict(),
        "验收清单": checks,
        "运行日志": list(result.log_lines[-12:]),
        "模型边界": project.model_scope,
    }


def _coerce_patch_value(current: Any, value: Any) -> Any:
    if isinstance(current, bool):
        return bool(value)
    if isinstance(current, int) and not isinstance(current, bool):
        return int(value)
    if isinstance(current, float):
        return float(value)
    return str(value)


def _clean_properties(item: Any, properties: Mapping[str, Any], allowed: set[str]) -> dict[str, Any]:
    unknown = set(properties) - allowed
    if unknown:
        item_id = getattr(item, "object_id", getattr(item, "material_id", item.__class__.__name__))
        raise ValueError(f"对象 {item_id} 不支持字段：{', '.join(sorted(unknown))}")
    cleaned: dict[str, Any] = {}
    for key, value in properties.items():
        cleaned[key] = _coerce_patch_value(getattr(item, key), value)
    return cleaned


def _replace_target(project: CAEProject, object_id: str, properties: Mapping[str, Any]) -> CAEProject | None:
    items = (project.target, *project.additional_targets)
    for index, item in enumerate(items):
        if item.object_id == object_id:
            updated = replace(item, **_clean_properties(item, properties, TARGET_FIELDS))
            if index == 0:
                return replace(project, target=updated)
            additional = list(project.additional_targets)
            additional[index - 1] = updated
            return replace(project, additional_targets=tuple(additional))
    return None


def _replace_protected(project: CAEProject, object_id: str, properties: Mapping[str, Any]) -> CAEProject | None:
    items = (project.protected_zone, *project.additional_protected_zones)
    for index, item in enumerate(items):
        if item.object_id == object_id:
            updated = replace(item, **_clean_properties(item, properties, PROTECTED_FIELDS))
            if index == 0:
                return replace(project, protected_zone=updated)
            additional = list(project.additional_protected_zones)
            additional[index - 1] = updated
            return replace(project, additional_protected_zones=tuple(additional))
    return None


def _replace_tuple_item(
    project: CAEProject,
    *,
    object_id: str,
    attribute: str,
    allowed: set[str],
    properties: Mapping[str, Any],
) -> CAEProject | None:
    items = list(getattr(project, attribute))
    for index, item in enumerate(items):
        if item.object_id == object_id:
            items[index] = replace(item, **_clean_properties(item, properties, allowed))
            return replace(project, **{attribute: tuple(items)})
    return None


def apply_workbench3d_material_update(project: CAEProject, material_id: str, properties: Mapping[str, Any]) -> CAEProject:
    """Apply a material-library patch and return a validated project."""
    if not properties:
        raise ValueError("材料更新属性不能为空")
    items = list(project.materials)
    for index, item in enumerate(items):
        if item.material_id == material_id:
            cleaned = _clean_properties(item, properties, MATERIAL_FIELDS)
            items[index] = replace(item, **cleaned)
            return replace(project, materials=tuple(items))
    raise ValueError(f"未找到材料：{material_id}")


def apply_workbench3d_update(project: CAEProject, object_id: str, properties: Mapping[str, Any]) -> CAEProject:
    """Apply an editable object patch and return a validated project."""
    if not properties:
        raise ValueError("更新属性不能为空")
    for handler in (
        _replace_target,
        _replace_protected,
    ):
        updated = handler(project, object_id, properties)
        if updated is not None:
            return updated
    for attribute, allowed in (
        ("reflecting_planes", REFLECTOR_FIELDS),
        ("cavities", CAVITY_FIELDS),
        ("apertures", APERTURE_FIELDS),
    ):
        updated = _replace_tuple_item(project, object_id=object_id, attribute=attribute, allowed=allowed, properties=properties)
        if updated is not None:
            return updated
    raise ValueError(f"未找到可编辑对象：{object_id}")


class Workbench3DService:
    """Thread-safe in-memory V2.0B scene service for the FastAPI UI."""

    def __init__(self, project_path: str | Path | None, output_dir: str | Path | None = None):
        self.project_path = Path(project_path) if project_path is not None else None
        self.output_dir = Path(output_dir) if output_dir is not None else None
        self._result_dir = self.output_dir / "workbench3d_results" if self.output_dir is not None else None
        self._snapshot_dir = self.output_dir / "workbench3d_snapshots" if self.output_dir is not None else None
        self._job_dir = self.output_dir / "workbench3d_solve_jobs" if self.output_dir is not None else None
        self._asset_dir = self.output_dir / "workbench3d_assets" if self.output_dir is not None else None
        self._asset_db_path = self._asset_dir / "assets.sqlite" if self._asset_dir is not None else None
        self._lock = threading.RLock()
        self._project = self._load_project()
        self._absolute_calibration = self._load_absolute_calibration_archive()
        self._revision = 1
        self._undo_stack: list[CAEProject] = []
        self._redo_stack: list[CAEProject] = []
        self._snapshots: list[dict[str, Any]] = []
        self._snapshot_projects: dict[str, CAEProject] = {}
        self._solve_results: list[dict[str, Any]] = []
        self._solve_result_payloads: dict[str, dict[str, Any]] = {}
        self._solve_jobs: list[dict[str, Any]] = []
        self._solve_job_payloads: dict[str, dict[str, Any]] = {}
        self._solve_job_workers: dict[str, threading.Thread] = {}
        self._snapshot_serial = 0
        self._solve_result_serial = 0
        self._solve_job_serial = 0
        self._max_history = 32
        self._max_snapshots = 24
        self._max_results = 24
        self._max_jobs = 32
        self._load_snapshot_archive()
        self._load_result_archive()
        self._load_solve_job_archive()
        self._write_asset_index()

    def _load_project(self) -> CAEProject:
        if self.project_path and self.project_path.exists():
            return CAEProject.load_yaml(self.project_path)
        return default_project()

    def _load_absolute_calibration_archive(self) -> dict[str, Any]:
        if self._asset_dir is None:
            return _default_absolute_calibration(self._project)
        path = self._asset_dir / "absolute_calibration.json"
        if path.exists():
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
                if isinstance(payload, Mapping):
                    source = {
                        "阵元功率": payload.get("阵元功率"),
                        "实测标定点": payload.get("实测标定点"),
                    }
                    return _normalize_absolute_calibration(self._project, source)
            except (OSError, json.JSONDecodeError, ValueError):
                pass
        return _default_absolute_calibration(self._project)

    def _absolute_calibration_payload(self) -> dict[str, Any]:
        return _absolute_calibration_analysis(
            self._project,
            self._absolute_calibration,
            revision=self._revision,
            paths=self._asset_index_paths(),
        )

    def _imported_calibration_bridge_payload(self) -> dict[str, Any]:
        return _imported_calibration_payload(
            self.output_dir,
            paths=self._asset_index_paths(),
        )

    def _write_absolute_calibration(self, payload: Mapping[str, Any] | None = None) -> None:
        if self._asset_dir is None:
            return
        self._asset_dir.mkdir(parents=True, exist_ok=True)
        calibration = dict(payload or self._absolute_calibration_payload())
        (self._asset_dir / "absolute_calibration.json").write_text(
            json.dumps(calibration, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        with (self._asset_dir / "absolute_calibration_points.csv").open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(
                handle,
                fieldnames=[
                    "point_id",
                    "label",
                    "distance_m",
                    "normalized_model_amplitude",
                    "measured_field_v_per_m",
                    "uncertainty_percent",
                    "calibrated_estimate_v_per_m",
                    "residual_v_per_m",
                    "relative_error_percent",
                    "uncertainty_v_per_m",
                    "within_2sigma",
                ],
                extrasaction="ignore",
            )
            writer.writeheader()
            writer.writerows(calibration.get("实测标定点", []))
        with (self._asset_dir / "absolute_element_powers.csv").open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(
                handle,
                fieldnames=["element_id", "row", "col", "power_w"],
                extrasaction="ignore",
            )
            writer.writeheader()
            writer.writerows(calibration.get("阵元功率", []))

    def _write_imported_calibration_bridge(self, payload: Mapping[str, Any] | None = None) -> None:
        if self._asset_dir is None:
            return
        self._asset_dir.mkdir(parents=True, exist_ok=True)
        bridge = dict(payload or self._imported_calibration_bridge_payload())
        (self._asset_dir / "imported_calibration_bridge.json").write_text(
            json.dumps(bridge, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        summary = bridge.get("摘要") if isinstance(bridge.get("摘要"), Mapping) else {}
        rows = [
            {
                "类别": "摘要",
                "项目": key,
                "通过": bridge.get("通过"),
                "数值": value,
                "说明": bridge.get("结论"),
            }
            for key, value in dict(summary).items()
        ]
        rows.extend(
            {
                "类别": "验收",
                "项目": item.get("项目"),
                "通过": item.get("通过"),
                "数值": "",
                "说明": item.get("说明"),
            }
            for item in bridge.get("验收清单", [])
            if isinstance(item, Mapping)
        )
        with (self._asset_dir / "imported_calibration_bridge.csv").open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=["类别", "项目", "通过", "数值", "说明"], extrasaction="ignore")
            writer.writeheader()
            writer.writerows(rows)

    def scene(self) -> dict[str, Any]:
        with self._lock:
            scene = build_workbench3d_scene(self._project, self._revision, self.history())
            scene["绝对量纲标定"] = self._absolute_calibration_payload()
            scene["导入数据标定桥接"] = self._imported_calibration_bridge_payload()
            return scene

    def history(self) -> dict[str, Any]:
        return {
            "可撤销": bool(self._undo_stack),
            "可重做": bool(self._redo_stack),
            "撤销步数": len(self._undo_stack),
            "重做步数": len(self._redo_stack),
            "快照数": len(self._snapshots),
            "快照": [dict(item) for item in self._snapshots],
            "结果数": len(self._solve_results),
            "结果": [dict(item) for item in self._solve_results],
            "求解任务数": len(self._solve_jobs),
            "求解任务": [dict(item) for item in self._solve_jobs],
        }

    def _push_undo(self) -> None:
        self._undo_stack.append(self._project)
        if len(self._undo_stack) > self._max_history:
            del self._undo_stack[0]
        self._redo_stack.clear()

    def update_object(self, object_id: str, properties: Mapping[str, Any], *, save: bool = False) -> dict[str, Any]:
        with self._lock:
            updated = apply_workbench3d_update(self._project, object_id, properties)
            self._push_undo()
            self._project = updated
            self._revision += 1
            if save:
                if self.project_path is None:
                    raise ValueError("未配置工程路径，无法保存场景")
                updated.save_yaml(self.project_path)
            return self.scene()

    def update_material(self, material_id: str, properties: Mapping[str, Any], *, save: bool = False) -> dict[str, Any]:
        with self._lock:
            updated = apply_workbench3d_material_update(self._project, material_id, properties)
            self._push_undo()
            self._project = updated
            self._revision += 1
            if save:
                if self.project_path is None:
                    raise ValueError("未配置工程路径，无法保存材料")
                updated.save_yaml(self.project_path)
            return self.scene()

    def solve_preview(self) -> dict[str, Any]:
        """Run the current 3D workbench project through the quick CAE solver."""
        with self._lock:
            payload = _workbench_solve_payload(self._project, revision=self._revision, history=self.history())
            return self._archive_solve_payload(payload)

    def submit_solve_job(self, label: str | None = None, *, retry_of: str | None = None) -> dict[str, Any]:
        """Submit a tracked V2.0B quick-solve job and return the finished result."""
        with self._lock:
            self._solve_job_serial += 1
            job_id = f"JOB-{self._solve_job_serial:04d}"
            submitted_at = time.strftime("%Y-%m-%d %H:%M:%S")
            record: dict[str, Any] = {
                "id": job_id,
                "标签": str(label).strip() if label and str(label).strip() else f"三维求解任务 {self._solve_job_serial:04d}",
                "状态": "运行中",
                "提交时间": submitted_at,
                "开始时间": submitted_at,
                "完成时间": None,
                "修订": self._revision,
                "scene_hash": None,
                "result_id": None,
                "field_hash": None,
                "传播后端": None,
                "方法": None,
                "目标RMSE": None,
                "最低覆盖率": None,
                "区外峰值": None,
                "保护区超限": None,
                "错误": None,
                "结果路径": None,
                "任务路径": None,
                "重试来源": retry_of,
                "取消时间": None,
                "操作日志": [
                    {
                        "动作": "提交",
                        "时间": submitted_at,
                        "通过": True,
                        "说明": "同步快速求解任务已进入本地任务台账。",
                    }
                ],
                "安全边界": "同步快速求解任务记录，仅用于归一化模型审计，不代表真实设备运行任务。",
            }
            try:
                payload = _workbench_solve_payload(self._project, revision=self._revision, history=self.history())
                payload["求解任务"] = dict(record)
                payload = self._archive_solve_payload(payload)
                result_layer = payload.get("结果图层", {})
                summary = payload.get("摘要", {})
                solver = payload.get("求解器", {})
                result_record = payload.get("结果档案", {})
                record.update(
                    {
                        "状态": "已完成",
                        "完成时间": time.strftime("%Y-%m-%d %H:%M:%S"),
                        "scene_hash": payload.get("scene_hash"),
                        "result_id": payload.get("result_id"),
                        "field_hash": result_layer.get("field_hash"),
                        "传播后端": solver.get("传播后端"),
                        "方法": solver.get("方法"),
                        "目标RMSE": summary.get("target_rmse_percent"),
                        "最低覆盖率": summary.get("minimum_target_coverage_percent"),
                        "区外峰值": summary.get("peak_outside_db"),
                        "保护区超限": summary.get("maximum_protected_violation_db"),
                        "结果路径": result_record.get("保存路径"),
                    }
                )
                payload["求解任务"] = dict(record)
                if isinstance(result_record, dict):
                    result_record["任务id"] = job_id
                    payload["结果档案"] = result_record
                self._solve_result_payloads[str(payload["result_id"])] = json.loads(json.dumps(payload, ensure_ascii=False))
                if result_record.get("保存路径"):
                    Path(str(result_record["保存路径"])).write_text(
                        json.dumps(payload, ensure_ascii=False, indent=2),
                        encoding="utf-8",
                    )
                self._store_solve_job(record, {"任务": record, "结果": payload})
                return {
                    "任务": dict(record),
                    "结果": json.loads(json.dumps(payload, ensure_ascii=False)),
                    "队列": [dict(item) for item in self._solve_jobs],
                    "审计": self._solve_job_audit_payload(),
                    "索引": self._solve_job_index_paths(),
                }
            except Exception as exc:
                record.update({"状态": "失败", "完成时间": time.strftime("%Y-%m-%d %H:%M:%S"), "错误": str(exc)})
                self._store_solve_job(record, {"任务": record, "结果": None})
                raise

    def submit_background_solve_job(
        self,
        label: str | None = None,
        *,
        retry_of: str | None = None,
        start_paused: bool = False,
    ) -> dict[str, Any]:
        """Submit a checkpointed local background quick-solve job."""
        should_start = not bool(start_paused)
        with self._lock:
            self._solve_job_serial += 1
            job_id = f"JOB-{self._solve_job_serial:04d}"
            submitted_at = time.strftime("%Y-%m-%d %H:%M:%S")
            record: dict[str, Any] = {
                "id": job_id,
                "标签": str(label).strip() if label and str(label).strip() else f"三维后台求解任务 {self._solve_job_serial:04d}",
                "状态": "已暂停" if start_paused else "排队中",
                "提交时间": submitted_at,
                "开始时间": None,
                "完成时间": None,
                "修订": self._revision,
                "scene_hash": build_workbench3d_scene(self._project, self._revision, self.history())["scene_hash"],
                "result_id": None,
                "field_hash": None,
                "传播后端": None,
                "方法": None,
                "目标RMSE": None,
                "最低覆盖率": None,
                "区外峰值": None,
                "保护区超限": None,
                "错误": None,
                "结果路径": None,
                "任务路径": None,
                "重试来源": retry_of,
                "取消时间": None,
                "暂停时间": submitted_at if start_paused else None,
                "恢复时间": None,
                "worker": "等待恢复" if start_paused else "本地后台worker",
                "操作日志": [
                    {
                        "动作": "提交",
                        "时间": submitted_at,
                        "通过": True,
                        "说明": "后台快速求解任务已写入本地可恢复任务台账。",
                    }
                ],
                "安全边界": "本地后台worker仅执行归一化快速求解检查点，不代表真实设备调度任务。",
            }
            if start_paused:
                record["操作日志"].append(
                    {
                        "动作": "暂停",
                        "时间": submitted_at,
                        "通过": True,
                        "说明": "任务以暂停检查点方式创建，恢复后从提交时工程快照继续。",
                    }
                )
            payload = {
                "任务": record,
                "结果": None,
                "工程快照": self._project.to_dict(),
                "历史快照": self.history(),
                "后台worker": {
                    "模式": "本地线程",
                    "start_paused": bool(start_paused),
                    "安全边界": "单机后台worker预览；不等价于多用户生产调度器。",
                },
            }
            self._store_solve_job(record, payload)
            response = {
                "任务": dict(record),
                "结果": None,
                "队列": [dict(item) for item in self._solve_jobs],
                "审计": self._solve_job_audit_payload(),
                "索引": self._solve_job_index_paths(),
                "后台worker": True,
            }
        if should_start:
            self._start_background_solve_worker(job_id)
        return response

    def _start_background_solve_worker(self, job_id: str) -> None:
        with self._lock:
            if job_id not in self._solve_job_payloads:
                return
            current = self._solve_job_payloads[job_id].get("任务", {})
            if not isinstance(current, Mapping) or current.get("状态") != "排队中":
                return
            old_thread = self._solve_job_workers.get(job_id)
            if old_thread is not None and old_thread.is_alive():
                return
            payload = json.loads(json.dumps(self._solve_job_payloads[job_id], ensure_ascii=False))
            project_payload = payload.get("工程快照")
            if not isinstance(project_payload, Mapping):
                return
            revision = int((payload.get("任务") or {}).get("修订") or self._revision)
            history_snapshot = payload.get("历史快照") if isinstance(payload.get("历史快照"), Mapping) else {}
        project = CAEProject.from_dict(project_payload)
        thread = threading.Thread(
            target=self._run_background_solve_job,
            args=(job_id, project, revision, dict(history_snapshot)),
            name=f"hpm-dt-worker-{job_id}",
            daemon=True,
        )
        with self._lock:
            self._solve_job_workers[job_id] = thread
        thread.start()

    def _run_background_solve_job(
        self,
        job_id: str,
        project: CAEProject,
        revision: int,
        history_snapshot: Mapping[str, Any],
    ) -> None:
        for _ in range(8):
            time.sleep(0.05)
            with self._lock:
                payload = self._solve_job_payloads.get(job_id)
                record = payload.get("任务") if isinstance(payload, Mapping) else None
                status = str(record.get("状态") or "") if isinstance(record, Mapping) else ""
                if status in {"已暂停", "已取消", "已完成", "失败"}:
                    return
        with self._lock:
            payload = self._solve_job_payloads.get(job_id)
            if not isinstance(payload, Mapping) or not isinstance(payload.get("任务"), Mapping):
                return
            record = dict(payload["任务"])
            if record.get("状态") != "排队中":
                return
            now = time.strftime("%Y-%m-%d %H:%M:%S")
            record["状态"] = "运行中"
            record["开始时间"] = record.get("开始时间") or now
            record["worker"] = threading.current_thread().name
            logs = record.get("操作日志") if isinstance(record.get("操作日志"), list) else []
            record["操作日志"] = [dict(item) for item in logs if isinstance(item, Mapping)] + [
                {"动作": "启动", "时间": now, "通过": True, "说明": f"后台worker {threading.current_thread().name} 开始执行。"}
            ]
            payload = dict(payload)
            payload["任务"] = dict(record)
            self._replace_solve_job_record(job_id, record, payload)
        try:
            solve_payload = _workbench_solve_payload(project, revision=revision, history=history_snapshot)
            with self._lock:
                current_payload = self._solve_job_payloads.get(job_id)
                if not isinstance(current_payload, Mapping) or not isinstance(current_payload.get("任务"), Mapping):
                    return
                record = dict(current_payload["任务"])
                if record.get("状态") in {"已暂停", "已取消"}:
                    return
                solve_payload["求解任务"] = dict(record)
                solve_payload = self._archive_solve_payload(solve_payload)
                result_layer = solve_payload.get("结果图层", {})
                summary = solve_payload.get("摘要", {})
                solver = solve_payload.get("求解器", {})
                result_record = solve_payload.get("结果档案", {})
                now = time.strftime("%Y-%m-%d %H:%M:%S")
                logs = record.get("操作日志") if isinstance(record.get("操作日志"), list) else []
                record.update(
                    {
                        "状态": "已完成",
                        "完成时间": now,
                        "scene_hash": solve_payload.get("scene_hash"),
                        "result_id": solve_payload.get("result_id"),
                        "field_hash": result_layer.get("field_hash"),
                        "传播后端": solver.get("传播后端"),
                        "方法": solver.get("方法"),
                        "目标RMSE": summary.get("target_rmse_percent"),
                        "最低覆盖率": summary.get("minimum_target_coverage_percent"),
                        "区外峰值": summary.get("peak_outside_db"),
                        "保护区超限": summary.get("maximum_protected_violation_db"),
                        "结果路径": result_record.get("保存路径") if isinstance(result_record, Mapping) else None,
                        "操作日志": [dict(item) for item in logs if isinstance(item, Mapping)]
                        + [{"动作": "完成", "时间": now, "通过": True, "说明": "后台快速求解已完成并归档结果。"}],
                    }
                )
                solve_payload["求解任务"] = dict(record)
                if isinstance(result_record, dict):
                    result_record["任务id"] = job_id
                    solve_payload["结果档案"] = result_record
                self._solve_result_payloads[str(solve_payload["result_id"])] = json.loads(json.dumps(solve_payload, ensure_ascii=False))
                if isinstance(result_record, Mapping) and result_record.get("保存路径"):
                    Path(str(result_record["保存路径"])).write_text(
                        json.dumps(solve_payload, ensure_ascii=False, indent=2),
                        encoding="utf-8",
                    )
                updated_payload = dict(current_payload)
                updated_payload["任务"] = dict(record)
                updated_payload["结果"] = solve_payload
                self._replace_solve_job_record(job_id, record, updated_payload)
        except Exception as exc:  # pragma: no cover - defensive worker boundary
            with self._lock:
                current_payload = self._solve_job_payloads.get(job_id, {})
                record = dict(current_payload.get("任务") or {"id": job_id})
                now = time.strftime("%Y-%m-%d %H:%M:%S")
                logs = record.get("操作日志") if isinstance(record.get("操作日志"), list) else []
                record.update(
                    {
                        "状态": "失败",
                        "完成时间": now,
                        "错误": str(exc),
                        "操作日志": [dict(item) for item in logs if isinstance(item, Mapping)]
                        + [{"动作": "失败", "时间": now, "通过": False, "说明": str(exc)}],
                    }
                )
                updated_payload = dict(current_payload) if isinstance(current_payload, Mapping) else {"结果": None}
                updated_payload["任务"] = dict(record)
                self._replace_solve_job_record(job_id, record, updated_payload)

    def _archive_solve_payload(self, payload: dict[str, Any]) -> dict[str, Any]:
        self._solve_result_serial += 1
        result_id = f"SOL-{self._solve_result_serial:04d}"
        result_layer = payload.get("结果图层", {})
        summary = payload.get("摘要", {})
        solver = payload.get("求解器", {})
        task = payload.get("求解任务", {})
        payload["result_id"] = result_id
        record = {
            "id": result_id,
            "任务id": task.get("id") if isinstance(task, Mapping) else None,
            "创建时间": time.strftime("%Y-%m-%d %H:%M:%S"),
            "修订": payload.get("修订"),
            "scene_hash": payload.get("scene_hash"),
            "field_hash": result_layer.get("field_hash"),
            "传播后端": solver.get("传播后端"),
            "方法": solver.get("方法"),
            "目标RMSE": summary.get("target_rmse_percent"),
            "最低覆盖率": summary.get("minimum_target_coverage_percent"),
            "区外峰值": summary.get("peak_outside_db"),
            "保护区超限": summary.get("maximum_protected_violation_db"),
            "结果统计": result_layer.get("统计", {}),
            "保存路径": None,
            "安全边界": payload.get("模型边界"),
        }
        payload["结果档案"] = record
        if self._result_dir is not None:
            self._result_dir.mkdir(parents=True, exist_ok=True)
            filename = f"{result_id}_{record['scene_hash']}_{record['field_hash']}.json"
            output_path = self._result_dir / filename
            record["保存路径"] = str(output_path)
            payload["结果档案"] = record
            output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        self._solve_results.append(dict(record))
        self._solve_result_payloads[result_id] = json.loads(json.dumps(payload, ensure_ascii=False))
        if len(self._solve_results) > self._max_results:
            removed = self._solve_results.pop(0)
            self._solve_result_payloads.pop(str(removed["id"]), None)
        self._write_result_index()
        return payload

    def _load_result_archive(self) -> None:
        if self._result_dir is None or not self._result_dir.exists():
            return
        records: list[dict[str, Any]] = []
        payloads: dict[str, dict[str, Any]] = {}
        max_serial = 0
        for path in sorted(self._result_dir.glob("SOL-*.json")):
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            result_id = str(payload.get("result_id") or "")
            record = payload.get("结果档案")
            if not result_id or not isinstance(record, dict):
                continue
            record = dict(record)
            record["id"] = result_id
            record["保存路径"] = str(path)
            payload["结果档案"] = record
            records.append(record)
            payloads[result_id] = payload
            try:
                max_serial = max(max_serial, int(result_id.split("-", 1)[1]))
            except (IndexError, ValueError):
                pass
        records = records[-self._max_results :]
        keep_ids = {str(item["id"]) for item in records}
        self._solve_results = [dict(item) for item in records]
        self._solve_result_payloads = {key: value for key, value in payloads.items() if key in keep_ids}
        self._solve_result_serial = max(self._solve_result_serial, max_serial)
        self._write_result_index()

    def _write_result_index(self) -> None:
        if self._result_dir is None:
            return
        self._result_dir.mkdir(parents=True, exist_ok=True)
        index_payload = {
            "版本": "V2.0B-result-index",
            "更新时间": time.strftime("%Y-%m-%d %H:%M:%S"),
            "数量": len(self._solve_results),
            "结果": [dict(item) for item in self._solve_results],
        }
        (self._result_dir / "index.json").write_text(
            json.dumps(index_payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        fieldnames = [
            "id",
            "任务id",
            "创建时间",
            "修订",
            "scene_hash",
            "field_hash",
            "传播后端",
            "方法",
            "目标RMSE",
            "最低覆盖率",
            "区外峰值",
            "保护区超限",
            "保存路径",
        ]
        with (self._result_dir / "index.csv").open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(self._solve_results)
        self._write_asset_index()

    def _solve_job_index_paths(self) -> dict[str, str | None]:
        index_path = str(self._job_dir / "index.json") if self._job_dir is not None else None
        csv_path = str(self._job_dir / "index.csv") if self._job_dir is not None else None
        audit_json = str(self._job_dir / "audit.json") if self._job_dir is not None else None
        audit_csv = str(self._job_dir / "audit.csv") if self._job_dir is not None else None
        return {"json": index_path, "csv": csv_path, "audit_json": audit_json, "audit_csv": audit_csv}

    def _normalize_solve_job_record(self, record: Mapping[str, Any]) -> dict[str, Any]:
        normalized = dict(record)
        normalized.setdefault("重试来源", None)
        normalized.setdefault("取消时间", None)
        logs = normalized.get("操作日志")
        if not isinstance(logs, list) or not logs:
            normalized["操作日志"] = [
                {
                    "动作": "导入",
                    "时间": normalized.get("提交时间") or normalized.get("完成时间") or time.strftime("%Y-%m-%d %H:%M:%S"),
                    "通过": True,
                    "说明": "从历史 JOB 档案恢复任务记录。",
                }
            ]
        else:
            normalized["操作日志"] = [dict(item) for item in logs if isinstance(item, Mapping)]
        return normalized

    def _store_solve_job(self, record: dict[str, Any], payload: dict[str, Any]) -> None:
        job_id = str(record["id"])
        normalized_record = self._normalize_solve_job_record(record)
        record.clear()
        record.update(normalized_record)
        self._write_solve_job_payload_file(record, payload)
        self._solve_jobs.append(dict(record))
        self._solve_job_payloads[job_id] = json.loads(json.dumps(payload, ensure_ascii=False))
        if len(self._solve_jobs) > self._max_jobs:
            removed = self._solve_jobs.pop(0)
            self._solve_job_payloads.pop(str(removed["id"]), None)
        self._write_solve_job_index()

    def _replace_solve_job_record(self, job_id: str, record: Mapping[str, Any], payload: Mapping[str, Any]) -> None:
        updated_record = dict(record)
        updated_payload = dict(payload)
        self._write_solve_job_payload_file(updated_record, updated_payload)
        self._solve_jobs = [dict(updated_record) if str(item.get("id")) == job_id else dict(item) for item in self._solve_jobs]
        self._solve_job_payloads[job_id] = json.loads(json.dumps(updated_payload, ensure_ascii=False))
        self._write_solve_job_index()

    def _solve_job_payload_path(self, record: Mapping[str, Any]) -> Path | None:
        if self._job_dir is None:
            return None
        job_id = str(record.get("id") or "")
        if not job_id:
            return None
        scene_hash = str(record.get("scene_hash") or "scene")
        result_id = str(record.get("result_id") or "no_result")
        return self._job_dir / f"{job_id}_{scene_hash}_{result_id}.json"

    def _write_solve_job_payload_file(self, record: dict[str, Any], payload: dict[str, Any]) -> None:
        output_path = self._solve_job_payload_path(record)
        if output_path is None:
            return
        output_path.parent.mkdir(parents=True, exist_ok=True)
        old_path_value = record.get("任务路径")
        old_path = Path(str(old_path_value)) if old_path_value else None
        record["任务路径"] = str(output_path)
        payload["任务"] = dict(record)
        output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        if old_path and old_path.exists() and old_path.resolve() != output_path.resolve():
            try:
                if old_path.parent.resolve() == output_path.parent.resolve():
                    old_path.unlink(missing_ok=True)
            except OSError:
                pass

    def _solve_job_audit_payload(self) -> dict[str, Any]:
        status_counts: dict[str, int] = {}
        job_ids: list[str] = []
        missing_paths: list[dict[str, Any]] = []
        retry_errors: list[dict[str, Any]] = []
        known_ids = {str(item.get("id")) for item in self._solve_jobs if item.get("id")}
        for item in self._solve_jobs:
            job_id = str(item.get("id") or "")
            if job_id:
                job_ids.append(job_id)
            status = str(item.get("状态") or "未知")
            status_counts[status] = status_counts.get(status, 0) + 1
            for key in ("任务路径", "结果路径"):
                path_value = item.get(key)
                if path_value and not Path(str(path_value)).exists():
                    missing_paths.append({"任务id": job_id, "字段": key, "路径": path_value})
            retry_source = item.get("重试来源")
            if retry_source and str(retry_source) not in known_ids:
                retry_errors.append({"任务id": job_id, "重试来源": retry_source, "说明": "重试来源任务不在当前任务台账。"})
        paths = self._solve_job_index_paths()
        index_checks = [
            bool(path_value) and Path(str(path_value)).exists()
            for key, path_value in paths.items()
            if key in {"json", "csv"} and path_value
        ]
        checks = [
            {
                "项目": "任务id唯一",
                "通过": len(job_ids) == len(set(job_ids)),
                "说明": f"{len(job_ids)} 个任务编号。",
            },
            {
                "项目": "索引文件可复查",
                "通过": all(index_checks) if index_checks else self._job_dir is None,
                "说明": "JSON 和 CSV 任务索引可由文件系统复查。",
            },
            {
                "项目": "任务路径可复查",
                "通过": not missing_paths,
                "说明": f"缺失路径 {len(missing_paths)} 条。",
            },
            {
                "项目": "重试链路可追溯",
                "通过": not retry_errors,
                "说明": f"异常重试来源 {len(retry_errors)} 条。",
            },
            {
                "项目": "任务操作有审计日志",
                "通过": all(isinstance(item.get("操作日志"), list) and item.get("操作日志") for item in self._solve_jobs),
                "说明": "每条任务记录至少保留提交、取消或重试操作日志。",
            },
        ]
        passed = all(bool(item["通过"]) for item in checks)
        return {
            "版本": "V2.0B-solve-job-audit",
            "更新时间": time.strftime("%Y-%m-%d %H:%M:%S"),
            "结论": "通过" if passed else "关注",
            "通过": passed,
            "任务总数": len(self._solve_jobs),
            "状态计数": status_counts,
            "最新任务": self._solve_jobs[-1]["id"] if self._solve_jobs else None,
            "缺失路径": missing_paths[:12],
            "重试异常": retry_errors[:12],
            "验收清单": checks,
            "索引": paths,
            "安全边界": "任务生命周期审计覆盖本地同步快速求解 JOB 记录，不代表真实设备调度队列。",
        }

    def _write_solve_job_audit(self) -> None:
        if self._job_dir is None:
            return
        self._job_dir.mkdir(parents=True, exist_ok=True)
        audit_payload = self._solve_job_audit_payload()
        (self._job_dir / "audit.json").write_text(
            json.dumps(audit_payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        with (self._job_dir / "audit.csv").open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=["项目", "通过", "说明"], extrasaction="ignore")
            writer.writeheader()
            writer.writerows(audit_payload["验收清单"])

    def _load_solve_job_archive(self) -> None:
        if self._job_dir is None or not self._job_dir.exists():
            return
        records: list[dict[str, Any]] = []
        payloads: dict[str, dict[str, Any]] = {}
        max_serial = 0
        for path in sorted(self._job_dir.glob("JOB-*.json")):
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            record = payload.get("任务")
            if not isinstance(record, dict):
                continue
            job_id = str(record.get("id") or "")
            if not job_id:
                continue
            record = dict(record)
            record["任务路径"] = str(path)
            record = self._normalize_solve_job_record(record)
            payload["任务"] = record
            result = payload.get("结果")
            if isinstance(result, dict):
                result["求解任务"] = dict(record)
                payload["结果"] = result
            expected_path = self._solve_job_payload_path(record)
            if expected_path is not None and expected_path.resolve() != path.resolve():
                if expected_path.exists():
                    try:
                        path.unlink(missing_ok=True)
                    except OSError:
                        pass
                    continue
                self._write_solve_job_payload_file(record, payload)
            records.append(record)
            payloads[job_id] = payload
            try:
                max_serial = max(max_serial, int(job_id.split("-", 1)[1]))
            except (IndexError, ValueError):
                pass
        records = records[-self._max_jobs :]
        keep_ids = {str(item["id"]) for item in records}
        self._solve_jobs = [dict(item) for item in records]
        self._solve_job_payloads = {key: value for key, value in payloads.items() if key in keep_ids}
        self._solve_job_serial = max(self._solve_job_serial, max_serial)
        self._write_solve_job_index()

    def _write_solve_job_index(self) -> None:
        if self._job_dir is None:
            return
        self._job_dir.mkdir(parents=True, exist_ok=True)
        index_payload = {
            "版本": "V2.0B-solve-job-index",
            "更新时间": time.strftime("%Y-%m-%d %H:%M:%S"),
            "数量": len(self._solve_jobs),
            "任务": [dict(item) for item in self._solve_jobs],
        }
        (self._job_dir / "index.json").write_text(
            json.dumps(index_payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        fieldnames = [
            "id",
            "标签",
            "状态",
            "提交时间",
            "开始时间",
            "完成时间",
            "修订",
            "scene_hash",
            "result_id",
            "field_hash",
            "传播后端",
            "方法",
            "目标RMSE",
            "最低覆盖率",
            "区外峰值",
            "保护区超限",
            "错误",
            "结果路径",
            "任务路径",
            "重试来源",
            "取消时间",
            "操作日志摘要",
        ]
        rows = []
        for item in self._solve_jobs:
            row = dict(item)
            logs = row.get("操作日志") if isinstance(row.get("操作日志"), list) else []
            row["操作日志摘要"] = "；".join(
                f"{entry.get('时间', '--')} {entry.get('动作', '--')} {'通过' if entry.get('通过') else '关注'}"
                for entry in logs[-6:]
                if isinstance(entry, Mapping)
            )
            rows.append(row)
        with (self._job_dir / "index.csv").open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(rows)
        self._write_solve_job_audit()
        self._write_asset_index()

    def _asset_index_paths(self) -> dict[str, str | None]:
        if self._asset_dir is None:
            return {
                "json": None,
                "csv": None,
                "sqlite": None,
                "audit_json": None,
                "audit_csv": None,
                "database_audit_json": None,
                "database_audit_csv": None,
                "naming_audit_json": None,
                "naming_audit_csv": None,
                "lineage_json": None,
                "lineage_csv": None,
                "reproducibility_audit_json": None,
                "reproducibility_audit_csv": None,
                "absolute_calibration_json": None,
                "absolute_calibration_points_csv": None,
                "absolute_element_powers_csv": None,
                "imported_calibration_bridge_json": None,
                "imported_calibration_bridge_csv": None,
            }
        return {
            "json": str(self._asset_dir / "index.json"),
            "csv": str(self._asset_dir / "index.csv"),
            "sqlite": str(self._asset_db_path) if self._asset_db_path is not None else None,
            "audit_json": str(self._asset_dir / "audit.json"),
            "audit_csv": str(self._asset_dir / "audit.csv"),
            "database_audit_json": str(self._asset_dir / "database_audit.json"),
            "database_audit_csv": str(self._asset_dir / "database_audit.csv"),
            "naming_audit_json": str(self._asset_dir / "naming_audit.json"),
            "naming_audit_csv": str(self._asset_dir / "naming_audit.csv"),
            "lineage_json": str(self._asset_dir / "lineage.json"),
            "lineage_csv": str(self._asset_dir / "lineage.csv"),
            "reproducibility_audit_json": str(self._asset_dir / "reproducibility_audit.json"),
            "reproducibility_audit_csv": str(self._asset_dir / "reproducibility_audit.csv"),
            "absolute_calibration_json": str(self._asset_dir / "absolute_calibration.json"),
            "absolute_calibration_points_csv": str(self._asset_dir / "absolute_calibration_points.csv"),
            "absolute_element_powers_csv": str(self._asset_dir / "absolute_element_powers.csv"),
            "imported_calibration_bridge_json": str(self._asset_dir / "imported_calibration_bridge.json"),
            "imported_calibration_bridge_csv": str(self._asset_dir / "imported_calibration_bridge.csv"),
        }

    @staticmethod
    def _asset_naming_rules() -> dict[str, Any]:
        return {
            "版本": "V2.0B-asset-naming-policy",
            "编号规则": {
                "求解任务": "JOB-0001 起的四位递增编号",
                "求解结果": "SOL-0001 起的四位递增编号",
                "工程快照": "SNP-0001 起的四位递增编号",
            },
            "文件名规则": {
                "求解任务": "JOB-xxxx_<scene_hash>_<result_id|no_result>.json",
                "求解结果": "SOL-xxxx_<scene_hash>_<field_hash>.json",
                "工程快照": "SNP-xxxx_<scene_hash>.yaml 与 SNP-xxxx_<scene_hash>_scene.json",
            },
            "哈希规则": "scene_hash 与 field_hash 使用 16 位小写十六进制摘要。",
            "标签规则": "标签必须非空，仅作为可读说明，不参与文件名。",
            "安全边界": "命名规范只治理归一化工程资产、任务和结果档案，不代表真实设备数据库编号体系。",
        }

    @staticmethod
    def _path_name(path_value: Any) -> str | None:
        if not path_value:
            return None
        return Path(str(path_value)).name

    @staticmethod
    def _naming_issue(asset_type: str, asset_id: str, field: str, actual: Any, expected: Any, note: str) -> dict[str, Any]:
        return {
            "类型": asset_type,
            "资产id": asset_id,
            "字段": field,
            "实际": actual,
            "期望": expected,
            "说明": note,
        }

    def _asset_naming_audit_payload(self) -> dict[str, Any]:
        rules = self._asset_naming_rules()
        issues: list[dict[str, Any]] = []
        labels_checked = 0
        labels_missing = 0
        path_checks = 0

        for item in self._solve_jobs:
            job_id = str(item.get("id") or "")
            labels_checked += 1
            if not _JOB_ID_RE.match(job_id):
                issues.append(self._naming_issue("求解任务", job_id, "id", job_id, "JOB-0000", "求解任务编号必须使用 JOB 四位数字前缀。"))
            if not str(item.get("标签") or "").strip():
                labels_missing += 1
                issues.append(self._naming_issue("求解任务", job_id, "标签", item.get("标签"), "非空", "任务标签用于人工检索和审计。"))
            scene_hash = str(item.get("scene_hash") or "")
            if scene_hash and not _HASH16_RE.match(scene_hash):
                issues.append(self._naming_issue("求解任务", job_id, "scene_hash", scene_hash, "16位小写十六进制", "任务必须绑定稳定场景摘要。"))
            result_id = str(item.get("result_id") or "")
            if result_id and not _SOL_ID_RE.match(result_id):
                issues.append(self._naming_issue("求解任务", job_id, "result_id", result_id, "SOL-0000", "任务结果编号必须指向 SOL 档案。"))
            task_path = item.get("任务路径")
            if task_path:
                path_checks += 1
                expected_name = f"{job_id}_{scene_hash or 'scene'}_{result_id or 'no_result'}.json"
                actual_name = self._path_name(task_path)
                if actual_name != expected_name:
                    issues.append(self._naming_issue("求解任务", job_id, "任务路径", actual_name, expected_name, "任务 JSON 文件名必须绑定 JOB、scene_hash 和 result_id/no_result。"))
            result_path = item.get("结果路径")
            field_hash = str(item.get("field_hash") or "")
            if result_id and result_path:
                path_checks += 1
                expected_name = f"{result_id}_{scene_hash}_{field_hash}.json"
                actual_name = self._path_name(result_path)
                if actual_name != expected_name:
                    issues.append(self._naming_issue("求解任务", job_id, "结果路径", actual_name, expected_name, "任务绑定的结果路径必须与 SOL 档案命名一致。"))

        for item in self._solve_results:
            result_id = str(item.get("id") or "")
            labels_checked += 1
            if not _SOL_ID_RE.match(result_id):
                issues.append(self._naming_issue("求解结果", result_id, "id", result_id, "SOL-0000", "结果档案编号必须使用 SOL 四位数字前缀。"))
            scene_hash = str(item.get("scene_hash") or "")
            field_hash = str(item.get("field_hash") or "")
            if not _HASH16_RE.match(scene_hash):
                issues.append(self._naming_issue("求解结果", result_id, "scene_hash", scene_hash, "16位小写十六进制", "结果档案必须绑定场景摘要。"))
            if not _HASH16_RE.match(field_hash):
                issues.append(self._naming_issue("求解结果", result_id, "field_hash", field_hash, "16位小写十六进制", "结果档案必须绑定场摘要。"))
            result_path = item.get("保存路径")
            if result_path:
                path_checks += 1
                expected_name = f"{result_id}_{scene_hash}_{field_hash}.json"
                actual_name = self._path_name(result_path)
                if actual_name != expected_name:
                    issues.append(self._naming_issue("求解结果", result_id, "保存路径", actual_name, expected_name, "结果 JSON 文件名必须绑定 SOL、scene_hash 和 field_hash。"))

        for item in self._snapshots:
            snapshot_id = str(item.get("id") or "")
            labels_checked += 1
            if not _SNP_ID_RE.match(snapshot_id):
                issues.append(self._naming_issue("工程快照", snapshot_id, "id", snapshot_id, "SNP-0000", "工程快照编号必须使用 SNP 四位数字前缀。"))
            if not str(item.get("标签") or "").strip():
                labels_missing += 1
                issues.append(self._naming_issue("工程快照", snapshot_id, "标签", item.get("标签"), "非空", "快照标签用于人工恢复和差异对比。"))
            scene_hash = str(item.get("scene_hash") or "")
            if not _HASH16_RE.match(scene_hash):
                issues.append(self._naming_issue("工程快照", snapshot_id, "scene_hash", scene_hash, "16位小写十六进制", "快照必须绑定场景摘要。"))
            project_path = item.get("工程路径")
            if project_path:
                path_checks += 1
                expected_name = f"{snapshot_id}_{scene_hash}.yaml"
                actual_name = self._path_name(project_path)
                if actual_name != expected_name:
                    issues.append(self._naming_issue("工程快照", snapshot_id, "工程路径", actual_name, expected_name, "快照工程 YAML 文件名必须绑定 SNP 和 scene_hash。"))
            scene_path = item.get("场景路径")
            if scene_path:
                path_checks += 1
                expected_name = f"{snapshot_id}_{scene_hash}_scene.json"
                actual_name = self._path_name(scene_path)
                if actual_name != expected_name:
                    issues.append(self._naming_issue("工程快照", snapshot_id, "场景路径", actual_name, expected_name, "快照场景 JSON 文件名必须绑定 SNP 和 scene_hash。"))

        assets = self._asset_records()
        asset_ids = [str(item.get("资产id") or "") for item in assets if item.get("资产id")]
        duplicate_asset_ids = sorted({asset_id for asset_id in asset_ids if asset_ids.count(asset_id) > 1})
        for asset_id in duplicate_asset_ids:
            issues.append(self._naming_issue("资产台账", asset_id, "资产id", asset_id, "全局唯一", "资产台账中的 JOB/SOL/SNP 编号不能重复。"))
        checks = [
            {
                "项目": "JOB/SOL/SNP编号规范",
                "通过": not any(item["字段"] in {"id", "result_id"} for item in issues),
                "说明": "任务、结果和快照编号使用固定前缀与四位数字。",
            },
            {
                "项目": "文件名绑定哈希",
                "通过": not any(item["字段"] in {"任务路径", "结果路径", "保存路径", "工程路径", "场景路径"} for item in issues),
                "说明": f"已检查 {path_checks} 条派生文件名。",
            },
            {
                "项目": "标签可读",
                "通过": labels_missing == 0,
                "说明": f"已检查 {labels_checked} 条记录，空标签 {labels_missing} 条。",
            },
            {
                "项目": "资产id全局唯一",
                "通过": not duplicate_asset_ids,
                "说明": f"重复资产编号 {len(duplicate_asset_ids)} 个。",
            },
        ]
        passed = all(bool(item["通过"]) for item in checks)
        return {
            "版本": "V2.0B-asset-naming-audit",
            "更新时间": time.strftime("%Y-%m-%d %H:%M:%S"),
            "结论": "通过" if passed else "关注",
            "通过": passed,
            "命名规则": rules,
            "统计": {
                "任务数": len(self._solve_jobs),
                "结果数": len(self._solve_results),
                "快照数": len(self._snapshots),
                "资产数": len(assets),
                "路径检查数": path_checks,
                "问题数": len(issues),
            },
            "命名问题": issues[:24],
            "验收清单": checks,
            "索引": self._asset_index_paths(),
            "安全边界": rules["安全边界"],
        }

    def _metric_summary(self, record: Mapping[str, Any]) -> str:
        return (
            f"RMSE {record.get('目标RMSE', '--')} · "
            f"覆盖 {record.get('最低覆盖率', '--')} · "
            f"区外 {record.get('区外峰值', '--')}"
        )

    def _asset_records(self) -> list[dict[str, Any]]:
        assets: list[dict[str, Any]] = []
        for item in self._snapshots:
            assets.append(
                {
                    "资产id": item.get("id"),
                    "类型": "工程快照",
                    "标签": item.get("标签"),
                    "状态": "已保存",
                    "创建时间": item.get("创建时间"),
                    "修订": item.get("修订"),
                    "scene_hash": item.get("scene_hash"),
                    "field_hash": None,
                    "job_id": None,
                    "result_id": None,
                    "路径": item.get("工程路径"),
                    "辅助路径": item.get("场景路径"),
                    "摘要": f"对象 {item.get('对象总数', '--')} · 启用 {item.get('启用对象数', '--')}",
                    "安全边界": "工程快照只保存归一化 CAEProject 和三维场景 JSON，不代表实物状态。",
                }
            )
        for item in self._solve_jobs:
            assets.append(
                {
                    "资产id": item.get("id"),
                    "类型": "求解任务",
                    "标签": item.get("标签"),
                    "状态": item.get("状态"),
                    "创建时间": item.get("完成时间") or item.get("提交时间"),
                    "修订": item.get("修订"),
                    "scene_hash": item.get("scene_hash"),
                    "field_hash": item.get("field_hash"),
                    "job_id": item.get("id"),
                    "result_id": item.get("result_id"),
                    "路径": item.get("任务路径"),
                    "辅助路径": item.get("结果路径"),
                    "摘要": self._metric_summary(item),
                    "安全边界": item.get("安全边界"),
                }
            )
        for item in self._solve_results:
            assets.append(
                {
                    "资产id": item.get("id"),
                    "类型": "求解结果",
                    "标签": item.get("id"),
                    "状态": "已归档",
                    "创建时间": item.get("创建时间"),
                    "修订": item.get("修订"),
                    "scene_hash": item.get("scene_hash"),
                    "field_hash": item.get("field_hash"),
                    "job_id": item.get("任务id"),
                    "result_id": item.get("id"),
                    "路径": item.get("保存路径"),
                    "辅助路径": None,
                    "摘要": self._metric_summary(item),
                    "安全边界": item.get("安全边界"),
                }
            )
        imported = self._imported_calibration_bridge_payload()
        imported_summary = imported.get("摘要") if isinstance(imported.get("摘要"), Mapping) else {}
        imported_paths = imported.get("索引") if isinstance(imported.get("索引"), Mapping) else {}
        if imported_summary or imported.get("样例ID"):
            assets.append(
                {
                    "资产id": "IMP-CAL-001",
                    "类型": "导入标定桥接",
                    "标签": imported.get("样例ID") or "外部数据标定桥接",
                    "状态": imported.get("结论") or ("通过" if imported.get("通过") else "关注"),
                    "创建时间": imported.get("更新时间"),
                    "修订": self._revision,
                    "scene_hash": None,
                    "field_hash": None,
                    "job_id": None,
                    "result_id": None,
                    "路径": imported_paths.get("imported_calibration_bridge_json"),
                    "辅助路径": imported_summary.get("导入源文件"),
                    "摘要": (
                        f"样本 {imported_summary.get('样本数', '--')} · "
                        f"相对RMSE {imported_summary.get('标定后相对RMSE/%', '--')}% · "
                        f"2σ覆盖 {imported_summary.get('2sigma覆盖率/%', '--')}% · "
                        f"正式评分 {'可纳入' if imported_summary.get('可纳入正式可信度评分') else '未纳入'}"
                    ),
                    "安全边界": imported.get("安全边界"),
                }
            )
        assets = [item for item in assets if item.get("资产id")]
        assets.sort(key=lambda item: str(item.get("创建时间") or ""), reverse=True)
        return assets

    def _asset_summary(self, assets: list[dict[str, Any]]) -> dict[str, Any]:
        type_counts: dict[str, int] = {}
        status_counts: dict[str, int] = {}
        missing_paths: list[dict[str, Any]] = []
        for item in assets:
            asset_type = str(item.get("类型") or "未分类")
            status = str(item.get("状态") or "未知")
            type_counts[asset_type] = type_counts.get(asset_type, 0) + 1
            status_counts[status] = status_counts.get(status, 0) + 1
            for key in ("路径", "辅助路径"):
                path_value = item.get(key)
                if path_value and not Path(str(path_value)).exists():
                    missing_paths.append({"资产id": item.get("资产id"), "字段": key, "路径": path_value})
        return {
            "总数": len(assets),
            "类型计数": type_counts,
            "状态计数": status_counts,
            "最新资产": assets[0]["资产id"] if assets else None,
            "缺失路径数": len(missing_paths),
            "缺失路径": missing_paths[:12],
            "安全边界": "资产台账仅审计归一化工程快照、快速求解任务和结果档案，不代表真实设备任务或全波仿真数据库。",
        }

    def _asset_audit_payload(
        self,
        assets: list[dict[str, Any]],
        *,
        filtered_assets: list[dict[str, Any]] | None = None,
        filter_meta: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        summary = self._asset_summary(assets)
        filtered = filtered_assets if filtered_assets is not None else assets
        asset_ids = [str(item.get("资产id")) for item in assets if item.get("资产id")]
        type_counts = summary["类型计数"]
        paths = self._asset_index_paths()
        index_checks = [
            bool(path_value) and Path(str(path_value)).exists()
            for key, path_value in paths.items()
            if key in {"json", "csv", "sqlite"} and path_value
        ]
        checks = [
            {
                "项目": "资产id唯一",
                "通过": len(asset_ids) == len(set(asset_ids)),
                "说明": f"{len(asset_ids)} 个资产编号。",
            },
            {
                "项目": "三类资产覆盖",
                "通过": not assets or {"工程快照", "求解任务", "求解结果"} <= set(type_counts),
                "说明": "覆盖工程快照、求解任务和求解结果时，台账可支撑项目-求解-结果闭环。",
            },
            {
                "项目": "索引文件可复查",
                "通过": all(index_checks) if index_checks else self._asset_dir is None,
                "说明": "JSON、CSV 和 SQLite 台账索引均可由文件系统复查。",
            },
            {
                "项目": "资产路径可复查",
                "通过": summary["缺失路径数"] == 0,
                "说明": f"缺失路径 {summary['缺失路径数']} 条。",
            },
        ]
        passed = all(bool(item["通过"]) for item in checks)
        return {
            "版本": "V2.0B-asset-audit",
            "更新时间": time.strftime("%Y-%m-%d %H:%M:%S"),
            "结论": "通过" if passed else "关注",
            "通过": passed,
            "筛选": dict(filter_meta or {}),
            "总资产": len(assets),
            "匹配资产": len(filtered),
            "摘要": summary,
            "验收清单": checks,
            "索引": paths,
            "安全边界": summary["安全边界"],
        }

    def _filter_asset_records(
        self,
        assets: list[dict[str, Any]],
        *,
        asset_type: str | None = None,
        query: str | None = None,
    ) -> list[dict[str, Any]]:
        normalized_type = str(asset_type or "").strip()
        normalized_query = str(query or "").strip().lower()
        rows = [dict(item) for item in assets]
        if normalized_type and normalized_type not in {"全部", "all", "*"}:
            rows = [item for item in rows if str(item.get("类型") or "") == normalized_type]
        if normalized_query:
            search_fields = ("资产id", "类型", "标签", "状态", "创建时间", "scene_hash", "field_hash", "job_id", "result_id", "路径", "辅助路径", "摘要")
            rows = [
                item
                for item in rows
                if any(normalized_query in str(item.get(field) or "").lower() for field in search_fields)
            ]
        return rows

    def _coerce_asset_limit(self, limit: int | None) -> int | None:
        if limit is None:
            return None
        try:
            value = int(limit)
        except (TypeError, ValueError):
            return None
        if value <= 0:
            return None
        return min(value, 200)

    def _solve_job_event_records(self) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for job in self._solve_jobs:
            normalized = self._normalize_solve_job_record(job)
            job_id = str(normalized.get("id") or "")
            logs = normalized.get("操作日志") if isinstance(normalized.get("操作日志"), list) else []
            for index, entry in enumerate(logs):
                if not isinstance(entry, Mapping):
                    continue
                action = str(entry.get("动作") or "未命名操作")
                event_time = str(entry.get("时间") or normalized.get("提交时间") or normalized.get("完成时间") or "")
                rows.append(
                    {
                        "event_id": f"{job_id}:{index:03d}:{action}",
                        "job_id": job_id,
                        "event_index": index,
                        "action": action,
                        "event_time": event_time,
                        "passed": 1 if bool(entry.get("通过")) else 0,
                        "source_job": entry.get("来源任务") or normalized.get("重试来源"),
                        "new_job": entry.get("新任务"),
                        "job_status": normalized.get("状态"),
                        "result_id": normalized.get("result_id"),
                        "scene_hash": normalized.get("scene_hash"),
                        "field_hash": normalized.get("field_hash"),
                        "task_path": normalized.get("任务路径"),
                        "note": entry.get("说明"),
                        "raw_json": json.dumps(entry, ensure_ascii=False, sort_keys=True),
                    }
                )
        return rows

    def _sqlite_table_names(self) -> tuple[str, ...]:
        return (
            "workbench3d_assets",
            "workbench3d_solve_jobs",
            "workbench3d_solve_job_events",
            "workbench3d_results",
            "workbench3d_snapshots",
            "workbench3d_database_manifest",
        )

    def _asset_database_audit_payload(self) -> dict[str, Any]:
        paths = self._asset_index_paths()
        db_path = paths.get("sqlite")
        expected_assets = len(self._asset_records())
        expected_jobs = len(self._solve_jobs)
        expected_events = len(self._solve_job_event_records())
        expected_results = len(self._solve_results)
        expected_snapshots = len(self._snapshots)
        if not db_path:
            return {
                "版本": "V2.0B-asset-database-audit",
                "更新时间": time.strftime("%Y-%m-%d %H:%M:%S"),
                "结论": "关注",
                "通过": False,
                "数据库路径": None,
                "表": [],
                "行数": {},
                "任务数": 0,
                "任务事件数": 0,
                "结果数": 0,
                "快照数": 0,
                "预期任务数": expected_jobs,
                "预期任务事件数": expected_events,
                "预期结果数": expected_results,
                "预期快照数": expected_snapshots,
                "最新任务事件": None,
                "验收清单": [{"项目": "SQLite路径已配置", "通过": False, "说明": "当前服务未配置输出目录。"}],
                "索引": paths,
                "安全边界": "SQLite 数据库仅保存归一化工程资产和本地任务事件，不代表真实设备任务数据库。",
            }
        table_names: list[str] = []
        row_counts: dict[str, int] = {}
        latest_event: dict[str, Any] | None = None
        known_jobs = {str(item.get("id")) for item in self._solve_jobs if item.get("id")}
        unknown_event_jobs = 0
        orphan_result_rows = 0
        db_exists = Path(str(db_path)).exists()
        if db_exists:
            with sqlite3.connect(str(db_path)) as connection:
                connection.row_factory = sqlite3.Row
                table_names = [
                    str(row["name"])
                    for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name").fetchall()
                ]
                for table in self._sqlite_table_names():
                    if table in table_names:
                        row_counts[table] = int(connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
                if "workbench3d_solve_job_events" in table_names:
                    unknown_event_jobs = int(
                        connection.execute(
                            "SELECT COUNT(*) FROM workbench3d_solve_job_events WHERE job_id NOT IN (%s)"
                            % ",".join("?" for _ in known_jobs),
                            tuple(known_jobs),
                        ).fetchone()[0]
                    ) if known_jobs else row_counts.get("workbench3d_solve_job_events", 0)
                    row = connection.execute(
                        """
                        SELECT event_id, job_id, action, event_time, passed, source_job, new_job, job_status, result_id
                        FROM workbench3d_solve_job_events
                        ORDER BY event_time DESC, event_index DESC
                        LIMIT 1
                        """
                    ).fetchone()
                    latest_event = dict(row) if row is not None else None
                if "workbench3d_results" in table_names and known_jobs:
                    orphan_result_rows = int(
                        connection.execute(
                            "SELECT COUNT(*) FROM workbench3d_results WHERE job_id IS NOT NULL AND job_id NOT IN (%s)"
                            % ",".join("?" for _ in known_jobs),
                            tuple(known_jobs),
                        ).fetchone()[0]
                    )
        required_tables = set(self._sqlite_table_names())
        checks = [
            {
                "项目": "SQLite数据库可复查",
                "通过": db_exists,
                "说明": f"数据库路径：{db_path}",
            },
            {
                "项目": "核心表存在",
                "通过": required_tables <= set(table_names),
                "说明": "需要资产、任务、任务事件、结果、快照和数据库 manifest 表。",
            },
            {
                "项目": "资产行数一致",
                "通过": row_counts.get("workbench3d_assets", 0) == expected_assets,
                "说明": f"SQLite {row_counts.get('workbench3d_assets', 0)} 行，当前资产 {expected_assets} 行。",
            },
            {
                "项目": "任务行数一致",
                "通过": row_counts.get("workbench3d_solve_jobs", 0) == expected_jobs,
                "说明": f"SQLite {row_counts.get('workbench3d_solve_jobs', 0)} 行，当前任务 {expected_jobs} 条。",
            },
            {
                "项目": "任务事件行数一致",
                "通过": row_counts.get("workbench3d_solve_job_events", 0) == expected_events,
                "说明": f"SQLite {row_counts.get('workbench3d_solve_job_events', 0)} 行，任务操作日志 {expected_events} 条。",
            },
            {
                "项目": "结果行数一致",
                "通过": row_counts.get("workbench3d_results", 0) == expected_results,
                "说明": f"SQLite {row_counts.get('workbench3d_results', 0)} 行，当前结果 {expected_results} 条。",
            },
            {
                "项目": "快照行数一致",
                "通过": row_counts.get("workbench3d_snapshots", 0) == expected_snapshots,
                "说明": f"SQLite {row_counts.get('workbench3d_snapshots', 0)} 行，当前快照 {expected_snapshots} 条。",
            },
            {
                "项目": "任务事件可关联",
                "通过": unknown_event_jobs == 0,
                "说明": f"无法关联到当前 JOB 台账的事件 {unknown_event_jobs} 条。",
            },
            {
                "项目": "结果任务可关联",
                "通过": orphan_result_rows == 0,
                "说明": f"无法关联到当前 JOB 台账的结果 {orphan_result_rows} 条。",
            },
        ]
        passed = all(bool(item["通过"]) for item in checks)
        return {
            "版本": "V2.0B-asset-database-audit",
            "更新时间": time.strftime("%Y-%m-%d %H:%M:%S"),
            "结论": "通过" if passed else "关注",
            "通过": passed,
            "数据库路径": db_path,
            "表": table_names,
            "行数": row_counts,
            "任务数": row_counts.get("workbench3d_solve_jobs", 0),
            "任务事件数": row_counts.get("workbench3d_solve_job_events", 0),
            "结果数": row_counts.get("workbench3d_results", 0),
            "快照数": row_counts.get("workbench3d_snapshots", 0),
            "预期任务数": expected_jobs,
            "预期任务事件数": expected_events,
            "预期结果数": expected_results,
            "预期快照数": expected_snapshots,
            "最新任务事件": latest_event,
            "验收清单": checks,
            "索引": paths,
            "安全边界": "SQLite 数据库仅保存归一化工程资产和本地任务事件，不代表真实设备任务数据库。",
        }

    def _asset_lineage_payload(self) -> dict[str, Any]:
        updated_at = time.strftime("%Y-%m-%d %H:%M:%S")
        nodes: list[dict[str, Any]] = []
        edges: list[dict[str, Any]] = []
        node_ids: set[str] = set()
        edge_ids: set[str] = set()
        node_types: dict[str, str] = {}

        def add_node(node: Mapping[str, Any]) -> None:
            node_id = str(node.get("id") or "")
            if not node_id:
                return
            node_ids.add(node_id)
            node_types[node_id] = str(node.get("类型") or "")
            nodes.append(dict(node))

        def add_edge(
            source: Any,
            target: Any,
            relation: str,
            *,
            scene_hash: Any = None,
            field_hash: Any = None,
            evidence: Any = None,
        ) -> None:
            source_id = str(source or "")
            target_id = str(target or "")
            if not source_id or not target_id:
                return
            edge_id = f"{source_id}->{target_id}:{relation}"
            if edge_id in edge_ids:
                return
            edge_ids.add(edge_id)
            edges.append(
                {
                    "edge_id": edge_id,
                    "source": source_id,
                    "target": target_id,
                    "关系": relation,
                    "source_type": node_types.get(source_id),
                    "target_type": node_types.get(target_id),
                    "scene_hash": scene_hash,
                    "field_hash": field_hash,
                    "证据": evidence,
                }
            )

        for item in self._snapshots:
            add_node(
                {
                    "id": item.get("id"),
                    "类型": "工程快照",
                    "标签": item.get("标签"),
                    "状态": "已保存",
                    "时间": item.get("创建时间"),
                    "revision": item.get("修订"),
                    "scene_hash": item.get("scene_hash"),
                    "field_hash": None,
                    "路径": item.get("工程路径"),
                    "摘要": f"对象 {item.get('对象总数', '--')} · 启用 {item.get('启用对象数', '--')}",
                }
            )
        for item in self._solve_jobs:
            add_node(
                {
                    "id": item.get("id"),
                    "类型": "求解任务",
                    "标签": item.get("标签"),
                    "状态": item.get("状态"),
                    "时间": item.get("完成时间") or item.get("提交时间"),
                    "revision": item.get("修订"),
                    "scene_hash": item.get("scene_hash"),
                    "field_hash": item.get("field_hash"),
                    "路径": item.get("任务路径"),
                    "摘要": self._metric_summary(item),
                }
            )
        for item in self._solve_results:
            add_node(
                {
                    "id": item.get("id"),
                    "类型": "求解结果",
                    "标签": item.get("id"),
                    "状态": "已归档",
                    "时间": item.get("创建时间"),
                    "revision": item.get("修订"),
                    "scene_hash": item.get("scene_hash"),
                    "field_hash": item.get("field_hash"),
                    "路径": item.get("保存路径"),
                    "摘要": self._metric_summary(item),
                }
            )

        job_ids = {str(item.get("id")) for item in self._solve_jobs if item.get("id")}
        result_ids = {str(item.get("id")) for item in self._solve_results if item.get("id")}
        snapshot_ids = {str(item.get("id")) for item in self._snapshots if item.get("id")}
        latest_snapshot_by_scene: dict[str, dict[str, Any]] = {}
        for snapshot in sorted(self._snapshots, key=lambda item: str(item.get("创建时间") or "")):
            scene_hash = str(snapshot.get("scene_hash") or "")
            if scene_hash:
                latest_snapshot_by_scene[scene_hash] = dict(snapshot)

        for job in self._solve_jobs:
            job_id = str(job.get("id") or "")
            scene_hash = job.get("scene_hash")
            field_hash = job.get("field_hash")
            result_id = str(job.get("result_id") or "")
            retry_source = str(job.get("重试来源") or "")
            snapshot = latest_snapshot_by_scene.get(str(scene_hash or ""))
            if snapshot and snapshot.get("id") in snapshot_ids:
                add_edge(
                    snapshot.get("id"),
                    job_id,
                    "同scene_hash基线",
                    scene_hash=scene_hash,
                    evidence="快照与任务共享归一化三维场景哈希；不声明真实设备状态继承。",
                )
            if retry_source:
                add_edge(
                    retry_source,
                    job_id,
                    "重试派生",
                    scene_hash=scene_hash,
                    field_hash=field_hash,
                    evidence=f"{job_id} 记录了重试来源 {retry_source}",
                )
            if result_id:
                add_edge(
                    job_id,
                    result_id,
                    "生成结果",
                    scene_hash=scene_hash,
                    field_hash=field_hash,
                    evidence=f"{job_id} 绑定 result_id={result_id}",
                )

        for event in self._solve_job_event_records():
            source_job = event.get("source_job")
            new_job = event.get("new_job")
            action = str(event.get("action") or "")
            if source_job and new_job:
                add_edge(
                    source_job,
                    new_job,
                    f"事件派生:{action}",
                    scene_hash=event.get("scene_hash"),
                    field_hash=event.get("field_hash"),
                    evidence=event.get("event_id"),
                )

        missing_job_results = [
            {"任务id": item.get("id"), "result_id": item.get("result_id")}
            for item in self._solve_jobs
            if item.get("result_id") and str(item.get("result_id")) not in result_ids
        ]
        orphan_results = [
            {"结果id": item.get("id"), "任务id": item.get("任务id")}
            for item in self._solve_results
            if item.get("任务id") and str(item.get("任务id")) not in job_ids
        ]
        retry_errors = [
            {"任务id": item.get("id"), "重试来源": item.get("重试来源")}
            for item in self._solve_jobs
            if item.get("重试来源") and str(item.get("重试来源")) not in job_ids
        ]
        missing_scene_hash = [
            str(item.get("id") or item.get("资产id") or "")
            for item in [*self._snapshots, *self._solve_jobs, *self._solve_results]
            if not item.get("scene_hash")
        ]
        checks = [
            {
                "项目": "谱系节点id唯一",
                "通过": len(nodes) == len(node_ids),
                "说明": f"{len(nodes)} 个节点，唯一 ID {len(node_ids)} 个。",
            },
            {
                "项目": "任务结果边可关联",
                "通过": not missing_job_results,
                "说明": f"无法关联到 SOL 节点的任务结果 {len(missing_job_results)} 条。",
            },
            {
                "项目": "结果任务边可关联",
                "通过": not orphan_results,
                "说明": f"无法回到 JOB 节点的结果 {len(orphan_results)} 条。",
            },
            {
                "项目": "重试来源可追溯",
                "通过": not retry_errors,
                "说明": f"无法关联来源 JOB 的重试任务 {len(retry_errors)} 条。",
            },
            {
                "项目": "scene_hash覆盖",
                "通过": not missing_scene_hash,
                "说明": f"缺少 scene_hash 的节点 {len(missing_scene_hash)} 个。",
            },
        ]
        passed = all(bool(item["通过"]) for item in checks)
        return {
            "版本": "V2.0B-asset-lineage",
            "更新时间": updated_at,
            "结论": "通过" if passed else "关注",
            "通过": passed,
            "节点": nodes,
            "边": edges,
            "摘要": {
                "节点数": len(nodes),
                "边数": len(edges),
                "快照数": len(snapshot_ids),
                "任务数": len(job_ids),
                "结果数": len(result_ids),
                "任务结果边": sum(1 for item in edges if item.get("关系") == "生成结果"),
                "重试派生边": sum(1 for item in edges if str(item.get("关系") or "").startswith("重试")),
                "同场景基线边": sum(1 for item in edges if item.get("关系") == "同scene_hash基线"),
            },
            "异常": {
                "任务缺失结果": missing_job_results[:12],
                "结果缺失任务": orphan_results[:12],
                "重试来源异常": retry_errors[:12],
                "缺少scene_hash": missing_scene_hash[:12],
            },
            "验收清单": checks,
            "索引": self._asset_index_paths(),
            "安全边界": "资产谱系仅表达归一化工程快照、JOB 任务、SOL 结果与本地事件日志之间的可审计关系；同 scene_hash 基线不代表真实设备状态或外部全波求解器血缘。",
        }

    def _write_asset_lineage(self, payload: Mapping[str, Any] | None = None) -> None:
        if self._asset_dir is None:
            return
        lineage = dict(payload or self._asset_lineage_payload())
        (self._asset_dir / "lineage.json").write_text(
            json.dumps(lineage, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        with (self._asset_dir / "lineage.csv").open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(
                handle,
                fieldnames=["edge_id", "source", "target", "关系", "source_type", "target_type", "scene_hash", "field_hash", "证据"],
                extrasaction="ignore",
            )
            writer.writeheader()
            writer.writerows(lineage.get("边", []))

    def _asset_reproducibility_payload(self, lineage: Mapping[str, Any] | None = None) -> dict[str, Any]:
        lineage_payload = dict(lineage or self._asset_lineage_payload())
        lineage_edges = {
            (str(edge.get("source") or ""), str(edge.get("target") or ""), str(edge.get("关系") or ""))
            for edge in lineage_payload.get("边", [])
            if isinstance(edge, Mapping)
        }
        jobs_by_id = {str(item.get("id")): dict(item) for item in self._solve_jobs if item.get("id")}
        records: list[dict[str, Any]] = []
        missing_result_paths: list[dict[str, Any]] = []
        missing_hashes: list[dict[str, Any]] = []
        missing_job_links: list[dict[str, Any]] = []
        missing_lineage_edges: list[dict[str, Any]] = []
        missing_vv_records: list[dict[str, Any]] = []

        for result in self._solve_results:
            result_id = str(result.get("id") or "")
            job_id = str(result.get("任务id") or "")
            scene_hash = str(result.get("scene_hash") or "")
            field_hash = str(result.get("field_hash") or "")
            result_path = result.get("保存路径")
            payload = self._solve_result_payloads.get(result_id, {})
            job = jobs_by_id.get(job_id) if job_id else None
            checks: list[dict[str, Any]] = []

            result_path_exists = bool(result_path) and Path(str(result_path)).exists()
            checks.append({"项目": "结果JSON可复查", "通过": result_path_exists, "说明": str(result_path or "--")})
            if not result_path_exists:
                missing_result_paths.append({"结果id": result_id, "结果路径": result_path})

            hashes_ok = bool(scene_hash) and bool(field_hash)
            checks.append({"项目": "scene/field哈希完整", "通过": hashes_ok, "说明": f"scene_hash={scene_hash or '--'}，field_hash={field_hash or '--'}"})
            if not hashes_ok:
                missing_hashes.append({"结果id": result_id, "scene_hash": scene_hash, "field_hash": field_hash})

            vv_ok = isinstance(payload, Mapping) and isinstance(payload.get("适用性"), Mapping) and isinstance(payload.get("验收清单"), list)
            checks.append({"项目": "V&V适用性记录存在", "通过": vv_ok, "说明": "结果 payload 包含适用性诊断和验收清单。"})
            if not vv_ok:
                missing_vv_records.append({"结果id": result_id, "任务id": job_id or None})

            if job_id:
                job_exists = isinstance(job, Mapping)
                task_path = job.get("任务路径") if job else None
                task_path_exists = bool(task_path) and Path(str(task_path)).exists()
                job_result_match = bool(job) and str(job.get("result_id") or "") == result_id
                lineage_edge_exists = (job_id, result_id, "生成结果") in lineage_edges
                checks.extend(
                    [
                        {"项目": "JOB任务可回溯", "通过": job_exists, "说明": job_id},
                        {"项目": "任务JSON可复查", "通过": task_path_exists, "说明": str(task_path or "--")},
                        {"项目": "JOB/SOL绑定一致", "通过": job_result_match, "说明": f"{job_id} -> {result_id}"},
                        {"项目": "谱系生成边存在", "通过": lineage_edge_exists, "说明": f"{job_id} -> {result_id}"},
                    ]
                )
                if not (job_exists and task_path_exists and job_result_match):
                    missing_job_links.append({"结果id": result_id, "任务id": job_id, "任务存在": job_exists, "任务路径可复查": task_path_exists, "绑定一致": job_result_match})
                if not lineage_edge_exists:
                    missing_lineage_edges.append({"结果id": result_id, "任务id": job_id, "关系": "生成结果"})
                source_type = "队列任务"
            else:
                source_type = "直接求解"
                checks.append({"项目": "直接求解记录", "通过": True, "说明": "该结果由直接求解接口生成，不要求 JOB 任务边。"})

            record_passed = all(bool(item["通过"]) for item in checks)
            records.append(
                {
                    "result_id": result_id,
                    "任务id": job_id or None,
                    "来源": source_type,
                    "通过": record_passed,
                    "复现等级": "可复查" if record_passed else "关注",
                    "scene_hash": scene_hash,
                    "field_hash": field_hash,
                    "结果路径": result_path,
                    "任务路径": job.get("任务路径") if isinstance(job, Mapping) else None,
                    "V&V适用性": bool(vv_ok),
                    "检查": checks,
                    "摘要": self._metric_summary(result),
                }
            )

        checks = [
            {
                "项目": "结果JSON可复查",
                "通过": not missing_result_paths,
                "说明": f"缺失结果路径 {len(missing_result_paths)} 条。",
            },
            {
                "项目": "哈希绑定完整",
                "通过": not missing_hashes,
                "说明": f"缺失 scene_hash 或 field_hash 的结果 {len(missing_hashes)} 条。",
            },
            {
                "项目": "队列结果可回到JOB",
                "通过": not missing_job_links,
                "说明": f"JOB 任务、任务路径或 JOB/SOL 绑定异常 {len(missing_job_links)} 条。",
            },
            {
                "项目": "队列结果有谱系边",
                "通过": not missing_lineage_edges,
                "说明": f"缺失 JOB -> SOL 生成边 {len(missing_lineage_edges)} 条。",
            },
            {
                "项目": "V&V记录可复查",
                "通过": not missing_vv_records,
                "说明": f"缺失适用性诊断或验收清单 {len(missing_vv_records)} 条。",
            },
        ]
        passed = all(bool(item["通过"]) for item in checks)
        reproducible_count = sum(1 for item in records if item["通过"])
        return {
            "版本": "V2.0B-reproducibility-audit",
            "更新时间": time.strftime("%Y-%m-%d %H:%M:%S"),
            "结论": "通过" if passed else "关注",
            "通过": passed,
            "摘要": {
                "结果数": len(records),
                "可复查结果数": reproducible_count,
                "关注结果数": len(records) - reproducible_count,
                "队列结果数": sum(1 for item in records if item["来源"] == "队列任务"),
                "直接求解结果数": sum(1 for item in records if item["来源"] == "直接求解"),
                "谱系边数": (lineage_payload.get("摘要") or {}).get("边数"),
                "任务结果边": (lineage_payload.get("摘要") or {}).get("任务结果边"),
            },
            "结果复现记录": records,
            "异常": {
                "缺失结果路径": missing_result_paths[:12],
                "缺失哈希": missing_hashes[:12],
                "任务关联异常": missing_job_links[:12],
                "谱系边异常": missing_lineage_edges[:12],
                "V&V记录缺失": missing_vv_records[:12],
            },
            "验收清单": checks,
            "索引": self._asset_index_paths(),
            "安全边界": "可复现实验审计只证明归一化快速求解结果的文件、哈希、任务、谱系和V&V记录可复查；不代表真实设备实验、全波仿真或外部测量数据已经完成复现。",
        }

    def _write_asset_reproducibility(self, payload: Mapping[str, Any] | None = None) -> None:
        if self._asset_dir is None:
            return
        audit = dict(payload or self._asset_reproducibility_payload())
        (self._asset_dir / "reproducibility_audit.json").write_text(
            json.dumps(audit, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        rows = []
        for record in audit.get("结果复现记录", []):
            if not isinstance(record, Mapping):
                continue
            rows.append(
                {
                    "result_id": record.get("result_id"),
                    "任务id": record.get("任务id"),
                    "来源": record.get("来源"),
                    "通过": record.get("通过"),
                    "复现等级": record.get("复现等级"),
                    "scene_hash": record.get("scene_hash"),
                    "field_hash": record.get("field_hash"),
                    "结果路径": record.get("结果路径"),
                    "任务路径": record.get("任务路径"),
                    "V&V适用性": record.get("V&V适用性"),
                    "摘要": record.get("摘要"),
                }
            )
        with (self._asset_dir / "reproducibility_audit.csv").open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(
                handle,
                fieldnames=["result_id", "任务id", "来源", "通过", "复现等级", "scene_hash", "field_hash", "结果路径", "任务路径", "V&V适用性", "摘要"],
                extrasaction="ignore",
            )
            writer.writeheader()
            writer.writerows(rows)

    def _write_asset_index(self) -> None:
        if self._asset_dir is None:
            return
        self._asset_dir.mkdir(parents=True, exist_ok=True)
        self._write_imported_calibration_bridge()
        assets = self._asset_records()
        index_payload = {
            "版本": "V2.0B-asset-ledger",
            "更新时间": time.strftime("%Y-%m-%d %H:%M:%S"),
            "数量": len(assets),
            "摘要": self._asset_summary(assets),
            "资产": assets,
            "索引": self._asset_index_paths(),
        }
        (self._asset_dir / "index.json").write_text(
            json.dumps(index_payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        fieldnames = [
            "资产id",
            "类型",
            "标签",
            "状态",
            "创建时间",
            "修订",
            "scene_hash",
            "field_hash",
            "job_id",
            "result_id",
            "路径",
            "辅助路径",
            "摘要",
            "安全边界",
        ]
        with (self._asset_dir / "index.csv").open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(assets)
        if self._asset_db_path is None:
            return
        event_rows = self._solve_job_event_records()
        updated_at = time.strftime("%Y-%m-%d %H:%M:%S")
        with sqlite3.connect(self._asset_db_path) as connection:
            connection.execute("DROP TABLE IF EXISTS workbench3d_assets")
            connection.execute(
                """
                CREATE TABLE workbench3d_assets (
                    asset_id TEXT PRIMARY KEY,
                    asset_type TEXT,
                    label TEXT,
                    status TEXT,
                    created_at TEXT,
                    revision INTEGER,
                    scene_hash TEXT,
                    field_hash TEXT,
                    job_id TEXT,
                    result_id TEXT,
                    path TEXT,
                    auxiliary_path TEXT,
                    summary TEXT,
                    safety_scope TEXT
                )
                """
            )
            connection.execute("DELETE FROM workbench3d_assets")
            connection.executemany(
                """
                INSERT OR REPLACE INTO workbench3d_assets (
                    asset_id, asset_type, label, status, created_at, revision,
                    scene_hash, field_hash, job_id, result_id, path,
                    auxiliary_path, summary, safety_scope
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        item.get("资产id"),
                        item.get("类型"),
                        item.get("标签"),
                        item.get("状态"),
                        item.get("创建时间"),
                        item.get("修订"),
                        item.get("scene_hash"),
                        item.get("field_hash"),
                        item.get("job_id"),
                        item.get("result_id"),
                        item.get("路径"),
                        item.get("辅助路径"),
                        item.get("摘要"),
                        item.get("安全边界"),
                    )
                    for item in assets
                ],
            )
            connection.execute("DROP TABLE IF EXISTS workbench3d_solve_jobs")
            connection.execute(
                """
                CREATE TABLE workbench3d_solve_jobs (
                    job_id TEXT PRIMARY KEY,
                    label TEXT,
                    status TEXT,
                    submitted_at TEXT,
                    started_at TEXT,
                    completed_at TEXT,
                    revision INTEGER,
                    scene_hash TEXT,
                    result_id TEXT,
                    field_hash TEXT,
                    retry_source TEXT,
                    task_path TEXT,
                    result_path TEXT,
                    log_count INTEGER,
                    safety_scope TEXT,
                    raw_json TEXT
                )
                """
            )
            connection.executemany(
                """
                INSERT OR REPLACE INTO workbench3d_solve_jobs (
                    job_id, label, status, submitted_at, started_at, completed_at,
                    revision, scene_hash, result_id, field_hash, retry_source,
                    task_path, result_path, log_count, safety_scope, raw_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        item.get("id"),
                        item.get("标签"),
                        item.get("状态"),
                        item.get("提交时间"),
                        item.get("开始时间"),
                        item.get("完成时间"),
                        item.get("修订"),
                        item.get("scene_hash"),
                        item.get("result_id"),
                        item.get("field_hash"),
                        item.get("重试来源"),
                        item.get("任务路径"),
                        item.get("结果路径"),
                        len(item.get("操作日志")) if isinstance(item.get("操作日志"), list) else 0,
                        item.get("安全边界"),
                        json.dumps(item, ensure_ascii=False, sort_keys=True),
                    )
                    for item in self._solve_jobs
                ],
            )
            connection.execute("DROP TABLE IF EXISTS workbench3d_solve_job_events")
            connection.execute(
                """
                CREATE TABLE workbench3d_solve_job_events (
                    event_id TEXT PRIMARY KEY,
                    job_id TEXT,
                    event_index INTEGER,
                    action TEXT,
                    event_time TEXT,
                    passed INTEGER,
                    source_job TEXT,
                    new_job TEXT,
                    job_status TEXT,
                    result_id TEXT,
                    scene_hash TEXT,
                    field_hash TEXT,
                    task_path TEXT,
                    note TEXT,
                    raw_json TEXT
                )
                """
            )
            connection.executemany(
                """
                INSERT OR REPLACE INTO workbench3d_solve_job_events (
                    event_id, job_id, event_index, action, event_time, passed,
                    source_job, new_job, job_status, result_id, scene_hash,
                    field_hash, task_path, note, raw_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        item.get("event_id"),
                        item.get("job_id"),
                        item.get("event_index"),
                        item.get("action"),
                        item.get("event_time"),
                        item.get("passed"),
                        item.get("source_job"),
                        item.get("new_job"),
                        item.get("job_status"),
                        item.get("result_id"),
                        item.get("scene_hash"),
                        item.get("field_hash"),
                        item.get("task_path"),
                        item.get("note"),
                        item.get("raw_json"),
                    )
                    for item in event_rows
                ],
            )
            connection.execute("DROP TABLE IF EXISTS workbench3d_results")
            connection.execute(
                """
                CREATE TABLE workbench3d_results (
                    result_id TEXT PRIMARY KEY,
                    job_id TEXT,
                    created_at TEXT,
                    revision INTEGER,
                    scene_hash TEXT,
                    field_hash TEXT,
                    backend TEXT,
                    method TEXT,
                    target_rmse REAL,
                    minimum_coverage REAL,
                    peak_outside_db REAL,
                    protected_violation REAL,
                    result_path TEXT,
                    safety_scope TEXT,
                    raw_json TEXT
                )
                """
            )
            connection.executemany(
                """
                INSERT OR REPLACE INTO workbench3d_results (
                    result_id, job_id, created_at, revision, scene_hash, field_hash,
                    backend, method, target_rmse, minimum_coverage,
                    peak_outside_db, protected_violation, result_path,
                    safety_scope, raw_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        item.get("id"),
                        item.get("任务id"),
                        item.get("创建时间"),
                        item.get("修订"),
                        item.get("scene_hash"),
                        item.get("field_hash"),
                        item.get("传播后端"),
                        item.get("方法"),
                        item.get("目标RMSE"),
                        item.get("最低覆盖率"),
                        item.get("区外峰值"),
                        item.get("保护区超限"),
                        item.get("保存路径"),
                        item.get("安全边界"),
                        json.dumps(item, ensure_ascii=False, sort_keys=True),
                    )
                    for item in self._solve_results
                ],
            )
            connection.execute("DROP TABLE IF EXISTS workbench3d_snapshots")
            connection.execute(
                """
                CREATE TABLE workbench3d_snapshots (
                    snapshot_id TEXT PRIMARY KEY,
                    label TEXT,
                    created_at TEXT,
                    revision INTEGER,
                    scene_hash TEXT,
                    object_count INTEGER,
                    enabled_object_count INTEGER,
                    project_path TEXT,
                    scene_path TEXT,
                    safety_scope TEXT,
                    raw_json TEXT
                )
                """
            )
            connection.executemany(
                """
                INSERT OR REPLACE INTO workbench3d_snapshots (
                    snapshot_id, label, created_at, revision, scene_hash,
                    object_count, enabled_object_count, project_path, scene_path,
                    safety_scope, raw_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        item.get("id"),
                        item.get("标签"),
                        item.get("创建时间"),
                        item.get("修订"),
                        item.get("scene_hash"),
                        item.get("对象总数"),
                        item.get("启用对象数"),
                        item.get("工程路径"),
                        item.get("场景路径"),
                        "工程快照只保存归一化 CAEProject 和三维场景 JSON，不代表实物状态。",
                        json.dumps(item, ensure_ascii=False, sort_keys=True),
                    )
                    for item in self._snapshots
                ],
            )
            connection.execute("DROP TABLE IF EXISTS workbench3d_database_manifest")
            connection.execute(
                """
                CREATE TABLE workbench3d_database_manifest (
                    key TEXT PRIMARY KEY,
                    value TEXT
                )
                """
            )
            manifest_rows = {
                "version": "V2.0B-workbench-database-preview",
                "updated_at": updated_at,
                "asset_count": str(len(assets)),
                "job_count": str(len(self._solve_jobs)),
                "event_count": str(len(event_rows)),
                "result_count": str(len(self._solve_results)),
                "snapshot_count": str(len(self._snapshots)),
                "table_count": str(len(self._sqlite_table_names())),
                "safety_scope": "SQLite 数据库仅保存归一化工程资产、任务、结果、快照和本地事件，不代表真实设备任务数据库。",
            }
            connection.executemany(
                "INSERT OR REPLACE INTO workbench3d_database_manifest (key, value) VALUES (?, ?)",
                list(manifest_rows.items()),
            )
        audit_payload = self._asset_audit_payload(assets)
        (self._asset_dir / "audit.json").write_text(
            json.dumps(audit_payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        with (self._asset_dir / "audit.csv").open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=["项目", "通过", "说明"], extrasaction="ignore")
            writer.writeheader()
            writer.writerows(audit_payload["验收清单"])
        database_audit = self._asset_database_audit_payload()
        (self._asset_dir / "database_audit.json").write_text(
            json.dumps(database_audit, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        with (self._asset_dir / "database_audit.csv").open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=["项目", "通过", "说明"], extrasaction="ignore")
            writer.writeheader()
            writer.writerows(database_audit["验收清单"])
        naming_audit = self._asset_naming_audit_payload()
        (self._asset_dir / "naming_audit.json").write_text(
            json.dumps(naming_audit, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        with (self._asset_dir / "naming_audit.csv").open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=["项目", "通过", "说明"], extrasaction="ignore")
            writer.writeheader()
            writer.writerows(naming_audit["验收清单"])
        lineage = self._asset_lineage_payload()
        self._write_asset_lineage(lineage)
        self._write_asset_reproducibility(self._asset_reproducibility_payload(lineage))
        self._write_absolute_calibration()
        self._write_imported_calibration_bridge()

    def list_assets(
        self,
        asset_type: str | None = None,
        query: str | None = None,
        limit: int | None = None,
    ) -> dict[str, Any]:
        with self._lock:
            self._write_asset_index()
            assets = self._asset_records()
            filtered = self._filter_asset_records(assets, asset_type=asset_type, query=query)
            limit_value = self._coerce_asset_limit(limit)
            limited = filtered[:limit_value] if limit_value is not None else filtered
            filter_meta = {
                "类型": str(asset_type or "全部").strip() or "全部",
                "关键字": str(query or "").strip(),
                "limit": limit_value,
                "总资产": len(assets),
                "匹配资产": len(filtered),
                "返回资产": len(limited),
            }
            return {
                "资产": limited,
                "摘要": self._asset_summary(assets),
                "审计": self._asset_audit_payload(assets, filtered_assets=filtered, filter_meta=filter_meta),
                "数据库审计": self._asset_database_audit_payload(),
                "命名审计": self._asset_naming_audit_payload(),
                "资产谱系": self._asset_lineage_payload(),
                "复现审计": self._asset_reproducibility_payload(),
                "绝对量纲标定": self._absolute_calibration_payload(),
                "导入数据标定桥接": self._imported_calibration_bridge_payload(),
                "筛选": filter_meta,
                "索引": self._asset_index_paths(),
                "历史": self.history(),
            }

    def audit_assets(self, asset_type: str | None = None, query: str | None = None) -> dict[str, Any]:
        with self._lock:
            self._write_asset_index()
            assets = self._asset_records()
            filtered = self._filter_asset_records(assets, asset_type=asset_type, query=query)
            filter_meta = {
                "类型": str(asset_type or "全部").strip() or "全部",
                "关键字": str(query or "").strip(),
                "总资产": len(assets),
                "匹配资产": len(filtered),
            }
            return {
                "审计": self._asset_audit_payload(assets, filtered_assets=filtered, filter_meta=filter_meta),
                "资产": filtered,
                "索引": self._asset_index_paths(),
            }

    def audit_asset_naming(self) -> dict[str, Any]:
        with self._lock:
            self._write_asset_index()
            naming_audit = self._asset_naming_audit_payload()
            if self._asset_dir is not None:
                (self._asset_dir / "naming_audit.json").write_text(
                    json.dumps(naming_audit, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
                with (self._asset_dir / "naming_audit.csv").open("w", encoding="utf-8-sig", newline="") as handle:
                    writer = csv.DictWriter(handle, fieldnames=["项目", "通过", "说明"], extrasaction="ignore")
                    writer.writeheader()
                    writer.writerows(naming_audit["验收清单"])
            return {
                "命名审计": naming_audit,
                "资产": self._asset_records(),
                "索引": self._asset_index_paths(),
                "历史": self.history(),
            }

    def audit_asset_database(self) -> dict[str, Any]:
        with self._lock:
            self._write_asset_index()
            database_audit = self._asset_database_audit_payload()
            if self._asset_dir is not None:
                (self._asset_dir / "database_audit.json").write_text(
                    json.dumps(database_audit, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
                with (self._asset_dir / "database_audit.csv").open("w", encoding="utf-8-sig", newline="") as handle:
                    writer = csv.DictWriter(handle, fieldnames=["项目", "通过", "说明"], extrasaction="ignore")
                    writer.writeheader()
                    writer.writerows(database_audit["验收清单"])
            return {
                "数据库审计": database_audit,
                "任务事件": self._solve_job_event_records(),
                "索引": self._asset_index_paths(),
                "历史": self.history(),
            }

    def asset_database_records(self, table: str | None = None, limit: int | None = 50) -> dict[str, Any]:
        with self._lock:
            self._write_asset_index()
            paths = self._asset_index_paths()
            db_path = paths.get("sqlite")
            limit_value = self._coerce_asset_limit(limit) or 50
            table_names = list(self._sqlite_table_names())
            selected_table = str(table or "").strip()
            if selected_table and selected_table not in table_names:
                raise ValueError(f"未知数据库表：{selected_table}")
            selected_tables = [selected_table] if selected_table else table_names
            schemas: dict[str, list[dict[str, Any]]] = {}
            records: dict[str, list[dict[str, Any]]] = {}
            row_counts: dict[str, int] = {}
            if db_path and Path(str(db_path)).exists():
                with sqlite3.connect(str(db_path)) as connection:
                    connection.row_factory = sqlite3.Row
                    existing_tables = {
                        str(row["name"])
                        for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
                    }
                    for name in selected_tables:
                        if name not in existing_tables:
                            schemas[name] = []
                            records[name] = []
                            row_counts[name] = 0
                            continue
                        schemas[name] = [
                            {
                                "列": row["name"],
                                "类型": row["type"],
                                "非空": bool(row["notnull"]),
                                "主键": bool(row["pk"]),
                            }
                            for row in connection.execute(f"PRAGMA table_info({name})").fetchall()
                        ]
                        row_counts[name] = int(connection.execute(f"SELECT COUNT(*) FROM {name}").fetchone()[0])
                        records[name] = [
                            dict(row)
                            for row in connection.execute(f"SELECT * FROM {name} LIMIT ?", (limit_value,)).fetchall()
                        ]
            return {
                "版本": "V2.0B-database-record-browser",
                "更新时间": time.strftime("%Y-%m-%d %H:%M:%S"),
                "数据库路径": db_path,
                "表": selected_tables,
                "表数量": len(selected_tables),
                "limit": limit_value,
                "行数": row_counts,
                "结构": schemas,
                "记录": records,
                "审计": self._asset_database_audit_payload(),
                "索引": paths,
                "安全边界": "数据库浏览接口只返回归一化工程资产、任务、结果、快照和本地事件的审计记录，不代表真实设备任务数据库。",
            }

    def asset_lineage(self) -> dict[str, Any]:
        with self._lock:
            self._write_asset_index()
            lineage = self._asset_lineage_payload()
            self._write_asset_lineage(lineage)
            return lineage

    def asset_reproducibility(self) -> dict[str, Any]:
        with self._lock:
            self._write_asset_index()
            lineage = self._asset_lineage_payload()
            audit = self._asset_reproducibility_payload(lineage)
            self._write_asset_reproducibility(audit)
            return audit

    def absolute_calibration(self) -> dict[str, Any]:
        with self._lock:
            payload = self._absolute_calibration_payload()
            self._write_absolute_calibration(payload)
            return payload

    def imported_calibration_bridge(self) -> dict[str, Any]:
        with self._lock:
            self._write_asset_index()
            payload = self._imported_calibration_bridge_payload()
            self._write_imported_calibration_bridge(payload)
            return payload

    def update_absolute_calibration(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        with self._lock:
            self._absolute_calibration = _normalize_absolute_calibration(self._project, payload)
            self._revision += 1
            calibration = self._absolute_calibration_payload()
            self._write_absolute_calibration(calibration)
            self._write_asset_index()
            return calibration

    def get_asset(self, asset_id: str) -> dict[str, Any]:
        with self._lock:
            self._write_asset_index()
            record = next((dict(item) for item in self._asset_records() if str(item.get("资产id")) == asset_id), None)
            if record is None:
                raise ValueError(f"未找到工程资产：{asset_id}")
            detail: Any = None
            if record["类型"] == "求解任务" and record.get("job_id"):
                detail = self.get_solve_job(str(record["job_id"]))
            elif record["类型"] == "求解结果" and record.get("result_id"):
                detail = self.get_result(str(record["result_id"]))
            elif record["类型"] == "工程快照":
                detail = next((dict(item) for item in self._snapshots if str(item.get("id")) == asset_id), None)
            elif record["类型"] == "导入标定桥接":
                detail = self._imported_calibration_bridge_payload()
            return {"资产": record, "详情": detail, "索引": self._asset_index_paths()}

    def list_results(self) -> dict[str, Any]:
        with self._lock:
            index_path = str(self._result_dir / "index.json") if self._result_dir is not None else None
            csv_path = str(self._result_dir / "index.csv") if self._result_dir is not None else None
            return {"结果": [dict(item) for item in self._solve_results], "索引": {"json": index_path, "csv": csv_path}, "历史": self.history()}

    def cancel_solve_job(self, job_id: str) -> dict[str, Any]:
        with self._lock:
            if job_id not in self._solve_job_payloads:
                raise ValueError(f"未找到求解任务：{job_id}")
            payload = json.loads(json.dumps(self._solve_job_payloads[job_id], ensure_ascii=False))
            record = dict(payload.get("任务") or {})
            now = time.strftime("%Y-%m-%d %H:%M:%S")
            status = str(record.get("状态") or "")
            can_cancel = status in {"排队中", "运行中", "已暂停"}
            operation = {
                "动作": "取消",
                "时间": now,
                "通过": can_cancel,
                "说明": "任务已取消。" if can_cancel else f"{status or '未知状态'}任务不可取消，已保留原记录。",
            }
            if can_cancel:
                record["状态"] = "已取消"
                record["取消时间"] = now
                record["完成时间"] = record.get("完成时间") or now
            logs = record.get("操作日志") if isinstance(record.get("操作日志"), list) else []
            record["操作日志"] = [dict(item) for item in logs if isinstance(item, Mapping)] + [operation]
            payload["任务"] = dict(record)
            result = payload.get("结果")
            if isinstance(result, dict):
                result["求解任务"] = dict(record)
                payload["结果"] = result
                result_id = str(record.get("result_id") or result.get("result_id") or "")
                if result_id:
                    self._solve_result_payloads[result_id] = json.loads(json.dumps(result, ensure_ascii=False))
                result_record = result.get("结果档案")
                if isinstance(result_record, Mapping) and result_record.get("保存路径"):
                    Path(str(result_record["保存路径"])).write_text(
                        json.dumps(result, ensure_ascii=False, indent=2),
                        encoding="utf-8",
                    )
            self._replace_solve_job_record(job_id, record, payload)
            return {
                "操作": operation,
                "任务": dict(record),
                "队列": [dict(item) for item in self._solve_jobs],
                "索引": self._solve_job_index_paths(),
                "审计": self._solve_job_audit_payload(),
            }

    def pause_solve_job(self, job_id: str) -> dict[str, Any]:
        with self._lock:
            if job_id not in self._solve_job_payloads:
                raise ValueError(f"未找到求解任务：{job_id}")
            payload = json.loads(json.dumps(self._solve_job_payloads[job_id], ensure_ascii=False))
            record = dict(payload.get("任务") or {})
            now = time.strftime("%Y-%m-%d %H:%M:%S")
            status = str(record.get("状态") or "")
            can_pause = status in {"排队中", "运行中"}
            operation = {
                "动作": "暂停",
                "时间": now,
                "通过": can_pause or status == "已暂停",
                "说明": "任务已暂停在后台worker检查点。" if can_pause else f"{status or '未知状态'}任务不可暂停。",
            }
            if can_pause:
                record["状态"] = "已暂停"
                record["暂停时间"] = now
                record["worker"] = record.get("worker") or "等待恢复"
            elif status == "已暂停":
                operation["说明"] = "任务已经处于暂停状态。"
            logs = record.get("操作日志") if isinstance(record.get("操作日志"), list) else []
            record["操作日志"] = [dict(item) for item in logs if isinstance(item, Mapping)] + [operation]
            payload["任务"] = dict(record)
            self._replace_solve_job_record(job_id, record, payload)
            return {
                "操作": operation,
                "任务": dict(record),
                "队列": [dict(item) for item in self._solve_jobs],
                "索引": self._solve_job_index_paths(),
                "审计": self._solve_job_audit_payload(),
            }

    def resume_solve_job(self, job_id: str) -> dict[str, Any]:
        should_start = False
        with self._lock:
            if job_id not in self._solve_job_payloads:
                raise ValueError(f"未找到求解任务：{job_id}")
            payload = json.loads(json.dumps(self._solve_job_payloads[job_id], ensure_ascii=False))
            record = dict(payload.get("任务") or {})
            now = time.strftime("%Y-%m-%d %H:%M:%S")
            status = str(record.get("状态") or "")
            can_resume = status == "已暂停"
            operation = {
                "动作": "恢复",
                "时间": now,
                "通过": can_resume,
                "说明": "任务已重新进入后台worker队列。" if can_resume else f"{status or '未知状态'}任务不可恢复。",
            }
            if can_resume:
                record["状态"] = "排队中"
                record["恢复时间"] = now
                record["worker"] = "本地后台worker"
                should_start = True
            logs = record.get("操作日志") if isinstance(record.get("操作日志"), list) else []
            record["操作日志"] = [dict(item) for item in logs if isinstance(item, Mapping)] + [operation]
            payload["任务"] = dict(record)
            self._replace_solve_job_record(job_id, record, payload)
            response = {
                "操作": operation,
                "任务": dict(record),
                "队列": [dict(item) for item in self._solve_jobs],
                "索引": self._solve_job_index_paths(),
                "审计": self._solve_job_audit_payload(),
            }
        if should_start:
            self._start_background_solve_worker(job_id)
        return response

    def retry_solve_job(self, job_id: str) -> dict[str, Any]:
        with self._lock:
            if job_id not in self._solve_job_payloads:
                raise ValueError(f"未找到求解任务：{job_id}")
            source_payload = json.loads(json.dumps(self._solve_job_payloads[job_id], ensure_ascii=False))
            source_record = dict(source_payload.get("任务") or {})
            label = f"重试 {source_record.get('标签') or job_id}"
            new_response = self.submit_solve_job(label, retry_of=job_id)
            now = time.strftime("%Y-%m-%d %H:%M:%S")
            new_job_id = str(new_response["任务"]["id"])
            operation = {
                "动作": "重试",
                "时间": now,
                "通过": True,
                "来源任务": job_id,
                "新任务": new_job_id,
                "说明": f"已生成重试任务 {new_job_id}。",
            }
            logs = source_record.get("操作日志") if isinstance(source_record.get("操作日志"), list) else []
            source_record["操作日志"] = [dict(item) for item in logs if isinstance(item, Mapping)] + [operation]
            source_payload["任务"] = dict(source_record)
            source_result = source_payload.get("结果")
            if isinstance(source_result, dict):
                source_result["求解任务"] = dict(source_record)
                source_payload["结果"] = source_result
                result_id = str(source_record.get("result_id") or source_result.get("result_id") or "")
                if result_id:
                    self._solve_result_payloads[result_id] = json.loads(json.dumps(source_result, ensure_ascii=False))
                result_record = source_result.get("结果档案")
                if isinstance(result_record, Mapping) and result_record.get("保存路径"):
                    Path(str(result_record["保存路径"])).write_text(
                        json.dumps(source_result, ensure_ascii=False, indent=2),
                        encoding="utf-8",
                    )
            self._replace_solve_job_record(job_id, source_record, source_payload)
            return {
                "操作": operation,
                "任务": dict(new_response["任务"]),
                "结果": new_response.get("结果"),
                "队列": [dict(item) for item in self._solve_jobs],
                "索引": self._solve_job_index_paths(),
                "审计": self._solve_job_audit_payload(),
            }

    def audit_solve_jobs(self) -> dict[str, Any]:
        with self._lock:
            self._write_solve_job_index()
            return {
                "审计": self._solve_job_audit_payload(),
                "任务": [dict(item) for item in self._solve_jobs],
                "索引": self._solve_job_index_paths(),
                "历史": self.history(),
            }

    def list_solve_jobs(self) -> dict[str, Any]:
        with self._lock:
            return {
                "任务": [dict(item) for item in self._solve_jobs],
                "审计": self._solve_job_audit_payload(),
                "索引": self._solve_job_index_paths(),
                "历史": self.history(),
            }

    def get_solve_job(self, job_id: str) -> dict[str, Any]:
        with self._lock:
            if job_id not in self._solve_job_payloads:
                raise ValueError(f"未找到求解任务：{job_id}")
            return json.loads(json.dumps(self._solve_job_payloads[job_id], ensure_ascii=False))

    def get_result(self, result_id: str) -> dict[str, Any]:
        with self._lock:
            if result_id not in self._solve_result_payloads:
                raise ValueError(f"未找到求解结果：{result_id}")
            return json.loads(json.dumps(self._solve_result_payloads[result_id], ensure_ascii=False))

    def reset(self) -> dict[str, Any]:
        with self._lock:
            self._push_undo()
            self._project = self._load_project()
            self._revision += 1
            return self.scene()

    def undo(self) -> dict[str, Any]:
        with self._lock:
            if not self._undo_stack:
                raise ValueError("没有可撤销的三维编辑")
            self._redo_stack.append(self._project)
            self._project = self._undo_stack.pop()
            self._revision += 1
            return self.scene()

    def redo(self) -> dict[str, Any]:
        with self._lock:
            if not self._redo_stack:
                raise ValueError("没有可重做的三维编辑")
            self._undo_stack.append(self._project)
            self._project = self._redo_stack.pop()
            self._revision += 1
            return self.scene()

    def capture_snapshot(self, label: str | None = None) -> dict[str, Any]:
        with self._lock:
            scene = build_workbench3d_scene(self._project, self._revision, self.history())
            self._snapshot_serial += 1
            snapshot_id = f"SNP-{self._snapshot_serial:04d}"
            record = {
                "id": snapshot_id,
                "标签": str(label).strip() if label and str(label).strip() else f"工程快照 {self._snapshot_serial:04d}",
                "创建时间": time.strftime("%Y-%m-%d %H:%M:%S"),
                "修订": self._revision,
                "scene_hash": scene["scene_hash"],
                "对象总数": scene["统计"]["对象总数"],
                "启用对象数": scene["统计"]["启用对象数"],
                "工程路径": None,
                "场景路径": None,
            }
            if self._snapshot_dir is not None:
                self._snapshot_dir.mkdir(parents=True, exist_ok=True)
                project_path = self._snapshot_dir / f"{snapshot_id}_{record['scene_hash']}.yaml"
                scene_path = self._snapshot_dir / f"{snapshot_id}_{record['scene_hash']}_scene.json"
                self._project.save_yaml(project_path)
                scene_path.write_text(json.dumps(scene, ensure_ascii=False, indent=2), encoding="utf-8")
                record["工程路径"] = str(project_path)
                record["场景路径"] = str(scene_path)
            self._snapshots.append(record)
            self._snapshot_projects[snapshot_id] = self._project
            if len(self._snapshots) > self._max_snapshots:
                removed = self._snapshots.pop(0)
                self._snapshot_projects.pop(str(removed["id"]), None)
                for key in ("工程路径", "场景路径"):
                    if removed.get(key):
                        Path(str(removed[key])).unlink(missing_ok=True)
            self._write_snapshot_index()
            return {"成功": True, "快照": dict(record), "历史": self.history()}

    def _load_snapshot_archive(self) -> None:
        if self._snapshot_dir is None or not self._snapshot_dir.exists():
            return
        records: list[dict[str, Any]] = []
        index_path = self._snapshot_dir / "index.json"
        if index_path.exists():
            try:
                index_payload = json.loads(index_path.read_text(encoding="utf-8"))
                raw_records = index_payload.get("快照", [])
                if isinstance(raw_records, list):
                    records = [dict(item) for item in raw_records if isinstance(item, Mapping)]
            except (OSError, json.JSONDecodeError):
                records = []
        if not records:
            for project_path in sorted(self._snapshot_dir.glob("SNP-*.yaml")):
                try:
                    project = CAEProject.load_yaml(project_path)
                except (OSError, ValueError):
                    continue
                snapshot_id = project_path.name.split("_", 1)[0]
                scene = build_workbench3d_scene(project, self._revision, {})
                records.append(
                    {
                        "id": snapshot_id,
                        "标签": snapshot_id,
                        "创建时间": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(project_path.stat().st_mtime)),
                        "修订": self._revision,
                        "scene_hash": scene["scene_hash"],
                        "对象总数": scene["统计"]["对象总数"],
                        "启用对象数": scene["统计"]["启用对象数"],
                        "工程路径": str(project_path),
                        "场景路径": str(project_path.with_name(f"{project_path.stem}_scene.json")),
                    }
                )
        snapshots: list[dict[str, Any]] = []
        projects: dict[str, CAEProject] = {}
        max_serial = 0
        for record in records[-self._max_snapshots :]:
            snapshot_id = str(record.get("id") or "")
            project_path_value = record.get("工程路径")
            if not snapshot_id or not project_path_value:
                continue
            project_path = Path(str(project_path_value))
            if not project_path.exists():
                project_path = self._snapshot_dir / project_path.name
            try:
                project = CAEProject.load_yaml(project_path)
            except (OSError, ValueError):
                continue
            record = dict(record)
            record["id"] = snapshot_id
            record["工程路径"] = str(project_path)
            if record.get("场景路径"):
                scene_path = Path(str(record["场景路径"]))
                if not scene_path.exists():
                    scene_path = self._snapshot_dir / scene_path.name
                record["场景路径"] = str(scene_path)
            snapshots.append(record)
            projects[snapshot_id] = project
            try:
                max_serial = max(max_serial, int(snapshot_id.split("-", 1)[1]))
            except (IndexError, ValueError):
                pass
        self._snapshots = snapshots
        self._snapshot_projects = projects
        self._snapshot_serial = max(self._snapshot_serial, max_serial)
        self._write_snapshot_index()

    def _write_snapshot_index(self) -> None:
        if self._snapshot_dir is None:
            return
        self._snapshot_dir.mkdir(parents=True, exist_ok=True)
        index_payload = {
            "版本": "V2.0B-snapshot-index",
            "更新时间": time.strftime("%Y-%m-%d %H:%M:%S"),
            "数量": len(self._snapshots),
            "快照": [dict(item) for item in self._snapshots],
        }
        (self._snapshot_dir / "index.json").write_text(
            json.dumps(index_payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        fieldnames = ["id", "标签", "创建时间", "修订", "scene_hash", "对象总数", "启用对象数", "工程路径", "场景路径"]
        with (self._snapshot_dir / "index.csv").open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(self._snapshots)
        self._write_asset_index()

    def list_snapshots(self) -> dict[str, Any]:
        with self._lock:
            index_path = str(self._snapshot_dir / "index.json") if self._snapshot_dir is not None else None
            csv_path = str(self._snapshot_dir / "index.csv") if self._snapshot_dir is not None else None
            return {"快照": [dict(item) for item in self._snapshots], "索引": {"json": index_path, "csv": csv_path}, "历史": self.history()}

    def diff_snapshots(self, left_id: str, right_id: str) -> dict[str, Any]:
        with self._lock:
            if left_id not in self._snapshot_projects:
                raise ValueError(f"未找到左侧工程快照：{left_id}")
            if right_id not in self._snapshot_projects:
                raise ValueError(f"未找到右侧工程快照：{right_id}")
            left_scene = build_workbench3d_scene(self._snapshot_projects[left_id], self._revision, {})
            right_scene = build_workbench3d_scene(self._snapshot_projects[right_id], self._revision, {})
            left_record = next((dict(item) for item in self._snapshots if item["id"] == left_id), {"id": left_id})
            right_record = next((dict(item) for item in self._snapshots if item["id"] == right_id), {"id": right_id})
            object_diffs = self._diff_scene_collection(left_scene["对象"], right_scene["对象"], ("名称", "类型", "层级", "启用", "材料", "几何", "属性"))
            material_diffs = self._diff_scene_collection(left_scene["材料库"], right_scene["材料库"], ("名称", "类型", "属性"))
            return {
                "成功": True,
                "左快照": left_record,
                "右快照": right_record,
                "scene_hash_changed": left_scene["scene_hash"] != right_scene["scene_hash"],
                "摘要": {
                    "对象差异数": len(object_diffs),
                    "材料差异数": len(material_diffs),
                    "字段变更数": sum(len(item["变更"]) for item in object_diffs) + sum(len(item["变更"]) for item in material_diffs),
                },
                "对象差异": object_diffs,
                "材料差异": material_diffs,
                "安全边界": "快照差异仅比较三维工作台工程参数和归一化代理字段，不代表实物状态或全波仿真差异。",
            }

    @staticmethod
    def _diff_scene_collection(
        left_items: list[dict[str, Any]],
        right_items: list[dict[str, Any]],
        compared_keys: tuple[str, ...],
    ) -> list[dict[str, Any]]:
        left_by_id = {str(item.get("id")): item for item in left_items}
        right_by_id = {str(item.get("id")): item for item in right_items}
        diffs: list[dict[str, Any]] = []
        for item_id in sorted(set(left_by_id) | set(right_by_id)):
            left = left_by_id.get(item_id)
            right = right_by_id.get(item_id)
            if left is None:
                diffs.append({"id": item_id, "名称": right.get("名称", item_id) if right else item_id, "类型": "新增", "变更": [{"字段": "__exists__", "左": None, "右": True}]})
                continue
            if right is None:
                diffs.append({"id": item_id, "名称": left.get("名称", item_id), "类型": "删除", "变更": [{"字段": "__exists__", "左": True, "右": None}]})
                continue
            left_flat = _flatten_payload({key: left.get(key) for key in compared_keys})
            right_flat = _flatten_payload({key: right.get(key) for key in compared_keys})
            changes = _diff_flattened(left_flat, right_flat)
            if changes:
                diffs.append(
                    {
                        "id": item_id,
                        "名称": right.get("名称") or left.get("名称") or item_id,
                        "类型": right.get("类型") or left.get("类型") or "unknown",
                        "变更": changes,
                    }
                )
        return diffs

    def restore_snapshot(self, snapshot_id: str) -> dict[str, Any]:
        with self._lock:
            if snapshot_id not in self._snapshot_projects:
                raise ValueError(f"未找到工程快照：{snapshot_id}")
            self._push_undo()
            self._project = self._snapshot_projects[snapshot_id]
            self._revision += 1
            return self.scene()

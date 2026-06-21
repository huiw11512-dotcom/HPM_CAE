"""V2.0A 单因素敏感性分析。"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from hpm_platform.physics.array_geometry import RectangularArray
from hpm_platform.physics.field_backends import get_field_backend
from hpm_platform.ui.project_model import CAEProject


@dataclass
class SensitivityResult:
    summary: dict[str, Any]
    records: list[dict[str, Any]]
    data: dict[str, Any] = field(default_factory=dict, repr=False)

    def frame(self) -> pd.DataFrame:
        return pd.DataFrame(self.records)

    def as_dict(self) -> dict[str, Any]:
        return {
            "汇总": self.summary,
            "记录": self.records,
        }


def run_oat_sensitivity(project_path: str | Path | None = None) -> SensitivityResult:
    project = CAEProject.load_yaml(project_path or _default_project_path())
    records = [
        _record("阵元相位误差", "deg", 0.0, 6.0, _array_metric(phase_error_deg=0.0), _array_metric(phase_error_deg=6.0)),
        _record("阵元幅度误差", "%", 0.0, 5.0, _array_metric(amplitude_error_percent=0.0), _array_metric(amplitude_error_percent=5.0)),
        _record("目标指向偏移", "uv", 0.0, 0.02, _array_metric(target_shift_uv=0.0), _array_metric(target_shift_uv=0.02)),
        _record("反射系数", "归一化", 0.0, 0.8, _reflection_metric(project, 0.0), _reflection_metric(project, 0.8)),
        _record("孔缝耦合系数", "归一化", 0.0, 0.55, _aperture_metric(project, 0.0), _aperture_metric(project, 0.55)),
    ]
    records.sort(key=lambda row: float(row["敏感度"]), reverse=True)
    for rank, row in enumerate(records, start=1):
        row["排序"] = rank
    summary = {
        "排序可用": True,
        "最敏感因素": records[0]["因素"],
        "最敏感因素敏感度": records[0]["敏感度"],
        "中文解释": "OAT 结果显示该归一化基准中方向指向偏移和阵元相位误差通常主导方向图误差；后端项反映模型机制打开后相对自由空间基线的偏离。",
    }
    return SensitivityResult(
        summary=summary,
        records=records,
        data={
            "labels": np.array([str(row["因素"]) for row in records]),
            "values": np.array([float(row["敏感度"]) for row in records]),
        },
    )


def _default_project_path() -> Path:
    return Path(__file__).resolve().parents[3] / "configs" / "cae_project_v14.yaml"


def _record(name: str, unit: str, low: float, high: float, low_metric: float, high_metric: float) -> dict[str, Any]:
    sensitivity = abs(float(high_metric) - float(low_metric)) / max(abs(float(high) - float(low)), np.finfo(float).tiny)
    return {
        "因素": name,
        "单位": unit,
        "低值": float(low),
        "高值": float(high),
        "低值误差指标": float(low_metric),
        "高值误差指标": float(high_metric),
        "敏感度": float(sensitivity),
    }


def _array_metric(
    *,
    phase_error_deg: float = 0.0,
    amplitude_error_percent: float = 0.0,
    target_shift_uv: float = 0.0,
) -> float:
    array = RectangularArray(nx=8, ny=8, frequency_hz=1.0e9)
    u0, v0 = 0.25, -0.15
    axis = np.linspace(-0.6, 0.6, 91)
    uu, vv = np.meshgrid(axis, axis, indexing="xy")
    base_phase = -array.wave_number * (array.positions_m[:, 0] * u0 + array.positions_m[:, 1] * v0)
    base_q = np.exp(1j * base_phase) / np.sqrt(array.n_elements)
    base = array.transmit_response_uv(base_q, uu, vv)

    rng = np.random.default_rng(1401)
    phase_template = rng.normal(0.0, 1.0, size=array.n_elements)
    amp_template = rng.normal(0.0, 1.0, size=array.n_elements)
    shifted_u = u0 + float(target_shift_uv)
    shifted_v = v0 - 0.5 * float(target_shift_uv)
    phase = -array.wave_number * (array.positions_m[:, 0] * shifted_u + array.positions_m[:, 1] * shifted_v)
    phase += np.deg2rad(float(phase_error_deg)) * phase_template
    amp = np.clip(1.0 + float(amplitude_error_percent) / 100.0 * amp_template, 0.05, None)
    q = amp * np.exp(1j * phase)
    q /= np.linalg.norm(q)
    pattern = array.transmit_response_uv(q, uu, vv)
    peak_idx = int(np.nanargmax(pattern))
    peak_error = float(np.hypot(float(np.ravel(uu)[peak_idx]) - u0, float(np.ravel(vv)[peak_idx]) - v0))
    rmse = float(np.sqrt(np.nanmean((pattern - base) ** 2)))
    return rmse + peak_error


def _sample_points(array: RectangularArray) -> np.ndarray:
    axis = np.linspace(-2.0, 2.0, 9) * array.wavelength_m
    xx, yy = np.meshgrid(axis, axis, indexing="xy")
    zz = np.full_like(xx, 8.0 * array.wavelength_m)
    return np.column_stack((xx.ravel(), yy.ravel(), zz.ravel()))


def _reflection_metric(project: CAEProject, reflection_scale: float) -> float:
    array = project.array.build_array()
    points = _sample_points(array)
    free = get_field_backend("free_space_green").matrix(
        array,
        points,
        project=replace(project, propagation=replace(project.propagation, backend="free_space_green", direct_path_scale=1.0)),
        reference_scale=1.0,
    )
    candidate_project = replace(
        project,
        propagation=replace(project.propagation, backend="image_ray", direct_path_scale=1.0, reflection_scale=float(reflection_scale)),
    )
    candidate = get_field_backend("image_ray").matrix(array, points, project=candidate_project, reference_scale=1.0)
    return float(np.linalg.norm(candidate - free) / max(np.linalg.norm(free), np.finfo(float).tiny))


def _aperture_metric(project: CAEProject, coupling_scale: float) -> float:
    array = project.array.build_array()
    points = _sample_points(array)
    free = get_field_backend("free_space_green").matrix(
        array,
        points,
        project=replace(project, propagation=replace(project.propagation, backend="free_space_green", direct_path_scale=1.0)),
        reference_scale=1.0,
    )
    candidate_project = replace(
        project,
        propagation=replace(project.propagation, backend="aperture_cavity_rom", direct_path_scale=1.0, cavity_scale=1.0),
        apertures=tuple(replace(item, coupling_scale=float(coupling_scale)) for item in project.apertures),
    )
    candidate = get_field_backend("aperture_cavity_rom").matrix(array, points, project=candidate_project, reference_scale=1.0)
    return float(np.linalg.norm(candidate - free) / max(np.linalg.norm(free), np.finfo(float).tiny))

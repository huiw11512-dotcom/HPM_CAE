"""V1.3 环境对象表格与中文界面适配。"""
from __future__ import annotations

from dataclasses import replace
from typing import Any

import pandas as pd

from hpm_platform.ui.project_model import (
    ApertureSpec,
    CAEProject,
    CavitySpec,
    MaterialSpec,
    ReflectingPlaneSpec,
)

MATERIAL_COLUMNS = [
    "material_id", "name", "relative_permittivity", "loss_tangent",
    "reflection_magnitude", "reflection_phase_deg", "roughness_proxy",
]
MATERIAL_HEADERS = ["材料标识", "材料名称", "相对介电常数", "损耗角正切", "反射幅度", "反射相位/°", "粗糙度代理"]

REFLECTOR_COLUMNS = ["object_id", "name", "enabled", "axis", "coordinate_lambda", "material_id"]
REFLECTOR_HEADERS = ["对象标识", "对象名称", "启用", "法向轴", "坐标/λ", "材料标识"]

APERTURE_COLUMNS = [
    "object_id", "name", "enabled", "center_x_lambda", "center_y_lambda", "center_z_lambda",
    "radius_lambda", "coupling_scale", "cavity_id",
]
APERTURE_HEADERS = ["对象标识", "对象名称", "启用", "中心x/λ", "中心y/λ", "中心z/λ", "半径/λ", "耦合系数", "关联腔体"]

CAVITY_COLUMNS = [
    "object_id", "name", "enabled", "center_x_lambda", "center_y_lambda", "center_z_lambda",
    "size_x_lambda", "size_y_lambda", "size_z_lambda", "quality_factor", "leakage_scale",
    "modes_x", "modes_y", "modes_z", "material_id",
]
CAVITY_HEADERS = [
    "对象标识", "对象名称", "启用", "中心x/λ", "中心y/λ", "中心z/λ",
    "尺寸x/λ", "尺寸y/λ", "尺寸z/λ", "品质因数代理", "泄漏系数",
    "x模态数", "y模态数", "z模态数", "材料标识",
]


def _frame(items: tuple[Any, ...], columns: list[str], headers: list[str]) -> pd.DataFrame:
    data = [{field: getattr(item, field) for field in columns} for item in items]
    frame = pd.DataFrame(data, columns=columns)
    frame.columns = headers
    return frame


def project_to_environment_frames(project: CAEProject) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    return (
        _frame(project.materials, MATERIAL_COLUMNS, MATERIAL_HEADERS),
        _frame(project.reflecting_planes, REFLECTOR_COLUMNS, REFLECTOR_HEADERS),
        _frame(project.apertures, APERTURE_COLUMNS, APERTURE_HEADERS),
        _frame(project.cavities, CAVITY_COLUMNS, CAVITY_HEADERS),
    )


def _records(frame: pd.DataFrame | list | None, columns: list[str], headers: list[str], id_field: str) -> list[dict[str, Any]]:
    if frame is None:
        return []
    data = frame.copy() if isinstance(frame, pd.DataFrame) else pd.DataFrame(frame)
    if list(data.columns) == headers:
        data.columns = columns
    elif len(data.columns) == len(columns):
        data.columns = columns
    else:
        data = data.reindex(columns=columns)
    data = data.dropna(how="all")
    output: list[dict[str, Any]] = []
    for record in data.to_dict(orient="records"):
        clean = {column: record.get(column) for column in columns}
        value = clean.get(id_field)
        if value is None or not str(value).strip():
            continue
        output.append(clean)
    return output


def apply_environment_frames(
    project: CAEProject,
    materials: pd.DataFrame | list,
    reflectors: pd.DataFrame | list,
    apertures: pd.DataFrame | list,
    cavities: pd.DataFrame | list,
) -> CAEProject:
    material_records = _records(materials, MATERIAL_COLUMNS, MATERIAL_HEADERS, "material_id")
    reflector_records = _records(reflectors, REFLECTOR_COLUMNS, REFLECTOR_HEADERS, "object_id")
    aperture_records = _records(apertures, APERTURE_COLUMNS, APERTURE_HEADERS, "object_id")
    cavity_records = _records(cavities, CAVITY_COLUMNS, CAVITY_HEADERS, "object_id")
    if not material_records:
        raise ValueError("材料库至少需要一条材料记录")
    return replace(
        project,
        materials=tuple(MaterialSpec(**item) for item in material_records),
        reflecting_planes=tuple(ReflectingPlaneSpec(**item) for item in reflector_records),
        apertures=tuple(ApertureSpec(**item) for item in aperture_records),
        cavities=tuple(CavitySpec(**item) for item in cavity_records),
    )


def add_material_row(frame: pd.DataFrame | list | None) -> pd.DataFrame:
    data = pd.DataFrame(frame, columns=MATERIAL_HEADERS).copy() if frame is not None else pd.DataFrame(columns=MATERIAL_HEADERS)
    index = len(data) + 1
    data.loc[len(data)] = [f"MAT-自定义{index:02d}", f"自定义材料{index}", 3.2, 0.04, 0.50, 165.0, 0.15]
    return data


def add_reflector_row(frame: pd.DataFrame | list | None) -> pd.DataFrame:
    data = pd.DataFrame(frame, columns=REFLECTOR_HEADERS).copy() if frame is not None else pd.DataFrame(columns=REFLECTOR_HEADERS)
    index = len(data) + 1
    data.loc[len(data)] = [f"REF-{index:03d}", f"反射面{index}", True, "y" if index % 2 == 0 else "x", 3.4 - 0.4 * index, "MAT-金属代理"]
    return data


def add_aperture_row(frame: pd.DataFrame | list | None) -> pd.DataFrame:
    data = pd.DataFrame(frame, columns=APERTURE_HEADERS).copy() if frame is not None else pd.DataFrame(columns=APERTURE_HEADERS)
    index = len(data) + 1
    data.loc[len(data)] = [f"APT-{index:03d}", f"等效孔缝{index}", True, 0.0, 0.0, 7.2, 0.10, 0.45, "CAV-001"]
    return data


def add_cavity_row(frame: pd.DataFrame | list | None) -> pd.DataFrame:
    data = pd.DataFrame(frame, columns=CAVITY_HEADERS).copy() if frame is not None else pd.DataFrame(columns=CAVITY_HEADERS)
    index = len(data) + 1
    data.loc[len(data)] = [
        f"CAV-{index:03d}", f"降阶腔体{index}", True, 0.0, 0.0, 8.0,
        3.0, 2.4, 1.6, 8.0, 0.45, 2, 2, 2, "MAT-损耗介质",
    ]
    return data


def environment_summary_markdown(project: CAEProject) -> str:
    return (
        f"**传播后端：** `{project.propagation.backend}`  \n"
        f"**材料：** {len(project.materials)} 种　"
        f"**启用反射面：** {len(project.active_reflectors)} 个　"
        f"**启用孔缝：** {len(project.active_apertures)} 个　"
        f"**启用腔体：** {len(project.active_cavities)} 个"
    )

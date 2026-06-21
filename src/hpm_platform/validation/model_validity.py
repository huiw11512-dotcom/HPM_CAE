"""V1.4 归一化传播模型适用性诊断。

该模块只检查本平台降阶模型的数值适用范围，不对现实设备、绝对功率、
作用距离或器件效应作出判断。所有长度均使用波长归一化表示。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

import numpy as np

from hpm_platform.ui.project_model import CAEProject


_STATUS_WEIGHT = {"适用": 1.0, "谨慎": 0.58, "越界": 0.0, "提示": 0.82}
_STATUS_SEVERITY = {"适用": 0, "提示": 1, "谨慎": 2, "越界": 3}


@dataclass(frozen=True)
class ValidityCheck:
    category: str
    item: str
    status: str
    value: str
    recommended: str
    explanation: str
    weight: float = 1.0

    def __post_init__(self) -> None:
        if self.status not in _STATUS_WEIGHT:
            raise ValueError(f"未知适用性状态：{self.status}")
        if not np.isfinite(float(self.weight)) or float(self.weight) <= 0:
            raise ValueError("适用性权重必须为正数")

    @property
    def score(self) -> float:
        return 100.0 * _STATUS_WEIGHT[self.status]

    def as_dict(self) -> dict[str, object]:
        return {
            "类别": self.category,
            "检查项": self.item,
            "状态": self.status,
            "当前值": self.value,
            "建议范围": self.recommended,
            "说明": self.explanation,
            "分项得分": round(self.score, 1),
        }


@dataclass(frozen=True)
class ValidityReport:
    backend_id: str
    backend_name: str
    score: float
    level: str
    checks: tuple[ValidityCheck, ...]
    summary: str

    @property
    def worst_status(self) -> str:
        return max(self.checks, key=lambda item: _STATUS_SEVERITY[item.status]).status

    def as_dict(self) -> dict[str, object]:
        return {
            "传播后端标识": self.backend_id,
            "传播后端": self.backend_name,
            "适用性得分": round(self.score, 2),
            "结论": self.level,
            "摘要": self.summary,
            "检查项": [item.as_dict() for item in self.checks],
        }


def _check(
    category: str,
    item: str,
    status: str,
    value: str,
    recommended: str,
    explanation: str,
    weight: float = 1.0,
) -> ValidityCheck:
    return ValidityCheck(category, item, status, value, recommended, explanation, weight)


def _aggregate(checks: Iterable[ValidityCheck]) -> tuple[float, str]:
    items = tuple(checks)
    numerator = sum(item.weight * _STATUS_WEIGHT[item.status] for item in items)
    denominator = sum(item.weight for item in items)
    score = 100.0 * numerator / max(denominator, 1e-12)
    worst = max((_STATUS_SEVERITY[item.status] for item in items), default=0)
    if worst >= 3 or score < 55:
        level = "存在越界项"
    elif worst >= 2 or score < 78:
        level = "可用于敏感性研究，需谨慎解释"
    elif score < 90:
        level = "适用于当前归一化研究场景"
    else:
        level = "适用性良好"
    return float(score), level


def _common_checks(project: CAEProject) -> list[ValidityCheck]:
    array = project.array
    aperture_x = (int(array.nx) - 1) * float(array.spacing_x_lambda)
    aperture_y = (int(array.ny) - 1) * float(array.spacing_y_lambda)
    aperture = max(aperture_x, aperture_y)
    z = float(project.plane.z_lambda)
    fraunhofer = 2.0 * aperture**2
    reactive_boundary = 0.62 * np.sqrt(max(aperture, 1e-9) ** 3)

    spacing = max(float(array.spacing_x_lambda), float(array.spacing_y_lambda))
    if spacing <= 0.5 + 1e-12:
        spacing_status = "适用"
    elif spacing <= 0.75:
        spacing_status = "谨慎"
    else:
        spacing_status = "越界"

    if z <= reactive_boundary:
        range_status = "谨慎"
        range_text = "位于近场强耦合区，必须使用逐点格林叠加，不能套用远场阵列因子。"
    elif z < fraunhofer:
        range_status = "适用"
        range_text = "位于辐射近场/菲涅耳区，当前逐点格林模型可用于归一化控场。"
    else:
        range_status = "适用"
        range_text = "位于远场判据之外，逐点格林模型仍可用，亦可与阵列因子交叉校验。"

    sample_step = max(
        float(project.plane.span_x_lambda), float(project.plane.span_y_lambda)
    ) / (int(project.plane.samples) - 1)
    if sample_step <= 0.12:
        grid_status = "适用"
    elif sample_step <= 0.22:
        grid_status = "提示"
    else:
        grid_status = "谨慎"

    return [
        _check(
            "阵列离散",
            "最大阵元间距",
            spacing_status,
            f"{spacing:.3f} λ",
            "≤0.50 λ（稳妥）；0.50–0.75 λ需检查栅瓣",
            "该项只评价空间采样与栅瓣风险，不评价实际阵元互耦。",
            1.4,
        ),
        _check(
            "观察区域",
            "阵列孔径与观察距离",
            range_status,
            f"孔径 {aperture:.2f} λ；z={z:.2f} λ；远场参考≈{fraunhofer:.2f} λ",
            "近场使用逐点格林叠加；远场可使用阵列因子交叉校验",
            range_text,
            1.2,
        ),
        _check(
            "数值采样",
            "观察面网格步长",
            grid_status,
            f"约 {sample_step:.3f} λ",
            "≤0.12 λ用于精细控场；≤0.22 λ用于快速预览",
            "过粗网格可能漏检局部峰值，尤其会高估保护区裕量。",
            1.1,
        ),
        _check(
            "模型边界",
            "归一化标量场假设",
            "提示",
            "标量复场、无量纲幅度",
            "仅用于算法与降阶模型研究",
            "未显式计算极化、矢量边界条件、宽带色散、绝对功率与真实器件效应。",
            1.6,
        ),
    ]


def _image_ray_checks(project: CAEProject) -> list[ValidityCheck]:
    reflectors = project.active_reflectors
    if not reflectors:
        return [
            _check(
                "镜像射线",
                "有效反射面",
                "越界",
                "0 个",
                "至少 1 个启用反射面",
                "未定义反射面时，镜像射线项退化为直达传播。",
                1.4,
            )
        ]
    checks: list[ValidityCheck] = []
    checks.append(
        _check(
            "镜像射线",
            "反射阶数与几何复杂度",
            "适用" if len(reflectors) <= 2 else "谨慎",
            f"一阶反射；{len(reflectors)} 个反射面",
            "1–2 个主要反射面用于快速敏感性研究",
            "当前后端不处理二阶反射、边缘绕射、遮挡和有限面边缘散射。",
            1.4,
        )
    )
    materials = {item.material_id: item for item in project.materials}
    for reflector in reflectors:
        material = materials[reflector.material_id]
        magnitude = float(material.reflection_magnitude)
        roughness = float(material.roughness_proxy)
        status = "适用" if magnitude <= 0.95 and roughness <= 0.5 else "谨慎"
        checks.append(
            _check(
                "镜像射线",
                f"材料代理：{material.name}",
                status,
                f"|Γ|={magnitude:.2f}；粗糙度代理={roughness:.2f}",
                "|Γ|≤0.95，粗糙度代理≤0.5用于稳定快速模型",
                "反射幅相为用户给定代理量，不是由完整Fresnel方程与极化自动求得。",
                0.9,
            )
        )
    return checks


def _cavity_checks(project: CAEProject) -> list[ValidityCheck]:
    apertures = project.active_apertures
    cavities = project.active_cavities
    checks: list[ValidityCheck] = []
    if not apertures or not cavities:
        checks.append(
            _check(
                "孔缝—腔体降阶",
                "对象连接",
                "越界",
                f"启用孔缝 {len(apertures)}；启用腔体 {len(cavities)}",
                "至少 1 个孔缝连接 1 个启用腔体",
                "缺少任一对象时降阶耦合通道无法形成。",
                1.5,
            )
        )
        return checks

    for aperture in apertures:
        radius = float(aperture.radius_lambda)
        if radius <= 0.20:
            status = "适用"
        elif radius <= 0.30:
            status = "谨慎"
        else:
            status = "越界"
        checks.append(
            _check(
                "孔缝—腔体降阶",
                f"孔缝电尺寸：{aperture.name}",
                status,
                f"半径 {radius:.3f} λ",
                "半径≤0.20 λ较稳妥；0.20–0.30 λ仅作趋势研究",
                "孔缝耦合为小孔近似代理，不包含真实缝隙厚度、形状与极化细节。",
                1.4,
            )
        )

    for cavity in cavities:
        q = float(cavity.quality_factor)
        sizes = np.array(
            [cavity.size_x_lambda, cavity.size_y_lambda, cavity.size_z_lambda], float
        )
        requested_modes = int(cavity.modes_x) * int(cavity.modes_y) * int(cavity.modes_z)
        retained = min(requested_modes, int(project.propagation.maximum_modes))
        q_status = "适用" if 2.0 <= q <= 30.0 else ("谨慎" if 1.0 <= q <= 60.0 else "越界")
        size_status = "适用" if float(np.min(sizes)) >= 0.75 else "谨慎"
        mode_status = "适用" if retained >= min(requested_modes, 8) else "谨慎"
        checks.extend(
            [
                _check(
                    "孔缝—腔体降阶",
                    f"品质因数代理：{cavity.name}",
                    q_status,
                    f"Q={q:.2f}",
                    "2≤Q≤30用于快速稳定研究",
                    "高Q情况下少量模态可能无法表示窄带尖峰与强局部驻波。",
                    1.0,
                ),
                _check(
                    "孔缝—腔体降阶",
                    f"腔体电尺寸：{cavity.name}",
                    size_status,
                    " × ".join(f"{item:.2f}λ" for item in sizes),
                    "每一维建议≥0.75 λ",
                    "尺寸过小时有限正弦模态基的物理解释会减弱。",
                    0.8,
                ),
                _check(
                    "孔缝—腔体降阶",
                    f"模态截断：{cavity.name}",
                    mode_status,
                    f"请求 {requested_modes}；保留 {retained}",
                    "至少保留主要低阶模态，并做截断敏感性分析",
                    "最终论文应报告模态数收敛性，不能只给单一截断结果。",
                    1.2,
                ),
            ]
        )
    return checks


def assess_model_validity(project: CAEProject, backend_id: str | None = None) -> ValidityReport:
    """Evaluate numerical applicability of the selected normalized backend."""
    backend = str(backend_id or project.propagation.backend)
    names = {
        "free_space_green": "自由空间标量格林",
        "image_ray": "镜像射线一阶多径",
        "aperture_cavity_rom": "孔缝—腔体降阶模型",
        "hybrid_scene": "混合场景后端",
    }
    if backend not in names:
        raise ValueError(f"未知传播后端：{backend}")

    checks = _common_checks(project)
    if backend in {"image_ray", "hybrid_scene"}:
        checks.extend(_image_ray_checks(project))
    if backend in {"aperture_cavity_rom", "hybrid_scene"}:
        checks.extend(_cavity_checks(project))
    if backend == "free_space_green":
        checks.append(
            _check(
                "自由空间",
                "环境散射忽略",
                "提示",
                "仅直达项",
                "作为算法基线或无遮挡场景参考",
                "该后端适合回归校验，但不能代表含反射面、孔缝或腔体的环境。",
                1.2,
            )
        )

    score, level = _aggregate(checks)
    n_warn = sum(item.status == "谨慎" for item in checks)
    n_bad = sum(item.status == "越界" for item in checks)
    summary = (
        f"共检查 {len(checks)} 项：{n_bad} 项越界、{n_warn} 项需谨慎。"
        "该评分只说明降阶模型在当前归一化参数下的数值适用性。"
    )
    return ValidityReport(backend, names[backend], score, level, tuple(checks), summary)

"""V1.3 插件式归一化场求解后端。

本模块只处理波长尺度几何、标量复场与无量纲代理量。它不是全波电磁
求解器，也不提供绝对功率、真实器件阈值、毁伤概率或作用距离。

后端统一返回 ``(采样点数, 阵元数)`` 的线性传播矩阵，因此现有区域赋形、
鲁棒优化和可视化代码可以在不改算法接口的前提下切换传播模型。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

import numpy as np

from hpm_platform.physics.array_geometry import RectangularArray


@dataclass(frozen=True)
class LinearBackendScenarioSet:
    target_matrices: tuple[np.ndarray, ...]
    outside_matrices: tuple[np.ndarray, ...]
    gain_vectors: tuple[np.ndarray, ...]
    shifts_m: tuple[np.ndarray, ...]


@dataclass(frozen=True)
class GroupedBackendScenarioSet:
    target_matrices: tuple[tuple[np.ndarray, ...], ...]
    outside_matrices: tuple[np.ndarray, ...]
    protected_matrices: tuple[tuple[np.ndarray, ...], ...]
    gain_vectors: tuple[np.ndarray, ...]
    shifts_m: tuple[np.ndarray, ...]


@dataclass(frozen=True)
class BackendSummary:
    backend_id: str
    backend_name: str
    active_reflectors: int
    active_apertures: int
    active_cavities: int
    direct_path_scale: float
    description: str

    def to_dict(self) -> dict[str, object]:
        return {
            "后端标识": self.backend_id,
            "后端名称": self.backend_name,
            "反射面数量": self.active_reflectors,
            "孔缝数量": self.active_apertures,
            "腔体数量": self.active_cavities,
            "直达分量系数": self.direct_path_scale,
            "适用说明": self.description,
        }


@runtime_checkable
class FieldBackend(Protocol):
    backend_id: str
    display_name: str
    description: str

    def matrix(
        self,
        array: RectangularArray,
        points_m: np.ndarray,
        *,
        project: Any,
        reference_scale: float = 1.0,
        element_gains: np.ndarray | None = None,
        chunk_size: int = 4096,
    ) -> np.ndarray: ...

    def focus_weights(
        self,
        array: RectangularArray,
        focus_point_m: np.ndarray,
        *,
        project: Any,
        rms_amplitude: float = 1.0,
    ) -> np.ndarray: ...

    def reference_scale(
        self,
        array: RectangularArray,
        focus_point_m: np.ndarray,
        *,
        project: Any,
    ) -> float: ...

    def summary(self, project: Any) -> BackendSummary: ...


def _complex_gains(array: RectangularArray, element_gains: np.ndarray | None) -> np.ndarray:
    if element_gains is None:
        return np.ones(array.n_elements, dtype=complex)
    gains = np.asarray(element_gains, complex).reshape(-1)
    if gains.size != array.n_elements:
        raise ValueError("阵元增益向量长度与阵列规模不一致")
    return gains


def _green_from_positions(
    array: RectangularArray,
    source_positions_m: np.ndarray,
    points_m: np.ndarray,
    *,
    reference_scale: float,
    element_gains: np.ndarray | None,
    chunk_size: int,
) -> np.ndarray:
    points = np.asarray(points_m, float).reshape(-1, 3)
    sources = np.asarray(source_positions_m, float).reshape(-1, 3)
    if sources.shape[0] != array.n_elements:
        raise ValueError("源位置数量与阵元数量不一致")
    if reference_scale <= 0 or chunk_size < 1:
        raise ValueError("参考尺度和分块长度必须为正")
    gains = _complex_gains(array, element_gains)
    output = np.empty((points.shape[0], array.n_elements), dtype=complex)
    for start in range(0, points.shape[0], int(chunk_size)):
        stop = min(start + int(chunk_size), points.shape[0])
        delta = points[start:stop, None, :] - sources[None, :, :]
        ranges = np.linalg.norm(delta, axis=2)
        ranges = np.maximum(ranges, array.wavelength_m * 1e-8)
        output[start:stop] = (
            np.exp(-1j * array.wave_number * ranges)
            / ranges
            / float(reference_scale)
        ) * gains[None, :]
    return output


def _active(project: Any, name: str) -> tuple[Any, ...]:
    value = getattr(project, name, ())
    return tuple(item for item in value if bool(getattr(item, "enabled", True)))


def _material_map(project: Any) -> dict[str, Any]:
    return {str(item.material_id): item for item in getattr(project, "materials", ())}


def _reflection_coefficient(material: Any, incidence_cosine: np.ndarray) -> np.ndarray:
    magnitude = float(getattr(material, "reflection_magnitude", 0.5))
    phase = np.deg2rad(float(getattr(material, "reflection_phase_deg", 180.0)))
    roughness = float(getattr(material, "roughness_proxy", 0.1))
    angular = np.clip(0.25 + 0.75 * np.abs(incidence_cosine), 0.05, 1.0)
    roughness_loss = np.exp(-roughness * (1.0 - np.abs(incidence_cosine)) ** 2)
    return magnitude * angular * roughness_loss * np.exp(1j * phase)


class _BackendBase:
    backend_id = "base"
    display_name = "基础后端"
    description = "基础接口"

    def focus_weights(
        self,
        array: RectangularArray,
        focus_point_m: np.ndarray,
        *,
        project: Any,
        rms_amplitude: float = 1.0,
    ) -> np.ndarray:
        if rms_amplitude < 0:
            raise ValueError("阵元均方根幅度不能为负")
        row = self.matrix(
            array,
            np.asarray(focus_point_m, float).reshape(1, 3),
            project=project,
            reference_scale=1.0,
        ).reshape(-1)
        if not np.any(np.abs(row) > np.finfo(float).tiny):
            raise RuntimeError("聚焦点传播矩阵退化")
        return float(rms_amplitude) * np.exp(-1j * np.angle(row))

    def reference_scale(
        self,
        array: RectangularArray,
        focus_point_m: np.ndarray,
        *,
        project: Any,
    ) -> float:
        point = np.asarray(focus_point_m, float).reshape(1, 3)
        matrix = self.matrix(array, point, project=project, reference_scale=1.0)
        weights = self.focus_weights(array, point.ravel(), project=project, rms_amplitude=1.0)
        value = float(np.abs(matrix @ weights).item())
        if not np.isfinite(value) or value <= 1e-12:
            raise RuntimeError("传播后端给出的参考场尺度无效")
        return value

    def summary(self, project: Any) -> BackendSummary:
        propagation = getattr(project, "propagation", None)
        return BackendSummary(
            backend_id=self.backend_id,
            backend_name=self.display_name,
            active_reflectors=len(_active(project, "reflecting_planes")),
            active_apertures=len(_active(project, "apertures")),
            active_cavities=len(_active(project, "cavities")),
            direct_path_scale=float(getattr(propagation, "direct_path_scale", 1.0)),
            description=self.description,
        )


class FreeSpaceGreenBackend(_BackendBase):
    backend_id = "free_space_green"
    display_name = "自由空间标量格林"
    description = "仅含直达标量格林函数，适合作为算法基线与回归校验。"

    def matrix(
        self,
        array: RectangularArray,
        points_m: np.ndarray,
        *,
        project: Any,
        reference_scale: float = 1.0,
        element_gains: np.ndarray | None = None,
        chunk_size: int = 4096,
    ) -> np.ndarray:
        return _green_from_positions(
            array,
            array.positions_m,
            points_m,
            reference_scale=reference_scale,
            element_gains=element_gains,
            chunk_size=chunk_size,
        )


class ImageRayBackend(_BackendBase):
    backend_id = "image_ray"
    display_name = "镜像射线一阶多径"
    description = "自由空间直达项叠加有限个平面的一阶镜像反射，适合快速多径敏感性研究。"

    @staticmethod
    def _reflected_component(
        array: RectangularArray,
        points_m: np.ndarray,
        *,
        project: Any,
        reference_scale: float,
        element_gains: np.ndarray | None,
        chunk_size: int,
    ) -> np.ndarray:
        points = np.asarray(points_m, float).reshape(-1, 3)
        materials = _material_map(project)
        output = np.zeros((points.shape[0], array.n_elements), dtype=complex)
        wavelength = array.wavelength_m
        sources = array.positions_m
        for plane in _active(project, "reflecting_planes"):
            axis_name = str(getattr(plane, "axis", "x")).lower()
            axis = {"x": 0, "y": 1, "z": 2}.get(axis_name)
            if axis is None:
                continue
            coordinate = float(getattr(plane, "coordinate_lambda", 0.0)) * wavelength
            images = sources.copy()
            images[:, axis] = 2.0 * coordinate - images[:, axis]
            material = materials.get(str(getattr(plane, "material_id", "")))
            if material is None:
                continue
            for start in range(0, points.shape[0], int(chunk_size)):
                stop = min(start + int(chunk_size), points.shape[0])
                sample = points[start:stop]
                delta = sample[:, None, :] - images[None, :, :]
                ranges = np.maximum(np.linalg.norm(delta, axis=2), wavelength * 1e-8)
                incidence_cosine = np.abs(delta[:, :, axis]) / ranges
                coefficient = _reflection_coefficient(material, incidence_cosine)
                same_side = (
                    (sample[:, None, axis] - coordinate)
                    * (sources[None, :, axis] - coordinate)
                    >= 0.0
                )
                coefficient = coefficient * same_side
                output[start:stop] += (
                    coefficient
                    * np.exp(-1j * array.wave_number * ranges)
                    / ranges
                    / float(reference_scale)
                )
        output *= _complex_gains(array, element_gains)[None, :]
        return output

    def matrix(
        self,
        array: RectangularArray,
        points_m: np.ndarray,
        *,
        project: Any,
        reference_scale: float = 1.0,
        element_gains: np.ndarray | None = None,
        chunk_size: int = 4096,
    ) -> np.ndarray:
        propagation = getattr(project, "propagation", None)
        direct_scale = float(getattr(propagation, "direct_path_scale", 1.0))
        reflection_scale = float(getattr(propagation, "reflection_scale", 1.0))
        direct = _green_from_positions(
            array,
            array.positions_m,
            points_m,
            reference_scale=reference_scale,
            element_gains=element_gains,
            chunk_size=chunk_size,
        )
        reflected = self._reflected_component(
            array,
            points_m,
            project=project,
            reference_scale=reference_scale,
            element_gains=element_gains,
            chunk_size=chunk_size,
        )
        return direct_scale * direct + reflection_scale * reflected


class ApertureCavityROMBackend(_BackendBase):
    backend_id = "aperture_cavity_rom"
    display_name = "孔缝—腔体降阶模型"
    description = "以孔缝耦合代理和有限模态基展开描述腔体内复场，只用于快速归一化算法研究。"

    @staticmethod
    def _rom_component(
        array: RectangularArray,
        points_m: np.ndarray,
        *,
        project: Any,
        reference_scale: float,
        element_gains: np.ndarray | None,
        chunk_size: int,
    ) -> np.ndarray:
        points = np.asarray(points_m, float).reshape(-1, 3)
        output = np.zeros((points.shape[0], array.n_elements), dtype=complex)
        wavelength = array.wavelength_m
        cavities = {str(item.object_id): item for item in _active(project, "cavities")}
        mode_limit = int(getattr(getattr(project, "propagation", None), "maximum_modes", 9))
        for aperture in _active(project, "apertures"):
            cavity = cavities.get(str(getattr(aperture, "cavity_id", "")))
            if cavity is None:
                continue
            center = wavelength * np.array(
                [
                    float(aperture.center_x_lambda),
                    float(aperture.center_y_lambda),
                    float(aperture.center_z_lambda),
                ],
                dtype=float,
            )
            incident = _green_from_positions(
                array,
                array.positions_m,
                center.reshape(1, 3),
                reference_scale=reference_scale,
                element_gains=element_gains,
                chunk_size=chunk_size,
            ).reshape(-1)

            cavity_center = wavelength * np.array(
                [float(cavity.center_x_lambda), float(cavity.center_y_lambda), float(cavity.center_z_lambda)],
                dtype=float,
            )
            size = wavelength * np.array(
                [float(cavity.size_x_lambda), float(cavity.size_y_lambda), float(cavity.size_z_lambda)],
                dtype=float,
            )
            local = (points - cavity_center[None, :]) / size[None, :] + 0.5
            inside = np.all((local >= 0.0) & (local <= 1.0), axis=1)
            if not np.any(inside):
                continue
            radius = float(aperture.radius_lambda)
            ka = 2.0 * np.pi * radius
            aperture_factor = (ka**3) / (1.0 + ka**3)
            coupling = float(aperture.coupling_scale) * aperture_factor
            quality = float(cavity.quality_factor)
            leakage = float(cavity.leakage_scale)
            max_mx = int(cavity.modes_x)
            max_my = int(cavity.modes_y)
            max_mz = int(cavity.modes_z)
            mode_counter = 0
            rom_value = np.zeros(points.shape[0], dtype=complex)
            for mx in range(1, max_mx + 1):
                for my in range(1, max_my + 1):
                    for mz in range(1, max_mz + 1):
                        if mode_counter >= mode_limit:
                            break
                        mode_counter += 1
                        normalized_frequency = 0.5 * np.sqrt(
                            (mx / float(cavity.size_x_lambda)) ** 2
                            + (my / float(cavity.size_y_lambda)) ** 2
                            + (mz / float(cavity.size_z_lambda)) ** 2
                        )
                        detuning = normalized_frequency - 1.0
                        transfer = 1.0 / (1.0 + 1j * quality * detuning)
                        basis = (
                            np.sin(np.pi * mx * local[:, 0])
                            * np.sin(np.pi * my * local[:, 1])
                            * np.sin(np.pi * mz * local[:, 2])
                        )
                        rom_value += transfer * basis
                    if mode_counter >= mode_limit:
                        break
                if mode_counter >= mode_limit:
                    break
            if mode_counter:
                rom_value /= np.sqrt(float(mode_counter))
            rom_value *= inside * coupling * leakage
            output += rom_value[:, None] * incident[None, :]
        return output

    def matrix(
        self,
        array: RectangularArray,
        points_m: np.ndarray,
        *,
        project: Any,
        reference_scale: float = 1.0,
        element_gains: np.ndarray | None = None,
        chunk_size: int = 4096,
    ) -> np.ndarray:
        propagation = getattr(project, "propagation", None)
        direct_scale = float(getattr(propagation, "direct_path_scale", 0.15))
        rom_scale = float(getattr(propagation, "cavity_scale", 1.0))
        direct = _green_from_positions(
            array,
            array.positions_m,
            points_m,
            reference_scale=reference_scale,
            element_gains=element_gains,
            chunk_size=chunk_size,
        )
        rom = self._rom_component(
            array,
            points_m,
            project=project,
            reference_scale=reference_scale,
            element_gains=element_gains,
            chunk_size=chunk_size,
        )
        return direct_scale * direct + rom_scale * rom


class HybridSceneBackend(_BackendBase):
    backend_id = "hybrid_scene"
    display_name = "混合场景后端"
    description = "直达项、一阶镜像反射与孔缝—腔体降阶分量的统一线性叠加。"

    def matrix(
        self,
        array: RectangularArray,
        points_m: np.ndarray,
        *,
        project: Any,
        reference_scale: float = 1.0,
        element_gains: np.ndarray | None = None,
        chunk_size: int = 4096,
    ) -> np.ndarray:
        propagation = getattr(project, "propagation", None)
        direct_scale = float(getattr(propagation, "direct_path_scale", 1.0))
        reflection_scale = float(getattr(propagation, "reflection_scale", 1.0))
        cavity_scale = float(getattr(propagation, "cavity_scale", 1.0))
        direct = _green_from_positions(
            array,
            array.positions_m,
            points_m,
            reference_scale=reference_scale,
            element_gains=element_gains,
            chunk_size=chunk_size,
        )
        reflected = ImageRayBackend._reflected_component(
            array,
            points_m,
            project=project,
            reference_scale=reference_scale,
            element_gains=element_gains,
            chunk_size=chunk_size,
        )
        rom = ApertureCavityROMBackend._rom_component(
            array,
            points_m,
            project=project,
            reference_scale=reference_scale,
            element_gains=element_gains,
            chunk_size=chunk_size,
        )
        return direct_scale * direct + reflection_scale * reflected + cavity_scale * rom


_BACKENDS: dict[str, FieldBackend] = {}


def register_field_backend(backend: FieldBackend, *, replace: bool = False) -> None:
    if not isinstance(backend, FieldBackend):
        raise TypeError("后端对象未实现 FieldBackend 协议")
    backend_id = str(backend.backend_id).strip()
    if not backend_id:
        raise ValueError("后端标识不能为空")
    if backend_id in _BACKENDS and not replace:
        raise ValueError(f"场求解后端已注册：{backend_id}")
    _BACKENDS[backend_id] = backend


def get_field_backend(backend_id: str) -> FieldBackend:
    key = str(backend_id)
    try:
        return _BACKENDS[key]
    except KeyError as exc:
        raise KeyError(f"未知场求解后端：{backend_id}；可用后端：{', '.join(_BACKENDS)}") from exc


def available_field_backends() -> tuple[FieldBackend, ...]:
    return tuple(_BACKENDS[key] for key in sorted(_BACKENDS))


def backend_choices() -> tuple[tuple[str, str], ...]:
    return tuple((backend.display_name, backend.backend_id) for backend in available_field_backends())


def sample_backend_scenarios(
    backend: FieldBackend,
    array: RectangularArray,
    target_points_m: np.ndarray,
    outside_points_m: np.ndarray,
    *,
    project: Any,
    reference_scale: float,
    n_scenarios: int,
    gain_std_fraction: float,
    phase_std_deg: float,
    registration_jitter_std_lambda: float,
    seed: int,
    include_nominal: bool = True,
) -> LinearBackendScenarioSet:
    if int(n_scenarios) < 1:
        raise ValueError("鲁棒场景数必须为正")
    target = np.asarray(target_points_m, float).reshape(-1, 3)
    outside = np.asarray(outside_points_m, float).reshape(-1, 3)
    rng = np.random.default_rng(int(seed))
    target_matrices: list[np.ndarray] = []
    outside_matrices: list[np.ndarray] = []
    gain_vectors: list[np.ndarray] = []
    shifts: list[np.ndarray] = []
    for index in range(int(n_scenarios)):
        nominal = include_nominal and index == 0
        if nominal:
            gains = np.ones(array.n_elements, dtype=complex)
            shift = np.zeros(3, dtype=float)
        else:
            amplitude = 1.0 + rng.normal(0.0, float(gain_std_fraction), size=array.n_elements)
            amplitude = np.clip(amplitude, 0.05, None)
            phase = rng.normal(0.0, np.deg2rad(float(phase_std_deg)), size=array.n_elements)
            gains = amplitude * np.exp(1j * phase)
            shift = rng.normal(0.0, float(registration_jitter_std_lambda) * array.wavelength_m, size=3)
            shift[2] = 0.0
        target_matrices.append(
            backend.matrix(array, target + shift, project=project, reference_scale=reference_scale, element_gains=gains)
        )
        outside_matrices.append(
            backend.matrix(array, outside + shift, project=project, reference_scale=reference_scale, element_gains=gains)
        )
        gain_vectors.append(gains)
        shifts.append(shift)
    return LinearBackendScenarioSet(
        tuple(target_matrices), tuple(outside_matrices), tuple(gain_vectors), tuple(shifts)
    )


def sample_grouped_backend_scenarios(
    backend: FieldBackend,
    array: RectangularArray,
    target_point_groups_m: tuple[np.ndarray, ...],
    outside_points_m: np.ndarray,
    protected_point_groups_m: tuple[np.ndarray, ...],
    *,
    project: Any,
    reference_scale: float,
    n_scenarios: int,
    gain_std_fraction: float,
    phase_std_deg: float,
    registration_jitter_std_lambda: float,
    seed: int,
    include_nominal: bool = True,
) -> GroupedBackendScenarioSet:
    if int(n_scenarios) < 1:
        raise ValueError("鲁棒场景数必须为正")
    targets = tuple(np.asarray(item, float).reshape(-1, 3) for item in target_point_groups_m)
    protected = tuple(np.asarray(item, float).reshape(-1, 3) for item in protected_point_groups_m)
    outside = np.asarray(outside_points_m, float).reshape(-1, 3)
    rng = np.random.default_rng(int(seed))
    target_scenarios: list[tuple[np.ndarray, ...]] = []
    outside_scenarios: list[np.ndarray] = []
    protected_scenarios: list[tuple[np.ndarray, ...]] = []
    gain_vectors: list[np.ndarray] = []
    shifts: list[np.ndarray] = []
    for index in range(int(n_scenarios)):
        nominal = include_nominal and index == 0
        if nominal:
            gains = np.ones(array.n_elements, dtype=complex)
            shift = np.zeros(3, dtype=float)
        else:
            amplitude = 1.0 + rng.normal(0.0, float(gain_std_fraction), size=array.n_elements)
            amplitude = np.clip(amplitude, 0.05, None)
            phase = rng.normal(0.0, np.deg2rad(float(phase_std_deg)), size=array.n_elements)
            gains = amplitude * np.exp(1j * phase)
            shift = rng.normal(0.0, float(registration_jitter_std_lambda) * array.wavelength_m, size=3)
            shift[2] = 0.0
        target_scenarios.append(
            tuple(
                backend.matrix(array, group + shift, project=project, reference_scale=reference_scale, element_gains=gains)
                for group in targets
            )
        )
        outside_scenarios.append(
            backend.matrix(array, outside + shift, project=project, reference_scale=reference_scale, element_gains=gains)
        )
        protected_scenarios.append(
            tuple(
                backend.matrix(array, group + shift, project=project, reference_scale=reference_scale, element_gains=gains)
                for group in protected
            )
        )
        gain_vectors.append(gains)
        shifts.append(shift)
    return GroupedBackendScenarioSet(
        tuple(target_scenarios), tuple(outside_scenarios), tuple(protected_scenarios),
        tuple(gain_vectors), tuple(shifts)
    )


for _backend in (
    FreeSpaceGreenBackend(),
    ImageRayBackend(),
    ApertureCavityROMBackend(),
    HybridSceneBackend(),
):
    register_field_backend(_backend)

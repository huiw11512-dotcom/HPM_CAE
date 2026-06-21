"""HPM-CAE V1.4 中文工程配置模型。

The public workbench deliberately operates with wavelength-scaled geometry,
normalized complex fields, and dimensionless response proxies.  It does not
expose absolute source power, hardware vulnerability thresholds, or real-world
engagement-distance calculations.

V1.4 在 V1.3 插件式传播模型基础上，新增插件式传播后端、材料库、反射面、
孔缝与腔体降阶对象，并保留旧工程的显式迁移路径。
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
import re
from typing import Any, Mapping

import numpy as np
import yaml

from hpm_platform.physics.array_geometry import RectangularArray

SCHEMA_VERSION = "1.4"
LEGACY_SCHEMAS = {"1.3", "1.2", "1.1", "1.0", "0.9"}
MODEL_SCOPE = (
    "波长尺度归一化标量场与阵列算法研究模型；绝对功率仅作为实测标定元数据，"
    "不输出器件阈值、毁伤概率或现实作用距离"
)


def _finite_positive(value: float, name: str) -> None:
    if not isinstance(value, (int, float)) or not np.isfinite(value) or value <= 0:
        raise ValueError(f"{name} must be finite and positive")


def _finite_nonnegative(value: float, name: str) -> None:
    if not isinstance(value, (int, float)) or not np.isfinite(value) or value < 0:
        raise ValueError(f"{name} must be finite and non-negative")


def _nonempty(value: str, name: str) -> None:
    if not str(value).strip():
        raise ValueError(f"{name} cannot be empty")


@dataclass(frozen=True)
class ArraySpec:
    nx: int = 8
    ny: int = 8
    frequency_ghz: float = 10.0
    spacing_x_lambda: float = 0.5
    spacing_y_lambda: float = 0.5

    def __post_init__(self) -> None:
        if not 2 <= int(self.nx) <= 32 or not 2 <= int(self.ny) <= 32:
            raise ValueError("nx and ny must be between 2 and 32 for the UI solver")
        _finite_positive(float(self.frequency_ghz), "frequency_ghz")
        _finite_positive(float(self.spacing_x_lambda), "spacing_x_lambda")
        _finite_positive(float(self.spacing_y_lambda), "spacing_y_lambda")
        if self.spacing_x_lambda > 1.5 or self.spacing_y_lambda > 1.5:
            raise ValueError("spacing in the UI research mode must not exceed 1.5 lambda")

    def build_array(self) -> RectangularArray:
        frequency_hz = float(self.frequency_ghz) * 1e9
        base = RectangularArray(nx=int(self.nx), ny=int(self.ny), frequency_hz=frequency_hz)
        return RectangularArray(
            nx=int(self.nx),
            ny=int(self.ny),
            frequency_hz=frequency_hz,
            dx_m=float(self.spacing_x_lambda) * base.wavelength_m,
            dy_m=float(self.spacing_y_lambda) * base.wavelength_m,
        )


@dataclass(frozen=True)
class ObservationPlaneSpec:
    z_lambda: float = 8.0
    span_x_lambda: float = 8.0
    span_y_lambda: float = 8.0
    samples: int = 81

    def __post_init__(self) -> None:
        _finite_positive(float(self.z_lambda), "z_lambda")
        _finite_positive(float(self.span_x_lambda), "span_x_lambda")
        _finite_positive(float(self.span_y_lambda), "span_y_lambda")
        if not 31 <= int(self.samples) <= 181:
            raise ValueError("samples must be between 31 and 181")
        if int(self.samples) % 2 == 0:
            raise ValueError("samples must be odd so the plane has a center sample")



@dataclass(frozen=True)
class MaterialSpec:
    """归一化材料代理；仅为快速反射与降阶模型提供参数。"""

    material_id: str = "MAT-金属代理"
    name: str = "金属反射代理"
    relative_permittivity: float = 4.0
    loss_tangent: float = 0.02
    reflection_magnitude: float = 0.82
    reflection_phase_deg: float = 180.0
    roughness_proxy: float = 0.08

    def __post_init__(self) -> None:
        _nonempty(self.material_id, "material_id")
        _nonempty(self.name, "material name")
        _finite_positive(float(self.relative_permittivity), "relative_permittivity")
        _finite_nonnegative(float(self.loss_tangent), "loss_tangent")
        if not 0.0 <= float(self.reflection_magnitude) <= 1.0:
            raise ValueError("reflection_magnitude must lie in [0, 1]")
        if not -360.0 <= float(self.reflection_phase_deg) <= 360.0:
            raise ValueError("reflection_phase_deg must lie in [-360, 360]")
        if not 0.0 <= float(self.roughness_proxy) <= 3.0:
            raise ValueError("roughness_proxy must lie in [0, 3]")


@dataclass(frozen=True)
class ReflectingPlaneSpec:
    """无限平面的一阶镜像反射代理。"""

    object_id: str = "REF-001"
    name: str = "侧向反射面"
    enabled: bool = False
    axis: str = "x"
    coordinate_lambda: float = -3.6
    material_id: str = "MAT-金属代理"

    AXES = ("x", "y", "z")

    def __post_init__(self) -> None:
        _nonempty(self.object_id, "reflector object_id")
        _nonempty(self.name, "reflector name")
        if str(self.axis).lower() not in self.AXES:
            raise ValueError(f"reflector axis must be one of {self.AXES}")
        if not np.isfinite(float(self.coordinate_lambda)):
            raise ValueError("coordinate_lambda must be finite")
        _nonempty(self.material_id, "reflector material_id")


@dataclass(frozen=True)
class CavitySpec:
    """矩形腔体的有限模态降阶代理。"""

    object_id: str = "CAV-001"
    name: str = "电子舱降阶腔体"
    enabled: bool = False
    center_x_lambda: float = 0.0
    center_y_lambda: float = 0.0
    center_z_lambda: float = 8.0
    size_x_lambda: float = 3.0
    size_y_lambda: float = 2.4
    size_z_lambda: float = 1.6
    quality_factor: float = 8.0
    leakage_scale: float = 0.45
    modes_x: int = 2
    modes_y: int = 2
    modes_z: int = 2
    material_id: str = "MAT-损耗介质"

    def __post_init__(self) -> None:
        _nonempty(self.object_id, "cavity object_id")
        _nonempty(self.name, "cavity name")
        for value, label in (
            (self.size_x_lambda, "size_x_lambda"),
            (self.size_y_lambda, "size_y_lambda"),
            (self.size_z_lambda, "size_z_lambda"),
            (self.quality_factor, "quality_factor"),
        ):
            _finite_positive(float(value), label)
        if not 0.0 <= float(self.leakage_scale) <= 2.0:
            raise ValueError("leakage_scale must lie in [0, 2]")
        for value, label in ((self.modes_x, "modes_x"), (self.modes_y, "modes_y"), (self.modes_z, "modes_z")):
            if not 1 <= int(value) <= 6:
                raise ValueError(f"{label} must lie in [1, 6]")
        _nonempty(self.material_id, "cavity material_id")


@dataclass(frozen=True)
class ApertureSpec:
    """孔缝耦合的无量纲代理，并通过 cavity_id 连接腔体。"""

    object_id: str = "APT-001"
    name: str = "等效圆孔"
    enabled: bool = False
    center_x_lambda: float = 0.0
    center_y_lambda: float = 0.0
    center_z_lambda: float = 7.2
    radius_lambda: float = 0.12
    coupling_scale: float = 0.55
    cavity_id: str = "CAV-001"

    def __post_init__(self) -> None:
        _nonempty(self.object_id, "aperture object_id")
        _nonempty(self.name, "aperture name")
        _finite_positive(float(self.radius_lambda), "radius_lambda")
        if not 0.005 <= float(self.radius_lambda) <= 0.5:
            raise ValueError("aperture radius_lambda must lie in [0.005, 0.5]")
        if not 0.0 <= float(self.coupling_scale) <= 3.0:
            raise ValueError("coupling_scale must lie in [0, 3]")
        _nonempty(self.cavity_id, "aperture cavity_id")


@dataclass(frozen=True)
class PropagationSpec:
    """插件式传播后端设置。"""

    backend: str = "free_space_green"
    direct_path_scale: float = 1.0
    reflection_scale: float = 1.0
    cavity_scale: float = 1.0
    maximum_modes: int = 8
    comparison_backends: tuple[str, ...] = (
        "free_space_green",
        "image_ray",
        "aperture_cavity_rom",
        "hybrid_scene",
    )

    BACKENDS = (
        "free_space_green",
        "image_ray",
        "aperture_cavity_rom",
        "hybrid_scene",
    )

    def __post_init__(self) -> None:
        if self.backend not in self.BACKENDS:
            raise ValueError(f"propagation backend must be one of {self.BACKENDS}")
        for value, label in (
            (self.direct_path_scale, "direct_path_scale"),
            (self.reflection_scale, "reflection_scale"),
            (self.cavity_scale, "cavity_scale"),
        ):
            if not 0.0 <= float(value) <= 5.0:
                raise ValueError(f"{label} must lie in [0, 5]")
        if not 1 <= int(self.maximum_modes) <= 64:
            raise ValueError("maximum_modes must lie in [1, 64]")
        if len(set(self.comparison_backends)) != len(self.comparison_backends):
            raise ValueError("comparison_backends must be unique")
        if any(item not in self.BACKENDS for item in self.comparison_backends):
            raise ValueError("comparison_backends contains an unknown backend")


@dataclass(frozen=True)
class TargetRegionSpec:
    center_x_lambda: float = 0.8
    center_y_lambda: float = -0.6
    semi_major_lambda: float = 1.10
    semi_minor_lambda: float = 0.65
    rotation_deg: float = 25.0
    guard_scale: float = 1.45
    object_id: str = "TGT-001"
    name: str = "目标区1"
    enabled: bool = True
    amplitude_scale: float = 1.0
    priority: float = 1.0
    tolerance_percent: float = 10.0

    def __post_init__(self) -> None:
        _nonempty(self.object_id, "target object_id")
        _nonempty(self.name, "target name")
        _finite_positive(float(self.semi_major_lambda), "semi_major_lambda")
        _finite_positive(float(self.semi_minor_lambda), "semi_minor_lambda")
        _finite_positive(float(self.amplitude_scale), "amplitude_scale")
        _finite_positive(float(self.priority), "target priority")
        _finite_positive(float(self.tolerance_percent), "tolerance_percent")
        if not 1.05 <= float(self.guard_scale) <= 3.0:
            raise ValueError("guard_scale must be in [1.05, 3.0]")
        if not -180.0 <= float(self.rotation_deg) <= 180.0:
            raise ValueError("rotation_deg must be in [-180, 180]")
        if float(self.amplitude_scale) > 3.0:
            raise ValueError("amplitude_scale must not exceed 3.0 in normalized mode")
        if float(self.priority) > 20.0:
            raise ValueError("target priority must not exceed 20")
        if not 2.0 <= float(self.tolerance_percent) <= 50.0:
            raise ValueError("tolerance_percent must be in [2, 50]")


@dataclass(frozen=True)
class ProtectedZoneSpec:
    enabled: bool = True
    center_x_lambda: float = -2.5
    center_y_lambda: float = 2.1
    radius_lambda: float = 0.70
    object_id: str = "PRT-001"
    name: str = "保护区1"
    priority: float = 1.0
    max_amplitude_scale: float = 0.25

    def __post_init__(self) -> None:
        _nonempty(self.object_id, "protected-zone object_id")
        _nonempty(self.name, "protected-zone name")
        _finite_positive(float(self.radius_lambda), "radius_lambda")
        _finite_positive(float(self.priority), "priority")
        _finite_positive(float(self.max_amplitude_scale), "max_amplitude_scale")
        if float(self.priority) > 10.0:
            raise ValueError("protected-zone priority must not exceed 10")
        if not 0.02 <= float(self.max_amplitude_scale) <= 1.0:
            raise ValueError("max_amplitude_scale must be in [0.02, 1.0]")


@dataclass(frozen=True)
class InterfererSpec:
    """Normalized far-field emitter plus one coherent echo for live sensing."""

    object_id: str = "INT-001"
    name: str = "相干辐射源1"
    enabled: bool = True
    theta_deg: float = 18.4
    phi_deg: float = -7.6
    relative_power_db: float = 0.0
    echo_enabled: bool = True
    echo_theta_deg: float = 35.7
    echo_phi_deg: float = 11.8
    echo_relative_power_db: float = -3.0
    echo_phase_deg: float = 55.0
    prior_theta_deg: float = 20.0
    prior_phi_deg: float = -5.0
    uncertainty_theta_deg: float = 2.0
    uncertainty_phi_deg: float = 2.5

    def __post_init__(self) -> None:
        _nonempty(self.object_id, "interferer object_id")
        _nonempty(self.name, "interferer name")
        for label, theta in (("theta_deg", self.theta_deg), ("echo_theta_deg", self.echo_theta_deg), ("prior_theta_deg", self.prior_theta_deg)):
            if not 0.0 <= float(theta) <= 90.0:
                raise ValueError(f"{label} must lie in [0, 90]")
        for label, phi in (("phi_deg", self.phi_deg), ("echo_phi_deg", self.echo_phi_deg), ("prior_phi_deg", self.prior_phi_deg)):
            if not -180.0 <= float(phi) <= 180.0:
                raise ValueError(f"{label} must lie in [-180, 180]")
        _finite_positive(float(self.uncertainty_theta_deg), "uncertainty_theta_deg")
        _finite_positive(float(self.uncertainty_phi_deg), "uncertainty_phi_deg")
        if self.uncertainty_theta_deg > 30 or self.uncertainty_phi_deg > 45:
            raise ValueError("interferer uncertainty is too broad for the interactive solver")


@dataclass(frozen=True)
class PerceptionSpec:
    method: str = "PAWR-MUSIC"
    snr_db: float = -8.0
    snapshots: int = 128
    subarray_nx: int = 6
    subarray_ny: int = 6
    scan_theta_min_deg: float = 5.0
    scan_theta_max_deg: float = 50.0
    scan_phi_min_deg: float = -25.0
    scan_phi_max_deg: float = 25.0
    scan_step_deg: float = 0.5
    diagonal_loading: float = 1e-3
    sensor_gain_std_db: float = 0.15
    sensor_phase_std_deg: float = 4.0
    fault_count: int = 2
    prior_sigma_deg: float = 5.0
    prior_strength: float = 0.002

    METHODS = ("FBSS-MUSIC", "PAWR-MUSIC", "FBSS-ESPRIT")

    def __post_init__(self) -> None:
        if self.method not in self.METHODS:
            raise ValueError(f"perception method must be one of {self.METHODS}")
        if not 16 <= int(self.snapshots) <= 4096:
            raise ValueError("perception snapshots must be in [16, 4096]")
        if not 2 <= int(self.subarray_nx) <= 31 or not 2 <= int(self.subarray_ny) <= 31:
            raise ValueError("perception subarray dimensions must be in [2, 31]")
        if not 0.1 <= float(self.scan_step_deg) <= 5.0:
            raise ValueError("scan_step_deg must be in [0.1, 5]")
        if not 0.0 <= float(self.scan_theta_min_deg) < float(self.scan_theta_max_deg) <= 90.0:
            raise ValueError("invalid theta scan interval")
        if not -180.0 <= float(self.scan_phi_min_deg) < float(self.scan_phi_max_deg) <= 180.0:
            raise ValueError("invalid phi scan interval")
        _finite_nonnegative(float(self.diagonal_loading), "diagonal_loading")
        _finite_nonnegative(float(self.sensor_gain_std_db), "sensor_gain_std_db")
        _finite_nonnegative(float(self.sensor_phase_std_deg), "sensor_phase_std_deg")
        if not 0 <= int(self.fault_count) <= 16:
            raise ValueError("fault_count must be in [0, 16]")
        _finite_positive(float(self.prior_sigma_deg), "prior_sigma_deg")
        _finite_nonnegative(float(self.prior_strength), "prior_strength")


@dataclass(frozen=True)
class ProtectionSpec:
    method: str = "CR-HybridNull"
    desired_theta_deg: float = 18.0
    desired_phi_deg: float = 12.0
    desired_power_db: float = 0.0
    interferer_power_db: float = 32.0
    noise_power: float = 1.0
    loading_factor: float = 0.03
    sector_scale: float = 2.2
    grid_step_deg: float = 1.0
    energy_threshold: float = 0.995
    max_rank: int = 10
    soft_strength: float = 0.65
    wng_floor_db: float = 5.0

    METHODS = ("DL-MVDR", "Point-LCMV", "Sector-MVDR", "CR-HybridNull")

    def __post_init__(self) -> None:
        if self.method not in self.METHODS:
            raise ValueError(f"protection method must be one of {self.METHODS}")
        if not 0.0 <= float(self.desired_theta_deg) <= 90.0:
            raise ValueError("desired_theta_deg must lie in [0, 90]")
        if not -180.0 <= float(self.desired_phi_deg) <= 180.0:
            raise ValueError("desired_phi_deg must lie in [-180, 180]")
        _finite_positive(float(self.noise_power), "noise_power")
        _finite_nonnegative(float(self.loading_factor), "loading_factor")
        _finite_positive(float(self.sector_scale), "sector_scale")
        if not 0.2 <= float(self.grid_step_deg) <= 5.0:
            raise ValueError("protection grid_step_deg must be in [0.2, 5]")
        if not 0.5 <= float(self.energy_threshold) <= 1.0:
            raise ValueError("energy_threshold must lie in [0.5, 1]")
        if not 1 <= int(self.max_rank) <= 32:
            raise ValueError("max_rank must be in [1, 32]")
        _finite_nonnegative(float(self.soft_strength), "soft_strength")


@dataclass(frozen=True)
class SolverSpec:
    method: str = "Robust-PGMS"
    target_amplitude: float = 0.47
    outside_penalty: float = 1.20
    outside_hinge_amplitude: float = 0.14
    outside_peak_limit_db: float = -2.0
    protected_penalty: float = 1.2
    fairness_penalty: float = 1.2
    tail_penalty: float = 0.05
    tail_fraction: float = 0.15
    ridge: float = 1e-3
    iterations: int = 360
    learning_rate: float = 0.025
    rms_limit: float = 0.80
    peak_limit: float = 1.00
    target_samples: int = 280
    outside_samples: int = 720
    uncertainty_scenarios: int = 5
    gain_std_percent: float = 3.0
    phase_std_deg: float = 5.0
    registration_jitter_lambda: float = 0.08
    pa_enabled: bool = True
    dpd_enabled: bool = True
    pa_saturation_amplitude: float = 1.00
    pa_smoothness: float = 3.0
    pa_maximum_phase_deg: float = 12.0
    pareto_points: int = 7

    METHODS = ("Point-Focus", "Region-LS", "Nominal-PGMS", "Robust-PGMS", "Constrained-MO-PGMS")

    def __post_init__(self) -> None:
        if self.method not in self.METHODS:
            raise ValueError(f"method must be one of {self.METHODS}")
        _finite_positive(float(self.target_amplitude), "target_amplitude")
        _finite_nonnegative(float(self.outside_penalty), "outside_penalty")
        _finite_nonnegative(float(self.outside_hinge_amplitude), "outside_hinge_amplitude")
        if not np.isfinite(float(self.outside_peak_limit_db)) or not -60.0 <= float(self.outside_peak_limit_db) <= 6.0:
            raise ValueError("outside_peak_limit_db must lie in [-60, 6]")
        _finite_nonnegative(float(self.protected_penalty), "protected_penalty")
        _finite_nonnegative(float(self.fairness_penalty), "fairness_penalty")
        _finite_nonnegative(float(self.tail_penalty), "tail_penalty")
        if not 0.01 <= float(self.tail_fraction) <= 0.5:
            raise ValueError("tail_fraction must be in [0.01, 0.5]")
        _finite_nonnegative(float(self.ridge), "ridge")
        _finite_positive(float(self.learning_rate), "learning_rate")
        _finite_positive(float(self.rms_limit), "rms_limit")
        _finite_positive(float(self.peak_limit), "peak_limit")
        if not 1 <= int(self.iterations) <= 4000:
            raise ValueError("iterations must be between 1 and 4000")
        if not 16 <= int(self.target_samples) <= 4000:
            raise ValueError("target_samples must be between 16 and 4000")
        if not 32 <= int(self.outside_samples) <= 8000:
            raise ValueError("outside_samples must be between 32 and 8000")
        if not 1 <= int(self.uncertainty_scenarios) <= 64:
            raise ValueError("uncertainty_scenarios must be between 1 and 64")
        _finite_nonnegative(float(self.gain_std_percent), "gain_std_percent")
        _finite_nonnegative(float(self.phase_std_deg), "phase_std_deg")
        _finite_nonnegative(float(self.registration_jitter_lambda), "registration_jitter_lambda")
        _finite_positive(float(self.pa_saturation_amplitude), "pa_saturation_amplitude")
        _finite_positive(float(self.pa_smoothness), "pa_smoothness")
        _finite_nonnegative(float(self.pa_maximum_phase_deg), "pa_maximum_phase_deg")
        if self.dpd_enabled and not self.pa_enabled:
            raise ValueError("DPD cannot be enabled while the PA model is disabled")
        if not 3 <= int(self.pareto_points) <= 15:
            raise ValueError("pareto_points must be in [3, 15]")


@dataclass(frozen=True)
class MotionSpec:
    """Deterministic wavelength-scaled path used by the visual timeline."""

    enabled: bool = True
    frames: int = 18
    dt_frames: float = 1.0
    velocity_x_lambda_per_frame: float = 0.055
    velocity_y_lambda_per_frame: float = 0.020
    acceleration_x_lambda_per_frame2: float = 0.0
    acceleration_y_lambda_per_frame2: float = 0.0
    maneuver_amplitude_lambda: float = 0.24
    maneuver_period_frames: float = 14.0
    observation_delay_frames: int = 2
    controller: str = "Predictive-PGMS"
    preview_samples: int = 51

    CONTROLLERS = ("Static-PGMS", "Delayed-PGMS", "Predictive-PGMS", "Oracle-PGMS")

    def __post_init__(self) -> None:
        if not 3 <= int(self.frames) <= 80:
            raise ValueError("motion frames must be between 3 and 80")
        _finite_positive(float(self.dt_frames), "dt_frames")
        if not 0 <= int(self.observation_delay_frames) <= 20:
            raise ValueError("observation_delay_frames must be between 0 and 20")
        _finite_nonnegative(float(self.maneuver_amplitude_lambda), "maneuver_amplitude_lambda")
        _finite_positive(float(self.maneuver_period_frames), "maneuver_period_frames")
        if self.controller not in self.CONTROLLERS:
            raise ValueError(f"controller must be one of {self.CONTROLLERS}")
        if not 31 <= int(self.preview_samples) <= 101 or int(self.preview_samples) % 2 == 0:
            raise ValueError("preview_samples must be an odd integer in [31, 101]")

    def trajectory(self, start_x: float, start_y: float) -> np.ndarray:
        t = np.arange(int(self.frames), dtype=float) * float(self.dt_frames)
        x = (
            float(start_x)
            + float(self.velocity_x_lambda_per_frame) * t
            + 0.5 * float(self.acceleration_x_lambda_per_frame2) * t**2
        )
        y = (
            float(start_y)
            + float(self.velocity_y_lambda_per_frame) * t
            + 0.5 * float(self.acceleration_y_lambda_per_frame2) * t**2
            + float(self.maneuver_amplitude_lambda)
            * np.sin(2.0 * np.pi * t / float(self.maneuver_period_frames))
        )
        return np.column_stack((x, y))


@dataclass(frozen=True)
class WorkflowSpec:
    """V1.4 实时任务图与实验管理设置。"""

    enabled_nodes: tuple[str, ...] = (
        "scene",
        "signal",
        "perception",
        "protection",
        "field_control",
        "effect_proxy",
        "report",
    )
    experiment_database: str = "outputs_v14_ui/experiments.sqlite3"
    parallel_workers: int = 2
    checkpoint_interval: int = 1

    def __post_init__(self) -> None:
        if len(set(self.enabled_nodes)) != len(self.enabled_nodes):
            raise ValueError("workflow enabled_nodes must be unique")
        if not str(self.experiment_database).strip():
            raise ValueError("experiment_database cannot be empty")
        if not 1 <= int(self.parallel_workers) <= 8:
            raise ValueError("parallel_workers must be in [1, 8]")
        if not 1 <= int(self.checkpoint_interval) <= 100:
            raise ValueError("checkpoint_interval must be in [1, 100]")


@dataclass(frozen=True)
class ProjectMeta:
    name: str = "HPM 数字化电磁算法 CAE 演示工程"
    seed: int = 20260620
    notes: str = "V1.4 中文模板工作台、模型适用性诊断与传播尺度标定工程"

    def __post_init__(self) -> None:
        if not str(self.name).strip():
            raise ValueError("project name cannot be empty")
        if not 0 <= int(self.seed) <= 2**32 - 1:
            raise ValueError("seed must be a uint32-compatible integer")


def _default_interferers() -> tuple[InterfererSpec, ...]:
    return (InterfererSpec(),)


def _default_materials() -> tuple[MaterialSpec, ...]:
    return (
        MaterialSpec(),
        MaterialSpec(
            material_id="MAT-损耗介质",
            name="损耗介质代理",
            relative_permittivity=2.8,
            loss_tangent=0.08,
            reflection_magnitude=0.38,
            reflection_phase_deg=-25.0,
            roughness_proxy=0.22,
        ),
    )


def _default_reflectors() -> tuple[ReflectingPlaneSpec, ...]:
    return (ReflectingPlaneSpec(),)


def _default_cavities() -> tuple[CavitySpec, ...]:
    return (CavitySpec(),)


def _default_apertures() -> tuple[ApertureSpec, ...]:
    return (ApertureSpec(),)


@dataclass(frozen=True)
class CAEProject:
    meta: ProjectMeta = field(default_factory=ProjectMeta)
    array: ArraySpec = field(default_factory=ArraySpec)
    plane: ObservationPlaneSpec = field(default_factory=ObservationPlaneSpec)
    propagation: PropagationSpec = field(default_factory=PropagationSpec)
    materials: tuple[MaterialSpec, ...] = field(default_factory=_default_materials)
    reflecting_planes: tuple[ReflectingPlaneSpec, ...] = field(default_factory=_default_reflectors)
    apertures: tuple[ApertureSpec, ...] = field(default_factory=_default_apertures)
    cavities: tuple[CavitySpec, ...] = field(default_factory=_default_cavities)
    target: TargetRegionSpec = field(default_factory=TargetRegionSpec)
    protected_zone: ProtectedZoneSpec = field(default_factory=ProtectedZoneSpec)
    additional_targets: tuple[TargetRegionSpec, ...] = ()
    additional_protected_zones: tuple[ProtectedZoneSpec, ...] = ()
    interferers: tuple[InterfererSpec, ...] = field(default_factory=_default_interferers)
    perception: PerceptionSpec = field(default_factory=PerceptionSpec)
    protection: ProtectionSpec = field(default_factory=ProtectionSpec)
    solver: SolverSpec = field(default_factory=SolverSpec)
    motion: MotionSpec = field(default_factory=MotionSpec)
    workflow: WorkflowSpec = field(default_factory=WorkflowSpec)
    schema_version: str = SCHEMA_VERSION
    model_scope: str = MODEL_SCOPE

    def __post_init__(self) -> None:
        if str(self.schema_version) != SCHEMA_VERSION:
            raise ValueError(f"unsupported project schema {self.schema_version!r}")
        if self.perception.subarray_nx > self.array.nx or self.perception.subarray_ny > self.array.ny:
            raise ValueError("perception subarray cannot exceed the physical array")
        self._validate_object_ids()
        self._validate_environment()
        self.validate_geometry()

    @property
    def targets(self) -> tuple[TargetRegionSpec, ...]:
        return tuple(item for item in (self.target, *self.additional_targets) if item.enabled)

    @property
    def protected_zones(self) -> tuple[ProtectedZoneSpec, ...]:
        return tuple(item for item in (self.protected_zone, *self.additional_protected_zones) if item.enabled)

    @property
    def active_interferers(self) -> tuple[InterfererSpec, ...]:
        return tuple(item for item in self.interferers if item.enabled)

    @property
    def active_reflectors(self) -> tuple[ReflectingPlaneSpec, ...]:
        return tuple(item for item in self.reflecting_planes if item.enabled)

    @property
    def active_apertures(self) -> tuple[ApertureSpec, ...]:
        return tuple(item for item in self.apertures if item.enabled)

    @property
    def active_cavities(self) -> tuple[CavitySpec, ...]:
        return tuple(item for item in self.cavities if item.enabled)

    def _validate_object_ids(self) -> None:
        ids = [item.object_id for item in (self.target, *self.additional_targets)]
        ids += [item.object_id for item in (self.protected_zone, *self.additional_protected_zones)]
        ids += [item.object_id for item in self.interferers]
        if len(ids) != len(set(ids)):
            raise ValueError("scene object_id values must be unique")
        if not self.targets:
            raise ValueError("at least one target region must be enabled")
        if not self.active_interferers:
            raise ValueError("at least one interferer must be enabled for the live sensing chain")
        if len(self.targets) > 6 or len(self.protected_zones) > 6 or len(self.active_interferers) > 4:
            raise ValueError("interactive mode supports at most 6 targets, 6 protected zones, and 4 interferers")

    def _validate_environment(self) -> None:
        material_ids = [item.material_id for item in self.materials]
        if not material_ids or len(material_ids) != len(set(material_ids)):
            raise ValueError("material_id values must be non-empty and unique")
        cavity_ids = [item.object_id for item in self.cavities]
        if len(cavity_ids) != len(set(cavity_ids)):
            raise ValueError("cavity object_id values must be unique")
        reflector_ids = [item.object_id for item in self.reflecting_planes]
        aperture_ids = [item.object_id for item in self.apertures]
        environment_ids = reflector_ids + cavity_ids + aperture_ids
        if len(environment_ids) != len(set(environment_ids)):
            raise ValueError("environment object_id values must be unique")
        material_set = set(material_ids)
        for reflector in self.reflecting_planes:
            if reflector.material_id not in material_set:
                raise ValueError(f"reflector {reflector.object_id} references unknown material")
        for cavity in self.cavities:
            if cavity.material_id not in material_set:
                raise ValueError(f"cavity {cavity.object_id} references unknown material")
        cavity_set = set(cavity_ids)
        for aperture in self.apertures:
            if aperture.cavity_id not in cavity_set:
                raise ValueError(f"aperture {aperture.object_id} references unknown cavity")
        if len(self.materials) > 12 or len(self.reflecting_planes) > 8 or len(self.apertures) > 8 or len(self.cavities) > 6:
            raise ValueError("interactive environment limits exceeded")

    def validate_geometry(self) -> None:
        half_x = 0.5 * float(self.plane.span_x_lambda)
        half_y = 0.5 * float(self.plane.span_y_lambda)
        for target in self.targets:
            target_extent = max(float(target.semi_major_lambda), float(target.semi_minor_lambda))
            guard_extent = target_extent * float(target.guard_scale)
            if abs(float(target.center_x_lambda)) + guard_extent >= half_x:
                raise ValueError(f"target {target.object_id} and guard region must fit inside the observation plane in x")
            if abs(float(target.center_y_lambda)) + guard_extent >= half_y:
                raise ValueError(f"target {target.object_id} and guard region must fit inside the observation plane in y")
        for zone in self.protected_zones:
            if abs(float(zone.center_x_lambda)) + zone.radius_lambda >= half_x:
                raise ValueError(f"protected zone {zone.object_id} must fit inside the observation plane in x")
            if abs(float(zone.center_y_lambda)) + zone.radius_lambda >= half_y:
                raise ValueError(f"protected zone {zone.object_id} must fit inside the observation plane in y")
        for cavity in self.active_cavities:
            half_cavity_x = 0.5 * float(cavity.size_x_lambda)
            half_cavity_y = 0.5 * float(cavity.size_y_lambda)
            if abs(float(cavity.center_x_lambda)) + half_cavity_x >= half_x:
                raise ValueError(f"cavity {cavity.object_id} must fit inside the observation span in x")
            if abs(float(cavity.center_y_lambda)) + half_cavity_y >= half_y:
                raise ValueError(f"cavity {cavity.object_id} must fit inside the observation span in y")
        for aperture in self.active_apertures:
            if abs(float(aperture.center_x_lambda)) + aperture.radius_lambda >= half_x:
                raise ValueError(f"aperture {aperture.object_id} must fit inside the observation span in x")
            if abs(float(aperture.center_y_lambda)) + aperture.radius_lambda >= half_y:
                raise ValueError(f"aperture {aperture.object_id} must fit inside the observation span in y")
        if self.motion.enabled:
            primary = self.target
            target_extent = max(float(primary.semi_major_lambda), float(primary.semi_minor_lambda))
            guard_extent = target_extent * float(primary.guard_scale)
            path = self.motion.trajectory(primary.center_x_lambda, primary.center_y_lambda)
            if np.max(np.abs(path[:, 0])) + guard_extent >= half_x:
                raise ValueError("motion path and primary target guard must fit inside the observation plane in x")
            if np.max(np.abs(path[:, 1])) + guard_extent >= half_y:
                raise ValueError("motion path and primary target guard must fit inside the observation plane in y")

    @property
    def slug(self) -> str:
        raw = re.sub(r"[^A-Za-z0-9._-]+", "_", self.meta.name.strip())
        return raw.strip("._-") or "hpm_cae_project"

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["workflow"]["enabled_nodes"] = list(payload["workflow"]["enabled_nodes"])
        payload["propagation"]["comparison_backends"] = list(payload["propagation"]["comparison_backends"])
        payload["materials"] = list(payload["materials"])
        payload["reflecting_planes"] = list(payload["reflecting_planes"])
        payload["apertures"] = list(payload["apertures"])
        payload["cavities"] = list(payload["cavities"])
        payload["additional_targets"] = list(payload["additional_targets"])
        payload["additional_protected_zones"] = list(payload["additional_protected_zones"])
        payload["interferers"] = list(payload["interferers"])
        return payload

    def save_yaml(self, path: str | Path) -> Path:
        destination = Path(path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        payload = self.to_dict()
        payload["saved_utc"] = datetime.now(timezone.utc).isoformat()
        destination.write_text(
            yaml.safe_dump(payload, sort_keys=False, allow_unicode=True),
            encoding="utf-8",
        )
        return destination

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "CAEProject":
        data = dict(payload)
        data.pop("saved_utc", None)
        incoming_schema = str(data.get("schema_version", SCHEMA_VERSION))
        if incoming_schema not in {SCHEMA_VERSION, *LEGACY_SCHEMAS}:
            raise ValueError(f"unsupported project schema {incoming_schema!r}")
        workflow_data = dict(data.get("workflow", {}))
        if "enabled_nodes" in workflow_data:
            workflow_data["enabled_nodes"] = tuple(workflow_data["enabled_nodes"])
        propagation_data = dict(data.get("propagation", {}))
        if "comparison_backends" in propagation_data:
            propagation_data["comparison_backends"] = tuple(propagation_data["comparison_backends"])
        raw_materials = data.get("materials")
        materials = _default_materials() if raw_materials is None else tuple(MaterialSpec(**dict(item)) for item in raw_materials)
        raw_reflectors = data.get("reflecting_planes")
        reflecting_planes = _default_reflectors() if raw_reflectors is None else tuple(ReflectingPlaneSpec(**dict(item)) for item in raw_reflectors)
        raw_apertures = data.get("apertures")
        apertures = _default_apertures() if raw_apertures is None else tuple(ApertureSpec(**dict(item)) for item in raw_apertures)
        raw_cavities = data.get("cavities")
        cavities = _default_cavities() if raw_cavities is None else tuple(CavitySpec(**dict(item)) for item in raw_cavities)
        # Migrate only known historical default paths; explicit custom paths remain untouched.
        if incoming_schema in LEGACY_SCHEMAS and workflow_data.get("experiment_database") in {
            "outputs_v10_ui/experiments.sqlite3",
            "outputs_v11_ui/experiments.sqlite3",
            "outputs_v12_ui/experiments.sqlite3",
            "outputs_v13_ui/experiments.sqlite3",
        }:
            workflow_data["experiment_database"] = "outputs_v14_ui/experiments.sqlite3"
        target_data = dict(data.get("target", {}))
        protected_data = dict(data.get("protected_zone", {}))
        additional_targets = tuple(TargetRegionSpec(**dict(item)) for item in data.get("additional_targets", ()))
        additional_protected = tuple(ProtectedZoneSpec(**dict(item)) for item in data.get("additional_protected_zones", ()))
        raw_interferers = data.get("interferers")
        interferers = _default_interferers() if raw_interferers is None else tuple(InterfererSpec(**dict(item)) for item in raw_interferers)
        return cls(
            meta=ProjectMeta(**dict(data.get("meta", {}))),
            array=ArraySpec(**dict(data.get("array", {}))),
            plane=ObservationPlaneSpec(**dict(data.get("plane", {}))),
            propagation=PropagationSpec(**propagation_data),
            materials=materials,
            reflecting_planes=reflecting_planes,
            apertures=apertures,
            cavities=cavities,
            target=TargetRegionSpec(**target_data),
            protected_zone=ProtectedZoneSpec(**protected_data),
            additional_targets=additional_targets,
            additional_protected_zones=additional_protected,
            interferers=interferers,
            perception=PerceptionSpec(**dict(data.get("perception", {}))),
            protection=ProtectionSpec(**dict(data.get("protection", {}))),
            solver=SolverSpec(**dict(data.get("solver", {}))),
            motion=MotionSpec(**dict(data.get("motion", {}))),
            workflow=WorkflowSpec(**workflow_data),
            schema_version=SCHEMA_VERSION,
            model_scope=(
                MODEL_SCOPE
                if incoming_schema in LEGACY_SCHEMAS
                else str(data.get("model_scope", MODEL_SCOPE))
            ),
        )

    @classmethod
    def load_yaml(cls, path: str | Path) -> "CAEProject":
        payload = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
        if not isinstance(payload, Mapping):
            raise ValueError("project YAML must contain a mapping at the top level")
        return cls.from_dict(payload)


def default_project() -> CAEProject:
    """Return the deterministic demonstration project used by the UI."""
    return CAEProject()

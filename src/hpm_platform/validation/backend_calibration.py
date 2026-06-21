"""V1.4 传播后端尺度参数标定。

标定对象仅为归一化传播后端的直达、反射和腔体分量尺度。该模块可接收
合成参考场或外部导入的归一化复场样本；不会推断绝对源功率、器件阈值或
现实作用距离。
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Iterable

import numpy as np
from scipy.optimize import least_squares

from hpm_platform.physics.field_backends import get_field_backend
from hpm_platform.ui.project_model import CAEProject


@dataclass(frozen=True)
class CalibrationSamples:
    points_lambda: np.ndarray
    reference_field: np.ndarray
    excitation: np.ndarray
    reference_backend: str
    reference_scales: tuple[float, float, float]

    def __post_init__(self) -> None:
        points = np.asarray(self.points_lambda, float)
        field = np.asarray(self.reference_field, complex).reshape(-1)
        excitation = np.asarray(self.excitation, complex).reshape(-1)
        if points.ndim != 2 or points.shape[1] != 3:
            raise ValueError("采样点必须为 N×3 数组")
        if points.shape[0] != field.size:
            raise ValueError("参考场长度与采样点数量不一致")
        if not np.all(np.isfinite(points)) or not np.all(np.isfinite(field)):
            raise ValueError("参考样本包含非有限值")
        if excitation.size == 0 or not np.all(np.isfinite(excitation)):
            raise ValueError("阵元激励无效")


@dataclass(frozen=True)
class CalibrationResult:
    reference_backend: str
    candidate_backend: str
    initial_scales: tuple[float, float, float]
    fitted_scales: tuple[float, float, float]
    lower_bounds: tuple[float, float, float]
    upper_bounds: tuple[float, float, float]
    rmse_before: float
    rmse_after: float
    relative_rmse_before_percent: float
    relative_rmse_after_percent: float
    r2_before: float
    r2_after: float
    iterations: int
    success: bool
    message: str
    points_lambda: np.ndarray
    reference_field: np.ndarray
    initial_field: np.ndarray
    fitted_field: np.ndarray
    cost_history: np.ndarray

    @property
    def improvement_percent(self) -> float:
        if self.rmse_before <= 1e-15:
            return 0.0
        return 100.0 * (self.rmse_before - self.rmse_after) / self.rmse_before

    def summary_dict(self) -> dict[str, object]:
        names = ("直达尺度", "反射尺度", "腔体尺度")
        output: dict[str, object] = {
            "参考后端": self.reference_backend,
            "待标定后端": self.candidate_backend,
            "标定成功": bool(self.success),
            "迭代次数": int(self.iterations),
            "标定前相对RMSE/%": round(self.relative_rmse_before_percent, 4),
            "标定后相对RMSE/%": round(self.relative_rmse_after_percent, 4),
            "RMSE改善/%": round(self.improvement_percent, 4),
            "标定前R²": round(self.r2_before, 6),
            "标定后R²": round(self.r2_after, 6),
            "求解信息": self.message,
        }
        for index, name in enumerate(names):
            output[f"{name}初值"] = round(self.initial_scales[index], 6)
            output[f"{name}标定值"] = round(self.fitted_scales[index], 6)
        return output


def _grid_points(project: CAEProject, samples_per_axis: int) -> np.ndarray:
    n = int(samples_per_axis)
    if n < 9 or n > 81 or n % 2 == 0:
        raise ValueError("标定网格每轴采样数必须为9到81之间的奇数")
    x = np.linspace(-project.plane.span_x_lambda / 2, project.plane.span_x_lambda / 2, n)
    y = np.linspace(-project.plane.span_y_lambda / 2, project.plane.span_y_lambda / 2, n)
    xx, yy = np.meshgrid(x, y, indexing="xy")
    return np.column_stack((xx.ravel(), yy.ravel(), np.full(xx.size, project.plane.z_lambda)))


def _scales(project: CAEProject) -> tuple[float, float, float]:
    propagation = project.propagation
    return (
        float(propagation.direct_path_scale),
        float(propagation.reflection_scale),
        float(propagation.cavity_scale),
    )


def _with_backend_scales(
    project: CAEProject,
    backend_id: str,
    scales: Iterable[float],
) -> CAEProject:
    direct, reflection, cavity = (float(item) for item in scales)
    return replace(
        project,
        propagation=replace(
            project.propagation,
            backend=str(backend_id),
            direct_path_scale=direct,
            reflection_scale=reflection,
            cavity_scale=cavity,
        ),
    )


def _field_for(
    project: CAEProject,
    backend_id: str,
    scales: Iterable[float],
    points_lambda: np.ndarray,
    excitation: np.ndarray,
) -> np.ndarray:
    candidate = _with_backend_scales(project, backend_id, scales)
    array = candidate.array.build_array()
    points_m = np.asarray(points_lambda, float) * array.wavelength_m
    backend = get_field_backend(backend_id)
    matrix = backend.matrix(
        array,
        points_m,
        project=candidate,
        reference_scale=1.0,
        chunk_size=4096,
    )
    return matrix @ np.asarray(excitation, complex).reshape(-1)


def _r2(reference: np.ndarray, estimate: np.ndarray) -> float:
    ref = np.concatenate((reference.real, reference.imag))
    est = np.concatenate((estimate.real, estimate.imag))
    residual = float(np.sum((ref - est) ** 2))
    total = float(np.sum((ref - np.mean(ref)) ** 2))
    return 1.0 - residual / max(total, 1e-15)


def generate_reference_samples(
    project: CAEProject,
    *,
    reference_backend: str = "hybrid_scene",
    reference_scales: tuple[float, float, float] | None = None,
    samples_per_axis: int = 25,
    noise_std_fraction: float = 0.0,
    seed: int | None = None,
) -> CalibrationSamples:
    """Generate deterministic normalized complex-field reference samples."""
    scales = reference_scales or _scales(project)
    points_lambda = _grid_points(project, samples_per_axis)
    array = project.array.build_array()
    focus_m = array.wavelength_m * np.array(
        [project.target.center_x_lambda, project.target.center_y_lambda, project.plane.z_lambda],
        dtype=float,
    )
    truth_project = _with_backend_scales(project, reference_backend, scales)
    truth_backend = get_field_backend(reference_backend)
    excitation = truth_backend.focus_weights(
        array, focus_m, project=truth_project, rms_amplitude=0.72
    )
    reference = _field_for(
        project, reference_backend, scales, points_lambda, excitation
    )
    if noise_std_fraction > 0:
        rng = np.random.default_rng(project.meta.seed if seed is None else seed)
        sigma = float(noise_std_fraction) * max(float(np.sqrt(np.mean(np.abs(reference) ** 2))), 1e-12)
        reference = reference + sigma / np.sqrt(2.0) * (
            rng.normal(size=reference.size) + 1j * rng.normal(size=reference.size)
        )
    return CalibrationSamples(
        points_lambda=points_lambda,
        reference_field=reference,
        excitation=excitation,
        reference_backend=reference_backend,
        reference_scales=tuple(float(item) for item in scales),
    )


def calibrate_backend_scales(
    project: CAEProject,
    samples: CalibrationSamples | None = None,
    *,
    reference_backend: str = "hybrid_scene",
    candidate_backend: str = "hybrid_scene",
    reference_scales: tuple[float, float, float] | None = None,
    initial_scales: tuple[float, float, float] = (0.55, 0.35, 0.35),
    bounds: tuple[tuple[float, float, float], tuple[float, float, float]] = (
        (0.0, 0.0, 0.0),
        (2.0, 2.0, 2.0),
    ),
    samples_per_axis: int = 25,
    noise_std_fraction: float = 0.0,
    robust_loss: str = "soft_l1",
    maximum_evaluations: int = 60,
) -> CalibrationResult:
    """Fit normalized direct/reflection/cavity scales to complex-field samples."""
    if samples is None:
        samples = generate_reference_samples(
            project,
            reference_backend=reference_backend,
            reference_scales=reference_scales,
            samples_per_axis=samples_per_axis,
            noise_std_fraction=noise_std_fraction,
        )
    if len(initial_scales) != 3:
        raise ValueError("标定初值必须包含直达、反射、腔体三个尺度")
    lower = np.asarray(bounds[0], float)
    upper = np.asarray(bounds[1], float)
    initial = np.asarray(initial_scales, float)
    if lower.shape != (3,) or upper.shape != (3,):
        raise ValueError("标定边界必须为两个三维向量")
    if np.any(lower < 0) or np.any(upper <= lower):
        raise ValueError("标定边界无效")
    initial = np.clip(initial, lower + 1e-9, upper - 1e-9)

    reference = np.asarray(samples.reference_field, complex).reshape(-1)
    normalization = max(float(np.sqrt(np.mean(np.abs(reference) ** 2))), 1e-12)
    cost_history: list[float] = []

    def evaluate(scales: np.ndarray) -> np.ndarray:
        return _field_for(
            project,
            candidate_backend,
            scales,
            samples.points_lambda,
            samples.excitation,
        )

    initial_field = evaluate(initial)

    def residual(scales: np.ndarray) -> np.ndarray:
        estimate = evaluate(scales)
        delta = (estimate - reference) / normalization
        vector = np.concatenate((delta.real, delta.imag))
        cost_history.append(float(np.sqrt(np.mean(vector**2))))
        return vector

    fit = least_squares(
        residual,
        initial,
        bounds=(lower, upper),
        loss=robust_loss,
        max_nfev=int(maximum_evaluations),
        x_scale="jac",
        ftol=1e-10,
        xtol=1e-10,
        gtol=1e-10,
    )
    fitted = np.asarray(fit.x, float)
    fitted_field = evaluate(fitted)

    rmse_before = float(np.sqrt(np.mean(np.abs(initial_field - reference) ** 2)))
    rmse_after = float(np.sqrt(np.mean(np.abs(fitted_field - reference) ** 2)))
    return CalibrationResult(
        reference_backend=samples.reference_backend,
        candidate_backend=candidate_backend,
        initial_scales=tuple(float(item) for item in initial),
        fitted_scales=tuple(float(item) for item in fitted),
        lower_bounds=tuple(float(item) for item in lower),
        upper_bounds=tuple(float(item) for item in upper),
        rmse_before=rmse_before,
        rmse_after=rmse_after,
        relative_rmse_before_percent=100.0 * rmse_before / normalization,
        relative_rmse_after_percent=100.0 * rmse_after / normalization,
        r2_before=_r2(reference, initial_field),
        r2_after=_r2(reference, fitted_field),
        iterations=int(fit.nfev),
        success=bool(fit.success),
        message=str(fit.message),
        points_lambda=np.asarray(samples.points_lambda, float),
        reference_field=reference,
        initial_field=initial_field,
        fitted_field=fitted_field,
        cost_history=np.asarray(cost_history, float),
    )

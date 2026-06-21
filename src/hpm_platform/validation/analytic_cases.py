"""V2.0A 可信度验证核心算例。

本模块只使用归一化阵列、解析公式和公开数值基准。所有距离均按波长
或方向余弦处理，不包含真实源功率、器件阈值或毁伤距离。
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

import numpy as np

from hpm_platform.perception.esprit import esprit_2d_from_covariance
from hpm_platform.perception.music import MusicGridScanner
from hpm_platform.perception.robust_covariance import pawr_estimate
from hpm_platform.physics.array_geometry import RectangularArray
from hpm_platform.physics.field_backends import get_field_backend
from hpm_platform.protection.beamforming import lcmv_weights, mvdr_weights
from hpm_platform.ui.project_model import CAEProject


Number = float | int | bool | str | None


@dataclass
class CaseResult:
    """单个 V&V 用例的可审计结果。"""

    case_id: str
    name: str
    category: str
    passed: bool
    metrics: dict[str, Number]
    thresholds: dict[str, Number]
    summary: str
    records: list[dict[str, Number]] = field(default_factory=list)
    data: dict[str, Any] = field(default_factory=dict, repr=False)

    def as_dict(self) -> dict[str, Any]:
        return {
            "用例编号": self.case_id,
            "用例名称": self.name,
            "类别": self.category,
            "通过": bool(self.passed),
            "指标": {key: _json_scalar(value) for key, value in self.metrics.items()},
            "判据": {key: _json_scalar(value) for key, value in self.thresholds.items()},
            "结论": self.summary,
            "记录": [
                {key: _json_scalar(value) for key, value in row.items()}
                for row in self.records
            ],
        }


def _json_scalar(value: Any) -> Number:
    if isinstance(value, np.bool_):
        return bool(value)
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating, float)):
        return float(value) if np.isfinite(value) else None
    if isinstance(value, (int, bool, str)) or value is None:
        return value
    return str(value)


def _rmse(a: np.ndarray, b: np.ndarray, mask: np.ndarray | None = None) -> float:
    x = np.asarray(a, float)
    y = np.asarray(b, float)
    valid = np.isfinite(x) & np.isfinite(y)
    if mask is not None:
        valid &= np.asarray(mask, bool)
    return float(np.sqrt(np.mean((x[valid] - y[valid]) ** 2)))


def _max_abs(a: np.ndarray, b: np.ndarray, mask: np.ndarray | None = None) -> float:
    x = np.asarray(a, float)
    y = np.asarray(b, float)
    valid = np.isfinite(x) & np.isfinite(y)
    if mask is not None:
        valid &= np.asarray(mask, bool)
    return float(np.max(np.abs(x[valid] - y[valid])))


def _main_lobe_position(u: np.ndarray, v: np.ndarray, pattern: np.ndarray) -> tuple[float, float]:
    idx = int(np.nanargmax(pattern))
    return float(np.ravel(u)[idx]), float(np.ravel(v)[idx])


def _direction_to_uv(theta_deg: float, phi_deg: float) -> tuple[float, float]:
    theta = np.deg2rad(theta_deg)
    phi = np.deg2rad(phi_deg)
    return float(np.sin(theta) * np.cos(phi)), float(np.sin(theta) * np.sin(phi))


def _uv_to_direction(u: float, v: float) -> tuple[float, float]:
    radius = np.clip(np.hypot(float(u), float(v)), 0.0, 1.0)
    theta = float(np.rad2deg(np.arcsin(radius)))
    phi = float(np.rad2deg(np.arctan2(float(v), float(u))))
    return theta, phi


def _array_factor_formula(
    nx: int,
    ny: int,
    dx_lambda: float,
    dy_lambda: float,
    u: np.ndarray,
    v: np.ndarray,
    *,
    u0: float = 0.0,
    v0: float = 0.0,
) -> np.ndarray:
    """闭式矩形阵列因子，返回归一化幅度。"""

    psi_x = 2.0 * np.pi * float(dx_lambda) * (np.asarray(u, float) - float(u0))
    psi_y = 2.0 * np.pi * float(dy_lambda) * (np.asarray(v, float) - float(v0))

    def dirichlet(n: int, psi: np.ndarray) -> np.ndarray:
        denom = np.sin(psi / 2.0)
        out = np.empty_like(psi, dtype=float)
        small = np.abs(denom) < 1e-12
        out[small] = 1.0
        out[~small] = np.abs(np.sin(n * psi[~small] / 2.0) / (n * denom[~small]))
        return out

    af = dirichlet(int(nx), psi_x) * dirichlet(int(ny), psi_y)
    af[np.asarray(u) ** 2 + np.asarray(v) ** 2 > 1.0] = np.nan
    return af


def _first_sidelobe_location(axis: np.ndarray, cut: np.ndarray, null_width: float) -> float:
    values = np.asarray(cut, float)
    coords = np.asarray(axis, float)
    valid = np.isfinite(values) & (np.abs(coords) > float(null_width))
    if not np.any(valid):
        return float("nan")
    candidates = np.where(valid)[0]
    idx = candidates[int(np.argmax(values[candidates]))]
    return float(coords[idx])


def run_array_factor_case(grid_points: int = 201) -> CaseResult:
    array = RectangularArray(nx=8, ny=8, frequency_hz=1.0e9)
    axis = np.linspace(-1.0, 1.0, int(grid_points))
    uu, vv = np.meshgrid(axis, axis, indexing="xy")
    excitations = np.ones(array.n_elements, dtype=complex) / np.sqrt(array.n_elements)
    platform = array.transmit_response_uv(excitations, uu, vv)
    analytic = _array_factor_formula(8, 8, 0.5, 0.5, uu, vv)
    visible = uu**2 + vv**2 <= 1.0

    peak_u, peak_v = _main_lobe_position(uu, vv, platform)
    ref_u, ref_v = _main_lobe_position(uu, vv, analytic)
    center = int(np.argmin(np.abs(axis)))
    u_cut_platform = platform[center, :]
    u_cut_analytic = analytic[center, :]
    v_cut_platform = platform[:, center]
    v_cut_analytic = analytic[:, center]
    sidelobe_u_error = abs(
        abs(_first_sidelobe_location(axis, u_cut_platform, 0.25))
        - abs(_first_sidelobe_location(axis, u_cut_analytic, 0.25))
    )
    sidelobe_v_error = abs(
        abs(_first_sidelobe_location(axis, v_cut_platform, 0.25))
        - abs(_first_sidelobe_location(axis, v_cut_analytic, 0.25))
    )
    metrics = {
        "主瓣u误差": abs(peak_u - ref_u),
        "主瓣v误差": abs(peak_v - ref_v),
        "主瓣位置误差": float(np.hypot(peak_u - ref_u, peak_v - ref_v)),
        "最大幅度误差": _max_abs(platform, analytic, visible),
        "归一化幅度RMSE": _rmse(platform, analytic, visible),
        "旁瓣u位置误差": sidelobe_u_error,
        "旁瓣v位置误差": sidelobe_v_error,
    }
    thresholds = {"主瓣位置误差": 0.01, "归一化幅度RMSE": 1e-3, "旁瓣位置误差": 0.02}
    passed = (
        metrics["主瓣位置误差"] < thresholds["主瓣位置误差"]
        and metrics["归一化幅度RMSE"] < thresholds["归一化幅度RMSE"]
        and max(sidelobe_u_error, sidelobe_v_error) < thresholds["旁瓣位置误差"]
    )
    return CaseResult(
        case_id="VV-01",
        name="8x8均匀矩形阵列远场方向图解析验证",
        category="解析解验证",
        passed=passed,
        metrics=metrics,
        thresholds=thresholds,
        summary="平台远场响应与闭式阵列因子在主瓣、旁瓣和全图RMSE上保持一致。",
        data={
            "u": axis,
            "v": axis,
            "uu": uu,
            "vv": vv,
            "platform": platform,
            "analytic": analytic,
            "error": np.abs(platform - analytic),
            "u_cut_platform": u_cut_platform,
            "u_cut_analytic": u_cut_analytic,
            "v_cut_platform": v_cut_platform,
            "v_cut_analytic": v_cut_analytic,
        },
    )


def run_scan_beam_case(
    u0: float = 0.25,
    v0: float = -0.15,
    grid_points: int = 241,
) -> CaseResult:
    array = RectangularArray(nx=8, ny=8, frequency_hz=1.0e9)
    axis = np.linspace(-0.6, 0.6, int(grid_points))
    uu, vv = np.meshgrid(axis, axis, indexing="xy")
    phase = array.wave_number * (array.positions_m[:, 0] * float(u0) + array.positions_m[:, 1] * float(v0))
    excitations = np.exp(-1j * phase) / np.sqrt(array.n_elements)
    platform = array.transmit_response_uv(excitations, uu, vv)
    analytic = _array_factor_formula(8, 8, 0.5, 0.5, uu, vv, u0=u0, v0=v0)
    peak_u, peak_v = _main_lobe_position(uu, vv, platform)
    peak_error = float(np.hypot(peak_u - float(u0), peak_v - float(v0)))
    v_index = int(np.argmin(np.abs(axis - float(v0))))
    cut = platform[v_index, :]
    threshold = 1.0 / np.sqrt(2.0)
    above = np.where(np.isfinite(cut) & (cut >= threshold))[0]
    beamwidth = float(axis[above[-1]] - axis[above[0]]) if above.size else float("nan")
    metrics = {
        "目标u": float(u0),
        "目标v": float(v0),
        "峰值u": peak_u,
        "峰值v": peak_v,
        "峰值偏差": peak_error,
        "u向3dB波束宽度": beamwidth,
        "扫描方向图RMSE": _rmse(platform, analytic, uu**2 + vv**2 <= 1.0),
    }
    thresholds = {"峰值偏差": 0.03, "扫描方向图RMSE": 1e-3}
    passed = metrics["峰值偏差"] < thresholds["峰值偏差"] and metrics["扫描方向图RMSE"] < thresholds["扫描方向图RMSE"]
    return CaseResult(
        case_id="VV-02",
        name="相位扫描波束指向解析验证",
        category="解析解验证",
        passed=passed,
        metrics=metrics,
        thresholds=thresholds,
        summary="解析 steering vector 生成的相位使平台方向图峰值落在目标方向附近。",
        data={
            "u": axis,
            "v": axis,
            "uu": uu,
            "vv": vv,
            "pattern": platform,
            "analytic": analytic,
            "target": np.array([float(u0), float(v0)]),
            "u_cut": cut,
            "v_index": v_index,
        },
    )


def run_green_function_case(samples: int = 120) -> CaseResult:
    array = RectangularArray(nx=1, ny=1, frequency_hz=1.0e9)
    distances_lambda = np.linspace(1.0, 12.0, int(samples))
    distances_m = distances_lambda * array.wavelength_m
    points = np.column_stack((np.zeros_like(distances_m), np.zeros_like(distances_m), distances_m))
    backend = get_field_backend("free_space_green")
    field = backend.matrix(array, points, project=object(), reference_scale=1.0).reshape(-1)
    analytic = np.exp(-1j * array.wave_number * distances_m) / distances_m
    amp_error = np.abs(np.abs(field) - np.abs(analytic))
    phase_error = np.angle(field * np.conj(analytic))
    metrics = {
        "幅度最大误差": float(np.max(amp_error)),
        "幅度RMSE": float(np.sqrt(np.mean(amp_error**2))),
        "相位RMSE_rad": float(np.sqrt(np.mean(phase_error**2))),
        "相位最大误差_rad": float(np.max(np.abs(phase_error))),
    }
    thresholds = {"幅度最大误差": 1e-6, "相位RMSE_rad": 1e-10}
    passed = metrics["幅度最大误差"] < thresholds["幅度最大误差"] and metrics["相位RMSE_rad"] < thresholds["相位RMSE_rad"]
    return CaseResult(
        case_id="VV-03",
        name="自由空间Green函数幅相验证",
        category="解析解验证",
        passed=passed,
        metrics=metrics,
        thresholds=thresholds,
        summary="自由空间后端的 exp(-jkr)/r 幅度和相位与解析公式一致。",
        data={
            "distance_lambda": distances_lambda,
            "field_amp": np.abs(field),
            "analytic_amp": np.abs(analytic),
            "field_phase": np.unwrap(np.angle(field)),
            "analytic_phase": np.unwrap(np.angle(analytic)),
            "amp_error": amp_error,
            "phase_error": phase_error,
        },
    )


def _covariance_for_sources(
    array: RectangularArray,
    directions: list[tuple[float, float]],
    powers: list[float],
    noise_power: float,
) -> np.ndarray:
    value = noise_power * np.eye(array.n_elements, dtype=complex)
    for direction, power in zip(directions, powers):
        steering = array.steering_vector(*direction)
        value += float(power) * np.outer(steering, np.conj(steering))
    return 0.5 * (value + np.conj(value.T))


def _angular_error_deg(a: tuple[float, float], b: tuple[float, float]) -> float:
    av = RectangularArray.direction_vector(a[0], a[1]).reshape(3)
    bv = RectangularArray.direction_vector(b[0], b[1]).reshape(3)
    return float(np.rad2deg(np.arccos(np.clip(np.dot(av, bv), -1.0, 1.0))))


def run_music_esprit_case(seed: int = 20260620) -> CaseResult:
    truth = (25.0, 20.0)
    array = RectangularArray(nx=6, ny=6, frequency_hz=1.0e9)
    covariance = _covariance_for_sources(array, [truth], [1.0], noise_power=1e-3)
    theta_grid = np.arange(10.0, 40.0 + 0.5, 0.5)
    phi_grid = np.arange(-10.0, 50.0 + 0.5, 0.5)
    scanner = MusicGridScanner(array, theta_grid, phi_grid)
    music = scanner.scan_covariance(covariance, n_sources=1, n_peaks=1)
    music_estimate = (music.peaks[0][0], music.peaks[0][1])
    esprit = esprit_2d_from_covariance(covariance, array, n_sources=1)
    esprit_estimate = esprit.estimates[0] if esprit.estimates else (float("nan"), float("nan"))

    rng = np.random.default_rng(int(seed))
    source = (rng.normal(size=(1, 256)) + 1j * rng.normal(size=(1, 256))) / np.sqrt(2.0)
    steering = array.steering_vector(*truth)
    noise = (rng.normal(size=(array.n_elements, 256)) + 1j * rng.normal(size=(array.n_elements, 256))) / np.sqrt(2.0)
    snapshots = steering[:, None] @ source + noise * 10 ** (-30.0 / 20.0)
    subarray = RectangularArray(nx=5, ny=5, frequency_hz=1.0e9)
    pawr_scanner = MusicGridScanner(subarray, np.arange(10.0, 41.0, 1.0), np.arange(-10.0, 51.0, 1.0))
    pawr = pawr_estimate(
        snapshots,
        array,
        pawr_scanner,
        n_sources=1,
        subarray_nx=5,
        subarray_ny=5,
        prior_centers_deg=[truth],
        prior_sigma_deg=5.0,
    )
    pawr_estimate_value = pawr.estimates[0] if pawr.estimates else (float("nan"), float("nan"))

    records = []
    for method, estimate in (
        ("MUSIC", music_estimate),
        ("ESPRIT", esprit_estimate),
        ("PAWR-MUSIC", pawr_estimate_value),
    ):
        records.append(
            {
                "方法": method,
                "估计theta_deg": estimate[0],
                "估计phi_deg": estimate[1],
                "角度误差_deg": _angular_error_deg(truth, estimate),
                "通过": _angular_error_deg(truth, estimate) < (0.5 if method != "PAWR-MUSIC" else 1.0),
            }
        )

    music_error = _angular_error_deg(truth, music_estimate)
    esprit_error = _angular_error_deg(truth, esprit_estimate)
    pawr_error = _angular_error_deg(truth, pawr_estimate_value)
    metrics = {
        "MUSIC角度误差_deg": music_error,
        "ESPRIT角度误差_deg": esprit_error,
        "PAWR角度误差_deg": pawr_error,
        "RMSE_deg": float(np.sqrt(np.mean(np.array([music_error, esprit_error, pawr_error]) ** 2))),
        "失败率": float(np.mean([not bool(row["通过"]) for row in records])),
    }
    thresholds = {"MUSIC/ESPRIT角度误差_deg": 0.5, "PAWR角度误差_deg": 1.0, "失败率": 0.01}
    passed = music_error < 0.5 and esprit_error < 0.5 and pawr_error < 1.0
    return CaseResult(
        case_id="VV-04",
        name="MUSIC/ESPRIT/PAWR测向基准验证",
        category="算法基准验证",
        passed=passed,
        metrics=metrics,
        thresholds=thresholds,
        summary="理想高SNR单源场景下，MUSIC、ESPRIT 与 PAWR-MUSIC 均能复现真值方向。",
        records=records,
        data={
            "theta_grid": theta_grid,
            "phi_grid": phi_grid,
            "music_spectrum": music.spectrum,
            "truth": np.array(truth),
            "music_estimate": np.array(music_estimate),
            "esprit_estimate": np.array(esprit_estimate),
            "pawr_estimate": np.array(pawr_estimate_value),
        },
    )


def run_mvdr_lcmv_case() -> CaseResult:
    array = RectangularArray(nx=8, ny=8, frequency_hz=1.0e9)
    desired = (20.0, 10.0)
    interferer = (35.0, -20.0)
    a_s = array.steering_vector(*desired)
    a_i = array.steering_vector(*interferer)
    covariance = np.eye(array.n_elements, dtype=complex) + 100.0 * np.outer(a_i, np.conj(a_i))
    mvdr = mvdr_weights(covariance, a_s, loading_factor=1e-3)
    constraints = np.column_stack((a_s, a_i))
    responses = np.array([1.0 + 0j, 0.0 + 0j])
    lcmv = lcmv_weights(covariance, constraints, responses, loading_factor=1e-3)
    residual = np.conj(constraints.T) @ lcmv - responses
    constraint_residual = float(np.linalg.norm(residual))
    null_response = float(np.abs(np.conj(a_i) @ lcmv))
    null_depth_db = float(20.0 * np.log10(max(null_response, np.finfo(float).tiny)))
    white_noise_gain = float(1.0 / max(np.vdot(lcmv, lcmv).real, np.finfo(float).tiny))

    theta_axis = np.linspace(0.0, 60.0, 301)
    phi = np.full_like(theta_axis, desired[1])
    steering_grid = array.steering_matrix(theta_axis, phi)
    mvdr_response = np.abs(np.conj(steering_grid.T) @ mvdr)
    lcmv_response = np.abs(np.conj(steering_grid.T) @ lcmv)
    mvdr_db = 20.0 * np.log10(np.maximum(mvdr_response / np.max(mvdr_response), 1e-12))
    lcmv_db = 20.0 * np.log10(np.maximum(lcmv_response / np.max(lcmv_response), 1e-12))

    metrics = {
        "LCMV约束残差": constraint_residual,
        "LCMV零陷深度_dB": null_depth_db,
        "白噪声增益": white_noise_gain,
        "MVDR目标响应": float(np.abs(np.conj(a_s) @ mvdr)),
        "MVDR干扰响应": float(np.abs(np.conj(a_i) @ mvdr)),
    }
    thresholds = {"LCMV约束残差": 1e-6, "LCMV零陷深度_dB": -100.0}
    passed = constraint_residual < thresholds["LCMV约束残差"] and null_depth_db < thresholds["LCMV零陷深度_dB"]
    return CaseResult(
        case_id="VV-05",
        name="MVDR/LCMV约束响应验证",
        category="算法基准验证",
        passed=passed,
        metrics=metrics,
        thresholds=thresholds,
        summary="LCMV 精确满足目标单位响应与干扰方向零陷约束，MVDR 作为对照给出失真less响应。",
        records=[
            {"方法": "MVDR", "目标响应": metrics["MVDR目标响应"], "干扰响应": metrics["MVDR干扰响应"], "约束残差": None},
            {"方法": "LCMV", "目标响应": float(np.abs(np.conj(a_s) @ lcmv)), "干扰响应": null_response, "约束残差": constraint_residual},
        ],
        data={
            "theta_axis": theta_axis,
            "mvdr_db": mvdr_db,
            "lcmv_db": lcmv_db,
            "desired": np.array(desired),
            "interferer": np.array(interferer),
        },
    )


def _default_project_path() -> Path:
    return Path(__file__).resolve().parents[3] / "configs" / "cae_project_v14.yaml"


def _sample_points(array: RectangularArray, n: int = 13) -> np.ndarray:
    axis = np.linspace(-2.0, 2.0, int(n)) * array.wavelength_m
    xx, yy = np.meshgrid(axis, axis, indexing="xy")
    zz = np.full_like(xx, 8.0 * array.wavelength_m)
    return np.column_stack((xx.ravel(), yy.ravel(), zz.ravel()))


def run_backend_consistency_case(project_path: str | Path | None = None) -> CaseResult:
    project = CAEProject.load_yaml(project_path or _default_project_path())
    array = project.array.build_array()
    points = _sample_points(array)
    free_backend = get_field_backend("free_space_green")
    free_project = replace(project, propagation=replace(project.propagation, backend="free_space_green", direct_path_scale=1.0))
    free = free_backend.matrix(array, points, project=free_project, reference_scale=1.0)

    hybrid_project = replace(
        project,
        propagation=replace(project.propagation, backend="hybrid_scene", direct_path_scale=1.0, reflection_scale=1.0, cavity_scale=1.0),
        reflecting_planes=tuple(replace(item, enabled=False) for item in project.reflecting_planes),
        apertures=tuple(replace(item, enabled=False) for item in project.apertures),
        cavities=tuple(replace(item, enabled=False) for item in project.cavities),
    )
    hybrid = get_field_backend("hybrid_scene").matrix(array, points, project=hybrid_project, reference_scale=1.0)

    image_project = replace(
        project,
        propagation=replace(project.propagation, backend="image_ray", direct_path_scale=1.0, reflection_scale=0.0),
    )
    image = get_field_backend("image_ray").matrix(array, points, project=image_project, reference_scale=1.0)

    aperture_project = replace(
        project,
        propagation=replace(project.propagation, backend="aperture_cavity_rom", direct_path_scale=1.0, cavity_scale=1.0),
        apertures=tuple(replace(item, coupling_scale=0.0) for item in project.apertures),
    )
    aperture = get_field_backend("aperture_cavity_rom").matrix(array, points, project=aperture_project, reference_scale=1.0)

    def rel_error(candidate: np.ndarray) -> float:
        return float(np.linalg.norm(candidate - free) / max(np.linalg.norm(free), np.finfo(float).tiny))

    records = [
        {"场景": "混合后端禁用反射/孔缝/腔体", "相对退化误差": rel_error(hybrid), "通过": rel_error(hybrid) < 1e-6},
        {"场景": "镜像后端反射系数为0", "相对退化误差": rel_error(image), "通过": rel_error(image) < 1e-6},
        {"场景": "孔缝腔体耦合系数为0", "相对退化误差": rel_error(aperture), "通过": rel_error(aperture) < 1e-6},
    ]
    max_error = max(float(row["相对退化误差"]) for row in records)
    metrics = {
        "最大退化相对误差": max_error,
        "通过场景数": int(sum(bool(row["通过"]) for row in records)),
        "总场景数": len(records),
    }
    thresholds = {"最大退化相对误差": 1e-6}
    passed = max_error < thresholds["最大退化相对误差"]
    return CaseResult(
        case_id="VV-06",
        name="传播后端一致性与适用性验证",
        category="后端一致性验证",
        passed=passed,
        metrics=metrics,
        thresholds=thresholds,
        summary="关闭附加传播机制后，各复合后端按设计退化为自由空间格林后端。",
        records=records,
        data={
            "radar_labels": np.array(["混合退化", "镜像退化", "孔缝退化"]),
            "radar_scores": np.array([max(0.0, 1.0 - float(row["相对退化误差"]) / 1e-6) for row in records]),
        },
    )


def run_all_validation_cases(project_path: str | Path | None = None, *, fast: bool = True) -> list[CaseResult]:
    grid = 151 if fast else 241
    scan_grid = 181 if fast else 241
    return [
        run_array_factor_case(grid_points=grid),
        run_scan_beam_case(grid_points=scan_grid),
        run_green_function_case(samples=80 if fast else 160),
        run_music_esprit_case(),
        run_mvdr_lcmv_case(),
        run_backend_consistency_case(project_path),
    ]

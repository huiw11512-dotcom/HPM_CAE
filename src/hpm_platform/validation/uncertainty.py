"""V2.0A Monte Carlo 不确定度量化。"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd

from hpm_platform.physics.array_geometry import RectangularArray


@dataclass
class UncertaintyResult:
    summary: dict[str, Any]
    records: list[dict[str, Any]]
    data: dict[str, Any] = field(default_factory=dict, repr=False)

    def frame(self) -> pd.DataFrame:
        return pd.DataFrame(self.records)

    def as_dict(self) -> dict[str, Any]:
        return {
            "汇总": self.summary,
            "样本数": len(self.records),
            "记录": self.records,
        }


def run_monte_carlo_uncertainty(
    *,
    n_samples: int = 64,
    seed: int = 20260620,
    phase_std_deg: float = 3.0,
    amplitude_std_percent: float = 2.0,
    target_jitter_uv: float = 0.006,
    noise_std: float = 0.003,
    grid_points: int = 101,
) -> UncertaintyResult:
    """对扫描波束峰值偏差做可复现 Monte Carlo 统计。"""

    records, data = _sample_records(
        n_samples=n_samples,
        seed=seed,
        phase_std_deg=phase_std_deg,
        amplitude_std_percent=amplitude_std_percent,
        target_jitter_uv=target_jitter_uv,
        noise_std=noise_std,
        grid_points=grid_points,
        keep_last_pattern=True,
    )
    replay, _ = _sample_records(
        n_samples=min(12, n_samples),
        seed=seed,
        phase_std_deg=phase_std_deg,
        amplitude_std_percent=amplitude_std_percent,
        target_jitter_uv=target_jitter_uv,
        noise_std=noise_std,
        grid_points=grid_points,
        keep_last_pattern=False,
    )
    reproducible = all(
        abs(float(a["峰值偏差"]) - float(b["峰值偏差"])) < 1e-15
        for a, b in zip(records[: len(replay)], replay)
    )

    frame = pd.DataFrame(records)
    peak_error = frame["峰值偏差"].to_numpy(float)
    rmse = frame["方向图相对RMSE"].to_numpy(float)
    ci_low, ci_high = np.percentile(peak_error, [2.5, 97.5])
    summary = {
        "随机种子": int(seed),
        "样本数": int(n_samples),
        "相位误差标准差_deg": float(phase_std_deg),
        "幅度误差标准差_percent": float(amplitude_std_percent),
        "目标扰动标准差_uv": float(target_jitter_uv),
        "噪声标准差": float(noise_std),
        "峰值偏差均值": float(np.mean(peak_error)),
        "峰值偏差标准差": float(np.std(peak_error, ddof=1)) if len(peak_error) > 1 else 0.0,
        "峰值偏差95%CI下限": float(ci_low),
        "峰值偏差95%CI上限": float(ci_high),
        "峰值偏差95%CI宽度": float(ci_high - ci_low),
        "方向图相对RMSE均值": float(np.mean(rmse)),
        "方向图相对RMSE标准差": float(np.std(rmse, ddof=1)) if len(rmse) > 1 else 0.0,
        "固定随机种子可复现": bool(reproducible),
    }
    return UncertaintyResult(summary=summary, records=records, data=data)


def _sample_records(
    *,
    n_samples: int,
    seed: int,
    phase_std_deg: float,
    amplitude_std_percent: float,
    target_jitter_uv: float,
    noise_std: float,
    grid_points: int,
    keep_last_pattern: bool,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    if int(n_samples) < 1:
        raise ValueError("Monte Carlo 样本数必须为正")
    array = RectangularArray(nx=8, ny=8, frequency_hz=1.0e9)
    target_u = 0.25
    target_v = -0.15
    axis = np.linspace(-0.65, 0.65, int(grid_points))
    uu, vv = np.meshgrid(axis, axis, indexing="xy")
    rng = np.random.default_rng(int(seed))
    nominal_phase = -array.wave_number * (array.positions_m[:, 0] * target_u + array.positions_m[:, 1] * target_v)
    nominal_q = np.exp(1j * nominal_phase) / np.sqrt(array.n_elements)
    nominal = array.transmit_response_uv(nominal_q, uu, vv)
    records: list[dict[str, Any]] = []
    last_pattern = nominal
    for idx in range(int(n_samples)):
        du = rng.normal(0.0, float(target_jitter_uv))
        dv = rng.normal(0.0, float(target_jitter_uv))
        amp = 1.0 + rng.normal(0.0, float(amplitude_std_percent) / 100.0, size=array.n_elements)
        amp = np.clip(amp, 0.05, None)
        phase_error = rng.normal(0.0, np.deg2rad(float(phase_std_deg)), size=array.n_elements)
        phase = -array.wave_number * (
            array.positions_m[:, 0] * (target_u + du)
            + array.positions_m[:, 1] * (target_v + dv)
        )
        q = amp * np.exp(1j * (phase + phase_error))
        q = q / np.linalg.norm(q)
        pattern = array.transmit_response_uv(q, uu, vv)
        if noise_std > 0:
            pattern = np.clip(pattern + rng.normal(0.0, float(noise_std), size=pattern.shape), 0.0, None)
            pattern = pattern / max(float(np.nanmax(pattern)), np.finfo(float).tiny)
        peak_index = int(np.nanargmax(pattern))
        peak_u = float(np.ravel(uu)[peak_index])
        peak_v = float(np.ravel(vv)[peak_index])
        peak_error = float(np.hypot(peak_u - target_u, peak_v - target_v))
        relative_rmse = float(
            np.sqrt(np.nanmean((pattern - nominal) ** 2))
            / max(float(np.nanmean(nominal)), np.finfo(float).tiny)
        )
        records.append(
            {
                "样本": idx + 1,
                "目标u扰动": float(du),
                "目标v扰动": float(dv),
                "峰值u": peak_u,
                "峰值v": peak_v,
                "峰值偏差": peak_error,
                "方向图相对RMSE": relative_rmse,
            }
        )
        if keep_last_pattern:
            last_pattern = pattern
    data = {
        "u": axis,
        "v": axis,
        "nominal": nominal,
        "last_pattern": last_pattern,
        "peak_errors": np.asarray([row["峰值偏差"] for row in records], dtype=float),
        "relative_rmse": np.asarray([row["方向图相对RMSE"] for row in records], dtype=float),
    }
    return records, data

"""Dynamic target timeline for the HPM-CAE V1.0 visual workbench.

The timeline reuses the normalized near-field region solver.  It is a visual
algorithm demonstrator: positions are expressed in wavelengths and the
response score is a dimensionless proxy, not a hardware damage probability.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable
import json
import time

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from hpm_platform.evaluation.field_metrics import evaluate_field_control
from hpm_platform.field_control.region_shaping import rotated_ellipse_masks
from hpm_platform.ui.project_model import CAEProject, MotionSpec
from hpm_platform.ui.quick_solver import CAESolveResult, solve_project

TimelineLog = Callable[[str], None] | None


@dataclass(frozen=True)
class TimelineResult:
    project: CAEProject
    controller: str
    true_centers_lambda: np.ndarray
    design_centers_lambda: np.ndarray
    fields: np.ndarray
    target_masks: np.ndarray
    metrics: pd.DataFrame
    x_lambda: np.ndarray
    y_lambda: np.ndarray
    frame_runtime_ms: np.ndarray
    log_lines: tuple[str, ...]

    @property
    def amplitudes(self) -> np.ndarray:
        return np.abs(self.fields)

    @property
    def n_frames(self) -> int:
        return int(self.fields.shape[0])

    def summary(self) -> dict[str, float | int | str]:
        frame = self.metrics
        return {
            "controller": self.controller,
            "frames": self.n_frames,
            "mean_tracking_error_lambda": float(frame["tracking_error_lambda"].mean()),
            "mean_target_rmse_percent": float(frame["target_rmse_percent"].mean()),
            "mean_target_coverage_percent": float(frame["target_coverage_percent"].mean()),
            "mean_protected_p95_db": float(frame["protected_p95_db"].mean()),
            "mean_response_proxy": float(frame["target_response_proxy"].mean()),
            "availability_percent": float(100.0 * frame["control_success"].mean()),
            "median_frame_runtime_ms": float(frame["runtime_ms"].median()),
        }


def _log(lines: list[str], callback: TimelineLog, message: str) -> None:
    lines.append(message)
    if callback is not None:
        callback(message)


def _predicted_center(path: np.ndarray, frame: int, motion: MotionSpec) -> np.ndarray:
    delay = int(motion.observation_delay_frames)
    observed = max(0, frame - delay)
    if motion.controller == "Static-PGMS":
        return path[0].copy()
    if motion.controller == "Delayed-PGMS":
        return path[observed].copy()
    if motion.controller == "Oracle-PGMS":
        return path[frame].copy()
    # Timestamp-aware constant-velocity predictor.  It intentionally cannot
    # perfectly predict the sinusoidal maneuver term.
    if observed >= 1:
        velocity = (path[observed] - path[observed - 1]) / float(motion.dt_frames)
    else:
        velocity = np.array(
            [motion.velocity_x_lambda_per_frame, motion.velocity_y_lambda_per_frame],
            dtype=float,
        )
    horizon = float(frame - observed) * float(motion.dt_frames)
    return path[observed] + velocity * horizon


def _clip_center(project: CAEProject, center: np.ndarray) -> np.ndarray:
    extent = max(project.target.semi_major_lambda, project.target.semi_minor_lambda) * project.target.guard_scale
    half_x = project.plane.span_x_lambda / 2.0 - extent - 0.02
    half_y = project.plane.span_y_lambda / 2.0 - extent - 0.02
    return np.array(
        [np.clip(center[0], -half_x, half_x), np.clip(center[1], -half_y, half_y)],
        dtype=float,
    )


def _actual_masks(project: CAEProject, result: CAESolveResult, center: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    xx, yy = np.meshgrid(result.x_lambda, result.y_lambda, indexing="xy")
    region = rotated_ellipse_masks(
        xx,
        yy,
        center_m=(float(center[0]), float(center[1])),
        semi_axes_m=(project.target.semi_major_lambda, project.target.semi_minor_lambda),
        rotation_deg=project.target.rotation_deg,
        guard_scale=project.target.guard_scale,
    )
    outside = np.asarray(region.outside | result.protected_mask, dtype=bool)
    outside &= ~region.target
    return region.target, outside


def run_timeline(
    project: CAEProject,
    *,
    controller: str | None = None,
    frames: int | None = None,
    log_callback: TimelineLog = None,
) -> TimelineResult:
    """Run a deterministic dynamic field-control timeline."""
    motion = project.motion
    if controller is not None:
        motion = replace(motion, controller=str(controller))
    if frames is not None:
        motion = replace(motion, frames=int(frames))
    path = motion.trajectory(project.target.center_x_lambda, project.target.center_y_lambda)
    design_path = np.vstack([_clip_center(project, _predicted_center(path, i, motion)) for i in range(path.shape[0])])

    lines: list[str] = []
    _log(lines, log_callback, f"[timeline] {motion.controller} · {motion.frames} frames · delay={motion.observation_delay_frames}")
    fields: list[np.ndarray] = []
    masks: list[np.ndarray] = []
    runtimes: list[float] = []
    records: list[dict[str, float | int | bool | str]] = []
    x_axis: np.ndarray | None = None
    y_axis: np.ndarray | None = None

    for frame_index, (true_center, design_center) in enumerate(zip(path, design_path, strict=True)):
        solver = replace(
            project.solver,
            method="Nominal-PGMS",
            iterations=min(int(project.solver.iterations), 140),
            target_samples=min(int(project.solver.target_samples), 180),
            outside_samples=min(int(project.solver.outside_samples), 420),
            uncertainty_scenarios=1,
        )
        design_project = replace(
            project,
            target=replace(
                project.target,
                center_x_lambda=float(design_center[0]),
                center_y_lambda=float(design_center[1]),
            ),
            plane=replace(project.plane, samples=int(motion.preview_samples)),
            solver=solver,
            motion=replace(motion, enabled=False),
        )
        started = time.perf_counter()
        result = solve_project(design_project)
        runtime_ms = 1000.0 * (time.perf_counter() - started)
        actual_target, actual_outside = _actual_masks(project, result, true_center)
        metrics = evaluate_field_control(
            result.field,
            actual_target,
            actual_outside,
            target_amplitude=project.solver.target_amplitude,
            success_rmse_fraction=0.20,
            success_min_coverage=0.45,
            success_max_peak_outside_db=0.0,
        )
        protected_values = np.abs(result.field[result.protected_mask])
        protected_p95_db = (
            20.0
            * np.log10(
                max(
                    float(np.quantile(protected_values, 0.95)) / project.solver.target_amplitude,
                    1e-12,
                )
            )
            if protected_values.size
            else np.nan
        )
        target_ratio = np.abs(result.field[actual_target]) / project.solver.target_amplitude
        # Dimensionless monotone response proxy; deliberately not calibrated to
        # a physical device or a damage threshold.
        response_proxy = float(np.mean(1.0 - np.exp(-0.72 * np.maximum(target_ratio, 0.0) ** 4)))
        tracking_error = float(np.linalg.norm(design_center - true_center))
        records.append(
            {
                "frame": frame_index,
                "true_x_lambda": float(true_center[0]),
                "true_y_lambda": float(true_center[1]),
                "design_x_lambda": float(design_center[0]),
                "design_y_lambda": float(design_center[1]),
                "tracking_error_lambda": tracking_error,
                "target_rmse_percent": 100.0 * metrics.target_rmse_fraction,
                "target_coverage_percent": 100.0 * metrics.target_coverage,
                "peak_outside_db": metrics.peak_outside_db,
                "protected_p95_db": float(protected_p95_db),
                "target_response_proxy": response_proxy,
                "control_success": bool(metrics.control_success),
                "runtime_ms": runtime_ms,
            }
        )
        fields.append(result.field)
        masks.append(actual_target)
        runtimes.append(runtime_ms)
        x_axis = result.x_lambda
        y_axis = result.y_lambda
        _log(
            lines,
            log_callback,
            f"[frame {frame_index + 1:02d}/{motion.frames:02d}] err={tracking_error:.3f}λ · RMSE={100*metrics.target_rmse_fraction:.1f}% · cover={100*metrics.target_coverage:.1f}%",
        )

    assert x_axis is not None and y_axis is not None
    return TimelineResult(
        project=replace(project, motion=motion),
        controller=motion.controller,
        true_centers_lambda=path,
        design_centers_lambda=design_path,
        fields=np.asarray(fields),
        target_masks=np.asarray(masks),
        metrics=pd.DataFrame.from_records(records),
        x_lambda=x_axis,
        y_lambda=y_axis,
        frame_runtime_ms=np.asarray(runtimes),
        log_lines=tuple(lines),
    )


def _ellipse(center: np.ndarray, project: CAEProject, points: int = 161) -> tuple[np.ndarray, np.ndarray]:
    angle = np.linspace(0.0, 2.0 * np.pi, points)
    rotation = np.deg2rad(project.target.rotation_deg)
    x0 = project.target.semi_major_lambda * np.cos(angle)
    y0 = project.target.semi_minor_lambda * np.sin(angle)
    x = center[0] + np.cos(rotation) * x0 - np.sin(rotation) * y0
    y = center[1] + np.sin(rotation) * x0 + np.cos(rotation) * y0
    return x, y


def make_timeline_animation(result: TimelineResult) -> go.Figure:
    target_amp = result.project.solver.target_amplitude
    z_all = 20.0 * np.log10(np.maximum(result.amplitudes / target_amp, 1e-4))
    z_all = np.clip(z_all, -40.0, 8.0)
    true_x, true_y = _ellipse(result.true_centers_lambda[0], result.project)
    design_x, design_y = _ellipse(result.design_centers_lambda[0], result.project)
    fig = go.Figure(
        data=[
            go.Heatmap(
                z=z_all[0], x=result.x_lambda, y=result.y_lambda, zmin=-30, zmax=3,
                colorscale="Turbo", colorbar={"title": "dB"}, hovertemplate="x=%{x:.2f}λ<br>y=%{y:.2f}λ<br>%{z:.2f} dB<extra></extra>",
            ),
            go.Scatter(x=true_x, y=true_y, mode="lines", name="真实目标区", line={"color": "#ffc857", "width": 3}),
            go.Scatter(x=design_x, y=design_y, mode="lines", name="赋形中心", line={"color": "#35d8ff", "width": 2, "dash": "dash"}),
        ]
    )
    frames = []
    for i in range(result.n_frames):
        tx, ty = _ellipse(result.true_centers_lambda[i], result.project)
        dx, dy = _ellipse(result.design_centers_lambda[i], result.project)
        frames.append(
            go.Frame(
                name=str(i),
                data=[
                    go.Heatmap(z=z_all[i]),
                    go.Scatter(x=tx, y=ty),
                    go.Scatter(x=dx, y=dy),
                ],
                traces=[0, 1, 2],
            )
        )
    fig.frames = frames
    steps = [
        {
            "label": str(i),
            "method": "animate",
            "args": [[str(i)], {"mode": "immediate", "frame": {"duration": 0, "redraw": True}, "transition": {"duration": 0}}],
        }
        for i in range(result.n_frames)
    ]
    fig.update_layout(
        title={"text": f"动态控场时间轴 · {result.controller}", "x": 0.02},
        paper_bgcolor="#07101d", plot_bgcolor="#0d1828", font={"color": "#e7eef9"}, height=620,
        margin={"l": 55, "r": 40, "t": 70, "b": 90},
        xaxis={"title": "x / λ", "range": [result.x_lambda[0], result.x_lambda[-1]], "gridcolor": "#26354d", "scaleanchor": "y"},
        yaxis={"title": "y / λ", "range": [result.y_lambda[0], result.y_lambda[-1]], "gridcolor": "#26354d"},
        legend={"bgcolor": "rgba(7,16,29,.7)"},
        updatemenus=[{
            "type": "buttons", "direction": "left", "x": 0.02, "y": -0.13,
            "buttons": [
                {"label": "▶ 播放", "method": "animate", "args": [None, {"frame": {"duration": 350, "redraw": True}, "fromcurrent": True, "transition": {"duration": 0}}]},
                {"label": "Ⅱ 暂停", "method": "animate", "args": [[None], {"mode": "immediate", "frame": {"duration": 0, "redraw": False}}]},
            ],
        }],
        sliders=[{"active": 0, "steps": steps, "x": 0.25, "len": 0.72, "y": -0.10, "currentvalue": {"prefix": "帧 "}}],
    )
    return fig


def make_timeline_metrics_figure(result: TimelineResult) -> go.Figure:
    frame = result.metrics
    fig = make_subplots(rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.10, subplot_titles=("目标区控制质量", "跟踪与代理响应"))
    fig.add_trace(go.Scatter(x=frame["frame"], y=frame["target_rmse_percent"], mode="lines+markers", name="RMSE / %", line={"color": "#ff6b7a"}), row=1, col=1)
    fig.add_trace(go.Scatter(x=frame["frame"], y=frame["target_coverage_percent"], mode="lines+markers", name="覆盖率 / %", line={"color": "#4ee0a5"}), row=1, col=1)
    fig.add_trace(go.Scatter(x=frame["frame"], y=frame["tracking_error_lambda"], mode="lines+markers", name="中心误差 / λ", line={"color": "#35d8ff"}), row=2, col=1)
    fig.add_trace(go.Scatter(x=frame["frame"], y=frame["target_response_proxy"], mode="lines+markers", name="响应代理", line={"color": "#ab8cff"}), row=2, col=1)
    fig.update_layout(title={"text": "逐帧指标监视器", "x": 0.02}, paper_bgcolor="#07101d", plot_bgcolor="#0d1828", font={"color": "#e7eef9"}, height=560, margin={"l": 55, "r": 25, "t": 70, "b": 50}, legend={"orientation": "h", "y": -0.12})
    fig.update_xaxes(title="帧", gridcolor="#26354d")
    fig.update_yaxes(gridcolor="#26354d")
    return fig


def make_trajectory_figure(result: TimelineResult) -> go.Figure:
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=result.true_centers_lambda[:, 0], y=result.true_centers_lambda[:, 1], mode="lines+markers", name="真实中心", line={"color": "#ffc857", "width": 3}))
    fig.add_trace(go.Scatter(x=result.design_centers_lambda[:, 0], y=result.design_centers_lambda[:, 1], mode="lines+markers", name="赋形中心", line={"color": "#35d8ff", "width": 2, "dash": "dash"}))
    fig.update_layout(title={"text": "目标轨迹与赋形中心", "x": 0.02}, paper_bgcolor="#07101d", plot_bgcolor="#0d1828", font={"color": "#e7eef9"}, height=480, margin={"l": 55, "r": 25, "t": 65, "b": 55}, xaxis={"title": "x / λ", "gridcolor": "#26354d", "scaleanchor": "y"}, yaxis={"title": "y / λ", "gridcolor": "#26354d"})
    return fig


def export_timeline(result: TimelineResult, root: str | Path, *, name: str | None = None) -> tuple[Path, Path]:
    root_path = Path(root)
    root_path.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    folder = root_path / (name or f"{result.project.slug}_timeline_{stamp}")
    folder.mkdir(parents=True, exist_ok=True)
    result.metrics.to_csv(folder / "timeline_metrics.csv", index=False)
    np.savez_compressed(
        folder / "timeline_fields.npz",
        fields=result.fields,
        true_centers_lambda=result.true_centers_lambda,
        design_centers_lambda=result.design_centers_lambda,
        x_lambda=result.x_lambda,
        y_lambda=result.y_lambda,
        target_masks=result.target_masks,
    )
    (folder / "summary.json").write_text(json.dumps(result.summary(), ensure_ascii=False, indent=2), encoding="utf-8")
    result.project.save_yaml(folder / "project.yaml")
    animation = make_timeline_animation(result)
    metrics_fig = make_timeline_metrics_figure(result)
    trajectory = make_trajectory_figure(result)
    animation.write_html(folder / "01_timeline_animation.html", include_plotlyjs="directory", full_html=True, config={"displaylogo": False})
    metrics_fig.write_html(folder / "02_timeline_metrics.html", include_plotlyjs="directory", full_html=True, config={"displaylogo": False})
    trajectory.write_html(folder / "03_trajectory.html", include_plotlyjs="directory", full_html=True, config={"displaylogo": False})
    sections = []
    include: str | bool = "inline"
    for title, fig in [("动态时间轴", animation), ("逐帧指标", metrics_fig), ("轨迹", trajectory)]:
        sections.append(f"<section><h2>{title}</h2>{fig.to_html(full_html=False, include_plotlyjs=include, config={'displaylogo': False})}</section>")
        include = False
    report = folder / "HPM_CAE_timeline_report.html"
    report.write_text(
        "<!doctype html><html lang='zh-CN'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'><title>HPM-CAE Timeline</title><style>body{margin:0;background:#07101d;color:#e7eef9;font-family:Inter,Segoe UI,Microsoft YaHei,sans-serif}header,main{max-width:1500px;margin:auto;padding:24px 4vw}section{background:#0d1828;border:1px solid #26354d;border-radius:12px;padding:14px;margin:16px 0}.scope{color:#91a2bb;line-height:1.7}</style></head><body><header><h1>HPM-CAE V1.0 动态时间轴</h1><p>" + result.controller + " · normalized research mode</p></header><main>" + "".join(sections) + "<section><h2>模型边界</h2><p class='scope'>全部位置、场量与响应均为波长尺度和无量纲代理变量，不对应真实功率、器件阈值或现实作用距离。</p></section></main></body></html>",
        encoding="utf-8",
    )
    import shutil
    archive = Path(shutil.make_archive(str(folder), "zip", root_dir=folder))
    return report, archive

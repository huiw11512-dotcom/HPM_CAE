"""V1.3 传播后端对比、可视化与导出。"""
from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
import json
import shutil
import time
from typing import Iterable

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from hpm_platform.physics.field_backends import get_field_backend
from hpm_platform.ui.figures import _ellipse_xy
from hpm_platform.ui.project_model import CAEProject
from hpm_platform.ui.quick_solver import CAESolveResult, solve_project


@dataclass(frozen=True)
class BackendComparisonResult:
    project: CAEProject
    backend_ids: tuple[str, ...]
    results: tuple[CAESolveResult, ...]
    records: pd.DataFrame
    log_lines: tuple[str, ...]

    @property
    def result_map(self) -> dict[str, CAESolveResult]:
        return {backend_id: result for backend_id, result in zip(self.backend_ids, self.results, strict=True)}


def run_backend_comparison(
    project: CAEProject,
    backend_ids: Iterable[str] | None = None,
    *,
    fast_mode: bool = True,
) -> BackendComparisonResult:
    ids = tuple(backend_ids or project.propagation.comparison_backends)
    if not ids:
        raise ValueError("至少选择一个传播后端")
    logs: list[str] = []
    results: list[CAESolveResult] = []
    rows: list[dict[str, object]] = []
    for index, backend_id in enumerate(ids, start=1):
        backend = get_field_backend(backend_id)
        solver = project.solver
        if fast_mode:
            solver = replace(
                solver,
                iterations=min(int(solver.iterations), 100),
                uncertainty_scenarios=min(int(solver.uncertainty_scenarios), 3),
                target_samples=min(int(solver.target_samples), 180),
                outside_samples=min(int(solver.outside_samples), 420),
            )
        candidate = replace(
            project,
            propagation=replace(project.propagation, backend=backend_id),
            solver=solver,
        )
        started = time.perf_counter()
        result = solve_project(candidate)
        elapsed = 1000.0 * (time.perf_counter() - started)
        results.append(result)
        rows.append(
            {
                "传播后端": backend.display_name,
                "后端标识": backend_id,
                "目标区RMSE/%": float(result.metrics["target_rmse_percent"]),
                "最低覆盖率/%": float(result.metrics["minimum_target_coverage_percent"]),
                "区外峰值/dB": float(result.metrics["peak_outside_db"]),
                "保护区最坏超限/dB": float(result.metrics["maximum_protected_violation_db"]),
                "联合判据": bool(result.metrics["control_success"]),
                "运行耗时/ms": float(elapsed),
            }
        )
        logs.append(
            f"[{index}/{len(ids)}] {backend.display_name}：RMSE={result.metrics['target_rmse_percent']:.2f}% · "
            f"区外峰值={result.metrics['peak_outside_db']:.2f} dB · 耗时={elapsed:.1f} ms"
        )
    return BackendComparisonResult(project, ids, tuple(results), pd.DataFrame(rows), tuple(logs))


def make_backend_gallery(comparison: BackendComparisonResult) -> go.Figure:
    count = len(comparison.results)
    columns = 2
    rows = int(np.ceil(count / columns))
    titles = [get_field_backend(item).display_name for item in comparison.backend_ids]
    fig = make_subplots(rows=rows, cols=columns, subplot_titles=titles, horizontal_spacing=0.08, vertical_spacing=0.12)
    for index, result in enumerate(comparison.results):
        row = index // columns + 1
        col = index % columns + 1
        field_db = np.clip(result.field_db, -30.0, 3.0)
        fig.add_trace(
            go.Heatmap(
                x=result.x_lambda,
                y=result.y_lambda,
                z=field_db,
                zmin=-30,
                zmax=3,
                colorscale="Turbo",
                showscale=index == count - 1,
                colorbar={"title": "相对幅度/dB", "len": 0.72},
                hovertemplate="x=%{x:.2f}λ<br>y=%{y:.2f}λ<br>幅度=%{z:.2f} dB<extra></extra>",
            ),
            row=row,
            col=col,
        )
        for target in result.project.targets:
            x, y = _ellipse_xy(
                target.center_x_lambda,
                target.center_y_lambda,
                target.semi_major_lambda,
                target.semi_minor_lambda,
                target.rotation_deg,
            )
            fig.add_trace(
                go.Scatter(x=x, y=y, mode="lines", line={"color": "white", "width": 2}, showlegend=False, hoverinfo="skip"),
                row=row,
                col=col,
            )
        fig.update_xaxes(title_text="x/λ", scaleanchor=f"y{index + 1}" if index else "y", scaleratio=1, row=row, col=col)
        fig.update_yaxes(title_text="y/λ", row=row, col=col)
    fig.update_layout(
        title="插件式传播后端：同一工程的场分布对比",
        template="plotly_white",
        height=max(520, 430 * rows),
        margin={"l": 55, "r": 40, "t": 75, "b": 45},
        legend={"orientation": "h", "y": -0.08},
    )
    return fig


def make_backend_metrics_figure(comparison: BackendComparisonResult) -> go.Figure:
    frame = comparison.records
    fig = make_subplots(rows=1, cols=2, subplot_titles=("目标区RMSE", "运行耗时"))
    fig.add_trace(
        go.Bar(x=frame["传播后端"], y=frame["目标区RMSE/%"], text=frame["目标区RMSE/%"].map(lambda x: f"{x:.2f}%"), textposition="outside", name="RMSE"),
        row=1, col=1,
    )
    fig.add_trace(
        go.Bar(x=frame["传播后端"], y=frame["运行耗时/ms"], text=frame["运行耗时/ms"].map(lambda x: f"{x:.0f}ms"), textposition="outside", name="耗时"),
        row=1, col=2,
    )
    fig.update_layout(title="传播后端性能概览", template="plotly_white", height=460, showlegend=False, margin={"l": 55, "r": 30, "t": 75, "b": 110})
    fig.update_xaxes(tickangle=-18)
    fig.update_yaxes(title_text="RMSE/%", row=1, col=1)
    fig.update_yaxes(title_text="耗时/ms", row=1, col=2)
    return fig


def make_propagation_mechanism_figure(project: CAEProject) -> go.Figure:
    """交互式机理预览；高质量生成图由外部 image2 接口替换。"""
    array = project.array.build_array()
    positions = array.positions_m / array.wavelength_m
    target = project.target
    focus = np.array([target.center_x_lambda, target.center_y_lambda, project.plane.z_lambda])
    fig = go.Figure()
    fig.add_trace(go.Scatter3d(x=positions[:, 0], y=positions[:, 1], z=positions[:, 2], mode="markers", name="相控阵", marker={"size": 4, "symbol": "square"}))
    fig.add_trace(go.Scatter3d(x=[0, focus[0]], y=[0, focus[1]], z=[0, focus[2]], mode="lines+markers", name="直达传播", line={"width": 6}))
    for reflector in project.active_reflectors:
        axis = reflector.axis
        coordinate = reflector.coordinate_lambda
        if axis == "x":
            x = [coordinate] * 4
            y = [-4, 4, 4, -4]
            z = [0, 0, project.plane.z_lambda, project.plane.z_lambda]
            image_origin = np.array([2 * coordinate, 0.0, 0.0])
        elif axis == "y":
            x = [-4, 4, 4, -4]
            y = [coordinate] * 4
            z = [0, 0, project.plane.z_lambda, project.plane.z_lambda]
            image_origin = np.array([0.0, 2 * coordinate, 0.0])
        else:
            continue
        fig.add_trace(go.Mesh3d(x=x, y=y, z=z, opacity=0.18, name=f"反射面：{reflector.name}", alphahull=0))
        reflection_point = 0.5 * (image_origin + focus)
        if axis == "x": reflection_point[0] = coordinate
        if axis == "y": reflection_point[1] = coordinate
        fig.add_trace(go.Scatter3d(x=[0, reflection_point[0], focus[0]], y=[0, reflection_point[1], focus[1]], z=[0, reflection_point[2], focus[2]], mode="lines", name="镜像反射路径", line={"dash": "dash", "width": 5}))
    for cavity in project.active_cavities:
        cx, cy, cz = cavity.center_x_lambda, cavity.center_y_lambda, cavity.center_z_lambda
        sx, sy, sz = cavity.size_x_lambda / 2, cavity.size_y_lambda / 2, cavity.size_z_lambda / 2
        vertices = np.array([[cx+dx*sx, cy+dy*sy, cz+dz*sz] for dx in (-1,1) for dy in (-1,1) for dz in (-1,1)])
        fig.add_trace(go.Scatter3d(x=vertices[:,0], y=vertices[:,1], z=vertices[:,2], mode="markers", name=f"降阶腔体：{cavity.name}", marker={"size": 4, "symbol": "diamond"}))
    for aperture in project.active_apertures:
        fig.add_trace(go.Scatter3d(x=[aperture.center_x_lambda], y=[aperture.center_y_lambda], z=[aperture.center_z_lambda], mode="markers", name=f"孔缝：{aperture.name}", marker={"size": 9, "symbol": "circle-open"}))
        fig.add_trace(go.Scatter3d(x=[0, aperture.center_x_lambda], y=[0, aperture.center_y_lambda], z=[0, aperture.center_z_lambda], mode="lines", name="孔缝耦合路径", line={"dash": "dot", "width": 5}))
    fig.update_layout(
        title="传播机理交互预览：直达、镜像反射与孔缝—腔体降阶通道",
        template="plotly_white",
        height=650,
        scene={
            "xaxis_title": "x/λ", "yaxis_title": "y/λ", "zaxis_title": "z/λ",
            "aspectmode": "data",
            "camera": {"eye": {"x": 1.55, "y": 1.35, "z": 1.0}},
        },
        margin={"l": 10, "r": 10, "t": 70, "b": 10},
    )
    return fig


def export_backend_comparison(comparison: BackendComparisonResult, root: str | Path) -> tuple[Path, Path, Path]:
    root_path = Path(root)
    root_path.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    folder = root_path / f"传播后端对比_{stamp}"
    if folder.exists():
        shutil.rmtree(folder)
    folder.mkdir(parents=True)
    comparison.project.save_yaml(folder / "工程配置.yaml")
    comparison.records.to_csv(folder / "传播后端对比.csv", index=False, encoding="utf-8-sig")
    (folder / "运行日志.txt").write_text("\n".join(comparison.log_lines), encoding="utf-8")
    gallery = make_backend_gallery(comparison)
    metrics = make_backend_metrics_figure(comparison)
    mechanism = make_propagation_mechanism_figure(comparison.project)
    sections = []
    include = "inline"
    for title, figure in (("场分布对比", gallery), ("性能概览", metrics), ("传播机理", mechanism)):
        sections.append(f"<section><h2>{title}</h2>{figure.to_html(full_html=False, include_plotlyjs=include, config={'displaylogo': False})}</section>")
        include = False
    report = folder / "传播后端对比报告.html"
    report.write_text(
        "<!doctype html><html lang='zh-CN'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>"
        "<title>传播后端对比报告</title><style>body{font-family:'Microsoft YaHei',sans-serif;margin:0;background:#f4f7fb;color:#1f2937}"
        "header{padding:28px 5vw;background:white;border-bottom:1px solid #e5e7eb}main{max-width:1500px;margin:auto;padding:24px}"
        "section{background:white;border:1px solid #e5e7eb;border-radius:12px;padding:18px;margin:18px 0}</style></head><body>"
        f"<header><h1>插件式传播后端对比报告</h1><p>{comparison.project.meta.name} · {datetime.now(timezone.utc).isoformat()}</p></header>"
        f"<main>{''.join(sections)}<section><h2>数据表</h2>{comparison.records.to_html(index=False)}</section>"
        "<section><h2>模型边界</h2><p>所有量均为波长尺度、归一化标量场与无量纲代理量，不对应真实功率、器件阈值、毁伤概率或作用距离。</p></section></main></body></html>",
        encoding="utf-8",
    )
    manifest = {
        "平台": "HPM 数字化电磁算法 CAE",
        "版本": "1.3.0",
        "创建时间": datetime.now(timezone.utc).isoformat(),
        "传播后端": list(comparison.backend_ids),
        "模型边界": comparison.project.model_scope,
    }
    (folder / "清单.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    archive = Path(shutil.make_archive(str(folder), "zip", root_dir=folder))
    return folder, report, archive

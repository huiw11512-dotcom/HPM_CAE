"""Plotly figures and standalone report rendering for the V1.2 workbench."""
from __future__ import annotations

from html import escape
from pathlib import Path
from typing import Iterable

import numpy as np
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from hpm_platform.ui.project_model import CAEProject
from hpm_platform.ui.quick_solver import CAESolveResult

BG = "#07101d"
PANEL = "#0d1828"
GRID = "#26354d"
TEXT = "#e7eef9"
MUTED = "#91a2bb"
CYAN = "#35d8ff"
AMBER = "#ffc857"
GREEN = "#4ee0a5"
RED = "#ff6b7a"
PURPLE = "#ab8cff"


def _base_layout(title: str, *, height: int = 560) -> dict:
    return {
        "title": {"text": title, "x": 0.02, "xanchor": "left", "font": {"size": 18, "color": TEXT}},
        "paper_bgcolor": BG,
        "plot_bgcolor": PANEL,
        "font": {"family": "Inter, Segoe UI, Microsoft YaHei, sans-serif", "color": TEXT},
        "margin": {"l": 55, "r": 30, "t": 62, "b": 52},
        "height": height,
        "hoverlabel": {"bgcolor": PANEL, "font": {"color": TEXT}},
        "legend": {"bgcolor": "rgba(7,16,29,0.72)", "bordercolor": GRID, "borderwidth": 1},
    }


def _ellipse_xy(
    center_x: float,
    center_y: float,
    semi_major: float,
    semi_minor: float,
    rotation_deg: float,
    points: int = 241,
) -> tuple[np.ndarray, np.ndarray]:
    angle = np.linspace(0.0, 2.0 * np.pi, points)
    c = np.cos(np.deg2rad(rotation_deg))
    s = np.sin(np.deg2rad(rotation_deg))
    x0 = semi_major * np.cos(angle)
    y0 = semi_minor * np.sin(angle)
    return center_x + c * x0 - s * y0, center_y + s * x0 + c * y0


def _add_plane_region_lines(fig: go.Figure, project: CAEProject, *, row=None, col=None) -> None:
    kwargs = {} if row is None else {"row": row, "col": col}
    for index, target in enumerate(project.targets):
        x, y = _ellipse_xy(
            target.center_x_lambda, target.center_y_lambda, target.semi_major_lambda,
            target.semi_minor_lambda, target.rotation_deg,
        )
        label = target.name or target.object_id
        fig.add_trace(
            go.Scatter(
                x=x, y=y, mode="lines", name=f"目标区 · {label}",
                line={"color": AMBER, "width": 3 if index == 0 else 2},
                hovertemplate=f"{label}<extra></extra>",
            ), **kwargs,
        )
        gx, gy = _ellipse_xy(
            target.center_x_lambda, target.center_y_lambda,
            target.semi_major_lambda * target.guard_scale,
            target.semi_minor_lambda * target.guard_scale, target.rotation_deg,
        )
        fig.add_trace(
            go.Scatter(
                x=gx, y=gy, mode="lines", name=f"过渡区 · {label}",
                line={"color": AMBER, "width": 1.2, "dash": "dot"},
                hovertemplate=f"{label} 过渡区<extra></extra>", showlegend=index == 0,
            ), **kwargs,
        )
    for index, zone in enumerate(project.protected_zones):
        px, py = _ellipse_xy(zone.center_x_lambda, zone.center_y_lambda, zone.radius_lambda, zone.radius_lambda, 0.0)
        label = zone.name or zone.object_id
        fig.add_trace(
            go.Scatter(
                x=px, y=py, mode="lines", name=f"保护区 · {label}",
                line={"color": GREEN, "width": 3 if index == 0 else 2},
                fill="toself", fillcolor="rgba(78,224,165,0.07)",
                hovertemplate=f"{label}<extra></extra>",
            ), **kwargs,
        )


def make_scene_figure(project: CAEProject) -> go.Figure:
    """Create an interactive 3-D wavelength-scaled geometry view."""
    array = project.array.build_array()
    positions = array.positions_m / array.wavelength_m
    half_x = project.plane.span_x_lambda / 2.0
    half_y = project.plane.span_y_lambda / 2.0
    z = project.plane.z_lambda

    fig = go.Figure()
    fig.add_trace(
        go.Scatter3d(
            x=positions[:, 0],
            y=positions[:, 1],
            z=positions[:, 2],
            mode="markers",
            name=f"阵元 ({array.n_elements})",
            marker={
                "size": 5,
                "color": CYAN,
                "line": {"color": "#d9f8ff", "width": 0.7},
                "symbol": "square",
            },
            hovertemplate="阵元<br>x=%{x:.2f}λ<br>y=%{y:.2f}λ<extra></extra>",
        )
    )
    rect_x = np.array([-half_x, half_x, half_x, -half_x, -half_x])
    rect_y = np.array([-half_y, -half_y, half_y, half_y, -half_y])
    fig.add_trace(
        go.Scatter3d(
            x=rect_x,
            y=rect_y,
            z=np.full_like(rect_x, z),
            mode="lines",
            name="观察面",
            line={"color": MUTED, "width": 4, "dash": "dash"},
            hovertemplate="观察面 z=%{z:.2f}λ<extra></extra>",
        )
    )

    for index, target in enumerate(project.targets):
        tx, ty = _ellipse_xy(
            target.center_x_lambda, target.center_y_lambda, target.semi_major_lambda,
            target.semi_minor_lambda, target.rotation_deg,
        )
        label = target.name or target.object_id
        fig.add_trace(
            go.Scatter3d(
                x=tx, y=ty, z=np.full_like(tx, z), mode="lines",
                name=f"目标区 · {label}", line={"color": AMBER, "width": 7 if index == 0 else 5},
                hovertemplate=f"{label}<extra></extra>",
            )
        )
        fig.add_trace(
            go.Scatter3d(
                x=[0.0, target.center_x_lambda], y=[0.0, target.center_y_lambda], z=[0.0, z],
                mode="lines+markers", name=f"指向 · {label}",
                line={"color": AMBER, "width": 3}, marker={"size": [3, 6], "color": [CYAN, AMBER]},
                hovertemplate="(%{x:.2f}, %{y:.2f}, %{z:.2f})λ<extra></extra>",
                showlegend=index == 0,
            )
        )
    for index, zone in enumerate(project.protected_zones):
        px, py = _ellipse_xy(zone.center_x_lambda, zone.center_y_lambda, zone.radius_lambda, zone.radius_lambda, 0.0)
        label = zone.name or zone.object_id
        fig.add_trace(
            go.Scatter3d(
                x=px, y=py, z=np.full_like(px, z), mode="lines",
                name=f"保护区 · {label}", line={"color": GREEN, "width": 7 if index == 0 else 5},
                hovertemplate=f"{label}<extra></extra>",
            )
        )

    # V1.3 环境几何：反射面、孔缝与降阶腔体。
    for reflector in project.active_reflectors:
        coordinate = float(reflector.coordinate_lambda)
        if reflector.axis == "x":
            vertices = np.array([
                [coordinate, -half_y, 0.0], [coordinate, half_y, 0.0],
                [coordinate, half_y, z], [coordinate, -half_y, z],
            ])
        elif reflector.axis == "y":
            vertices = np.array([
                [-half_x, coordinate, 0.0], [half_x, coordinate, 0.0],
                [half_x, coordinate, z], [-half_x, coordinate, z],
            ])
        else:
            vertices = np.array([
                [-half_x, -half_y, coordinate], [half_x, -half_y, coordinate],
                [half_x, half_y, coordinate], [-half_x, half_y, coordinate],
            ])
        fig.add_trace(
            go.Mesh3d(
                x=vertices[:, 0], y=vertices[:, 1], z=vertices[:, 2],
                i=[0, 0], j=[1, 2], k=[2, 3], opacity=0.18,
                name=f"反射面 · {reflector.name}", color=PURPLE,
                hovertemplate=f"{reflector.name}<br>{reflector.axis}={coordinate:.2f}λ<extra></extra>",
            )
        )
    for cavity in project.active_cavities:
        cx, cy, cz = cavity.center_x_lambda, cavity.center_y_lambda, cavity.center_z_lambda
        sx, sy, sz = cavity.size_x_lambda / 2.0, cavity.size_y_lambda / 2.0, cavity.size_z_lambda / 2.0
        vertices = np.array([[cx + dx * sx, cy + dy * sy, cz + dz * sz] for dx in (-1, 1) for dy in (-1, 1) for dz in (-1, 1)])
        i = [0,0,0,0,1,1,2,2,3,3,4,4]
        j = [1,2,4,3,3,5,3,6,1,7,5,6]
        k = [3,3,5,4,7,7,6,7,7,5,7,7]
        fig.add_trace(
            go.Mesh3d(
                x=vertices[:,0], y=vertices[:,1], z=vertices[:,2], i=i, j=j, k=k,
                opacity=0.14, name=f"降阶腔体 · {cavity.name}", color=GREEN,
                hovertemplate=f"{cavity.name}<br>{cavity.size_x_lambda:.2f}×{cavity.size_y_lambda:.2f}×{cavity.size_z_lambda:.2f}λ<extra></extra>",
            )
        )
    for aperture in project.active_apertures:
        fig.add_trace(
            go.Scatter3d(
                x=[aperture.center_x_lambda], y=[aperture.center_y_lambda], z=[aperture.center_z_lambda],
                mode="markers", name=f"孔缝 · {aperture.name}",
                marker={"size": 9, "symbol": "circle-open", "color": RED, "line": {"width": 2}},
                hovertemplate=f"{aperture.name}<br>半径={aperture.radius_lambda:.3f}λ<extra></extra>",
            )
        )

    layout = _base_layout("三维场景、阵列与环境几何", height=620)
    layout["scene"] = {
        "bgcolor": PANEL,
        "xaxis": {"title": "x / λ", "gridcolor": GRID, "zerolinecolor": GRID, "showbackground": True, "backgroundcolor": PANEL},
        "yaxis": {"title": "y / λ", "gridcolor": GRID, "zerolinecolor": GRID, "showbackground": True, "backgroundcolor": PANEL},
        "zaxis": {"title": "z / λ", "gridcolor": GRID, "zerolinecolor": GRID, "showbackground": True, "backgroundcolor": PANEL},
        "aspectmode": "manual",
        "aspectratio": {"x": 1.0, "y": 0.85, "z": 1.0},
        "camera": {"eye": {"x": 1.5, "y": 1.45, "z": 1.05}},
    }
    layout["uirevision"] = "scene-v13"
    fig.update_layout(**layout)
    return fig


def make_field_figure(result: CAESolveResult) -> go.Figure:
    field_db = np.clip(result.field_db, -36.0, 4.0)
    fig = go.Figure(
        go.Heatmap(
            x=result.x_lambda,
            y=result.y_lambda,
            z=field_db,
            zmin=-30,
            zmax=3,
            colorscale=[
                [0.0, "#07101d"],
                [0.20, "#17345a"],
                [0.45, "#126a8a"],
                [0.68, "#25c7bd"],
                [0.84, "#f0c75e"],
                [1.0, "#ff6b5f"],
            ],
            colorbar={"title": {"text": "幅度 / dB", "font": {"color": TEXT}}, "tickfont": {"color": TEXT}},
            hovertemplate="x=%{x:.2f}λ<br>y=%{y:.2f}λ<br>相对幅度=%{z:.2f} dB<extra></extra>",
        )
    )
    _add_plane_region_lines(fig, result.project)
    fig.update_layout(**_base_layout(f"观察面场分布 · {result.project.solver.method}", height=590))
    fig.update_xaxes(title="x / λ", gridcolor=GRID, zerolinecolor=GRID, scaleanchor="y", scaleratio=1)
    fig.update_yaxes(title="y / λ", gridcolor=GRID, zerolinecolor=GRID)
    fig.update_layout(uirevision="field-v11")
    return fig


def make_cut_figure(result: CAESolveResult) -> go.Figure:
    y_index = int(np.argmin(np.abs(result.y_lambda - result.project.target.center_y_lambda)))
    amplitude = np.abs(result.field[y_index, :])
    target = result.project.solver.target_amplitude
    fig = go.Figure()
    fig.add_trace(
        go.Scatter(
            x=result.x_lambda,
            y=amplitude,
            mode="lines",
            name=f"y={result.y_lambda[y_index]:.2f}λ 截线",
            line={"color": CYAN, "width": 3},
            hovertemplate="x=%{x:.2f}λ<br>|E|=%{y:.3f}<extra></extra>",
        )
    )
    fig.add_hrect(
        y0=0.9 * target,
        y1=1.1 * target,
        fillcolor="rgba(255,200,87,0.15)",
        line_width=0,
        annotation_text="目标 ±10%",
        annotation_font_color=AMBER,
    )
    fig.add_hline(y=target, line={"color": AMBER, "dash": "dash", "width": 2})
    fig.update_layout(**_base_layout("目标中心横向截线", height=470))
    fig.update_xaxes(title="x / λ", gridcolor=GRID, zerolinecolor=GRID)
    fig.update_yaxes(title="归一化幅度", gridcolor=GRID, zerolinecolor=GRID, rangemode="tozero")
    return fig


def make_far_field_figure(result: CAESolveResult) -> go.Figure:
    response = np.asarray(result.far_field, dtype=float)
    response_db = 20.0 * np.log10(np.maximum(response, 1e-5))
    fig = go.Figure(
        go.Heatmap(
            x=result.u,
            y=result.v,
            z=np.clip(response_db, -40.0, 0.0),
            zmin=-35,
            zmax=0,
            colorscale="Turbo",
            colorbar={"title": "dB"},
            hovertemplate="u=%{x:.2f}<br>v=%{y:.2f}<br>响应=%{z:.2f} dB<extra></extra>",
        )
    )
    angle = np.linspace(0, 2 * np.pi, 361)
    fig.add_trace(
        go.Scatter(
            x=np.cos(angle),
            y=np.sin(angle),
            mode="lines",
            line={"color": "rgba(231,238,249,0.65)", "width": 1.5},
            name="可见域",
            hoverinfo="skip",
        )
    )
    fig.update_layout(**_base_layout("归一化远场方向余弦图", height=540))
    fig.update_xaxes(title="u", gridcolor=GRID, zerolinecolor=GRID, scaleanchor="y", scaleratio=1)
    fig.update_yaxes(title="v", gridcolor=GRID, zerolinecolor=GRID)
    return fig


def make_weights_figure(result: CAESolveResult) -> go.Figure:
    nx = result.project.array.nx
    ny = result.project.array.ny
    amplitude = np.abs(result.actual_weights).reshape(nx, ny)
    phase = np.rad2deg(np.angle(result.actual_weights)).reshape(nx, ny)
    fig = make_subplots(
        rows=1,
        cols=2,
        subplot_titles=("实际阵元幅度", "实际阵元相位 / °"),
        horizontal_spacing=0.13,
    )
    fig.add_trace(
        go.Heatmap(
            z=amplitude,
            x=np.arange(ny),
            y=np.arange(nx),
            colorscale="Viridis",
            colorbar={"x": 0.46, "len": 0.78, "title": "幅度"},
            hovertemplate="x阵元=%{y}<br>y阵元=%{x}<br>幅度=%{z:.3f}<extra></extra>",
        ),
        row=1,
        col=1,
    )
    fig.add_trace(
        go.Heatmap(
            z=phase,
            x=np.arange(ny),
            y=np.arange(nx),
            zmin=-180,
            zmax=180,
            colorscale="Twilight",
            colorbar={"x": 1.02, "len": 0.78, "title": "°"},
            hovertemplate="x阵元=%{y}<br>y阵元=%{x}<br>相位=%{z:.1f}°<extra></extra>",
        ),
        row=1,
        col=2,
    )
    fig.update_layout(**_base_layout("阵元激励检查器", height=500))
    fig.update_xaxes(title="y 阵元索引", gridcolor=GRID)
    fig.update_yaxes(title="x 阵元索引", gridcolor=GRID, autorange="reversed")
    return fig


def make_convergence_figure(result: CAESolveResult) -> go.Figure:
    fig = go.Figure()
    if result.objective_history.size:
        fig.add_trace(
            go.Scatter(
                x=np.arange(1, result.objective_history.size + 1),
                y=np.maximum(result.objective_history, 1e-12),
                mode="lines",
                line={"color": PURPLE, "width": 3.0},
                name="总目标",
                hovertemplate="迭代=%{x}<br>目标=%{y:.5g}<extra></extra>",
            )
        )
        if result.objective_component_history.size:
            component_colors = [CYAN, AMBER, RED, GREEN, MUTED]
            for index, label in enumerate(result.objective_component_labels[:-1]):
                values = np.maximum(result.objective_component_history[:, index], 1e-12)
                fig.add_trace(
                    go.Scatter(
                        x=np.arange(1, values.size + 1), y=values, mode="lines",
                        name=label, line={"color": component_colors[index % len(component_colors)], "width": 1.4, "dash": "dot"},
                        hovertemplate=f"{label}<br>迭代=%{{x}}<br>分量=%{{y:.5g}}<extra></extra>",
                    )
                )
        fig.update_yaxes(type="log")
    else:
        fig.add_annotation(
            text="当前求解器没有迭代历史", x=0.5, y=0.5, xref="paper", yref="paper",
            showarrow=False, font={"size": 18, "color": MUTED},
        )
    fig.update_layout(**_base_layout("求解收敛与约束分量", height=460))
    fig.update_xaxes(title="迭代步", gridcolor=GRID, zerolinecolor=GRID)
    fig.update_yaxes(title="目标函数", gridcolor=GRID, zerolinecolor=GRID)
    return fig


def make_constraint_margin_figure(result: CAESolveResult) -> go.Figure:
    """Visualize signed object/outside constraint margin; positive means pass."""
    amplitude = np.abs(result.field)
    reference = max(float(result.project.solver.target_amplitude), 1e-12)
    margin = np.full(amplitude.shape, np.nan, dtype=float)
    outside_cap = reference * 10.0 ** (float(result.project.solver.outside_peak_limit_db) / 20.0)
    margin[result.outside_mask] = (outside_cap - amplitude[result.outside_mask]) / reference
    for item, mask in zip(result.project.targets, result.target_component_masks, strict=True):
        setpoint = reference * float(item.amplitude_scale)
        tolerance = float(item.tolerance_percent) / 100.0
        margin[np.asarray(mask, bool)] = tolerance - np.abs(amplitude[np.asarray(mask, bool)] / setpoint - 1.0)
    for item, mask in zip(result.project.protected_zones, result.protected_component_masks, strict=True):
        cap = reference * float(item.max_amplitude_scale)
        margin[np.asarray(mask, bool)] = (cap - amplitude[np.asarray(mask, bool)]) / reference
    fig = go.Figure(
        go.Heatmap(
            x=result.x_lambda, y=result.y_lambda, z=100.0 * np.clip(margin, -0.45, 0.45),
            zmin=-30, zmax=30, zmid=0, colorscale="RdBu",
            colorbar={"title": "约束裕量 / %"},
            hovertemplate="x=%{x:.2f}λ<br>y=%{y:.2f}λ<br>裕量=%{z:.2f}%<extra></extra>",
        )
    )
    _add_plane_region_lines(fig, result.project)
    fig.update_layout(**_base_layout("对象约束裕量图 · 蓝色通过 / 红色超限", height=590))
    fig.update_xaxes(title="x / λ", gridcolor=GRID, scaleanchor="y", scaleratio=1)
    fig.update_yaxes(title="y / λ", gridcolor=GRID)
    return fig


def make_object_metrics_figure(result: CAESolveResult) -> go.Figure:
    """Show target fairness and protected-zone cap compliance by object."""
    frame = result.object_metrics_frame()
    targets = frame[frame["object_type"] == "target"]
    protected = frame[frame["object_type"] == "protected"]
    fig = make_subplots(rows=1, cols=2, subplot_titles=("目标对象：RMSE 与覆盖率", "保护对象：P95 与上限"), horizontal_spacing=0.14)
    if not targets.empty:
        fig.add_trace(go.Bar(x=targets["object_id"], y=targets["rmse_percent"], name="RMSE / %", marker={"color": AMBER}, hovertemplate="%{x}<br>RMSE=%{y:.2f}%<extra></extra>"), row=1, col=1)
        fig.add_trace(go.Scatter(x=targets["object_id"], y=targets["coverage_percent"], name="覆盖率 / %", mode="lines+markers", line={"color": CYAN, "width": 3}, marker={"size": 9}, hovertemplate="%{x}<br>覆盖率=%{y:.1f}%<extra></extra>"), row=1, col=1)
    if not protected.empty:
        fig.add_trace(go.Bar(x=protected["object_id"], y=protected["p95_db"], name="保护区 P95 / dB", marker={"color": GREEN}, hovertemplate="%{x}<br>P95=%{y:.2f} dB<extra></extra>"), row=1, col=2)
        fig.add_trace(go.Scatter(x=protected["object_id"], y=protected["limit_db"], name="上限 / dB", mode="lines+markers", line={"color": RED, "width": 2.5, "dash": "dash"}, marker={"size": 8}, hovertemplate="%{x}<br>上限=%{y:.2f} dB<extra></extra>"), row=1, col=2)
    else:
        fig.add_annotation(text="当前场景无启用保护区", x=0.78, y=0.5, xref="paper", yref="paper", showarrow=False, font={"color": MUTED})
    fig.update_layout(**_base_layout("对象级公平性与约束检查器", height=480), barmode="group")
    fig.update_xaxes(gridcolor=GRID)
    fig.update_yaxes(gridcolor=GRID)
    return fig


def make_empty_result_figure(title: str, message: str) -> go.Figure:
    fig = go.Figure()
    fig.add_annotation(
        text=message,
        x=0.5,
        y=0.5,
        xref="paper",
        yref="paper",
        showarrow=False,
        align="center",
        font={"size": 18, "color": MUTED},
    )
    fig.update_xaxes(visible=False)
    fig.update_yaxes(visible=False)
    fig.update_layout(**_base_layout(title, height=520))
    return fig


def make_metric_cards_html(result: CAESolveResult) -> str:
    m = result.metrics
    success = bool(m["control_success"])
    status_class = "ok" if success else "warn"
    status_text = "通过" if success else "需调参"
    protected_violation = float(m.get("maximum_protected_violation_db", float("nan")))
    protected_text = "—" if not np.isfinite(protected_violation) else f"{protected_violation:+.2f} dB"
    cards = [
        ("总体 RMSE", f"{m['target_rmse_percent']:.2f}%", "目标并集"),
        ("最差目标 RMSE", f"{m.get('worst_target_rmse_percent', m['target_rmse_percent']):.2f}%", "公平性检查"),
        ("最低覆盖率", f"{m.get('minimum_target_coverage_percent', m['target_coverage_percent']):.1f}%", "对象级容差"),
        ("区外峰值", f"{m['peak_outside_db']:.2f} dB", f"上限 {m.get('outside_peak_limit_db', -2.0):.1f} dB"),
        ("保护区最坏超限", protected_text, "≤0 dB 为满足"),
        ("求解耗时", f"{m['solver_runtime_ms']:.1f} ms", str(m["method"])),
    ]
    card_html = "".join(
        f'<div class="metric-card"><span>{escape(label)}</span><strong>{escape(value)}</strong><small>{escape(note)}</small></div>'
        for label, value, note in cards
    )
    return '<div class="metric-grid">' + card_html + f'<div class="metric-card status {status_class}"><span>联合判据</span><strong>{status_text}</strong><small>归一化算法判据</small></div>' + "</div>"


def write_standalone_report(
    result: CAESolveResult,
    figures: Iterable[tuple[str, go.Figure]],
    path: str | Path,
) -> Path:
    """Write a self-contained HTML report with embedded Plotly JavaScript."""
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    figure_sections: list[str] = []
    include_js: str | bool = "inline"
    for title, figure in figures:
        body = figure.to_html(full_html=False, include_plotlyjs=include_js, config={"displaylogo": False})
        include_js = False
        figure_sections.append(f"<section><h2>{escape(title)}</h2>{body}</section>")
    metrics_html = result.metrics_frame().to_html(index=False, border=0, classes="metrics")
    object_metrics_html = result.object_metrics_frame().to_html(index=False, border=0, classes="metrics", float_format=lambda value: f"{value:.4g}")
    html = f"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{escape(result.project.meta.name)} · HPM-CAE V1.3</title>
<style>
body{{margin:0;background:{BG};color:{TEXT};font-family:Inter,'Segoe UI','Microsoft YaHei',sans-serif}}
header{{padding:28px 5vw;border-bottom:1px solid {GRID};background:linear-gradient(115deg,#0c1a2e,#07101d)}}
main{{max-width:1500px;margin:auto;padding:24px 4vw 60px}}h1{{margin:0 0 8px}}h2{{margin:0 0 10px}}
.badge{{display:inline-block;padding:5px 10px;border-radius:999px;background:rgba(53,216,255,.12);color:{CYAN};border:1px solid rgba(53,216,255,.35)}}
section{{background:{PANEL};border:1px solid {GRID};border-radius:14px;padding:16px;margin:18px 0;box-shadow:0 10px 30px rgba(0,0,0,.16)}}
.metrics{{width:100%;border-collapse:collapse}}.metrics th,.metrics td{{padding:11px;border-bottom:1px solid {GRID};text-align:left}}
.scope{{color:{MUTED};line-height:1.7}}code{{color:{CYAN}}}
</style></head><body>
<header><span class="badge">归一化数值研究模式</span><h1>{escape(result.project.meta.name)}</h1><p>{escape(str(result.metrics['method']))} · {escape(str(result.metrics.get('propagation_backend_name', '自由空间标量格林')))} · {result.project.array.nx}×{result.project.array.ny} 阵列 · {result.project.array.frequency_ghz:.3f} GHz</p></header>
<main><section><h2>关键指标</h2>{metrics_html}</section><section><h2>对象级约束</h2>{object_metrics_html}</section>{''.join(figure_sections)}
<section><h2>模型边界</h2><p class="scope">{escape(result.project.model_scope)}。本报告中的场量、阈值和控制判据均为无量纲数值研究变量，不对应真实源功率、器件毁伤概率或现实作用距离。</p></section></main>
</body></html>"""
    destination.write_text(html, encoding="utf-8")
    return destination

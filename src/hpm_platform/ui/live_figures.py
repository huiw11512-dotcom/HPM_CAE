"""Plotly diagnostics for the V1.2 live sensing and receive-protection chain."""
from __future__ import annotations

from html import escape

import numpy as np
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from hpm_platform.ui.figures import AMBER, BG, CYAN, GREEN, GRID, MUTED, PANEL, PURPLE, RED, TEXT
from hpm_platform.ui.live_chain import LivePerceptionResult, LiveProtectionResult


def _layout(title: str, height: int = 520) -> dict:
    return {
        "title": {"text": title, "x": 0.02, "font": {"size": 18}},
        "paper_bgcolor": BG,
        "plot_bgcolor": PANEL,
        "font": {"family": "Inter, Segoe UI, Microsoft YaHei, sans-serif", "color": TEXT},
        "margin": {"l": 58, "r": 28, "t": 65, "b": 55},
        "height": height,
        "hoverlabel": {"bgcolor": PANEL, "font": {"color": TEXT}},
        "legend": {"bgcolor": "rgba(7,16,29,.72)", "bordercolor": GRID, "borderwidth": 1},
    }


def make_perception_spectrum(result: LivePerceptionResult) -> go.Figure:
    spectrum_db = 10.0 * np.log10(np.maximum(result.spectrum / max(float(np.max(result.spectrum)), 1e-15), 1e-8))
    fig = go.Figure(
        go.Heatmap(
            x=result.phi_grid_deg,
            y=result.theta_grid_deg,
            z=spectrum_db,
            zmin=-35,
            zmax=0,
            colorscale="Turbo",
            colorbar={"title": "归一化谱/dB"},
            hovertemplate="φ=%{x:.1f}°<br>θ=%{y:.1f}°<br>P=%{z:.2f} dB<extra></extra>",
        )
    )
    truth_theta = [value[0] for value in result.truths]
    truth_phi = [value[1] for value in result.truths]
    est_theta = [value[0] for value in result.estimates]
    est_phi = [value[1] for value in result.estimates]
    fig.add_trace(go.Scatter(x=truth_phi, y=truth_theta, mode="markers", name="数值真值", marker={"symbol": "x", "size": 14, "color": GREEN, "line": {"width": 2}}))
    fig.add_trace(go.Scatter(x=est_phi, y=est_theta, mode="markers+text", name=result.metrics["method"], text=[f"E{i+1}" for i in range(len(est_theta))], textposition="top center", marker={"symbol": "circle-open", "size": 15, "color": AMBER, "line": {"width": 3}}))
    fig.update_layout(**_layout(f"实时二维空间谱 · {result.metrics['method']}", 560))
    fig.update_xaxes(title="方位角 φ / °", gridcolor=GRID)
    fig.update_yaxes(title="极角 θ / °", gridcolor=GRID)
    return fig


def make_perception_diagnostics(result: LivePerceptionResult) -> go.Figure:
    fig = make_subplots(rows=1, cols=2, subplot_titles=("协方差特征值", "阵元可靠度"), horizontal_spacing=0.13)
    eig = np.maximum(np.real(result.eigenvalues), 1e-15)
    eig_db = 10.0 * np.log10(eig / max(float(eig[0]), 1e-15))
    fig.add_trace(go.Bar(x=np.arange(1, eig_db.size + 1), y=eig_db, marker={"color": CYAN}, name="特征值"), row=1, col=1)
    reliability = np.asarray(result.sensor_reliability).reshape(result.project.array.nx, result.project.array.ny)
    fig.add_trace(go.Heatmap(z=reliability, zmin=0, zmax=1, colorscale="Viridis", colorbar={"title": "可靠度", "x": 1.02}, hovertemplate="x=%{y}<br>y=%{x}<br>r=%{z:.3f}<extra></extra>"), row=1, col=2)
    for fault in result.fault_indices:
        ix, iy = divmod(int(fault), result.project.array.ny)
        fig.add_annotation(x=iy, y=ix, text="×", showarrow=False, font={"color": RED, "size": 18}, row=1, col=2)
    fig.update_layout(**_layout("秩恢复与坏通道诊断", 450), showlegend=False)
    fig.update_xaxes(title="序号", gridcolor=GRID, row=1, col=1)
    fig.update_yaxes(title="相对最大值 / dB", gridcolor=GRID, row=1, col=1)
    fig.update_xaxes(title="y 阵元索引", row=1, col=2)
    fig.update_yaxes(title="x 阵元索引", autorange="reversed", row=1, col=2)
    return fig


def make_perception_comparison(result: LivePerceptionResult) -> go.Figure:
    frame = result.comparison_frame()
    colors = [GREEN if bool(value) else AMBER for value in frame["≤2°分辨"]]
    fig = go.Figure(go.Bar(x=frame["方法"], y=frame["RMSE/°"], marker={"color": colors}, text=[f"{v:.2f}°" for v in frame["RMSE/°"]], textposition="outside"))
    fig.add_hline(y=2.0, line={"color": RED, "dash": "dash"}, annotation_text="2°分辨判据", annotation_font_color=RED)
    fig.update_layout(**_layout("同数据三算法对比", 430), showlegend=False)
    fig.update_xaxes(gridcolor=GRID)
    fig.update_yaxes(title="球面角 RMSE / °", gridcolor=GRID, rangemode="tozero")
    return fig


def make_protection_map(result: LiveProtectionResult) -> go.Figure:
    fig = go.Figure(go.Heatmap(x=result.phi_grid_deg, y=result.theta_grid_deg, z=np.clip(result.response_db, -70, 3), zmin=-60, zmax=0, colorscale="Turbo", colorbar={"title": "相对响应/dB"}, hovertemplate="φ=%{x:.1f}°<br>θ=%{y:.1f}°<br>R=%{z:.2f} dB<extra></extra>"))
    fig.add_trace(go.Scatter(x=[result.desired_direction[1]], y=[result.desired_direction[0]], mode="markers", name="期望方向", marker={"symbol": "star", "size": 16, "color": GREEN}))
    fig.add_trace(go.Scatter(x=[v[1] for v in result.true_directions], y=[v[0] for v in result.true_directions], mode="markers", name="干扰路径真值", marker={"symbol": "x", "size": 13, "color": RED, "line": {"width": 2}}))
    fig.add_trace(go.Scatter(x=[v[1] for v in result.estimated_centers], y=[v[0] for v in result.estimated_centers], mode="markers", name="感知中心", marker={"symbol": "circle-open", "size": 13, "color": AMBER, "line": {"width": 3}}))
    fig.update_layout(**_layout(f"接收端二维响应 · {result.method}", 560))
    fig.update_xaxes(title="方位角 φ / °", gridcolor=GRID)
    fig.update_yaxes(title="极角 θ / °", gridcolor=GRID)
    return fig


def make_protection_comparison(result: LiveProtectionResult) -> go.Figure:
    frame = result.comparison_frame()
    fig = make_subplots(rows=1, cols=2, subplot_titles=("输出 SINR", "最坏真实路径响应"), horizontal_spacing=0.16)
    success_colors = [GREEN if bool(value) else AMBER for value in frame["防护判据"]]
    fig.add_trace(go.Bar(x=frame["方法"], y=frame["输出SINR/dB"], marker={"color": success_colors}, text=[f"{v:.1f}" for v in frame["输出SINR/dB"]], textposition="outside", showlegend=False), row=1, col=1)
    fig.add_trace(go.Bar(x=frame["方法"], y=frame["最坏真实方向响应/dB"], marker={"color": PURPLE}, text=[f"{v:.1f}" for v in frame["最坏真实方向响应/dB"]], textposition="outside", showlegend=False), row=1, col=2)
    fig.add_hline(y=5.0, line={"color": RED, "dash": "dash"}, row=1, col=1)
    fig.add_hline(y=-35.0, line={"color": RED, "dash": "dash"}, row=1, col=2)
    fig.update_layout(**_layout("接收防护基准对比", 470))
    fig.update_xaxes(tickangle=-18, gridcolor=GRID)
    fig.update_yaxes(title="dB", gridcolor=GRID)
    return fig


def make_live_metric_cards(perception: LivePerceptionResult | None, protection: LiveProtectionResult | None) -> str:
    cards: list[tuple[str, str, str, str]] = []
    if perception is not None:
        ok = bool(perception.metrics["resolved_within_2deg"])
        cards.extend([
            ("感知 RMSE", f"{float(perception.metrics['rmse_deg']):.3f}°", str(perception.metrics["method"]), "ok" if ok else "warn"),
            ("秩裕量", f"{float(perception.metrics['rank_margin_db']):.2f} dB", f"{int(perception.metrics['n_sources'])} 条相干路径", "ok"),
            ("最小阵元可靠度", f"{float(perception.metrics['minimum_sensor_reliability']):.3f}", f"{int(perception.metrics['fault_count'])} 个注入故障", "warn" if float(perception.metrics['minimum_sensor_reliability']) < .3 else "ok"),
        ])
    if protection is not None:
        ok = bool(protection.metrics["protection_success"])
        cards.extend([
            ("输出 SINR", f"{float(protection.metrics['output_sinr_db']):.2f} dB", str(protection.metrics["method"]), "ok" if ok else "warn"),
            ("最坏干扰响应", f"{float(protection.metrics['worst_true_response_db']):.2f} dB", "相对期望方向", "ok" if float(protection.metrics['worst_true_response_db']) <= -35 else "warn"),
            ("接收防护判据", "通过" if ok else "需调参", f"{int(protection.metrics['sector_count'])} 个置信扇区", "ok" if ok else "warn"),
        ])
    if not cards:
        return '<div class="cae-status">尚未运行实时链路。</div>'
    html = "".join(f'<div class="metric-card status {klass}"><span>{escape(label)}</span><strong>{escape(value)}</strong><small>{escape(note)}</small></div>' for label, value, note, klass in cards)
    return f'<div class="metric-grid">{html}</div>'

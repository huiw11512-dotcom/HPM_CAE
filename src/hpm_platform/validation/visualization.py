"""V1.4 适用性诊断与传播参数标定的 Plotly 中文图形。"""
from __future__ import annotations

import numpy as np
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from .backend_calibration import CalibrationResult
from .model_validity import ValidityReport


def make_validity_figure(report: ValidityReport) -> go.Figure:
    labels = [item.item for item in report.checks]
    scores = [item.score for item in report.checks]
    colors = {
        "适用": "#22c55e",
        "提示": "#38bdf8",
        "谨慎": "#f59e0b",
        "越界": "#ef4444",
    }
    bar_colors = [colors[item.status] for item in report.checks]
    fig = make_subplots(
        rows=1,
        cols=2,
        column_widths=[0.28, 0.72],
        specs=[[{"type": "indicator"}, {"type": "bar"}]],
        subplot_titles=("综合适用性", "分项诊断"),
    )
    fig.add_trace(
        go.Indicator(
            mode="gauge+number",
            value=report.score,
            number={"suffix": " 分", "font": {"size": 30}},
            gauge={
                "axis": {"range": [0, 100]},
                "bar": {"color": "#2563eb"},
                "steps": [
                    {"range": [0, 55], "color": "#fee2e2"},
                    {"range": [55, 78], "color": "#fef3c7"},
                    {"range": [78, 90], "color": "#dbeafe"},
                    {"range": [90, 100], "color": "#dcfce7"},
                ],
                "threshold": {
                    "line": {"color": "#111827", "width": 3},
                    "thickness": 0.7,
                    "value": report.score,
                },
            },
            title={"text": report.level, "font": {"size": 14}},
        ),
        row=1,
        col=1,
    )
    fig.add_trace(
        go.Bar(
            x=scores,
            y=labels,
            orientation="h",
            marker={"color": bar_colors},
            text=[f"{item.status} · {item.score:.0f}" for item in report.checks],
            textposition="inside",
            insidetextanchor="end",
            hovertemplate="%{y}<br>分项得分=%{x:.1f}<extra></extra>",
        ),
        row=1,
        col=2,
    )
    fig.update_xaxes(range=[0, 100], title="分项得分", row=1, col=2)
    fig.update_yaxes(autorange="reversed", row=1, col=2)
    fig.update_layout(
        title=f"{report.backend_name} · 数值模型适用性诊断",
        template="plotly_white",
        height=max(480, 46 * len(labels) + 170),
        margin={"l": 40, "r": 30, "t": 80, "b": 50},
        showlegend=False,
        font={"family": "Noto Sans CJK SC, Microsoft YaHei, sans-serif"},
    )
    return fig


def _reshape_samples(result: CalibrationResult) -> tuple[np.ndarray, np.ndarray, tuple[int, int]]:
    points = np.asarray(result.points_lambda, float)
    unique_x = np.unique(points[:, 0])
    unique_y = np.unique(points[:, 1])
    shape = (unique_y.size, unique_x.size)
    if unique_x.size * unique_y.size != points.shape[0]:
        raise ValueError("标定采样点不是规则网格")
    return unique_x, unique_y, shape


def make_calibration_overview(result: CalibrationResult) -> go.Figure:
    fig = make_subplots(
        rows=1,
        cols=2,
        subplot_titles=("尺度参数：初值与标定值", "残差收敛"),
        horizontal_spacing=0.12,
    )
    names = ["直达尺度", "反射尺度", "腔体尺度"]
    fig.add_trace(
        go.Bar(name="初值", x=names, y=list(result.initial_scales), marker_color="#94a3b8"),
        row=1,
        col=1,
    )
    fig.add_trace(
        go.Bar(name="标定值", x=names, y=list(result.fitted_scales), marker_color="#2563eb"),
        row=1,
        col=1,
    )
    history = np.asarray(result.cost_history, float)
    fig.add_trace(
        go.Scatter(
            x=np.arange(1, history.size + 1),
            y=history,
            mode="lines+markers",
            name="归一化残差",
            line={"color": "#10b981", "width": 3},
            marker={"size": 5},
        ),
        row=1,
        col=2,
    )
    fig.update_layout(
        title=f"传播尺度参数标定 · RMSE 改善 {result.improvement_percent:.2f}%",
        barmode="group",
        template="plotly_white",
        height=430,
        margin={"l": 55, "r": 30, "t": 80, "b": 65},
        legend={"orientation": "h", "y": -0.18},
        font={"family": "Noto Sans CJK SC, Microsoft YaHei, sans-serif"},
    )
    fig.update_yaxes(title="尺度值", row=1, col=1)
    fig.update_yaxes(title="复场归一化残差", type="log" if np.all(history > 0) else "linear", row=1, col=2)
    fig.update_xaxes(title="残差函数调用次数", row=1, col=2)
    return fig


def make_calibration_field_figure(result: CalibrationResult) -> go.Figure:
    x, y, shape = _reshape_samples(result)
    reference = np.abs(result.reference_field).reshape(shape)
    initial = np.abs(result.initial_field).reshape(shape)
    fitted = np.abs(result.fitted_field).reshape(shape)
    norm = max(float(np.max(reference)), 1e-12)
    ref = reference / norm
    init_res = np.abs(result.initial_field - result.reference_field).reshape(shape) / norm
    fit_res = np.abs(result.fitted_field - result.reference_field).reshape(shape) / norm
    zmax = max(float(np.quantile(init_res, 0.995)), 1e-6)

    fig = make_subplots(
        rows=1,
        cols=3,
        subplot_titles=("参考归一化幅度", "标定前绝对残差", "标定后绝对残差"),
        horizontal_spacing=0.06,
    )
    fig.add_trace(
        go.Heatmap(x=x, y=y, z=ref, colorscale="Turbo", zmin=0, zmax=1, colorbar={"title": "归一化幅度", "x": 0.30}),
        row=1,
        col=1,
    )
    fig.add_trace(
        go.Heatmap(x=x, y=y, z=init_res, colorscale="Magma", zmin=0, zmax=zmax, showscale=False),
        row=1,
        col=2,
    )
    fig.add_trace(
        go.Heatmap(x=x, y=y, z=fit_res, colorscale="Magma", zmin=0, zmax=zmax, colorbar={"title": "相对残差", "x": 1.02}),
        row=1,
        col=3,
    )
    for column in (1, 2, 3):
        fig.update_xaxes(title="x / λ", scaleanchor=f"y{column}" if column > 1 else "y", scaleratio=1, row=1, col=column)
        fig.update_yaxes(title="y / λ" if column == 1 else "", row=1, col=column)
    fig.update_layout(
        title=f"标定空间复核 · 相对RMSE {result.relative_rmse_before_percent:.2f}% → {result.relative_rmse_after_percent:.4f}%",
        template="plotly_white",
        height=520,
        margin={"l": 55, "r": 70, "t": 80, "b": 55},
        font={"family": "Noto Sans CJK SC, Microsoft YaHei, sans-serif"},
    )
    return fig

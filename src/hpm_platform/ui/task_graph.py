"""Visual directed task graph for the HPM-CAE V1.2 workbench."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Mapping

import pandas as pd
import plotly.graph_objects as go


@dataclass(frozen=True)
class TaskNode:
    node_id: str
    label: str
    subtitle: str
    dependencies: tuple[str, ...]
    implementation: str
    default_enabled: bool = True


DEFAULT_NODES: tuple[TaskNode, ...] = (
    TaskNode("scene", "场景与阵列", "多对象几何 / 网格 / 约束区", (), "live"),
    TaskNode("signal", "信号与信道", "相干多径 / 阵列失配 / 坏通道", ("scene",), "live"),
    TaskNode("perception", "感知识别", "PAWR / FBSS / ESPRIT 实时计算", ("signal",), "live"),
    TaskNode("protection", "接收防护", "DOA置信扇区 / 鲁棒宽零陷", ("perception",), "live"),
    TaskNode("field_control", "空间控场", "多目标 PGMS / 功放 / DPD", ("scene",), "live"),
    TaskNode("dynamic_timeline", "动态时间轴", "延迟观测 / 预测赋形", ("field_control",), "live", False),
    TaskNode("effect_proxy", "效应代理评价", "归一化响应 / 保护区风险", ("protection", "field_control"), "live"),
    TaskNode("batch_sweep", "任务队列", "并行 worker / 暂停恢复 / SQLite", ("field_control",), "live", False),
    TaskNode("report", "报告与归档", "HTML / CSV / NPZ / ZIP", ("effect_proxy",), "live"),
)


class WorkflowGraph:
    def __init__(self, nodes: Iterable[TaskNode] = DEFAULT_NODES):
        self.nodes = tuple(nodes)
        self.by_id = {node.node_id: node for node in self.nodes}
        if len(self.by_id) != len(self.nodes):
            raise ValueError("task node ids must be unique")
        for node in self.nodes:
            unknown = set(node.dependencies) - set(self.by_id)
            if unknown:
                raise ValueError(f"unknown dependencies for {node.node_id}: {sorted(unknown)}")
        self.topological_order(tuple(self.by_id))

    def closure(self, selected: Iterable[str]) -> tuple[str, ...]:
        chosen = set(selected)
        unknown = chosen - set(self.by_id)
        if unknown:
            raise ValueError(f"unknown task nodes: {sorted(unknown)}")
        changed = True
        while changed:
            changed = False
            for node_id in tuple(chosen):
                before = len(chosen)
                chosen.update(self.by_id[node_id].dependencies)
                changed |= len(chosen) > before
        return self.topological_order(tuple(chosen))

    def topological_order(self, subset: Iterable[str]) -> tuple[str, ...]:
        selected = set(subset)
        indegree: dict[str, int] = {node_id: 0 for node_id in selected}
        children: dict[str, list[str]] = {node_id: [] for node_id in selected}
        for node_id in selected:
            for dependency in self.by_id[node_id].dependencies:
                if dependency in selected:
                    indegree[node_id] += 1
                    children[dependency].append(node_id)
        ready = [node.node_id for node in self.nodes if node.node_id in selected and indegree[node.node_id] == 0]
        ordered: list[str] = []
        while ready:
            current = ready.pop(0)
            ordered.append(current)
            for child in children[current]:
                indegree[child] -= 1
                if indegree[child] == 0:
                    ready.append(child)
        if len(ordered) != len(selected):
            raise ValueError("task graph contains a cycle")
        return tuple(ordered)

    def compile_plan(self, selected: Iterable[str]) -> pd.DataFrame:
        ordered = self.closure(selected)
        rows = []
        for index, node_id in enumerate(ordered, start=1):
            node = self.by_id[node_id]
            rows.append(
                {
                    "序号": index,
                    "任务": node.label,
                    "说明": node.subtitle,
                    "依赖": ", ".join(self.by_id[item].label for item in node.dependencies) or "—",
                    "执行方式": {"live": "实时执行", "adapter": "历史结果适配器", "planned": "待实现"}.get(node.implementation, node.implementation),
                    "状态": "就绪" if node.implementation in {"live", "adapter"} else "未实现",
                }
            )
        return pd.DataFrame(rows)


GRAPH = WorkflowGraph()


def node_choices() -> list[tuple[str, str]]:
    return [(f"{node.label} · {node.subtitle}", node.node_id) for node in DEFAULT_NODES]


def default_selection() -> list[str]:
    return [node.node_id for node in DEFAULT_NODES if node.default_enabled]


def make_task_graph_figure(
    selected: Iterable[str] | None = None,
    *,
    statuses: Mapping[str, str] | None = None,
) -> go.Figure:
    selected_set = set(GRAPH.closure(selected or default_selection()))
    statuses = dict(statuses or {})
    positions = {
        "scene": (0.0, 1.0),
        "signal": (1.3, 1.65),
        "perception": (2.6, 1.65),
        "protection": (3.9, 1.65),
        "field_control": (1.3, 0.55),
        "dynamic_timeline": (2.6, 0.55),
        "effect_proxy": (3.9, 0.55),
        "batch_sweep": (2.6, -0.55),
        "report": (5.2, 0.55),
    }
    fig = go.Figure()
    for node in DEFAULT_NODES:
        for dep in node.dependencies:
            x0, y0 = positions[dep]
            x1, y1 = positions[node.node_id]
            active = dep in selected_set and node.node_id in selected_set
            fig.add_trace(
                go.Scatter(
                    x=[x0, x1], y=[y0, y1], mode="lines", showlegend=False, hoverinfo="skip",
                    line={"color": "#35d8ff" if active else "#26354d", "width": 3 if active else 1.5},
                )
            )
            # Arrow head annotation keeps the direction legible without a
            # custom frontend dependency.
            fig.add_annotation(
                x=x1, y=y1, ax=x0, ay=y0, xref="x", yref="y", axref="x", ayref="y",
                showarrow=True, arrowhead=2, arrowsize=1.1, arrowwidth=1.5,
                arrowcolor="#35d8ff" if active else "#26354d", opacity=0.9,
            )
    colors = {"live": "#35d8ff", "adapter": "#ffc857", "planned": "#91a2bb"}
    for node in DEFAULT_NODES:
        x, y = positions[node.node_id]
        chosen = node.node_id in selected_set
        status = statuses.get(node.node_id, "selected" if chosen else "idle")
        color = colors.get(node.implementation, "#91a2bb") if chosen else "#26354d"
        if status == "completed":
            color = "#4ee0a5"
        elif status == "running":
            color = "#ab8cff"
        elif status in {"paused", "pause_requested"}:
            color = "#ffc857"
        elif status == "failed":
            color = "#ff6b7a"
        fig.add_trace(
            go.Scatter(
                x=[x], y=[y], mode="markers+text", name=node.label, showlegend=False,
                marker={"size": 70, "color": color, "line": {"color": "#e7eef9" if chosen else "#526178", "width": 2}, "symbol": "square"},
                text=[node.label], textposition="middle center", textfont={"color": "#07101d" if chosen else "#91a2bb", "size": 11},
                customdata=[[node.subtitle, node.implementation, status]],
                hovertemplate="<b>%{text}</b><br>%{customdata[0]}<br>mode=%{customdata[1]}<br>status=%{customdata[2]}<extra></extra>",
            )
        )
    fig.update_layout(
        title={"text": "全链路任务图 · 依赖自动补全", "x": 0.02},
        paper_bgcolor="#07101d", plot_bgcolor="#0d1828", font={"color": "#e7eef9"}, height=560,
        margin={"l": 25, "r": 25, "t": 70, "b": 30},
        xaxis={"visible": False, "range": [-0.6, 5.8]}, yaxis={"visible": False, "range": [-1.05, 2.15]},
        annotations=list(fig.layout.annotations) + [
            {"x": 0.02, "y": 0.02, "xref": "paper", "yref": "paper", "text": "蓝：实时模块 · 紫：运行中 · 黄：已暂停 · 绿：本次已完成", "showarrow": False, "font": {"size": 11, "color": "#91a2bb"}}
        ],
    )
    return fig

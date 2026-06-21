"""Multi-object Pareto exploration for the HPM-CAE V1.2 workbench."""
from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timezone
from hashlib import sha256
from html import escape
from pathlib import Path
import json
import shutil
import time
from typing import Callable, Sequence

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from threadpoolctl import threadpool_limits

from hpm_platform.ui.figures import AMBER, BG, CYAN, GREEN, GRID, MUTED, PANEL, PURPLE, RED, TEXT
from hpm_platform.ui.project_model import CAEProject
from hpm_platform.ui.quick_solver import CAESolveResult, solve_project

ParetoLog = Callable[[str], None] | None


@dataclass(frozen=True)
class ParetoStudyResult:
    project: CAEProject
    multipliers: np.ndarray
    records: pd.DataFrame
    results: tuple[CAESolveResult, ...]
    recommended_index: int
    log_lines: tuple[str, ...]
    runtime_ms: float

    @property
    def recommended_result(self) -> CAESolveResult:
        return self.results[int(self.recommended_index)]

    @property
    def recommended_record(self) -> pd.Series:
        return self.records.iloc[int(self.recommended_index)]


def _non_dominated(points: np.ndarray) -> np.ndarray:
    values = np.asarray(points, float)
    mask = np.ones(values.shape[0], dtype=bool)
    for index, point in enumerate(values):
        dominated = np.any(
            np.all(values <= point + 1e-12, axis=1)
            & np.any(values < point - 1e-12, axis=1)
        )
        mask[index] = not dominated
    return mask


def _recommended_index(records: pd.DataFrame) -> int:
    candidates = records[records["pareto"]].copy()
    if candidates.empty:
        candidates = records.copy()
    objectives = candidates[["worst_target_rmse_percent", "risk_violation_db"]].to_numpy(float)
    minimum = np.nanmin(objectives, axis=0)
    span = np.maximum(np.nanmax(objectives, axis=0) - minimum, 1e-12)
    normalized = (objectives - minimum) / span
    efficiency = candidates["sampled_plane_efficiency_percent"].to_numpy(float)
    efficiency_penalty = 1.0 - (efficiency - np.min(efficiency)) / max(float(np.ptp(efficiency)), 1e-12)
    score = np.sqrt(np.sum(normalized**2, axis=1)) + 0.08 * efficiency_penalty
    return int(candidates.index[int(np.argmin(score))])


def run_pareto_study(
    project: CAEProject,
    *,
    multipliers: Sequence[float] | None = None,
    fast_mode: bool = True,
    log_callback: ParetoLog = None,
) -> ParetoStudyResult:
    """Sweep exposure penalties and identify the non-dominated compromise set."""
    project.validate_geometry()
    if multipliers is None:
        multipliers_array = np.geomspace(0.22, 5.0, int(project.solver.pareto_points))
    else:
        multipliers_array = np.asarray(tuple(multipliers), float)
    if multipliers_array.ndim != 1 or multipliers_array.size < 3 or np.any(multipliers_array <= 0):
        raise ValueError("Pareto multipliers must contain at least three positive values")

    lines: list[str] = []
    results: list[CAESolveResult] = []
    records: list[dict[str, float | int | bool]] = []
    started = time.perf_counter()

    def emit(message: str) -> None:
        lines.append(message)
        if log_callback is not None:
            log_callback(message)

    emit(f"[pareto] {multipliers_array.size} points · target fidelity ↔ exposure risk")
    with threadpool_limits(limits=1):
        for index, multiplier in enumerate(multipliers_array):
            solver = replace(
                project.solver,
                method="Constrained-MO-PGMS",
                outside_penalty=float(project.solver.outside_penalty) * float(multiplier),
                protected_penalty=float(project.solver.protected_penalty) * float(multiplier),
            )
            case = replace(project, solver=solver, motion=replace(project.motion, enabled=False))
            if fast_mode:
                case = replace(
                    case,
                    plane=replace(case.plane, samples=min(case.plane.samples, 61)),
                    solver=replace(
                        case.solver,
                        iterations=min(case.solver.iterations, 150),
                        uncertainty_scenarios=min(case.solver.uncertainty_scenarios, 3),
                        target_samples=min(case.solver.target_samples, 220),
                        outside_samples=min(case.solver.outside_samples, 520),
                    ),
                )
            result = solve_project(case)
            results.append(result)
            outside_limit_db = float(case.solver.outside_peak_limit_db)
            outside_violation = float(result.metrics["peak_outside_db"]) - outside_limit_db
            protected_violation = float(result.metrics["maximum_protected_violation_db"])
            if not np.isfinite(protected_violation):
                protected_violation = -60.0
            risk_violation = max(outside_violation, protected_violation)
            record = {
                "index": index,
                "risk_multiplier": float(multiplier),
                "worst_target_rmse_percent": float(result.metrics["worst_target_rmse_percent"]),
                "minimum_target_coverage_percent": float(result.metrics["minimum_target_coverage_percent"]),
                "target_fairness_gap_percent": float(result.metrics["target_fairness_gap_percent"]),
                "peak_outside_db": float(result.metrics["peak_outside_db"]),
                "outside_limit_db": outside_limit_db,
                "outside_violation_db": outside_violation,
                "maximum_protected_violation_db": protected_violation,
                "risk_violation_db": risk_violation,
                "sampled_plane_efficiency_percent": float(result.metrics["sampled_plane_efficiency_percent"]),
                "control_success": bool(result.metrics["control_success"]),
                "runtime_ms": float(result.metrics["solver_runtime_ms"]),
            }
            records.append(record)
            emit(
                f"[{index + 1:02d}/{len(multipliers_array):02d}] μ={multiplier:.3g} · worst RMSE={record['worst_target_rmse_percent']:.2f}% · risk={risk_violation:+.2f} dB"
            )
    frame = pd.DataFrame(records)
    frame["pareto"] = _non_dominated(frame[["worst_target_rmse_percent", "risk_violation_db"]].to_numpy(float))
    recommended = _recommended_index(frame)
    frame["recommended"] = False
    frame.loc[recommended, "recommended"] = True
    emit(
        f"[recommended] μ={frame.loc[recommended, 'risk_multiplier']:.3g} · RMSE={frame.loc[recommended, 'worst_target_rmse_percent']:.2f}% · risk={frame.loc[recommended, 'risk_violation_db']:+.2f} dB"
    )
    return ParetoStudyResult(
        project=project,
        multipliers=multipliers_array,
        records=frame,
        results=tuple(results),
        recommended_index=recommended,
        log_lines=tuple(lines),
        runtime_ms=1000.0 * (time.perf_counter() - started),
    )


def _layout(title: str, height: int = 520) -> dict:
    return {
        "title": {"text": title, "x": 0.02, "font": {"color": TEXT, "size": 18}},
        "paper_bgcolor": BG,
        "plot_bgcolor": PANEL,
        "font": {"family": "Inter, Segoe UI, Microsoft YaHei, sans-serif", "color": TEXT},
        "margin": {"l": 65, "r": 30, "t": 62, "b": 58},
        "height": height,
        "legend": {"bgcolor": "rgba(7,16,29,.76)", "bordercolor": GRID, "borderwidth": 1},
    }


def make_pareto_figure(study: ParetoStudyResult) -> go.Figure:
    frame = study.records
    fig = go.Figure()
    dominated = frame[~frame["pareto"]]
    pareto = frame[frame["pareto"]].sort_values("worst_target_rmse_percent")
    if not dominated.empty:
        fig.add_trace(
            go.Scatter(
                x=dominated["worst_target_rmse_percent"], y=dominated["risk_violation_db"],
                mode="markers", name="被支配方案", marker={"size": 10, "color": MUTED, "opacity": 0.55},
                customdata=dominated[["risk_multiplier", "minimum_target_coverage_percent"]],
                hovertemplate="worst RMSE=%{x:.2f}%<br>risk=%{y:+.2f} dB<br>μ=%{customdata[0]:.3g}<br>min cover=%{customdata[1]:.1f}%<extra></extra>",
            )
        )
    fig.add_trace(
        go.Scatter(
            x=pareto["worst_target_rmse_percent"], y=pareto["risk_violation_db"],
            mode="lines+markers+text", name="Pareto 前沿", text=[f"μ={value:.2g}" for value in pareto["risk_multiplier"]],
            textposition="top center", line={"color": CYAN, "width": 3}, marker={"size": 12, "color": CYAN, "line": {"color": TEXT, "width": 1}},
            customdata=pareto[["minimum_target_coverage_percent", "sampled_plane_efficiency_percent"]],
            hovertemplate="worst RMSE=%{x:.2f}%<br>risk=%{y:+.2f} dB<br>min cover=%{customdata[0]:.1f}%<br>eff=%{customdata[1]:.1f}%<extra></extra>",
        )
    )
    rec = study.recommended_record
    fig.add_trace(
        go.Scatter(
            x=[rec["worst_target_rmse_percent"]], y=[rec["risk_violation_db"]], mode="markers", name="推荐折中",
            marker={"symbol": "star", "size": 22, "color": AMBER, "line": {"color": TEXT, "width": 1.5}},
            hovertemplate="推荐点<br>worst RMSE=%{x:.2f}%<br>risk=%{y:+.2f} dB<extra></extra>",
        )
    )
    fig.add_hline(y=0.0, line={"color": GREEN, "dash": "dash", "width": 1.5}, annotation_text="约束边界", annotation_font_color=GREEN)
    fig.update_layout(**_layout("多目标约束 Pareto 前沿 · 左下更优", 560))
    fig.update_xaxes(title="最差目标 RMSE / %", gridcolor=GRID)
    fig.update_yaxes(title="最坏风险超限 / dB", gridcolor=GRID)
    return fig


def make_tradeoff_figure(study: ParetoStudyResult) -> go.Figure:
    frame = study.records.sort_values("risk_multiplier")
    fig = make_subplots(rows=2, cols=2, subplot_titles=("最差目标 RMSE", "最低目标覆盖率", "区外峰值", "保护区最坏超限"), horizontal_spacing=0.12, vertical_spacing=0.18)
    series = [
        ("worst_target_rmse_percent", AMBER, 1, 1, "%"),
        ("minimum_target_coverage_percent", CYAN, 1, 2, "%"),
        ("peak_outside_db", PURPLE, 2, 1, "dB"),
        ("maximum_protected_violation_db", GREEN, 2, 2, "dB"),
    ]
    for key, color, row, col, unit in series:
        fig.add_trace(
            go.Scatter(
                x=frame["risk_multiplier"], y=frame[key], mode="lines+markers", name=key,
                line={"color": color, "width": 2.5}, marker={"size": 7}, showlegend=False,
                hovertemplate=f"μ=%{{x:.3g}}<br>{key}=%{{y:.3f}} {unit}<extra></extra>",
            ), row=row, col=col,
        )
    fig.update_xaxes(type="log", title="风险权重倍率 μ", gridcolor=GRID)
    fig.update_yaxes(gridcolor=GRID)
    fig.update_layout(**_layout("风险权重扫描与对象约束响应", 650))
    return fig


def make_pareto_field_gallery(study: ParetoStudyResult) -> go.Figure:
    order = [0, int(study.recommended_index), len(study.results) - 1]
    labels = ["目标优先", "推荐折中", "风险优先"]
    fig = make_subplots(rows=1, cols=3, subplot_titles=tuple(labels), horizontal_spacing=0.06)
    for column, (index, label) in enumerate(zip(order, labels, strict=True), start=1):
        result = study.results[index]
        fig.add_trace(
            go.Heatmap(
                x=result.x_lambda, y=result.y_lambda, z=np.clip(result.field_db, -30, 3),
                zmin=-25, zmax=2, colorscale="Turbo", showscale=column == 3,
                colorbar={"title": "dB", "x": 1.02} if column == 3 else None,
                hovertemplate=f"{label}<br>x=%{{x:.2f}}λ<br>y=%{{y:.2f}}λ<br>%{{z:.2f}} dB<extra></extra>",
            ), row=1, col=column,
        )
        rec = study.records.iloc[index]
        fig.add_annotation(
            x=0.5, y=-0.12, xref=f"x{column} domain" if column > 1 else "x domain", yref="paper",
            text=f"μ={rec['risk_multiplier']:.2g} · RMSE={rec['worst_target_rmse_percent']:.1f}% · risk={rec['risk_violation_db']:+.1f}dB",
            showarrow=False, font={"size": 10, "color": MUTED},
        )
    fig.update_xaxes(title="x / λ", gridcolor=GRID, scaleanchor=None)
    fig.update_yaxes(title="y / λ", gridcolor=GRID)
    fig.update_layout(**_layout("Pareto 代表方案场分布对照", 520))
    return fig


def _digest(path: Path) -> str:
    hasher = sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def export_pareto_bundle(study: ParetoStudyResult, root: str | Path, *, run_name: str | None = None) -> tuple[Path, Path, Path]:
    root_path = Path(root)
    root_path.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    folder = root_path / (run_name or f"{study.project.slug}_pareto_{timestamp}")
    if folder.exists():
        shutil.rmtree(folder)
    folder.mkdir(parents=True)
    study.project.save_yaml(folder / "project.yaml")
    study.records.to_csv(folder / "pareto_records.csv", index=False, encoding="utf-8-sig")
    summary = {
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "runtime_ms": study.runtime_ms,
        "recommended_index": int(study.recommended_index),
        "recommended": study.recommended_record.to_dict(),
        "model_scope": study.project.model_scope,
    }
    (folder / "pareto_summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    (folder / "pareto.log").write_text("\n".join(study.log_lines) + "\n", encoding="utf-8")
    figures = [
        ("Pareto 前沿", make_pareto_figure(study)),
        ("权重扫描", make_tradeoff_figure(study)),
        ("场分布对照", make_pareto_field_gallery(study)),
    ]
    include_js: str | bool = "inline"
    sections = []
    for index, (title, figure) in enumerate(figures, start=1):
        figure.write_html(folder / f"{index:02d}_{title}.html", include_plotlyjs="directory", full_html=True, config={"displaylogo": False})
        sections.append(f"<section><h2>{escape(title)}</h2>{figure.to_html(full_html=False, include_plotlyjs=include_js, config={'displaylogo': False})}</section>")
        include_js = False
    table = study.records.to_html(index=False, border=0, classes="metrics", float_format=lambda value: f"{value:.4g}")
    rec = study.recommended_record
    report = folder / "HPM_CAE_V12_pareto_report.html"
    report.write_text(
        f"""<!doctype html><html lang='zh-CN'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'><title>HPM-CAE V1.2 Pareto</title><style>body{{margin:0;background:{BG};color:{TEXT};font-family:Inter,'Segoe UI','Microsoft YaHei',sans-serif}}header{{padding:28px 5vw;background:#0b182a;border-bottom:1px solid {GRID}}}main{{max-width:1500px;margin:auto;padding:24px 4vw}}section{{background:{PANEL};border:1px solid {GRID};border-radius:14px;padding:16px;margin:18px 0}}.metrics{{width:100%;border-collapse:collapse}}.metrics th,.metrics td{{padding:9px;border-bottom:1px solid {GRID};text-align:left}}.badge{{color:{CYAN};border:1px solid {CYAN};border-radius:999px;padding:5px 10px}}</style></head><body><header><span class='badge'>NORMALIZED MULTI-OBJECT STUDY</span><h1>{escape(study.project.meta.name)} · Pareto</h1><p>推荐 μ={float(rec['risk_multiplier']):.3g} · worst RMSE={float(rec['worst_target_rmse_percent']):.2f}% · risk={float(rec['risk_violation_db']):+.2f} dB</p></header><main><section><h2>全体方案</h2>{table}</section>{''.join(sections)}<section><h2>模型边界</h2><p>{escape(study.project.model_scope)}。所有幅度、约束和风险均为无量纲代理量。</p></section></main></body></html>""",
        encoding="utf-8",
    )
    manifest = {
        "platform": "HPM-CAE",
        "version": "1.2.0",
        "files": [
            {"path": str(path.relative_to(folder)).replace("\\", "/"), "bytes": path.stat().st_size, "sha256": _digest(path)}
            for path in sorted(folder.rglob("*")) if path.is_file()
        ],
    }
    (folder / "manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    archive = Path(shutil.make_archive(str(folder), "zip", root_dir=folder))
    return folder, report, archive

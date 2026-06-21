"""Batch-sweep queue and persistent experiment database for HPM-CAE V1.2."""
from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Iterable
import json
import shutil
import sqlite3
import time
import uuid

import numpy as np
import pandas as pd
import plotly.graph_objects as go

from hpm_platform.ui.project_model import CAEProject
from hpm_platform.ui.quick_solver import solve_project

SweepLog = Callable[[str], None] | None

SWEEP_PARAMETERS: dict[str, str] = {
    "target.center_x_lambda": "目标中心 x / λ",
    "target.center_y_lambda": "目标中心 y / λ",
    "target.semi_major_lambda": "目标长半轴 / λ",
    "target.semi_minor_lambda": "目标短半轴 / λ",
    "target.rotation_deg": "目标旋转角 / °",
    "target.priority": "主目标优先级",
    "target.tolerance_percent": "主目标容差 / %",
    "protected_zone.radius_lambda": "保护区半径 / λ",
    "protected_zone.priority": "主保护区优先级",
    "protected_zone.max_amplitude_scale": "主保护区幅度上限 / 目标参考",
    "solver.target_amplitude": "目标归一化幅度",
    "solver.outside_penalty": "区外惩罚",
    "solver.protected_penalty": "保护区惩罚",
    "solver.fairness_penalty": "多目标公平惩罚",
    "solver.tail_penalty": "峰值尾部惩罚",
    "solver.phase_std_deg": "相位误差 σ / °",
    "solver.gain_std_percent": "增益误差 σ / %",
    "solver.registration_jitter_lambda": "配准抖动 σ / λ",
    "array.spacing_x_lambda": "阵元 x 间距 / λ",
    "array.spacing_y_lambda": "阵元 y 间距 / λ",
    "plane.z_lambda": "观察面距离 / λ",
}

METRIC_LABELS: dict[str, str] = {
    "target_rmse_percent": "目标区 RMSE / %",
    "target_coverage_percent": "±10%覆盖率 / %",
    "worst_target_rmse_percent": "最差目标 RMSE / %",
    "minimum_target_coverage_percent": "最低目标覆盖率 / %",
    "target_fairness_gap_percent": "目标间 RMSE 差 / 百分点",
    "peak_outside_db": "区外峰值 / dB",
    "outside_peak_violation_db": "区外峰值超限 / dB",
    "protected_p95_db": "保护区 P95 / dB",
    "maximum_protected_violation_db": "最坏保护区超限 / dB",
    "constraint_success_rate_percent": "对象约束通过率 / %",
    "sampled_plane_efficiency_percent": "采样面能量占比 / %",
    "solver_runtime_ms": "求解耗时 / ms",
}


@dataclass(frozen=True)
class SweepSpec:
    parameter: str = "solver.phase_std_deg"
    start: float = 0.0
    stop: float = 12.0
    points: int = 5
    replicates: int = 2
    metric: str = "target_rmse_percent"
    fast_mode: bool = True

    def __post_init__(self) -> None:
        if self.parameter not in SWEEP_PARAMETERS:
            raise ValueError(f"unsupported sweep parameter {self.parameter!r}")
        if self.metric not in METRIC_LABELS:
            raise ValueError(f"unsupported metric {self.metric!r}")
        if not np.isfinite(self.start) or not np.isfinite(self.stop):
            raise ValueError("sweep bounds must be finite")
        if not 2 <= int(self.points) <= 31:
            raise ValueError("sweep points must be between 2 and 31")
        if not 1 <= int(self.replicates) <= 20:
            raise ValueError("replicates must be between 1 and 20")

    @property
    def values(self) -> np.ndarray:
        return np.linspace(float(self.start), float(self.stop), int(self.points))


@dataclass(frozen=True)
class SweepResult:
    experiment_id: str
    project: CAEProject
    spec: SweepSpec
    records: pd.DataFrame
    summary: pd.DataFrame
    log_lines: tuple[str, ...]

    def best_record(self) -> pd.Series:
        valid = self.records[self.records["status"] == "completed"]
        if valid.empty:
            raise ValueError("sweep contains no completed runs")
        metric = self.spec.metric
        ascending = metric in {"target_rmse_percent", "worst_target_rmse_percent", "target_fairness_gap_percent", "peak_outside_db", "protected_p95_db", "maximum_protected_violation_db", "solver_runtime_ms"}
        return valid.sort_values(metric, ascending=ascending).iloc[0]


class ExperimentDatabase:
    """Small SQLite store used by the local queue and history panel."""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        return connection

    def _initialize(self) -> None:
        with self._connect() as db:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS experiments (
                    experiment_id TEXT PRIMARY KEY,
                    created_utc TEXT NOT NULL,
                    project_name TEXT NOT NULL,
                    parameter TEXT NOT NULL,
                    start_value REAL NOT NULL,
                    stop_value REAL NOT NULL,
                    points INTEGER NOT NULL,
                    replicates INTEGER NOT NULL,
                    metric TEXT NOT NULL,
                    fast_mode INTEGER NOT NULL,
                    status TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS runs (
                    run_id TEXT PRIMARY KEY,
                    experiment_id TEXT NOT NULL,
                    parameter_value REAL NOT NULL,
                    replicate INTEGER NOT NULL,
                    seed INTEGER NOT NULL,
                    status TEXT NOT NULL,
                    metrics_json TEXT,
                    error_text TEXT,
                    created_utc TEXT NOT NULL,
                    FOREIGN KEY(experiment_id) REFERENCES experiments(experiment_id)
                );
                CREATE INDEX IF NOT EXISTS idx_runs_experiment ON runs(experiment_id);
                """
            )

    def create_experiment(self, project: CAEProject, spec: SweepSpec, experiment_id: str) -> None:
        with self._connect() as db:
            db.execute(
                "INSERT OR REPLACE INTO experiments VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (
                    experiment_id,
                    datetime.now(timezone.utc).isoformat(),
                    project.meta.name,
                    spec.parameter,
                    spec.start,
                    spec.stop,
                    spec.points,
                    spec.replicates,
                    spec.metric,
                    int(spec.fast_mode),
                    "running",
                ),
            )

    def add_run(
        self,
        experiment_id: str,
        *,
        parameter_value: float,
        replicate: int,
        seed: int,
        status: str,
        metrics: dict | None = None,
        error: str | None = None,
    ) -> str:
        run_id = uuid.uuid4().hex[:16]
        with self._connect() as db:
            db.execute(
                "INSERT INTO runs VALUES (?,?,?,?,?,?,?,?,?)",
                (
                    run_id,
                    experiment_id,
                    float(parameter_value),
                    int(replicate),
                    int(seed),
                    status,
                    json.dumps(metrics, ensure_ascii=False) if metrics is not None else None,
                    error,
                    datetime.now(timezone.utc).isoformat(),
                ),
            )
        return run_id

    def finish_experiment(self, experiment_id: str, status: str = "completed") -> None:
        with self._connect() as db:
            db.execute("UPDATE experiments SET status=? WHERE experiment_id=?", (status, experiment_id))

    def history(self, limit: int = 30) -> pd.DataFrame:
        with self._connect() as db:
            rows = db.execute(
                """
                SELECT e.*, COUNT(r.run_id) AS run_count,
                       SUM(CASE WHEN r.status='completed' THEN 1 ELSE 0 END) AS completed_count
                FROM experiments e LEFT JOIN runs r ON e.experiment_id=r.experiment_id
                GROUP BY e.experiment_id ORDER BY e.created_utc DESC LIMIT ?
                """,
                (int(limit),),
            ).fetchall()
        if not rows:
            return pd.DataFrame(columns=["experiment_id", "created_utc", "project_name", "parameter", "status", "run_count", "completed_count"])
        return pd.DataFrame([dict(row) for row in rows])

    def runs(self, experiment_id: str) -> pd.DataFrame:
        with self._connect() as db:
            rows = db.execute("SELECT * FROM runs WHERE experiment_id=? ORDER BY parameter_value, replicate", (experiment_id,)).fetchall()
        output: list[dict] = []
        for row in rows:
            item = dict(row)
            metrics = json.loads(item.pop("metrics_json")) if item.get("metrics_json") else {}
            item.update(metrics)
            output.append(item)
        return pd.DataFrame(output)


def set_project_parameter(project: CAEProject, path: str, value: float) -> CAEProject:
    section, field = path.split(".", 1)
    if section == "target":
        return replace(project, target=replace(project.target, **{field: float(value)}))
    if section == "protected_zone":
        return replace(project, protected_zone=replace(project.protected_zone, **{field: float(value)}))
    if section == "solver":
        return replace(project, solver=replace(project.solver, **{field: float(value)}))
    if section == "array":
        return replace(project, array=replace(project.array, **{field: float(value)}))
    if section == "plane":
        return replace(project, plane=replace(project.plane, **{field: float(value)}))
    raise ValueError(f"unsupported parameter path {path!r}")


def _summary(records: pd.DataFrame, metric: str) -> pd.DataFrame:
    valid = records[records["status"] == "completed"].copy()
    if valid.empty:
        return pd.DataFrame(columns=["parameter_value", "mean", "std", "ci95_low", "ci95_high", "n"])
    rows = []
    for value, group in valid.groupby("parameter_value", sort=True):
        values = group[metric].astype(float).to_numpy()
        mean = float(np.mean(values))
        std = float(np.std(values, ddof=1)) if values.size > 1 else 0.0
        half = 1.96 * std / np.sqrt(values.size) if values.size > 1 else 0.0
        rows.append({"parameter_value": float(value), "mean": mean, "std": std, "ci95_low": mean - half, "ci95_high": mean + half, "n": int(values.size)})
    return pd.DataFrame(rows)


def run_sweep(
    project: CAEProject,
    spec: SweepSpec,
    database: ExperimentDatabase,
    *,
    log_callback: SweepLog = None,
) -> SweepResult:
    experiment_id = datetime.now(timezone.utc).strftime("EXP-%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:6]
    database.create_experiment(project, spec, experiment_id)
    lines: list[str] = []
    records: list[dict] = []

    def emit(message: str) -> None:
        lines.append(message)
        if log_callback is not None:
            log_callback(message)

    total = spec.points * spec.replicates
    emit(f"[queue] {experiment_id} · {SWEEP_PARAMETERS[spec.parameter]} · {total} runs")
    index = 0
    failed = False
    for value in spec.values:
        for replicate in range(int(spec.replicates)):
            index += 1
            seed = int((project.meta.seed + 1009 * replicate + 65537 * index) % (2**32 - 1))
            started = time.perf_counter()
            try:
                case = set_project_parameter(project, spec.parameter, float(value))
                case = replace(case, meta=replace(case.meta, seed=seed), motion=replace(case.motion, enabled=False))
                if spec.fast_mode:
                    uncertain_parameter = spec.parameter in {
                        "solver.phase_std_deg",
                        "solver.gain_std_percent",
                        "solver.registration_jitter_lambda",
                    }
                    object_constraint_parameter = spec.parameter in {
                        "target.priority", "target.tolerance_percent",
                        "protected_zone.priority", "protected_zone.max_amplitude_scale",
                        "solver.protected_penalty", "solver.fairness_penalty", "solver.tail_penalty",
                    }
                    use_multi_object = case.solver.method == "Constrained-MO-PGMS" or object_constraint_parameter
                    case = replace(
                        case,
                        plane=replace(case.plane, samples=min(case.plane.samples, 51)),
                        solver=replace(
                            case.solver,
                            method="Constrained-MO-PGMS" if use_multi_object else ("Robust-PGMS" if uncertain_parameter else "Nominal-PGMS"),
                            iterations=min(case.solver.iterations, 120),
                            uncertainty_scenarios=3 if (uncertain_parameter or use_multi_object) else 1,
                            target_samples=min(case.solver.target_samples, 180),
                            outside_samples=min(case.solver.outside_samples, 420),
                        ),
                    )
                result = solve_project(case)
                metrics = dict(result.metrics)
                elapsed_ms = 1000.0 * (time.perf_counter() - started)
                record = {
                    "experiment_id": experiment_id,
                    "parameter": spec.parameter,
                    "parameter_value": float(value),
                    "replicate": replicate,
                    "seed": seed,
                    "status": "completed",
                    "wall_runtime_ms": elapsed_ms,
                    **metrics,
                }
                records.append(record)
                database.add_run(experiment_id, parameter_value=float(value), replicate=replicate, seed=seed, status="completed", metrics=metrics)
                emit(f"[{index:02d}/{total:02d}] value={value:.5g} rep={replicate + 1} · {spec.metric}={float(metrics[spec.metric]):.4g}")
            except Exception as exc:  # keep queue records rather than aborting the whole sweep
                failed = True
                error = f"{type(exc).__name__}: {exc}"
                record = {
                    "experiment_id": experiment_id,
                    "parameter": spec.parameter,
                    "parameter_value": float(value),
                    "replicate": replicate,
                    "seed": seed,
                    "status": "failed",
                    "wall_runtime_ms": 1000.0 * (time.perf_counter() - started),
                    "error": error,
                }
                records.append(record)
                database.add_run(experiment_id, parameter_value=float(value), replicate=replicate, seed=seed, status="failed", error=error)
                emit(f"[{index:02d}/{total:02d}] FAILED value={value:.5g}: {error}")
    database.finish_experiment(experiment_id, "completed_with_errors" if failed else "completed")
    frame = pd.DataFrame.from_records(records)
    summary = _summary(frame, spec.metric)
    emit(f"[done] completed={int((frame['status']=='completed').sum())}/{total}")
    return SweepResult(experiment_id, project, spec, frame, summary, tuple(lines))


def make_sweep_figure(result: SweepResult) -> go.Figure:
    summary = result.summary
    fig = go.Figure()
    if not summary.empty:
        error_plus = summary["ci95_high"] - summary["mean"]
        error_minus = summary["mean"] - summary["ci95_low"]
        fig.add_trace(
            go.Scatter(
                x=summary["parameter_value"],
                y=summary["mean"],
                mode="lines+markers",
                name="均值 ± 95% CI",
                line={"color": "#35d8ff", "width": 3},
                marker={"size": 8},
                error_y={"type": "data", "array": error_plus, "arrayminus": error_minus, "visible": True, "color": "#91a2bb"},
                hovertemplate="参数=%{x:.5g}<br>均值=%{y:.4g}<extra></extra>",
            )
        )
        completed = result.records[result.records["status"] == "completed"]
        fig.add_trace(
            go.Scatter(
                x=completed["parameter_value"], y=completed[result.spec.metric], mode="markers", name="单次试验",
                marker={"color": "rgba(255,200,87,.58)", "size": 6},
                hovertemplate="参数=%{x:.5g}<br>值=%{y:.4g}<extra></extra>",
            )
        )
    fig.update_layout(
        title={"text": f"批量扫参 · {SWEEP_PARAMETERS[result.spec.parameter]}", "x": 0.02},
        paper_bgcolor="#07101d", plot_bgcolor="#0d1828", font={"color": "#e7eef9"}, height=540,
        margin={"l": 65, "r": 30, "t": 70, "b": 65},
        xaxis={"title": SWEEP_PARAMETERS[result.spec.parameter], "gridcolor": "#26354d"},
        yaxis={"title": METRIC_LABELS[result.spec.metric], "gridcolor": "#26354d"},
        legend={"orientation": "h", "y": -0.20},
    )
    return fig


def export_sweep(result: SweepResult, root: str | Path) -> tuple[Path, Path]:
    root_path = Path(root)
    root_path.mkdir(parents=True, exist_ok=True)
    folder = root_path / result.experiment_id
    if folder.exists():
        shutil.rmtree(folder)
    folder.mkdir(parents=True)
    result.records.to_csv(folder / "sweep_runs.csv", index=False)
    result.summary.to_csv(folder / "sweep_summary.csv", index=False)
    result.project.save_yaml(folder / "project.yaml")
    (folder / "sweep_spec.json").write_text(json.dumps(result.spec.__dict__, ensure_ascii=False, indent=2), encoding="utf-8")
    (folder / "log.txt").write_text("\n".join(result.log_lines), encoding="utf-8")
    figure = make_sweep_figure(result)
    figure.write_html(folder / "sweep_figure.html", include_plotlyjs="inline", full_html=True, config={"displaylogo": False})
    report = folder / "HPM_CAE_sweep_report.html"
    table = result.summary.to_html(index=False, border=0)
    report.write_text(
        "<!doctype html><html lang='zh-CN'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'><title>HPM-CAE Sweep</title><style>body{margin:0;background:#07101d;color:#e7eef9;font-family:Inter,Segoe UI,Microsoft YaHei,sans-serif}main{max-width:1400px;margin:auto;padding:25px 4vw}section{background:#0d1828;border:1px solid #26354d;border-radius:12px;padding:16px;margin:16px 0}table{width:100%;border-collapse:collapse}th,td{padding:9px;border-bottom:1px solid #26354d}.scope{color:#91a2bb}</style></head><body><main><h1>HPM-CAE V1.0 批量扫参</h1><p>" + result.experiment_id + "</p><section>" + figure.to_html(full_html=False, include_plotlyjs="inline", config={"displaylogo": False}) + "</section><section><h2>统计摘要</h2>" + table + "</section><section><p class='scope'>本报告只含波长尺度几何、归一化复场和无量纲算法指标。</p></section></main></body></html>",
        encoding="utf-8",
    )
    archive = Path(shutil.make_archive(str(folder), "zip", root_dir=folder))
    return report, archive

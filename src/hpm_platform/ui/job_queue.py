"""Persistent pause/resume worker queue for HPM-CAE V1.2.

Jobs are checkpointed after every case in SQLite.  Pause is cooperative at case
boundaries: running numerical kernels finish, while no new case is dispatched.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
import json
import sqlite3
import threading
import time
import traceback
import uuid
from typing import Callable

import numpy as np
import pandas as pd

from hpm_platform.ui.experiment_manager import SweepSpec, set_project_parameter
from hpm_platform.ui.project_model import CAEProject
from hpm_platform.ui.quick_solver import solve_project

QueueCallback = Callable[[str], None] | None
_ACTIVE_THREADS: dict[tuple[str, str], threading.Thread] = {}
_ACTIVE_LOCK = threading.Lock()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class QueueRunSummary:
    job_id: str
    status: str
    total: int
    completed: int
    failed: int
    pending: int
    runtime_s: float


class PersistentJobQueue:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.path, timeout=30.0)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("PRAGMA busy_timeout=30000")
        return db

    def _initialize(self) -> None:
        with self._connect() as db:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS jobs (
                    job_id TEXT PRIMARY KEY,
                    created_utc TEXT NOT NULL,
                    updated_utc TEXT NOT NULL,
                    project_name TEXT NOT NULL,
                    project_json TEXT NOT NULL,
                    spec_json TEXT NOT NULL,
                    status TEXT NOT NULL,
                    requested_workers INTEGER NOT NULL,
                    message TEXT
                );
                CREATE TABLE IF NOT EXISTS job_items (
                    item_id TEXT PRIMARY KEY,
                    job_id TEXT NOT NULL,
                    item_index INTEGER NOT NULL,
                    parameter_value REAL NOT NULL,
                    replicate INTEGER NOT NULL,
                    seed INTEGER NOT NULL,
                    status TEXT NOT NULL,
                    started_utc TEXT,
                    finished_utc TEXT,
                    runtime_ms REAL,
                    metrics_json TEXT,
                    error_text TEXT,
                    worker_name TEXT,
                    FOREIGN KEY(job_id) REFERENCES jobs(job_id)
                );
                CREATE UNIQUE INDEX IF NOT EXISTS idx_job_item_index ON job_items(job_id,item_index);
                CREATE INDEX IF NOT EXISTS idx_job_item_status ON job_items(job_id,status);
                """
            )
            # A previously interrupted process cannot still own a running item.
            db.execute("UPDATE job_items SET status='pending', started_utc=NULL, worker_name=NULL WHERE status='running'")
            db.execute("UPDATE jobs SET status='paused', message='Recovered after process restart' WHERE status IN ('running','pause_requested')")

    def submit_sweep(self, project: CAEProject, spec: SweepSpec, *, workers: int | None = None) -> str:
        workers = int(workers or project.workflow.parallel_workers)
        if not 1 <= workers <= 8:
            raise ValueError("workers must be in [1, 8]")
        job_id = datetime.now(timezone.utc).strftime("JOB-%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:6]
        project_json = json.dumps(project.to_dict(), ensure_ascii=False)
        spec_json = json.dumps(spec.__dict__, ensure_ascii=False)
        rows = []
        index = 0
        for value in spec.values:
            for replicate in range(int(spec.replicates)):
                index += 1
                seed = int((project.meta.seed + 1009 * replicate + 65537 * index) % (2**32 - 1))
                rows.append((uuid.uuid4().hex[:18], job_id, index, float(value), replicate, seed, "pending"))
        now = _now()
        with self._connect() as db:
            db.execute(
                "INSERT INTO jobs VALUES (?,?,?,?,?,?,?,?,?)",
                (job_id, now, now, project.meta.name, project_json, spec_json, "queued", workers, f"Queued {len(rows)} cases"),
            )
            db.executemany(
                "INSERT INTO job_items(item_id,job_id,item_index,parameter_value,replicate,seed,status) VALUES (?,?,?,?,?,?,?)",
                rows,
            )
        return job_id

    def job(self, job_id: str) -> dict:
        with self._connect() as db:
            row = db.execute("SELECT * FROM jobs WHERE job_id=?", (job_id,)).fetchone()
        if row is None:
            raise KeyError(f"unknown job {job_id}")
        return dict(row)

    def jobs(self, limit: int = 50) -> pd.DataFrame:
        with self._connect() as db:
            rows = db.execute(
                """
                SELECT j.job_id,j.created_utc,j.updated_utc,j.project_name,j.status,j.requested_workers,j.message,
                       COUNT(i.item_id) total,
                       SUM(CASE WHEN i.status='completed' THEN 1 ELSE 0 END) completed,
                       SUM(CASE WHEN i.status='failed' THEN 1 ELSE 0 END) failed,
                       SUM(CASE WHEN i.status='pending' THEN 1 ELSE 0 END) pending,
                       SUM(CASE WHEN i.status='running' THEN 1 ELSE 0 END) running
                FROM jobs j LEFT JOIN job_items i ON j.job_id=i.job_id
                GROUP BY j.job_id ORDER BY j.created_utc DESC LIMIT ?
                """,
                (int(limit),),
            ).fetchall()
        columns = ["job_id", "created_utc", "project_name", "status", "requested_workers", "total", "completed", "failed", "pending", "running", "message"]
        if not rows:
            return pd.DataFrame(columns=columns)
        frame = pd.DataFrame([dict(row) for row in rows])
        return frame[columns]

    def items(self, job_id: str) -> pd.DataFrame:
        with self._connect() as db:
            rows = db.execute("SELECT * FROM job_items WHERE job_id=? ORDER BY item_index", (job_id,)).fetchall()
        output = []
        for row in rows:
            item = dict(row)
            metrics = json.loads(item.pop("metrics_json")) if item.get("metrics_json") else {}
            item.update(metrics)
            output.append(item)
        return pd.DataFrame(output)

    def _set_status(self, job_id: str, status: str, message: str) -> None:
        with self._connect() as db:
            db.execute("UPDATE jobs SET status=?,updated_utc=?,message=? WHERE job_id=?", (status, _now(), message, job_id))

    def pause(self, job_id: str) -> None:
        current = self.job(job_id)["status"]
        if current in {"completed", "completed_with_errors", "cancelled"}:
            return
        self._set_status(job_id, "pause_requested", "Pause requested; finishing active cases")

    def cancel(self, job_id: str) -> None:
        with self._connect() as db:
            db.execute("UPDATE jobs SET status='cancelled',updated_utc=?,message='Cancelled by user' WHERE job_id=?", (_now(), job_id))
            db.execute("UPDATE job_items SET status='cancelled',finished_utc=? WHERE job_id=? AND status='pending'", (_now(), job_id))

    def resume(self, job_id: str, *, workers: int | None = None, callback: QueueCallback = None) -> threading.Thread:
        row = self.job(job_id)
        if row["status"] in {"completed", "completed_with_errors", "cancelled"}:
            raise ValueError(f"job {job_id} is already terminal")
        if workers is not None:
            if not 1 <= int(workers) <= 8:
                raise ValueError("workers must be in [1, 8]")
            with self._connect() as db:
                db.execute("UPDATE jobs SET requested_workers=? WHERE job_id=?", (int(workers), job_id))
        self._set_status(job_id, "queued", "Queued for resume")
        return self.start(job_id, callback=callback)

    def start(self, job_id: str, *, callback: QueueCallback = None) -> threading.Thread:
        key = (str(self.path.resolve()), job_id)
        with _ACTIVE_LOCK:
            old = _ACTIVE_THREADS.get(key)
            if old is not None and old.is_alive():
                return old
            thread = threading.Thread(target=self.run_job, args=(job_id,), kwargs={"callback": callback}, daemon=True, name=f"hpm-cae-{job_id}")
            _ACTIVE_THREADS[key] = thread
            thread.start()
            return thread

    @staticmethod
    def _make_case(project: CAEProject, spec: SweepSpec, value: float, seed: int) -> CAEProject:
        case = set_project_parameter(project, spec.parameter, float(value))
        case = replace(case, meta=replace(case.meta, seed=int(seed)), motion=replace(case.motion, enabled=False))
        if spec.fast_mode:
            uncertain = spec.parameter in {"solver.phase_std_deg", "solver.gain_std_percent", "solver.registration_jitter_lambda"}
            case = replace(
                case,
                plane=replace(case.plane, samples=min(case.plane.samples, 51)),
                solver=replace(
                    case.solver,
                    method="Robust-PGMS" if uncertain else "Nominal-PGMS",
                    iterations=min(case.solver.iterations, 90),
                    uncertainty_scenarios=3 if uncertain else 1,
                    target_samples=min(case.solver.target_samples, 140),
                    outside_samples=min(case.solver.outside_samples, 300),
                ),
            )
        return case

    def _claim(self, job_id: str, limit: int) -> list[dict]:
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            rows = db.execute(
                "SELECT * FROM job_items WHERE job_id=? AND status='pending' ORDER BY item_index LIMIT ?",
                (job_id, int(limit)),
            ).fetchall()
            now = _now()
            for row in rows:
                db.execute("UPDATE job_items SET status='running',started_utc=? WHERE item_id=?", (now, row["item_id"]))
            db.commit()
        return [dict(row) for row in rows]

    def _execute_item(self, project: CAEProject, spec: SweepSpec, item: dict) -> tuple[str, dict | None, str | None, float, str]:
        started = time.perf_counter()
        worker = threading.current_thread().name
        try:
            case = self._make_case(project, spec, float(item["parameter_value"]), int(item["seed"]))
            result = solve_project(case)
            return "completed", dict(result.metrics), None, 1000.0 * (time.perf_counter() - started), worker
        except Exception:
            return "failed", None, traceback.format_exc(limit=8), 1000.0 * (time.perf_counter() - started), worker

    def _store_item(self, item_id: str, status: str, metrics: dict | None, error: str | None, runtime_ms: float, worker: str) -> None:
        with self._connect() as db:
            db.execute(
                "UPDATE job_items SET status=?,finished_utc=?,runtime_ms=?,metrics_json=?,error_text=?,worker_name=? WHERE item_id=?",
                (status, _now(), float(runtime_ms), json.dumps(metrics, ensure_ascii=False) if metrics is not None else None, error, worker, item_id),
            )

    def run_job(self, job_id: str, *, callback: QueueCallback = None, max_items: int | None = None) -> QueueRunSummary:
        started = time.perf_counter()
        row = self.job(job_id)
        project = CAEProject.from_dict(json.loads(row["project_json"]))
        spec = SweepSpec(**json.loads(row["spec_json"]))
        workers = int(row["requested_workers"])
        self._set_status(job_id, "running", f"Running with {workers} worker(s)")
        processed = 0

        def emit(message: str) -> None:
            if callback is not None:
                callback(message)

        emit(f"[queue] {job_id} started with {workers} worker(s)")
        while True:
            state = self.job(job_id)["status"]
            if state == "cancelled":
                break
            if state == "pause_requested":
                self._set_status(job_id, "paused", "Paused at a case checkpoint")
                emit(f"[queue] {job_id} paused")
                break
            if max_items is not None and processed >= int(max_items):
                self._set_status(job_id, "paused", f"Paused after test limit {max_items}")
                break
            allowance = workers
            if max_items is not None:
                allowance = min(allowance, int(max_items) - processed)
            claimed = self._claim(job_id, allowance)
            if not claimed:
                frame = self.items(job_id)
                failures = int((frame["status"] == "failed").sum()) if not frame.empty else 0
                terminal = "completed_with_errors" if failures else "completed"
                self._set_status(job_id, terminal, f"Finished {len(frame)} case(s); failures={failures}")
                emit(f"[queue] {job_id} {terminal}")
                break
            with ThreadPoolExecutor(max_workers=min(workers, len(claimed)), thread_name_prefix="cae-worker") as pool:
                futures = {pool.submit(self._execute_item, project, spec, item): item for item in claimed}
                for future in as_completed(futures):
                    item = futures[future]
                    status, metrics, error, runtime_ms, worker = future.result()
                    self._store_item(item["item_id"], status, metrics, error, runtime_ms, worker)
                    processed += 1
                    metric_text = ""
                    if metrics is not None and spec.metric in metrics:
                        metric_text = f" · {spec.metric}={float(metrics[spec.metric]):.4g}"
                    emit(f"[{item['item_index']}] {status} value={item['parameter_value']:.5g}{metric_text}")
            # Pause/cancel is checked after every concurrently running batch.

        frame = self.items(job_id)
        status = self.job(job_id)["status"]
        total = len(frame)
        completed = int((frame["status"] == "completed").sum()) if total else 0
        failed = int((frame["status"] == "failed").sum()) if total else 0
        pending = int(frame["status"].isin(["pending", "running"]).sum()) if total else 0
        return QueueRunSummary(job_id, status, total, completed, failed, pending, time.perf_counter() - started)

    def summary_frame(self, job_id: str) -> pd.DataFrame:
        row = self.job(job_id)
        spec = SweepSpec(**json.loads(row["spec_json"]))
        items = self.items(job_id)
        valid = items[items["status"] == "completed"].copy()
        if valid.empty or spec.metric not in valid:
            return pd.DataFrame(columns=["parameter_value", "mean", "std", "ci95_low", "ci95_high", "n"])
        rows = []
        for value, group in valid.groupby("parameter_value", sort=True):
            values = group[spec.metric].astype(float).to_numpy()
            mean = float(np.mean(values)); std = float(np.std(values, ddof=1)) if len(values) > 1 else 0.0
            half = 1.96 * std / np.sqrt(len(values)) if len(values) > 1 else 0.0
            rows.append({"parameter_value": float(value), "mean": mean, "std": std, "ci95_low": mean-half, "ci95_high": mean+half, "n": len(values)})
        return pd.DataFrame(rows)

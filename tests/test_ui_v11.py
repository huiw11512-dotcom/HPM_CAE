from dataclasses import replace
from pathlib import Path

import numpy as np

from hpm_platform.ui.experiment_manager import SweepSpec
from hpm_platform.ui.job_queue import PersistentJobQueue
from hpm_platform.ui.live_chain import run_live_perception, run_live_protection
from hpm_platform.ui.object_manager import add_target_row, apply_object_frames, project_to_object_frames
from hpm_platform.ui.project_model import TargetRegionSpec, default_project
from hpm_platform.ui.quick_solver import solve_project
from hpm_platform.ui.task_graph import GRAPH
from hpm_platform.ui.workflow_executor import execute_workflow


def fast_project():
    p = default_project()
    return replace(
        p,
        plane=replace(p.plane, samples=41),
        solver=replace(p.solver, iterations=50, target_samples=90, outside_samples=180, uncertainty_scenarios=2),
    )


def test_live_perception_and_protection_are_executable():
    p = fast_project()
    sensing = run_live_perception(p)
    protection = run_live_protection(p, sensing)
    assert sensing.spectrum.ndim == 2
    assert len(sensing.estimates) == len(sensing.truths)
    assert sensing.metrics["rmse_deg"] < 2.0
    assert protection.response_db.shape == (81, 181)
    assert np.isfinite(protection.metrics["output_sinr_db"])
    assert protection.metrics["sector_count"] == len(sensing.estimates)


def test_multi_object_tables_roundtrip_and_solver_uses_union():
    p = fast_project()
    targets, zones, sources = project_to_object_frames(p)
    targets = add_target_row(targets)
    q = apply_object_frames(p, targets, zones, sources)
    result = solve_project(q)
    assert len(q.targets) == 2
    assert result.metrics["target_count"] == 2
    assert np.count_nonzero(result.target_mask) > 0


def test_v10_payload_migrates_to_current_schema():
    p = default_project()
    payload = p.to_dict()
    payload["schema_version"] = "1.0"
    payload.pop("perception")
    payload.pop("protection")
    payload.pop("interferers")
    migrated = type(p).from_dict(payload)
    assert migrated.schema_version == "1.4"
    assert migrated.active_interferers


def test_task_graph_has_no_adapters_for_main_chain():
    main = GRAPH.closure(["report"])
    assert {"signal", "perception", "protection", "field_control", "effect_proxy"}.issubset(main)
    assert all(GRAPH.by_id[node].implementation == "live" for node in main)


def test_queue_pause_resume_checkpoint(tmp_path: Path):
    queue = PersistentJobQueue(tmp_path / "queue.sqlite3")
    job_id = queue.submit_sweep(fast_project(), SweepSpec(points=2, replicates=1, fast_mode=True), workers=2)
    first = queue.run_job(job_id, max_items=1)
    assert first.status == "paused"
    assert first.completed == 1
    second = queue.run_job(job_id)
    assert second.status == "completed"
    assert second.completed == 2
    assert queue.items(job_id)["worker_name"].notna().all()


def test_full_chain_executor_produces_normalized_score(tmp_path: Path):
    result = execute_workflow(fast_project(), export_root=tmp_path)
    assert result.effect_metrics["normalized_mission_score"] > 0
    assert isinstance(result.effect_metrics["full_chain_available"], bool)
    assert result.report_path and result.report_path.exists()
    assert result.archive_path and result.archive_path.exists()

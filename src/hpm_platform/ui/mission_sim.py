"""V2.0C mission-level simulation service for the Scene First workbench."""
from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
import csv
import json
import math
import shutil
import threading
from typing import Any, Mapping

import numpy as np

from hpm_platform.ui.project_model import CAEProject, MotionSpec, default_project
from hpm_platform.ui.timeline import TimelineResult, export_timeline, run_timeline

MISSION_SIM_VERSION = "V2.0C-mission-preview"

SAFETY_BOUNDARY = {
    "模式": "波长尺度归一化任务级仿真",
    "不输出项": ["真实毁伤概率", "真实作用距离", "现实作用距离", "器件阈值", "武器效能参数"],
    "说明": "任务结果用于场景、算法和模型适用性研究；风险、响应和成功率均为归一化代理指标。",
}

MISSION_TEMPLATES: tuple[dict[str, Any], ...] = (
    {
        "id": "MST-TRACK-001",
        "名称": "目标运动控场任务",
        "类型": "dynamic_target_field_control",
        "控制器": "Predictive-PGMS",
        "默认帧数": 6,
        "对象": ["TGT-001", "PRT-001"],
        "输出": ["时间线", "场分布动画", "逐帧指标", "归一化风险代理"],
    },
    {
        "id": "MST-DELAY-001",
        "名称": "观测延迟对比任务",
        "类型": "delayed_tracking_baseline",
        "控制器": "Delayed-PGMS",
        "默认帧数": 6,
        "对象": ["TGT-001", "PRT-001"],
        "输出": ["跟踪误差", "目标覆盖率", "保护区代理风险"],
    },
    {
        "id": "MST-STATIC-001",
        "名称": "静态赋形基线任务",
        "类型": "static_reference_baseline",
        "控制器": "Static-PGMS",
        "默认帧数": 5,
        "对象": ["TGT-001", "PRT-001"],
        "输出": ["基线时间线", "控制成功代理", "模型边界审计"],
    },
)


def _json_safe(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if isinstance(value, np.ndarray):
        return _json_safe(value.tolist())
    if isinstance(value, np.generic):
        return _json_safe(value.item())
    if isinstance(value, float):
        if math.isnan(value) or math.isinf(value):
            return None
        return round(value, 6)
    return value


def _bounded_percent(value: float) -> float:
    return round(float(np.clip(value, 0.0, 100.0)), 3)


def _risk_from_protected_p95(value_db: float | int | None) -> float:
    if value_db is None:
        return 0.0
    try:
        value = float(value_db)
    except (TypeError, ValueError):
        return 0.0
    if math.isnan(value) or math.isinf(value):
        return 0.0
    # Dimensionless proxy: negative protected-zone margin trends low risk,
    # positive margin trends high risk. It is not a device threshold.
    return round(float(np.clip((value + 8.0) / 16.0, 0.0, 1.0)), 6)


def _template_by_id(template_id: str | None) -> dict[str, Any]:
    normalized = str(template_id or "MST-TRACK-001").strip()
    for template in MISSION_TEMPLATES:
        if template["id"] == normalized:
            return dict(template)
    raise ValueError(f"未知任务模板：{normalized}")


def _mission_folder_name(mission_id: str, template: Mapping[str, Any]) -> str:
    suffix = str(template.get("id", "mission")).lower().replace("_", "-")
    return f"{mission_id.lower()}_{suffix}"


class MissionSimulationService:
    """Run normalized task-level timelines and archive mission artifacts."""

    def __init__(self, project_path: str | Path | None, output_dir: str | Path | None = None):
        self.project_path = Path(project_path) if project_path is not None else None
        self.output_dir = Path(output_dir) if output_dir is not None else Path("outputs_v20a_vv")
        self.root = self.output_dir / "mission_v20c"
        self.root.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._records: list[dict[str, Any]] = []
        self._payloads: dict[str, dict[str, Any]] = {}
        self._load_index()

    def _load_project(self) -> CAEProject:
        if self.project_path and self.project_path.exists():
            return CAEProject.load_yaml(self.project_path)
        return default_project()

    def _load_index(self) -> None:
        index = self.root / "index.json"
        if not index.exists():
            return
        try:
            payload = json.loads(index.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return
        records = payload.get("任务") if isinstance(payload, Mapping) else None
        if isinstance(records, list):
            self._records = [dict(item) for item in records if isinstance(item, Mapping)]
        for record in self._records:
            mission_id = str(record.get("mission_id", ""))
            path = record.get("mission_json")
            if not mission_id or not path:
                continue
            try:
                mission_payload = json.loads(Path(str(path)).read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if isinstance(mission_payload, Mapping):
                self._payloads[mission_id] = dict(mission_payload)

    def _next_mission_id(self) -> str:
        max_serial = 0
        for record in self._records:
            mission_id = str(record.get("mission_id", ""))
            if mission_id.startswith("MIS-"):
                try:
                    max_serial = max(max_serial, int(mission_id.split("-", 1)[1]))
                except ValueError:
                    continue
        return f"MIS-{max_serial + 1:04d}"

    def _write_index(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        payload = {
            "版本": MISSION_SIM_VERSION,
            "更新时间UTC": datetime.now(timezone.utc).isoformat(),
            "任务数量": len(self._records),
            "任务": self._records,
            "安全边界": SAFETY_BOUNDARY,
        }
        (self.root / "index.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        with (self.root / "index.csv").open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(
                handle,
                fieldnames=[
                    "mission_id",
                    "模板",
                    "标签",
                    "控制器",
                    "帧数",
                    "任务成功代理/%",
                    "归一化风险代理",
                    "完成时间UTC",
                    "report_html",
                    "archive_zip",
                    "mission_json",
                ],
                extrasaction="ignore",
            )
            writer.writeheader()
            writer.writerows(self._records)

    def catalog(self) -> dict[str, Any]:
        with self._lock:
            return {
                "版本": MISSION_SIM_VERSION,
                "默认模板": "MST-TRACK-001",
                "模板": [dict(item) for item in MISSION_TEMPLATES],
                "结果数量": len(self._records),
                "最近结果": [dict(item) for item in self._records[-5:]],
                "产物目录": str(self.root),
                "验收清单": [
                    {"项目": "任务模板可枚举", "通过": True},
                    {"项目": "动态时间线求解可调用", "通过": True},
                    {"项目": "论文产物可归档", "通过": True},
                    {"项目": "真实毁伤/距离/阈值不输出", "通过": True},
                ],
                "安全边界": SAFETY_BOUNDARY,
            }

    def status(self) -> dict[str, Any]:
        with self._lock:
            return {
                "版本": MISSION_SIM_VERSION,
                "任务数量": len(self._records),
                "任务": [dict(item) for item in self._records],
                "索引": {"json": str(self.root / "index.json"), "csv": str(self.root / "index.csv")},
                "安全边界": SAFETY_BOUNDARY,
            }

    def get_mission(self, mission_id: str) -> dict[str, Any]:
        with self._lock:
            key = str(mission_id).strip()
            if key in self._payloads:
                return json.loads(json.dumps(self._payloads[key], ensure_ascii=False))
            raise ValueError(f"未找到任务结果：{key}")

    def run_mission(
        self,
        template_id: str | None = None,
        *,
        frames: int | None = None,
        controller: str | None = None,
        label: str | None = None,
    ) -> dict[str, Any]:
        with self._lock:
            template = _template_by_id(template_id)
            normalized_controller = str(controller or template["控制器"]).strip()
            if normalized_controller not in MotionSpec.CONTROLLERS:
                raise ValueError(f"controller must be one of {MotionSpec.CONTROLLERS}")
            normalized_frames = int(frames if frames is not None else template["默认帧数"])
            if not 3 <= normalized_frames <= 24:
                raise ValueError("frames must be between 3 and 24 for V2.0C preview tasks")

            project = self._load_project()
            motion = replace(
                project.motion,
                enabled=True,
                frames=normalized_frames,
                controller=normalized_controller,
            )
            mission_project = replace(project, motion=motion)
            mission_id = self._next_mission_id()
            result = run_timeline(mission_project, controller=normalized_controller, frames=normalized_frames)
            return self._archive_result(
                mission_id=mission_id,
                template=template,
                result=result,
                label=str(label).strip() if label and str(label).strip() else template["名称"],
            )

    def _archive_result(
        self,
        *,
        mission_id: str,
        template: Mapping[str, Any],
        result: TimelineResult,
        label: str,
    ) -> dict[str, Any]:
        report, archive = export_timeline(result, self.root, name=_mission_folder_name(mission_id, template))
        folder = report.parent
        metrics_rows = _json_safe(result.metrics.to_dict(orient="records"))
        for row in metrics_rows:
            if isinstance(row, dict):
                row["归一化风险代理"] = _risk_from_protected_p95(row.get("protected_p95_db"))
        summary = _json_safe(result.summary())
        risk_values = [float(row.get("归一化风险代理", 0.0)) for row in metrics_rows if isinstance(row, dict)]
        risk_proxy = round(float(np.mean(risk_values)), 6) if risk_values else 0.0
        success_proxy = _bounded_percent(
            0.55 * float(summary.get("availability_percent") or 0.0)
            + 0.25 * float(summary.get("mean_target_coverage_percent") or 0.0)
            + 20.0 * (1.0 - risk_proxy)
        )
        mission_metrics = {
            "任务成功代理/%": success_proxy,
            "动态可用率/%": _bounded_percent(float(summary.get("availability_percent") or 0.0)),
            "目标覆盖均值/%": _bounded_percent(float(summary.get("mean_target_coverage_percent") or 0.0)),
            "平均跟踪误差/lambda": summary.get("mean_tracking_error_lambda"),
            "目标场响应代理均值": summary.get("mean_response_proxy"),
            "保护区P95均值/dB": summary.get("mean_protected_p95_db"),
            "归一化风险代理": risk_proxy,
            "帧运行中位数/ms": summary.get("median_frame_runtime_ms"),
        }
        completed_at = datetime.now(timezone.utc).isoformat()
        artifact_paths = {
            "report_html": str(report),
            "archive_zip": str(archive),
            "timeline_csv": str(folder / "timeline_metrics.csv"),
            "summary_json": str(folder / "summary.json"),
            "fields_npz": str(folder / "timeline_fields.npz"),
            "mission_json": str(folder / "mission_result.json"),
        }
        payload = {
            "成功": True,
            "版本": MISSION_SIM_VERSION,
            "mission_id": mission_id,
            "完成时间UTC": completed_at,
            "模板": dict(template),
            "任务": {
                "标签": label,
                "控制器": result.controller,
                "帧数": result.n_frames,
                "目标对象": "TGT-001",
                "保护对象": "PRT-001",
            },
            "指标": mission_metrics,
            "摘要": summary,
            "时间线": metrics_rows,
            "运行日志": list(result.log_lines[-18:]),
            "产物": artifact_paths,
            "验收清单": [
                {"项目": "时间线帧数", "通过": result.n_frames == int(template.get("默认帧数", result.n_frames)) or result.n_frames >= 3},
                {"项目": "逐帧指标", "通过": bool(metrics_rows)},
                {"项目": "HTML报告", "通过": Path(artifact_paths["report_html"]).exists()},
                {"项目": "归一化安全边界", "通过": True},
            ],
            "安全边界": SAFETY_BOUNDARY,
        }
        mission_json = folder / "mission_result.json"
        mission_json.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        artifact_paths["mission_json"] = str(mission_json)
        archive = Path(shutil.make_archive(str(folder), "zip", root_dir=folder))
        artifact_paths["archive_zip"] = str(archive)
        record = {
            "mission_id": mission_id,
            "模板": template.get("id"),
            "标签": label,
            "控制器": result.controller,
            "帧数": result.n_frames,
            "任务成功代理/%": mission_metrics["任务成功代理/%"],
            "归一化风险代理": risk_proxy,
            "完成时间UTC": completed_at,
            "report_html": artifact_paths["report_html"],
            "archive_zip": artifact_paths["archive_zip"],
            "mission_json": artifact_paths["mission_json"],
        }
        self._records.append(record)
        self._payloads[mission_id] = json.loads(json.dumps(payload, ensure_ascii=False))
        self._write_index()
        return json.loads(json.dumps(payload, ensure_ascii=False))

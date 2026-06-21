"""单用户本地工作区服务。"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from hpmdt.application.factories import (
    asset_entity,
    city_dynamic_project,
    empty_project,
    static_multi_receiver_project,
)
from hpmdt.domain.models import Entity, MissionDefinition, ProjectDocument, Transform
from hpmdt.infrastructure.project_store import ProjectStore
from hpmdt.solvers import SimulationResult, run_free_space


class Workspace:
    def __init__(self, root: str | Path):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.store = ProjectStore()
        self.project: ProjectDocument = city_dynamic_project()
        self.results: dict[str, SimulationResult | dict] = {}

    def bootstrap(self) -> dict[str, Any]:
        latest_result = None
        if self.project.result_summaries:
            result_id = self.project.result_summaries[-1].result_id
            stored = self.results.get(result_id)
            latest_result = stored.to_jsonable() if isinstance(stored, SimulationResult) else stored
        return {
            "project": self.project.model_dump(),
            "latest_result": latest_result,
            "examples": [
                {"id": "city", "name": "城市多对象动态覆盖"},
                {"id": "static", "name": "多接收器静态场调查"},
                {"id": "empty", "name": "空白工程"},
            ],
        }

    def load_example(self, example_id: str) -> ProjectDocument:
        factory = {
            "city": city_dynamic_project,
            "static": static_multi_receiver_project,
            "empty": empty_project,
        }.get(example_id)
        if factory is None:
            raise KeyError(example_id)
        self.project = factory()
        self.results = {}
        return self.project

    def add_entity(self, kind: str) -> Entity:
        serial = len(self.project.scene.entities) + 1
        entity = asset_entity(kind, serial)
        self.project.scene.entities.append(entity)
        return entity

    def update_entity(self, entity_id: str, payload: dict[str, Any]) -> Entity:
        entity = self.project.scene.entity(entity_id)
        if "name" in payload:
            entity.name = str(payload["name"])
        if "enabled" in payload:
            entity.enabled = bool(payload["enabled"])
        if "tags" in payload:
            entity.tags = [str(item) for item in payload["tags"]]
        if "transform" in payload:
            entity.transform = Transform.model_validate(payload["transform"])
        return entity

    def delete_entity(self, entity_id: str) -> None:
        self.project.scene.entities = [item for item in self.project.scene.entities if item.id != entity_id]

    def add_default_mission(self) -> MissionDefinition:
        mission = MissionDefinition(
            name="新建动态覆盖任务",
            mission_type="DynamicCoverageMission",
        )
        self.project.missions.append(mission)
        return mission

    def run(self, mission_id: str) -> SimulationResult:
        mission = next((item for item in self.project.missions if item.id == mission_id), None)
        if mission is None:
            raise KeyError(mission_id)
        result = run_free_space(self.project, mission)
        self.results[result.result_id] = result
        self.project.result_summaries.append(result.summary)
        return result

    def save(self, filename: str | None = None) -> Path:
        safe_name = filename or self.project.metadata.name.replace(" ", "_")
        path = self.root / safe_name
        serializable_results = {
            key: value for key, value in self.results.items() if isinstance(value, SimulationResult)
        }
        return self.store.save(path, self.project, serializable_results)

    def load_path(self, path: str | Path) -> ProjectDocument:
        project, results = self.store.load(path)
        self.project = project
        self.results = results
        return project

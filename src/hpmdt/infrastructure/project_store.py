"""*.hpmdt 工程容器读写。"""
from __future__ import annotations

import json
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

from hpmdt.domain.models import ProjectDocument
from hpmdt.solvers.free_space import SimulationResult


class ProjectStore:
    def save(
        self,
        path: str | Path,
        project: ProjectDocument,
        results: dict[str, SimulationResult] | None = None,
    ) -> Path:
        destination = Path(path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.suffix.lower() != ".hpmdt":
            destination = destination.with_suffix(".hpmdt")
        manifest = {
            "format": "HPM-DT Studio Project",
            "schema_version": project.metadata.schema_version,
            "app_version": project.metadata.app_version,
            "project_id": project.metadata.project_id,
            "project_name": project.metadata.name,
            "result_ids": sorted((results or {}).keys()),
        }
        with ZipFile(destination, "w", compression=ZIP_DEFLATED) as archive:
            archive.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
            archive.writestr(
                "metadata/project.json",
                project.metadata.model_dump_json(indent=2),
            )
            archive.writestr("scene/scene.json", project.scene.model_dump_json(indent=2))
            for mission in project.missions:
                archive.writestr(
                    f"missions/{mission.id}.json",
                    mission.model_dump_json(indent=2),
                )
            archive.writestr(
                "results/index.json",
                json.dumps(
                    [summary.model_dump() for summary in project.result_summaries],
                    ensure_ascii=False,
                    indent=2,
                ),
            )
            for result_id, result in (results or {}).items():
                archive.writestr(
                    f"results/{result_id}.json",
                    json.dumps(result.to_jsonable(), ensure_ascii=False),
                )
        return destination

    def load(self, path: str | Path) -> tuple[ProjectDocument, dict[str, dict]]:
        source = Path(path)
        with ZipFile(source, "r") as archive:
            metadata = json.loads(archive.read("metadata/project.json"))
            scene = json.loads(archive.read("scene/scene.json"))
            missions = []
            for name in sorted(item for item in archive.namelist() if item.startswith("missions/")):
                missions.append(json.loads(archive.read(name)))
            summaries = json.loads(archive.read("results/index.json"))
            project = ProjectDocument.model_validate(
                {
                    "metadata": metadata,
                    "scene": scene,
                    "missions": missions,
                    "result_summaries": summaries,
                }
            )
            results: dict[str, dict] = {}
            for name in archive.namelist():
                if name.startswith("results/") and name.endswith(".json") and name != "results/index.json":
                    result_id = Path(name).stem
                    results[result_id] = json.loads(archive.read(name))
        return project, results

from __future__ import annotations

import json
from zipfile import ZipFile

from hpmdt.application.factories import city_dynamic_project
from hpmdt.infrastructure.project_store import ProjectStore


def test_hpmdt_roundtrip(tmp_path):
    project = city_dynamic_project()
    store = ProjectStore()
    path = store.save(tmp_path / "工程.hpmdt", project)
    loaded, results = store.load(path)
    assert loaded.metadata.name == project.metadata.name
    assert len(loaded.scene.entities) == len(project.scene.entities)
    assert loaded.missions[0].solver.target_query == "role:trackable"
    assert results == {}


def test_hpmdt_container_has_expected_layout(tmp_path):
    path = ProjectStore().save(tmp_path / "工程.hpmdt", city_dynamic_project())
    with ZipFile(path) as archive:
        names = set(archive.namelist())
        assert "manifest.json" in names
        assert "scene/scene.json" in names
        assert "metadata/project.json" in names
        assert "results/index.json" in names
        manifest = json.loads(archive.read("manifest.json"))
        assert manifest["format"] == "HPM-DT Studio Project"

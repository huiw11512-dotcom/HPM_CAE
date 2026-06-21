from __future__ import annotations

from fastapi.testclient import TestClient

from hpmdt.api.app import app, workspace

client = TestClient(app)


def test_health_and_home():
    assert client.get("/api/health").status_code == 200
    response = client.get("/")
    assert response.status_code == 200
    assert "HPM-DT Studio" in response.text
    assert "场景树" in response.text


def test_bootstrap_returns_scene_first_project():
    response = client.post("/api/examples/city/load")
    assert response.status_code == 200
    data = response.json()
    assert len(data["project"]["scene"]["entities"]) >= 10
    assert data["project"]["missions"][0]["solver"]["target_query"] == "role:trackable"


def test_entity_crud_api():
    client.post("/api/examples/empty/load")
    created = client.post("/api/entities", json={"kind": "receiver"})
    assert created.status_code == 200
    entity_id = created.json()["id"]
    updated = client.patch(
        f"/api/entities/{entity_id}",
        json={
            "name": "API接收器",
            "transform": {
                "position_m": {"x": 2, "y": 3, "z": 4},
                "rotation_deg": {"x": 0, "y": 0, "z": 0},
                "scale": {"x": 1, "y": 1, "z": 1},
            },
        },
    )
    assert updated.json()["name"] == "API接收器"
    assert client.delete(f"/api/entities/{entity_id}").status_code == 200


def test_static_mission_api_runs():
    data = client.post("/api/examples/static/load").json()
    mission_id = data["project"]["missions"][0]["id"]
    response = client.post(f"/api/missions/{mission_id}/run")
    assert response.status_code == 200
    result = response.json()
    assert result["summary"]["receiver_count"] == 3
    assert len(result["plane"]["field"]) == 1


def test_new_and_open_project_api(tmp_path):
    from hpmdt.application.factories import static_multi_receiver_project
    from hpmdt.infrastructure.project_store import ProjectStore

    blank = client.post("/api/project/new")
    assert blank.status_code == 200
    assert blank.json()["project"]["metadata"]["name"] == "未命名工程"

    source = ProjectStore().save(tmp_path / "待打开工程.hpmdt", static_multi_receiver_project())
    with source.open("rb") as handle:
        response = client.post(
            "/api/project/open",
            files={"file": (source.name, handle, "application/zip")},
        )
    assert response.status_code == 200
    assert response.json()["project"]["metadata"]["name"] == "多接收器静态场调查"

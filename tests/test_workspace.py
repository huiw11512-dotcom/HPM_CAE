from __future__ import annotations

from hpmdt.application.workspace import Workspace


def test_workspace_add_update_delete(tmp_path):
    workspace = Workspace(tmp_path)
    entity = workspace.add_entity("building")
    workspace.update_entity(
        entity.id,
        {
            "name": "新建筑",
            "transform": {
                "position_m": {"x": 1, "y": 2, "z": 3},
                "rotation_deg": {"x": 0, "y": 0, "z": 15},
                "scale": {"x": 1, "y": 1, "z": 1},
            },
        },
    )
    assert workspace.project.scene.entity(entity.id).name == "新建筑"
    workspace.delete_entity(entity.id)
    assert all(item.id != entity.id for item in workspace.project.scene.entities)


def test_workspace_save(tmp_path):
    workspace = Workspace(tmp_path)
    path = workspace.save("测试工程")
    assert path.exists()
    assert path.suffix == ".hpmdt"

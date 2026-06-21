from __future__ import annotations

from hpmdt.application.factories import city_dynamic_project, empty_project
from hpmdt.domain.models import Entity, GeometryComponent, RoleComponent
from hpmdt.domain.query import matches, select


def test_city_example_contains_physical_objects_not_target_regions():
    project = city_dynamic_project()
    assert len(select(project.scene.entities, "role:emitter_platform")) == 2
    assert len(select(project.scene.entities, "role:trackable")) == 3
    assert len(select(project.scene.entities, "component:receiver")) == 4
    assert all(component.type not in {"target_region", "protected_zone"} for entity in project.scene.entities for component in entity.components)


def test_entity_query_by_role_component_and_tag():
    entity = Entity(
        name="测试对象",
        tags=["group-a"],
        components=[GeometryComponent(), RoleComponent(roles=["trackable"])],
    )
    assert matches(entity, "role:trackable")
    assert matches(entity, "component:geometry tag:group-a")
    assert not matches(entity, "role:environment")


def test_empty_project_only_has_ground_proxy():
    project = empty_project()
    assert len(project.scene.entities) == 1
    assert project.scene.entities[0].has_role("environment")

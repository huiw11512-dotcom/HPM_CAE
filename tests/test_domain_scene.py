from __future__ import annotations

import math
from uuid import uuid4

import pytest

from hpmdt.domain import (
    ArrayComponent,
    EmitterComponent,
    Entity,
    GeometryComponent,
    MaterialComponent,
    MotionComponent,
    ReceiverComponent,
    RoleComponent,
    SceneDocument,
    Transform,
)
from hpmdt.domain.scene import SceneError
from hpmdt.domain.units import angle_to_rad, frequency_to_hz, length_from_m, length_to_m, time_to_s


def test_scene_graph_tracks_parent_child_hierarchy() -> None:
    scene = SceneDocument(name="scene")
    platform_id = scene.add_entity(Entity(name="platform", tags={"group-a"}))
    sensor = Entity(name="sensor", parent_id=platform_id)
    sensor.add_component(ReceiverComponent())
    sensor_id = scene.add_entity(sensor)

    assert scene.roots()[0].id == platform_id
    assert [child.id for child in scene.children_of(platform_id)] == [sensor_id]
    assert scene.query(f"parent:{platform_id}") == [sensor]
    assert scene.query("parent:platform") == [sensor]


def test_entities_can_be_added_updated_and_removed() -> None:
    scene = SceneDocument(name="edit")
    entity = Entity(name="vehicle")
    entity.add_component(GeometryComponent(primitive="box"))
    entity_id = scene.add_entity(entity)

    updated = scene.get_entity(entity_id)
    updated.name = "vehicle-renamed"
    updated.transform = Transform(position_m=(1.0, 2.0, 3.0))
    updated.add_component(MaterialComponent(material_proxy="metal"))
    scene.update_entity(updated)

    assert scene.get_entity(entity_id).name == "vehicle-renamed"
    assert scene.get_entity(entity_id).transform.position_m == (1.0, 2.0, 3.0)
    assert scene.get_entity(entity_id).has_component(MaterialComponent)

    scene.remove_entity(entity_id)
    assert scene.all_entities() == []


@pytest.mark.parametrize("entity_count", [0, 1, 3, 20])
def test_scene_accepts_arbitrary_entity_counts(entity_count: int) -> None:
    scene = SceneDocument(name="count")
    for index in range(entity_count):
        scene.add_entity(Entity(name=f"entity-{index}", tags={f"n-{index}"}))

    assert len(scene.all_entities()) == entity_count


def test_queries_select_by_uuid_tag_role_component_and_parent() -> None:
    scene = SceneDocument(name="query")
    root_id = scene.add_entity(Entity(name="platform-root"))
    emitter = Entity(name="array-platform", parent_id=root_id, tags={"group-a"})
    emitter.add_component(ArrayComponent(element_positions_m=((0.0, 0.0, 0.0), (0.5, 0.0, 0.0))))
    emitter.add_component(EmitterComponent(operating_state="on"))
    emitter.add_component(RoleComponent(roles=("emitter", "controller")))
    emitter_id = scene.add_entity(emitter)

    trackable = Entity(name="moving-object", parent_id=root_id, tags={"group-b"})
    trackable.add_component(MotionComponent(motion_type="linear", velocity_mps=(1.0, 0.0, 0.0)))
    trackable.add_component(RoleComponent(roles=("trackable",)))
    scene.add_entity(trackable)

    assert scene.query(f"id:{emitter_id}") == [emitter]
    assert scene.query("tag:group-a") == [emitter]
    assert scene.query("role:emitter component:ArrayComponent") == [emitter]
    assert scene.query("role:trackable component:MotionComponent") == [trackable]
    assert len(scene.query("parent:platform-root")) == 2


def test_scene_rejects_missing_parent_and_cycles() -> None:
    scene = SceneDocument(name="validation")
    root = Entity(name="root")
    child = Entity(name="child")
    root_id = scene.add_entity(root)
    child.parent_id = root_id
    child_id = scene.add_entity(child)

    root.parent_id = child_id
    with pytest.raises(SceneError):
        scene.update_entity(root)

    with pytest.raises(SceneError):
        scene.add_entity(Entity(name="orphan", parent_id=uuid4()))


def test_scene_serialization_round_trips_components() -> None:
    scene = SceneDocument(name="roundtrip")
    entity = Entity(name="array", tags={"demo"})
    entity.add_component(ArrayComponent(element_positions_m=((0, 0, 0), (1, 0, 0))))
    entity.add_component(RoleComponent(roles=("emitter",)))
    scene.add_entity(entity)

    restored = SceneDocument.from_dict(scene.to_dict())

    restored_entity = restored.query("role:emitter component:ArrayComponent")[0]
    assert restored_entity.name == "array"
    assert restored_entity.tags == {"demo"}
    assert restored_entity.get_component(ArrayComponent).element_positions_m == (
        (0.0, 0.0, 0.0),
        (1.0, 0.0, 0.0),
    )


def test_si_unit_conversions_are_explicit() -> None:
    assert length_to_m(250.0, "mm") == 0.25
    assert length_from_m(0.25, "cm") == 25.0
    assert frequency_to_hz(2.45, "GHz") == 2.45e9
    assert time_to_s(30.0, "ms") == 0.03
    assert math.isclose(angle_to_rad(180.0, "deg"), math.pi)


def test_domain_does_not_define_legacy_region_entities() -> None:
    import hpmdt.domain as domain

    exported = set(domain.__all__)
    assert "TargetRegion" not in exported
    assert "ProtectedZone" not in exported
    assert "ObservationPlane" not in exported

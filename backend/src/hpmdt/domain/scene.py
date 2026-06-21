"""Scene graph and entity query support."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable
from uuid import UUID, uuid4

from hpmdt.domain.components import RoleComponent, component_type_names
from hpmdt.domain.entity import Entity


class SceneError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class EntityQuery:
    expression: str

    def tokens(self) -> list[tuple[str, str]]:
        tokens: list[tuple[str, str]] = []
        for raw_token in self.expression.split():
            if ":" not in raw_token:
                raise SceneError(f"Invalid entity query token: {raw_token}")
            key, value = raw_token.split(":", 1)
            tokens.append((key.strip(), value.strip()))
        return tokens


@dataclass(slots=True)
class SceneDocument:
    name: str
    id: UUID = field(default_factory=uuid4)
    units: dict[str, str] = field(default_factory=lambda: {"length": "m", "time": "s", "frequency": "Hz"})
    coordinate_system: str = "ENU"
    entities: dict[UUID, Entity] = field(default_factory=dict)

    def add_entity(self, entity: Entity) -> UUID:
        if entity.id in self.entities:
            raise SceneError(f"Entity already exists: {entity.id}")
        if entity.parent_id is not None and entity.parent_id not in self.entities:
            raise SceneError(f"Parent entity does not exist: {entity.parent_id}")
        self.entities[entity.id] = entity
        return entity.id

    def update_entity(self, entity: Entity) -> None:
        if entity.id not in self.entities:
            raise SceneError(f"Entity does not exist: {entity.id}")
        if entity.parent_id == entity.id:
            raise SceneError("Entity cannot be its own parent")
        if entity.parent_id is not None and entity.parent_id not in self.entities:
            raise SceneError(f"Parent entity does not exist: {entity.parent_id}")
        if self._would_create_cycle(entity.id, entity.parent_id):
            raise SceneError("Parent update would create a scene graph cycle")
        self.entities[entity.id] = entity

    def get_entity(self, entity_id: UUID) -> Entity:
        try:
            return self.entities[entity_id]
        except KeyError as exc:
            raise SceneError(f"Entity does not exist: {entity_id}") from exc

    def remove_entity(self, entity_id: UUID, *, cascade: bool = True) -> None:
        child_ids = [entity.id for entity in self.children_of(entity_id)]
        if child_ids and not cascade:
            raise SceneError("Entity has children; set cascade=True to remove them")
        for child_id in child_ids:
            self.remove_entity(child_id, cascade=True)
        self.entities.pop(entity_id, None)

    def children_of(self, entity_id: UUID) -> list[Entity]:
        return [entity for entity in self.entities.values() if entity.parent_id == entity_id]

    def roots(self) -> list[Entity]:
        return [entity for entity in self.entities.values() if entity.parent_id is None]

    def all_entities(self) -> list[Entity]:
        return list(self.entities.values())

    def query(self, query: str | EntityQuery) -> list[Entity]:
        entity_query = query if isinstance(query, EntityQuery) else EntityQuery(query)
        matches: Iterable[Entity] = self.entities.values()
        for key, value in entity_query.tokens():
            matches = [entity for entity in matches if self._matches(entity, key, value)]
        return list(matches)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "name": self.name,
            "units": dict(self.units),
            "coordinate_system": self.coordinate_system,
            "entities": [entity.to_dict() for entity in self.entities.values()],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SceneDocument:
        scene = cls(
            id=UUID(data["id"]),
            name=data["name"],
            units=dict(data.get("units", {})),
            coordinate_system=data.get("coordinate_system", "ENU"),
        )
        for entity_data in data.get("entities", []):
            scene.add_entity(Entity.from_dict(entity_data))
        return scene

    def _matches(self, entity: Entity, key: str, value: str) -> bool:
        if key == "id":
            return str(entity.id) == value
        if key == "name":
            return entity.name == value
        if key == "tag":
            return value in entity.tags
        if key == "enabled":
            return entity.enabled is (value.lower() == "true")
        if key == "component":
            return value in component_type_names() and entity.has_component(value)
        if key == "role":
            role_component = entity.get_component(RoleComponent)
            return role_component is not None and role_component.has_role(value)
        if key == "parent":
            return self._matches_parent(entity, value)
        raise SceneError(f"Unsupported entity query key: {key}")

    def _matches_parent(self, entity: Entity, value: str) -> bool:
        if entity.parent_id is None:
            return value in {"none", "root"}
        parent = self.entities.get(entity.parent_id)
        return str(entity.parent_id) == value or (parent is not None and parent.name == value)

    def _would_create_cycle(self, entity_id: UUID, parent_id: UUID | None) -> bool:
        next_parent = parent_id
        while next_parent is not None:
            if next_parent == entity_id:
                return True
            parent = self.entities.get(next_parent)
            next_parent = parent.parent_id if parent else None
        return False

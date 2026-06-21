"""Generic entities used by the Studio scene graph."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, TypeVar
from uuid import UUID, uuid4

from hpmdt.domain.components import Component, component_from_dict
from hpmdt.domain.units import Quaternion, Vec3, quaternion, vec3

TComponent = TypeVar("TComponent", bound=Component)


@dataclass(slots=True)
class Transform:
    position_m: Vec3 = (0.0, 0.0, 0.0)
    rotation_quaternion: Quaternion = (0.0, 0.0, 0.0, 1.0)
    scale: Vec3 = (1.0, 1.0, 1.0)

    def __post_init__(self) -> None:
        self.position_m = vec3(self.position_m)
        self.rotation_quaternion = quaternion(self.rotation_quaternion)
        self.scale = vec3(self.scale)

    def to_dict(self) -> dict[str, Any]:
        return {
            "position_m": list(self.position_m),
            "rotation_quaternion": list(self.rotation_quaternion),
            "scale": list(self.scale),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Transform:
        return cls(
            position_m=data.get("position_m", (0.0, 0.0, 0.0)),
            rotation_quaternion=data.get("rotation_quaternion", (0.0, 0.0, 0.0, 1.0)),
            scale=data.get("scale", (1.0, 1.0, 1.0)),
        )


@dataclass(slots=True)
class Entity:
    name: str
    id: UUID = field(default_factory=uuid4)
    parent_id: UUID | None = None
    enabled: bool = True
    tags: set[str] = field(default_factory=set)
    transform: Transform = field(default_factory=Transform)
    components: list[Component] = field(default_factory=list)

    def add_component(self, component: Component) -> None:
        self.remove_component(type(component))
        self.components.append(component)

    def get_component(self, component_cls: type[TComponent]) -> TComponent | None:
        for component in self.components:
            if isinstance(component, component_cls):
                return component
        return None

    def has_component(self, component_cls: type[Component] | str) -> bool:
        if isinstance(component_cls, str):
            return any(component.type_name == component_cls for component in self.components)
        return self.get_component(component_cls) is not None

    def components_of(self, component_cls: type[TComponent]) -> list[TComponent]:
        return [component for component in self.components if isinstance(component, component_cls)]

    def remove_component(self, component_cls: type[Component] | str) -> bool:
        before = len(self.components)
        if isinstance(component_cls, str):
            self.components = [component for component in self.components if component.type_name != component_cls]
        else:
            self.components = [component for component in self.components if not isinstance(component, component_cls)]
        return len(self.components) != before

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "name": self.name,
            "parent_id": str(self.parent_id) if self.parent_id else None,
            "enabled": self.enabled,
            "tags": sorted(self.tags),
            "transform": self.transform.to_dict(),
            "components": [component.to_dict() for component in self.components],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Entity:
        return cls(
            id=UUID(data["id"]),
            name=data["name"],
            parent_id=UUID(data["parent_id"]) if data.get("parent_id") else None,
            enabled=bool(data.get("enabled", True)),
            tags=set(data.get("tags", [])),
            transform=Transform.from_dict(data.get("transform", {})),
            components=[component_from_dict(item) for item in data.get("components", [])],
        )

"""Entity components for the generic Studio scene graph."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field, fields, is_dataclass
from typing import Any, ClassVar
from uuid import UUID

from hpmdt.domain.units import Vec2, Vec3, vec3


def _normalize(value: Any) -> Any:
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, set):
        return sorted(value)
    if isinstance(value, tuple):
        return [_normalize(item) for item in value]
    if isinstance(value, list):
        return [_normalize(item) for item in value]
    if isinstance(value, dict):
        return {key: _normalize(item) for key, item in value.items()}
    if is_dataclass(value):
        return _normalize(asdict(value))
    return value


@dataclass(slots=True)
class Component:
    """Base class for composable entity behavior."""

    component_type: ClassVar[str] = "Component"
    enabled: bool = True
    schema_version: int = 1

    @property
    def type_name(self) -> str:
        return self.__class__.__name__

    def to_dict(self) -> dict[str, Any]:
        payload = _normalize(asdict(self))
        payload["type"] = self.type_name
        return payload


@dataclass(slots=True)
class GeometryComponent(Component):
    primitive: str = "box"
    mesh_asset: str | None = None
    bounding_box_m: tuple[Vec3, Vec3] = ((-0.5, -0.5, -0.5), (0.5, 0.5, 0.5))

    def __post_init__(self) -> None:
        self.bounding_box_m = (
            vec3(self.bounding_box_m[0]),
            vec3(self.bounding_box_m[1]),
        )


@dataclass(slots=True)
class MaterialComponent(Component):
    material_proxy: str = "generic"
    visual_material: dict[str, Any] = field(default_factory=lambda: {"color": "#8aa4b8"})
    propagation_properties: dict[str, float] = field(default_factory=dict)


@dataclass(slots=True)
class MotionComponent(Component):
    motion_type: str = "static"
    velocity_mps: Vec3 = (0.0, 0.0, 0.0)
    waypoints_m: tuple[Vec3, ...] = ()
    angular_rate_rad_s: float = 0.0
    trajectory_asset: str | None = None

    def __post_init__(self) -> None:
        self.velocity_mps = vec3(self.velocity_mps)
        self.waypoints_m = tuple(vec3(point) for point in self.waypoints_m)


@dataclass(slots=True)
class ArrayComponent(Component):
    array_geometry: str = "rectangular"
    mounting_frame: str = "entity"
    element_positions_m: tuple[Vec3, ...] = ()
    element_state: dict[str, Any] = field(default_factory=dict)
    beam_weights: tuple[tuple[float, float], ...] = ()

    def __post_init__(self) -> None:
        self.element_positions_m = tuple(vec3(point) for point in self.element_positions_m)
        self.beam_weights = tuple((float(real), float(imag)) for real, imag in self.beam_weights)


@dataclass(slots=True)
class EmitterComponent(Component):
    source_definition: str = "normalized"
    waveform_ref: str | None = None
    operating_state: str = "off"
    normalized_amplitude: float = 1.0
    authorized_power_w: float | None = None


@dataclass(slots=True)
class ReceiverComponent(Component):
    receiver_model: str = "point"
    noise_model: dict[str, float] = field(default_factory=dict)
    saturation_proxy: float | None = None


@dataclass(slots=True)
class ScattererComponent(Component):
    reflection_proxy: float = 0.5
    scattering_mode: str = "specular"
    model_backend: str = "reduced"


@dataclass(slots=True)
class BoundaryComponent(Component):
    boundary_type: str = "reflective_surface"
    semantics: str = "wall"
    absorption_proxy: float = 0.0


@dataclass(slots=True)
class ApertureComponent(Component):
    attached_entity_id: UUID | None = None
    local_position_m: Vec3 = (0.0, 0.0, 0.0)
    local_normal: Vec3 = (0.0, 0.0, 1.0)
    coupling_proxy: dict[str, float] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.local_position_m = vec3(self.local_position_m)
        self.local_normal = vec3(self.local_normal)


@dataclass(slots=True)
class EnclosureComponent(Component):
    cavity_geometry: str = "box"
    mode_configuration: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ProbeComponent(Component):
    probe_type: str = "point"
    local_points_m: tuple[Vec3, ...] = ((0.0, 0.0, 0.0),)
    plane_size_m: Vec2 | None = None
    sample_shape: tuple[int, int] | None = None
    attached_entity_id: UUID | None = None

    def __post_init__(self) -> None:
        self.local_points_m = tuple(vec3(point) for point in self.local_points_m)
        if self.plane_size_m is not None:
            self.plane_size_m = (float(self.plane_size_m[0]), float(self.plane_size_m[1]))
        if self.sample_shape is not None:
            self.sample_shape = (int(self.sample_shape[0]), int(self.sample_shape[1]))


@dataclass(slots=True)
class RoleComponent(Component):
    roles: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        self.roles = tuple(sorted({role.strip() for role in self.roles if role.strip()}))

    def has_role(self, role: str) -> bool:
        return role in self.roles


@dataclass(slots=True)
class UncertaintyComponent(Component):
    position_std_m: Vec3 = (0.0, 0.0, 0.0)
    orientation_std_rad: Vec3 = (0.0, 0.0, 0.0)
    amplitude_std: float = 0.0
    phase_std_rad: float = 0.0

    def __post_init__(self) -> None:
        self.position_std_m = vec3(self.position_std_m)
        self.orientation_std_rad = vec3(self.orientation_std_rad)


_COMPONENT_TYPES: dict[str, type[Component]] = {
    cls.__name__: cls
    for cls in (
        GeometryComponent,
        MaterialComponent,
        MotionComponent,
        ArrayComponent,
        EmitterComponent,
        ReceiverComponent,
        ScattererComponent,
        BoundaryComponent,
        ApertureComponent,
        EnclosureComponent,
        ProbeComponent,
        RoleComponent,
        UncertaintyComponent,
    )
}


def component_from_dict(data: dict[str, Any]) -> Component:
    payload = dict(data)
    type_name = payload.pop("type")
    cls = _COMPONENT_TYPES[type_name]
    valid_fields = {field_info.name for field_info in fields(cls)}
    return cls(**{key: value for key, value in payload.items() if key in valid_fields})


def component_type_names() -> set[str]:
    return set(_COMPONENT_TYPES)

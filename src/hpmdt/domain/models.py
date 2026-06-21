"""HPM-DT Studio 的通用场景领域模型。

核心原则：
- 物理实体优先；
- 能力通过组件组合；
- 任务通过查询选择实体；
- 分析区域不是场景主角。
"""
from __future__ import annotations

from typing import Annotated, Literal, Union
from uuid import uuid4

from pydantic import BaseModel, Field, field_validator


class Vec3(BaseModel):
    x: float = 0.0
    y: float = 0.0
    z: float = 0.0

    def as_list(self) -> list[float]:
        return [float(self.x), float(self.y), float(self.z)]


class Transform(BaseModel):
    position_m: Vec3 = Field(default_factory=Vec3)
    rotation_deg: Vec3 = Field(default_factory=Vec3)
    scale: Vec3 = Field(default_factory=lambda: Vec3(x=1.0, y=1.0, z=1.0))


class GeometryComponent(BaseModel):
    type: Literal["geometry"] = "geometry"
    shape: Literal[
        "box",
        "sphere",
        "cylinder",
        "aircraft",
        "vehicle",
        "array_panel",
        "receiver",
        "plane",
    ] = "box"
    dimensions_m: Vec3 = Field(default_factory=lambda: Vec3(x=1.0, y=1.0, z=1.0))
    color: str = "#64748b"
    opacity: float = 1.0

    @field_validator("opacity")
    @classmethod
    def opacity_range(cls, value: float) -> float:
        if not 0.0 <= value <= 1.0:
            raise ValueError("透明度必须位于0到1之间")
        return value


class MaterialComponent(BaseModel):
    type: Literal["material"] = "material"
    material_name: str = "归一化材料"
    relative_permittivity: float = 1.0
    loss_tangent: float = 0.0
    reflection_magnitude: float = 0.0
    reflection_phase_deg: float = 180.0


class ArrayComponent(BaseModel):
    type: Literal["array"] = "array"
    nx: int = 4
    ny: int = 4
    frequency_hz: float = 10e9
    dx_m: float | None = None
    dy_m: float | None = None
    boresight_axis: Literal["+x", "-x", "+y", "-y", "+z", "-z"] = "+z"

    @field_validator("nx", "ny")
    @classmethod
    def positive_count(cls, value: int) -> int:
        if value < 1:
            raise ValueError("阵列规模必须为正整数")
        return value


class EmitterComponent(BaseModel):
    type: Literal["emitter"] = "emitter"
    enabled: bool = True
    normalized_amplitude: float = 1.0
    phase_deg: float = 0.0
    channel: str = "默认通道"


class ReceiverComponent(BaseModel):
    type: Literal["receiver"] = "receiver"
    enabled: bool = True
    noise_floor_normalized: float = 0.01
    saturation_proxy: float = 3.0


class Waypoint(BaseModel):
    time_s: float
    position_m: Vec3


class MotionComponent(BaseModel):
    type: Literal["motion"] = "motion"
    mode: Literal["static", "linear", "waypoint", "circular"] = "static"
    velocity_mps: Vec3 = Field(default_factory=Vec3)
    waypoints: list[Waypoint] = Field(default_factory=list)
    circle_center_m: Vec3 = Field(default_factory=Vec3)
    circle_radius_m: float = 1.0
    circle_period_s: float = 10.0
    loop: bool = False


class BoundaryComponent(BaseModel):
    type: Literal["boundary"] = "boundary"
    boundary_kind: Literal["reflective", "absorbing", "ground_proxy"] = "reflective"
    enabled: bool = True


class ScattererComponent(BaseModel):
    type: Literal["scatterer"] = "scatterer"
    model: Literal["none", "image_plane_proxy", "point_scatterer_proxy"] = "none"
    strength: float = 0.3


class EnclosureComponent(BaseModel):
    type: Literal["enclosure"] = "enclosure"
    mode_count: int = 8
    damping_proxy: float = 0.15


class ApertureComponent(BaseModel):
    type: Literal["aperture"] = "aperture"
    coupling_proxy: float = 0.15
    attached_surface_id: str | None = None


class ProbeComponent(BaseModel):
    type: Literal["probe"] = "probe"
    probe_kind: Literal["point", "line", "plane", "volume"] = "point"
    dimensions_m: Vec3 = Field(default_factory=lambda: Vec3(x=20.0, y=20.0, z=0.0))
    resolution: list[int] = Field(default_factory=lambda: [35, 35, 1])
    attached_entity_id: str | None = None
    enabled: bool = True

    @field_validator("resolution")
    @classmethod
    def validate_resolution(cls, value: list[int]) -> list[int]:
        if len(value) != 3 or any(item < 1 for item in value):
            raise ValueError("探针分辨率必须包含3个正整数")
        return value


class RoleComponent(BaseModel):
    type: Literal["role"] = "role"
    roles: list[
        Literal[
            "emitter_platform",
            "receiver",
            "trackable",
            "protected_asset",
            "environment",
            "observer",
            "controller",
        ]
    ] = Field(default_factory=list)


class UncertaintyComponent(BaseModel):
    type: Literal["uncertainty"] = "uncertainty"
    position_std_m: Vec3 = Field(default_factory=Vec3)
    orientation_std_deg: Vec3 = Field(default_factory=Vec3)
    amplitude_std: float = 0.0
    phase_std_deg: float = 0.0


Component = Annotated[
    Union[
        GeometryComponent,
        MaterialComponent,
        ArrayComponent,
        EmitterComponent,
        ReceiverComponent,
        MotionComponent,
        BoundaryComponent,
        ScattererComponent,
        EnclosureComponent,
        ApertureComponent,
        ProbeComponent,
        RoleComponent,
        UncertaintyComponent,
    ],
    Field(discriminator="type"),
]


class Entity(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    name: str
    parent_id: str | None = None
    enabled: bool = True
    tags: list[str] = Field(default_factory=list)
    transform: Transform = Field(default_factory=Transform)
    components: list[Component] = Field(default_factory=list)

    def component(self, component_type: str):
        return next((item for item in self.components if item.type == component_type), None)

    def has_component(self, component_type: str) -> bool:
        return self.component(component_type) is not None

    def has_role(self, role: str) -> bool:
        role_component = self.component("role")
        return bool(role_component and role in role_component.roles)


class SceneDocument(BaseModel):
    coordinate_system: str = "右手笛卡尔坐标系，+z向上"
    length_unit: Literal["m"] = "m"
    entities: list[Entity] = Field(default_factory=list)

    def entity(self, entity_id: str) -> Entity:
        for item in self.entities:
            if item.id == entity_id:
                return item
        raise KeyError(f"未找到实体：{entity_id}")

    def children_of(self, parent_id: str | None) -> list[Entity]:
        return [item for item in self.entities if item.parent_id == parent_id]


class EntityQuery(BaseModel):
    expression: str


class TimeGrid(BaseModel):
    start_s: float = 0.0
    stop_s: float = 12.0
    frame_count: int = 30

    @field_validator("frame_count")
    @classmethod
    def enough_frames(cls, value: int) -> int:
        if value < 1:
            raise ValueError("帧数必须大于0")
        return value


class SolverConfig(BaseModel):
    backend: Literal["free_space_scalar"] = "free_space_scalar"
    controller_mode: Literal["centroid_focus", "least_squares_multi_focus", "broadside"] = (
        "least_squares_multi_focus"
    )
    target_query: str = "role:trackable"
    emitter_query: str = "role:emitter_platform"
    receiver_query: str = "component:receiver"
    plane_probe_query: str = "component:probe"
    regularization: float = 1e-3
    normalize_field: bool = True


class MissionDefinition(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    name: str
    mission_type: Literal["StaticFieldSurvey", "DynamicCoverageMission"]
    description: str = ""
    time_grid: TimeGrid = Field(default_factory=TimeGrid)
    solver: SolverConfig = Field(default_factory=SolverConfig)
    metrics: list[str] = Field(
        default_factory=lambda: ["平均接收幅度", "最低接收幅度", "平面热点位置", "时间稳定性"]
    )


class ProjectMetadata(BaseModel):
    project_id: str = Field(default_factory=lambda: str(uuid4()))
    name: str
    description: str = ""
    schema_version: str = "1.0"
    app_version: str = "0.1.0-alpha"


class ResultSummary(BaseModel):
    result_id: str
    mission_id: str
    frame_count: int
    emitter_count: int
    receiver_count: int
    moving_entity_count: int
    mean_receiver_amplitude: float
    minimum_receiver_amplitude: float
    temporal_stability: float
    runtime_ms: float


class ProjectDocument(BaseModel):
    metadata: ProjectMetadata
    scene: SceneDocument
    missions: list[MissionDefinition] = Field(default_factory=list)
    result_summaries: list[ResultSummary] = Field(default_factory=list)

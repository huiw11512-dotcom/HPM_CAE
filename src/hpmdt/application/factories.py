"""场景对象和示例工程工厂。"""
from __future__ import annotations

from hpmdt.domain.models import (
    ArrayComponent,
    BoundaryComponent,
    EmitterComponent,
    Entity,
    GeometryComponent,
    MaterialComponent,
    MissionDefinition,
    MotionComponent,
    ProbeComponent,
    ProjectDocument,
    ProjectMetadata,
    ReceiverComponent,
    RoleComponent,
    SceneDocument,
    SolverConfig,
    TimeGrid,
    Transform,
    Vec3,
    Waypoint,
)


def make_array_platform(name: str, position: tuple[float, float, float]) -> Entity:
    return Entity(
        name=name,
        tags=["阵列平台"],
        transform=Transform(position_m=Vec3(x=position[0], y=position[1], z=position[2])),
        components=[
            GeometryComponent(
                shape="array_panel",
                dimensions_m=Vec3(x=2.2, y=2.2, z=0.15),
                color="#22d3ee",
            ),
            ArrayComponent(nx=4, ny=4, frequency_hz=10e9),
            EmitterComponent(normalized_amplitude=1.0),
            RoleComponent(roles=["emitter_platform", "controller"]),
        ],
    )


def make_moving_aircraft(
    name: str,
    waypoints: list[tuple[float, tuple[float, float, float]]],
    color: str = "#f59e0b",
) -> Entity:
    return Entity(
        name=name,
        tags=["运动对象", "空中对象"],
        transform=Transform(position_m=Vec3(**dict(zip("xyz", waypoints[0][1])))),
        components=[
            GeometryComponent(
                shape="aircraft",
                dimensions_m=Vec3(x=2.4, y=1.6, z=0.6),
                color=color,
            ),
            ReceiverComponent(),
            MotionComponent(
                mode="waypoint",
                waypoints=[
                    Waypoint(time_s=time_s, position_m=Vec3(**dict(zip("xyz", position))))
                    for time_s, position in waypoints
                ],
            ),
            RoleComponent(roles=["trackable", "receiver"]),
        ],
    )


def make_building(
    name: str,
    position: tuple[float, float, float],
    dimensions: tuple[float, float, float],
    color: str = "#475569",
) -> Entity:
    return Entity(
        name=name,
        tags=["建筑物", "环境"],
        transform=Transform(position_m=Vec3(x=position[0], y=position[1], z=position[2])),
        components=[
            GeometryComponent(
                shape="box",
                dimensions_m=Vec3(x=dimensions[0], y=dimensions[1], z=dimensions[2]),
                color=color,
                opacity=0.92,
            ),
            MaterialComponent(
                material_name="建筑反射代理",
                relative_permittivity=4.0,
                loss_tangent=0.02,
                reflection_magnitude=0.65,
            ),
            BoundaryComponent(boundary_kind="reflective"),
            RoleComponent(roles=["environment"]),
        ],
    )


def make_receiver(name: str, position: tuple[float, float, float]) -> Entity:
    return Entity(
        name=name,
        tags=["固定接收设备"],
        transform=Transform(position_m=Vec3(x=position[0], y=position[1], z=position[2])),
        components=[
            GeometryComponent(
                shape="receiver",
                dimensions_m=Vec3(x=0.8, y=0.8, z=1.2),
                color="#a78bfa",
            ),
            ReceiverComponent(),
            RoleComponent(roles=["receiver", "protected_asset"]),
        ],
    )


def make_plane_probe(
    name: str,
    position: tuple[float, float, float],
    dimensions: tuple[float, float],
    resolution: tuple[int, int] = (36, 30),
) -> Entity:
    return Entity(
        name=name,
        tags=["分析探针"],
        transform=Transform(position_m=Vec3(x=position[0], y=position[1], z=position[2])),
        components=[
            GeometryComponent(
                shape="plane",
                dimensions_m=Vec3(x=dimensions[0], y=dimensions[1], z=0.05),
                color="#38bdf8",
                opacity=0.3,
            ),
            ProbeComponent(
                probe_kind="plane",
                dimensions_m=Vec3(x=dimensions[0], y=dimensions[1], z=0.0),
                resolution=[resolution[0], resolution[1], 1],
            ),
            RoleComponent(roles=["observer"]),
        ],
    )


def make_ground() -> Entity:
    return Entity(
        name="地面代理",
        tags=["环境", "地面"],
        transform=Transform(position_m=Vec3(x=0, y=0, z=-0.2)),
        components=[
            GeometryComponent(
                shape="plane",
                dimensions_m=Vec3(x=120, y=100, z=0.1),
                color="#172033",
                opacity=1.0,
            ),
            BoundaryComponent(boundary_kind="ground_proxy"),
            RoleComponent(roles=["environment"]),
        ],
    )


def city_dynamic_project() -> ProjectDocument:
    entities = [
        make_ground(),
        make_array_platform("阵列平台A", (-32, -24, 2.0)),
        make_array_platform("阵列平台B", (32, -24, 2.0)),
        make_building("办公楼A", (-14, 4, 9), (16, 14, 18), "#334155"),
        make_building("办公楼B", (18, 10, 7), (14, 18, 14), "#3f4c63"),
        make_moving_aircraft(
            "运动对象Alpha",
            [(0, (-35, 22, 14)), (6, (-5, 7, 17)), (12, (30, 25, 15))],
            "#f59e0b",
        ),
        make_moving_aircraft(
            "运动对象Bravo",
            [(0, (28, 30, 19)), (5, (9, 1, 14)), (12, (-28, 25, 18))],
            "#fb7185",
        ),
        make_moving_aircraft(
            "运动对象Charlie",
            [(0, (-26, -2, 11)), (7, (5, 30, 13)), (12, (32, -2, 16))],
            "#facc15",
        ),
        make_receiver("固定接收设备", (3, 35, 2.5)),
        make_plane_probe("城市上空场切片", (0, 4, 10), (86, 68), (32, 24)),
    ]
    mission = MissionDefinition(
        name="城市多对象动态覆盖",
        mission_type="DynamicCoverageMission",
        description="两个阵列平台、三个独立运动对象、建筑环境和一个固定接收设备的系统级场景。",
        time_grid=TimeGrid(start_s=0.0, stop_s=12.0, frame_count=30),
        solver=SolverConfig(
            controller_mode="least_squares_multi_focus",
            target_query="role:trackable",
            emitter_query="role:emitter_platform",
            receiver_query="component:receiver",
            plane_probe_query="component:probe",
        ),
    )
    return ProjectDocument(
        metadata=ProjectMetadata(
            name="城市多对象动态覆盖",
            description="Scene First 示例：物理对象先于分析区域，任务通过角色查询自动选择对象。",
        ),
        scene=SceneDocument(entities=entities),
        missions=[mission],
    )


def static_multi_receiver_project() -> ProjectDocument:
    entities = [
        make_ground(),
        make_array_platform("测试阵列", (0, -18, 1.5)),
        make_receiver("接收器1", (-10, 12, 4)),
        make_receiver("接收器2", (0, 18, 6)),
        make_receiver("接收器3", (12, 10, 5)),
        make_plane_probe("静态调查平面", (0, 8, 4), (50, 40), (36, 30)),
    ]
    mission = MissionDefinition(
        name="多接收器静态场调查",
        mission_type="StaticFieldSurvey",
        description="不使用手工目标区，直接对多个物理接收器和空间探针进行调查。",
        time_grid=TimeGrid(start_s=0, stop_s=0, frame_count=1),
        solver=SolverConfig(
            controller_mode="broadside",
            target_query="role:protected_asset",
            receiver_query="component:receiver",
        ),
    )
    return ProjectDocument(
        metadata=ProjectMetadata(name="多接收器静态场调查"),
        scene=SceneDocument(entities=entities),
        missions=[mission],
    )


def empty_project() -> ProjectDocument:
    return ProjectDocument(
        metadata=ProjectMetadata(name="未命名工程", description="空白HPM-DT Studio工程"),
        scene=SceneDocument(entities=[make_ground()]),
        missions=[],
    )


def asset_entity(kind: str, serial: int = 1) -> Entity:
    offset = float(serial * 3)
    if kind == "array_platform":
        return make_array_platform(f"阵列平台{serial}", (-20 + offset, -20, 2))
    if kind == "moving_aircraft":
        return make_moving_aircraft(
            f"运动对象{serial}",
            [(0, (-20 + offset, 5, 12)), (10, (20 - offset, 20, 15))],
        )
    if kind == "building":
        return make_building(f"建筑物{serial}", (offset, 4, 6), (10, 8, 12))
    if kind == "receiver":
        return make_receiver(f"接收设备{serial}", (offset, 18, 3))
    if kind == "plane_probe":
        return make_plane_probe(f"场切片{serial}", (0, 5, 8), (60, 45))
    raise ValueError(f"不支持的对象类型：{kind}")

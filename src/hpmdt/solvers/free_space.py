"""通用多实体自由空间标量场求解器。

该后端是系统级、归一化、快速数值模型，不替代全波电磁求解器。
"""
from __future__ import annotations

from dataclasses import dataclass
from time import perf_counter
from uuid import uuid4

import numpy as np

from hpmdt.domain.models import (
    ArrayComponent,
    EmitterComponent,
    Entity,
    GeometryComponent,
    MissionDefinition,
    ProbeComponent,
    ProjectDocument,
    ReceiverComponent,
    ResultSummary,
)
from hpmdt.domain.query import select
from hpmdt.solvers.math3d import entity_position_at, euler_matrix_xyz, vec3

C0 = 299_792_458.0


@dataclass
class SimulationResult:
    result_id: str
    mission_id: str
    mission_name: str
    times_s: np.ndarray
    entity_positions: dict[str, np.ndarray]
    receiver_amplitudes: dict[str, np.ndarray]
    plane_x_m: np.ndarray
    plane_y_m: np.ndarray
    plane_z_m: np.ndarray
    plane_field: np.ndarray
    plane_probe_id: str | None
    summary: ResultSummary

    def to_jsonable(self) -> dict:
        return {
            "result_id": self.result_id,
            "mission_id": self.mission_id,
            "mission_name": self.mission_name,
            "times_s": self.times_s.tolist(),
            "entity_positions": {key: value.tolist() for key, value in self.entity_positions.items()},
            "receiver_amplitudes": {
                key: value.tolist() for key, value in self.receiver_amplitudes.items()
            },
            "plane": {
                "probe_id": self.plane_probe_id,
                "x_m": self.plane_x_m.tolist(),
                "y_m": self.plane_y_m.tolist(),
                "z_m": self.plane_z_m.tolist(),
                "field": self.plane_field.tolist(),
            },
            "summary": self.summary.model_dump(),
        }


def _array_axis_rotation(axis: str) -> np.ndarray:
    if axis == "+z":
        return np.eye(3)
    if axis == "-z":
        return np.array([[1, 0, 0], [0, -1, 0], [0, 0, -1]], dtype=float)
    mapping = {
        "+x": np.array([[0, 0, 1], [0, 1, 0], [-1, 0, 0]], dtype=float),
        "-x": np.array([[0, 0, -1], [0, 1, 0], [1, 0, 0]], dtype=float),
        "+y": np.array([[1, 0, 0], [0, 0, 1], [0, -1, 0]], dtype=float),
        "-y": np.array([[1, 0, 0], [0, 0, -1], [0, 1, 0]], dtype=float),
    }
    return mapping.get(axis, np.eye(3))


def array_element_positions(entity: Entity, time_s: float) -> tuple[np.ndarray, float]:
    array = entity.component("array")
    if not isinstance(array, ArrayComponent):
        raise ValueError(f"实体{entity.name}没有阵列组件")
    wavelength = C0 / float(array.frequency_hz)
    dx = wavelength / 2.0 if array.dx_m is None else float(array.dx_m)
    dy = wavelength / 2.0 if array.dy_m is None else float(array.dy_m)
    x = (np.arange(array.nx) - (array.nx - 1) / 2.0) * dx
    y = (np.arange(array.ny) - (array.ny - 1) / 2.0) * dy
    xx, yy = np.meshgrid(x, y, indexing="ij")
    local = np.column_stack([xx.ravel(), yy.ravel(), np.zeros(xx.size)])
    rotation = euler_matrix_xyz(entity.transform.rotation_deg) @ _array_axis_rotation(array.boresight_axis)
    world = local @ rotation.T + entity_position_at(entity, time_s)[None, :]
    return world, wavelength


def green_matrix(points_m: np.ndarray, sources_m: np.ndarray, wavelength_m: float) -> np.ndarray:
    points = np.asarray(points_m, dtype=float).reshape(-1, 3)
    sources = np.asarray(sources_m, dtype=float).reshape(-1, 3)
    delta = points[:, None, :] - sources[None, :, :]
    ranges = np.linalg.norm(delta, axis=2)
    ranges = np.maximum(ranges, wavelength_m * 1e-7)
    k = 2.0 * np.pi / wavelength_m
    return np.exp(-1j * k * ranges) / ranges


def _weights(
    element_positions: np.ndarray,
    target_positions: np.ndarray,
    wavelength_m: float,
    mode: str,
    regularization: float,
) -> np.ndarray:
    count = element_positions.shape[0]
    if mode == "broadside" or target_positions.size == 0:
        return np.ones(count, dtype=complex) / np.sqrt(count)
    if mode == "centroid_focus":
        centroid = np.mean(target_positions, axis=0, keepdims=True)
        row = green_matrix(centroid, element_positions, wavelength_m).reshape(-1)
        result = np.exp(-1j * np.angle(row))
        return result / np.linalg.norm(result)
    h = green_matrix(target_positions, element_positions, wavelength_m)
    desired = np.ones(h.shape[0], dtype=complex)
    gram = h @ h.conj().T + float(regularization) * np.eye(h.shape[0])
    try:
        result = h.conj().T @ np.linalg.solve(gram, desired)
    except np.linalg.LinAlgError:
        result = h.conj().T @ np.linalg.pinv(gram) @ desired
    norm = np.linalg.norm(result)
    if norm <= 1e-12:
        return np.ones(count, dtype=complex) / np.sqrt(count)
    return result / norm


def _plane_grid(probe_entity: Entity) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    probe = probe_entity.component("probe")
    if not isinstance(probe, ProbeComponent) or probe.probe_kind != "plane":
        raise ValueError("仅支持平面探针")
    nx, ny, _ = probe.resolution
    width = float(probe.dimensions_m.x)
    height = float(probe.dimensions_m.y)
    local_x = np.linspace(-width / 2.0, width / 2.0, nx)
    local_y = np.linspace(-height / 2.0, height / 2.0, ny)
    xx, yy = np.meshgrid(local_x, local_y, indexing="xy")
    local = np.column_stack([xx.ravel(), yy.ravel(), np.zeros(xx.size)])
    rotation = euler_matrix_xyz(probe_entity.transform.rotation_deg)
    world = local @ rotation.T + vec3(probe_entity.transform.position_m)[None, :]
    return world, world[:, 0].reshape(ny, nx), world[:, 1].reshape(ny, nx), world[:, 2].reshape(ny, nx)


def run_free_space(project: ProjectDocument, mission: MissionDefinition) -> SimulationResult:
    started = perf_counter()
    entities = [item for item in project.scene.entities if item.enabled]
    emitters = [
        item
        for item in select(entities, mission.solver.emitter_query)
        if isinstance(item.component("array"), ArrayComponent)
        and isinstance(item.component("emitter"), EmitterComponent)
        and item.component("emitter").enabled
    ]
    receivers = [
        item
        for item in select(entities, mission.solver.receiver_query)
        if isinstance(item.component("receiver"), ReceiverComponent)
        and item.component("receiver").enabled
    ]
    targets = select(entities, mission.solver.target_query)
    plane_candidates = [
        item
        for item in select(entities, mission.solver.plane_probe_query)
        if isinstance(item.component("probe"), ProbeComponent)
        and item.component("probe").probe_kind == "plane"
        and item.component("probe").enabled
    ]
    if not emitters:
        raise ValueError("任务至少需要一个启用的阵列发射实体")
    if mission.mission_type == "StaticFieldSurvey":
        times = np.asarray([mission.time_grid.start_s], dtype=float)
    else:
        times = np.linspace(
            mission.time_grid.start_s,
            mission.time_grid.stop_s,
            mission.time_grid.frame_count,
        )

    plane_probe = plane_candidates[0] if plane_candidates else None
    if plane_probe is not None:
        plane_points, plane_x, plane_y, plane_z = _plane_grid(plane_probe)
        plane_shape = plane_x.shape
    else:
        plane_points = np.empty((0, 3), dtype=float)
        plane_x = plane_y = plane_z = np.empty((0, 0), dtype=float)
        plane_shape = (0, 0)

    entity_positions = {
        item.id: np.vstack([entity_position_at(item, float(time)) for time in times]) for item in entities
    }
    receiver_raw = {item.id: np.zeros(times.size, dtype=float) for item in receivers}
    plane_raw = np.zeros((times.size, *plane_shape), dtype=float)

    # 静态阵列的空间传播矩阵在所有时间帧内不变，预计算可显著缩短交互式预览时间。
    emitter_cache: dict[str, tuple[np.ndarray, float, np.ndarray | None]] = {}
    for emitter_entity in emitters:
        motion = emitter_entity.component("motion")
        is_static = motion is None or motion.mode == "static"
        if is_static:
            positions, wavelength = array_element_positions(emitter_entity, float(times[0]))
            plane_matrix = (
                green_matrix(plane_points, positions, wavelength) if plane_points.size else None
            )
            emitter_cache[emitter_entity.id] = (positions, wavelength, plane_matrix)

    for frame_index, time_s in enumerate(times):
        target_positions = (
            np.vstack([entity_position_at(item, float(time_s)) for item in targets])
            if targets
            else np.empty((0, 3), dtype=float)
        )
        receiver_positions = (
            np.vstack([entity_position_at(item, float(time_s)) for item in receivers])
            if receivers
            else np.empty((0, 3), dtype=float)
        )
        plane_field = np.zeros(plane_points.shape[0], dtype=complex)
        receiver_field = np.zeros(len(receivers), dtype=complex)

        for emitter_entity in emitters:
            emitter = emitter_entity.component("emitter")
            cached = emitter_cache.get(emitter_entity.id)
            if cached is None:
                element_positions, wavelength = array_element_positions(emitter_entity, float(time_s))
                plane_matrix = (
                    green_matrix(plane_points, element_positions, wavelength)
                    if plane_points.size
                    else None
                )
            else:
                element_positions, wavelength, plane_matrix = cached
            weights = _weights(
                element_positions,
                target_positions,
                wavelength,
                mission.solver.controller_mode,
                mission.solver.regularization,
            )
            excitation = (
                weights
                * float(emitter.normalized_amplitude)
                * np.exp(1j * np.deg2rad(float(emitter.phase_deg)))
            )
            if plane_points.size and plane_matrix is not None:
                plane_field += plane_matrix @ excitation
            if receiver_positions.size:
                receiver_field += green_matrix(receiver_positions, element_positions, wavelength) @ excitation

        if plane_points.size:
            plane_raw[frame_index] = np.abs(plane_field).reshape(plane_shape)
        for receiver_index, receiver in enumerate(receivers):
            receiver_raw[receiver.id][frame_index] = float(np.abs(receiver_field[receiver_index]))

    scales: list[float] = []
    if plane_raw.size:
        scales.append(float(np.max(plane_raw)))
    for values in receiver_raw.values():
        if values.size:
            scales.append(float(np.max(values)))
    reference = max(scales + [1e-12]) if mission.solver.normalize_field else 1.0
    plane_field = plane_raw / reference
    receiver_amplitudes = {key: values / reference for key, values in receiver_raw.items()}

    all_receiver_values = (
        np.concatenate(list(receiver_amplitudes.values()))
        if receiver_amplitudes
        else np.asarray([0.0])
    )
    means_by_frame = (
        np.mean(np.vstack(list(receiver_amplitudes.values())), axis=0)
        if receiver_amplitudes
        else np.asarray([0.0])
    )
    mean_amplitude = float(np.mean(all_receiver_values))
    min_amplitude = float(np.min(all_receiver_values))
    temporal_stability = float(1.0 / (1.0 + np.std(means_by_frame)))
    moving_count = sum(
        1
        for item in entities
        if item.has_component("motion") and item.component("motion").mode != "static"
    )
    result_id = str(uuid4())
    summary = ResultSummary(
        result_id=result_id,
        mission_id=mission.id,
        frame_count=int(times.size),
        emitter_count=len(emitters),
        receiver_count=len(receivers),
        moving_entity_count=moving_count,
        mean_receiver_amplitude=mean_amplitude,
        minimum_receiver_amplitude=min_amplitude,
        temporal_stability=temporal_stability,
        runtime_ms=(perf_counter() - started) * 1000.0,
    )
    return SimulationResult(
        result_id=result_id,
        mission_id=mission.id,
        mission_name=mission.name,
        times_s=times,
        entity_positions=entity_positions,
        receiver_amplitudes=receiver_amplitudes,
        plane_x_m=plane_x,
        plane_y_m=plane_y,
        plane_z_m=plane_z,
        plane_field=plane_field,
        plane_probe_id=plane_probe.id if plane_probe else None,
        summary=summary,
    )

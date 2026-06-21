"""三维变换与运动插值工具。"""
from __future__ import annotations

import math
import numpy as np

from hpmdt.domain.models import Entity, MotionComponent, Vec3


def vec3(value: Vec3) -> np.ndarray:
    return np.asarray(value.as_list(), dtype=float)


def euler_matrix_xyz(rotation_deg: Vec3) -> np.ndarray:
    rx, ry, rz = np.deg2rad(vec3(rotation_deg))
    cx, sx = math.cos(rx), math.sin(rx)
    cy, sy = math.cos(ry), math.sin(ry)
    cz, sz = math.cos(rz), math.sin(rz)
    mx = np.array([[1, 0, 0], [0, cx, -sx], [0, sx, cx]], dtype=float)
    my = np.array([[cy, 0, sy], [0, 1, 0], [-sy, 0, cy]], dtype=float)
    mz = np.array([[cz, -sz, 0], [sz, cz, 0], [0, 0, 1]], dtype=float)
    return mz @ my @ mx


def entity_position_at(entity: Entity, time_s: float) -> np.ndarray:
    base = vec3(entity.transform.position_m)
    motion = entity.component("motion")
    if not isinstance(motion, MotionComponent) or motion.mode == "static":
        return base
    if motion.mode == "linear":
        return base + vec3(motion.velocity_mps) * float(time_s)
    if motion.mode == "circular":
        period = max(float(motion.circle_period_s), 1e-9)
        angle = 2.0 * np.pi * float(time_s) / period
        center = vec3(motion.circle_center_m)
        return center + np.array(
            [motion.circle_radius_m * np.cos(angle), motion.circle_radius_m * np.sin(angle), base[2]],
            dtype=float,
        )
    if motion.mode == "waypoint" and motion.waypoints:
        points = sorted(motion.waypoints, key=lambda item: item.time_s)
        start = points[0].time_s
        stop = points[-1].time_s
        current = float(time_s)
        if motion.loop and stop > start:
            current = start + (current - start) % (stop - start)
        if current <= start:
            return vec3(points[0].position_m)
        if current >= stop:
            return vec3(points[-1].position_m)
        for left, right in zip(points[:-1], points[1:]):
            if left.time_s <= current <= right.time_s:
                ratio = (current - left.time_s) / max(right.time_s - left.time_s, 1e-12)
                return (1.0 - ratio) * vec3(left.position_m) + ratio * vec3(right.position_m)
    return base

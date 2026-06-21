"""SI unit helpers used by the Studio domain model."""

from __future__ import annotations

from typing import Literal

Vec2 = tuple[float, float]
Vec3 = tuple[float, float, float]
Quaternion = tuple[float, float, float, float]

LengthUnit = Literal["mm", "cm", "m", "km"]
AngleUnit = Literal["deg", "rad"]
FrequencyUnit = Literal["Hz", "kHz", "MHz", "GHz"]
TimeUnit = Literal["s", "ms", "us", "ns"]

_LENGTH_TO_M = {"mm": 1e-3, "cm": 1e-2, "m": 1.0, "km": 1e3}
_ANGLE_TO_RAD = {"deg": 0.017453292519943295, "rad": 1.0}
_FREQUENCY_TO_HZ = {"Hz": 1.0, "kHz": 1e3, "MHz": 1e6, "GHz": 1e9}
_TIME_TO_S = {"s": 1.0, "ms": 1e-3, "us": 1e-6, "ns": 1e-9}


def length_to_m(value: float, unit: LengthUnit = "m") -> float:
    return value * _LENGTH_TO_M[unit]


def length_from_m(value_m: float, unit: LengthUnit = "m") -> float:
    return value_m / _LENGTH_TO_M[unit]


def angle_to_rad(value: float, unit: AngleUnit = "rad") -> float:
    return value * _ANGLE_TO_RAD[unit]


def angle_from_rad(value_rad: float, unit: AngleUnit = "rad") -> float:
    return value_rad / _ANGLE_TO_RAD[unit]


def frequency_to_hz(value: float, unit: FrequencyUnit = "Hz") -> float:
    return value * _FREQUENCY_TO_HZ[unit]


def frequency_from_hz(value_hz: float, unit: FrequencyUnit = "Hz") -> float:
    return value_hz / _FREQUENCY_TO_HZ[unit]


def time_to_s(value: float, unit: TimeUnit = "s") -> float:
    return value * _TIME_TO_S[unit]


def time_from_s(value_s: float, unit: TimeUnit = "s") -> float:
    return value_s / _TIME_TO_S[unit]


def vec3(value: tuple[float, float, float] | list[float]) -> Vec3:
    if len(value) != 3:
        raise ValueError("Expected a 3D vector")
    return (float(value[0]), float(value[1]), float(value[2]))


def quaternion(value: tuple[float, float, float, float] | list[float]) -> Quaternion:
    if len(value) != 4:
        raise ValueError("Expected a quaternion")
    return (float(value[0]), float(value[1]), float(value[2]), float(value[3]))

"""Dynamic normalized region control for a moving target zone.

The module works exclusively with dimensionless field setpoints and coordinates
expressed in wavelengths.  It provides timestamp-aware planar tracking,
covariance sigma points, and a direct robust region least-squares controller.
It does not contain source-power, range, susceptibility, or damage parameters.
"""
from __future__ import annotations

from dataclasses import dataclass
import time
from typing import Sequence

import numpy as np

from hpm_platform.field_control.region_shaping import (
    project_excitation,
    scalar_green_matrix,
    scale_to_target_amplitude,
    unit_rms_point_focus_weights,
)
from hpm_platform.physics.array_geometry import RectangularArray


@dataclass(frozen=True)
class PlanarPrediction:
    """Predicted center state on the normalized control plane."""

    mean_lambda: np.ndarray
    covariance_lambda2: np.ndarray
    velocity_lambda_per_frame: np.ndarray
    timestamp: float


@dataclass(frozen=True)
class PlanarUpdate:
    """Diagnostics for one delayed measurement update."""

    innovation_lambda: np.ndarray
    innovation_mahalanobis_sq: float
    accepted: bool


@dataclass(frozen=True)
class DynamicDesignResult:
    """Result of one online robust region least-squares design."""

    weights: np.ndarray
    runtime_ms: float
    condition_number: float
    n_center_scenarios: int
    n_hardware_scenarios: int


def _symmetrize(matrix: np.ndarray) -> np.ndarray:
    value = np.asarray(matrix, dtype=float)
    return 0.5 * (value + value.T)


def ensure_spd(matrix: np.ndarray, floor: float = 1e-8) -> np.ndarray:
    """Return a symmetric positive-definite matrix with an eigenvalue floor."""
    value = _symmetrize(matrix)
    eigenvalues, eigenvectors = np.linalg.eigh(value)
    eigenvalues = np.maximum(eigenvalues, float(floor))
    return (eigenvectors * eigenvalues) @ eigenvectors.T


class PlanarKalmanTracker:
    """Timestamp-aware constant-velocity tracker in wavelength coordinates.

    The state is ``[x, y, vx, vy]``.  The internal state is anchored at the
    most recent measurement timestamp, allowing a delayed packet to be updated
    at acquisition time and then predicted to the current actuation time.
    """

    def __init__(
        self,
        initial_center_lambda: Sequence[float],
        *,
        initial_position_std_lambda: float = 0.45,
        initial_velocity_std_lambda_per_frame: float = 0.12,
        process_acceleration_std_lambda_per_frame2: float = 0.025,
        initial_time: float = 0.0,
    ) -> None:
        center = np.asarray(initial_center_lambda, dtype=float).reshape(2)
        if initial_position_std_lambda <= 0 or initial_velocity_std_lambda_per_frame <= 0:
            raise ValueError("initial standard deviations must be positive")
        if process_acceleration_std_lambda_per_frame2 <= 0:
            raise ValueError("process acceleration standard deviation must be positive")
        self._state = np.array([center[0], center[1], 0.0, 0.0], dtype=float)
        self._covariance = np.diag(
            [
                float(initial_position_std_lambda) ** 2,
                float(initial_position_std_lambda) ** 2,
                float(initial_velocity_std_lambda_per_frame) ** 2,
                float(initial_velocity_std_lambda_per_frame) ** 2,
            ]
        )
        self._last_time = float(initial_time)
        self._acceleration_variance = float(process_acceleration_std_lambda_per_frame2) ** 2

    @property
    def last_measurement_time(self) -> float:
        return float(self._last_time)

    @staticmethod
    def transition(dt: float) -> np.ndarray:
        dt = float(dt)
        return np.array(
            [
                [1.0, 0.0, dt, 0.0],
                [0.0, 1.0, 0.0, dt],
                [0.0, 0.0, 1.0, 0.0],
                [0.0, 0.0, 0.0, 1.0],
            ],
            dtype=float,
        )

    def process_covariance(self, dt: float) -> np.ndarray:
        dt = max(float(dt), 0.0)
        block = self._acceleration_variance * np.array(
            [[dt**4 / 4.0, dt**3 / 2.0], [dt**3 / 2.0, dt**2]],
            dtype=float,
        )
        output = np.zeros((4, 4), dtype=float)
        output[np.ix_([0, 2], [0, 2])] = block
        output[np.ix_([1, 3], [1, 3])] = block
        return output

    def _predict_arrays(self, timestamp: float) -> tuple[np.ndarray, np.ndarray]:
        dt = float(timestamp) - self._last_time
        if dt < -1e-9:
            raise ValueError("measurement timestamps must be nondecreasing")
        dt = max(dt, 0.0)
        f = self.transition(dt)
        state = f @ self._state
        covariance = ensure_spd(f @ self._covariance @ f.T + self.process_covariance(dt))
        return state, covariance

    def predict(self, timestamp: float) -> PlanarPrediction:
        state, covariance = self._predict_arrays(timestamp)
        return PlanarPrediction(
            mean_lambda=state[:2].copy(),
            covariance_lambda2=ensure_spd(covariance[:2, :2]),
            velocity_lambda_per_frame=state[2:].copy(),
            timestamp=float(timestamp),
        )

    def update(
        self,
        measurement_lambda: Sequence[float],
        measurement_covariance_lambda2: np.ndarray,
        *,
        measurement_time: float,
        gate_mahalanobis_sq: float = 25.0,
    ) -> PlanarUpdate:
        if gate_mahalanobis_sq <= 0:
            raise ValueError("gate_mahalanobis_sq must be positive")
        measurement = np.asarray(measurement_lambda, dtype=float).reshape(2)
        r = ensure_spd(np.asarray(measurement_covariance_lambda2, dtype=float), floor=1e-7)
        predicted_state, predicted_covariance = self._predict_arrays(float(measurement_time))
        h = np.array([[1.0, 0.0, 0.0, 0.0], [0.0, 1.0, 0.0, 0.0]])
        innovation = measurement - h @ predicted_state
        s = ensure_spd(h @ predicted_covariance @ h.T + r)
        distance = float(innovation @ np.linalg.solve(s, innovation))
        accepted = bool(np.isfinite(distance) and distance <= float(gate_mahalanobis_sq))
        if accepted:
            gain = predicted_covariance @ h.T @ np.linalg.inv(s)
            identity = np.eye(4)
            self._state = predicted_state + gain @ innovation
            kh = gain @ h
            self._covariance = ensure_spd(
                (identity - kh) @ predicted_covariance @ (identity - kh).T + gain @ r @ gain.T
            )
        else:
            self._state = predicted_state
            self._covariance = predicted_covariance
        self._last_time = float(measurement_time)
        return PlanarUpdate(
            innovation_lambda=innovation,
            innovation_mahalanobis_sq=distance,
            accepted=accepted,
        )


def covariance_sigma_centers(
    mean_lambda: Sequence[float],
    covariance_lambda2: np.ndarray,
    *,
    sigma_scale: float = 1.8,
    maximum_offset_lambda: float = 1.0,
    include_diagonals: bool = False,
) -> np.ndarray:
    """Return deterministic center scenarios from a 2-D covariance ellipse."""
    if sigma_scale < 0 or maximum_offset_lambda <= 0:
        raise ValueError("sigma_scale must be non-negative and maximum offset positive")
    mean = np.asarray(mean_lambda, dtype=float).reshape(2)
    covariance = ensure_spd(np.asarray(covariance_lambda2, dtype=float))
    values, vectors = np.linalg.eigh(covariance)
    order = np.argsort(values)[::-1]
    values = values[order]
    vectors = vectors[:, order]
    offsets: list[np.ndarray] = [np.zeros(2, dtype=float)]
    principal: list[np.ndarray] = []
    for index in range(2):
        magnitude = min(float(sigma_scale) * float(np.sqrt(values[index])), float(maximum_offset_lambda))
        vector = magnitude * vectors[:, index]
        principal.append(vector)
        offsets.extend([vector, -vector])
    if include_diagonals:
        diagonal_scale = 1.0 / np.sqrt(2.0)
        offsets.extend(
            [
                diagonal_scale * (principal[0] + principal[1]),
                diagonal_scale * (principal[0] - principal[1]),
                diagonal_scale * (-principal[0] + principal[1]),
                diagonal_scale * (-principal[0] - principal[1]),
            ]
        )
    return mean[None, :] + np.asarray(offsets)


def ellipse_sample_points_lambda(
    center_lambda: Sequence[float],
    semi_axes_lambda: Sequence[float],
    *,
    rotation_deg: float,
    z_lambda: float,
    radial_samples: int = 5,
    angular_samples: int = 12,
) -> np.ndarray:
    """Return deterministic interior samples of a rotated ellipse."""
    if radial_samples < 2 or angular_samples < 4:
        raise ValueError("radial_samples >= 2 and angular_samples >= 4 are required")
    center = np.asarray(center_lambda, dtype=float).reshape(2)
    axes = np.asarray(semi_axes_lambda, dtype=float).reshape(2)
    if np.any(axes <= 0):
        raise ValueError("semi axes must be positive")
    angle = np.deg2rad(float(rotation_deg))
    rotation = np.array([[np.cos(angle), -np.sin(angle)], [np.sin(angle), np.cos(angle)]])
    points: list[np.ndarray] = [center.copy()]
    radii = np.sqrt(np.linspace(0.08, 1.0, int(radial_samples) - 1))
    for ring_index, radius in enumerate(radii):
        offset = (ring_index % 2) * np.pi / int(angular_samples)
        angles = np.linspace(0.0, 2.0 * np.pi, int(angular_samples), endpoint=False) + offset
        unit = np.column_stack((np.cos(angles), np.sin(angles)))
        local = radius * unit * axes[None, :]
        points.extend(center[None, :] + local @ rotation.T)
    xy = np.asarray(points, dtype=float)
    return np.column_stack((xy, np.full(xy.shape[0], float(z_lambda))))


def sample_outside_points_lambda(
    x_limits_lambda: Sequence[float],
    y_limits_lambda: Sequence[float],
    *,
    z_lambda: float,
    center_lambda: Sequence[float],
    semi_axes_lambda: Sequence[float],
    rotation_deg: float,
    guard_scale: float,
    n_points: int,
    seed: int,
) -> np.ndarray:
    """Sample points outside a guarded ellipse on the normalized plane."""
    if n_points < 1 or guard_scale <= 1:
        raise ValueError("n_points must be positive and guard_scale must exceed one")
    rng = np.random.default_rng(int(seed))
    center = np.asarray(center_lambda, dtype=float).reshape(2)
    axes = np.asarray(semi_axes_lambda, dtype=float).reshape(2)
    angle = np.deg2rad(float(rotation_deg))
    c, s = np.cos(angle), np.sin(angle)
    selected: list[np.ndarray] = []
    batch = max(4 * int(n_points), 256)
    while sum(item.shape[0] for item in selected) < int(n_points):
        x = rng.uniform(float(x_limits_lambda[0]), float(x_limits_lambda[1]), batch)
        y = rng.uniform(float(y_limits_lambda[0]), float(y_limits_lambda[1]), batch)
        dx = x - center[0]
        dy = y - center[1]
        xr = c * dx + s * dy
        yr = -s * dx + c * dy
        radius = np.sqrt((xr / axes[0]) ** 2 + (yr / axes[1]) ** 2)
        keep = radius >= float(guard_scale)
        selected.append(np.column_stack((x[keep], y[keep])))
    xy = np.vstack(selected)[: int(n_points)]
    return np.column_stack((xy, np.full(int(n_points), float(z_lambda))))


def robust_dynamic_region_ls(
    array: RectangularArray,
    center_scenarios_lambda: np.ndarray,
    *,
    semi_axes_lambda: Sequence[float],
    rotation_deg: float,
    z_lambda: float,
    outside_points_lambda: np.ndarray,
    reference_scale: float,
    target_amplitude: float,
    outside_penalty: float,
    ridge: float,
    rms_limit: float,
    peak_limit: float,
    hardware_gain_scenarios: Sequence[np.ndarray] | None = None,
    radial_samples: int = 5,
    angular_samples: int = 12,
    alternating_iterations: int = 3,
) -> DynamicDesignResult:
    """Solve a scenario-averaged complex region least-squares problem.

    The desired phase for each center scenario is inherited from a point-focus
    template, while the magnitude setpoint is shared.  Target and outside
    Gram matrices are normalized by their sample counts so the trade-off is
    stable when visualization grids change.
    """
    start = time.perf_counter()
    centers = np.asarray(center_scenarios_lambda, dtype=float).reshape(-1, 2)
    if centers.shape[0] < 1:
        raise ValueError("at least one center scenario is required")
    if target_amplitude <= 0 or outside_penalty < 0 or ridge <= 0:
        raise ValueError("invalid robust region-LS parameter")
    if alternating_iterations < 1:
        raise ValueError("alternating_iterations must be positive")
    outside_lambda = np.asarray(outside_points_lambda, dtype=float).reshape(-1, 3)
    if outside_lambda.shape[0] < 1:
        raise ValueError("outside point set cannot be empty")
    if hardware_gain_scenarios is None:
        gains_list = [np.ones(array.n_elements, dtype=complex)]
    else:
        gains_list = [np.asarray(item, dtype=complex).reshape(-1) for item in hardware_gain_scenarios]
        if not gains_list or any(item.size != array.n_elements for item in gains_list):
            raise ValueError("hardware gain scenario dimensions do not match the array")

    wavelength = array.wavelength_m
    outside_m = outside_lambda * wavelength
    hessian = np.zeros((array.n_elements, array.n_elements), dtype=complex)
    rhs = np.zeros(array.n_elements, dtype=complex)
    nominal_target_matrices: list[np.ndarray] = []
    target_terms: list[np.ndarray] = []
    n_target_terms = centers.shape[0] * len(gains_list)

    for center_index, center in enumerate(centers):
        target_lambda = ellipse_sample_points_lambda(
            center,
            semi_axes_lambda,
            rotation_deg=rotation_deg,
            z_lambda=z_lambda,
            radial_samples=radial_samples,
            angular_samples=angular_samples,
        )
        target_m = target_lambda * wavelength
        focus_m = wavelength * np.array([center[0], center[1], float(z_lambda)])
        template = unit_rms_point_focus_weights(array, focus_m, rms_amplitude=1.0)
        for gain_index, gains in enumerate(gains_list):
            matrix = scalar_green_matrix(
                array,
                target_m,
                reference_scale=reference_scale,
                element_gains=gains,
            )
            desired = float(target_amplitude) * np.exp(1j * np.angle(matrix @ template))
            hessian += (matrix.conj().T @ matrix) / (matrix.shape[0] * n_target_terms)
            rhs += (matrix.conj().T @ desired) / (matrix.shape[0] * n_target_terms)
            target_terms.append(matrix)
            if center_index == 0 and gain_index == 0:
                nominal_target_matrices.append(matrix)

    outside_gram = np.zeros_like(hessian)
    for gains in gains_list:
        matrix = scalar_green_matrix(
            array,
            outside_m,
            reference_scale=reference_scale,
            element_gains=gains,
        )
        outside_gram += (matrix.conj().T @ matrix) / (matrix.shape[0] * len(gains_list))
    hessian += float(outside_penalty) * outside_gram
    hessian += float(ridge) * np.eye(array.n_elements)
    condition_number = float(np.linalg.cond(hessian))
    weights = np.linalg.solve(hessian, rhs)
    weights = project_excitation(weights, rms_limit=rms_limit, peak_limit=peak_limit)
    for _ in range(1, int(alternating_iterations)):
        rhs_iter = np.zeros(array.n_elements, dtype=complex)
        for matrix in target_terms:
            phase = np.angle(matrix @ weights)
            desired = float(target_amplitude) * np.exp(1j * phase)
            rhs_iter += (matrix.conj().T @ desired) / (matrix.shape[0] * n_target_terms)
        weights = np.linalg.solve(hessian, rhs_iter)
        weights = project_excitation(weights, rms_limit=rms_limit, peak_limit=peak_limit)
    scale_matrix = np.vstack(nominal_target_matrices)
    weights = scale_to_target_amplitude(
        weights,
        scale_matrix,
        target_amplitude=target_amplitude,
        rms_limit=rms_limit,
        peak_limit=peak_limit,
    )
    return DynamicDesignResult(
        weights=weights,
        runtime_ms=1000.0 * (time.perf_counter() - start),
        condition_number=condition_number,
        n_center_scenarios=int(centers.shape[0]),
        n_hardware_scenarios=int(len(gains_list)),
    )


def update_feedback_scale(
    previous_scale: float,
    measured_target_mean: float,
    *,
    target_amplitude: float,
    proportional_gain: float = 0.35,
    smoothing: float = 0.55,
    minimum_scale: float = 0.78,
    maximum_scale: float = 1.28,
) -> float:
    """Update a bounded multiplicative command scale from normalized feedback."""
    if target_amplitude <= 0 or measured_target_mean <= 0:
        return float(np.clip(previous_scale, minimum_scale, maximum_scale))
    ratio_error = float(target_amplitude) / float(measured_target_mean) - 1.0
    proposed = float(previous_scale) * (1.0 + float(proportional_gain) * ratio_error)
    filtered = float(smoothing) * float(previous_scale) + (1.0 - float(smoothing)) * proposed
    return float(np.clip(filtered, float(minimum_scale), float(maximum_scale)))

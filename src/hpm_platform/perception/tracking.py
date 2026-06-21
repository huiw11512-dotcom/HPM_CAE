"""Timestamp-aware multi-target angular tracking.

The tracker works in the local ``(theta, phi)`` chart and is intended for
moderate angular excursions that do not cross the azimuth wrap boundary.  It
propagates the full 2-D measurement covariance delivered by the perception
stage into a constant-velocity Kalman model.  This makes update latency and
uncertainty visible to downstream receive-protection algorithms.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

import numpy as np
from scipy.optimize import linear_sum_assignment


@dataclass(frozen=True)
class TrackPrediction:
    """Predicted angular state for one track."""

    mean_deg: tuple[float, float]
    covariance_deg2: np.ndarray
    velocity_deg_per_frame: tuple[float, float]
    state_covariance: np.ndarray


@dataclass(frozen=True)
class TrackerUpdateResult:
    """Diagnostics from one timestamped multi-target update."""

    assignment: tuple[int, ...]
    innovations_deg: np.ndarray
    accepted: tuple[bool, ...]
    innovation_mahalanobis: np.ndarray


def _symmetrize(matrix: np.ndarray) -> np.ndarray:
    value = np.asarray(matrix, dtype=float)
    return 0.5 * (value + value.T)


def _ensure_spd(matrix: np.ndarray, floor: float = 1e-8) -> np.ndarray:
    value = _symmetrize(matrix)
    eigenvalues, eigenvectors = np.linalg.eigh(value)
    eigenvalues = np.maximum(eigenvalues, float(floor))
    return (eigenvectors * eigenvalues) @ eigenvectors.T


class MultiTargetKalmanTracker:
    """Constant-velocity Kalman tracker for a fixed number of angular tracks.

    Measurements may arrive after a fixed processing delay.  The internal
    state remains anchored at the most recent *measurement timestamp*, so an
    arriving packet can be assimilated at its acquisition time and then
    predicted to the current protection frame without pretending it is fresh.
    """

    def __init__(
        self,
        initial_directions_deg: Sequence[tuple[float, float]],
        *,
        initial_position_std_deg: float = 4.0,
        initial_velocity_std_deg_per_frame: float = 1.0,
        process_acceleration_std_deg_per_frame2: float = 0.18,
        initial_time: float = 0.0,
    ) -> None:
        centers = np.asarray(initial_directions_deg, dtype=float)
        if centers.ndim != 2 or centers.shape[1] != 2 or centers.shape[0] < 1:
            raise ValueError("initial_directions_deg must have shape (K, 2)")
        if initial_position_std_deg <= 0 or initial_velocity_std_deg_per_frame <= 0:
            raise ValueError("initial standard deviations must be positive")
        if process_acceleration_std_deg_per_frame2 <= 0:
            raise ValueError("process acceleration standard deviation must be positive")

        self._states = np.zeros((centers.shape[0], 4), dtype=float)
        self._states[:, :2] = centers
        position_variance = float(initial_position_std_deg) ** 2
        velocity_variance = float(initial_velocity_std_deg_per_frame) ** 2
        base_covariance = np.diag(
            [position_variance, position_variance, velocity_variance, velocity_variance]
        )
        self._covariances = np.repeat(base_covariance[None, :, :], centers.shape[0], axis=0)
        self._last_time = float(initial_time)
        self._acceleration_variance = float(process_acceleration_std_deg_per_frame2) ** 2

    @property
    def n_tracks(self) -> int:
        return int(self._states.shape[0])

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
        q = self._acceleration_variance
        block = np.array(
            [
                [dt**4 / 4.0, dt**3 / 2.0],
                [dt**3 / 2.0, dt**2],
            ],
            dtype=float,
        ) * q
        # State order is theta, phi, theta_rate, phi_rate.
        result = np.zeros((4, 4), dtype=float)
        result[np.ix_([0, 2], [0, 2])] = block
        result[np.ix_([1, 3], [1, 3])] = block
        return result

    def _predict_arrays(self, timestamp: float) -> tuple[np.ndarray, np.ndarray]:
        dt = float(timestamp) - self._last_time
        if dt < -1e-9:
            raise ValueError("measurement timestamps must be nondecreasing")
        dt = max(dt, 0.0)
        f = self.transition(dt)
        q = self.process_covariance(dt)
        states = (f @ self._states.T).T
        covariances = np.empty_like(self._covariances)
        for index, covariance in enumerate(self._covariances):
            covariances[index] = _ensure_spd(f @ covariance @ f.T + q)
        return states, covariances

    def predict(self, timestamp: float) -> tuple[TrackPrediction, ...]:
        states, covariances = self._predict_arrays(timestamp)
        output: list[TrackPrediction] = []
        for state, covariance in zip(states, covariances):
            output.append(
                TrackPrediction(
                    mean_deg=(float(np.clip(state[0], 0.1, 89.9)), float(state[1])),
                    covariance_deg2=_ensure_spd(covariance[:2, :2]),
                    velocity_deg_per_frame=(float(state[2]), float(state[3])),
                    state_covariance=_ensure_spd(covariance),
                )
            )
        return tuple(output)

    def update(
        self,
        measurements_deg: Sequence[tuple[float, float]],
        measurement_covariances_deg2: Sequence[np.ndarray],
        *,
        measurement_time: float,
        gate_mahalanobis_sq: float = 36.0,
    ) -> TrackerUpdateResult:
        measurements = np.asarray(measurements_deg, dtype=float)
        if measurements.shape != (self.n_tracks, 2):
            raise ValueError("measurements_deg must have shape (n_tracks, 2)")
        if len(measurement_covariances_deg2) != self.n_tracks:
            raise ValueError("one measurement covariance is required per track")
        if gate_mahalanobis_sq <= 0:
            raise ValueError("gate_mahalanobis_sq must be positive")

        predicted_states, predicted_covariances = self._predict_arrays(float(measurement_time))
        h = np.array([[1.0, 0.0, 0.0, 0.0], [0.0, 1.0, 0.0, 0.0]])
        measurement_covariances = [
            _ensure_spd(np.asarray(value, dtype=float), floor=1e-6)
            for value in measurement_covariances_deg2
        ]

        cost = np.empty((self.n_tracks, self.n_tracks), dtype=float)
        for track_index in range(self.n_tracks):
            predicted_position = h @ predicted_states[track_index]
            predicted_position_covariance = h @ predicted_covariances[track_index] @ h.T
            for measurement_index in range(self.n_tracks):
                residual = measurements[measurement_index] - predicted_position
                innovation_covariance = _ensure_spd(
                    predicted_position_covariance + measurement_covariances[measurement_index]
                )
                cost[track_index, measurement_index] = float(
                    residual @ np.linalg.solve(innovation_covariance, residual)
                )

        rows, columns = linear_sum_assignment(cost)
        assignment = np.full(self.n_tracks, -1, dtype=int)
        assignment[rows] = columns
        innovations = np.zeros((self.n_tracks, 2), dtype=float)
        mahalanobis = np.full(self.n_tracks, np.inf, dtype=float)
        accepted: list[bool] = []

        updated_states = predicted_states.copy()
        updated_covariances = predicted_covariances.copy()
        identity = np.eye(4)
        for track_index, measurement_index in enumerate(assignment):
            residual = measurements[measurement_index] - h @ predicted_states[track_index]
            r = measurement_covariances[measurement_index]
            s = _ensure_spd(h @ predicted_covariances[track_index] @ h.T + r)
            distance = float(residual @ np.linalg.solve(s, residual))
            is_accepted = bool(np.isfinite(distance) and distance <= gate_mahalanobis_sq)
            innovations[track_index] = residual
            mahalanobis[track_index] = distance
            accepted.append(is_accepted)
            if not is_accepted:
                continue
            gain = predicted_covariances[track_index] @ h.T @ np.linalg.inv(s)
            updated_states[track_index] = predicted_states[track_index] + gain @ residual
            # Joseph stabilized covariance update.
            kh = gain @ h
            updated_covariances[track_index] = _ensure_spd(
                (identity - kh) @ predicted_covariances[track_index] @ (identity - kh).T
                + gain @ r @ gain.T
            )

        self._states = updated_states
        self._states[:, 0] = np.clip(self._states[:, 0], 0.1, 89.9)
        self._covariances = updated_covariances
        self._last_time = float(measurement_time)
        return TrackerUpdateResult(
            assignment=tuple(int(value) for value in assignment),
            innovations_deg=innovations,
            accepted=tuple(accepted),
            innovation_mahalanobis=mahalanobis,
        )

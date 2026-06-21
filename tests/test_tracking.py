from __future__ import annotations

import numpy as np

from hpm_platform.perception.tracking import MultiTargetKalmanTracker


def test_tracker_propagates_measurement_covariance_and_velocity() -> None:
    tracker = MultiTargetKalmanTracker(
        [(20.0, -5.0), (40.0, 10.0)],
        initial_position_std_deg=2.0,
        initial_velocity_std_deg_per_frame=1.0,
        process_acceleration_std_deg_per_frame2=0.1,
    )
    tracker.update(
        [(20.5, -4.8), (39.5, 10.4)],
        [np.diag([0.4, 0.4]) ** 2, np.diag([0.5, 0.5]) ** 2],
        measurement_time=1.0,
    )
    tracker.update(
        [(21.5, -4.3), (38.5, 10.9)],
        [np.diag([0.4, 0.4]) ** 2, np.diag([0.5, 0.5]) ** 2],
        measurement_time=2.0,
    )
    prediction = tracker.predict(4.0)
    assert len(prediction) == 2
    assert prediction[0].mean_deg[0] > 21.5
    assert prediction[1].mean_deg[0] < 38.5
    assert np.min(np.linalg.eigvalsh(prediction[0].covariance_deg2)) > 0


def test_tracker_association_handles_reversed_measurement_order() -> None:
    tracker = MultiTargetKalmanTracker([(20.0, -10.0), (45.0, 12.0)])
    result = tracker.update(
        [(44.8, 12.2), (20.2, -9.8)],
        [np.eye(2) * 0.2, np.eye(2) * 0.2],
        measurement_time=1.0,
    )
    assert result.assignment == (1, 0)
    prediction = tracker.predict(1.0)
    assert abs(prediction[0].mean_deg[0] - 20.2) < 1.0
    assert abs(prediction[1].mean_deg[0] - 44.8) < 1.0


def test_prediction_uncertainty_grows_with_staleness() -> None:
    tracker = MultiTargetKalmanTracker([(30.0, 0.0)], process_acceleration_std_deg_per_frame2=0.3)
    near = tracker.predict(1.0)[0].covariance_deg2
    far = tracker.predict(8.0)[0].covariance_deg2
    assert np.trace(far) > np.trace(near)

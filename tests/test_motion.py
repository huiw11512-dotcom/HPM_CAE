from __future__ import annotations

import numpy as np

from hpmdt.application.factories import make_moving_aircraft
from hpmdt.solvers.math3d import entity_position_at


def test_waypoint_motion_interpolates():
    entity = make_moving_aircraft("对象", [(0, (0, 0, 0)), (10, (10, 20, 30))])
    np.testing.assert_allclose(entity_position_at(entity, 5), [5, 10, 15])


def test_waypoint_motion_clamps_at_endpoints():
    entity = make_moving_aircraft("对象", [(2, (1, 2, 3)), (4, (5, 6, 7))])
    np.testing.assert_allclose(entity_position_at(entity, 0), [1, 2, 3])
    np.testing.assert_allclose(entity_position_at(entity, 9), [5, 6, 7])

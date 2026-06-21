"""Array geometry and field superposition utilities.

Coordinate convention
---------------------
* The rectangular array lies in the x-y plane and is centered at the origin.
* Broadside is +z.
* theta is measured away from +z (0...90 degrees).
* phi is the azimuth measured from +x toward +y.
* Receive steering vector: a(rhat) = exp(+j k r_n dot rhat).
* Transmit propagation: exp(-j k R_n) / R_n.

The module computes normalized fields only. It deliberately does not contain a
source-power or real-device vulnerability budget.
"""
from __future__ import annotations

from dataclasses import dataclass
import numpy as np

C0 = 299_792_458.0


@dataclass(frozen=True)
class RectangularArray:
    """Uniform rectangular array in the x-y plane."""

    nx: int
    ny: int
    frequency_hz: float
    dx_m: float | None = None
    dy_m: float | None = None

    def __post_init__(self) -> None:
        if self.nx < 1 or self.ny < 1:
            raise ValueError("nx and ny must be positive integers")
        if self.frequency_hz <= 0:
            raise ValueError("frequency_hz must be positive")
        wavelength = C0 / self.frequency_hz
        object.__setattr__(self, "dx_m", wavelength / 2 if self.dx_m is None else self.dx_m)
        object.__setattr__(self, "dy_m", wavelength / 2 if self.dy_m is None else self.dy_m)
        if self.dx_m <= 0 or self.dy_m <= 0:
            raise ValueError("Element spacing must be positive")

    @property
    def wavelength_m(self) -> float:
        return C0 / self.frequency_hz

    @property
    def wave_number(self) -> float:
        return 2.0 * np.pi / self.wavelength_m

    @property
    def n_elements(self) -> int:
        return self.nx * self.ny

    @property
    def positions_m(self) -> np.ndarray:
        """Return centered element coordinates with shape (M, 3)."""
        x = (np.arange(self.nx) - (self.nx - 1) / 2.0) * float(self.dx_m)
        y = (np.arange(self.ny) - (self.ny - 1) / 2.0) * float(self.dy_m)
        xx, yy = np.meshgrid(x, y, indexing="ij")
        zz = np.zeros_like(xx)
        return np.column_stack((xx.ravel(), yy.ravel(), zz.ravel()))

    @staticmethod
    def direction_vector(theta_deg: np.ndarray | float, phi_deg: np.ndarray | float) -> np.ndarray:
        """Return unit direction vectors, broadcast to (..., 3)."""
        theta = np.deg2rad(theta_deg)
        phi = np.deg2rad(phi_deg)
        theta, phi = np.broadcast_arrays(theta, phi)
        return np.stack(
            (
                np.sin(theta) * np.cos(phi),
                np.sin(theta) * np.sin(phi),
                np.cos(theta),
            ),
            axis=-1,
        )

    def steering_vector(self, theta_deg: float, phi_deg: float) -> np.ndarray:
        """Receive steering vector with shape (M,)."""
        direction = self.direction_vector(theta_deg, phi_deg).reshape(3)
        phase = self.wave_number * (self.positions_m @ direction)
        return np.exp(1j * phase)

    def steering_matrix(self, theta_deg: np.ndarray, phi_deg: np.ndarray) -> np.ndarray:
        """Steering matrix for paired angle arrays; output shape (M, G)."""
        theta = np.asarray(theta_deg, dtype=float).ravel()
        phi = np.asarray(phi_deg, dtype=float).ravel()
        if theta.shape != phi.shape:
            raise ValueError("theta_deg and phi_deg must have the same flattened shape")
        directions = self.direction_vector(theta, phi).reshape(-1, 3)
        phase = self.wave_number * (self.positions_m @ directions.T)
        return np.exp(1j * phase)

    def conventional_receive_weights(self, theta_deg: float, phi_deg: float) -> np.ndarray:
        """Distortionless conventional receive weights (w^H a = 1)."""
        a = self.steering_vector(theta_deg, phi_deg)
        return a / np.vdot(a, a)

    def far_field_transmit_weights(self, theta_deg: float, phi_deg: float) -> np.ndarray:
        """Unit-norm transmit excitations for a far-field look direction."""
        a = self.steering_vector(theta_deg, phi_deg)
        return np.conj(a) / np.sqrt(self.n_elements)

    def receive_response(
        self,
        weights: np.ndarray,
        theta_deg: np.ndarray,
        phi_deg: np.ndarray,
    ) -> np.ndarray:
        """Compute |w^H a| for paired angle coordinates."""
        w = np.asarray(weights, dtype=complex).reshape(-1)
        if w.size != self.n_elements:
            raise ValueError("weights size does not match array element count")
        a = self.steering_matrix(theta_deg, phi_deg)
        return np.abs(np.conj(w) @ a)

    def transmit_response_uv(
        self,
        excitations: np.ndarray,
        u: np.ndarray,
        v: np.ndarray,
    ) -> np.ndarray:
        """Compute normalized transmit response over direction-cosine coordinates.

        u = sin(theta) cos(phi), v = sin(theta) sin(phi). Values outside the
        visible unit disk are returned as NaN.
        """
        q = np.asarray(excitations, dtype=complex).reshape(-1)
        if q.size != self.n_elements:
            raise ValueError("excitations size does not match array element count")
        uu, vv = np.broadcast_arrays(np.asarray(u, float), np.asarray(v, float))
        visible = uu**2 + vv**2 <= 1.0
        directions = np.column_stack(
            (uu.ravel(), vv.ravel(), np.sqrt(np.maximum(0.0, 1.0 - uu.ravel() ** 2 - vv.ravel() ** 2)))
        )
        phase = self.wave_number * (self.positions_m @ directions.T)
        field = (np.exp(1j * phase).T @ q).reshape(uu.shape)
        field = np.abs(field)
        field[~visible] = np.nan
        finite_max = np.nanmax(field)
        if finite_max > 0:
            field = field / finite_max
        return field

    def phase_conjugate_focus_weights(self, focus_point_m: np.ndarray) -> np.ndarray:
        """Unit-norm phase-only excitations for a near-field focal point."""
        focus = np.asarray(focus_point_m, dtype=float).reshape(3)
        ranges = np.linalg.norm(focus[None, :] - self.positions_m, axis=1)
        if np.any(ranges <= 0):
            raise ValueError("Focus point cannot coincide with an element")
        q = np.exp(1j * self.wave_number * ranges)
        return q / np.linalg.norm(q)

    def near_field_coherence(
        self,
        excitations: np.ndarray,
        points_m: np.ndarray,
        chunk_size: int = 8192,
    ) -> np.ndarray:
        """Return a range-normalized coherent-gain map in [0, 1].

        The metric is |g q|^2 / (||g||^2 ||q||^2), where g contains the
        scalar Green-function coefficients from all elements to a field point.
        It removes trivial distance decay while retaining phase-focusing and
        aperture effects, which makes algorithm comparisons visually honest.
        """
        q = np.asarray(excitations, dtype=complex).reshape(-1)
        pts = np.asarray(points_m, dtype=float).reshape(-1, 3)
        if q.size != self.n_elements:
            raise ValueError("excitations size does not match array element count")
        if chunk_size < 1:
            raise ValueError("chunk_size must be positive")
        q_norm_sq = float(np.vdot(q, q).real)
        output = np.empty(pts.shape[0], dtype=float)
        for start in range(0, pts.shape[0], chunk_size):
            stop = min(start + chunk_size, pts.shape[0])
            delta = pts[start:stop, None, :] - self.positions_m[None, :, :]
            ranges = np.linalg.norm(delta, axis=2)
            ranges = np.maximum(ranges, self.wavelength_m * 1e-6)
            kernel = np.exp(-1j * self.wave_number * ranges) / ranges
            field = kernel @ q
            denominator = np.sum(np.abs(kernel) ** 2, axis=1) * q_norm_sq
            output[start:stop] = np.abs(field) ** 2 / np.maximum(denominator, np.finfo(float).tiny)
        return np.clip(output, 0.0, 1.0)

    def near_field(
        self,
        excitations: np.ndarray,
        points_m: np.ndarray,
        include_spreading: bool = True,
    ) -> np.ndarray:
        """Scalar Green-function superposition at arbitrary field points.

        This is a fast scalar approximation for algorithm development, not a
        replacement for a full-wave solver near conductors, apertures, or
        strongly coupled structures.
        """
        q = np.asarray(excitations, dtype=complex).reshape(-1)
        pts = np.asarray(points_m, dtype=float).reshape(-1, 3)
        if q.size != self.n_elements:
            raise ValueError("excitations size does not match array element count")
        delta = pts[:, None, :] - self.positions_m[None, :, :]
        ranges = np.linalg.norm(delta, axis=2)
        ranges = np.maximum(ranges, self.wavelength_m * 1e-6)
        kernel = np.exp(-1j * self.wave_number * ranges)
        if include_spreading:
            kernel = kernel / ranges
        return kernel @ q

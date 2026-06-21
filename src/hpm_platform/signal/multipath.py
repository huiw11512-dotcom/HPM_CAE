"""Coherent narrowband multipath observations for array-algorithm research.

The model is deliberately normalized: emitter and path powers are expressed
relative to receiver noise. Paths belonging to one emitter share one complex
waveform, reproducing covariance-rank collapse without introducing absolute
source-power or device-vulnerability parameters.
"""
from __future__ import annotations

from dataclasses import dataclass
import numpy as np

from hpm_platform.physics.array_geometry import RectangularArray


@dataclass(frozen=True)
class CoherentPath:
    """One propagation path of a narrowband emitter."""

    theta_deg: float
    phi_deg: float
    relative_power_db: float = 0.0
    phase_deg: float = 0.0
    label: str = "path"


@dataclass(frozen=True)
class CoherentEmitter:
    """An emitter whose propagation paths share one waveform."""

    reference_power_db: float
    paths: tuple[CoherentPath, ...]
    label: str = "emitter"

    def __post_init__(self) -> None:
        if len(self.paths) == 0:
            raise ValueError("An emitter must contain at least one path")


def _complex_normal(rng: np.random.Generator, shape: tuple[int, ...]) -> np.ndarray:
    return (rng.standard_normal(shape) + 1j * rng.standard_normal(shape)) / np.sqrt(2.0)


def draw_sensor_gain_phase_errors(
    n_sensors: int,
    rng: np.random.Generator,
    gain_std_db: float = 0.0,
    phase_std_deg: float = 0.0,
) -> np.ndarray:
    """Draw multiplicative sensor calibration errors."""

    if n_sensors < 1:
        raise ValueError("n_sensors must be positive")
    if gain_std_db < 0 or phase_std_deg < 0:
        raise ValueError("Error standard deviations must be non-negative")
    gain_db = rng.normal(0.0, gain_std_db, n_sensors)
    phase_rad = np.deg2rad(rng.normal(0.0, phase_std_deg, n_sensors))
    return 10.0 ** (gain_db / 20.0) * np.exp(1j * phase_rad)


def simulate_coherent_multipath(
    array: RectangularArray,
    emitters: list[CoherentEmitter],
    n_snapshots: int,
    noise_power: float = 1.0,
    seed: int | None = None,
    sensor_gains: np.ndarray | None = None,
) -> tuple[np.ndarray, dict[str, np.ndarray]]:
    """Generate coherent multipath snapshots.

    Observation model::

        X = G sum_e sum_p a(theta_ep, phi_ep) c_ep s_e + N

    Paths of one emitter share ``s_e``; different emitters are independent.
    """

    if n_snapshots < 2:
        raise ValueError("n_snapshots must be at least 2")
    if noise_power <= 0:
        raise ValueError("noise_power must be positive")
    if len(emitters) == 0:
        raise ValueError("At least one emitter is required")

    rng = np.random.default_rng(seed)
    m = array.n_elements
    gains = np.ones(m, dtype=complex) if sensor_gains is None else np.asarray(sensor_gains, complex).reshape(-1)
    if gains.size != m:
        raise ValueError("sensor_gains size does not match array element count")

    x_signal = np.zeros((m, n_snapshots), dtype=complex)
    components: dict[str, np.ndarray] = {}

    for emitter_index, emitter in enumerate(emitters):
        waveform = _complex_normal(rng, (1, n_snapshots))
        emitter_component = np.zeros_like(x_signal)
        for path_index, path in enumerate(emitter.paths):
            path_power = noise_power * 10.0 ** (
                (float(emitter.reference_power_db) + float(path.relative_power_db)) / 10.0
            )
            excess_phase = np.exp(1j * np.deg2rad(path.phase_deg))
            manifold = gains * array.steering_vector(path.theta_deg, path.phi_deg)
            component = manifold[:, None] @ (
                np.sqrt(path_power) * excess_phase * waveform
            )
            path_key = f"{emitter.label}:{path.label}"
            if path_key in components:
                path_key = f"{path_key}_{emitter_index}_{path_index}"
            components[path_key] = component
            emitter_component += component
        components[f"{emitter.label}:sum"] = emitter_component
        x_signal += emitter_component

    noise = np.sqrt(noise_power) * _complex_normal(rng, x_signal.shape)
    components["noise"] = noise
    return x_signal + noise, components

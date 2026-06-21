"""Synthetic narrowband array observations for repeatable algorithm tests."""
from __future__ import annotations

from dataclasses import dataclass
import numpy as np

from hpm_platform.physics.array_geometry import RectangularArray


@dataclass(frozen=True)
class Source:
    theta_deg: float
    phi_deg: float
    power_db: float
    label: str = "source"


def _complex_normal(rng: np.random.Generator, shape: tuple[int, ...]) -> np.ndarray:
    return (rng.standard_normal(shape) + 1j * rng.standard_normal(shape)) / np.sqrt(2.0)


def simulate_snapshots(
    array: RectangularArray,
    sources: list[Source],
    n_snapshots: int,
    noise_power: float = 1.0,
    seed: int | None = None,
    coherent: bool = False,
) -> tuple[np.ndarray, dict[str, np.ndarray]]:
    """Generate X = sum a_k s_k + noise.

    Source ``power_db`` values are relative to the noise power. Returned data
    shape is (M, snapshots). Components are returned for transparent metrics.
    """
    if n_snapshots < 2:
        raise ValueError("n_snapshots must be at least 2")
    if noise_power <= 0:
        raise ValueError("noise_power must be positive")
    rng = np.random.default_rng(seed)
    x = np.zeros((array.n_elements, n_snapshots), dtype=complex)
    components: dict[str, np.ndarray] = {}
    shared = _complex_normal(rng, (1, n_snapshots)) if coherent else None

    for idx, source in enumerate(sources):
        a = array.steering_vector(source.theta_deg, source.phi_deg)[:, None]
        waveform = shared if shared is not None else _complex_normal(rng, (1, n_snapshots))
        power = noise_power * 10.0 ** (source.power_db / 10.0)
        component = a @ (np.sqrt(power) * waveform)
        key = source.label if source.label not in components else f"{source.label}_{idx}"
        components[key] = component
        x += component

    noise = np.sqrt(noise_power) * _complex_normal(rng, x.shape)
    components["noise"] = noise
    x += noise
    return x, components

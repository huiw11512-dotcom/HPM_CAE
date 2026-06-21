"""Publication-oriented visualizations for the v0.2 perception study."""
from __future__ import annotations

from pathlib import Path
import numpy as np
import matplotlib.pyplot as plt
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch, Rectangle


def _save(fig: plt.Figure, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=230, bbox_inches="tight")
    plt.close(fig)


def plot_fbss_mechanism(output_png: Path, output_svg: Path | None = None) -> None:
    """Draw a fully editable mechanism diagram using Matplotlib only."""

    def draw(path: Path) -> None:
        fig, ax = plt.subplots(figsize=(15.5, 5.2))
        ax.set_xlim(0, 15.5)
        ax.set_ylim(0, 5.2)
        ax.axis("off")

        # Scene: one emitter, two coherent paths, and an 8x8 receiving array.
        ax.text(0.6, 4.45, "One emitter", ha="center", fontsize=11)
        ax.scatter([0.6], [3.75], marker="*", s=180)
        ax.add_patch(Rectangle((2.15, 1.0), 0.14, 3.1, hatch="//", fill=False))
        ax.text(2.22, 0.65, "Reflector", ha="center", fontsize=9)
        for ix in range(8):
            for iy in range(8):
                ax.scatter([4.05 + ix * 0.13], [2.25 + iy * 0.13], s=12)
        ax.text(4.5, 1.85, "8 x 8 URA", ha="center", fontsize=10)
        ax.add_patch(FancyArrowPatch((0.75, 3.72), (4.0, 3.05), arrowstyle="->", mutation_scale=15))
        ax.add_patch(FancyArrowPatch((0.75, 3.68), (2.15, 3.2), arrowstyle="->", mutation_scale=15))
        ax.add_patch(FancyArrowPatch((2.28, 3.2), (4.0, 2.55), arrowstyle="->", mutation_scale=15))
        ax.text(2.9, 3.7, "direct path", fontsize=9)
        ax.text(2.75, 2.55, "coherent echo", fontsize=9)

        boxes = [
            (5.35, 2.2, 2.05, 1.1, "Sample covariance\nrank collapses"),
            (8.0, 2.2, 2.05, 1.1, "Overlapping\nsubarrays"),
            (10.65, 2.2, 2.05, 1.1, "Covariance averaging\n+ FB symmetry"),
            (13.3, 2.2, 1.75, 1.1, "Two MUSIC\npeaks restored"),
        ]
        for x, y, w, h, text in boxes:
            ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0.08", fill=False))
            ax.text(x + w / 2, y + h / 2, text, ha="center", va="center", fontsize=10)
        for first, second in zip(boxes[:-1], boxes[1:]):
            ax.add_patch(FancyArrowPatch(
                (first[0] + first[2], first[1] + first[3] / 2),
                (second[0], second[1] + second[3] / 2),
                arrowstyle="->", mutation_scale=15,
            ))
        ax.add_patch(FancyArrowPatch((4.98, 2.75), (5.35, 2.75), arrowstyle="->", mutation_scale=15))

        ax.text(7.75, 4.75, "Coherent multipath and forward-backward spatial smoothing (FBSS)", ha="center", fontsize=15)
        ax.text(7.75, 0.55, "Shared waveform -> signal-subspace rank loss -> translation diversity -> rank restoration", ha="center", fontsize=11)
        _save(fig, path)

    draw(output_png)
    if output_svg is not None:
        draw(output_svg)


def plot_music_spectrum(
    theta: np.ndarray,
    phi: np.ndarray,
    spectrum: np.ndarray,
    truth: list[tuple[float, float]],
    estimates: list[tuple[float, float]],
    method_label: str,
    output: Path,
) -> None:
    fig, ax = plt.subplots(figsize=(8.4, 6.2))
    mesh = ax.pcolormesh(phi, theta, 10.0 * np.log10(np.maximum(spectrum, 1e-6)), shading="auto")
    ax.scatter([p for _, p in truth], [t for t, _ in truth], marker="x", s=95, linewidths=2.0, label="True paths", zorder=3)
    ax.scatter([p for _, p in estimates], [t for t, _ in estimates], marker="+", s=150, linewidths=2.2, label="Estimated peaks", zorder=4)
    ax.set_xlabel("Azimuth phi (deg)")
    ax.set_ylabel("Elevation from broadside theta (deg)")
    ax.set_title(f"{method_label}: normalized 2-D pseudospectrum")
    ax.legend(loc="upper right")
    fig.colorbar(mesh, ax=ax, label="Pseudospectrum (dB)")
    _save(fig, output)


def plot_eigenspectrum(
    standard: np.ndarray,
    smoothed: np.ndarray,
    output: Path,
    independent: np.ndarray | None = None,
    n_display: int = 14,
) -> None:
    fig, ax = plt.subplots(figsize=(8.8, 5.5))
    series = [(standard, "Coherent: sample covariance"), (smoothed, "Coherent: FBSS covariance")]
    if independent is not None:
        series.append((independent, "Incoherent control: sample covariance"))
    for values, label in series:
        values = np.maximum(np.asarray(values, float), np.finfo(float).tiny)
        normalized_db = 10.0 * np.log10(values / values[0])
        n = min(n_display, normalized_db.size)
        ax.plot(np.arange(1, n + 1), normalized_db[:n], marker="o", label=label)
    ax.axvline(2.5, linestyle="--", label="Two-path signal/noise boundary")
    ax.set_xlabel("Ordered eigenvalue index")
    ax.set_ylabel("Relative eigenvalue (dB)")
    ax.set_title("Signal-subspace rank restoration")
    ax.grid(True, alpha=0.3)
    ax.legend()
    _save(fig, output)


def plot_metric_curve(
    summary_rows: list[dict[str, float | str]],
    x_key: str,
    mean_key: str,
    low_key: str,
    high_key: str,
    xlabel: str,
    ylabel: str,
    title: str,
    output: Path,
    y_limits: tuple[float, float] | None = None,
) -> None:
    fig, ax = plt.subplots(figsize=(8.8, 5.5))
    methods = sorted({str(row["method"]) for row in summary_rows})
    for method in methods:
        rows = sorted((row for row in summary_rows if row["method"] == method), key=lambda row: float(row[x_key]))
        x = np.array([float(row[x_key]) for row in rows])
        mean = np.array([float(row[mean_key]) for row in rows])
        low = np.array([float(row[low_key]) for row in rows])
        high = np.array([float(row[high_key]) for row in rows])
        ax.plot(x, mean, marker="o", label=method)
        ax.fill_between(x, low, high, alpha=0.18)
    ax.set_xlabel(xlabel)
    ax.set_ylabel(ylabel)
    ax.set_title(title)
    if y_limits is not None:
        ax.set_ylim(*y_limits)
    ax.grid(True, alpha=0.3)
    ax.legend()
    _save(fig, output)


def plot_error_cdf(
    records: list[dict[str, float | str]],
    output: Path,
    title: str,
) -> None:
    fig, ax = plt.subplots(figsize=(8.8, 5.5))
    methods = sorted({str(row["method"]) for row in records})
    for method in methods:
        values = np.sort(np.array([float(row["rmse_deg"]) for row in records if row["method"] == method]))
        probability = np.arange(1, values.size + 1) / values.size
        ax.step(values, probability, where="post", label=method)
    ax.set_xlabel("Per-trial matched-path RMSE (deg)")
    ax.set_ylabel("Empirical cumulative probability")
    ax.set_title(title)
    ax.grid(True, alpha=0.3)
    ax.legend()
    _save(fig, output)

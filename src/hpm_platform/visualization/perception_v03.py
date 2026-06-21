"""Publication-oriented visualizations for the v0.3 robust perception study."""
from __future__ import annotations

from pathlib import Path
from typing import Sequence

import numpy as np
import matplotlib.pyplot as plt
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch, Rectangle, Circle


def _save(fig: plt.Figure, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=230, bbox_inches="tight")
    plt.close(fig)


def plot_pawr_mechanism(output_png: Path, output_svg: Path | None = None) -> None:
    """Draw the PAWR signal-flow mechanism as an editable vector figure."""

    def draw(path: Path) -> None:
        fig, ax = plt.subplots(figsize=(16.0, 6.4))
        ax.set_xlim(0, 16)
        ax.set_ylim(0, 6.4)
        ax.axis("off")

        ax.text(8.0, 6.0, "PAWR-MUSIC: robust coherent-multipath perception", ha="center", fontsize=16)

        # Physical scene.
        ax.scatter([0.7], [4.55], marker="*", s=200)
        ax.text(0.7, 5.05, "Emitter", ha="center", fontsize=10)
        ax.add_patch(Rectangle((2.0, 2.0), 0.16, 3.0, hatch="//", fill=False))
        ax.text(2.08, 1.65, "Reflector", ha="center", fontsize=9)
        for ix in range(8):
            for iy in range(8):
                x = 3.65 + 0.13 * ix
                y = 3.08 + 0.13 * iy
                ax.scatter([x], [y], s=13)
        # Mark two unreliable channels.
        ax.add_patch(Circle((3.65, 3.08), 0.10, fill=False, linewidth=1.8))
        ax.add_patch(Circle((4.56, 3.99), 0.10, fill=False, linewidth=1.8))
        ax.text(4.1, 2.62, "8 x 8 URA\nwith local channel corruption", ha="center", fontsize=9)
        ax.add_patch(FancyArrowPatch((0.85, 4.52), (3.62, 3.85), arrowstyle="->", mutation_scale=15))
        ax.add_patch(FancyArrowPatch((0.85, 4.48), (2.0, 4.1), arrowstyle="->", mutation_scale=15))
        ax.add_patch(FancyArrowPatch((2.17, 4.1), (3.62, 3.32), arrowstyle="->", mutation_scale=15))
        ax.text(2.72, 4.62, "direct", fontsize=9)
        ax.text(2.55, 3.34, "coherent echo", fontsize=9)

        boxes = [
            (5.25, 3.0, 1.8, 1.25, "Local-power\nhealth map"),
            (7.45, 3.0, 1.9, 1.25, "Health-weighted\nFB smoothing"),
            (9.75, 3.0, 1.8, 1.25, "Light 2-D\nBTTB regularizer"),
            (11.95, 3.0, 1.8, 1.25, "Broad path prior\n+ continuous WSF"),
            (14.15, 3.0, 1.45, 1.25, "Low-rank\ncovariance fit"),
        ]
        for x, y, w, h, label in boxes:
            ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0.08", fill=False))
            ax.text(x + w / 2, y + h / 2, label, ha="center", va="center", fontsize=9.5)
        ax.add_patch(FancyArrowPatch((4.78, 3.62), (5.25, 3.62), arrowstyle="->", mutation_scale=15))
        for first, second in zip(boxes[:-1], boxes[1:]):
            ax.add_patch(FancyArrowPatch(
                (first[0] + first[2], first[1] + first[3] / 2),
                (second[0], second[1] + second[3] / 2),
                arrowstyle="->",
                mutation_scale=15,
            ))

        ax.text(6.15, 1.55, "data reliability", ha="center", fontsize=9)
        ax.text(8.4, 1.55, "rank restoration", ha="center", fontsize=9)
        ax.text(10.65, 1.55, "weak structure prior", ha="center", fontsize=9)
        ax.text(12.85, 1.55, "ambiguity resolution", ha="center", fontsize=9)
        ax.text(14.88, 1.55, "reproducible output", ha="center", fontsize=9)
        ax.add_patch(FancyArrowPatch((5.3, 1.95), (15.55, 1.95), arrowstyle="-|>", mutation_scale=16))
        ax.text(
            8.0,
            0.72,
            "The broad prior constrains sectors, not exact directions; bias sweeps quantify where that assumption breaks.",
            ha="center",
            fontsize=10.5,
        )
        _save(fig, path)

    draw(output_png)
    if output_svg is not None:
        draw(output_svg)


def plot_sensor_reliability(
    reliability: np.ndarray,
    fault_indices: Sequence[int],
    output: Path,
) -> None:
    values = np.asarray(reliability, dtype=float)
    fig, ax = plt.subplots(figsize=(7.2, 6.0))
    image = ax.imshow(values.T, origin="lower", vmin=0.0, vmax=1.0, aspect="equal")
    if fault_indices:
        nx, ny = values.shape
        xs = [int(index) // ny for index in fault_indices]
        ys = [int(index) % ny for index in fault_indices]
        ax.scatter(xs, ys, marker="x", s=120, linewidths=2.2, label="Injected corrupted channels")
        ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.10))
    ax.set_xlabel("Array x index")
    ax.set_ylabel("Array y index")
    ax.set_title("Data-driven channel reliability")
    ax.set_xticks(np.arange(values.shape[0]))
    ax.set_yticks(np.arange(values.shape[1]))
    fig.colorbar(image, ax=ax, label="Reliability weight")
    _save(fig, output)


def plot_subarray_weights(
    weights: np.ndarray,
    parent_nx: int,
    parent_ny: int,
    subarray_nx: int,
    subarray_ny: int,
    output: Path,
) -> None:
    shape = (parent_nx - subarray_nx + 1, parent_ny - subarray_ny + 1)
    values = np.asarray(weights, dtype=float).reshape(shape)
    fig, ax = plt.subplots(figsize=(7.2, 5.8))
    image = ax.imshow(values.T, origin="lower", aspect="equal")
    for ix in range(shape[0]):
        for iy in range(shape[1]):
            ax.text(ix, iy, f"{values[ix, iy]:.3f}", ha="center", va="center", fontsize=9)
    ax.set_xlabel("Subarray x offset")
    ax.set_ylabel("Subarray y offset")
    ax.set_title("Adaptive overlapping-subarray weights")
    ax.set_xticks(np.arange(shape[0]))
    ax.set_yticks(np.arange(shape[1]))
    fig.colorbar(image, ax=ax, label="Normalized weight")
    _save(fig, output)


def plot_prior_map(
    theta: np.ndarray,
    phi: np.ndarray,
    prior_components: np.ndarray,
    prior_centers: Sequence[tuple[float, float]],
    truth: Sequence[tuple[float, float]],
    estimates: Sequence[tuple[float, float]],
    output: Path,
) -> None:
    prior = np.max(np.asarray(prior_components, dtype=float), axis=0)
    fig, ax = plt.subplots(figsize=(8.4, 6.2))
    mesh = ax.pcolormesh(phi, theta, prior, shading="auto")
    ax.scatter([p for _, p in truth], [t for t, _ in truth], marker="x", s=100, linewidths=2.0, label="True paths")
    ax.scatter([p for _, p in prior_centers], [t for t, _ in prior_centers], marker="o", s=70, facecolors="none", linewidths=1.8, label="Broad prior centers")
    ax.scatter([p for _, p in estimates], [t for t, _ in estimates], marker="+", s=150, linewidths=2.2, label="PAWR estimates")
    ax.set_xlabel("Azimuth phi (deg)")
    ax.set_ylabel("Elevation from broadside theta (deg)")
    ax.set_title("Broad coupling-path prior and continuous estimates")
    ax.legend(loc="upper right")
    fig.colorbar(mesh, ax=ax, label="Prior membership")
    _save(fig, output)


def plot_metric_curve(
    summary_rows: list[dict[str, float | str]],
    *,
    x_key: str,
    mean_key: str,
    low_key: str,
    high_key: str,
    xlabel: str,
    ylabel: str,
    title: str,
    output: Path,
    y_limits: tuple[float, float] | None = None,
    method_order: Sequence[str] | None = None,
) -> None:
    fig, ax = plt.subplots(figsize=(9.0, 5.7))
    methods_present = {str(row["method"]) for row in summary_rows}
    methods = [m for m in (method_order or sorted(methods_present)) if m in methods_present]
    for method in methods:
        rows = sorted(
            (row for row in summary_rows if row["method"] == method),
            key=lambda row: float(row[x_key]),
        )
        x = np.asarray([float(row[x_key]) for row in rows])
        mean = np.asarray([float(row[mean_key]) for row in rows])
        low = np.asarray([float(row[low_key]) for row in rows])
        high = np.asarray([float(row[high_key]) for row in rows])
        ax.plot(x, mean, marker="o", label=method)
        ax.fill_between(x, low, high, alpha=0.16)
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
    method_order: Sequence[str] | None = None,
) -> None:
    fig, ax = plt.subplots(figsize=(8.8, 5.5))
    methods_present = {str(row["method"]) for row in records}
    methods = [m for m in (method_order or sorted(methods_present)) if m in methods_present]
    for method in methods:
        values = np.sort(np.asarray([float(row["rmse_deg"]) for row in records if row["method"] == method]))
        probability = np.arange(1, values.size + 1) / values.size
        ax.step(values, probability, where="post", label=method)
    ax.set_xlabel("Matched-path RMSE (deg)")
    ax.set_ylabel("Empirical cumulative probability")
    ax.set_title(title)
    ax.grid(True, alpha=0.3)
    ax.legend()
    _save(fig, output)


def plot_ablation(
    summary_rows: list[dict[str, float | str]],
    output: Path,
) -> None:
    labels = [str(row["method"]) for row in summary_rows]
    means = np.asarray([float(row["mean_rmse_deg"]) for row in summary_rows])
    low = np.asarray([float(row["rmse_ci_low_deg"]) for row in summary_rows])
    high = np.asarray([float(row["rmse_ci_high_deg"]) for row in summary_rows])
    errors = np.vstack((means - low, high - means))
    fig, ax = plt.subplots(figsize=(9.2, 5.6))
    x = np.arange(len(labels))
    ax.bar(x, means, yerr=errors, capsize=5)
    ax.set_xticks(x, labels, rotation=18, ha="right")
    ax.set_ylabel("Mean matched-path RMSE (deg)")
    ax.set_title("PAWR component ablation (95% confidence intervals)")
    ax.grid(True, axis="y", alpha=0.3)
    _save(fig, output)


def plot_runtime(
    runtime_rows: list[dict[str, float | str]],
    output: Path,
) -> None:
    labels = [str(row["method"]) for row in runtime_rows]
    values = [float(row["median_runtime_ms"]) for row in runtime_rows]
    fig, ax = plt.subplots(figsize=(8.8, 5.4))
    x = np.arange(len(labels))
    ax.bar(x, values)
    ax.set_xticks(x, labels, rotation=18, ha="right")
    ax.set_ylabel("Median runtime per trial (ms)")
    ax.set_title("Algorithm runtime on the recorded environment")
    ax.grid(True, axis="y", alpha=0.3)
    _save(fig, output)


def plot_eigenspectrum_comparison(
    covariance_series: Sequence[tuple[np.ndarray, str]],
    output: Path,
    n_display: int = 14,
) -> None:
    fig, ax = plt.subplots(figsize=(8.8, 5.5))
    for covariance, label in covariance_series:
        values = np.linalg.eigvalsh(0.5 * (covariance + np.conj(covariance.T)))[::-1]
        values = np.maximum(np.real(values), np.finfo(float).tiny)
        values_db = 10.0 * np.log10(values / values[0])
        n = min(n_display, values_db.size)
        ax.plot(np.arange(1, n + 1), values_db[:n], marker="o", label=label)
    ax.axvline(2.5, linestyle="--", label="Two-path boundary")
    ax.set_xlabel("Ordered eigenvalue index")
    ax.set_ylabel("Relative eigenvalue (dB)")
    ax.set_title("Covariance structure and low-rank reconstruction")
    ax.grid(True, alpha=0.3)
    ax.legend()
    _save(fig, output)

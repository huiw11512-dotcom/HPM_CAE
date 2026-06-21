"""Visualization helpers for V0.4 receive-protection experiments."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Sequence

import matplotlib.pyplot as plt
from matplotlib.patches import Ellipse, FancyArrowPatch, FancyBboxPatch
import numpy as np


def _save(fig: plt.Figure, output: str | Path) -> None:
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output, dpi=190, bbox_inches="tight")
    plt.close(fig)


def plot_mechanism(output_png: str | Path, output_svg: str | Path) -> None:
    """Draw the V0.4 confidence-region wide-null mechanism."""
    fig, ax = plt.subplots(figsize=(15.5, 5.0), constrained_layout=True)
    ax.set_xlim(0, 16.4)
    ax.set_ylim(0, 5.0)
    ax.axis("off")

    stages = [
        (0.25, "Perception output", "DOA estimate\n+ confidence ellipse"),
        (3.05, "Angular manifold", "Weighted steering\nsector samples"),
        (5.85, "Subspace model", "SVD energy rank\n+ residual covariance"),
        (8.65, "Robust receive weights", "Hard eigen-null\n+ soft sector penalty"),
        (11.45, "Array response", "Broad null under\ndirection drift"),
        (14.15, "Protection metric", "Output SINR\n+ WNG + latency"),
    ]
    width = 1.95
    for x, title, subtitle in stages:
        box = FancyBboxPatch(
            (x, 1.55),
            width,
            1.9,
            boxstyle="round,pad=0.08,rounding_size=0.08",
            linewidth=1.5,
            facecolor="none",
        )
        ax.add_patch(box)
        ax.text(x + width / 2, 2.9, title, ha="center", va="center", fontsize=11, weight="bold")
        ax.text(x + width / 2, 2.15, subtitle, ha="center", va="center", fontsize=10)
    for left in [2.2, 5.0, 7.8, 10.6, 13.4]:
        ax.add_patch(
            FancyArrowPatch(
                (left, 2.5),
                (left + 0.75, 2.5),
                arrowstyle="-|>",
                mutation_scale=15,
                linewidth=1.4,
            )
        )
    ax.text(
        8.2,
        4.42,
        "V0.3 perception uncertainty becomes an explicit V0.4 spatial constraint",
        ha="center",
        va="center",
        fontsize=13,
        weight="bold",
    )
    ax.text(
        8.2,
        0.62,
        "Normalized defensive receive processing only — no absolute source budget or device-damage inference",
        ha="center",
        va="center",
        fontsize=10,
    )
    _save(fig, output_png)
    fig, ax = plt.subplots(figsize=(15.5, 5.0), constrained_layout=True)
    ax.set_xlim(0, 16.4)
    ax.set_ylim(0, 5.0)
    ax.axis("off")
    for x, title, subtitle in stages:
        box = FancyBboxPatch(
            (x, 1.55), width, 1.9, boxstyle="round,pad=0.08,rounding_size=0.08", linewidth=1.5, facecolor="none"
        )
        ax.add_patch(box)
        ax.text(x + width / 2, 2.9, title, ha="center", va="center", fontsize=11, weight="bold")
        ax.text(x + width / 2, 2.15, subtitle, ha="center", va="center", fontsize=10)
    for left in [2.2, 5.0, 7.8, 10.6, 13.4]:
        ax.add_patch(FancyArrowPatch((left, 2.5), (left + 0.75, 2.5), arrowstyle="-|>", mutation_scale=15, linewidth=1.4))
    ax.text(8.2, 4.42, "V0.3 perception uncertainty becomes an explicit V0.4 spatial constraint", ha="center", va="center", fontsize=13, weight="bold")
    ax.text(8.2, 0.62, "Normalized defensive receive processing only — no absolute source budget or device-damage inference", ha="center", va="center", fontsize=10)
    _save(fig, output_svg)


def plot_response_map(
    theta_grid_deg: np.ndarray,
    phi_grid_deg: np.ndarray,
    response_db: np.ndarray,
    *,
    desired_deg: tuple[float, float],
    interferer_center_deg: tuple[float, float],
    actual_interferer_deg: tuple[float, float],
    half_width_deg: tuple[float, float],
    title: str,
    output: str | Path,
) -> None:
    fig, ax = plt.subplots(figsize=(9.0, 6.5), constrained_layout=True)
    mesh = ax.pcolormesh(phi_grid_deg, theta_grid_deg, response_db, shading="auto", vmin=-80.0, vmax=0.0)
    cbar = fig.colorbar(mesh, ax=ax)
    cbar.set_label("Receive response relative to desired direction (dB)")
    ax.scatter([desired_deg[1]], [desired_deg[0]], marker="*", s=150, label="Desired")
    ax.scatter([interferer_center_deg[1]], [interferer_center_deg[0]], marker="x", s=90, label="Estimated interferer")
    ax.scatter([actual_interferer_deg[1]], [actual_interferer_deg[0]], marker="D", s=72, facecolors="none", edgecolors="black", linewidths=1.8, label="Drifted interferer")
    ellipse = Ellipse(
        (interferer_center_deg[1], interferer_center_deg[0]),
        2.0 * half_width_deg[1],
        2.0 * half_width_deg[0],
        fill=False,
        linewidth=1.5,
        linestyle="--",
        label="Confidence region",
    )
    ax.add_patch(ellipse)
    ax.set_xlabel("Azimuth phi (deg)")
    ax.set_ylabel("Polar angle theta (deg)")
    ax.set_title(title)
    ax.legend(loc="best")
    _save(fig, output)


def plot_angular_cut(
    signed_offset_deg: np.ndarray,
    responses: dict[str, np.ndarray],
    *,
    actual_offset_deg: float,
    title: str,
    output: str | Path,
) -> None:
    fig, ax = plt.subplots(figsize=(9.2, 5.8), constrained_layout=True)
    for method, values in responses.items():
        ax.plot(signed_offset_deg, values, linewidth=1.8, label=method)
    ax.axvline(0.0, linestyle="--", linewidth=1.1, label="Estimated center")
    ax.axvline(actual_offset_deg, linestyle=":", linewidth=1.5, label="Actual interferer")
    ax.axhline(-40.0, linestyle="--", linewidth=1.0, label="-40 dB reference")
    ax.set_xlabel("Signed direction drift along representative path (deg)")
    ax.set_ylabel("Response relative to desired direction (dB)")
    ax.set_ylim(-90.0, 5.0)
    ax.set_title(title)
    ax.grid(True, alpha=0.3)
    ax.legend(ncol=2, fontsize=9)
    _save(fig, output)


def plot_sector_energy(
    singular_values: np.ndarray,
    cumulative_energy: np.ndarray,
    selected_rank: int,
    output: str | Path,
) -> None:
    indices = np.arange(1, min(16, singular_values.size) + 1)
    normalized = singular_values[: indices.size] ** 2
    normalized = normalized / np.sum(singular_values**2)
    fig, ax = plt.subplots(figsize=(8.6, 5.5), constrained_layout=True)
    ax.semilogy(indices, normalized, marker="o", label="Mode energy fraction")
    ax.semilogy(indices, np.maximum(1.0 - cumulative_energy[: indices.size], 1e-8), marker="s", label="Uncovered energy")
    ax.axvline(selected_rank, linestyle="--", linewidth=1.4, label=f"Selected rank = {selected_rank}")
    ax.set_xlabel("Angular-manifold mode index")
    ax.set_ylabel("Fraction")
    ax.set_title("Confidence-sector manifold energy compaction")
    ax.grid(True, which="both", alpha=0.3)
    ax.legend()
    _save(fig, output)


def plot_rank_tradeoff(
    ranks: Sequence[int],
    worst_response_db: Sequence[float],
    *,
    selected_rank: int,
    output: str | Path,
) -> None:
    fig, ax = plt.subplots(figsize=(8.6, 5.4), constrained_layout=True)
    ax.plot(ranks, worst_response_db, marker="o")
    ax.axvline(selected_rank, linestyle="--", linewidth=1.4, label=f"Selected rank = {selected_rank}")
    ax.set_xlabel("Hard eigen-null rank")
    ax.set_ylabel("Worst confidence-region response (dB)")
    ax.set_title("Null-depth benefit of angular-subspace rank")
    ax.grid(True, alpha=0.3)
    ax.legend()
    _save(fig, output)


def plot_metric_curve(
    summary: Sequence[dict[str, Any]],
    *,
    mean_key: str,
    low_key: str | None,
    high_key: str | None,
    xlabel: str,
    ylabel: str,
    title: str,
    output: str | Path,
    method_order: Sequence[str],
    y_limits: tuple[float, float] | None = None,
) -> None:
    fig, ax = plt.subplots(figsize=(9.2, 5.8), constrained_layout=True)
    for method in method_order:
        rows = sorted((row for row in summary if row["method"] == method), key=lambda row: float(row["x_value"]))
        if not rows:
            continue
        x = np.asarray([float(row["x_value"]) for row in rows])
        mean = np.asarray([float(row[mean_key]) for row in rows])
        ax.plot(x, mean, marker="o", linewidth=1.7, label=method)
        if low_key is not None and high_key is not None:
            low = np.asarray([float(row[low_key]) for row in rows])
            high = np.asarray([float(row[high_key]) for row in rows])
            ax.fill_between(x, low, high, alpha=0.12)
    ax.set_xlabel(xlabel)
    ax.set_ylabel(ylabel)
    ax.set_title(title)
    if y_limits is not None:
        ax.set_ylim(*y_limits)
    ax.grid(True, alpha=0.3)
    ax.legend(ncol=2, fontsize=9)
    _save(fig, output)


def plot_cdf(
    records: Sequence[dict[str, Any]],
    *,
    value_key: str,
    xlabel: str,
    title: str,
    method_order: Sequence[str],
    output: str | Path,
) -> None:
    fig, ax = plt.subplots(figsize=(8.8, 5.6), constrained_layout=True)
    for method in method_order:
        values = np.sort(np.asarray([float(row[value_key]) for row in records if row["method"] == method]))
        if values.size == 0:
            continue
        probability = np.arange(1, values.size + 1) / values.size
        ax.step(values, probability, where="post", linewidth=1.7, label=method)
    ax.set_xlabel(xlabel)
    ax.set_ylabel("Empirical CDF")
    ax.set_title(title)
    ax.grid(True, alpha=0.3)
    ax.legend(ncol=2, fontsize=9)
    _save(fig, output)


def plot_ablation(
    rows: Sequence[dict[str, Any]],
    *,
    output: str | Path,
) -> None:
    labels = [str(row["method"]) for row in rows]
    values = [float(row["mean_output_sinr_db"]) for row in rows]
    low = [float(row["sinr_ci_low_db"]) for row in rows]
    high = [float(row["sinr_ci_high_db"]) for row in rows]
    errors = np.vstack((np.asarray(values) - np.asarray(low), np.asarray(high) - np.asarray(values)))
    fig, ax = plt.subplots(figsize=(9.0, 5.6), constrained_layout=True)
    x = np.arange(len(labels))
    ax.bar(x, values, yerr=errors, capsize=4)
    ax.axhline(5.0, linestyle="--", linewidth=1.2, label="5 dB protection criterion")
    ax.set_xticks(x, labels, rotation=18, ha="right")
    ax.set_ylabel("Mean output SINR (dB)")
    ax.set_title("Ablation at 6-degree direction drift (95% CI)")
    ax.grid(True, axis="y", alpha=0.3)
    ax.legend()
    _save(fig, output)


def plot_runtime(rows: Sequence[dict[str, Any]], output: str | Path) -> None:
    labels = [str(row["method"]) for row in rows]
    values = [float(row["median_runtime_ms"]) for row in rows]
    fig, ax = plt.subplots(figsize=(8.8, 5.4), constrained_layout=True)
    x = np.arange(len(labels))
    ax.bar(x, values)
    ax.set_xticks(x, labels, rotation=18, ha="right")
    ax.set_ylabel("Median weight-update time (ms)")
    ax.set_title("Receive-weight computation time")
    ax.grid(True, axis="y", alpha=0.3)
    _save(fig, output)

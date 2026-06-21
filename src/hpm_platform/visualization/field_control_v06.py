"""Publication-oriented figures for V0.6 normalized field control."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping, Sequence

import matplotlib.pyplot as plt
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch
import numpy as np


def _save(fig: plt.Figure, output: str | Path) -> None:
    path = Path(output)
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=220, bbox_inches="tight")
    plt.close(fig)


def _mechanism_figure() -> plt.Figure:
    fig, ax = plt.subplots(figsize=(16.0, 5.1), constrained_layout=True)
    ax.set_xlim(0.0, 17.0)
    ax.set_ylim(0.0, 5.2)
    ax.axis("off")
    stages = [
        (0.35, "Region specification", "Rotated target zone\n+ guard + outside"),
        (3.15, "Field operator", "Scalar Green matrix\n+ normalized reference"),
        (5.95, "Uncertainty ensemble", "Gain / phase errors\n+ registration jitter"),
        (8.75, "SR-PGMS", "Scenario magnitude loss\n+ projected complex Adam"),
        (11.55, "DPD and PA", "Rapp AM/AM\n+ bounded AM/PM inverse"),
        (14.35, "Evaluation", "Uniformity / exposure\n+ robustness probability"),
    ]
    width, height = 2.15, 1.95
    for x, title, subtitle in stages:
        patch = FancyBboxPatch(
            (x, 1.55),
            width,
            height,
            boxstyle="round,pad=0.08,rounding_size=0.08",
            linewidth=1.5,
            facecolor="none",
        )
        ax.add_patch(patch)
        ax.text(x + width / 2.0, 2.92, title, ha="center", va="center", fontsize=11, weight="bold")
        ax.text(x + width / 2.0, 2.18, subtitle, ha="center", va="center", fontsize=9.6)
    for left in [2.52, 5.32, 8.12, 10.92, 13.72]:
        ax.add_patch(
            FancyArrowPatch(
                (left, 2.52),
                (left + 0.55, 2.52),
                arrowstyle="-|>",
                mutation_scale=15,
                linewidth=1.4,
            )
        )
    ax.add_patch(
        FancyArrowPatch(
            (15.42, 1.43),
            (9.75, 1.15),
            connectionstyle="arc3,rad=-0.22",
            arrowstyle="-|>",
            mutation_scale=15,
            linewidth=1.3,
        )
    )
    ax.text(12.55, 0.62, "Metric feedback selects the operating point on the uniformity–exposure trade-off", ha="center", fontsize=9.8)
    ax.text(8.5, 4.62, "V0.6 normalized near-field region control under model and hardware uncertainty", ha="center", fontsize=14, weight="bold")
    return fig


def plot_mechanism(output_png: str | Path, output_svg: str | Path) -> None:
    _save(_mechanism_figure(), output_png)
    _save(_mechanism_figure(), output_svg)


def plot_region_geometry(
    x_lambda: np.ndarray,
    y_lambda: np.ndarray,
    target_mask: np.ndarray,
    guard_mask: np.ndarray,
    array_x_lambda: np.ndarray,
    array_y_lambda: np.ndarray,
    *,
    plane_z_lambda: float,
    output: str | Path,
) -> None:
    labels = np.zeros_like(np.asarray(target_mask, dtype=float))
    labels[np.asarray(guard_mask, bool)] = 1.0
    labels[~(np.asarray(target_mask, bool) | np.asarray(guard_mask, bool))] = 2.0
    fig, ax = plt.subplots(figsize=(8.2, 6.5), constrained_layout=True)
    mesh = ax.pcolormesh(x_lambda, y_lambda, labels, shading="auto")
    fig.colorbar(mesh, ax=ax, ticks=[0, 1, 2], label="0 target, 1 guard, 2 evaluated outside")
    ax.scatter(array_x_lambda, array_y_lambda, marker=".", s=12, label="Array aperture projection")
    ax.set_aspect("equal")
    ax.set_xlabel("x / wavelength")
    ax.set_ylabel("y / wavelength")
    ax.set_title(f"Control-plane region definition at z = {plane_z_lambda:g} wavelengths")
    ax.legend(loc="upper right")
    _save(fig, output)


def plot_field_map(
    x_lambda: np.ndarray,
    y_lambda: np.ndarray,
    amplitude: np.ndarray,
    target_mask: np.ndarray,
    guard_mask: np.ndarray,
    *,
    target_amplitude: float,
    title: str,
    output: str | Path,
) -> None:
    relative_db = 20.0 * np.log10(np.maximum(np.asarray(amplitude, float) / float(target_amplitude), 1e-3))
    fig, ax = plt.subplots(figsize=(8.3, 6.5), constrained_layout=True)
    mesh = ax.pcolormesh(x_lambda, y_lambda, relative_db, shading="auto", vmin=-20.0, vmax=3.0)
    ax.contour(x_lambda, y_lambda, np.asarray(target_mask, float), levels=[0.5], linewidths=1.6)
    ax.contour(x_lambda, y_lambda, np.asarray(guard_mask, float), levels=[0.5], linewidths=1.1, linestyles="--")
    ax.set_aspect("equal")
    ax.set_xlabel("x / wavelength")
    ax.set_ylabel("y / wavelength")
    ax.set_title(title)
    fig.colorbar(mesh, ax=ax, label="Field magnitude relative to target setpoint (dB)")
    _save(fig, output)


def plot_target_amplitude_cdf(
    target_amplitudes: Mapping[str, np.ndarray],
    *,
    target_amplitude: float,
    tolerance_fraction: float,
    output: str | Path,
) -> None:
    fig, ax = plt.subplots(figsize=(8.8, 5.7), constrained_layout=True)
    for method, values in target_amplitudes.items():
        data = np.sort(np.asarray(values, float) / float(target_amplitude))
        probability = np.arange(1, data.size + 1) / data.size
        ax.step(data, probability, where="post", linewidth=1.6, label=method)
    ax.axvline(1.0 - tolerance_fraction, linestyle="--", linewidth=1.2)
    ax.axvline(1.0 + tolerance_fraction, linestyle="--", linewidth=1.2, label="Target tolerance band")
    ax.set_xlabel("Target-zone magnitude / setpoint")
    ax.set_ylabel("Empirical CDF over target-zone samples")
    ax.set_title("Spatial target-zone magnitude distribution")
    ax.grid(True, alpha=0.3)
    ax.legend(fontsize=9)
    _save(fig, output)


def plot_cross_section(
    coordinate_lambda: np.ndarray,
    curves: Mapping[str, np.ndarray],
    *,
    target_amplitude: float,
    target_interval_lambda: tuple[float, float],
    output: str | Path,
) -> None:
    fig, ax = plt.subplots(figsize=(9.2, 5.8), constrained_layout=True)
    for method, values in curves.items():
        ax.plot(coordinate_lambda, np.asarray(values, float) / float(target_amplitude), linewidth=1.7, label=method)
    ax.axhline(1.0, linestyle="--", linewidth=1.2, label="Setpoint")
    ax.axvspan(target_interval_lambda[0], target_interval_lambda[1], alpha=0.12, label="Target-zone cut")
    ax.set_xlabel("x / wavelength at target-center y")
    ax.set_ylabel("Magnitude / target setpoint")
    ax.set_title("Control-plane cross-section")
    ax.grid(True, alpha=0.3)
    ax.legend(ncol=2, fontsize=9)
    _save(fig, output)


def plot_convergence(histories: Mapping[str, np.ndarray], output: str | Path) -> None:
    fig, ax = plt.subplots(figsize=(8.8, 5.6), constrained_layout=True)
    for method, values in histories.items():
        ax.semilogy(np.arange(1, len(values) + 1), np.asarray(values, float), linewidth=1.6, label=method)
    ax.set_xlabel("Optimization iteration")
    ax.set_ylabel("Normalized training objective")
    ax.set_title("Projected magnitude-shaping convergence")
    ax.grid(True, which="both", alpha=0.3)
    ax.legend()
    _save(fig, output)


def plot_metric_curve(
    rows: Sequence[dict[str, Any]],
    *,
    mean_key: str,
    low_key: str | None,
    high_key: str | None,
    xlabel: str,
    ylabel: str,
    title: str,
    methods: Sequence[str],
    output: str | Path,
    y_limits: tuple[float, float] | None = None,
) -> None:
    fig, ax = plt.subplots(figsize=(9.2, 5.8), constrained_layout=True)
    for method in methods:
        selected = sorted((row for row in rows if row["method"] == method), key=lambda row: float(row["x_value"]))
        if not selected:
            continue
        x = np.asarray([float(row["x_value"]) for row in selected])
        mean = np.asarray([float(row[mean_key]) for row in selected])
        ax.plot(x, mean, marker="o", linewidth=1.7, label=method)
        if low_key is not None and high_key is not None:
            low = np.asarray([float(row[low_key]) for row in selected])
            high = np.asarray([float(row[high_key]) for row in selected])
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
    methods: Sequence[str],
    output: str | Path,
) -> None:
    fig, ax = plt.subplots(figsize=(8.8, 5.6), constrained_layout=True)
    for method in methods:
        values = np.sort(np.asarray([float(row[value_key]) for row in records if row["method"] == method]))
        if values.size == 0:
            continue
        probability = np.arange(1, values.size + 1) / values.size
        ax.step(values, probability, where="post", linewidth=1.7, label=method)
    ax.set_xlabel(xlabel)
    ax.set_ylabel("Empirical CDF")
    ax.set_title(title)
    ax.grid(True, alpha=0.3)
    ax.legend(fontsize=9)
    _save(fig, output)


def plot_pa_transfer(
    drive_amplitude: np.ndarray,
    output_curves: Mapping[str, np.ndarray],
    *,
    output: str | Path,
) -> None:
    fig, ax = plt.subplots(figsize=(8.4, 5.5), constrained_layout=True)
    ax.plot(drive_amplitude, drive_amplitude, linestyle="--", linewidth=1.2, label="Ideal linear")
    for label, values in output_curves.items():
        ax.plot(drive_amplitude, values, linewidth=1.7, label=label)
    ax.set_xlabel("Normalized drive magnitude")
    ax.set_ylabel("Normalized output magnitude")
    ax.set_title("Rapp AM/AM curves used in the numerical stress test")
    ax.grid(True, alpha=0.3)
    ax.legend()
    _save(fig, output)


def plot_element_quantity(
    values: np.ndarray,
    *,
    nx: int,
    ny: int,
    title: str,
    label: str,
    output: str | Path,
) -> None:
    matrix = np.asarray(values).reshape(nx, ny).T
    fig, ax = plt.subplots(figsize=(7.2, 5.8), constrained_layout=True)
    mesh = ax.imshow(matrix, origin="lower", aspect="equal")
    ax.set_xlabel("x-element index")
    ax.set_ylabel("y-element index")
    ax.set_title(title)
    fig.colorbar(mesh, ax=ax, label=label)
    _save(fig, output)


def plot_pareto(
    rows: Sequence[dict[str, Any]],
    *,
    selected_penalty: float,
    output: str | Path,
) -> None:
    ordered = sorted(rows, key=lambda row: float(row["outside_penalty"]))
    x = np.asarray([100.0 * float(row["target_rmse_fraction"]) for row in ordered])
    y = np.asarray([float(row["p95_outside_db"]) for row in ordered])
    penalties = np.asarray([float(row["outside_penalty"]) for row in ordered])
    fig, ax = plt.subplots(figsize=(8.2, 5.8), constrained_layout=True)
    ax.plot(x, y, marker="o")
    for xi, yi, penalty in zip(x, y, penalties):
        ax.annotate(f"{penalty:g}", (xi, yi), xytext=(5, 4), textcoords="offset points", fontsize=8)
    selected = int(np.argmin(np.abs(penalties - float(selected_penalty))))
    ax.scatter([x[selected]], [y[selected]], marker="s", s=90, facecolors="none", linewidths=1.7, label="Selected operating point")
    ax.set_xlabel("Target-zone RMSE (%)")
    ax.set_ylabel("95th-percentile outside magnitude (dB relative to setpoint)")
    ax.set_title("Uniformity–outside-exposure trade-off")
    ax.grid(True, alpha=0.3)
    ax.legend()
    _save(fig, output)


def plot_ablation(rows: Sequence[dict[str, Any]], output: str | Path) -> None:
    labels = [str(row["method"]) for row in rows]
    values = [100.0 * float(row["success_rate"]) for row in rows]
    low = [100.0 * float(row["success_ci_low"]) for row in rows]
    high = [100.0 * float(row["success_ci_high"]) for row in rows]
    errors = np.vstack((np.asarray(values) - np.asarray(low), np.asarray(high) - np.asarray(values)))
    fig, ax = plt.subplots(figsize=(9.0, 5.7), constrained_layout=True)
    x = np.arange(len(labels))
    ax.bar(x, values, yerr=errors, capsize=4)
    ax.set_xticks(x, labels, rotation=18, ha="right")
    ax.set_ylabel("Normalized control-success rate (%)")
    ax.set_ylim(0.0, 105.0)
    ax.set_title("Ablation under the representative uncertainty condition")
    ax.grid(True, axis="y", alpha=0.3)
    _save(fig, output)


def plot_runtime(rows: Sequence[dict[str, Any]], output: str | Path) -> None:
    labels = [str(row["method"]) for row in rows]
    values = [float(row["runtime_ms"]) for row in rows]
    fig, ax = plt.subplots(figsize=(8.8, 5.5), constrained_layout=True)
    x = np.arange(len(labels))
    ax.bar(x, values)
    ax.set_xticks(x, labels, rotation=18, ha="right")
    ax.set_ylabel("One-time weight-design runtime (ms)")
    ax.set_title("Normalized field-control weight-design time")
    ax.grid(True, axis="y", alpha=0.3)
    _save(fig, output)

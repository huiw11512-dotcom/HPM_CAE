"""Visualization helpers for the V0.5 dynamic closed-loop workflow."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Sequence

import matplotlib.pyplot as plt
from matplotlib.patches import Ellipse, FancyArrowPatch, FancyBboxPatch
import numpy as np


METHOD_STYLES = {
    "Static-Point": {"linestyle": "--", "marker": None},
    "Delayed-Point": {"linestyle": "-.", "marker": None},
    "Predictive-Point": {"linestyle": "-", "marker": None},
    "Delayed-FixedCR": {"linestyle": "-", "marker": None},
    "PCP-HybridNull": {"linestyle": "-", "marker": None, "linewidth": 2.4},
}


def _save(fig: plt.Figure, output: str | Path) -> None:
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output, dpi=190, bbox_inches="tight")
    plt.close(fig)


def plot_mechanism(output_png: str | Path, output_svg: str | Path) -> None:
    """Draw the sensing-covariance-propagation-protection loop."""
    def draw(path: str | Path) -> None:
        fig, ax = plt.subplots(figsize=(15.8, 6.0), constrained_layout=True)
        ax.set_xlim(0, 16.8)
        ax.set_ylim(0, 6.0)
        ax.axis("off")
        stages = [
            (0.3, "Array snapshots", "Moving sources\n+ sparse channel faults"),
            (3.05, "PAWR perception", "Health-weighted covariance\n+ off-grid DOA"),
            (5.8, "Local uncertainty", "2-D MUSIC posterior\n→ DOA covariance"),
            (8.55, "Timestamped tracker", "Kalman propagation\nthrough latency"),
            (11.3, "PCP-HybridNull", "Multi-sector eigennulls\n+ health penalty"),
            (14.05, "Protection feedback", "SINR, null depth, WNG\n→ next update policy"),
        ]
        width = 2.1
        for x, title, subtitle in stages:
            box = FancyBboxPatch(
                (x, 2.0),
                width,
                2.0,
                boxstyle="round,pad=0.08,rounding_size=0.1",
                linewidth=1.5,
                facecolor="none",
            )
            ax.add_patch(box)
            ax.text(x + width / 2, 3.4, title, ha="center", va="center", fontsize=11, weight="bold")
            ax.text(x + width / 2, 2.65, subtitle, ha="center", va="center", fontsize=9.5)
        for left in [2.4, 5.15, 7.9, 10.65, 13.4]:
            ax.add_patch(
                FancyArrowPatch(
                    (left, 3.0),
                    (left + 0.55, 3.0),
                    arrowstyle="-|>",
                    mutation_scale=15,
                    linewidth=1.4,
                )
            )
        ax.add_patch(
            FancyArrowPatch(
                (15.1, 1.85),
                (1.35, 1.85),
                connectionstyle="arc3,rad=-0.18",
                arrowstyle="-|>",
                mutation_scale=15,
                linewidth=1.35,
            )
        )
        ax.text(8.35, 0.65, "Closed-loop feedback: protection quality and staleness govern the next sensing/update cycle", ha="center", fontsize=11)
        ax.text(8.35, 5.35, "V0.5: perception covariance is propagated in time and converted into dynamic multi-interferer null sectors", ha="center", fontsize=13, weight="bold")
        ax.text(8.35, 0.18, "Normalized defensive receive processing only — no absolute source budget, range, or equipment-damage inference", ha="center", fontsize=9.5)
        _save(fig, path)

    draw(output_png)
    draw(output_svg)


def plot_trajectory(diagnostics: dict[str, Any], output: str | Path) -> None:
    truth = np.asarray(diagnostics["trajectories_deg"])
    packet_frames = np.asarray(diagnostics["packet_frames"], dtype=int)
    measurements = np.asarray(diagnostics["packet_estimates_deg"])
    covariances = np.asarray(diagnostics["packet_covariance_deg2"])
    predictions = np.asarray(diagnostics["predicted_centers_deg"])
    fig, ax = plt.subplots(figsize=(9.2, 7.0), constrained_layout=True)
    for index in range(truth.shape[1]):
        ax.plot(truth[:, index, 1], truth[:, index, 0], linewidth=2.0, label=f"Interferer {index + 1} truth")
        ax.scatter(measurements[:, index, 1], measurements[:, index, 0], s=36, marker="x", label=f"Interferer {index + 1} PAWR")
        ax.plot(predictions[:, index, 1], predictions[:, index, 0], linewidth=1.2, linestyle="--", label=f"Interferer {index + 1} predicted")
        for packet_index in np.linspace(0, max(0, packet_frames.size - 1), min(5, packet_frames.size), dtype=int):
            covariance = covariances[packet_index, index]
            eigenvalues, eigenvectors = np.linalg.eigh(covariance)
            order = np.argsort(eigenvalues)[::-1]
            eigenvalues = eigenvalues[order]
            eigenvectors = eigenvectors[:, order]
            angle = np.rad2deg(np.arctan2(eigenvectors[1, 0], eigenvectors[0, 0]))
            center = measurements[packet_index, index]
            ellipse = Ellipse(
                (center[1], center[0]),
                width=2.0 * 2.45 * np.sqrt(eigenvalues[1]),
                height=2.0 * 2.45 * np.sqrt(eigenvalues[0]),
                angle=90.0 - angle,
                fill=False,
                linewidth=0.9,
                alpha=0.55,
            )
            ax.add_patch(ellipse)
    ax.set_xlabel("Azimuth phi (deg)")
    ax.set_ylabel("Polar angle theta (deg)")
    ax.set_title("Moving-interferer trajectories, PAWR measurements, and latency-compensated predictions")
    ax.grid(True, alpha=0.3)
    ax.legend(ncol=2, fontsize=8.5)
    _save(fig, output)


def plot_timeline(
    packet_frames: np.ndarray,
    ready_frames: np.ndarray,
    fault_masks: np.ndarray,
    output: str | Path,
) -> None:
    packet_frames = np.asarray(packet_frames, dtype=int)
    ready_frames = np.asarray(ready_frames, dtype=int)
    fault_masks = np.asarray(fault_masks, dtype=bool)
    n_frames = fault_masks.shape[0]
    fault_count = np.sum(fault_masks, axis=1)
    fig, ax = plt.subplots(figsize=(10.0, 4.8), constrained_layout=True)
    ax.step(np.arange(n_frames), fault_count, where="post", linewidth=2.0, label="Active failed channels")
    for index, (acquired, ready) in enumerate(zip(packet_frames, ready_frames)):
        y = max(float(np.max(fault_count)) + 0.8, 1.0) + 0.2 * (index % 2)
        ax.scatter([acquired], [y], marker="o", s=42)
        ax.scatter([ready], [y], marker="s", s=42)
        if ready > acquired:
            ax.annotate("", xy=(ready, y), xytext=(acquired, y), arrowprops={"arrowstyle": "->", "lw": 1.0})
    ax.set_xlabel("Frame")
    ax.set_ylabel("Count / event lane")
    ax.set_title("Acquisition-to-actuation latency and staged channel failures")
    ax.grid(True, alpha=0.3)
    ax.legend(loc="upper left")
    _save(fig, output)


def plot_tracking(frame_records: Sequence[dict[str, Any]], threshold_db: float, method_order: Sequence[str], output: str | Path) -> None:
    fig, ax = plt.subplots(figsize=(10.2, 5.8), constrained_layout=True)
    for method in method_order:
        rows = sorted((row for row in frame_records if row["method"] == method), key=lambda row: int(row["frame"]))
        if not rows:
            continue
        x = [int(row["frame"]) for row in rows]
        y = [float(row["output_sinr_db"]) for row in rows]
        style = dict(METHOD_STYLES.get(method, {}))
        ax.plot(x, y, label=method, **style)
    ax.axhline(threshold_db, linestyle=":", linewidth=1.5, label=f"Protection threshold ({threshold_db:g} dB)")
    ax.set_xlabel("Frame")
    ax.set_ylabel("Output SINR (dB)")
    ax.set_title("Dynamic closed-loop receive protection")
    ax.grid(True, alpha=0.3)
    ax.legend(ncol=2, fontsize=8.8)
    _save(fig, output)


def plot_tracking_error(diagnostics: dict[str, Any], packet_records: Sequence[dict[str, Any]], output: str | Path) -> None:
    tracking = np.asarray(diagnostics["tracking_error_deg"])
    packet_frames = np.asarray(diagnostics["packet_frames"], dtype=int)
    measurement_error = np.asarray([float(row["mean_measurement_error_deg"]) for row in packet_records])
    fig, ax = plt.subplots(figsize=(9.6, 5.4), constrained_layout=True)
    ax.plot(np.arange(tracking.shape[0]), np.mean(tracking, axis=1), linewidth=2.0, label="Predicted track error")
    ax.scatter(packet_frames, measurement_error, marker="x", s=48, label="PAWR measurement error")
    ax.set_xlabel("Frame")
    ax.set_ylabel("Mean angular error (deg)")
    ax.set_title("Perception error versus timestamp-propagated tracking error")
    ax.grid(True, alpha=0.3)
    ax.legend()
    _save(fig, output)


def plot_confidence_width_rank(diagnostics: dict[str, Any], output: str | Path) -> None:
    widths = np.asarray(diagnostics["sector_half_width_deg"])
    rank = np.asarray(diagnostics["selected_rank"])
    equivalent_width = np.mean(np.sqrt(widths[:, :, 0] * widths[:, :, 1]), axis=1)
    fig, ax = plt.subplots(figsize=(9.5, 5.4), constrained_layout=True)
    frames = np.arange(widths.shape[0])
    ax.plot(frames, equivalent_width, linewidth=2.0, label="Mean equivalent half-width")
    ax.set_xlabel("Frame")
    ax.set_ylabel("Confidence-sector half-width (deg)")
    ax.grid(True, alpha=0.3)
    second = ax.twinx()
    second.step(frames, rank, where="mid", linewidth=1.6, label="Selected hard-null rank")
    second.set_ylabel("Selected rank")
    lines, labels = ax.get_legend_handles_labels()
    lines2, labels2 = second.get_legend_handles_labels()
    ax.legend(lines + lines2, labels + labels2, loc="best")
    ax.set_title("Uncertainty growth automatically expands sectors and null-subspace rank")
    _save(fig, output)


def plot_sensor_health_timeline(diagnostics: dict[str, Any], output: str | Path) -> None:
    health = np.asarray(diagnostics["packet_health"])
    packet_frames = np.asarray(diagnostics["packet_frames"], dtype=int)
    fig, ax = plt.subplots(figsize=(10.0, 5.6), constrained_layout=True)
    image = ax.imshow(health.T, origin="lower", aspect="auto", vmin=0.0, vmax=1.0, extent=[packet_frames[0] - 0.5, packet_frames[-1] + 0.5, -0.5, health.shape[1] - 0.5])
    cbar = fig.colorbar(image, ax=ax)
    cbar.set_label("PAWR sensor reliability")
    ax.set_xlabel("Acquisition frame")
    ax.set_ylabel("Array channel index")
    ax.set_title("Sensor-health timeline inferred from local power consistency")
    _save(fig, output)


def plot_health_maps(diagnostics: dict[str, Any], array_shape: tuple[int, int], output: str | Path) -> None:
    health = np.asarray(diagnostics["packet_health"])
    faults = np.asarray(diagnostics["packet_fault_masks"])
    frames = np.asarray(diagnostics["packet_frames"])
    selected = sorted(set([0, len(frames) // 2, len(frames) - 1]))
    fig, axes = plt.subplots(1, len(selected), figsize=(4.5 * len(selected), 4.5), constrained_layout=True)
    axes = np.atleast_1d(axes)
    for ax, index in zip(axes, selected):
        grid = health[index].reshape(array_shape)
        image = ax.imshow(grid, origin="lower", vmin=0.0, vmax=1.0)
        failed = np.argwhere(faults[index].reshape(array_shape))
        if failed.size:
            ax.scatter(failed[:, 1], failed[:, 0], marker="x", s=85, linewidths=2.0, label="Injected fault")
            ax.legend(fontsize=8)
        ax.set_title(f"Frame {int(frames[index])}")
        ax.set_xlabel("y index")
        ax.set_ylabel("x index")
    cbar = fig.colorbar(image, ax=axes.tolist(), shrink=0.86)
    cbar.set_label("Sensor reliability")
    fig.suptitle("Spatial localization of channel faults")
    _save(fig, output)


def plot_response_map(
    theta_deg: np.ndarray,
    phi_deg: np.ndarray,
    response_db: np.ndarray,
    *,
    desired_deg: tuple[float, float],
    interferers_deg: np.ndarray,
    predicted_deg: np.ndarray,
    title: str,
    output: str | Path,
) -> None:
    fig, ax = plt.subplots(figsize=(8.8, 6.6), constrained_layout=True)
    mesh = ax.pcolormesh(phi_deg, theta_deg, response_db, shading="auto", vmin=-75.0, vmax=0.0)
    cbar = fig.colorbar(mesh, ax=ax)
    cbar.set_label("Response relative to desired direction (dB)")
    ax.scatter([desired_deg[1]], [desired_deg[0]], marker="*", s=150, label="Desired")
    ax.scatter(interferers_deg[:, 1], interferers_deg[:, 0], marker="D", s=70, facecolors="none", edgecolors="black", linewidths=1.6, label="Actual interferers")
    ax.scatter(predicted_deg[:, 1], predicted_deg[:, 0], marker="x", s=75, linewidths=1.8, label="Protection centers")
    ax.set_xlabel("Azimuth phi (deg)")
    ax.set_ylabel("Polar angle theta (deg)")
    ax.set_title(title)
    ax.legend(loc="best")
    _save(fig, output)


def plot_metric_sweep(
    summary: Sequence[dict[str, Any]],
    *,
    sweep: str,
    mean_key: str,
    low_key: str,
    high_key: str,
    xlabel: str,
    ylabel: str,
    title: str,
    method_order: Sequence[str],
    output: str | Path,
    y_limits: tuple[float, float] | None = None,
) -> None:
    fig, ax = plt.subplots(figsize=(9.2, 5.7), constrained_layout=True)
    for method in method_order:
        rows = sorted(
            (row for row in summary if row["sweep"] == sweep and row["method"] == method),
            key=lambda row: float(row["x_value"]),
        )
        if not rows:
            continue
        x = np.asarray([float(row["x_value"]) for row in rows])
        mean = np.asarray([float(row[mean_key]) for row in rows])
        low = np.asarray([float(row[low_key]) for row in rows])
        high = np.asarray([float(row[high_key]) for row in rows])
        style = dict(METHOD_STYLES.get(method, {}))
        style.pop("marker", None)
        ax.plot(x, mean, marker="o", label=method, **style)
        ax.fill_between(x, low, high, alpha=0.10)
    ax.set_xlabel(xlabel)
    ax.set_ylabel(ylabel)
    ax.set_title(title)
    if y_limits is not None:
        ax.set_ylim(*y_limits)
    ax.grid(True, alpha=0.3)
    ax.legend(ncol=2, fontsize=8.5)
    _save(fig, output)


def plot_runtime(method_summary: Sequence[dict[str, Any]], packet_records: Sequence[dict[str, Any]], output: str | Path) -> None:
    labels = [str(row["method"]) for row in method_summary]
    values = [float(row["median_design_runtime_ms"]) for row in method_summary]
    perception = float(np.median([float(row["runtime_ms"]) for row in packet_records]))
    labels.append("PAWR + covariance")
    values.append(perception)
    fig, ax = plt.subplots(figsize=(9.4, 5.2), constrained_layout=True)
    ax.bar(np.arange(len(labels)), values)
    ax.set_xticks(np.arange(len(labels)), labels, rotation=25, ha="right")
    ax.set_ylabel("Median runtime (ms)")
    ax.set_yscale("log")
    ax.set_title("Per-frame protection update and perception latency")
    ax.grid(True, axis="y", which="both", alpha=0.3)
    _save(fig, output)


def plot_ablation(rows: Sequence[dict[str, Any]], output: str | Path) -> None:
    labels = [str(row["method"]) for row in rows]
    mean = np.asarray([float(row["mean_output_sinr_db"]) for row in rows])
    low = np.asarray([float(row["sinr_ci_low_db"]) for row in rows])
    high = np.asarray([float(row["sinr_ci_high_db"]) for row in rows])
    errors = np.vstack((mean - low, high - mean))
    fig, ax = plt.subplots(figsize=(9.4, 5.5), constrained_layout=True)
    ax.bar(np.arange(len(labels)), mean, yerr=errors, capsize=4)
    ax.set_xticks(np.arange(len(labels)), labels, rotation=22, ha="right")
    ax.set_ylabel("Mean sequence output SINR (dB)")
    ax.set_title("PCP-HybridNull component ablation")
    ax.grid(True, axis="y", alpha=0.3)
    _save(fig, output)

"""Publication-oriented visualization and reporting for V0.7."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping, Sequence
import base64
import html
import io
import json

import matplotlib.pyplot as plt
from matplotlib.patches import Ellipse, FancyArrowPatch, FancyBboxPatch
import numpy as np

from hpm_platform.field_control.region_shaping import rotated_ellipse_masks
from hpm_platform.workflows.dynamic_field_control_v07 import (
    METHOD_COVARIANCE,
    METHOD_DELAYED,
    METHOD_ORDER,
    METHOD_PREDICTIVE,
    METHOD_PROPOSED,
    METHOD_STATIC,
    PlaneGrid,
    TrialOutput,
)


def _save(fig: plt.Figure, output: str | Path, dpi: int = 220) -> None:
    path = Path(output)
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=dpi, bbox_inches="tight")
    plt.close(fig)


def _mechanism_figure() -> plt.Figure:
    fig, ax = plt.subplots(figsize=(17.0, 5.7), constrained_layout=True)
    ax.set_xlim(0.0, 18.0)
    ax.set_ylim(0.0, 5.8)
    ax.axis("off")
    stages = [
        (0.25, "Delayed sensing", "Noisy center packet\nwith acquisition timestamp"),
        (3.15, "State prediction", "Planar Kalman model\nmean + covariance"),
        (6.05, "Uncertainty set", "Covariance sigma centers\n+ hardware ensemble"),
        (8.95, "PCF-RLS", "Moving-region LS\n+ alternating phase update"),
        (11.85, "DPD and PA", "Bounded inverse\n+ normalized Rapp model"),
        (14.75, "Spatial evaluation", "RMSE / coverage / p95\non the true moving zone"),
    ]
    width, height = 2.35, 2.0
    for x, title, subtitle in stages:
        patch = FancyBboxPatch(
            (x, 1.72),
            width,
            height,
            boxstyle="round,pad=0.08,rounding_size=0.08",
            linewidth=1.5,
            facecolor="none",
        )
        ax.add_patch(patch)
        ax.text(x + width / 2, 3.12, title, ha="center", va="center", fontsize=11, weight="bold")
        ax.text(x + width / 2, 2.37, subtitle, ha="center", va="center", fontsize=9.6)
    for left in [2.62, 5.52, 8.42, 11.32, 14.22]:
        ax.add_patch(
            FancyArrowPatch(
                (left, 2.72),
                (left + 0.46, 2.72),
                arrowstyle="-|>",
                mutation_scale=15,
                linewidth=1.35,
            )
        )
    ax.add_patch(
        FancyArrowPatch(
            (16.0, 1.58),
            (9.95, 1.18),
            connectionstyle="arc3,rad=-0.22",
            arrowstyle="-|>",
            mutation_scale=15,
            linewidth=1.35,
        )
    )
    ax.text(12.85, 0.62, "One-frame normalized field-quality feedback adjusts the next region setpoint", ha="center", fontsize=9.8)
    ax.text(9.0, 5.05, "V0.7 dynamic perception–prediction–region-control feedback loop", ha="center", fontsize=14.2, weight="bold")
    return fig


def plot_mechanism(output_png: Path, output_svg: Path) -> None:
    _save(_mechanism_figure(), output_png)
    _save(_mechanism_figure(), output_svg)


def _records_by_method(records: Sequence[Mapping[str, Any]], method: str) -> list[Mapping[str, Any]]:
    return sorted((row for row in records if row["method"] == method), key=lambda row: int(row["frame"]))


def plot_trajectory(
    representative: TrialOutput,
    config: Mapping[str, Any],
    output: Path,
) -> None:
    n_frames = int(config["trajectory"]["frames"])
    actuation = int(config["sensing"]["actuation_latency_frames"])
    truth = representative.trajectory_lambda[actuation : actuation + n_frames]
    predictions = np.asarray(
        [[row["mean_x_lambda"], row["mean_y_lambda"]] for row in representative.predictions],
        dtype=float,
    )
    proposed = _records_by_method(representative.records, METHOD_PROPOSED)
    commands = np.asarray([[row["command_x_lambda"], row["command_y_lambda"]] for row in proposed])
    measurements = np.asarray([[row["x_lambda"], row["y_lambda"]] for row in representative.measurements])

    fig, ax = plt.subplots(figsize=(8.8, 7.0), constrained_layout=True)
    ax.plot(truth[:, 0], truth[:, 1], linewidth=2.0, label="True moving-zone center")
    ax.plot(predictions[:, 0], predictions[:, 1], linestyle="--", linewidth=1.7, label="Timestamped prediction")
    ax.plot(commands[:, 0], commands[:, 1], linestyle=":", linewidth=1.6, label="Applied PCF-RLS center")
    ax.scatter(measurements[:, 0], measurements[:, 1], marker="x", s=35, label="Delayed measurements")
    for index in range(0, len(representative.predictions), 6):
        row = representative.predictions[index]
        covariance = np.array(
            [[row["cov_xx_lambda2"], row["cov_xy_lambda2"]], [row["cov_xy_lambda2"], row["cov_yy_lambda2"]]],
            dtype=float,
        )
        values, vectors = np.linalg.eigh(covariance)
        order = np.argsort(values)[::-1]
        values = values[order]
        vectors = vectors[:, order]
        angle = np.rad2deg(np.arctan2(vectors[1, 0], vectors[0, 0]))
        ellipse = Ellipse(
            xy=(row["mean_x_lambda"], row["mean_y_lambda"]),
            width=4.0 * np.sqrt(max(values[0], 0.0)),
            height=4.0 * np.sqrt(max(values[1], 0.0)),
            angle=angle,
            fill=False,
            linewidth=1.0,
            alpha=0.55,
        )
        ax.add_patch(ellipse)
        ax.text(truth[index, 0], truth[index, 1], str(index), fontsize=8)
    ax.set_aspect("equal")
    ax.set_xlabel("x / wavelength")
    ax.set_ylabel("y / wavelength")
    ax.set_title("Moving-zone trajectory, delayed measurements, and 2σ prediction ellipses")
    ax.grid(True, alpha=0.3)
    ax.legend(fontsize=9)
    _save(fig, output)


def plot_field_snapshot(
    field: np.ndarray,
    metadata: Mapping[str, Any],
    grid: PlaneGrid,
    config: Mapping[str, Any],
    output: Path,
) -> None:
    target = float(config["moving_region"]["target_amplitude"])
    true_center = np.asarray(metadata["true_center_lambda"], dtype=float)
    command_center = np.asarray(metadata["command_center_lambda"], dtype=float)
    masks = rotated_ellipse_masks(
        grid.xx_lambda,
        grid.yy_lambda,
        center_m=(float(true_center[0]), float(true_center[1])),
        semi_axes_m=tuple(float(v) for v in config["moving_region"]["semi_axes_lambda"]),
        rotation_deg=float(config["moving_region"]["rotation_deg"]),
        guard_scale=float(config["moving_region"]["guard_scale"]),
    )
    relative_db = 20.0 * np.log10(np.maximum(np.abs(field) / target, 1e-3))
    fig, ax = plt.subplots(figsize=(8.4, 6.7), constrained_layout=True)
    mesh = ax.pcolormesh(grid.xx_lambda, grid.yy_lambda, relative_db, shading="auto", vmin=-20.0, vmax=3.0)
    ax.contour(grid.xx_lambda, grid.yy_lambda, masks.target.astype(float), levels=[0.5], linewidths=1.7)
    ax.contour(grid.xx_lambda, grid.yy_lambda, masks.guard.astype(float), levels=[0.5], linewidths=1.1, linestyles="--")
    ax.scatter([true_center[0]], [true_center[1]], marker="o", s=50, label="True center")
    ax.scatter([command_center[0]], [command_center[1]], marker="x", s=55, label="Command center")
    ax.set_aspect("equal")
    ax.set_xlabel("x / wavelength")
    ax.set_ylabel("y / wavelength")
    ax.set_title(
        f"{metadata['method']} at frame {metadata['frame']} | "
        f"RMSE {100*metadata['target_rmse_fraction']:.1f}%, coverage {100*metadata['target_coverage']:.1f}%"
    )
    fig.colorbar(mesh, ax=ax, label="Magnitude relative to setpoint (dB)")
    ax.legend(fontsize=9)
    _save(fig, output)


def plot_timeseries(
    records: Sequence[Mapping[str, Any]],
    *,
    value_key: str,
    ylabel: str,
    title: str,
    output: Path,
    scale: float = 1.0,
    reference: float | None = None,
) -> None:
    fig, ax = plt.subplots(figsize=(9.4, 5.8), constrained_layout=True)
    for method in METHOD_ORDER:
        selected = _records_by_method(records, method)
        ax.plot(
            [int(row["frame"]) for row in selected],
            [scale * float(row[value_key]) for row in selected],
            linewidth=1.65,
            label=method,
        )
    if reference is not None:
        ax.axhline(float(reference), linestyle="--", linewidth=1.2, label="Criterion / setpoint")
    ax.set_xlabel("Command frame")
    ax.set_ylabel(ylabel)
    ax.set_title(title)
    ax.grid(True, alpha=0.3)
    ax.legend(ncol=2, fontsize=8.8)
    _save(fig, output)


def plot_feedback_scale(records: Sequence[Mapping[str, Any]], output: Path) -> None:
    selected = _records_by_method(records, METHOD_PROPOSED)
    fig, ax = plt.subplots(figsize=(9.2, 5.5), constrained_layout=True)
    ax.plot([row["frame"] for row in selected], [row["feedback_scale"] for row in selected], marker="o", markersize=3)
    ax.axhline(1.0, linestyle="--", linewidth=1.2, label="Open-loop scale")
    ax.set_xlabel("Command frame")
    ax.set_ylabel("Bounded feedback scale")
    ax.set_title("PCF-RLS normalized setpoint adaptation")
    ax.grid(True, alpha=0.3)
    ax.legend()
    _save(fig, output)


def plot_success_timeline(records: Sequence[Mapping[str, Any]], output: Path) -> None:
    matrix = np.array(
        [[float(row["control_success"]) for row in _records_by_method(records, method)] for method in METHOD_ORDER],
        dtype=float,
    )
    fig, ax = plt.subplots(figsize=(10.0, 4.7), constrained_layout=True)
    mesh = ax.imshow(matrix, aspect="auto", interpolation="nearest", vmin=0.0, vmax=1.0)
    ax.set_yticks(np.arange(len(METHOD_ORDER)), METHOD_ORDER)
    ax.set_xlabel("Command frame")
    ax.set_title("Dynamic control availability timeline (1 = all normalized criteria met)")
    fig.colorbar(mesh, ax=ax, ticks=[0, 1])
    _save(fig, output)


def plot_sweep(
    summary: Sequence[Mapping[str, Any]],
    *,
    sweep: str,
    metric_prefix: str,
    xlabel: str,
    ylabel: str,
    title: str,
    output: Path,
    scale: float = 1.0,
) -> None:
    fig, ax = plt.subplots(figsize=(9.3, 5.8), constrained_layout=True)
    for method in METHOD_ORDER:
        selected = sorted(
            (row for row in summary if row["sweep"] == sweep and row["method"] == method),
            key=lambda row: float(row["x_value"]),
        )
        if not selected:
            continue
        x = np.asarray([float(row["x_value"]) for row in selected])
        mean = scale * np.asarray([float(row[f"{metric_prefix}_mean"]) for row in selected])
        low = scale * np.asarray([float(row[f"{metric_prefix}_ci_low"]) for row in selected])
        high = scale * np.asarray([float(row[f"{metric_prefix}_ci_high"]) for row in selected])
        ax.plot(x, mean, marker="o", linewidth=1.65, label=method)
        ax.fill_between(x, low, high, alpha=0.12)
    ax.set_xlabel(xlabel)
    ax.set_ylabel(ylabel)
    ax.set_title(title)
    ax.grid(True, alpha=0.3)
    ax.legend(ncol=2, fontsize=8.8)
    _save(fig, output)


def plot_rmse_cdf(
    rows: Sequence[Mapping[str, Any]],
    config: Mapping[str, Any],
    output: Path,
) -> None:
    base_delay = float(config["sensing"]["processing_delay_frames"])
    selected = [row for row in rows if row["sweep"] == "processing_delay_frames" and float(row["x_value"]) == base_delay]
    fig, ax = plt.subplots(figsize=(8.8, 5.7), constrained_layout=True)
    for method in METHOD_ORDER:
        values = np.sort(
            np.asarray(
                [100.0 * float(row["mean_target_rmse_fraction"]) for row in selected if row["method"] == method]
            )
        )
        if values.size == 0:
            continue
        probability = np.arange(1, values.size + 1) / values.size
        ax.step(values, probability, where="post", linewidth=1.7, label=method)
    ax.set_xlabel("Trial-mean target-zone RMSE (%)")
    ax.set_ylabel("Empirical CDF")
    ax.set_title(f"Paired Monte Carlo RMSE distribution at {base_delay:g}-frame processing delay")
    ax.grid(True, alpha=0.3)
    ax.legend(fontsize=8.8)
    _save(fig, output)


def plot_ablation(summary: Sequence[Mapping[str, Any]], output: Path) -> None:
    labels = [str(row["method"]).replace("PCF-RLS: ", "") for row in summary]
    values = [100.0 * float(row["mean_target_rmse_fraction_mean"]) for row in summary]
    low = [100.0 * float(row["mean_target_rmse_fraction_ci_low"]) for row in summary]
    high = [100.0 * float(row["mean_target_rmse_fraction_ci_high"]) for row in summary]
    errors = np.vstack((np.asarray(values) - np.asarray(low), np.asarray(high) - np.asarray(values)))
    fig, ax = plt.subplots(figsize=(9.7, 5.9), constrained_layout=True)
    ax.bar(np.arange(len(labels)), values, yerr=errors, capsize=4)
    ax.set_xticks(np.arange(len(labels)), labels, rotation=18, ha="right")
    ax.set_ylabel("Mean target-zone RMSE (%)")
    ax.set_title("PCF-RLS component ablation with trial-level confidence intervals")
    ax.grid(True, axis="y", alpha=0.3)
    _save(fig, output)


def plot_runtime(summary: Sequence[Mapping[str, Any]], output: Path) -> None:
    values = [float(row["median_update_runtime_ms"]) for row in summary]
    fig, ax = plt.subplots(figsize=(8.8, 5.4), constrained_layout=True)
    ax.bar(np.arange(len(METHOD_ORDER)), values)
    ax.set_xticks(np.arange(len(METHOD_ORDER)), METHOD_ORDER, rotation=18, ha="right")
    ax.set_ylabel("Median online update time (ms)")
    ax.set_title("Representative online controller update cost")
    ax.grid(True, axis="y", alpha=0.3)
    _save(fig, output)


def create_animation(
    representative: TrialOutput,
    grid: PlaneGrid,
    config: Mapping[str, Any],
    output: Path,
) -> bool:
    try:
        from PIL import Image
    except Exception:
        return False
    keys = sorted(
        (key for key in representative.snapshots if key.startswith(f"{METHOD_PROPOSED}__")),
        key=lambda key: int(representative.snapshot_metadata[key]["frame"]),
    )
    if not keys:
        return False
    target = float(config["moving_region"]["target_amplitude"])
    images: list[Image.Image] = []
    for key in keys:
        field = representative.snapshots[key]
        meta = representative.snapshot_metadata[key]
        true_center = np.asarray(meta["true_center_lambda"], float)
        command_center = np.asarray(meta["command_center_lambda"], float)
        masks = rotated_ellipse_masks(
            grid.xx_lambda,
            grid.yy_lambda,
            center_m=tuple(true_center),
            semi_axes_m=tuple(float(v) for v in config["moving_region"]["semi_axes_lambda"]),
            rotation_deg=float(config["moving_region"]["rotation_deg"]),
            guard_scale=float(config["moving_region"]["guard_scale"]),
        )
        relative_db = 20.0 * np.log10(np.maximum(np.abs(field) / target, 1e-3))
        fig, ax = plt.subplots(figsize=(7.2, 5.8), constrained_layout=True)
        mesh = ax.pcolormesh(grid.xx_lambda, grid.yy_lambda, relative_db, shading="auto", vmin=-20.0, vmax=3.0)
        ax.contour(grid.xx_lambda, grid.yy_lambda, masks.target.astype(float), levels=[0.5], linewidths=1.6)
        ax.contour(grid.xx_lambda, grid.yy_lambda, masks.guard.astype(float), levels=[0.5], linewidths=1.0, linestyles="--")
        ax.scatter([true_center[0]], [true_center[1]], marker="o", s=45)
        ax.scatter([command_center[0]], [command_center[1]], marker="x", s=50)
        ax.set_aspect("equal")
        ax.set_xlabel("x / wavelength")
        ax.set_ylabel("y / wavelength")
        ax.set_title(
            f"PCF-RLS frame {meta['frame']} | RMSE {100*meta['target_rmse_fraction']:.1f}% | "
            f"coverage {100*meta['target_coverage']:.0f}%"
        )
        fig.colorbar(mesh, ax=ax, label="Relative magnitude (dB)")
        buffer = io.BytesIO()
        fig.savefig(buffer, format="png", dpi=115, bbox_inches="tight")
        plt.close(fig)
        buffer.seek(0)
        images.append(Image.open(buffer).convert("P", palette=Image.ADAPTIVE))
    output.parent.mkdir(parents=True, exist_ok=True)
    images[0].save(output, save_all=True, append_images=images[1:], duration=260, loop=0, optimize=False)
    return True


def _manifest_entry(filename: str, title: str, description: str) -> dict[str, str]:
    return {"filename": filename, "title": title, "description": description}


def generate_all_figures(
    *,
    output_dir: Path,
    config: Mapping[str, Any],
    representative: TrialOutput,
    representative_summary: Sequence[Mapping[str, Any]],
    sweep_summary: Sequence[Mapping[str, Any]],
    sweep_rows: Sequence[Mapping[str, Any]],
    ablation_summary: Sequence[Mapping[str, Any]],
    grid: PlaneGrid,
) -> list[dict[str, str]]:
    manifest: list[dict[str, str]] = []
    plot_mechanism(output_dir / "00_pcf_rls_mechanism.png", output_dir / "00_pcf_rls_mechanism.svg")
    manifest.append(_manifest_entry("00_pcf_rls_mechanism.png", "V0.7 closed-loop mechanism", "Timestamped sensing, prediction covariance, robust moving-region design, normalized PA, and feedback."))

    plot_trajectory(representative, config, output_dir / "01_trajectory_and_uncertainty.png")
    manifest.append(_manifest_entry("01_trajectory_and_uncertainty.png", "Trajectory and prediction uncertainty", "True moving-zone center, delayed measurements, prediction path, applied command centers, and 2σ ellipses."))

    middle = int(config["representative"]["snapshot_frames"][1])
    numbering = {
        METHOD_STATIC: "02_static_field.png",
        METHOD_DELAYED: "03_delayed_field.png",
        METHOD_PREDICTIVE: "04_predictive_field.png",
        METHOD_COVARIANCE: "05_covariance_field.png",
        METHOD_PROPOSED: "06_pcf_rls_field.png",
    }
    for method in METHOD_ORDER:
        key = f"{method}__frame_{middle:03d}"
        plot_field_snapshot(representative.snapshots[key], representative.snapshot_metadata[key], grid, config, output_dir / numbering[method])
        manifest.append(_manifest_entry(numbering[method], f"{method} field snapshot", f"Control-plane magnitude at the maneuver snapshot (frame {middle})."))

    for number, frame, label in [(7, int(config["representative"]["snapshot_frames"][0]), "early"), (8, int(config["representative"]["snapshot_frames"][2]), "late")]:
        key = f"{METHOD_PROPOSED}__frame_{frame:03d}"
        filename = f"{number:02d}_pcf_rls_{label}_field.png"
        plot_field_snapshot(representative.snapshots[key], representative.snapshot_metadata[key], grid, config, output_dir / filename)
        manifest.append(_manifest_entry(filename, f"PCF-RLS {label} snapshot", f"Moving-zone field at frame {frame}."))

    plot_timeseries(representative.records, value_key="target_rmse_fraction", ylabel="Target-zone RMSE (%)", title="Dynamic target-zone magnitude error", output=output_dir / "09_rmse_vs_frame.png", scale=100.0, reference=100.0 * float(config["success_criterion"]["target_rmse_fraction"]))
    manifest.append(_manifest_entry("09_rmse_vs_frame.png", "RMSE versus frame", "Time-resolved target-zone error for all control methods."))
    plot_timeseries(representative.records, value_key="target_coverage", ylabel="Samples within ±10% (%)", title="Dynamic target-zone coverage", output=output_dir / "10_coverage_vs_frame.png", scale=100.0, reference=100.0 * float(config["success_criterion"]["minimum_target_coverage"]))
    manifest.append(_manifest_entry("10_coverage_vs_frame.png", "Coverage versus frame", "Fraction of the true moving target zone within the normalized tolerance band."))
    plot_timeseries(representative.records, value_key="p95_outside_db", ylabel="Outside p95 relative magnitude (dB)", title="Dynamic outside-zone exposure statistic", output=output_dir / "11_p95_outside_vs_frame.png", reference=float(config["success_criterion"]["maximum_p95_outside_db"]))
    manifest.append(_manifest_entry("11_p95_outside_vs_frame.png", "Outside p95 versus frame", "Robust outside-zone statistic used in the dynamic availability criterion."))
    plot_timeseries(representative.records, value_key="command_center_error_lambda", ylabel="Command-center error (wavelengths)", title="Tracking and actuation alignment error", output=output_dir / "12_center_error_vs_frame.png")
    manifest.append(_manifest_entry("12_center_error_vs_frame.png", "Center error versus frame", "Distance from each method's applied center to the future true center."))
    plot_timeseries(representative.records, value_key="target_mean", ylabel="Mean target-zone magnitude", title="Normalized target-zone mean response", output=output_dir / "13_target_mean_vs_frame.png", reference=float(config["moving_region"]["target_amplitude"]))
    manifest.append(_manifest_entry("13_target_mean_vs_frame.png", "Target mean versus frame", "Feedback corrects systematic under-response while remaining bounded."))
    plot_feedback_scale(representative.records, output_dir / "14_feedback_scale.png")
    manifest.append(_manifest_entry("14_feedback_scale.png", "Feedback scale", "Bounded one-frame-delayed setpoint correction used only by PCF-RLS."))
    plot_success_timeline(representative.records, output_dir / "15_success_timeline.png")
    manifest.append(_manifest_entry("15_success_timeline.png", "Availability timeline", "Frames that jointly satisfy RMSE, coverage, and outside-p95 criteria."))

    sweep_specs = [
        ("processing_delay_frames", "Processing delay (frames)", "delay"),
        ("measurement_noise_std_lambda", "Measurement noise standard deviation (wavelengths)", "noise"),
        ("maneuver_scale", "Maneuver scale", "maneuver"),
        ("phase_error_std_deg", "Element phase-error standard deviation (deg)", "phase"),
    ]
    number = 16
    for sweep, xlabel, short in sweep_specs:
        rmse_name = f"{number:02d}_{short}_rmse.png"
        plot_sweep(sweep_summary, sweep=sweep, metric_prefix="mean_target_rmse_fraction", xlabel=xlabel, ylabel="Trial-mean target-zone RMSE (%)", title=f"RMSE sensitivity to {xlabel.lower()}", output=output_dir / rmse_name, scale=100.0)
        manifest.append(_manifest_entry(rmse_name, f"RMSE versus {short}", "Paired Monte Carlo mean and trial-level 95% confidence interval."))
        number += 1
        success_name = f"{number:02d}_{short}_success.png"
        plot_sweep(sweep_summary, sweep=sweep, metric_prefix="control_success_rate", xlabel=xlabel, ylabel="Dynamic availability (%)", title=f"Availability sensitivity to {xlabel.lower()}", output=output_dir / success_name, scale=100.0)
        manifest.append(_manifest_entry(success_name, f"Availability versus {short}", "Fraction of frames meeting all normalized dynamic criteria."))
        number += 1

    plot_rmse_cdf(sweep_rows, config, output_dir / "24_rmse_cdf_base_delay.png")
    manifest.append(_manifest_entry("24_rmse_cdf_base_delay.png", "Base-delay RMSE CDF", "Trial-level paired distribution at the representative processing delay."))
    plot_ablation(ablation_summary, output_dir / "25_ablation.png")
    manifest.append(_manifest_entry("25_ablation.png", "Component ablation", "Removal of prediction, covariance, hardware ensemble, feedback, or DPD."))
    plot_runtime(representative_summary, output_dir / "26_runtime.png")
    manifest.append(_manifest_entry("26_runtime.png", "Online update runtime", "Median representative update time; field-grid rendering is excluded."))
    if create_animation(representative, grid, config, output_dir / "27_pcf_rls_dynamic_field.gif"):
        manifest.append(_manifest_entry("27_pcf_rls_dynamic_field.gif", "Dynamic field animation", "Frame-by-frame PCF-RLS field, true region, and command center."))
    return manifest


def _summary_table(rows: Sequence[Mapping[str, Any]]) -> str:
    body = []
    for row in rows:
        body.append(
            "<tr>"
            f"<td>{html.escape(str(row['method']))}</td>"
            f"<td>{100*float(row['mean_target_rmse_fraction']):.2f}%</td>"
            f"<td>{100*float(row['mean_target_coverage']):.1f}%</td>"
            f"<td>{float(row['mean_peak_outside_db']):.2f} dB</td>"
            f"<td>{100*float(row['control_success_rate']):.1f}%</td>"
            f"<td>{float(row['mean_command_center_error_lambda']):.3f}λ</td>"
            f"<td>{float(row['median_update_runtime_ms']):.2f} ms</td>"
            "</tr>"
        )
    return (
        "<table><thead><tr><th>Method</th><th>Mean RMSE</th><th>Coverage</th><th>Mean peak outside</th>"
        "<th>Availability</th><th>Center error</th><th>Median update</th></tr></thead><tbody>"
        + "".join(body)
        + "</tbody></table>"
    )


def _ablation_table(rows: Sequence[Mapping[str, Any]]) -> str:
    body = []
    for row in rows:
        body.append(
            "<tr>"
            f"<td>{html.escape(str(row['method']))}</td>"
            f"<td>{100*float(row['mean_target_rmse_fraction_mean']):.2f}%</td>"
            f"<td>{100*float(row['mean_target_coverage_mean']):.1f}%</td>"
            f"<td>{100*float(row['control_success_rate_mean']):.1f}%</td>"
            "</tr>"
        )
    return "<table><thead><tr><th>Variant</th><th>Mean RMSE</th><th>Coverage</th><th>Availability</th></tr></thead><tbody>" + "".join(body) + "</tbody></table>"


def _asset_uri(path: Path) -> str:
    suffix = path.suffix.lower()
    mime = {".png": "image/png", ".gif": "image/gif", ".svg": "image/svg+xml"}.get(suffix, "application/octet-stream")
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{mime};base64,{encoded}"


def _report_html(
    *,
    output_dir: Path,
    config: Mapping[str, Any],
    metrics: Mapping[str, Any],
    representative_summary: Sequence[Mapping[str, Any]],
    ablation_summary: Sequence[Mapping[str, Any]],
    figure_manifest: Sequence[Mapping[str, str]],
    standalone: bool,
) -> str:
    proposed = next(row for row in representative_summary if row["method"] == METHOD_PROPOSED)
    predictive = next(row for row in representative_summary if row["method"] == METHOD_PREDICTIVE)
    reduction = 100.0 * (float(predictive["mean_target_rmse_fraction"]) - float(proposed["mean_target_rmse_fraction"])) / max(float(predictive["mean_target_rmse_fraction"]), 1e-12)
    figures = []
    for item in figure_manifest:
        path = output_dir / item["filename"]
        src = _asset_uri(path) if standalone else item["filename"]
        figures.append(
            f"<section class='figure'><h3>{html.escape(item['title'])}</h3>"
            f"<img src='{src}' alt='{html.escape(item['title'])}' loading='lazy'>"
            f"<p>{html.escape(item['description'])}</p></section>"
        )
    paired = metrics["paired_statistics"]["comparisons"]
    comparisons = "".join(
        f"<li>vs {html.escape(name)}: {value['mean_rmse_reduction_percentage_points']:.2f} percentage points, "
        f"one-sided paired Wilcoxon p={value['wilcoxon_one_sided_p']:.4g} (quick configuration).</li>"
        for name, value in paired.items()
    )
    return f"""<!doctype html>
<html lang='en'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>
<title>HPM Digital Twin V0.7 Dynamic Field Control</title>
<style>
body{{font-family:Arial,Helvetica,sans-serif;max-width:1180px;margin:0 auto;padding:28px;line-height:1.55;color:#202124}}
h1,h2,h3{{line-height:1.22}} .card{{border:1px solid #d0d4d8;border-radius:10px;padding:18px;margin:16px 0}}
table{{border-collapse:collapse;width:100%;font-size:14px}} th,td{{border:1px solid #cfd4da;padding:8px;text-align:right}} th:first-child,td:first-child{{text-align:left}}
.figure{{margin:34px 0}} .figure img{{display:block;max-width:100%;height:auto;margin:0 auto;border:1px solid #e0e0e0}}
.note{{background:#f6f7f8;padding:14px;border-left:4px solid #666}} code{{background:#f2f2f2;padding:2px 4px}}
</style></head><body>
<h1>HPM Digital Twin V0.7: Dynamic Prediction–Region-Control Loop</h1>
<p>This report documents a fully Python, normalized numerical experiment. It connects delayed moving-zone sensing to timestamped prediction, covariance-aware spatial control, normalized PA/DPD, and one-frame field-quality feedback.</p>
<div class='card'><h2>Representative result</h2>
<p>Under a 4-frame processing delay, 0.17λ measurement noise, 8° element phase-error standard deviation, and a maneuvering target zone, PCF-RLS reached <strong>{100*float(proposed['mean_target_rmse_fraction']):.2f}%</strong> mean target-zone RMSE and <strong>{100*float(proposed['mean_target_coverage']):.1f}%</strong> mean ±10% coverage. Its RMSE was {reduction:.1f}% lower than Predictive-RLS in this representative run.</p>
{_summary_table(representative_summary)}</div>
<div class='card'><h2>Paired quick-configuration statistics</h2><ul>{comparisons}</ul>
<p>These p-values use only the quick Monte Carlo setting in the YAML file. The paper configuration is provided but was not executed in this artifact.</p></div>
<div class='card'><h2>Component ablation</h2>{_ablation_table(ablation_summary)}</div>
<div class='note'><strong>Scope boundary.</strong> Coordinates, field setpoints, PA saturation, and response criteria are normalized. The platform contains no absolute source power, range budget, real device susceptibility, calibrated damage threshold, or real-world effect claim. “Availability” means only that the configured numerical RMSE, coverage, and outside-p95 criteria were met.</div>
<h2>Figures</h2>{''.join(figures)}
<h2>Reproducibility</h2><p>Configuration: <code>config_snapshot.yaml</code>. Frame records, Monte Carlo trials, summaries, NPZ snapshots, LaTeX table, environment record, and SHA-256 checksums are included in the same output directory.</p>
<p>Generated with platform version {html.escape(str(metrics['platform_version']))}; total workflow runtime recorded as {float(metrics['run_time_seconds']):.2f} s before report finalization.</p>
</body></html>"""


def write_reports(
    *,
    output_dir: Path,
    config: Mapping[str, Any],
    metrics: Mapping[str, Any],
    representative_summary: Sequence[Mapping[str, Any]],
    sweep_summary: Sequence[Mapping[str, Any]],
    ablation_summary: Sequence[Mapping[str, Any]],
    figure_manifest: Sequence[Mapping[str, str]],
) -> None:
    regular = _report_html(
        output_dir=output_dir,
        config=config,
        metrics=metrics,
        representative_summary=representative_summary,
        ablation_summary=ablation_summary,
        figure_manifest=figure_manifest,
        standalone=False,
    )
    standalone = _report_html(
        output_dir=output_dir,
        config=config,
        metrics=metrics,
        representative_summary=representative_summary,
        ablation_summary=ablation_summary,
        figure_manifest=figure_manifest,
        standalone=True,
    )
    (output_dir / "dynamic_field_control_v07_report.html").write_text(regular, encoding="utf-8")
    (output_dir / "dynamic_field_control_v07_report_standalone.html").write_text(standalone, encoding="utf-8")

    proposed = next(row for row in representative_summary if row["method"] == METHOD_PROPOSED)
    predictive = next(row for row in representative_summary if row["method"] == METHOD_PREDICTIVE)
    text = f"""# V0.7 key findings

- Representative PCF-RLS mean target-zone RMSE: **{100*float(proposed['mean_target_rmse_fraction']):.2f}%**.
- Representative PCF-RLS mean ±10% coverage: **{100*float(proposed['mean_target_coverage']):.1f}%**.
- Representative normalized availability: **{100*float(proposed['control_success_rate']):.1f}%**.
- Predictive-RLS mean RMSE: **{100*float(predictive['mean_target_rmse_fraction']):.2f}%**.
- PCF-RLS median online update time: **{float(proposed['median_update_runtime_ms']):.2f} ms** under the recorded environment.
- The quick Monte Carlo and ablation settings are intended for acceptance testing, not final paper statistics.
- All outputs are normalized and cannot be used to infer real source power, range, equipment thresholds, or physical damage.
"""
    (output_dir / "KEY_FINDINGS.md").write_text(text, encoding="utf-8")
    readme = """# V0.7 output directory

Open `dynamic_field_control_v07_report_standalone.html` for the self-contained visual report. The GIF shows the frame-by-frame normalized field. CSV files contain representative and Monte Carlo records; `representative_case.npz` contains the trajectory, hardware gain vector, and complex field snapshots.
"""
    (output_dir / "README.md").write_text(readme, encoding="utf-8")

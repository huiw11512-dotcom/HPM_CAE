"""Publication-oriented figures and reports for V0.8."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping, Sequence
import base64
import html
import io
import json

import matplotlib.pyplot as plt
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch
import numpy as np
from PIL import Image

from hpm_platform.evaluation.effect_digital_twin import EffectTier, lognormal_response_probability
from hpm_platform.field_control.region_shaping import rotated_ellipse_masks
from hpm_platform.workflows.dynamic_field_control_v07 import METHOD_ORDER, METHOD_PROPOSED
from hpm_platform.workflows.effect_twin_v08 import (
    POLICY_ALWAYS,
    POLICY_EFFECT_AWARE,
    POLICY_ORDER,
    EffectRunOutput,
    _primary_tier,
    _tiers,
)


def _save(fig: plt.Figure, path: Path, dpi: int = 220) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=dpi, bbox_inches="tight")
    plt.close(fig)


def _mechanism_figure() -> plt.Figure:
    fig, ax = plt.subplots(figsize=(17.5, 6.2), constrained_layout=True)
    ax.set_xlim(0.0, 18.0)
    ax.set_ylim(0.0, 6.2)
    ax.axis("off")
    stages = [
        (0.25, "Dynamic field map", "Complex field on a\nnormalized control plane"),
        (3.1, "Dual reference frames", "Target-attached map\n+ world-fixed map"),
        (5.95, "Leaky accumulation", "Dimensionless dose\nwith relaxation memory"),
        (8.8, "Threshold uncertainty", "Lognormal tiers\n+ coupling spread"),
        (11.65, "Probability maps", "Target response\n+ protected-zone risk"),
        (14.5, "Mission metrics", "Coverage / selectivity\n/ risk / duty"),
    ]
    width, height = 2.3, 2.05
    for x, title, subtitle in stages:
        ax.add_patch(
            FancyBboxPatch(
                (x, 2.2), width, height,
                boxstyle="round,pad=0.08,rounding_size=0.08",
                linewidth=1.5, facecolor="none",
            )
        )
        ax.text(x + width / 2, 3.62, title, ha="center", va="center", fontsize=11, weight="bold")
        ax.text(x + width / 2, 2.78, subtitle, ha="center", va="center", fontsize=9.5)
    for left in [2.6, 5.45, 8.3, 11.15, 14.0]:
        ax.add_patch(FancyArrowPatch((left, 3.22), (left + 0.45, 3.22), arrowstyle="-|>", mutation_scale=15, linewidth=1.3))
    ax.add_patch(
        FancyArrowPatch(
            (15.7, 2.05), (10.0, 1.42), connectionstyle="arc3,rad=-0.2",
            arrowstyle="-|>", mutation_scale=15, linewidth=1.35,
        )
    )
    ax.text(12.8, 0.88, "Optional normalized effect-aware duty feedback", ha="center", fontsize=10)
    ax.text(9.0, 5.35, "V0.8 normalized effect-evaluation digital twin", ha="center", fontsize=14.5, weight="bold")
    ax.text(9.0, 4.88, "No absolute power, range, device threshold, or physical damage claim", ha="center", fontsize=10)
    return fig


def plot_mechanism(output_png: Path, output_svg: Path) -> None:
    _save(_mechanism_figure(), output_png)
    _save(_mechanism_figure(), output_svg)


def _map_figure(
    values: np.ndarray,
    xx: np.ndarray,
    yy: np.ndarray,
    *,
    title: str,
    xlabel: str,
    ylabel: str,
    colorbar_label: str,
    vmin: float | None = None,
    vmax: float | None = None,
    target_mask: np.ndarray | None = None,
    protected_mask: np.ndarray | None = None,
    trajectory: np.ndarray | None = None,
) -> plt.Figure:
    fig, ax = plt.subplots(figsize=(8.5, 6.8), constrained_layout=True)
    mesh = ax.pcolormesh(xx, yy, values, shading="auto", vmin=vmin, vmax=vmax)
    if target_mask is not None:
        ax.contour(xx, yy, np.asarray(target_mask, float), levels=[0.5], linewidths=1.5)
    if protected_mask is not None:
        ax.contour(xx, yy, np.asarray(protected_mask, float), levels=[0.5], linewidths=1.8, linestyles="--")
    if trajectory is not None:
        ax.plot(trajectory[:, 0], trajectory[:, 1], linewidth=1.5, label="Moving-zone center")
        ax.legend(fontsize=9)
    ax.set_aspect("equal")
    ax.set_xlabel(xlabel)
    ax.set_ylabel(ylabel)
    ax.set_title(title)
    fig.colorbar(mesh, ax=ax, label=colorbar_label)
    return fig


def plot_target_map(result: EffectRunOutput, values: np.ndarray, title: str, label: str, output: Path, *, vmin=None, vmax=None) -> None:
    _save(
        _map_figure(
            values,
            result.local_grid.xx_lambda,
            result.local_grid.yy_lambda,
            title=title,
            xlabel="Body-fixed x / wavelength",
            ylabel="Body-fixed y / wavelength",
            colorbar_label=label,
            vmin=vmin,
            vmax=vmax,
            target_mask=result.local_grid.target_mask,
        ),
        output,
    )


def plot_world_map(result: EffectRunOutput, values: np.ndarray, title: str, label: str, output: Path, *, vmin=None, vmax=None) -> None:
    _save(
        _map_figure(
            values,
            result.grid.xx_lambda,
            result.grid.yy_lambda,
            title=title,
            xlabel="x / wavelength",
            ylabel="y / wavelength",
            colorbar_label=label,
            vmin=vmin,
            vmax=vmax,
            protected_mask=result.protected_mask,
            trajectory=result.exposure.true_centers_lambda,
        ),
        output,
    )


def _rows(records: Sequence[Mapping[str, Any]], key: str, value: str, tier: str | None = None) -> list[Mapping[str, Any]]:
    selected = [row for row in records if row[key] == value and (tier is None or row["tier"] == tier)]
    return sorted(selected, key=lambda row: int(row["frame"]))


def plot_method_timeline(result: EffectRunOutput, tier: str, value_key: str, ylabel: str, title: str, output: Path, reference: float | None = None) -> None:
    fig, ax = plt.subplots(figsize=(9.6, 5.8), constrained_layout=True)
    for method in METHOD_ORDER:
        selected = _rows(result.method_records, "method", method, tier)
        ax.plot([row["frame"] for row in selected], [row[value_key] for row in selected], linewidth=1.65, label=method)
    if reference is not None:
        ax.axhline(reference, linestyle="--", linewidth=1.2, label="Criterion")
    ax.set_xlabel("Frame")
    ax.set_ylabel(ylabel)
    ax.set_title(title)
    ax.grid(True, alpha=0.3)
    ax.legend(ncol=2, fontsize=8.8)
    _save(fig, output)


def plot_policy_timeline(result: EffectRunOutput, value_key: str, ylabel: str, title: str, output: Path, reference: float | None = None) -> None:
    fig, ax = plt.subplots(figsize=(9.6, 5.8), constrained_layout=True)
    for policy in POLICY_ORDER:
        selected = _rows(result.policy_records, "policy", policy)
        ax.plot([row["frame"] for row in selected], [row[value_key] for row in selected], linewidth=1.75, label=policy)
    if reference is not None:
        ax.axhline(reference, linestyle="--", linewidth=1.2, label="Criterion")
    ax.set_xlabel("Frame")
    ax.set_ylabel(ylabel)
    ax.set_title(title)
    ax.grid(True, alpha=0.3)
    ax.legend(fontsize=8.8)
    _save(fig, output)


def plot_success_heatmap(result: EffectRunOutput, tier: str, output: Path) -> None:
    matrix = np.asarray(
        [[float(row["mission_success"]) for row in _rows(result.method_records, "method", method, tier)] for method in METHOD_ORDER]
    )
    fig, ax = plt.subplots(figsize=(10.0, 4.7), constrained_layout=True)
    mesh = ax.imshow(matrix, aspect="auto", interpolation="nearest", vmin=0.0, vmax=1.0)
    ax.set_yticks(np.arange(len(METHOD_ORDER)), METHOD_ORDER)
    ax.set_xlabel("Frame")
    ax.set_title("Normalized mission-criterion availability (1 = all criteria met)")
    fig.colorbar(mesh, ax=ax, ticks=[0, 1])
    _save(fig, output)


def plot_final_tier_bars(result: EffectRunOutput, tiers: Sequence[EffectTier], output: Path) -> None:
    x = np.arange(len(METHOD_ORDER))
    width = 0.24
    fig, ax = plt.subplots(figsize=(10.2, 5.9), constrained_layout=True)
    for index, tier in enumerate(tiers):
        values = []
        for method in METHOD_ORDER:
            row = next(r for r in result.method_summary if r["method"] == method and r["tier"] == tier.name)
            values.append(float(row["final_target_probability"]))
        ax.bar(x + (index - (len(tiers)-1)/2) * width, values, width=width, label=tier.name)
    ax.set_xticks(x, METHOD_ORDER, rotation=18, ha="right")
    ax.set_ylim(0.0, 1.0)
    ax.set_ylabel("Final target-attached mean probability")
    ax.set_title("Final response probability across normalized threshold tiers")
    ax.grid(True, axis="y", alpha=0.3)
    ax.legend(fontsize=8.5)
    _save(fig, output)


def plot_risk_utility(result: EffectRunOutput, primary: str, output: Path) -> None:
    rows = [row for row in result.method_summary if row["tier"] == primary]
    fig, ax = plt.subplots(figsize=(8.4, 6.2), constrained_layout=True)
    for row in rows:
        ax.scatter(float(row["mean_protected_p95_probability"]), float(row["mean_target_probability"]), s=65)
        ax.annotate(row["method"], (float(row["mean_protected_p95_probability"]), float(row["mean_target_probability"])), xytext=(5, 4), textcoords="offset points", fontsize=8.8)
    ax.set_xlabel("Mean protected-zone P95 probability")
    ax.set_ylabel("Mean target response probability")
    ax.set_title("Target utility versus protected-zone risk")
    ax.grid(True, alpha=0.3)
    _save(fig, output)


def plot_policy_bars(result: EffectRunOutput, key: str, ylabel: str, title: str, output: Path) -> None:
    rows = [next(row for row in result.policy_summary if row["policy"] == policy) for policy in POLICY_ORDER]
    fig, ax = plt.subplots(figsize=(9.1, 5.7), constrained_layout=True)
    ax.bar(np.arange(len(rows)), [float(row[key]) for row in rows])
    ax.set_xticks(np.arange(len(rows)), [row["policy"] for row in rows], rotation=16, ha="right")
    ax.set_ylabel(ylabel)
    ax.set_title(title)
    ax.grid(True, axis="y", alpha=0.3)
    _save(fig, output)


def plot_sweep(result: EffectRunOutput, sweep: str, key: str, xlabel: str, ylabel: str, title: str, output: Path) -> None:
    fig, ax = plt.subplots(figsize=(9.4, 5.8), constrained_layout=True)
    for method in METHOD_ORDER:
        selected = sorted((row for row in result.sweep_summary if row["sweep"] == sweep and row["method"] == method), key=lambda row: float(row["x_value"]))
        x = np.asarray([float(row["x_value"]) for row in selected])
        mean = np.asarray([float(row[f"{key}_mean"]) for row in selected])
        low = np.asarray([float(row[f"{key}_ci_low"]) for row in selected])
        high = np.asarray([float(row[f"{key}_ci_high"]) for row in selected])
        ax.plot(x, mean, marker="o", linewidth=1.55, label=method)
        ax.fill_between(x, low, high, alpha=0.12)
    ax.set_xlabel(xlabel)
    ax.set_ylabel(ylabel)
    ax.set_title(title)
    ax.grid(True, alpha=0.3)
    ax.legend(ncol=2, fontsize=8.5)
    _save(fig, output)


def plot_transfer_curves(tiers: Sequence[EffectTier], coupling_sigma: float, output: Path) -> None:
    dose = np.geomspace(0.03, 3.0, 300)
    fig, ax = plt.subplots(figsize=(8.8, 5.9), constrained_layout=True)
    for tier in tiers:
        ax.semilogx(dose, lognormal_response_probability(dose, tier, coupling_log_sigma=coupling_sigma), linewidth=1.8, label=tier.name)
        ax.axvline(tier.threshold_median, linestyle=":", linewidth=0.9)
    ax.set_xlabel("Normalized cumulative dose")
    ax.set_ylabel("Response probability")
    ax.set_ylim(0.0, 1.0)
    ax.set_title("Dimensionless probability-transfer curves")
    ax.grid(True, which="both", alpha=0.3)
    ax.legend(fontsize=8.8)
    _save(fig, output)


def plot_mc_histogram(result: EffectRunOutput, output: Path) -> None:
    rows = [row for row in result.sweep_rows if row["sweep"] == "threshold_median_scale" and abs(float(row["x_value"]) - 0.9) < 1e-9]
    fig, ax = plt.subplots(figsize=(8.8, 5.6), constrained_layout=True)
    for method in [METHOD_ORDER[-2], METHOD_PROPOSED]:
        values = [float(row["mean_target_probability"]) for row in rows if row["method"] == method]
        ax.hist(values, bins=max(5, len(values)//2), alpha=0.55, label=method)
    ax.set_xlabel("Trial mean target probability")
    ax.set_ylabel("Count")
    ax.set_title("Effect-model uncertainty distribution near the nominal threshold scale")
    ax.legend()
    ax.grid(True, alpha=0.25)
    _save(fig, output)


def _gif_frame(probability: np.ndarray, result: EffectRunOutput, frame: int) -> Image.Image:
    fig, ax = plt.subplots(figsize=(6.2, 5.0), constrained_layout=True)
    mesh = ax.pcolormesh(result.local_grid.xx_lambda, result.local_grid.yy_lambda, probability, shading="auto", vmin=0.0, vmax=1.0)
    ax.contour(result.local_grid.xx_lambda, result.local_grid.yy_lambda, result.local_grid.target_mask.astype(float), levels=[0.5], linewidths=1.3)
    ax.set_aspect("equal")
    ax.set_xlabel("Body-fixed x / wavelength")
    ax.set_ylabel("Body-fixed y / wavelength")
    ax.set_title(f"EA-Duty target-attached probability | frame {frame}")
    fig.colorbar(mesh, ax=ax, label="Response probability")
    buffer = io.BytesIO()
    fig.savefig(buffer, format="png", dpi=110, bbox_inches="tight")
    plt.close(fig)
    buffer.seek(0)
    return Image.open(buffer).convert("P", palette=Image.Palette.ADAPTIVE)


def create_dynamic_gif(result: EffectRunOutput, output: Path) -> None:
    frames = []
    n_frames = result.exposure.true_centers_lambda.shape[0]
    for frame in range(n_frames):
        key = f"target_probability__{POLICY_EFFECT_AWARE}__frame_{frame:03d}"
        frames.append(_gif_frame(result.policy_snapshot_maps[key], result, frame))
    frames[0].save(output, save_all=True, append_images=frames[1:], duration=180, loop=0, optimize=True)


def _manifest_entry(path: Path, title: str, description: str) -> dict[str, str]:
    return {"file": path.name, "title": title, "description": description}


def generate_all_figures(output_dir: Path, config: Mapping[str, Any], result: EffectRunOutput) -> list[dict[str, str]]:
    output = Path(output_dir)
    tiers = _tiers(config)
    primary = _primary_tier(config, tiers)
    manifest: list[dict[str, str]] = []

    def add(name: str, title: str, description: str) -> Path:
        path = output / name
        manifest.append(_manifest_entry(path, title, description))
        return path

    mechanism_png = add("00_effect_twin_mechanism.png", "V0.8 mechanism", "Dual-frame accumulation, threshold uncertainty, probability maps, and mission feedback.")
    mechanism_svg = output / "00_effect_twin_mechanism.svg"
    plot_mechanism(mechanism_png, mechanism_svg)

    target_dose = result.final_maps[f"target_dose__{METHOD_PROPOSED}"]
    world_dose = result.final_maps[f"world_dose__{METHOD_PROPOSED}"]
    target_p = result.final_maps[f"target_probability__{METHOD_PROPOSED}__{primary.name}"]
    world_p = result.final_maps[f"world_probability__{METHOD_PROPOSED}__{primary.name}"]
    plot_target_map(result, target_dose, "PCF-RLS final target-attached cumulative dose", "Normalized dose", add("01_target_attached_dose.png", "Target-attached dose", "Cumulative exposure carried with the moving target."))
    plot_target_map(result, target_p, f"PCF-RLS final target probability: {primary.name}", "Response probability", add("02_target_attached_probability.png", "Target response probability", "Final probability map in the target body frame."), vmin=0.0, vmax=1.0)
    plot_world_map(result, world_dose, "PCF-RLS final world-fixed cumulative dose", "Normalized dose", add("03_world_fixed_dose.png", "World-fixed dose", "Accumulated spatial exposure with target trajectory and protected zone."))
    plot_world_map(result, world_p, f"PCF-RLS final world-fixed risk: {primary.name}", "Response probability", add("04_world_fixed_probability.png", "World risk map", "World-fixed probability map; dashed contour is the protected zone."), vmin=0.0, vmax=1.0)
    plot_target_map(result, result.uncertainty_maps["target_width"], "Target probability interval width", "95% interval width", add("05_target_uncertainty_width.png", "Target uncertainty width", "Epistemic threshold uncertainty propagated to target probability."), vmin=0.0, vmax=1.0)
    plot_world_map(result, result.uncertainty_maps["world_width"], "World probability interval width", "95% interval width", add("06_world_uncertainty_width.png", "World uncertainty width", "Where threshold uncertainty most strongly affects risk interpretation."), vmin=0.0, vmax=1.0)

    plot_method_timeline(result, primary.name, "target_mean_probability", "Mean target probability", "Target-attached response probability versus frame", add("07_method_target_probability_timeline.png", "Target probability timeline", "Dynamic target response for all field controllers."), reference=primary.probability_goal)
    plot_method_timeline(result, primary.name, "target_coverage", "Target coverage", "Target-zone probability coverage versus frame", add("08_method_target_coverage_timeline.png", "Target coverage timeline", "Fraction of the target zone above the tier coverage probability."), reference=float(config["effect_success"]["minimum_target_coverage"]))
    plot_method_timeline(result, primary.name, "protected_p95_probability", "Protected-zone P95 probability", "Protected-zone risk versus frame", add("09_method_protected_risk_timeline.png", "Protected risk timeline", "P95 risk in the fixed protected zone."), reference=float(config["effect_success"]["maximum_protected_p95_probability"]))
    plot_method_timeline(result, primary.name, "off_target_high_risk_fraction", "Off-target high-risk area fraction", "Off-target risk-area fraction versus frame", add("10_method_off_target_risk_timeline.png", "Off-target risk timeline", "Fraction of off-target samples above the high-risk probability."), reference=float(config["effect_success"]["maximum_off_target_high_risk_fraction"]))
    plot_success_heatmap(result, primary.name, add("11_method_success_heatmap.png", "Mission availability", "Frame-wise satisfaction of target and non-target criteria."))
    plot_final_tier_bars(result, tiers, add("12_final_tier_probabilities.png", "Tier probabilities", "Final target response across three normalized threshold tiers."))
    plot_risk_utility(result, primary.name, add("13_risk_utility_scatter.png", "Risk–utility trade-off", "Target response versus protected-zone risk."))

    plot_policy_timeline(result, "duty_factor", "Normalized duty", "Effect-aware exposure allocation", add("14_policy_duty_timeline.png", "Duty timeline", "Abstract normalized exposure allocation; not a hardware pulse command."))
    plot_policy_timeline(result, "target_mean_probability", "Mean target probability", "Policy target response versus frame", add("15_policy_target_probability.png", "Policy target response", "Always-on, target-stop, and effect-aware allocation."), reference=primary.probability_goal)
    plot_policy_timeline(result, "protected_p95_probability", "Protected-zone P95 probability", "Policy protected-zone risk versus frame", add("16_policy_protected_risk.png", "Policy protected risk", "Risk reduction achieved by normalized exposure allocation."), reference=float(config["effect_success"]["maximum_protected_p95_probability"]))
    plot_policy_bars(result, "cumulative_duty", "Cumulative normalized duty", "Total normalized exposure allocation", add("17_policy_cumulative_duty.png", "Cumulative duty", "Relative exposure allocation across policies."))
    plot_policy_bars(result, "risk_adjusted_utility", "Risk-adjusted utility", "Target utility after protected/off-target risk penalties", add("18_policy_risk_adjusted_utility.png", "Risk-adjusted utility", "Single summary metric used only for algorithm comparison."))

    plot_sweep(result, "threshold_median_scale", "mean_target_probability", "Threshold median scale", "Mean target probability", "Threshold uncertainty sensitivity", add("19_sweep_threshold_scale.png", "Threshold sensitivity", "Monte Carlo sensitivity to the normalized tier median."))
    plot_sweep(result, "retention", "mean_target_probability", "Retention factor", "Mean target probability", "Accumulation-memory sensitivity", add("20_sweep_retention.png", "Retention sensitivity", "Effect of normalized relaxation memory."))
    plot_sweep(result, "coupling_log_sigma", "mean_target_probability", "Coupling log-sigma", "Mean target probability", "Coupling-uncertainty sensitivity", add("21_sweep_coupling_sigma.png", "Coupling sensitivity", "Effect of multiplicative coupling spread."))
    plot_sweep(result, "pulse_weight", "mean_target_probability", "Normalized pulse weight", "Mean target probability", "Exposure-allocation sensitivity", add("22_sweep_pulse_weight.png", "Exposure sensitivity", "Sensitivity to the dimensionless per-frame exposure weight."))
    plot_transfer_curves(tiers, float(config["effect_twin"]["coupling_log_sigma"]), add("23_probability_transfer_curves.png", "Probability transfer curves", "Dimensionless dose-to-probability maps for all tiers."))
    plot_mc_histogram(result, add("24_mc_probability_histogram.png", "Monte Carlo distribution", "Trial distribution near the nominal threshold scale."))

    for number, frame in enumerate(config["representative_effect"]["snapshot_frames"], start=25):
        key = f"target_probability__{POLICY_EFFECT_AWARE}__frame_{int(frame):03d}"
        plot_target_map(result, result.policy_snapshot_maps[key], f"EA-Duty target probability at frame {frame}", "Response probability", add(f"{number:02d}_ea_duty_probability_frame_{int(frame):03d}.png", f"EA-Duty frame {frame}", "Target-attached probability snapshot."), vmin=0.0, vmax=1.0)

    gif_path = add("29_ea_duty_dynamic_probability.gif", "Dynamic response GIF", "Target-attached probability evolution under effect-aware allocation.")
    create_dynamic_gif(result, gif_path)
    return manifest


def _table(rows: Sequence[Mapping[str, Any]], columns: Sequence[tuple[str, str, str]]) -> str:
    head = "".join(f"<th>{html.escape(label)}</th>" for _, label, _ in columns)
    body = []
    for row in rows:
        cells = []
        for key, _, fmt in columns:
            value = row[key]
            if fmt == "s": text = str(value)
            elif fmt == "%": text = f"{100*float(value):.1f}%"
            elif fmt == "f3": text = f"{float(value):.3f}"
            elif fmt == "f2": text = f"{float(value):.2f}"
            else: text = str(value)
            cells.append(f"<td>{html.escape(text)}</td>")
        body.append("<tr>" + "".join(cells) + "</tr>")
    return f"<table><thead><tr>{head}</tr></thead><tbody>{''.join(body)}</tbody></table>"


def _data_uri(path: Path) -> str:
    mime = "image/gif" if path.suffix.lower() == ".gif" else "image/png"
    return f"data:{mime};base64,{base64.b64encode(path.read_bytes()).decode('ascii')}"


def _report_html(output: Path, config: Mapping[str, Any], result: EffectRunOutput, metrics: Mapping[str, Any], manifest: Sequence[Mapping[str, str]], standalone: bool) -> str:
    primary = _primary_tier(config, _tiers(config))
    method_rows = [row for row in result.method_summary if row["tier"] == primary.name]
    method_table = _table(method_rows, [
        ("method", "Method", "s"), ("mean_target_probability", "Mean target P", "f3"),
        ("mean_target_coverage", "Coverage", "%"), ("mean_protected_p95_probability", "Protected P95", "f3"),
        ("mission_success_rate", "Availability", "%"), ("risk_adjusted_utility", "Risk utility", "f3"),
    ])
    policy_table = _table(result.policy_summary, [
        ("policy", "Policy", "s"), ("mean_target_probability", "Mean target P", "f3"),
        ("mean_protected_p95_probability", "Protected P95", "f3"), ("mission_success_rate", "Availability", "%"),
        ("cumulative_duty", "Duty", "f2"), ("risk_adjusted_utility", "Risk utility", "f3"),
    ])
    cards = []
    for item in manifest:
        path = output / item["file"]
        src = _data_uri(path) if standalone else item["file"]
        cards.append(
            f"<section class='figure'><h3>{html.escape(item['title'])}</h3>"
            f"<p>{html.escape(item['description'])}</p><img src='{src}' alt='{html.escape(item['title'])}'></section>"
        )
    proposed = next(row for row in method_rows if row["method"] == METHOD_PROPOSED)
    always = next(row for row in result.policy_summary if row["policy"] == POLICY_ALWAYS)
    adaptive = next(row for row in result.policy_summary if row["policy"] == POLICY_EFFECT_AWARE)
    duty_saving = 100.0 * (1.0 - float(adaptive["cumulative_duty"]) / float(always["cumulative_duty"]))
    comparison = result.paired_statistics["comparisons"].get(METHOD_ORDER[-2], {})
    return f"""<!doctype html><html><head><meta charset='utf-8'><title>HPM Digital Twin V0.8</title>
<style>
body{{font-family:Arial,Helvetica,sans-serif;max-width:1180px;margin:0 auto;padding:28px;line-height:1.55;color:#20242a}}
h1,h2,h3{{line-height:1.25}} .notice{{border:1px solid #777;padding:14px;border-radius:8px;background:#f7f7f7}}
.metric-grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(190px,1fr));gap:12px;margin:18px 0}}
.metric{{border:1px solid #bbb;border-radius:8px;padding:12px}} .metric b{{display:block;font-size:1.35rem}}
table{{border-collapse:collapse;width:100%;margin:12px 0 24px}} th,td{{border:1px solid #bbb;padding:7px;text-align:right}} th:first-child,td:first-child{{text-align:left}}
.figure{{margin:28px 0;border-top:1px solid #ddd;padding-top:18px}} .figure img{{max-width:100%;height:auto;border:1px solid #ddd}}
code{{background:#eee;padding:2px 5px}} .small{{font-size:.9rem;color:#555}}
</style></head><body>
<h1>HPM Digital Twin V0.8 — Normalized Effect Evaluation</h1>
<div class='notice'><b>Scope:</b> all field, dose, threshold, duty, and probability quantities are dimensionless. The report does not infer a real source power, standoff distance, component threshold, physical damage probability, or operational outcome.</div>
<h2>What changed</h2><p>V0.8 consumes V0.7 dynamic field maps, accumulates exposure in both a target-attached frame and a world-fixed frame, propagates lognormal threshold and coupling uncertainty, and reports target utility together with protected-zone and off-target risk.</p>
<div class='metric-grid'>
<div class='metric'>PCF-RLS mean target P<b>{float(proposed['mean_target_probability']):.3f}</b></div>
<div class='metric'>PCF-RLS availability<b>{100*float(proposed['mission_success_rate']):.1f}%</b></div>
<div class='metric'>EA-Duty allocation saving<b>{duty_saving:.1f}%</b></div>
<div class='metric'>EA-Duty risk utility<b>{float(adaptive['risk_adjusted_utility']):.3f}</b></div>
</div>
<h2>Primary tier: {html.escape(primary.name)}</h2>{method_table}
<h2>Normalized exposure policies</h2>{policy_table}
<p class='small'>Paired Monte Carlo comparison against {html.escape(METHOD_ORDER[-2])}: target-probability gain {float(comparison.get('mean_target_probability_gain', float('nan'))):.3f}, one-sided Wilcoxon p={float(comparison.get('wilcoxon_one_sided_p', float('nan'))):.4g}. The quick configuration uses only {int(config['monte_carlo_effect']['trials_per_point'])} trials per point and is an engineering acceptance run, not final paper statistics.</p>
<h2>Figures</h2>{''.join(cards)}
<h2>Reproducibility</h2><p>Run <code>python run_effect_twin_v08.py</code>. CSV, NPZ, JSON, LaTeX tables, configuration snapshot, environment metadata, and SHA-256 checksums are included in this output directory.</p>
</body></html>"""


def write_reports(output_dir: Path, config: Mapping[str, Any], result: EffectRunOutput, metrics: Mapping[str, Any], manifest: Sequence[Mapping[str, str]]) -> None:
    output = Path(output_dir)
    (output / "effect_twin_v08_report.html").write_text(_report_html(output, config, result, metrics, manifest, False), encoding="utf-8")
    (output / "effect_twin_v08_report_standalone.html").write_text(_report_html(output, config, result, metrics, manifest, True), encoding="utf-8")
    primary = _primary_tier(config, _tiers(config))
    proposed = next(row for row in result.method_summary if row["method"] == METHOD_PROPOSED and row["tier"] == primary.name)
    adaptive = next(row for row in result.policy_summary if row["policy"] == POLICY_EFFECT_AWARE)
    always = next(row for row in result.policy_summary if row["policy"] == POLICY_ALWAYS)
    saving = 100.0 * (1.0 - float(adaptive["cumulative_duty"]) / float(always["cumulative_duty"]))
    findings = f"""# V0.8 key findings\n\n- Primary normalized tier: **{primary.name}**.\n- PCF-RLS mean target probability: **{float(proposed['mean_target_probability']):.3f}**; mission-criterion availability: **{100*float(proposed['mission_success_rate']):.1f}%**.\n- EA-Duty reduces cumulative normalized allocation by **{saving:.1f}%**, lowers mean protected-zone P95 probability from **{float(always['mean_protected_p95_probability']):.3f}** to **{float(adaptive['mean_protected_p95_probability']):.3f}**, and changes risk-adjusted utility from **{float(always['risk_adjusted_utility']):.3f}** to **{float(adaptive['risk_adjusted_utility']):.3f}**.\n- The target-attached/world-fixed split is essential: it avoids accumulating a moving target's history on a stationary spatial grid.\n- All results are dimensionless and uncalibrated; they support numerical-method comparison only.\n"""
    (output / "KEY_FINDINGS.md").write_text(findings, encoding="utf-8")
    (output / "README.md").write_text(
        "# V0.8 outputs\n\nOpen `effect_twin_v08_report_standalone.html` for the complete self-contained report. Run `python run_effect_twin_v08.py` from the project root to reproduce the quick configuration.\n",
        encoding="utf-8",
    )

"""V0.2 coherent-multipath perception study and Monte Carlo workflow."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
import base64
import csv
import json
import platform
import sys
import time
from typing import Any

import matplotlib
import numpy as np
import scipy
import yaml

from hpm_platform.evaluation.doa_statistics import (
    match_directions,
    mean_confidence_interval,
    wilson_interval,
)
from hpm_platform.perception.music import MusicGridScanner, sample_covariance
from hpm_platform.perception.spatial_smoothing import spatially_smoothed_covariance
from hpm_platform.physics.array_geometry import C0, RectangularArray
from hpm_platform.signal.sources import Source, simulate_snapshots
from hpm_platform.signal.multipath import (
    CoherentEmitter,
    CoherentPath,
    draw_sensor_gain_phase_errors,
    simulate_coherent_multipath,
)
from hpm_platform.visualization.perception_v02 import (
    plot_eigenspectrum,
    plot_error_cdf,
    plot_fbss_mechanism,
    plot_metric_curve,
    plot_music_spectrum,
)


METHOD_STANDARD = "Standard MUSIC"
METHOD_FBSS = "FBSS-MUSIC"


@dataclass(frozen=True)
class RepresentativeMetrics:
    standard_rmse_deg: float
    fbss_rmse_deg: float
    standard_max_error_deg: float
    fbss_max_error_deg: float
    standard_rank2_above_noise_db: float
    fbss_rank2_above_noise_db: float
    standard_direct_theta_deg: float
    standard_direct_phi_deg: float
    standard_echo_theta_deg: float
    standard_echo_phi_deg: float
    fbss_direct_theta_deg: float
    fbss_direct_phi_deg: float
    fbss_echo_theta_deg: float
    fbss_echo_phi_deg: float
    incoherent_control_rmse_deg: float
    incoherent_control_rank2_above_noise_db: float
    incoherent_control_direct_theta_deg: float
    incoherent_control_direct_phi_deg: float
    incoherent_control_echo_theta_deg: float
    incoherent_control_echo_phi_deg: float


def _array_from_config(config: dict[str, Any]) -> RectangularArray:
    cfg = config["array"]
    frequency = float(cfg["frequency_hz"])
    wavelength = C0 / frequency
    spacing = float(cfg["spacing_lambda"]) * wavelength
    return RectangularArray(
        nx=int(cfg["nx"]),
        ny=int(cfg["ny"]),
        frequency_hz=frequency,
        dx_m=spacing,
        dy_m=spacing,
    )


def _truths_from_config(config: dict[str, Any]) -> tuple[tuple[float, float], tuple[float, float]]:
    direct = config["scenario"]["direct_path"]
    echo = config["scenario"]["coherent_echo"]
    return (
        (float(direct["theta_deg"]), float(direct["phi_deg"])),
        (float(echo["theta_deg"]), float(echo["phi_deg"])),
    )


def _emitter_from_config(config: dict[str, Any], snr_db: float) -> CoherentEmitter:
    direct = config["scenario"]["direct_path"]
    echo = config["scenario"]["coherent_echo"]
    return CoherentEmitter(
        reference_power_db=float(snr_db),
        paths=(
            CoherentPath(
                theta_deg=float(direct["theta_deg"]),
                phi_deg=float(direct["phi_deg"]),
                relative_power_db=float(direct["relative_power_db"]),
                phase_deg=float(direct["phase_deg"]),
                label="direct",
            ),
            CoherentPath(
                theta_deg=float(echo["theta_deg"]),
                phi_deg=float(echo["phi_deg"]),
                relative_power_db=float(echo["relative_power_db"]),
                phase_deg=float(echo["phase_deg"]),
                label="coherent_echo",
            ),
        ),
        label="source_1",
    )


def _scan_grids(config: dict[str, Any]) -> tuple[np.ndarray, np.ndarray]:
    scan = config["scan"]
    theta = np.arange(
        float(scan["theta_min_deg"]),
        float(scan["theta_max_deg"]) + 0.5 * float(scan["theta_step_deg"]),
        float(scan["theta_step_deg"]),
    )
    phi = np.arange(
        float(scan["phi_min_deg"]),
        float(scan["phi_max_deg"]) + 0.5 * float(scan["phi_step_deg"]),
        float(scan["phi_step_deg"]),
    )
    return theta, phi


def _rank2_above_noise_db(eigenvalues: np.ndarray, n_sources: int = 2) -> float:
    values = np.maximum(np.asarray(eigenvalues, float), np.finfo(float).tiny)
    if values.size <= n_sources:
        return float("nan")
    noise_floor = float(np.median(values[n_sources:]))
    return float(10.0 * np.log10(values[1] / max(noise_floor, np.finfo(float).tiny)))


def _estimate_both(
    x: np.ndarray,
    array: RectangularArray,
    standard_scanner: MusicGridScanner,
    fbss_scanner: MusicGridScanner,
    config: dict[str, Any],
):
    smooth_cfg = config["spatial_smoothing"]
    scan_cfg = config["scan"]
    kwargs = {
        "diagonal_loading": float(smooth_cfg["diagonal_loading"]),
        "n_peaks": 2,
        "min_separation_deg": float(scan_cfg["min_peak_separation_deg"]),
    }
    standard = standard_scanner.scan_covariance(sample_covariance(x), 2, **kwargs)
    smooth = spatially_smoothed_covariance(
        x,
        array,
        int(smooth_cfg["subarray_nx"]),
        int(smooth_cfg["subarray_ny"]),
        forward_backward=bool(smooth_cfg["forward_backward"]),
        diagonal_loading=0.0,
    )
    fbss = fbss_scanner.scan_covariance(smooth.covariance, 2, **kwargs)
    return standard, fbss, smooth


def _trial_records(
    *,
    x: np.ndarray,
    array: RectangularArray,
    standard_scanner: MusicGridScanner,
    fbss_scanner: MusicGridScanner,
    truths: tuple[tuple[float, float], tuple[float, float]],
    config: dict[str, Any],
    sweep: str,
    x_value: float,
    trial: int,
    tolerance_deg: float,
) -> list[dict[str, float | int | str]]:
    standard, fbss, _ = _estimate_both(
        x, array, standard_scanner, fbss_scanner, config
    )
    output: list[dict[str, float | int | str]] = []
    for method, result in [(METHOD_STANDARD, standard), (METHOD_FBSS, fbss)]:
        estimates = [(peak[0], peak[1]) for peak in result.peaks]
        match = match_directions(estimates, truths)
        ordered = match.ordered_estimates
        output.append(
            {
                "sweep": sweep,
                "x_value": float(x_value),
                "method": method,
                "trial": int(trial),
                "rmse_deg": match.rmse_deg,
                "max_error_deg": match.max_error_deg,
                "resolved": int(match.max_error_deg <= tolerance_deg),
                "direct_error_deg": float(match.errors_deg[0]),
                "echo_error_deg": float(match.errors_deg[1]),
                "direct_est_theta_deg": float(ordered[0][0]),
                "direct_est_phi_deg": float(ordered[0][1]),
                "echo_est_theta_deg": float(ordered[1][0]),
                "echo_est_phi_deg": float(ordered[1][1]),
            }
        )
    return output


def _simulate_trial(
    *,
    array: RectangularArray,
    config: dict[str, Any],
    snr_db: float,
    snapshots: int,
    seed: int,
    gain_std_db: float = 0.0,
    phase_std_deg: float = 0.0,
) -> np.ndarray:
    rng = np.random.default_rng(seed)
    gains = draw_sensor_gain_phase_errors(
        array.n_elements,
        rng,
        gain_std_db=float(gain_std_db),
        phase_std_deg=float(phase_std_deg),
    )
    signal_seed = int(rng.integers(0, np.iinfo(np.int32).max))
    x, _ = simulate_coherent_multipath(
        array,
        [_emitter_from_config(config, snr_db)],
        n_snapshots=int(snapshots),
        noise_power=1.0,
        seed=signal_seed,
        sensor_gains=gains,
    )
    return x


def _summarize_records(
    records: list[dict[str, float | int | str]], confidence: float
) -> list[dict[str, float | int | str]]:
    keys = sorted(
        {(str(row["sweep"]), float(row["x_value"]), str(row["method"])) for row in records}
    )
    summary: list[dict[str, float | int | str]] = []
    for sweep, x_value, method in keys:
        group = [
            row
            for row in records
            if row["sweep"] == sweep
            and float(row["x_value"]) == x_value
            and row["method"] == method
        ]
        rmse = np.asarray([float(row["rmse_deg"]) for row in group])
        max_error = np.asarray([float(row["max_error_deg"]) for row in group])
        resolved = int(sum(int(row["resolved"]) for row in group))
        mean, low, high = mean_confidence_interval(rmse, confidence=confidence)
        rate, rate_low, rate_high = wilson_interval(
            resolved, len(group), confidence=confidence
        )
        summary.append(
            {
                "sweep": sweep,
                "x_value": x_value,
                "method": method,
                "n_trials": len(group),
                "mean_rmse_deg": mean,
                "rmse_ci_low_deg": max(0.0, low),
                "rmse_ci_high_deg": high,
                "median_rmse_deg": float(np.median(rmse)),
                "mean_max_error_deg": float(np.mean(max_error)),
                "resolution_rate": rate,
                "resolution_ci_low": rate_low,
                "resolution_ci_high": rate_high,
            }
        )
    return summary


def _write_dict_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        raise ValueError("Cannot write an empty CSV")
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def _select_summary(
    summary: list[dict[str, Any]], sweep: str, x_value: float, method: str
) -> dict[str, Any]:
    return next(
        row
        for row in summary
        if row["sweep"] == sweep
        and np.isclose(float(row["x_value"]), float(x_value))
        and row["method"] == method
    )


def _flatten(prefix: str, value: Any, output: list[tuple[str, str]]) -> None:
    if isinstance(value, dict):
        for key, nested in value.items():
            _flatten(f"{prefix}.{key}" if prefix else str(key), nested, output)
    elif isinstance(value, list):
        output.append((prefix, json.dumps(value, ensure_ascii=False)))
    elif isinstance(value, float):
        output.append((prefix, f"{value:.6g}"))
    else:
        output.append((prefix, str(value)))


def _write_html_report(output_dir: Path, metrics: dict[str, Any]) -> None:
    flattened: list[tuple[str, str]] = []
    _flatten("", metrics, flattened)
    rows = "\n".join(
        f"<tr><td>{key}</td><td>{value}</td></tr>" for key, value in flattened
    )
    images = [
        ("机理：相干多径与前后向空间平滑", "00_fbss_mechanism.png"),
        ("传统 MUSIC 代表性二维谱", "01_standard_music_spectrum.png"),
        ("FBSS-MUSIC 代表性二维谱", "02_fbss_music_spectrum.png"),
        ("非相干双源对照组二维谱", "10_incoherent_control_music_spectrum.png"),
        ("特征值与秩恢复", "03_eigenvalue_rank_restoration.png"),
        ("SNR 扫描：测向 RMSE", "04_rmse_vs_snr.png"),
        ("SNR 扫描：双路径分辨率", "05_resolution_vs_snr.png"),
        ("快拍数扫描：测向 RMSE", "06_rmse_vs_snapshots.png"),
        ("阵列相位失配：测向 RMSE", "07_rmse_vs_phase_error.png"),
        ("阵列相位失配：双路径分辨率", "08_resolution_vs_phase_error.png"),
        ("0 dB 条件下误差经验 CDF", "09_error_cdf_snr0.png"),
    ]
    cards = "\n".join(
        f'<section><h2>{title}</h2><img src="{filename}" alt="{title}"></section>'
        for title, filename in images
    )
    standalone_cards_parts: list[str] = []
    for title, filename in images:
        payload = base64.b64encode((output_dir / filename).read_bytes()).decode("ascii")
        standalone_cards_parts.append(
            f'<section><h2>{title}</h2><img src="data:image/png;base64,{payload}" alt="{title}"></section>'
        )
    standalone_cards = "\n".join(standalone_cards_parts)
    html = f"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><title>HPM Digital Twin v0.2 感知测向报告</title>
<style>
body{{font-family:Arial,"Microsoft YaHei",sans-serif;max-width:1120px;margin:34px auto;padding:0 20px;line-height:1.6}}
h1{{margin-bottom:6px}} .note{{padding:14px;border:1px solid #999;border-radius:8px;background:#fafafa}}
img{{max-width:100%;border:1px solid #bbb;border-radius:8px}} section{{margin:34px 0}}
table{{border-collapse:collapse;width:100%;font-size:14px}} td{{border:1px solid #aaa;padding:7px;word-break:break-word}}
code{{background:#eee;padding:2px 5px;border-radius:4px}}
</style></head><body>
<h1>HPM Digital Twin v0.2 — 相干多径感知测向基线</h1>
<p class="note"><strong>模型边界：</strong>本报告使用归一化窄带阵列快拍与统计误差模型，研究相干多径下的子空间测向。结果不包含真实高功率源预算、具体设备易损参数或作战效能推断。快速配置仅运行有限 Monte Carlo 次数，论文定稿应使用 <code>configs/perception_v02_paper.yaml</code> 复算。</p>
<h2>关键指标</h2><table>{rows}</table>{cards}
</body></html>"""
    (output_dir / "perception_v02_report.html").write_text(html, encoding="utf-8")
    standalone_html = html.replace(cards, standalone_cards)
    (output_dir / "perception_v02_report_standalone.html").write_text(
        standalone_html, encoding="utf-8"
    )


def run(config_path: str | Path, output_dir: str | Path) -> dict[str, Any]:
    start_time = time.perf_counter()
    config_path = Path(config_path)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    progress_path = output_dir / "progress.log"
    progress_path.write_text("start\n", encoding="utf-8")

    def mark(message: str) -> None:
        with progress_path.open("a", encoding="utf-8") as handle:
            handle.write(message + "\n")

    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    array = _array_from_config(config)
    truths = _truths_from_config(config)
    theta_grid, phi_grid = _scan_grids(config)
    smooth_cfg = config["spatial_smoothing"]
    subarray = RectangularArray(
        nx=int(smooth_cfg["subarray_nx"]),
        ny=int(smooth_cfg["subarray_ny"]),
        frequency_hz=array.frequency_hz,
        dx_m=array.dx_m,
        dy_m=array.dy_m,
    )
    standard_scanner = MusicGridScanner(array, theta_grid, phi_grid)
    fbss_scanner = MusicGridScanner(subarray, theta_grid, phi_grid)
    mark("configuration_and_scanners_ready")

    plot_fbss_mechanism(
        output_dir / "00_fbss_mechanism.png",
        output_dir / "00_fbss_mechanism.svg",
    )
    mark("mechanism_figure_done")

    rep_cfg = config["representative_case"]
    rep_x = _simulate_trial(
        array=array,
        config=config,
        snr_db=float(rep_cfg["snr_db"]),
        snapshots=int(rep_cfg["snapshots"]),
        seed=int(config["seed"]),
        gain_std_db=float(rep_cfg["sensor_gain_std_db"]),
        phase_std_deg=float(rep_cfg["sensor_phase_std_deg"]),
    )
    standard_rep, fbss_rep, smooth_rep = _estimate_both(
        rep_x, array, standard_scanner, fbss_scanner, config
    )
    standard_match = match_directions(
        [(p[0], p[1]) for p in standard_rep.peaks], truths
    )
    fbss_match = match_directions([(p[0], p[1]) for p in fbss_rep.peaks], truths)

    # Ablation/control: keep the same directions and powers but give the two
    # arrivals independent waveforms. Standard MUSIC should recover both,
    # demonstrating that the failure above is caused by coherence rather than
    # an implementation defect or insufficient aperture.
    echo_relative_db = float(config["scenario"]["coherent_echo"]["relative_power_db"])
    independent_x, _ = simulate_snapshots(
        array,
        [
            Source(*truths[0], power_db=float(rep_cfg["snr_db"]), label="direct_control"),
            Source(*truths[1], power_db=float(rep_cfg["snr_db"]) + echo_relative_db, label="echo_control"),
        ],
        n_snapshots=int(rep_cfg["snapshots"]),
        noise_power=1.0,
        seed=int(config["seed"]) + 1,
        coherent=False,
    )
    independent_rep = standard_scanner.scan_covariance(
        sample_covariance(independent_x),
        2,
        diagonal_loading=float(smooth_cfg["diagonal_loading"]),
        n_peaks=2,
        min_separation_deg=float(config["scan"]["min_peak_separation_deg"]),
    )
    independent_match = match_directions(
        [(p[0], p[1]) for p in independent_rep.peaks], truths
    )

    plot_music_spectrum(
        theta_grid,
        phi_grid,
        standard_rep.spectrum,
        list(truths),
        list(standard_match.ordered_estimates),
        METHOD_STANDARD,
        output_dir / "01_standard_music_spectrum.png",
    )
    plot_music_spectrum(
        theta_grid,
        phi_grid,
        fbss_rep.spectrum,
        list(truths),
        list(fbss_match.ordered_estimates),
        METHOD_FBSS,
        output_dir / "02_fbss_music_spectrum.png",
    )
    plot_music_spectrum(
        theta_grid,
        phi_grid,
        independent_rep.spectrum,
        list(truths),
        list(independent_match.ordered_estimates),
        "Incoherent two-source control",
        output_dir / "10_incoherent_control_music_spectrum.png",
    )
    plot_eigenspectrum(
        standard_rep.eigenvalues,
        fbss_rep.eigenvalues,
        output_dir / "03_eigenvalue_rank_restoration.png",
        independent=independent_rep.eigenvalues,
    )
    np.savez_compressed(
        output_dir / "representative_case.npz",
        theta_grid_deg=theta_grid,
        phi_grid_deg=phi_grid,
        standard_spectrum=standard_rep.spectrum,
        fbss_spectrum=fbss_rep.spectrum,
        standard_eigenvalues=standard_rep.eigenvalues,
        fbss_eigenvalues=fbss_rep.eigenvalues,
        incoherent_control_spectrum=independent_rep.spectrum,
        incoherent_control_eigenvalues=independent_rep.eigenvalues,
        smoothed_covariance=smooth_rep.covariance,
    )
    mark("representative_case_done")

    rep_metrics = RepresentativeMetrics(
        standard_rmse_deg=standard_match.rmse_deg,
        fbss_rmse_deg=fbss_match.rmse_deg,
        standard_max_error_deg=standard_match.max_error_deg,
        fbss_max_error_deg=fbss_match.max_error_deg,
        standard_rank2_above_noise_db=_rank2_above_noise_db(standard_rep.eigenvalues),
        fbss_rank2_above_noise_db=_rank2_above_noise_db(fbss_rep.eigenvalues),
        standard_direct_theta_deg=standard_match.ordered_estimates[0][0],
        standard_direct_phi_deg=standard_match.ordered_estimates[0][1],
        standard_echo_theta_deg=standard_match.ordered_estimates[1][0],
        standard_echo_phi_deg=standard_match.ordered_estimates[1][1],
        fbss_direct_theta_deg=fbss_match.ordered_estimates[0][0],
        fbss_direct_phi_deg=fbss_match.ordered_estimates[0][1],
        fbss_echo_theta_deg=fbss_match.ordered_estimates[1][0],
        fbss_echo_phi_deg=fbss_match.ordered_estimates[1][1],
        incoherent_control_rmse_deg=independent_match.rmse_deg,
        incoherent_control_rank2_above_noise_db=_rank2_above_noise_db(independent_rep.eigenvalues),
        incoherent_control_direct_theta_deg=independent_match.ordered_estimates[0][0],
        incoherent_control_direct_phi_deg=independent_match.ordered_estimates[0][1],
        incoherent_control_echo_theta_deg=independent_match.ordered_estimates[1][0],
        incoherent_control_echo_phi_deg=independent_match.ordered_estimates[1][1],
    )

    mc = config["monte_carlo"]
    trials = int(mc["trials"])
    tolerance = float(mc["resolution_tolerance_deg"])
    records: list[dict[str, float | int | str]] = []
    base_seed = int(config["seed"])

    # SNR sweep.
    for point_index, snr_db in enumerate(mc["snr_sweep_db"]):
        for trial in range(trials):
            seed = base_seed + 100_000 + point_index * 10_000 + trial
            x = _simulate_trial(
                array=array,
                config=config,
                snr_db=float(snr_db),
                snapshots=int(mc["snapshots_for_snr_sweep"]),
                seed=seed,
            )
            records.extend(
                _trial_records(
                    x=x,
                    array=array,
                    standard_scanner=standard_scanner,
                    fbss_scanner=fbss_scanner,
                    truths=truths,
                    config=config,
                    sweep="snr_db",
                    x_value=float(snr_db),
                    trial=trial,
                    tolerance_deg=tolerance,
                )
            )
        mark(f"snr_point_done:{snr_db}")

    # Snapshot sweep.
    for point_index, snapshots in enumerate(mc["snapshot_sweep"]):
        for trial in range(trials):
            seed = base_seed + 300_000 + point_index * 10_000 + trial
            x = _simulate_trial(
                array=array,
                config=config,
                snr_db=float(mc["snr_db_for_snapshot_sweep"]),
                snapshots=int(snapshots),
                seed=seed,
            )
            records.extend(
                _trial_records(
                    x=x,
                    array=array,
                    standard_scanner=standard_scanner,
                    fbss_scanner=fbss_scanner,
                    truths=truths,
                    config=config,
                    sweep="snapshots",
                    x_value=float(snapshots),
                    trial=trial,
                    tolerance_deg=tolerance,
                )
            )
        mark(f"snapshot_point_done:{snapshots}")

    # Calibration mismatch sweep.
    for point_index, phase_std in enumerate(mc["phase_error_sweep_deg"]):
        for trial in range(trials):
            seed = base_seed + 500_000 + point_index * 10_000 + trial
            x = _simulate_trial(
                array=array,
                config=config,
                snr_db=float(mc["snr_db_for_mismatch_sweep"]),
                snapshots=int(mc["snapshots_for_mismatch_sweep"]),
                seed=seed,
                gain_std_db=float(mc["gain_error_std_db"]),
                phase_std_deg=float(phase_std),
            )
            records.extend(
                _trial_records(
                    x=x,
                    array=array,
                    standard_scanner=standard_scanner,
                    fbss_scanner=fbss_scanner,
                    truths=truths,
                    config=config,
                    sweep="phase_error_std_deg",
                    x_value=float(phase_std),
                    trial=trial,
                    tolerance_deg=tolerance,
                )
            )
        mark(f"phase_error_point_done:{phase_std}")

    summary = _summarize_records(records, confidence=float(mc["confidence"]))
    _write_dict_csv(output_dir / "monte_carlo_trials.csv", records)
    _write_dict_csv(output_dir / "monte_carlo_summary.csv", summary)
    mark("monte_carlo_tables_done")

    snr_summary = [row for row in summary if row["sweep"] == "snr_db"]
    snapshot_summary = [row for row in summary if row["sweep"] == "snapshots"]
    mismatch_summary = [
        row for row in summary if row["sweep"] == "phase_error_std_deg"
    ]
    plot_metric_curve(
        snr_summary,
        "x_value",
        "mean_rmse_deg",
        "rmse_ci_low_deg",
        "rmse_ci_high_deg",
        "Reference-path SNR (dB)",
        "Mean matched-path RMSE (deg)",
        "Coherent multipath DOA error versus SNR (95% CI)",
        output_dir / "04_rmse_vs_snr.png",
    )
    plot_metric_curve(
        snr_summary,
        "x_value",
        "resolution_rate",
        "resolution_ci_low",
        "resolution_ci_high",
        "Reference-path SNR (dB)",
        "Two-path resolution probability",
        f"Resolution probability versus SNR (error <= {tolerance:g} deg)",
        output_dir / "05_resolution_vs_snr.png",
        y_limits=(0.0, 1.05),
    )
    plot_metric_curve(
        snapshot_summary,
        "x_value",
        "mean_rmse_deg",
        "rmse_ci_low_deg",
        "rmse_ci_high_deg",
        "Number of snapshots",
        "Mean matched-path RMSE (deg)",
        "Coherent multipath DOA error versus snapshots (95% CI)",
        output_dir / "06_rmse_vs_snapshots.png",
    )
    plot_metric_curve(
        mismatch_summary,
        "x_value",
        "mean_rmse_deg",
        "rmse_ci_low_deg",
        "rmse_ci_high_deg",
        "Sensor phase-error standard deviation (deg)",
        "Mean matched-path RMSE (deg)",
        "Robustness to array-manifold mismatch (95% CI)",
        output_dir / "07_rmse_vs_phase_error.png",
    )
    plot_metric_curve(
        mismatch_summary,
        "x_value",
        "resolution_rate",
        "resolution_ci_low",
        "resolution_ci_high",
        "Sensor phase-error standard deviation (deg)",
        "Two-path resolution probability",
        f"Resolution under array-manifold mismatch (error <= {tolerance:g} deg)",
        output_dir / "08_resolution_vs_phase_error.png",
        y_limits=(0.0, 1.05),
    )
    cdf_records = [
        row
        for row in records
        if row["sweep"] == "snr_db" and np.isclose(float(row["x_value"]), 0.0)
    ]
    plot_error_cdf(
        cdf_records,
        output_dir / "09_error_cdf_snr0.png",
        "Error distribution at 0 dB reference-path SNR",
    )
    mark("monte_carlo_figures_done")

    std_0 = _select_summary(summary, "snr_db", 0.0, METHOD_STANDARD)
    fbss_0 = _select_summary(summary, "snr_db", 0.0, METHOD_FBSS)
    rmse_reduction = 100.0 * (
        float(std_0["mean_rmse_deg"]) - float(fbss_0["mean_rmse_deg"])
    ) / max(float(std_0["mean_rmse_deg"]), np.finfo(float).tiny)
    standard_zero_records = sorted(
        (row for row in records if row["sweep"] == "snr_db" and np.isclose(float(row["x_value"]), 0.0) and row["method"] == METHOD_STANDARD),
        key=lambda row: int(row["trial"]),
    )
    fbss_zero_records = sorted(
        (row for row in records if row["sweep"] == "snr_db" and np.isclose(float(row["x_value"]), 0.0) and row["method"] == METHOD_FBSS),
        key=lambda row: int(row["trial"]),
    )
    standard_zero_rmse = np.asarray([float(row["rmse_deg"]) for row in standard_zero_records])
    fbss_zero_rmse = np.asarray([float(row["rmse_deg"]) for row in fbss_zero_records])
    paired_test = scipy.stats.wilcoxon(standard_zero_rmse, fbss_zero_rmse, alternative="greater")
    paired_median_reduction = float(np.median(standard_zero_rmse - fbss_zero_rmse))
    runtime = time.perf_counter() - start_time

    metrics: dict[str, Any] = {
        "version": "0.2.0",
        "truth_directions_deg": {
            "direct": list(truths[0]),
            "coherent_echo": list(truths[1]),
        },
        "representative_case": asdict(rep_metrics),
        "monte_carlo": {
            "trials_per_point": trials,
            "confidence": float(mc["confidence"]),
            "resolution_tolerance_deg": tolerance,
            "at_0_db": {
                "standard_mean_rmse_deg": float(std_0["mean_rmse_deg"]),
                "standard_rmse_ci_deg": [
                    float(std_0["rmse_ci_low_deg"]),
                    float(std_0["rmse_ci_high_deg"]),
                ],
                "standard_resolution_rate": float(std_0["resolution_rate"]),
                "fbss_mean_rmse_deg": float(fbss_0["mean_rmse_deg"]),
                "fbss_rmse_ci_deg": [
                    float(fbss_0["rmse_ci_low_deg"]),
                    float(fbss_0["rmse_ci_high_deg"]),
                ],
                "fbss_resolution_rate": float(fbss_0["resolution_rate"]),
                "fbss_rmse_reduction_percent": float(rmse_reduction),
                "paired_median_rmse_reduction_deg": paired_median_reduction,
                "paired_wilcoxon_one_sided_p_value": float(paired_test.pvalue),
            },
        },
        "runtime_seconds": float(runtime),
        "scope": "Normalized coherent-multipath array processing; no absolute source-power or device-effect parameters.",
    }
    (output_dir / "results_summary.json").write_text(
        json.dumps(metrics, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    (output_dir / "config_snapshot.yaml").write_text(
        yaml.safe_dump(config, sort_keys=False, allow_unicode=True), encoding="utf-8"
    )
    environment = {
        "python": sys.version,
        "platform": platform.platform(),
        "numpy": np.__version__,
        "scipy": scipy.__version__,
        "matplotlib": matplotlib.__version__,
        "seed": int(config["seed"]),
    }
    (output_dir / "environment.json").write_text(
        json.dumps(environment, indent=2), encoding="utf-8"
    )
    _write_html_report(output_dir, metrics)
    mark("report_done")
    return metrics

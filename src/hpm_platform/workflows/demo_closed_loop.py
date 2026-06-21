"""End-to-end v0.1 demonstration workflow."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
import csv
import json
import platform
import sys
import numpy as np
import scipy
import matplotlib
import yaml

from hpm_platform.evaluation.metrics import (
    angular_error_deg,
    focal_peak_error_lambda,
    outside_region_fraction,
    response_ratio_db,
)
from hpm_platform.field_control.focusing import focus_on_xz_plane
from hpm_platform.perception.music import music_2d
from hpm_platform.physics.array_geometry import RectangularArray
from hpm_platform.physics.effect_model import NormalizedEffectModel
from hpm_platform.protection.beamforming import covariance_matrix, lcmv_weights, output_sinr_db
from hpm_platform.signal.sources import Source, simulate_snapshots
from hpm_platform.visualization.plots import (
    plot_architecture,
    plot_far_field_uv,
    plot_music_spectrum,
    plot_receive_beampattern,
    plot_xz_map,
)


@dataclass
class DemoMetrics:
    desired_doa_error_deg: float
    interferer_doa_error_deg: float
    estimated_desired_theta_deg: float
    estimated_desired_phi_deg: float
    estimated_interferer_theta_deg: float
    estimated_interferer_phi_deg: float
    conventional_output_sinr_db: float
    lcmv_output_sinr_db: float
    sinr_improvement_db: float
    lcmv_interferer_response_relative_db: float
    focal_peak_error_lambda: float
    focal_peak_x_lambda: float
    focal_peak_z_lambda: float
    outside_target_probability_fraction: float


def _select_peaks(
    peaks: list[tuple[float, float, float]],
    desired_direction: tuple[float, float],
) -> tuple[tuple[float, float], tuple[float, float]]:
    paired = [(p[0], p[1]) for p in peaks]
    desired_est = min(paired, key=lambda p: angular_error_deg(p, desired_direction))
    remaining = [p for p in paired if p != desired_est]
    interferer_est = remaining[0] if remaining else desired_est
    return desired_est, interferer_est


def _write_html_report(output_dir: Path, metrics: DemoMetrics) -> None:
    rows = "\n".join(
        f"<tr><td>{key}</td><td>{value:.4f}</td></tr>" for key, value in asdict(metrics).items()
    )
    images = [
        ("Architecture and mechanism", "00_architecture.png"),
        ("Far-field array pattern", "01_far_field_uv.png"),
        ("Perception: 2-D MUSIC", "02_music_spectrum.png"),
        ("Protection: receive nulling", "03_receive_suppression.png"),
        ("Field control: normalized near-field focus", "04_near_field_focus.png"),
        ("Assessment: normalized response probability", "05_effect_probability.png"),
    ]
    cards = "\n".join(
        f'<section><h2>{title}</h2><img src="{filename}" alt="{title}"></section>'
        for title, filename in images
    )
    html = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>HPM Digital Twin v0.1 Demo</title>
<style>
body{{font-family:Arial,sans-serif;max-width:1100px;margin:36px auto;padding:0 20px;line-height:1.55}}
h1{{margin-bottom:0}} .note{{padding:14px;border:1px solid #999;border-radius:8px}}
img{{max-width:100%;border:1px solid #bbb;border-radius:8px}} section{{margin:34px 0}}
table{{border-collapse:collapse;width:100%}} td{{border:1px solid #aaa;padding:8px}}
</style></head><body>
<h1>HPM Digital Twin v0.1 — end-to-end normalized demo</h1>
<p class="note"><strong>Scope:</strong> This public baseline uses dimensionless field and response indices. It does not contain a real source-power budget, real equipment vulnerability thresholds, or operational targeting parameters.</p>
<h2>Metrics</h2><table>{rows}</table>{cards}
</body></html>"""
    (output_dir / "demo_report.html").write_text(html, encoding="utf-8")


def run(config_path: str | Path, output_dir: str | Path) -> DemoMetrics:
    config_path = Path(config_path)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    progress_path = output_dir / "progress.log"
    progress_path.write_text("start\n", encoding="utf-8")

    def mark(message: str) -> None:
        with progress_path.open("a", encoding="utf-8") as handle:
            handle.write(message + "\n")

    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    mark("config_loaded")

    array_cfg = config["array"]
    wavelength = 299_792_458.0 / float(array_cfg["frequency_hz"])
    spacing = float(array_cfg["spacing_lambda"]) * wavelength
    array = RectangularArray(
        nx=int(array_cfg["nx"]),
        ny=int(array_cfg["ny"]),
        frequency_hz=float(array_cfg["frequency_hz"]),
        dx_m=spacing,
        dy_m=spacing,
    )

    plot_architecture(output_dir / "00_architecture.png", output_dir / "00_architecture.svg")
    mark("architecture_done")

    desired_cfg = config["perception"]["desired"]
    interferer_cfg = config["perception"]["interferer"]
    desired = (float(desired_cfg["theta_deg"]), float(desired_cfg["phi_deg"]))
    interferer = (float(interferer_cfg["theta_deg"]), float(interferer_cfg["phi_deg"]))

    # Far-field visualization of a conventional transmit look direction.
    q_far = array.far_field_transmit_weights(*desired)
    uv_axis = np.linspace(-1.0, 1.0, 241)
    uu, vv = np.meshgrid(uv_axis, uv_axis, indexing="xy")
    far_response = array.transmit_response_uv(q_far, uu, vv)
    plot_far_field_uv(uv_axis, uv_axis, far_response, output_dir / "01_far_field_uv.png")
    mark("far_field_done")

    # Synthetic observation and MUSIC perception.
    x, _ = simulate_snapshots(
        array,
        [
            Source(*desired, power_db=float(desired_cfg["snr_db"]), label="desired"),
            Source(*interferer, power_db=float(interferer_cfg["inr_db"]), label="interferer"),
        ],
        n_snapshots=int(config["perception"]["snapshots"]),
        noise_power=1.0,
        seed=int(config["seed"]),
    )
    scan = config["perception"]["scan"]
    theta_grid = np.linspace(float(scan["theta_min_deg"]), float(scan["theta_max_deg"]), int(scan["theta_points"]))
    phi_grid = np.linspace(float(scan["phi_min_deg"]), float(scan["phi_max_deg"]), int(scan["phi_points"]))
    music = music_2d(x, array, 2, theta_grid, phi_grid, n_peaks=2)
    desired_est, interferer_est = _select_peaks(music.peaks, desired)
    plot_music_spectrum(
        theta_grid,
        phi_grid,
        music.spectrum,
        [desired, interferer],
        [desired_est, interferer_est],
        output_dir / "02_music_spectrum.png",
    )
    mark("music_done")

    # Receive protection using the estimated interferer direction.
    r = covariance_matrix(x)
    a_des = array.steering_vector(*desired)
    a_int_est = array.steering_vector(*interferer_est)
    w_conventional = array.conventional_receive_weights(*desired)
    w_lcmv = lcmv_weights(
        r,
        np.column_stack((a_des, a_int_est)),
        np.array([1.0, 0.0], dtype=complex),
        loading_factor=float(config["protection"]["diagonal_loading"]),
    )
    cut_theta = np.linspace(0.0, 65.0, 1301)
    cut_phi = np.zeros_like(cut_theta)
    conventional_response = array.receive_response(w_conventional, cut_theta, cut_phi)
    lcmv_response = array.receive_response(w_lcmv, cut_theta, cut_phi)
    conventional_db = 20 * np.log10(np.maximum(conventional_response / np.max(conventional_response), 1e-4))
    lcmv_db = 20 * np.log10(np.maximum(lcmv_response / np.max(lcmv_response), 1e-4))
    plot_receive_beampattern(
        cut_theta,
        conventional_db,
        lcmv_db,
        desired[0],
        interferer[0],
        output_dir / "03_receive_suppression.png",
    )
    mark("receive_plot_done")

    p_des = 10.0 ** (float(desired_cfg["snr_db"]) / 10.0)
    p_int = 10.0 ** (float(interferer_cfg["inr_db"]) / 10.0)
    sinr_conv = output_sinr_db(w_conventional, array, desired, interferer, p_des, p_int, 1.0)
    sinr_lcmv = output_sinr_db(w_lcmv, array, desired, interferer, p_des, p_int, 1.0)
    true_interferer_response = float(np.abs(np.vdot(w_lcmv, array.steering_vector(*interferer))))
    desired_response = float(np.abs(np.vdot(w_lcmv, a_des)))
    relative_interferer_db = response_ratio_db(true_interferer_response, desired_response)

    # Normalized near-field field control.
    field_cfg = config["field_control"]
    focus_lambda_xyz = np.asarray(field_cfg["focus_lambda"], dtype=float)
    focus_m = focus_lambda_xyz * wavelength
    x_lambda = np.linspace(float(field_cfg["x_min_lambda"]), float(field_cfg["x_max_lambda"]), int(field_cfg["x_points"]))
    z_lambda = np.linspace(float(field_cfg["z_min_lambda"]), float(field_cfg["z_max_lambda"]), int(field_cfg["z_points"]))
    intensity, _ = focus_on_xz_plane(array, focus_m, x_lambda * wavelength, z_lambda * wavelength)
    focus_xz = (float(focus_lambda_xyz[0]), float(focus_lambda_xyz[2]))
    plot_xz_map(
        x_lambda,
        z_lambda,
        intensity,
        focus_xz,
        "Range-normalized near-field coherent gain",
        "Coherent gain",
        output_dir / "04_near_field_focus.png",
    )
    mark("near_field_done")

    effect_cfg = config["effect_model"]
    effect_model = NormalizedEffectModel(
        threshold_median=float(effect_cfg["threshold_median"]),
        threshold_log_sigma=float(effect_cfg["threshold_log_sigma"]),
    )
    probability = effect_model.probability(
        intensity,
        pulse_width_norm=float(effect_cfg["pulse_width_norm"]),
        pulse_count=int(effect_cfg["pulse_count"]),
    )
    plot_xz_map(
        x_lambda,
        z_lambda,
        probability,
        focus_xz,
        "Normalized probabilistic response map",
        "Response probability",
        output_dir / "05_effect_probability.png",
    )
    mark("effect_plot_done")

    focal_error, focal_peak = focal_peak_error_lambda(intensity, x_lambda, z_lambda, focus_xz)
    outside_fraction = outside_region_fraction(probability, x_lambda, z_lambda, focus_xz, radius_lambda=5.0, threshold=0.5)
    metrics = DemoMetrics(
        desired_doa_error_deg=angular_error_deg(desired_est, desired),
        interferer_doa_error_deg=angular_error_deg(interferer_est, interferer),
        estimated_desired_theta_deg=desired_est[0],
        estimated_desired_phi_deg=desired_est[1],
        estimated_interferer_theta_deg=interferer_est[0],
        estimated_interferer_phi_deg=interferer_est[1],
        conventional_output_sinr_db=sinr_conv,
        lcmv_output_sinr_db=sinr_lcmv,
        sinr_improvement_db=sinr_lcmv - sinr_conv,
        lcmv_interferer_response_relative_db=relative_interferer_db,
        focal_peak_error_lambda=focal_error,
        focal_peak_x_lambda=focal_peak[0],
        focal_peak_z_lambda=focal_peak[1],
        outside_target_probability_fraction=outside_fraction,
    )
    metrics_dict = asdict(metrics)
    (output_dir / "metrics.json").write_text(json.dumps(metrics_dict, indent=2), encoding="utf-8")
    with (output_dir / "metrics.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["metric", "value"])
        writer.writerows(metrics_dict.items())
    (output_dir / "config_snapshot.yaml").write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")
    environment = {
        "python": sys.version,
        "platform": platform.platform(),
        "numpy": np.__version__,
        "scipy": scipy.__version__,
        "matplotlib": matplotlib.__version__,
        "seed": int(config["seed"]),
    }
    (output_dir / "environment.json").write_text(json.dumps(environment, indent=2), encoding="utf-8")
    _write_html_report(output_dir, metrics)
    mark("report_done")
    return metrics

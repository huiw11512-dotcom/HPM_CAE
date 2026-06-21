"""Live normalized perception and receive-protection nodes for HPM-CAE V1.2.

The routines execute the existing array-processing algorithms directly from a
``CAEProject``.  They intentionally use relative powers and normalized array
manifolds; no absolute source budget or equipment-effect threshold is present.
"""
from __future__ import annotations

from dataclasses import dataclass
import time
from typing import Iterable

import numpy as np
import pandas as pd
from scipy.optimize import linear_sum_assignment
from threadpoolctl import threadpool_limits

from hpm_platform.perception.esprit import esprit_2d_from_covariance
from hpm_platform.perception.music import MusicGridScanner
from hpm_platform.perception.robust_covariance import (
    pawr_estimate,
    sensor_health_from_local_power,
)
from hpm_platform.perception.spatial_smoothing import spatially_smoothed_covariance
from hpm_platform.protection.beamforming import covariance_matrix, lcmv_weights, mvdr_weights
from hpm_platform.protection.robust_beamforming import (
    ConfidenceSector,
    build_confidence_sector,
    sector_energy_rank,
    white_noise_gain_db,
)
from hpm_platform.signal.multipath import (
    CoherentEmitter,
    CoherentPath,
    draw_sensor_gain_phase_errors,
    simulate_coherent_multipath,
)
from hpm_platform.ui.project_model import CAEProject, InterfererSpec


def _complex_normal(rng: np.random.Generator, shape: tuple[int, ...]) -> np.ndarray:
    return (rng.standard_normal(shape) + 1j * rng.standard_normal(shape)) / np.sqrt(2.0)


def angular_distance_deg(a: tuple[float, float], b: tuple[float, float]) -> float:
    """Great-circle angular distance between two ``(theta, phi)`` directions."""
    theta_a, phi_a = np.deg2rad(a)
    theta_b, phi_b = np.deg2rad(b)
    va = np.array([np.sin(theta_a) * np.cos(phi_a), np.sin(theta_a) * np.sin(phi_a), np.cos(theta_a)])
    vb = np.array([np.sin(theta_b) * np.cos(phi_b), np.sin(theta_b) * np.sin(phi_b), np.cos(theta_b)])
    return float(np.rad2deg(np.arccos(np.clip(float(np.dot(va, vb)), -1.0, 1.0))))


def _match_directions(
    truths: tuple[tuple[float, float], ...],
    estimates: tuple[tuple[float, float], ...],
) -> tuple[np.ndarray, tuple[tuple[float, float], ...]]:
    if not truths:
        return np.empty(0), ()
    if not estimates:
        return np.full(len(truths), np.inf), tuple((float("nan"), float("nan")) for _ in truths)
    cost = np.array([[angular_distance_deg(t, e) for e in estimates] for t in truths], dtype=float)
    rows, cols = linear_sum_assignment(cost)
    errors = np.full(len(truths), np.inf)
    ordered: list[tuple[float, float]] = [(float("nan"), float("nan")) for _ in truths]
    for row, col in zip(rows, cols, strict=True):
        errors[row] = cost[row, col]
        ordered[row] = estimates[col]
    return errors, tuple(ordered)


def _axis(start: float, stop: float, step: float) -> np.ndarray:
    values = np.arange(float(start), float(stop) + 0.5 * float(step), float(step))
    if values[-1] > stop + 1e-9:
        values[-1] = stop
    return values


def _emitter_paths(item: InterfererSpec) -> tuple[CoherentPath, ...]:
    paths = [
        CoherentPath(
            theta_deg=item.theta_deg,
            phi_deg=item.phi_deg,
            relative_power_db=item.relative_power_db,
            phase_deg=0.0,
            label="direct",
        )
    ]
    if item.echo_enabled:
        paths.append(
            CoherentPath(
                theta_deg=item.echo_theta_deg,
                phi_deg=item.echo_phi_deg,
                relative_power_db=item.echo_relative_power_db,
                phase_deg=item.echo_phase_deg,
                label="echo",
            )
        )
    return tuple(paths)


def _truths(project: CAEProject) -> tuple[tuple[float, float], ...]:
    output: list[tuple[float, float]] = []
    for item in project.active_interferers:
        output.append((float(item.theta_deg), float(item.phi_deg)))
        if item.echo_enabled:
            output.append((float(item.echo_theta_deg), float(item.echo_phi_deg)))
    return tuple(output)


def _prior_centers(project: CAEProject) -> tuple[tuple[float, float], ...]:
    output: list[tuple[float, float]] = []
    for item in project.active_interferers:
        output.append((float(item.prior_theta_deg), float(item.prior_phi_deg)))
        if item.echo_enabled:
            # The direct prior is often available from a tracker while the echo
            # is only broadly predicted.  Use the configured echo direction as
            # the center of that broad numerical prior.
            output.append((float(item.echo_theta_deg), float(item.echo_phi_deg)))
    return tuple(output)


def _nearest_estimate(
    center: tuple[float, float],
    estimates: Iterable[tuple[float, float]],
) -> tuple[float, float]:
    values = tuple(estimates)
    if not values:
        return center
    return min(values, key=lambda value: angular_distance_deg(center, value))


def _local_sigma(
    spectrum: np.ndarray,
    theta: np.ndarray,
    phi: np.ndarray,
    center: tuple[float, float],
    *,
    radius_deg: float = 5.0,
) -> tuple[float, float]:
    tt, pp = np.meshgrid(theta, phi, indexing="ij")
    mask = (tt - center[0]) ** 2 + (pp - center[1]) ** 2 <= radius_deg**2
    if not np.any(mask):
        return 2.0, 2.5
    weights = np.maximum(np.asarray(spectrum, float)[mask], 1e-12) ** 5
    weights /= np.sum(weights)
    theta_values = tt[mask]
    phi_values = pp[mask]
    sigma_theta = float(np.sqrt(np.sum(weights * (theta_values - center[0]) ** 2)))
    sigma_phi = float(np.sqrt(np.sum(weights * (phi_values - center[1]) ** 2)))
    return float(np.clip(sigma_theta, 0.45, 8.0)), float(np.clip(sigma_phi, 0.55, 10.0))


@dataclass(frozen=True)
class PerceptionMethodRecord:
    method: str
    estimates: tuple[tuple[float, float], ...]
    errors_deg: np.ndarray
    runtime_ms: float
    valid: bool


@dataclass(frozen=True)
class LivePerceptionResult:
    project: CAEProject
    snapshots: np.ndarray
    truths: tuple[tuple[float, float], ...]
    estimates: tuple[tuple[float, float], ...]
    ordered_estimates: tuple[tuple[float, float], ...]
    theta_grid_deg: np.ndarray
    phi_grid_deg: np.ndarray
    spectrum: np.ndarray
    covariance: np.ndarray
    eigenvalues: np.ndarray
    sensor_reliability: np.ndarray
    fault_indices: tuple[int, ...]
    direct_centers: tuple[tuple[float, float], ...]
    direct_sigmas_deg: tuple[tuple[float, float], ...]
    method_records: tuple[PerceptionMethodRecord, ...]
    metrics: dict[str, float | int | bool | str]
    log_lines: tuple[str, ...]

    def estimates_frame(self) -> pd.DataFrame:
        rows = []
        for index, truth in enumerate(self.truths):
            estimate = self.ordered_estimates[index]
            error = angular_distance_deg(truth, estimate) if np.all(np.isfinite(estimate)) else float("inf")
            rows.append(
                {
                    "路径": index + 1,
                    "真值 θ/°": truth[0],
                    "真值 φ/°": truth[1],
                    "估计 θ/°": estimate[0],
                    "估计 φ/°": estimate[1],
                    "球面误差/°": error,
                }
            )
        return pd.DataFrame(rows)

    def comparison_frame(self) -> pd.DataFrame:
        rows = []
        for record in self.method_records:
            finite = record.errors_deg[np.isfinite(record.errors_deg)]
            rows.append(
                {
                    "方法": record.method,
                    "RMSE/°": float(np.sqrt(np.mean(finite**2))) if finite.size else float("inf"),
                    "最大误差/°": float(np.max(finite)) if finite.size else float("inf"),
                    "≤2°分辨": bool(record.valid and np.all(record.errors_deg <= 2.0)),
                    "耗时/ms": record.runtime_ms,
                }
            )
        return pd.DataFrame(rows)


def run_live_perception(project: CAEProject) -> LivePerceptionResult:
    """Execute one coherent-multipath sensing case from the current project."""
    with threadpool_limits(limits=1):
        started = time.perf_counter()
        lines: list[str] = []
        array = project.array.build_array()
        spec = project.perception
        if spec.subarray_nx > array.nx or spec.subarray_ny > array.ny:
            raise ValueError("perception subarray cannot exceed the physical array")
        truths = _truths(project)
        n_sources = len(truths)
        if n_sources >= spec.subarray_nx * spec.subarray_ny:
            raise ValueError("too many path components for the selected smoothing subarray")
        lines.append(f"[signal] {len(project.active_interferers)} emitter(s), {n_sources} coherent path(s), {spec.snapshots} snapshots")

        rng = np.random.default_rng(int(project.meta.seed) + 1101)
        gains = draw_sensor_gain_phase_errors(
            array.n_elements,
            rng,
            gain_std_db=spec.sensor_gain_std_db,
            phase_std_deg=spec.sensor_phase_std_deg,
        )
        fault_count = min(int(spec.fault_count), array.n_elements)
        faults = tuple(sorted(int(value) for value in rng.choice(array.n_elements, size=fault_count, replace=False))) if fault_count else ()
        if faults:
            fault_gain_db = rng.normal(4.0, 0.5, len(faults))
            fault_phase = rng.normal(25.0, 4.0, len(faults))
            gains[list(faults)] *= 10.0 ** (fault_gain_db / 20.0) * np.exp(1j * np.deg2rad(fault_phase))
        emitters = [
            CoherentEmitter(
                reference_power_db=float(spec.snr_db),
                paths=_emitter_paths(item),
                label=item.object_id,
            )
            for item in project.active_interferers
        ]
        snapshots, _ = simulate_coherent_multipath(
            array,
            emitters,
            n_snapshots=spec.snapshots,
            noise_power=1.0,
            seed=int(project.meta.seed) + 1103,
            sensor_gains=gains,
        )
        if faults:
            snapshots[list(faults)] += np.sqrt(10.0) * _complex_normal(rng, (len(faults), spec.snapshots))
        lines.append(f"[signal] injected calibration mismatch and {len(faults)} local channel fault(s)")

        theta = _axis(spec.scan_theta_min_deg, spec.scan_theta_max_deg, spec.scan_step_deg)
        phi = _axis(spec.scan_phi_min_deg, spec.scan_phi_max_deg, spec.scan_step_deg)
        smooth = spatially_smoothed_covariance(
            snapshots,
            array,
            spec.subarray_nx,
            spec.subarray_ny,
            forward_backward=True,
            diagonal_loading=0.0,
        )
        scanner = MusicGridScanner(smooth.subarray, theta, phi)
        reliability = sensor_health_from_local_power(
            snapshots,
            array,
            window=5,
            tuning=2.5,
            reliability_floor=0.05,
        )
        lines.append(f"[covariance] FBSS with {smooth.n_subarrays} overlapping subarrays")

        method_records: list[PerceptionMethodRecord] = []
        method_payloads: dict[str, tuple[tuple[tuple[float, float], ...], np.ndarray, np.ndarray, np.ndarray]] = {}

        t0 = time.perf_counter()
        fbss = scanner.scan_covariance(
            smooth.covariance,
            n_sources,
            diagonal_loading=spec.diagonal_loading,
            n_peaks=n_sources,
            min_separation_deg=2.0,
        )
        fbss_estimates = tuple((float(a), float(b)) for a, b, _ in fbss.peaks)
        fbss_errors, _ = _match_directions(truths, fbss_estimates)
        fbss_ms = 1000.0 * (time.perf_counter() - t0)
        method_records.append(PerceptionMethodRecord("FBSS-MUSIC", fbss_estimates, fbss_errors, fbss_ms, len(fbss_estimates) == n_sources))
        method_payloads["FBSS-MUSIC"] = (fbss_estimates, fbss.spectrum, smooth.covariance, fbss.eigenvalues)

        t0 = time.perf_counter()
        pawr = pawr_estimate(
            snapshots,
            array,
            scanner,
            n_sources,
            spec.subarray_nx,
            spec.subarray_ny,
            _prior_centers(project),
            prior_sigma_deg=spec.prior_sigma_deg,
            prior_strength=spec.prior_strength,
            selection_exponent=1.0,
            search_radius_sigma=1.5,
            structure_blend=0.03,
            forward_backward=True,
            health_window=5,
            health_tuning=2.5,
            reliability_floor=0.05,
            weight_exponent=20.0,
            weight_floor_fraction=0.03,
        )
        pawr_estimates = tuple((float(a), float(b)) for a, b in pawr.estimates)
        pawr_scan = scanner.scan_covariance(
            pawr.covariance,
            n_sources,
            diagonal_loading=spec.diagonal_loading,
            n_peaks=n_sources,
            min_separation_deg=2.0,
        )
        pawr_errors, _ = _match_directions(truths, pawr_estimates)
        pawr_ms = 1000.0 * (time.perf_counter() - t0)
        method_records.append(PerceptionMethodRecord("PAWR-MUSIC", pawr_estimates, pawr_errors, pawr_ms, len(pawr_estimates) == n_sources))
        method_payloads["PAWR-MUSIC"] = (pawr_estimates, pawr_scan.spectrum, pawr.covariance, np.linalg.eigvalsh(pawr.covariance)[::-1])
        reliability = pawr.sensor_reliability

        t0 = time.perf_counter()
        esprit = esprit_2d_from_covariance(smooth.covariance, smooth.subarray, n_sources)
        esprit_estimates = tuple((float(a), float(b)) for a, b in esprit.estimates)
        esprit_errors, _ = _match_directions(truths, esprit_estimates)
        esprit_ms = 1000.0 * (time.perf_counter() - t0)
        method_records.append(PerceptionMethodRecord("FBSS-ESPRIT", esprit_estimates, esprit_errors, esprit_ms, len(esprit_estimates) == n_sources))
        # Keep a MUSIC map as the spatial diagnostic when ESPRIT is selected.
        method_payloads["FBSS-ESPRIT"] = (esprit_estimates, fbss.spectrum, smooth.covariance, esprit.eigenvalues)

        estimates, spectrum, covariance, eigenvalues = method_payloads[spec.method]
        errors, ordered = _match_directions(truths, estimates)
        # Every resolved coherent path is a spatial interference component for
        # the downstream receive-protection node.  Passing only one direct-path
        # center per emitter would leave a strong echo outside the robust sector.
        # Keep the legacy field name for file compatibility, but carry all live
        # path centers and their spectrum-derived uncertainty.
        direct_centers = [tuple(map(float, center)) for center in estimates]
        direct_sigmas = [_local_sigma(spectrum, theta, phi, center) for center in direct_centers]

        finite = errors[np.isfinite(errors)]
        rmse = float(np.sqrt(np.mean(finite**2))) if finite.size else float("inf")
        max_error = float(np.max(finite)) if finite.size else float("inf")
        runtime_ms = 1000.0 * (time.perf_counter() - started)
        sorted_eigs = np.sort(np.real(np.linalg.eigvalsh(covariance)))[::-1]
        noise_floor = float(np.median(sorted_eigs[n_sources:])) if sorted_eigs.size > n_sources else 1e-12
        rank_margin_db = float(10.0 * np.log10(max(sorted_eigs[n_sources - 1] / max(noise_floor, 1e-12), 1e-12)))
        metrics: dict[str, float | int | bool | str] = {
            "method": spec.method,
            "n_sources": n_sources,
            "snapshots": int(spec.snapshots),
            "rmse_deg": rmse,
            "max_error_deg": max_error,
            "resolved_within_2deg": bool(len(estimates) >= n_sources and np.all(errors <= 2.0)),
            "rank_margin_db": rank_margin_db,
            "minimum_sensor_reliability": float(np.min(reliability)),
            "fault_count": len(faults),
            "runtime_ms": runtime_ms,
        }
        lines.append(f"[estimate] {spec.method}: RMSE={rmse:.3f}°, max={max_error:.3f}°, rank margin={rank_margin_db:.2f} dB")
        lines.append(f"[done] live perception completed in {runtime_ms:.1f} ms")
        return LivePerceptionResult(
            project=project,
            snapshots=snapshots,
            truths=truths,
            estimates=estimates,
            ordered_estimates=ordered,
            theta_grid_deg=theta,
            phi_grid_deg=phi,
            spectrum=spectrum,
            covariance=covariance,
            eigenvalues=np.asarray(eigenvalues, float),
            sensor_reliability=np.asarray(reliability, float),
            fault_indices=faults,
            direct_centers=tuple(direct_centers),
            direct_sigmas_deg=tuple(direct_sigmas),
            method_records=tuple(method_records),
            metrics=metrics,
            log_lines=tuple(lines),
        )


@dataclass(frozen=True)
class ProtectionMethodRecord:
    method: str
    output_sinr_db: float
    worst_true_response_db: float
    white_noise_gain_db: float
    selected_rank: int
    runtime_ms: float
    success: bool


@dataclass(frozen=True)
class LiveProtectionResult:
    project: CAEProject
    perception: LivePerceptionResult | None
    method: str
    weights: np.ndarray
    theta_grid_deg: np.ndarray
    phi_grid_deg: np.ndarray
    response_db: np.ndarray
    desired_direction: tuple[float, float]
    true_directions: tuple[tuple[float, float], ...]
    estimated_centers: tuple[tuple[float, float], ...]
    sectors: tuple[ConfidenceSector, ...]
    covariance: np.ndarray
    comparison: tuple[ProtectionMethodRecord, ...]
    metrics: dict[str, float | int | bool | str]
    log_lines: tuple[str, ...]

    def comparison_frame(self) -> pd.DataFrame:
        return pd.DataFrame(
            [
                {
                    "方法": item.method,
                    "输出SINR/dB": item.output_sinr_db,
                    "最坏真实方向响应/dB": item.worst_true_response_db,
                    "白噪声增益/dB": item.white_noise_gain_db,
                    "硬零陷秩": item.selected_rank,
                    "耗时/ms": item.runtime_ms,
                    "防护判据": item.success,
                }
                for item in self.comparison
            ]
        )


def _effective_interference_vectors(project: CAEProject) -> tuple[np.ndarray, ...]:
    array = project.array.build_array()
    base_power = 10.0 ** (float(project.protection.interferer_power_db) / 10.0)
    vectors: list[np.ndarray] = []
    for item in project.active_interferers:
        vector = np.zeros(array.n_elements, dtype=complex)
        direct_power = base_power * 10.0 ** (float(item.relative_power_db) / 10.0)
        vector += np.sqrt(direct_power) * array.steering_vector(item.theta_deg, item.phi_deg)
        if item.echo_enabled:
            echo_power = base_power * 10.0 ** (float(item.echo_relative_power_db) / 10.0)
            vector += np.sqrt(echo_power) * np.exp(1j * np.deg2rad(item.echo_phase_deg)) * array.steering_vector(item.echo_theta_deg, item.echo_phi_deg)
        vectors.append(vector)
    return tuple(vectors)


def _multi_sector_hybrid(
    covariance: np.ndarray,
    desired: np.ndarray,
    sectors: tuple[ConfidenceSector, ...],
    project: CAEProject,
) -> tuple[np.ndarray, int, float]:
    spec = project.protection
    scale = float(np.trace(covariance).real) / covariance.shape[0]
    effective = np.asarray(covariance, complex).copy()
    bases: list[np.ndarray] = []
    for sector in sectors:
        effective += float(spec.soft_strength) * scale * sector.covariance
        rank = sector_energy_rank(sector, spec.energy_threshold, max_rank=spec.max_rank)
        bases.append(sector.eigenvectors[:, :rank])
    merged = np.column_stack(bases)
    q, r = np.linalg.qr(merged)
    keep = np.abs(np.diag(r)) > 1e-8 * max(float(np.max(np.abs(np.diag(r)))), 1.0)
    basis = q[:, keep]
    if basis.shape[1] > covariance.shape[0] - 2:
        basis = basis[:, : covariance.shape[0] - 2]
    last: Exception | None = None
    for rank in range(basis.shape[1], 0, -1):
        constraints = np.column_stack((desired, basis[:, :rank]))
        responses = np.r_[1.0, np.zeros(rank)]
        try:
            weights = lcmv_weights(effective, constraints, responses, spec.loading_factor)
            wng = white_noise_gain_db(weights)
            if wng >= spec.wng_floor_db:
                return weights, rank, wng
        except np.linalg.LinAlgError as exc:
            last = exc
    if last is not None:
        raise np.linalg.LinAlgError("no stable multi-sector null solution") from last
    # A very broad sector can make every hard-rank option unstable. Keep the
    # soft covariance penalty rather than failing the whole live task.
    weights = mvdr_weights(effective, desired, spec.loading_factor)
    return weights, 0, white_noise_gain_db(weights)


def _protection_metrics(
    weights: np.ndarray,
    desired: np.ndarray,
    interference_vectors: tuple[np.ndarray, ...],
    project: CAEProject,
    true_directions: tuple[tuple[float, float], ...],
) -> tuple[float, float, float]:
    spec = project.protection
    desired_power = 10.0 ** (float(spec.desired_power_db) / 10.0)
    signal = desired_power * float(np.abs(np.vdot(weights, desired)) ** 2)
    interference = float(sum(np.abs(np.vdot(weights, vector)) ** 2 for vector in interference_vectors))
    noise = float(spec.noise_power) * float(np.vdot(weights, weights).real)
    sinr = float(10.0 * np.log10(max(signal, 1e-18) / max(interference + noise, 1e-18)))
    array = project.array.build_array()
    steering = np.column_stack([array.steering_vector(*direction) for direction in true_directions])
    denominator = max(float(np.abs(np.vdot(weights, desired))), 1e-15)
    response = np.abs(np.conj(weights) @ steering) / denominator
    worst = float(20.0 * np.log10(max(float(np.max(response)), 1e-12)))
    return sinr, worst, white_noise_gain_db(weights)


def run_live_protection(
    project: CAEProject,
    perception: LivePerceptionResult | None = None,
) -> LiveProtectionResult:
    """Execute receive beamforming using live DOA estimates and uncertainty."""
    with threadpool_limits(limits=1):
        started = time.perf_counter()
        lines: list[str] = []
        array = project.array.build_array()
        spec = project.protection
        desired_direction = (float(spec.desired_theta_deg), float(spec.desired_phi_deg))
        desired = array.steering_vector(*desired_direction)
        true_directions = _truths(project)
        interference_vectors = _effective_interference_vectors(project)

        if perception is not None:
            centers = perception.direct_centers
            sigmas = perception.direct_sigmas_deg
            lines.append("[input] using live perception estimates and spectrum-derived uncertainty")
        else:
            centers = tuple((item.prior_theta_deg, item.prior_phi_deg) for item in project.active_interferers)
            sigmas = tuple((item.uncertainty_theta_deg, item.uncertainty_phi_deg) for item in project.active_interferers)
            lines.append("[input] using configured prior centers because no live perception result was supplied")

        sectors = tuple(
            build_confidence_sector(
                array,
                center,
                (
                    max(
                        float(spec.sector_scale) * float(sigma[0]),
                        1.6 * float(spec.grid_step_deg),
                        0.8,
                    ),
                    max(
                        float(spec.sector_scale) * float(sigma[1]),
                        1.6 * float(spec.grid_step_deg),
                        1.0,
                    ),
                ),
                grid_step_deg=spec.grid_step_deg,
                sigma_deg=(max(float(sigma[0]), 0.4), max(float(sigma[1]), 0.5)),
            )
            for center, sigma in zip(centers, sigmas, strict=True)
        )
        lines.append(f"[sector] built {len(sectors)} confidence sector(s)")

        rng = np.random.default_rng(int(project.meta.seed) + 2201)
        snapshots = np.zeros((array.n_elements, project.perception.snapshots), dtype=complex)
        for vector in interference_vectors:
            snapshots += vector[:, None] @ _complex_normal(rng, (1, project.perception.snapshots))
        snapshots += np.sqrt(spec.noise_power) * _complex_normal(rng, snapshots.shape)
        covariance = covariance_matrix(snapshots)

        records: list[ProtectionMethodRecord] = []
        payloads: dict[str, tuple[np.ndarray, int, float]] = {}
        methods = ("DL-MVDR", "Point-LCMV", "Sector-MVDR", "CR-HybridNull")
        for method in methods:
            t0 = time.perf_counter()
            selected_rank = 0
            if method == "DL-MVDR":
                weights = mvdr_weights(covariance, desired, spec.loading_factor)
            elif method == "Point-LCMV":
                point_constraints = [array.steering_vector(*center) for center in centers]
                constraints = np.column_stack((desired, *point_constraints))
                weights = lcmv_weights(covariance, constraints, np.r_[1.0, np.zeros(len(point_constraints))], spec.loading_factor)
                selected_rank = len(point_constraints)
            elif method == "Sector-MVDR":
                scale = float(np.trace(covariance).real) / covariance.shape[0]
                effective = covariance + float(spec.soft_strength) * scale * sum((sector.covariance for sector in sectors), np.zeros_like(covariance))
                weights = mvdr_weights(effective, desired, spec.loading_factor)
            else:
                weights, selected_rank, _ = _multi_sector_hybrid(covariance, desired, sectors, project)
            runtime_ms = 1000.0 * (time.perf_counter() - t0)
            sinr, worst, wng = _protection_metrics(weights, desired, interference_vectors, project, true_directions)
            success = bool(sinr >= 5.0 and worst <= -35.0 and wng >= 0.0)
            records.append(ProtectionMethodRecord(method, sinr, worst, wng, selected_rank, runtime_ms, success))
            payloads[method] = (weights, selected_rank, wng)

        weights, selected_rank, wng = payloads[spec.method]
        selected_record = next(item for item in records if item.method == spec.method)
        theta = np.linspace(0.0, 80.0, 81)
        phi = np.linspace(-90.0, 90.0, 181)
        tt, pp = np.meshgrid(theta, phi, indexing="ij")
        steering = array.steering_matrix(tt.ravel(), pp.ravel())
        denominator = max(float(np.abs(np.vdot(weights, desired))), 1e-15)
        response = np.abs(np.conj(weights) @ steering) / denominator
        response_db = 20.0 * np.log10(np.maximum(response.reshape(tt.shape), 1e-8))
        runtime_ms = 1000.0 * (time.perf_counter() - started)
        metrics: dict[str, float | int | bool | str] = {
            "method": spec.method,
            "output_sinr_db": selected_record.output_sinr_db,
            "worst_true_response_db": selected_record.worst_true_response_db,
            "white_noise_gain_db": selected_record.white_noise_gain_db,
            "selected_rank": selected_rank,
            "sector_count": len(sectors),
            "protection_success": selected_record.success,
            "runtime_ms": runtime_ms,
        }
        lines.append(
            f"[beamformer] {spec.method}: SINR={selected_record.output_sinr_db:.2f} dB, "
            f"worst response={selected_record.worst_true_response_db:.2f} dB, rank={selected_rank}"
        )
        lines.append(f"[done] live receive protection completed in {runtime_ms:.1f} ms")
        return LiveProtectionResult(
            project=project,
            perception=perception,
            method=spec.method,
            weights=weights,
            theta_grid_deg=theta,
            phi_grid_deg=phi,
            response_db=response_db,
            desired_direction=desired_direction,
            true_directions=true_directions,
            estimated_centers=tuple(centers),
            sectors=sectors,
            covariance=covariance,
            comparison=tuple(records),
            metrics=metrics,
            log_lines=tuple(lines),
        )

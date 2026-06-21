"""Publication-oriented, one-figure-per-file visualization helpers."""
from __future__ import annotations

from pathlib import Path
import numpy as np
import matplotlib.pyplot as plt
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch


def _save(fig: plt.Figure, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=220, bbox_inches="tight")
    plt.close(fig)


def plot_architecture(output_png: Path, output_svg: Path | None = None) -> None:
    fig, ax = plt.subplots(figsize=(15, 4.8))
    ax.set_xlim(0, 15)
    ax.set_ylim(0, 5)
    ax.axis("off")
    labels = [
        (0.4, 2.0, "Scenario &\nUncertainty"),
        (2.9, 2.0, "Propagation &\nCoupling"),
        (5.4, 2.0, "Array\nObservation"),
        (7.9, 2.0, "Perception\nMUSIC / Classifier"),
        (10.4, 2.0, "Protection &\nField Control"),
        (12.9, 2.0, "Normalized\nEffect Assessment"),
    ]
    width, height = 1.8, 1.05
    for x, y, label in labels:
        box = FancyBboxPatch((x, y), width, height, boxstyle="round,pad=0.08")
        ax.add_patch(box)
        ax.text(x + width / 2, y + height / 2, label, ha="center", va="center", fontsize=10)
    for (x1, y1, _), (x2, y2, _) in zip(labels[:-1], labels[1:]):
        arrow = FancyArrowPatch((x1 + width, y1 + height / 2), (x2, y2 + height / 2), arrowstyle="->", mutation_scale=15)
        ax.add_patch(arrow)
    feedback = FancyArrowPatch(
        (13.8, 1.85),
        (11.2, 1.35),
        connectionstyle="arc3,rad=0.35",
        arrowstyle="->",
        mutation_scale=15,
    )
    ax.add_patch(feedback)
    ax.text(12.5, 0.75, "Feedback: state / uncertainty / control update", ha="center", fontsize=10)
    ax.text(7.5, 4.25, "HPM Digital Twin v0.1 — normalized, reproducible, full-chain simulation", ha="center", fontsize=15)
    _save(fig, output_png)
    if output_svg is not None:
        fig2, ax2 = plt.subplots(figsize=(15, 4.8))
        ax2.set_xlim(0, 15)
        ax2.set_ylim(0, 5)
        ax2.axis("off")
        for x, y, label in labels:
            box = FancyBboxPatch((x, y), width, height, boxstyle="round,pad=0.08")
            ax2.add_patch(box)
            ax2.text(x + width / 2, y + height / 2, label, ha="center", va="center", fontsize=10)
        for (x1, y1, _), (x2, y2, _) in zip(labels[:-1], labels[1:]):
            ax2.add_patch(FancyArrowPatch((x1 + width, y1 + height / 2), (x2, y2 + height / 2), arrowstyle="->", mutation_scale=15))
        ax2.add_patch(FancyArrowPatch((13.8, 1.85), (11.2, 1.35), connectionstyle="arc3,rad=0.35", arrowstyle="->", mutation_scale=15))
        ax2.text(12.5, 0.75, "Feedback: state / uncertainty / control update", ha="center", fontsize=10)
        ax2.text(7.5, 4.25, "HPM Digital Twin v0.1 — normalized, reproducible, full-chain simulation", ha="center", fontsize=15)
        _save(fig2, output_svg)


def plot_far_field_uv(u: np.ndarray, v: np.ndarray, response: np.ndarray, output: Path) -> None:
    response_db = 20.0 * np.log10(np.maximum(response, 1e-4))
    fig, ax = plt.subplots(figsize=(7.6, 6.4))
    mesh = ax.pcolormesh(u, v, response_db, shading="auto")
    ax.set_aspect("equal")
    ax.set_xlabel("u = sin(theta) cos(phi)")
    ax.set_ylabel("v = sin(theta) sin(phi)")
    ax.set_title("Normalized far-field transmit pattern (dB)")
    fig.colorbar(mesh, ax=ax, label="Normalized response (dB)")
    _save(fig, output)


def plot_music_spectrum(
    theta: np.ndarray,
    phi: np.ndarray,
    spectrum: np.ndarray,
    truth: list[tuple[float, float]],
    estimates: list[tuple[float, float]],
    output: Path,
) -> None:
    fig, ax = plt.subplots(figsize=(8.4, 6.1))
    mesh = ax.pcolormesh(phi, theta, 10.0 * np.log10(np.maximum(spectrum, 1e-6)), shading="auto")
    if truth:
        ax.scatter([p for _, p in truth], [t for t, _ in truth], marker="x", s=90, label="Truth")
    if estimates:
        ax.scatter([p for _, p in estimates], [t for t, _ in estimates], marker="o", facecolors="none", s=80, label="MUSIC peaks")
    ax.set_xlabel("phi (deg)")
    ax.set_ylabel("theta from broadside (deg)")
    ax.set_title("2-D MUSIC pseudospectrum")
    ax.legend(loc="upper right")
    fig.colorbar(mesh, ax=ax, label="Normalized pseudospectrum (dB)")
    _save(fig, output)


def plot_receive_beampattern(
    theta_deg: np.ndarray,
    conventional_db: np.ndarray,
    lcmv_db: np.ndarray,
    desired_theta: float,
    interferer_theta: float,
    output: Path,
) -> None:
    fig, ax = plt.subplots(figsize=(9.0, 5.5))
    ax.plot(theta_deg, conventional_db, label="Conventional")
    ax.plot(theta_deg, lcmv_db, label="LCMV with estimated interferer")
    ax.axvline(desired_theta, linestyle="--", label="Desired direction")
    ax.axvline(interferer_theta, linestyle=":", label="Interferer direction")
    ax.set_ylim(-80, 5)
    ax.set_xlabel("theta at phi = 0 deg")
    ax.set_ylabel("Normalized receive response (dB)")
    ax.set_title("Receive-side interference suppression")
    ax.grid(True, alpha=0.3)
    ax.legend()
    _save(fig, output)


def plot_xz_map(
    x_lambda: np.ndarray,
    z_lambda: np.ndarray,
    values: np.ndarray,
    focus_lambda: tuple[float, float],
    title: str,
    colorbar_label: str,
    output: Path,
) -> None:
    fig, ax = plt.subplots(figsize=(8.4, 6.1))
    mesh = ax.pcolormesh(x_lambda, z_lambda, values, shading="auto")
    ax.scatter([focus_lambda[0]], [focus_lambda[1]], marker="x", s=90, label="Requested focus")
    ax.set_xlabel("x / wavelength")
    ax.set_ylabel("z / wavelength")
    ax.set_title(title)
    ax.legend(loc="upper right")
    fig.colorbar(mesh, ax=ax, label=colorbar_label)
    _save(fig, output)

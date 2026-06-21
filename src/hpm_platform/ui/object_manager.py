"""Persisted multi-object scene tables for the V1.2 CAE workbench."""
from __future__ import annotations

from dataclasses import replace
from html import escape
from typing import Any

import pandas as pd

from hpm_platform.ui.project_model import (
    CAEProject,
    InterfererSpec,
    ProtectedZoneSpec,
    TargetRegionSpec,
)

TARGET_COLUMNS = ["object_id", "name", "enabled", "center_x_lambda", "center_y_lambda", "semi_major_lambda", "semi_minor_lambda", "rotation_deg", "guard_scale", "amplitude_scale", "priority", "tolerance_percent"]
ZONE_COLUMNS = ["object_id", "name", "enabled", "center_x_lambda", "center_y_lambda", "radius_lambda", "priority", "max_amplitude_scale"]
INTERFERER_COLUMNS = ["object_id", "name", "enabled", "theta_deg", "phi_deg", "relative_power_db", "echo_enabled", "echo_theta_deg", "echo_phi_deg", "echo_relative_power_db", "echo_phase_deg", "prior_theta_deg", "prior_phi_deg", "uncertainty_theta_deg", "uncertainty_phi_deg"]


def _frame(items: tuple[Any, ...], columns: list[str]) -> pd.DataFrame:
    return pd.DataFrame([{column: getattr(item, column) for column in columns} for item in items], columns=columns)


def project_to_object_frames(project: CAEProject) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    return (
        _frame((project.target, *project.additional_targets), TARGET_COLUMNS),
        _frame((project.protected_zone, *project.additional_protected_zones), ZONE_COLUMNS),
        _frame(project.interferers, INTERFERER_COLUMNS),
    )


def _records(frame: pd.DataFrame | list | None, columns: list[str]) -> list[dict[str, Any]]:
    if frame is None:
        return []
    data = pd.DataFrame(frame, columns=columns) if not isinstance(frame, pd.DataFrame) else frame.copy()
    data = data.dropna(how="all")
    output: list[dict[str, Any]] = []
    for record in data.to_dict(orient="records"):
        clean = {column: record.get(column) for column in columns}
        if clean["object_id"] is None or not str(clean["object_id"]).strip():
            continue
        output.append(clean)
    return output


def apply_object_frames(
    project: CAEProject,
    targets: pd.DataFrame | list,
    zones: pd.DataFrame | list,
    interferers: pd.DataFrame | list,
) -> CAEProject:
    target_records = _records(targets, TARGET_COLUMNS)
    zone_records = _records(zones, ZONE_COLUMNS)
    interferer_records = _records(interferers, INTERFERER_COLUMNS)
    if not target_records:
        raise ValueError("对象树至少需要一个目标区")
    if not interferer_records:
        raise ValueError("实时感知链路至少需要一个辐射源对象")
    target_items = tuple(TargetRegionSpec(**item) for item in target_records)
    zone_items = tuple(ProtectedZoneSpec(**item) for item in zone_records)
    interferer_items = tuple(InterfererSpec(**item) for item in interferer_records)
    if not zone_items:
        # Keep a disabled primary placeholder so the backward-compatible schema
        # remains structurally complete while the active-zone tuple is empty.
        zone_items = (replace(project.protected_zone, enabled=False),)
    return replace(
        project,
        target=target_items[0],
        additional_targets=target_items[1:],
        protected_zone=zone_items[0],
        additional_protected_zones=zone_items[1:],
        interferers=interferer_items,
    )


def add_target_row(frame: pd.DataFrame | list | None) -> pd.DataFrame:
    data = pd.DataFrame(frame, columns=TARGET_COLUMNS).copy() if frame is not None else pd.DataFrame(columns=TARGET_COLUMNS)
    index = len(data) + 1
    data.loc[len(data)] = [f"TGT-{index:03d}", f"目标区{index}", True, -1.4 + .35 * index, -1.0, .70, .45, -15.0, 1.35, 1.0, 1.0, 10.0]
    return data


def add_zone_row(frame: pd.DataFrame | list | None) -> pd.DataFrame:
    data = pd.DataFrame(frame, columns=ZONE_COLUMNS).copy() if frame is not None else pd.DataFrame(columns=ZONE_COLUMNS)
    index = len(data) + 1
    data.loc[len(data)] = [f"PRT-{index:03d}", f"保护区{index}", True, 2.0, -2.1 + .25 * index, .50, 1.0, 0.25]
    return data


def add_interferer_row(frame: pd.DataFrame | list | None) -> pd.DataFrame:
    data = pd.DataFrame(frame, columns=INTERFERER_COLUMNS).copy() if frame is not None else pd.DataFrame(columns=INTERFERER_COLUMNS)
    index = len(data) + 1
    theta = 11.0 + 11.0 * index
    phi = -22.0 + 14.0 * index
    data.loc[len(data)] = [f"INT-{index:03d}", f"相干辐射源{index}", True, theta, phi, -2.0, True, min(theta + 12.0, 75.0), min(phi + 16.0, 80.0), -5.0, 35.0, theta + 1.5, phi + 1.5, 2.5, 3.0]
    return data


def object_tree_html(project: CAEProject) -> str:
    def item(icon: str, name: str, object_id: str, enabled: bool, detail: str) -> str:
        state = "on" if enabled else "off"
        dot = "#4ee0a5" if enabled else "#526178"
        return f'<div class="object-row {state}"><span style="color:{dot}">●</span><span>{icon}</span><b>{escape(name)}</b><code>{escape(object_id)}</code><small>{escape(detail)}</small></div>'

    rows = [f'<div class="object-root">▾ 📁 {escape(project.meta.name)}</div>']
    rows.append(f'<div class="object-group">▾ 🎯 目标区 <em>{len(project.targets)}</em></div>')
    for target in (project.target, *project.additional_targets):
        rows.append(item("◉", target.name, target.object_id, target.enabled, f"({target.center_x_lambda:.2f}, {target.center_y_lambda:.2f})λ · {target.semi_major_lambda:.2f}×{target.semi_minor_lambda:.2f}λ · w={target.priority:.2g} · ±{target.tolerance_percent:.0f}%"))
    rows.append(f'<div class="object-group">▾ 🛡 保护区 <em>{len(project.protected_zones)}</em></div>')
    for zone in (project.protected_zone, *project.additional_protected_zones):
        rows.append(item("○", zone.name, zone.object_id, zone.enabled, f"({zone.center_x_lambda:.2f}, {zone.center_y_lambda:.2f})λ · r={zone.radius_lambda:.2f}λ · cap={zone.max_amplitude_scale:.2f}× · w={zone.priority:.2g}"))
    rows.append(f'<div class="object-group">▾ 📡 辐射源 <em>{len(project.active_interferers)}</em></div>')
    for source in project.interferers:
        rows.append(item("⌁", source.name, source.object_id, source.enabled, f"θ={source.theta_deg:.1f}° · φ={source.phi_deg:.1f}° · echo={'on' if source.echo_enabled else 'off'}"))
    return '<div class="object-tree">' + "".join(rows) + "</div>"

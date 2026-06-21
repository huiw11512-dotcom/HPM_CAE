"""V2.0A 可信度验证体系运行器。"""
from __future__ import annotations

from pathlib import Path
import json
import zipfile
from typing import Any

from hpm_platform.validation.analytic_cases import CaseResult, run_all_validation_cases
from hpm_platform.validation.plotting_vv import generate_static_artifacts, make_vv_plotly_payloads
from hpm_platform.validation.sensitivity import run_oat_sensitivity
from hpm_platform.validation.uncertainty import run_monte_carlo_uncertainty
from hpm_platform.validation.vv_metrics import compute_credibility_score, summarize_cases
from hpm_platform.validation.vv_report import write_vv_outputs


def project_root() -> Path:
    return Path(__file__).resolve().parents[3]


def run_vv(
    *,
    mode: str = "fast",
    project_path: str | Path | None = None,
    output_dir: str | Path | None = None,
    include_plotly: bool = False,
    include_external_data_audit: bool = True,
) -> dict[str, Any]:
    """运行 V2.0A V&V 验证体系并生成中文交付物。"""

    root = project_root()
    out = Path(output_dir) if output_dir else root / "outputs_v20a_vv"
    out.mkdir(parents=True, exist_ok=True)
    normalized_mode = "full" if str(mode).lower() in {"full", "完整", "完整v&v"} else "fast"
    fast = normalized_mode == "fast"
    cfg_project = Path(project_path) if project_path else root / "configs" / "cae_project_v14.yaml"

    cases: list[CaseResult] = run_all_validation_cases(cfg_project, fast=fast)
    uncertainty = run_monte_carlo_uncertainty(
        n_samples=64 if fast else 160,
        seed=20260620,
        grid_points=101 if fast else 131,
    )
    sensitivity = run_oat_sensitivity(cfg_project)
    score = compute_credibility_score(cases, uncertainty.summary, sensitivity.summary)
    external_data_audit = None
    if include_external_data_audit:
        try:
            from hpm_platform.data_import.vv_audit import generate_external_data_vv_audit

            external_data_audit = generate_external_data_vv_audit(
                cfg_project,
                out,
                base_credibility_score=score.total_score,
                maximum_evaluations=16 if fast else 24,
            )
        except Exception as exc:  # pragma: no cover - V&V should remain usable without V3.0 samples.
            external_data_audit = {
                "版本": "V3.0-preview",
                "名称": "外部数据 V&V 可信度审计",
                "通过": False,
                "可纳入正式可信度评分": False,
                "预评分": 0.0,
                "预评分等级": "D",
                "风险信号": [f"外部数据审计未完成：{exc}"],
                "正式评分策略": {
                    "当前V2.0A核心评分": round(score.total_score, 2),
                    "风险调整预览评分": round(score.total_score, 2),
                    "是否改写正式评分": False,
                },
            }
    artifacts = generate_static_artifacts(
        cases=cases,
        uncertainty=uncertainty,
        sensitivity=sensitivity,
        score=score,
        output_dir=out,
    )
    output_paths = write_vv_outputs(
        project_root=root,
        output_dir=out,
        cases=cases,
        uncertainty=uncertainty,
        sensitivity=sensitivity,
        score=score,
        artifacts=artifacts,
        mode=normalized_mode,
        external_data_audit=external_data_audit,
    )
    result_zip = package_vv_results(out)
    payload: dict[str, Any] = {
        "version": "HPM_Digital_Twin_v2_0A",
        "mode": normalized_mode,
        "summary": summarize_cases(cases),
        "score": score.as_dict(),
        "cases": [case.as_dict() for case in cases],
        "uncertainty": uncertainty.as_dict(),
        "sensitivity": sensitivity.as_dict(),
        "external_data_vv": external_data_audit,
        "artifacts": artifacts,
        "outputs": output_paths | {"vv_results_zip": str(result_zip)},
    }
    if include_plotly:
        payload["plotly"] = make_vv_plotly_payloads(cases=cases, uncertainty=uncertainty, sensitivity=sensitivity, score=score)
    return payload


def package_vv_results(output_dir: str | Path) -> Path:
    out = Path(output_dir)
    zip_path = out / "v20A_VV结果包.zip"
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for path in out.rglob("*"):
            if path.is_dir() or path == zip_path:
                continue
            zf.write(path, path.relative_to(out))
    return zip_path


def load_last_vv_result(output_dir: str | Path | None = None) -> dict[str, Any] | None:
    out = Path(output_dir) if output_dir else project_root() / "outputs_v20a_vv"
    path = out / "v20A_验证结果.json"
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))

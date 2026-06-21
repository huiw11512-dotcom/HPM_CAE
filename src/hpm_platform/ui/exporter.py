"""Project and result export helpers for the 本地 V1.3 中文工作台."""
from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
import json
import shutil

from hpm_platform.ui.figures import (
    make_convergence_figure,
    make_constraint_margin_figure,
    make_object_metrics_figure,
    make_cut_figure,
    make_far_field_figure,
    make_field_figure,
    make_scene_figure,
    make_weights_figure,
    write_standalone_report,
)
from hpm_platform.ui.project_model import CAEProject
from hpm_platform.ui.quick_solver import CAESolveResult, save_numeric_result


def export_project_file(project: CAEProject, root: str | Path) -> Path:
    destination = Path(root)
    destination.mkdir(parents=True, exist_ok=True)
    return project.save_yaml(destination / f"{project.slug}.hpmcae.yaml")


def _digest(path: Path) -> str:
    hasher = sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def export_result_bundle(
    result: CAESolveResult,
    root: str | Path,
    *,
    run_name: str | None = None,
) -> tuple[Path, Path, Path]:
    """Write a complete run folder and zip; return folder, report, zip."""
    root_path = Path(root)
    root_path.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    folder_name = run_name or f"{result.project.slug}_{timestamp}"
    run_dir = root_path / folder_name
    if run_dir.exists():
        shutil.rmtree(run_dir)
    save_numeric_result(result, run_dir)

    figures = [
        ("三维场景", make_scene_figure(result.project)),
        ("观察面场分布", make_field_figure(result)),
        ("目标中心截线", make_cut_figure(result)),
        ("远场方向余弦图", make_far_field_figure(result)),
        ("阵元激励", make_weights_figure(result)),
        ("收敛历史", make_convergence_figure(result)),
        ("约束裕量", make_constraint_margin_figure(result)),
        ("对象级指标", make_object_metrics_figure(result)),
    ]
    figures_dir = run_dir / "interactive_figures"
    figures_dir.mkdir(parents=True, exist_ok=True)
    for index, (title, figure) in enumerate(figures, start=1):
        safe = ["scene", "field", "cut", "far_field", "weights", "convergence", "constraint_margin", "object_metrics"][index - 1]
        figure.write_html(
            figures_dir / f"{index:02d}_{safe}.html",
            include_plotlyjs="directory",
            full_html=True,
            config={"displaylogo": False, "responsive": True},
        )
    report = write_standalone_report(result, figures, run_dir / "HPM_CAE_report.html")

    files = [path for path in run_dir.rglob("*") if path.is_file()]
    manifest = {
        "platform": "HPM-CAE",
        "version": "1.3.0",
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "project": result.project.meta.name,
        "model_scope": result.project.model_scope,
        "files": [
            {
                "path": str(path.relative_to(run_dir)).replace("\\", "/"),
                "bytes": path.stat().st_size,
                "sha256": _digest(path),
            }
            for path in sorted(files)
        ],
    }
    (run_dir / "result_manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    archive_base = root_path / folder_name
    archive = Path(shutil.make_archive(str(archive_base), "zip", root_dir=run_dir))
    (archive.with_suffix(archive.suffix + ".sha256")).write_text(
        f"{_digest(archive)}  {archive.name}\n", encoding="utf-8"
    )
    return run_dir, report, archive

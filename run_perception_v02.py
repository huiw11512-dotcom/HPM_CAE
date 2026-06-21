#!/usr/bin/env python3
"""Run the v0.2 coherent-multipath perception study."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys

os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
os.environ.setdefault("OMP_NUM_THREADS", "1")
os.environ.setdefault("MKL_NUM_THREADS", "1")

ROOT = Path(__file__).resolve().parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from hpm_platform.workflows.perception_v02 import run  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--config",
        type=Path,
        default=ROOT / "configs" / "perception_v02.yaml",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "outputs_v02_perception",
    )
    args = parser.parse_args()
    metrics = run(args.config, args.output)
    print(json.dumps(metrics, indent=2, ensure_ascii=False))
    print(f"Report: {(args.output / 'perception_v02_report.html').resolve()}")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Run the HPM Digital Twin v0.1 end-to-end demonstration."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys

# Small/medium complex matrix operations are faster and more stable with a
# single BLAS worker in this reproducible demo. Users can override explicitly.
os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
os.environ.setdefault("OMP_NUM_THREADS", "1")
os.environ.setdefault("MKL_NUM_THREADS", "1")

ROOT = Path(__file__).resolve().parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from hpm_platform.workflows.demo_closed_loop import run  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, default=ROOT / "configs" / "default.yaml")
    parser.add_argument("--output", type=Path, default=ROOT / "outputs")
    args = parser.parse_args()
    metrics = run(args.config, args.output)
    print(json.dumps(metrics.__dict__, indent=2))
    print(f"Report: {(args.output / 'demo_report.html').resolve()}")


if __name__ == "__main__":
    main()

"""Command-line entry point for V0.7 dynamic normalized field control."""
from __future__ import annotations

from pathlib import Path
import argparse
import os
import sys

for _name in ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS"):
    os.environ.setdefault(_name, "1")

ROOT = Path(__file__).resolve().parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from hpm_platform.workflows.dynamic_field_control_v07 import run


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default="configs/dynamic_field_control_v07.yaml")
    parser.add_argument("--output", default="outputs_v07_dynamic_field_control")
    args = parser.parse_args()
    run(args.config, args.output)


if __name__ == "__main__":
    main()

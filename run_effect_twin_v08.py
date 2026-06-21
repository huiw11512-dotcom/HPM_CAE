"""Command-line entry point for V0.8 normalized effect digital twin."""
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

from hpm_platform.workflows.effect_twin_v08 import run


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default="configs/effect_twin_v08.yaml")
    parser.add_argument("--output", default="outputs_v08_effect_twin")
    args = parser.parse_args()
    run(args.config, args.output)


if __name__ == "__main__":
    main()

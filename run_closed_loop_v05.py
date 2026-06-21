"""Command-line entry point for the V0.5 dynamic closed-loop study."""
from __future__ import annotations

from pathlib import Path
import os
import sys

for _name in ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS"):
    os.environ.setdefault(_name, "1")

ROOT = Path(__file__).resolve().parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from hpm_platform.workflows.closed_loop_v05 import cli


if __name__ == "__main__":
    raise SystemExit(cli())

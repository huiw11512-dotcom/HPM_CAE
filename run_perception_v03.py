#!/usr/bin/env python3
"""Run the v0.3 robust coherent-multipath perception study."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from hpm_platform.workflows.perception_v03 import run


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default=str(ROOT / "configs" / "perception_v03.yaml"))
    parser.add_argument("--output", default=str(ROOT / "outputs_v03_perception"))
    args = parser.parse_args()
    metrics = run(args.config, args.output)
    print(json.dumps(metrics, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()

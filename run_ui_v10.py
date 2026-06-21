#!/usr/bin/env python3
"""Launch the local HPM-CAE V1.0 workbench."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from hpm_platform.ui.app import launch


def main() -> None:
    parser = argparse.ArgumentParser(description="Launch HPM-CAE Workbench V1.0")
    parser.add_argument("--host", default="127.0.0.1", help="Bind address")
    parser.add_argument("--port", type=int, default=7860, help="HTTP port")
    parser.add_argument("--no-browser", action="store_true", help="Do not open a browser")
    args = parser.parse_args()
    launch(server_name=args.host, server_port=args.port, inbrowser=not args.no_browser)


if __name__ == "__main__":
    main()

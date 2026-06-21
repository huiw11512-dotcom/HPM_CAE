#!/usr/bin/env python3
"""启动 HPM 数字化电磁算法 CAE V1.3 全中文工作台。"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from hpm_platform.ui.app_v13 import launch


def main() -> None:
    parser = argparse.ArgumentParser(description="启动 HPM 数字化电磁算法 CAE V1.3")
    parser.add_argument("--host", default="127.0.0.1", help="监听地址")
    parser.add_argument("--port", type=int, default=7860, help="监听端口")
    parser.add_argument("--no-browser", action="store_true", help="不自动打开浏览器")
    args = parser.parse_args()
    launch(server_name=args.host, server_port=args.port, inbrowser=not args.no_browser)


if __name__ == "__main__":
    main()

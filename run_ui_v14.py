#!/usr/bin/env python3
"""启动 HPM 数字化电磁算法 CAE V1.4 中文工作台。"""
from __future__ import annotations

import argparse
from pathlib import Path
import sys
import threading
import time
import webbrowser

import uvicorn

ROOT = Path(__file__).resolve().parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from hpm_platform.ui.app_v14 import create_app  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description="启动 HPM 数字化电磁算法 CAE V1.4")
    parser.add_argument("--host", default="127.0.0.1", help="监听地址")
    parser.add_argument("--port", type=int, default=7860, help="监听端口")
    parser.add_argument("--project", default=str(ROOT / "configs" / "cae_project_v14.yaml"), help="工程 YAML")
    parser.add_argument("--no-browser", action="store_true", help="不自动打开浏览器")
    args = parser.parse_args()
    if not args.no_browser:
        url = f"http://{args.host}:{args.port}"
        threading.Thread(target=lambda: (time.sleep(1.2), webbrowser.open(url)), daemon=True).start()
    uvicorn.run(create_app(args.project), host=args.host, port=args.port, log_level="info")


if __name__ == "__main__":
    main()

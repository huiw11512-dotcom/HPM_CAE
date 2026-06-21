#!/usr/bin/env python3
"""命令行运行 HPM 数字化电磁算法 CAE V2.0A 可信度验证体系。"""
from __future__ import annotations

import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from hpm_platform.validation.vv_runner import run_vv  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description="运行 V2.0A 可信度验证体系")
    parser.add_argument("--mode", choices=["fast", "full"], default="fast", help="运行模式")
    parser.add_argument("--project", default=str(ROOT / "configs" / "cae_project_v14.yaml"), help="工程 YAML")
    parser.add_argument("--output-dir", default=str(ROOT / "outputs_v20a_vv"), help="输出目录")
    args = parser.parse_args()
    result = run_vv(mode=args.mode, project_path=args.project, output_dir=args.output_dir)
    score = result["score"]
    summary = result["summary"]
    print("V2.0A 可信度验证完成")
    print(f"总测试数：{summary['总测试数']}，通过：{summary['通过数']}，失败：{summary['失败数']}")
    print(f"可信度评分：{score['可信度评分']}，等级：{score['当前等级']}")
    print(f"HTML报告：{result['outputs']['html']}")
    print(f"结果包：{result['outputs']['vv_results_zip']}")


if __name__ == "__main__":
    main()

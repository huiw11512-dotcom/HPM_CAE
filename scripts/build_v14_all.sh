#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
export PYTHONPATH="${PYTHONPATH:-}:$(pwd)/src"
python scripts/generate_v14_illustrations.py
pytest -q
python scripts/build_v14_preview.py
python scripts/build_v14_acceptance.py
printf 'V1.4 全部构建与验收完成。\n'

#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
python run_ui_v14.py "$@"

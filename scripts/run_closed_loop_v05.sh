#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
python run_closed_loop_v05.py "$@"

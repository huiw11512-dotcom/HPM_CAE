#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
python run_dynamic_field_control_v07.py "$@"

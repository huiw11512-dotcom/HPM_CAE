#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
python -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python run_demo.py
printf '\nOpen: %s\n' "$(pwd)/outputs/demo_report.html"

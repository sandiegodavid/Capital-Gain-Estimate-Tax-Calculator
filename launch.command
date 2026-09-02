#!/bin/zsh
set -e
APP_DIR="${0:A:h}"
cd "$APP_DIR"
if [[ -x .venv/bin/python ]]; then
  PYTHON=.venv/bin/python
else
  PYTHON="$(command -v python3)"
fi
"$PYTHON" capital_gain_estimate_tax_calculator.py

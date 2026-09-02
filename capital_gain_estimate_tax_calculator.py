#!/usr/bin/env python3
"""Entry point for the Capital Gain Estimate Tax Calculator web app."""

from __future__ import annotations

import sys
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent
VENDOR_DIR = APP_DIR / "vendor"
if VENDOR_DIR.exists():
    sys.path.insert(0, str(VENDOR_DIR))

from capital_gain_estimate_tax_calculator.cli import main


if __name__ == "__main__":
    raise SystemExit(main())

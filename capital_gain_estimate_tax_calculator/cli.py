"""Web-app launch entry point."""

from __future__ import annotations

import argparse
from typing import Sequence

from .web import run_web_app

APP_VERSION = "1.0.0"


def build_parser() -> argparse.ArgumentParser:
    """Build arguments required only to launch the local web server."""
    parser = argparse.ArgumentParser(description="Start the Capital Gain Estimate Tax Calculator web app.")
    parser.add_argument("--version", action="version", version=f"Capital Gain Estimate Tax Calculator {APP_VERSION}")
    parser.add_argument("--port", type=int, default=8765, help="Local web-server port (default: 8765).")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Start the web app; report generation is available in the browser."""
    args = build_parser().parse_args(argv)
    if not 1 <= args.port <= 65535:
        raise SystemExit("--port must be between 1 and 65535.")
    return run_web_app(port=args.port)

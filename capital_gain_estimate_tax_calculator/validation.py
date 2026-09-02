"""Validation shared by the web application and reporting engine."""

from __future__ import annotations

import argparse


def parse_year(value: str) -> int:
    """Validate a user-supplied calendar year."""
    try:
        year = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("Year must be a four-digit number.") from exc
    if not 1900 <= year <= 2200:
        raise argparse.ArgumentTypeError("Year must be between 1900 and 2200.")
    return year

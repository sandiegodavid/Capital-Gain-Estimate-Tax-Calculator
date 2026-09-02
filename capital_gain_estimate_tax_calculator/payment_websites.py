"""Official tax-payment destinations loaded from the bundled reference file."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml


REFERENCE_PATH = Path(__file__).resolve().parent.parent / "reference" / "income_tax_payment_websites.yaml"


@dataclass(frozen=True)
class PaymentWebsite:
    """One official payment website for a tax jurisdiction."""

    jurisdiction: str
    url: str


def payment_website(abbreviation: str) -> PaymentWebsite | None:
    """Return the official payment destination for a federal or state abbreviation."""
    try:
        entries = yaml.safe_load(REFERENCE_PATH.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError):
        return None
    if not isinstance(entries, list):
        return None
    for entry in entries:
        if not isinstance(entry, dict) or entry.get("abbreviation") != abbreviation:
            continue
        jurisdiction = entry.get("jurisdiction")
        url = entry.get("payment_url")
        if isinstance(jurisdiction, str) and isinstance(url, str) and url.startswith("https://"):
            return PaymentWebsite(jurisdiction, url)
    return None

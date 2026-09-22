"""Official tax-payment destinations embedded in jurisdiction tax data."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

TAX_DATA_ROOT = Path(__file__).resolve().parent.parent / "tax_data"


@dataclass(frozen=True)
class PaymentWebsite:
    """One official payment website for a tax jurisdiction."""

    jurisdiction: str
    url: str


def payment_website(abbreviation: str) -> PaymentWebsite | None:
    """Return the official payment destination for a federal or state abbreviation."""
    normalized = abbreviation.upper()
    if normalized == "US":
        path = TAX_DATA_ROOT / "federal" / "2026.yaml"
    elif len(normalized) == 2 and normalized.isalpha():
        path = TAX_DATA_ROOT / "states" / normalized.lower() / "2026.yaml"
    else:
        return None
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError):
        return None
    if not isinstance(data, dict):
        return None
    jurisdiction = data.get("jurisdiction")
    filing = data.get("filing")
    url = filing.get("payment_url") if isinstance(filing, dict) else None
    if isinstance(jurisdiction, str) and isinstance(url, str) and url.startswith("https://"):
        return PaymentWebsite(jurisdiction, url)
    return None

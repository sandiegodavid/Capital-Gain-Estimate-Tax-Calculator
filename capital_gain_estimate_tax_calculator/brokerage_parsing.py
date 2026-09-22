"""Shared parsing primitives used by brokerage CSV normalizers."""

from __future__ import annotations

import csv
import re
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

from .models import ZERO, ReportError

HEADER_SEARCH_ROWS = 5


@dataclass(frozen=True)
class CsvSource:
    """A CSV candidate and the path shown in the resulting report."""

    path: Path
    source_file: str

    def header_rows(self) -> tuple[tuple[str, ...], ...]:
        """Read only the rows needed to identify an export format."""
        try:
            with self.path.open("r", encoding="utf-8-sig", newline="") as handle:
                reader = csv.reader(handle)
                return tuple(tuple(next(reader, [])) for _ in range(HEADER_SEARCH_ROWS))
        except (OSError, UnicodeError, csv.Error) as exc:
            raise ReportError(f"Could not read CSV file: {self.path.name}") from exc


def parse_decimal(value: str | None) -> Decimal:
    """Parse brokerage currency and quantity fields into a normalized decimal."""
    text = (value or "").strip()
    if not text or text in {"--", "—", "N/A"}:
        return ZERO
    is_negative = text.startswith("(") and text.endswith(")")
    cleaned = re.sub(r"[$,+%\s()]", "", text)
    try:
        parsed = Decimal(cleaned) if cleaned else ZERO
    except InvalidOperation as exc:
        raise ReportError(f"Cannot parse numeric value {value!r}.") from exc
    return -parsed if is_negative else parsed


def parse_optional_decimal(value: str | None) -> Decimal | None:
    """Parse a field while preserving whether the brokerage left it unavailable."""
    text = (value or "").strip()
    if not text or text in {"--", "—", "N/A"}:
        return None
    return parse_decimal(text)


def parse_date(value: str | None) -> date:
    """Parse the date formats used by the supported brokerage exports."""
    text = (value or "").strip()
    for pattern in ("%m/%d/%Y", "%Y-%m-%d", "%m/%d/%y"):
        try:
            return datetime.strptime(text, pattern).date()
        except ValueError:
            pass
    raise ReportError(f"Cannot parse date value {value!r}.")


def row_from_values(headers: list[str], values: list[str]) -> dict[str, str]:
    """Create a complete row mapping when a CSV row has missing trailing cells."""
    return dict(zip(headers, (values + [""] * len(headers))[: len(headers)]))


def split_symbol_cusip(value: str, description: str) -> tuple[str, str]:
    """Split Fidelity's combined Symbol(CUSIP) value with its currency fallback."""
    match = re.match(r"^(.*?)\(([^()]*)\)$", value.strip())
    symbol, cusip = (match.group(1).strip(), match.group(2).strip()) if match else (value.strip(), "")
    if not symbol and "EURO" in description.upper():
        symbol = "EUR"
    return symbol or "N/A", cusip


def infer_security_type(symbol: str, description: str) -> str:
    """Classify source labels for report presentation, not tax treatment."""
    upper = description.upper()
    if upper.startswith("CALL ") or re.search(r"\d{6}C\d", symbol):
        return "Option"
    if "EURO" in upper:
        return "Currency"
    if "ETF" in upper or "INDEX FUND" in upper:
        return "ETF/Fund"
    if "MUTUAL" in upper:
        return "Mutual Fund"
    return "Stock/Other"

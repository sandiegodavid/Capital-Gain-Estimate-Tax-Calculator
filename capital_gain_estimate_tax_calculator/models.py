"""Domain types and calculation rules for realized investment gains."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Iterable

ZERO = Decimal("0")
CENT = Decimal("0.01")


class ReportError(Exception):
    """A user-actionable report generation error."""


@dataclass(frozen=True)
class Lot:
    source_name: str
    source_file: str
    source_row: int
    account: str
    symbol: str
    cusip: str
    description: str
    security_type: str
    quantity: Decimal
    acquired_date: date
    sale_date: date
    proceeds_usd: Decimal
    cost_basis_usd: Decimal
    short_term_gain_loss_usd: Decimal
    long_term_gain_loss_usd: Decimal
    total_realized_gain_loss_usd: Decimal
    disallowed_loss_usd: Decimal
    economic_gain_loss_usd: Decimal
    return_pct: Decimal
    tax_term: str


@dataclass(frozen=True)
class SourceSummary:
    source_name: str
    source_file: str
    recognized_rows: int
    included_rows: int
    earliest_sale: date | None
    latest_sale: date | None
    notes: str


@dataclass(frozen=True)
class NormalizedReport:
    report_year: int
    available_sale_years: tuple[int, ...]
    lots: tuple[Lot, ...]
    sources: tuple[SourceSummary, ...]
    ignored_csv_files: tuple[str, ...]

    def with_selected_sources(self, source_files: tuple[str, ...] | None) -> NormalizedReport:
        """Return this report limited to explicitly selected source-file paths."""
        if source_files is None:
            return self
        selected_files = frozenset(source_files)
        selected_lots = tuple(lot for lot in self.lots if lot.source_file in selected_files)
        if not selected_lots:
            raise ReportError("Select at least one source that contains realized gain/loss rows for this sale year.")
        return NormalizedReport(
            self.report_year,
            self.available_sale_years,
            selected_lots,
            self.sources,
            self.ignored_csv_files,
        )


def classify_tax_term(short_term: Decimal, long_term: Decimal, disallowed: Decimal) -> str:
    if short_term != 0 and long_term == 0:
        return "Short-Term"
    if long_term != 0 and short_term == 0:
        return "Long-Term"
    if short_term != 0 and long_term != 0:
        return "Mixed"
    if disallowed != 0:
        return "Wash Sale"
    return "None"


def totals(lots: Iterable[Lot]) -> dict[str, Decimal]:
    fields = (
        "proceeds_usd",
        "cost_basis_usd",
        "short_term_gain_loss_usd",
        "long_term_gain_loss_usd",
        "total_realized_gain_loss_usd",
        "disallowed_loss_usd",
        "economic_gain_loss_usd",
    )
    lot_list = list(lots)
    return {field: sum((getattr(lot, field) for lot in lot_list), ZERO) for field in fields}


def reconciliation_difference(lots: Iterable[Lot]) -> Decimal:
    values = totals(lots)
    return values["total_realized_gain_loss_usd"] - (
        values["proceeds_usd"] - values["cost_basis_usd"] + values["disallowed_loss_usd"]
    )


def validate_reconciliation(lots: Iterable[Lot]) -> None:
    difference = reconciliation_difference(lots)
    if abs(difference) > CENT:
        raise ReportError(
            "Reported gain/loss does not reconcile to proceeds - basis + disallowed loss. "
            f"Difference: ${difference.quantize(CENT)}."
        )

"""Translate submitted browser values into a validated tax profile input."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Mapping


@dataclass(frozen=True)
class TaxProfileInput:
    state_code: str
    filing_status: str
    qualified_children: int
    other_dependents: int
    state_eligible_dependents: int | None
    other_ordinary_taxable_income: Decimal
    short_term_carryover_loss: Decimal
    long_term_carryover_loss: Decimal


def parse_tax_profile(
    values: Mapping[str, list[str]], defaults: TaxProfileInput, filing_statuses: frozenset[str]
) -> TaxProfileInput:
    """Parse a browser form without consulting settings or tax rules."""

    def text(name: str, fallback: str = "") -> str:
        value = values.get(name, [fallback])
        return value[0] if value else fallback

    def count(name: str, fallback: int | None) -> int | None:
        raw = text(name, "" if fallback is None else str(fallback)).strip()
        if raw == "":
            return None
        try:
            return max(0, int(raw))
        except ValueError:
            return fallback

    def money(name: str, fallback: Decimal) -> Decimal:
        try:
            return max(
                Decimal("0"), Decimal(text(name, str(fallback)).replace(",", "").replace("$", "").strip() or "0")
            )
        except (InvalidOperation, AttributeError):
            return fallback

    status = text("filing_status", defaults.filing_status)
    return TaxProfileInput(
        text("state", defaults.state_code).upper(),
        status if status in filing_statuses else defaults.filing_status,
        count("qualified_children", defaults.qualified_children) or 0,
        count("other_dependents", defaults.other_dependents) or 0,
        count("state_eligible_dependents", defaults.state_eligible_dependents),
        money("other_ordinary_taxable_income", defaults.other_ordinary_taxable_income),
        money("short_term_carryover_loss", defaults.short_term_carryover_loss),
        money("long_term_carryover_loss", defaults.long_term_carryover_loss),
    )

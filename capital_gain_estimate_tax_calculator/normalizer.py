"""Read supported brokerage CSV files into a common, auditable domain model."""

from __future__ import annotations

import csv
import re
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

from .models import Lot, NormalizedReport, ReportError, SourceSummary, ZERO, classify_tax_term, validate_reconciliation


OUTPUT_DIRECTORY_NAMES = frozenset({"reports", "archive", "audit", "ai-rate-guidance"})


def parse_decimal(value: str | None) -> Decimal:
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


def parse_date(value: str | None):
    text = (value or "").strip()
    for pattern in ("%m/%d/%Y", "%Y-%m-%d", "%m/%d/%y"):
        try:
            return datetime.strptime(text, pattern).date()
        except ValueError:
            pass
    raise ReportError(f"Cannot parse date value {value!r}.")


def detect_schema(path: Path) -> str | None:
    """Select known brokerage mappers by filename before inspecting headers."""
    filename = path.name.casefold()
    if "chase" in filename:
        return "Chase"
    if "fidelity" in filename:
        return "Fidelity"
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            fields = {value.strip() for value in next(csv.reader(handle), [])}
    except (OSError, UnicodeError, csv.Error) as exc:
        raise ReportError(f"Could not read CSV file: {path.name}") from exc
    if {"Account Name", "Market Cost/Proceeds USD", "Total Realized Gain Loss USD"} <= fields:
        return "Chase"
    if {"Account", "Symbol(CUSIP)", "Short Term Gain/Loss", "Long Term Gain/Loss"} <= fields:
        return "Fidelity"
    return None


def normalize_chase(path: Path, source_file: str) -> list[Lot]:
    lots: list[Lot] = []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        for row_number, row in enumerate(csv.DictReader(handle), start=2):
            if not (row.get("Sale Date") or "").strip():
                continue
            proceeds = parse_decimal(row.get("Market Cost/Proceeds USD"))
            basis = parse_decimal(row.get("Cost Basis USD"))
            short_term = parse_decimal(row.get("Short Term Realized Gain Loss USD"))
            long_term = parse_decimal(row.get("Long Term Realized Gain Loss USD"))
            reported = parse_decimal(row.get("Total Realized Gain Loss USD"))
            disallowed = parse_decimal(row.get("Disallowed Loss"))
            lots.append(Lot(
                source_name="Chase", source_file=source_file, source_row=row_number,
                account=(row.get("Account Number") or "").strip(),
                symbol=(row.get("Ticker") or row.get("CUSIP") or "N/A").strip(),
                cusip=(row.get("CUSIP") or "").strip(),
                description=(row.get("Description") or "").strip(),
                security_type=(row.get("Security Type") or "Other").strip().title(),
                quantity=parse_decimal(row.get("Quantity")),
                acquired_date=parse_date(row.get("Acquired Date")), sale_date=parse_date(row.get("Sale Date")),
                proceeds_usd=proceeds, cost_basis_usd=basis,
                short_term_gain_loss_usd=short_term, long_term_gain_loss_usd=long_term,
                total_realized_gain_loss_usd=reported, disallowed_loss_usd=disallowed,
                economic_gain_loss_usd=proceeds - basis, return_pct=reported / basis if basis else ZERO,
                tax_term=classify_tax_term(short_term, long_term, disallowed),
            ))
    return lots


def split_symbol_cusip(value: str, description: str) -> tuple[str, str]:
    match = re.match(r"^(.*?)\(([^()]*)\)$", value.strip())
    symbol, cusip = (match.group(1).strip(), match.group(2).strip()) if match else (value.strip(), "")
    if not symbol and "EURO" in description.upper():
        symbol = "EUR"
    return symbol or "N/A", cusip


def fidelity_security_type(symbol: str, description: str) -> str:
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


def normalize_fidelity(path: Path, source_file: str) -> list[Lot]:
    lots: list[Lot] = []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.reader(handle)
        headers = next(reader, [])
        for row_number, values in enumerate(reader, start=2):
            if not values or not any(value.strip() for value in values):
                continue
            row = dict(zip(headers, (values + [""] * len(headers))[:len(headers)]))
            if not (row.get("Date Sold") or "").strip():
                continue
            description = (row.get("Security Description") or "").strip()
            symbol, cusip = split_symbol_cusip(row.get("Symbol(CUSIP)") or "", description)
            proceeds = parse_decimal(row.get("Proceeds"))
            basis = parse_decimal(row.get("Cost Basis"))
            short_term = parse_decimal(row.get("Short Term Gain/Loss"))
            long_term = parse_decimal(row.get("Long Term Gain/Loss"))
            reported = short_term + long_term
            lots.append(Lot(
                source_name="Fidelity", source_file=source_file, source_row=row_number,
                account=(row.get("Account") or "").strip(), symbol=symbol, cusip=cusip,
                description=description, security_type=fidelity_security_type(symbol, description),
                quantity=parse_decimal(row.get("Quantity")),
                acquired_date=parse_date(row.get("Date Acquired")), sale_date=parse_date(row.get("Date Sold")),
                proceeds_usd=proceeds, cost_basis_usd=basis,
                short_term_gain_loss_usd=short_term, long_term_gain_loss_usd=long_term,
                total_realized_gain_loss_usd=reported, disallowed_loss_usd=ZERO,
                economic_gain_loss_usd=proceeds - basis, return_pct=reported / basis if basis else ZERO,
                tax_term=classify_tax_term(short_term, long_term, ZERO),
            ))
    return lots


def source_note(schema: str) -> str:
    return (
        "Reported realized G/L may include a separately shown disallowed-loss adjustment."
        if schema == "Chase"
        else "Fidelity export is informational; trailing disclaimers are treated as source metadata only."
    )


def normalize_sources(input_dir: Path, requested_year: int | None = None) -> NormalizedReport:
    input_dir = input_dir.expanduser().resolve()
    if not input_dir.is_dir():
        raise ReportError(f"Input directory does not exist: {input_dir}")
    recognized: list[tuple[str, str, list[Lot]]] = []
    ignored: list[str] = []
    all_lots: list[Lot] = []
    for path in sorted(input_dir.rglob("*.csv")):
        relative_path = path.relative_to(input_dir)
        source_file = str(relative_path)
        if any(part.lower() in OUTPUT_DIRECTORY_NAMES for part in relative_path.parts[:-1]):
            ignored.append(source_file)
            continue
        schema = detect_schema(path)
        parser = {"Chase": normalize_chase, "Fidelity": normalize_fidelity}.get(schema)
        if parser is None:
            ignored.append(source_file)
            continue
        lots = parser(path, source_file)
        all_lots.extend(lots)
        recognized.append((source_file, schema, lots))
    if not all_lots:
        raise ReportError("No supported Chase or Fidelity realized gain/loss rows were found.")
    years = tuple(sorted({lot.sale_date.year for lot in all_lots}))
    report_year = requested_year if requested_year is not None else years[-1]
    selected = sorted(
        (lot for lot in all_lots if lot.sale_date.year == report_year),
        key=lambda lot: (lot.sale_date, lot.source_name, lot.symbol, lot.source_row),
    )
    if not selected:
        raise ReportError(f"No recognized realized gain/loss rows have sale year {report_year}. Available years: {', '.join(map(str, years))}.")
    summaries = tuple(
        SourceSummary(
            source_name=schema, source_file=source_file, recognized_rows=len(file_lots),
            included_rows=len(included := [lot for lot in file_lots if lot.sale_date.year == report_year]),
            earliest_sale=min((lot.sale_date for lot in included), default=None),
            latest_sale=max((lot.sale_date for lot in included), default=None), notes=source_note(schema),
        )
        for source_file, schema, file_lots in recognized
    )
    report = NormalizedReport(report_year, years, tuple(selected), summaries, tuple(ignored))
    validate_reconciliation(report.lots)
    return report

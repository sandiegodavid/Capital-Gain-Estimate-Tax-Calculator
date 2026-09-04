"""Read supported brokerage CSV files into a common, auditable domain model."""

from __future__ import annotations

import csv
import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from collections.abc import Iterable
from pathlib import Path

from .models import Lot, NormalizedReport, ReportError, SourceSummary, ZERO, classify_tax_term, validate_reconciliation


OUTPUT_DIRECTORY_NAMES = frozenset({"reports", "archive", "audit", "ai-rate-guidance"})
CHASE_SCHEMA = "Chase"
FIDELITY_SCHEMA = "Fidelity"
SCHWAB_SCHEMA = "Charles Schwab"
HEADER_SEARCH_ROWS = 5
CHASE_REQUIRED_HEADERS = frozenset({"Account Name", "Market Cost/Proceeds USD", "Total Realized Gain Loss USD"})
FIDELITY_REQUIRED_HEADERS = frozenset({"Account", "Symbol(CUSIP)", "Short Term Gain/Loss", "Long Term Gain/Loss"})
SCHWAB_REQUIRED_HEADERS = frozenset({"Symbol", "Closed Date", "Cost Basis (CB)", "Total Gain/Loss ($)"})
SCHEMA_BY_FILENAME = (("chase", CHASE_SCHEMA), ("fidelity", FIDELITY_SCHEMA), ("schwab", SCHWAB_SCHEMA))
SCHEMA_BY_HEADERS = ((CHASE_REQUIRED_HEADERS, CHASE_SCHEMA), (FIDELITY_REQUIRED_HEADERS, FIDELITY_SCHEMA), (SCHWAB_REQUIRED_HEADERS, SCHWAB_SCHEMA))


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


def parse_optional_decimal(value: str | None) -> Decimal | None:
    """Return a numeric CSV value, preserving whether the field was unavailable."""
    text = (value or "").strip()
    if not text or text in {"--", "—", "N/A"}:
        return None
    return parse_decimal(text)


def parse_date(value: str | None):
    text = (value or "").strip()
    for pattern in ("%m/%d/%Y", "%Y-%m-%d", "%m/%d/%y"):
        try:
            return datetime.strptime(text, pattern).date()
        except ValueError:
            pass
    raise ReportError(f"Cannot parse date value {value!r}.")


def _schema_from_filename(path: Path) -> str | None:
    filename = path.name.casefold()
    return next((schema for marker, schema in SCHEMA_BY_FILENAME if marker in filename), None)


def _schema_from_headers(header_rows: Iterable[list[str]]) -> str | None:
    for header_row in header_rows:
        fields = {value.strip() for value in header_row}
        for required_headers, schema in SCHEMA_BY_HEADERS:
            if required_headers <= fields:
                return schema
    return None


def detect_schema(path: Path) -> str | None:
    """Identify a supported brokerage export from its filename or CSV headers."""
    filename_schema = _schema_from_filename(path)
    if filename_schema:
        return filename_schema
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.reader(handle)
            header_rows = [next(reader, []) for _ in range(HEADER_SEARCH_ROWS)]
    except (OSError, UnicodeError, csv.Error) as exc:
        raise ReportError(f"Could not read CSV file: {path.name}") from exc
    return _schema_from_headers(header_rows)


def _row_from_values(headers: list[str], values: list[str]) -> dict[str, str]:
    return dict(zip(headers, (values + [""] * len(headers))[:len(headers)]))


def _create_lot(
    *,
    source_name: str,
    source_file: str,
    source_row: int,
    account: str,
    symbol: str,
    cusip: str,
    description: str,
    security_type: str,
    quantity: Decimal,
    acquired_date: date,
    sale_date: date,
    proceeds: Decimal,
    basis: Decimal,
    short_term: Decimal,
    long_term: Decimal,
    reported: Decimal,
    disallowed: Decimal,
    tax_term: str | None = None,
) -> Lot:
    """Create the common domain model after a brokerage mapper extracts its fields."""
    return Lot(
        source_name=source_name, source_file=source_file, source_row=source_row,
        account=account, symbol=symbol, cusip=cusip, description=description,
        security_type=security_type, quantity=quantity,
        acquired_date=acquired_date, sale_date=sale_date,
        proceeds_usd=proceeds, cost_basis_usd=basis,
        short_term_gain_loss_usd=short_term, long_term_gain_loss_usd=long_term,
        total_realized_gain_loss_usd=reported, disallowed_loss_usd=disallowed,
        economic_gain_loss_usd=proceeds - basis,
        return_pct=reported / basis if basis else ZERO,
        tax_term=tax_term or classify_tax_term(short_term, long_term, disallowed),
    )


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
            lots.append(_create_lot(
                source_name=CHASE_SCHEMA, source_file=source_file, source_row=row_number,
                account=(row.get("Account Number") or "").strip(),
                symbol=(row.get("Ticker") or row.get("CUSIP") or "N/A").strip(),
                cusip=(row.get("CUSIP") or "").strip(),
                description=(row.get("Description") or "").strip(),
                security_type=(row.get("Security Type") or "Other").strip().title(),
                quantity=parse_decimal(row.get("Quantity")),
                acquired_date=parse_date(row.get("Acquired Date")), sale_date=parse_date(row.get("Sale Date")),
                proceeds=proceeds, basis=basis, short_term=short_term, long_term=long_term,
                reported=reported, disallowed=disallowed,
            ))
    return lots


def split_symbol_cusip(value: str, description: str) -> tuple[str, str]:
    match = re.match(r"^(.*?)\(([^()]*)\)$", value.strip())
    symbol, cusip = (match.group(1).strip(), match.group(2).strip()) if match else (value.strip(), "")
    if not symbol and "EURO" in description.upper():
        symbol = "EUR"
    return symbol or "N/A", cusip


def infer_security_type(symbol: str, description: str) -> str:
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
            row = _row_from_values(headers, values)
            if not (row.get("Date Sold") or "").strip():
                continue
            description = (row.get("Security Description") or "").strip()
            symbol, cusip = split_symbol_cusip(row.get("Symbol(CUSIP)") or "", description)
            proceeds = parse_decimal(row.get("Proceeds"))
            basis = parse_decimal(row.get("Cost Basis"))
            short_term = parse_decimal(row.get("Short Term Gain/Loss"))
            long_term = parse_decimal(row.get("Long Term Gain/Loss"))
            reported = short_term + long_term
            lots.append(_create_lot(
                source_name=FIDELITY_SCHEMA, source_file=source_file, source_row=row_number,
                account=(row.get("Account") or "").strip(), symbol=symbol, cusip=cusip,
                description=description, security_type=infer_security_type(symbol, description),
                quantity=parse_decimal(row.get("Quantity")),
                acquired_date=parse_date(row.get("Date Acquired")), sale_date=parse_date(row.get("Date Sold")),
                proceeds=proceeds, basis=basis, short_term=short_term, long_term=long_term,
                reported=reported, disallowed=ZERO,
            ))
    return lots


def normalize_charles_schwab(path: Path, source_file: str) -> list[Lot]:
    """Normalize Schwab's realized gain/loss export, which includes a title row before headers."""
    lots: list[Lot] = []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.reader(handle)
        headers: list[str] | None = None
        header_row_number = 0
        for row_number, values in enumerate(reader, start=1):
            candidate = [value.strip() for value in values]
            if SCHWAB_REQUIRED_HEADERS <= set(candidate):
                headers = candidate
                header_row_number = row_number
                break
        if headers is None:
            raise ReportError(f"Could not find the Charles Schwab column headers in {path.name}.")
        for row_number, values in enumerate(reader, start=header_row_number + 1):
            row = _row_from_values(headers, values)
            if not (row.get("Closed Date") or "").strip():
                continue
            sale_date = parse_date(row.get("Closed Date"))
            proceeds = parse_decimal(row.get("Proceeds"))
            basis = parse_decimal(row.get("Cost Basis (CB)"))
            short_term_value = parse_optional_decimal(row.get("Short Term (ST) Gain/Loss ($)"))
            long_term_value = parse_optional_decimal(row.get("Long Term (LT) Gain/Loss ($)"))
            short_term = short_term_value if short_term_value is not None else ZERO
            long_term = long_term_value if long_term_value is not None else ZERO
            tax_term = _schwab_tax_term(short_term_value, long_term_value)
            reported = parse_decimal(row.get("Total Gain/Loss ($)"))
            disallowed = parse_decimal(row.get("Disallowed Loss"))
            symbol = (row.get("Symbol") or "N/A").strip()
            description = (row.get("Name") or "").strip()
            lots.append(_create_lot(
                source_name=SCHWAB_SCHEMA, source_file=source_file, source_row=row_number,
                account="", symbol=symbol, cusip="", description=description,
                security_type=infer_security_type(symbol, description),
                quantity=parse_decimal(row.get("Quantity")),
                acquired_date=sale_date, sale_date=sale_date,
                proceeds=proceeds, basis=basis, short_term=short_term, long_term=long_term,
                reported=reported, disallowed=disallowed, tax_term=tax_term,
            ))
    return lots


def _schwab_tax_term(short_term: Decimal | None, long_term: Decimal | None) -> str | None:
    """Use Schwab's populated gain/loss columns instead of inferring a holding period."""
    if short_term is not None and long_term is not None:
        return "Mixed"
    if short_term is not None:
        return "Short-Term"
    if long_term is not None:
        return "Long-Term"
    return None


def source_note(schema: str) -> str:
    if schema == CHASE_SCHEMA:
        return "Reported realized G/L may include a separately shown disallowed-loss adjustment."
    if schema == SCHWAB_SCHEMA:
        return "Charles Schwab does not include acquisition dates in this export; the closed date is used as a workbook placeholder."
    return "Fidelity export is informational; trailing disclaimers are treated as source metadata only."


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
        parser = {
            CHASE_SCHEMA: normalize_chase,
            FIDELITY_SCHEMA: normalize_fidelity,
            SCHWAB_SCHEMA: normalize_charles_schwab,
        }.get(schema)
        if parser is None:
            ignored.append(source_file)
            continue
        lots = parser(path, source_file)
        all_lots.extend(lots)
        recognized.append((source_file, schema, lots))
    if not all_lots:
        raise ReportError("No supported Chase, Fidelity, or Charles Schwab realized gain/loss rows were found.")
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

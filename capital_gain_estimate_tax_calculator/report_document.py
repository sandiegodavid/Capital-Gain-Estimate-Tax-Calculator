"""Pure report-content model built before any workbook formatting occurs."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from .models import NormalizedReport


@dataclass(frozen=True)
class SecuritySummaryRow:
    symbol: str
    description: str
    security_type: str


@dataclass(frozen=True)
class AccountSummaryRow:
    account: str
    source_name: str


@dataclass(frozen=True)
class WorkbookContent:
    """Human-readable workbook content independent of its Excel representation."""

    lots_title: str
    lots_subtitle: str
    lots_headers: tuple[str, ...]
    security_title: str
    security_subtitle: str
    security_headers: tuple[str, ...]
    checks_title: str
    checks_subtitle: str
    checks_headers: tuple[str, ...]
    source_notes_title: str
    source_notes_headers: tuple[str, ...]
    planning_note: str


@dataclass(frozen=True)
class AuditCheck:
    """An audit assertion the workbook renders using linked Excel cells."""

    code: str
    label: str
    tolerance: float
    note: str


@dataclass(frozen=True)
class ReportDocument:
    """Business content required to render a normalized annual report."""

    report: NormalizedReport
    sources_text: str
    lot_first_sale: date
    lot_last_sale: date
    securities: tuple[SecuritySummaryRow, ...]
    accounts: tuple[AccountSummaryRow, ...]
    report_months: tuple[int, ...]
    conventions: tuple[tuple[str, str], ...]
    content: WorkbookContent
    audit_checks: tuple[AuditCheck, ...]


class ReportBuilder:
    """Interpret normalized brokerage data without importing Excel libraries."""

    def build(self, report: NormalizedReport) -> ReportDocument:
        securities: dict[str, SecuritySummaryRow] = {}
        for lot in report.lots:
            securities.setdefault(
                lot.symbol,
                SecuritySummaryRow(lot.symbol, lot.description, lot.security_type),
            )
        accounts = tuple(
            AccountSummaryRow(account, source_name)
            for account, source_name in sorted({(lot.account, lot.source_name) for lot in report.lots}, reverse=True)
        )
        first_sale = min(lot.sale_date for lot in report.lots)
        last_sale = max(lot.sale_date for lot in report.lots)
        sources_text = " and ".join(sorted({lot.source_name for lot in report.lots}))
        return ReportDocument(
            report=report,
            sources_text=sources_text,
            lot_first_sale=first_sale,
            lot_last_sale=last_sale,
            securities=tuple(sorted(securities.values(), key=lambda item: item.symbol.upper())),
            accounts=accounts,
            report_months=tuple(range(1, max(lot.sale_date.month for lot in report.lots) + 1)),
            conventions=(
                ("Currency", "USD"),
                ("Period", f"{report.report_year} sale dates contained in the provided exports"),
                ("Total realized G/L", "Short-term G/L + long-term G/L, as reported by each export"),
                ("Economic G/L", "Proceeds − cost basis"),
                (
                    "Wash-sale treatment",
                    "Disallowed loss is shown separately and explains the difference between reported and economic G/L",
                ),
                (
                    "Use",
                    "Planning and review only; verify against year-end Forms 1099-B, account statements, and a tax professional",
                ),
            ),
            content=WorkbookContent(
                lots_title=f"{report.report_year} Realized Investment Gain/Loss — Tax Lots",
                lots_subtitle=(
                    f"USD amounts; {len(report.lots)} reported lots sold "
                    f"{first_sale:%Y-%m-%d} through {last_sale:%Y-%m-%d}."
                ),
                lots_headers=(
                    "Source",
                    "Account",
                    "Symbol",
                    "Security Description",
                    "Security Type",
                    "Quantity",
                    "Acquired",
                    "Sold",
                    "Proceeds",
                    "Cost Basis",
                    "Short-Term G/L",
                    "Long-Term G/L",
                    "Total Realized G/L",
                    "Disallowed Loss",
                    "Economic G/L",
                    "Return %",
                    "Tax Term",
                    "Source Row",
                ),
                security_title="Realized Gain/Loss by Security",
                security_subtitle="Formula-driven rollup with separate short- and long-term transaction counts and gain/loss amounts.",
                security_headers=(
                    "Symbol",
                    "Security Description",
                    "Type",
                    "Total Lots",
                    "Short-Term Lots",
                    "Long-Term Lots",
                    "Proceeds",
                    "Cost Basis",
                    "Short-Term G/L",
                    "Long-Term G/L",
                    "Total Realized G/L",
                    "Return %",
                ),
                checks_title="Audit Checks",
                checks_subtitle="Each check reconciles the consolidated report to the supplied source records.",
                checks_headers=("Check", "Actual", "Expected", "Difference", "Tolerance", "Status", "Notes"),
                source_notes_title="Source Notes & Reporting Conventions",
                source_notes_headers=("Source", "File", "Records", "Earliest Sale", "Latest Sale", "Notes"),
                planning_note=(
                    "Planning note: This report summarizes brokerage-export data and is not tax advice. "
                    "Verify final figures against year-end Forms 1099-B and brokerage statements; "
                    "wash-sale adjustments may change before year-end."
                ),
            ),
            audit_checks=self._audit_checks(report),
        )

    @staticmethod
    def _audit_checks(report: NormalizedReport) -> tuple[AuditCheck, ...]:
        checks = [
            AuditCheck(
                "transaction_count", "Transaction count", 0, "Consolidated lots equal the source record counts."
            ),
            AuditCheck(
                "reported_gain_loss",
                "Reported G/L reconciliation",
                0.01,
                "Reported G/L = proceeds − basis + disallowed loss.",
            ),
            AuditCheck(
                "tax_term_tie_out", "Short + long-term tie-out", 0.01, "Tax-term components equal total reported G/L."
            ),
            AuditCheck(
                "sale_dates",
                f"{report.report_year} sale dates",
                0,
                f"All included lots have {report.report_year} sale dates.",
            ),
            AuditCheck(
                "missing_proceeds_or_basis", "Missing proceeds/basis", 0, "No blank proceeds or cost-basis cells."
            ),
        ]
        checks.extend(
            AuditCheck(
                f"source_count:{source.source_name}",
                f"{source.source_name} source count",
                0,
                f"{source.source_name} normalized rows equal {source.source_name} export records.",
            )
            for source in report.sources
        )
        checks.extend(
            (
                AuditCheck(
                    "security_short_term",
                    "Security short-term summary tie-out",
                    0.01,
                    "Security Summary short-term G/L equals the lot-level short-term total.",
                ),
                AuditCheck(
                    "security_long_term",
                    "Security long-term summary tie-out",
                    0.01,
                    "Security Summary long-term G/L equals the lot-level long-term total.",
                ),
                AuditCheck(
                    "security_total",
                    "Security term total tie-out",
                    0.01,
                    "Security Summary total G/L equals short-term plus long-term columns.",
                ),
                AuditCheck(
                    "lot_numeric_types",
                    "Realized Lots numeric field types",
                    0,
                    "All populated quantity, date, amount, return, and source-row cells are true numeric/date values.",
                ),
                AuditCheck(
                    "security_numeric_types",
                    "Security Summary numeric field types",
                    0,
                    "All populated count, amount, and return formula cells are numeric so Excel sorts them by value.",
                ),
            )
        )
        return tuple(checks)

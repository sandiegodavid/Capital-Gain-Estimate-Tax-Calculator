"""Application service for creating auditable investment-gain reports."""

from __future__ import annotations

import shutil
from datetime import datetime
from pathlib import Path

from .audit import write_audit_files
from .excel_export import build_workbook
from .models import CENT, NormalizedReport, ReportError, reconciliation_difference, totals
from .normalizer import normalize_sources


def default_output_dir(input_dir: Path) -> Path:
    """Choose the standard report folder without creating it."""
    input_dir = input_dir.expanduser().resolve()
    return input_dir.parent / "reports" if input_dir.name.lower() == "source" else input_dir / "reports"


def report_summary(report: NormalizedReport, output_path: Path) -> dict[str, object]:
    """Build the concise machine-readable result returned to callers."""
    values = totals(report.lots)
    return {
        "report_year": report.report_year,
        "records": len(report.lots),
        "source_counts": {source: sum(lot.source_name == source for lot in report.lots) for source in sorted({lot.source_name for lot in report.lots})},
        "earliest_sale": min(lot.sale_date for lot in report.lots).isoformat(),
        "latest_sale": max(lot.sale_date for lot in report.lots).isoformat(),
        "totals_usd": {key: str(value.quantize(CENT)) for key, value in values.items()},
        "reconciliation_difference_usd": str(reconciliation_difference(report.lots).quantize(CENT)),
        "reconciliation_ok": abs(reconciliation_difference(report.lots)) <= CENT,
        "ignored_csv_files": list(report.ignored_csv_files),
        "output": str(output_path),
    }


def generate_report(
    input_dir: Path,
    year: int | None = None,
    output_dir: Path | None = None,
    overwrite: bool = False,
    backup_existing: bool = True,
    keep_audit_files: bool = False,
) -> tuple[Path, dict[str, object]]:
    """Normalize broker exports, produce the workbook, and optionally retain audit data."""
    report = normalize_sources(input_dir, year)
    destination_dir = (output_dir or default_output_dir(input_dir)).expanduser().resolve()
    output_path = destination_dir / f"{report.report_year}-investment-gain-report.xlsx"
    if output_path.exists() and not overwrite:
        raise ReportError(f"Report already exists: {output_path}. Use --overwrite to refresh it.")
    if output_path.exists() and overwrite and backup_existing:
        archive = destination_dir / "archive"
        archive.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        shutil.copy2(output_path, archive / f"{output_path.stem}-{stamp}{output_path.suffix}")
    build_workbook(report, output_path)
    summary = report_summary(report, output_path)
    if keep_audit_files:
        write_audit_files(report, destination_dir / "audit" / str(report.report_year), summary)
    return output_path, summary

"""Optional, source-auditable sidecar files for generated reports."""

from __future__ import annotations

import csv
import json
from dataclasses import asdict
from datetime import date
from decimal import Decimal
from pathlib import Path

from .models import Lot, NormalizedReport


def serialize_lot(lot: Lot) -> dict[str, str | int]:
    """Convert a normalized lot into CSV- and JSON-safe values."""
    values = asdict(lot)
    for key, value in list(values.items()):
        if isinstance(value, Decimal):
            values[key] = format(value, "f")
        elif isinstance(value, date):
            values[key] = value.isoformat()
    return values


def write_audit_files(report: NormalizedReport, audit_dir: Path, summary: dict[str, object]) -> None:
    """Persist normalized records and source provenance beside a report."""
    audit_dir.mkdir(parents=True, exist_ok=True)
    _write_normalized_lots(report, audit_dir / "normalized_realized_lots.csv")
    _write_source_manifest(report, audit_dir / "source_manifest.csv")
    (audit_dir / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")


def _write_normalized_lots(report: NormalizedReport, output_path: Path) -> None:
    records = [serialize_lot(lot) for lot in report.lots]
    with output_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(records[0]))
        writer.writeheader()
        writer.writerows(records)


def _write_source_manifest(report: NormalizedReport, output_path: Path) -> None:
    with output_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["source_name", "source_file", "recognized_rows", "included_rows", "earliest_sale", "latest_sale"])
        for source in report.sources:
            writer.writerow([source.source_name, source.source_file, source.recognized_rows, source.included_rows, source.earliest_sale.isoformat() if source.earliest_sale else "", source.latest_sale.isoformat() if source.latest_sale else ""])

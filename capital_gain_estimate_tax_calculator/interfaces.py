"""Narrow ports used by application services."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

from .report_document import ReportDocument
from .tax_rules import TaxRuleBundle


class TaxRuleRepository(Protocol):
    def load(
        self, year: int, state_code: str, filing_status: str, qualified_children: int = 0, other_dependents: int = 0
    ) -> TaxRuleBundle: ...


class SettingsRepository(Protocol):
    def load(self) -> dict[str, object]: ...
    def save(self, value: dict[str, object]) -> None: ...


class ReportWriter(Protocol):
    def write(self, document: ReportDocument, output_path: Path) -> None: ...


class FolderChooser(Protocol):
    def __call__(self, initial: Path | None = None) -> Path | None: ...

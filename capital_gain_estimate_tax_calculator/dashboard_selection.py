"""Build dashboard selections from browser input and common records layouts."""

from __future__ import annotations

import argparse
from collections.abc import Callable
from dataclasses import dataclass, replace
from pathlib import Path

from .service import default_output_dir
from .settings import available_report_years, realized_gains_root
from .validation import parse_year


FormValues = dict[str, list[str]]
RecordsRootProvider = Callable[[], Path | None]


@dataclass(frozen=True)
class DashboardSelection:
    """The source, destination, and optional sale year selected in the dashboard."""

    source_dir: Path
    output_dir: Path
    year: int | None

    def with_year(self, year: int) -> DashboardSelection:
        """Return this selection after data-based year detection."""
        return replace(self, year=year)


@dataclass(frozen=True)
class SourceFolderResolution:
    """A source folder and the year implied by its surrounding layout."""

    source_dir: Path
    inferred_year: int | None


class SourceFolderResolver:
    """Resolve supported records-root, year-folder, and source-folder layouts."""

    def resolve(self, path: Path, requested_year: int | None) -> SourceFolderResolution:
        """Resolve a path without recursively considering generated output folders."""
        path = path.expanduser()
        containing_year = _year_from_path(path.parent) if path.name.lower() == "source" else None
        if containing_year is not None:
            if requested_year is not None and requested_year != containing_year:
                return SourceFolderResolution(self._source_for_year(path.parent.parent, requested_year), requested_year)
            return SourceFolderResolution(path, containing_year)

        direct_year = _year_from_path(path)
        if direct_year is not None:
            if requested_year is not None and requested_year != direct_year:
                return SourceFolderResolution(self._source_for_year(path.parent, requested_year), requested_year)
            return SourceFolderResolution(self._source_inside_year_folder(path), direct_year)

        available_years = available_report_years(path)
        if available_years:
            year = requested_year if requested_year is not None else available_years[-1]
            return SourceFolderResolution(self._source_for_year(path, year), year)

        standard_source = path / "source"
        return SourceFolderResolution(standard_source if standard_source.is_dir() else path, requested_year)

    def _source_for_year(self, records_root: Path, year: int) -> Path:
        """Locate one year's source folder without falling into generated outputs."""
        return self._source_inside_year_folder(records_root / str(year))

    @staticmethod
    def _source_inside_year_folder(year_folder: Path) -> Path:
        source_folder = year_folder / "source"
        if source_folder.is_dir():
            return source_folder
        if year_folder.is_dir() and any(year_folder.glob("*.csv")):
            return year_folder
        return source_folder


class DashboardSelectionService:
    """Create selections while keeping configuration and folder resolution replaceable."""

    def __init__(
        self,
        records_root_provider: RecordsRootProvider = realized_gains_root,
        source_folder_resolver: SourceFolderResolver | None = None,
    ) -> None:
        self._records_root_provider = records_root_provider
        self._source_folder_resolver = source_folder_resolver or SourceFolderResolver()

    def from_form(self, values: FormValues) -> DashboardSelection | None:
        """Parse a load request, preserving a blank year for data-based detection."""
        root = self._records_root_provider()
        source_value = _form_value(values, "source", str(root) if root else "")
        if not source_value:
            return None

        requested_year = _optional_year(_form_value(values, "year"))
        resolution = self._source_folder_resolver.resolve(Path(source_value), requested_year)
        effective_year = requested_year if requested_year is not None else resolution.inferred_year
        output_value = _form_value(values, "output")
        output_dir = Path(output_value).expanduser() if output_value else default_output_dir(resolution.source_dir)
        return DashboardSelection(resolution.source_dir, output_dir, effective_year)


def selection_from_form(
    values: FormValues,
    configured_root: Path | None = None,
) -> DashboardSelection | None:
    """Compatibility entry point for converting dashboard form values."""
    if configured_root is None:
        return DashboardSelectionService().from_form(values)
    return DashboardSelectionService(lambda: configured_root).from_form(values)


def _form_value(values: FormValues, name: str, default: str = "") -> str:
    """Read one browser form value as trimmed text."""
    return values.get(name, [default])[0].strip()


def _optional_year(value: str) -> int | None:
    """Return a valid year when supplied; keep a blank selection for auto-detection."""
    if not value:
        return None
    try:
        return parse_year(value)
    except argparse.ArgumentTypeError:
        return None


def _year_from_path(path: Path) -> int | None:
    """Return a valid numeric year represented by a path component, if present."""
    try:
        return parse_year(path.name)
    except argparse.ArgumentTypeError:
        return None

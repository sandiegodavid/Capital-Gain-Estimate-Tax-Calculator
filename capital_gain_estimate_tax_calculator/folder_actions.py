"""Endpoint actions for choosing and initializing realized-gains folders."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from http import HTTPStatus
from pathlib import Path

from .finder import picker_start_folder
from .models import ReportError
from .web_http import FormValues

RecordsRootSaver = Callable[[Path], Path | None]
FinderFolderChooser = Callable[[Path | None], Path | None]
RecordsRootProvider = Callable[[], Path | None]
RecordsRootSkeletonCreator = Callable[[Path, int], Path]


@dataclass(frozen=True)
class FinderActionResult:
    """A callback payload independent of any HTTP request handler."""

    message: str
    ok: bool
    status: HTTPStatus = HTTPStatus.OK
    source: Path | None = None
    setup_parent: Path | None = None


@dataclass(frozen=True)
class FolderActions:
    """Coordinate Finder selection and standard records-layout creation."""

    records_root_saver: RecordsRootSaver
    finder_folder_chooser: FinderFolderChooser
    records_root_skeleton_creator: RecordsRootSkeletonCreator
    records_root_provider: RecordsRootProvider

    def choose_records_root(self, form: FormValues) -> FinderActionResult:
        root = None
        try:
            source_value = form.get("source", [""])[0].strip()
            initial_folder = picker_start_folder(source_value, self.records_root_provider())
            root = self.finder_folder_chooser(initial_folder)
            if root is None:
                return FinderActionResult("No folder was selected.", ok=True)
            saved_root = self.records_root_saver(root)
            return FinderActionResult("Realized gains folder saved.", ok=True, source=saved_root or root)
        except (ReportError, OSError, ValueError) as exc:
            return FinderActionResult(
                str(exc),
                ok=False,
                status=HTTPStatus.BAD_REQUEST,
                setup_parent=root,
            )

    def create_records_layout(self, form: FormValues) -> FinderActionResult:
        try:
            parent = Path(form.get("parent", [""])[0])
            year = int(form.get("year", [""])[0])
            records_root = self.records_root_skeleton_creator(parent, year)
            source_folder = records_root / str(year) / "source"
            return FinderActionResult(
                f"Folders are ready. Put brokerage CSV files in {source_folder}, then select Load data.",
                ok=True,
                source=records_root,
            )
        except (OSError, ValueError) as exc:
            return FinderActionResult(str(exc), ok=False, status=HTTPStatus.BAD_REQUEST)

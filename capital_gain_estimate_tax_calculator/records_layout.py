"""Rules for locating and creating the user's realized-gains folder layout."""

from __future__ import annotations

from pathlib import Path


REALIZED_GAINS_FOLDER_NAME = "Realized Gains"


def resolve_realized_gains_root(selected_folder: Path) -> Path:
    """Return a selected records root or its Realized Gains child folder."""
    selected_folder = selected_folder.expanduser().resolve()
    if not selected_folder.is_dir():
        raise ValueError("Choose an existing Realized Gains folder or its parent folder.")
    if selected_folder.name.casefold() == REALIZED_GAINS_FOLDER_NAME.casefold():
        return selected_folder
    records_root = selected_folder / REALIZED_GAINS_FOLDER_NAME
    if records_root.is_dir():
        return records_root
    raise ValueError("The selected folder does not contain a Realized Gains folder.")


def create_realized_gains_layout(parent_folder: Path, year: int) -> Path:
    """Create the standard year-specific source and report folders."""
    parent_folder = parent_folder.expanduser().resolve()
    if not parent_folder.is_dir():
        raise ValueError("Choose an existing folder before setting up the records layout.")
    if not 1900 <= year <= 2200:
        raise ValueError("Choose a valid sale year before setting up the records layout.")
    records_root = parent_folder / REALIZED_GAINS_FOLDER_NAME
    (records_root / str(year) / "source").mkdir(parents=True, exist_ok=True)
    (records_root / str(year) / "reports").mkdir(parents=True, exist_ok=True)
    return records_root

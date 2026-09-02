"""macOS Finder integration kept separate from the web application."""

from __future__ import annotations

import subprocess
from pathlib import Path

from .models import ReportError


def picker_start_folder(source_value: str, records_root: Path | None) -> Path | None:
    """Choose the most helpful Finder starting location for a source-folder change."""
    if not source_value.strip():
        return None
    if records_root is not None and records_root.is_dir():
        return records_root
    source_folder = Path(source_value).expanduser()
    return source_folder if source_folder.is_dir() else None


def _folder_picker_script(initial_folder: Path | None) -> str:
    """Build an AppleScript folder-picker command with an optional start location."""
    default_location = ""
    if initial_folder is not None and initial_folder.is_dir():
        escaped = str(initial_folder).replace("\\", "\\\\").replace('"', '\\"')
        default_location = f' default location POSIX file "{escaped}"'
    return f'POSIX path of (choose folder with prompt "Choose your realized gains folder"{default_location})'


def choose_folder_in_finder(initial_folder: Path | None = None) -> Path | None:
    """Show the native folder picker, starting at the current records root when available."""
    try:
        result = subprocess.run(
            ["osascript", "-e", _folder_picker_script(initial_folder)],
            check=False,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        raise ReportError("Finder could not be opened.") from exc
    if result.returncode == 1:
        return None
    if result.returncode != 0:
        raise ReportError("Finder could not choose a folder.")
    folder = Path(result.stdout.strip()).expanduser()
    if not folder.is_dir():
        raise ReportError("Finder did not return a valid folder.")
    return folder

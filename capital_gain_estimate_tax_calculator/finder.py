"""macOS Finder integration kept separate from the web application."""

from __future__ import annotations

import subprocess
from pathlib import Path

from .models import ReportError


def choose_folder_in_finder() -> Path | None:
    """Show the native folder picker and return its selected folder, if any."""
    try:
        result = subprocess.run(
            ["osascript", "-e", 'POSIX path of (choose folder with prompt "Choose your realized gains folder")'],
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

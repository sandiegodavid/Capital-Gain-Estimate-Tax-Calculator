"""Safe access to local dashboard static assets."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

STATIC_ROOT = Path(__file__).with_name("static")
CONTENT_TYPES = {".css": "text/css; charset=utf-8", ".js": "text/javascript; charset=utf-8"}


@dataclass(frozen=True)
class StaticAsset:
    payload: bytes
    content_type: str


def load_static_asset(request_path: str) -> StaticAsset | None:
    """Return a bundled asset for a simple `/static/name.ext` request only."""
    name = request_path.removeprefix("/static/")
    if not name or Path(name).name != name:
        return None
    path = STATIC_ROOT / name
    content_type = CONTENT_TYPES.get(path.suffix)
    if content_type is None or not path.is_file():
        return None
    return StaticAsset(path.read_bytes(), content_type)

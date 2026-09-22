"""Minimal HTTP parsing and response-writing adapters for the local web app."""

from __future__ import annotations

import json
from collections.abc import Mapping
from email.message import Message
from http import HTTPStatus
from pathlib import Path
from typing import Protocol
from urllib.parse import parse_qs

FormValues = dict[str, list[str]]


class HttpResponseWriter(Protocol):
    """The narrow subset of a request handler needed to send a response."""

    def send_response(self, code: int) -> None: ...
    def send_header(self, keyword: str, value: str) -> None: ...
    def end_headers(self) -> None: ...

    @property
    def wfile(self): ...


def query_form(query: str) -> FormValues:
    """Decode URL query data using the dashboard's existing parsing semantics."""
    return parse_qs(query)


def body_form(headers: Mapping[str, str] | Message[str, str], stream) -> FormValues:
    """Decode a URL-encoded request body from its declared content length."""
    length = int(headers.get("Content-Length", "0"))
    return parse_qs(stream.read(length).decode())


def send_html(handler: HttpResponseWriter, page: str, status: HTTPStatus = HTTPStatus.OK) -> None:
    """Send a UTF-8 HTML page with the correct content length."""
    send_bytes(handler, page.encode("utf-8"), "text/html; charset=utf-8", status)


def send_download(handler: HttpResponseWriter, path: Path) -> None:
    """Send one generated workbook as an attachment."""
    payload = path.read_bytes()
    handler.send_response(HTTPStatus.OK)
    handler.send_header("Content-Type", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    handler.send_header("Content-Disposition", f'attachment; filename="{path.name}"')
    handler.send_header("Content-Length", str(len(payload)))
    handler.end_headers()
    handler.wfile.write(payload)


def finder_result_page(
    message: str,
    ok: bool,
    source: Path | None = None,
    setup_parent: Path | None = None,
) -> str:
    """Build the same-origin callback page consumed by the folder-picker UI."""
    result = json.dumps(
        {
            "type": "finder-result",
            "message": message,
            "ok": ok,
            "source": str(source) if source else None,
            "setup_parent": str(setup_parent) if setup_parent else None,
        }
    )
    return f"<!doctype html><script>parent.postMessage({result}, window.location.origin)</script>"


def send_bytes(
    handler: HttpResponseWriter,
    payload: bytes,
    content_type: str,
    status: HTTPStatus = HTTPStatus.OK,
) -> None:
    handler.send_response(status)
    handler.send_header("Content-Type", content_type)
    handler.send_header("Content-Length", str(len(payload)))
    handler.end_headers()
    handler.wfile.write(payload)

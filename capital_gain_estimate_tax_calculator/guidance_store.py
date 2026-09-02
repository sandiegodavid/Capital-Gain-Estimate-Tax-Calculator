"""Local persistence for validated AI guidance response sets."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Protocol

import yaml

from .guidance_mapping import GuidanceResponse, validate_guidance_response
from .models import ReportError


@dataclass(frozen=True)
class SavedGuidanceResponse:
    """One validated response and its local storage metadata."""

    response: GuidanceResponse
    path: Path
    selected: bool


class GuidanceResponseRepository(Protocol):
    """Persistence boundary used by the guidance review service."""

    def save(
        self,
        output_dir: Path,
        year: int,
        provider_id: str,
        responses: list[GuidanceResponse],
        selected_index: int,
    ) -> tuple[Path, ...]: ...

    def load_all(self, output_dir: Path, year: int, provider_id: str) -> tuple[SavedGuidanceResponse, ...]: ...

    def load_selected(self, output_dir: Path, year: int, provider_id: str) -> SavedGuidanceResponse | None: ...


class GuidanceResponseStore:
    """Read and write independently selectable response files."""

    def save(
        self,
        output_dir: Path,
        year: int,
        provider_id: str,
        responses: list[GuidanceResponse],
        selected_index: int,
    ) -> tuple[Path, ...]:
        """Persist all reviewed candidates and mark the selected filename."""
        if not responses or not 0 <= selected_index < len(responses):
            raise ReportError("Choose one valid AI response before saving.")
        validated = [validate_guidance_response(response) for response in responses]
        directory = self._directory(output_dir)
        directory.mkdir(parents=True, exist_ok=True)
        self._remove_previous_candidates(directory, year, provider_id)

        saved_at = datetime.now().astimezone().isoformat(timespec="seconds")
        paths: list[Path] = []
        for index, response in enumerate(validated):
            selected = index == selected_index
            marker = "-selected" if selected else ""
            path = directory / f"{year}-{provider_id}-response-{index + 1}{marker}.yaml"
            payload = {
                "saved_at": saved_at,
                "provider": provider_id,
                "report_year": year,
                "selected": selected,
                "response": response,
            }
            path.write_text(yaml.safe_dump(payload, allow_unicode=True, sort_keys=False), encoding="utf-8")
            paths.append(path)
        return tuple(paths)

    def load_all(self, output_dir: Path, year: int, provider_id: str) -> tuple[SavedGuidanceResponse, ...]:
        """Load all saved responses for a provider and year."""
        directory = self._directory(output_dir)
        paths = sorted(directory.glob(f"{year}-{provider_id}-response-*.yaml")) if directory.is_dir() else []
        legacy_path = directory / f"{year}-{provider_id}-rate-guidance.json"
        if not paths and legacy_path.is_file():
            paths = [legacy_path]
        return tuple(self._read(path, len(paths) == 1) for path in paths)

    def load_selected(self, output_dir: Path, year: int, provider_id: str) -> SavedGuidanceResponse | None:
        """Load the marked response, or the first response if none is marked."""
        responses = self.load_all(output_dir, year, provider_id)
        return next((item for item in responses if item.selected), responses[0] if responses else None)

    @staticmethod
    def _directory(output_dir: Path) -> Path:
        return output_dir / "ai-rate-guidance"

    @staticmethod
    def _remove_previous_candidates(directory: Path, year: int, provider_id: str) -> None:
        for suffix in ("yaml", "json"):
            for old_path in directory.glob(f"{year}-{provider_id}-response-*.{suffix}"):
                old_path.unlink()

    @staticmethod
    def _read(path: Path, default_selected: bool) -> SavedGuidanceResponse:
        try:
            contents = path.read_text(encoding="utf-8")
            saved = yaml.safe_load(contents) if path.suffix == ".yaml" else json.loads(contents)
        except (OSError, json.JSONDecodeError, yaml.YAMLError) as exc:
            raise ReportError(f"Saved AI guidance could not be read: {path}") from exc
        response = saved.get("response") if isinstance(saved, dict) else None
        if not isinstance(response, dict):
            raise ReportError(f"Saved AI guidance has no usable response: {path}")
        return SavedGuidanceResponse(validate_guidance_response(response), path, bool(saved.get("selected", default_selected)))

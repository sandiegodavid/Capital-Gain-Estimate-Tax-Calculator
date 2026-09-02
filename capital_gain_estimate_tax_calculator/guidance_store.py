"""Local persistence for validated AI guidance response sets."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Protocol

import yaml

from .guidance_mapping import GuidanceResponse, validate_guidance_response
from .guidance_profile import GuidanceProfile
from .models import ReportError


@dataclass(frozen=True)
class SavedGuidanceResponse:
    """One validated response and its local storage metadata."""

    response: GuidanceResponse
    path: Path
    selected: bool
    profile: GuidanceProfile | None

    def assigned_to(self, profile: GuidanceProfile) -> SavedGuidanceResponse:
        """Attach the active profile to a legacy response that predates profile metadata."""
        return SavedGuidanceResponse(self.response, self.path, self.selected, profile)


class GuidanceResponseRepository(Protocol):
    """Persistence boundary used by the guidance review service."""

    def save(
        self,
        output_dir: Path,
        year: int,
        profile: GuidanceProfile,
        responses: list[GuidanceResponse],
        selected_index: int,
    ) -> tuple[Path, ...]: ...

    def load_all(self, output_dir: Path, year: int, profile: GuidanceProfile) -> tuple[SavedGuidanceResponse, ...]: ...

    def load_selected(self, output_dir: Path, year: int, profile: GuidanceProfile) -> SavedGuidanceResponse | None: ...


class GuidanceResponseStore:
    """Read and write independently selectable response files."""

    def save(
        self,
        output_dir: Path,
        year: int,
        profile: GuidanceProfile,
        responses: list[GuidanceResponse],
        selected_index: int,
    ) -> tuple[Path, ...]:
        """Persist all reviewed candidates and mark the selected filename."""
        if not responses or not 0 <= selected_index < len(responses):
            raise ReportError("Choose one valid AI response before saving.")
        validated = [validate_guidance_response(response) for response in responses]
        directory = self._directory(output_dir)
        directory.mkdir(parents=True, exist_ok=True)
        self._remove_previous_candidates(directory, year, profile)

        saved_at = datetime.now().astimezone().isoformat(timespec="seconds")
        paths: list[Path] = []
        for index, response in enumerate(validated):
            selected = index == selected_index
            path = directory / self._filename(year, profile, index, selected)
            payload = self._payload(saved_at, year, profile, selected, response)
            path.write_text(yaml.safe_dump(payload, allow_unicode=True, sort_keys=False), encoding="utf-8")
            paths.append(path)
        return tuple(paths)

    def load_all(self, output_dir: Path, year: int, profile: GuidanceProfile) -> tuple[SavedGuidanceResponse, ...]:
        """Load matching responses, falling back to one legacy provider/year set when needed."""
        directory = self._directory(output_dir)
        if not directory.is_dir():
            return ()
        current = self._load_current_candidates(directory, year, profile)
        if current is not None:
            return current
        return self._load_legacy_candidates(directory, year, profile)

    def load_selected(self, output_dir: Path, year: int, profile: GuidanceProfile) -> SavedGuidanceResponse | None:
        """Load the marked response, or the first response if none is marked."""
        responses = self.load_all(output_dir, year, profile)
        return next((item for item in responses if item.selected), responses[0] if responses else None)

    @staticmethod
    def _directory(output_dir: Path) -> Path:
        return output_dir / "ai-rate-guidance"

    @staticmethod
    def _remove_previous_candidates(directory: Path, year: int, profile: GuidanceProfile) -> None:
        pattern = f"{year}-{profile.storage_key}-response-*.yaml"
        for old_path in directory.glob(pattern):
            old_path.unlink()

    def _load_legacy_candidates(
        self,
        directory: Path,
        year: int,
        profile: GuidanceProfile,
    ) -> tuple[SavedGuidanceResponse, ...]:
        """Adapt pre-profile YAML responses to the active provider/year once for compatibility."""
        paths = sorted(directory.glob(f"{year}-{profile.provider_id}-response-*.yaml"))
        return tuple(item.assigned_to(profile) for item in self._read_paths(paths) if item.profile is None)

    def _load_current_candidates(
        self,
        directory: Path,
        year: int,
        profile: GuidanceProfile,
    ) -> tuple[SavedGuidanceResponse, ...] | None:
        """Load the current metadata-aware response set, when it exists."""
        paths = sorted(directory.glob(f"{year}-{profile.storage_key}-response-*.yaml"))
        if not paths:
            return None
        return tuple(item for item in self._read_paths(paths) if item.profile == profile)

    def _read_paths(self, paths: list[Path]) -> tuple[SavedGuidanceResponse, ...]:
        """Read one response set, defaulting a single unmarked item to selected."""
        return tuple(self._read(path, len(paths) == 1) for path in paths)

    @staticmethod
    def _filename(year: int, profile: GuidanceProfile, index: int, selected: bool) -> str:
        marker = "-selected" if selected else ""
        return f"{year}-{profile.storage_key}-response-{index + 1}{marker}.yaml"

    @staticmethod
    def _payload(
        saved_at: str,
        year: int,
        profile: GuidanceProfile,
        selected: bool,
        response: GuidanceResponse,
    ) -> dict[str, object]:
        return {
            "saved_at": saved_at,
            "provider": profile.provider_id,
            "report_year": year,
            "tax_profile": profile.as_dict(),
            "selected": selected,
            "response": response,
        }

    @staticmethod
    def _read(path: Path, default_selected: bool) -> SavedGuidanceResponse:
        try:
            contents = path.read_text(encoding="utf-8")
            saved = yaml.safe_load(contents)
        except (OSError, yaml.YAMLError) as exc:
            raise ReportError(f"Saved AI guidance could not be read: {path}") from exc
        response = saved.get("response") if isinstance(saved, dict) else None
        if not isinstance(response, dict):
            raise ReportError(f"Saved AI guidance has no usable response: {path}")
        return SavedGuidanceResponse(
            validate_guidance_response(response),
            path,
            bool(saved.get("selected", default_selected)),
            GuidanceProfile.from_dict(saved.get("tax_profile")) if isinstance(saved, dict) else None,
        )

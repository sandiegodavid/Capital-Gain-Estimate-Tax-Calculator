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
    source_provider: str = ""
    manually_updated: bool = False

@dataclass(frozen=True)
class _CandidateToSave:
    """A validated response paired with the review metadata that belongs to it."""

    response: GuidanceResponse
    source_provider: str
    manually_updated: bool


class GuidanceResponseRepository(Protocol):
    """Persistence boundary used by the guidance review service."""

    def save(
        self,
        output_dir: Path,
        year: int,
        profile: GuidanceProfile,
        responses: list[GuidanceResponse],
        selected_index: int,
        source_providers: list[str] | None = None,
        manually_updated: list[bool] | None = None,
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
        source_providers: list[str] | None = None,
        manually_updated: list[bool] | None = None,
    ) -> tuple[Path, ...]:
        """Persist all reviewed candidates and mark the selected filename."""
        if not responses or not 0 <= selected_index < len(responses):
            raise ReportError("Choose one valid AI response before saving.")
        candidates = self._candidates_to_save(responses, profile, source_providers, manually_updated)
        directory = self._directory(output_dir)
        directory.mkdir(parents=True, exist_ok=True)
        self._remove_previous_candidates(directory, year, profile)

        saved_at = datetime.now().astimezone().isoformat(timespec="seconds")
        return tuple(
            self._write_candidate(directory, saved_at, year, profile, index, index == selected_index, candidate)
            for index, candidate in enumerate(candidates)
        )

    def load_all(self, output_dir: Path, year: int, profile: GuidanceProfile) -> tuple[SavedGuidanceResponse, ...]:
        """Load responses for the tax context, regardless of their source provider."""
        directory = self._directory(output_dir)
        if not directory.is_dir():
            return ()
        return self._load_current_candidates(directory, year, profile) or ()

    def load_selected(self, output_dir: Path, year: int, profile: GuidanceProfile) -> SavedGuidanceResponse | None:
        """Load the marked response, or the first response if none is marked."""
        responses = self.load_all(output_dir, year, profile)
        return next((item for item in responses if item.selected), responses[0] if responses else None)

    @staticmethod
    def _directory(output_dir: Path) -> Path:
        return output_dir / "ai-rate-guidance"

    @staticmethod
    def _candidates_to_save(
        responses: list[GuidanceResponse],
        profile: GuidanceProfile,
        source_providers: list[str] | None,
        manually_updated: list[bool] | None,
    ) -> tuple[_CandidateToSave, ...]:
        validated = tuple(validate_guidance_response(response) for response in responses)
        providers = source_providers or [profile.provider_id] * len(validated)
        updates = manually_updated or [False] * len(validated)
        if len(providers) != len(validated):
            raise ReportError("Each reviewed response needs its source AI provider.")
        if len(updates) != len(validated):
            raise ReportError("Each reviewed response needs its edit status.")
        return tuple(
            _CandidateToSave(response, provider.strip().lower(), updated)
            for response, provider, updated in zip(validated, providers, updates, strict=True)
        )

    def _write_candidate(
        self,
        directory: Path,
        saved_at: str,
        year: int,
        profile: GuidanceProfile,
        index: int,
        selected: bool,
        candidate: _CandidateToSave,
    ) -> Path:
        path = directory / self._filename(year, profile, index, selected)
        payload = self._payload(
            saved_at,
            year,
            profile,
            selected,
            candidate.response,
            candidate.source_provider,
            candidate.manually_updated,
        )
        path.write_text(yaml.safe_dump(payload, allow_unicode=True, sort_keys=False), encoding="utf-8")
        return path

    def _remove_previous_candidates(self, directory: Path, year: int, profile: GuidanceProfile) -> None:
        for old_path in directory.glob(f"{year}-*-response-*.yaml"):
            try:
                saved = self._read(old_path, False)
            except ReportError:
                continue
            if saved.profile and saved.profile.matches_tax_context(profile):
                old_path.unlink()

    def _load_current_candidates(
        self,
        directory: Path,
        year: int,
        profile: GuidanceProfile,
    ) -> tuple[SavedGuidanceResponse, ...] | None:
        """Load the current metadata-aware response set, when it exists."""
        paths = sorted(directory.glob(f"{year}-*-response-*.yaml"))
        current = tuple(
            item
            for item in self._read_paths(paths)
            if item.profile and item.profile.matches_tax_context(profile)
        )
        if not current:
            return None
        return current

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
        source_provider: str,
        manually_updated: bool,
    ) -> dict[str, object]:
        return {
            "saved_at": saved_at,
            "source_ai_provider": source_provider,
            "report_year": year,
            "tax_profile": profile.as_dict(),
            "selected": selected,
            "manually_updated": manually_updated,
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
            str(saved.get("source_ai_provider") or saved.get("provider") or "") if isinstance(saved, dict) else "",
            bool(saved.get("manually_updated", False)) if isinstance(saved, dict) else False,
        )

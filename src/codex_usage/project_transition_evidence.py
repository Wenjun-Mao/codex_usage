from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

from codex_usage.project_identity import normalize_project_key

if TYPE_CHECKING:
    from codex_usage.project_transition_candidates import RawRepoPathCandidate


_WINDOWS_PATH_PATTERN = r"[A-Za-z]:[\\/](?:[^\\/:*?\"<>|\r\n`]+[\\/])*[^\\/:*?\"<>|\r\n`]+"
_DELIMITED_WINDOWS_PATH_PATTERN = re.compile(rf"(?P<delimiter>[`\"])(?P<path>{_WINDOWS_PATH_PATTERN})(?P=delimiter)")
_BARE_WINDOWS_PATH_PATTERN = re.compile(r"[A-Za-z]:[\\/](?:[^\\/:*?\"<>|\s\r\n`]+[\\/])*[^\\/:*?\"<>|\s\r\n`]+")
_POSIX_PATH_PATTERN = r"/(?:[^/\0\r\n`\"<>|]+/)*[^/\0\r\n`\"<>|]+"
_DELIMITED_POSIX_PATH_PATTERN = re.compile(rf"(?P<delimiter>[`\"])(?P<path>{_POSIX_PATH_PATTERN})(?P=delimiter)")
_BARE_POSIX_PATH_PATTERN = re.compile(r"(?<!:)/(?:[^/\s\r\n`\"<>|]+/)*[^/\s\r\n`\"<>|]+")
_TRAILING_PATH_PUNCTUATION = ".,;:)]}'\""


@dataclass(frozen=True)
class RepoPathObservation:
    raw_path: str
    resolved_path: str
    project_key: str
    project_label: str
    timestamp: datetime
    thread_id: str
    source: str

    def to_evidence_text(self) -> str:
        return (
            f"verified repo path {self.resolved_path} -> {self.project_key} "
            f"(thread {self.thread_id}, source {self.source})"
        )


def extract_repo_paths(text: str, *, preserve_exact_field: bool = False) -> list[str]:
    paths: list[str] = []
    seen: set[str] = set()
    candidates: list[tuple[int, str, bool]] = []
    occupied_spans: list[tuple[int, int]] = []

    for pattern in (_DELIMITED_WINDOWS_PATH_PATTERN, _DELIMITED_POSIX_PATH_PATTERN):
        for match in pattern.finditer(text):
            occupied_spans.append(match.span())
            candidates.append((match.start("path"), match.group("path"), False))

    for pattern in (_BARE_WINDOWS_PATH_PATTERN, _BARE_POSIX_PATH_PATTERN):
        for match in pattern.finditer(text):
            if any(start <= match.start() and match.end() <= end for start, end in occupied_spans):
                continue
            occupied_spans.append(match.span())
            candidates.append((match.start(), match.group(0), True))

    exact_path_field = _exact_path_field_candidate(text) if preserve_exact_field else None
    if exact_path_field is not None:
        start, end, value = exact_path_field
        candidates = [
            candidate
            for candidate in candidates
            if not (start <= candidate[0] and candidate[0] + len(candidate[1]) <= end)
        ]
        candidates.append((start, value, False))

    for _, candidate, trim_trailing_punctuation in sorted(candidates, key=lambda item: item[0]):
        value = candidate.rstrip(_TRAILING_PATH_PUNCTUATION) if trim_trailing_punctuation else candidate
        if value and value not in seen:
            seen.add(value)
            paths.append(value)
    return paths


def _exact_path_field_candidate(text: str) -> tuple[int, int, str] | None:
    return _exact_windows_path_field_candidate(text) or _exact_posix_path_field_candidate(text)


def _exact_windows_path_field_candidate(text: str) -> tuple[int, int, str] | None:
    stripped = text.strip()
    if not re.match(r"^[A-Za-z]:[\\/]", stripped) or not any(character.isspace() for character in stripped):
        return None
    if _DELIMITED_WINDOWS_PATH_PATTERN.search(stripped) or _DELIMITED_POSIX_PATH_PATTERN.search(stripped):
        return None

    windows_matches = [
        match
        for match in _BARE_WINDOWS_PATH_PATTERN.finditer(stripped)
        if match.start() == 0 or stripped[match.start() - 1].isspace()
    ]
    if len(windows_matches) != 1 or windows_matches[0].start() != 0:
        return None

    remainder = stripped[windows_matches[0].end() :]
    posix_remainder_matches = [
        match
        for match in _BARE_POSIX_PATH_PATTERN.finditer(remainder)
        if match.start() == 0 or remainder[match.start() - 1].isspace()
    ]
    if _BARE_WINDOWS_PATH_PATTERN.search(remainder) or posix_remainder_matches:
        return None

    start = len(text) - len(text.lstrip())
    return start, start + len(stripped), stripped


def _exact_posix_path_field_candidate(text: str) -> tuple[int, int, str] | None:
    stripped = text.strip()
    if not stripped.startswith("/") or not any(character.isspace() for character in stripped):
        return None
    if _DELIMITED_WINDOWS_PATH_PATTERN.search(stripped) or _DELIMITED_POSIX_PATH_PATTERN.search(stripped):
        return None
    if _BARE_WINDOWS_PATH_PATTERN.search(stripped):
        return None

    absolute_posix_matches = [
        match
        for match in _BARE_POSIX_PATH_PATTERN.finditer(stripped)
        if match.start() == 0 or stripped[match.start() - 1].isspace()
    ]
    if len(absolute_posix_matches) != 1 or absolute_posix_matches[0].start() != 0:
        return None

    start = len(text) - len(text.lstrip())
    return start, start + len(stripped), stripped


def extract_windows_paths(text: str) -> list[str]:
    return extract_repo_paths(text)


def verified_repo_observation_from_path(
    raw_path: str | Path,
    timestamp: datetime,
    thread_id: str,
    source: str,
) -> RepoPathObservation | None:
    raw_path_text = str(raw_path)
    try:
        path = Path(raw_path).expanduser()
        if not path.exists():
            return None
        resolved_path = path.resolve()
        project_key = normalize_project_key(str(resolved_path))
    except (OSError, RuntimeError, ValueError):
        return None

    if not project_key.startswith("https://"):
        return None

    return RepoPathObservation(
        raw_path=raw_path_text,
        resolved_path=str(resolved_path),
        project_key=project_key,
        project_label=_label_from_project_key(project_key),
        timestamp=timestamp,
        thread_id=thread_id,
        source=source,
    )


_VerifiedRepoDetails = tuple[str, str, str]
VerificationCache = dict[str, _VerifiedRepoDetails | None]


def verify_repo_path_candidates(
    candidates: Sequence[RawRepoPathCandidate],
    *,
    verification_cache: VerificationCache,
) -> list[RepoPathObservation]:
    observations: list[RepoPathObservation] = []
    for candidate in candidates:
        observation = _cached_verified_repo_observation(
            raw_path=candidate.raw_path,
            timestamp=candidate.timestamp,
            thread_id=candidate.thread_id,
            source=candidate.source,
            cache=verification_cache,
        )
        if observation is not None:
            observations.append(observation)
    return observations


def _cached_verified_repo_observation(
    raw_path: str,
    timestamp: datetime,
    thread_id: str,
    source: str,
    cache: VerificationCache,
) -> RepoPathObservation | None:
    if raw_path not in cache:
        observation = verified_repo_observation_from_path(
            raw_path=raw_path,
            timestamp=timestamp,
            thread_id=thread_id,
            source=source,
        )
        cache[raw_path] = (
            None
            if observation is None
            else (observation.resolved_path, observation.project_key, observation.project_label)
        )

    details = cache[raw_path]
    if details is None:
        return None

    resolved_path, project_key, project_label = details
    return RepoPathObservation(
        raw_path=raw_path,
        resolved_path=resolved_path,
        project_key=project_key,
        project_label=project_label,
        timestamp=timestamp,
        thread_id=thread_id,
        source=source,
    )


def _dedupe_observations(observations: list[RepoPathObservation]) -> list[RepoPathObservation]:
    unique: list[RepoPathObservation] = []
    seen: set[tuple[str, str, str, datetime]] = set()
    for observation in observations:
        key = (
            observation.thread_id,
            observation.project_key,
            observation.resolved_path,
            observation.timestamp,
        )
        if key in seen:
            continue
        seen.add(key)
        unique.append(observation)
    return sorted(unique, key=lambda item: (item.timestamp, item.thread_id, item.project_key, item.source))


def _label_from_project_key(value: str) -> str:
    cleaned = value.strip().rstrip("/").removesuffix(".git")
    return cleaned.rsplit("/", 1)[-1] or cleaned

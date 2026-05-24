from __future__ import annotations

import configparser
import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

from codex_usage.models import SessionMetadata
from codex_usage.settings import get_settings


@dataclass(frozen=True)
class ProjectIdentity:
    key: str
    label: str
    aliases: tuple[str, ...] = ()
    git_repository_url: str = ""


_EXTERNAL_PROJECT_PARENT_NAMES = frozenset({"external_projects", "zz_external_projects", "third_party", "vendor"})


def resolve_project_identity(metadata: SessionMetadata, project_aliases: Mapping[str, str] | None = None) -> ProjectIdentity:
    cwd_key = _normalize_path_text(metadata.cwd) if metadata.cwd else ""
    repo_url = metadata.git_repository_url.strip() or _origin_url_from_cwd(metadata.cwd)
    if repo_url:
        key = _normalize_repo_url(repo_url)
        return apply_project_aliases(
            ProjectIdentity(
                key=key,
                label=_label_from_repo_url(key),
                aliases=_dedupe_aliases([cwd_key], key),
                git_repository_url=key,
            ),
            project_aliases,
        )

    if cwd_key:
        return apply_project_aliases(ProjectIdentity(key=cwd_key, label=_label_from_path_text(metadata.cwd)), project_aliases)
    return apply_project_aliases(ProjectIdentity(key=metadata.session_id, label=metadata.session_id), project_aliases)


def apply_project_aliases(identity: ProjectIdentity, project_aliases: Mapping[str, str] | None = None) -> ProjectIdentity:
    aliases = project_aliases if project_aliases is not None else get_settings().project_aliases
    alias_map = _normalize_alias_map(aliases)
    if not alias_map:
        return identity

    original_key = normalize_project_key(identity.key)
    target_key = _resolve_alias_target(original_key, alias_map)
    if target_key == original_key:
        return ProjectIdentity(
            key=original_key,
            label=identity.label,
            aliases=_dedupe_aliases([*identity.aliases], original_key),
            git_repository_url=normalize_project_key(identity.git_repository_url) if identity.git_repository_url else "",
        )

    alias_values = [original_key, *identity.aliases]
    git_repository_url = target_key if _looks_like_repo_key(target_key) else identity.git_repository_url
    return ProjectIdentity(
        key=target_key,
        label=_label_from_repo_url(target_key) if _looks_like_repo_key(target_key) else _label_from_path_text(target_key),
        aliases=_dedupe_aliases(alias_values, target_key),
        git_repository_url=git_repository_url,
    )


def normalize_project_key(value: str) -> str:
    raw = value.strip()
    if not raw:
        return ""
    if _looks_like_github_shorthand(raw):
        return _clean_repo_key(f"https://github.com/{raw}")
    if _looks_like_repo_value(raw):
        return _normalize_repo_url(raw)

    origin_url = _origin_url_from_cwd(raw)
    if origin_url:
        return _normalize_repo_url(origin_url)

    return _normalize_path_text(raw)


def _origin_url_from_cwd(cwd: str) -> str:
    config_path = _find_git_config(cwd)
    if config_path is None:
        return ""
    parser = configparser.ConfigParser(interpolation=None)
    try:
        parser.read_string(config_path.read_text(encoding="utf-8", errors="ignore"))
    except (OSError, configparser.Error):
        return ""
    if not parser.has_section('remote "origin"'):
        return ""
    return parser.get('remote "origin"', "url", fallback="").strip()


def _find_git_config(cwd: str) -> Path | None:
    if not cwd:
        return None
    path = Path(cwd).expanduser()
    if not path.exists():
        return None

    current = path if path.is_dir() else path.parent
    project_boundary = _external_project_boundary(current)
    while True:
        config_path = _git_config_from_entry(current / ".git", current)
        if config_path is not None and config_path.is_file():
            return config_path
        if project_boundary is not None and current == project_boundary:
            return None
        if current.parent == current:
            return None
        current = current.parent


def _external_project_boundary(path: Path) -> Path | None:
    current = path
    while True:
        if current.name.casefold() in _EXTERNAL_PROJECT_PARENT_NAMES:
            return current
        if current.parent.name.casefold() in _EXTERNAL_PROJECT_PARENT_NAMES:
            return current
        if current.parent == current:
            return None
        current = current.parent


def _git_config_from_entry(git_entry: Path, repo_dir: Path) -> Path | None:
    if git_entry.is_dir():
        return git_entry / "config"
    if not git_entry.is_file():
        return None

    try:
        text = git_entry.read_text(encoding="utf-8", errors="ignore").strip()
    except OSError:
        return None
    if not text.casefold().startswith("gitdir:"):
        return None

    git_dir = Path(text.split(":", 1)[1].strip())
    if not git_dir.is_absolute():
        git_dir = repo_dir / git_dir
    return git_dir / "config"


def _normalize_repo_url(value: str) -> str:
    raw = value.strip().replace("\\", "/")
    scp_match = re.match(r"^[^@/]+@([^:]+):(.+)$", raw)
    if scp_match:
        return _clean_repo_key(f"https://{scp_match.group(1)}/{scp_match.group(2)}")

    parsed = urlparse(raw)
    if parsed.scheme in {"http", "https", "ssh", "git"} and parsed.hostname:
        path = parsed.path.lstrip("/")
        return _clean_repo_key(f"https://{parsed.hostname}/{path}")

    return _clean_repo_key(raw)


def _normalize_alias_map(values: Mapping[str, str]) -> dict[str, str]:
    alias_map: dict[str, str] = {}
    for source, target in values.items():
        source_key = normalize_project_key(str(source))
        target_key = normalize_project_key(str(target))
        if source_key and target_key and source_key != target_key:
            alias_map[source_key] = target_key
    return alias_map


def _resolve_alias_target(key: str, alias_map: Mapping[str, str]) -> str:
    current = key
    seen = {current}
    for _ in range(10):
        next_key = alias_map.get(current)
        if not next_key or next_key in seen:
            return current
        current = next_key
        seen.add(current)
    return current


def _looks_like_repo_value(value: str) -> bool:
    raw = value.strip()
    if re.match(r"^[^@/]+@[^:]+:.+$", raw):
        return True
    parsed = urlparse(raw)
    return parsed.scheme in {"http", "https", "ssh", "git"} and bool(parsed.hostname)


def _looks_like_repo_key(value: str) -> bool:
    return value.startswith("https://") or bool(re.match(r"^[^/\\:]+/[^/\\:]+$", value.strip()))


def _looks_like_github_shorthand(value: str) -> bool:
    return bool(re.match(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+(?:\.git)?$", value.strip()))


def _clean_repo_key(value: str) -> str:
    cleaned = value.strip().rstrip("/").casefold()
    return cleaned.removesuffix(".git")


def _label_from_repo_url(value: str) -> str:
    cleaned = value.strip().rstrip("/").removesuffix(".git")
    return cleaned.rsplit("/", 1)[-1] or cleaned


def _normalize_path_text(value: str) -> str:
    return value.replace("\\", "/").rstrip("/").casefold()


def _label_from_path_text(value: str) -> str:
    cleaned = value.replace("\\", "/").rstrip("/")
    return cleaned.rsplit("/", 1)[-1] or cleaned


def _dedupe_aliases(values: list[str], primary_key: str) -> tuple[str, ...]:
    aliases: list[str] = []
    seen = {primary_key}
    for value in values:
        if not value or value in seen:
            continue
        seen.add(value)
        aliases.append(value)
    return tuple(aliases)

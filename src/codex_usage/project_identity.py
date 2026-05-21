from __future__ import annotations

import configparser
import re
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

from codex_usage.models import SessionMetadata


@dataclass(frozen=True)
class ProjectIdentity:
    key: str
    label: str
    aliases: tuple[str, ...] = ()
    git_repository_url: str = ""


def resolve_project_identity(metadata: SessionMetadata) -> ProjectIdentity:
    cwd_key = _normalize_path_text(metadata.cwd) if metadata.cwd else ""
    repo_url = metadata.git_repository_url.strip() or _origin_url_from_cwd(metadata.cwd)
    if repo_url:
        key = _normalize_repo_url(repo_url)
        return ProjectIdentity(
            key=key,
            label=_label_from_repo_url(key),
            aliases=_dedupe_aliases([cwd_key], key),
            git_repository_url=key,
        )

    if cwd_key:
        return ProjectIdentity(key=cwd_key, label=_label_from_path_text(metadata.cwd))
    return ProjectIdentity(key=metadata.session_id, label=metadata.session_id)


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
    while True:
        config_path = _git_config_from_entry(current / ".git", current)
        if config_path is not None and config_path.is_file():
            return config_path
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

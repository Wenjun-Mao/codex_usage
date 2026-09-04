from __future__ import annotations

import configparser
import re
import subprocess
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
    uses_current_checkout_origin: bool = False


@dataclass(frozen=True)
class _GitCheckout:
    root: Path
    git_dir: Path
    common_dir: Path
    origin_url: str


_EXTERNAL_PROJECT_PARENT_NAMES = frozenset({"external_projects", "zz_external_projects", "third_party", "vendor"})


def resolve_project_identity(metadata: SessionMetadata) -> ProjectIdentity:
    cwd_key = _normalize_path_text(metadata.cwd) if metadata.cwd else ""
    recorded_repo_url = metadata.git_repository_url.strip()
    checkout = _checkout_from_cwd(metadata.cwd)
    current_origin_url = checkout.origin_url if checkout is not None else ""
    recorded_key = normalize_repository_key(recorded_repo_url)
    current_origin_key = normalize_repository_key(current_origin_url)

    if _verified_replacement(
        recorded_key,
        current_origin_key,
        metadata.git_commit_hash,
        checkout,
    ):
        return ProjectIdentity(
            key=current_origin_key,
            label=_label_from_repo_url(current_origin_key),
            aliases=_dedupe_aliases([cwd_key, recorded_key], current_origin_key),
            git_repository_url=current_origin_key,
            uses_current_checkout_origin=True,
        )

    repo_url = recorded_repo_url or current_origin_url
    if repo_url:
        key = normalize_repository_key(repo_url)
        return ProjectIdentity(
            key=key,
            label=_label_from_repo_url(key),
            aliases=_dedupe_aliases([cwd_key], key),
            git_repository_url=key,
        )

    if cwd_key:
        return ProjectIdentity(key=cwd_key, label=_label_from_path_text(metadata.cwd))
    return ProjectIdentity(key=metadata.session_id, label=metadata.session_id)


def normalize_project_key(value: str) -> str:
    raw = value.strip()
    if not raw:
        return ""
    if _looks_like_github_shorthand(raw):
        return normalize_repository_key(f"https://github.com/{raw}")
    if _looks_like_repo_value(raw):
        return normalize_repository_key(raw)

    origin_url = _origin_url_from_cwd(raw)
    if origin_url:
        return normalize_repository_key(origin_url)

    return _normalize_path_text(raw)


def normalize_declared_project_key(value: str) -> str:
    """Normalize serialized project metadata without inspecting the filesystem."""
    raw = value.strip()
    if not raw:
        return ""
    if _looks_like_github_shorthand(raw):
        return normalize_repository_key(f"https://github.com/{raw}")
    if _looks_like_repo_value(raw):
        return normalize_repository_key(raw)
    return _normalize_path_text(raw)


def normalize_repository_key(value: str) -> str:
    """Normalize a repository value without inspecting the filesystem."""
    raw = value.strip()
    return _normalize_repo_url(raw) if raw else ""


def is_git_project_key(value: str) -> bool:
    return _looks_like_repo_value(value.strip())


def _origin_url_from_cwd(cwd: str) -> str:
    checkout = _checkout_from_cwd(cwd)
    return checkout.origin_url if checkout is not None else ""


def _checkout_from_cwd(cwd: str) -> _GitCheckout | None:
    located = _find_git_checkout(cwd)
    if located is None:
        return None
    root, git_dir, common_dir = located
    origin_url = _origin_url_from_git_dirs(git_dir, common_dir)
    return _GitCheckout(root, git_dir, common_dir, origin_url)


def _find_git_config(cwd: str) -> Path | None:
    checkout = _find_git_checkout(cwd)
    if checkout is None:
        return None
    _root, git_dir, common_dir = checkout
    for path in (git_dir / "config", common_dir / "config"):
        if path.is_file():
            return path
    return None


def _find_git_checkout(cwd: str) -> tuple[Path, Path, Path] | None:
    """Locate the nearest checkout without crossing an external-project boundary."""
    if not cwd:
        return None
    path = Path(cwd).expanduser()
    if not path.exists():
        return None

    current = path if path.is_dir() else path.parent
    project_boundary = _external_project_boundary(current)
    while True:
        git_dir = _git_dir_from_entry(current / ".git", current)
        if git_dir is not None and git_dir.is_dir():
            try:
                root = current.resolve()
                resolved_git_dir = git_dir.resolve()
                common_dir = _git_common_dir(resolved_git_dir)
            except OSError:
                return None
            return root, resolved_git_dir, common_dir
        if project_boundary is not None and current == project_boundary:
            return None
        if current.parent == current:
            return None
        current = current.parent


def _origin_url_from_git_dirs(git_dir: Path, common_dir: Path) -> str:
    parser = configparser.ConfigParser(interpolation=None)
    try:
        config_paths = tuple(
            dict.fromkeys((common_dir / "config", git_dir / "config"))
        )
        for config_path in config_paths:
            if config_path.is_file():
                parser.read_string(
                    config_path.read_text(encoding="utf-8", errors="ignore")
                )
    except (OSError, configparser.Error):
        return ""
    if not parser.has_section('remote "origin"'):
        return ""
    return parser.get('remote "origin"', "url", fallback="").strip()


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


def _git_dir_from_entry(git_entry: Path, repo_dir: Path) -> Path | None:
    if git_entry.is_dir():
        return git_entry
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
    return git_dir


def _git_common_dir(git_dir: Path) -> Path:
    marker = git_dir / "commondir"
    if not marker.is_file():
        return git_dir
    try:
        configured = marker.read_text(encoding="utf-8", errors="ignore").strip()
    except OSError:
        return git_dir
    if not configured:
        return git_dir
    common_dir = Path(configured)
    if not common_dir.is_absolute():
        common_dir = git_dir / common_dir
    try:
        return common_dir.resolve()
    except OSError:
        return git_dir


def _verified_replacement(
    recorded_key: str,
    current_origin_key: str,
    commit_hash: str,
    checkout: _GitCheckout | None,
) -> bool:
    if (
        checkout is None
        or not recorded_key
        or not current_origin_key
        or recorded_key == current_origin_key
        or not _looks_like_commit_hash(commit_hash)
    ):
        return False
    try:
        result = subprocess.run(
            [
                "git",
                "-C",
                str(checkout.root),
                "merge-base",
                "--is-ancestor",
                commit_hash,
                "HEAD",
            ],
            check=False,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=2,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return result.returncode == 0


def _looks_like_commit_hash(value: str) -> bool:
    return bool(re.fullmatch(r"[0-9a-fA-F]{7,64}", value.strip()))


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


def _looks_like_repo_value(value: str) -> bool:
    raw = value.strip()
    if re.match(r"^[^@/]+@[^:]+:.+$", raw):
        return True
    parsed = urlparse(raw)
    return parsed.scheme in {"http", "https", "ssh", "git"} and bool(parsed.hostname)


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

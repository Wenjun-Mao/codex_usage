from __future__ import annotations

import os
import subprocess
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
LEGACY_OVERSIZED_FILES = {
    "src/codex_usage/session_cache.py",
    "tests/test_parser_aggregation.py",
    "tests/test_sync_planner.py",
    "tests/test_sync_store.py",
}


def test_changed_python_source_and_tests_stay_under_500_lines() -> None:
    oversized = {
        path.relative_to(REPOSITORY_ROOT).as_posix(): _line_count(path)
        for path in _guarded_python_files()
        if _line_count(path) >= 500
    }

    assert oversized == {}


def _guarded_python_files() -> tuple[Path, ...]:
    merge_base = _merge_base()
    if merge_base is None:
        return tuple(
            path
            for root in ("src", "tests", "scripts")
            for path in (REPOSITORY_ROOT / root).rglob("*.py")
            if path.relative_to(REPOSITORY_ROOT).as_posix()
            not in LEGACY_OVERSIZED_FILES
        )

    changed = _git_lines(
        "diff",
        "--name-only",
        "--diff-filter=ACMRT",
        merge_base,
        "--",
        "*.py",
    )
    changed.extend(
        _git_lines(
            "ls-files",
            "--others",
            "--exclude-standard",
            "--",
            "*.py",
        )
    )
    return tuple(
        path
        for relative in dict.fromkeys(changed)
        for path in (REPOSITORY_ROOT / relative,)
        if path.is_file()
    )


def _merge_base() -> str | None:
    base_refs = [
        os.environ.get("GITHUB_BASE_REF", "").strip(),
        "main",
        "origin/main",
    ]
    for base_ref in dict.fromkeys(ref for ref in base_refs if ref):
        result = subprocess.run(
            ["git", "merge-base", "HEAD", base_ref],
            cwd=REPOSITORY_ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
    return None


def _git_lines(*arguments: str) -> list[str]:
    result = subprocess.run(
        ["git", *arguments],
        cwd=REPOSITORY_ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    return [line for line in result.stdout.splitlines() if line]


def _line_count(path: Path) -> int:
    return len(path.read_text(encoding="utf-8").splitlines())

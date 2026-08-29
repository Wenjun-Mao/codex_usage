from __future__ import annotations

from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
LEGACY_OVERSIZED_FILES = {
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


def test_session_cache_facade_stays_under_500_lines() -> None:
    path = REPOSITORY_ROOT / "src" / "codex_usage" / "session_cache.py"
    assert _line_count(path) < 500


def _guarded_python_files() -> tuple[Path, ...]:
    return tuple(
        path
        for root in ("src", "tests", "scripts")
        for path in (REPOSITORY_ROOT / root).rglob("*.py")
        if path.relative_to(REPOSITORY_ROOT).as_posix()
        not in LEGACY_OVERSIZED_FILES
    )


def _line_count(path: Path) -> int:
    return len(path.read_text(encoding="utf-8").splitlines())

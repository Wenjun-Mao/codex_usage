from pathlib import Path

from codex_usage.discovery import candidate_session_dirs, collect_jsonl_files, find_session_dirs
from codex_usage.settings import AppSettings


def test_candidate_session_dirs_include_windows_and_home_paths(tmp_path: Path) -> None:
    home = tmp_path / "home" / "alice"
    userprofile = tmp_path / "Users" / "alice"
    candidates = candidate_session_dirs(
        codex_home=str(tmp_path / "codex-home"),
        userprofile=str(userprofile),
        home=home,
    )

    assert tmp_path / "codex-home" / "sessions" in candidates
    assert userprofile / ".codex" / "sessions" in candidates
    assert home / ".codex" / "sessions" in candidates


def test_find_session_dirs_uses_explicit_path(tmp_path: Path) -> None:
    sessions = tmp_path / "sessions"
    sessions.mkdir()

    found = find_session_dirs(sessions, AppSettings())

    assert found == [sessions]


def test_collect_jsonl_files_recurses_and_sorts(tmp_path: Path) -> None:
    sessions = tmp_path / "sessions"
    nested = sessions / "2026" / "04" / "29"
    nested.mkdir(parents=True)
    later = nested / "b.jsonl"
    earlier = nested / "a.jsonl"
    ignored = nested / "note.txt"
    later.write_text("{}", encoding="utf-8")
    earlier.write_text("{}", encoding="utf-8")
    ignored.write_text("{}", encoding="utf-8")

    files = collect_jsonl_files([sessions])

    assert files == [earlier, later]

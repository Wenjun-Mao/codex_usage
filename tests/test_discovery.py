from pathlib import Path

from codex_usage.discovery import candidate_session_dirs, collect_jsonl_files, default_session_dir, find_session_dirs


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


def test_find_session_dirs_uses_codex_home_without_manual_override(monkeypatch, tmp_path: Path) -> None:
    sessions = tmp_path / "codex-home" / "sessions"
    sessions.mkdir(parents=True)
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / "codex-home"))

    found = find_session_dirs()

    assert found == [sessions]


def test_default_session_dir_prefers_codex_home(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / "codex-home"))

    assert default_session_dir() == tmp_path / "codex-home" / "sessions"


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

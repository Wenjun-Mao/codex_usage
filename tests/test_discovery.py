import json
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


def test_find_session_dirs_includes_archived_sessions(monkeypatch, tmp_path: Path) -> None:
    codex_home = tmp_path / "codex-home"
    sessions = codex_home / "sessions"
    archived = codex_home / "archived_sessions"
    sessions.mkdir(parents=True)
    archived.mkdir(parents=True)
    monkeypatch.setenv("CODEX_HOME", str(codex_home))

    found = find_session_dirs()

    assert found == [sessions, archived]


def test_find_session_dirs_allows_archived_only_for_historical_reports(monkeypatch, tmp_path: Path) -> None:
    codex_home = tmp_path / "codex-home"
    archived = codex_home / "archived_sessions"
    archived.mkdir(parents=True)
    monkeypatch.setenv("CODEX_HOME", str(codex_home))

    found = find_session_dirs()

    assert found == [archived]


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


def test_collect_jsonl_files_dedupes_active_and_archived_by_file_key(tmp_path: Path) -> None:
    codex_home = tmp_path / "codex"
    sessions = codex_home / "sessions"
    archived = codex_home / "archived_sessions"
    active = _write_inventory_session(sessions, "thread-1", 100)
    _write_inventory_session(archived, "thread-1", 100)

    files = collect_jsonl_files([sessions, archived])

    assert files == [active]


def _write_inventory_session(root: Path, session_id: str, total: int) -> Path:
    day = root / "2026" / "05" / "27"
    day.mkdir(parents=True, exist_ok=True)
    path = day / f"rollout-{session_id}.jsonl"
    rows = [
        {"timestamp": "2026-05-27T10:00:00Z", "type": "session_meta", "payload": {"id": session_id}},
        {
            "timestamp": "2026-05-27T10:00:01Z",
            "type": "event_msg",
            "payload": {
                "type": "token_count",
                "info": {"total_token_usage": {"input_tokens": total, "total_tokens": total}},
            },
        },
    ]
    path.write_text("\n".join(json.dumps(row) for row in rows), encoding="utf-8")
    return path

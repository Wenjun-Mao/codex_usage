from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path

import pytest

from codex_usage.session_cache import CACHE_DB_NAME, load_cached_session_data
from codex_usage.session_inventory import (
    collect_session_file_inventory,
    session_file_key,
)


@pytest.mark.parametrize(
    "unreadable_is_newer",
    (False, True),
    ids=("canonical-newer", "fallback-newer"),
)
def test_exact_fallback_stem_and_canonical_id_both_survive_cold_and_warm_loads(
    tmp_path: Path,
    unreadable_is_newer: bool,
) -> None:
    sessions = tmp_path / "codex" / "sessions"
    valid = sessions / "nested" / "valid.jsonl"
    unreadable = sessions / "other" / "shared-session.jsonl"
    _write_usage_session(valid, "shared-session", total_tokens=123)
    unreadable.parent.mkdir(parents=True)
    unreadable.write_bytes(b"\xff\xfe")
    _order_mtimes(valid, unreadable, unreadable_is_newer=unreadable_is_newer)
    cache_dir = tmp_path / "cache"

    cold_inventory = collect_session_file_inventory([sessions])
    cold = load_cached_session_data(
        [sessions],
        cache_dir=cache_dir,
        auto_transitions=False,
        max_workers=1,
    )
    cold_keys = _file_keys_by_path(cache_dir)
    warm_inventory = collect_session_file_inventory([sessions])
    warm = load_cached_session_data(
        [sessions],
        cache_dir=cache_dir,
        auto_transitions=False,
        max_workers=1,
    )

    assert len(cold_inventory) == len(warm_inventory) == 2
    assert [(record.session_id, record.usage.total_tokens) for record in cold.records] == [
        ("shared-session", 123)
    ]
    assert warm.records == cold.records
    assert list(cold.file_errors) == [str(unreadable)]
    assert list(warm.file_errors) == [str(unreadable)]
    assert cold_keys[str(valid)] == "shared-session"
    assert cold_keys[str(unreadable)] != "shared-session"
    assert cold_keys[str(unreadable)].startswith("codex-usage:fallback:path:")
    assert _file_keys_by_path(cache_dir) == cold_keys
    assert warm.stats.files_reused == 2
    assert warm.stats.files_parsed == 0


def test_canonical_id_reserves_the_path_derived_fallback_key_globally(
    tmp_path: Path,
) -> None:
    sessions = tmp_path / "codex" / "sessions"
    unreadable = sessions / "unreadable.jsonl"
    unreadable.parent.mkdir(parents=True)
    unreadable.write_bytes(b"\xff\xfe")
    generated_fallback_key = session_file_key(unreadable)
    valid = sessions / "valid.jsonl"
    _write_usage_session(valid, generated_fallback_key, total_tokens=321)

    inventory = collect_session_file_inventory([sessions])
    entries = {entry.path: entry for entry in inventory}

    assert len(entries) == 2
    assert entries[valid].file_key == generated_fallback_key
    assert entries[valid].file_key_is_fallback is False
    assert entries[unreadable].file_key != generated_fallback_key
    assert entries[unreadable].file_key_is_fallback is True


def _file_keys_by_path(cache_dir: Path) -> dict[str, str]:
    with sqlite3.connect(cache_dir / CACHE_DB_NAME) as connection:
        return {
            str(path): str(file_key)
            for file_key, path in connection.execute(
                "select file_key, path from files order by path"
            )
        }


def _order_mtimes(
    valid: Path,
    unreadable: Path,
    *,
    unreadable_is_newer: bool,
) -> None:
    older = 1_700_000_000_000_000_000
    newer = older + 1_000_000_000
    valid_mtime, unreadable_mtime = (
        (older, newer) if unreadable_is_newer else (newer, older)
    )
    os.utime(valid, ns=(valid_mtime, valid_mtime))
    os.utime(unreadable, ns=(unreadable_mtime, unreadable_mtime))


def _write_usage_session(path: Path, thread_id: str, *, total_tokens: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = (
        {
            "timestamp": "2026-07-31T12:00:00Z",
            "type": "session_meta",
            "payload": {
                "id": thread_id,
                "timestamp": "2026-07-31T12:00:00Z",
                "cwd": "/repo/cache-keys",
            },
        },
        {
            "timestamp": "2026-07-31T12:00:01Z",
            "type": "event_msg",
            "payload": {
                "type": "token_count",
                "info": {
                    "total_token_usage": {
                        "input_tokens": total_tokens,
                        "cached_input_tokens": 0,
                        "output_tokens": 0,
                        "reasoning_output_tokens": 0,
                        "total_tokens": total_tokens,
                    }
                },
            },
        },
    )
    path.write_text(
        "".join(json.dumps(row, separators=(",", ":")) + "\n" for row in rows),
        encoding="utf-8",
    )

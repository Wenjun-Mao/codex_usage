from __future__ import annotations

import json
from pathlib import Path

import pytest

import codex_usage.storage_metadata as storage_metadata
from codex_usage.session_files import SessionMetadataRead
from codex_usage.storage_context import load_storage_context


def test_unreadable_storage_metadata_is_never_reused(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sessions = tmp_path / "codex" / "sessions"
    path = sessions / "2026" / "08" / "07" / "recoverable.jsonl"
    path.parent.mkdir(parents=True)
    path.write_text(
        json.dumps(
            {
                "type": "session_meta",
                "payload": {"id": "recoverable", "cwd": "/repo/recovered"},
            }
        )
        + "\n",
        encoding="utf-8",
    )
    cache_dir = tmp_path / "cache"
    original_read = storage_metadata.read_session_metadata_bounded
    calls = 0

    def transient_failure(candidate: Path):
        nonlocal calls
        if candidate == path:
            calls += 1
            if calls == 1:
                return SessionMetadataRead(None, "session_meta_unreadable")
        return original_read(candidate)

    monkeypatch.setattr(
        storage_metadata,
        "read_session_metadata_bounded",
        transient_failure,
    )
    cold = load_storage_context(session_dirs=[sessions], cache_dir=cache_dir)
    warm = load_storage_context(session_dirs=[sessions], cache_dir=cache_dir)

    assert cold.insights.task_trees[0].recovery_ready is False
    assert warm.insights.task_trees[0].recovery_ready is True
    assert warm.refresh_stats.metadata_reads == 1
    assert calls == 2

from __future__ import annotations

import os
import sqlite3
from pathlib import Path

import pytest

import codex_usage.agent_rebuild as rebuild_module
from codex_usage.agent_capture import capture_once
from codex_usage.agent_paths import ledger_database_path
from codex_usage.agent_rebuild import _staging_path, rebuild_stale_source_slice
from codex_usage.agent_rebuild_models import RebuildOutcome, RebuildReason
from codex_usage.ledger_queries import load_ledger_records, load_ledger_status
from codex_usage.session_files import read_session_metadata_bounded
from codex_usage.session_history import source_identity
from test_paginated_history import (
    PAGE,
    THREAD,
    corpus,
    meta,
    rollout_name,
    tokens,
    write_rows,
)

EXTERNAL_FORK = "33333333-3333-4333-8333-333333333333"


@pytest.mark.parametrize("external_base_fork", [False, True])
def test_paginated_rebuild_uses_owned_base_as_context_not_parse_work(
    tmp_path: Path,
    monkeypatch,
    external_base_fork: bool,
) -> None:
    home, legacy, target, source_key = _prepare_stale_source(
        tmp_path,
        filler_rows=24,
        external_base_fork=external_base_fork,
    )
    ledger = ledger_database_path(home)
    if external_base_fork:
        assert target.name == rollout_name(thread=EXTERNAL_FORK)
        assert source_key == EXTERNAL_FORK
    else:
        assert source_key == f"codex-usage:page:{PAGE}"
    assert _trusted_total(ledger) == 150

    observed = []
    inventory_scans = []
    original_refresh = rebuild_module.refresh_files
    original_collect = rebuild_module.collect_session_file_inventory

    def observe_refresh(connection, session_dirs, inventory, **kwargs):
        history_inventory = kwargs.get("history_inventory")
        observed.append((tuple(inventory), tuple(history_inventory or ())))
        return original_refresh(connection, session_dirs, inventory, **kwargs)

    def observe_inventory_scan(session_dirs, *, read_metadata=True):
        inventory_scans.append((tuple(session_dirs), read_metadata))
        return original_collect(session_dirs, read_metadata=read_metadata)

    monkeypatch.setattr(rebuild_module, "refresh_files", observe_refresh)
    monkeypatch.setattr(
        rebuild_module,
        "collect_session_file_inventory",
        observe_inventory_scan,
    )

    result = rebuild_stale_source_slice(home, source_key, max_bytes=384)
    rebuild_slices = 1
    assert not result.complete
    assert 0 < result.captured_bytes < result.target_bytes
    assert _trusted_total(ledger) == 150
    previous_captured = result.captured_bytes
    original_path_open = Path.open

    def reject_warm_ancestor_read(path, *args, **kwargs):
        if path == legacy:
            raise AssertionError("warm append must not reread inherited history")
        return original_path_open(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", reject_warm_ancestor_read)

    while not result.complete and rebuild_slices < 64:
        result = rebuild_stale_source_slice(home, source_key, max_bytes=384)
        rebuild_slices += 1
        assert result.captured_bytes > previous_captured
        previous_captured = result.captured_bytes
        if not result.complete:
            assert result.captured_bytes < result.target_bytes
            assert _trusted_total(ledger) == 150

    assert result.complete
    assert result.captured_bytes == result.target_bytes
    assert rebuild_slices < 64
    assert _trusted_total(ledger) == 175
    assert load_ledger_status(ledger).coverage.stale_sources == 0
    assert len(observed) == rebuild_slices
    assert len(inventory_scans) == rebuild_slices
    assert all(
        session_dirs == (home / "sessions",) and not read_metadata
        for session_dirs, read_metadata in inventory_scans
    )
    assert all(
        tuple(entry.path for entry in parsed) == (target,)
        for parsed, _ in observed
    )
    assert all(
        {entry.path for entry in context} == {legacy, target}
        and all(entry.file_key_is_fallback for entry in context)
        for _, context in observed
    )


def test_paginated_rebuild_without_owned_ancestor_keeps_named_gap_and_trusted_rows(
    tmp_path: Path,
) -> None:
    home, legacy, _, source_key = _prepare_stale_source(tmp_path)
    ledger = ledger_database_path(home)
    assert _trusted_total(ledger) == 150
    assert load_ledger_status(ledger).coverage.stale_sources == 1

    legacy.unlink()
    result = rebuild_stale_source_slice(home, source_key, max_bytes=384)

    assert not result.complete
    assert result.captured_bytes == 0
    assert result.outcome == RebuildOutcome.BLOCKED
    assert result.reason == RebuildReason.NO_PROGRESS
    assert _trusted_total(ledger) == 150
    assert load_ledger_status(ledger).coverage.stale_sources == 1
    with sqlite3.connect(_staging_path(home, source_key)) as connection:
        error = connection.execute(
            "select error from files where file_key = ?", (source_key,)
        ).fetchone()[0]
    assert "paginated_history_source_unavailable" in error


def _prepare_stale_source(
    tmp_path: Path,
    *,
    filler_rows: int = 0,
    external_base_fork: bool = False,
) -> tuple[Path, Path, Path, str]:
    home = tmp_path / ".codex"
    session_dir = home / "sessions" / "2026" / "10" / "13"
    legacy, target, base = corpus(session_dir)
    if external_base_fork:
        target.unlink()
        target = session_dir / rollout_name(thread=EXTERNAL_FORK)
        write_rows(
            target,
            [
                meta(
                    thread=EXTERNAL_FORK,
                    stamp="2026-10-13T02:00:00Z",
                    base=base,
                    forked_from_id=THREAD,
                    forked_from_ordinal_exclusive=base["end_ordinal_exclusive"],
                ),
                {
                    "type": "turn_context",
                    "ordinal": 3,
                    "payload": {"model": "gpt-6.1-sol", "turn_id": "turn"},
                },
                tokens(100, "2026-10-13T02:01:00Z", ordinal=4),
                tokens(150, "2026-10-13T02:02:00Z", ordinal=5),
            ],
        )
    assert capture_once(home, request_kind="manual", max_workers=1).outcome == "success"

    old_mtime_ns = target.stat().st_mtime_ns
    page_metadata = {
        "thread": EXTERNAL_FORK,
        "forked_from_id": THREAD,
        "forked_from_ordinal_exclusive": base["end_ordinal_exclusive"],
    } if external_base_fork else {}
    rows = [
        meta(stamp="2026-10-13T02:00:00Z", base=base, **page_metadata),
        {
            "type": "turn_context",
            "ordinal": 3,
            "payload": {"model": "gpt-6.1-sol", "turn_id": "turn"},
        },
        tokens(125, "2026-10-13T02:01:00Z", ordinal=4),
        tokens(175, "2026-10-13T02:02:00Z", ordinal=5),
    ]
    rows.extend(
        {
            "type": "unknown",
            "ordinal": ordinal,
            "payload": {"padding": "x" * 180},
        }
        for ordinal in range(6, 6 + filler_rows)
    )
    write_rows(target, rows)
    stat = target.stat()
    os.utime(
        target,
        ns=(stat.st_atime_ns, max(stat.st_mtime_ns, old_mtime_ns + 1_000_000_000)),
    )

    assert capture_once(home, request_kind="scheduled", max_workers=1).outcome == "success"
    metadata = read_session_metadata_bounded(target).metadata
    return home, legacy, target, source_identity(metadata)


def _trusted_total(ledger: Path) -> int:
    return sum(record.usage.total_tokens for record in load_ledger_records(ledger))

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from codex_usage.ledger_migration import (
    LegacyCacheCandidate,
    migrate_legacy_caches,
    plan_legacy_migration,
)
from codex_usage.ledger_migration_source import legacy_cache_digest
from codex_usage.ledger_queries import load_ledger_records
from codex_usage.ledger_schema import open_ledger
from codex_usage.session_cache import CACHE_DB_NAME, load_cached_session_data


def test_migration_merges_prefix_history_and_is_resumable(tmp_path: Path) -> None:
    first = _legacy_cache(tmp_path / "one", [100])
    second = _legacy_cache(tmp_path / "two", [100, 175])
    ledger = tmp_path / "home" / ".codex-usage" / "usage-ledger.sqlite3"
    with open_ledger(ledger):
        pass
    candidates = (
        LegacyCacheCandidate(first, legacy_cache_digest(first), "VS Code"),
        LegacyCacheCandidate(second, legacy_cache_digest(second), "VSCodium"),
    )

    plan = plan_legacy_migration(ledger, candidates)
    result = migrate_legacy_caches(ledger, candidates)
    repeated = migrate_legacy_caches(ledger, candidates)

    assert plan.conflicts == ()
    assert plan.importable_generations == 1
    assert plan.superseding_generations == 1
    assert [record.usage.total_tokens for record in load_ledger_records(ledger)] == [
        100,
        75,
    ]
    assert result["imported_caches"] == 2
    assert repeated["skipped_caches"] == 2


def test_migration_keeps_task_storage_diagnostics_disposable(tmp_path: Path) -> None:
    legacy = _legacy_cache(tmp_path / "legacy", [100])
    ledger = tmp_path / "home" / ".codex-usage" / "usage-ledger.sqlite3"
    with sqlite3.connect(legacy) as connection:
        assert connection.execute("select count(*) from storage_files").fetchone()[0]
    with open_ledger(ledger):
        pass

    migrate_legacy_caches(
        ledger,
        (LegacyCacheCandidate(legacy, legacy_cache_digest(legacy), "VS Code"),),
    )

    with sqlite3.connect(ledger) as connection:
        assert connection.execute("select count(*) from storage_files").fetchone()[0] == 0
        assert (
            connection.execute(
                "select count(*) from storage_content_diagnostics"
            ).fetchone()[0]
            == 0
        )


def test_migration_surfaces_divergent_history(tmp_path: Path) -> None:
    first = _legacy_cache(tmp_path / "one", [100, 175])
    second = _legacy_cache(tmp_path / "two", [100, 160])
    ledger = tmp_path / "ledger.sqlite3"
    with open_ledger(ledger):
        pass

    plan = plan_legacy_migration(
        ledger,
        (
            LegacyCacheCandidate(first, legacy_cache_digest(first), "VS Code"),
            LegacyCacheCandidate(second, legacy_cache_digest(second), "VSCodium"),
        ),
    )

    assert len(plan.conflicts) == 1
    assert plan.conflicts[0].file_key == "task-1"


def test_migration_does_not_deduplicate_different_usage_context(tmp_path: Path) -> None:
    first = _legacy_cache(tmp_path / "one", [100])
    second = _legacy_cache(tmp_path / "two", [100])
    with sqlite3.connect(second) as connection:
        connection.execute(
            "update usage_records set model = 'gpt-5.6-terra' where file_key = ?",
            ("task-1",),
        )
        connection.commit()
    ledger = tmp_path / "ledger.sqlite3"
    with open_ledger(ledger):
        pass

    plan = plan_legacy_migration(
        ledger,
        (
            LegacyCacheCandidate(first, legacy_cache_digest(first), "VS Code"),
            LegacyCacheCandidate(second, legacy_cache_digest(second), "VSCodium"),
        ),
    )

    assert len(plan.conflicts) == 1
    assert "usage context" in plan.conflicts[0].reason
    assert plan.conflicts[0].sources == (str(first), str(second))


def test_migration_obeys_selected_source_for_divergent_history(tmp_path: Path) -> None:
    first = _legacy_cache(tmp_path / "one", [100])
    second = _legacy_cache(tmp_path / "two", [100])
    with sqlite3.connect(second) as connection:
        connection.execute(
            "update usage_records set model = 'gpt-5.6-terra' where file_key = ?",
            ("task-1",),
        )
        connection.commit()
    _add_transition(first, "first-project")
    _add_transition(second, "second-project")
    ledger = tmp_path / "ledger.sqlite3"
    with open_ledger(ledger):
        pass
    candidates = (
        LegacyCacheCandidate(first, legacy_cache_digest(first), "VS Code"),
        LegacyCacheCandidate(second, legacy_cache_digest(second), "VSCodium"),
    )

    migrate_legacy_caches(
        ledger,
        candidates,
        precedence={"task-1": str(first)},
    )

    assert [record.model for record in load_ledger_records(ledger)] == [
        "gpt-5.6-sol"
    ]
    with open_ledger(ledger, read_only=True) as connection:
        transitions = connection.execute(
            "select target_key from project_transitions"
        ).fetchall()
    assert [str(row["target_key"]) for row in transitions] == ["first-project"]


def test_migration_does_not_deduplicate_different_task_metadata(
    tmp_path: Path,
) -> None:
    first = _legacy_cache(tmp_path / "one", [])
    second = _legacy_cache(tmp_path / "two", [])
    with sqlite3.connect(second) as connection:
        connection.execute(
            "update session_metadata set cwd = '/repo/other' where file_key = ?",
            ("task-1",),
        )
        connection.commit()
    ledger = tmp_path / "ledger.sqlite3"
    with open_ledger(ledger):
        pass

    plan = plan_legacy_migration(
        ledger,
        (
            LegacyCacheCandidate(first, legacy_cache_digest(first), "VS Code"),
            LegacyCacheCandidate(second, legacy_cache_digest(second), "VSCodium"),
        ),
    )

    assert len(plan.conflicts) == 1
    assert plan.conflicts[0].file_key == "task-1"


def test_migration_reads_committed_rows_from_live_wal(tmp_path: Path) -> None:
    legacy = _legacy_cache(tmp_path / "legacy", [100])
    writer = sqlite3.connect(legacy)
    writer.row_factory = sqlite3.Row
    try:
        writer.execute("pragma journal_mode = wal")
        writer.execute("pragma wal_autocheckpoint = 0")
        row = writer.execute(
            "select * from usage_records where file_key = 'task-1'"
        ).fetchone()
        columns = tuple(row.keys())
        values = dict(row)
        values.update(
            {
                "record_index": 1,
                "timestamp": "2026-09-02T10:03:00+00:00",
                "timestamp_us": 1788343380000000,
                "input_tokens": 75,
                "total_tokens": 75,
            }
        )
        writer.execute(
            f"insert into usage_records ({', '.join(columns)}) values "
            f"({', '.join('?' for _ in columns)})",
            tuple(values[column] for column in columns),
        )
        writer.commit()
        wal_path = legacy.with_name(legacy.name + "-wal")
        assert wal_path.stat().st_size > 0

        ledger = tmp_path / "home" / ".codex-usage" / "usage-ledger.sqlite3"
        with open_ledger(ledger):
            pass
        candidate = LegacyCacheCandidate(
            legacy,
            legacy_cache_digest(legacy),
            "VS Code",
        )
        migrate_legacy_caches(ledger, (candidate,))

        assert [
            record.usage.total_tokens for record in load_ledger_records(ledger)
        ] == [100, 75]
    finally:
        writer.close()


def _legacy_cache(root: Path, totals: list[int]) -> Path:
    sessions = root / "sessions"
    day = sessions / "2026" / "09" / "02"
    day.mkdir(parents=True)
    path = day / "rollout-task-1.jsonl"
    rows: list[dict[str, object]] = [
        {
            "timestamp": "2026-09-02T10:00:00Z",
            "type": "session_meta",
            "payload": {"id": "task-1", "cwd": "/repo/demo"},
        },
        {
            "timestamp": "2026-09-02T10:00:01Z",
            "type": "turn_context",
            "payload": {"model": "gpt-5.6-sol"},
        },
    ]
    for index, total in enumerate(totals):
        rows.append(
            {
                "timestamp": f"2026-09-02T10:0{index + 2}:00Z",
                "type": "event_msg",
                "payload": {
                    "type": "token_count",
                    "info": {
                        "total_token_usage": {
                            "input_tokens": total,
                            "total_tokens": total,
                        }
                    },
                },
            }
        )
    path.write_text("\n".join(json.dumps(row) for row in rows) + "\n")
    cache_dir = root / "cache"
    load_cached_session_data(
        [sessions], cache_dir=cache_dir, auto_transitions=False, max_workers=1
    )
    return cache_dir / CACHE_DB_NAME


def _add_transition(cache: Path, target_key: str) -> None:
    with sqlite3.connect(cache) as connection:
        connection.execute(
            """
            insert into project_transitions (
                owner_thread_id, source_key, source_label, target_key,
                target_label, effective_from, confidence, evidence_json,
                thread_ids_json
            ) values (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "task-1",
                "/repo/demo",
                "demo",
                target_key,
                target_key,
                "2026-09-02T10:00:00+00:00",
                100,
                "[]",
                '["task-1"]',
            ),
        )
        connection.commit()

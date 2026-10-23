"""Capture and report-cache writers share admission, without blocking readers."""
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
import threading

import pytest

from codex_usage import allowance_index, ledger_schema, session_cache
from codex_usage.agent_capture import capture_once
from codex_usage.agent_paths import ledger_database_path
from codex_usage.allowance_models import QuotaObservation
from codex_usage.allowance_probe import QuotaRead
from codex_usage.allowance_store import store_observations
from codex_usage.ledger_schema import ledger_revision, open_ledger


@pytest.mark.parametrize("injected_failure", [False, True])
def test_capture_waits_for_cold_report_writer_and_records_completion(tmp_path, monkeypatch, injected_failure):
    home = tmp_path / "home"
    (home / "sessions").mkdir(parents=True)
    path = ledger_database_path(home)
    stamp = datetime(2026, 10, 17, tzinfo=UTC).isoformat()
    with open_ledger(path) as writer:
        store_observations(writer, [QuotaObservation(stamp, "codex", "secondary", "pro", 10, 10080, None)],
            source_key="test", provenance="live")
        writer.commit()

    configured = ledger_schema.configure_ledger_connection

    def short_sqlite_wait(connection, **kwargs):
        configured(connection, **kwargs)
        connection.execute("pragma busy_timeout=25")

    monkeypatch.setattr(ledger_schema, "configure_ledger_connection", short_sqlite_wait)
    building, release = threading.Event(), threading.Event()
    original = allowance_index._build_from_costs

    def slow_build(*args, **kwargs):
        building.set()
        assert release.wait(5), "test did not release the report computation"
        return original(*args, **kwargs)

    monkeypatch.setattr(allowance_index, "_build_from_costs", slow_build)

    def report():
        with open_ledger(path, read_only=True) as reader:
            reader.execute("begin")
            return allowance_index.indexed_allowance_report(reader, path,
                revision=ledger_revision(reader), pricing_revision="test", coverage_complete=True)

    with ThreadPoolExecutor(max_workers=1) as pool:
        futures = []
        timers = []

        def probe(_):
            futures.append(pool.submit(report))
            assert building.wait(5)
            timer = threading.Timer(0.2, release.set)
            timers.append(timer)
            timer.start()
            return QuotaRead(stamp, diagnostics="test")

        monkeypatch.setattr("codex_usage.allowance_capture.probe_allowance", probe)
        if injected_failure:
            def fail_capture(*_):
                probe(home)
                raise ValueError("injected capture failure")
            monkeypatch.setattr("codex_usage.agent_capture.capture_quota_read", fail_capture)
        expected_outcome = "failed" if injected_failure else "success"
        expected_error = "ValueError: injected capture failure" if injected_failure else ""
        try:
            result = capture_once(home, request_kind="manual", max_workers=1)
            assert result.outcome == expected_outcome, result.error
            assert result.error == expected_error
        finally:
            release.set()
            for timer in timers:
                timer.join()
            for future in futures:
                future.result(timeout=5)
    with open_ledger(path, read_only=True) as reader:
        run = reader.execute("select outcome, completed_at, error from capture_runs").fetchone()
        assert run["outcome"] == expected_outcome and run["completed_at"]
        assert run["error"] == expected_error


@pytest.mark.parametrize("parser_writer", [False, True])
def test_same_database_writers_serialize_but_readers_remain_available(tmp_path, parser_writer):
    path = tmp_path / "ledger.sqlite3"
    with open_ledger(path):
        pass
    entered, attempted = threading.Event(), threading.Event()

    def other_writer():
        attempted.set()
        context = session_cache._open_cache_connection(path) if parser_writer else open_ledger(path)
        with context as writer:
            entered.set()
            writer.execute("insert or replace into ledger_meta values ('test', 'done')")
            writer.commit()

    with ThreadPoolExecutor(max_workers=1) as pool:
        with open_ledger(path):
            future = pool.submit(other_writer)
            assert attempted.wait(5)
            assert not entered.wait(0.1), "second writable connection bypassed admission"
            with open_ledger(path, read_only=True) as reader:
                assert ledger_revision(reader) == 0
        future.result(timeout=5)
    assert entered.is_set()


def test_other_databases_and_same_thread_nested_opens_do_not_deadlock(tmp_path):
    first, second = tmp_path / "first.sqlite3", tmp_path / "second.sqlite3"
    with open_ledger(first):
        with open_ledger(first):
            pass
        with ThreadPoolExecutor(max_workers=1) as pool:
            def write_other():
                with open_ledger(second) as writer:
                    return ledger_revision(writer)
            assert pool.submit(write_other).result(timeout=5) == 0


def test_admission_released_after_error_and_canonical_path_aliases_share_it(tmp_path):
    from codex_usage import sqlite_writer_admission
    path = tmp_path / "ledger.sqlite3"
    alias_directory = tmp_path / "alias"
    alias_directory.mkdir()
    alias = alias_directory / ".." / path.name
    with pytest.raises(ValueError, match="injected"):
        with open_ledger(path):
            assert path.resolve() in sqlite_writer_admission._writers
            with open_ledger(alias):
                assert len(sqlite_writer_admission._writers) == 1
            raise ValueError("injected")
    assert path.resolve() not in sqlite_writer_admission._writers
    with ThreadPoolExecutor(max_workers=1) as pool:
        def reopen():
            with open_ledger(alias) as writer:
                return ledger_revision(writer)
        assert pool.submit(reopen).result(timeout=5) == 0


@pytest.mark.parametrize("bump_revision", [False, True])
def test_capture_can_commit_during_preparation_and_stale_publication_is_discarded(tmp_path, monkeypatch, bump_revision):
    from codex_usage.ledger_schema import increment_ledger_revision
    from codex_usage.allowance_queries import build_allowance_report
    path = tmp_path / "ledger.sqlite3"
    stamp = datetime(2026, 10, 17, tzinfo=UTC).isoformat()
    with open_ledger(path) as writer:
        store_observations(writer, [QuotaObservation(stamp, "codex", "secondary", "pro", 10, 10080, None)],
            source_key="test", provenance="live")
        writer.commit()
    building, release = threading.Event(), threading.Event()
    original = allowance_index._build_from_costs

    def slow_build(*args, **kwargs):
        building.set()
        assert release.wait(5)
        return original(*args, **kwargs)

    monkeypatch.setattr(allowance_index, "_build_from_costs", slow_build)

    def report():
        with open_ledger(path, read_only=True) as reader:
            reader.execute("begin")
            oracle = build_allowance_report(reader)
            actual = allowance_index.indexed_allowance_report(reader, path,
                revision=ledger_revision(reader), pricing_revision="test", coverage_complete=True,
                status=oracle["status"])
            assert actual == oracle

    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(report)
        try:
            assert building.wait(5)
            with open_ledger(path) as writer:
                writer.execute("update quota_observations set used_percent=20")
                if bump_revision:
                    increment_ledger_revision(writer)
                writer.commit()
        finally:
            release.set()
        future.result(timeout=5)
    with open_ledger(path, read_only=True) as reader:
        assert reader.execute("select count(*) from allowance_report_cache").fetchone()[0] == 0

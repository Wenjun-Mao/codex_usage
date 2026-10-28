"""Project speed queries retain released values with query-local metadata reuse."""
from datetime import UTC, timedelta
from unittest.mock import patch

import pytest

from codex_usage.agent_capture import capture_once
from codex_usage.agent_paths import ledger_database_path
from codex_usage.aggregation import resolve_report_range
from codex_usage.ledger_schema import open_ledger
from codex_usage import ledger_record_materialization as materialization
from codex_usage import speed_queries as queries
from codex_usage.speed_store import touch
from speed_test_support import AT, append_rows, response, write_source
import speed_2_13_2_oracle as released


@pytest.fixture
def ledger(tmp_path, monkeypatch):
    monkeypatch.setattr("codex_usage.agent_capture.capture_quota_read", lambda *a: None)
    for task, cwd, age in (("parent", "/synthetic/one", 0),
                           ("child", "/synthetic/two", 0),
                           ("old", "/synthetic/unrelated", 90)):
        path = write_source(tmp_path, task=task, cwd=cwd, count=0)
        for index in range(12):
            rows = response(index, at=AT-timedelta(days=age),
                            model="gpt-6.1-terra" if index % 2 else "gpt-6.1-sol",
                            response_id=f"{task}-{index}")
            rows[0]["payload"]["effort"] = "high" if index % 3 else "medium"
            append_rows(path, rows)
    assert capture_once(tmp_path, request_kind="manual", max_workers=1).outcome == "success"
    return ledger_database_path(tmp_path)


def compare(connection, selected, projects, *, auto_transitions=True):
    records = {"released": [], "candidate": []}
    original_old, original_new = released._row_to_usage_record, queries._row_to_usage_record

    def old(row, metadata=None):
        record = original_old(row, metadata)
        records["released"].append(record)
        return record

    def new(row, metadata=None):
        record = original_new(row, metadata)
        records["candidate"].append(record)
        return record

    sql = []
    connection.set_trace_callback(sql.append)
    try:
        with patch.object(released, "_row_to_usage_record", old):
            expected = released.speed_aggregates(connection, selected, projects, UTC,
                                                 auto_transitions=auto_transitions)
        before = list(sql)
        sql.clear()
        with patch.object(queries, "_row_to_usage_record", new):
            actual = queries.speed_aggregates(connection, selected, projects, UTC,
                                              auto_transitions=auto_transitions)
        assert sql == before, "Metadata reuse must introduce no extra SQL or mutation"
    finally:
        connection.set_trace_callback(None)
    assert actual == expected
    assert records["candidate"] == records["released"]
    return actual, records["candidate"]


@pytest.mark.parametrize("projects", [[], ["shared-alias"], ["  shared-alias  "], ["   "], ["moved"], ["absent"]])
@pytest.mark.parametrize("auto_transitions", [False, True])
def test_every_record_and_aggregate_matches_released_oracle(ledger, projects, auto_transitions):
    selected = resolve_report_range("30d", UTC, now=AT+timedelta(hours=1))
    with open_ledger(ledger) as connection:
        connection.execute("update ledger_contexts set project_aliases_json='[\"shared-alias\"]'")
        connection.execute("update ledger_usage_events set usage_role='subagent', parent_task_id='parent' "
                           "where task_id='child'")
        key = connection.execute("""select p.project_key from ledger_projects p
            join ledger_contexts c using(project_id) join ledger_usage_events e using(context_id)
            where e.task_id='child' limit 1""").fetchone()[0]
        connection.execute("""insert into ledger_transitions(owner_task_id,source_key,source_label,
            target_key,target_label,effective_from,confidence,evidence_json,task_ids_json)
            values ('child',?,'Before','moved','After',?,100,'[]','["child"]')""",
            (key, (AT+timedelta(seconds=150)).isoformat()))
        touch(connection)
        _, records = compare(connection, selected, projects, auto_transitions=auto_transitions)
        assert len(records) == (24 if projects else 0)


def test_conversions_scale_with_selected_contexts_and_paths(ledger, monkeypatch):
    selected = resolve_report_range("30d", UTC, now=AT+timedelta(hours=1))
    with open_ledger(ledger, read_only=True) as connection:
        counts = connection.execute("""select count(distinct e.context_id),count(distinct s.path)
            from ledger_usage_events e join ledger_generations g using(generation_id)
            join ledger_sources s using(source_id) where g.status='trusted'
            and e.timestamp_us>=? and e.timestamp_us<?""",
            (selected.bounds.start_us, selected.bounds.end_us)).fetchone()
        with patch.object(materialization, "context_values", wraps=materialization.context_values) as contexts:
            with patch.object(materialization, "Path", wraps=materialization.Path) as paths:
                _, records = compare(connection, selected, ["absent"])
        assert len(records) == 24
        assert contexts.call_count == counts[0] < len(records)
        assert paths.call_count == counts[1] < len(records)


def test_metadata_is_not_reused_across_queries_or_rollback(ledger):
    selected = resolve_report_range("30d", UTC, now=AT+timedelta(hours=1))
    with open_ledger(ledger) as connection:
        _, before = compare(connection, selected, ["changed-alias"])
        connection.execute("savepoint metadata_change")
        connection.execute("update ledger_contexts set project_aliases_json='[\"changed-alias\"]'")
        touch(connection)
        _, after = compare(connection, selected, ["changed-alias"])
        assert before and after and before != after
        assert all("changed-alias" in record.project_aliases for record in after)
        connection.execute("rollback to metadata_change")
        _, restored = compare(connection, selected, ["changed-alias"])
        assert restored == before


def test_account_wide_query_constructs_no_usage_metadata(ledger, monkeypatch):
    selected = resolve_report_range("30d", UTC, now=AT+timedelta(hours=1))
    def forbidden(*args, **kwargs):
        raise AssertionError("Account-wide speed must not decode usage records")
    monkeypatch.setattr(queries, "_row_to_usage_record", forbidden)
    monkeypatch.setattr(materialization, "context_values", forbidden)
    with open_ledger(ledger, read_only=True) as connection:
        result, cached = queries.speed_aggregates(connection, selected, [], UTC)
        assert not cached and result["summaries"]


@pytest.mark.parametrize("projects", [[], ["moved"]])
def test_project_filter_runs_once_on_post_transition_objects(ledger, monkeypatch, projects):
    selected = resolve_report_range("30d", UTC, now=AT+timedelta(hours=1))
    transitioned = []
    original = queries.apply_project_transitions

    def apply(records, transitions):
        result = original(records, transitions)
        transitioned.extend(result)
        return result

    monkeypatch.setattr(queries, "apply_project_transitions", apply)
    with open_ledger(ledger) as connection:
        key = connection.execute("""select p.project_key from ledger_projects p
            join ledger_contexts c using(project_id) join ledger_usage_events e using(context_id)
            where e.task_id='child' limit 1""").fetchone()[0]
        connection.execute("""insert into ledger_transitions(owner_task_id,source_key,source_label,
            target_key,target_label,effective_from,confidence,evidence_json,task_ids_json)
            values ('child',?,'Before','moved','After',?,100,'[]','["child"]')""",
            (key, AT.isoformat()))
        touch(connection)
        with patch.object(queries, "filter_records_by_project_keys",
                          wraps=queries.filter_records_by_project_keys) as filtering:
            result, _ = compare(connection, selected, projects)
            assert result[0]["summaries"]
    assert filtering.call_count == bool(projects)
    if projects:
        supplied = filtering.call_args.args[0]
        assert len(supplied) == len(transitioned) == 24
        assert all(left is right for left, right in zip(supplied, transitioned, strict=True))

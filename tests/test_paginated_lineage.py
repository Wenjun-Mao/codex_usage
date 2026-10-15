"""Physical lineage coordinates are not logical task IDs or row counts."""
from dataclasses import replace

import pytest

from codex_usage.parser import parse_session_files, parse_session_generation
from codex_usage.session_files import read_session_metadata_bounded
from codex_usage.session_history import resolve_baseline
from codex_usage.session_history_models import PaginatedHistoryError

from test_paginated_history import (
    PAGE, THREAD, corpus, meta, owned, rollout_name, tokens, write_rows,
)

NEXT = "33333333-3333-4333-8333-333333333333"
CHILD = "44444444-4444-4444-8444-444444444444"
LEAF = "55555555-5555-4555-8555-555555555555"


def reference(physical, path, ordinal):
    return {"thread_id": physical, "end_ordinal_exclusive": ordinal,
            "end_byte_offset": path.stat().st_size}


def test_nested_page_baseline_uses_physical_rollout_id(tmp_path):
    root, _, base = corpus(tmp_path)
    parent = write_rows(tmp_path / rollout_name(physical=PAGE), [
        meta(stamp="2026-10-13T02:00:00Z", base=base),
        tokens(150, "2026-10-13T02:01:00Z", ordinal=3)])
    leaf = write_rows(tmp_path / rollout_name(physical=NEXT), [
        meta(stamp="2026-10-13T03:00:00Z", base=reference(PAGE, parent, 4)),
        tokens(150, "2026-10-13T03:01:00Z", ordinal=5),
        tokens(175, "2026-10-13T03:02:00Z", ordinal=6)])
    parsed = parse_session_generation(leaf, history_sources=(owned(root), owned(parent)))
    assert [r.usage.total_tokens for r in parsed.records] == [25]
    all_records = parse_session_files([root, parent, leaf])
    assert sum(r.usage.total_tokens for r in all_records) == 175
    assert {r.session_id for r in all_records} == {THREAD}


@pytest.mark.parametrize("empty_prefix", [False, True])
def test_counter_free_intermediate_page_inherits_earlier_counter(tmp_path, empty_prefix):
    root, _, base = corpus(tmp_path)
    parent = write_rows(tmp_path / rollout_name(physical=PAGE), [
        meta(stamp="2026-10-13T02:00:00Z", base=base),
        {"type": "event_msg", "ordinal": 3, "payload": {"type": "user_message", "message": "synthetic"}}])
    cut = ({"thread_id": PAGE, "end_ordinal_exclusive": 2, "end_byte_offset": 0}
           if empty_prefix else reference(PAGE, parent, 4))
    leaf = write_rows(tmp_path / rollout_name(physical=NEXT), [
        meta(stamp="2026-10-13T03:00:00Z", base=cut),
        tokens(120, "2026-10-13T03:01:00Z", ordinal=cut["end_ordinal_exclusive"] + 1)])
    parsed = parse_session_generation(leaf, history_sources=(owned(root), owned(parent)))
    assert [r.usage.total_tokens for r in parsed.records] == [20]


def test_foreign_base_can_differ_from_logical_thread_and_immediate_fork_parent(tmp_path):
    ancestor = write_rows(tmp_path / rollout_name(THREAD, PAGE), [
        meta(history_mode="paginated"), tokens(100, ordinal=1)])
    leaf = write_rows(tmp_path / rollout_name(CHILD, LEAF), [
        meta(CHILD, stamp="2026-10-13T02:00:00Z", base=reference(PAGE, ancestor, 2),
             forked_from_id=NEXT, forked_from_ordinal_exclusive=2),
        tokens(100, "2026-10-13T02:01:00Z", ordinal=3),
        tokens(150, "2026-10-13T02:02:00Z", ordinal=4)])
    parsed = parse_session_generation(leaf, history_sources=(owned(ancestor),))
    assert [r.usage.total_tokens for r in parsed.records] == [50]
    assert parsed.records[0].session_id == CHILD


def test_endpoint_ordinal_is_validated_without_counting_jsonl_rows(tmp_path):
    root, leaf, _ = corpus(tmp_path)
    metadata = read_session_metadata_bounded(leaf).metadata
    wrong = replace(metadata.history_base, end_ordinal_exclusive=3)
    with pytest.raises(PaginatedHistoryError, match="endpoint_ordinal_mismatch"):
        resolve_baseline(replace(metadata, history_base=wrong, history_ordinal=3), (owned(root),))


def test_cycles_and_missing_recursive_sources_do_not_create_zero_baselines(tmp_path):
    first = write_rows(tmp_path / rollout_name(physical=PAGE), [meta(
        base={"thread_id": NEXT, "end_ordinal_exclusive": 5, "end_byte_offset": 0})])
    second = write_rows(tmp_path / rollout_name(physical=NEXT), [meta(
        base={"thread_id": PAGE, "end_ordinal_exclusive": 5, "end_byte_offset": 0})])
    leaf = write_rows(tmp_path / rollout_name(physical=LEAF), [meta(
        base={"thread_id": PAGE, "end_ordinal_exclusive": 5, "end_byte_offset": 0})])
    with pytest.raises(PaginatedHistoryError, match="cycle"):
        parse_session_generation(leaf, history_sources=(owned(first), owned(second)))
    with pytest.raises(PaginatedHistoryError, match="source_unavailable"):
        parse_session_generation(leaf, history_sources=(owned(first),))


def test_abandoned_branch_consumption_remains_financial_history(tmp_path):
    root, first, base = corpus(tmp_path)
    second = write_rows(tmp_path / rollout_name(physical=NEXT), [
        meta(stamp="2026-10-13T03:00:00Z", base=base),
        tokens(100, "2026-10-13T03:01:00Z", ordinal=3),
        tokens(140, "2026-10-13T03:02:00Z", ordinal=4)])
    # Conversation reconstruction can abandon the first page's suffix. Its
    # actual 50 consumed tokens still belong in a historical consumption ledger.
    records = parse_session_files([root, first, second])
    assert sum(r.usage.total_tokens for r in records) == 190


def test_empty_reference_is_distinct_from_missing_zero_token_evidence(tmp_path):
    root = write_rows(tmp_path / rollout_name(), [meta(history_mode="paginated")])
    leaf = write_rows(tmp_path / rollout_name(physical=PAGE), [
        meta(base=reference(THREAD, root, 1)), tokens(100, ordinal=2)])
    with pytest.raises(PaginatedHistoryError, match="counter_unavailable"):
        parse_session_generation(leaf, history_sources=(owned(root),))


def test_ordinal_gaps_are_not_replaced_by_jsonl_row_counts(tmp_path):
    root = write_rows(tmp_path / rollout_name(), [
        meta(history_mode="paginated"), tokens(100, ordinal=10)])
    leaf = write_rows(tmp_path / rollout_name(physical=PAGE), [
        meta(base=reference(THREAD, root, 11)), tokens(120, ordinal=12)])
    assert parse_session_generation(leaf, history_sources=(owned(root),)).records[0].usage.total_tokens == 20


def test_compaction_without_later_info_does_not_borrow_older_baseline(tmp_path):
    root = write_rows(tmp_path / rollout_name(), [
        meta(history_mode="paginated"), tokens(100, ordinal=1),
        {"type": "compacted", "ordinal": 2, "payload": {"message": "synthetic"}}])
    leaf = write_rows(tmp_path / rollout_name(physical=PAGE), [
        meta(base=reference(THREAD, root, 3)), tokens(120, ordinal=4)])
    with pytest.raises(PaginatedHistoryError, match="replay_boundary_unresolved"):
        parse_session_generation(leaf, history_sources=(owned(root),))


def test_newer_counter_can_establish_seed_after_older_unproven_compaction(tmp_path):
    root = write_rows(tmp_path / rollout_name(), [
        meta(history_mode="paginated"),
        {"type": "compacted", "ordinal": 1, "payload": {"message": "synthetic"}}])
    parent = write_rows(tmp_path / rollout_name(physical=PAGE), [
        meta(base=reference(THREAD, root, 2)), tokens(150, ordinal=3)])
    leaf = write_rows(tmp_path / rollout_name(physical=NEXT), [
        meta(base=reference(PAGE, parent, 4)), tokens(175, ordinal=5)])
    parsed = parse_session_generation(leaf, history_sources=(owned(root), owned(parent)))
    assert parsed.records[0].usage.total_tokens == 25


@pytest.mark.parametrize("new_physical", [False, True])
def test_empty_new_fork_or_replacement_page_preserves_first_new_work(tmp_path, new_physical):
    path = tmp_path / rollout_name(physical=PAGE if new_physical else None)
    header = meta(history_mode="paginated", forked_from_id=NEXT,
        forked_from_ordinal_exclusive=20 if new_physical else 0,
        source={"subagent": {"thread_spawn": {"parent_thread_id": NEXT, "depth": 1}}})
    write_rows(path, [header, tokens(100, ordinal=1)])
    parsed = parse_session_generation(path)
    assert [r.usage.total_tokens for r in parsed.records] == [100]
    assert parsed.records[0].usage_role == "subagent"
    assert parsed.checkpoint.state.root_session_is_fork
    assert not parsed.checkpoint.state.root_inline_replay_possible

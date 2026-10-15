"""Physical page boundaries must not manufacture logical-thread consumption."""
from dataclasses import replace
from datetime import UTC, datetime
import json
import os
from pathlib import Path

import pytest

from codex_usage.models import TokenUsage
from codex_usage.parser import parse_session_append, parse_session_generation
from codex_usage.session_files import read_session_metadata_bounded
from codex_usage.session_history import (
    HISTORY_READ_BUDGET, HistorySource, resolve_baseline, source_identity,
)
from codex_usage.session_history_models import HistoryBoundary, PaginatedHistoryError
from codex_usage.session_parser_models import parser_state_from_json, parser_state_to_json

THREAD = "11111111-1111-4111-8111-111111111111"
PAGE = "22222222-2222-4222-8222-222222222222"


def rollout_name(thread=THREAD, physical=None):
    suffix = f"_{physical}" if physical and physical != thread else ""
    return f"rollout-2026-10-13T00-00-00-{thread}{suffix}.jsonl"


def write_rows(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row) + "\n" for row in rows))
    return path


def meta(thread=THREAD, *, stamp="2026-10-13T00:00:00Z", base=None, ordinal=None, **extra):
    payload = {"id": thread, "timestamp": stamp, "cwd": "/repo", **extra}
    if base is not None:
        payload.update(history_mode="paginated", history_base=base)
    row = {"type": "session_meta", "timestamp": stamp, "payload": payload}
    if ordinal is not None:
        row["ordinal"] = ordinal
    elif isinstance(base, dict) and "end_ordinal_exclusive" in base:
        row["ordinal"] = base["end_ordinal_exclusive"]
    elif extra.get("history_mode") == "paginated":
        row["ordinal"] = 0
    return row


def tokens(total, stamp="2026-10-13T01:00:00Z", *, ordinal=None):
    usage = {"input_tokens": total - 10, "cached_input_tokens": total - 20,
             "output_tokens": 10, "reasoning_output_tokens": 5, "total_tokens": total}
    row = {"type": "event_msg", "timestamp": stamp, "payload": {"type": "token_count",
            "info": {"total_token_usage": usage, "last_token_usage": usage}}}
    if ordinal is not None:
        row["ordinal"] = ordinal
    return row


def owned(path):
    stat = path.stat()
    return HistorySource(path, stat.st_size, stat.st_dev, stat.st_ino)


def corpus(tmp_path, opening=100):
    legacy = write_rows(tmp_path / rollout_name(), [meta(history_mode="paginated"), tokens(100, ordinal=1)])
    base = {"thread_id": THREAD, "end_ordinal_exclusive": 2,
            "end_byte_offset": legacy.stat().st_size}
    page = write_rows(tmp_path / rollout_name(physical=PAGE), [
        meta(stamp="2026-10-13T02:00:00Z", base=base),
        {"type": "turn_context", "ordinal": 3, "payload": {"model": "gpt-6.1-sol", "turn_id": "turn"}},
        tokens(opening, "2026-10-13T02:01:00Z", ordinal=4), tokens(150, "2026-10-13T02:02:00Z", ordinal=5),
    ])
    return legacy, page, base


@pytest.mark.parametrize("opening,expected", [(100, [50]), (120, [20, 30])])
def test_repeated_and_advanced_opening_counters(tmp_path, opening, expected):
    legacy, page, _ = corpus(tmp_path, opening)
    parsed = parse_session_generation(page, history_sources=(owned(legacy), owned(page)))
    assert [r.usage.total_tokens for r in parsed.records] == expected
    assert all(r.model == "gpt-6.1-sol" and r.turn_id == "turn" for r in parsed.records)
    assert parsed.metadata.history_base.rollout_id == THREAD
    assert parsed.bytes_read > page.stat().st_size
    assert parsed.checkpoint.state.history_boundary_digest


def test_checkpoint_before_first_counter_keeps_validated_baseline(tmp_path, monkeypatch):
    legacy, page, _ = corpus(tmp_path, 120)
    first = parse_session_generation(page, max_bytes=1, history_sources=(owned(legacy),))
    assert not first.records
    assert first.checkpoint.state.history_baseline_pending
    state = parser_state_from_json(parser_state_to_json(first.checkpoint.state), page)
    assert state == first.checkpoint.state
    assert state.previous_usage.total_tokens == 100
    def no_reopen(*_args):
        raise AssertionError("append must not resolve inherited history again")
    monkeypatch.setattr("codex_usage.session_parser_incremental.resolve_baseline", no_reopen)
    appended = parse_session_append(page, first.checkpoint, stop_offset=page.stat().st_size)
    assert [r.usage.total_tokens for r in appended.records] == [20, 30]
    assert not appended.checkpoint.state.history_baseline_pending


def test_missing_history_is_explicit_not_entire_inherited_counter(tmp_path):
    _, page, _ = corpus(tmp_path)
    with pytest.raises(PaginatedHistoryError, match="source_unavailable"):
        parse_session_generation(page)


def test_ordinary_new_session_and_paginated_empty_origin_count_first_usage(tmp_path):
    for page_mode in (False, True):
        payload = meta(history_mode="paginated") if page_mode else meta()
        path = write_rows(tmp_path / rollout_name(), [payload, tokens(100, ordinal=1)])
        assert parse_session_generation(path).records[0].usage.total_tokens == 100


def test_zero_ordinal_reference_is_invalid_not_an_inferred_empty_baseline(tmp_path):
    base = {"thread_id": THREAD, "end_ordinal_exclusive": 0, "end_byte_offset": 0}
    path = write_rows(tmp_path / "empty.jsonl", [meta(base=base), tokens(100)])
    with pytest.raises(PaginatedHistoryError, match="invalid_reference"):
        parse_session_generation(path)


def test_mismatched_thread_or_decreasing_opening_rejects_attribution(tmp_path):
    legacy, page, _ = corpus(tmp_path, 90)
    with pytest.raises(PaginatedHistoryError, match="precedes_baseline"):
        parse_session_generation(page, history_sources=(owned(legacy),))
    metadata = read_session_metadata_bounded(page).metadata
    metadata = replace(metadata, history_base=replace(metadata.history_base, thread_id="wrong"))
    with pytest.raises(PaginatedHistoryError, match="source_unavailable"):
        resolve_baseline(metadata, (owned(legacy),))


def test_byte_boundary_not_latest_tail_controls_baseline(tmp_path):
    legacy, page, _ = corpus(tmp_path, 120)
    with legacy.open("a") as handle:
        handle.write(json.dumps(tokens(999, "2026-10-13T03:00:00Z")) + "\n")
    parsed = parse_session_generation(page, history_sources=(owned(legacy),))
    assert [r.usage.total_tokens for r in parsed.records] == [20, 30]


def test_conflicting_owned_prefixes_do_not_choose_mtime_or_path(tmp_path):
    legacy, page, _ = corpus(tmp_path)
    other = tmp_path / "mirror" / legacy.name
    other.parent.mkdir()
    other.write_bytes(legacy.read_bytes().replace(b'"total_tokens": 100', b'"total_tokens": 101'))
    with pytest.raises(PaginatedHistoryError, match="conflicting_baselines"):
        parse_session_generation(page, history_sources=(owned(legacy), owned(other)))


def test_file_identity_mismatch_is_not_read_as_baseline(tmp_path):
    legacy, page, _ = corpus(tmp_path)
    with pytest.raises(PaginatedHistoryError, match="source_changed"):
        parse_session_generation(page, history_sources=(replace(owned(legacy), source_inode=0),))


def test_partial_row_boundary_is_not_accepted(tmp_path):
    legacy, page, _ = corpus(tmp_path)
    metadata = read_session_metadata_bounded(page).metadata
    metadata = replace(metadata, history_base=replace(metadata.history_base,
        end_byte_offset=metadata.history_base.end_byte_offset - 1))
    with pytest.raises(PaginatedHistoryError, match="invalid_byte_boundary"):
        resolve_baseline(metadata, (owned(legacy),))


def test_source_key_distinguishes_physical_pages_not_task_identity(tmp_path):
    legacy, page, _ = corpus(tmp_path)
    root = read_session_metadata_bounded(legacy).metadata
    metadata = read_session_metadata_bounded(page).metadata
    assert source_identity(root) == THREAD
    assert source_identity(metadata) != source_identity(root)
    assert source_identity(metadata) == source_identity(replace(metadata, file_path=tmp_path / "mirror" / page.name))
    later = replace(metadata, timestamp=datetime(2026, 10, 14, tzinfo=UTC))
    assert source_identity(later) == source_identity(metadata)
    assert source_identity(replace(later, file_path=tmp_path / rollout_name(
        physical="33333333-3333-4333-8333-333333333333"))) != source_identity(metadata)
    assert later.session_id == metadata.session_id


@pytest.mark.parametrize("bad", [[], "file:///secret", {"thread_id": "thread"},
    {"thread_id": "thread", "end_ordinal_exclusive": True, "end_byte_offset": 2},
    {"thread_id": "thread", "end_ordinal_exclusive": 2, "end_byte_offset": -1}])
def test_invalid_reference_is_a_named_diagnostic(tmp_path, bad):
    path = write_rows(tmp_path / "bad.jsonl", [meta(base=bad)])
    assert read_session_metadata_bounded(path).diagnostic == "paginated_history_invalid_reference"
    with pytest.raises(PaginatedHistoryError, match="invalid_reference"):
        HistoryBoundary.from_mapping(bad)


def test_resolver_io_is_bounded_with_large_legacy_file(tmp_path):
    legacy, page, base = corpus(tmp_path)
    header = json.dumps(meta(history_mode="paginated")).encode() + b"\n"
    with legacy.open("wb") as handle:
        handle.write(header)
        handle.seek(8 * 1024 * 1024)
        handle.write(b"\n" + json.dumps(tokens(100, ordinal=1)).encode() + b"\n")
    metadata = read_session_metadata_bounded(page).metadata
    metadata = replace(metadata, history_base=replace(metadata.history_base,
        end_byte_offset=legacy.stat().st_size))
    baseline = resolve_baseline(metadata, (owned(legacy),))
    assert baseline.usage.total_tokens == 100
    assert baseline.bytes_read <= HISTORY_READ_BUDGET
    assert baseline.usage == TokenUsage.from_mapping(tokens(100)["payload"]["info"]["total_token_usage"])


@pytest.mark.parametrize("info", [None, {}, {"total_token_usage": None}])
def test_trailing_quota_only_events_do_not_hide_last_usage(tmp_path, info):
    legacy, page, _ = corpus(tmp_path)
    with legacy.open("a") as handle:
        handle.write(json.dumps({"type": "event_msg", "ordinal": 2, "timestamp": "2026-10-13T01:10:00Z",
            "payload": {"type": "token_count", "info": info, "rate_limits": {}}}) + "\n")
    metadata = read_session_metadata_bounded(page).metadata
    metadata = replace(metadata, history_base=replace(metadata.history_base,
        end_byte_offset=legacy.stat().st_size, end_ordinal_exclusive=3), history_ordinal=3)
    assert resolve_baseline(metadata, (owned(legacy),)).usage.total_tokens == 100


def test_continued_subagent_fork_does_not_suppress_post_boundary_deltas(tmp_path):
    legacy, page, base = corpus(tmp_path)
    rows = [meta(stamp="2026-10-13T02:00:00Z", base=base, forked_from_id="parent",
        source={"subagent": {"thread_spawn": {"parent_thread_id": "parent", "depth": 1}}}),
        tokens(120, "2026-10-13T02:01:00Z"), tokens(150, "2026-10-13T02:02:00Z")]
    write_rows(page, rows)
    parsed = parse_session_generation(page, history_sources=(owned(legacy),))
    assert [r.usage.total_tokens for r in parsed.records] == [20, 30]
    assert all(r.usage_role == "subagent" for r in parsed.records)
    first = parse_session_generation(page, max_bytes=1, history_sources=(owned(legacy),))
    assert first.checkpoint.state.subagent_own_activity_started
    appended = parse_session_append(page, first.checkpoint, stop_offset=page.stat().st_size)
    assert [r.usage.total_tokens for r in appended.records] == [20, 30]


@pytest.mark.parametrize("change", ["rewrite", "replace", "truncate", "append", "rewrite-and-grow"])
def test_history_read_races_fail_closed(tmp_path, monkeypatch, change):
    legacy, page, _ = corpus(tmp_path)
    source = owned(legacy)
    original_open = Path.open
    class RacingRead:
        def __init__(self, raw):
            self.raw = raw
            self.changed = False
        def __enter__(self):
            return self
        def __exit__(self, *args):
            self.raw.close()
        def __getattr__(self, name):
            return getattr(self.raw, name)
        def read(self, size):
            if not self.changed:
                self.changed = True
                data = legacy.read_bytes()
                if change == "replace":
                    other = tmp_path / "replacement"
                    other.write_bytes(data)
                    other.replace(legacy)
                elif change == "truncate":
                    legacy.write_bytes(data[:10])
                elif change == "rewrite":
                    legacy.write_bytes(data.replace(b'"total_tokens": 100', b'"total_tokens": 101'))
                elif change == "append":
                    with original_open(legacy, "ab") as writer:
                        writer.write(b"{}\n")
                else:
                    legacy.write_bytes(data.replace(b'"total_tokens": 100', b'"total_tokens": 101') + b"{}\n")
                stat = legacy.stat()
                os.utime(legacy, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1_000_000))
            return self.raw.read(size)
    def open_source(path, *args, **kwargs):
        raw = original_open(path, *args, **kwargs)
        return RacingRead(raw) if path == legacy and args == ("rb",) else raw
    monkeypatch.setattr(Path, "open", open_source)
    metadata = read_session_metadata_bounded(page).metadata
    with pytest.raises(PaginatedHistoryError, match="source_changed"):
        resolve_baseline(metadata, (source,))


def test_append_before_open_preserves_declared_captured_prefix(tmp_path):
    legacy, page, _ = corpus(tmp_path)
    source = owned(legacy)
    with legacy.open("ab") as handle:
        handle.write(json.dumps(tokens(200, "2026-10-13T03:00:00Z")).encode() + b"\n")
    assert resolve_baseline(read_session_metadata_bounded(page).metadata, (source,)).usage.total_tokens == 100


@pytest.mark.parametrize("info", [None, {}, {"total_token_usage": None}])
@pytest.mark.parametrize("before_opening", [False, True])
@pytest.mark.parametrize("paginated", [False, True])
def test_quota_only_rows_preserve_usage_baseline_across_full_and_append(
        tmp_path, info, before_opening, paginated):
    legacy, page, base = corpus(tmp_path)
    rows = [meta(stamp="2026-10-13T02:00:00Z", base=base if paginated else None)]
    opening = tokens(100, "2026-10-13T02:01:00Z")
    quota = {"type": "event_msg", "timestamp": "2026-10-13T02:01:00Z",
             "payload": {"type": "token_count", "info": info}}
    rows += [quota, opening] if before_opening else [opening, quota]
    rows += [tokens(120, "2026-10-13T02:02:00Z")]
    write_rows(page, rows)
    sources = (owned(legacy),) if paginated else ()
    result = parse_session_generation(page, history_sources=sources)
    expected = [20] if paginated else [100, 20]
    assert [r.usage.total_tokens for r in result.records] == expected
    prefix = sum(len(json.dumps(row).encode()) + 1 for row in rows[:-1])
    initial = parse_session_generation(page, stop_offset=prefix, history_sources=sources)
    appended = parse_session_append(page, initial.checkpoint, stop_offset=page.stat().st_size)
    assert [r.usage.total_tokens for r in initial.records + appended.records] == expected


def test_failed_baseline_accounts_for_bounded_bytes_read(tmp_path):
    legacy, page, _ = corpus(tmp_path)
    other = tmp_path / "mirror" / legacy.name
    other.parent.mkdir()
    other.write_bytes(legacy.read_bytes().replace(b'"total_tokens": 100', b'"total_tokens": 101'))
    with pytest.raises(PaginatedHistoryError) as failure:
        parse_session_generation(page, history_sources=(owned(legacy), owned(other)))
    assert 0 < failure.value.bytes_read <= HISTORY_READ_BUDGET + page.stat().st_size

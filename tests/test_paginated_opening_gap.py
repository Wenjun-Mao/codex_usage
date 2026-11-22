"""An unavailable opening is not a reason to discard verified later usage."""
import json
import shutil

import pytest

from codex_usage.agent_capture import capture_once
from codex_usage.agent_paths import ledger_database_path
from codex_usage.agent_rebuild import rebuild_stale_source_slice, stale_source_keys
from codex_usage.agent_reports import _status_banner
from codex_usage.ledger_queries import load_ledger_records, load_ledger_status
from codex_usage.ledger_schema import open_ledger
from codex_usage.parser import parse_session_append, parse_session_generation
from codex_usage.session_history import PAGE_KEY_PREFIX
from codex_usage.session_history_gap import OPENING_GAP
from codex_usage.session_history_models import PaginatedHistoryError
from codex_usage.session_parser_models import parser_state_from_json, parser_state_to_json
from test_paginated_history import PAGE, corpus, owned, tokens


def test_missing_opening_survives_checkpoint_and_does_not_charge_seed(tmp_path):
    legacy, page, _ = corpus(tmp_path, 120)
    legacy.unlink()
    first = parse_session_generation(page, max_bytes=1, allow_missing_history=True)
    assert not first.records
    assert first.checkpoint.state.history_gap_ordinal == 2
    assert first.checkpoint.state.previous_usage is None
    serialized = parser_state_to_json(first.checkpoint.state)
    assert json.loads(serialized)["history_boundary_digest"] is None
    assert parser_state_from_json(serialized, page) == first.checkpoint.state
    result = parse_session_append(page, first.checkpoint, stop_offset=page.stat().st_size)
    assert [r.usage.total_tokens for r in result.records] == [30]
    assert result.checkpoint.state.history_gap_ordinal == 5


def test_invalid_or_replayed_counters_cannot_bridge_an_unknown_interval(tmp_path):
    legacy, page, _ = corpus(tmp_path, 120)
    legacy.unlink()
    with page.open("a") as stream:
        broken = tokens(300, ordinal=6)
        broken["payload"]["info"]["total_token_usage"]["input_tokens"] = 0
        for row in [broken, tokens(310, ordinal=7), tokens(325, ordinal=8),
                    tokens(500, ordinal=8), tokens(520, ordinal=9), tokens(550, ordinal=10),
                    tokens(450, ordinal=11), tokens(470, ordinal=12)]:
            stream.write(json.dumps(row) + "\n")
    result = parse_session_generation(page, allow_missing_history=True)
    assert [r.usage.total_tokens for r in result.records] == [30, 15, 30, 20]


def test_available_but_short_predecessor_is_not_treated_as_missing(tmp_path):
    legacy, page, _ = corpus(tmp_path, 120)
    legacy.write_bytes(legacy.read_bytes()[:-1])
    with pytest.raises(PaginatedHistoryError, match="source_unavailable"):
        parse_session_generation(page, history_sources=(owned(legacy),), allow_missing_history=True)


def test_collector_normalization_append_and_exact_restoration(tmp_path):
    home = tmp_path / "codex"
    session_dir = home / "sessions"
    session_dir.mkdir(parents=True)
    legacy, page, _ = corpus(session_dir, 120)
    original = legacy.read_bytes()
    legacy.unlink()
    # A byte-identical archive copy must not become independent consumption.
    archive = home / "archived_sessions"
    archive.mkdir()
    mirror = archive / page.name
    shutil.copyfile(page, mirror)
    ledger = ledger_database_path(home)
    key = PAGE_KEY_PREFIX + PAGE

    first = capture_once(home, request_kind="manual", auto_transitions=False, max_workers=1)
    assert first.outcome == "success", first.error
    assert [r.usage.total_tokens for r in load_ledger_records(ledger)] == [30]
    assert first.status.coverage.history_gap_sources == 1 and not first.status.coverage.complete
    assert "Verified later usage is included" in _status_banner(first.status)
    assert key not in stale_source_keys(ledger)
    with open_ledger(ledger, read_only=True) as connection:
        assert connection.execute("select stale_reason from ledger_sources where source_key=?", (key,)).fetchone()[0] == OPENING_GAP
        first_generation = connection.execute("select generation_id from ledger_generations where status='trusted'").fetchone()[0]

    with page.open("a") as stream:
        for row in [tokens(150, ordinal=6), tokens(180, ordinal=7)]:
            stream.write(json.dumps(row) + "\n")
    for _ in range(2):
        result = capture_once(home, request_kind="manual", auto_transitions=False, max_workers=1)
        assert result.outcome == "success", result.error
        assert sorted(r.usage.total_tokens for r in load_ledger_records(ledger)) == [30, 30]
        assert load_ledger_status(ledger).coverage.history_gap_sources == 1

    legacy.write_bytes(original)
    result = capture_once(home, request_kind="manual", auto_transitions=False, max_workers=1)
    assert result.outcome == "success", result.error
    assert key in stale_source_keys(ledger)
    pending = load_ledger_status(ledger)
    assert pending.coverage.history_gap_sources == 1
    assert sum(r.usage.total_tokens for r in load_ledger_records(ledger)) == 160

    rebuilt = rebuild_stale_source_slice(home, key, max_bytes=1024 * 1024)
    assert rebuilt.complete
    assert sorted(r.usage.total_tokens for r in load_ledger_records(ledger)) == [20, 30, 30, 100]
    assert load_ledger_status(ledger).coverage.history_gap_sources == 0
    with open_ledger(ledger, read_only=True) as connection:
        assert connection.execute("select status from ledger_generations where generation_id=?",
                                  (first_generation,)).fetchone()[0] == "superseded"

from datetime import UTC, datetime
from pathlib import Path

import parser_test_support as parser_fixtures
import pytest

from codex_usage import pricing
from codex_usage.aggregation import (
    aggregate_records,
    filter_records_by_range,
    resolve_timezone,
    summarize_records,
)
from codex_usage.models import ROOT_USAGE_ROLE, TokenUsage, UsageRecord
from codex_usage.parser import parse_session_file
from codex_usage.pricing import EffectiveModelRate, ModelRate

_session_meta = parser_fixtures.session_meta
_subagent_boundary = parser_fixtures.inter_agent_communication_metadata
_token = parser_fixtures.token
_turn_context = parser_fixtures.turn_context
_usage = parser_fixtures.usage
_write_session = parser_fixtures.write_session


def test_parser_uses_positive_cumulative_deltas(tmp_path: Path) -> None:
    path = _write_session(
        tmp_path,
        [
            _session_meta(cwd="C:/repo/demo"),
            _turn_context(model="gpt-5.5"),
            _token("2026-04-29T10:00:00Z", None),
            _token(
                "2026-04-29T10:01:00Z",
                _usage(total=100, input_tokens=80, cached=20, cache_write=10, output=20),
            ),
            _token(
                "2026-04-29T10:02:00Z",
                _usage(total=100, input_tokens=80, cached=20, cache_write=10, output=20),
            ),
            _token(
                "2026-04-29T10:03:00Z",
                _usage(total=160, input_tokens=120, cached=30, cache_write=15, output=40),
            ),
        ],
    )

    records = parse_session_file(path)

    assert [record.usage.total_tokens for record in records] == [100, 60]
    assert [record.usage.cache_write_input_tokens for record in records] == [10, 5]
    assert summarize_records(records).usage.total_tokens == 160
    assert summarize_records(records).usage.cache_write_input_tokens == 15


def test_parser_tracks_model_changes_within_session(tmp_path: Path) -> None:
    path = _write_session(
        tmp_path,
        [
            _session_meta(repo="https://github.com/example/demo.git"),
            _turn_context(model="gpt-5.4"),
            _token("2026-04-29T10:00:00Z", _usage(total=100)),
            _turn_context(model="gpt-5.5"),
            _token("2026-04-29T10:05:00Z", _usage(total=175)),
        ],
    )

    records = parse_session_file(path)
    rows = aggregate_records(records, "model", resolve_timezone("UTC"))

    assert {row.key: row.usage.total_tokens for row in rows} == {
        "gpt-5.4": 100,
        "gpt-5.5": 75,
    }


def test_side_chat_turn_remains_root_usage_in_parent_session(tmp_path: Path) -> None:
    path = _write_session(
        tmp_path,
        [
            _session_meta(cwd="/repo/demo", session_id="root-task"),
            _turn_context(model="gpt-5.6-sol"),
            {
                "timestamp": "2026-08-07T10:00:00Z",
                "type": "event_msg",
                "payload": {"type": "task_started", "turn_id": "main-turn"},
            },
            _token("2026-08-07T10:01:00Z", _usage(total=100)),
            {
                "timestamp": "2026-08-07T10:02:00Z",
                "type": "event_msg",
                "payload": {"type": "task_complete", "turn_id": "main-turn"},
            },
            _turn_context(model="gpt-5.6-terra"),
            {
                "timestamp": "2026-08-07T10:03:00Z",
                "type": "event_msg",
                "payload": {"type": "task_started", "turn_id": "side-turn"},
            },
            _token("2026-08-07T10:04:00Z", _usage(total=160)),
            {
                "timestamp": "2026-08-07T10:05:00Z",
                "type": "event_msg",
                "payload": {"type": "task_complete", "turn_id": "side-turn"},
            },
        ],
    )

    records = parse_session_file(path)

    assert [record.session_id for record in records] == ["root-task", "root-task"]
    assert [record.usage.total_tokens for record in records] == [100, 60]
    assert [record.model for record in records] == ["gpt-5.6-sol", "gpt-5.6-terra"]
    assert {record.usage_role for record in records} == {ROOT_USAGE_ROLE}
    assert summarize_records(records).usage.total_tokens == 160


def test_parser_ignores_imported_parent_usage_in_forked_session_file(
    tmp_path: Path,
) -> None:
    path = _write_session(
        tmp_path,
        [
            _session_meta(
                cwd="/repo/fork",
                session_id="fork-session",
                forked_from_id="parent-session",
            ),
            _turn_context(model="gpt-5.5"),
            _session_meta(
                cwd="/repo/parent",
                repo="https://github.com/example/parent.git",
                session_id="parent-session",
            ),
            _turn_context(model="gpt-5.5"),
            _token("2026-04-29T10:00:00Z", _usage(total=1_000)),
            _token("2026-04-29T10:01:00Z", _usage(total=2_000)),
            _session_meta(
                cwd="/repo/fork",
                session_id="fork-session",
                forked_from_id="parent-session",
            ),
            _turn_context(model="gpt-5.5"),
            _token("2026-04-29T10:02:00Z", _usage(total=2_100)),
            _token("2026-04-29T10:03:00Z", _usage(total=2_300)),
        ],
    )

    records = parse_session_file(path)

    assert [record.session_id for record in records] == [
        "fork-session",
        "fork-session",
    ]
    assert [record.project_key for record in records] == ["/repo/fork", "/repo/fork"]
    assert [record.usage.total_tokens for record in records] == [100, 200]
    assert {record.usage_role for record in records} == {ROOT_USAGE_ROLE}
    assert summarize_records(records).usage.total_tokens == 300


def test_parser_treats_first_root_token_count_in_forked_file_as_baseline(
    tmp_path: Path,
) -> None:
    path = _write_session(
        tmp_path,
        [
            _session_meta(
                cwd="/repo/fork",
                session_id="fork-session",
                forked_from_id="parent-session",
            ),
            _turn_context(model="gpt-5.5"),
            _token("2026-04-29T10:00:00Z", _usage(total=2_000)),
            _token("2026-04-29T10:01:00Z", _usage(total=2_300)),
        ],
    )

    records = parse_session_file(path)

    assert [record.session_id for record in records] == ["fork-session"]
    assert [record.usage.total_tokens for record in records] == [300]


def test_parser_ignores_inherited_replay_in_structured_subagent_fork(
    tmp_path: Path,
) -> None:
    path = _write_session(
        tmp_path,
        [
            _session_meta(
                cwd="/repo/parent",
                session_id="subagent-task",
                forked_from_id="parent-task",
                parent_thread_id="parent-task",
            ),
            _token("2026-04-29T10:00:00Z", _usage(total=1_000)),
            _token("2026-04-29T10:01:00Z", _usage(total=1_200)),
            _turn_context(model="gpt-5.6-terra"),
            _subagent_boundary(),
            _token("2026-04-29T10:02:00Z", _usage(total=1_250)),
            _token("2026-04-29T10:03:00Z", _usage(total=1_300)),
        ],
    )

    records = parse_session_file(path)

    assert [record.usage.total_tokens for record in records] == [50, 50]
    assert {record.model for record in records} == {"gpt-5.6-terra"}
    assert {record.usage_role for record in records} == {"subagent"}
    assert summarize_records(records).usage.total_tokens == 100


def test_aggregation_accumulates_api_cost_and_codex_credits(tmp_path: Path) -> None:
    path = _write_session(
        tmp_path,
        [
            _session_meta(cwd="/repo/demo"),
            _turn_context(model="gpt-5.3-codex"),
            _token(
                "2026-04-29T10:00:00Z",
                _usage(
                    total=1_100_000,
                    input_tokens=1_000_000,
                    cached=250_000,
                    output=100_000,
                ),
            ),
        ],
    )

    records = parse_session_file(path)
    total = summarize_records(records)
    rows = aggregate_records(records, "model", resolve_timezone("UTC"))

    assert total.cost.total_usd == 2.75625
    assert total.cost.unpriced_tokens == 0
    assert total.credits.total_credits == 68.90625
    assert total.credits.unpriced_tokens == 0
    assert rows[0].to_dict()["cost"]["total_usd"] == 2.75625
    assert rows[0].to_dict()["credits"]["total_credits"] == 68.90625


def test_gpt_5_6_sol_ultra_is_priced_by_model(tmp_path: Path) -> None:
    path = _write_session(
        tmp_path,
        [
            _session_meta(cwd="/repo/demo"),
            _turn_context(model="gpt-5.6-sol", effort="ultra"),
            _token(
                "2026-07-09T10:00:00Z",
                _usage(
                    total=1_100_000,
                    input_tokens=1_000_000,
                    cached=250_000,
                    cache_write=200_000,
                    output=100_000,
                ),
            ),
        ],
    )

    records = parse_session_file(path)
    total = summarize_records(records)
    rows = aggregate_records(records, "model", UTC)

    assert records[0].model == "gpt-5.6-sol"
    assert records[0].effort == "ultra"
    assert records[0].usage.cache_write_input_tokens == 200_000
    assert rows[0].key == "gpt-5.6-sol"
    assert total.cost.ordinary_input_usd == 5.5
    assert total.cost.cache_write_input_usd == 2.5
    assert total.cost.total_usd == 12.75
    assert total.cost.unpriced_tokens == 0
    assert total.credits.total_credits == 171.875
    assert total.credits.unpriced_tokens == 0


def test_gpt_6_astra_report_aggregation_preserves_the_pricing_boundary(
    tmp_path: Path,
) -> None:
    usage = TokenUsage(
        input_tokens=1_000_000,
        output_tokens=100_000,
        total_tokens=1_100_000,
    )
    records = [
        UsageRecord(
            timestamp=datetime(2026, 9, 3, 23, 59, 59, tzinfo=UTC),
            usage=usage,
            session_id="before-astra-pricing",
            file_path=tmp_path / "before.jsonl",
            usage_role=ROOT_USAGE_ROLE,
            model="gpt-6-astra",
        ),
        UsageRecord(
            timestamp=datetime(2026, 9, 4, tzinfo=UTC),
            usage=usage,
            session_id="after-astra-pricing",
            file_path=tmp_path / "after.jsonl",
            usage_role=ROOT_USAGE_ROLE,
            model="gpt-6-astra",
        ),
    ]

    total = summarize_records(records)
    rows = aggregate_records(records, "model", UTC)

    assert rows[0].key == "gpt-6-astra"
    assert total.cost.total_usd == pytest.approx(27.5)
    assert total.cost.unpriced_tokens == 1_100_000
    assert total.credits.total_credits == pytest.approx(375.0)
    assert total.credits.unpriced_tokens == 1_100_000
    assert rows[0].cost == total.cost
    assert rows[0].credits == total.credits


def test_gpt_5_6_long_context_pricing_uses_request_delta_not_cumulative_session_total(
    tmp_path: Path,
) -> None:
    path = _write_session(
        tmp_path,
        [
            _session_meta(cwd="/repo/demo"),
            _turn_context(model="gpt-5.6-sol"),
            _token(
                "2026-07-09T10:00:00Z",
                _usage(
                    total=220_000,
                    input_tokens=200_000,
                    cached=50_000,
                    output=20_000,
                ),
            ),
            _token(
                "2026-07-09T10:01:00Z",
                _usage(
                    total=440_000,
                    input_tokens=400_000,
                    cached=100_000,
                    output=40_000,
                ),
            ),
        ],
    )

    records = parse_session_file(path)
    total = summarize_records(records)
    rows = aggregate_records(records, "session", UTC)

    assert [record.usage.input_tokens for record in records] == [200_000, 200_000]
    assert all(record.usage.input_tokens <= 272_000 for record in records)
    assert total.usage.input_tokens == 400_000
    assert total.cost.uncached_input_usd == pytest.approx(1.5)
    assert total.cost.cached_input_usd == pytest.approx(0.05)
    assert total.cost.output_usd == pytest.approx(1.2)
    assert total.cost.total_usd == pytest.approx(2.75)
    assert total.credits.total_credits == pytest.approx(68.75)
    assert rows[0].cost.total_usd == pytest.approx(2.75)


def test_unknown_future_model_is_grouped_but_unpriced(tmp_path: Path) -> None:
    path = _write_session(
        tmp_path,
        [
            _session_meta(cwd=str(tmp_path)),
            _turn_context(model="gpt-5.6-pro"),
            _token(
                "2026-07-09T10:00:00Z",
                _usage(total=1_050, input_tokens=1_000, cached=100, output=50),
            ),
        ],
    )

    records = parse_session_file(path)
    total = summarize_records(records)
    rows = aggregate_records(records, "model", UTC)

    assert rows[0].key == "gpt-5.6-pro"
    assert rows[0].usage.total_tokens == 1_050
    assert rows[0].cost.total_usd == 0
    assert rows[0].cost.unpriced_tokens == 1_050
    assert rows[0].credits.total_credits == 0
    assert rows[0].credits.unpriced_tokens == 1_050
    assert total.cost.total_usd == 0
    assert total.cost.unpriced_tokens == 1_050
    assert total.credits.total_credits == 0
    assert total.credits.unpriced_tokens == 1_050


def test_aggregation_prices_records_with_rates_effective_at_each_timestamp(
    monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(
        pricing,
        "API_PRICING_USD_SCHEDULE",
        (
            EffectiveModelRate(
                model_key="gpt-test-effective",
                effective_from=datetime(1970, 1, 1, tzinfo=UTC),
                rate=ModelRate(
                    input_per_1m=1.0,
                    cached_input_per_1m=0.1,
                    output_per_1m=10.0,
                ),
            ),
            EffectiveModelRate(
                model_key="gpt-test-effective",
                effective_from=datetime(2026, 8, 18, tzinfo=UTC),
                rate=ModelRate(
                    input_per_1m=2.0,
                    cached_input_per_1m=0.2,
                    output_per_1m=20.0,
                ),
            ),
        ),
    )
    records = [
        UsageRecord(
            timestamp=datetime(2026, 8, 17, 12, tzinfo=UTC),
            usage=TokenUsage(
                input_tokens=1_000_000,
                output_tokens=100_000,
                total_tokens=1_100_000,
            ),
            session_id="before",
            file_path=tmp_path / "before.jsonl",
            usage_role=ROOT_USAGE_ROLE,
            model="gpt-test-effective",
        ),
        UsageRecord(
            timestamp=datetime(2026, 8, 18, 12, tzinfo=UTC),
            usage=TokenUsage(
                input_tokens=1_000_000,
                output_tokens=100_000,
                total_tokens=1_100_000,
            ),
            session_id="after",
            file_path=tmp_path / "after.jsonl",
            usage_role=ROOT_USAGE_ROLE,
            model="gpt-test-effective",
        ),
    ]

    total = summarize_records(records)

    assert total.cost.total_usd == 6.0
    assert total.cost.unpriced_tokens == 0


def test_aggregation_by_day_and_hour_for_spanning_session(tmp_path: Path) -> None:
    path = _write_session(
        tmp_path,
        [
            _session_meta(cwd="/repo/demo"),
            _turn_context(model="gpt-5.5"),
            _token("2026-04-28T23:55:00Z", _usage(total=100)),
            _token("2026-04-29T00:05:00Z", _usage(total=150)),
        ],
    )
    records = parse_session_file(path)
    timezone = resolve_timezone("UTC")

    day_rows = aggregate_records(records, "day", timezone)
    hour_rows = aggregate_records(records, "hour", timezone)

    assert [row.key for row in day_rows] == ["2026-04-28", "2026-04-29"]
    assert [row.usage.total_tokens for row in day_rows] == [100, 50]
    assert [row.key for row in hour_rows] == [
        "2026-04-28 23:00",
        "2026-04-29 00:00",
    ]


def test_filter_records_by_month(tmp_path: Path) -> None:
    path = _write_session(
        tmp_path,
        [
            _session_meta(cwd="/repo/demo"),
            _turn_context(model="gpt-5.5"),
            _token("2026-03-31T23:00:00Z", _usage(total=100)),
            _token("2026-04-01T00:00:00Z", _usage(total=150)),
        ],
    )
    records = parse_session_file(path)
    filtered = filter_records_by_range(
        records,
        "month",
        resolve_timezone("UTC"),
        now=datetime(2026, 4, 29, tzinfo=UTC),
    )

    assert [record.usage.total_tokens for record in filtered] == [50]

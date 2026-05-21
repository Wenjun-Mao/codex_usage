import json
from datetime import UTC, datetime
from pathlib import Path

import codex_usage.pricing as pricing
from codex_usage.aggregation import (
    aggregate_records,
    filter_records_by_project_keys,
    filter_records_by_range,
    resolve_timezone,
    summarize_records,
)
from codex_usage.models import TokenUsage, UsageRecord
from codex_usage.parser import parse_session_file
from codex_usage.pricing import EffectiveModelRate, ModelRate


def test_parser_uses_positive_cumulative_deltas(tmp_path: Path) -> None:
    path = _write_session(
        tmp_path,
        [
            _session_meta(cwd="C:/repo/demo"),
            _turn_context(model="gpt-5.5"),
            _token("2026-04-29T10:00:00Z", None),
            _token("2026-04-29T10:01:00Z", _usage(total=100, input_tokens=80, cached=20, output=20)),
            _token("2026-04-29T10:02:00Z", _usage(total=100, input_tokens=80, cached=20, output=20)),
            _token("2026-04-29T10:03:00Z", _usage(total=160, input_tokens=120, cached=30, output=40)),
        ],
    )

    records = parse_session_file(path)

    assert [record.usage.total_tokens for record in records] == [100, 60]
    assert summarize_records(records).usage.total_tokens == 160


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

    assert {row.key: row.usage.total_tokens for row in rows} == {"gpt-5.4": 100, "gpt-5.5": 75}


def test_parser_ignores_imported_parent_usage_in_forked_session_file(tmp_path: Path) -> None:
    path = _write_session(
        tmp_path,
        [
            _session_meta(cwd="/repo/fork", session_id="fork-session", forked_from_id="parent-session"),
            _turn_context(model="gpt-5.5"),
            _session_meta(
                cwd="/repo/parent",
                repo="https://github.com/example/parent.git",
                session_id="parent-session",
            ),
            _turn_context(model="gpt-5.5"),
            _token("2026-04-29T10:00:00Z", _usage(total=1_000)),
            _token("2026-04-29T10:01:00Z", _usage(total=2_000)),
            _session_meta(cwd="/repo/fork", session_id="fork-session", forked_from_id="parent-session"),
            _turn_context(model="gpt-5.5"),
            _token("2026-04-29T10:02:00Z", _usage(total=2_100)),
            _token("2026-04-29T10:03:00Z", _usage(total=2_300)),
        ],
    )

    records = parse_session_file(path)

    assert [record.session_id for record in records] == ["fork-session", "fork-session"]
    assert [record.project_key for record in records] == ["/repo/fork", "/repo/fork"]
    assert [record.usage.total_tokens for record in records] == [100, 200]
    assert summarize_records(records).usage.total_tokens == 300


def test_parser_treats_first_root_token_count_in_forked_file_as_baseline(tmp_path: Path) -> None:
    path = _write_session(
        tmp_path,
        [
            _session_meta(cwd="/repo/fork", session_id="fork-session", forked_from_id="parent-session"),
            _turn_context(model="gpt-5.5"),
            _token("2026-04-29T10:00:00Z", _usage(total=2_000)),
            _token("2026-04-29T10:01:00Z", _usage(total=2_300)),
        ],
    )

    records = parse_session_file(path)

    assert [record.session_id for record in records] == ["fork-session"]
    assert [record.usage.total_tokens for record in records] == [300]


def test_aggregation_accumulates_api_cost_and_codex_credits(tmp_path: Path) -> None:
    path = _write_session(
        tmp_path,
        [
            _session_meta(cwd="/repo/demo"),
            _turn_context(model="gpt-5.3-codex"),
            _token("2026-04-29T10:00:00Z", _usage(total=1_100_000, input_tokens=1_000_000, cached=250_000, output=100_000)),
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


def test_aggregation_prices_records_with_rates_effective_at_each_timestamp(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(
        pricing,
        "API_PRICING_USD_SCHEDULE",
        (
            EffectiveModelRate(
                model_key="gpt-test-effective",
                effective_from=datetime(1970, 1, 1, tzinfo=UTC),
                rate=ModelRate(input_per_1m=1.0, cached_input_per_1m=0.1, output_per_1m=10.0),
            ),
            EffectiveModelRate(
                model_key="gpt-test-effective",
                effective_from=datetime(2026, 8, 18, tzinfo=UTC),
                rate=ModelRate(input_per_1m=2.0, cached_input_per_1m=0.2, output_per_1m=20.0),
            ),
        ),
    )
    records = [
        UsageRecord(
            timestamp=datetime(2026, 8, 17, 12, tzinfo=UTC),
            usage=TokenUsage(input_tokens=1_000_000, output_tokens=100_000, total_tokens=1_100_000),
            session_id="before",
            file_path=tmp_path / "before.jsonl",
            model="gpt-test-effective",
        ),
        UsageRecord(
            timestamp=datetime(2026, 8, 18, 12, tzinfo=UTC),
            usage=TokenUsage(input_tokens=1_000_000, output_tokens=100_000, total_tokens=1_100_000),
            session_id="after",
            file_path=tmp_path / "after.jsonl",
            model="gpt-test-effective",
        ),
    ]

    total = summarize_records(records)

    assert total.cost.total_usd == 6.0
    assert total.cost.unpriced_tokens == 0


def test_project_grouping_falls_back_to_cwd_when_git_missing(tmp_path: Path) -> None:
    path = _write_session(
        tmp_path,
        [
            _session_meta(cwd="D:\\Projects\\Demo"),
            _turn_context(model="gpt-5.5"),
            _token("2026-04-29T10:00:00Z", _usage(total=100)),
        ],
    )

    record = parse_session_file(path)[0]

    assert record.project_key == "d:/projects/demo"
    assert record.project_label == "Demo"


def test_project_grouping_resolves_missing_git_url_from_cwd_git_config(tmp_path: Path) -> None:
    repo = tmp_path / "Persona_Generators"
    nested = repo / "src" / "feature"
    git_dir = repo / ".git"
    nested.mkdir(parents=True)
    git_dir.mkdir()
    (git_dir / "config").write_text(
        "\n".join(
            [
                "[core]",
                "\trepositoryformatversion = 0",
                '[remote "origin"]',
                "\turl = https://github.com/Wenjun-Mao/persona_generators.git",
            ]
        ),
        encoding="utf-8",
    )
    path = _write_session(
        tmp_path / "session",
        [
            _session_meta(cwd=str(nested)),
            _turn_context(model="gpt-5.5"),
            _token("2026-04-29T10:00:00Z", _usage(total=100)),
        ],
    )

    record = parse_session_file(path)[0]

    assert record.project_key == "https://github.com/wenjun-mao/persona_generators"
    assert record.project_label == "persona_generators"
    assert _normalized_path(str(nested)) in record.project_aliases


def test_project_grouping_prefers_json_git_url_over_cwd_git_config(tmp_path: Path) -> None:
    repo = tmp_path / "demo"
    git_dir = repo / ".git"
    repo.mkdir()
    git_dir.mkdir()
    (git_dir / "config").write_text(
        '[remote "origin"]\n\turl = https://github.com/example/from-cwd.git\n',
        encoding="utf-8",
    )
    path = _write_session(
        tmp_path / "session",
        [
            _session_meta(cwd=str(repo), repo="https://github.com/example/from-json.git"),
            _turn_context(model="gpt-5.5"),
            _token("2026-04-29T10:00:00Z", _usage(total=100)),
        ],
    )

    record = parse_session_file(path)[0]

    assert record.project_key == "https://github.com/example/from-json"
    assert _normalized_path(str(repo)) in record.project_aliases


def test_project_grouping_normalizes_ssh_git_remotes(tmp_path: Path) -> None:
    repo = tmp_path / "demo"
    git_dir = repo / ".git"
    repo.mkdir()
    git_dir.mkdir()
    (git_dir / "config").write_text(
        '[remote "origin"]\n\turl = git@github.com:Wenjun-Mao/persona_generators.git\n',
        encoding="utf-8",
    )
    path = _write_session(
        tmp_path / "session",
        [
            _session_meta(cwd=str(repo)),
            _turn_context(model="gpt-5.5"),
            _token("2026-04-29T10:00:00Z", _usage(total=100)),
        ],
    )

    record = parse_session_file(path)[0]

    assert record.project_key == "https://github.com/wenjun-mao/persona_generators"


def test_project_aggregation_combines_json_git_url_and_cwd_resolved_repo(tmp_path: Path) -> None:
    repo = tmp_path / "persona_generators"
    git_dir = repo / ".git"
    repo.mkdir()
    git_dir.mkdir()
    (git_dir / "config").write_text(
        '[remote "origin"]\n\turl = git@github.com:Wenjun-Mao/persona_generators.git\n',
        encoding="utf-8",
    )
    first = _write_session(
        tmp_path / "first",
        [
            _session_meta(
                cwd=str(repo),
                repo="https://github.com/Wenjun-Mao/persona_generators.git",
                session_id="session-1",
            ),
            _turn_context(model="gpt-5.5"),
            _token("2026-04-29T10:00:00Z", _usage(total=100)),
        ],
    )
    second = _write_session(
        tmp_path / "second",
        [
            _session_meta(cwd=str(repo), session_id="session-2"),
            _turn_context(model="gpt-5.5"),
            _token("2026-04-29T10:00:00Z", _usage(total=75)),
        ],
    )
    records = parse_session_file(first) + parse_session_file(second)

    rows = aggregate_records(records, "project", resolve_timezone("UTC"))

    assert [(row.key, row.usage.total_tokens) for row in rows] == [
        ("https://github.com/wenjun-mao/persona_generators", 175)
    ]
    assert summarize_records(
        filter_records_by_project_keys(records, ["https://github.com/wenjun-mao/persona_generators"])
    ).usage.total_tokens == 175
    assert summarize_records(filter_records_by_project_keys(records, [_normalized_path(str(repo))])).usage.total_tokens == 175


def test_project_filter_supports_empty_single_multiple_and_unmatched_keys(tmp_path: Path) -> None:
    first = _write_session(
        tmp_path / "first",
        [
            _session_meta(cwd="/repo/first"),
            _turn_context(model="gpt-5.5"),
            _token("2026-04-29T10:00:00Z", _usage(total=100)),
        ],
    )
    second = _write_session(
        tmp_path / "second",
        [
            _session_meta(cwd="/repo/second"),
            _turn_context(model="gpt-5.5"),
            _token("2026-04-29T10:00:00Z", _usage(total=75)),
        ],
    )
    records = parse_session_file(first) + parse_session_file(second)

    assert summarize_records(filter_records_by_project_keys(records, [])).usage.total_tokens == 175
    assert summarize_records(filter_records_by_project_keys(records, ["/repo/first"])).usage.total_tokens == 100
    assert summarize_records(filter_records_by_project_keys(records, ["/repo/first", "/repo/second"])).usage.total_tokens == 175
    assert filter_records_by_project_keys(records, ["/repo/missing"]) == []


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
    assert [row.key for row in hour_rows] == ["2026-04-28 23:00", "2026-04-29 00:00"]


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


def _write_session(tmp_path: Path, rows: list[dict]) -> Path:
    tmp_path.mkdir(parents=True, exist_ok=True)
    path = tmp_path / "session.jsonl"
    path.write_text("\n".join(json.dumps(row) for row in rows), encoding="utf-8")
    return path


def _session_meta(cwd: str = "/repo/demo", repo: str = "", session_id: str = "session-1", forked_from_id: str = "") -> dict:
    git = {"repository_url": repo, "branch": "main"} if repo else {}
    payload = {
        "id": session_id,
        "timestamp": "2026-04-29T09:59:00Z",
        "cwd": cwd,
        "source": "vscode",
        "originator": "codex_vscode",
        "cli_version": "0.1.0",
        "git": git,
    }
    if forked_from_id:
        payload["forked_from_id"] = forked_from_id
    return {
        "timestamp": "2026-04-29T09:59:00Z",
        "type": "session_meta",
        "payload": payload,
    }


def _turn_context(model: str) -> dict:
    return {
        "timestamp": "2026-04-29T09:59:30Z",
        "type": "turn_context",
        "payload": {
            "turn_id": f"turn-{model}",
            "model": model,
            "effort": "medium",
            "collaboration_mode": {"mode": "default", "settings": {"model": model, "reasoning_effort": "medium"}},
        },
    }


def _token(timestamp: str, usage: dict | None) -> dict:
    return {
        "timestamp": timestamp,
        "type": "event_msg",
        "payload": {
            "type": "token_count",
            "info": None if usage is None else {"total_token_usage": usage},
        },
    }


def _usage(total: int, input_tokens: int | None = None, cached: int = 0, output: int | None = None) -> dict:
    input_value = input_tokens if input_tokens is not None else total
    output_value = output if output is not None else 0
    return {
        "input_tokens": input_value,
        "cached_input_tokens": cached,
        "output_tokens": output_value,
        "reasoning_output_tokens": 0,
        "total_tokens": total,
    }


def _normalized_path(value: str) -> str:
    return value.replace("\\", "/").rstrip("/").casefold()

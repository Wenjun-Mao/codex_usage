from argparse import Namespace
from datetime import UTC, datetime
from pathlib import Path

from codex_usage import cli
from codex_usage.aggregation import aggregate_valued_records
from codex_usage.models import TokenUsage, UsageRecord
from codex_usage.session_cache import CacheStats
from codex_usage.usage_context import UsageContext


def test_handle_report_builds_one_breakdown_without_project_or_model_aggregation(
    monkeypatch, tmp_path: Path
) -> None:
    record = UsageRecord(
        timestamp=datetime(2026, 4, 29, tzinfo=UTC),
        usage=TokenUsage(input_tokens=10, total_tokens=10),
        session_id="session-1",
        file_path=tmp_path / "session.jsonl",
        usage_role="root",
        model="gpt-5.6-sol",
        project_key="repo",
        project_label="repo",
    )
    context = UsageContext(
        session_dirs=[tmp_path],
        files=[record.file_path],
        records=[record],
        timezone=UTC,
        project_keys=[],
        project_transitions=[],
        storage_stats=CacheStats(),
    )
    args = Namespace(
        output=tmp_path / "report.html",
        range_name="all",
        theme="night",
    )
    aggregate_groups: list[str] = []
    valuation_calls: list[list[UsageRecord]] = []
    breakdown_calls = 0
    captured: dict[str, object] = {}
    real_value_records = cli.value_records
    real_build_breakdown = cli.build_report_breakdown_from_valued

    def track_aggregate(valued_records, group_by, timezone):
        aggregate_groups.append(group_by)
        return aggregate_valued_records(valued_records, group_by, timezone)

    def track_value(records: list[UsageRecord]):
        valuation_calls.append(records)
        return real_value_records(records)

    def capture_report(
        *,
        output_path,
        generated_at,
        range_name,
        total,
        daily_rows,
        hourly_rows,
        breakdown,
        sessions_dirs,
        files_scanned,
        storage_roots=None,
        files_archived=0,
        files_retained_missing=0,
        project_keys=None,
        project_transitions=None,
        theme="auto",
    ):
        captured["breakdown"] = breakdown
        return output_path

    def track_breakdown(valued_records):
        nonlocal breakdown_calls
        breakdown_calls += 1
        return real_build_breakdown(valued_records)

    monkeypatch.setattr(cli, "load_usage_context", lambda args: context)
    monkeypatch.setattr(cli, "value_records", track_value)
    monkeypatch.setattr(cli, "aggregate_valued_records", track_aggregate)
    monkeypatch.setattr(cli, "build_report_breakdown_from_valued", track_breakdown)
    monkeypatch.setattr(cli, "render_html_report", capture_report)

    assert cli.handle_report(args) == 0
    assert valuation_calls == [context.records]
    assert aggregate_groups == ["day", "hour"]
    assert breakdown_calls == 1
    assert captured["breakdown"].project_rows[0].key == "repo"  # type: ignore[union-attr]

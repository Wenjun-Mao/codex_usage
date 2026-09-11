from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from codex_usage.aggregation import summarize_valued_records, value_records
from codex_usage.models import TokenUsage, UsageRecord
from codex_usage.project_economics import build_project_economics
from codex_usage.report_breakdown import build_report_breakdown_from_valued
from codex_usage.reporting import render_html_report


def test_report_renders_compact_accessible_project_economics_from_precomputed_ledger(
    tmp_path: Path,
) -> None:
    records = [
        _record("alpha", "alpha-turn", "gpt-5.6-sol", 100, cache_write=30),
        _record("alpha", "alpha-turn", "gpt-5.6-terra", 50, cache_write=10),
        _record("beta", "beta-turn", "gpt-5.6-sol", 40, cache_write=0),
        _record("beta", "", "unknown-model", 20, cache_write=0),
    ]
    valued = value_records(records)
    output = tmp_path / "report.html"

    render_html_report(
        output_path=output,
        generated_at=datetime(2026, 9, 10, tzinfo=UTC),
        range_name="all",
        total=summarize_valued_records(valued),
        daily_rows=[],
        hourly_rows=[],
        breakdown=build_report_breakdown_from_valued(valued),
        sessions_dirs=[Path("sessions")],
        files_scanned=1,
        project_economics=build_project_economics(valued),
    )

    html = output.read_text(encoding="utf-8")

    assert 'data-report-section="project-economics"' in html
    assert 'aria-labelledby="project-economics-heading"' in html
    assert "Weighted all-project benchmark" in html
    assert "Ledger only" in html
    assert "alpha" in html and "beta" in html
    assert "Small sample" in html
    assert '<details class="project-economics-project">' in html
    assert '<th scope="col">Model</th>' in html
    assert '<th scope="row">gpt-5.6-sol</th>' in html
    assert "Priceable turns only" in html
    assert '<details class="token-accounting">' in html
    assert '<summary>Token Accounting</summary>' in html
    assert "Cache Write (reported) is taken from the selected ledger exactly as Codex reported it" in html
    assert '<th class="num">Cache Write (reported)</th>' in html
    assert "fetch(" not in html
    assert "XMLHttpRequest" not in html
    assert "<script" not in html


def _record(
    project: str,
    turn_id: str,
    model: str,
    total: int,
    *,
    cache_write: int,
) -> UsageRecord:
    return UsageRecord(
        timestamp=datetime(2026, 9, 10, tzinfo=UTC),
        usage=TokenUsage(
            input_tokens=total,
            cached_input_tokens=total // 2,
            cache_write_input_tokens=cache_write,
            output_tokens=total // 10,
            total_tokens=total,
        ),
        session_id=f"{project}-session",
        turn_id=turn_id,
        file_path=Path("session.jsonl"),
        usage_role="root",
        model=model,
        project_key=project,
        project_label=project,
    )

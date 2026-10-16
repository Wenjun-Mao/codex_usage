from __future__ import annotations

from datetime import UTC, datetime
from html.parser import HTMLParser
from pathlib import Path

from codex_usage.aggregation import (
    UsageSummary,
    ValuedUsageRecord,
    summarize_valued_records,
    value_records,
)
from codex_usage.models import TokenUsage, UsageRecord
from codex_usage.project_economics import build_project_economics
from codex_usage.pricing import CostBreakdown, CreditBreakdown
from codex_usage.report_breakdown import build_report_breakdown_from_valued
from codex_usage.report_numbers import adaptive_usd, compact_token_count
from codex_usage.reporting import render_html_report
from codex_usage.report_tables import render_project_economics_section


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
    assert "Response cost averages use fully priced responses; turn cost averages use fully priced turns." in html
    assert "alpha" in html and "beta" in html
    assert "Small sample" in html
    assert '<details class="project-economics-project">' in html
    assert '<th scope="col">Model</th>' in html
    assert '<th scope="row">gpt-5.6-sol</th>' in html
    assert 'aria-label="Average API-equivalent cost per response"' in html
    assert "Cost / resp." in html
    assert 'aria-label="Average API-equivalent cost per turn"' in html
    assert "Cost / turn" in html
    assert "Responses / turn" in html
    assert "Tokens / turn" in html
    assert "Measured turns" in html
    assert "Totals, shares, coverage and priceability" in html
    assert "Response coverage" in html
    assert "Token coverage" in html
    assert "Average cost / turn" in html
    assert "Priceable turns only" in html
    assert '<details class="token-accounting">' in html
    assert '<summary>Token Accounting</summary>' in html
    assert "Cache Write (reported) is taken from the selected ledger exactly as Codex reported it" in html
    assert '<th class="num">Cache Write (reported)</th>' in html
    assert "fetch(" not in html
    assert "XMLHttpRequest" not in html
    assert "<script" not in html


def test_project_model_comparison_preserves_model_grain_and_secondary_evidence() -> None:
    report = build_project_economics(
        (
            _valued_record("turn-a", "gpt-6.1-sol", 1_200, 0.00001234),
            _valued_record("turn-a", "gpt-6.1-sol", 1_200, 0.00001234),
            _valued_record("turn-a", "gpt-6-astra", 500, 0.00001235),
            _valued_record("turn-b", "gpt-6-astra", 500, 0.00001235),
            _valued_record("turn-c", "gpt-6-luna", 100, 0.0),
            _valued_record("turn-unpriced", "unknown-model-no-price", 80, 0.0, unpriced=80),
            _valued_record("", "unknown-model-no-turn", 40, 0.0, unpriced=40),
        )
    )

    markup = render_project_economics_section(report)

    assert '<table class="project-economics-models"' in markup
    assert 'aria-label="Per-model comparison for Research &amp; Tools"' in markup
    primary = markup.split('<table class="project-economics-models"', 1)[1].split(
        "</table>", 1
    )[0]
    assert "$0.0000123" in primary
    assert "$0.0000124" in primary
    assert "$0.00001234" in markup
    assert "$0.00001235" in markup
    assert "$0.0000" in markup
    assert "2.0" in markup and "2.4K" in markup
    assert "1.0" in markup and ">500<" in markup
    assert "Unavailable" in markup
    assert "Small sample" in markup
    assert "2 / 2 responses; 1 / 1 turns" in markup
    assert "0 / 1 responses; 0 / 1 turns" in markup
    assert "0 / 1 (0%); 1 missing turn IDs" in markup
    assert "0 / 40 (0%); 40 missing-turn tokens" in markup
    assert 'Exact: $0.00001234' in markup
    assert "Totals, shares, coverage and priceability" in markup


def test_aggregated_response_cohorts_hide_float_noise_but_keep_exact_details() -> None:
    report = build_project_economics(
        (
            _valued_record("single-turn", "single-response", 100, 0.10),
            _valued_record("three-turn-a", "three-responses", 100, 0.10),
            _valued_record("three-turn-b", "three-responses", 100, 0.10),
            _valued_record("three-turn-c", "three-responses", 100, 0.10),
        )
    )
    models = {model.key: model for model in report.projects[0].models}

    assert models["single-response"].metrics.average_cost_per_response == 0.1
    assert models["three-responses"].metrics.average_cost_per_response == 0.10000000000000002

    markup = render_project_economics_section(report)
    primary = markup.split('<table class="project-economics-models"', 1)[1].split(
        "</table>", 1
    )[0]
    assert primary.count("$0.1000") == 4
    assert "0.10000000000000002" not in primary
    assert "Exact: $0.1" in markup
    assert "Exact: $0.10000000000000002" in markup


def test_economics_display_numbers_distinguish_zero_and_tiny_costs() -> None:
    labels = adaptive_usd((0, 0.00001234, 0.00001235, None))
    assert labels == ("$0.0000", "$0.0000123", "$0.0000124", "Unavailable")
    assert adaptive_usd((0.00000012,)) == ("$0.0000001",)
    assert adaptive_usd((0, 0.00000012, 0.00000013)) == (
        "$0.0000",
        "$0.00000012",
        "$0.00000013",
    )
    assert adaptive_usd((0.0261312345, 0.24255351)) == ("$0.0261", "$0.2426")
    assert adaptive_usd((0.1, 0.10000000000000002)) == ("$0.1000", "$0.1000")

    subnano = adaptive_usd((0, 1e-13, 2e-13))
    assert subnano == ("$0.0000", "<$0.000000001", "<$0.000000001")

    assert compact_token_count(999) == "999"
    assert compact_token_count(2_400) == "2.4K"
    assert compact_token_count(1_250_000) == "1.25M"
    assert compact_token_count(None) == "Unavailable"


def test_primary_turn_cost_uses_fully_priced_model_turns_not_response_averages() -> None:
    report = build_project_economics((
        _valued_record("shared", "gpt-6.1-sol", 100, 0.1),
        _valued_record("shared", "gpt-6.1-sol", 100, 0.1),
        _valued_record("", "gpt-6.1-sol", 100, 99.0),
        _valued_record("shared", "gpt-6-astra", 100, 0.3),
        _valued_record("partial-a", "partial", 100, 0.2),
        _valued_record("partial-a", "partial", 100, 0.0, unpriced=100),
        _valued_record("partial-b", "partial", 100, 0.4),
        _valued_record("unpriced-turn", "no-priced-turns", 100, 0.2),
        _valued_record("unpriced-turn", "no-priced-turns", 100, 0.0, unpriced=100),
        _valued_record("zero", "gpt-6-luna", 100, 0.0),
        _valued_record("", "no-turn", 100, 0.5),
    ))
    parsed = _PrimaryRows()
    parsed.feed(render_project_economics_section(report))

    assert parsed.rows["gpt-6.1-sol"][1:3] == [
        ("$0.1000", "2 of 2 responses priceable"),
        ("$0.2000", "1 of 1 turns priceable"),
    ]
    assert parsed.rows["gpt-6-astra"][2] == ("$0.3000", "1 of 1 turns priceable")
    assert parsed.rows["partial"][1:3] == [
        ("$0.3000", "2 of 3 responses priceable"),
        ("$0.4000", "1 of 2 turns priceable"),
    ]
    assert parsed.rows["no-priced-turns"][1:3] == [
        ("$0.2000", "1 of 2 responses priceable"), ("Unavailable", ""),
    ]
    assert parsed.rows["gpt-6-luna"][2] == ("$0.0000", "1 of 1 turns priceable")
    assert parsed.rows["no-turn"][1:3] == [("Unavailable", ""), ("Unavailable", "")]
    assert all(len(row) == 6 for row in parsed.rows.values())


class _PrimaryRows(HTMLParser):
    def __init__(self):
        super().__init__()
        self.active = False
        self.rows = {}
        self.row = []
        self.cell = None
        self.title = ""

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "table":
            self.active = attrs.get("class") == "project-economics-models"
        elif self.active and tag == "tr":
            self.row = []
        elif self.active and tag in ("td", "th"):
            self.cell, self.title = [], ""
        elif self.active and tag == "span" and self.cell is not None:
            self.title = attrs.get("title", "")

    def handle_data(self, data):
        if self.active and self.cell is not None:
            self.cell.append(data)

    def handle_endtag(self, tag):
        if self.active and tag in ("td", "th"):
            self.row.append(("".join(self.cell), self.title))
            self.cell = None
        elif self.active and tag == "tr" and self.row[0][0] != "Model":
            self.rows[self.row[0][0]] = self.row
        elif tag == "table":
            self.active = False


def test_project_economics_empty_populations_remain_inspectable() -> None:
    markup = render_project_economics_section(build_project_economics(()))
    assert "No positive ledger usage is available for project economics." in markup
    assert render_project_economics_section(None) == ""


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


def _valued_record(
    turn_id: str,
    model: str,
    tokens: int,
    cost_usd: float,
    *,
    unpriced: int = 0,
) -> ValuedUsageRecord:
    usage = TokenUsage(input_tokens=tokens, total_tokens=tokens)
    return ValuedUsageRecord(
        record=UsageRecord(
            timestamp=datetime(2026, 9, 10, tzinfo=UTC),
            usage=usage,
            session_id="research-session",
            turn_id=turn_id,
            file_path=Path("synthetic.jsonl"),
            usage_role="root",
            model=model,
            project_key="research-tools",
            project_label="Research & Tools",
        ),
        summary=UsageSummary(
            usage=usage,
            cost=CostBreakdown(total_usd=cost_usd, unpriced_tokens=unpriced),
            credits=CreditBreakdown(unpriced_tokens=unpriced),
            record_count=1,
        ),
    )

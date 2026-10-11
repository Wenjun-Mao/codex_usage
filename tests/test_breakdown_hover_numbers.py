"""Readable, immediate chart labels must not alter accounting or time domains."""
from datetime import UTC, datetime, timedelta
from html.parser import HTMLParser
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest

from codex_usage.breakdown_aggregation import empty
from codex_usage.report_allowance import money
from codex_usage.report_breakdown_axis import time_axis
from codex_usage.report_breakdown_hover import bucket_hover, css
from codex_usage.report_numbers import decimal_text, estimated_credits, summary_money, percentage_text
from codex_usage.report_breakdown_numbers import compact_decimal
from codex_usage.report_tables import format_credits
from codex_usage.report_usage_breakdown import detail_table
from codex_usage.report_view import _fmt_credits


class Ticks(HTMLParser):
    def __init__(self, document):
        super().__init__()
        self.labels = []
        self.exact = []
        self.inside = False
        self.feed(document)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "span" and "ub-tick " in attrs.get("class", ""):
            self.inside = True
            self.labels.append("")
            self.exact.append(attrs["title"])
        if tag == "br" and self.inside:
            self.labels[-1] += "\n"

    def handle_endtag(self, tag):
        if tag == "span":
            self.inside = False

    def handle_data(self, data):
        if self.inside:
            self.labels[-1] += data


@pytest.mark.parametrize("value,expected", [
    (74.19778399999994, "74.20"), (17.814169600000003, "17.81"),
    (0.1 + 0.2, "0.30"), (0, "0.00"), (-0.0, "0.00"),
    (.000001, "0.000001"), (1234567.891, "1,234,567.89"),
    (1e-30, "<0.000001"), (-1e-30, ">-0.000001"),
])
def test_decimal_display_is_bounded_but_does_not_erase_nonzero(value, expected):
    assert decimal_text(value) == expected


@pytest.mark.parametrize("value,expected", [
    (0, "0.0"), (.04, "0.04"), (.00001, "0.00001"),
    (1.0175831999999995, "1.0"), (17782.45, "17,782"),
])
def test_all_credit_summary_callers_use_readable_nonzero_labels(value, expected):
    assert estimated_credits(value) == format_credits(value) == _fmt_credits(value) == expected


@pytest.mark.parametrize("value,expected", [(0, "$0.00"), (.005, "<$0.01"),
    (.009, "<$0.01"), (.01, "$0.01"), (74.19778399999994, "$74.20")])
def test_small_summary_dollars_are_not_known_zero(value, expected):
    assert summary_money(value) == expected
    assert money(value) == expected.replace("<", "&lt;")


@pytest.mark.parametrize("value,expected", [(0, "0"), (100, "100"),
    (99.99999, ">99.99"), (.00001, "<0.01"), (12.345, "12.34"), (50, "50")])
def test_percentages_do_not_claim_saturation_or_use_scientific_notation(value, expected):
    assert percentage_text(value) == expected


def test_chart_precision_is_bounded_and_tiny_nonzero_stays_distinct():
    assert compact_decimal(1e-30, unit="cost") == "<$0.000001"
    assert compact_decimal(-1e-30) == ">-0.000001"
    assert estimated_credits(1e-30) == "<0.000001"


def test_tiny_balance_axes_rescale_instead_of_collapsing_distinct_ticks():
    from codex_usage.report_breakdown_balances import balance_ticks
    axis, offset = balance_ticks(Decimal(0), Decimal("2e-20"))
    assert offset == 0
    assert '× 10<sup>-20</sup> credits' in axis
    assert '>2</span>' in axis and '>1</span>' in axis and '>0</span>' in axis
    assert 'title="0.00000000000000000002 credits"' in axis


@pytest.mark.parametrize("used,label", [(99.99999, "&lt;0.01%"), (.00001, "&gt;99.99%")])
def test_weekly_overlay_uses_the_same_bounded_percentage_contract(used, label):
    from codex_usage.report_breakdown_overlay import captured_layer
    start = datetime(2026, 10, 10, tzinfo=UTC)
    point = {"timestamp": start.isoformat(), "limit_id": "codex", "plan": "pro",
        "slot": "primary", "duration_minutes": 10080, "used_percent": used,
        "resets_at": int(start.timestamp())+604800, "provenance": "synthetic"}
    layer = captured_layer([point], "weekly", start.timestamp(), start.timestamp()+86400,
        UTC, ["#087ea4"], compact_key=True)
    assert "Latest: " + label in layer.key
    assert label + " remaining" in layer.marks
    exact = captured_layer([point], "weekly", start.timestamp(), start.timestamp()+86400,
        UTC, ["#087ea4"], inspection=True)
    assert repr(used) + "% used" in exact.evidence


def test_hover_formats_each_series_and_preserves_issued_navigation():
    href = 'command:codexUsage.navigateBreakdown?issued="abc"&value=1'
    document = bucket_hover("2026-10-10 21:00 -0400", {"astra": 74.19778399999994,
        "sol": 17.814169600000003, "luna": 1.0175831999999995}, "cost",
        {"astra": "#087ea4", "sol": "#24896e", "luna": "#bf4565"},
        {"sol": "Sol & friends"}, left=25, width=5, top=7, height=180, center=27.5,
        href=href, incomplete=True)
    assert "$74.20" in document and "$17.81" in document and "$1.02" in document
    assert "74.19778399999994" not in document
    assert "Sol &amp; friends" in document and 'issued=&quot;abc&quot;&amp;value=1' in document
    assert 'aria-label="Inspect ' in document and 'tabindex="0"' in document
    assert 'class="ub-hover-hit" title=""' in document
    assert "not zero" in document and "<title>" not in document and "<script" not in document
    assert 'Known total $93.03' in document
    assert "transition:none" in css() and ":focus-visible" in css()


def test_detail_table_rounds_presentation_without_mutating_source_values():
    row = {**empty(), "project": "demo", "label": "Demo", "model": "astra",
        "tokens": 1234567, "cost": 74.19778399999994, "credits": .04,
        "unknown": 1, "api_excluded": 2, "credit_unknown": 3}
    original = dict(row)
    document = detail_table([row], {"value": None, "reason": "not enough evidence"},
        {}, {}, selected_projects={})
    assert "$74.20" in document and "0.04 + unknown" in document
    assert "1,234,567" in document and "API-excluded review tokens 2" in document
    assert "74.19778399999994" not in document and row == original


def test_single_day_ticks_show_hours_and_date_zone_once():
    zone = ZoneInfo("America/Toronto")
    start = datetime(2026, 10, 10, tzinfo=zone)
    document = time_axis(start.timestamp(), (start+timedelta(days=1)).timestamp(), zone)
    ticks = Ticks(document)
    assert ticks.labels[0] == "00:00" and ticks.labels[-1] == "24:00"
    assert all("\n" not in label and "Oct" not in label for label in ticks.labels)
    assert "Oct 10, 2026 · America/Toronto · UTC-04:00" in document
    assert ticks.exact[0] == "2026-10-10 00:00:00 -0400"
    assert '--ub-tick-rows:1' in document


def test_multiple_days_use_two_rows_without_repeated_offset_rows():
    start = datetime(2026, 10, 4, tzinfo=UTC)
    document = time_axis(start.timestamp(), (start+timedelta(days=7)).timestamp(), UTC)
    ticks = Ticks(document)
    assert all(label.count("\n") == 1 for label in ticks.labels)
    assert all("+0000" not in label for label in ticks.labels)
    assert "UTC+00:00" in document and '--ub-tick-rows:2' in document


def test_dst_offset_change_stays_explicit_without_a_third_row():
    zone = ZoneInfo("America/Toronto")
    start = datetime(2026, 11, 1, tzinfo=zone)
    end = start + timedelta(days=1)
    document = time_axis(start.timestamp(), end.timestamp(), zone)
    ticks = Ticks(document)
    assert ticks.labels[0] == "00:00 EDT" and ticks.labels[-1] == "24:00 EST"
    assert "UTC-04:00 / UTC-05:00" in document
    assert all(label.count("\n") == 0 for label in ticks.labels)

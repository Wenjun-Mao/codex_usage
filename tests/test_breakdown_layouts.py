"""Selected axis-linked presentation preserves values and captured identities."""
from datetime import UTC, datetime, timedelta
from html.parser import HTMLParser
import re
from pathlib import Path
from runpy import run_path
from xml.etree import ElementTree

import pytest

from codex_usage.report_usage_breakdown_chart import plot
from codex_usage.report_breakdown_overlay import overlay
from codex_usage.report_usage_breakdown_chart import COLORS


AT = datetime(2026, 10, 4, tzinfo=UTC)


def inputs(kind="weekly"):
    points = [{"timestamp": (AT + timedelta(hours=i)).isoformat(), "limit_id": "codex",
        "plan": "pro", "slot": "primary", "duration_minutes": 10080, "used_percent": i * 20,
        "resets_at": int((AT+timedelta(days=7)).timestamp()), "reset_credits": None,
        "provenance": "synthetic", "_boundary": True} for i in range(5)]
    if kind == "balance":
        points = [{"timestamp": p["timestamp"], "plan": "pro", "balance": str(10000-i),
            "unlimited": False, "diagnostic": ""} for i, p in enumerate(points)]
    return {"bars": [{"sol": 125, "astra": 37.5}, {"sol": 20, "astra": 0}],
        "metric": "cost", "labels": ["sol", "astra"], "timezone": UTC, "daily": True,
        "title": "Daily selected range", "bucket_labels": ["Oct 4", "Oct 5"],
        "intervals": [(AT.timestamp(), (AT+timedelta(days=1)).timestamp()),
            ((AT+timedelta(days=1)).timestamp(), (AT+timedelta(days=2)).timestamp())],
        "account_points": points, "account_overlay": kind, "incomplete": [True, False]}


def svgs(document):
    return [ElementTree.fromstring(svg) for svg in re.findall(r"<svg\b[^>]*>.*?</svg>", document, re.DOTALL)]


def visible_text(fragment):
    class Text(HTMLParser):
        def __init__(self):
            super().__init__()
            self.parts = []

        def handle_data(self, data):
            self.parts.append(data)
    reader = Text()
    reader.feed(fragment)
    return " ".join(reader.parts)


def account_marks(document):
    return [mark for svg in svgs(document) for mark in svg if mark.attrib.get("class") == "ub-account-point"]


@pytest.mark.parametrize("metric", ["tokens", "cost", "credits"])
@pytest.mark.parametrize("kind", ["weekly", "balance"])
def test_selected_layout_preserves_account_evidence(metric, kind):
    kwargs = {**inputs(kind), "metric": metric}
    candidate = plot(**kwargs)
    marks, _, _, _ = overlay(kwargs["account_points"], kind,
        kwargs["intervals"][0][0], kwargs["intervals"][-1][1], UTC, COLORS)
    original = ElementTree.fromstring("<g>" + marks + "</g>")
    assert len(account_marks(candidate)) == len(original)
    for source, result in zip(original, account_marks(candidate)):
        assert source.attrib == result.attrib
    assert candidate.count('class="ub-time-axis"') == 1
    assert candidate.count('class="ub-legend ub-meter-legend"') == 1
    assert candidate.count('<svg') == 1


def test_axis_keys_belong_to_the_corresponding_marks():
    document = plot(**inputs())
    assert 'ub-linked-head' in document and 'ub-right-axis' in document
    assert 'API-equivalent cost ($)' in document and '<strong>Allowance Remaining</strong>' in document
    assert document.index('class="ub-linked-heading ub-account-heading"') < document.index('<svg')
    assert all("right axis" in point.attrib["aria-label"] for point in account_marks(document))
    header = document.split('<div class="ub-linked-heading ub-account-heading">', 1)[1].split('</div></div>', 1)[0]
    assert visible_text(header) == "Allowance Remaining Latest: 20%"
    assert "account-wide" in header and "codex / pro" in header
    assert "2026-10-04T04:00:00+00:00" in header and 'tabindex="0"' in header


def test_no_account_selection_has_one_usage_plot_and_no_account_key():
    candidate = plot(**inputs("none"))
    assert candidate.count('<svg') == 1
    assert '<strong>Allowance Remaining</strong>' not in candidate
    assert not account_marks(candidate)
    svg = svgs(candidate)[0]
    assert svg.attrib["height"] == "188"
    assert svg.attrib["viewBox"] == "0 -4 720 188"
    assert svg.attrib["style"] == "width:100.000000%;margin-left:0.000000%"


def test_plot_viewport_includes_boundary_marker_hit_areas():
    document = plot(**inputs("balance"))
    svg = svgs(document)[0]
    assert svg.attrib["height"] == "188"
    assert svg.attrib["viewBox"] == "-4 -4 728 188"
    assert svg.attrib["style"] == "width:101.111111%;margin-left:-0.555556%"
    assert min(float(point.attrib["cy"]) for point in account_marks(document)) == 0
    assert max(float(point.attrib["cy"]) for point in account_marks(document)) == 180


def test_narrow_bars_keep_centers_and_exact_heights():
    document = plot(**inputs())
    bars = [mark for mark in svgs(document)[0] if mark.tag == "rect"]
    assert all(float(bar.attrib["width"]) == 180 for bar in bars)
    assert [float(bar.attrib["x"]) + float(bar.attrib["width"])/2 for bar in bars] == [180, 180, 540]
    assert float(bars[0].attrib["height"]) == pytest.approx(125 / 200 * 180)
    assert "sol: $125.00" in bars[0].find("desc").text
    assert bars[0].find("title") is None


def test_below_resolution_values_use_ticks_not_circles_or_inflated_bars():
    document = plot([{"sol": 100, "luna": .0001}], metric="cost", labels=["sol", "luna"])
    svg = svgs(document)[0]
    ticks = [mark for mark in svg if mark.attrib.get("class") == "ub-tiny-segment"]
    assert len(ticks) == 1 and ticks[0].tag == "line"
    assert "luna: $0.0001" in ticks[0].find("desc").text
    assert not any(mark.tag == "circle" for mark in svg)
    assert document.count('<rect') == 1
    assert 'class="ub-resolution-evidence"' not in document and "Small segments" not in document


def test_multiple_account_identities_remain_visible():
    kwargs = inputs()
    kwargs["account_points"] += [{**kwargs["account_points"][-1], "limit_id": "secondary", "plan": "plus"}]
    document = plot(**kwargs)
    header = document.split('<div class="ub-linked-heading ub-account-heading">', 1)[1].split('</div></div>', 1)[0]
    assert "codex · weekly · pro" in visible_text(header)
    assert "secondary · weekly · plus" in visible_text(header)


def test_balance_scale_qualifications_remain_visible():
    document = plot(**inputs("balance"))
    assert '<strong>Credit Balance</strong>' in document
    assert "observed range, not zero-based" in document.split('</svg>', 1)[1]


def test_preview_builder_uses_single_issued_control_actions(tmp_path):
    repo = Path(__file__).resolve().parents[1]
    fixture = run_path(str(repo / "scripts/usage_breakdown_fixture.py"))
    preview = run_path(str(repo / "scripts/preview_breakdown_layouts.py"))
    ledger = fixture["breakdown_home"](tmp_path / "frozen")
    candidates, revision = preview["chart_inputs"](ledger, "7d", fixture["AT"], "UTC")
    assert len(candidates) == 6 and revision > 0
    for (grain, metric), (_, kwargs) in candidates.items():
        assert kwargs["metric"] == metric and kwargs["daily"] == (grain == "daily")
        assert kwargs["links"] is None

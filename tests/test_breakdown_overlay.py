"""Dense account captures stay distinct from additive usage stacks."""
from datetime import UTC, datetime, timedelta
from xml.etree import ElementTree

from codex_usage.report_breakdown_overlay import overlay
from codex_usage.report_usage_breakdown_chart import COLORS


AT = datetime(2026, 10, 4, tzinfo=UTC)


def reading(index, **changes):
    return {
        "timestamp": (AT + timedelta(minutes=index)).isoformat(),
        "limit_id": "codex", "slot": "primary", "plan": "pro",
        "duration_minutes": 10080, "used_percent": index / 200,
        "resets_at": int((AT + timedelta(days=7)).timestamp()),
        "reset_credits": None, "provenance": "synthetic", **changes,
    }


def render(points, *, inspection=False):
    return overlay(points, "weekly", AT.timestamp(), (AT + timedelta(days=14)).timestamp(),
        UTC, COLORS, inspection=inspection)


def test_boundary_density_changes_no_account_observations():
    points = [reading(i, _boundary=True) for i in range(12240)]
    marks, axis, name, evidence = render(points)
    nodes = ElementTree.fromstring("<g>" + marks + "</g>")
    assert len(nodes) == len(points)
    assert all(n.tag == "circle" and n.attrib["fill"] == "var(--text)" for n in nodes)
    assert all(n.attrib["data-boundary"] == "true" for n in nodes)
    assert [n.attrib["data-at"] for n in nodes] == [
        f'{datetime.fromisoformat(p["timestamp"]).timestamp():.6f}' for p in points]
    assert sum(n.attrib["data-latest"] == "true" for n in nodes) == 1
    assert all(float(n.attrib["r"]) < 1 for n in list(nodes)[:-1])
    assert float(nodes[-1].attrib["r"]) == 2
    assert "right axis" in name and "100%" in axis
    assert "12,240 captured boundary points" in evidence
    assert evidence.index('class="ub-overlay-evidence"') < evidence.index("Dense boundary evidence")


def test_separate_capture_stretches_are_never_joined():
    points = [reading(0, used_percent=30), reading(10, used_percent=60),
        reading(100, used_percent=0, resets_at=99999999), reading(110, used_percent=10)]
    marks, _, _, evidence = render(points)
    nodes = ElementTree.fromstring("<g>" + marks + "</g>")
    assert len(nodes) == 4
    assert all(n.tag == "circle" for n in nodes)
    assert "95%" not in evidence
    assert "90% remaining" in evidence
    assert "no joining or interpolation" in evidence


def test_account_series_labels_bind_latest_capture_and_identity():
    points = [reading(0), reading(1, used_percent=70),
        reading(2, limit_id="additional", plan="plus", used_percent=25)]
    marks, _, _, evidence = render(list(reversed(points)))
    nodes = ElementTree.fromstring("<g>" + marks + "</g>")
    assert sum(n.attrib["data-latest"] == "true" for n in nodes) == 2
    assert "codex · weekly · pro · 30% remaining" in evidence
    assert "additional · weekly · plus · 75% remaining" in evidence
    for n in nodes:
        assert n.attrib["aria-label"].startswith("Weekly allowance · right axis")
        assert n.attrib["aria-label"] == n.find("title").text
    # The ordinary single account overlay is always neutral, not a model color.
    assert nodes[-1].attrib["fill"] != nodes[0].attrib["fill"]


def test_conflicting_readings_are_inspectable_but_not_plotted():
    points = [reading(0), reading(1, used_percent=40), reading(1, used_percent=50)]
    marks, _, _, evidence = render(points)
    nodes = ElementTree.fromstring("<g>" + marks + "</g>")
    assert len(nodes) == 1
    assert "Conflicting account readings" in evidence
    _, _, _, exact = render(points, inspection=True)
    assert "40% used" in exact and "50% used" in exact


def test_unsafe_series_labels_are_escaped():
    marks, _, _, evidence = render([reading(0, plan='<script>"')])
    assert "<script>" not in evidence + marks
    assert "&lt;script&gt;" in evidence + marks


def test_simultaneous_balance_conflict_never_picks_a_latest_value():
    points = [{"timestamp": AT.isoformat(), "balance": str(value), "plan": "pro",
        "unlimited": False, "diagnostic": "", "change": None} for value in (4000, 5000)]
    marks, _, _, evidence = overlay(points, "balance", AT.timestamp(), AT.timestamp()+3600, UTC, COLORS)
    assert 'data-latest="true"' in marks
    assert "Credit balance · conflicting latest captures" in evidence
    assert "4 K credits" not in evidence and "5 K credits" not in evidence

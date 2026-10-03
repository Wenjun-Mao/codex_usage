"""Credit balance adds no standing paragraph or expensive warm-view work."""
from copy import deepcopy
from datetime import timedelta
from zoneinfo import ZoneInfo

import pytest

from codex_usage.agent_capture import capture_once
from codex_usage.agent_reports import render_ledger_report
from codex_usage.report_allowance import render_allowance_section
from codex_usage.report_allowance_credits import credit_amount
from test_allowance_capture_report import _report
from test_allowance_credits import BASE, _read


def _report_with_credits(balance="61964.8392100000", *, freshness="fresh", unlimited=False):
    report = _report([])
    report["status"]["credits"] = {
        "balance": balance, "unlimited": unlimited, "has_credits": True,
        "freshness": freshness, "observed_at": BASE.isoformat(),
    }
    report["credits"] = {"count": 1, "observations": [{
        "timestamp": BASE.isoformat(), "balance": balance, "unlimited": unlimited,
        "diagnostic": "", "change": None,
    }]}
    return report


def test_balance_shares_heading_and_cautions_are_folded_without_more_paragraphs():
    report = _report_with_credits()
    plain = deepcopy(report)
    plain["status"].pop("credits")
    plain.pop("credits")
    markup = render_allowance_section(report, timezone=ZoneInfo("America/Toronto"))
    prefix = markup.split('<details><summary>Probe, coverage, and allowance history')[0]
    without = render_allowance_section(plain).split('<details><summary>Probe, coverage, and allowance history')[0]
    heading = prefix.split('<div class="allowance-heading">')[1].split("</div>")[0]
    assert "Plan Allowance</h2>" in heading and "61,964.84 credits" in heading
    assert prefix.count("<p") == without.count("<p")
    assert "again" not in markup and "Included allowance available" not in markup
    assert "Workload-specific" not in prefix and "VS Code capture stops" not in prefix
    assert "Workload-specific" in markup and "VS Code capture stops" in markup
    assert 'title="Current balance · 2026-10-02 08:00 EDT · Exact balance: 61964.8392100000"' in markup
    assert markup.index("Credit balance captures") > markup.index("Reset windows and capture details")
    assert "<script" not in markup and "<details open" not in markup


@pytest.mark.parametrize("balance,expected", [("0", "0.00"), ("62500", "62,500.00"),
                                            ("0.004", "<0.01"), ("-0.004", "<0.01")])
def test_credit_display_is_compact_without_hiding_tiny_balances(balance, expected):
    assert credit_amount(balance) == expected


def test_high_precision_balance_does_not_double_round_before_display():
    assert credit_amount("999999999999999999.994999999999999999") == "999,999,999,999,999,999.99"


def test_unlimited_and_stale_balances_are_explicit_and_unknown_is_not_zero():
    unlimited = render_allowance_section(_report_with_credits("0", unlimited=True))
    assert "Unlimited credits" in unlimited and "0.00 credits" not in unlimited
    stale = render_allowance_section(_report_with_credits(freshness="stale"))
    assert "61,964.84 credits · last known" in stale and 'title="Last known balance' in stale
    report = _report_with_credits()
    report["status"]["credits"] = None
    report["credits"]["observations"][0].update(balance=None, diagnostic="credits_unavailable")
    unknown = render_allowance_section(report)
    assert 'class="allowance-credit-balance"' not in unknown
    assert "Credit balance unavailable" in unknown and "0.00 credits" not in unknown
    tiny = render_allowance_section(_report_with_credits("0.004"))
    assert "&lt;0.01 credits" in tiny


def test_balances_and_net_changes_are_never_labeled_actual_token_bills():
    report = _report_with_credits()
    row = report["credits"]["observations"][0]
    report["credits"]["observations"] = [dict(row, change="-35.16079"), dict(row, change="500"),
                                          dict(row, change="0")]
    report["credits"]["count"] = 500
    markup = render_allowance_section(report)
    assert "Newest 3 of 500 captures" in markup
    assert "Decrease: 35.16" in markup and "Increase: 500.00" in markup and "No change" in markup
    assert "account-wide" in markup.lower() and "may include adjustments" in markup
    assert "token-based estimated credits" in markup
    assert 'title="Exact change: -35.16079"' in markup
    assert "spent since baseline" not in markup.lower()


def test_warm_views_do_not_reload_balance_history_or_reprice_and_stale_html_invalidates(tmp_path, monkeypatch):
    import codex_usage.allowance_credits as credits_module
    import codex_usage.allowance_index as index_module

    home = tmp_path / "codex"
    (home / "sessions").mkdir(parents=True)
    monkeypatch.setattr("codex_usage.allowance_capture.probe_allowance", lambda _: _read(0))
    capture_once(home, request_kind="manual", max_workers=1)

    def render(now):
        return render_ledger_report(home, range_name="all", project_keys=[], theme="day",
                                    timezone_name="America/Toronto", now=now)

    first = render(BASE + timedelta(minutes=10))
    assert not first.cache_hit and "62,500.00 credits" in first.html

    def forbidden(*args, **kwargs):
        raise AssertionError("warm report loaded history, repriced, or probed")

    with monkeypatch.context() as patch:
        patch.setattr(credits_module, "credit_history", forbidden)
        patch.setattr("codex_usage.allowance_queries.credit_history", forbidden)
        patch.setattr(index_module, "_decode_cached_report", forbidden)
        patch.setattr(index_module, "estimate_cost", forbidden)
        patch.setattr("codex_usage.allowance_capture.probe_allowance", forbidden)
        warm = render(BASE + timedelta(minutes=20))
        assert warm.cache_hit and warm.html == first.html
    stale = render(BASE + timedelta(hours=2))
    assert not stale.cache_hit and "62,500.00 credits · last known" in stale.html
    assert render(BASE + timedelta(hours=2, minutes=10)).cache_hit

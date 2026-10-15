"""Private history traversal, issued scope validation and bounded warm work."""
from contextlib import ExitStack
from copy import deepcopy
from datetime import UTC, datetime, timedelta
import json
from unittest.mock import patch

import pytest

from release_tooling_support import load_tool
from codex_usage.agent_reports import PRICING_REVISION, render_ledger_report
from codex_usage.allowance_history_navigation import (
    AllowanceScopeExpired, DEFAULT_STATE, navigation, validate_state,
)
from codex_usage.allowance_index import _revisions
from codex_usage.allowance_models import QuotaObservation
from codex_usage.allowance_probe import QuotaRead
from codex_usage.allowance_report_codec import encode_report
from codex_usage.allowance_store import store_read
from codex_usage.ledger_schema import increment_ledger_revision, ledger_revision, open_ledger

fixtures = load_tool("allowance_period_fixture")
AT = datetime(2026, 11, 1, 9, 30, tzinfo=UTC)


def seeded(home, *, dense=False):
    from codex_usage.agent_paths import ledger_database_path
    home.mkdir(exist_ok=True)
    report = (fixtures.dense_period_fixture if dense else fixtures.allowance_period_fixture)(home)
    # Exercise many independent fits and >1 capture page under one owner.
    if not dense:
        base = deepcopy(report["windows"][0])
        report["windows"] = [deepcopy(base) for _ in range(29)]
        report["qualified"] = []
        report["history"] = []
        report["headline"] = report["windows"][0]
        for fragment in report["display_history"]["periods"] + report["display_history"]["uncertain"]:
            fragment["fit_indices"] = []
        report["display_history"]["cross_boundary_fit_indices"] = list(range(29))
    path = ledger_database_path(home)
    point = QuotaObservation(AT.isoformat(), "codex", "primary", "pro", 5, 300, int(AT.timestamp())+3600, 1)
    with open_ledger(path) as connection:
        store_read(connection, QuotaRead(AT.isoformat(), "pro", (point,)), None)
        increment_ledger_revision(connection)
        connection.commit()
        revision = ledger_revision(connection)
        _, key = _revisions(PRICING_REVISION)
        connection.execute("insert into allowance_report_cache values (?,?,?,?)", (revision, key, 1, encode_report(report)))
        connection.execute("insert into allowance_report_cache values (?,?,?,?)", (revision, key+":pace-state", 1, '{"paces":[]}'))
        connection.commit()
    return path, report


def render(home, action=None, **kwargs):
    return render_ledger_report(home, range_name=kwargs.pop("range_name", "all"), project_keys=kwargs.pop("keys", []),
        theme=kwargs.pop("theme", "day"), timezone_name=kwargs.pop("timezone", "UTC"), now=AT,
        allowance_action=json.dumps(action) if action is not None else None, **kwargs)


def action(report, **fields):
    nav = report.allowance_navigation
    return next(a for a in nav["actions"] if a["state"] == dict(nav["state"], **fields))


def test_all_periods_and_uncertain_fragments_remain_reachable_with_bounded_html(tmp_path):
    _, source = seeded(tmp_path, dense=True)
    current = render(tmp_path)
    for kind, field in (("periods", "period_page"), ("uncertain", "uncertain_page")):
        seen = set()
        current = render(tmp_path)
        count = len(source["display_history"][kind])
        for page in range((count+11)//12):
            nav = current.allowance_navigation
            seen.update(a["state"]["index"] for a in nav["actions"] if a["state"]["kind"] == kind)
            assert current.html.count('class="allowance-history-item"') <= 24
            assert 'class="allowance-observations"' not in current.html
            if (page+1)*12 < count:
                current = render(tmp_path, action(current, **{field: page+1}))
        assert seen == set(range(count))
        selected = next(a for a in current.allowance_navigation["actions"] if a["state"]["kind"] == kind)
        detail = render(tmp_path, selected)
        assert detail.html.count('class="allowance-observations"') == 1
        assert '<details open><summary>Probe, coverage, and allowance history' in detail.html


def test_fit_and_capture_pagination_default_newest_and_optional_oldest(tmp_path):
    _, source = seeded(tmp_path)
    first = render(tmp_path)
    cross = render(tmp_path, action(first, kind="cross"))
    seen = set()
    for page in range(3):
        shown = source["display_history"]["cross_boundary_fit_indices"][::-1][page*12:(page+1)*12]
        for index in shown:
            assert f"Fit {index+1} ·" in cross.html
            seen.add(index)
        assert cross.html.count('class="allowance-fit"') == len(shown)
        if page < 2:
            cross = render(tmp_path, action(cross, fit_page=page+1))
    assert seen == set(range(29))
    selected = render(tmp_path, action(first, kind="periods", index=1))
    assert selected.html.count("<tr><td") == 100
    newest = render(tmp_path, action(selected, capture_page=1))
    assert newest.html.count("<tr><td") == 25
    oldest = render(tmp_path, action(selected, capture_order="oldest"))
    assert "Oldest first" in oldest.html and "Later captures" in oldest.html
    assert oldest.html.count("<tr><td") == 100
    assert oldest.html.index('title="UTC: 2026-11-01T03:30:00+00:00"') < oldest.html.index('title="UTC: 2026-11-01T03:31:00+00:00"')


def test_new_page_uses_cached_evidence_only_and_revisited_page_never_decodes_history(tmp_path):
    _, _ = seeded(tmp_path)
    first = render(tmp_path)
    selected = action(first, kind="periods", index=1)

    def forbidden(*_args, **_kwargs):
        raise AssertionError("History navigation performed historical work")

    with ExitStack() as stack:
        for target in (
            "codex_usage.agent_reports.materialize_ledger", "codex_usage.breakdown_reports.prepare",
            "codex_usage.breakdown_reports.prepare_evidence", "codex_usage.allowance_queries.load_quota_evidence",
            "codex_usage.allowance_queries._build_from_costs", "codex_usage.allowance_index._build_from_costs",
            "codex_usage.allowance_index._price_missing_events", "codex_usage.allowance_pace.fit_paces",
            "codex_usage.allowance_display_history.display_history", "codex_usage.allowance_capture.probe_allowance",
            "codex_usage.ledger_queries.query_ledger_records",
        ):
            stack.enter_context(patch(target, forbidden))
        inspected = render(tmp_path, selected)
        older_action = action(inspected, capture_page=1)
        older = render(tmp_path, older_action)
        with patch("codex_usage.allowance_history_reports._decode_cached_report", forbidden):
            assert render(tmp_path, selected).html == inspected.html
            hit = render(tmp_path, older_action)
            assert hit.html == older.html and hit.cache_hit
            assert render(tmp_path).cache_hit


@pytest.mark.parametrize("fields", [{"period_page": True}, {"uncertain_page": -1}, {"capture_page": "1"},
    {"index": False}, {"index": 2**32}, {"extra": 1}, {"capture_order": "random"}, {"kind": "foreign"}])
def test_invalid_state_fields_are_rejected(fields):
    with pytest.raises(ValueError):
        validate_state(dict(DEFAULT_STATE, **fields))


@pytest.mark.parametrize("fields", [{"period_page": 99}, {"uncertain_page": 99}, {"capture_page": 1},
    {"kind": "periods", "index": 99}, {"fit_page": 1}])
def test_out_of_range_state_cannot_be_issued(tmp_path, fields):
    report = fixtures.dense_period_fixture(tmp_path)
    with pytest.raises(ValueError):
        navigation(report, "synthetic", dict(DEFAULT_STATE, **fields))


@pytest.mark.parametrize("damage", ["extra", "bool", "out-of-range", "wrong-scope", "wrong-series"])
def test_crafted_actions_are_never_retried_as_expired(tmp_path, damage):
    seeded(tmp_path)
    first = render(tmp_path)
    bad = deepcopy(action(first, kind="periods", index=1))
    if damage == "extra":
        bad["extra"] = True
    elif damage == "wrong-scope":
        bad["scope"] = "f"*64
    elif damage == "wrong-series":
        bad["state"]["series"] = "other"
    else:
        bad["state"]["index"] = True if damage == "bool" else 999
    with pytest.raises(ValueError) as error:
        render(tmp_path, bad)
    assert not isinstance(error.value, AllowanceScopeExpired)


@pytest.mark.parametrize("change", ["timezone", "filter", "theme", "revision", "series"])
def test_real_issued_actions_expire_under_changed_report_or_account_scope(tmp_path, change):
    path, _ = seeded(tmp_path)
    first = render(tmp_path)
    issued = action(first, kind="periods", index=1)
    kwargs = {}
    if change == "timezone":
        kwargs["timezone"] = "America/Toronto"
    elif change == "filter":
        kwargs["keys"] = ["other"]
    elif change == "theme":
        kwargs["theme"] = "night"
    else:
        with open_ledger(path) as writer:
            if change == "revision":
                increment_ledger_revision(writer)
            else:
                writer.execute("update quota_reads set plan='team'")
                writer.execute("update quota_observations set plan='team'")
            writer.commit()
    with pytest.raises(AllowanceScopeExpired):
        render(tmp_path, issued, **kwargs)
    assert render(tmp_path).allowance_navigation


def test_expired_receipt_is_unissued_and_retention_is_bounded(tmp_path):
    path, _ = seeded(tmp_path)
    first = render(tmp_path)
    issued = action(first, kind="periods", index=1)
    with open_ledger(path) as writer:
        writer.execute("update rendered_reports set created_at=? where cache_key like 'allowance-issued:%'",
                       ((datetime.now(UTC)-timedelta(days=2)).isoformat(),))
        writer.commit()
    with pytest.raises(ValueError, match="Unissued"):
        render(tmp_path, issued)
    render(tmp_path)
    with open_ledger(path, read_only=True) as connection:
        assert connection.execute("select count(*) from rendered_reports where cache_key like 'allowance-issued:%'").fetchone()[0] == 1


def test_tokens_do_not_cross_ledger_homes_or_html_revision(tmp_path, monkeypatch):
    import codex_usage.agent_reports as reports
    first_home, other_home = tmp_path / "one", tmp_path / "two"
    seeded(first_home)
    seeded(other_home)
    first, other = render(first_home), render(other_home)
    assert first.allowance_navigation["scope"] != other.allowance_navigation["scope"]
    issued = action(first, kind="periods", index=1)
    with pytest.raises(ValueError, match="Unissued"):
        render(other_home, issued)
    monkeypatch.setattr(reports, "REPORT_RENDER_REVISION", reports.REPORT_RENDER_REVISION+1)
    with pytest.raises(AllowanceScopeExpired):
        render(first_home, issued)


def test_receipt_retention_does_not_prune_foreign_domains(tmp_path):
    from codex_usage.breakdown_commands import prune_receipts, RECEIPT_MAX_SCOPES
    path, _ = seeded(tmp_path)
    with open_ledger(path) as writer:
        stamp = datetime.now(UTC).isoformat()
        writer.executemany("insert into rendered_reports values (?,?,?,?,?)",
            [(f"allowance-issued:{index:064x}", 1, "synthetic", stamp, "{}") for index in range(300)])
        writer.execute("insert into rendered_reports values (?,?,?,?,?)",
                       ("breakdown-issued:retained", 1, "synthetic", stamp, "{}"))
        prune_receipts(writer, prefix="allowance-issued:")
        assert writer.execute("select count(*) from rendered_reports where cache_key like 'allowance-issued:%'").fetchone()[0] == RECEIPT_MAX_SCOPES
        assert writer.execute("select 1 from rendered_reports where cache_key='breakdown-issued:retained'").fetchone()


def test_missing_derived_history_fails_closed_instead_of_hiding_old_periods(tmp_path):
    path, _ = seeded(tmp_path)
    first = render(tmp_path)
    issued = action(first, kind="periods", index=1)
    with open_ledger(path) as writer:
        writer.execute("delete from allowance_report_cache where pricing_revision not like '%:pace-state'")
        writer.commit()
    with pytest.raises(ValueError, match="Cached allowance history unavailable"):
        render(tmp_path, issued)

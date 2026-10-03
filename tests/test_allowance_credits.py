"""Credit balances are observed metadata, never reconstructed token charges."""
import json
import sqlite3
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from codex_usage.allowance_credits import (
    CreditBalance, credit_balance, credit_history, credit_status, decimal_balance,
)
from codex_usage.allowance_estimation import estimate_window
from codex_usage.allowance_models import QuotaObservation
from codex_usage.allowance_probe import QuotaRead
from codex_usage.allowance_queries import _build_from_costs, build_allowance_report
from codex_usage.allowance_store import store_read
from codex_usage.allowance_windows import AllowanceWindow
from codex_usage.ledger_schema import LEDGER_SCHEMA_VERSION, open_ledger


BASE = datetime(2026, 10, 2, 12, tzinfo=UTC)


def _read(index, used=40, balance="62500", *, plan="pro", unlimited=False):
    stamp = (BASE + timedelta(minutes=15 * index)).isoformat()
    point = QuotaObservation(stamp, "codex", "primary", plan, used, 10080, 2_000_000_000, 2)
    credits = CreditBalance(balance, True, unlimited) if balance is not None else None
    return QuotaRead(stamp, plan, (point,), credits=credits)


@pytest.mark.parametrize("invalid", [None, True, False, 1.5, "NaN", "Infinity", "-1", "", "secret",
                                     "1e-999999", "1e999999", "0e999999", "1" * 65, "1e19"])
def test_malformed_balance_is_not_zero_or_retained(invalid):
    assert decimal_balance(invalid) is None
    parsed = credit_balance({"credits": {"balance": invalid}})
    assert parsed.balance is None
    assert "secret" not in repr(parsed)


def test_oversized_integer_balance_is_bounded_before_string_conversion():
    assert decimal_balance(10 ** 5000) is None


@pytest.mark.parametrize("value", ["61964.8392100000", "0", 0, "0.000000000000000001", "1e18"])
def test_balances_preserve_exact_decimal_value(value):
    assert Decimal(decimal_balance(value)) == Decimal(str(value))


def test_duplicate_balances_and_banked_resets_are_not_summed():
    credits = {"balance": "61964.8392100000", "hasCredits": True, "unlimited": False,
               "secret": "PRIVATE"}
    payload = {"accountId": "PRIVATE", "rateLimits": {"credits": credits},
               "rateLimitsByLimitId": {"codex": {"credits": credits},
                                       "other": {"credits": dict(credits, balance="61964.83921")}},
               "rateLimitResetCredits": {"availableCount": 2, "credits": [{"id": "PRIVATE"}]}}
    reading = credit_balance(payload)
    assert reading == CreditBalance("61964.8392100000", True, False)
    assert "PRIVATE" not in repr(reading)
    assert credit_balance({"rateLimitResetCredits": payload["rateLimitResetCredits"]}) is None


def test_conflicting_bucket_balances_are_unavailable_not_arbitrarily_chosen():
    parsed = credit_balance({"rateLimits": {"credits": {"balance": "100"}},
                            "rateLimitsByLimitId": {"other": {"credits": {"balance": "200"}}}})
    assert parsed.balance is None and parsed.diagnostic == "conflicting_credit_balances"
    assert credit_balance({"rateLimitsByLimitId": dict.fromkeys(range(65), {})}).diagnostic


@pytest.mark.parametrize("metadata", [{"hasCredits": "false"}, {"unlimited": "false"}, []])
def test_malformed_boolean_metadata_is_explicit(metadata):
    assert credit_balance({"credits": metadata}).diagnostic == "invalid_credit_metadata"


def test_capture_preserves_balance_across_exhaustion_and_reset(tmp_path):
    with open_ledger(tmp_path / "ledger") as connection:
        for index, (used, balance) in enumerate(((40, "62500"), (99, "62500"),
                                               (100, "62000"), (100, "61964.8392100000"),
                                               (3, "61964.8392100000"))):
            store_read(connection, _read(index, used, balance), None)
        assert connection.execute("select count(*) from credit_observations").fetchone()[0] == 5
        assert {r[0] for r in connection.execute("select reset_credits from quota_observations")} == {2}
        history = credit_history(connection)
        assert [p["change"] for p in history["observations"]] == [
            "0.0000000000", "-35.1607900000", "-500", "0", None,
        ]
        report = build_allowance_report(connection)
        assert len(report["windows"]) == 2
        assert report["windows"][0]["closure"] == "early/unknown"
        assert report["status"]["active_buckets"][0]["used_percent"] == 3
        assert report["status"]["credits"]["balance"] == "61964.8392100000"


def test_missing_capture_does_not_replace_balance_with_zero_or_bridge_a_change(tmp_path):
    with open_ledger(tmp_path / "ledger") as connection:
        store_read(connection, _read(0), None)
        store_read(connection, _read(1, balance=None), None)
        current = credit_status(connection, latest_read_id=2, now=BASE + timedelta(minutes=20))
        assert current["freshness"] == "stale" and current["balance"] == "62500"
        store_read(connection, _read(2, balance="62000"), None)
        history = credit_history(connection)
        assert history["observations"][0]["change"] is None
        assert history["observations"][1]["balance"] is None


def test_status_lookup_does_not_scan_a_long_missing_balance_history(tmp_path):
    with open_ledger(tmp_path / "ledger") as connection:
        def lookup(read_id):
            steps = []
            connection.set_progress_handler(lambda: steps.append(1) or 0, 1)
            status = credit_status(connection, latest_read_id=read_id, now=BASE + timedelta(days=11))
            connection.set_progress_handler(None, 0)
            return status, len(steps)

        store_read(connection, _read(0), None)
        _, baseline_steps = lookup(1)
        for index in range(1, 1001):
            store_read(connection, _read(index, balance=None), None)
        status, long_history_steps = lookup(1001)
        assert status["balance"] == "62500" and status["freshness"] == "stale"
        assert long_history_steps <= baseline_steps + 50


def test_balance_increase_is_adjustment_and_plan_change_is_not_a_spend_interval(tmp_path):
    with open_ledger(tmp_path / "ledger") as connection:
        for read in (_read(0, balance="0"), _read(1, balance="500"), _read(2, balance="100", plan="plus")):
            store_read(connection, read, None)
        assert [p["change"] for p in credit_history(connection)["observations"]] == [None, "500", None]


def test_unlimited_and_malformed_reads_are_not_numerical_depletion(tmp_path):
    with open_ledger(tmp_path / "ledger") as connection:
        store_read(connection, _read(0, balance="0", unlimited=True), None)
        store_read(connection, _read(1), None)
        bad = replace(_read(2), credits=CreditBalance(diagnostic="invalid_credit_balance"))
        store_read(connection, bad, None)
        assert all(row["change"] is None for row in credit_history(connection)["observations"])
        assert credit_status(connection, latest_read_id=3, now=BASE + timedelta(minutes=35))["freshness"] == "stale"


def test_history_is_bounded_and_decimal_subtraction_is_exact(tmp_path):
    with open_ledger(tmp_path / "ledger") as connection:
        for index in range(105):
            store_read(connection, _read(index, balance="1000000000000000000"), None)
        store_read(connection, _read(106, balance="999999999999999999.999999999999999999"), None)
        history = credit_history(connection)
        assert history["count"] == 106 and len(history["observations"]) == 100
        assert history["observations"][0]["change"] == "-0.000000000000000001"


def test_schema_4_backup_and_migration_preserve_quota_and_render_cache(tmp_path):
    ledger = tmp_path / "ledger"
    with open_ledger(ledger) as connection:
        store_read(connection, _read(0), None)
        quota = [tuple(row) for row in connection.execute("select * from quota_observations")]
        connection.execute("drop table credit_observations")
        connection.execute("update ledger_meta set value='4' where key='schema_version'")
        connection.execute("insert into rendered_reports values ('old',0,'old','old','old')")
        connection.commit()
    with open_ledger(ledger, read_only=True) as connection:
        assert credit_status(connection) is None
        assert credit_history(connection) == {"count": 0, "observations": []}
        assert build_allowance_report(connection)["status"]["credits"] is None
    with open_ledger(ledger) as connection:
        assert connection.execute("select value from ledger_meta where key='schema_version'").fetchone()[0] == str(LEDGER_SCHEMA_VERSION)
        assert [tuple(row) for row in connection.execute("select * from quota_observations")] == quota
        assert connection.execute("select html from rendered_reports where cache_key='old'").fetchone()[0] == "old"
        assert connection.execute("select count(*) from credit_observations").fetchone()[0] == 0
        connection.commit()
    backups = list(tmp_path.glob("ledger.schema-4-backup-*"))
    assert len(backups) == 1
    with sqlite3.connect(backups[0]) as connection:
        assert connection.execute("select value from ledger_meta where key='schema_version'").fetchone()[0] == "4"


def test_credit_only_probe_uses_existing_rpc_and_retains_no_identity(tmp_path, monkeypatch):
    import codex_usage.allowance_probe as module
    calls = []

    class Rpc:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def call(self, method, params):
            calls.append(method)
            return {"account/read": {"account": {"planType": "pro", "email": "PRIVATE"}},
                    "account/rateLimits/read": {"accountId": "PRIVATE", "rateLimits": {
                        "credits": {"balance": "61964.8392100000", "hasCredits": True, "unlimited": False}}},
                    "account/usage/read": {}}[method]

    monkeypatch.setattr(module, "AppServerRpc", Rpc)
    monkeypatch.setattr(module, "discover_codex_executables", lambda: ("codex",))
    read = module.probe_allowance(tmp_path)
    assert read.credits == CreditBalance("61964.8392100000", True, False)
    assert read.observations == () and "quota_unavailable" in read.diagnostics
    assert "PRIVATE" not in repr(read)
    assert calls == ["account/read", "account/rateLimits/read", "account/usage/read"]


def test_allowance_fit_freezes_before_saturation_even_after_small_corrections():
    points = [_read(i, used).observations[0] for i, used in enumerate((0, 25, 50, 75, 99, 100, 100, 99, 100))]
    costs = [0, 375, 750, 1125, 1485, 1600, 1800, 2000, 2200]
    estimate = estimate_window(AllowanceWindow(points), costs, fully_priced=True)
    assert estimate.value == pytest.approx(1500)
    assert estimate.span == 99 and estimate.bins == 5 and estimate.cost_span == 1485
    assert len(points) == 9


def test_unpriced_full_meter_tail_does_not_invalidate_previous_fit_or_pollute_new_cycle(tmp_path):
    uses = (0, 25, 50, 75, 99, 100, 100, 99, 3, 23, 43, 63, 83)
    points = [_read(i, used).observations[0] for i, used in enumerate(uses)]
    prices = [0, 375, 375, 375, 360, 500, 500, 500, 0, 200, 200, 200, 200]
    with open_ledger(tmp_path / "ledger") as connection:
        for index, point in enumerate(points):
            store_read(connection, replace(_read(index), observations=(point,)), None)
        report = _build_from_costs(connection, [
            (datetime.fromisoformat(point.timestamp).timestamp(), price, 100 if index in (5, 6, 7) else 0)
            for index, (point, price) in enumerate(zip(points, prices, strict=True))
        ])
    old, new = report["windows"]
    assert old["estimate"]["value"] == pytest.approx(1500)
    assert old["fully_priced"] and old["excluded_observations"] == 3
    assert old["fit_end"] == points[4].timestamp and len(old["points"]) == 8
    assert new["estimate"]["value"] == pytest.approx(1000)
    assert new["excluded_observations"] == 0
    json.dumps(report)


def test_already_exhausted_window_has_no_fit_and_fractional_near_full_remains_usable():
    full = [_read(i, 100).observations[0] for i in range(5)]
    assert estimate_window(AllowanceWindow(full), [0, 1, 2, 3, 4], fully_priced=True).value is None
    points = [_read(i, used).observations[0] for i, used in enumerate((80, 85, 90, 95, 99.9))]
    assert estimate_window(AllowanceWindow(points), [0, 50, 100, 150, 200], fully_priced=True).value == pytest.approx(1000)


@pytest.mark.parametrize("full_first", [False, True])
def test_conflicting_same_timestamp_full_reading_is_preserved_for_calibration(tmp_path, full_first):
    from codex_usage.allowance_windows import segment_windows

    readings = [_read(i, used) for i, used in enumerate((0, 25, 50, 75, 99))]
    full = replace(readings[-1], observations=(replace(readings[-1].observations[0], used_percent=100),))
    conflict = [full, readings[-1]] if full_first else [readings[-1], full]
    later = [_read(i, 99) for i in (5, 6)]
    source = readings[:-1] + conflict + later
    window = segment_windows([r.observations[0] for r in source])[0]
    assert window.ambiguous and len(window.points) == 7
    assert window.reported_full_at == full.timestamp
    estimate = estimate_window(window, [0, 375, 750, 1125, 1485, 2500, 3500], fully_priced=True)
    assert estimate.value is None and estimate.bins == 4
    with open_ledger(tmp_path / "ledger") as connection:
        for read in source:
            store_read(connection, read, None)
        assert connection.execute("select count(*) from quota_observations where used_percent=100").fetchone()[0] == 1
        report = _build_from_costs(connection, [(datetime.fromisoformat(r.timestamp).timestamp(), cost, 0)
                                              for r, cost in zip(readings + later,
                                                                 (0, 375, 375, 375, 360, 1015, 1000), strict=True)])
    assert report["windows"][0]["reported_full_at"] == full.timestamp
    assert report["windows"][0]["estimate"]["value"] is None
    assert report["windows"][0]["excluded_observations"] == 3

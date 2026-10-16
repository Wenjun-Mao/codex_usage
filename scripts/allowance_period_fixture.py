"""Synthetic raw-evidence histories shared by R unit and visual qualification."""
from dataclasses import replace
from datetime import UTC, datetime, timedelta

from codex_usage.allowance_display_history import display_history
from codex_usage.allowance_models import QuotaObservation
from codex_usage.allowance_preparation import AllowancePreparation
from codex_usage.allowance_queries import _build_from_costs, allowance_status
from codex_usage.allowance_store import store_observations
from codex_usage.ledger_schema import open_ledger


def allowance_period_fixture(directory):
    at = datetime(2026, 11, 1, 3, 30, tzinfo=UTC)
    reset = int((at + timedelta(hours=8)).timestamp())
    points = [QuotaObservation((at + timedelta(minutes=i)).isoformat(), "codex", "primary", "pro",
                               10 + i / 4, 300, reset, 2) for i in range(125)]
    # The estimator does not cut on a clock rebase without a meter drop.
    points += [replace(points[-1], timestamp=(at + timedelta(hours=3)).isoformat(), used_percent=45,
                       resets_at=reset + 120)]
    points += [replace(points[-1], timestamp=(at + timedelta(hours=4)).isoformat(), used_percent=50),
               replace(points[-1], timestamp=(at + timedelta(hours=4)).isoformat(), used_percent=55)]
    points += [replace(points[-1], timestamp=(at + timedelta(hours=5)).isoformat(), used_percent=60),
               replace(points[-1], timestamp=(at + timedelta(hours=6)).isoformat(), used_percent=5, reset_credits=1)]
    with open_ledger(directory / "synthetic.sqlite3") as connection:
        store_observations(connection, points, source_key="synthetic", provenance="live")
        status = allowance_status(connection)
        status.update(active_buckets=[points[-1].to_dict()], plan="pro", probe_status="fresh",
                      last_probe_at=points[-1].timestamp, last_observed_at=points[-1].timestamp)
        preparation = AllowancePreparation(connection)
        costs = [(datetime.fromisoformat(p.timestamp).timestamp(), 1.0, 0) for p in points]
        report = _build_from_costs(connection, costs, status=status, preparation=preparation)
        # Retain the legacy capture-fragment fixture for compatibility/navigation
        # coverage; reset_economics_fixture exercises the new primary UI.
        report.pop("reset_history")
        return report


def dense_period_fixture(directory):
    report = allowance_period_fixture(directory)
    at = datetime(2026, 10, 14, tzinfo=UTC)
    periods = [QuotaObservation((at + timedelta(minutes=i)).isoformat(), "codex", "primary", "pro",
                               10, 300, None, 100-i) for i in range(40)]
    fragments = [replace(periods[0], timestamp=(at + timedelta(minutes=i)).isoformat(), limit_id="other",
                         used_percent=80 if i % 2 == 0 else 10, reset_credits=None) for i in range(80)]
    points = periods + fragments
    report.update(windows=[], history=[], headline=None, qualified=[], paces=[])
    report["display_history"] = display_history(points, {p: {"Task snapshot"} for p in points}, [], [])
    return report


def official_display_fixture(directory, variant):
    at = datetime(2026, 11, 1, 3, 30, tzinfo=UTC)
    def point(hours, used, **fields):
        return replace(QuotaObservation((at+timedelta(hours=hours)).isoformat(), "codex", "primary", "pro",
                                       used, 10080, int((at+timedelta(days=5)).timestamp()), 3), **fields)
    if variant == "official-conflicts":
        live = [point(0, 40), point(2, 50), point(4, 60)]
        tasks = [point(1, 1), point(2, 99, slot="secondary"),
                 point(3, 55, resets_at=live[0].resets_at+3600)]
    elif variant == "uncertain-current":
        live = [point(0, 80, resets_at=None), point(1, 10, resets_at=None), point(2, 15, resets_at=None)]
        tasks = []
    elif variant == "lone-current":
        live = [point(4, 60, resets_at=None)]
        tasks = [point(0, 10, resets_at=None)]
    else:
        raise ValueError("Unknown synthetic official history variant")
    with open_ledger(directory / "synthetic.sqlite3") as connection:
        store_observations(connection, live, source_key="official", provenance="live")
        store_observations(connection, tasks, source_key="tasks", provenance="parsed")
        status = allowance_status(connection)
        status.update(active_buckets=[live[-1].to_dict()], plan="pro", probe_status="fresh",
                      last_probe_at=live[-1].timestamp, last_observed_at=live[-1].timestamp)
        costs = [(datetime.fromisoformat(p.timestamp).timestamp(), 1.0, 0)
                 for p in sorted(live+tasks, key=lambda p: p.timestamp)]
        report = _build_from_costs(connection, costs, status=status, preparation=AllowancePreparation(connection))
        report.pop("reset_history")
        return report


def reset_economics_fixture(directory):
    at = datetime(2026, 11, 1, 3, 30, tzinfo=UTC)
    def point(hour, used, reset):
        return QuotaObservation((at+timedelta(hours=hour)).isoformat(), "codex", "primary", "pro",
                                used, 10080, int((at+timedelta(hours=reset)).timestamp()), 2)
    live = [point(0, 80, 5), point(.9, 90, 5)]
    live += [point(1+i*.4, i*10, 8) for i in range(6)]
    live += [point(4+i*.2, i*10, 10) for i in range(6)]
    tasks = [point(.95, 0, 8), point(3.95, 0, 10)]
    with open_ledger(directory / "synthetic.sqlite3") as connection:
        store_observations(connection, live, source_key="official", provenance="live")
        store_observations(connection, tasks, source_key="tasks", provenance="parsed")
        status = allowance_status(connection)
        status.update(active_buckets=[live[-1].to_dict()], plan="pro", probe_status="fresh",
                      last_probe_at=live[-1].timestamp, last_observed_at=live[-1].timestamp)
        costs = [(datetime.fromisoformat(p.timestamp).timestamp(), 5., 0) for p in live]
        return _build_from_costs(connection, costs, status=status, preparation=AllowancePreparation(connection))


def install_history_cache(home, report):
    """Seed synthetic derived evidence for real private-host navigation replay."""
    import json
    from codex_usage.agent_paths import ledger_database_path
    from codex_usage.agent_reports import PRICING_REVISION
    from codex_usage.allowance_index import _revisions
    from codex_usage.allowance_probe import QuotaRead
    from codex_usage.allowance_report_codec import encode_report
    from codex_usage.allowance_store import store_read
    from codex_usage.ledger_schema import increment_ledger_revision, ledger_revision

    bucket = report["status"]["active_buckets"][0]
    anchor = QuotaObservation(**{key: bucket[key] for key in QuotaObservation.__dataclass_fields__})
    with open_ledger(ledger_database_path(home)) as connection:
        store_read(connection, QuotaRead(anchor.timestamp, anchor.plan, (anchor,)), None)
        increment_ledger_revision(connection)
        revision = ledger_revision(connection)
        _, key = _revisions(PRICING_REVISION)
        connection.execute("insert or replace into allowance_report_cache values (?,?,?,?)", (revision, key, 1, encode_report(report)))
        connection.execute("insert or replace into allowance_report_cache values (?,?,?,?)",
                           (revision, key+":pace-state", 1, json.dumps({"paces": report["paces"]})))
        connection.commit()
    return datetime.fromisoformat(anchor.timestamp)

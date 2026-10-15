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
        return _build_from_costs(connection, costs, status=status, preparation=preparation)


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

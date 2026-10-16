"""Bounded, opt-in allowance support evidence from a read-only ledger snapshot."""
import json
import math
import sqlite3
from datetime import UTC, datetime

from codex_usage import __version__
from codex_usage.agent_paths import ledger_database_path
from codex_usage.allowance_index import _revisions
from codex_usage.ledger_queries import query_ledger_status
from codex_usage.ledger_schema import open_ledger
from codex_usage.pricing_identity import pricing_revision

MAX_DIAGNOSTICS_BYTES = 48 * 1024
PACE_FIELDS = ("name", "limit_id", "duration_minutes", "anchor", "reset", "method", "reason",
    "boundary", "span_seconds", "horizon_seconds", "observations", "movement", "rate", "gap_seconds",
    "corrections", "conflicts", "cost", "observed_start", "coverage_complete", "unpriced_tokens",
    "calibrated_reason", "exhaustion", "reset_balance", "expires_at")
ESTIMATE_FIELDS = ("confidence", "value", "span", "bins", "cost_span", "r_squared", "sensitivity_ratio")


def _scalars(source, fields):
    result = {}
    for key in fields:
        value = source.get(key)
        if isinstance(value, str):
            result[key] = value[:96]
        elif value is None or type(value) is bool or type(value) in (int, float) and math.isfinite(value):
            result[key] = value
    return result


def _cached_evidence(connection, revision, complete):
    _, key = _revisions(pricing_revision())
    where = " from allowance_report_cache where ledger_revision=? and pricing_revision=? and coverage_complete=?"
    args = (revision, key, int(complete))
    try:
        row = connection.execute("select json_extract(report_json,'$.report.paces'), "
            "json_extract(report_json,'$.report.headline'), json_array_length(report_json,'$.report.windows'), "
            "json_array_length(report_json,'$.captures')" + where, args).fetchone()
    except sqlite3.OperationalError as error:
        if "no such table: allowance_report_cache" not in str(error):
            raise
        row = None
    if row is None:
        return dict(state="not_generated", paces=[])
    result = dict(state="cached", window_count=row[2], capture_count=row[3], paces=[])
    if type(row[1]) is int and row[1] >= 0:
        estimate = connection.execute("select json_extract(report_json,?)" + where,
            (f"$.report.windows[{row[1]}].estimate", *args)).fetchone()[0]
        result["headline_estimate"] = _scalars(json.loads(estimate or "{}"), ESTIMATE_FIELDS)
    rows = [p for series in json.loads(row[0] or "[]") for p in series]
    for pace in rows[:24]:
        item = _scalars(pace, PACE_FIELDS)
        if isinstance(pace.get("reference"), dict):
            item["reference"] = _scalars(pace["reference"],
                ("value", "previous", "start", "end", "available_at", "confidence"))
        result["paces"].append(item)
    result["omitted_paces"] = max(0, len(rows)-24)
    return result


def allowance_diagnostics(codex_home, *, now=None):
    """Never probe, capture, fit, reprice, render HTML or open task files.

    Extract selected aggregate JSON fields in SQLite, not raw window/capture
    pools. A cold cache is reported as missing, not permission to build it.
    """
    now = now or datetime.now(UTC)
    with open_ledger(ledger_database_path(codex_home), read_only=True) as connection:
        connection.execute("begin")
        ledger = query_ledger_status(connection, now=now)
        status = ledger.plan_allowance
        evidence = _cached_evidence(connection, ledger.revision, ledger.coverage.complete)
    probe_code = status.get("diagnostics") or "none"
    if probe_code not in {"none", "probe_failed", "probe_unavailable", "not_captured"}:
        probe_code = "other"
    data = dict(schema_version=1, version=__version__, generated_at=now.isoformat(),
        scope="Account-wide; cached allowance calculations, not live capture or a bill",
        ledger_revision=ledger.revision, coverage_complete=ledger.coverage.complete,
        probe=_scalars(status, ("plan", "probe_status", "last_probe_at", "last_observed_at")),
        probe_code=probe_code, recovery=_scalars(status.get("recovery", {}),
            ("total", "complete", "pending", "unavailable")), evidence=evidence)
    encoded = json.dumps(data, indent=2, allow_nan=False)
    while len(encoded.encode()) > MAX_DIAGNOSTICS_BYTES and evidence["paces"]:
        evidence["paces"].pop()
        evidence["omitted_paces"] += 1
        encoded = json.dumps(data, indent=2, allow_nan=False)
    if len(encoded.encode()) > MAX_DIAGNOSTICS_BYTES:
        raise ValueError("Allowance diagnostics exceeded the support-data limit")
    return dict(schema_version=1, text=encoded)

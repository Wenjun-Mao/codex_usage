"""Collector-owned private analytics queries, never an alternate collector."""
from datetime import UTC, datetime
from threading import RLock
from contextlib import nullcontext

from codex_usage.agent_paths import ledger_database_path
from codex_usage.agent_reports import PRICING_REVISION
from codex_usage.aggregation import resolve_report_range, resolve_timezone
from codex_usage.allowance_index import indexed_allowance_report
from codex_usage.allowance_queries import allowance_status
from codex_usage.companion_contract import (
    SCHEMA_VERSION, CompanionError, QueryScope, SelectionHandles, check_fields, page_size,
)
from codex_usage.companion_projection import allowance_projection, status_projection, usage_projection
from codex_usage.companion_snapshots import SnapshotStore
from codex_usage.ledger_materialization import materialize_ledger
from codex_usage.ledger_queries import query_ledger_status
from codex_usage.ledger_schema import open_ledger

CAPABILITY = "private-companion-v1"


class CompanionService:
    def __init__(self, home, settings, *, now=lambda: datetime.now(UTC), store=None, storage=None):
        self.home, self.settings, self.now = home, settings, now
        self.handles = SelectionHandles()
        self.store = store or SnapshotStore()
        self._lock = RLock()
        self._cache: dict[tuple, str] = {}
        self.storage = storage

    def query(self, payload: dict, *, capture=None, runtime_status=None) -> dict:
        if not isinstance(payload, dict) or not isinstance(payload.get("kind"), str):
            raise CompanionError()
        # Waiting I/O must not prevent a different HTTP worker from cancelling.
        controls = {"storage", "storage_start", "storage_job", "storage_cancel", "capture", "health"}
        with nullcontext() if payload.get("kind") in controls else self._lock:
            try:
                return self._query(payload, capture=capture, runtime_status=runtime_status)
            except CompanionError:
                raise
            except (ValueError, TypeError, KeyError):
                raise CompanionError() from None

    def _query(self, payload, *, capture, runtime_status):
        kind = payload.get("kind")
        if kind in {"storage", "storage_start", "storage_job", "storage_cancel"}:
            if self.storage is None:
                raise CompanionError("action_unavailable")
            return self.storage.query(payload, self.handles)
        if kind == "health":
            check_fields(payload, {"kind"})
            return {"schema_version": SCHEMA_VERSION, "capability": CAPABILITY,
                    "data": self._health(runtime_status)}
        if kind == "capture":
            check_fields(payload, {"kind"})
            if capture is None:
                raise CompanionError("action_unavailable")
            result = capture().result()
            return {"schema_version": SCHEMA_VERSION, "data": {
                "run_id": result.run_id, "request_kind": result.request_kind,
                "outcome": result.outcome, "elapsed_seconds": result.elapsed_seconds,
                "status": status_projection(result.status),
                "error_code": "capture_failed" if result.outcome != "success" else None,
            }}
        if "cursor" in payload:
            check_fields(payload, {"kind", "cursor"})
            if not isinstance(payload["cursor"], str):
                raise CompanionError()
            return self.store.next_page(payload["cursor"], kind)
        now = self.now()
        settings = self.settings()
        timezone = resolve_timezone(settings.timezone)
        with open_ledger(ledger_database_path(self.home), read_only=True) as connection:
            connection.execute("begin")
            status = query_ledger_status(connection)
            if kind == "projects":
                check_fields(payload, {"kind", "limit"})
                limit = page_size(payload)
                rows = [{"id": self.handles.issue("project", row["project_key"]),
                         "label": "Project " + self.handles.issue("project", row["project_key"])[-6:]}
                        for row in connection.execute("select project_key from ledger_projects order by project_key")]
                envelope = self._envelope(status, now, timezone, {"period": "catalog"})
                token = self.store.put(envelope, {"dimensions": {"project": rows}})
                return self.store.page(token, kind, "project", 0, limit)
            if kind == "allowance":
                check_fields(payload, {"kind"})
                report = indexed_allowance_report(
                    connection, ledger_database_path(self.home), revision=status.revision,
                    pricing_revision=PRICING_REVISION, coverage_complete=status.coverage.complete,
                )
                report = dict(report, status=allowance_status(connection, now=now))
                return {**self._envelope(status, now, timezone, {"period": "account-wide"}),
                        "data": allowance_projection(report, now.timestamp())}
            if kind == "compare":
                check_fields(payload, {"kind", "left", "right"})
                left, le = self._usage(connection, status, payload.get("left"), timezone, settings, now)
                right, re = self._usage(connection, status, payload.get("right"), timezone, settings, now)
                fields = {"tokens": ("usage", "total_tokens"), "api_cost_usd": ("api_cost", "total_usd"),
                          "estimated_standard_credits": ("estimated_standard_credits", "total_credits")}
                changes = {}
                for name, (category, field) in fields.items():
                    a, b = left["language"][category][field], right["language"][category][field]
                    changes[name] = {"left": a, "right": b, "delta": b - a,
                                     "percent_change": 100 * (b - a) / a if a else None}
                return {**self._envelope(status, now, timezone, {"left": le["scope"], "right": re["scope"]}),
                        "resolved_range": {"left": le["resolved_range"], "right": re["resolved_range"]},
                        "data": {"left": self._summary(left), "right": self._summary(right),
                                 "changes": changes, "direction": "right minus left"}}
            if kind not in {"summary", "breakdown"}:
                raise CompanionError()
            check_fields(payload, {"kind", "scope"} if kind == "summary" else
                         {"kind", "scope", "dimension", "metric", "limit"})
            data, envelope = self._usage(connection, status, payload.get("scope", {}), timezone, settings, now)
            if kind == "summary":
                return {**envelope, "data": self._summary(data)}
            dimension, metric = payload.get("dimension", "project"), payload.get("metric", "api_cost")
            if dimension not in data["dimensions"] or metric not in {"api_cost", "tokens"}:
                raise CompanionError()
            rows = sorted(data["dimensions"][dimension], key=lambda r: (
                -(r["api_cost"]["total_usd"] if metric == "api_cost" else r["usage"]["total_tokens"]), r["id"],
            )) if dimension not in {"day", "hour"} else data["dimensions"][dimension]
            token = self.store.put(envelope, {"dimensions": {dimension: rows}})
            return self.store.page(token, kind, dimension, 0, page_size(payload))

    def _usage(self, connection, status, raw_scope, timezone, settings, now):
        scope = QueryScope.parse(raw_scope)
        keys = [self.handles.resolve("project", handle) for handle in scope.project_ids]
        report_range = resolve_report_range(scope.period, timezone, start_date=scope.start_date,
                                            end_date=scope.end_date, now=now)
        cache_key = (status.revision, report_range.cache_identity, scope.project_ids,
                     settings.auto_project_transitions, PRICING_REVISION,
                     repr(status_projection(status)))
        cached = self._cache.get(cache_key)
        if cached:
            try:
                snapshot = self.store.get(cached)
                return snapshot.data, snapshot.envelope
            except CompanionError:
                del self._cache[cache_key]
        data = usage_projection(materialize_ledger(
            connection, report_range, keys, timezone, status,
            auto_transitions=settings.auto_project_transitions,
        ), timezone, self.handles)
        envelope = self._envelope(status, now, timezone, scope.to_dict()) | {
            "resolved_range": {
                "start_date": report_range.start_date.isoformat() if report_range.start_date else None,
                "end_date": report_range.end_date.isoformat() if report_range.end_date else None,
            },
        }
        token = self.store.put(envelope, data)
        self._cache = {key: value for key, value in self._cache.items() if value in self.store.items}
        self._cache[cache_key] = token
        return data, envelope

    @staticmethod
    def _summary(data):
        return {key: data[key] for key in (
            "language", "categories", "images", "image_coverage", "image_groups", "roles",
        )} | {"economics": data["economics"]["benchmark"],
             "row_counts": {key: len(rows) for key, rows in data["dimensions"].items()}}

    @staticmethod
    def _envelope(status, now, timezone, scope):
        return {"schema_version": SCHEMA_VERSION, "generated_at": now.isoformat(),
                "timezone": str(timezone), "scope": scope, "status": status_projection(status),
                "pricing_revision": PRICING_REVISION,
                "price_basis": "effective-dated API equivalent; estimated Standard credits; images separate"}

    def _health(self, runtime_status):
        with open_ledger(ledger_database_path(self.home), read_only=True) as connection:
            status = status_projection(query_ledger_status(connection))
        raw = runtime_status() if runtime_status else {}
        return {**status, "capture_running": bool(raw.get("capture_running", False)),
                "next_capture_seconds": raw.get("next_capture_seconds"),
                "capabilities": [CAPABILITY]}

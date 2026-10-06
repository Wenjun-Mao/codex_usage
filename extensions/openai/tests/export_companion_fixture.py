"""Generate bridge fixtures from disposable captured data, never a live home."""
from datetime import UTC, datetime
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

from codex_usage.agent_capture import capture_once
from codex_usage.agent_jobs import HeavyIOLane
from codex_usage.agent_operations import OperationRegistry
from codex_usage.companion_service import CompanionService
from codex_usage.companion_storage import CompanionStorage
from codex_usage.agent_paths import ledger_database_path
from codex_usage.allowance_models import QuotaObservation
from codex_usage.allowance_probe import QuotaRead
from codex_usage.allowance_store import store_read
from codex_usage.ledger_schema import increment_ledger_revision, open_ledger


def main():
    with TemporaryDirectory(prefix="codex-usage-private-fixture-") as directory:
        home = Path(directory)
        sessions = home / "sessions"
        sessions.mkdir()
        for task, project, day, tokens in (("a", "alpha", 5, 2000000), ("b", "beta", 6, 4000000)):
            stamp = f"2026-10-{day:02d}T15:00:00Z"
            rows = [
                {"type": "session_meta", "timestamp": stamp, "payload": {"id": task, "cwd": f"/private/{project}"}},
                {"type": "turn_context", "timestamp": stamp, "payload": {"model": "gpt-6-sol"}},
                {"type": "event_msg", "timestamp": stamp, "payload": {"type": "token_count", "info": {
                    "total_token_usage": {"input_tokens": tokens - 1000, "cached_input_tokens": tokens - 10000,
                                          "output_tokens": 1000, "total_tokens": tokens}}}},
                {"type": "compacted", "payload": {"message": "x" * 10000}},
            ]
            (sessions / f"{task}.jsonl").write_text("\n".join(json.dumps(r) for r in rows) + "\n")
        with patch("codex_usage.agent_capture.capture_quota_read", lambda *args: None):
            assert capture_once(home, request_kind="manual", max_workers=1).outcome == "success"
        with open_ledger(ledger_database_path(home)) as conn:
            stamp = "2026-10-06T20:00:00+00:00"
            reset = int(datetime(2026, 10, 10, 20, tzinfo=UTC).timestamp())
            point = QuotaObservation(stamp, "codex", "primary", "pro", 20, 10080, reset)
            store_read(conn, QuotaRead(stamp, "pro", (point,)), 1)
            increment_ledger_revision(conn)
            conn.commit()
        lane = HeavyIOLane()
        try:
            settings = SimpleNamespace(timezone="America/Toronto", auto_project_transitions=True)
            service = CompanionService(home, lambda: settings, now=lambda: datetime(2026, 10, 6, 20, tzinfo=UTC),
                storage=CompanionStorage(home, lane, OperationRegistry(lane)))
            fixtures = {"projects": service.query({"kind": "projects", "limit": 100}),
                        "allowance": service.query({"kind": "allowance"}),
                        "storage": service.query({"kind": "storage"}), "scopes": {}}
            for period in ("today", "yesterday", "7d", "30d", "month", "all", "custom"):
                for project in ["all", *[r["id"] for r in fixtures["projects"]["data"]["rows"]]]:
                    scope = {"period": period, "project_ids": [] if project == "all" else [project]}
                    if period == "custom":
                        scope.update(start_date="2026-10-05", end_date="2026-10-06")
                    fixtures["scopes"][f"{period}:{project}"] = {
                        "summary": service.query({"kind": "summary", "scope": scope}),
                        "breakdowns": {d: service.query({"kind": "breakdown", "scope": scope, "dimension": d})
                                       for d in ("project", "model", "agent", "day", "hour")},
                    }
            fixtures["comparison"] = service.query({"kind": "compare", "left": {"period": "yesterday"}, "right": {"period": "today"}})
            print(json.dumps(fixtures))
        finally:
            lane.close()


if __name__ == "__main__":
    main()

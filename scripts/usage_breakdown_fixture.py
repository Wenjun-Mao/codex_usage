"""Public synthetic usage/capture evidence; never probes a real account."""
from datetime import UTC, datetime, timedelta
import json

from codex_usage.agent_paths import ledger_database_path
from codex_usage.allowance_models import QuotaObservation
from codex_usage.allowance_probe import QuotaRead
from codex_usage.allowance_store import store_read
from codex_usage.ledger_schema import increment_ledger_revision, open_ledger
from codex_usage.ledger_sync import synchronize_parser_workset
from codex_usage.session_cache import refresh_cached_session_data


AT = datetime(2026, 10, 9, 12, tzinfo=UTC)


def breakdown_home(home, *, now=AT, projects=13, days=4, duration=10080):
    sessions = home / "sessions"
    sessions.mkdir(parents=True, exist_ok=True)
    models = ("gpt-6.1-sol", "gpt-6-luna", "codex-auto-review", "unknown-synthetic")
    for p in range(projects):
        rows = [{"type": "session_meta", "timestamp": (now - timedelta(days=days-1)).isoformat(),
                 "payload": {"id": f"synthetic-{p}", "cwd": f"/synthetic/project-{p:02d}"}}]
        cumulative = {"input_tokens": 0, "cached_input_tokens": 0, "output_tokens": 0, "total_tokens": 0}
        for day in reversed(range(days)):
            for hour in (1, 6, 11):
                for i, model in enumerate(models):
                    at = now.replace(hour=hour, minute=i + 1) - timedelta(days=day)
                    rows.append({"type": "turn_context", "timestamp": at.isoformat(), "payload": {"model": model}})
                    tokens = (projects - p) * (i + 1) * 100
                    usage = {"input_tokens": tokens, "cached_input_tokens": tokens // 2,
                             "output_tokens": tokens, "total_tokens": tokens * 2}
                    for key, value in usage.items():
                        cumulative[key] += value
                    rows.append({"type": "event_msg", "timestamp": at.isoformat(), "payload": {
                        "type": "token_count", "info": {"last_token_usage": usage,
                        "total_token_usage": dict(cumulative)}}})
        (sessions / f"rollout-synthetic-{p}.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
    path = ledger_database_path(home)
    with open_ledger(path):
        pass
    refresh_cached_session_data([sessions], cache_database_path=path, max_workers=1)
    synchronize_parser_workset(path)
    with open_ledger(path) as connection:
        for index in range(7):
            at = now - timedelta(hours=(6 - index) * 12)
            point = QuotaObservation(at.isoformat(), "codex", "secondary" if index % 2 else "primary",
                                     "pro", 21 if index == 4 else 10 + index * 4,
                                     duration, int((now + timedelta(days=4)).timestamp()))
            store_read(connection, QuotaRead(at.isoformat(), "pro", (point,)), None)
        increment_ledger_revision(connection)
        connection.commit()
    return path

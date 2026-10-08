"""Public synthetic response evidence for tests and packaged/browser acceptance."""
from datetime import UTC, datetime, timedelta
import json

from codex_usage.models import TokenUsage

AT = datetime(2026, 10, 8, 12, tzinfo=UTC)
TOKENS = TokenUsage(100, 20, 5, 600, 200, 700)


def response(index=0, *, at=AT, seconds=2, model="gpt-6.1-sol", response_id=None):
    at += timedelta(seconds=index * 30)
    base = at.timestamp() * 1000
    usage = TOKENS.to_dict()
    total = {k: v * (index + 1) for k, v in usage.items()}
    def row(kind, payload, offset=0):
        return {"type": kind, "timestamp": (at + timedelta(seconds=offset)).isoformat(), "payload": payload}
    return [
        row("turn_context", {"turn_id": f"turn-{index}", "model": model, "effort": "medium"}),
        row("event_msg", {"type": "item_completed", "turn_id": f"turn-{index}", "started_at_ms": base, "completed_at_ms": base + seconds * 500, "item": {"type": "Reasoning", "id": f"reason-{index}"}}, seconds / 2),
        row("event_msg", {"type": "item_completed", "turn_id": f"turn-{index}", "started_at_ms": base + seconds * 500, "completed_at_ms": base + seconds * 1000, "item": {"type": "AgentMessage", "id": f"answer-{index}"}}, seconds),
        row("response_item", {"type": "message", "role": "assistant", "content": [{"text": "SYNTHETIC SECRET NOT STORED"}]}, seconds),
        row("token_usage_record", {"response_id": response_id or f"response-{index}", "turn_id": f"turn-{index}", "usage": usage}, seconds),
        row("event_msg", {"type": "token_count", "info": {"total_token_usage": total, "last_token_usage": usage}}, seconds + .001),
    ]


def write_source(home, *, task="task", count=5, directory="sessions", seconds=2, at=AT, cwd="/synthetic/project"):
    path = home / directory / f"rollout-{task}.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = [{"type": "session_meta", "timestamp": at.isoformat(), "payload": {"id": task, "cwd": cwd, "cli_version": "synthetic"}}]
    for i in range(count):
        rows.extend(response(i, at=at, seconds=seconds))
    path.write_text("".join(json.dumps(r) + "\n" for r in rows))
    return path


def append_rows(path, rows):
    with path.open("a") as stream:
        stream.write("".join(json.dumps(row) + "\n" for row in rows))


def legacy_speed_home(home):
    """Freeze a schema-5/10 captured home for executable migration checks."""
    from codex_usage.agent_paths import ledger_database_path
    from codex_usage.ledger_schema import open_ledger
    from codex_usage.ledger_sync import synchronize_parser_workset
    from codex_usage.session_cache import refresh_cached_session_data
    write_source(home, task="timed", count=20)
    db = ledger_database_path(home)
    with open_ledger(db):
        pass
    refresh_cached_session_data([home / "sessions"], cache_database_path=db, max_workers=1)
    synchronize_parser_workset(db)
    with open_ledger(db) as connection:
        baseline = tuple(connection.execute("select count(*), sum(total_tokens), sum(output_tokens) from ledger_usage_events").fetchone())
        for row in connection.execute("select file_key, state_json from parser_checkpoints").fetchall():
            state = json.loads(row["state_json"])
            state.pop("speed_state", None)
            connection.execute("update parser_checkpoints set state_json=? where file_key=?", (json.dumps(state), row["file_key"]))
        for table in ("ledger_speed_identities", "ledger_speed_facts", "speed_recovery", "speed_report_cache", "speed_html_cache", "speed_cache_facts", "speed_cache_tools", "speed_cache_dirty"):
            connection.execute(f"drop table {table}")
        connection.execute("update ledger_meta set value='5' where key='schema_version'")
        connection.execute("update schema_meta set value='10' where key='schema_version'")
        connection.commit()
    return db, baseline


def chart_home(home):
    """Three exact models, sparse dates, varied efforts and normal/small samples."""
    from codex_usage.agent_paths import ledger_database_path
    from codex_usage.ledger_schema import open_ledger
    from codex_usage.ledger_sync import synchronize_parser_workset
    from codex_usage.session_cache import refresh_cached_session_data
    for model, seconds in (("gpt-6-astra", 18), ("gpt-6.1-sol", 12), ("gpt-6-luna", 5)):
        path = write_source(home, task=model, count=0, at=AT - timedelta(days=8))
        index = 0
        for day in range(9):
            if day == 4:
                continue
            for i in range(20 if day < 7 else 8):
                rows = response(index, at=AT - timedelta(days=8 - day, seconds=(index - i) * 30),
                                seconds=seconds + i % 3, model=model, response_id=f"{model}-{index}")
                rows[0]["payload"]["effort"] = "high" if i % 2 else "medium"
                append_rows(path, rows)
                index += 1
    db = ledger_database_path(home)
    with open_ledger(db):
        pass
    refresh_cached_session_data([home / "sessions"], cache_database_path=db, max_workers=1)
    synchronize_parser_workset(db)
    return db

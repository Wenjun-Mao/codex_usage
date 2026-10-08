"""Generation-bound promotion and order-independent duplicate settlement."""
from dataclasses import replace
import hashlib
import json
import sqlite3

from codex_usage.speed_models import TOKEN_FIELDS, SpeedFact


def revision(connection: sqlite3.Connection) -> int:
    row = connection.execute("select value from ledger_meta where key='speed_revision'").fetchone()
    return int(row[0]) if row else 0


def touch(connection: sqlite3.Connection) -> None:
    connection.execute("update ledger_meta set value=? where key='speed_revision'", (str(revision(connection) + 1),))
    connection.execute("delete from speed_report_cache")
    connection.execute("delete from speed_html_cache")


def cache_speed(connection, file_key, parsed) -> None:
    if not parsed.speed_facts and not parsed.speed_tools and not parsed.speed_uncertain_tools:
        return
    for fact in parsed.speed_facts:
        connection.execute("""insert into speed_cache_facts values (?, ?, ?, ?, ?, 1)
            on conflict(file_key, record_index) do update set evidence_json=excluded.evidence_json,
            start_ms=excluded.start_ms, end_ms=excluded.end_ms, dirty=1
            where speed_cache_facts.evidence_json!=excluded.evidence_json""",
            (file_key, fact.record_index, json.dumps(fact.to_dict(), sort_keys=True), fact.start_ms, fact.end_ms))
    for start, end in parsed.speed_tools:
        inserted = connection.execute("insert or ignore into speed_cache_tools values (?, ?, ?)", (file_key, start, end))
        if inserted.rowcount:
            connection.execute("update speed_cache_facts set dirty=1 where file_key=? and end_ms>? and start_ms<?",
                               (file_key, start, end if end > start else start + .001))
    for turn in parsed.speed_uncertain_tools:
        inserted = connection.execute("insert or ignore into speed_cache_uncertain_tools values (?, ?)", (file_key, turn))
        if inserted.rowcount:
            connection.execute("""update speed_cache_facts set dirty=1 where file_key=?
                and json_extract(evidence_json, '$.turn_id')=?""", (file_key, turn))
    connection.execute("insert or ignore into speed_cache_dirty values (?)", (file_key,))


def synchronize_speed(connection, *, usage_changed=False) -> bool:
    dirty = connection.execute("select file_key from speed_cache_dirty").fetchall()
    changed = False
    identities = set()
    for row in dirty:
        key = row[0]
        generation = connection.execute("""select g.generation_id from ledger_generations g
            join ledger_sources s using(source_id) where s.source_key=? and g.status='trusted'""", (key,)).fetchone()
        if generation is None:
            continue
        generation_id = generation[0]
        for cached in connection.execute("select evidence_json from speed_cache_facts where file_key=? and dirty=1", (key,)):
            value = json.loads(cached[0])
            value["usage"] = tuple(value["usage"])
            fact = SpeedFact(**value)
            trusted = connection.execute("""select e.*, m.model_key from ledger_usage_events e
                join ledger_models m using(model_id) where generation_id=? and source_record_index=?""",
                (generation_id, fact.record_index)).fetchone()
            if trusted is None:
                continue
            if (tuple(trusted[k] for k in TOKEN_FIELDS) != fact.usage or
                trusted["model_key"] != fact.model or trusted["turn_id"] != fact.turn_id or
                trusted["timestamp"] != fact.timestamp or trusted["task_id"] != fact.task_id):
                fact = replace(fact, reason="trusted_event_mismatch")
            elif not fact.reason and connection.execute("""select 1 from speed_cache_uncertain_tools
                where file_key=? and turn_id=? limit 1""", (key, fact.turn_id)).fetchone():
                fact = replace(fact, reason="missing_tool_interval")
            elif not fact.reason and connection.execute("""select 1 from speed_cache_tools
                where file_key=? and ((start_ms < ? and end_ms > ?) or
                (start_ms=end_ms and start_ms > ? and start_ms < ?)) limit 1""",
                (key, fact.end_ms, fact.start_ms, fact.start_ms, fact.end_ms)).fetchone():
                fact = replace(fact, reason="tool_execution_overlap")
            encoded = json.dumps(fact.to_dict(), sort_keys=True, separators=(",", ":"))
            signature_value = {k: v for k, v in fact.to_dict().items()
                               if k not in {"task_id", "record_index", "cli_version", "effort"}}
            signature = hashlib.sha256(json.dumps(signature_value, sort_keys=True).encode()).hexdigest()
            old = connection.execute("select evidence_json from ledger_speed_facts where generation_id=? and record_index=?",
                                     (generation_id, fact.record_index)).fetchone()
            if old is not None and old[0] == encoded:
                continue
            if old:
                identities.add(json.loads(old[0])["response_id"])
            connection.execute("insert or replace into ledger_speed_facts values (?, ?, ?, ?, ?, ?, ?)",
                               (generation_id, fact.record_index, fact.response_id, trusted["timestamp_us"], encoded, signature, fact.reason))
            identities.add(fact.response_id)
            changed = True
        connection.execute("update speed_cache_facts set dirty=0 where file_key=?", (key,))
        usable = connection.execute("select 1 from ledger_speed_facts where generation_id=? and reason='' limit 1", (generation_id,)).fetchone()
        status, reason = ("complete", "") if usable else ("unmeasurable", "no_usable_timing")
        updated = connection.execute("""update speed_recovery set status=?, reason=? where generation_id=?
            and status!='pending' and reason in ('', 'no_usable_timing') and status!=?""",
            (status, reason, generation_id, status))
        changed |= bool(updated.rowcount)
    connection.execute("delete from speed_cache_dirty")
    if usage_changed:
        identities.update(row[0] for row in connection.execute("""select i.response_id from ledger_speed_identities i
            where exists(select 1 from ledger_generations g where g.generation_id=i.generation_id and g.status!='trusted')
            or (i.conflict=1 and exists(select 1 from ledger_speed_facts f join ledger_generations g using(generation_id)
                where f.response_id=i.response_id and g.status!='trusted'))"""))
        changed |= bool(identities)
    for identity in sorted(identities - {""}):
        # Replayed facts agree as a group or the entire group is excluded.
        group = connection.execute("""select f.* from ledger_speed_facts f
            join ledger_generations g using(generation_id)
            where f.response_id=? and g.status='trusted' order by f.generation_id, f.record_index""", (identity,)).fetchall()
        if not group:
            connection.execute("delete from ledger_speed_identities where response_id=?", (identity,))
            continue
        conflict = int(len({row["signature"] for row in group}) > 1)
        connection.execute("insert or replace into ledger_speed_identities values (?, ?, ?, ?)",
                           (identity, group[0]["generation_id"], group[0]["record_index"], conflict))
    if changed:
        touch(connection)
    return changed

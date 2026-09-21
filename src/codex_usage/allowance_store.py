"""Durable quota observations with deduplicated, content-free provenance."""
import hashlib
import json
import zlib
from dataclasses import asdict

from codex_usage.allowance_models import QuotaObservation


def observation_key(observation: QuotaObservation) -> str:
    return hashlib.sha256(json.dumps(asdict(observation), sort_keys=True).encode()).hexdigest()


def store_observations(connection, observations, *, source_key: str, provenance: str):
    grouped = {}
    for observation in observations:
        values = asdict(observation)
        if provenance == "recovered":
            values.pop("timestamp")
        key = hashlib.sha256(json.dumps(values, sort_keys=True).encode()).hexdigest()
        if provenance == "recovered":
            key = "recovered:" + key
        grouped.setdefault(key, []).append(observation)
    for key, group in grouped.items():
        observation = group[0]
        times = {item.timestamp for item in group}
        existing = connection.execute("select timestamps_blob from quota_observations where observation_key = ?", (key,)).fetchone()
        if existing and existing[0]:
            times.update(json.loads(zlib.decompress(existing[0])))
        ordered = sorted(times)
        blob = zlib.compress(json.dumps(ordered).encode()) if provenance == "recovered" else None
        connection.execute(
            """insert into quota_observations values (?,?,?,?,?,?,?,?,?,?,?,?)
            on conflict(observation_key) do update set timestamp=excluded.timestamp,
            last_timestamp=excluded.last_timestamp, sample_count=excluded.sample_count,
            timestamps_blob=excluded.timestamps_blob""",
            (key, ordered[0], ordered[-1], len(ordered),
             observation.limit_id, observation.slot, observation.plan,
             observation.used_percent, observation.duration_minutes,
             observation.resets_at, observation.reset_credits, blob),
        )
        connection.execute("insert or ignore into quota_provenance values (?,?,?)", (key, source_key, provenance))


def store_read(connection, read, run_id):
    cursor = connection.execute(
        "insert into quota_reads(capture_run_id,timestamp,plan,lifetime_tokens,diagnostics) values (?,?,?,?,?)",
        (run_id, read.timestamp, read.plan, read.lifetime_tokens, read.diagnostics),
    )
    store_observations(connection, read.observations, source_key=f"read:{cursor.lastrowid}", provenance="live")


def cache_observations(connection, file_key, observations):
    connection.executemany("insert or ignore into quota_cache values (?,?,?)", [
        (file_key, observation_key(item), json.dumps(asdict(item), sort_keys=True)) for item in observations
    ])


def synchronize_quota_cache(connection):
    for row in connection.execute("select * from quota_cache"):
        store_observations(connection, (QuotaObservation(**json.loads(row["observation_json"])),),
                           source_key=row["file_key"], provenance="parsed")
    connection.execute("delete from quota_cache")

"""Indexed provenance loading preserves compacted samples and exact origins."""
from datetime import UTC, datetime, timedelta
import json
from unittest.mock import patch
import zlib

from codex_usage.allowance_models import QuotaObservation
from codex_usage.allowance_queries import load_quota_evidence
from codex_usage.allowance_store import observation_key, store_observations
from codex_usage.ledger_schema import open_ledger


def point(hour, used=20):
    return QuotaObservation((datetime(2026, 10, 1, tzinfo=UTC) + timedelta(hours=hour)).isoformat(),
        "codex", "secondary", "pro", used, 10080, 1791244800, 2)


def legacy_load(connection):
    labels = {"live": "Live probe", "parsed": "Task snapshot", "recovered": "Recovered task snapshot"}
    rows = connection.execute("""select o.*, p.origins from quota_observations o left join (
        select observation_key, json_group_array(distinct provenance) origins
        from quota_provenance group by observation_key) p using(observation_key)
        order by o.timestamp, o.rowid""")
    points, provenance, live = [], {}, set()
    for row in rows:
        raw = QuotaObservation(**{key: row[key] for key in QuotaObservation.__dataclass_fields__})
        stamps = json.loads(zlib.decompress(row["timestamps_blob"])) if row["timestamps_blob"] else [raw.timestamp]
        origins = json.loads(row["origins"]) if row["origins"] else []
        sources = {labels.get(origin, "Unknown source") for origin in origins} or {"Unknown source"}
        for stamp in stamps:
            selected = QuotaObservation(**{**raw.to_dict(), "timestamp": stamp})
            points.append(selected)
            provenance.setdefault(selected, set()).update(sources)
            if "live" in origins:
                live.add(selected)
    return points, provenance, live


def test_compact_duplicate_conflicting_and_missing_provenance_match_legacy(tmp_path):
    with open_ledger(tmp_path / "ledger.sqlite3") as connection:
        for origin in ("parsed", "recovered", "live", "unknown"):
            store_observations(connection, [point(i) for i in range(5)], source_key=origin, provenance=origin)
        store_observations(connection, [point(2, 90)], source_key="conflict", provenance="parsed")
        store_observations(connection, [point(6)], source_key="removed", provenance="live")
        connection.execute("delete from quota_provenance where observation_key=?", (observation_key(point(6)),))
        assert load_quota_evidence(connection) == legacy_load(connection)


def test_repeated_origin_combinations_decode_once_and_query_uses_existing_index(tmp_path):
    with open_ledger(tmp_path / "ledger.sqlite3") as connection:
        store_observations(connection, [point(i) for i in range(100)], source_key="same", provenance="parsed")
        statements = []
        connection.set_trace_callback(statements.append)
        with patch("codex_usage.allowance_queries.json.loads", wraps=json.loads) as decode:
            points, provenance, live = load_quota_evidence(connection)
        connection.set_trace_callback(None)
        assert len(points) == len(provenance) == 100 and not live
        assert len({id(labels) for labels in provenance.values()}) == 1
        assert all(isinstance(labels, frozenset) for labels in provenance.values())
        assert decode.call_count == 1
        plan = [row[3] for row in connection.execute("explain query plan " + statements[0])]
        assert any("SEARCH p USING COVERING INDEX" in step for step in plan)
        assert not any("MATERIALIZE" in step for step in plan)

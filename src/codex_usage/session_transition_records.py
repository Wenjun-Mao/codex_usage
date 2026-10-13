"""Indexed predecessor selection for repository-transition inference."""
from datetime import UTC

from codex_usage.session_cache_queries import row_to_usage_record


def load_transition_predecessors(connection, observations):
    """Load only records that can be the latest record before an observation.

    Keep all timestamp ties and the old file/index input order: the inference
    oracle resolves ties using parsed timestamps, normalized paths and labels.
    """
    selected = {}
    origins = {(p.thread_id, p.timestamp) for p in observations if p.thread_id}
    for task, timestamp in sorted(origins):
        bound = int(timestamp.astimezone(UTC).timestamp() * 1_000_000)
        while True:
            row = connection.execute("""
                select r.timestamp_us from usage_records r
                join files f using(file_key)
                where r.session_id=? and r.timestamp_us<=? and f.file_key=f.session_id
                order by r.timestamp_us desc limit 1
            """, (task, bound)).fetchone()
            if row is None:
                break
            stamp = row[0]
            ties = connection.execute("""
                select r.* from usage_records r join files f using(file_key)
                where r.session_id=? and r.timestamp_us=? and f.file_key=f.session_id
                order by r.file_key, r.record_index
            """, (task, stamp)).fetchall()
            eligible = []
            for candidate in ties:
                record = row_to_usage_record(candidate)
                if record.timestamp < timestamp:
                    eligible.append(((candidate['file_key'], candidate['record_index']), record))
            if eligible:
                selected.update(eligible)
                break
            # Equal-time records are not predecessors. The parsed comparison
            # also preserves correctness at integer-microsecond rounding edges.
            bound = stamp - 1
    return [selected[key] for key in sorted(selected)]

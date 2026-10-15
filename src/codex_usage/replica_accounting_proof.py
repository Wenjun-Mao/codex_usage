"""Stored accounting containment is not authority to resume a raw parser."""
from dataclasses import dataclass
from datetime import UTC
import hashlib
import json

from codex_usage.ledger_events import _resolved_generation_records
from codex_usage.session_cache_queries import row_to_usage_record
from codex_usage.session_history import source_identity, validate_page_metadata
from codex_usage.session_parser_models import parser_state_to_json
from codex_usage.session_parser_events import parse_timestamp

class AccountingProofError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class AccountingCapture:
    key: str
    binding: dict
    lineage: dict
    cache: tuple
    normalized: tuple | None
    generation_id: int | None


def fact(record):
    # Project keys/aliases are accounting attribution; labels are mutable UI
    # metadata, just as storage paths are not independent consumption identity.
    usage = record.usage
    return (record.timestamp.astimezone(UTC).isoformat(), record.session_id, record.parent_thread_id,
        record.usage_role, record.turn_id, record.model, record.effort, record.collaboration_mode,
        record.project_key, record.project_aliases, record.cwd, record.git_repository_url, record.git_branch,
        record.project_previous_key, record.project_transition_effective_from,
        usage.input_tokens, usage.cached_input_tokens, usage.cache_write_input_tokens,
        usage.output_tokens, usage.reasoning_output_tokens, usage.total_tokens)


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True,
                                    separators=(",", ":")).encode()).hexdigest()


def capture_binding(replica):
    checkpoint, row = replica.checkpoint, replica.row
    state = json.loads(parser_state_to_json(checkpoint.state))
    return dict(key=row["file_key"], offset=checkpoint.byte_offset,
        head=checkpoint.head_sha256, boundary=checkpoint.boundary_sha256,
        device=checkpoint.source_device, inode=checkpoint.source_inode,
        count=checkpoint.next_record_index, parsed_at=row["parsed_at"],
        state=digest(state), session_id=checkpoint.session_id,
        root_json=json.dumps(state["root_metadata"], sort_keys=True, separators=(",", ":")),
        history_boundary=checkpoint.state.history_boundary_digest,
        root_session_id=checkpoint.state.root_session_id,
        root_fork=checkpoint.state.root_session_is_fork,
        inline_replay=checkpoint.state.root_inline_replay_possible)


def load_accounting_capture(connection, physical_key, replica):
    checkpoint, row = replica.checkpoint, replica.row
    metadata = checkpoint.state.root_metadata
    validate_page_metadata(metadata)
    if source_identity(metadata) != physical_key:
        raise AccountingProofError("identity_conflict")
    if checkpoint.state.row_drain or checkpoint.state.history_baseline_pending:
        raise AccountingProofError("partial_capture")
    if metadata.history_base is not None and not checkpoint.state.history_boundary_digest:
        raise AccountingProofError("lineage_evidence_missing")
    if row["error"] and "paginated_history_replica_" not in row["error"]:
        raise AccountingProofError("accounting_capture_error")
    lineage = dict(metadata=json.loads(parser_state_to_json(checkpoint.state))["root_metadata"],
        boundary=checkpoint.state.history_boundary_digest,
        root=checkpoint.state.root_session_id, fork=checkpoint.state.root_session_is_fork,
        inline_replay=checkpoint.state.root_inline_replay_possible)
    rows = connection.execute("select * from usage_records where file_key=? order by record_index",
                             (row["file_key"],)).fetchall()
    _complete(rows, "record_index", checkpoint.next_record_index)
    cached = tuple(fact(row_to_usage_record(item)) for item in rows)
    if connection.execute("select 1 from image_operations where file_key=? limit 1", (row["file_key"],)).fetchone():
        raise AccountingProofError("image_accounting_requires_separate_proof")
    generation = _generation(connection, row["file_key"])
    expected = tuple(fact(record) for _, record in _resolved_generation_records(
        connection, row["file_key"], start_record_index=0))
    normalized = expected
    if generation is not None:
        if (generation["captured_size"], generation["head_sha256"], generation["boundary_sha256"],
                generation["record_count"]) != (checkpoint.byte_offset, checkpoint.head_sha256,
                    checkpoint.boundary_sha256, checkpoint.next_record_index):
            raise AccountingProofError("normalized_capture_mismatch")
        if connection.execute("select 1 from ledger_image_events where generation_id=? limit 1",
                              (generation["generation_id"],)).fetchone():
            raise AccountingProofError("image_accounting_requires_separate_proof")
        normalized_rows = _normalized_rows(connection, generation["generation_id"])
        _complete(normalized_rows, "record_index", checkpoint.next_record_index)
        normalized = tuple(fact(row_to_usage_record(item)) for item in normalized_rows)
        if normalized != expected:
            raise AccountingProofError("cache_normalized_facts_mismatch")
    binding = capture_binding(replica)
    binding["normalized"] = (None if generation is None else dict(id=generation["generation_id"],
        offset=generation["captured_size"], count=generation["record_count"],
        head=generation["head_sha256"], boundary=generation["boundary_sha256"]))
    return AccountingCapture(row["file_key"], binding, lineage, cached,
        normalized, generation["generation_id"] if generation is not None else None)


def dominant_capture(captures):
    candidates = []
    for candidate in captures:
        if all(_covers(candidate, other) for other in captures):
            candidates.append(candidate)
    if not candidates:
        raise AccountingProofError("incomparable_captures")
    return min(candidates, key=lambda capture: capture.key)


def _covers(candidate, other):
    return (candidate.lineage == other.lineage
        and candidate.binding["offset"] >= other.binding["offset"]
        and len(candidate.cache) >= len(other.cache)
        and candidate.cache[:len(other.cache)] == other.cache
        and (other.normalized is None or (candidate.normalized is not None
            and candidate.normalized[:len(other.normalized)] == other.normalized)))


def _complete(rows, column, count):
    if len(rows) != count or any(row[column] != index for index, row in enumerate(rows)):
        raise AccountingProofError("incomplete_record_index")
    for row in rows:
        timestamp = parse_timestamp(row["timestamp"])
        if timestamp is None or row["timestamp_us"] != int(timestamp.timestamp()*1_000_000):
            raise AccountingProofError("inconsistent_timestamp_index")


def _generation(connection, key):
    if connection.execute("select 1 from sqlite_master where name='ledger_generations'").fetchone() is None:
        return None
    return connection.execute("""select g.* from ledger_generations g join ledger_sources s using(source_id)
        where s.source_key=? order by g.generation_number desc limit 1""", (key,)).fetchone()


def _normalized_rows(connection, generation_id):
    return connection.execute("""select e.*, e.source_record_index record_index, e.task_id session_id,
        m.model_key model, p.project_key, p.label project_label, c.project_aliases_json, c.cwd,
        c.repository_url git_repository_url, c.git_branch, c.effort, c.collaboration_mode,
        e.parent_task_id parent_thread_id, s.path file_path
        from ledger_usage_events e join ledger_generations g using(generation_id)
        join ledger_sources s using(source_id) join ledger_models m using(model_id)
        join ledger_contexts c using(context_id) join ledger_projects p on p.project_id=c.project_id
        where e.generation_id=? order by e.source_record_index""", (generation_id,)).fetchall()

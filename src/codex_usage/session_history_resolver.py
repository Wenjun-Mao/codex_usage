"""Resolve physical history prefixes without scanning or summing copied history."""
from dataclasses import dataclass
import hashlib
import os

from codex_usage.models import TokenUsage
from codex_usage.session_history import (
    HISTORY_CHAIN_LIMIT, HISTORY_PREFIX_LIMIT, HISTORY_READ_BUDGET, HISTORY_TAIL_LIMIT,
    HistoryBaseline,
)
from codex_usage.session_history_models import HistoryBoundary, PaginatedHistoryError, optional_ordinal
from codex_usage.session_parser_events import parse_json_line
from codex_usage.session_rollout_identity import rollout_identity

_COUNTERS = ("input_tokens", "cached_input_tokens", "cache_write_input_tokens",
             "output_tokens", "reasoning_output_tokens", "total_tokens")


@dataclass(slots=True)
class _Budget:
    remaining: int = HISTORY_READ_BUDGET

    @property
    def bytes_read(self):
        return HISTORY_READ_BUDGET - self.remaining

    def read(self, handle, size):
        if self.remaining < size:
            raise PaginatedHistoryError("paginated_history_read_budget_exhausted")
        data = handle.read(size)
        self.remaining -= len(data)
        return data


@dataclass(frozen=True, slots=True)
class _Counter:
    usage: TokenUsage | None = None
    replay_barrier: bool = False


def resolve(metadata, sources):
    budget = _Budget()
    try:
        identity = rollout_identity(metadata.file_path)
        counter, digest = _prefix(metadata.history_base, sources, budget, (identity.rollout_id,), {})
        if counter.usage is None:
            reason = "replay_boundary_unresolved" if counter.replay_barrier else "counter_unavailable"
            raise PaginatedHistoryError(f"paginated_history_{reason}")
        return HistoryBaseline(counter.usage, budget.bytes_read, digest)
    except PaginatedHistoryError as error:
        error.bytes_read = budget.bytes_read
        raise
    except OSError as error:
        failure = PaginatedHistoryError("paginated_history_source_unavailable")
        failure.bytes_read = budget.bytes_read
        raise failure from error


def _prefix(reference, sources, budget, chain, cache):
    physical = reference.rollout_id.lower()
    if physical in chain:
        raise PaginatedHistoryError("paginated_history_cycle")
    if len(chain) >= HISTORY_CHAIN_LIMIT:
        raise PaginatedHistoryError("paginated_history_chain_limit")
    key = (physical, reference.end_ordinal_exclusive, reference.end_byte_offset)
    if key in cache:
        return cache[key]
    found = []
    for source in sources:
        identity = rollout_identity(source.path)
        if identity is None or identity.rollout_id != physical:
            continue
        if source.rollout_id_hint and source.rollout_id_hint != physical:
            raise PaginatedHistoryError("paginated_history_inventory_mismatch")
        if source.size_bytes < reference.end_byte_offset:
            continue
        header, local_counter, digest = _read_prefix(source, identity, reference, budget)
        ancestor = HistoryBoundary.from_mapping(header["payload"].get("history_base"))
        inherited = _Counter()
        if ancestor is not None:
            inherited, prior_digest = _prefix(ancestor, sources, budget, (*chain, physical), cache)
            digest = hashlib.sha256((digest + prior_digest).encode()).hexdigest()
        counter = local_counter if local_counter.usage is not None or local_counter.replay_barrier else inherited
        found.append((counter, digest))
    if not found:
        raise PaginatedHistoryError("paginated_history_source_unavailable")
    if any(result != found[0] for result in found[1:]):
        raise PaginatedHistoryError("paginated_history_conflicting_baselines")
    cache[key] = found[0]
    return found[0]


def _read_prefix(source, identity, reference, budget):
    with source.path.open("rb", buffering=0) as handle:
        before = os.fstat(handle.fileno())
        _check_source(source, before)
        prefix = budget.read(handle, min(HISTORY_PREFIX_LIMIT, source.size_bytes))
        if _stat_version(before) != _stat_version(os.fstat(handle.fileno())):
            raise PaginatedHistoryError("paginated_history_source_changed")
        head, separator, _ = prefix.partition(b"\n")
        header = parse_json_line(head) if separator else None
        payload = header.get("payload") if header and header.get("type") == "session_meta" else None
        if (not isinstance(payload, dict) or not isinstance(payload.get("id"), str)
                or payload["id"].lower() != identity.thread_id
                or payload.get("history_mode") != "paginated"):
            raise PaginatedHistoryError("paginated_history_header_mismatch")
        parent = HistoryBoundary.from_mapping(payload.get("history_base"))
        first = optional_ordinal(header.get("ordinal"))
        expected = parent.end_ordinal_exclusive if parent else 0
        if first != expected or reference.end_ordinal_exclusive < first:
            raise PaginatedHistoryError("paginated_history_metadata_ordinal_mismatch")
        offset = reference.end_byte_offset
        counter = _Counter()
        tail = b""
        if offset == 0:
            if reference.end_ordinal_exclusive != first:
                raise PaginatedHistoryError("paginated_history_endpoint_ordinal_mismatch")
        else:
            width = min(HISTORY_TAIL_LIMIT, offset)
            start = offset - width
            handle.seek(start)
            tail = budget.read(handle, width)
            if len(tail) != width or not tail.endswith(b"\n"):
                raise PaginatedHistoryError("paginated_history_invalid_byte_boundary")
            lines = tail.splitlines() if start == 0 else tail.splitlines()[1:]
            if not lines:
                raise PaginatedHistoryError("paginated_history_endpoint_unavailable")
            last = parse_json_line(lines[-1])
            last_ordinal = optional_ordinal(last.get("ordinal")) if last else None
            if last_ordinal != reference.end_ordinal_exclusive - 1:
                raise PaginatedHistoryError("paginated_history_endpoint_ordinal_mismatch")
            counter = _last_counter(lines, first, reference.end_ordinal_exclusive)
            if counter.usage is None and not counter.replay_barrier and start > len(head) + 1:
                # There may be a local counter in the unread interior. Skipping
                # straight to the ancestor would manufacture a smaller baseline.
                raise PaginatedHistoryError("paginated_history_counter_outside_budget")
        after = os.fstat(handle.fileno())
        _check_source(source, after)
        if _stat_version(before) != _stat_version(after) or _stat_version(source.path.stat()) != _stat_version(after):
            raise PaginatedHistoryError("paginated_history_source_changed")
    digest = hashlib.sha256(head + b"\n" + tail).hexdigest()
    return header, counter, digest


def _last_counter(lines, first, end):
    for raw in reversed(lines):
        obj = parse_json_line(raw)
        if not obj:
            continue
        if obj.get("type") == "compacted":
            # Replay may begin at a usable compaction. Until its companion
            # telemetry is established, an older counter is not a proven seed.
            return _Counter(replay_barrier=True)
        if obj.get("type") != "event_msg":
            continue
        payload = obj.get("payload")
        if not isinstance(payload, dict) or payload.get("type") != "token_count":
            continue
        info = payload.get("info")
        counter = info.get("total_token_usage") if isinstance(info, dict) else None
        if counter is None:
            continue
        ordinal = optional_ordinal(obj.get("ordinal"))
        if ordinal is None or not first <= ordinal < end:
            raise PaginatedHistoryError("paginated_history_counter_ordinal_mismatch")
        if (not isinstance(counter, dict)
                or any(type(counter.get(k, 0)) is not int or counter.get(k, 0) < 0 for k in _COUNTERS)
                or any(k not in counter for k in ("input_tokens", "output_tokens", "total_tokens"))):
            raise PaginatedHistoryError("paginated_history_invalid_counter")
        return _Counter(TokenUsage.from_mapping(counter))
    return _Counter()


def _check_source(source, stat):
    if (stat.st_dev != source.source_device or stat.st_ino != source.source_inode
            or stat.st_size < source.size_bytes):
        raise PaginatedHistoryError("paginated_history_source_changed")


def _stat_version(stat):
    return (stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns)

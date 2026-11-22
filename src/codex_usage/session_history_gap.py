"""Conservative usage deltas when a continuation's opening counter is lost."""
from uuid import UUID

from codex_usage.models import TokenUsage
from codex_usage.session_history_models import PaginatedHistoryError
from codex_usage.session_rollout_identity import rollout_identity

OPENING_GAP = "paginated_history_opening_counter_unavailable"
COUNTERS = ("input_tokens", "cached_input_tokens", "cache_write_input_tokens",
            "output_tokens", "reasoning_output_tokens", "total_tokens")


def opening_baseline(metadata, sources, resolve, *, allow_missing):
    try:
        return resolve(metadata, sources)
    except PaginatedHistoryError as error:
        if not allow_missing or not _missing_predecessor(metadata, sources, error):
            raise
        return None


def _missing_predecessor(metadata, sources, error):
    # An invalid, short, conflicting, or changing owned file is not absent.
    if str(error) != "paginated_history_source_unavailable" or getattr(error, "bytes_read", 0):
        return False
    identity = rollout_identity(metadata.file_path)
    base = metadata.history_base
    if identity is None or identity.rollout_id == identity.thread_id or base is None:
        return False
    try:
        physical = str(UUID(base.rollout_id))
    except ValueError:
        return False
    return (physical == base.rollout_id.lower() and physical != identity.rollout_id
            and base.end_byte_offset > 0 and not any(
                (candidate := rollout_identity(source.path)) is not None
                and candidate.rollout_id == physical for source in sources))


def verified_counter(raw):
    if not isinstance(raw, dict) or not all(key in raw for key in
            ("input_tokens", "output_tokens", "total_tokens")):
        return None
    if any(type(raw.get(key, 0)) is not int or raw.get(key, 0) < 0 for key in COUNTERS):
        return None
    current = TokenUsage.from_mapping(raw)
    if (current.total_tokens != current.input_tokens + current.output_tokens
            or current.cached_input_tokens + current.cache_write_input_tokens > current.input_tokens
            or current.reasoning_output_tokens > current.output_tokens):
        return None
    return current


def observe_gap_counter(raw, ordinal, last_ordinal, previous):
    """Do not bridge a malformed/replayed row or a nonmonotone counter."""
    if type(ordinal) is not int or ordinal <= last_ordinal:
        return None, last_ordinal, None
    current = verified_counter(raw)
    if current is None or previous is None:
        return current, ordinal, None
    if any(getattr(current, key) < getattr(previous, key) for key in COUNTERS):
        return current, ordinal, None
    return current, ordinal, current.positive_delta(previous)

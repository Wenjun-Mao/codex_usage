"""Give parse workers a frozen owned inventory, not filesystem discovery power."""
from dataclasses import replace

from codex_usage.session_files import read_session_metadata_bounded
from codex_usage.session_history import HISTORY_PREFIX_LIMIT, HISTORY_READ_BUDGET, HistorySource

HISTORY_EXTRA_READ_BUDGET = 8 * 1024 * 1024


def prepare_history_requests(inventory, requests, cached_rows):
    metadata_by_path = {}
    selected = []
    remaining = HISTORY_EXTRA_READ_BUDGET
    bytes_read = 0
    for request in requests:
        if request.deferred_full_parse_reason:
            selected.append(request)
            continue
        checkpoint = request.checkpoint
        if checkpoint is not None and checkpoint.state.root_metadata is not None:
            metadata = checkpoint.state.root_metadata
        else:
            limit = max(1, min(HISTORY_PREFIX_LIMIT, request.size_bytes,
                               request.max_bytes or HISTORY_PREFIX_LIMIT))
            if remaining < limit + 1:
                continue
            read = read_session_metadata_bounded(request.path, max_bytes=limit)
            remaining -= read.bytes_read
            bytes_read += read.bytes_read
            metadata = read.metadata
        if metadata is not None:
            metadata_by_path[request.path] = metadata
        can_resolve = checkpoint is None or not request.defer_full_fallback or checkpoint.state.root_metadata is None
        reserve = HISTORY_READ_BUDGET if (request.size_bytes and can_resolve
            and (metadata is None or metadata.history_base is not None)) else 0
        if remaining < reserve:
            continue
        remaining -= reserve
        selected.append(request)

    sources = []
    for entry in inventory:
        sources.append(HistorySource.from_inventory(entry))

    prepared = []
    for request in selected:
        metadata = metadata_by_path.get(request.path)
        reference = metadata.history_base if metadata else None
        # An append with validated root metadata needs no historical reads.
        # Carry candidates only for a possible guarded full-parse fallback.
        fallback = request.checkpoint is not None and not request.defer_full_fallback
        needs_history = reference is not None or metadata is None or fallback
        candidates = tuple(source for source in sources
            if source.path != request.path and needs_history
            and source.rollout_id_hint)
        prepared.append(replace(request, history_sources=candidates))
    return prepared, bytes_read

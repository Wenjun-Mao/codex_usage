"""Schedule bounded parsing separately from cache ownership transactions."""
import os
from dataclasses import replace

from codex_usage.parallel.usage import UsageParseRequest
from codex_usage.session_cache_requests import eligible_append_checkpoint


def prepare_requests(connection, parse_entries, cached_rows, *, rebuilt,
                     max_parse_bytes, max_total_parse_bytes, defer_full_fallback,
                     preferred_paths, blocked_sources):
    plans = []
    preferred = {_normalized_path(path) for path in preferred_paths}
    for ordinal, entry in parse_entries:
        cached = cached_rows.get(entry.file_key)
        checkpoint = eligible_append_checkpoint(connection, entry, cached, rebuilt=rebuilt)
        reason = blocked_sources.get(entry.file_key, "")
        if (not reason and defer_full_fallback and not rebuilt and cached is not None
                and cached["checkpoint_offset"] is not None and checkpoint is None):
            reason = "source no longer satisfies the guarded append-only contract"
        request = UsageParseRequest(ordinal=ordinal, file_key=entry.file_key,
            path=entry.path, size_bytes=entry.size_bytes, mtime_ns=entry.mtime_ns,
            checkpoint=checkpoint, max_bytes=max_parse_bytes,
            defer_full_fallback=defer_full_fallback, deferred_full_parse_reason=reason)
        plans.append((_request_priority(request, cached,
            preferred=_normalized_path(entry.path) in preferred), request))
    return apply_total_parse_budget(plans, max_total_parse_bytes=max_total_parse_bytes,
                                    max_parse_bytes=max_parse_bytes)


def _request_priority(request, cached, *, preferred):
    if request.deferred_full_parse_reason:
        work_kind = 0
    elif (request.checkpoint is not None and cached is not None
            and int(cached["size_bytes"]) < request.size_bytes):
        work_kind = 1
    elif cached is None:
        work_kind = 2
    else:
        work_kind = 3
    parsed_at = str(cached["parsed_at"] or "") if cached is not None else ""
    return (0 if preferred else 1, work_kind, parsed_at, request.estimated_bytes, request.ordinal)


def apply_total_parse_budget(request_plans, *, max_total_parse_bytes, max_parse_bytes):
    if max_total_parse_bytes is None:
        return [request for _, request in request_plans]
    if max_total_parse_bytes < 1:
        raise ValueError("max_total_parse_bytes must be at least one")
    remaining = max_total_parse_bytes
    selected = []
    for _, request in sorted(request_plans, key=lambda item: item[0]):
        if request.deferred_full_parse_reason:
            selected.append(request)
            continue
        if remaining <= 0:
            continue
        request_limit = remaining
        if max_parse_bytes is not None:
            request_limit = min(request_limit, max_parse_bytes)
        request_limit = max(1, request_limit)
        selected.append(replace(request, max_bytes=request_limit))
        remaining -= min(request.estimated_bytes, request_limit)
    return selected


def _normalized_path(path):
    return os.path.normcase(os.path.abspath(os.path.expanduser(str(path))))

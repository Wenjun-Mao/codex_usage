from __future__ import annotations

import argparse
import os
import sys
from contextlib import nullcontext
from dataclasses import dataclass
from datetime import tzinfo
from pathlib import Path

from codex_usage.aggregation import (
    RangeBounds,
    filter_records_by_project_keys,
    filter_records_by_range,
    resolve_range_bounds,
    resolve_timezone,
)
from codex_usage.discovery import collect_jsonl_files, find_session_dirs
from codex_usage.models import UsageRecord
from codex_usage.parallel_audit import write_parallel_audit
from codex_usage.parser import parse_session_files
from codex_usage.performance_timing import PhaseTimer
from codex_usage.project_identity import normalize_project_key
from codex_usage.project_transitions import (
    ProjectTransition,
    apply_project_transitions,
    collect_repo_path_observations,
    infer_project_transitions,
)
from codex_usage.session_cache import (
    CachedSessionData,
    CacheStats,
    load_cached_session_data,
    uncached_session_data,
)
from codex_usage.session_inventory import collect_session_file_inventory
from codex_usage.settings import get_settings
from codex_usage.storage_insights import build_task_storage_insights
from codex_usage.storage_metadata import inspect_storage_files


@dataclass(frozen=True, slots=True)
class UsageContext:
    session_dirs: list[Path]
    files: list[Path]
    records: list[UsageRecord]
    timezone: tzinfo
    project_keys: list[str]
    project_transitions: list[ProjectTransition]
    storage_stats: CacheStats
    session_data: CachedSessionData | None = None


def load_usage_context(args: argparse.Namespace) -> UsageContext:
    settings = get_settings()
    timezone = resolve_timezone(args.timezone or settings.timezone)
    bounds = resolve_range_bounds(args.range_name, timezone)
    data = load_session_data_for_context(args, bounds)
    args._timing_cache_stats = data.stats
    write_requested_parallel_audit(args, data)
    project_keys = normalize_project_keys(args.project_key)
    records = filter_records_by_project_keys(data.records, project_keys)
    return UsageContext(
        session_dirs=data.session_dirs,
        files=data.files,
        records=records,
        timezone=timezone,
        project_keys=project_keys,
        project_transitions=filter_project_transitions(
            data.project_transitions, records
        ),
        storage_stats=data.stats,
        session_data=data,
    )


def load_session_data_for_context(
    args: argparse.Namespace,
    bounds: RangeBounds,
) -> CachedSessionData:
    settings = get_settings()
    timezone = resolve_timezone(args.timezone or settings.timezone)
    timer = getattr(args, "_phase_timer", None)
    with timer.measure("inventory") if timer else nullcontext():
        session_dirs = find_session_dirs()
    return load_session_data(
        session_dirs,
        auto_transitions=auto_project_transitions_enabled(args, settings),
        range_bounds=bounds,
        range_name=args.range_name,
        timezone=timezone,
        timer=timer,
    )


def load_session_data(
    session_dirs: list[Path],
    *,
    auto_transitions: bool,
    range_bounds: RangeBounds | None = None,
    range_name: str = "all",
    timezone: tzinfo | None = None,
    timer: PhaseTimer | None = None,
) -> CachedSessionData:
    try:
        return load_cached_session_data(
            session_dirs,
            auto_transitions=auto_transitions,
            range_bounds=range_bounds,
            timer=timer,
        )
    except Exception as exc:  # noqa: BLE001 - cache failures retain the direct-parse fallback contract.
        print(
            f"codex-usage: cache unavailable, falling back to direct parse: {exc}",
            file=sys.stderr,
        )
        with timer.measure("inventory") if timer else nullcontext():
            physical_inventory = collect_session_file_inventory(
                session_dirs, read_metadata=False
            )
            files = collect_jsonl_files(session_dirs)
        with timer.measure("storage_refresh") if timer else nullcontext():
            storage_insights = build_task_storage_insights(
                inspect_storage_files(physical_inventory), session_dirs
            )
        with timer.measure("usage_refresh") if timer else nullcontext():
            records = parse_session_files(files)
        project_transitions: list[ProjectTransition] = []
        with timer.measure("transition_refresh") if timer else nullcontext():
            if auto_transitions:
                observations = collect_repo_path_observations(session_dirs, files)
                project_transitions = infer_project_transitions(records, observations)
                records = apply_project_transitions(records, project_transitions)
        with timer.measure("range_query") if timer else nullcontext():
            if range_bounds is not None:
                if timezone is None:
                    raise ValueError(
                        "timezone is required for a range-selected fallback"
                    )
                records = filter_records_by_range(
                    records,
                    range_name,
                    timezone,
                    bounds=range_bounds,
                )
        return uncached_session_data(
            session_dirs=session_dirs,
            files=files,
            records=records,
            project_transitions=project_transitions,
            direct_fallback=True,
            storage_insights=storage_insights,
        )


def write_requested_parallel_audit(
    args: argparse.Namespace,
    data: CachedSessionData,
) -> None:
    path = getattr(args, "parallel_audit", None)
    if path is None:
        return
    write_parallel_audit(
        path,
        parent_pid=os.getpid(),
        usage_run=data.usage_run,
        transition_run=data.transition_run,
    )


def normalize_project_keys(values: list[str] | None) -> list[str]:
    selected: list[str] = []
    seen: set[str] = set()
    for value in values or []:
        key = normalize_project_key(value)
        if key and key not in seen:
            selected.append(key)
            seen.add(key)
    return selected


def auto_project_transitions_enabled(
    args: argparse.Namespace, settings: object
) -> bool:
    return settings.auto_project_transitions and not getattr(
        args, "no_auto_transitions", False
    )


def filter_project_transitions(
    transitions: list[ProjectTransition],
    records: list[UsageRecord],
) -> list[ProjectTransition]:
    if not transitions or not records:
        return []

    keys_by_session: dict[str, set[str]] = {}
    for record in records:
        if record.session_id:
            keys_by_session.setdefault(record.session_id, set()).update(
                record_project_keys(record)
            )

    filtered: list[ProjectTransition] = []
    for transition in transitions:
        transition_sessions = set(transition.thread_ids) or set(keys_by_session)
        matching_sessions = transition_sessions.intersection(keys_by_session)
        if any(
            transition_keys_represented(transition, keys_by_session[session_id])
            for session_id in matching_sessions
        ):
            filtered.append(transition)
    return filtered


def transition_keys_represented(
    transition: ProjectTransition,
    keys: set[str],
) -> bool:
    return transition.source_key in keys and transition.target_key in keys


def record_project_keys(record: UsageRecord) -> set[str]:
    return {
        key
        for key in (
            record.project_key,
            record.project_previous_key,
            *record.project_aliases,
        )
        if key
    }

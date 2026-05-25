from __future__ import annotations

import argparse
import socket
import sys
from datetime import datetime
from pathlib import Path

from codex_usage.aggregation import (
    GROUP_CHOICES,
    RANGE_CHOICES,
    aggregate_records,
    filter_records_by_project_keys,
    filter_records_by_range,
    resolve_timezone,
    summarize_records,
)
from codex_usage.discovery import collect_jsonl_files, default_session_dir, find_session_dirs
from codex_usage.models import UsageRecord
from codex_usage.parser import parse_session_files
from codex_usage.project_identity import normalize_project_key
from codex_usage.project_transitions import (
    ProjectTransition,
    apply_project_transitions,
    collect_repo_path_observations,
    infer_project_transitions,
)
from codex_usage.reporting import (
    print_json,
    render_html_report,
    render_terminal,
    summary_payload,
    write_csv,
)
from codex_usage.report_theme import REPORT_THEME_CHOICES, normalize_report_theme
from codex_usage.session_cache import CachedSessionData, load_cached_session_data, uncached_session_data
from codex_usage.settings import get_settings
from codex_usage.sync import export_threads, import_threads, sync_status
from codex_usage.threads import list_threads_from_cached_data


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not hasattr(args, "handler"):
        parser.print_help(sys.stderr)
        return 2
    try:
        return args.handler(args)
    except (FileNotFoundError, ValueError) as exc:
        print(f"codex-usage: {exc}", file=sys.stderr)
        return 2


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Analyze local Codex session token usage.")
    subparsers = parser.add_subparsers(dest="command")

    summary_parser = subparsers.add_parser("summary", help="Print usage summary.")
    _add_common_options(summary_parser)
    summary_parser.add_argument("--range", dest="range_name", choices=RANGE_CHOICES, default="today")
    summary_parser.add_argument("--by", dest="group_by", choices=GROUP_CHOICES, default="day")
    summary_parser.add_argument("--json", action="store_true", help="Print machine-readable JSON.")
    summary_parser.add_argument(
        "--csv",
        nargs="?",
        const="-",
        default=None,
        help="Write CSV to a path, or stdout when no path is provided.",
    )
    summary_parser.set_defaults(handler=handle_summary)

    report_parser = subparsers.add_parser("report", help="Write a self-contained HTML report.")
    _add_common_options(report_parser)
    report_parser.add_argument("--range", dest="range_name", choices=RANGE_CHOICES, default="30d")
    report_parser.add_argument("--theme", choices=REPORT_THEME_CHOICES, default=None)
    report_parser.add_argument("--output", type=Path, default=Path("output/report.html"))
    report_parser.set_defaults(handler=handle_report)

    threads_parser = subparsers.add_parser("threads", help="List Codex threads.")
    _add_common_options(threads_parser)
    threads_parser.add_argument("--json", action="store_true", help="Print machine-readable JSON.")
    threads_parser.set_defaults(handler=handle_threads)

    transitions_parser = subparsers.add_parser("transitions", help="Inspect inferred project transitions.")
    transitions_subparsers = transitions_parser.add_subparsers(dest="transitions_command")
    transitions_parser.set_defaults(handler=handle_subparser_help, help_parser=transitions_parser)

    suggest_parser = transitions_subparsers.add_parser("suggest", help="Suggest project transitions.")
    suggest_parser.add_argument("--json", action="store_true", help="Print machine-readable JSON.")
    suggest_parser.set_defaults(handler=handle_transitions_suggest)

    sync_parser = subparsers.add_parser("sync", help="Synchronize selected Codex threads.")
    sync_subparsers = sync_parser.add_subparsers(dest="sync_command")

    export_parser = sync_subparsers.add_parser("export", help="Export selected threads to a sync folder.")
    _add_sync_options(export_parser)
    export_parser.add_argument("--machine-id", default=None, help="Source machine id for sync manifests.")
    export_parser.set_defaults(handler=handle_sync_export)

    import_parser = sync_subparsers.add_parser("import", help="Import selected threads from a sync folder.")
    _add_sync_options(import_parser)
    import_parser.add_argument("--conflict-policy", choices=("skip", "remote"), default="skip")
    import_parser.set_defaults(handler=handle_sync_import)

    status_parser = sync_subparsers.add_parser("status", help="Show selected thread sync status.")
    _add_sync_options(status_parser)
    status_parser.add_argument("--json", action="store_true", help="Print machine-readable JSON.")
    status_parser.set_defaults(handler=handle_sync_status)

    return parser


def handle_summary(args: argparse.Namespace) -> int:
    context = _load_context(args)
    rows = aggregate_records(context.records, args.group_by, context.timezone)
    total = summarize_records(context.records)
    generated_at = datetime.now(context.timezone)

    payload = summary_payload(
        rows=rows,
        total=total,
        generated_at=generated_at,
        range_name=args.range_name,
        group_by=args.group_by,
        sessions_dirs=context.session_dirs,
        files_scanned=len(context.files),
        project_keys=context.project_keys,
        project_transitions=_transition_dicts(context.project_transitions),
    )
    if args.json:
        print_json(payload)
    elif args.csv is not None:
        write_csv(rows, args.csv)
    else:
        print(
            render_terminal(
                rows=rows,
                total=total,
                range_name=args.range_name,
                group_by=args.group_by,
                files_scanned=len(context.files),
            )
        )
    return 0


def handle_report(args: argparse.Namespace) -> int:
    context = _load_context(args)
    total = summarize_records(context.records)
    output_path = render_html_report(
        output_path=args.output,
        generated_at=datetime.now(context.timezone),
        range_name=args.range_name,
        total=total,
        daily_rows=aggregate_records(context.records, "day", context.timezone),
        hourly_rows=aggregate_records(context.records, "hour", context.timezone),
        project_rows=aggregate_records(context.records, "project", context.timezone),
        model_rows=aggregate_records(context.records, "model", context.timezone),
        sessions_dirs=context.session_dirs,
        files_scanned=len(context.files),
        project_keys=context.project_keys,
        project_transitions=_transition_dicts(context.project_transitions),
        theme=normalize_report_theme(args.theme or get_settings().theme),
    )
    print(f"Wrote {output_path}")
    return 0


def handle_threads(args: argparse.Namespace) -> int:
    settings = get_settings()
    session_dirs = find_session_dirs()
    project_keys = _normalize_project_keys(args.project_key)
    data = _load_session_data(
        session_dirs,
        auto_transitions=_auto_project_transitions_enabled(args, settings),
    )
    threads = list_threads_from_cached_data(data, project_keys=project_keys)
    payload = {"threads": [thread.to_dict() for thread in threads], "project_keys": project_keys}
    if args.json:
        print_json(payload)
    else:
        for thread in threads:
            print(f"{thread.thread_id}\t{thread.title}\t{thread.project_label}\t{thread.updated_at}")
    return 0


def handle_transitions_suggest(args: argparse.Namespace) -> int:
    session_dirs = _existing_session_dirs()
    data = _load_session_data(session_dirs, auto_transitions=True)
    observations = collect_repo_path_observations(session_dirs, data.files)

    if args.json:
        print_json(
            {
                "sessions_dirs": [str(path) for path in session_dirs],
                "files_scanned": len(data.files),
                "observations_count": len(observations),
                "project_transitions": _transition_dicts(data.project_transitions),
            }
        )
    else:
        for transition in data.project_transitions:
            print(
                f"{transition.source_label} -> {transition.target_label} @ "
                f"{transition.effective_from.isoformat()} {transition.confidence}"
            )
    return 0


def handle_subparser_help(args: argparse.Namespace) -> int:
    args.help_parser.print_help(sys.stderr)
    return 2


def handle_sync_export(args: argparse.Namespace) -> int:
    result = export_threads(
        session_dirs=_existing_session_dirs(),
        sync_dir=args.sync_dir,
        thread_ids=_normalize_thread_ids(args.thread_id),
        machine_id=args.machine_id or _default_machine_id(),
    )
    print_json(result.to_dict())
    return 0


def handle_sync_import(args: argparse.Namespace) -> int:
    result = import_threads(
        session_dirs=_sync_session_dirs(create=True),
        sync_dir=args.sync_dir,
        thread_ids=_normalize_thread_ids(args.thread_id),
        conflict_policy=args.conflict_policy,
    )
    print_json(result.to_dict())
    return 0


def handle_sync_status(args: argparse.Namespace) -> int:
    result = sync_status(
        session_dirs=_existing_session_dirs(),
        sync_dir=args.sync_dir,
        thread_ids=_normalize_thread_ids(args.thread_id),
    )
    if args.json:
        print_json(result.to_dict())
    else:
        for item in result.threads:
            print(f"{item['thread_id']}\t{item['state']}\t{item.get('updated_at', '')}")
    return 0


class _Context:
    def __init__(
        self,
        *,
        session_dirs: list[Path],
        files: list[Path],
        records,
        timezone,
        project_keys: list[str],
        project_transitions: list[ProjectTransition],
    ) -> None:
        self.session_dirs = session_dirs
        self.files = files
        self.records = records
        self.timezone = timezone
        self.project_keys = project_keys
        self.project_transitions = project_transitions


def _load_context(args: argparse.Namespace) -> _Context:
    settings = get_settings()
    timezone = resolve_timezone(args.timezone or settings.timezone)
    session_dirs = find_session_dirs()
    auto_transitions = _auto_project_transitions_enabled(args, settings)
    data = _load_session_data(session_dirs, auto_transitions=auto_transitions)
    project_keys = _normalize_project_keys(args.project_key)
    range_records = filter_records_by_range(data.records, args.range_name, timezone)
    filtered_records = filter_records_by_project_keys(range_records, project_keys)
    filtered_transitions = _filter_project_transitions(data.project_transitions, filtered_records)
    return _Context(
        session_dirs=session_dirs,
        files=data.files,
        records=filtered_records,
        timezone=timezone,
        project_keys=project_keys,
        project_transitions=filtered_transitions,
    )


def _load_session_data(session_dirs: list[Path], *, auto_transitions: bool) -> CachedSessionData:
    try:
        return load_cached_session_data(session_dirs, auto_transitions=auto_transitions)
    except Exception as exc:
        print(f"codex-usage: cache unavailable, falling back to direct parse: {exc}", file=sys.stderr)
        files = collect_jsonl_files(session_dirs)
        records = parse_session_files(files)
        project_transitions: list[ProjectTransition] = []
        if auto_transitions:
            observations = collect_repo_path_observations(session_dirs, files)
            project_transitions = infer_project_transitions(records, observations)
            records = apply_project_transitions(records, project_transitions)
        return uncached_session_data(
            session_dirs=session_dirs,
            files=files,
            records=records,
            project_transitions=project_transitions,
        )


def _add_common_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--timezone", help="IANA timezone name, for example America/Toronto.")
    parser.add_argument(
        "--project-key",
        action="append",
        help="Filter usage to a project key. Repeat to include multiple projects.",
    )
    parser.add_argument(
        "--no-auto-transitions",
        action="store_true",
        help="Disable automatic project transition inference.",
    )


def _add_sync_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--sync-dir", type=Path, required=True, help="Bring-your-own local sync folder.")
    parser.add_argument(
        "--thread-id",
        action="append",
        required=True,
        help="Codex thread id to sync. Repeat to include multiple threads.",
    )

def _normalize_project_keys(values: list[str] | None) -> list[str]:
    selected: list[str] = []
    seen: set[str] = set()
    for value in values or []:
        key = normalize_project_key(value)
        if key and key not in seen:
            selected.append(key)
            seen.add(key)
    return selected


def _normalize_thread_ids(values: list[str] | None) -> list[str]:
    selected: list[str] = []
    seen: set[str] = set()
    for value in values or []:
        thread_id = value.strip()
        if not thread_id or thread_id in seen:
            continue
        selected.append(thread_id)
        seen.add(thread_id)
    return selected


def _auto_project_transitions_enabled(args: argparse.Namespace, settings) -> bool:
    return settings.auto_project_transitions and not getattr(args, "no_auto_transitions", False)


def _transition_dicts(transitions: list[ProjectTransition]) -> list[dict[str, object]]:
    return [transition.to_dict() for transition in transitions]


def _filter_project_transitions(
    transitions: list[ProjectTransition],
    records: list[UsageRecord],
) -> list[ProjectTransition]:
    if not transitions or not records:
        return []

    keys_by_session: dict[str, set[str]] = {}
    for record in records:
        if not record.session_id:
            continue
        keys_by_session.setdefault(record.session_id, set()).update(_record_project_keys(record))

    filtered: list[ProjectTransition] = []
    for transition in transitions:
        transition_sessions = set(transition.thread_ids) or set(keys_by_session)
        matching_sessions = transition_sessions.intersection(keys_by_session)
        if any(_transition_keys_represented(transition, keys_by_session[session_id]) for session_id in matching_sessions):
            filtered.append(transition)
    return filtered


def _transition_keys_represented(transition: ProjectTransition, keys: set[str]) -> bool:
    return transition.source_key in keys and transition.target_key in keys


def _record_project_keys(record: UsageRecord) -> set[str]:
    return {key for key in (record.project_key, record.project_previous_key, *record.project_aliases) if key}


def _existing_session_dirs() -> list[Path]:
    return find_session_dirs()


def _sync_session_dirs(*, create: bool) -> list[Path]:
    try:
        return find_session_dirs()
    except FileNotFoundError:
        if not create:
            raise
    path = default_session_dir().expanduser()
    if create:
        path.mkdir(parents=True, exist_ok=True)
    return [path]


def _default_machine_id() -> str:
    try:
        return socket.gethostname()
    except OSError:
        return "unknown-machine"


if __name__ == "__main__":
    raise SystemExit(main())

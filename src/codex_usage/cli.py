from __future__ import annotations

import argparse
import sys
from contextlib import nullcontext
from datetime import datetime
from pathlib import Path

from codex_usage.aggregation import (
    GROUP_CHOICES,
    RANGE_CHOICES,
    aggregate_valued_records,
    summarize_valued_records,
    value_records,
)
from codex_usage.performance_timing import PhaseTimer, write_timing_sidecar
from codex_usage.project_transitions import ProjectTransition
from codex_usage.report_breakdown import build_report_breakdown_from_valued
from codex_usage.report_theme import REPORT_THEME_CHOICES, normalize_report_theme
from codex_usage.reporting import (
    print_json,
    render_html_report,
    render_terminal,
    summary_payload,
    write_csv,
)
from codex_usage.session_cache import CacheStats
from codex_usage.session_cache_transitions import load_cached_transition_observations
from codex_usage.session_inventory import find_session_dirs
from codex_usage.settings import get_settings
from codex_usage.storage_cli_reporting import (
    render_storage_terminal,
    storage_snapshot_payload,
)
from codex_usage.storage_context import load_storage_context
from codex_usage.storage_insights import build_task_storage_snapshot
from codex_usage.storage_commands import add_storage_subcommands
from codex_usage.sync.local_session_probe import load_local_transfer_probe
from codex_usage.sync_cli import (
    add_sync_common_options,
    add_sync_execution_options,
    add_sync_transfer_options,
)
from codex_usage.sync_cli import (
    handle_sync_inventory as sync_inventory_command,
)
from codex_usage.sync_cli import (
    handle_sync_pull as sync_pull_command,
)
from codex_usage.sync_cli import (
    handle_sync_push as sync_push_command,
)
from codex_usage.sync_cli import (
    handle_sync_status as sync_status_command,
)
from codex_usage.threads import list_threads_from_cached_data
from codex_usage.usage_context import (
    auto_project_transitions_enabled,
    load_session_data,
    load_usage_context,
    normalize_project_keys,
    write_requested_parallel_audit,
)


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not hasattr(args, "handler"):
        parser.print_help(sys.stderr)
        return 2
    timer = PhaseTimer()
    args._phase_timer = timer
    try:
        with timer.measure("total_cli"):
            result = args.handler(args)
    except Exception as exc:  # noqa: BLE001 - CLI handlers must present any failure uniformly.
        print(f"codex-usage: {exc}", file=sys.stderr)
        return 2
    timing_path = getattr(args, "timing_output", None)
    if timing_path is not None:
        try:
            write_timing_sidecar(
                timing_path,
                timer,
                cache_stats=getattr(args, "_timing_cache_stats", CacheStats()),
                command=args.command,
            )
        except Exception as exc:  # noqa: BLE001 - timing is observability only.
            print(f"codex-usage: timing sidecar unavailable: {exc}", file=sys.stderr)
    return result


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

    add_storage_subcommands(
        subparsers,
        add_common_options=_add_common_options,
        snapshot_handler=handle_storage_snapshot,
    )

    sync_parser = subparsers.add_parser(
        "sync", help="Synchronize selected Codex tasks."
    )
    sync_subparsers = sync_parser.add_subparsers(dest="sync_command")

    inventory_parser = sync_subparsers.add_parser(
        "inventory", help="List Codex tasks available for sync."
    )
    add_sync_common_options(inventory_parser)
    inventory_parser.set_defaults(handler=handle_sync_inventory)

    pull_parser = sync_subparsers.add_parser(
        "pull", help="Pull selected Codex tasks from the sync folder."
    )
    add_sync_transfer_options(pull_parser)
    pull_parser.set_defaults(handler=handle_sync_pull)

    push_parser = sync_subparsers.add_parser(
        "push", help="Push selected Codex tasks to the sync folder."
    )
    add_sync_transfer_options(push_parser)
    push_parser.add_argument(
        "--machine-id", default=None, help="Source machine id for sync metadata."
    )
    push_parser.set_defaults(handler=handle_sync_push)

    status_parser = sync_subparsers.add_parser(
        "status", help="Show sync status for selected Codex tasks."
    )
    add_sync_execution_options(status_parser)
    status_parser.set_defaults(handler=handle_sync_status)

    return parser


def handle_summary(args: argparse.Namespace) -> int:
    context = load_usage_context(args)
    timer = getattr(args, "_phase_timer", None)
    with timer.measure("aggregation_render") if timer else nullcontext():
        valued_records = value_records(context.records)
        rows = aggregate_valued_records(
            valued_records,
            args.group_by,
            context.timezone,
        )
        total = summarize_valued_records(valued_records)
        generated_at = datetime.now(context.timezone)

        payload = summary_payload(
            rows=rows,
            total=total,
            generated_at=generated_at,
            range_name=args.range_name,
            group_by=args.group_by,
            sessions_dirs=context.session_dirs,
            files_scanned=len(context.files),
            storage_roots=[str(path) for path in context.session_dirs],
            files_archived=context.storage_stats.files_archived,
            files_retained_missing=context.storage_stats.files_missing_retained,
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
                    files_archived=context.storage_stats.files_archived,
                    files_retained_missing=context.storage_stats.files_missing_retained,
                )
            )
    return 0


def handle_report(args: argparse.Namespace) -> int:
    context = load_usage_context(args)
    timer = getattr(args, "_phase_timer", None)
    with timer.measure("aggregation_render") if timer else nullcontext():
        valued_records = value_records(context.records)
        total = summarize_valued_records(valued_records)
        breakdown = build_report_breakdown_from_valued(valued_records)
        storage_snapshot = _report_storage_snapshot(context.session_data, context.project_keys)
        output_path = render_html_report(
            output_path=args.output,
            generated_at=datetime.now(context.timezone),
            range_name=args.range_name,
            total=total,
            daily_rows=aggregate_valued_records(
                valued_records,
                "day",
                context.timezone,
            ),
            hourly_rows=aggregate_valued_records(
                valued_records,
                "hour",
                context.timezone,
            ),
            breakdown=breakdown,
            sessions_dirs=context.session_dirs,
            files_scanned=len(context.files),
            storage_roots=[str(path) for path in context.session_dirs],
            files_archived=context.storage_stats.files_archived,
            files_retained_missing=context.storage_stats.files_missing_retained,
            project_keys=context.project_keys,
            project_transitions=_transition_dicts(context.project_transitions),
            storage_snapshot=storage_snapshot,
            theme=normalize_report_theme(args.theme or get_settings().theme),
        )
        print(f"Wrote {output_path}")
    return 0


def handle_threads(args: argparse.Namespace) -> int:
    settings = get_settings()
    timer = getattr(args, "_phase_timer", None)
    with timer.measure("inventory") if timer else nullcontext():
        session_dirs = find_session_dirs()
    project_keys = normalize_project_keys(args.project_key)
    data = load_session_data(
        session_dirs,
        auto_transitions=auto_project_transitions_enabled(args, settings),
        timer=timer,
    )
    args._timing_cache_stats = data.stats
    write_requested_parallel_audit(args, data)
    with timer.measure("aggregation_render") if timer else nullcontext():
        threads = list_threads_from_cached_data(data, project_keys=project_keys)
        payload = {
            "threads": [thread.to_dict() for thread in threads],
            "project_keys": project_keys,
        }
        if args.json:
            print_json(payload)
        else:
            for thread in threads:
                print(
                    f"{thread.thread_id}\t{thread.title}\t{thread.project_label}\t{thread.updated_at}"
                )
    return 0


def handle_transitions_suggest(args: argparse.Namespace) -> int:
    session_dirs = _existing_session_dirs()
    data = load_session_data(session_dirs, auto_transitions=True)
    observations = load_cached_transition_observations(session_dirs)

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


def handle_storage_snapshot(args: argparse.Namespace) -> int:
    timer = getattr(args, "_phase_timer", None)
    with timer.measure("inventory") if timer else nullcontext():
        session_dirs = find_session_dirs()
    project_keys = normalize_project_keys(args.project_key)
    with timer.measure("storage_refresh") if timer else nullcontext():
        context = load_storage_context(session_dirs=session_dirs)
    with timer.measure("aggregation_render") if timer else nullcontext():
        snapshot = context.insights.filter_projects(project_keys)
        payload = storage_snapshot_payload(snapshot)
    if args.json:
        print_json(payload)
    else:
        print(render_storage_terminal(payload))
    return 0


def _report_storage_snapshot(data, project_keys: list[str] | None) -> object | None:
    if data is None:
        return None
    return build_task_storage_snapshot(data, project_keys=project_keys)


def handle_sync_pull(args: argparse.Namespace) -> int:
    return sync_pull_command(args, load_local_transfer_probe)


def handle_sync_push(args: argparse.Namespace) -> int:
    return sync_push_command(args, load_local_transfer_probe)


def handle_sync_inventory(args: argparse.Namespace) -> int:
    return sync_inventory_command(args, load_local_transfer_probe)


def handle_sync_status(args: argparse.Namespace) -> int:
    return sync_status_command(args, load_local_transfer_probe)


def _add_common_options(
    parser: argparse.ArgumentParser,
    *,
    project_help: str = "Filter usage to a project key. Repeat to include multiple projects.",
) -> None:
    parser.add_argument(
        "--parallel-audit",
        type=Path,
        help=argparse.SUPPRESS,
    )
    parser.add_argument(
        "--timing-output",
        type=Path,
        help=argparse.SUPPRESS,
    )
    parser.add_argument(
        "--timezone", help="IANA timezone name, for example America/Toronto."
    )
    parser.add_argument(
        "--project-key",
        action="append",
        help=project_help,
    )
    parser.add_argument(
        "--no-auto-transitions",
        action="store_true",
        help="Disable automatic project transition inference.",
    )


def _transition_dicts(transitions: list[ProjectTransition]) -> list[dict[str, object]]:
    return [transition.to_dict() for transition in transitions]


def _existing_session_dirs() -> list[Path]:
    return find_session_dirs()


if __name__ == "__main__":
    raise SystemExit(main())

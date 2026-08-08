from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

from codex_usage.reporting import print_json
from codex_usage.session_cache import resolve_cache_dir
from codex_usage.session_inventory import find_session_dirs
from codex_usage.storage_analysis import analyze_storage_tree
from codex_usage.storage_cli_reporting import storage_snapshot_payload
from codex_usage.storage_context import load_storage_context
from codex_usage.task_backup import (
    create_task_backup,
    select_backup_tree,
    verify_task_backup,
)
from codex_usage.task_backup.progress import emit_json_progress, ignore_progress
from codex_usage.task_rollover import prepare_task_rollover


type CommandHandler = Callable[[argparse.Namespace], int]
type CommonOptionsAdder = Callable[..., None]


def add_storage_subcommands(
    subparsers: Any,
    *,
    add_common_options: CommonOptionsAdder,
    snapshot_handler: CommandHandler,
) -> None:
    storage_parser = subparsers.add_parser(
        "storage", help="Inspect local Codex storage state."
    )
    storage_subparsers = storage_parser.add_subparsers(dest="storage_command")
    storage_parser.set_defaults(
        handler=_handle_subparser_help, help_parser=storage_parser
    )

    snapshot_parser = storage_subparsers.add_parser(
        "snapshot", help="Print a local Codex storage snapshot."
    )
    add_common_options(
        snapshot_parser,
        project_help=(
            "Filter task storage to a canonical project key. "
            "Repeat to include multiple projects."
        ),
    )
    snapshot_parser.add_argument(
        "--json", action="store_true", help="Print machine-readable JSON."
    )
    snapshot_parser.set_defaults(handler=snapshot_handler)

    analyze_parser = storage_subparsers.add_parser(
        "analyze", help="Analyze compacted-history amplification for one task tree."
    )
    analyze_parser.add_argument(
        "--tree-id", required=True, help="Root task-tree id from storage snapshot."
    )
    analyze_parser.add_argument(
        "--json", action="store_true", help="Print machine-readable JSON."
    )
    analyze_parser.add_argument(
        "--progress-json",
        action="store_true",
        help="Write line-delimited progress events to stderr.",
    )
    analyze_parser.set_defaults(handler=handle_storage_analyze)

    backup_parser = storage_subparsers.add_parser(
        "backup", help="Create and verify one Codex task-tree backup."
    )
    backup_parser.add_argument(
        "--tree-id", required=True, help="Root task-tree id from storage snapshot."
    )
    backup_parser.add_argument(
        "--output",
        required=True,
        type=Path,
        help="Destination .codex-task-backup file.",
    )
    backup_parser.add_argument(
        "--compression",
        choices=("maximum", "balanced"),
        default="maximum",
        help="Compression preset; maximum is smaller and slower.",
    )
    backup_parser.add_argument(
        "--replace",
        action="store_true",
        help="Atomically replace an existing verified backup.",
    )
    _add_output_options(backup_parser)
    backup_parser.set_defaults(handler=handle_storage_backup)

    rollover_parser = storage_subparsers.add_parser(
        "rollover", help="Create a verified backup and prepare a fresh-root handoff."
    )
    rollover_parser.add_argument(
        "--tree-id", required=True, help="Root task-tree id from storage snapshot."
    )
    rollover_parser.add_argument(
        "--output",
        required=True,
        type=Path,
        help="New destination .codex-task-backup file.",
    )
    rollover_parser.add_argument(
        "--compression",
        choices=("maximum", "balanced"),
        default="maximum",
        help="Compression preset; maximum is recommended for rollover archives.",
    )
    _add_output_options(rollover_parser)
    rollover_parser.set_defaults(handler=handle_storage_rollover)

    verify_parser = storage_subparsers.add_parser(
        "verify", help="Verify a Codex task backup without extracting it."
    )
    verify_parser.add_argument("archive", type=Path)
    _add_output_options(verify_parser)
    verify_parser.set_defaults(handler=handle_storage_verify)


def handle_storage_analyze(args: argparse.Namespace) -> int:
    session_dirs = find_session_dirs()
    callback = _emit_analysis_progress if args.progress_json else None
    summary = analyze_storage_tree(
        args.tree_id,
        session_dirs=session_dirs,
        progress=callback,
    )
    refreshed = load_storage_context(session_dirs=session_dirs)
    tree_payload = next(
        (
            item
            for item in storage_snapshot_payload(refreshed.insights)["task_trees"]
            if item["root_task_id"] == args.tree_id
        ),
        None,
    )
    payload = {
        "schema_version": 1,
        "analysis": summary.to_dict(),
        "task_tree": tree_payload,
    }
    if args.json:
        print_json(payload)
    else:
        print(
            f"Analyzed {summary.files_analyzed:,} of {summary.files_total:,} files | "
            f"read {summary.source_bytes_read:,} bytes | tree {summary.tree_id}"
        )
    return 0


def handle_storage_backup(args: argparse.Namespace) -> int:
    session_dirs = find_session_dirs()
    context = load_storage_context(session_dirs=session_dirs)
    selection = select_backup_tree(context, args.tree_id)
    callback = emit_json_progress if args.progress_json else ignore_progress
    result = create_task_backup(
        selection,
        args.output,
        refresh_selection=lambda: select_backup_tree(
            load_storage_context(session_dirs=session_dirs), args.tree_id
        ),
        compression=args.compression,
        replace_existing=args.replace,
        progress=callback,
        lock_path=resolve_cache_dir(session_dirs) / "task-backup.lock",
    )
    payload = result.to_dict()
    if args.json:
        print_json(payload)
    else:
        print(_render_backup_result(payload, action="Created"))
    return 0


def handle_storage_rollover(args: argparse.Namespace) -> int:
    session_dirs = find_session_dirs()
    callback = emit_json_progress if args.progress_json else ignore_progress
    result = prepare_task_rollover(
        args.tree_id,
        args.output,
        session_dirs=session_dirs,
        compression=args.compression,
        progress=callback,
    )
    payload = result.to_dict()
    if args.json:
        print_json(payload)
    else:
        print(_render_backup_result(payload["backup"], action="Created rollover backup"))
        print("\nStarter prompt copied by the VS Code command:\n")
        print(payload["starter_prompt"])
        print("Checklist:")
        for index, item in enumerate(payload["checklist"], start=1):
            print(f"{index}. {item}")
    return 0


def handle_storage_verify(args: argparse.Namespace) -> int:
    callback = emit_json_progress if args.progress_json else ignore_progress
    result = verify_task_backup(args.archive, progress=callback)
    payload = result.to_dict()
    if args.json:
        print_json(payload)
    else:
        print(_render_backup_result(payload, action="Verified"))
    return 0


def _handle_subparser_help(args: argparse.Namespace) -> int:
    args.help_parser.print_help(sys.stderr)
    return 2


def _emit_analysis_progress(payload: dict[str, object]) -> None:
    print(json.dumps(payload, sort_keys=True), file=sys.stderr, flush=True)


def _add_output_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON.")
    parser.add_argument(
        "--progress-json",
        action="store_true",
        help="Write line-delimited progress events to stderr.",
    )


def _render_backup_result(payload: dict[str, object], *, action: str) -> str:
    readiness = "recovery-ready" if payload["recovery_ready"] else "salvage only"
    return (
        f"{action} {payload['archive_path']} | {payload['file_count']} files | "
        f"{payload['archive_bytes']} compressed bytes | {readiness} | "
        f"SHA-256 {payload['archive_sha256']}"
    )

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable
from typing import Any

from codex_usage.reporting import print_json
from codex_usage.session_inventory import find_session_dirs
from codex_usage.storage_analysis import analyze_storage_tree
from codex_usage.storage_cli_reporting import storage_snapshot_payload
from codex_usage.storage_context import load_storage_context


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
    _add_output_options(analyze_parser)
    analyze_parser.set_defaults(handler=handle_storage_analyze)


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

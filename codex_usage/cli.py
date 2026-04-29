from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

from codex_usage.aggregation import (
    GROUP_CHOICES,
    RANGE_CHOICES,
    aggregate_records,
    filter_records_by_range,
    resolve_timezone,
    summarize_records,
)
from codex_usage.discovery import collect_jsonl_files, find_session_dirs
from codex_usage.parser import parse_session_files
from codex_usage.reporting import (
    print_json,
    render_html_report,
    render_terminal,
    summary_payload,
    write_csv,
)
from codex_usage.settings import get_settings


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
    report_parser.add_argument("--output", type=Path, default=Path("output/report.html"))
    report_parser.set_defaults(handler=handle_report)

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
        subscription_usd=context.subscription_usd,
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
                subscription_usd=context.subscription_usd,
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
        subscription_usd=context.subscription_usd,
    )
    print(f"Wrote {output_path}")
    return 0


class _Context:
    def __init__(
        self,
        *,
        session_dirs: list[Path],
        files: list[Path],
        records,
        timezone,
        subscription_usd: float | None,
    ) -> None:
        self.session_dirs = session_dirs
        self.files = files
        self.records = records
        self.timezone = timezone
        self.subscription_usd = subscription_usd


def _load_context(args: argparse.Namespace) -> _Context:
    settings = get_settings()
    timezone = resolve_timezone(args.timezone or settings.timezone)
    session_dirs = find_session_dirs(args.sessions_dir, settings)
    files = collect_jsonl_files(session_dirs)
    records = parse_session_files(files)
    filtered_records = filter_records_by_range(records, args.range_name, timezone)
    subscription_usd = args.subscription_usd if args.subscription_usd is not None else settings.subscription_usd
    return _Context(
        session_dirs=session_dirs,
        files=files,
        records=filtered_records,
        timezone=timezone,
        subscription_usd=subscription_usd,
    )


def _add_common_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--sessions-dir", type=Path, help="Path to the Codex sessions directory.")
    parser.add_argument("--timezone", help="IANA timezone name, for example America/Toronto.")
    parser.add_argument("--subscription-usd", type=float, help="Monthly subscription cost for comparison.")


if __name__ == "__main__":
    raise SystemExit(main())

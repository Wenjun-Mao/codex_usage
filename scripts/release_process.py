"""On-demand release preparation and explicit exact-run promotion; no daemon."""
import argparse
import json
import os
from pathlib import Path

from release.policy import ROOT, positive, require
from release.process_candidate import candidate
from release.process_coordinator import Coordinator
from release.process_preflight import preflight
from release.process_runs import request_id
from release.process_state import Pending, Progress


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="mode", required=True)
    check = sub.add_parser("validate-request", help="Validate optional workflow correlation only")
    check.add_argument("value")
    for mode in ("preflight", "prepare", "dry-run", "promote", "resume"):
        p = sub.add_parser(mode)
        p.add_argument("--output", type=Path, required=True)
        p.add_argument("--base", required=mode in ("preflight", "prepare"),
            help="Explicit verified release base for local suite selection")
        p.add_argument("--wait-seconds", type=int, default=1800)
        if mode in ("preflight", "prepare"):
            p.add_argument("--reuse", type=Path)
        if mode in ("dry-run", "promote"):
            p.add_argument("--run", type=positive, required=True)
            p.add_argument("--attempt", type=positive, required=True)
    args = parser.parse_args()
    if args.mode == "validate-request":
        request_id(args.value, optional=True)
        return
    require(not os.environ.get("VSCE_PAT"), "Local release tools must not receive publisher credentials")
    require(0 < args.wait_seconds <= 3600, "Finite wait must be between 1 and 3600 seconds")
    require(args.output.resolve().is_relative_to((ROOT / "output").resolve()), "Output must stay under output/")
    args.output.mkdir(parents=True, exist_ok=True)
    if args.mode == "preflight":
        print(json.dumps(preflight(args.base, args.output, reuse=args.reuse), sort_keys=True))
        return
    context = candidate(allow_receipt_edits=args.mode == "resume")
    progress = Progress(args.output, context)
    with progress.locked():
        flow = Coordinator(progress, seconds=args.wait_seconds)
        try:
            if args.mode == "prepare":
                flow.prepare(args.base, reuse=args.reuse)
            elif args.mode == "dry-run":
                flow.dry_run(args.run, args.attempt, allow=True)
            elif args.mode == "promote":
                flow.promote(args.run, args.attempt)
            else:
                flow.resume(args.base)
        finally:
            flow.summary()


if __name__ == "__main__":
    try:
        main()
    except Pending as error:
        print(json.dumps({"status": "pending-reconciliation", "reason": str(error)}), flush=True)
        raise SystemExit(2) from None

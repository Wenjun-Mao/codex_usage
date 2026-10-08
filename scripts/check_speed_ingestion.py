"""Bounded, read-only recovery of an existing frozen sample's original bytes.

Read at most the original up-to-eight-sources/three-model, four-MiB tails. Hash
verification binds bytes to the prior private snapshot, not current live data.
Raw copies exist only in a disposable directory. Never publish private output.
"""
import argparse
from collections import Counter, defaultdict
from contextlib import closing
from dataclasses import replace
from datetime import datetime
import hashlib
import json
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
from unittest.mock import patch
from zoneinfo import ZoneInfo

from codex_usage.parser import parse_session_generation, parse_session_append
from codex_usage.session_chunk_reader import CandidateRow
from codex_usage.session_parser_models import parser_state_to_json, parser_state_from_json
from codex_usage.speed_models import TOKEN_FIELDS
from codex_usage.speed_recovery import SLICE_BYTES

SOURCE_SQL = """
with candidates as (
 select m.model_key,s.path,count(*) n,max(e.timestamp_us) latest
 from ledger_usage_events e join ledger_generations g using(generation_id)
 join ledger_sources s using(source_id) join ledger_models m using(model_id)
 where g.status='trusted' and e.timestamp_us>=? and e.timestamp_us<=?
 and m.model_key in (?,?,?) group by m.model_key,s.source_id having count(*)>20
), ranked as (
 select *,row_number() over(partition by model_key order by latest desc) rank from candidates
)
select distinct path from ranked where rank<=8 order by path limit 24
"""


def time_us(value):
    return int(datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp() * 1000000)


def whole_row(handle, stop_offset, **kwargs):
    raw = handle.readline(stop_offset - handle.tell())
    return CandidateRow(raw, raw.endswith(b"\n"), len(raw), "relevant")


def settled(facts, tools, uncertain):
    result = []
    for fact in facts:
        reason = fact.reason
        if not reason and fact.turn_id in uncertain:
            reason = "missing_tool_interval"
        if not reason and any((a < fact.end_ms and b > fact.start_ms) or
                              (a == b and fact.start_ms < a < fact.end_ms) for a, b in tools):
            reason = "tool_execution_overlap"
        result.append(replace(fact, reason=reason))
    return result


def parse_paths(path):
    with patch("codex_usage.session_parser_incremental.read_candidate_row", whole_row):
        whole = parse_session_generation(path)
    full = parse_session_generation(path)
    first = parse_session_generation(path, stop_offset=path.stat().st_size // 2)
    last = parse_session_append(path, first.checkpoint, stop_offset=path.stat().st_size)
    results = {
        "whole_object": (whole.records, whole.speed_facts, whole.speed_tools, whole.speed_uncertain_tools),
        "full": (full.records, full.speed_facts, full.speed_tools, full.speed_uncertain_tools),
        "append": (first.records + last.records, first.speed_facts + last.speed_facts,
                   first.speed_tools + last.speed_tools, first.speed_uncertain_tools + last.speed_uncertain_tools),
    }
    chunk = parse_session_generation(path, max_bytes=SLICE_BYTES, strict_byte_budget=True)
    records, facts, tools, uncertain = [], [], [], []
    maximum_state = 0
    for _ in range(100):
        records.extend(chunk.records)
        facts.extend(chunk.speed_facts)
        tools.extend(chunk.speed_tools)
        uncertain.extend(chunk.speed_uncertain_tools)
        state = parser_state_to_json(chunk.checkpoint.state)
        maximum_state = max(maximum_state, len(state))
        if chunk.checkpoint.byte_offset >= path.stat().st_size:
            break
        checkpoint = replace(chunk.checkpoint, state=parser_state_from_json(state, path))
        next_chunk = parse_session_append(path, checkpoint, stop_offset=path.stat().st_size,
                                         max_bytes=SLICE_BYTES, strict_byte_budget=True)
        if next_chunk.checkpoint.byte_offset <= chunk.checkpoint.byte_offset:
            raise ValueError("unsupported incomplete tail or no checkpoint progress")
        chunk = next_chunk
    else:
        raise ValueError("bounded sample did not finish in 100 slices")
    results["recovery"] = (tuple(records), tuple(facts), tuple(tools), tuple(uncertain))
    baseline = [r.to_dict() for r in whole.records]
    for records, _, _, _ in results.values():
        assert [r.to_dict() for r in records] == baseline, "monetary ingestion changed"
    return {key: settled(facts, tools, uncertain) for key, (_, facts, tools, uncertain) in results.items()}, maximum_state


def trusted(fact, source):
    return any(event["timestamp"] == fact.timestamp and event["turn_id"] == fact.turn_id
               and event["model_key"] == fact.model and
               tuple(event[key] for key in TOKEN_FIELDS) == fact.usage for event in source["events"])


def summarize(facts):
    # Equivalent copies count once and conflicting identities count zero.
    grouped = defaultdict(list)
    for fact in facts:
        grouped[fact.response_id].append(fact)
    accepted = []
    rejected = Counter()
    for identity, group in grouped.items():
        signatures = {json.dumps({k: v for k, v in f.to_dict().items()
                                 if k not in {"task_id", "record_index", "cli_version", "effort"}}, sort_keys=True) for f in group}
        if not identity or len(signatures) != 1:
            rejected["conflicting_or_missing_identity"] += len(group)
        elif group[0].reason:
            rejected[group[0].reason] += len(group)
        else:
            accepted.append(group[0])
    sensitivity = {}
    for floor in (10, 50, 100):
        for output in (100, 500, 2000):
            models, days, hours = Counter(), Counter(), Counter()
            for fact in accepted:
                if fact.min_item_ms < floor or fact.usage[3] < output:
                    continue
                local = datetime.fromisoformat(fact.timestamp).astimezone(ZoneInfo("America/Toronto"))
                models[fact.model] += 1
                days[(fact.model, local.date().isoformat())] += 1
                hours[(fact.model, local.replace(minute=0, second=0, microsecond=0).isoformat())] += 1
            sensitivity[f"{floor}ms/{output}tokens"] = {
                "eligible": sum(models.values()), "models_with_summary": sum(n >= 5 for n in models.values()),
                "model_daily_points": sum(n >= 5 for n in days.values()),
                "model_hourly_points": sum(n >= 5 for n in hours.values()),
            }
    return {"accepted": len(accepted), "rejections": dict(rejected), "sensitivity": sensitivity}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--private-snapshot", type=Path, required=True)
    parser.add_argument("--private-ledger", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    assert args.output.resolve().is_relative_to(Path("output/research/model-speed").resolve())
    raw = args.private_snapshot.read_bytes()
    snapshot = json.loads(raw)
    scope = snapshot["scope"]
    assert len(scope["models"]) == 3 and scope["files_per_model"] == 8 and scope["tail_mib"] == 4
    frozen = {s["source"]["source_id"]: s for s in snapshot["sources"]}
    with closing(sqlite3.connect(f"{args.private_ledger.resolve().as_uri()}?mode=ro", uri=True)) as connection:
        connection.execute("pragma query_only=on")
        paths = [Path(row[0]) for row in connection.execute(SOURCE_SQL, (
            time_us(scope["since"]), time_us(snapshot["recorded_at"]), *scope["models"],
        ))]
    totals = defaultdict(list)
    evidence = {"evidence_kind": "hash_bound_original_bytes_actual_ingestion", "input_sha256": hashlib.sha256(raw).hexdigest(),
                "selected_frozen_sources": len(frozen), "matched_sources": 0, "read_bytes": 0,
                "skip_reasons": {}, "maximum_checkpoint_chars": 0, "monetary_paths_equal": True}
    evidence["recovery_slice_bytes"] = SLICE_BYTES
    skipped = Counter()
    with TemporaryDirectory(prefix="speed-ingestion-") as temporary:
        for path in paths:
            identity = hashlib.sha256(str(path).encode()).hexdigest()[:12]
            source = frozen.get(identity)
            if source is None:
                continue
            size = source["source"]["captured_size_bytes"]
            offset = max(0, size - 4 * 1024 * 1024)
            try:
                before = path.stat()
                assert before.st_size >= size
                with path.open("rb") as handle:
                    handle.seek(offset)
                    data = handle.read(size - offset)
                after = path.stat()
                assert (before.st_dev, before.st_ino) == (after.st_dev, after.st_ino) and after.st_size >= size
                if offset:
                    boundary = data.find(b"\n")
                    data = data[boundary + 1:] if boundary >= 0 else b""
                assert hashlib.sha256(data).hexdigest() == source["source"]["sample_sha256"]
            except (OSError, AssertionError):
                skipped["missing_changed_or_hash_mismatch"] += 1
                continue
            evidence["read_bytes"] += size - offset
            disposable = Path(temporary) / "sample.jsonl"
            disposable.write_bytes(data)
            try:
                results, maximum = parse_paths(disposable)
            except (OSError, ValueError):
                skipped["unsupported_bounded_ingestion_format"] += 1
                continue
            evidence["matched_sources"] += 1
            evidence["maximum_checkpoint_chars"] = max(maximum, evidence["maximum_checkpoint_chars"])
            for key, facts in results.items():
                totals[key].extend(replace(f, reason=f.reason or ("" if trusted(f, source) else "trusted_event_mismatch")) for f in facts)
    skipped["not_reidentified_in_bounded_inventory"] = len(frozen) - evidence["matched_sources"] - sum(skipped.values())
    evidence["skip_reasons"] = dict(skipped)
    evidence["paths"] = {key: summarize(facts) for key, facts in totals.items()}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(evidence, indent=2) + "\n")
    print(json.dumps({"matched_sources": evidence["matched_sources"], "output": str(args.output),
                      "paths_accepted": {k: v["accepted"] for k, v in evidence["paths"].items()}}))


if __name__ == "__main__":
    main()
